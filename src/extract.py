"""Reads the source Excel file into a DataFrame. Read-only: the source
file is never written to, renamed, or moved by anything in this pipeline.
"""

import logging
import os
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = [
    "InvoiceNo",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "UnitPrice",
    "CustomerID",
    "Country",
]

DEFAULT_SOURCE_PATH = Path("data/Online Retail.xlsx")


def extract(source_path: str | Path | None = None) -> pd.DataFrame:
    """Read the raw retail Excel file and tag each row with its original
    position (source_row_number). That number becomes the natural key the
    rest of the pipeline upserts on, so rerunning extraction never shifts
    which database row a given source line maps to.
    """
    path = Path(source_path) if source_path else Path(os.environ.get("SOURCE_XLSX_PATH", DEFAULT_SOURCE_PATH))

    if not path.exists():
        raise FileNotFoundError(
            f"Source file not found at '{path}'. Place the UCI Online Retail "
            f"dataset at that path before running the pipeline."
        )

    df = pd.read_excel(path, engine="openpyxl")

    missing_columns = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing_columns:
        raise ValueError(
            f"Source file is missing expected column(s): {sorted(missing_columns)}. "
            f"Expected columns: {REQUIRED_COLUMNS}"
        )

    df = df[REQUIRED_COLUMNS].copy()

    # Every text column here can come back from openpyxl with mixed
    # Python types in the same column — a numeric-looking value (a stock
    # code like 20713, or even a purely numeric Description) reads as
    # int, an alphanumeric one (85123A, C536379) reads as str. That's
    # tolerable in a DataFrame but breaks Parquet (via pyarrow, which
    # needs one type per column) the moment run() tries to persist this
    # intermediate file — confirmed by hitting this for InvoiceNo,
    # StockCode, AND Description in turn. Normalised here, immediately
    # after reading, rather than downstream in transform.py, since the
    # failure happens before transform.py ever runs. NaN is left alone
    # (not stringified to the literal "nan") so missing-value checks
    # downstream still see real missing values.
    for col in ("InvoiceNo", "StockCode", "Description", "Country"):
        df[col] = df[col].apply(lambda v: str(v) if pd.notna(v) else v)

    df.insert(0, "source_row_number", range(1, len(df) + 1))

    logger.info("Extracted %d records from %s", len(df), path)
    return df


def run(output_path: str | Path) -> int:
    """CLI/Airflow entry point: extract and write an intermediate Parquet
    file for the next task to pick up, instead of passing the DataFrame
    through XCom.
    """
    df = extract()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
    logger.info("Wrote %d extracted records to %s", len(df), output_path)
    return len(df)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    out = sys.argv[1] if len(sys.argv) > 1 else "data/processed/extracted.parquet"
    run(out)
