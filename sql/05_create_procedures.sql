-- Upserts by sales_date rather than truncate-and-reload or plain INSERT,
-- so calling this twice in a row (e.g. a rerun of generate_daily_summary)
-- lands on the same totals instead of doubling them.
CREATE OR REPLACE PROCEDURE refresh_daily_sales_summary()
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO daily_sales_summary (sales_date, total_orders, total_quantity, total_revenue, refreshed_at)
    SELECT sales_date, total_orders, total_quantity, total_revenue, now()
    FROM vw_daily_sales
    ON CONFLICT (sales_date) DO UPDATE
        SET total_orders   = EXCLUDED.total_orders,
            total_quantity  = EXCLUDED.total_quantity,
            total_revenue   = EXCLUDED.total_revenue,
            refreshed_at    = EXCLUDED.refreshed_at;
END;
$$;

-- Usage: CALL refresh_daily_sales_summary();
