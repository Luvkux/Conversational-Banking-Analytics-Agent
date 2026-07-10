-- ============================================================
-- Banking Analytics Warehouse — 12 tables
-- ============================================================

DROP TABLE IF EXISTS campaign_contacts CASCADE;
DROP TABLE IF EXISTS campaigns CASCADE;
DROP TABLE IF EXISTS credit_cards CASCADE;
DROP TABLE IF EXISTS loans CASCADE;
DROP TABLE IF EXISTS deposits CASCADE;
DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS transaction_categories CASCADE;
DROP TABLE IF EXISTS accounts CASCADE;
DROP TABLE IF EXISTS customers CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS employees CASCADE;
DROP TABLE IF EXISTS branches CASCADE;

-- ------------------------------------------------------------
CREATE TABLE branches (
    branch_id     SERIAL PRIMARY KEY,
    branch_code   TEXT UNIQUE NOT NULL,
    name          TEXT NOT NULL,
    city          TEXT NOT NULL,
    state         TEXT NOT NULL,
    region        TEXT NOT NULL,            -- North/South/East/West
    opened_date   DATE NOT NULL
);

CREATE TABLE employees (
    employee_id   SERIAL PRIMARY KEY,
    branch_id     INT  NOT NULL REFERENCES branches(branch_id),
    full_name     TEXT NOT NULL,
    role          TEXT NOT NULL,            -- Manager, Teller, RelationshipMgr, etc.
    hire_date     DATE NOT NULL,
    salary        NUMERIC(10,2) NOT NULL
);
CREATE INDEX idx_employees_branch ON employees(branch_id);

CREATE TABLE products (
    product_id    SERIAL PRIMARY KEY,
    product_code  TEXT UNIQUE NOT NULL,
    name          TEXT NOT NULL,
    product_type  TEXT NOT NULL CHECK (product_type IN
                  ('savings','current','term_deposit','personal_loan','home_loan','auto_loan','credit_card')),
    interest_rate NUMERIC(5,2),
    min_balance   NUMERIC(10,2),
    term_months   INT
);

CREATE TABLE customers (
    customer_id        SERIAL PRIMARY KEY,
    full_name          TEXT NOT NULL,
    age                INT  NOT NULL,
    gender             TEXT,
    marital_status     TEXT,                -- single/married/divorced
    education          TEXT,                -- primary/secondary/tertiary
    occupation         TEXT,                -- admin/blue-collar/technician/management/...
    annual_income      NUMERIC(12,2),
    city               TEXT,
    state              TEXT,
    has_default        BOOLEAN DEFAULT FALSE,
    has_housing_loan   BOOLEAN DEFAULT FALSE,
    has_personal_loan  BOOLEAN DEFAULT FALSE,
    preferred_contact  TEXT,                -- email/phone/sms
    onboarded_at       TIMESTAMP NOT NULL
);
CREATE INDEX idx_customers_state ON customers(state);
CREATE INDEX idx_customers_occupation ON customers(occupation);

CREATE TABLE accounts (
    account_id      SERIAL PRIMARY KEY,
    customer_id     INT  NOT NULL REFERENCES customers(customer_id),
    branch_id       INT  NOT NULL REFERENCES branches(branch_id),
    product_id      INT  NOT NULL REFERENCES products(product_id),
    account_number  TEXT UNIQUE NOT NULL,
    opened_date     DATE NOT NULL,
    closed_date     DATE,
    status          TEXT NOT NULL CHECK (status IN ('active','dormant','closed')),
    current_balance NUMERIC(14,2) NOT NULL DEFAULT 0
);
CREATE INDEX idx_accounts_customer ON accounts(customer_id);
CREATE INDEX idx_accounts_branch   ON accounts(branch_id);
CREATE INDEX idx_accounts_status   ON accounts(status);

CREATE TABLE transaction_categories (
    category_id     SERIAL PRIMARY KEY,
    name            TEXT UNIQUE NOT NULL,
    parent_category TEXT
);

CREATE TABLE transactions (
    txn_id      BIGSERIAL PRIMARY KEY,
    account_id  INT  NOT NULL REFERENCES accounts(account_id),
    txn_date    TIMESTAMP NOT NULL,
    txn_type    TEXT NOT NULL CHECK (txn_type IN ('credit','debit')),
    amount      NUMERIC(12,2) NOT NULL,
    channel     TEXT NOT NULL CHECK (channel IN ('online','atm','branch','upi','card','cheque')),
    category_id INT  REFERENCES transaction_categories(category_id),
    merchant    TEXT,
    status      TEXT NOT NULL CHECK (status IN ('success','failed','pending')),
    description TEXT
);
CREATE INDEX idx_txn_account  ON transactions(account_id);
CREATE INDEX idx_txn_date     ON transactions(txn_date);
CREATE INDEX idx_txn_type     ON transactions(txn_type);
CREATE INDEX idx_txn_category ON transactions(category_id);

