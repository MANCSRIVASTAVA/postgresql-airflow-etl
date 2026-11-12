"""Unit tests for load.py's pure helper functions — the parts that don't
need a database to be wrong. The SQL-executing functions (load_staging,
load_dimensions, load_transactions, generate_daily_summary) are covered
by the live end-to-end run against the real retail_db documented in
progress.md (Phase 4), not here — running them against a throwaway test
database is possible but out of scope for this time-boxed pass, and
running them against the real one would pollute the loaded demo data.
"""

from datetime import datetime

import pandas as pd

from src.load import _chunked, _row_to_native


def test_chunked_splits_into_expected_batch_sizes():
    records = list(range(2500))
    batches = list(_chunked(records, 1000))

    assert [len(b) for b in batches] == [1000, 1000, 500]
    assert sum(batches, []) == records


def test_chunked_handles_empty_list():
    assert list(_chunked([], 1000)) == []


def test_row_to_native_converts_nan_description_to_none():
    row = pd.Series(
        {
            "source_row_number": 1,
            "invoice_no": "536365",
            "stock_code": "85123A",
            "description": float("nan"),
            "quantity": 6,
            "invoice_date": pd.Timestamp("2010-12-01 08:26:00"),
            "unit_price": 2.55,
            "customer_identifier": "17850",
            "country_name": "United Kingdom",
            "is_cancelled": False,
            "line_revenue": 15.3,
        }
    )

    native = _row_to_native(row)

    assert native[3] is None  # description
    assert isinstance(native[5], datetime)  # invoice_date, not a pandas Timestamp
    assert native[9] is False and isinstance(native[9], bool)  # not numpy.bool_
    assert isinstance(native[0], int) and isinstance(native[4], int)
    assert isinstance(native[6], float) and isinstance(native[10], float)


def test_row_to_native_keeps_real_description():
    row = pd.Series(
        {
            "source_row_number": 2,
            "invoice_no": "536365",
            "stock_code": "71053",
            "description": "WHITE METAL LANTERN",
            "quantity": 6,
            "invoice_date": pd.Timestamp("2010-12-01 08:26:00"),
            "unit_price": 3.39,
            "customer_identifier": None,
            "country_name": "United Kingdom",
            "is_cancelled": False,
            "line_revenue": 20.34,
        }
    )

    native = _row_to_native(row)

    assert native[3] == "WHITE METAL LANTERN"
    assert native[7] is None  # customer_identifier, a guest purchase
