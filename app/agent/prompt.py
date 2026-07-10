"""
Prompt builder. Assembles retrieved schema docs + few-shots into a focused
context for the SQL generator.

We use a strict instruction prompt: tell the model exactly what it can and
can't do, and demand a single SQL statement with no commentary. The retry
path appends the previous (sql, error) pair so the model can self-correct.
"""
from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent

from app.agent.retriever import FewShotHit, SchemaHit


SYSTEM_PROMPT = dedent("""
    You are a senior data analyst at an Indian retail bank. You translate
    natural-language business questions into a single, correct PostgreSQL
    SELECT statement against the bank's data warehouse.

    HARD RULES
    1. Output ONLY a single PostgreSQL SELECT or WITH ... SELECT statement.
       No commentary, no markdown fences, no trailing semicolons.
    2. Read-only. Never write INSERT/UPDATE/DELETE/DDL.
    3. Only reference tables and columns shown in the schema context.
       If something the user wants isn't in the schema, return your best
       approximation using available columns — do NOT invent column names.
    4. Filter `status = 'success'` on transactions unless the user explicitly
       asks about failed/pending.
    5. For "active" entities (accounts, loans, cards) filter on
       status = 'active' unless the question implies otherwise.
    6. Use ROUND(..., 2) for percentages and averages of money.
    7. For relative dates use CURRENT_DATE / DATE_TRUNC / INTERVAL.
    8. Prefer explicit JOINs over implicit comma joins.
    9. Always alias aggregated columns with descriptive names.
""").strip()


@dataclass
class PromptBundle:
    system: str
    user: str


def build_prompt(
    question: str,
    schema_hits: list[SchemaHit],
    fewshot_hits: list[FewShotHit],
    retry_context: tuple[str, str] | None = None,  # (prev_sql, error_msg)
) -> PromptBundle:
    schema_block = "\n\n".join(h.doc for h in schema_hits)
    fs_block = "\n\n".join(
        f"-- Example: {h.question}\n{h.sql}" for h in fewshot_hits
    )

    parts = [
        "=== SCHEMA CONTEXT (relevant tables only) ===",
        schema_block,
        "",
        "=== FEW-SHOT EXAMPLES ===",
        fs_block,
        "",
        "=== USER QUESTION ===",
        question,
    ]

    if retry_context is not None:
        prev_sql, err = retry_context
        parts += [
            "",
            "=== PREVIOUS ATTEMPT FAILED ===",
            "SQL:",
            prev_sql,
            "Error:",
            err,
            "",
            "Fix the SQL. Return only the corrected SELECT statement.",
        ]
    else:
        parts += ["", "Return only the SQL statement."]

    return PromptBundle(system=SYSTEM_PROMPT, user="\n".join(parts))
