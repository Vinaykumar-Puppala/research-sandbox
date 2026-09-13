import json
import sqlite3
import threading
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from discovery_agent import DiscoveryAgent

DB_DIR = Path("data")
DB_DIR.mkdir(exist_ok=True)
DEFAULT_DB = DB_DIR / "workspace.db"

st.set_page_config(page_title="Autonomous Data Discovery", layout="wide")

if "running" not in st.session_state:
    st.session_state.running = False
if "paused" not in st.session_state:
    st.session_state.paused = False
if "events" not in st.session_state:
    st.session_state.events = []
if "discoveries" not in st.session_state:
    st.session_state.discoveries = []
if "agent_thread" not in st.session_state:
    st.session_state.agent_thread = None
if "steering" not in st.session_state:
    st.session_state.steering = ""


def add_event(kind, message):
    st.session_state.events.append({
        "time": time.strftime("%H:%M:%S"),
        "kind": kind,
        "message": message,
    })


def list_tables(db_path):
    with sqlite3.connect(db_path) as con:
        rows = con.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    return [r[0] for r in rows]


def import_csv(uploaded_file, db_path, table_name):
    df = pd.read_csv(uploaded_file)
    with sqlite3.connect(db_path) as con:
        df.to_sql(table_name, con, if_exists="replace", index=False)
    return len(df)


def run_agent(db_path, tables, model_url, model_name, steering):
    agent = DiscoveryAgent(
        db_path=str(db_path),
        tables=tables,
        model_url=model_url,
        model_name=model_name,
        on_event=add_event,
    )
    try:
        result = agent.run(initial_steering=steering)
        st.session_state.discoveries = result.get("discoveries", [])
        add_event("DONE", f"Investigation completed with {len(st.session_state.discoveries)} discovery candidates.")
    except Exception as exc:
        add_event("ERROR", str(exc))
    finally:
        st.session_state.running = False


st.title("Autonomous Organizational Data Discovery — V1")
st.caption("One autonomous explorer. SQLite + local model. No predefined personas or workflows.")

left, right = st.columns([0.34, 0.66])

with left:
    st.subheader("1. Data")

    db_path = st.text_input("SQLite database", str(DEFAULT_DB))

    if not Path(db_path).exists():
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        sqlite3.connect(db_path).close()

    uploaded = st.file_uploader("Optional: upload CSV", type=["csv"])
    if uploaded:
        suggested = Path(uploaded.name).stem.replace(" ", "_")
        table_name = st.text_input("Table name", suggested)
        if st.button("Import CSV"):
            rows = import_csv(uploaded, db_path, table_name)
            add_event("DATA", f"Imported {rows} rows into table '{table_name}'.")

    tables = list_tables(db_path)
    selected = st.multiselect("Tables to investigate", tables, default=tables[:3])

    st.subheader("2. Local model")
    model_url = st.text_input("OpenAI-compatible endpoint", "http://localhost:8000/v1/chat/completions")
    model_name = st.text_input("Model name", "local-model")

    st.subheader("3. Human steering")
    steering = st.text_area(
        "Optional thought / hunch",
        placeholder="Example: Look closely for repeated workflows or unusual user behavior.",
        height=110,
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        start = st.button("▶ Start", disabled=st.session_state.running)
    with c2:
        pause = st.button("⏸ Pause", disabled=not st.session_state.running)
    with c3:
        resume = st.button("▶ Resume", disabled=not st.session_state.running)

    if start:
        if not selected:
            st.error("Select at least one table.")
        else:
            st.session_state.events = []
            st.session_state.discoveries = []
            st.session_state.running = True
            st.session_state.paused = False
            st.session_state.steering = steering
            st.session_state.agent_thread = threading.Thread(
                target=run_agent,
                args=(db_path, selected, model_url, model_name, steering),
                daemon=True,
            )
            st.session_state.agent_thread.start()
            st.rerun()

    if pause:
        st.session_state.paused = True
        add_event("CONTROL", "Pause requested. Current agent iteration will finish safely.")

    if resume:
        st.session_state.paused = False
        add_event("CONTROL", "Resume requested.")

with right:
    st.subheader("Live investigation")
    st.info(
        "The console shows observable agent actions, evidence, hypotheses, "
        "and tool calls. It intentionally does not expose private chain-of-thought."
    )

    if st.session_state.events:
        for e in reversed(st.session_state.events[-80:]):
            st.markdown(f"**[{e['time']}] {e['kind']}** — {e['message']}")
    else:
        st.write("Waiting for investigation...")

    st.divider()
    st.subheader("Discovery candidates")

    if st.session_state.discoveries:
        for i, d in enumerate(st.session_state.discoveries, 1):
            with st.container(border=True):
                st.markdown(f"### Discovery {i}")
                st.write(d.get("title", "Untitled"))
                st.write(d.get("summary", ""))
                if d.get("evidence"):
                    st.markdown("**Evidence**")
                    st.code(json.dumps(d["evidence"], indent=2))
                if d.get("confidence") is not None:
                    st.caption(f"Confidence: {d['confidence']}")
    else:
        st.write("No discoveries yet.")

if st.session_state.running:
    time.sleep(1)
    st.rerun()
