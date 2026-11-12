-- Reference queries behind the project's analytics. All revenue figures
-- exclude cancelled invoices (is_cancelled = TRUE) but keep legitimate
-- returns (negative-quantity lines on non-cancelled invoices), which net
-- out of revenue on their own. Several of these are the ones measured
-- with EXPLAIN ANALYZE before/after indexing in docs/performance_analysis.md.

-- 1. Daily revenue
SELECT * FROM vw_daily_sales ORDER BY sales_date;

-- 2. Monthly revenue
SELECT * FROM vw_monthly_sales ORDER BY sales_month;

-- 3. Top 10 products by revenue
SELECT * FROM vw_top_products ORDER BY total_revenue DESC LIMIT 10;

-- 4. Top 10 customers by revenue
SELECT
    c.customer_identifier,
    COUNT(DISTINCT i.invoice_id)     AS total_orders,
    SUM(ii.quantity * ii.unit_price) AS total_revenue
FROM customers c
JOIN invoices i ON i.customer_id = c.customer_id
JOIN invoice_items ii ON ii.invoice_id = i.invoice_id
WHERE i.is_cancelled = FALSE
GROUP BY c.customer_identifier
ORDER BY total_revenue DESC
LIMIT 10;

-- 5. Revenue by country
SELECT
    co.country_name,
    COUNT(DISTINCT i.invoice_id)     AS total_orders,
    SUM(ii.quantity * ii.unit_price) AS total_revenue
FROM countries co
JOIN invoices i ON i.country_id = co.country_id
JOIN invoice_items ii ON ii.invoice_id = i.invoice_id
WHERE i.is_cancelled = FALSE
GROUP BY co.country_name
ORDER BY total_revenue DESC;

-- 6. Total invoices, split by cancelled vs completed
SELECT
    COUNT(*)                                   AS total_invoices,
    COUNT(*) FILTER (WHERE is_cancelled)        AS cancelled_invoices,
    COUNT(*) FILTER (WHERE NOT is_cancelled)    AS completed_invoices
FROM invoices;

-- 7. Cancelled invoices (invoice numbers starting with 'C' in the source)
SELECT invoice_number, customer_id, country_id, invoice_date
FROM invoices
WHERE is_cancelled = TRUE
ORDER BY invoice_date DESC;

-- 8. Product returns: negative-quantity lines on invoices that were NOT
-- cancelled (a cancelled invoice's negative lines are just the reversal
-- of its own sale, not a separate return)
SELECT
    p.stock_code,
    p.description,
    ii.quantity,
    ii.unit_price,
    i.invoice_number,
    i.invoice_date
FROM invoice_items ii
JOIN invoices i ON i.invoice_id = ii.invoice_id
JOIN products p ON p.product_id = ii.product_id
WHERE ii.quantity < 0 AND i.is_cancelled = FALSE
ORDER BY i.invoice_date DESC;
