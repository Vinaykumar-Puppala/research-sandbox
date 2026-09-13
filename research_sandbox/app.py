import os
import tempfile
import threading
import uuid
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from chat_agent import chat_with_data
from db import Database
from discovery_agent import AutonomousDiscovery, Controller
from graph_viz import build_graph_html
from ingestion import FileIngestionService


st.set_page_config(
    page_title="Autonomous Organizational Discovery",
    page_icon="🔎",
    layout="wide"
)

DEFAULT_DB = os.getenv("DISCOVERY_DB_PATH", "discovery_final.db")
DEFAULT_ENDPOINT = os.getenv(
    "MODEL_ENDPOINT", "http://localhost:8000/v1/chat/completions"
)
DEFAULT_MODEL = os.getenv("MODEL_NAME", "local-model")


if "controller" not in st.session_state:
    st.session_state.controller = Controller()
if "run_id" not in st.session_state:
    st.session_state.run_id = None
if "run_thread" not in st.session_state:
    st.session_state.run_thread = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []


st.title("🔎 Autonomous Organizational Discovery")
st.caption(
    "Final V1 + V2 · One autonomous explorer · Generic data tools · "
    "Evidence-backed discovery · Human steering"
)

with st.sidebar:
    st.header("Runtime")
    db_path = st.text_input("SQLite database", DEFAULT_DB)
    endpoint = st.text_input("Local model endpoint", DEFAULT_ENDPOINT)
    model_name = st.text_input("Model name", DEFAULT_MODEL)
    max_iterations = st.slider("Max investigation iterations", 3, 30, 12)
    max_tool_calls = st.slider("Max tool calls", 5, 100, 30)

db = Database(db_path)
ingestor = FileIngestionService()

ingest_tab, discover_tab, workspace_tab, chat_tab = st.tabs([
    "1 · Ingest Data",
    "2 · Autonomous Discovery",
    "3 · Discovery Workspace",
    "4 · Chat With My Data"
])


with ingest_tab:
    st.subheader("1. Ingest organizational data")
    st.write(
        "Supported: CSV, Excel/XLSX/XLS, Parquet, JSON, JSONL and NDJSON."
    )

    uploads = st.file_uploader(
        "Upload one or more files",
        type=["csv", "xlsx", "xls", "parquet", "json", "jsonl", "ndjson"],
        accept_multiple_files=True,
    )

    for upload in uploads or []:
        suffix = Path(upload.name).suffix.lower()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(upload.getvalue())
        tmp.close()

        sheet = None
        if suffix in {".xlsx", ".xls"}:
            sheets = ingestor.inspect_excel(tmp.name)
            sheet = st.selectbox(
                f"Sheet — {upload.name}", sheets,
                key=f"sheet_{upload.name}"
            )

        if st.button(f"Import {upload.name}", key=f"import_{upload.name}"):
            try:
                df = ingestor.load(tmp.name, sheet)
                with db.connect() as conn:
                    table = ingestor.write_sqlite(
                        conn, df, Path(upload.name).stem +
                        (f"_{sheet}" if sheet else "")
                    )
                db.register_ingestion(
                    upload.name, suffix.lstrip("."), table, sheet,
                    len(df), len(df.columns)
                )
                st.success(
                    f"Imported {len(df):,} rows × {len(df.columns)} columns "
                    f"as `{table}`"
                )
            except Exception as exc:
                st.error(f"Import failed: {exc}")

    st.markdown("### Loaded data")
    registry = db.registry()
    if registry:
        st.dataframe(registry, use_container_width=True, hide_index=True)
    else:
        st.info("No data loaded.")