CREATE TABLE deposits (
    deposit_id    SERIAL PRIMARY KEY,
    account_id    INT NOT NULL REFERENCES accounts(account_id),
    customer_id   INT NOT NULL REFERENCES customers(customer_id),
    principal     NUMERIC(12,2) NOT NULL,
    interest_rate NUMERIC(5,2)  NOT NULL,
    term_months   INT NOT NULL,
    opened_date   DATE NOT NULL,
    maturity_date DATE NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('active','matured','withdrawn'))
);
CREATE INDEX idx_deposits_customer ON deposits(customer_id);

CREATE TABLE loans (
    loan_id        SERIAL PRIMARY KEY,
    customer_id    INT NOT NULL REFERENCES customers(customer_id),
    product_id     INT NOT NULL REFERENCES products(product_id),
    principal      NUMERIC(14,2) NOT NULL,
    interest_rate  NUMERIC(5,2)  NOT NULL,
    term_months    INT NOT NULL,
    emi            NUMERIC(12,2) NOT NULL,
    disbursed_date DATE NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('active','closed','defaulted','overdue'))
);
CREATE INDEX idx_loans_customer ON loans(customer_id);
CREATE INDEX idx_loans_status   ON loans(status);

CREATE TABLE credit_cards (
    card_id         SERIAL PRIMARY KEY,
    customer_id     INT NOT NULL REFERENCES customers(customer_id),
    card_number     TEXT UNIQUE NOT NULL,
    credit_limit    NUMERIC(12,2) NOT NULL,
    current_balance NUMERIC(12,2) NOT NULL DEFAULT 0,
    issued_date     DATE NOT NULL,
    expiry_date     DATE NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('active','blocked','expired'))
);
CREATE INDEX idx_cards_customer ON credit_cards(customer_id);

CREATE TABLE campaigns (
    campaign_id    SERIAL PRIMARY KEY,
    name           TEXT NOT NULL,
    channel        TEXT NOT NULL,           -- email/phone/sms
    target_segment TEXT,                    -- e.g. 'high_income_urban'
    start_date     DATE NOT NULL,
    end_date       DATE NOT NULL,
    budget         NUMERIC(12,2),
    objective      TEXT                     -- e.g. 'term_deposit_signup'
);

CREATE TABLE campaign_contacts (
    contact_id              BIGSERIAL PRIMARY KEY,
    campaign_id             INT  NOT NULL REFERENCES campaigns(campaign_id),
    customer_id             INT  NOT NULL REFERENCES customers(customer_id),
    contact_date            DATE NOT NULL,
    contact_count           INT  NOT NULL DEFAULT 1,
    duration_seconds        INT,
    previous_outcome        TEXT,           -- success/failure/unknown
    days_since_last_contact INT,
    outcome                 TEXT NOT NULL CHECK (outcome IN ('subscribed','not_subscribed','no_response')),
    subscribed              BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX idx_cc_campaign ON campaign_contacts(campaign_id);
CREATE INDEX idx_cc_customer ON campaign_contacts(customer_id);
CREATE INDEX idx_cc_outcome  ON campaign_contacts(outcome);

-- ============================================================
-- Quick sanity view
-- ============================================================
CREATE OR REPLACE VIEW v_table_counts AS
SELECT 'branches'              AS table_name, COUNT(*) FROM branches UNION ALL
SELECT 'employees',                            COUNT(*) FROM employees UNION ALL
SELECT 'products',                             COUNT(*) FROM products UNION ALL
SELECT 'customers',                            COUNT(*) FROM customers UNION ALL
SELECT 'accounts',                             COUNT(*) FROM accounts UNION ALL
SELECT 'transaction_categories',               COUNT(*) FROM transaction_categories UNION ALL
SELECT 'transactions',                         COUNT(*) FROM transactions UNION ALL
SELECT 'deposits',                             COUNT(*) FROM deposits UNION ALL
SELECT 'loans',                                COUNT(*) FROM loans UNION ALL
SELECT 'credit_cards',                         COUNT(*) FROM credit_cards UNION ALL
SELECT 'campaigns',                            COUNT(*) FROM campaigns UNION ALL
SELECT 'campaign_contacts',                    COUNT(*) FROM campaign_contacts;
