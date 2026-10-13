-- Features as of the end of week t (the forecast origin) and targets for weeks t+1, t+2.
-- Every window below ends at CURRENT ROW, so nothing after the origin leaks in;
-- only the LEAD() targets look forward.

CREATE OR REPLACE TABLE features AS
WITH
cust_w AS (
    SELECT customer_id, week_start, SUM(qty) AS cust_qty
    FROM panel GROUP BY customer_id, week_start
),
sku_w AS (
    SELECT sku_id, week_start, SUM(qty) AS sku_qty
    FROM panel GROUP BY sku_id, week_start
),
cust_r AS (
    SELECT customer_id, week_start,
        AVG(cust_qty) OVER (PARTITION BY customer_id ORDER BY week_start
                            ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) AS cust_qty_4w,
        AVG(cust_qty) OVER (PARTITION BY customer_id ORDER BY week_start
                            ROWS BETWEEN 25 PRECEDING AND CURRENT ROW) AS cust_qty_26w
    FROM cust_w
),
sku_r AS (
    SELECT sku_id, week_start,
        AVG(sku_qty) OVER (PARTITION BY sku_id ORDER BY week_start
                           ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) AS sku_qty_4w,
        AVG(sku_qty) OVER (PARTITION BY sku_id ORDER BY week_start
                           ROWS BETWEEN 25 PRECEDING AND CURRENT ROW) AS sku_qty_26w
    FROM sku_w
),
base AS (
    SELECT
        p.*,
        CASE WHEN p.qty > 0 THEN 1 ELSE 0 END AS ordered,
        MAX(CASE WHEN p.qty > 0 THEN p.week_start END) OVER w_all AS last_order_week,
        ROW_NUMBER() OVER w_all AS history_weeks
    FROM panel AS p
    WINDOW w_all AS (PARTITION BY p.customer_id, p.sku_id ORDER BY p.week_start
                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
)
SELECT
    b.customer_id,
    b.sku_id,
    b.week_start,
    k.category,
    c.segment,
    b.history_weeks,
    -- demand history
    b.qty AS qty_l0,
    LAG(b.qty, 1) OVER w AS qty_l1,
    LAG(b.qty, 2) OVER w AS qty_l2,
    LAG(b.qty, 3) OVER w AS qty_l3,
    LAG(b.qty, 51) OVER w AS qty_ly_h1,
    LAG(b.qty, 50) OVER w AS qty_ly_h2,
    AVG(b.qty) OVER (w ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) AS qty_mean_4w,
    AVG(b.qty) OVER (w ROWS BETWEEN 12 PRECEDING AND CURRENT ROW) AS qty_mean_13w,
    AVG(b.qty) OVER (w ROWS BETWEEN 25 PRECEDING AND CURRENT ROW) AS qty_mean_26w,
    STDDEV_SAMP(b.qty) OVER (w ROWS BETWEEN 12 PRECEDING AND CURRENT ROW) AS qty_std_13w,
    AVG(b.ordered) OVER (w ROWS BETWEEN 12 PRECEDING AND CURRENT ROW) AS order_rate_13w,
    AVG(b.ordered) OVER (w ROWS BETWEEN 51 PRECEDING AND CURRENT ROW) AS order_rate_52w,
    SUM(b.qty) OVER (w ROWS BETWEEN 25 PRECEDING AND CURRENT ROW)
        / NULLIF(SUM(b.ordered) OVER (w ROWS BETWEEN 25 PRECEDING AND CURRENT ROW), 0) AS size_when_ordered_26w,
    DATE_DIFF('day', b.last_order_week, b.week_start) / 7 AS weeks_since_order,
    cr.cust_qty_4w,
    cr.cust_qty_26w,
    sr.sku_qty_4w,
    sr.sku_qty_26w,
    -- field-sales app
    b.quotes AS quotes_l0,
    LAG(b.quotes, 1) OVER w AS quotes_l1,
    SUM(b.quotes) OVER (w ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) AS quotes_4w,
    b.views AS views_l0,
    b.visits AS visits_l0,
    LAG(b.visits, 1) OVER w AS visits_l1,
    b.cust_events AS cust_events_l0,
    -- logistics
    b.partial_lines AS partial_l0,
    b.qty_short AS qty_short_l0,
    b.missing_pod AS missing_pod_l0,
    SUM(b.late_lines) OVER (w ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) AS late_lines_4w,
    AVG(b.transit_days) OVER (w ROWS BETWEEN 7 PRECEDING AND CURRENT ROW) AS transit_days_8w,
    -- calendar of the target weeks (known in advance)
    WEEKOFYEAR(b.week_start + INTERVAL 7 DAY) AS target_woy_h1,
    WEEKOFYEAR(b.week_start + INTERVAL 14 DAY) AS target_woy_h2,
    -- targets
    LEAD(b.qty, 1) OVER w AS y_h1,
    LEAD(b.qty, 2) OVER w AS y_h2
FROM base AS b
JOIN raw_skus AS k ON k.sku_id = b.sku_id
JOIN raw_customers AS c ON c.customer_id = b.customer_id
JOIN cust_r AS cr ON cr.customer_id = b.customer_id AND cr.week_start = b.week_start
JOIN sku_r AS sr ON sr.sku_id = b.sku_id AND sr.week_start = b.week_start
WINDOW w AS (PARTITION BY b.customer_id, b.sku_id ORDER BY b.week_start);
