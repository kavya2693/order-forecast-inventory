"""Markdown run report, so the numbers in the README can be traced to a file."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def _table(df: pd.DataFrame, floatfmt: str = "{:.3f}") -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        cells = [floatfmt.format(v) if isinstance(v, float) else str(v) for v in r]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_report(
    path: Path, meta: dict, acc: pd.DataFrame, inv: pd.DataFrame, auc: pd.DataFrame, abl: pd.DataFrame
) -> None:
    parts = [
        "# Run report",
        "",
        f"Scale: {meta['scale']}. Test window starts {meta['split']['test_start_week']} "
        f"({meta['split']['test_weeks']} weeks); validation for safety stock starts "
        f"{meta['split']['val_start_week']}.",
        "",
        "## Source counts",
        "",
        _table(pd.DataFrame([meta["source_counts"]])),
        "",
        "## Forecast accuracy (test weeks)",
        "",
        _table(acc),
        "",
        "## Inventory policy (test weeks, SKU level)",
        "",
        _table(inv.round(4), "{:,.4f}"),
        "",
        "## Order-occurrence AUC (h=1)",
        "",
        _table(auc),
    ]
    if not abl.empty:
        parts += ["", "## Source ablation (LightGBM two-stage, h=1)", "", _table(abl)]
    parts += ["", f"Runtime: {meta['runtime_seconds']} s", ""]
    path.write_text("\n".join(parts))
