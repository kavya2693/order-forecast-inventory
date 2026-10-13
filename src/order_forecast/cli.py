"""One command: generate data, run the SQL pipeline, backtest the forecasters and the inventory policy."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from order_forecast.config import FULL, SMALL, TARGET_FILL_RATE
from order_forecast.data import generate
from order_forecast.evaluate import (
    ablation_table,
    accuracy_table,
    add_week_index,
    auc_table,
    fit_predict,
    inventory_table,
    log,
    make_split,
    pair_order_rate,
    summary,
)
from order_forecast.pipeline import build_features, source_counts
from order_forecast.report import write_report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true", help="regenerate the source data first")
    ap.add_argument("--small", action="store_true", help="CI-sized run (80 customers, 40 SKUs)")
    ap.add_argument("--data", default="data/raw")
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--no-ablation", action="store_true")
    args = ap.parse_args(argv)

    t0 = time.time()
    raw, out = Path(args.data), Path(args.out)
    scale = SMALL if args.small else FULL
    if args.refresh or not (raw / "sales_orders.parquet").exists():
        generate(scale, raw)
        log(f"generated {scale.n_customers} customers x {scale.n_skus} SKUs x {scale.n_weeks} weeks", t0)

    counts = source_counts(raw)
    df = add_week_index(build_features(raw))
    split = make_split(df)
    log(f"SQL pipeline: {counts['panel_rows']:,} customer x SKU weeks, {counts['pairs']:,} pairs", t0)

    pred, extras = fit_predict(df, split, t0, ablate=not args.no_ablation)
    acc = accuracy_table(pred, pair_order_rate(df, split), split)
    auc = auc_table(pred, extras, split)
    abl = ablation_table(pred, split) if not args.no_ablation else pd.DataFrame()
    skus = pd.read_parquet(raw / "skus.parquet").set_index("sku_id")["unit_cost"]
    inv = inventory_table(df, pred, skus, split)
    log("inventory simulation done", t0)

    out.mkdir(parents=True, exist_ok=True)
    acc.to_csv(out / "accuracy.csv", index=False)
    inv.to_csv(out / "inventory.csv", index=False)
    auc.to_csv(out / "order_auc.csv", index=False)
    if not abl.empty:
        abl.to_csv(out / "ablation.csv", index=False)
    meta = {
        "scale": {"customers": scale.n_customers, "skus": scale.n_skus, "weeks": scale.n_weeks},
        "split": {
            "val_start_week": str(split.weeks[split.val_start].date()),
            "test_start_week": str(split.weeks[split.test_start].date()),
            "test_weeks": split.n_weeks - split.test_start,
        },
        "source_counts": counts,
        "target_fill_rate": TARGET_FILL_RATE,
        "summary": summary(acc, inv),
        "feature_importance_gain_top10": dict(list(extras["importance"].items())[:10]),
        "runtime_seconds": round(time.time() - t0, 1),
    }
    (out / "metrics.json").write_text(json.dumps(meta, indent=2))
    write_report(out / "results.md", meta, acc, inv, auc, abl)

    with pd.option_context("display.width", 200, "display.max_columns", 20, "display.precision", 3):
        print("\nForecast accuracy on the test weeks (1 - WAPE)")
        print(
            acc[
                [
                    "horizon",
                    "method",
                    "accuracy_pair",
                    "bias_pair",
                    "accuracy_sku",
                    "accuracy_frequent",
                    "accuracy_intermittent",
                    "weeks_better_than_ets",
                ]
            ].to_string(index=False)
        )
        print("\nInventory policy over the test weeks")
        print(inv.to_string(index=False))
        print("\nOrder-occurrence ranking (h=1)")
        print(auc.to_string(index=False))
        if not abl.empty:
            print("\nSource ablation, LightGBM two-stage, h=1")
            print(abl.to_string(index=False))
    log(f"wrote {out}/", t0)


if __name__ == "__main__":
    main()
