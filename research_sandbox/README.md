# Autonomous Organizational Data Discovery — V1

A local prototype for experimenting with an autonomous discovery agent over SQLite.

## Architecture

Streamlit UI
    |
    +-- SQLite database/table selection
    |
    +-- Human steering input
    |
    +-- Start / Pause / Resume
    |
Python DiscoveryAgent
    |
    +-- SQLiteTools
    +-- LocalModel
    |
localhost:8000/v1/chat/completions

The model receives evidence and decides what to investigate next. There are no
predefined CEO/CISO/product sub-agents in V1.

## Run

Create a virtual environment, then:

    pip install -r requirements.txt
    streamlit run app.py

Put a SQLite database at:

    data/workspace.db

or use the CSV uploader to create a table.

The local model endpoint is expected to be OpenAI-compatible:

    http://localhost:8000/v1/chat/completions

Change the URL and model name in the UI if needed.

## Important V1 design choice

The console displays observable events:
- TOOL
- HYPOTHESIS
- DECISION
- DISCOVERY
- HUMAN
- LOOP

It does not display private chain-of-thought. This is intentional: the useful
transparency is what data was inspected, what hypothesis was selected, what
tool was called, what evidence was found, and what discovery was produced.

## Next evolution

V2 can add:
- discovery memory
- evidence graph
- relationship discovery across tables
- richer analytics/data-interpreter skills
- persona lenses (CEO, product, security, employee, customer, operations, etc.)
- a separate "Chat with My Data" page
- human steering while an investigation is running
- persistent investigation history
