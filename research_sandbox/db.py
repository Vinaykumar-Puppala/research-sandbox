import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


META_TABLES = {
    "ingestion_registry", "investigation_runs", "activity_events",
    "evidence", "discoveries", "graph_nodes", "graph_edges",
    "steering_messages"
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path):
        self.path = str(Path(path))
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.init_meta()

    def connect(self):
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def init_meta(self):
        with self._lock, self.connect() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS ingestion_registry (
                id TEXT PRIMARY KEY,
                source_name TEXT NOT NULL,
                source_type TEXT NOT NULL,
                table_name TEXT NOT NULL,
                sheet_name TEXT,
                row_count INTEGER,
                column_count INTEGER,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS investigation_runs (
                run_id TEXT PRIMARY KEY,
                table_names TEXT NOT NULL,
                objective TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                iterations INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS activity_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                payload TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evidence (
                evidence_id TEXT PRIMARY KEY,
                run_id TEXT,
                title TEXT NOT NULL,
                finding TEXT NOT NULL,
                source TEXT,
                query TEXT,
                data_json TEXT,
                confidence REAL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS discoveries (
                discovery_id TEXT PRIMARY KEY,
                run_id TEXT,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                significance TEXT,
                confidence REAL,
                evidence_ids TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS graph_nodes (
                node_id TEXT PRIMARY KEY,
                run_id TEXT,
                node_type TEXT NOT NULL,
                label TEXT NOT NULL,
                properties TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS graph_edges (
                edge_id TEXT PRIMARY KEY,
                run_id TEXT,
                source_node TEXT NOT NULL,
                target_node TEXT NOT NULL,
                relation TEXT NOT NULL,
                evidence_id TEXT,
                properties TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS steering_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                message TEXT NOT NULL,
                consumed INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """)

    def table_names(self):
        with self._lock, self.connect() as c:
            rows = c.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                AND name NOT IN (
                    'ingestion_registry','investigation_runs','activity_events',
                    'evidence','discoveries','graph_nodes','graph_edges',
                    'steering_messages'
                )
                ORDER BY name
            """).fetchall()
            return [r["name"] for r in rows]

    def register_ingestion(self, source_name, source_type, table_name,
                           sheet_name, row_count, column_count):
        with self._lock, self.connect() as c:
            c.execute(
                """INSERT INTO ingestion_registry
                VALUES (?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), source_name, source_type, table_name,
                 sheet_name, int(row_count), int(column_count), utc_now())
            )

    def registry(self):
        with self._lock, self.connect() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM ingestion_registry ORDER BY created_at DESC"
            ).fetchall()]

    def start_run(self, tables, objective, run_id: str | None = None):
        if run_id is None:
            run_id = str(uuid.uuid4())
        with self._lock, self.connect() as c:
            c.execute(
                """INSERT INTO investigation_runs
                VALUES (?,?,?,?,?,?,?)""",
                (run_id, json.dumps(tables), objective, "running",
                 utc_now(), None, 0)
            )
        return run_id

    def update_run(self, run_id, status=None, iterations=None, finished=False):
        with self._lock, self.connect() as c:
            sets, vals = [], []
            if status is not None:
                sets.append("status=?"); vals.append(status)
            if iterations is not None:
                sets.append("iterations=?"); vals.append(iterations)
            if finished:
                sets.append("finished_at=?"); vals.append(utc_now())
            if sets:
                vals.append(run_id)
                c.execute(
                    f"UPDATE investigation_runs SET {','.join(sets)} WHERE run_id=?",
                    vals
                )

    def log_event(self, run_id, event_type, message, payload=None):
        with self._lock, self.connect() as c:
            c.execute(
                """INSERT INTO activity_events
                (run_id,event_type,message,payload,created_at)
                VALUES (?,?,?,?,?)""",
                (run_id, event_type, message,
                 json.dumps(payload, default=str) if payload is not None else None,
                 utc_now())
            )

    def events(self, run_id, limit=300):
        with self._lock, self.connect() as c:
            rows = c.execute(
                """SELECT * FROM activity_events
                WHERE run_id=? ORDER BY id DESC LIMIT ?""",
                (run_id, limit)
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def add_evidence(self, run_id, title, finding, source="",
                     query="", data=None, confidence=0.5):
        evidence_id = str(uuid.uuid4())
        with self._lock, self.connect() as c:
            c.execute(
                """INSERT INTO evidence
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (evidence_id, run_id, title, finding, source, query,
                 json.dumps(data, default=str) if data is not None else None,
                 float(confidence), utc_now())
            )
        return evidence_id

    def evidence(self, run_id, limit=200):
        with self._lock, self.connect() as c:
            return [dict(r) for r in c.execute(
                """SELECT * FROM evidence WHERE run_id=?
                ORDER BY created_at DESC LIMIT ?""", (run_id, limit)
            ).fetchall()]

    def add_discovery(self, run_id, title, summary, significance="",
                      confidence=0.5, evidence_ids=None):
        discovery_id = str(uuid.uuid4())
        with self._lock, self.connect() as c:
            c.execute(
                """INSERT INTO discoveries
                VALUES (?,?,?,?,?,?,?,?)""",
                (discovery_id, run_id, title, summary, significance,
                 float(confidence), json.dumps(evidence_ids or []), utc_now())
            )
        return discovery_id

    def discoveries(self, run_id, limit=100):
        with self._lock, self.connect() as c:
            return [dict(r) for r in c.execute(
                """SELECT * FROM discoveries WHERE run_id=?
                ORDER BY created_at DESC LIMIT ?""", (run_id, limit)
            ).fetchall()]

    def add_node(self, run_id, node_type, label, properties=None):
        node_id = f"{run_id}:{node_type}:{label}".lower()
        with self._lock, self.connect() as c:
            c.execute(
                """INSERT OR IGNORE INTO graph_nodes
                VALUES (?,?,?,?,?,?)""",
                (node_id, run_id, node_type, label,
                 json.dumps(properties or {}, default=str), utc_now())
            )
        return node_id

    def add_edge(self, run_id, source_node, target_node, relation,
                 evidence_id=None, properties=None):
        edge_id = str(uuid.uuid4())
        with self._lock, self.connect() as c:
            c.execute(
                """INSERT INTO graph_edges
                VALUES (?,?,?,?,?,?,?,?)""",
                (edge_id, run_id, source_node, target_node, relation,
                 evidence_id, json.dumps(properties or {}, default=str),
                 utc_now())
            )
        return edge_id

    def graph(self, run_id):
        with self._lock, self.connect() as c:
            nodes = [dict(r) for r in c.execute(
                "SELECT * FROM graph_nodes WHERE run_id=?", (run_id,)
            ).fetchall()]
            edges = [dict(r) for r in c.execute(
                "SELECT * FROM graph_edges WHERE run_id=?", (run_id,)
            ).fetchall()]
            return nodes, edges

    def add_steering(self, run_id, message):
        with self._lock, self.connect() as c:
            c.execute(
                """INSERT INTO steering_messages
                (run_id,message,created_at) VALUES (?,?,?)""",
                (run_id, message, utc_now())
            )

    def consume_steering(self, run_id):
        with self._lock, self.connect() as c:
            rows = c.execute(
                """SELECT id,message FROM steering_messages
                WHERE run_id=? AND consumed=0 ORDER BY id""",
                (run_id,)
            ).fetchall()
            if rows:
                c.executemany(
                    "UPDATE steering_messages SET consumed=1 WHERE id=?",
                    [(r["id"],) for r in rows]
                )
            return [r["message"] for r in rows]
