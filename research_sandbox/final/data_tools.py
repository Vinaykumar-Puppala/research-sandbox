import json
import math
import os
import re

import pandas as pd
from langchain_core.tools import tool


META_TABLES = {
    "ingestion_registry", "investigation_runs", "activity_events",
    "evidence", "discoveries", "graph_nodes", "graph_edges",
    "steering_messages"
}


def _db_path():
    return os.getenv("DISCOVERY_DB", "discovery_final.db")


def _conn():
    import sqlite3
    return sqlite3.connect(_db_path(), check_same_thread=False)


def _validate_table(table):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        raise ValueError("Invalid table identifier")
    if table in META_TABLES:
        raise ValueError("Metadata tables are not available")
    with _conn() as c:
        if not c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        ).fetchone():
            raise ValueError(f"Unknown table: {table}")


def _validate_sql(sql):
    s = sql.strip().lower()
    if not (s.startswith("select") or s.startswith("with") or s.startswith("pragma")):
        raise ValueError("Only read-only SELECT/WITH/PRAGMA SQL is allowed")
    forbidden = [
        "insert ", "update ", "delete ", "drop ", "alter ", "create ",
        "replace ", "attach ", "detach ", "vacuum ", "pragma writable_schema"
    ]
    if any(x in s for x in forbidden):
        raise ValueError("Mutating SQL is not allowed")
    if ";" in s.rstrip(";"):
        raise ValueError("Multiple SQL statements are not allowed")


@tool
def inspect_schema(table: str) -> str:
    """Inspect columns, types, row count and sample records for a data table."""
    _validate_table(table)
    with _conn() as c:
        info = c.execute(f'PRAGMA table_info("{table}")').fetchall()
        count = c.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        sample = c.execute(f'SELECT * FROM "{table}" LIMIT 5').fetchall()
        cols = [r[1] for r in info]
        rows = [dict(zip(cols, r)) for r in sample]
    return json.dumps({
        "table": table, "row_count": count,
        "columns": [{"name": r[1], "type": r[2]} for r in info],
        "sample": rows
    }, default=str)


