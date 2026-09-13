from langchain_core.messages import HumanMessage
from langgraph.prebuilt import ToolNode

from data_tools import TOOLS, openai_tool_schemas
from local_model import call_local_model


SYSTEM = """
You are Chat With My Data, a grounded data analyst.

Answer only from selected SQLite tables using tool evidence.
Inspect schema when needed, generate read-only SQL, use statistical tools
when useful, and never invent numbers.

Clearly separate observed facts from interpretation.
"""


def chat_with_data(question, tables, endpoint, model, history=None, api_key=None):
    messages = [
        HumanMessage(content=SYSTEM),
        HumanMessage(content=f"SELECTED TABLES: {tables}")
    ]
    if history:
        messages.extend(history)
    messages.append(HumanMessage(content=question))

    tools = openai_tool_schemas()
    tool_node = ToolNode(TOOLS)

    for _ in range(8):
        ai = call_local_model(
            messages, tools=tools, endpoint=endpoint,
            model=model, temperature=0.1, api_key=api_key,
        )
        messages.append(ai)
        if not ai.tool_calls:
            return ai.content or "No answer returned.", messages

        result = tool_node.invoke({"messages": [ai]})
        messages.extend(result["messages"])

    return "Analysis limit reached before a final answer.", messages
