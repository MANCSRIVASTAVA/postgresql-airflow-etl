# Architecture

## Components

```
                    +------------------+
                    |  Online Retail   |
                    |     .xlsx        |
                    +--------+---------+
                             |  read-only
                             v
  +--------------------------------------------------------+
  |                  Airflow (LocalExecutor)                |
  |  extract -> validate -> transform -> load_staging        |
  |  -> load_dimensions -> load_transactions                 |
  |  -> generate_daily_summary -> run_quality_checks          |
  |                                                            |
  |  Parquet files on a shared volume between tasks            |
  |  (data_processed/), never through XCom                     |
  +---------------------------+--------------------------------+
                              |
                              v
                  +-----------------------+
                  |  Postgres container    |
                  |  - airflow DB (meta)   |
                  |  - retail_db (ETL)     |
                  +-----------------------+
```

Two logically separate databases share one Postgres container: `airflow`
(Airflow's own scheduling metadata) and `retail_db` (this project's actual
data). That's a deliberate resource-saving choice for a local, single-
machine project — a production deployment would very likely put them on
separate instances so Airflow's own load never competes with the
application database's.

## Why LocalExecutor, not CeleryExecutor

Airflow's official Docker Compose template defaults to CeleryExecutor
with Redis and a separate worker service — built for distributing task
execution across multiple machines. On one machine, that's solving a
problem that doesn't exist here, at the cost of running Redis and an
extra process. LocalExecutor lets the scheduler run tasks directly, which
is the documented, correct choice for a single-machine setup, and cuts
the stack from ~8 services to 5 (`postgres`, `airflow-init`,
`airflow-apiserver`, `airflow-scheduler`, `airflow-dag-processor`). The
`airflow-dag-processor` is still a separate, mandatory component even
without Celery — Airflow 3 requires it in every deployment, specifically
so the scheduler never has to execute DAG-author code directly.

## Why a custom Dockerfile

The stock `apache/airflow:3.4.0` image only has Airflow's own
dependencies. This project's DAG imports `pandas`, `openpyxl`,
`sqlalchemy`, and `psycopg` — none of which ship with the base image. The
`Dockerfile` extends it and installs `requirements.txt` at build time,
rather than using `_PIP_ADDITIONAL_REQUIREMENTS` (which the official
compose docs themselves warn is "ONLY for quick checks" — it reinstalls
on every container start).

## Staging vs. curated schema

`staging.raw_staging` has no constraints — it has to accept whatever
`transform.py` hands it, including validated-but-imperfect data, without
the database rejecting a row before `validation.py` gets a chance to
evaluate it. The curated tables (`public.customers`, `countries`,
`products`, `invoices`, `invoice_items`) carry real PK/FK/UNIQUE/NOT NULL
constraints, because by the time data reaches them it's supposed to be
trustworthy — a constraint violation there is the database catching a
real bug, not rejecting ordinary messy input.

## Idempotency

Every load is keyed on a natural identifier that exists independently of
any surrogate ID the database assigns:

- `staging.raw_staging`: truncated and fully reloaded every run — it's a
  landing zone, not a system of record, so a full overwrite is simpler
  than an upsert and exactly as idempotent.
- `countries`/`customers`/`products`: upserted on `country_name` /
  `customer_identifier` / `stock_code`.
- `invoices`: upserted on `invoice_number`.
- `invoice_items`: upserted on `source_row_number` — the original row's
  position in the source file, which never changes between runs.

Rerunning the whole pipeline on the same file always lands on the same
rows instead of duplicating them, whether that rerun happens because of
an Airflow retry, a manual re-trigger, or a backfill.

## Intermediate data: Parquet, not XCom

Airflow's XCom mechanism is backed by the metadata database — it's built
for small values (a row count, a summary dict), not a 500k-row dataset.
Pushing the whole extracted/transformed DataFrame through XCom would mean
serialising it into Airflow's own Postgres database as task metadata.
Instead, each task writes a Parquet file to a shared volume
(`data_processed/`), and the next task reads it back — only small values
(counts, a results dict) actually travel through XCom.
