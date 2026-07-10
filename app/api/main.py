"""
FastAPI app — production interface for the Text-to-SQL agent.

Endpoints:
  POST /query    — natural language → SQL + results + explainability
  GET  /schema   — list tables and columns
  GET  /health   — db, chroma, and cache status
"""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.agent.cache import get_cache
from app.agent.runner import run as run_agent
from app.api.schemas import (
    AttemptOut, Explainability, HealthResponse, QueryRequest, QueryResponse,
    SchemaResponse, TableSchema,
)
from app.db.connection import get_engine, live_schema


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("banking-agent.api")


app = FastAPI(
    title="Banking Analytics Agent",
    description="Natural-language → SQL agent over a 12-table banking warehouse.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------------------------------------
@app.middleware("http")
async def request_logger(request: Request, call_next):
    req_id = uuid.uuid4().hex[:8]
    t0 = time.perf_counter()
    log.info("req=%s %s %s", req_id, request.method, request.url.path)
    response = await call_next(request)
    ms = int((time.perf_counter() - t0) * 1000)
    log.info("req=%s status=%d %dms", req_id, response.status_code, ms)
    response.headers["X-Request-ID"] = req_id
    return response


# -------------------------------------------------------------
@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question must be non-empty")

    result = run_agent(req.question, mode=req.mode, use_cache=req.use_cache)

    return QueryResponse(
        success=result.success,
        sql=result.sql,
        columns=result.columns,
        rows=result.rows,
        row_count=result.row_count,
        truncated=result.truncated,
        error=result.error,
        error_kind=result.error_kind,
        latency_ms=result.total_elapsed_ms,
        explainability=Explainability(
            retrieved_tables=result.retrieved_tables,
            retrieved_examples=result.retrieved_examples,
            attempts=[
                AttemptOut(
                    safety_ok=a.safety_ok, safety_stage=a.safety_stage,
                    safety_reason=a.safety_reason, exec_ok=a.exec_ok,
                    exec_error=a.exec_error, elapsed_ms=a.elapsed_ms,
                )
                for a in result.attempts
            ],
            attempt_count=len(result.attempts),
            cache_hit=result.cache_hit,
            hallucination_detected=result.hallucination_detected,
            mode=result.mode,
        ),
    )


@app.get("/schema", response_model=SchemaResponse)
async def schema():
    s = live_schema()
    return SchemaResponse(
        tables=[TableSchema(table=t, columns=cols) for t, cols in sorted(s.items())]
    )


@app.get("/health", response_model=HealthResponse)
async def health():
    # DB ping
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"

    # Chroma ping
    try:
        from app.agent.retriever import get_retriever
        get_retriever()._client.heartbeat()
        chroma_status = "ok"
    except Exception as e:
        chroma_status = f"error: {e}"

    return HealthResponse(
        status="ok" if db_status == "ok" and chroma_status == "ok" else "degraded",
        db=db_status,
        chroma=chroma_status,
        cache_size=get_cache().stats()["size"],
    )
