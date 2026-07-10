"""
Tests for the SQL safety layer.

Mocks live_schema() so they run offline (no DB needed).
Run: pytest tests/test_safety.py -v
"""
from __future__ import annotations

import pytest

from app.agent import safety


FAKE_SCHEMA = {
    "customers":           ["customer_id", "full_name", "age", "annual_income",
                            "occupation", "city", "state", "has_default"],
    "accounts":            ["account_id", "customer_id", "branch_id", "product_id",
                            "current_balance", "status"],
    "transactions":        ["txn_id", "account_id", "txn_date", "amount",
                            "txn_type", "channel", "status"],
    "branches":            ["branch_id", "name", "city", "state", "region"],
    "loans":               ["loan_id", "customer_id", "product_id", "principal",
                            "status"],
    "campaigns":           ["campaign_id", "name", "channel", "objective"],
    "campaign_contacts":   ["contact_id", "campaign_id", "customer_id", "subscribed"],
}


@pytest.fixture(autouse=True)
def _patch_schema(monkeypatch):
    monkeypatch.setattr(safety, "live_schema", lambda: FAKE_SCHEMA)


# ----------------- happy paths -----------------
def test_simple_select_passes():
    r = safety.validate("SELECT customer_id, full_name FROM customers")
    assert r.ok
    assert "LIMIT 500" in r.sql.upper()


def test_select_with_join_passes():
    sql = """
    SELECT c.full_name, SUM(a.current_balance)
    FROM customers c JOIN accounts a ON c.customer_id = a.customer_id
    WHERE a.status = 'active'
    GROUP BY c.full_name
    """
    r = safety.validate(sql)
    assert r.ok


def test_cte_passes():
    sql = """
    WITH high_val AS (
      SELECT customer_id, SUM(current_balance) AS bal
      FROM accounts WHERE status = 'active' GROUP BY customer_id
    )
    SELECT c.full_name, h.bal
    FROM high_val h JOIN customers c ON h.customer_id = c.customer_id
    """
    r = safety.validate(sql)
    assert r.ok


def test_existing_limit_not_overridden():
    r = safety.validate("SELECT customer_id FROM customers LIMIT 10")
    assert r.ok
    assert "LIMIT 10" in r.sql.upper()
    assert "LIMIT 500" not in r.sql.upper()


def test_trailing_semicolon_stripped():
    r = safety.validate("SELECT 1 FROM customers;")
    assert r.ok
    assert not r.sql.endswith(";")


# ----------------- parse-stage rejects -----------------
def test_garbage_rejected():
    # "not even sql" gets rejected, but sqlglot may parse it as something
    # weird that fails at readonly stage instead of parse. Either is fine —
    # what matters is that it's rejected.
    r = safety.validate("not even sql")
    assert not r.ok


def test_multiple_statements_rejected():
    r = safety.validate("SELECT 1 FROM customers; SELECT 2 FROM customers")
    assert not r.ok
    assert r.stage == "parse"


def test_empty_rejected():
    r = safety.validate("   ")
    assert not r.ok


# ----------------- readonly-stage rejects -----------------
@pytest.mark.parametrize("sql", [
    "INSERT INTO customers (full_name) VALUES ('x')",
    "UPDATE customers SET full_name = 'x' WHERE customer_id = 1",
    "DELETE FROM customers WHERE customer_id = 1",
    "DROP TABLE customers",
    "TRUNCATE customers",
    "ALTER TABLE customers ADD COLUMN x INT",
    "CREATE TABLE foo (id INT)",
    "GRANT ALL ON customers TO public",
])
def test_dml_ddl_rejected(sql):
    r = safety.validate(sql)
    assert not r.ok
    assert r.stage == "readonly", f"{sql} → stage={r.stage}, reason={r.reason}"


def test_select_into_rejected():
    # SELECT ... INTO is a write
    r = safety.validate("SELECT * INTO snapshot FROM customers")
    assert not r.ok


# ----------------- schema-stage rejects -----------------
def test_unknown_table_rejected():
    r = safety.validate("SELECT * FROM pg_user")
    assert not r.ok
    assert r.stage == "schema"
    assert "pg_user" in r.reason


def test_hallucinated_column_rejected():
    # `email` is not in the customers table
    r = safety.validate("SELECT email FROM customers c WHERE c.email LIKE '%@%'")
    assert not r.ok
    assert r.stage == "schema"
    assert "email" in r.reason.lower()


def test_hallucinated_column_in_join_rejected():
    sql = """
    SELECT c.full_name, t.fraud_score
    FROM customers c JOIN transactions t ON c.customer_id = t.account_id
    """
    r = safety.validate(sql)
    assert not r.ok
    assert r.stage == "schema"
    assert "fraud_score" in r.reason


def test_unqualified_column_passes():
    # We don't reject unqualified columns since postgres will catch real
    # ambiguities. This is the documented behavior.
    r = safety.validate("SELECT current_balance FROM accounts")
    assert r.ok
