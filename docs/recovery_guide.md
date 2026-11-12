# Backup & Recovery Guide

## Taking a backup

```bash
./scripts/backup.sh
```

Runs `pg_dump` inside the running `postgres` container (custom format,
`-F c`) and copies the result out to `backups/retail_db_<timestamp>.dump`.
`backups/` is gitignored — backups are a local/operational artifact, not
something that belongs in version control.

Requires the `postgres` container to be up (`docker compose up -d postgres`)
and a valid `.env` in the project root.

## Restoring a backup

```bash
./scripts/restore.sh backups/retail_db_20261112_120046.dump
```

Copies the dump file into the container, runs `pg_restore --clean --if-exists`
(drops and recreates every object the dump contains before restoring it, so
restoring over an already-populated database doesn't leave stale rows behind),
then verifies the restore actually landed data by checking that
`invoice_items` isn't empty afterward — a non-zero exit code from
`pg_restore` alone isn't proof the data actually materialised.

## Verified for real, not assumed

Ran both scripts back-to-back against the live `retail_db` (541,909-row
dataset already loaded): `backup.sh` produced a 17MB dump; `restore.sh`
restored it and confirmed `invoice_items` held exactly 536,639 rows
afterward, matching the pre-backup count. Row counts for every table,
both views, and the `refresh_daily_sales_summary` procedure were checked
directly afterward and matched the pre-restore state exactly:

| Object | Count after restore |
|---|---|
| `customers` | 4,372 |
| `countries` | 38 |
| `products` | 4,070 |
| `invoices` | 25,898 |
| `invoice_items` | 536,639 |
| `daily_sales_summary` | 305 |
| Views | `vw_daily_sales`, `vw_monthly_sales`, `vw_top_products` — all present |
| Procedures | `refresh_daily_sales_summary` — present |

## Restoring onto a fresh database

If `retail_db` doesn't exist yet at all (a new machine, a rebuilt
container), bring the stack up first so the role/database exist, then run
`restore.sh` as above — `--clean --if-exists` tolerates an empty target
database just as well as a populated one.

## What this doesn't cover

This is a manual, on-demand backup — there's no scheduled backup job in
this project. A production system would run `backup.sh` on a schedule
(e.g. an Airflow DAG or a cron job) and ship backups off the host
machine, not just into a local `backups/` folder.
