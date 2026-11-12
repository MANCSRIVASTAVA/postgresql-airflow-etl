"""retail_etl_pipeline: extracts the UCI Online Retail Excel file, cleans
it, loads it into retail_db, refreshes the daily summary, then checks the
whole run for data quality.

Intermediate data moves between tasks as Parquet files on a shared volume
(INTERMEDIATE_DIR) — never through XCom. XCom carries only small values
(row counts, a summary dict), since that's what it's built for; the
dataset itself is 500k+ rows and would bloat the metadata database if
pushed through there instead.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from airflow.sdk import dag, task

from src import load as load_mod
from src import transform as transform_mod
from src import validation as validation_mod
from src.database import get_engine
from src.extract import run as extract_run

INTERMEDIATE_DIR = Path(os.environ.get("INTERMEDIATE_DIR", "/opt/airflow/data_processed"))
EXTRACTED_PATH = INTERMEDIATE_DIR / "extracted.parquet"
CLEAN_PATH = INTERMEDIATE_DIR / "clean.parquet"
REJECTED_PATH = INTERMEDIATE_DIR / "rejected.parquet"

default_args = {
    "owner": "data-engineering",
    "retries": 3,
    "retry_delay": timedelta(minutes=2),
}


@dag(
    dag_id="retail_etl_pipeline",
    description="Extract, clean, load and summarise the UCI Online Retail dataset",
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["retail", "etl"],
)
def retail_etl_pipeline():
    @task
    def extract_data() -> int:
        INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)
        return extract_run(EXTRACTED_PATH)

    @task
    def validate_raw_data(extracted_count: int) -> None:
        if extracted_count <= 0:
            raise ValueError("Extracted zero records — refusing to continue")
        on_disk_count = len(pd.read_parquet(EXTRACTED_PATH, columns=["source_row_number"]))
        if on_disk_count != extracted_count:
            raise ValueError(
                f"Extracted file row count ({on_disk_count}) does not match the "
                f"reported extraction count ({extracted_count})"
            )

    @task
    def transform_data() -> None:
        df = pd.read_parquet(EXTRACTED_PATH)
        clean_df, rejected_df = transform_mod.transform(df)
        clean_df.to_parquet(CLEAN_PATH, index=False)
        rejected_df.to_parquet(REJECTED_PATH, index=False)

    @task
    def load_staging() -> None:
        clean_df = pd.read_parquet(CLEAN_PATH)
        load_mod.load_staging(clean_df)

    @task
    def load_dimensions() -> None:
        clean_df = pd.read_parquet(CLEAN_PATH)
        load_mod.load_dimensions(get_engine(), clean_df)

    @task
    def load_transactions() -> dict:
        clean_df = pd.read_parquet(CLEAN_PATH)
        return load_mod.load_transactions(get_engine(), clean_df)

    @task
    def generate_daily_summary() -> None:
        load_mod.generate_daily_summary(get_engine())

    @task
    def run_quality_checks(extracted_count: int, transaction_result: dict) -> dict:
        clean_df = pd.read_parquet(CLEAN_PATH)
        rejected_df = pd.read_parquet(REJECTED_PATH)
        return validation_mod.run_quality_checks(
            get_engine(),
            extracted_count,
            clean_df,
            rejected_df,
            transaction_result["invoice_items"],
        )

    t_extract = extract_data()
    t_validate = validate_raw_data(t_extract)
    t_transform = transform_data()
    t_load_staging = load_staging()
    t_load_dimensions = load_dimensions()
    t_load_transactions = load_transactions()
    t_summary = generate_daily_summary()
    t_quality = run_quality_checks(t_extract, t_load_transactions)

    t_validate >> t_transform >> t_load_staging >> t_load_dimensions >> t_load_transactions >> t_summary >> t_quality


retail_etl_pipeline()
