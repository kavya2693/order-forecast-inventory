"""Inline the exported order list into the compositions (renders cannot fetch files).

Writes the SHEET block of compositions/value.html (the planner's order list, slide 07) and the
TRACE block of compositions/s04-routes.html (the forecast and stock traces, slide 06).

Usage: python3 tools/inject_sheet.py assets/order_list.json compositions/value.html \
         compositions/s04-routes.html --rows S0029,S0014,S0005,S0066,S0131,S0044
"""

import argparse
import json
import re

ap = argparse.ArgumentParser()
ap.add_argument("export")
ap.add_argument("value_html")
ap.add_argument("routes_html")
ap.add_argument("--rows", required=True, help="SKU ids shown as sheet rows, in order")
a = ap.parse_args()

with open(a.export) as fh:
    d = json.load(fh)
dec = d["decision"]
by_sku = {r["sku"]: r for r in dec["rows"]}
keys = (
    "sku",
    "category",
    "on_hand",
    "in_transit",
    "forecast_2wk",
    "safety",
    "order_qty",
    "exp_customer_orders",
    "customer_lines",
    "next_week_demand",
)
sheet = {
    "friday": dec["friday"],
    "week_start": dec["week_start"],
    "arrives": dec["arrives"],
    "next_week": d["weeks"][dec["week_index"] + 1],
    "n_skus": dec["n_skus"],
    "n_to_order": dec["n_to_order"],
    "order_value": dec["order_value"],
    "z": d["z"]["lgbm_two_stage"],
    "rows": [{k: by_sku[s][k] for k in keys} for s in a.rows.split(",")],
}
w0 = d["warmup_weeks"]
trace = {
    "weeks": d["weeks"],
    "warmup": w0,
    "sku": d["trace"]["sku"],
    "demand": d["trace"]["demand"],
    "lgbm": d["trace"]["forecast_h1_lgbm"],
    "ets": d["trace"]["forecast_h1_ets"],
    "stock_lgbm": d["stock_value_weekly"]["lgbm_two_stage"],
    "stock_ets": d["stock_value_weekly"]["ets"],
}


def inject(path: str, name: str, obj: dict) -> None:
    with open(path) as fh:
        html = fh.read()
    tag = name.upper()
    block = (
        f"/* {tag}:BEGIN */ const {tag} = " + json.dumps(obj, separators=(",", ":")) + f"; /* {tag}:END */"
    )
    html, n = re.subn(rf"/\* {tag}:BEGIN \*/.*?/\* {tag}:END \*/", lambda _: block, html, flags=re.S)
    assert n == 1, f"{tag} marker not found in {path}"
    with open(path, "w") as fh:
        fh.write(html)


inject(a.value_html, "sheet", sheet)
inject(a.routes_html, "trace", trace)
print("injected", len(sheet["rows"]), "rows and", len(trace["weeks"]), "weeks")
