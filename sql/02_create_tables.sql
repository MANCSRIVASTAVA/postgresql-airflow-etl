-- staging.raw_staging: one row per line in the source file, after
-- transform.py has cleaned types and flagged cancellations/returns but
-- before anything is split into the dimensional model. source_row_number
-- is the position of the row in the original extract — it is the natural
-- key every downstream load keys off, so reruns upsert instead of
-- duplicating. No foreign keys here on purpose: this table has to accept
-- whatever transform.py hands it, including rows later rejected as
-- invalid, so load_dimensions/load_transactions can decide what to do
-- with them rather than having the database silently refuse the insert.
CREATE TABLE IF NOT EXISTS staging.raw_staging (
    id                 BIGSERIAL PRIMARY KEY,
    source_row_number  BIGINT NOT NULL,
    invoice_no         TEXT,
    stock_code         TEXT,
    description        TEXT,
    quantity           INTEGER,
    invoice_date       TIMESTAMP,
    unit_price         NUMERIC(10, 2),
    customer_identifier TEXT,
    country_name       TEXT,
    is_cancelled       BOOLEAN,
    line_revenue       NUMERIC(14, 2),
    loaded_at          TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_raw_staging_source_row UNIQUE (source_row_number)
);

CREATE TABLE IF NOT EXISTS countries (
    country_id   SERIAL PRIMARY KEY,
    country_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS customers (
    customer_id         SERIAL PRIMARY KEY,
    customer_identifier TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS products (
    product_id  SERIAL PRIMARY KEY,
    stock_code  TEXT NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE IF NOT EXISTS invoices (
    invoice_id     SERIAL PRIMARY KEY,
    invoice_number TEXT NOT NULL UNIQUE,
    customer_id    INTEGER REFERENCES customers(customer_id),
    country_id     INTEGER NOT NULL REFERENCES countries(country_id),
    invoice_date   TIMESTAMP NOT NULL,
    is_cancelled   BOOLEAN NOT NULL DEFAULT FALSE
);

-- source_row_number ties each line item back to its exact row in the
-- original file, giving loads a real natural key to upsert on instead of
-- guessing from (invoice, product) pairs, which the source file does not
-- guarantee are unique (the same product can legitimately appear twice on
-- one invoice).
CREATE TABLE IF NOT EXISTS invoice_items (
    invoice_item_id   BIGSERIAL PRIMARY KEY,
    invoice_id        INTEGER NOT NULL REFERENCES invoices(invoice_id),
    product_id        INTEGER NOT NULL REFERENCES products(product_id),
    source_row_number BIGINT NOT NULL UNIQUE,
    quantity          INTEGER NOT NULL,
    unit_price        NUMERIC(10, 2) NOT NULL
);

-- Deliberately denormalised reporting aggregate (see docs/architecture.md
-- for the 3NF-vs-denormalisation rationale). Refreshed wholesale per date
-- by sql/05_create_procedures.sql, not accumulated incrementally, so a
-- rerun can never double-count a day.
CREATE TABLE IF NOT EXISTS daily_sales_summary (
    sales_date     DATE PRIMARY KEY,
    total_orders   INTEGER NOT NULL,
    total_quantity INTEGER NOT NULL,
    total_revenue  NUMERIC(14, 2) NOT NULL,
    refreshed_at   TIMESTAMP NOT NULL DEFAULT now()
);
