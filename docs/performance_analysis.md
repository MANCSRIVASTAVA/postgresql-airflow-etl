# Query Performance Analysis

Measured against the live `retail_db` with the real 541,909-row dataset
loaded (536,639 clean rows → 25,898 invoices, 536,639 invoice_items).
Every number below is `EXPLAIN (ANALYZE, BUFFERS)` output captured before
and after running `sql/03_create_indexes.sql` — nothing here is estimated
or invented.

## Summary

| Query | Before | After | Change |
|---|---|---|---|
| Q1: invoices in a date range, not cancelled | 5.93 ms | 0.89 ms | **~6.7x faster** |
| Q2: top 10 products by revenue | 110.65 ms | 120.03 ms | No real change (noise) |
| Q3: revenue by country | 74.82 ms | 74.80 ms | No real change |
| Q4: full daily sales rollup (305 days) | 222.50 ms | 227.38 ms | No real change |
| Q5: all invoices for one customer | 0.71 ms | 0.075 ms | **~9.4x faster** |

**The honest takeaway: indexing helped the two selective, filtered
queries a lot, and did nothing measurable for the three full-table
aggregation queries.** That's not a failed optimisation — it's exactly
what should be expected, and worth explaining rather than glossing over.

## Why Q1 and Q5 got dramatically faster

Both filter down to a small fraction of the table before doing any real
work — Q1 to one month's non-cancelled invoices (1,683 of 25,898), Q5 to
one customer's invoices (2 of 25,898). Before indexing, Postgres has no
way to find those rows except a sequential scan of the whole table,
checking every row's filter condition. After indexing:

```
Q1 before: Seq Scan on invoices (actual time=0.127..5.860, rows=1683)
Q1 after:  Bitmap Index Scan on idx_invoices_not_cancelled (actual time=0.281, rows=1683)
           -> Bitmap Heap Scan (actual time=0.336..0.792)

Q5 before: Seq Scan on invoices, Filter: customer_id = $0 (actual time=0.080..0.702)
Q5 after:  Bitmap Index Scan on idx_invoices_customer_id (actual time=0.064)
           -> Bitmap Heap Scan (actual time=0.066..0.068)
```

The planner switched from reading every row to reading only the matching
ones via the index — the textbook case an index is for.

## Why Q2, Q3, and Q4 did NOT get faster

All three have to touch nearly every row in `invoice_items` (536,639 of
them) to compute an aggregate (total revenue per product, per country, or
per day) — there's no selective filter to push down into an index. The
plan for Q4 before and after is essentially identical:

```
Before: Seq Scan on invoice_items (actual time=0.027..22.135, rows=536639)
After:  Seq Scan on invoice_items (actual time=0.014..21.375, rows=536639)
```

An index helps Postgres find a *subset* of rows quickly. When the query
needs almost all the rows anyway, a sequential scan reading them in
physical order is already the fastest way to touch them all — using an
index to look them up one at a time would be slower, not faster, and the
planner correctly doesn't try to. The indexes added in `03_create_indexes.sql`
target the columns these aggregation queries filter *before* joining
(`is_cancelled`), which they already do cheaply (1.5ms on `invoices`
alone); the expensive part is downstream, in the join against 536k-row
`invoice_items`, which no index on `invoices` can speed up.

**What would actually help Q2–Q4:** materialising the aggregate instead
of recomputing it from raw rows on every query — which is exactly what
`daily_sales_summary` and `refresh_daily_sales_summary()` do for the
daily rollup (see `docs/er_diagram.md`'s 3NF/denormalisation note). The
same logic would apply to a `top_products_summary` or
`country_revenue_summary` table if those were queried often enough in
production to justify maintaining one.

## Indexes actually applied

See `sql/03_create_indexes.sql` for the full list. Summary: a plain index
on `invoices.invoice_date`, a partial index on non-cancelled invoices by
date (`idx_invoices_not_cancelled`), indexes on `invoices.customer_id` and
`invoices.country_id`, and on `invoice_items.invoice_id`/`product_id`.
`EXPLAIN` confirms `idx_invoices_not_cancelled` and
`idx_invoices_customer_id` are the two actually used by the planner for
the query shapes tested above.
