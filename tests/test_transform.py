import pandas as pd

from src.transform import transform


def _row(source_row_number, invoice_no="536365", stock_code="85123A", description="WIDGET",
         quantity=6, invoice_date="2010-12-01 08:26:00", unit_price=2.55, customer_id=17850.0,
         country="United Kingdom"):
    return {
        "source_row_number": source_row_number,
        "InvoiceNo": invoice_no,
        "StockCode": stock_code,
        "Description": description,
        "Quantity": quantity,
        "InvoiceDate": pd.Timestamp(invoice_date) if invoice_date is not None else pd.NaT,
        "UnitPrice": unit_price,
        "CustomerID": customer_id,
        "Country": country,
    }


def test_normal_row_is_clean_and_not_cancelled():
    df = pd.DataFrame([_row(1)])
    clean_df, rejected_df = transform(df)

    assert len(clean_df) == 1
    assert len(rejected_df) == 0
    assert clean_df.iloc[0]["is_cancelled"] == False
    assert clean_df.iloc[0]["line_revenue"] == 6 * 2.55


def test_c_prefixed_invoice_is_flagged_cancelled():
    df = pd.DataFrame([_row(1, invoice_no="C536379", quantity=-1)])
    clean_df, rejected_df = transform(df)

    assert len(rejected_df) == 0
    assert clean_df.iloc[0]["is_cancelled"] == True


def test_negative_quantity_on_normal_invoice_is_a_kept_return():
    df = pd.DataFrame([_row(1, quantity=-3)])
    clean_df, rejected_df = transform(df)

    assert len(rejected_df) == 0
    assert clean_df.iloc[0]["is_cancelled"] == False
    assert clean_df.iloc[0]["quantity"] == -3
    assert clean_df.iloc[0]["line_revenue"] == -3 * 2.55


def test_negative_unit_price_is_rejected():
    df = pd.DataFrame([_row(1, unit_price=-5.0)])
    clean_df, rejected_df = transform(df)

    assert len(clean_df) == 0
    assert rejected_df.iloc[0]["rejection_reason"] == "negative_unit_price"


def test_zero_quantity_is_rejected():
    df = pd.DataFrame([_row(1, quantity=0)])
    clean_df, rejected_df = transform(df)

    assert len(clean_df) == 0
    assert rejected_df.iloc[0]["rejection_reason"] == "zero_quantity"


def test_zero_unit_price_is_kept_as_free_item():
    df = pd.DataFrame([_row(1, unit_price=0.0)])
    clean_df, rejected_df = transform(df)

    assert len(rejected_df) == 0
    assert len(clean_df) == 1
    assert clean_df.iloc[0]["line_revenue"] == 0.0


def test_missing_stock_code_is_rejected_not_dropped_silently():
    df = pd.DataFrame([_row(1, stock_code=None)])
    clean_df, rejected_df = transform(df)

    assert len(clean_df) == 0
    assert len(rejected_df) == 1
    assert rejected_df.iloc[0]["rejection_reason"] == "missing_core_field"
    assert rejected_df.iloc[0]["source_row_number"] == 1


def test_missing_country_is_rejected():
    df = pd.DataFrame([_row(1, country=None)])
    clean_df, rejected_df = transform(df)

    assert len(clean_df) == 0
    assert rejected_df.iloc[0]["rejection_reason"] == "missing_country"


def test_missing_customer_id_is_kept_as_guest_purchase():
    df = pd.DataFrame([_row(1, customer_id=None)])
    clean_df, rejected_df = transform(df)

    assert len(rejected_df) == 0
    assert clean_df.iloc[0]["customer_identifier"] is None


def test_exact_duplicate_rows_keep_only_the_first():
    df = pd.DataFrame([_row(1), _row(2)])  # identical except source_row_number
    clean_df, rejected_df = transform(df)

    assert len(clean_df) == 1
    assert clean_df.iloc[0]["source_row_number"] == 1
    assert rejected_df.iloc[0]["source_row_number"] == 2
    assert rejected_df.iloc[0]["rejection_reason"] == "exact_duplicate"


def test_same_invoice_different_quantity_is_not_a_duplicate():
    df = pd.DataFrame([_row(1, quantity=6), _row(2, quantity=3)])
    clean_df, rejected_df = transform(df)

    assert len(clean_df) == 2
    assert len(rejected_df) == 0


def test_mixed_int_and_str_stock_codes_both_normalise_to_str():
    df = pd.DataFrame([_row(1, stock_code=20713), _row(2, stock_code="85123A")])
    clean_df, _ = transform(df)

    assert clean_df["stock_code"].apply(type).eq(str).all()
    assert set(clean_df["stock_code"]) == {"20713", "85123A"}


def test_invalid_date_is_rejected():
    df = pd.DataFrame([_row(1, invoice_date=None)])
    clean_df, rejected_df = transform(df)

    assert len(clean_df) == 0
    assert rejected_df.iloc[0]["rejection_reason"] == "invalid_invoice_date"


def test_every_extracted_row_is_accounted_for():
    df = pd.DataFrame([_row(1), _row(2, quantity=0), _row(3, country=None)])
    clean_df, rejected_df = transform(df)

    assert len(clean_df) + len(rejected_df) == len(df)
