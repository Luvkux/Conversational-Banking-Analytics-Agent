"""
Schema docs for the banking warehouse.

Each table gets a dense human-readable doc that includes purpose, columns,
common joins, values, and natural-language phrases an analyst would use.
These are embedded and retrieved at query time so the LLM only sees the
relevant tables (token savings + sharper context).
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class TableDoc:
    table: str
    doc: str


SCHEMA_DOCS: list[TableDoc] = [
    TableDoc("branches", """
TABLE: branches
PURPOSE: Bank branch locations across India. 25 rows.
ALSO KNOWN AS: locations, offices, outlets.

COLUMNS:
- branch_id (SERIAL, PK)
- branch_code (TEXT, UNIQUE) — e.g. 'BR0001'
- name (TEXT)
- city (TEXT) — e.g. Mumbai, Bengaluru, Delhi
- state (TEXT)
- region (TEXT) — one of: 'North', 'South', 'East', 'West'
- opened_date (DATE)

COMMON JOINS:
- accounts.branch_id = branches.branch_id
- employees.branch_id = branches.branch_id

ANALYST PHRASES: "branch performance", "by region", "city-wise", "office".
"""),

    TableDoc("employees", """
TABLE: employees
PURPOSE: Bank staff at each branch. 500 rows.

COLUMNS:
- employee_id (SERIAL, PK)
- branch_id (INT, FK → branches.branch_id)
- full_name (TEXT)
- role (TEXT) — 'Branch Manager', 'Teller', 'Relationship Manager', 'Loan Officer', 'Customer Service', 'Operations'
- hire_date (DATE)
- salary (NUMERIC(10,2)) — annual, INR

COMMON JOINS:
- employees.branch_id = branches.branch_id

ANALYST PHRASES: "staff", "headcount", "payroll", "managers", "tellers".
"""),

    TableDoc("products", """
TABLE: products
PURPOSE: Catalog of banking products (accounts, deposits, loans, cards). 20 rows.

COLUMNS:
- product_id (SERIAL, PK)
- product_code (TEXT, UNIQUE) — e.g. 'SAV001', 'FD002', 'HL001'
- name (TEXT)
- product_type (TEXT) — one of: 'savings', 'current', 'term_deposit',
                              'personal_loan', 'home_loan', 'auto_loan', 'credit_card'
- interest_rate (NUMERIC(5,2)) — annual %, nullable for current accounts
- min_balance (NUMERIC(10,2)) — only for savings/current
- term_months (INT) — only for deposits and loans

COMMON JOINS:
- accounts.product_id = products.product_id
- loans.product_id = products.product_id

ANALYST PHRASES: "product mix", "by product type", "FD", "fixed deposit",
"home loan", "credit card variant".
"""),

    TableDoc("customers", """
TABLE: customers
PURPOSE: Bank customers. 15,000 rows. Central dimension.

COLUMNS:
- customer_id (SERIAL, PK)
- full_name (TEXT)
- age (INT)
- gender (TEXT) — 'male', 'female'
- marital_status (TEXT) — 'single', 'married', 'divorced'
- education (TEXT) — 'primary', 'secondary', 'tertiary', 'unknown'
- occupation (TEXT) — 'admin', 'blue-collar', 'technician', 'management',
                      'services', 'retired', 'self-employed', 'student',
                      'unemployed', 'entrepreneur'
- annual_income (NUMERIC(12,2)) — INR
- city (TEXT), state (TEXT)
- has_default (BOOLEAN) — has any defaulted credit history
- has_housing_loan (BOOLEAN) — flag from customer profile
- has_personal_loan (BOOLEAN) — flag from customer profile
- preferred_contact (TEXT) — 'email', 'phone', 'sms'
- onboarded_at (TIMESTAMP)

COMMON JOINS:
- accounts.customer_id = customers.customer_id
- loans.customer_id, credit_cards.customer_id, deposits.customer_id,
  campaign_contacts.customer_id all = customers.customer_id

NOTE: has_housing_loan / has_personal_loan are FLAGS on the customer record
(self-declared / profile data). For ACTUAL loan records use the `loans` table.

ANALYST PHRASES: "customers", "demographics", "by age group", "income bands",
"by state", "by occupation", "default rate".
"""),

    TableDoc("accounts", """
