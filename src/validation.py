"""Data quality checks. Anything flagged 'critical' here raises
ValidationError, and the caller (the Airflow task) lets that propagate so
the task actually fails instead of a bad run looking green.
"""

import logging

import pandas as pd
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when a critical data quality check fails."""


def check_missing_core_fields(df: pd.DataFrame, columns: list[str]) -> dict[str, int]:
    return {col: int(df[col].isna().sum()) for col in columns if col in df.columns}


def check_duplicate_source_rows(df: pd.DataFrame) -> int:
    """clean_df should have exactly one row per source_row_number — if not,
    something in transform.py produced duplicates, which is a bug, not a
    data quality issue in the source.
    """
    return int(df["source_row_number"].duplicated().sum())


def check_invalid_dates(df: pd.DataFrame) -> int:
    return int(df["invoice_date"].isna().sum())


def check_invalid_quantity(df: pd.DataFrame) -> int:
    return int((df["quantity"] == 0).sum())


def check_invalid_price(df: pd.DataFrame) -> int:
    return int((df["unit_price"] < 0).sum())


def check_referential_integrity(engine: Engine) -> dict[str, int]:
    """Belt-and-suspenders check: FK constraints already prevent orphans at
    insert time, but this confirms it explicitly rather than trusting that
    nothing bypassed them.
    """
    queries = {
        "invoice_items_orphaned_invoice": """
            SELECT COUNT(*) FROM invoice_items ii
            LEFT JOIN invoices i ON i.invoice_id = ii.invoice_id
            WHERE i.invoice_id IS NULL
        """,
        "invoice_items_orphaned_product": """
            SELECT COUNT(*) FROM invoice_items ii
            LEFT JOIN products p ON p.product_id = ii.product_id
            WHERE p.product_id IS NULL
        """,
        "invoices_orphaned_country": """
            SELECT COUNT(*) FROM invoices i
            LEFT JOIN countries c ON c.country_id = i.country_id
            WHERE c.country_id IS NULL
        """,
    }
    results = {}
    with engine.connect() as conn:
        for name, sql in queries.items():
            results[name] = conn.exec_driver_sql(sql).scalar_one()
    return results


def reconcile_record_counts(extracted_count: int, clean_count: int, rejected_count: int) -> bool:
    """Every extracted row must be accounted for as either clean or
    rejected — if the numbers don't add up, rows disappeared silently
    somewhere in transform.py.
    """
    return extracted_count == clean_count + rejected_count


def run_quality_checks(
    engine: Engine,
    extracted_count: int,
    clean_df: pd.DataFrame,
    rejected_df: pd.DataFrame,
    loaded_invoice_items_count: int,
) -> dict:
    """Runs every check, logs the full report, and raises ValidationError
    if any critical check fails.
    """
    report: dict = {
        "extracted_count": extracted_count,
        "clean_count": len(clean_df),
        "rejected_count": len(rejected_df),
        "rejection_reasons": rejected_df["rejection_reason"].value_counts().to_dict() if len(rejected_df) else {},
        "duplicate_source_rows_in_clean": check_duplicate_source_rows(clean_df),
        "invalid_dates_in_clean": check_invalid_dates(clean_df),
        "invalid_quantity_in_clean": check_invalid_quantity(clean_df),
        "invalid_price_in_clean": check_invalid_price(clean_df),
        "referential_integrity": check_referential_integrity(engine),
        "counts_reconcile": reconcile_record_counts(extracted_count, len(clean_df), len(rejected_df)),
        "loaded_invoice_items_count": loaded_invoice_items_count,
        "load_matches_clean_count": loaded_invoice_items_count == len(clean_df),
    }

    logger.info("Validation report: %s", report)

    failures = []
    if report["duplicate_source_rows_in_clean"] > 0:
        failures.append("duplicate source_row_number values in clean data")
    if report["invalid_dates_in_clean"] > 0:
        failures.append("unparsed invoice_date values survived into clean data")
    if report["invalid_quantity_in_clean"] > 0:
        failures.append("zero-quantity rows survived into clean data")
    if report["invalid_price_in_clean"] > 0:
        failures.append("negative-price rows survived into clean data")
    if any(v > 0 for v in report["referential_integrity"].values()):
        failures.append(f"referential integrity violations: {report['referential_integrity']}")
    if not report["counts_reconcile"]:
        failures.append(
            f"extracted ({extracted_count}) != clean ({len(clean_df)}) + rejected ({len(rejected_df)})"
        )
    if not report["load_matches_clean_count"]:
        failures.append(
            f"loaded invoice_items ({loaded_invoice_items_count}) != clean rows ({len(clean_df)})"
        )

    if failures:
        raise ValidationError("Critical data quality failure(s): " + "; ".join(failures))

    return report
