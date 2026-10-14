"""ETS(A,N,N) baseline: simple exponential smoothing per customer x SKU series.

Point forecasts are flat across horizons, so the same level serves t+1 and t+2. The smoothing
weight is chosen per series from a grid by one-step squared error on training weeks only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ALPHAS = np.array([0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.7])
INIT_WEEKS = 8


def _smooth(y: np.ndarray, alpha: float, init: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (level after each week, one-step forecast for each week). y is pairs x weeks, NaN = not live."""
    n_p, n_w = y.shape
    level = np.full(n_p, np.nan)
    levels = np.full((n_p, n_w), np.nan)
    fcst = np.full((n_p, n_w), np.nan)
    for t in range(n_w):
        obs = y[:, t]
        live = ~np.isnan(obs)
        start = live & np.isnan(level)
        level = np.where(start, init, level)
        fcst[:, t] = np.where(live, level, np.nan)
        level = np.where(live, alpha * obs + (1 - alpha) * level, level)
        levels[:, t] = np.where(live, level, np.nan)
    return levels, fcst


def ets_forecasts(panel: pd.DataFrame, fit_until: pd.Timestamp) -> pd.DataFrame:
    """Level at the end of every origin week, with alpha fitted on weeks before ``fit_until``.

    ``panel`` needs customer_id, sku_id, week_start, qty_l0 (the week's demand).
    """
    wide = panel.pivot_table(
        index=["customer_id", "sku_id"], columns="week_start", values="qty_l0", aggfunc="sum", observed=True
    )
    weeks = wide.columns
    y = wide.to_numpy(dtype=float)
    first = np.argmax(~np.isnan(y), axis=1)
    init = np.array([np.nanmean(y[i, f : f + INIT_WEEKS]) for i, f in enumerate(first)])
    fit_mask = np.asarray(pd.DatetimeIndex(weeks) < fit_until)

    best_sse = np.full(len(y), np.inf)
    best_levels = np.full_like(y, np.nan)
    best_alpha = np.zeros(len(y))
    for a in ALPHAS:
        levels, fcst = _smooth(y, float(a), init)
        err = (y[:, fit_mask] - fcst[:, fit_mask]) ** 2
        sse = np.nansum(err, axis=1)
        better = sse < best_sse
        best_sse = np.where(better, sse, best_sse)
        best_alpha = np.where(better, a, best_alpha)
        best_levels[better] = levels[better]

    keys = ["customer_id", "sku_id"]
    long = (
        pd.DataFrame(best_levels, index=wide.index, columns=weeks)
        .reset_index()
        .melt(id_vars=keys, var_name="week_start", value_name="ets")
        .dropna(subset=["ets"])
    )
    # melt hands back the column labels as objects; restore the panel's datetime dtype for the join.
    long["week_start"] = pd.to_datetime(long["week_start"]).astype(panel["week_start"].dtype)
    alphas = pd.DataFrame({"ets_alpha": best_alpha}, index=wide.index).reset_index()
    return long.merge(alphas, on=keys).sort_values([*keys, "week_start"]).reset_index(drop=True)
