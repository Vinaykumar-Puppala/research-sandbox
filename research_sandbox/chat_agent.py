from langchain_core.messages import HumanMessage
from langgraph.prebuilt import ToolNode

from data_tools import TOOLS, openai_tool_schemas
from local_model import call_local_model
from skill_loader import load_skill_prompts, load_skill_tools


SYSTEM = """
You are Chat With My Data, a grounded data analyst.

Answer only from selected SQLite tables using tool evidence.
Inspect schema when needed, generate read-only SQL, use statistical tools
when useful, and never invent numbers.

Clearly separate observed facts from interpretation.
"""


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
        HumanMessage(content=system_text),
        HumanMessage(content=f"SELECTED TABLES: {tables}")
    ]
    if history:
        messages.extend(history)
    messages.append(HumanMessage(content=question))

    tool_node = ToolNode(all_tools_lc)

    for _ in range(8):
        ai = call_local_model(
            messages, tools=all_tools_oai, endpoint=endpoint,
            model=model, temperature=0.1, api_key=api_key,
        )
        messages.append(ai)
        if not ai.tool_calls:
            return ai.content or "No answer returned.", messages

        result = tool_node.invoke({"messages": [ai]})
        messages.extend(result["messages"])

    return "Analysis limit reached before a final answer.", messages
