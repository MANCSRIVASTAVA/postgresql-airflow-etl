# Data Dictionary

## staging.raw_staging

One row per source line, after `transform.py` has cleaned it but before
it's split into the dimensional model. No foreign keys — see
`docs/architecture.md` for why.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| id | BIGSERIAL PK | no | surrogate key |
| source_row_number | BIGINT | no | position of this row in the original source file; UNIQUE; the natural key every downstream load keys off |
| invoice_no | TEXT | yes | `C`-prefix marks a cancellation |
| stock_code | TEXT | yes | |
| description | TEXT | yes | the source has stock codes with no description on some rows |
| quantity | INTEGER | yes | negative = legitimate return (never deleted) |
| invoice_date | TIMESTAMP | yes | |
| unit_price | NUMERIC(10,2) | yes | |
| customer_identifier | TEXT | yes | NULL = guest/unlinked purchase |
| country_name | TEXT | yes | |
| is_cancelled | BOOLEAN | yes | derived from `invoice_no` |
| line_revenue | NUMERIC(14,2) | yes | `quantity * unit_price` |
| loaded_at | TIMESTAMP | no | defaults to `now()` |

## countries

| Column | Type | Nullable | Notes |
|---|---|---|---|
| country_id | SERIAL PK | no | |
| country_name | TEXT | no | UNIQUE |

## customers

| Column | Type | Nullable | Notes |
|---|---|---|---|
| customer_id | SERIAL PK | no | |
| customer_identifier | TEXT | no | UNIQUE; the original `CustomerID` from the source, stored as text |

## products

| Column | Type | Nullable | Notes |
|---|---|---|---|
| product_id | SERIAL PK | no | |
| stock_code | TEXT | no | UNIQUE |
| description | TEXT | yes | the first non-null description seen for a stock_code wins; later variants (a known source data quality issue) don't overwrite it |

## invoices

| Column | Type | Nullable | Notes |
|---|---|---|---|
| invoice_id | SERIAL PK | no | |
| invoice_number | TEXT | no | UNIQUE |
| customer_id | INTEGER FK -> customers | yes | nullable: guest/unlinked purchases have no customer |
| country_id | INTEGER FK -> countries | no | |
| invoice_date | TIMESTAMP | no | |
| is_cancelled | BOOLEAN | no | default FALSE; derived from `invoice_number` starting with `C` |

## invoice_items

| Column | Type | Nullable | Notes |
|---|---|---|---|
| invoice_item_id | BIGSERIAL PK | no | |
| invoice_id | INTEGER FK -> invoices | no | |
| product_id | INTEGER FK -> products | no | |
| source_row_number | BIGINT | no | UNIQUE; ties this row back to its exact position in the source file |
| quantity | INTEGER | no | negative = return |
| unit_price | NUMERIC(10,2) | no | |

Revenue (`quantity * unit_price`) is deliberately **not** stored here —
it's computed wherever it's needed, so there's no derived value that can
drift out of sync with its inputs.

## daily_sales_summary

Deliberately denormalised reporting rollup — see `docs/er_diagram.md`.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| sales_date | DATE PK | no | |
| total_orders | INTEGER | no | distinct invoices that day, excluding cancelled |
| total_quantity | INTEGER | no | |
| total_revenue | NUMERIC(14,2) | no | |
| refreshed_at | TIMESTAMP | no | default `now()`; updated by `refresh_daily_sales_summary()` |

## Views

- **vw_daily_sales** — daily revenue/orders/quantity, excluding cancelled invoices.
- **vw_monthly_sales** — same, grouped by month.
- **vw_top_products** — revenue/quantity sold per product, excluding cancelled invoices.

## Procedures

- **refresh_daily_sales_summary()** — upserts `daily_sales_summary` from
  `vw_daily_sales`, keyed on `sales_date`. Idempotent: calling it twice in
  a row produces the same totals, not doubled ones.
