"""Pydantic schemas for the FastAPI endpoints."""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=1000,
                          description="Natural-language banking question")
    mode: str = Field("rag", pattern="^(rag|baseline)$")
    use_cache: bool = True


class AttemptOut(BaseModel):
    safety_ok: bool
    safety_stage: Optional[str] = None
    safety_reason: Optional[str] = None
    exec_ok: Optional[bool] = None
    exec_error: Optional[str] = None
    elapsed_ms: int


class Explainability(BaseModel):
    retrieved_tables: list[str]
    retrieved_examples: list[str]
    attempts: list[AttemptOut]
    attempt_count: int
    cache_hit: bool
    hallucination_detected: bool
    mode: str


class QueryResponse(BaseModel):
    success: bool
    sql: Optional[str] = None
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
    row_count: int = 0
    truncated: bool = False
    error: Optional[str] = None
    error_kind: Optional[str] = None
    latency_ms: int
    explainability: Explainability


class TableSchema(BaseModel):
    table: str
    columns: list[str]


class SchemaResponse(BaseModel):
    tables: list[TableSchema]


class HealthResponse(BaseModel):
    status: str
    db: str
    chroma: str
    cache_size: int
