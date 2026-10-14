"""Seeded generator for the three source systems of a B2B distributor.

Writes, as parquet under ``data/raw``:

- ``sales_orders``     one row per order line (ERP), including cancelled lines
- ``field_app_events`` visit check-ins, catalog views and quote requests from the reps' app API,
                       with API-retry duplicates and three regional outage windows
- ``shipments``        one row per shipped line (WMS/TMS), with partial and late deliveries
- ``customers``, ``skus`` small dimension tables

Demand is generated week by week so that each source carries a causal signal the others do
not: a quote request precedes an order, a rep visit raises next week's order probability, and
a partial shipment makes the customer reorder the following week.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from order_forecast.config import FULL, Scale

CATEGORIES = ["beverages", "snacks", "household", "personal_care", "frozen", "dry_grocery"]
CASE_PACKS = np.array([1, 6, 12, 24])
REGIONS = ["north", "south", "east", "west", "central"]


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def holiday_effects(week_starts: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """Logit shift on order probability and multiplier on quantity, per week.

    Customers stock up in the two weeks before Christmas, then mostly stop ordering over the
    Christmas / New Year shutdown and the first week of August.
    """
    logit = np.zeros(len(week_starts))
    qty = np.ones(len(week_starts))
    for i, ws in enumerate(week_starts):
        we = ws + timedelta(days=6)
        xmas = pd.Timestamp(year=ws.year, month=12, day=25)
        if ws <= xmas <= we or (ws.month == 1 and ws.day <= 7) or (ws.month == 12 and ws.day >= 29):
            logit[i], qty[i] = -2.0, 0.6
        elif 7 <= (xmas - ws).days <= 20:
            logit[i], qty[i] = 0.5, 1.35
        elif ws.month == 8 and ws.day <= 7:
            logit[i], qty[i] = -1.2, 0.8
    return logit, qty


def generate(scale: Scale = FULL, out_dir: Path | str = "data/raw") -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(scale.seed)
    out = Path(out_dir)
    n_c, n_s, n_w = scale.n_customers, scale.n_skus, scale.n_weeks
    week_starts = pd.date_range(pd.Timestamp(scale.start), periods=n_w, freq="7D")

    # ---- dimensions -------------------------------------------------------------------------
    sku_cat = rng.integers(0, len(CATEGORIES), n_s)
    unit_cost = np.round(rng.lognormal(2.0, 0.6, n_s), 2)
    skus = pd.DataFrame(
        {
            "sku_id": [f"S{i:04d}" for i in range(n_s)],
            "category": [CATEGORIES[c] for c in sku_cat],
            "case_pack": rng.choice(CASE_PACKS, n_s, p=[0.2, 0.35, 0.3, 0.15]),
            "unit_cost": unit_cost,
            "list_price": np.round(unit_cost * rng.uniform(1.25, 1.6, n_s), 2),
        }
    )
    cust_size = rng.lognormal(0.0, 0.7, n_c)
    cust_region = rng.integers(0, len(REGIONS), n_c)
    cust_cycle = rng.choice([1, 2, 4], n_c, p=[0.45, 0.4, 0.15])
    cust_trend = rng.normal(0.0, 0.25, n_c)  # log-size drift per year
    adopts_app = rng.random(n_c) < 0.7
    app_start = np.where(adopts_app, rng.integers(0, n_w // 3, n_c), n_w + 1)
    churn_week = np.where(rng.random(n_c) < 0.05, rng.integers(n_w // 3, n_w, n_c), n_w + 1)
    pref_day = rng.integers(0, 5, n_c)
    rep_of = rng.integers(0, max(4, n_c // 25), n_c)
    customers = pd.DataFrame(
        {
            "customer_id": [f"C{i:04d}" for i in range(n_c)],
            "region": [REGIONS[r] for r in cust_region],
            "segment": np.where(cust_size > 1.5, "key_account", np.where(cust_size > 0.6, "mid", "small")),
            "rep_id": [f"R{r:03d}" for r in rep_of],
        }
    )

    # ---- assortment: each customer buys a popularity-weighted subset of SKUs -----------------
    pop = rng.dirichlet(np.full(n_s, 0.6))
    pc, ps = [], []
    for c in range(n_c):
        k = int(rng.integers(max(3, n_s // 10), max(6, n_s // 5) + 1))
        chosen = rng.choice(n_s, size=min(k, n_s), replace=False, p=pop)
        pc.extend([c] * len(chosen))
        ps.extend(chosen.tolist())
    pair_c = np.array(pc)
    pair_s = np.array(ps)
    n_p = len(pair_c)
    # Pair propensity: some lines are staples ordered every cycle, others occasional.
    pair_base = rng.normal(-0.3, 1.1, n_p)
    pair_mean_qty = cust_size[pair_c] * rng.lognormal(2.3, 0.6, n_p)
    pair_start = np.where(rng.random(n_p) < 0.85, 0, rng.integers(0, n_w // 2, n_p))

    season_amp = rng.uniform(0.15, 0.6, len(CATEGORIES))
    season_phase = rng.uniform(0, 2 * np.pi, len(CATEGORIES))
    hol_logit, hol_qty = holiday_effects(week_starts)

    # Regional field-app outages: no events reach the API for a whole region for 1-2 weeks.
    outages = [
        (int(rng.integers(10, n_w - 5)), int(rng.integers(1, 3)), int(rng.integers(0, len(REGIONS))))
        for _ in range(3)
    ]

    # ---- weekly latent process ----------------------------------------------------------------
    weeks_since = rng.integers(0, 4, n_p).astype(float)
    partial_prev = np.zeros(n_p, dtype=bool)
    intent_next = _sigmoid(pair_base) > rng.random(n_p)
    visit_prev = np.zeros(n_c, dtype=bool)

    qty_w = np.zeros((n_w, n_p))
    partial_w = np.zeros((n_w, n_p), dtype=bool)
    quote_w = np.zeros((n_w, n_p), dtype=bool)
    view_w = np.zeros((n_w, n_p), dtype=bool)
    visit_w = np.zeros((n_w, n_c), dtype=bool)
    blackout_w = np.zeros((n_w, n_c), dtype=bool)

    for t in range(n_w):
        cat = sku_cat[pair_s]
        season = season_amp[cat] * np.sin(2 * np.pi * t / 52.0 + season_phase[cat])
        live = (t >= pair_start) & (t < churn_week[pair_c])
        cycle = cust_cycle[pair_c]
        due = np.clip(weeks_since / cycle - 1.0, -1.0, 2.0)
        logit = pair_base + 1.2 * due + season + hol_logit[t] + 0.6 * visit_prev[pair_c] + 1.3 * partial_prev
        # Next week's intent is formed now; a quote this week is how the rep's app sees it.
        p_order = _sigmoid(logit)
        order = (
            live
            & (intent_next | (rng.random(n_p) < 0.15 * p_order))
            & (rng.random(n_p) < 0.9 + 0.1 * p_order)
        )
        size = np.exp(cust_trend[pair_c] * t / 52.0)
        mu = pair_mean_qty * size * np.exp(0.5 * season) * hol_qty[t] * (1 + 0.5 * partial_prev)
        q = mu * rng.lognormal(-0.06, 0.35, n_p)
        outlier = rng.random(n_p) < 0.012
        q = np.where(outlier, q * rng.uniform(4, 8, n_p), q)
        pack = skus["case_pack"].to_numpy()[pair_s]
        q = np.maximum(pack, np.ceil(q / pack) * pack)
        qty_w[t] = np.where(order, q, 0.0)

        partial = order & (rng.random(n_p) < 0.05)
        partial_w[t] = partial

        # Intent for t+1 drives quotes and catalog views during week t.
        logit_next = (
            pair_base
            + 1.2 * np.clip((np.where(order, 0, weeks_since + 1)) / cycle - 1.0, -1.0, 2.0)
            + season_amp[cat] * np.sin(2 * np.pi * (t + 1) / 52.0 + season_phase[cat])
            + hol_logit[min(t + 1, n_w - 1)]
            + 1.3 * partial
        )
        visit = rng.random(n_c) < np.where(cust_size > 1.5, 0.45, 0.2)
        logit_next = logit_next + 0.6 * visit[pair_c]
        intent_next = rng.random(n_p) < _sigmoid(logit_next)

        on_app = t >= app_start[pair_c]
        quote_w[t] = on_app & np.where(intent_next, rng.random(n_p) < 0.45, rng.random(n_p) < 0.04)
        view_w[t] = on_app & np.where(intent_next, rng.random(n_p) < 0.2, rng.random(n_p) < 0.07)
        visit_w[t] = visit
        for start, length, region in outages:
            if start <= t < start + length:
                blackout_w[t] |= cust_region == region

        weeks_since = np.where(order, 0.0, weeks_since + 1)
        partial_prev = partial
        visit_prev = visit

    tables = _materialise(
        rng,
        scale,
        week_starts,
        customers,
        skus,
        pair_c,
        pair_s,
        pref_day,
        rep_of,
        qty_w,
        partial_w,
        quote_w,
        view_w,
        visit_w,
        blackout_w,
    )
    out.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(out / f"{name}.parquet", index=False)
    return tables


def _materialise(
    rng: np.random.Generator,
    scale: Scale,
    week_starts: pd.DatetimeIndex,
    customers: pd.DataFrame,
    skus: pd.DataFrame,
    pair_c: np.ndarray,
    pair_s: np.ndarray,
    pref_day: np.ndarray,
    rep_of: np.ndarray,
    qty_w: np.ndarray,
    partial_w: np.ndarray,
    quote_w: np.ndarray,
    view_w: np.ndarray,
    visit_w: np.ndarray,
    blackout_w: np.ndarray,
) -> dict[str, pd.DataFrame]:
    cust_ids = customers["customer_id"].to_numpy()
    sku_ids = skus["sku_id"].to_numpy()
    list_price = skus["list_price"].to_numpy()
    ws = week_starts.to_numpy()

    # ---- sales orders -----------------------------------------------------------------------
    t_idx, p_idx = np.nonzero(qty_w)
    qty = qty_w[t_idx, p_idx]
    day = np.where(rng.random(len(t_idx)) < 0.8, pref_day[pair_c[p_idx]], rng.integers(0, 5, len(t_idx)))
    # One in ten order weeks arrives as two lines on different days.
    split = rng.random(len(t_idx)) < 0.10
    q1 = np.where(split, np.maximum(1, np.round(qty * rng.uniform(0.3, 0.7, len(t_idx)))), qty)
    lines = pd.DataFrame(
        {
            "t": np.concatenate([t_idx, t_idx[split]]),
            "p": np.concatenate([p_idx, p_idx[split]]),
            "qty": np.concatenate([q1, qty[split] - q1[split]]),
            "day": np.concatenate([day, (day[split] + rng.integers(1, 4, split.sum())) % 5]),
            "partial": np.concatenate([partial_w[t_idx, p_idx], np.zeros(split.sum(), dtype=bool)]),
        }
    )
    lines = lines[lines["qty"] > 0].reset_index(drop=True)
    order_date = ws[lines["t"].to_numpy()] + lines["day"].to_numpy().astype("timedelta64[D]")
    cust = cust_ids[pair_c[lines["p"].to_numpy()]]
    sku = sku_ids[pair_s[lines["p"].to_numpy()]]
    lines["customer_id"], lines["sku_id"], lines["order_date"] = cust, sku, order_date
    hdr = lines.groupby(["customer_id", "order_date"]).ngroup()
    lines["order_id"] = "SO" + (hdr + 100000).astype(str)
    lines = lines.sort_values(["order_id", "sku_id"]).reset_index(drop=True)
    lines["line_no"] = lines.groupby("order_id").cumcount() + 1
    n = len(lines)
    discount = np.where(rng.random(n) < 0.2, rng.uniform(0.02, 0.12, n), 0.0)
    price_idx = pd.Index(sku_ids).get_indexer(lines["sku_id"])
    status = np.where(rng.random(n) < 0.02, "cancelled", "open")
    sales_orders = pd.DataFrame(
        {
            "order_id": lines["order_id"],
            "line_no": lines["line_no"],
            "customer_id": lines["customer_id"],
            "sku_id": lines["sku_id"],
            "order_date": pd.to_datetime(lines["order_date"]).dt.date,
            "qty_ordered": lines["qty"].astype(int),
            "unit_price": np.round(list_price[price_idx] * (1 - discount), 2),
            "channel": rng.choice(["field_app", "edi", "phone"], n, p=[0.45, 0.35, 0.2]),
            "status": status,
        }
    )
    # A cancelled line was re-keyed by the customer service desk the same day, so demand stands.
    cancelled = sales_orders[sales_orders["status"] == "cancelled"].copy()
    cancelled["status"] = "open"
    cancelled["line_no"] = cancelled["line_no"] + 100
    sales_orders = pd.concat([sales_orders, cancelled], ignore_index=True)

    # ---- shipments --------------------------------------------------------------------------
    so = sales_orders[sales_orders["status"] == "open"].reset_index(drop=True)
    part_map = lines.set_index(["order_id", "line_no"])["partial"]
    key = pd.MultiIndex.from_arrays(
        [so["order_id"], so["line_no"].where(so["line_no"] < 100, so["line_no"] - 100)]
    )
    is_partial = part_map.reindex(key).fillna(False).to_numpy(dtype=bool)
    m = len(so)
    ship_lag = rng.choice([0, 1, 2], m, p=[0.5, 0.35, 0.15])
    transit = rng.choice([1, 2, 3, 4, 6], m, p=[0.35, 0.35, 0.15, 0.1, 0.05])
    ship_date = pd.to_datetime(so["order_date"]) + pd.to_timedelta(ship_lag, unit="D")
    delivered = ship_date + pd.to_timedelta(transit, unit="D")
    delivered = delivered.where(rng.random(m) > 0.03)  # proof-of-delivery scans go missing
    shipped = np.where(is_partial, np.floor(so["qty_ordered"] * rng.uniform(0.4, 0.9, m)), so["qty_ordered"])
    region_idx = pd.Index(cust_ids).get_indexer(so["customer_id"])
    shipments = pd.DataFrame(
        {
            "shipment_id": [f"SH{i:07d}" for i in range(m)],
            "order_id": so["order_id"],
            "line_no": so["line_no"],
            "customer_id": so["customer_id"],
            "sku_id": so["sku_id"],
            "warehouse_id": "W" + customers["region"].str[:2].str.upper().to_numpy()[region_idx],
            "ship_date": ship_date.dt.date,
            "promised_date": (pd.to_datetime(so["order_date"]) + pd.to_timedelta(3, unit="D")).dt.date,
            "delivered_date": delivered.dt.date,
            "qty_shipped": shipped.astype(int),
        }
    )

    # ---- field app events -------------------------------------------------------------------
    ev = []
    for kind, mat, per_pair in (
        ("quote_request", quote_w, True),
        ("catalog_view", view_w, True),
        ("visit_checkin", visit_w, False),
    ):
        tt, ii = np.nonzero(mat)
        c = pair_c[ii] if per_pair else ii
        keep = ~blackout_w[tt, c]
        tt, ii, c = tt[keep], ii[keep], c[keep]
        secs = rng.integers(0, 5 * 24 * 3600, len(tt)).astype("timedelta64[s]")
        ev.append(
            pd.DataFrame(
                {
                    "event_ts": ws[tt] + secs,
                    "customer_id": cust_ids[c],
                    "sku_id": sku_ids[pair_s[ii]] if per_pair else None,
                    "rep_id": pd.Series(rep_of[c]).map("R{:03d}".format).to_numpy(),
                    "event_type": kind,
                }
            )
        )
    events = pd.concat(ev, ignore_index=True).sort_values("event_ts").reset_index(drop=True)
    events.insert(0, "event_id", [f"E{i:08d}" for i in range(len(events))])
    # The app retries on timeouts, so the API log carries exact duplicates a few seconds apart.
    dup = events.sample(frac=0.03, random_state=scale.seed).copy()
    dup["event_ts"] = dup["event_ts"] + pd.to_timedelta(rng.integers(1, 4, len(dup)), unit="s")
    events = pd.concat([events, dup], ignore_index=True).sort_values("event_ts").reset_index(drop=True)

    return {
        "customers": customers,
        "skus": skus,
        "sales_orders": sales_orders,
        "shipments": shipments,
        "field_app_events": events,
    }
