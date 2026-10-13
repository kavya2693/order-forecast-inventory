"""Runs the SQL pipeline (staging -> weekly panel -> features) in DuckDB."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import duckdb
import pandas as pd

RAW_TABLES = ("customers", "skus", "sales_orders", "shipments", "field_app_events")
SQL_STAGES = ("01_staging.sql", "02_panel.sql", "03_features.sql")


def connect(raw_dir: Path | str, database: str = ":memory:") -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(database)
    con.execute("SET enable_progress_bar = false")
    for name in RAW_TABLES:
        path = Path(raw_dir) / f"{name}.parquet"
        con.execute(f"CREATE OR REPLACE VIEW raw_{name} AS SELECT * FROM read_parquet('{path.as_posix()}')")
    return con


def run_sql(con: duckdb.DuckDBPyConnection) -> None:
    sql_dir = resources.files("order_forecast") / "sql"
    for stage in SQL_STAGES:
        con.execute((sql_dir / stage).read_text())


def build_features(raw_dir: Path | str) -> pd.DataFrame:
    con = connect(raw_dir)
    run_sql(con)
    df = con.execute("SELECT * FROM features ORDER BY customer_id, sku_id, week_start").df()
    con.close()
    df["week_start"] = pd.to_datetime(df["week_start"])
    for col in ("category", "segment"):
        df[col] = df[col].astype("category")
    return df


def source_counts(raw_dir: Path | str) -> dict[str, int]:
    """Row counts before and after cleaning, for the run report."""
    con = connect(raw_dir)
    run_sql(con)
    q = {
        "raw_order_lines": "SELECT COUNT(*) FROM raw_sales_orders",
        "clean_order_lines": "SELECT COUNT(*) FROM stg_orders",
        "raw_app_events": "SELECT COUNT(*) FROM raw_field_app_events",
        "dedup_app_events": "SELECT COUNT(*) FROM stg_events",
        "shipments": "SELECT COUNT(*) FROM stg_shipments",
        "pairs": "SELECT COUNT(*) FROM pairs",
        "panel_rows": "SELECT COUNT(*) FROM panel",
    }
    out = {k: int(con.execute(v).fetchone()[0]) for k, v in q.items()}  # type: ignore[index]
    con.close()
    return out
