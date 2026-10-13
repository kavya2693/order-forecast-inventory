# Running the SQL on BigQuery

The pipeline in `src/order_forecast/sql/` is written for DuckDB so it runs on a laptop and in
CI, but it was kept close to BigQuery Standard SQL so it can move to a warehouse with small,
mechanical edits. The raw tables are referenced as `raw_<name>`; in BigQuery these become
`project.dataset.<name>`.

| Construct | DuckDB (here) | BigQuery |
|---|---|---|
| Week bucket (Monday start) | `DATE_TRUNC('week', d)` | `DATE_TRUNC(d, WEEK(MONDAY))` |
| Week bucket of a timestamp | `CAST(DATE_TRUNC('week', ts) AS DATE)` | `DATE(TIMESTAMP_TRUNC(ts, WEEK(MONDAY)))` |
| Day difference | `DATE_DIFF('day', a, b)` | `DATE_DIFF(b, a, DAY)` (argument order flips) |
| Calendar of weeks | `generate_series(start, end, INTERVAL 7 DAY)` | `UNNEST(GENERATE_DATE_ARRAY(start, end, INTERVAL 7 DAY))` |
| Conditional count | `COUNT_IF(cond)` | `COUNTIF(cond)` |
| Dedupe on a key | `QUALIFY ROW_NUMBER() OVER (...) = 1` | same (`QUALIFY` needs a `WHERE`/`GROUP BY`/`HAVING` in the same query on BigQuery; add `WHERE TRUE`) |
| Week of year | `WEEKOFYEAR(d)` | `EXTRACT(ISOWEEK FROM d)` |
| Date + interval | `d + INTERVAL 7 DAY` | `DATE_ADD(d, INTERVAL 7 DAY)` |
| Sample std dev | `STDDEV_SAMP(x)` | `STDDEV_SAMP(x)` |
| Named windows | `WINDOW w AS (...)` and `OVER (w ROWS ...)` | same |
| Create table | `CREATE OR REPLACE TABLE t AS` | same, with a dataset prefix |
| Read parquet | `read_parquet('path')` view | external table or `LOAD DATA` into a native table |

Things that do not translate one to one:

- The panel cross-joins every customer x SKU pair with every week after its first order. On
  BigQuery this is the most expensive step; partition `panel` and `features` by `week_start`
  and cluster by `customer_id, sku_id`, and restrict the calendar to the training horizon.
- Window frames (`ROWS BETWEEN 12 PRECEDING AND CURRENT ROW`) behave identically, but
  BigQuery bills the full scan of the partitioned input, so build features incrementally per
  week in production rather than rebuilding three years each night.
- `LEAD()` for the targets is only used in backtests. A production scoring query drops the
  two target columns and scores the latest `week_start`.
