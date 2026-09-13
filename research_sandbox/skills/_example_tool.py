"""
Example skill tool — copy this file, rename it without the leading underscore,
and replace the function body with your own analytics logic.

This file is NOT auto-loaded (underscore prefix).
"""
import json
import os
import sqlite3

from langchain_core.tools import tool


@tool
def top_n_by_column(table: str, rank_column: str, n: int = 10) -> str:
    """Return the top N rows of a table ranked by a numeric column (descending).

    Args:
        table: Name of the SQLite table to query.
        rank_column: Numeric column to rank by.
        n: Number of rows to return (default 10, max 50).
    """
    n = max(1, min(int(n), 50))
    db = os.getenv("DISCOVERY_DB", "discovery_final.db")
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f'SELECT * FROM "{table}" ORDER BY "{rank_column}" DESC LIMIT ?', (n,)
        ).fetchall()
    return json.dumps({"table": table, "rank_column": rank_column,
                       "rows": [dict(r) for r in rows]}, default=str)
