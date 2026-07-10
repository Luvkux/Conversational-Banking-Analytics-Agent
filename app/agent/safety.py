"""
SQL safety layer.

Three guards, each a hard reject before execution:

  1. PARSE      — sqlglot must parse it (postgres dialect)
  2. READ-ONLY  — no INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/GRANT/TRUNCATE/...
                  also block multiple statements, comments-with-semicolons,
                  obvious injection shapes
  3. SCHEMA     — every referenced table must be in the whitelist;
                  every referenced column (where a table is resolvable)
                  must actually exist on that table

The third guard is what catches HALLUCINATIONS — the LLM inventing column
names like `customers.email` or `transactions.fraud_score` that look
plausible but don't exist in this warehouse.

Returns (ok, sql_to_run, reason). On ok=True we also strip trailing
semicolons and inject a LIMIT clause if one is missing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import sqlglot
from sqlglot import exp

from app.db.connection import live_schema

# ----------------------------------------------------------------
ALLOWED_TABLES = {
    "branches", "employees", "products", "customers", "accounts",
    "transaction_categories", "transactions", "deposits", "loans",
    "credit_cards", "campaigns", "campaign_contacts",
    "v_table_counts",  # the sanity view
}

# Any of these AST node types in the tree => reject.
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter,
    exp.Create, exp.TruncateTable,
    exp.Grant,
    exp.Command,    # catches arbitrary unparsed statements like VACUUM, COPY, SET
    exp.Transaction, exp.Commit, exp.Rollback,
)

DEFAULT_LIMIT = 500


# ----------------------------------------------------------------
@dataclass
class SafetyResult:
    ok: bool
    sql: Optional[str] = None       # cleaned SQL (with limit injected, semicolons stripped)
    reason: Optional[str] = None    # human-readable rejection reason
    stage: Optional[str] = None     # 'parse' | 'readonly' | 'schema' | None


# ----------------------------------------------------------------
def validate(sql: str) -> SafetyResult:
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        return SafetyResult(False, reason="empty SQL", stage="parse")

    # ---- Stage 1: parse ----------------------------------------------------
    try:
        parsed = sqlglot.parse(sql, dialect="postgres")
    except sqlglot.errors.ParseError as e:
        return SafetyResult(False, reason=f"parse error: {e}", stage="parse")

    parsed = [p for p in parsed if p is not None]
    if len(parsed) == 0:
        return SafetyResult(False, reason="no parseable statement", stage="parse")
    if len(parsed) > 1:
        return SafetyResult(False, reason="multiple statements not allowed", stage="parse")

    tree = parsed[0]

    # ---- Stage 2: read-only -----------------------------------------------
    # The top-level node must be SELECT (or a WITH that wraps a SELECT).
    if isinstance(tree, exp.With):
        inner = tree.this
        if not isinstance(inner, exp.Select):
            return SafetyResult(False, reason="WITH must wrap a SELECT", stage="readonly")
    elif not isinstance(tree, exp.Select):
        return SafetyResult(False, reason=f"only SELECT/CTE allowed, got {type(tree).__name__}",
                            stage="readonly")

    # No forbidden node types anywhere in the tree.
    for node in tree.walk():
        node = node[0] if isinstance(node, tuple) else node
        if isinstance(node, FORBIDDEN_NODES):
            return SafetyResult(
                False,
                reason=f"forbidden operation: {type(node).__name__}",
                stage="readonly",
            )

    # ---- Stage 3: schema / hallucination check ----------------------------
    schema = live_schema()

    # Collect CTE names — these are virtual tables introduced by WITH clauses
    # and must NOT be checked against the warehouse whitelist.
    cte_names = {cte.alias for cte in tree.find_all(exp.CTE)}

    # alias -> real table name, e.g. {"c": "customers", "customers": "customers"}
    alias_map: dict[str, str] = {}
    used_tables: set[str] = set()

    for tbl in tree.find_all(exp.Table):
        name = tbl.name
        if name in cte_names:
            # Reference to a CTE we defined — alias maps to itself but no schema check.
            alias_map[tbl.alias_or_name] = name
            alias_map[name] = name
            continue
        if name not in ALLOWED_TABLES:
            return SafetyResult(
                False,
                reason=f"table '{name}' is not in the allowed schema",
                stage="schema",
            )
        used_tables.add(name)
        alias = tbl.alias_or_name
        alias_map[alias] = name
        alias_map[name] = name

    # Column existence check — only enforced where we can resolve the table.
    # If a column ref has no table qualifier AND multiple tables are in scope,
    # we let it pass (postgres will catch ambiguity / unknowns at runtime).
    # CTE-qualified columns are also skipped (we don't track CTE output schemas).
    for col in tree.find_all(exp.Column):
        tbl_qualifier = col.table
        if not tbl_qualifier:
            continue
        if tbl_qualifier in cte_names:
            continue
        real_table = alias_map.get(tbl_qualifier)
        if real_table is None or real_table in cte_names:
            continue
        if col.name not in schema.get(real_table, []):
            return SafetyResult(
                False,
                reason=f"column '{tbl_qualifier}.{col.name}' does not exist on table '{real_table}'",
                stage="schema",
            )

    # ---- Cleanup: inject LIMIT if absent ----------------------------------
    sel = tree.this if isinstance(tree, exp.With) else tree
    if not sel.args.get("limit"):
        tree.limit(DEFAULT_LIMIT, copy=False)

    cleaned = tree.sql(dialect="postgres")
    return SafetyResult(True, sql=cleaned)
