# Interview Prep

Everything here is grounded in a decision actually made somewhere in this
repository — not generic trivia. Each answer names the file it comes from
so you can go re-read the real code if you want more depth.

## 20 Data Engineering interview questions and answers

**1. Why separate a staging schema from the curated tables?**
`staging.raw_staging` (`sql/01_create_schema.sql`, `sql/02_create_tables.sql`)
has no constraints — it has to accept whatever `transform.py` produces,
including edge cases, without the database rejecting a row before
`validation.py` gets to evaluate it. The curated tables carry real
PK/FK/UNIQUE/NOT NULL constraints because by the time data reaches them
it's supposed to be trustworthy.

**2. How do you make an ETL pipeline idempotent?**
Key every load on a natural identifier that exists independently of any
surrogate ID the database assigns: `source_row_number` for
staging/invoice_items, `invoice_number` for invoices,
`stock_code`/`country_name`/`customer_identifier` for dimensions
(`src/load.py`). Rerunning the whole pipeline on the same file always
upserts onto the same rows instead of duplicating them.

**3. Why truncate-and-reload staging but upsert everything downstream?**
Staging isn't a system of record — it's re-derived fresh from the source
file every run, so a full overwrite is simpler and exactly as idempotent
as an upsert. The curated tables *are* the system of record, so upserting
preserves anything a later run doesn't touch.

**4. How do you bulk-load 500k+ rows into Postgres efficiently?**
Server-side `COPY` instead of row-by-row `INSERT`s. For the upsert case
(`invoice_items`), `COPY` into a temp table, then one
`INSERT ... SELECT ... ON CONFLICT` statement (`src/load.py`,
`_bulk_upsert_invoice_items`) — one round trip instead of 500k.

**5. What's the Postgres bound-parameter limit, and how did it bite you?**
~65,535 parameters per query. A single multi-row `INSERT` for ~25,900
invoices (5 columns each) exceeded it. Fixed by batching into chunks of
1,000 (`_chunked()` in `src/load.py`) — a real bug found by actually
running the code against the real data volume, not by reading it.

**6. How do cancellations and returns affect revenue calculations, and
how do you avoid double-counting?**
An `InvoiceNo` starting with `C` marks the whole invoice cancelled —
excluded entirely from every revenue view/query (`sql/04_create_views.sql`).
A negative-quantity line on a *non-cancelled* invoice is a legitimate
return, kept, and nets out of revenue on its own since
`quantity * unit_price` is negative. Never delete negative-quantity rows
blindly — that would silently discard real transaction history.

**7. Why is `invoice_items` missing a `line_revenue` column when
`staging.raw_staging` has one?**
3NF reasoning: revenue is `quantity * unit_price`, fully derivable from
columns already in the row. Storing it again in the curated table would
be a value that can drift out of sync with its inputs. `daily_sales_summary`
is the one deliberate exception — a denormalised reporting rollup,
refreshed wholesale, not incrementally.

**8. What's the difference between 3NF and the denormalisation used
here?**
3NF: every non-key column depends on the whole key and nothing but the
key — true for `customers`, `countries`, `products`, `invoices`,
`invoice_items`. `daily_sales_summary` deliberately breaks this: it
duplicates information derivable from `invoices`/`invoice_items`, because
recomputing "yesterday's revenue" from 500k+ raw rows on every dashboard
load is wasted work once a day's numbers are final.

**9. Why does Airflow 3 require a separate DAG processor process?**
So the scheduler never executes DAG-author code directly — a buggy or
compromised DAG file can't take down the component responsible for
scheduling every other DAG (confirmed from the official Airflow 3
architecture docs, not assumed).

**10. Why does this project avoid passing data through XCom?**
XCom is backed by the metadata database — built for small values (a row
count, a summary dict), not a 500k-row dataset. This DAG passes
intermediate data as Parquet files on a shared volume
(`dags/retail_etl_pipeline.py`); only small values travel through XCom.

**11. Why LocalExecutor instead of the Celery default?**
CeleryExecutor distributes task execution across multiple worker
machines — solving a problem that doesn't exist on one machine, at the
cost of running Redis and a separate worker process. LocalExecutor is the
documented, correct choice for a single-machine deployment, and cuts the
stack from ~8 services to 5.

**12. How did you choose which columns to index?**
By the query patterns actually used, not by guessing — indexed
`invoices.invoice_date`, `customer_id`, `country_id` (looked up by value,
not just uniqueness), plus a partial index on non-cancelled invoices by
date. PK/UNIQUE constraints already gave free indexes on
`invoice_number`, `stock_code`, `customer_identifier`, `country_name`.

**13. Does adding an index always make a query faster?**
No — measured, not assumed, in this project (`docs/performance_analysis.md`).
Two selective queries got 6-9x faster. Three full-table aggregation
queries (top products, revenue by country, the full daily rollup) showed
no real improvement, because they touch nearly every row in
`invoice_items` regardless of what's indexed — an index helps the planner
skip rows, and there's nothing to skip when the query needs almost all of
them.

**14. How do you read an `EXPLAIN ANALYZE` plan?**
Bottom-up — the innermost node runs first. Compare `actual time` to the
planner's `cost` estimate (a big gap means stale statistics). `Seq Scan`
vs. `Bitmap Index Scan`/`Index Scan` shows whether an index was usable.
`Rows Removed by Filter` shows how selective a filter actually was.

