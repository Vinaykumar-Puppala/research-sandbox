import json
import os
import threading
import time
from typing import Any, List, Optional, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from data_tools import TOOLS, openai_tool_schemas
from db import Database
from local_model import call_local_model


SYSTEM_PROMPT = """
You are an autonomous organizational data discovery agent.

Your objective is to discover meaningful, non-obvious, evidence-backed
patterns from selected organizational data.

Do NOT use predefined personas or fixed business workflows. Do not force
the investigation into CEO, Product, Security, Employee, Customer,
Operations, Finance, Compliance, or Engineering categories.

One explorer agent must dynamically determine what to investigate next.

LOOP:
OBSERVE
-> identify UNKNOWN / interesting pattern
-> form HYPOTHESIS
-> choose highest-value next investigation
-> USE TOOL
-> gather EVIDENCE
-> VALIDATE / REJECT
-> update understanding
-> continue or STOP

Explore when justified:
- distributions
- concentrations
- unusual segments
- temporal patterns when time fields exist
- repeated activity
- duplicated workflows
- cross-table relationships
- anomalies
- data quality gaps
- adoption patterns
- operational bottlenecks
- hidden dependencies
- unexpected correlations
- meaningful exceptions
- emerging patterns

Do not call a correlation meaningful merely because it is large.
Validate plausible relationships with additional evidence.

Cross-table rule:
inspect schemas first and infer relationships from actual data. Never assume
a join merely because table names appear related.

Evidence rule:
Every strong discovery must be supported by actual tool output.
Never invent values, records, causes, or relationships.
Separate observation from interpretation.

Human steering:
Human input is a hypothesis/hunch. Validate it independently.

Stopping:
Stop when discoveries are sufficiently validated, remaining investigation
has low expected information value, useful data is exhausted, or the budget
is reached.

Observable events can expose:
OBSERVE, HYPOTHESIS, TOOL, QUERY, EVIDENCE, VALIDATION, DISCOVERY, DECISION,
HUMAN, STOP.

Never expose private chain-of-thought.

Final synthesis:
Return up to five strongest discoveries using:

DISCOVERY:
title: ...
summary: ...
significance: ...
confidence: 0.0-1.0
evidence: ...

If evidence is insufficient, return NO_STRONG_DISCOVERY.
"""


class State(TypedDict, total=False):
    messages: List[Any]
    iteration: int
    max_iterations: int
    max_tool_calls: int
    tool_calls_used: int
    run_id: str
    tables: List[str]
    objective: str
    status: str
    final_text: str


class Controller:
    def __init__(self):
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.stop_event = threading.Event()

    def pause(self):
        self.pause_event.clear()

    def resume(self):
        self.pause_event.set()

    def stop(self):
        self.stop_event.set()
        self.pause_event.set()

    def gate(self):
        while not self.pause_event.is_set():
            if self.stop_event.is_set():
                return False
            time.sleep(0.2)
        return not self.stop_event.is_set()


