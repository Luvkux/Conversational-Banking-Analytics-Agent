"""
Agent runner — orchestrates retrieve → generate → validate → execute → retry.

Public API
----------
    run(question)                                  # backward-compat (defaults: rag, cached)
    run(question, mode="rag", use_cache=True)
    run(question, mode="baseline", use_cache=False)

Modes
-----
    rag        : top-k schema docs + top-k few-shots from ChromaDB (default)
    baseline   : full static schema, ZERO few-shots, NO retrieval at all
                 (used by the eval harness to measure RAG lift)

Baseline isolation: the retriever (and therefore ChromaDB) is imported
LAZILY inside the rag branch. Baseline mode never touches Chroma.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Literal, Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.agent.cache import CachedGeneration, get_cache
from app.agent.entity_guard import check as entity_check
from app.agent.prompt import build_prompt
from app.agent.safety import validate
from app.config import settings
from app.db.connection import execute_select
from app.rag.schema_docs import all_docs as all_schema_docs


log = logging.getLogger(__name__)
Mode = Literal["rag", "baseline"]
VALID_MODES = ("rag", "baseline")


# -------------------------------------------------------------
# LLM (lazy)
# -------------------------------------------------------------
_llm: Optional[ChatOpenAI] = None


def get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0,
            timeout=30,
        )
    return _llm


# -------------------------------------------------------------
@dataclass
class Attempt:
    sql_raw: str
    sql_cleaned: Optional[str]
    safety_ok: bool
    safety_reason: Optional[str]
    safety_stage: Optional[str]
    exec_ok: Optional[bool]
    exec_error: Optional[str]
    elapsed_ms: int


@dataclass
class AgentResult:
    question: str
    success: bool
    sql: Optional[str]
    columns: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    error: Optional[str] = None
    error_kind: Optional[str] = None
    attempts: list[Attempt] = field(default_factory=list)
    total_elapsed_ms: int = 0
    retrieved_tables: list[str] = field(default_factory=list)
    retrieved_examples: list[str] = field(default_factory=list)
    cache_hit: bool = False
    hallucination_detected: bool = False
    mode: str = "rag"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# -------------------------------------------------------------
SQL_FENCE_RE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_sql(text: str) -> str:
    m = SQL_FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def _llm_call(system: str, user: str) -> str:
    prompt = ChatPromptTemplate.from_messages([
        ("system", system),
        ("human", "{user}"),
    ])
    chain = prompt | get_llm() | StrOutputParser()
    return chain.invoke({"user": user})


# -------------------------------------------------------------
def _retrieve(question: str, mode: Mode):
    """
    Returns (schema_hits, fewshot_hits).

    - baseline → static schema dump, ZERO few-shots, no Chroma/embedding calls
    - rag      → embedding-based top-k retrieval against ChromaDB
    """
    if mode == "baseline":
        from app.agent.retriever import SchemaHit  # local import — cheap
        docs = all_schema_docs()
        return [SchemaHit(table=d.table, doc=d.doc, score=1.0) for d in docs], []

    # rag path — import lazily so baseline mode has no Chroma hard dep
    from app.agent.retriever import get_retriever
    r = get_retriever()
    return r.retrieve_schema(question), r.retrieve_few_shots(question)


# -------------------------------------------------------------
def run(question: str, mode: Mode = "rag", use_cache: bool = True) -> AgentResult:
    """
    Entry point. Returns AgentResult.

    Backward compatibility: `run(q)` still works — `mode` and `use_cache`
    have safe defaults.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {VALID_MODES!r}, got {mode!r}")

    t_total = time.perf_counter()
    result = AgentResult(question=question, success=False, sql=None, mode=mode)

    # ---- 0. Entity guard --------------------------------------------
    eg = entity_check(question)
    if not eg.ok:
        result.error = eg.message
        result.error_kind = "entity_guard"
        result.total_elapsed_ms = int((time.perf_counter() - t_total) * 1000)
        log.info("entity_guard rejected: %s", eg.matched)
        return result

    # ---- 1. Cache hit? ----------------------------------------------
    cache = get_cache()
    cached: CachedGeneration | None = cache.get(question, mode) if use_cache else None
    if cached is not None:
        sr = validate(cached.sql)
        if sr.ok:
            ex = execute_select(sr.sql)
            if ex["ok"]:
                result.success = True
                result.sql = sr.sql
                result.columns = ex["columns"]
                result.rows = ex["rows"]
                result.row_count = ex["row_count"]
                result.truncated = ex["truncated"]
                result.retrieved_tables = list(cached.retrieved_tables)
                result.retrieved_examples = list(cached.retrieved_examples)
                result.cache_hit = True
                result.attempts.append(Attempt(
                    sql_raw=cached.sql, sql_cleaned=sr.sql,
                    safety_ok=True, safety_reason=None, safety_stage=None,
                    exec_ok=True, exec_error=None,
                    elapsed_ms=ex["elapsed_ms"],
                ))
                result.total_elapsed_ms = int((time.perf_counter() - t_total) * 1000)
                return result

    # ---- 2. Retrieval -----------------------------------------------
    schema_hits, fs_hits = _retrieve(question, mode)
    result.retrieved_tables = [h.table for h in schema_hits]
    result.retrieved_examples = [h.question for h in fs_hits]

    # ---- 3-6. Generate + validate + execute, with retry ------------
    retry_ctx: tuple[str, str] | None = None
    last_error = "unknown error"
    last_kind: str | None = None

    for attempt_idx in range(settings.max_retries + 1):
        t_attempt = time.perf_counter()
        bundle = build_prompt(question, schema_hits, fs_hits, retry_ctx)

        raw = _llm_call(bundle.system, bundle.user)
        sql_raw = _extract_sql(raw)

        sr = validate(sql_raw)
        if not sr.ok:
            ms = int((time.perf_counter() - t_attempt) * 1000)
            result.attempts.append(Attempt(
                sql_raw=sql_raw, sql_cleaned=None,
                safety_ok=False, safety_reason=sr.reason, safety_stage=sr.stage,
                exec_ok=None, exec_error=None, elapsed_ms=ms,
            ))
            if sr.stage == "schema":
                result.hallucination_detected = True
            last_error = f"[safety/{sr.stage}] {sr.reason}"
            last_kind = "safety"
            log.warning("attempt %d safety failed: %s", attempt_idx + 1, last_error)
            retry_ctx = (sql_raw, last_error)
            continue

        ex = execute_select(sr.sql)
        ms = int((time.perf_counter() - t_attempt) * 1000)

        if ex["ok"]:
            result.attempts.append(Attempt(
                sql_raw=sql_raw, sql_cleaned=sr.sql,
                safety_ok=True, safety_reason=None, safety_stage=None,
                exec_ok=True, exec_error=None, elapsed_ms=ms,
            ))
            result.success = True
            result.sql = sr.sql
            result.columns = ex["columns"]
            result.rows = ex["rows"]
            result.row_count = ex["row_count"]
            result.truncated = ex["truncated"]
            if use_cache:
                cache.put(question, CachedGeneration(
                    sql=sr.sql,
                    retrieved_tables=tuple(result.retrieved_tables),
                    retrieved_examples=tuple(result.retrieved_examples),
                    attempts=len(result.attempts),
                ), mode)
            break

        result.attempts.append(Attempt(
            sql_raw=sql_raw, sql_cleaned=sr.sql,
            safety_ok=True, safety_reason=None, safety_stage=None,
            exec_ok=False, exec_error=ex["error"], elapsed_ms=ms,
        ))
        last_error = f"[execution] {ex['error']}"
        last_kind = "execution"
        log.warning("attempt %d exec failed: %s", attempt_idx + 1, last_error)
        retry_ctx = (sr.sql, ex["error"])

    if not result.success:
        result.error = last_error
        result.error_kind = last_kind

    result.total_elapsed_ms = int((time.perf_counter() - t_total) * 1000)
    return result
