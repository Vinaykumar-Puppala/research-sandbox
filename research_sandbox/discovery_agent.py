import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Callable

import requests


@dataclass
class AgentState:
    iteration: int = 0
    max_iterations: int = 8
    paused: bool = False


class SQLiteTools:
    def __init__(self, db_path: str, tables: list[str], on_event: Callable):
        self.db_path = db_path
        self.tables = tables
        self.on_event = on_event

    def schema(self):
        result = {}
        with sqlite3.connect(self.db_path) as con:
            for table in self.tables:
                cols = con.execute(f'PRAGMA table_info("{table}")').fetchall()
                result[table] = [
                    {"name": c[1], "type": c[2], "nullable": not bool(c[3])}
                    for c in cols
                ]
        self.on_event("TOOL", "Inspected schemas for selected tables.")
        return result

    def profile(self, table: str):
        with sqlite3.connect(self.db_path) as con:
            count = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            sample = con.execute(f'SELECT * FROM "{table}" LIMIT 5').fetchall()
            columns = [x[1] for x in con.execute(f'PRAGMA table_info("{table}")').fetchall()]

        result = {
            "table": table,
            "row_count": count,
            "columns": columns,
            "sample": [dict(zip(columns, row)) for row in sample],
        }
        self.on_event("TOOL", f"Profiled '{table}': {count:,} rows.")
        return result

    def aggregate_numeric(self, table: str, column: str):
        # Identifier names come only from PRAGMA metadata, not arbitrary user input.
        with sqlite3.connect(self.db_path) as con:
            row = con.execute(
                f'SELECT MIN("{column}"), MAX("{column}"), AVG("{column}") FROM "{table}"'
            ).fetchone()
        result = {"table": table, "column": column, "min": row[0], "max": row[1], "avg": row[2]}
        self.on_event("TOOL", f"Calculated numeric summary for {table}.{column}.")
        return result


class LocalModel:
    def __init__(self, url: str, model_name: str):
        self.url = url
        self.model_name = model_name

    def ask(self, system: str, user: str) -> str:
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        response = requests.post(self.url, json=payload, timeout=180)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


class DiscoveryAgent:
    """
    V1 autonomous explorer.

    It is deliberately NOT given CEO/CISO/product workflows.
    The model decides what question to investigate next from available evidence.
    """

    SYSTEM = """
You are an autonomous organizational data discovery researcher.

Your objective is to discover useful, non-obvious, evidence-backed patterns in
the supplied organizational data.

Do NOT assume predefined personas, business workflows, or hypotheses.
Do NOT invent facts.

At each iteration:
1. Review the available evidence.
2. Identify the most valuable unanswered question.
3. Request the next analysis through the available tool plan.
4. Compare the result with previous evidence.
5. Produce a candidate discovery only when evidence supports it.
6. Decide what should be investigated next.

Prioritize discoveries involving:
- repeated workflows and user behavior
- process bottlenecks or duplication
- relationships between systems/tables
- unusual patterns or outliers
- high-value or underused capabilities
- opportunities to automate
- data quality problems
- security/privacy-relevant anomalies when evidence supports them
- dependencies and cross-system behavior

Return JSON only:
{
  "next_action": "profile" | "numeric_summary" | "stop",
  "table": "...",
  "column": "...",
  "hypothesis": "...",
  "discovery": {
      "title": "...",
      "summary": "...",
      "evidence": [],
      "confidence": 0.0
  }
}

If more evidence is needed, discovery may be null.
"""

    def __init__(self, db_path, tables, model_url, model_name, on_event):
        self.tools = SQLiteTools(db_path, tables, on_event)
        self.model = LocalModel(model_url, model_name)
        self.tables = tables
        self.on_event = on_event
        self.state = AgentState()
        self.evidence = []
        self.discoveries = []

    def _ask(self, context):
        self.on_event("AGENT", "Evaluating evidence and selecting the next investigation.")
        raw = self.model.ask(self.SYSTEM, json.dumps(context, default=str))
        raw = raw.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(raw)

    def run(self, initial_steering=""):
        self.on_event("START", f"Autonomous investigation started on {len(self.tables)} table(s).")

        schemas = self.tools.schema()
        profiles = [self.tools.profile(t) for t in self.tables]

        self.evidence.extend([{"type": "schema", "value": schemas}])
        self.evidence.extend([{"type": "profile", "value": p} for p in profiles])

        if initial_steering:
            self.on_event("HUMAN", f"Human steering received: {initial_steering}")

        while self.state.iteration < self.state.max_iterations:
            while getattr(self.state, "paused", False):
                time.sleep(0.5)

            self.state.iteration += 1
            self.on_event("LOOP", f"Investigation iteration {self.state.iteration}/{self.state.max_iterations}")

            context = {
                "tables": self.tables,
                "evidence": self.evidence[-20:],
                "human_steering": initial_steering,
                "iteration": self.state.iteration,
            }

            try:
                decision = self._ask(context)
            except Exception as exc:
                self.on_event("ERROR", f"Model response could not be parsed: {exc}")
                break

            action = decision.get("next_action", "stop")
            hypothesis = decision.get("hypothesis", "")
            if hypothesis:
                self.on_event("HYPOTHESIS", hypothesis)

            if action == "stop":
                self.on_event("DECISION", "Agent decided that additional investigation is unlikely to add enough value.")
                candidate = decision.get("discovery")
                if candidate:
                    self.discoveries.append(candidate)
                break

            table = decision.get("table")
            if table not in self.tables:
                self.on_event("WARN", f"Agent selected invalid table '{table}'. Stopping.")
                break

            if action == "profile":
                result = self.tools.profile(table)
                self.evidence.append({"type": "profile", "value": result})

            elif action == "numeric_summary":
                column = decision.get("column")
                valid_columns = {c["name"] for c in self.tools.schema()[table]}
                if column not in valid_columns:
                    self.on_event("WARN", f"Invalid column '{column}'.")
                    continue
                result = self.tools.aggregate_numeric(table, column)
                self.evidence.append({"type": "numeric_summary", "value": result})

            candidate = decision.get("discovery")
            if candidate and candidate.get("title"):
                self.discoveries.append(candidate)
                self.on_event("DISCOVERY", candidate["title"])

        self.on_event("END", "Explorer finished.")
        return {"discoveries": self.discoveries, "evidence": self.evidence}