@tool
def profile_table(table: str) -> str:
    """Profile missingness, cardinality, numeric summaries and top values."""
    _validate_table(table)
    with _conn() as c:
        df = pd.read_sql_query(f'SELECT * FROM "{table}" LIMIT 100000', c)

    result = {"table": table, "rows_analyzed": len(df), "columns": {}}
    for col in df.columns:
        s = df[col]
        item = {
            "dtype": str(s.dtype),
            "missing": int(s.isna().sum()),
            "missing_pct": round(float(s.isna().mean() * 100), 2) if len(s) else 0,
            "unique": int(s.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(s):
            item["numeric"] = {
                "min": float(s.min()) if s.notna().any() else None,
                "max": float(s.max()) if s.notna().any() else None,
                "mean": float(s.mean()) if s.notna().any() else None,
                "median": float(s.median()) if s.notna().any() else None,
            }
        else:
            item["top_values"] = s.astype(str).value_counts(
                dropna=False).head(10).to_dict()
        result["columns"][str(col)] = item
    return json.dumps(result, default=str)


@tool
def readonly_sql(sql: str) -> str:
    """Execute one read-only SQL query and return a capped result."""
    _validate_sql(sql)
    with _conn() as c:
        df = pd.read_sql_query(sql, c)
    df = df.head(200)
    return json.dumps({
        "columns": [str(c) for c in df.columns],
        "row_count_returned": len(df),
        "rows": df.to_dict(orient="records")
    }, default=str)


@tool
def descriptive_stats(table: str, numeric_columns: list) -> str:
    """Calculate descriptive statistics for numeric columns."""
    _validate_table(table)
    with _conn() as c:
        df = pd.read_sql_query(f'SELECT * FROM "{table}" LIMIT 100000', c)
    cols = [
        c for c in numeric_columns
        if c in df.columns and pd.api.types.is_numeric_dtype(df[c])
    ]
    if not cols:
        return json.dumps({"error": "No requested numeric columns exist"})
    stats = df[cols].describe().replace({math.nan: None}).to_dict()
    return json.dumps({"table": table, "statistics": stats}, default=str)


@tool
def value_distribution(table: str, column: str, top_n: int = 20) -> str:
    """Get top values, counts and shares for a column."""
    _validate_table(table)
    with _conn() as c:
        df = pd.read_sql_query(f'SELECT * FROM "{table}" LIMIT 100000', c)
    if column not in df.columns:
        return json.dumps({"error": f"Unknown column: {column}"})
    vc = df[column].value_counts(dropna=False).head(max(1, min(int(top_n), 100)))
    total = max(len(df), 1)
    return json.dumps({
        "table": table, "column": column,
        "distribution": [
            {
                "value": None if pd.isna(v) else v,
                "count": int(n),
                "share_pct": round(float(n / total * 100), 2)
            }
            for v, n in vc.items()
        ]
    }, default=str)


@tool
def correlations(table: str, numeric_columns: list) -> str:
    """Find strongest pairwise Pearson correlations."""
    _validate_table(table)
    with _conn() as c:
        df = pd.read_sql_query(f'SELECT * FROM "{table}" LIMIT 100000', c)
    cols = [
        c for c in numeric_columns
        if c in df.columns and pd.api.types.is_numeric_dtype(df[c])
    ]
    if len(cols) < 2:
        return json.dumps({"error": "At least two numeric columns required"})
    corr = df[cols].corr(numeric_only=True)
    pairs = []
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            value = corr.loc[a, b]
            if pd.notna(value):
                pairs.append({
                    "a": a, "b": b, "correlation": round(float(value), 4)
                })
    pairs.sort(key=lambda x: abs(x["correlation"]), reverse=True)
    return json.dumps({"table": table, "pairs": pairs[:30]}, default=str)


@tool
def compare_tables(table_a: str, table_b: str, join_sql: str) -> str:
    """Explore a cross-table relationship using one read-only JOIN query."""
    _validate_table(table_a)
    _validate_table(table_b)
    _validate_sql(join_sql)
    with _conn() as c:
        df = pd.read_sql_query(join_sql, c)
    return json.dumps({
        "tables": [table_a, table_b],
        "row_count_returned": len(df.head(200)),
        "rows": df.head(200).to_dict(orient="records")
    }, default=str)


@tool
def detect_anomalies(table: str, column: str, method: str = "iqr") -> str:
    """Detect outliers/anomalies in a numeric column using IQR or z-score method."""
    _validate_table(table)
    with _conn() as c:
        df = pd.read_sql_query(f'SELECT * FROM "{table}" LIMIT 100000', c)
    
    if column not in df.columns:
        return json.dumps({"error": f"Column not found: {column}"})
    if not pd.api.types.is_numeric_dtype(df[column]):
        return json.dumps({"error": f"Column must be numeric: {column}"})
    
    s = df[column].dropna()
    if len(s) == 0:
        return json.dumps({"error": "No numeric values in column"})
    
    anomalies = []
    if method == "iqr":
        Q1 = s.quantile(0.25)
        Q3 = s.quantile(0.75)
        IQR = Q3 - Q1
        lower = Q1 - 1.5 * IQR
        upper = Q3 + 1.5 * IQR
        mask = (df[column] < lower) | (df[column] > upper)
        anomalies = [
            {"value": float(v), "type": "outlier"} 
            for v in df[mask][column].head(50)
        ]
    else:  # z-score
        mean = s.mean()
        std = s.std()
        if std > 0:
            z_scores = ((s - mean) / std).abs()
            mask = z_scores > 3
            anomalies = [
                {"value": float(v), "z_score": float((v-mean)/std)} 
                for v in df[mask][column].head(50)
            ]
    
    return json.dumps({
        "table": table, "column": column, "method": method,
        "total_rows": len(df),
        "anomalies_found": len(anomalies),
        "anomalies": anomalies
    }, default=str)


@tool
def data_quality_score(table: str) -> str:
    """Score overall data quality of a table (completeness, duplicates, formats)."""
    _validate_table(table)
    with _conn() as c:
        df = pd.read_sql_query(f'SELECT * FROM "{table}" LIMIT 100000', c)
        
        total_rows = len(df)
        total_cells = df.size
        missing_cells = df.isna().sum().sum()
        duplicate_rows = df.duplicated().sum()
    
    completeness = round(((total_cells - missing_cells) / total_cells * 100), 2) if total_cells > 0 else 0
    duplicate_pct = round((duplicate_rows / total_rows * 100), 2) if total_rows > 0 else 0
    
    # Column-level quality
    col_quality = {}
    for col in df.columns:
        missing = int(df[col].isna().sum())
        unique = int(df[col].nunique())
        col_quality[str(col)] = {
            "completeness_pct": round(((total_rows - missing) / total_rows * 100), 2) if total_rows > 0 else 0,
            "cardinality": unique
        }
    
    # Overall score (0-100)
    score = min(100, (completeness * 0.7) + ((100 - duplicate_pct) * 0.3))
    
    return json.dumps({
        "table": table,
        "quality_score": round(score, 2),
        "total_rows": total_rows,
        "completeness_pct": completeness,
        "duplicate_rows": duplicate_rows,
        "duplicate_pct": duplicate_pct,
        "column_quality": col_quality
    }, default=str)


@tool
def temporal_analysis(table: str, time_column: str, value_column: str, interval: str = "auto") -> str:
    """Analyze temporal trends in a numeric value over time."""
    _validate_table(table)
    with _conn() as c:
        df = pd.read_sql_query(
            f'SELECT "{time_column}", "{value_column}" FROM "{table}" LIMIT 100000',
            c
        )
    
    if time_column not in df.columns or value_column not in df.columns:
        return json.dumps({"error": "Column(s) not found"})
    
    # Try to parse as datetime
    try:
        df[time_column] = pd.to_datetime(df[time_column])
    except Exception:
        return json.dumps({"error": "Time column cannot be parsed as datetime"})
    
    if not pd.api.types.is_numeric_dtype(df[value_column]):
        return json.dumps({"error": f"Value column must be numeric: {value_column}"})
    
    # Sort and drop NaN
    df = df.dropna().sort_values(time_column)
    
    if len(df) < 2:
        return json.dumps({"error": "Insufficient data for temporal analysis"})
    
    # Calculate trend
    trend = "stable"
    first_quarter = df[value_column].iloc[:len(df)//4].mean()
    last_quarter = df[value_column].iloc[-len(df)//4:].mean()
    change_pct = ((last_quarter - first_quarter) / first_quarter * 100) if first_quarter != 0 else 0
    
    if abs(change_pct) > 5:
        trend = "increasing" if change_pct > 0 else "decreasing"
    
    return json.dumps({
        "table": table,
        "time_column": time_column,
        "value_column": value_column,
        "period_start": str(df[time_column].min()),
        "period_end": str(df[time_column].max()),
        "data_points": len(df),
        "trend": trend,
        "first_quarter_avg": round(float(first_quarter), 4),
        "last_quarter_avg": round(float(last_quarter), 4),
        "percent_change": round(float(change_pct), 2),
        "min_value": float(df[value_column].min()),
        "max_value": float(df[value_column].max()),
        "current_value": float(df[value_column].iloc[-1])
    }, default=str)


TOOLS = [
    inspect_schema, profile_table, readonly_sql,
    descriptive_stats, value_distribution, correlations,
    compare_tables, detect_anomalies, data_quality_score,
    temporal_analysis
]


def openai_tool_schemas():
    return [{
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description,
            "parameters": t.args_schema.model_json_schema()
        }
    } for t in TOOLS]
