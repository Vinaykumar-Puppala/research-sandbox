import json
import re
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd


RESERVED = {
    "ingestion_registry", "investigation_runs", "activity_events",
    "evidence", "discoveries", "graph_nodes", "graph_edges",
    "steering_messages"
}


def safe_identifier(value):
    value = re.sub(r"[^A-Za-z0-9_]+", "_", str(value).strip())
    value = re.sub(r"_+", "_", value).strip("_")
    value = value or "table"
    if value[0].isdigit():
        value = "t_" + value
    return value.lower()


def unique_table_name(conn, base):
    base = safe_identifier(base)
    candidate = base
    i = 2
    while candidate in RESERVED or conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (candidate,)
    ).fetchone():
        candidate = f"{base}_{i}"
        i += 1
    return candidate


class FileIngestionService:
    SUPPORTED = [".csv", ".xlsx", ".xls", ".parquet",
                 ".json", ".jsonl", ".ndjson"]

    def inspect_excel(self, path):
        return pd.ExcelFile(path).sheet_names

    def load(self, path, sheet_name: Optional[str] = None):
        ext = Path(path).suffix.lower()
        if ext == ".csv":
            return pd.read_csv(path)
        if ext in {".xlsx", ".xls"}:
            return pd.read_excel(path, sheet_name=sheet_name or 0)
        if ext == ".parquet":
            return pd.read_parquet(path)
        if ext == ".json":
            try:
                return pd.read_json(path)
            except ValueError:
                with open(path, "r", encoding="utf-8") as f:
                    return pd.DataFrame(json.load(f))
        if ext in {".jsonl", ".ndjson"}:
            return pd.read_json(path, lines=True)
        raise ValueError(f"Unsupported file type: {ext}")

    def write_sqlite(self, conn, df, preferred_name):
        out = df.copy()
        cols = []
        seen = {}
        for i, col in enumerate(out.columns):
            c = safe_identifier(col) or f"column_{i}"
            n = seen.get(c, 0)
            seen[c] = n + 1
            cols.append(c if n == 0 else f"{c}_{n+1}")
        out.columns = cols
        table = unique_table_name(conn, preferred_name)
        out.to_sql(table, conn, if_exists="fail", index=False)
        return table