TABLE: accounts
PURPOSE: Deposit accounts (savings, current, term deposit). 20,000 rows.
NOT for loans or credit cards — those are in their own tables.

COLUMNS:
- account_id (SERIAL, PK)
- customer_id (INT, FK → customers.customer_id)
- branch_id (INT, FK → branches.branch_id)
- product_id (INT, FK → products.product_id) — only savings/current/term_deposit products
- account_number (TEXT, UNIQUE)
- opened_date (DATE)
- closed_date (DATE, nullable)
- status (TEXT) — 'active', 'dormant', 'closed' (~85% active, 10% dormant, 5% closed)
- current_balance (NUMERIC(14,2)) — INR

COMMON JOINS:
- accounts.customer_id = customers.customer_id
- accounts.branch_id = branches.branch_id
- accounts.product_id = products.product_id
- transactions.account_id = accounts.account_id

NOTE: A customer can have multiple accounts. For customer-level totals,
aggregate accounts by customer_id.

ANALYST PHRASES: "balance", "AUM", "deposits", "active accounts", "dormant",
"account opening", "savings vs current".
"""),

    TableDoc("transaction_categories", """
TABLE: transaction_categories
PURPOSE: Spending categories for transactions. 30 rows.

COLUMNS:
- category_id (SERIAL, PK)
- name (TEXT, UNIQUE) — e.g. 'Groceries', 'Restaurants', 'Salary', 'Rent', 'Fuel'
- parent_category (TEXT) — e.g. 'Essentials', 'Dining', 'Transport',
                                'Shopping', 'Income', 'Lifestyle', 'Finance'

COMMON JOINS:
- transactions.category_id = transaction_categories.category_id

ANALYST PHRASES: "spending category", "by category", "dining spend", "essentials".
"""),

    TableDoc("transactions", """
TABLE: transactions
PURPOSE: All money movements on deposit accounts. ~80,000 rows. Largest table.

COLUMNS:
- txn_id (BIGSERIAL, PK)
- account_id (INT, FK → accounts.account_id)
- txn_date (TIMESTAMP) — when it happened
- txn_type (TEXT) — 'credit' (money in) or 'debit' (money out)
- amount (NUMERIC(12,2)) — INR, always positive
- channel (TEXT) — 'online', 'atm', 'branch', 'upi', 'card', 'cheque'
- category_id (INT, FK → transaction_categories.category_id, nullable)
- merchant (TEXT, nullable) — present mostly for upi/card/online
- status (TEXT) — 'success' (~94%), 'failed' (~4%), 'pending' (~2%)
- description (TEXT)

COMMON JOINS:
- transactions JOIN accounts ON transactions.account_id = accounts.account_id
- transactions JOIN transaction_categories ON transactions.category_id = transaction_categories.category_id
- For customer-level: transactions → accounts → customers
- For branch-level: transactions → accounts → branches

NOTES:
- Filter status = 'success' for revenue/spending analysis unless asked otherwise.
- txn_type = 'credit' = inflow; 'debit' = outflow.
- Date range: Jan 2023 → Dec 2025.

ANALYST PHRASES: "transactions", "spend", "transfers", "UPI volume",
"failed transactions", "monthly transaction volume", "transaction trends".
"""),

    TableDoc("deposits", """
TABLE: deposits
PURPOSE: Fixed deposit (FD) / term deposit records. 5,000 rows.

COLUMNS:
- deposit_id (SERIAL, PK)
- account_id (INT, FK → accounts.account_id)
- customer_id (INT, FK → customers.customer_id)
- principal (NUMERIC(12,2)) — INR
- interest_rate (NUMERIC(5,2)) — annual %
- term_months (INT) — 6, 12, 24, 36, or 60
- opened_date (DATE)
- maturity_date (DATE)
- status (TEXT) — 'active', 'matured', 'withdrawn'

COMMON JOINS:
- deposits.customer_id = customers.customer_id
- deposits.account_id = accounts.account_id

ANALYST PHRASES: "FD", "fixed deposit", "term deposit", "deposit book",
"maturity", "FD principal".
"""),

    TableDoc("loans", """
TABLE: loans
PURPOSE: Actual loan accounts (personal, home, auto). 4,000 rows.
This is distinct from the `has_personal_loan` / `has_housing_loan` flags on customers.

