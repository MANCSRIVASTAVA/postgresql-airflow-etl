-- Every view here excludes cancelled invoices (is_cancelled = TRUE,
-- invoice numbers starting with 'C') from revenue and order counts, so a
-- cancelled purchase never gets counted once as a sale and then again as
-- a reversal. Legitimate returns (negative quantity on a non-cancelled
-- invoice) are NOT excluded — they net out of revenue naturally, since
-- quantity * unit_price is negative for those lines, which is exactly the
-- real-world effect a return has.

CREATE OR REPLACE VIEW vw_daily_sales AS
SELECT
    i.invoice_date::date                 AS sales_date,
    COUNT(DISTINCT i.invoice_id)         AS total_orders,
    SUM(ii.quantity)                     AS total_quantity,
    SUM(ii.quantity * ii.unit_price)     AS total_revenue
FROM invoices i
JOIN invoice_items ii ON ii.invoice_id = i.invoice_id
WHERE i.is_cancelled = FALSE
GROUP BY i.invoice_date::date;

CREATE OR REPLACE VIEW vw_monthly_sales AS
SELECT
    date_trunc('month', i.invoice_date)::date AS sales_month,
    COUNT(DISTINCT i.invoice_id)              AS total_orders,
    SUM(ii.quantity)                          AS total_quantity,
    SUM(ii.quantity * ii.unit_price)          AS total_revenue
FROM invoices i
JOIN invoice_items ii ON ii.invoice_id = i.invoice_id
WHERE i.is_cancelled = FALSE
GROUP BY date_trunc('month', i.invoice_date);

CREATE OR REPLACE VIEW vw_top_products AS
SELECT
    p.product_id,
    p.stock_code,
    p.description,
    SUM(ii.quantity)                 AS total_quantity_sold,
    SUM(ii.quantity * ii.unit_price) AS total_revenue
FROM products p
JOIN invoice_items ii ON ii.product_id = p.product_id
JOIN invoices i ON i.invoice_id = ii.invoice_id
WHERE i.is_cancelled = FALSE
GROUP BY p.product_id, p.stock_code, p.description;
