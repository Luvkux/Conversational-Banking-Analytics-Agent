"""
Tests for the entity guard (P0.1).

Runs offline — no DB, no LLM, no embeddings.
"""
import pytest
from app.agent import entity_guard as eg


# ----- legitimate banking queries — must pass --------------------------
@pytest.mark.parametrize("q", [
    "How many active accounts do we have?",
    "Top 10 customers by total balance",
    "Conversion rate by campaign channel",
    "Customers who prefer email contact",                # 'email' here is a VALUE
    "Customers who prefer phone over sms",               # same
    "Loans by product type",
    "Monthly transaction volume in 2024",
    "Average annual income by occupation",
    "Branches in the South region",
    "What is the default rate on home loans?",
    "Show me FD principal by term length",
])
def test_legitimate_queries_pass(q):
    r = eg.check(q)
    assert r.ok, f"legit query rejected: {q} → matched {r.matched}"


# ----- adversarial — must be rejected ----------------------------------
@pytest.mark.parametrize("q,expected_label", [
    ("find customers by linkedin profile",        "linkedin"),
    ("show instagram handles of high-value customers", "instagram"),
    ("list customers with their Aadhaar number",  "aadhaar"),
    ("Aadhar verified customers count",           "aadhaar"),
    ("get email addresses of subscribers",        "email address"),
    ("show email IDs for the dormant accounts",   "email address"),
    ("phone numbers of overdue loan customers",   "phone number"),
    ("mobile no for top depositors",              "mobile number"),
    ("date of birth distribution of customers",   "date of birth"),
    ("DOB of high-value customers",               "dob"),
    ("salary history of branch managers",         "salary history"),
    ("compensation history by role",              "compensation history"),
    ("street address of every branch",            "street address"),
    ("zip code wise breakdown",                   "zip code"),
    ("PIN code wise customer count",              "zip code"),
    ("PAN card numbers of defaulters",            "pan card"),
    ("credit score by income bracket",            "credit score"),
    ("CIBIL score buckets",                       "cibil"),
])
def test_adversarial_queries_rejected(q, expected_label):
    r = eg.check(q)
    assert not r.ok, f"adversarial query passed: {q}"
    assert expected_label in r.matched, \
        f"expected '{expected_label}' in matches; got {r.matched}"
    # message must be informative
    assert "Unknown field" in (r.message or "")


# ----- multiple forbidden fields surface together ----------------------
def test_multiple_matches_reported():
    r = eg.check("export linkedin and aadhaar for all customers")
    assert not r.ok
    assert "linkedin" in r.matched
    assert "aadhaar" in r.matched


# ----- legitimate use of words that PARTIALLY overlap forbidden --------
def test_email_as_contact_value_passes():
    # `preferred_contact` is a column whose values include 'email'.
    # This query is legitimately asking about that column.
    r = eg.check("how many customers chose email as preferred contact")
    assert r.ok


def test_phone_as_contact_value_passes():
    r = eg.check("phone vs email vs sms breakdown of contact preferences")
    assert r.ok
