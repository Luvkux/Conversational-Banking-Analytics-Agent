"""
Tests for the agent runner.

Two things this file proves:
  1. SIGNATURE CONTRACT — `run(q)`, `run(q, mode=...)`, `run(q, use_cache=...)`
     all work. This catches the "got unexpected keyword argument 'mode'" bug.
  2. MODE DISPATCH    — baseline mode does NOT call the Chroma retriever;
     rag mode DOES.

External deps (OpenAI, Postgres, Chroma) are mocked so tests run offline.
"""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest

from app.agent import runner
from app.agent.runner import AgentResult, run


# =============================================================
# 1. SIGNATURE CONTRACT
# =============================================================
def test_signature_has_required_params():
    sig = inspect.signature(run)
    assert "question" in sig.parameters
    assert "mode" in sig.parameters
    assert "use_cache" in sig.parameters


def test_signature_defaults():
    sig = inspect.signature(run)
    assert sig.parameters["mode"].default == "rag"
    assert sig.parameters["use_cache"].default is True


def test_backward_compat_positional_question_only():
    """`run(q)` must not raise — defaults cover the rest."""
    sig = inspect.signature(run)
    sig.bind("how many customers")    # raises TypeError if signature is broken


def test_accepts_mode_kwarg():
    sig = inspect.signature(run)
    sig.bind("q", mode="rag")
    sig.bind("q", mode="baseline")


def test_accepts_use_cache_kwarg():
    sig = inspect.signature(run)
    sig.bind("q", use_cache=True)
    sig.bind("q", use_cache=False)


def test_accepts_both_kwargs_together():
    sig = inspect.signature(run)
    sig.bind("q", mode="baseline", use_cache=False)


def test_invalid_mode_rejected(monkeypatch):
    """Defensive: passing an invalid mode raises ValueError, not a silent fall-through."""
    with pytest.raises(ValueError):
        run("how many customers", mode="totally_invalid")  # type: ignore[arg-type]


# =============================================================
# 2. MODE DISPATCH (with mocks)
# =============================================================
def _install_mocks(monkeypatch, llm_sql: str = "SELECT 1 FROM customers"):
    """Patch external deps so run() executes end-to-end without OpenAI/DB/Chroma."""
    from app.agent import entity_guard as _eg
    from app.agent import safety as _safety

    # Bypass entity guard
    monkeypatch.setattr(runner, "entity_check",
                        lambda q: _eg.EntityGuardResult(ok=True, matched=[]))

    # Mock LLM
    monkeypatch.setattr(runner, "_llm_call", lambda system, user: llm_sql)

    # Mock DB execution (called both by runner directly AND inside cache replay)
    monkeypatch.setattr(runner, "execute_select", lambda sql: {
        "ok": True, "columns": ["x"], "rows": [{"x": 1}],
        "row_count": 1, "truncated": False, "elapsed_ms": 5,
    })

    # Safety guard needs a schema to validate against
    monkeypatch.setattr(_safety, "live_schema",
                        lambda: {"customers": ["customer_id", "full_name"]})

    # Fresh cache for each test
    runner.get_cache().clear()


def test_baseline_does_not_call_retriever(monkeypatch):
    _install_mocks(monkeypatch)

    # Replace the lazy import target. The runner does:
    #     from app.agent.retriever import get_retriever
    # inside `_retrieve` only on the rag branch. We patch the module so
    # if baseline accidentally took the rag branch, this would crash loudly.
    import app.agent.retriever as retriever_mod
    sentinel = MagicMock(side_effect=AssertionError(
        "baseline mode must not call get_retriever()"
    ))
    monkeypatch.setattr(retriever_mod, "get_retriever", sentinel)

    result = run("how many customers", mode="baseline", use_cache=False)

    assert isinstance(result, AgentResult)
    assert result.mode == "baseline"
    assert result.success is True
    sentinel.assert_not_called()
    # Baseline gets ALL schema tables (12 of them) and ZERO few-shots
    assert len(result.retrieved_tables) == 12
    assert result.retrieved_examples == []


def test_rag_calls_retriever(monkeypatch):
    _install_mocks(monkeypatch)

    import app.agent.retriever as retriever_mod
    fake = MagicMock()
    fake.retrieve_schema.return_value = []
    fake.retrieve_few_shots.return_value = []
    monkeypatch.setattr(retriever_mod, "get_retriever", lambda: fake)

    result = run("how many customers", mode="rag", use_cache=False)

    assert isinstance(result, AgentResult)
    assert result.mode == "rag"
    fake.retrieve_schema.assert_called_once()
    fake.retrieve_few_shots.assert_called_once()


def test_backward_compat_run_q_only(monkeypatch):
    """`run(q)` with no kwargs defaults to rag mode and executes."""
    _install_mocks(monkeypatch)
    import app.agent.retriever as retriever_mod
    fake = MagicMock()
    fake.retrieve_schema.return_value = []
    fake.retrieve_few_shots.return_value = []
    monkeypatch.setattr(retriever_mod, "get_retriever", lambda: fake)

    result = run("how many customers")     # ← the call shape that used to break

    assert isinstance(result, AgentResult)
    assert result.mode == "rag"
    assert result.success is True


def test_entity_guard_blocks_before_any_mode(monkeypatch):
    """Forbidden entities reject BEFORE retrieval, in both modes."""
    _install_mocks(monkeypatch)
    import app.agent.retriever as retriever_mod

    # Restore real entity guard
    from app.agent.entity_guard import check
    monkeypatch.setattr(runner, "entity_check", check)

    sentinel = MagicMock()
    monkeypatch.setattr(retriever_mod, "get_retriever", sentinel)

    for mode in ("rag", "baseline"):
        result = run("find customers by linkedin profile", mode=mode, use_cache=False)
        assert result.success is False
        assert result.error_kind == "entity_guard"
        sentinel.assert_not_called()
