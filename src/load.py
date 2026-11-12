"""Loads transformed data into retail_db.

Idempotency, in one sentence: every load keys off a natural key that
exists independently of any surrogate ID the database assigns —
source_row_number for staging/invoice_items, invoice_number for invoices,
stock_code/country_name/customer_identifier for dimensions — so running
the whole pipeline twice on the same source file always upserts onto the
same rows instead of inserting them again. staging.raw_staging is the one
exception: it's truncated and fully reloaded each run, which is trivially
idempotent since it's a landing table, not a system of record.
"""

import logging

import pandas as pd
from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

from src.database import get_raw_connection

logger = logging.getLogger(__name__)

STAGING_COPY_COLUMNS = [
    "source_row_number",
    "invoice_no",
    "stock_code",
    "description",
    "quantity",
    "invoice_date",
    "unit_price",
    "customer_identifier",
    "country_name",
    "is_cancelled",
    "line_revenue",
]


def _row_to_native(row) -> tuple:
    return (
        int(row.source_row_number),
        row.invoice_no,
        row.stock_code,
        None if pd.isna(row.description) else str(row.description),
        int(row.quantity),
        row.invoice_date.to_pydatetime(),
        float(row.unit_price),
        row.customer_identifier,
        row.country_name,
        bool(row.is_cancelled),
        float(row.line_revenue),
    )


def load_staging(clean_df: pd.DataFrame) -> int:
    """Truncate-and-reload: staging is a landing zone, so a full overwrite
    every run is simpler than upserting and just as idempotent.
    """
    conn = get_raw_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE staging.raw_staging")
            cols_sql = ", ".join(STAGING_COPY_COLUMNS)
            with cur.copy(f"COPY staging.raw_staging ({cols_sql}) FROM STDIN") as copy:
                for row in clean_df.itertuples(index=False):
                    copy.write_row(_row_to_native(row))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    logger.info("Loaded %d rows into staging.raw_staging", len(clean_df))
    return len(clean_df)


def load_dimensions(engine: Engine, clean_df: pd.DataFrame) -> dict[str, int]:
    metadata = MetaData()
    countries_t = Table("countries", metadata, autoload_with=engine)
    customers_t = Table("customers", metadata, autoload_with=engine)
    products_t = Table("products", metadata, autoload_with=engine)

    countries = sorted(clean_df["country_name"].dropna().unique().tolist())
    customers = sorted(clean_df["customer_identifier"].dropna().unique().tolist())

    # First non-null description seen for a stock_code wins; later variants
    # for the same code (a known data quality issue in the source) are not
    # used to overwrite it.
    products = (
        clean_df.dropna(subset=["stock_code"])
        .sort_values("source_row_number")
        .groupby("stock_code", as_index=False)
        .first()[["stock_code", "description"]]
    )
    products["description"] = products["description"].where(products["description"].notna(), None)

    with engine.begin() as conn:
        if countries:
            stmt = pg_insert(countries_t).values([{"country_name": c} for c in countries])
            conn.execute(stmt.on_conflict_do_nothing(index_elements=["country_name"]))
        if customers:
            stmt = pg_insert(customers_t).values([{"customer_identifier": c} for c in customers])
            conn.execute(stmt.on_conflict_do_nothing(index_elements=["customer_identifier"]))
        if len(products):
            stmt = pg_insert(products_t).values(products.to_dict(orient="records"))
            conn.execute(stmt.on_conflict_do_nothing(index_elements=["stock_code"]))

    logger.info("Loaded dimensions: %d countries, %d customers, %d products", len(countries), len(customers), len(products))
    return {"countries": len(countries), "customers": len(customers), "products": len(products)}


