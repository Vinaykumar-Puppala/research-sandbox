import json

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from data_tools import TOOLS, openai_tool_schemas
from local_model import call_local_model, strip_tool_markup
from skill_loader import load_skill_prompts, load_skill_tools


SYSTEM = """
You are Chat With My Data, a grounded data analyst.

Answer only from selected SQLite tables using tool evidence.
Inspect schema when needed, generate read-only SQL, use statistical tools
when useful, and never invent numbers.

Clearly separate observed facts from interpretation.
"""


def _run_tool_calls(ai, tools_by_name):
    """Execute the model's tool calls directly.

    Deliberately not langgraph's ToolNode: its standalone .invoke() requires a
    graph config in langgraph 1.x. A failing tool returns its error to the model
    as a ToolMessage so the conversation can recover instead of crashing.
    """
    results = []
    for call in ai.tool_calls:
        tool = tools_by_name.get(call["name"])
        if tool is None:
            content = json.dumps({"error": f"Unknown tool: {call['name']}"})
        else:
            try:
                content = str(tool.invoke(call.get("args", {})))
            except Exception as exc:
                content = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        results.append(ToolMessage(
            content=content, tool_call_id=call["id"], name=call["name"],
        ))
    return results


def _skill_schemas(tools):
    return [{
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description,
            "parameters": t.args_schema.model_json_schema(),
        }
    } for t in tools]


def chat_with_data(question, tables, endpoint, model, history=None, api_key=None):
    skill_tools = load_skill_tools()
    skill_context = load_skill_prompts()

    system_text = SYSTEM + ("\n\n" + skill_context if skill_context else "")
    all_tools_lc = TOOLS + skill_tools
    all_tools_oai = openai_tool_schemas() + _skill_schemas(skill_tools)

    messages = [
        SystemMessage(content=system_text),
        HumanMessage(content=f"SELECTED TABLES: {tables}")
    ]
    if history:
        messages.extend(history)
    messages.append(HumanMessage(content=question))

    tools_by_name = {t.name: t for t in all_tools_lc}

    for _ in range(8):
        ai = call_local_model(
            messages, tools=all_tools_oai, endpoint=endpoint,
            model=model, temperature=0.1, api_key=api_key,
        )
        messages.append(ai)
        if not ai.tool_calls:
            # A model may emit an unparseable tool call; never show raw markup.
            answer = strip_tool_markup(ai.content)
            if not answer:
                answer = ("The model returned a tool call this app could not parse. Check "
                          "the raw response (sidebar toggle) and confirm the server's chat "
                          "template supports function calling.")
            return answer, messages

        messages.extend(_run_tool_calls(ai, tools_by_name))

    return "Analysis limit reached before a final answer.", messages