class AutonomousDiscovery:
    def __init__(self, db_path, endpoint, model,
                 controller=None, max_iterations=12, max_tool_calls=30):
        os.environ["DISCOVERY_DB"] = db_path
        self.db = Database(db_path)
        self.endpoint = endpoint
        self.model = model
        self.controller = controller or Controller()
        self.max_iterations = max_iterations
        self.max_tool_calls = max_tool_calls
        self.tool_schemas = openai_tool_schemas()
        self.graph = self._build_graph()

    def log(self, run_id, event_type, message, payload=None):
        self.db.log_event(run_id, event_type, message, payload)

    def _build_graph(self):
        workflow = StateGraph(State)
        workflow.add_node("decide", self.decide)
        workflow.add_node("tools", ToolNode(TOOLS))
        workflow.add_node("observe", self.observe_tool_result)
        workflow.add_node("finish", self.finish)

        workflow.add_edge(START, "decide")
        workflow.add_conditional_edges(
            "decide", self.route,
            {"tools": "tools", "finish": "finish"}
        )
        workflow.add_edge("tools", "observe")
        workflow.add_edge("observe", "decide")
        workflow.add_edge("finish", END)
        return workflow.compile()

    def decide(self, state):
        run_id = state["run_id"]

        if not self.controller.gate():
            return {"status": "stopped"}

        iteration = state.get("iteration", 0) + 1
        if iteration > state["max_iterations"]:
            self.log(run_id, "STOP", "Maximum investigation iterations reached.")
            return {"status": "finished", "iteration": iteration}

        if state.get("tool_calls_used", 0) >= state["max_tool_calls"]:
            self.log(run_id, "STOP", "Maximum tool-call budget reached.")
            return {"status": "finished", "iteration": iteration}

        steering = self.db.consume_steering(run_id)
        new_messages = list(state.get("messages", []))
        if steering:
            text = "\n".join(f"HUMAN STEERING: {x}" for x in steering)
            new_messages.append(HumanMessage(content=text))
            self.log(run_id, "HUMAN", text)

        context = (
            f"SELECTED TABLES: {json.dumps(state['tables'])}\n"
            f"OPEN-ENDED OBJECTIVE: {state['objective']}\n"
            f"ITERATION: {iteration}/{state['max_iterations']}\n"
            f"TOOL BUDGET: {state.get('tool_calls_used',0)}/"
            f"{state['max_tool_calls']}\n"
            "Continue autonomously. Choose the next highest-value evidence "
            "gathering action, or finish if evidence is sufficient."
        )
        new_messages.append(HumanMessage(content=context))

        self.log(run_id, "OBSERVE", f"Evaluating iteration {iteration}.",
                 {"tables": state["tables"]})

        ai = call_local_model(
            [HumanMessage(content=SYSTEM_PROMPT)] + new_messages,
            tools=self.tool_schemas,
            endpoint=self.endpoint,
            model=self.model,
        )

        if ai.tool_calls:
            count = len(ai.tool_calls)
            names = [x["name"] for x in ai.tool_calls]
            self.log(run_id, "TOOL",
                     f"Selected: {', '.join(names)}",
                     {"tool_calls": [
                         {"name": x["name"], "args": x.get("args", {})}
                         for x in ai.tool_calls
                     ]})
            return {
                "messages": new_messages + [ai],
                "iteration": iteration,
                "tool_calls_used": state.get("tool_calls_used", 0) + count
            }

        if ai.content:
            self.log(run_id, "DECISION", ai.content[:4000])
        return {
            "messages": new_messages + [ai],
            "iteration": iteration,
            "status": "finished"
        }

    def route(self, state):
        if state.get("status") in {"finished", "stopped"}:
            return "finish"
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return "finish"

    def observe_tool_result(self, state):
        run_id = state["run_id"]
        for message in state["messages"][-20:]:
            if isinstance(message, ToolMessage):
                text = str(message.content)
                event = "QUERY" if "sql" in (message.name or "").lower() else "EVIDENCE"
                self.log(
                    run_id, event,
                    f"{message.name or 'tool'} returned evidence.",
                    {"preview": text[:5000]}
                )
        return {}

    def finish(self, state):
        run_id = state["run_id"]

        if not self.controller.gate():
            self.db.update_run(run_id, status="stopped",
                               iterations=state.get("iteration", 0), finished=True)
            self.log(run_id, "STOP", "Investigation stopped by user.")
            return {"status": "stopped"}

        synthesis = list(state["messages"])
        synthesis.append(HumanMessage(content="""
Synthesize only from actual tool results above.

Return 0-5 strongest validated discoveries:

DISCOVERY:
title: ...
summary: ...
significance: ...
confidence: 0.0-1.0
evidence: ...

Do not invent evidence. If nothing is sufficiently supported:
NO_STRONG_DISCOVERY
"""))

        try:
            ai = call_local_model(
                [HumanMessage(content=SYSTEM_PROMPT)] + synthesis,
                tools=None, endpoint=self.endpoint, model=self.model
            )
            text = ai.content or "NO_STRONG_DISCOVERY"
        except Exception as exc:
            text = f"Synthesis failed: {exc}"

        self.persist_discoveries(run_id, text)
        status = "stopped" if state.get("status") == "stopped" else "finished"
        self.db.update_run(run_id, status=status,
                           iterations=state.get("iteration", 0), finished=True)
        self.log(run_id, "DISCOVERY", text[:10000])
        self.log(run_id, "STOP", "Investigation complete.")
        return {"final_text": text, "status": status}

    def persist_discoveries(self, run_id, text):
        if "NO_STRONG_DISCOVERY" in text:
            return

        for block in [x.strip() for x in text.split("DISCOVERY:") if x.strip()][:5]:
            data = {}
            for line in block.splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    data[key.strip().lower()] = value.strip()

            title = data.get("title", "Untitled discovery")
            summary = data.get("summary", block[:1200])
            significance = data.get("significance", "")
            try:
                confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
            except Exception:
                confidence = 0.5

            evidence_id = self.db.add_evidence(
                run_id,
                f"Validated discovery: {title}",
                summary,
                source="validated model synthesis",
                confidence=confidence,
            )
            discovery_id = self.db.add_discovery(
                run_id, title, summary, significance, confidence, [evidence_id]
            )

            dataset_node = self.db.add_node(run_id, "dataset", "selected_data")
            discovery_node = self.db.add_node(
                run_id, "discovery", title,
                {"confidence": confidence, "discovery_id": discovery_id}
            )
            self.db.add_edge(
                run_id, dataset_node, discovery_node, "supports",
                evidence_id=evidence_id
            )

    def run(self, tables, objective):
        run_id = self.db.start_run(tables, objective)
        state = {
            "messages": [HumanMessage(content=(
                "Start a fresh autonomous investigation. Explore the selected "
                "tables and discover meaningful evidence-backed patterns."
            ))],
            "iteration": 0,
            "max_iterations": self.max_iterations,
            "max_tool_calls": self.max_tool_calls,
            "tool_calls_used": 0,
            "run_id": run_id,
            "tables": tables,
            "objective": objective,
            "status": "running",
        }
        try:
            result = self.graph.invoke(state)
            return run_id, result
        except Exception as exc:
            self.db.update_run(run_id, status="error",
                               iterations=state["iteration"], finished=True)
            self.log(run_id, "ERROR", str(exc))
            raise
