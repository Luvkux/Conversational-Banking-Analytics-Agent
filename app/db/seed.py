"""
Seed banking warehouse with realistic synthetic data.
Run: python -m app.db.seed

Uses psycopg COPY for speed. Whole job ~30s on a laptop.
"""
from __future__ import annotations

import io
import random
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterable

import numpy as np
import psycopg
from faker import Faker

from app.config import settings

# -------------------------------------------------------------
fake = Faker("en_IN")
Faker.seed(42)
random.seed(42)
np.random.seed(42)

VOL = {
    "branches": 25,
    "employees": 500,
    "products": 20,
    "customers": 15_000,
    "accounts": 20_000,
    "transaction_categories": 30,
    "transactions": 80_000,
    "deposits": 5_000,
    "loans": 4_000,
    "credit_cards": 6_000,
    "campaigns": 10,
    "campaign_contacts": 30_000,
}

REGIONS_STATES = {
    "North": ["Delhi", "Punjab", "Haryana", "Uttar Pradesh", "Rajasthan"],
    "South": ["Karnataka", "Tamil Nadu", "Kerala", "Telangana", "Andhra Pradesh"],
    "East":  ["West Bengal", "Odisha", "Bihar", "Jharkhand", "Assam"],
    "West":  ["Maharashtra", "Gujarat", "Goa", "Madhya Pradesh"],
}
CITY_FOR_STATE = {
    "Delhi": "New Delhi", "Punjab": "Ludhiana", "Haryana": "Gurugram",
    "Uttar Pradesh": "Lucknow", "Rajasthan": "Jaipur", "Karnataka": "Bengaluru",
    "Tamil Nadu": "Chennai", "Kerala": "Kochi", "Telangana": "Hyderabad",
    "Andhra Pradesh": "Vijayawada", "West Bengal": "Kolkata", "Odisha": "Bhubaneswar",
    "Bihar": "Patna", "Jharkhand": "Ranchi", "Assam": "Guwahati",
    "Maharashtra": "Mumbai", "Gujarat": "Ahmedabad", "Goa": "Panaji",
    "Madhya Pradesh": "Indore",
}

OCCUPATIONS = ["admin", "blue-collar", "technician", "management", "services",
               "retired", "self-employed", "student", "unemployed", "entrepreneur"]
EDUCATIONS = ["primary", "secondary", "tertiary", "unknown"]
MARITAL = ["single", "married", "divorced"]
CONTACT_PREF = ["email", "phone", "sms"]
EMPLOYEE_ROLES = ["Branch Manager", "Teller", "Relationship Manager",
                  "Loan Officer", "Customer Service", "Operations"]

# -------------------------------------------------------------
def conn():
    # psycopg3 connection (note: we strip SQLAlchemy prefix here)
    dsn = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    return psycopg.connect(dsn)


def copy_rows(cur, table: str, columns: list[str], rows: Iterable[tuple]):
    """Stream rows via COPY for speed."""
    cols = ", ".join(columns)
    with cur.copy(f"COPY {table} ({cols}) FROM STDIN") as cp:
        for r in rows:
            cp.write_row(r)


# -------------------------------------------------------------
def seed_branches(cur):
    rows = []
    code = 1
    for region, states in REGIONS_STATES.items():
        for st in states:
            rows.append((
                f"BR{code:04d}",
                f"{CITY_FOR_STATE[st]} Main",
                CITY_FOR_STATE[st], st, region,
                fake.date_between(date(2010, 1, 1), date(2022, 12, 31)),
            ))
            code += 1
            if len(rows) >= VOL["branches"]:
                break
        if len(rows) >= VOL["branches"]:
            break
    copy_rows(cur, "branches",
              ["branch_code", "name", "city", "state", "region", "opened_date"],
              rows)
    return len(rows)


def seed_employees(cur, n_branches: int):
    rows = []
    for _ in range(VOL["employees"]):
        rows.append((
            random.randint(1, n_branches),
            fake.name(),
            random.choice(EMPLOYEE_ROLES),
            fake.date_between(date(2015, 1, 1), date(2024, 12, 31)),
            round(random.uniform(25_000, 250_000), 2),
        ))
    copy_rows(cur, "employees",
              ["branch_id", "full_name", "role", "hire_date", "salary"], rows)


