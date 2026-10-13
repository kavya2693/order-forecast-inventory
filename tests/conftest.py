from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

MON = date(2024, 1, 1)  # a Monday


def week(n: int, day: int = 0) -> date:
    return MON + timedelta(days=7 * n + day)


def write_raw(root: Path, orders: list[dict], events: list[dict], shipments: list[dict]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"customer_id": "C1", "region": "north", "segment": "mid", "rep_id": "R001"},
            {"customer_id": "C2", "region": "south", "segment": "small", "rep_id": "R002"},
        ]
    ).to_parquet(root / "customers.parquet")
    pd.DataFrame(
        [
            {"sku_id": "S1", "category": "snacks", "case_pack": 1, "unit_cost": 2.0, "list_price": 3.0},
            {"sku_id": "S2", "category": "frozen", "case_pack": 1, "unit_cost": 5.0, "list_price": 7.0},
        ]
    ).to_parquet(root / "skus.parquet")
    o = pd.DataFrame(orders)
    o["unit_price"], o["channel"] = 3.0, "edi"
    o.to_parquet(root / "sales_orders.parquet")
    e = pd.DataFrame(
        events, columns=["event_id", "event_ts", "customer_id", "sku_id", "rep_id", "event_type"]
    )
    e["event_ts"] = pd.to_datetime(e["event_ts"])
    e.to_parquet(root / "field_app_events.parquet")
    pd.DataFrame(shipments).to_parquet(root / "shipments.parquet")
    return root


def order(oid: str, cust: str, sku: str, d: date, qty: int, status: str = "open", line: int = 1) -> dict:
    return {
        "order_id": oid,
        "line_no": line,
        "customer_id": cust,
        "sku_id": sku,
        "order_date": d,
        "qty_ordered": qty,
        "status": status,
    }


def shipment(sid: str, o: dict, ship: date, delivered: date | None, shipped: int) -> dict:
    return {
        "shipment_id": sid,
        "order_id": o["order_id"],
        "line_no": o["line_no"],
        "customer_id": o["customer_id"],
        "sku_id": o["sku_id"],
        "warehouse_id": "WNO",
        "ship_date": ship,
        "promised_date": o["order_date"] + timedelta(days=3),
        "delivered_date": delivered,
        "qty_shipped": shipped,
    }


@pytest.fixture
def tiny_raw(tmp_path: Path) -> Path:
    o1 = order("SO1", "C1", "S1", week(0, 1), 10)
    o2 = order("SO2", "C1", "S1", week(2, 4), 6)  # Friday order, shipped the following Monday
    o3 = order("SO3", "C1", "S1", week(2, 4), 6, status="cancelled", line=2)
    o4 = order("SO4", "C2", "S2", week(1, 0), 4)
    o5 = order("SO5", "C1", "S1", week(5, 0), 8)
    orders = [o1, o2, o3, o4, o5]
    ts = datetime(2024, 1, 16, 10, 0, 0)  # week 2
    events = [
        ("E1", ts, "C1", "S1", "R001", "quote_request"),
        ("E1", ts + timedelta(seconds=2), "C1", "S1", "R001", "quote_request"),  # API retry
        ("E2", ts, "C1", None, "R001", "visit_checkin"),
    ]
    ev = [
        dict(zip(["event_id", "event_ts", "customer_id", "sku_id", "rep_id", "event_type"], e, strict=True))
        for e in events
    ]
    ships = [
        shipment("SH1", o1, week(0, 2), week(0, 4), 10),
        shipment("SH2", o2, week(3, 0), None, 3),  # partial, no proof of delivery
        shipment("SH4", o4, week(1, 1), week(1, 6), 4),  # late: promised day 3, delivered day 6
        shipment("SH5", o5, week(5, 1), week(5, 2), 8),
    ]
    return write_raw(tmp_path / "raw", orders, ev, ships)
