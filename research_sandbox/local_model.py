import json
from typing import Any, Dict, List, Optional

import requests
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage


def message_to_openai(m: BaseMessage) -> Dict[str, Any]:
    if isinstance(m, HumanMessage):
        return {"role": "user", "content": str(m.content)}
    if isinstance(m, ToolMessage):
        return {
            "role": "tool",
            "tool_call_id": m.tool_call_id,
            "content": str(m.content),
        }
    if isinstance(m, AIMessage):
        item = {"role": "assistant", "content": m.content or ""}
        if getattr(m, "tool_calls", None):
            item["tool_calls"] = [{
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": json.dumps(tc.get("args", {}), default=str),
                },
            } for tc in m.tool_calls]
        return item
    return {"role": "user", "content": str(m.content)}


def call_local_model(messages: List[BaseMessage],
                     tools: Optional[List[Dict[str, Any]]] = None,
                     endpoint="http://localhost:8000/v1/chat/completions",
                     model="local-model", temperature=0.2, timeout=120):
    payload = {
        "model": model,
        "messages": [message_to_openai(m) for m in messages],
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    response = requests.post(endpoint, json=payload, timeout=timeout)
    response.raise_for_status()
    choice = response.json()["choices"][0]["message"]

    tool_calls = []
    for tc in choice.get("tool_calls", []) or []:
        fn = tc.get("function", {})
        raw = fn.get("arguments", "{}")
        try:
            args = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            args = {}
        tool_calls.append({
            "name": fn.get("name"),
            "args": args,
            "id": tc.get("id"),
            "type": "tool_call",
        })

    return AIMessage(content=choice.get("content", "") or "",
                     tool_calls=tool_calls)
