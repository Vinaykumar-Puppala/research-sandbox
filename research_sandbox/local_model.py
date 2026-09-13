import ast
import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

# Chars kept per tool result / AI reasoning text to stay within small context windows.
# Gemma 4B/27B quant typically has 8K-32K tokens; each tool result can be thousands
# of chars, so we cap early rather than let the server reject with a context error.
_MAX_TOOL_CHARS = 800
_MAX_AI_CHARS = 400

# Many local servers (llama.cpp with Gemma/Qwen/Hermes templates, some LiteLLM
# passthroughs) never populate the structured `tool_calls` field - they emit the
# call as text inside `content`. Without these fallbacks the raw markup is shown
# to the user and no tool ever runs.
_JSON_CALL_PATTERNS = [
    re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL),
    re.compile(r"<function_call>\s*(.*?)\s*</function_call>", re.DOTALL),
    re.compile(r"```(?:json|tool_call|tool_calls)\s*(.*?)\s*```", re.DOTALL),
    re.compile(r"\[TOOL_CALLS\]\s*(\[.*\]|\{.*\})", re.DOTALL),
    # Some templates truncate the closing tag.
    re.compile(r"<tool_call>\s*(\{.*\})", re.DOTALL),
]

# Gemma's native style: a fenced block holding a Python call expression.
_PY_CALL_PATTERN = re.compile(r"```(?:tool_code|python)\s*(.*?)\s*```", re.DOTALL)

_RESIDUAL_TAGS = re.compile(r"</?(?:tool_call|function_call|tool_response)>")


def _new_call_id() -> str:
    return f"call_{uuid.uuid4().hex[:8]}"


def _normalize_call(obj: Any) -> Optional[Dict[str, Any]]:
    """Coerce one decoded tool-call object into LangChain's tool_call shape."""
    if not isinstance(obj, dict):
        return None

    name = obj.get("name") or obj.get("tool") or obj.get("function")
    if isinstance(name, dict):
        obj = {**obj, **name}
        name = name.get("name")
    if not isinstance(name, str) or not name:
        return None

    args = obj.get("arguments")
    if args is None:
        args = obj.get("parameters")
    if args is None:
        args = obj.get("args")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    if not isinstance(args, dict):
        args = {}

    return {"name": name, "args": args, "id": _new_call_id(), "type": "tool_call"}


def _parse_python_call(expr: str) -> Optional[Dict[str, Any]]:
    """Parse `func(a="b")` into a tool call. Parses only - never evaluates."""
    expr = expr.strip()
    if expr.startswith("print(") and expr.endswith(")"):
        expr = expr[len("print("):-1].strip()
    try:
        node = ast.parse(expr, mode="eval").body
    except (SyntaxError, ValueError):
        return None
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        return None

    args: Dict[str, Any] = {}
    for kw in node.keywords:
        if kw.arg is None:
            continue
        try:
            args[kw.arg] = ast.literal_eval(kw.value)
        except (ValueError, SyntaxError):
            return None

    return {"name": node.func.id, "args": args,
            "id": _new_call_id(), "type": "tool_call"}


def extract_text_tool_calls(content: str) -> Tuple[List[Dict[str, Any]], str]:
    """Recover tool calls a model emitted as text, plus the content without them."""
    if not content or not content.strip():
        return [], content or ""

    calls: List[Dict[str, Any]] = []
    cleaned = content

    for pattern in _JSON_CALL_PATTERNS:
        for match in pattern.finditer(content):
            try:
                parsed = json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                continue
            items = parsed if isinstance(parsed, list) else [parsed]
            found = [c for c in (_normalize_call(i) for i in items) if c]
            if found:
                calls.extend(found)
                cleaned = cleaned.replace(match.group(0), "")
        if calls:
            break

    if not calls:
        for match in _PY_CALL_PATTERN.finditer(content):
            block = [c for c in (_parse_python_call(line)
                                 for line in match.group(1).strip().splitlines()) if c]
            if block:
                calls.extend(block)
                cleaned = cleaned.replace(match.group(0), "")

    if not calls:
        stripped = content.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                call = _normalize_call(json.loads(stripped))
            except json.JSONDecodeError:
                call = None
            if call:
                calls.append(call)
                cleaned = ""

    return calls, _RESIDUAL_TAGS.sub("", cleaned).strip()


def strip_tool_markup(text: str) -> str:
    """Remove residual tool-call markup so raw tags never reach the user."""
    if not text:
        return ""
    for pattern in _JSON_CALL_PATTERNS + [_PY_CALL_PATTERN]:
        text = pattern.sub("", text)
    return _RESIDUAL_TAGS.sub("", text).strip()


def _trim_message(m: BaseMessage) -> BaseMessage:
    if isinstance(m, ToolMessage):
        text = str(m.content)
        if len(text) > _MAX_TOOL_CHARS:
            return ToolMessage(
                content=text[:_MAX_TOOL_CHARS] + "...[truncated]",
                tool_call_id=m.tool_call_id,
                name=m.name,
            )
    elif isinstance(m, AIMessage) and m.content and len(m.content) > _MAX_AI_CHARS:
        return AIMessage(
            content=m.content[:_MAX_AI_CHARS] + "...",
            tool_calls=list(m.tool_calls),
        )
    return m


def message_to_openai(m: BaseMessage) -> Dict[str, Any]:
    if isinstance(m, SystemMessage):
        return {"role": "system", "content": str(m.content)}
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
            "id": tc.get("id") or _new_call_id(),
            "type": "tool_call",
        })

    content = choice.get("content", "") or ""
    if not tool_calls:
        tool_calls, content = extract_text_tool_calls(content)

    return AIMessage(content=content, tool_calls=tool_calls)
