from __future__ import annotations

from pathlib import Path

import pandas as pd

from order_forecast.pipeline import build_features, connect, run_sql
from tests.conftest import week, write_raw


def _panel(raw: Path) -> pd.DataFrame:
    con = connect(raw)
    run_sql(con)
    df = con.execute("SELECT * FROM panel ORDER BY customer_id, sku_id, week_start").df()
    con.close()
    df["week_start"] = pd.to_datetime(df["week_start"]).dt.date
    return df.set_index(["customer_id", "sku_id", "week_start"])


def test_cancelled_lines_and_retried_events_are_not_counted(tiny_raw: Path) -> None:
    p = _panel(tiny_raw)
    assert p.loc[("C1", "S1", week(2)), "qty"] == 6  # the cancelled duplicate line is dropped
    assert p.loc[("C1", "S1", week(2)), "quotes"] == 1  # the retry with the same event_id is dropped
    assert p.loc[("C1", "S1", week(2)), "visits"] == 1


def test_panel_has_zero_weeks_and_starts_at_first_order(tiny_raw: Path) -> None:
    p = _panel(tiny_raw)
    c1 = p.loc[("C1", "S1")]
    assert list(c1.index) == [week(i) for i in range(6)]
    assert c1["qty"].tolist() == [10, 0, 6, 0, 0, 8]
    # C2 x S2 first ordered in week 1, so week 0 is not a zero-demand week for it.
    assert p.loc[("C2", "S2")].index.min() == week(1)


def test_shipment_facts_land_in_the_week_they_become_known(tiny_raw: Path) -> None:
    p = _panel(tiny_raw)
    # Ordered in week 2 but short-shipped on the Monday of week 3.
    assert p.loc[("C1", "S1", week(2)), "partial_lines"] == 0
    assert p.loc[("C1", "S1", week(3)), "partial_lines"] == 1
    assert p.loc[("C1", "S1", week(3)), "qty_short"] == 3
    assert p.loc[("C1", "S1", week(3)), "missing_pod"] == 1
    assert p.loc[("C2", "S2", week(1)), "late_lines"] == 1


def test_features_do_not_see_the_future(tmp_path: Path, tiny_raw: Path) -> None:
    """Changing week 5 must not change any feature at an origin before week 5, only the targets."""
    base = build_features(tiny_raw)
    orders = pd.read_parquet(tiny_raw / "sales_orders.parquet")
    orders.loc[orders["order_id"] == "SO5", "qty_ordered"] = 500
    raw2 = write_raw(
        tmp_path / "raw2",
        orders.drop(columns=["unit_price", "channel"]).to_dict("records"),
        pd.read_parquet(tiny_raw / "field_app_events.parquet").to_dict("records"),
        pd.read_parquet(tiny_raw / "shipments.parquet").to_dict("records"),
    )
    changed = build_features(raw2)
    early = base["week_start"] < pd.Timestamp(week(5))
    feature_cols = [c for c in base.columns if not c.startswith("y_") and c not in ("category", "segment")]
    pd.testing.assert_frame_equal(
        base.loc[early, feature_cols].reset_index(drop=True),
        changed.loc[early, feature_cols].reset_index(drop=True),
    )
    row = (changed["customer_id"] == "C1") & (changed["week_start"] == pd.Timestamp(week(4)))
    assert changed.loc[row, "y_h1"].item() == 500
