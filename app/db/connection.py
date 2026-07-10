"""
SQLAlchemy engine + helpers for executing generated SQL safely.

Belt-and-braces with the AST guard:
- statement_timeout (postgres-side cancellation)
- default_transaction_read_only (postgres-side write block)
- result row cap
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings


# -------------------------------------------------------------
_engine: Engine | None = None
MAX_RESULT_ROWS = 500


def get_engine() -> Engine:
    """Singleton engine with safety pragmas applied per-connection."""
    global _engine
    if _engine is not None:
        return _engine

    _engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        future=True,
    )

    @event.listens_for(_engine, "connect")
    def _set_session_defaults(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        # Statement timeout — kills anything over budget at the postgres layer.
        cur.execute(f"SET statement_timeout = '{settings.query_timeout_seconds}s'")
        # Force read-only at the session level too.
        cur.execute("SET default_transaction_read_only = on")
        cur.close()

    return _engine


# -------------------------------------------------------------
@contextmanager
def ro_connection():
    eng = get_engine()
    with eng.connect() as conn:
        # Explicit read-only transaction (redundant w/ session default, but defensive).
        conn.execute(text("SET TRANSACTION READ ONLY"))
        yield conn


# -------------------------------------------------------------
def execute_select(sql: str) -> dict[str, Any]:
    """
    Run a SELECT and return rows + timing.
    Caller must have validated the SQL with safety.validate() first.
    """
    t0 = time.perf_counter()
    try:
        with ro_connection() as conn:
            df = pd.read_sql(text(sql), conn)
    except SQLAlchemyError as e:
        return {
            "ok": False,
            "error": _clean_error(e),
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        }

    truncated = False
    if len(df) > MAX_RESULT_ROWS:
        df = df.head(MAX_RESULT_ROWS)
        truncated = True

    return {
        "ok": True,
        "columns": list(df.columns),
        "rows": df.to_dict(orient="records"),
        "row_count": len(df),
        "truncated": truncated,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }


def _clean_error(e: SQLAlchemyError) -> str:
    """Strip the noisier SQLAlchemy wrapper so the LLM sees just the postgres message."""
    msg = str(getattr(e, "orig", e))
    # Trim multi-line postgres errors to the first 2 useful lines.
    lines = [ln for ln in msg.splitlines() if ln.strip()][:3]
    return " | ".join(lines)


# -------------------------------------------------------------
def live_schema() -> dict[str, list[str]]:
    """
    Pull {table: [columns]} from information_schema. Used by the safety layer
    for hallucination detection (column existence check). Cached per-process.
    """
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is not None:
        return _SCHEMA_CACHE

    sql = """
    SELECT table_name, column_name
    FROM information_schema.columns
    WHERE table_schema = 'public'
    ORDER BY table_name, ordinal_position
    """
    with get_engine().connect() as conn:
        rows = conn.execute(text(sql)).fetchall()

    schema: dict[str, list[str]] = {}
    for tbl, col in rows:
        schema.setdefault(tbl, []).append(col)

    _SCHEMA_CACHE = schema
    return schema


_SCHEMA_CACHE: dict[str, list[str]] | None = None