def seed_products(cur):
    catalog = [
        ("SAV001", "Basic Savings",       "savings",       3.50,   1000,    None),
        ("SAV002", "Premium Savings",     "savings",       4.00,  25000,    None),
        ("SAV003", "Senior Citizen Save", "savings",       4.25,   5000,    None),
        ("CUR001", "Business Current",    "current",       0.00,  10000,    None),
        ("CUR002", "Trader Current",      "current",       0.00,  50000,    None),
        ("FD001",  "FD 6M",               "term_deposit",  6.50,   None,       6),
        ("FD002",  "FD 1Y",               "term_deposit",  7.00,   None,      12),
        ("FD003",  "FD 3Y",               "term_deposit",  7.25,   None,      36),
        ("FD004",  "FD 5Y Tax Saver",     "term_deposit",  7.50,   None,      60),
        ("PL001",  "Personal Loan Std",   "personal_loan",10.50,   None,      36),
        ("PL002",  "Personal Loan Plus",  "personal_loan",11.25,   None,      60),
        ("HL001",  "Home Loan 15Y",       "home_loan",     8.40,   None,     180),
        ("HL002",  "Home Loan 20Y",       "home_loan",     8.65,   None,     240),
        ("HL003",  "Home Loan 30Y",       "home_loan",     8.95,   None,     360),
        ("AL001",  "Auto Loan New",       "auto_loan",     9.10,   None,      60),
        ("AL002",  "Auto Loan Used",      "auto_loan",     9.85,   None,      48),
        ("CC001",  "Platinum Credit",     "credit_card",  36.00,   None,    None),
        ("CC002",  "Gold Credit",         "credit_card",  38.00,   None,    None),
        ("CC003",  "Silver Credit",       "credit_card",  40.00,   None,    None),
        ("CC004",  "Travel Rewards",      "credit_card",  37.50,   None,    None),
    ]
    copy_rows(cur, "products",
              ["product_code", "name", "product_type", "interest_rate",
               "min_balance", "term_months"], catalog)


def seed_customers(cur):
    rows = []
    for _ in range(VOL["customers"]):
        st = random.choice([s for ss in REGIONS_STATES.values() for s in ss])
        age = int(np.clip(np.random.normal(40, 13), 18, 85))
        income = round(np.random.lognormal(mean=12.5, sigma=0.7), 2)  # INR
        rows.append((
            fake.name(),
            age,
            random.choice(["male", "female"]),
            random.choice(MARITAL),
            random.choice(EDUCATIONS),
            random.choice(OCCUPATIONS),
            income,
            CITY_FOR_STATE[st], st,
            random.random() < 0.04,         # default
            random.random() < 0.18,         # housing loan
            random.random() < 0.12,         # personal loan
            random.choice(CONTACT_PREF),
            fake.date_time_between(datetime(2018, 1, 1), datetime(2025, 12, 31)),
        ))
    copy_rows(cur, "customers",
              ["full_name", "age", "gender", "marital_status", "education",
               "occupation", "annual_income", "city", "state",
               "has_default", "has_housing_loan", "has_personal_loan",
               "preferred_contact", "onboarded_at"], rows)


def seed_accounts(cur, n_customers: int, n_branches: int):
    # Only deposit-style products in `accounts` (savings/current/term_deposit).
    # We'll fetch their IDs first.
    cur.execute("SELECT product_id FROM products WHERE product_type IN ('savings','current','term_deposit')")
    deposit_pids = [r[0] for r in cur.fetchall()]

    rows = []
    used_acc_nums = set()
    for _ in range(VOL["accounts"]):
        # account number unique
        while True:
            ac = f"AC{random.randint(10**10, 10**11 - 1)}"
            if ac not in used_acc_nums:
                used_acc_nums.add(ac); break
        opened = fake.date_between(date(2019, 1, 1), date(2025, 6, 30))
        status = np.random.choice(["active", "dormant", "closed"], p=[0.85, 0.10, 0.05])
        closed = fake.date_between(opened, date(2025, 12, 31)) if status == "closed" else None
        bal = round(np.random.lognormal(mean=10.5, sigma=1.1), 2)
        rows.append((
            random.randint(1, n_customers),
            random.randint(1, n_branches),
            random.choice(deposit_pids),
            ac, opened, closed, status, bal,
        ))
    copy_rows(cur, "accounts",
              ["customer_id", "branch_id", "product_id", "account_number",
               "opened_date", "closed_date", "status", "current_balance"], rows)


