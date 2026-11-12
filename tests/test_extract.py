import pandas as pd
import pytest

from src.extract import REQUIRED_COLUMNS, extract

SAMPLE_ROWS = [
    {
        "InvoiceNo": "536365",
        "StockCode": "85123A",
        "Description": "WHITE HANGING HEART T-LIGHT HOLDER",
        "Quantity": 6,
        "InvoiceDate": pd.Timestamp("2010-12-01 08:26:00"),
        "UnitPrice": 2.55,
        "CustomerID": 17850.0,
        "Country": "United Kingdom",
    },
    {
        "InvoiceNo": "536365",
        "StockCode": "71053",
        "Description": "WHITE METAL LANTERN",
        "Quantity": 6,
        "InvoiceDate": pd.Timestamp("2010-12-01 08:26:00"),
        "UnitPrice": 3.39,
        "CustomerID": 17850.0,
        "Country": "United Kingdom",
    },
]


def _write_sample_xlsx(path, rows=SAMPLE_ROWS):
    pd.DataFrame(rows).to_excel(path, index=False, engine="openpyxl")


def test_extract_missing_file_raises(tmp_path):
    missing = tmp_path / "does_not_exist.xlsx"
    with pytest.raises(FileNotFoundError, match="Source file not found"):
        extract(missing)


def test_extract_missing_required_column_raises(tmp_path):
    xlsx = tmp_path / "bad.xlsx"
    rows = [{k: v for k, v in row.items() if k != "Country"} for row in SAMPLE_ROWS]
    _write_sample_xlsx(xlsx, rows)
    with pytest.raises(ValueError, match="missing expected column"):
        extract(xlsx)


def test_extract_reads_rows_and_assigns_source_row_number(tmp_path):
    xlsx = tmp_path / "good.xlsx"
    _write_sample_xlsx(xlsx)

    df = extract(xlsx)

    assert len(df) == 2
    assert list(df["source_row_number"]) == [1, 2]
    assert set(REQUIRED_COLUMNS).issubset(df.columns)
    # str(): a numeric-looking value written to xlsx can round-trip as an
    # int rather than a str, same inconsistency transform.py normalises
    # out of StockCode — extract() itself doesn't touch InvoiceNo's type.
    assert str(df.iloc[0]["InvoiceNo"]) == "536365"


def test_extract_never_writes_to_source_file(tmp_path):
    xlsx = tmp_path / "good.xlsx"
    _write_sample_xlsx(xlsx)
    before = xlsx.read_bytes()

    extract(xlsx)

    assert xlsx.read_bytes() == before