COLUMNS:
- loan_id (SERIAL, PK)
- customer_id (INT, FK → customers.customer_id)
- product_id (INT, FK → products.product_id) — a loan-type product
- principal (NUMERIC(14,2)) — INR sanctioned amount
- interest_rate (NUMERIC(5,2)) — annual %
- term_months (INT)
- emi (NUMERIC(12,2)) — equated monthly installment
- disbursed_date (DATE)
- status (TEXT) — 'active' (~70%), 'closed' (~20%), 'defaulted' (~4%), 'overdue' (~6%)

COMMON JOINS:
- loans.customer_id = customers.customer_id
- loans.product_id = products.product_id

ANALYST PHRASES: "loan book", "disbursals", "NPA", "default rate",
"overdue loans", "home loan portfolio", "EMI".
"""),

    TableDoc("credit_cards", """
TABLE: credit_cards
PURPOSE: Credit card holdings. 6,000 rows.

COLUMNS:
- card_id (SERIAL, PK)
- customer_id (INT, FK → customers.customer_id)
- card_number (TEXT, UNIQUE) — masked-style
- credit_limit (NUMERIC(12,2)) — INR
- current_balance (NUMERIC(12,2)) — outstanding owed by customer
- issued_date (DATE)
- expiry_date (DATE)
- status (TEXT) — 'active', 'blocked', 'expired'

COMMON JOINS:
- credit_cards.customer_id = customers.customer_id

NOTES:
- Utilization = current_balance / credit_limit.
- Credit card transactions are NOT in this table — those live in the
  `transactions` table with channel='card' (when applicable).

ANALYST PHRASES: "card portfolio", "credit utilization", "active cards",
"blocked cards", "credit limit".
"""),

    TableDoc("campaigns", """
TABLE: campaigns
PURPOSE: Marketing campaign master. 10 rows.

COLUMNS:
- campaign_id (SERIAL, PK)
- name (TEXT)
- channel (TEXT) — 'email', 'phone', 'sms'
- target_segment (TEXT) — e.g. 'high_income_urban', 'salaried_25_40',
                              'retired_seniors', 'self_employed', 'tier2_emerging_affluent'
- start_date (DATE), end_date (DATE)
- budget (NUMERIC(12,2)) — INR
- objective (TEXT) — 'term_deposit_signup', 'credit_card_acquisition',
                     'personal_loan_x_sell', 'home_loan_balance_transfer',
                     'savings_account_upgrade'

COMMON JOINS:
- campaign_contacts.campaign_id = campaigns.campaign_id

ANALYST PHRASES: "campaign", "marketing spend", "objective", "channel mix".
"""),

    TableDoc("campaign_contacts", """
TABLE: campaign_contacts
PURPOSE: Each customer outreach attempt under a campaign. 30,000 rows.
This is the FACT table for campaign effectiveness analysis.

COLUMNS:
- contact_id (BIGSERIAL, PK)
- campaign_id (INT, FK → campaigns.campaign_id)
- customer_id (INT, FK → customers.customer_id)
- contact_date (DATE)
- contact_count (INT) — number of contact attempts in this round
- duration_seconds (INT, nullable) — for phone channels
- previous_outcome (TEXT) — 'success', 'failure', 'unknown'
- days_since_last_contact (INT) — -1 means never contacted before
- outcome (TEXT) — 'subscribed', 'not_subscribed', 'no_response'
- subscribed (BOOLEAN) — outcome = 'subscribed'

COMMON JOINS:
- campaign_contacts.campaign_id = campaigns.campaign_id
- campaign_contacts.customer_id = customers.customer_id

NOTES:
- Conversion rate = SUM(CASE WHEN subscribed THEN 1 ELSE 0 END)::float / COUNT(*)
- Subscription rate by campaign / segment / channel is the most common ask.

ANALYST PHRASES: "campaign conversion", "subscription rate", "responded",
"opt-in rate", "effectiveness".
"""),
]


def all_docs() -> list[TableDoc]:
    return SCHEMA_DOCS


def docs_as_text() -> str:
    """Concatenate all docs (for fallback / debugging)."""
    return "\n\n".join(d.doc.strip() for d in SCHEMA_DOCS)
