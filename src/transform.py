"""Cleans and validates extracted retail data.

Transformation rules (every one of these is a deliberate decision, not a
default pandas behaviour):

1. Core-field completeness: InvoiceNo, StockCode, InvoiceDate, Quantity and
   UnitPrice must all be present. A row missing any of these can't be
   placed anywhere in the schema, so it's rejected (routed to the rejected
   set with a reason), never silently dropped.
2. CustomerID may be missing — the source dataset includes guest/unlinked
   purchases. Those rows are kept; invoices.customer_id is nullable for
   exactly this reason.
3. Description may be missing even though StockCode is present (the
   source has stock codes with no description on some rows). Kept, with
   description left null.
4. Exact duplicates — every one of the 8 source columns identical across
   two rows — are removed, keeping the first occurrence. This is a narrow
   rule on purpose: two rows with the same invoice/product but a
   different quantity are two distinct line items, not duplicates, and
   are both kept.
5. InvoiceDate is parsed to a real timestamp. A row whose date can't be
   parsed is rejected.
6. Quantity: zero is rejected (nothing was transacted). Negative quantity
   is NOT rejected — the source dataset uses it for legitimate returns and
   is never blindly deleted (per project rule); it reduces revenue/stock
   naturally once quantity * unit_price is computed on a negative line.
7. UnitPrice: negative values are rejected as a data error (returns are
   expressed via negative Quantity, never via negative price). Zero is
   kept — it represents promotional/free items.
8. Cancellations: InvoiceNo starting with 'C' (case-insensitive, after
   stripping whitespace) marks the whole invoice as cancelled.
9. line_revenue = Quantity * UnitPrice, computed here so downstream load
   code never recomputes it differently.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

STAGING_COLUMNS = [
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


def transform(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (clean_df, rejected_df). clean_df has STAGING_COLUMNS, ready
    to load into staging.raw_staging. rejected_df keeps every rejected
    row plus a rejection_reason column, so nothing is silently discarded.
    """
    working = df.copy()
    working.columns = [str(c) for c in working.columns]

    working["invoice_date"] = pd.to_datetime(working["InvoiceDate"], errors="coerce")

    reasons = pd.Series([None] * len(working), index=working.index, dtype="object")

    missing_core = (
        working["InvoiceNo"].isna()
        | working["StockCode"].isna()
        | working["Quantity"].isna()
        | working["UnitPrice"].isna()
    )
    reasons[missing_core & reasons.isna()] = "missing_core_field"

    bad_date = working["invoice_date"].isna()
    reasons[bad_date & reasons.isna()] = "invalid_invoice_date"

    zero_quantity = working["Quantity"] == 0
    reasons[zero_quantity & reasons.isna()] = "zero_quantity"

    negative_price = working["UnitPrice"] < 0
    reasons[negative_price & reasons.isna()] = "negative_unit_price"

    missing_country = working["Country"].isna() | (working["Country"].astype(str).str.strip() == "")
    reasons[missing_country & reasons.isna()] = "missing_country"

    working["_rejection_reason"] = reasons

    exact_dup = working.duplicated(
        subset=["InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate", "UnitPrice", "CustomerID", "Country"],
        keep="first",
    )
    working.loc[exact_dup & working["_rejection_reason"].isna(), "_rejection_reason"] = "exact_duplicate"

    rejected_mask = working["_rejection_reason"].notna()
    rejected_df = working.loc[rejected_mask, ["source_row_number", "_rejection_reason"]].rename(
        columns={"_rejection_reason": "rejection_reason"}
    )

    clean = working.loc[~rejected_mask].copy()

    clean["invoice_no_clean"] = clean["InvoiceNo"].astype(str).str.strip()
    clean["is_cancelled"] = clean["invoice_no_clean"].str.upper().str.startswith("C")
    clean["line_revenue"] = clean["Quantity"] * clean["UnitPrice"]
    clean["customer_identifier"] = clean["CustomerID"].apply(
        lambda v: None if pd.isna(v) else str(int(v))
    )
    clean["country_name"] = clean["Country"].astype(str).str.strip()

    clean_df = clean.rename(
        columns={
            "invoice_no_clean": "invoice_no",
            "StockCode": "stock_code",
            "Description": "description",
            "Quantity": "quantity",
            "UnitPrice": "unit_price",
        }
    )[STAGING_COLUMNS]

    logger.info(
        "Transform complete: %d clean rows, %d rejected rows (%s)",
        len(clean_df),
        len(rejected_df),
        rejected_df["rejection_reason"].value_counts().to_dict() if len(rejected_df) else {},
    )

    return clean_df.reset_index(drop=True), rejected_df.reset_index(drop=True)
