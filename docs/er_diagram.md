# Entity-Relationship Diagram

```mermaid
erDiagram
    CUSTOMERS ||--o{ INVOICES : places
    COUNTRIES ||--o{ INVOICES : "billed from"
    INVOICES ||--|{ INVOICE_ITEMS : contains
    PRODUCTS ||--o{ INVOICE_ITEMS : "sold as"

    CUSTOMERS {
        int customer_id PK
        text customer_identifier
    }
    COUNTRIES {
        int country_id PK
        text country_name
    }
    PRODUCTS {
        int product_id PK
        text stock_code
        text description
    }
    INVOICES {
        int invoice_id PK
        text invoice_number
        int customer_id FK
        int country_id FK
        timestamp invoice_date
        bool is_cancelled
    }
    INVOICE_ITEMS {
        bigint invoice_item_id PK
        int invoice_id FK
        int product_id FK
        bigint source_row_number
        int quantity
        numeric unit_price
    }
    DAILY_SALES_SUMMARY {
        date sales_date PK
        int total_orders
        int total_quantity
        numeric total_revenue
    }
```

## 3NF vs. deliberate denormalisation

`customers`, `countries`, `products`, `invoices` and `invoice_items` are in
3NF: every non-key column depends on the whole key and nothing but the key.
Revenue is never stored on `invoice_items` — it's `quantity * unit_price`,
computed wherever it's needed, so there's no derived value that can drift
out of sync with its inputs.

`daily_sales_summary` is the one deliberate exception. It's a materialised,
denormalised rollup that duplicates information already derivable from
`invoices`/`invoice_items`, and it's refreshed wholesale per date by
`refresh_daily_sales_summary()` rather than kept normalised. That's a
reporting-table trade-off, not an oversight: scanning 500k+ line items to
answer "what was yesterday's revenue" every time a dashboard loads is wasted
work once the numbers for a closed day are final.
