import json, sqlite3, threading, requests
from typing import Annotated, TypedDict
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages

class State(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    evidence: list
    discoveries: list
    iteration: int
    max_iterations: int
    tables: list[str]

class LocalModel:
    def __init__(self, url, model): self.url, self.model = url, model

    def invoke(self, messages, tools):
        converted=[]
        for m in messages:
            role="system" if isinstance(m,SystemMessage) else "tool" if isinstance(m,ToolMessage) else "assistant" if isinstance(m,AIMessage) else "user"
            converted.append({"role":role,"content":m.content if isinstance(m.content,str) else str(m.content)})
        payload={"model":self.model,"messages":converted,"temperature":.2}
        if tools:
            payload["tools"]=[{"type":"function","function":{"name":t.name,"description":t.description,"parameters":t.args_schema.model_json_schema()}} for t in tools]
            payload["tool_choice"]="auto"
        r=requests.post(self.url,json=payload,timeout=180); r.raise_for_status()
        msg=r.json()["choices"][0]["message"]
        return AIMessage(content=msg.get("content") or "", tool_calls=[
            {"name":c["function"]["name"],"args":json.loads(c["function"]["arguments"]),"id":c["id"],"type":"tool_call"}
            for c in msg.get("tool_calls",[])
        ])

class DiscoveryAgent:
    SYSTEM="""You are an autonomous organizational data discovery agent.
Explore the selected organizational data and discover valuable, non-obvious,
evidence-backed patterns. Do NOT assume personas, workflows, business
questions, or a fixed sequence. Decide what to investigate next from evidence.
Use tools when evidence is needed. Stop when further investigation has low
value. Never invent facts. Human steering is a hint, not a mandatory workflow.
Do not expose private chain-of-thought. Give concise observable decisions,
hypotheses, evidence summaries and discoveries."""
    def __init__(self, db_path, tables, model_url, model_name, on_event):
        self.db_path,self.tables,self.on_event=db_path,tables,on_event
        self.model=LocalModel(model_url,model_name); self.gate=threading.Event(); self.gate.set()
        self.graph=self._build()
    def pause(self): self.gate.clear()
    def resume(self): self.gate.set()
    def _wait(self): self.gate.wait()
    def _schema(self,t):
        with sqlite3.connect(self.db_path) as c:
            return [{"name":r[1],"type":r[2]} for r in c.execute(f'PRAGMA table_info("{t}")')]
    def _tools(self):
        allowed=set(self.tables); db=self.db_path
        @tool
        def inspect_schema(table:str)->dict:
            """Inspect columns and types of a selected SQLite table."""
            if table not in allowed: raise ValueError("Table is not selected")
            self.on_event("TOOL",f"inspect_schema('{table}')")
            return {"table":table,"schema":self._schema(table)}
        @tool
        def profile_table(table:str)->dict:
            """Get row count and a five-row sample from a selected SQLite table."""
            if table not in allowed: raise ValueError("Table is not selected")
            schema=self._schema(table)
            with sqlite3.connect(db) as c:
                n=c.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                rows=c.execute(f'SELECT * FROM "{table}" LIMIT 5').fetchall()
            self.on_event("TOOL",f"profile_table('{table}') → {n:,} rows")
            return {"table":table,"row_count":n,"sample":[dict(zip([x["name"] for x in schema],r)) for r in rows]}
        @tool
        def readonly_sql(sql:str)->dict:
            """Run a read-only SELECT or WITH query for evidence gathering."""
            q=sql.strip().rstrip(";")
            if not q.lower().startswith(("select","with")): raise ValueError("Only SELECT/WITH allowed")
            with sqlite3.connect(db) as c:
                c.row_factory=sqlite3.Row; rows=c.execute(q).fetchmany(100)
            self.on_event("TOOL",f"readonly SQL → {len(rows)} rows")
            return {"rows":[dict(x) for x in rows]}
        return [inspect_schema,profile_table,readonly_sql]
    def _build(self):
        tools=self._tools(); toolnode=ToolNode(tools)
        def decide(s):
            self._wait(); i=s.get("iteration",0)+1
            self.on_event("LOOP",f"LangGraph iteration {i}")
            ctx={"tables":s["tables"],"evidence":s.get("evidence",[])[-20:],"iteration":i,"max_iterations":s.get("max_iterations",8)}
            prompt="Current investigation state:\n"+json.dumps(ctx,default=str)+"\nDecide the next useful investigation. Call a tool if needed. If enough evidence exists, return JSON {title,summary,evidence,confidence}; otherwise investigate further or say STOP."
            r=self.model.invoke([SystemMessage(content=self.SYSTEM),*s.get("messages",[]),HumanMessage(content=prompt)],tools)
            self.on_event("AGENT","Agent selected the next investigation step.")
            return {"messages":[r],"iteration":i}
        def route(s):
            if s.get("iteration",0)>=s.get("max_iterations",8): return "finish"
            return "tools" if getattr(s["messages"][-1],"tool_calls",[]) else "finish"
        def run_tools(s): self._wait(); return toolnode.invoke(s)
        def finish(s):
            ds=list(s.get("discoveries",[])); last=s["messages"][-1]
            try:
                x=json.loads(last.content)
                if isinstance(x,dict) and x.get("title"):
                    ds.append(x); self.on_event("DISCOVERY",x["title"])
            except Exception: pass
            self.on_event("DECISION","Investigation finished.")
            return {"discoveries":ds}
        g=StateGraph(State)
        g.add_node("decide",decide); g.add_node("tools",run_tools); g.add_node("finish",finish)
        g.add_edge(START,"decide")
        g.add_conditional_edges("decide",route,{"tools":"tools","finish":"finish"})
        g.add_edge("tools","decide"); g.add_edge("finish",END)
        return g.compile()
    def run(self, steering=""):
        self.on_event("START",f"Investigation started on {len(self.tables)} selected table(s).")
        evidence=[{"table":t,"schema":self._schema(t)} for t in self.tables]
        msgs=[HumanMessage(content=f"Human steering/hunch: {steering}")] if steering else []
        result=self.graph.invoke({"messages":msgs,"evidence":evidence,"discoveries":[],"iteration":0,"max_iterations":8,"tables":self.tables})
        self.on_event("END","LangGraph explorer completed.")
        return {"discoveries":result.get("discoveries",[]),"evidence":result.get("evidence",evidence)}
