# Autonomous Organizational Discovery — Final V1+V2

A complete local prototype combining the V1 autonomous explorer and V2
evidence/discovery platform.

## What is included

### Data
- CSV
- Excel XLSX/XLS, including sheet selection
- Parquet
- JSON
- JSONL / NDJSON
- Multiple tables/datasets in one investigation
- SQLite normalization

### Autonomous exploration
- One autonomous explorer agent
- Open-ended objective
- Dynamic next-action selection
- Cyclic LangGraph execution
- Generic data-analysis tools
- Cross-table investigation
- Human steering
- Pause / resume / stop
- Investigation budgets
- Explicit stopping criteria

### Analysis tools
- Schema inspection
- Table profiling
- Read-only SQL
- Descriptive statistics
- Value distributions
- Correlation analysis
- Cross-table JOIN exploration

### Knowledge layer
- Persistent activity events
- Persistent evidence
- Persistent discoveries
- Lightweight discovery graph
- Discovery Workspace

### Conversational layer
- Chat With My Data
- Selected-table grounding
- Tool-assisted answers
- Read-only analysis

## Core architecture

Streamlit
  |
  +--> Ingestion --> SQLite data tables
  |
  +--> Autonomous Discovery
  |       |
  |       +--> LangGraph
  |       +--> Local LLM
  |       +--> Generic Data Tools
  |       +--> Evidence Store
  |       +--> Discovery Store
  |       +--> Discovery Graph
  |
  +--> Discovery Workspace
  |
  +--> Chat With My Data

The LangGraph execution graph is intentionally small:

START -> DECIDE -> TOOLS -> OBSERVE -> DECIDE -> ... -> FINISH

The graph is not the organization's workflow. The LLM dynamically chooses
what to investigate next.

## Local model

Default:
http://localhost:8000/v1/chat/completions

Environment variables:
- MODEL_ENDPOINT
- MODEL_NAME
- DISCOVERY_DB_PATH

The local endpoint should support OpenAI-compatible tool/function calling.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Prototype safety

SQL is restricted to read-only SELECT/WITH/PRAGMA operations and result
sizes are capped. This is a local prototype, not a production multi-tenant
security boundary. Production should add authentication, authorization,
tenant isolation, query governance, resource quotas, durable checkpointing,
and audit controls.

## Design principle

Do not hard-code CEO/Product/Security/Employee/Customer/etc. as autonomous
agents or workflows.

Those are future lenses over the common evidence/discovery graph.

The organizational story should emerge from the data.


rm -r ../autonomous_org_discovery_v1_multiformat/
rm ../app.py ../discovery_agent.py