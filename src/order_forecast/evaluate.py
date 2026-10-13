"""Backtest: fit on the training weeks, score forecasts and inventory policy on the held-out weeks."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from order_forecast.baseline import ets_forecasts
from order_forecast.config import (
    HORIZONS,
    MIN_HISTORY_WEEKS,
    SERVICE_Z,
    TARGET_FILL_RATE,
    TEST_WEEKS,
    VAL_WEEKS,
)
from order_forecast.inventory import simulate, z_for_fill_rate
from order_forecast.metrics import accuracy, bias
from order_forecast.models import (
    ALL_FEATURES,
    FIELD_APP,
    HISTORY,
    LOGISTICS,
    SingleStage,
    TwoStage,
    horizon_frame,
)

METHODS: dict[str, Callable[[], TwoStage | SingleStage]] = {
    "lgbm_two_stage": lambda: TwoStage("lightgbm"),
    "xgb_two_stage": lambda: TwoStage("xgboost"),
    "lgbm_single_tweedie": lambda: SingleStage(),
}
ABLATIONS = {
    "history only": HISTORY,
    "history + field app": HISTORY + FIELD_APP,
    "history + logistics": HISTORY + LOGISTICS,
    "all three sources": ALL_FEATURES,
}
BASELINES = ("ets", "moving_avg_4w")
# Derived from the LightGBM two-stage model, not separately fitted.
VARIANTS = ("lgbm_point",)
FREQUENT_RATE = 0.5


@dataclass
class Split:
    n_weeks: int
    val_start: int
    test_start: int
    weeks: list[pd.Timestamp] = field(default_factory=list)


def make_split(df: pd.DataFrame) -> Split:
    weeks = sorted(df["week_start"].unique())
    n = len(weeks)
    test_start = n - TEST_WEEKS
    return Split(n, test_start - VAL_WEEKS, test_start, [pd.Timestamp(w) for w in weeks])


def add_week_index(df: pd.DataFrame) -> pd.DataFrame:
    first = df["week_start"].min()
    df = df.copy()
    df["wk"] = ((df["week_start"] - first).dt.days // 7).astype(int)
    return df


def log(msg: str, t0: float) -> None:
    print(f"[{time.time() - t0:6.1f}s] {msg}", flush=True)


def fit_predict(df: pd.DataFrame, split: Split, t0: float, ablate: bool = True) -> tuple[pd.DataFrame, dict]:
    """Return one row per pair x origin (from the validation window on) with every forecast."""
    ets = ets_forecasts(df[["customer_id", "sku_id", "week_start", "qty_l0"]], split.weeks[split.val_start])
    df = df.merge(ets, on=["customer_id", "sku_id", "week_start"], how="left")
    log("ETS baseline fitted", t0)

    keep = ["customer_id", "sku_id", "week_start", "wk", "category", "ets", "qty_mean_4w", "y_h1", "y_h2"]
    pred = df.loc[df["wk"] + 1 >= split.val_start, keep].copy()
    pred = pred.rename(columns={"qty_mean_4w": "moving_avg_4w"})
    for b in BASELINES:
        for h in HORIZONS:
            pred[f"{b}_h{h}"] = pred[b]
    extras: dict[str, Any] = {"auc": {}, "importance": {}}

    for h in HORIZONS:
        hf = horizon_frame(df, h)
        train = hf[
            (hf["wk"] + h < split.val_start) & (hf["history_weeks"] >= MIN_HISTORY_WEEKS) & hf["y"].notna()
        ]
        score = hf.loc[pred.index]
        for name, make in METHODS.items():
            model = make().fit(train, train["y"].to_numpy())
            pred[f"{name}_h{h}"] = model.predict(score)
            if name == "lgbm_two_stage":
                # The volume-weighted median of a mostly-zero week is zero, so WAPE rewards a
                # forecast that says "no order" unless an order is likely. Kept to show that.
                assert isinstance(model, TwoStage)
                p_order = model.predict_proba(score)
                pred[f"lgbm_point_h{h}"] = np.where(p_order >= 0.5, model.predict_size(score), 0.0)
            if h == 1 and isinstance(model, TwoStage):
                extras["auc"][name] = model.predict_proba(score)
                if name == "lgbm_two_stage":
                    imp = pd.Series(model.clf.booster_.feature_importance("gain"), index=model.features)
                    extras["importance"] = (imp / imp.sum()).sort_values(ascending=False).round(4).to_dict()
            log(f"h={h} {name} fitted on {len(train):,} rows", t0)
        if h == 1 and ablate:
            for label, feats in ABLATIONS.items():
                if label == "all three sources":
                    pred[f"abl::{label}"] = pred["lgbm_two_stage_h1"]
                    continue
                model = TwoStage("lightgbm", features=list(feats)).fit(train, train["y"].to_numpy())
                pred[f"abl::{label}"] = model.predict(score)
                log(f"ablation '{label}' fitted", t0)
    return pred, extras


def pair_order_rate(df: pd.DataFrame, split: Split) -> pd.Series:
    hist = df[df["wk"] < split.val_start]
    return hist.groupby(["customer_id", "sku_id"])["qty_l0"].apply(lambda s: float((s > 0).mean()))


def accuracy_table(pred: pd.DataFrame, rate: pd.Series, split: Split) -> pd.DataFrame:
    rows = []
    rate_df = rate.rename("train_order_rate").reset_index()
    p = pred.merge(rate_df, on=["customer_id", "sku_id"], how="left")
    p["segment"] = np.where(p["train_order_rate"].fillna(0) >= FREQUENT_RATE, "frequent", "intermittent")
    methods = [*METHODS, *VARIANTS, *BASELINES]
    for h in HORIZONS:
        t = p[(p["wk"] + h >= split.test_start) & p[f"y_h{h}"].notna()]
        y = t[f"y_h{h}"].to_numpy()
        for m in methods:
            f = t[f"{m}_h{h}"].to_numpy()
            sku = t.assign(f=f, y=y).groupby(["sku_id", "wk"])[["f", "y"]].sum()
            weekly = (
                t.assign(f=f, y=y, e=np.abs(f - y), eb=np.abs(t[f"ets_h{h}"] - y))
                .groupby("wk")[["e", "eb"]]
                .sum()
            )
            row = {
                "horizon": h,
                "method": m,
                "accuracy_pair": accuracy(y, f),
                "bias_pair": bias(y, f),
                "accuracy_sku": accuracy(sku["y"].to_numpy(), sku["f"].to_numpy()),
                "weeks_better_than_ets": int((weekly["e"] < weekly["eb"]).sum()),
                "test_weeks": len(weekly),
            }
            for seg in ("frequent", "intermittent"):
                mask = (t["segment"] == seg).to_numpy()
                row[f"accuracy_{seg}"] = accuracy(y[mask], f[mask])
                row[f"bias_{seg}"] = bias(y[mask], f[mask])
            rows.append(row)
    return pd.DataFrame(rows)


def ablation_table(pred: pd.DataFrame, split: Split) -> pd.DataFrame:
    t = pred[(pred["wk"] + 1 >= split.test_start) & pred["y_h1"].notna()]
    y = t["y_h1"].to_numpy()
    rows = []
    for label in ABLATIONS:
        f = t[f"abl::{label}"].to_numpy()
        rows.append({"features": label, "accuracy_pair": accuracy(y, f), "bias_pair": bias(y, f)})
    return pd.DataFrame(rows)


def auc_table(pred: pd.DataFrame, extras: dict, split: Split) -> pd.DataFrame:
    mask = ((pred["wk"] + 1 >= split.test_start) & pred["y_h1"].notna()).to_numpy()
    ordered = (pred.loc[mask, "y_h1"] > 0).astype(int).to_numpy()
    rows = [
        {"scorer": "ETS level (rank only)", "auc": roc_auc_score(ordered, pred.loc[mask, "ets"].fillna(0))}
    ]
    for name, proba in extras["auc"].items():
        rows.append({"scorer": f"{name} P(order)", "auc": roc_auc_score(ordered, np.asarray(proba)[mask])})
    return pd.DataFrame(rows)


def _sku_matrix(frame: pd.DataFrame, col: str, skus: list[str], weeks: range) -> np.ndarray:
    g = frame.groupby(["sku_id", "wk"])[col].sum()
    full = pd.MultiIndex.from_product([skus, list(weeks)], names=["sku_id", "wk"])
    return g.reindex(full, fill_value=0.0).to_numpy(dtype=float).reshape(len(skus), len(weeks))


def inventory_table(df: pd.DataFrame, pred: pd.DataFrame, unit_cost: pd.Series, split: Split) -> pd.DataFrame:
    skus = sorted(unit_cost.index)
    cost = unit_cost.reindex(skus).to_numpy(dtype=float)
    test_weeks = range(split.test_start, split.n_weeks)
    origins = range(split.test_start - 1, split.n_weeks)
    val_origins = range(split.val_start - 1, split.test_start - 2)

    # Actual demand includes pairs that first ordered inside the window, which no forecaster saw.
    demand = _sku_matrix(df, "qty_l0", skus, test_weeks)
    val = pred[pred["wk"].isin(val_origins)]
    tst = pred[pred["wk"].isin(origins)]
    actual2 = _sku_matrix(val.assign(a=val["y_h1"] + val["y_h2"]), "a", skus, val_origins)

    rows = []
    for m in [*METHODS, *VARIANTS, *BASELINES, "perfect"]:
        if m == "perfect":
            # Perfect knowledge of every week, including new pairs, so stock can be exact.
            nxt = np.concatenate([demand, np.zeros((len(skus), 2))], axis=1)
            f1, f2 = nxt[:, 0 : len(origins)], nxt[:, 1 : len(origins) + 1]
            sigma = np.zeros(len(skus))
        else:
            f1 = _sku_matrix(tst, f"{m}_h1", skus, origins)
            f2 = _sku_matrix(tst, f"{m}_h2", skus, origins)
            fc2 = _sku_matrix(val.assign(x=val[f"{m}_h1"] + val[f"{m}_h2"]), "x", skus, val_origins)
            sigma = np.sqrt(((actual2 - fc2) ** 2).mean(axis=1))
        fixed = simulate(demand, f1, f2, sigma, cost, SERVICE_Z)
        if m == "perfect":
            z_star, matched = 0.0, fixed
        else:
            z_star = z_for_fill_rate(demand, f1, f2, sigma, cost, TARGET_FILL_RATE)
            matched = simulate(demand, f1, f2, sigma, cost, z_star) if np.isfinite(z_star) else fixed
        rows.append(
            {
                "method": m,
                "fixed_z": SERVICE_Z,
                "fill_rate_fixed_z": fixed.fill_rate,
                "holding_cost_fixed_z": fixed.holding_cost_annual,
                "safety_stock_value": float((SERVICE_Z * sigma * cost).sum()),
                f"z_for_{int(TARGET_FILL_RATE * 100)}pct_fill": z_star,
                "holding_cost_matched_fill": matched.holding_cost_annual,
                "avg_inventory_value_matched": matched.avg_inventory_value,
                "fill_rate_matched": matched.fill_rate,
            }
        )
    return pd.DataFrame(rows)


def summary(acc: pd.DataFrame, inv: pd.DataFrame) -> dict:
    h1 = acc[acc["horizon"] == 1].set_index("method")
    i = inv.set_index("method")
    return {
        "accuracy_pair_h1": h1["accuracy_pair"].round(4).to_dict(),
        "accuracy_sku_h1": h1["accuracy_sku"].round(4).to_dict(),
        "bias_pair_h1": h1["bias_pair"].round(4).to_dict(),
        "holding_cost_matched_fill": i["holding_cost_matched_fill"].round(0).to_dict(),
        "fill_rate_fixed_z": i["fill_rate_fixed_z"].round(4).to_dict(),
    }