def seed_transaction_categories(cur):
    cats = [
        ("Groceries", "Essentials"), ("Utilities", "Essentials"),
        ("Rent", "Essentials"), ("Fuel", "Transport"),
        ("Ride Sharing", "Transport"), ("Public Transit", "Transport"),
        ("Restaurants", "Dining"), ("Coffee Shops", "Dining"),
        ("Online Shopping", "Shopping"), ("Apparel", "Shopping"),
        ("Electronics", "Shopping"), ("Healthcare", "Health"),
        ("Pharmacy", "Health"), ("Insurance", "Finance"),
        ("Investments", "Finance"), ("Loan EMI", "Finance"),
        ("Salary", "Income"), ("Interest Credit", "Income"),
        ("Refunds", "Income"), ("Bonus", "Income"),
        ("Entertainment", "Lifestyle"), ("Travel", "Lifestyle"),
        ("Hotels", "Lifestyle"), ("Subscriptions", "Lifestyle"),
        ("Education", "Personal"), ("Gym", "Personal"),
        ("Donations", "Personal"), ("Transfer In", "Internal"),
        ("Transfer Out", "Internal"), ("ATM Withdrawal", "Internal"),
    ]
    copy_rows(cur, "transaction_categories", ["name", "parent_category"], cats)


def seed_transactions(cur, n_accounts: int, n_categories: int):
    channels = ["online", "atm", "branch", "upi", "card", "cheque"]
    channel_p = [0.25, 0.10, 0.05, 0.35, 0.20, 0.05]
    status_choices = ["success", "failed", "pending"]
    status_p = [0.94, 0.04, 0.02]

    rows = []
    for i in range(VOL["transactions"]):
        acc = random.randint(1, n_accounts)
        when = fake.date_time_between(datetime(2023, 1, 1), datetime(2025, 12, 31))
        ttype = "credit" if random.random() < 0.30 else "debit"
        amt = round(np.random.lognormal(mean=6.0, sigma=1.2), 2)  # INR-ish
        ch = np.random.choice(channels, p=channel_p)
        cat = random.randint(1, n_categories)
        merchant = fake.company() if ch in ("upi", "card", "online") else None
        status = np.random.choice(status_choices, p=status_p)
        desc = f"{ttype.title()} via {ch}"
        rows.append((acc, when, ttype, amt, ch, cat, merchant, status, desc))
    copy_rows(cur, "transactions",
              ["account_id", "txn_date", "txn_type", "amount", "channel",
               "category_id", "merchant", "status", "description"], rows)


def seed_deposits(cur, n_customers: int):
    cur.execute("SELECT account_id FROM accounts ORDER BY random() LIMIT %s", (VOL["deposits"],))
    accs = [r[0] for r in cur.fetchall()]
    rows = []
    for acc in accs:
        opened = fake.date_between(date(2022, 1, 1), date(2025, 6, 30))
        term = random.choice([6, 12, 24, 36, 60])
        principal = round(np.random.lognormal(mean=11.5, sigma=0.8), 2)
        rate = round(random.uniform(6.0, 7.75), 2)
        maturity = opened + timedelta(days=term * 30)
        status = "matured" if maturity < date.today() else random.choice(["active", "active", "active", "withdrawn"])
        rows.append((acc, random.randint(1, n_customers), principal, rate, term, opened, maturity, status))
    copy_rows(cur, "deposits",
              ["account_id", "customer_id", "principal", "interest_rate",
               "term_months", "opened_date", "maturity_date", "status"], rows)


def seed_loans(cur, n_customers: int):
    cur.execute("SELECT product_id FROM products WHERE product_type IN ('personal_loan','home_loan','auto_loan')")
    loan_pids = [r[0] for r in cur.fetchall()]
    rows = []
    for _ in range(VOL["loans"]):
        pid = random.choice(loan_pids)
        principal = round(np.random.lognormal(mean=12.5, sigma=1.0), 2)
        rate = round(random.uniform(8.0, 12.0), 2)
        term = random.choice([36, 60, 120, 180, 240])
        monthly_rate = rate / 12 / 100
        emi = round(principal * monthly_rate / (1 - (1 + monthly_rate) ** -term), 2)
        disbursed = fake.date_between(date(2020, 1, 1), date(2025, 6, 30))
        status = np.random.choice(["active", "closed", "defaulted", "overdue"], p=[0.70, 0.20, 0.04, 0.06])
        rows.append((random.randint(1, n_customers), pid, principal, rate, term, emi, disbursed, status))
    copy_rows(cur, "loans",
              ["customer_id", "product_id", "principal", "interest_rate",
               "term_months", "emi", "disbursed_date", "status"], rows)


