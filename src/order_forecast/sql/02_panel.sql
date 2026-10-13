-- Weekly customer x SKU panel with explicit zero weeks.
-- A pair enters the panel the week of its first order; weeks before that are not demand.

CREATE OR REPLACE TABLE calendar AS
SELECT CAST(w AS DATE) AS week_start
FROM generate_series(
    (SELECT MIN(week_start) FROM stg_orders),
    (SELECT MAX(week_start) FROM stg_orders),
    INTERVAL 7 DAY
) AS t(w);

CREATE OR REPLACE TABLE pairs AS
SELECT customer_id, sku_id, MIN(week_start) AS first_week
FROM stg_orders
GROUP BY customer_id, sku_id;

CREATE OR REPLACE TABLE panel AS
WITH
orders_w AS (
    SELECT customer_id, sku_id, week_start, SUM(qty_ordered) AS qty, COUNT(*) AS n_lines
    FROM stg_orders
    GROUP BY customer_id, sku_id, week_start
),
pair_events_w AS (
    SELECT
        customer_id, sku_id, week_start,
        COUNT_IF(event_type = 'quote_request') AS quotes,
        COUNT_IF(event_type = 'catalog_view') AS views
    FROM stg_events
    WHERE sku_id IS NOT NULL
    GROUP BY customer_id, sku_id, week_start
),
cust_events_w AS (
    SELECT
        customer_id, week_start,
        COUNT_IF(event_type = 'visit_checkin') AS visits,
        COUNT(*) AS cust_events
    FROM stg_events
    GROUP BY customer_id, week_start
),
short_w AS (
    SELECT
        customer_id, sku_id, ship_week AS week_start,
        COUNT_IF(is_partial) AS partial_lines,
        SUM(qty_short) AS qty_short,
        COUNT_IF(delivered_date IS NULL) AS missing_pod
    FROM stg_shipments
    GROUP BY customer_id, sku_id, ship_week
),
late_w AS (
    SELECT
        customer_id, sku_id, delivered_week AS week_start,
        COUNT_IF(is_late) AS late_lines,
        AVG(transit_days) AS transit_days
    FROM stg_shipments
    WHERE delivered_date IS NOT NULL
    GROUP BY customer_id, sku_id, delivered_week
)
SELECT
    p.customer_id,
    p.sku_id,
    c.week_start,
    COALESCE(o.qty, 0) AS qty,
    COALESCE(o.n_lines, 0) AS n_lines,
    COALESCE(pe.quotes, 0) AS quotes,
    COALESCE(pe.views, 0) AS views,
    COALESCE(ce.visits, 0) AS visits,
    COALESCE(ce.cust_events, 0) AS cust_events,
    COALESCE(sw.partial_lines, 0) AS partial_lines,
    COALESCE(sw.qty_short, 0) AS qty_short,
    COALESCE(sw.missing_pod, 0) AS missing_pod,
    COALESCE(lw.late_lines, 0) AS late_lines,
    lw.transit_days
FROM pairs AS p
JOIN calendar AS c
  ON c.week_start >= p.first_week
LEFT JOIN orders_w AS o
  ON o.customer_id = p.customer_id AND o.sku_id = p.sku_id AND o.week_start = c.week_start
LEFT JOIN pair_events_w AS pe
  ON pe.customer_id = p.customer_id AND pe.sku_id = p.sku_id AND pe.week_start = c.week_start
LEFT JOIN cust_events_w AS ce
  ON ce.customer_id = p.customer_id AND ce.week_start = c.week_start
LEFT JOIN short_w AS sw
  ON sw.customer_id = p.customer_id AND sw.sku_id = p.sku_id AND sw.week_start = c.week_start
LEFT JOIN late_w AS lw
  ON lw.customer_id = p.customer_id AND lw.sku_id = p.sku_id AND lw.week_start = c.week_start;
