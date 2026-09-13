import json
from typing import Any, Dict, List, Optional

import requests
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

# Chars kept per tool result / AI reasoning text to stay within small context windows.
# Gemma 4B/27B quant typically has 8K–32K tokens; each tool result can be thousands
# of chars, so we cap early rather than let the server reject with a context error.
_MAX_TOOL_CHARS = 800
_MAX_AI_CHARS = 400


def _trim_message(m: BaseMessage) -> BaseMessage:
    if isinstance(m, ToolMessage):
        text = str(m.content)
        if len(text) > _MAX_TOOL_CHARS:
            return ToolMessage(
                content=text[:_MAX_TOOL_CHARS] + "…[truncated]",
                tool_call_id=m.tool_call_id,
                name=m.name,
            )
    elif isinstance(m, AIMessage) and m.content and len(m.content) > _MAX_AI_CHARS:
        return AIMessage(
            content=m.content[:_MAX_AI_CHARS] + "…",
            tool_calls=list(m.tool_calls),
        )
    return m


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
                     model="local-model", temperature=0.2, timeout=120,
                     api_key: Optional[str] = None):
    headers: Dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    trimmed = [_trim_message(m) for m in messages]

    payload = {
        "model": model,
        "messages": [message_to_openai(m) for m in trimmed],
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    response = requests.post(endpoint, json=payload, timeout=timeout, headers=headers)
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
