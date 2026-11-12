from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.validation import (
    ValidationError,
    check_duplicate_source_rows,
    check_invalid_dates,
    check_invalid_price,
    check_invalid_quantity,
    check_referential_integrity,
    reconcile_record_counts,
    run_quality_checks,
)


def _clean_df(n=3):
    return pd.DataFrame(
        {
            "source_row_number": range(1, n + 1),
            "invoice_date": [pd.Timestamp("2010-12-01")] * n,
            "quantity": [1] * n,
            "unit_price": [2.5] * n,
        }
    )


def _empty_rejected_df():
    return pd.DataFrame({"source_row_number": [], "rejection_reason": []})


def _mock_engine(orphan_counts=(0, 0, 0)):
    """A fake SQLAlchemy engine good enough to stand in for
    `with engine.connect() as conn: conn.exec_driver_sql(sql).scalar_one()`,
    without needing a real database for these checks.
    """
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    remaining = iter(orphan_counts)
    conn.exec_driver_sql.return_value.scalar_one.side_effect = lambda: next(remaining)
    return engine


def test_check_duplicate_source_rows_detects_duplicates():
    df = _clean_df(3)
    df.loc[1, "source_row_number"] = 1
    assert check_duplicate_source_rows(df) == 1


def test_check_duplicate_source_rows_clean_is_zero():
    assert check_duplicate_source_rows(_clean_df(3)) == 0


def test_check_invalid_dates():
    df = _clean_df(2)
    df.loc[0, "invoice_date"] = pd.NaT
    assert check_invalid_dates(df) == 1


def test_check_invalid_quantity():
    df = _clean_df(2)
    df.loc[0, "quantity"] = 0
    assert check_invalid_quantity(df) == 1


def test_check_invalid_price():
    df = _clean_df(2)
    df.loc[0, "unit_price"] = -1.0
    assert check_invalid_price(df) == 1


def test_reconcile_record_counts_true_when_matching():
    assert reconcile_record_counts(10, 7, 3) is True


def test_reconcile_record_counts_false_when_mismatched():
    assert reconcile_record_counts(10, 7, 2) is False


def test_check_referential_integrity_reports_zero_when_clean():
    result = check_referential_integrity(_mock_engine((0, 0, 0)))
    assert all(v == 0 for v in result.values())


def test_run_quality_checks_passes_when_everything_clean():
    engine = _mock_engine((0, 0, 0))
    clean_df = _clean_df(3)
    rejected_df = pd.DataFrame({"source_row_number": [4], "rejection_reason": ["zero_quantity"]})

    report = run_quality_checks(
        engine, extracted_count=4, clean_df=clean_df, rejected_df=rejected_df, loaded_invoice_items_count=3
    )

    assert report["counts_reconcile"] is True
    assert report["load_matches_clean_count"] is True


def test_run_quality_checks_raises_on_referential_integrity_violation():
    engine = _mock_engine((1, 0, 0))
    clean_df = _clean_df(3)

    with pytest.raises(ValidationError, match="referential integrity"):
        run_quality_checks(
            engine, extracted_count=3, clean_df=clean_df, rejected_df=_empty_rejected_df(), loaded_invoice_items_count=3
        )


def test_run_quality_checks_raises_when_counts_dont_reconcile():
    engine = _mock_engine((0, 0, 0))
    clean_df = _clean_df(3)

    with pytest.raises(ValidationError, match="extracted"):
        run_quality_checks(
            engine, extracted_count=99, clean_df=clean_df, rejected_df=_empty_rejected_df(), loaded_invoice_items_count=3
        )


def test_run_quality_checks_raises_when_load_count_mismatches():
    engine = _mock_engine((0, 0, 0))
    clean_df = _clean_df(3)

    with pytest.raises(ValidationError, match="loaded invoice_items"):
        run_quality_checks(
            engine, extracted_count=3, clean_df=clean_df, rejected_df=_empty_rejected_df(), loaded_invoice_items_count=1
        )
