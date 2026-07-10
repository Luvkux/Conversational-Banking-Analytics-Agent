"""
Benchmark runner.

Runs every question in `evals/benchmark.json` through the agent and computes:
  - exact_match    : normalized SQL string equality with gold
  - exec_match     : result sets equal (after sorting + numeric tolerance)
  - latency_ms     : end-to-end per question
  - retried        : true if >1 attempt was needed
  - hallucinated   : true if at least one attempt failed schema validation
  - error_kind     : entity_guard / safety / execution / None

Run modes:
  - rag       : full RAG pipeline (default)
  - baseline  : all-schema dump, no few-shots — the "before" number

Usage:
  python -m evals.runner                    # 100 Qs in rag mode
  python -m evals.runner --mode baseline
  python -m evals.runner --limit 20         # smoke test
  python -m evals.runner --both             # rag + baseline, side-by-side
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import time
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from app.agent.runner import run
from app.db.connection import execute_select


BENCH_PATH = Path(__file__).parent / "benchmark.json"
RESULTS_DIR = Path(__file__).parent / "results"


# -------------------------------------------------------------
def _normalize_sql(sql: str) -> str:
    """Collapse whitespace, lowercase, strip trailing punctuation."""
    if not sql:
        return ""
    s = sql.lower().strip().rstrip(";")
    s = re.sub(r"\s+", " ", s)
    return s


def _exec_match(pred_sql: str, gold_sql: str, tol: float = 0.01) -> bool:
    """
    Execute both, compare row sets.
    Numeric columns compared with relative tolerance to absorb ROUND() etc.
    """
    p = execute_select(pred_sql)
    g = execute_select(gold_sql)
    if not p["ok"] or not g["ok"]:
        return False
    if abs(len(p["rows"]) - len(g["rows"])) > 0:
        return False

    df_p = pd.DataFrame(p["rows"])
    df_g = pd.DataFrame(g["rows"])

    if df_p.empty and df_g.empty:
        return True
    if df_p.shape != df_g.shape:
        return False

    # Try to align by sorting on all columns (handles ORDER BY mismatch
    # for queries where order isn't specified).
    try:
        # Sort by string-cast every column for stability
        df_p = df_p.astype(str).sort_values(by=list(df_p.columns)).reset_index(drop=True)
        df_g = df_g.astype(str).sort_values(by=list(df_g.columns)).reset_index(drop=True)
    except Exception:
        pass

    # Compare cell-by-cell, allowing tolerance on numeric-looking strings.
    for col_p, col_g in zip(df_p.columns, df_g.columns):
        for v_p, v_g in zip(df_p[col_p], df_g[col_g]):
            if v_p == v_g:
                continue
            try:
                f_p, f_g = float(v_p), float(v_g)
                if abs(f_p - f_g) <= tol * max(1.0, abs(f_g)):
                    continue
            except (ValueError, TypeError):
                pass
            return False
    return True


# -------------------------------------------------------------
def _summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records)
    if n == 0:
        return {"n": 0}

    exec_ok = [r for r in records if r["exec_match"]]
    exact_ok = [r for r in records if r["exact_match"]]
    latencies = [r["latency_ms"] for r in records]
    retried = [r for r in records if r["retried"]]
    hallucinated = [r for r in records if r["hallucinated"]]
    entity_blocked = [r for r in records if r["error_kind"] == "entity_guard"]

    p50 = statistics.median(latencies)
    p95 = sorted(latencies)[max(0, int(0.95 * n) - 1)]

    return {
        "n": n,
        "exact_match_pct": round(100 * len(exact_ok) / n, 2),
        "exec_accuracy_pct": round(100 * len(exec_ok) / n, 2),
        "retry_pct": round(100 * len(retried) / n, 2),
        "hallucination_pct": round(100 * len(hallucinated) / n, 2),
        "entity_blocked_pct": round(100 * len(entity_blocked) / n, 2),
        "latency_p50_ms": int(p50),
        "latency_p95_ms": int(p95),
        "latency_mean_ms": int(statistics.mean(latencies)),
    }


# -------------------------------------------------------------
def _run_mode(benchmark: Iterable[dict], mode: str, limit: int | None) -> list[dict]:
    records: list[dict[str, Any]] = []
    items = list(benchmark)
    if limit:
        items = items[:limit]

    for i, item in enumerate(items, 1):
        q = item["question"]
        gold_sql = item["gold_sql"]
        print(f"  [{mode}] {i:>3}/{len(items)}  {item['id']}  {q[:70]}...", flush=True)

        t0 = time.perf_counter()
        # Bypass cache during evals so we measure actual generation latency
        res = run(q, mode=mode, use_cache=False)
        elapsed = int((time.perf_counter() - t0) * 1000)

        pred_sql = res.sql or ""
        exact = _normalize_sql(pred_sql) == _normalize_sql(gold_sql)
        exec_ok = False
        if res.success and pred_sql:
            try:
                exec_ok = _exec_match(pred_sql, gold_sql)
            except Exception as e:
                print(f"      exec-match error: {e}")

        records.append({
            "id": item["id"],
            "category": item["category"],
            "question": q,
            "gold_sql": gold_sql,
            "pred_sql": pred_sql,
            "success": res.success,
            "exact_match": exact,
            "exec_match": exec_ok,
            "latency_ms": elapsed,
            "attempts": len(res.attempts),
            "retried": len(res.attempts) > 1,
            "hallucinated": res.hallucination_detected,
            "error_kind": res.error_kind,
            "error": res.error,
            "retrieved_tables": ",".join(res.retrieved_tables[:5]),
        })

    return records


# -------------------------------------------------------------
def _write_csv(records: list[dict], path: Path) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)
    print(f"  wrote {path} ({len(records)} rows)")


# -------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["rag", "baseline"], default="rag")
    ap.add_argument("--both", action="store_true", help="Run rag and baseline back-to-back")
    ap.add_argument("--limit", type=int, default=None, help="Run only the first N questions")
    args = ap.parse_args()

    benchmark = json.loads(BENCH_PATH.read_text())
    stamp = time.strftime("%Y%m%d-%H%M%S")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    summaries: dict[str, dict] = {}
    modes = ["baseline", "rag"] if args.both else [args.mode]

    for m in modes:
        print(f"\n==== Mode: {m} ====")
        records = _run_mode(benchmark, m, args.limit)
        _write_csv(records, RESULTS_DIR / f"report_{m}_{stamp}.csv")
        summaries[m] = _summarize(records)

    # Print compact summary
    print("\n==== Summary ====")
    print(json.dumps(summaries, indent=2))
    (RESULTS_DIR / f"summary_{stamp}.json").write_text(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
