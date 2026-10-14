"""Re-run the repo's own backtest for the LightGBM two-stage forecaster and export the planner's
replenishment order list for one Friday, plus the traces drawn on slide 06.

Same data (data/raw, seed 7), split, features, models and inventory policy as `make run`.
Only the forecasters are restricted: the LightGBM two-stage model (the one the README says it
would explain to a planner) and the ETS baseline. The script re-computes the inventory table for
those two and asserts it matches outputs/inventory.csv, so the exported rows come from the same
simulation as the published numbers.

The order list is the order-up-to decision of order_forecast.inventory.simulate at the end of
one test week (z tuned for 98% fill), traced step by step with the same arithmetic.

Run:  cd <repo> && PYTHONPATH=src .venv/bin/python <this file> <out.json>  (about 4 min)
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from order_forecast import evaluate
from order_forecast.config import ANNUAL_HOLDING_RATE, SERVICE_Z, TARGET_FILL_RATE, WARMUP_WEEKS
from order_forecast.evaluate import _sku_matrix, add_week_index, fit_predict, inventory_table, make_split
from order_forecast.inventory import simulate, z_for_fill_rate
from order_forecast.models import TwoStage
from order_forecast.pipeline import build_features

DECISION_WEEK = 12  # simulated test week whose Friday order list is shown (0-based, after warm-up)
TRACE_SKU_RANK = 20  # slide 06 SKU: 20th by test-window demand (a typical, not a top, SKU)

t0 = time.time()
raw = Path("data/raw")
evaluate.METHODS = {"lgbm_two_stage": lambda: TwoStage("lightgbm")}
df = add_week_index(build_features(raw))
split = make_split(df)
pred, extras = fit_predict(df, split, t0, ablate=False)
skus_df = pd.read_parquet(raw / "skus.parquet").set_index("sku_id")
unit_cost = skus_df["unit_cost"]
inv = inventory_table(df, pred, unit_cost, split).set_index("method")

pub = pd.read_csv("outputs/inventory.csv").set_index("method")
for m in ("lgbm_two_stage", "ets"):
    for col in ("holding_cost_matched_fill", "z_for_98pct_fill", "fill_rate_fixed_z"):
        assert abs(inv.at[m, col] - pub.at[m, col]) < 1e-6 * max(1.0, abs(pub.at[m, col])), (m, col)
print("re-run matches outputs/inventory.csv for lgbm_two_stage and ets")

# ---- same matrices as inventory_table
skus = sorted(unit_cost.index)
cost = unit_cost.reindex(skus).to_numpy(dtype=float)
test_weeks = range(split.test_start, split.n_weeks)
origins = range(split.test_start - 1, split.n_weeks)
val_origins = range(split.val_start - 1, split.test_start - 2)
demand = _sku_matrix(df, "qty_l0", skus, test_weeks)
val = pred[pred["wk"].isin(val_origins)]
tst = pred[pred["wk"].isin(origins)]
actual2 = _sku_matrix(val.assign(a=val["y_h1"] + val["y_h2"]), "a", skus, val_origins)


def trace(m):
    f1 = _sku_matrix(tst, f"{m}_h1", skus, origins)
    f2 = _sku_matrix(tst, f"{m}_h2", skus, origins)
    fc2 = _sku_matrix(val.assign(x=val[f"{m}_h1"] + val[f"{m}_h2"]), "x", skus, val_origins)
    sigma = np.sqrt(((actual2 - fc2) ** 2).mean(axis=1))
    z = z_for_fill_rate(demand, f1, f2, sigma, cost, TARGET_FILL_RATE)
    ref = simulate(demand, f1, f2, sigma, cost, z)
    # step-by-step copy of inventory.simulate that keeps the state of every week
    n_s, n_w = demand.shape
    ss = z * sigma
    on_hand = (np.nan_to_num(f1[:, 0] + f2[:, 0]) + ss).clip(0)
    arrivals = np.zeros((n_s, n_w + 2))
    st = {
        k: np.zeros((n_s, n_w))
        for k in ("open", "arrive", "demand", "filled", "close", "transit", "fc2", "order")
    }
    holding = 0.0
    for t in range(n_w):
        st["open"][:, t] = on_hand
        on_hand = on_hand + arrivals[:, t]
        st["arrive"][:, t] = arrivals[:, t]
        d = demand[:, t]
        filled = np.minimum(on_hand, d)
        on_hand = on_hand - filled
        st["demand"][:, t], st["filled"][:, t], st["close"][:, t] = d, filled, on_hand
        if t >= WARMUP_WEEKS:
            holding += (on_hand * cost).sum() * ANNUAL_HOLDING_RATE / 52.0
        target = np.nan_to_num(f1[:, t + 1] + f2[:, t + 1]) + ss
        position = on_hand + arrivals[:, t + 1]
        q = np.maximum(0.0, target - position)
        st["transit"][:, t], st["fc2"][:, t], st["order"][:, t] = arrivals[:, t + 1], target - ss, q
        arrivals[:, t + 2] += q
    hc = holding * 52.0 / (n_w - WARMUP_WEEKS)
    assert abs(hc - ref.holding_cost_annual) < 1e-6 * ref.holding_cost_annual, (
        m,
        hc,
        ref.holding_cost_annual,
    )
    return dict(z=z, sigma=sigma, ss=ss, f1=f1, f2=f2, ref=ref, **st)


lg, et = trace("lgbm_two_stage"), trace("ets")
weeks = [split.weeks[w] for w in test_weeks]
t = DECISION_WEEK
wk_start = weeks[t]
friday = wk_start + pd.Timedelta(days=4)
arrive = weeks[t + 2] if t + 2 < len(weeks) else wk_start + pd.Timedelta(days=14)

# expected customer orders next week = sum of P(order) over the SKU's customer lines at origin wk
proba = pd.Series(np.asarray(extras["auc"]["lgbm_two_stage"]), index=pred.index)
origin_wk = split.test_start + t
at = pred["wk"] == origin_wk
p_by_sku = proba[at].groupby(pred.loc[at, "sku_id"].astype(str)).sum()
lines_by_sku = pred.loc[at].groupby(pred.loc[at, "sku_id"].astype(str)).size()

rows = []
for i, s in enumerate(skus):
    rows.append(
        {
            "sku": s,
            "category": str(skus_df.at[s, "category"]) if "category" in skus_df.columns else "",
            "unit_cost": round(float(cost[i]), 2),
            "on_hand": round(float(lg["close"][i, t]), 1),
            "in_transit": round(float(lg["transit"][i, t]), 1),
            "forecast_2wk": round(float(lg["fc2"][i, t]), 1),
            "safety": round(float(lg["ss"][i]), 1),
            "order_qty": round(float(lg["order"][i, t]), 1),
            "order_value": round(float(lg["order"][i, t] * cost[i]), 2),
            "exp_customer_orders": round(float(p_by_sku.get(s, 0.0)), 2),
            "customer_lines": int(lines_by_sku.get(s, 0)),
            "ets_order_qty": round(float(et["order"][i, t]), 1),
            "ets_safety": round(float(et["ss"][i]), 1),
            "next_week_demand": round(float(lg["demand"][i, t + 1]), 1) if t + 1 < len(weeks) else None,
        }
    )

# slide 06 SKU trace
vol = demand.sum(axis=1)
k = int(np.argsort(-vol)[TRACE_SKU_RANK - 1])
f1_lg = lg["f1"][k, : len(weeks)]  # forecast made at the origin before week j, for week j
f1_et = et["f1"][k, : len(weeks)]
stock_val = lambda tr: [round(float((tr["close"][:, j] * cost).sum()), 0) for j in range(len(weeks))]  # noqa: E731
out = {
    "source": "re-run of make run (data/raw, seed 7), forecasters restricted to lgbm_two_stage + ets",
    "test_start_week": str(weeks[0].date()),
    "weeks": [str(w.date()) for w in weeks],
    "warmup_weeks": WARMUP_WEEKS,
    "z": {"lgbm_two_stage": round(lg["z"], 3), "ets": round(et["z"], 3), "fixed": SERVICE_Z},
    "fill_rate": {"lgbm_two_stage": round(lg["ref"].fill_rate, 4), "ets": round(et["ref"].fill_rate, 4)},
    "holding_cost": {
        "lgbm_two_stage": round(lg["ref"].holding_cost_annual, 0),
        "ets": round(et["ref"].holding_cost_annual, 0),
    },
    "decision": {
        "week_index": t,
        "week_start": str(wk_start.date()),
        "friday": str(friday.date()),
        "arrives": str(arrive.date()),
        "n_skus": len(skus),
        "n_to_order": int((lg["order"][:, t] > 0.5).sum()),
        "order_value": round(float((lg["order"][:, t] * cost).sum()), 0),
        "ets_order_value": round(float((et["order"][:, t] * cost).sum()), 0),
        "safety_value": round(float((lg["ss"] * cost).sum()), 0),
        "ets_safety_value": round(float((et["ss"] * cost).sum()), 0),
        "rows": rows,
    },
    "trace": {
        "sku": skus[k],
        "rank_by_volume": TRACE_SKU_RANK,
        "demand": [round(float(x), 1) for x in demand[k]],
        "forecast_h1_lgbm": [round(float(x), 1) for x in f1_lg],
        "forecast_h1_ets": [round(float(x), 1) for x in f1_et],
        "stock_lgbm": [round(float(x), 1) for x in lg["close"][k]],
        "stock_ets": [round(float(x), 1) for x in et["close"][k]],
        "safety_lgbm": round(float(lg["ss"][k]), 1),
        "safety_ets": round(float(et["ss"][k]), 1),
    },
    "stock_value_weekly": {"lgbm_two_stage": stock_val(lg), "ets": stock_val(et)},
}
Path(sys.argv[1]).write_text(json.dumps(out, indent=1))
d = out["decision"]
print({k_: v_ for k_, v_ in d.items() if k_ != "rows"}, out["z"], out["holding_cost"], "trace sku", skus[k])
print(f"done in {time.time() - t0:.0f}s")
