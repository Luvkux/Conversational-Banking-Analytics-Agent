"""
Entity guard — pre-flight check on the *user's natural-language question*.

The problem this solves: GPT-4 silently substitutes missing fields with
"semantically similar" ones in our schema. e.g.:
  - "find customers by LinkedIn profile"  →  WHERE preferred_contact = 'email'
  - "show DOB of high-value customers"    →  age-based formula
  - "list email addresses for campaign X" →  preferred_contact = 'email'

The substitution is plausible but WRONG — the user expected actual fields
that don't exist in our warehouse. We catch these before they ever reach
the LLM by scanning the question against a curated blocklist.

Design notes:
  - Phrase matching, not token matching (so "email address" hits but the
    legitimate "prefers email" doesn't — the column `preferred_contact`
    contains values 'email'/'phone'/'sms' which is fine).
  - Case-insensitive, word-boundary aware.
  - Returns the matched phrases so the error message is helpful.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# Phrases that imply schema we do NOT have. Each entry is a regex pattern
# that must match on word boundaries to count as a hit.
_FORBIDDEN: dict[str, str] = {
    # Identity / PII fields we don't store
    "linkedin":            r"\blinkedin\b",
    "instagram":           r"\binstagram\b",
    "facebook":            r"\bfacebook\b",
    "twitter":             r"\b(twitter|x\s+handle)\b",
    "social media":        r"\bsocial\s+media\b",
    "aadhaar":             r"\baadh?aa?r\b",                       # aadhaar / aadhar / aadar
    "pan card":            r"\b(pan\s+cards?|pan\s+numbers?)\b",
    "passport":            r"\bpassports?\b",
    "ssn":                 r"\b(ssn|social\s+security)\b",

    # Contact fields the warehouse doesn't store as columns
    "email address":       r"\bemail\s+(addresse?s?|ids?)\b",        # address/addresses/id/ids
    "phone number":        r"\bphone\s+(numbers?|nos?\.?)\b",
    "mobile number":       r"\b(mobile|cell|cellphone)(\s*(numbers?|nos?\.?))?\b",
    "telephone":           r"\btelephones?\b",

    # Date of birth — we have `age` not `dob`
    "date of birth":       r"\bdate\s+of\s+birth\b",
    "dob":                 r"\bdob\b",
    "birthday":            r"\b(birthday|birth\s+date)\b",

    # Compensation history — we have `annual_income` (single point)
    "salary history":      r"\bsalary\s+history\b",
    "compensation history":r"\bcompensation\s+history\b",
    "pay history":         r"\bpay\s+history\b",

    # Address sub-components we don't store (we have city/state only)
    "street address":      r"\b(street|line\s*1|line\s*2)\s+address\b",
    "zip code":            r"\b(zip\s*code|postal\s*code|pin\s*code|pincode)\b",

    # External credit data
    "credit score":        r"\bcredit\s+score\b",
    "cibil":               r"\bcibil\b",
}

# Compile once
_PATTERNS: list[tuple[str, re.Pattern]] = [
    (label, re.compile(pat, re.IGNORECASE)) for label, pat in _FORBIDDEN.items()
]


# ----------------------------------------------------------------
@dataclass
class EntityGuardResult:
    ok: bool
    matched: list[str]          # forbidden phrases found in the query
    message: str | None = None  # user-facing rejection message


SUPPORTED_FIELDS_SUMMARY = (
    "Available customer fields: customer_id, full_name, age, gender, marital_status, "
    "education, occupation, annual_income, city, state, has_default, has_housing_loan, "
    "has_personal_loan, preferred_contact (values: email/phone/sms), onboarded_at. "
    "We do NOT store: email addresses, phone numbers, LinkedIn/Instagram/etc., "
    "Aadhaar/PAN/passport, date of birth, salary history, street addresses, "
    "or external credit scores."
)


def check(question: str) -> EntityGuardResult:
    matched: list[str] = []
    for label, pat in _PATTERNS:
        if pat.search(question):
            matched.append(label)

    if not matched:
        return EntityGuardResult(ok=True, matched=[])

    return EntityGuardResult(
        ok=False,
        matched=matched,
        message=(
            f"Unknown field(s) requested: {', '.join(matched)}. "
            f"These are not in the banking warehouse. {SUPPORTED_FIELDS_SUMMARY}"
        ),
    )
