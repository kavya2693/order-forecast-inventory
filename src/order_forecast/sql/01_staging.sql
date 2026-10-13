-- Staging: one cleaned table per source system.
-- Raw tables are exposed as raw_<name> (in BigQuery these are dataset tables).

-- Cancelled lines are re-keyed by the service desk as new lines, so counting them would
-- double the demand they represent.
CREATE OR REPLACE TABLE stg_orders AS
SELECT
    order_id,
    line_no,
    customer_id,
    sku_id,
    CAST(order_date AS DATE) AS order_date,
    CAST(DATE_TRUNC('week', CAST(order_date AS DATE)) AS DATE) AS week_start,
    qty_ordered
FROM raw_sales_orders
WHERE status <> 'cancelled'
  AND qty_ordered > 0;

-- The field app retries on timeouts; the API log keeps every attempt under the same event_id.
CREATE OR REPLACE TABLE stg_events AS
SELECT
    event_id,
    customer_id,
    sku_id,
    rep_id,
    event_type,
    event_ts,
    CAST(DATE_TRUNC('week', event_ts) AS DATE) AS week_start
FROM raw_field_app_events
QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY event_ts) = 1;

-- A shipment fact is attributed to the week it became known, not to the order week:
-- a short shipment is known on ship_date, a late delivery on delivered_date.
CREATE OR REPLACE TABLE stg_shipments AS
SELECT
    s.shipment_id,
    s.customer_id,
    s.sku_id,
    CAST(s.ship_date AS DATE) AS ship_date,
    CAST(DATE_TRUNC('week', CAST(s.ship_date AS DATE)) AS DATE) AS ship_week,
    CAST(s.delivered_date AS DATE) AS delivered_date,
    CAST(DATE_TRUNC('week', CAST(s.delivered_date AS DATE)) AS DATE) AS delivered_week,
    o.qty_ordered,
    s.qty_shipped,
    s.qty_shipped < o.qty_ordered AS is_partial,
    o.qty_ordered - s.qty_shipped AS qty_short,
    CAST(s.delivered_date AS DATE) > CAST(s.promised_date AS DATE) AS is_late,
    DATE_DIFF('day', CAST(s.ship_date AS DATE), CAST(s.delivered_date AS DATE)) AS transit_days
FROM raw_shipments AS s
JOIN stg_orders AS o
  ON o.order_id = s.order_id
 AND o.line_no = s.line_no;
