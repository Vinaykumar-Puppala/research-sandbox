# Autonomous Organizational Discovery

A local prototype combining autonomous data exploration with a persistent
evidence/discovery platform. Ingest tabular data, let an LLM-driven agent
discover patterns and anomalies, and chat with your data — all running
against a local model.

## What is included

### Data formats
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
- Anomaly detection
- Data quality scoring
- Temporal trend analysis
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

## Architecture

```
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
```

The LangGraph execution graph is intentionally small:

```
START -> DECIDE -> TOOLS -> OBSERVE -> DECIDE -> ... -> FINISH
```

The graph is not the organization's workflow. The LLM dynamically chooses
what to investigate next.

## Quick Start

```bash
pip install -r research_sandbox/requirements.txt
# or install as a package:
pip install -e .

streamlit run research_sandbox/app.py
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MODEL_ENDPOINT` | `http://localhost:8000/v1/chat/completions` | Local LLM endpoint URL |
| `MODEL_NAME` | `local-model` | Model identifier sent in API requests |
| `DISCOVERY_DB_PATH` | `discovery_final.db` | SQLite database file path |

Copy `.env.example` to `.env` and fill in your values.

## Local Model

The local endpoint must support OpenAI-compatible tool/function calling.
Default: `http://localhost:8000/v1/chat/completions`

See [`docs/local_model_setup.md`](docs/local_model_setup.md) for Windows
llama.cpp / llama-cpp-python setup notes.

## Prototype Safety

SQL is restricted to read-only SELECT/WITH/PRAGMA operations and result
sizes are capped. This is a local prototype, not a production multi-tenant
security boundary. Production deployments should add authentication,
authorization, tenant isolation, query governance, resource quotas,
durable checkpointing, and audit controls.

## Design Principle

Do not hard-code CEO/Product/Security/Employee/Customer/etc. as autonomous
agents or workflows.

Those are future lenses over the common evidence/discovery graph.

The organizational story should emerge from the data.

## Documentation

| File | Description |
|---|---|
| [`docs/v1_agent_design.md`](docs/v1_agent_design.md) | V1 agent design specification and system prompt |
| [`docs/local_model_setup.md`](docs/local_model_setup.md) | Windows llama.cpp / llama-cpp-python setup notes |
| [`docs/REVIEW_SUMMARY.md`](docs/REVIEW_SUMMARY.md) | Code review executive summary |
| [`docs/CODE_REVIEW.md`](docs/CODE_REVIEW.md) | Gap analysis and technical recommendations |
| [`docs/IMPLEMENTATION_GUIDE.md`](docs/IMPLEMENTATION_GUIDE.md) | Step-by-step enhancement tasks |
| [`docs/QUICK_REFERENCE.md`](docs/QUICK_REFERENCE.md) | Architecture cheat sheet and troubleshooting |
| [`docs/DOCUMENTATION_INDEX.md`](docs/DOCUMENTATION_INDEX.md) | Full documentation index |