**15. How do you validate a data source before building a pipeline
against it?**
Inspect structure, schema, and volume first — this project parsed the
raw `.xlsx` (a ZIP of XML) directly to confirm sheet name, 8 expected
columns, and the exact row count (541,909) before writing any extraction
code or even installing pandas.

**16. What's a real example of a data quality issue you had to design
around, not just filter out?**
`StockCode`, `InvoiceNo`, and `Description` all came back from
`openpyxl` with mixed Python types in the same column — a numeric-looking
value (`20713`) reads as `int`, an alphanumeric one (`85123A`, `C536379`)
reads as `str`. Pandas tolerates this; every downstream dict-based lookup
and Parquet serialization doesn't. Fixed by normalising to `str`
immediately in `extract()`, guarding real missing values with
`pd.notna()` so `NaN` isn't turned into the literal string `"nan"`.

**17. Why mock the database in `test_validation.py` instead of using a
real test database?**
`run_quality_checks`'s logic (does it raise on a referential-integrity
violation, does it compute the report correctly) depends on what
`conn.exec_driver_sql(...).scalar_one()` returns — a mock dictates that
directly and deterministically, without the cost of a real database per
test run.

**18. Why do unit tests use a 2-row synthetic fixture instead of the real
541k-row file?**
A unit test's job is to pin down one rule in isolation (e.g. "is a
zero-quantity row rejected?"). A hand-built fixture makes that assertion
exact and any failure legible. The real dataset's job is end-to-end
verification, not unit testing — a 541k-row fixture would be slow and
wouldn't test anything a 2-row one can't.

**19. How do you verify a backup is actually recoverable?**
Restore it, then check the data is actually there — not just that
`pg_restore` exited 0. This project's `restore.sh` checks
`invoice_items`'s row count after every restore; `pg_restore` can
succeed while still producing an empty database if something upstream
silently failed.

**20. What's the difference between testing code locally and testing it
in its real deployment environment, and why does it matter?**
They're different claims. Running the ETL pipeline from a manual script
in a local venv passed completely — but the actual Airflow container was
missing every one of this project's Python dependencies entirely (the
base Airflow image only ships Airflow's own deps), and running the real
DAG exercised a code path (`extract.run()`'s Parquet write) the manual
script never touched, surfacing three more real bugs. "It works on my
machine" and "it works where it actually runs" are not the same claim.

## SQL queries worth practising

All in `sql/06_analytics_queries.sql` — practice writing each from
scratch, then compare:
1. Daily revenue (date-grouped aggregate, excluding cancellations)
2. Monthly revenue (same, `date_trunc`)
3. Top 10 products by revenue (`ORDER BY ... DESC LIMIT 10`)
4. Top 10 customers by revenue (3-way join + aggregate)
5. Revenue by country (3-way join + aggregate, different grouping key)
6. Total vs. cancelled invoice counts (`COUNT(*) FILTER (WHERE ...)`)
7. Cancelled invoices detail query
8. Product returns (negative-quantity lines on non-cancelled invoices)

Also worth practising: the `refresh_daily_sales_summary()` upsert
procedure (`sql/05_create_procedures.sql`) — `INSERT ... ON CONFLICT DO
UPDATE`, and why that's idempotent where a plain `INSERT` wouldn't be.

## Python concepts used

- pandas: `read_excel`, dtype inference pitfalls (mixed int/str columns),
  `groupby().agg()` with named aggregations, `duplicated(subset=...)`,
  vectorised boolean masking for validation rules, Parquet I/O via pyarrow
- SQLAlchemy 2.0 Core (not the ORM): `MetaData`/`Table` reflection,
  `sqlalchemy.dialects.postgresql.insert` for `ON CONFLICT` upserts,
  `engine.begin()` transaction context managers
- psycopg 3: raw connections for server-side `COPY`, separate from the
  SQLAlchemy-pooled connection used everywhere else
- Type normalisation: `pd.notna()`-guarded casts, native Python
  int/float/bool conversion before handing values to a DB driver
  (`_row_to_native()` in `src/load.py`)
- pytest: fixtures via `tmp_path`, `unittest.mock.MagicMock` for faking a
  SQLAlchemy engine/connection, `pytest.raises(..., match=...)`
- Environment/config: `python-dotenv`, never hardcoding secrets

## Airflow concepts used

- TaskFlow API (`@dag`, `@task` decorators) vs. classic operators
- Airflow 3 architecture: mandatory separate `dag-processor`, the
  `execution-api-server` URL tasks talk to regardless of executor
- LocalExecutor vs. CeleryExecutor trade-offs
- XCom (what it's for — small values) vs. shared-volume files (what
  they're for — datasets)
- `retries` / `retry_delay` in `default_args`
- `schedule`, `catchup=False`, manual triggering (`airflow dags trigger`)
- Task dependency wiring: mixing data-passing (`task(arg)`) with
  explicit `>>` ordering where no data actually needs to pass
- Reading task logs and `airflow tasks states-for-dag-run` /
  `airflow dags list-import-errors` for real debugging, not guessing

## Screenshot checklist for the GitHub README

- [ ] Airflow UI: DAG graph view for `retail_etl_pipeline`
- [ ] Airflow UI: a successful DAG run (all 8 tasks green)
- [ ] A query result or table browser view of `retail_db`'s tables
- [ ] `EXPLAIN ANALYZE` output for one before/after indexing comparison
- [ ] Terminal output of `pytest -q` showing 34 passed
- [ ] The ER diagram (already in `docs/er_diagram.md` as Mermaid — a
      rendered screenshot is a nice-to-have, not required)