with discover_tab:
    st.subheader("2. Autonomous Discovery")

    tables = db.table_names()
    if not tables:
        st.warning("Load data first.")
    else:
        selected_tables = st.multiselect(
            "Select tables for this investigation",
            tables,
            default=tables[:min(3, len(tables))],
            key="discovery_tables"
        )

        objective = st.text_area(
            "Open-ended objective",
            value=(
                "Explore the selected organizational data and discover "
                "meaningful, non-obvious, evidence-backed patterns. "
                "Do not assume a predefined business workflow."
            ),
            height=110
        )

        col1, col2, col3, col4 = st.columns(4)

        if col1.button(
            "▶ Start",
            use_container_width=True,
            disabled=not selected_tables
        ):
            controller = Controller()
            st.session_state.controller = controller

            pre_run_id = str(uuid.uuid4())
            db.start_run(selected_tables, objective, run_id=pre_run_id)
            st.session_state.run_id = pre_run_id

            def worker():
                try:
                    agent = AutonomousDiscovery(
                        db_path=db_path,
                        endpoint=endpoint,
                        model=model_name,
                        controller=controller,
                        max_iterations=max_iterations,
                        max_tool_calls=max_tool_calls
                    )
                    agent.run(selected_tables, objective, run_id=pre_run_id)
                except Exception as exc:
                    db.log_event(pre_run_id, "ERROR", f"Investigation failed: {exc}")
                    db.update_run(pre_run_id, status="error", finished=True)

            thread = threading.Thread(target=worker, daemon=True)
            st.session_state.run_thread = thread
            thread.start()
            st.success("Investigation started. Refresh to see activity.")

        if col2.button("⏸ Pause", use_container_width=True):
            st.session_state.controller.pause()

        if col3.button("▶ Resume", use_container_width=True):
            st.session_state.controller.resume()

        if col4.button("■ Stop", use_container_width=True):
            st.session_state.controller.stop()

        run_id = st.session_state.run_id

        if run_id:
            st.markdown(f"**Investigation ID:** `{run_id}`")

            steering = st.text_input(
                "Human steering / hunch",
                placeholder=(
                    "Example: I suspect two workflows are duplicating work."
                )
            )
            if st.button("Inject steering") and steering.strip():
                db.add_steering(run_id, steering.strip())
                st.success("Steering queued for the next investigation cycle.")

            events = db.events(run_id)
            st.markdown("### Observable activity")
            for event in events[-100:]:
                payload = ""
                if event.get("payload"):
                    payload = f"  \n`{event['payload'][:1200]}`"
                st.markdown(
                    f"**[{event['event_type']}]** "
                    f"{event['message']}{payload}"
                )

            discoveries = db.discoveries(run_id)
            if discoveries:
                st.markdown("### Validated discoveries")
                for d in discoveries:
                    with st.expander(
                        f"🔍 {d['title']} · confidence {d['confidence']:.2f}"
                    ):
                        st.write(d["summary"])
                        if d["significance"]:
                            st.write(
                                "**Significance:**",
                                d["significance"]
                            )


with workspace_tab:
    st.subheader("3. Discovery Workspace")

    run_id = st.session_state.run_id
    if not run_id:
        st.info("Start an investigation first.")
    else:
        discoveries = db.discoveries(run_id)
        evidence = db.evidence(run_id)
        nodes, edges = db.graph(run_id)

        a, b, c, d = st.columns(4)
        a.metric("Discoveries", len(discoveries))
        b.metric("Evidence", len(evidence))
        c.metric("Graph nodes", len(nodes))
        d.metric("Graph edges", len(edges))

        st.markdown("### Discoveries")
        if discoveries:
            st.dataframe(
                discoveries, use_container_width=True, hide_index=True
            )
        else:
            st.info("No validated discoveries yet.")

        st.markdown("### Evidence")
        if evidence:
            st.dataframe(
                evidence, use_container_width=True, hide_index=True
            )
        else:
            st.info("No evidence persisted yet.")

        st.markdown("### Knowledge graph")
        if nodes:
            graph_html = build_graph_html(nodes, edges, height=600)
            components.html(graph_html, height=630, scrolling=False)
            with st.expander("Raw graph tables"):
                col_n, col_e = st.columns(2)
                with col_n:
                    st.caption(f"{len(nodes)} nodes")
                    st.dataframe(
                        nodes, use_container_width=True, hide_index=True
                    )
                with col_e:
                    st.caption(f"{len(edges)} edges")
                    st.dataframe(
                        edges, use_container_width=True, hide_index=True
                    )
        else:
            st.info(
                "The knowledge graph will appear here once the investigation "
                "validates its first discovery."
            )


with chat_tab:
    st.subheader("4. Chat With My Data")

    tables = db.table_names()
    if not tables:
        st.warning("Load data first.")
    else:
        chat_tables = st.multiselect(
            "Select tables for chat",
            tables,
            default=tables[:min(3, len(tables))],
            key="chat_tables"
        )

        for role, content in st.session_state.chat_history:
            with st.chat_message(role):
                st.markdown(content)

        question = st.chat_input("Ask a question about the selected data")

        if question:
            st.session_state.chat_history.append(("user", question))
            with st.chat_message("user"):
                st.markdown(question)

            with st.chat_message("assistant"):
                try:
                    with st.spinner("Analyzing data..."):
                        answer, _ = chat_with_data(
                            question=question,
                            tables=chat_tables,
                            endpoint=endpoint,
                            model=model_name,
                            history=[]
                        )
                    st.markdown(answer)
                    st.session_state.chat_history.append(
                        ("assistant", answer)
                    )
                except Exception as exc:
                    answer = f"Analysis failed: {exc}"
                    st.error(answer)
                    st.session_state.chat_history.append(
                        ("assistant", answer)
                    )


st.divider()
st.caption(
    "Core principle: LangGraph controls execution; it does not define the "
    "organizational story. The agent discovers that story from evidence."
)