def seed_credit_cards(cur, n_customers: int):
    rows = []
    used = set()
    for _ in range(VOL["credit_cards"]):
        while True:
            cn = f"{random.randint(4000, 5999)}-{random.randint(1000,9999)}-{random.randint(1000,9999)}-{random.randint(1000,9999)}"
            if cn not in used:
                used.add(cn); break
        issued = fake.date_between(date(2020, 1, 1), date(2025, 6, 30))
        expiry = issued + timedelta(days=365 * random.choice([3, 4, 5]))
        limit = round(np.random.lognormal(mean=11.5, sigma=0.6), 2)
        bal = round(random.uniform(0, float(limit) * 0.85), 2)
        status = "expired" if expiry < date.today() else np.random.choice(["active", "blocked"], p=[0.95, 0.05])
        rows.append((random.randint(1, n_customers), cn, limit, bal, issued, expiry, status))
    copy_rows(cur, "credit_cards",
              ["customer_id", "card_number", "credit_limit", "current_balance",
               "issued_date", "expiry_date", "status"], rows)


def seed_campaigns(cur):
    objectives = ["term_deposit_signup", "credit_card_acquisition", "personal_loan_x_sell",
                  "home_loan_balance_transfer", "savings_account_upgrade"]
    channels = ["email", "phone", "sms"]
    segments = ["high_income_urban", "salaried_25_40", "retired_seniors",
                "self_employed", "tier2_emerging_affluent"]
    rows = []
    for i in range(VOL["campaigns"]):
        start = fake.date_between(date(2024, 1, 1), date(2025, 9, 30))
        end = start + timedelta(days=random.randint(30, 120))
        rows.append((
            f"Q{((start.month - 1) // 3) + 1}{start.year} {random.choice(objectives).replace('_',' ').title()}",
            random.choice(channels),
            random.choice(segments),
            start, end,
            round(random.uniform(200000, 5000000), 2),
            random.choice(objectives),
        ))
    copy_rows(cur, "campaigns",
              ["name", "channel", "target_segment", "start_date", "end_date",
               "budget", "objective"], rows)


def seed_campaign_contacts(cur, n_customers: int):
    cur.execute("SELECT campaign_id, start_date, end_date FROM campaigns")
    camps = cur.fetchall()
    rows = []
    for _ in range(VOL["campaign_contacts"]):
        cid, s, e = random.choice(camps)
        contact_d = fake.date_between(s, e)
        cnt = max(1, int(np.random.poisson(2)))
        dur = random.randint(15, 900) if random.random() < 0.7 else None
        prev = np.random.choice(["success", "failure", "unknown"], p=[0.10, 0.30, 0.60])
        days_since = random.choice([-1, *range(1, 999)])  # -1 == never
        outcome = np.random.choice(
            ["subscribed", "not_subscribed", "no_response"],
            p=[0.12, 0.55, 0.33],
        )
        rows.append((cid, random.randint(1, n_customers), contact_d, cnt, dur,
                     prev, days_since, outcome, outcome == "subscribed"))
    copy_rows(cur, "campaign_contacts",
              ["campaign_id", "customer_id", "contact_date", "contact_count",
               "duration_seconds", "previous_outcome", "days_since_last_contact",
               "outcome", "subscribed"], rows)


# -------------------------------------------------------------
def main():
    print("Connecting...")
    with conn() as c, c.cursor() as cur:
        # Wipe & start fresh
        cur.execute("""
            TRUNCATE campaign_contacts, campaigns, credit_cards, loans, deposits,
                     transactions, transaction_categories, accounts, customers,
                     products, employees, branches
            RESTART IDENTITY CASCADE;
        """)
        print("Truncated.")

        n_branches = seed_branches(cur); print(f"  branches:  {n_branches}")
        seed_employees(cur, n_branches);  print(f"  employees: {VOL['employees']}")
        seed_products(cur);               print(f"  products:  20")
        seed_customers(cur);              print(f"  customers: {VOL['customers']}")
        seed_accounts(cur, VOL["customers"], n_branches); print(f"  accounts:  {VOL['accounts']}")
        seed_transaction_categories(cur); print(f"  categories: 30")
        seed_transactions(cur, VOL["accounts"], VOL["transaction_categories"])
        print(f"  transactions: {VOL['transactions']}")
        seed_deposits(cur, VOL["customers"]);     print(f"  deposits:  {VOL['deposits']}")
        seed_loans(cur, VOL["customers"]);        print(f"  loans:     {VOL['loans']}")
        seed_credit_cards(cur, VOL["customers"]); print(f"  cards:     {VOL['credit_cards']}")
        seed_campaigns(cur);                       print(f"  campaigns: {VOL['campaigns']}")
        seed_campaign_contacts(cur, VOL["customers"])
        print(f"  campaign_contacts: {VOL['campaign_contacts']}")

        c.commit()

        cur.execute("SELECT * FROM v_table_counts ORDER BY table_name")
        print("\n— Row counts —")
        for tbl, cnt in cur.fetchall():
            print(f"  {tbl:<25} {cnt:>8}")
    print("\nDone.")


if __name__ == "__main__":
    main()