def load_transactions(engine: Engine, clean_df: pd.DataFrame) -> dict[str, int]:
    metadata = MetaData()
    invoices_t = Table("invoices", metadata, autoload_with=engine)
    countries_t = Table("countries", metadata, autoload_with=engine)
    customers_t = Table("customers", metadata, autoload_with=engine)
    products_t = Table("products", metadata, autoload_with=engine)

    with engine.begin() as conn:
        country_map = dict(conn.execute(select(countries_t.c.country_name, countries_t.c.country_id)).all())
        customer_map = dict(conn.execute(select(customers_t.c.customer_identifier, customers_t.c.customer_id)).all())
        product_map = dict(conn.execute(select(products_t.c.stock_code, products_t.c.product_id)).all())

    invoice_rows = clean_df.copy()
    invoice_rows["country_id"] = invoice_rows["country_name"].map(country_map)
    invoice_rows["customer_id"] = invoice_rows["customer_identifier"].map(customer_map)

    invoices_agg = (
        invoice_rows.sort_values("source_row_number")
        .groupby("invoice_no", as_index=False)
        .agg(
            country_id=("country_id", "first"),
            customer_id=("customer_id", "first"),
            invoice_date=("invoice_date", "min"),
            is_cancelled=("is_cancelled", "first"),
        )
        .rename(columns={"invoice_no": "invoice_number"})
    )
    invoices_agg["customer_id"] = invoices_agg["customer_id"].where(invoices_agg["customer_id"].notna(), None)

    with engine.begin() as conn:
        stmt = pg_insert(invoices_t).values(invoices_agg.to_dict(orient="records"))
        stmt = stmt.on_conflict_do_update(
            index_elements=["invoice_number"],
            set_={
                "customer_id": stmt.excluded.customer_id,
                "country_id": stmt.excluded.country_id,
                "invoice_date": stmt.excluded.invoice_date,
                "is_cancelled": stmt.excluded.is_cancelled,
            },
        )
        conn.execute(stmt)
        invoice_map = dict(conn.execute(select(invoices_t.c.invoice_number, invoices_t.c.invoice_id)).all())

    invoice_items_rows = clean_df[["source_row_number", "invoice_no", "stock_code", "quantity", "unit_price"]].copy()
    invoice_items_rows["invoice_id"] = invoice_items_rows["invoice_no"].map(invoice_map)
    invoice_items_rows["product_id"] = invoice_items_rows["stock_code"].map(product_map)

    loaded_count = _bulk_upsert_invoice_items(invoice_items_rows)

    logger.info("Loaded %d invoices, %d invoice_items", len(invoices_agg), loaded_count)
    return {"invoices": len(invoices_agg), "invoice_items": loaded_count}


def _bulk_upsert_invoice_items(rows: pd.DataFrame) -> int:
    """COPY into a temp table, then upsert from the temp table into
    invoice_items in a single statement — the standard way to bulk-upsert
    hundreds of thousands of rows in Postgres without round-tripping one
    row at a time.
    """
    conn = get_raw_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TEMP TABLE temp_invoice_items (
                    source_row_number BIGINT,
                    invoice_id INTEGER,
                    product_id INTEGER,
                    quantity INTEGER,
                    unit_price NUMERIC(10, 2)
                ) ON COMMIT DROP
                """
            )
            with cur.copy(
                "COPY temp_invoice_items (source_row_number, invoice_id, product_id, quantity, unit_price) FROM STDIN"
            ) as copy:
                for row in rows.itertuples(index=False):
                    copy.write_row(
                        (
                            int(row.source_row_number),
                            int(row.invoice_id),
                            int(row.product_id),
                            int(row.quantity),
                            float(row.unit_price),
                        )
                    )
            cur.execute(
                """
                INSERT INTO invoice_items (invoice_id, product_id, source_row_number, quantity, unit_price)
                SELECT invoice_id, product_id, source_row_number, quantity, unit_price
                FROM temp_invoice_items
                ON CONFLICT (source_row_number) DO UPDATE
                    SET invoice_id = EXCLUDED.invoice_id,
                        product_id = EXCLUDED.product_id,
                        quantity = EXCLUDED.quantity,
                        unit_price = EXCLUDED.unit_price
                """
            )
            loaded = cur.rowcount
        conn.commit()
        return loaded
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def generate_daily_summary(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("CALL refresh_daily_sales_summary()"))
    logger.info("Refreshed daily_sales_summary")
