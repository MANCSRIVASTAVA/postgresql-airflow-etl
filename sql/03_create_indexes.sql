-- Applied after the baseline EXPLAIN ANALYZE run in Phase 10 (see
-- docs/performance_analysis.md) so the before/after comparison is real
-- rather than assumed. PK/UNIQUE constraints already give free indexes on
-- invoice_number, stock_code, customer_identifier, country_name and the
-- *_id columns below only need explicit ones because they're looked up by
-- value (date ranges, joins) rather than just uniqueness.

CREATE INDEX IF NOT EXISTS idx_invoices_invoice_date ON invoices (invoice_date);
CREATE INDEX IF NOT EXISTS idx_invoices_customer_id ON invoices (customer_id);
CREATE INDEX IF NOT EXISTS idx_invoices_country_id ON invoices (country_id);

-- Revenue/analytics queries filter cancelled invoices out constantly;
-- a partial index keeps it small since most invoices aren't cancelled.
CREATE INDEX IF NOT EXISTS idx_invoices_not_cancelled ON invoices (invoice_date)
    WHERE is_cancelled = FALSE;

CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice_id ON invoice_items (invoice_id);
CREATE INDEX IF NOT EXISTS idx_invoice_items_product_id ON invoice_items (product_id);

CREATE INDEX IF NOT EXISTS idx_raw_staging_invoice_no ON staging.raw_staging (invoice_no);
