"""Weekly order-up-to simulation at SKU level, driven by a forecast and its own error history.

Policy per SKU: at the end of week t, order up to
    S_t = F(t+1 | t) + F(t+2 | t) + z * sigma
where F is the summed customer forecast and sigma is the RMSE of that two-week sum on the
validation weeks, measured for the same forecaster. An order placed at the end of week t
arrives at the start of week t+2. Demand that cannot be met from stock is lost.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from order_forecast.config import ANNUAL_HOLDING_RATE, WARMUP_WEEKS


@dataclass
class SimResult:
    fill_rate: float
    holding_cost_annual: float
    avg_inventory_value: float
    stockout_week_share: float
    units_lost: float


def simulate(
    demand: np.ndarray,
    f1: np.ndarray,
    f2: np.ndarray,
    sigma: np.ndarray,
    unit_cost: np.ndarray,
    z: float,
    warmup: int = WARMUP_WEEKS,
) -> SimResult:
    """``demand`` is SKUs x weeks; ``f1``/``f2`` are SKUs x (weeks + 1).

    Column j of ``f1``/``f2`` is the forecast made at the end of simulated week j - 1 for the
    following one and two weeks, so column 0 is the origin just before the window opens.
    """
    n_s, n_w = demand.shape
    ss = z * sigma
    # Nothing is in transit at the start, so opening stock has to cover the first two weeks.
    on_hand = (np.nan_to_num(f1[:, 0] + f2[:, 0]) + ss).clip(0)
    arrivals = np.zeros((n_s, n_w + 2))
    filled_sum = demand_sum = lost_sum = 0.0
    holding = inv_value = 0.0
    stockout_weeks = 0
    measured = 0
    for t in range(n_w):
        on_hand = on_hand + arrivals[:, t]
        d = demand[:, t]
        filled = np.minimum(on_hand, d)
        on_hand = on_hand - filled
        if t >= warmup:
            measured += 1
            filled_sum += filled.sum()
            demand_sum += d.sum()
            lost_sum += (d - filled).sum()
            value = (on_hand * unit_cost).sum()
            holding += value * ANNUAL_HOLDING_RATE / 52.0
            inv_value += value
            stockout_weeks += int(((d - filled) > 0).sum())
        target = np.nan_to_num(f1[:, t + 1] + f2[:, t + 1]) + ss
        position = on_hand + arrivals[:, t + 1]
        arrivals[:, t + 2] += np.maximum(0.0, target - position)
    return SimResult(
        fill_rate=filled_sum / demand_sum if demand_sum else float("nan"),
        holding_cost_annual=holding * 52.0 / max(measured, 1),
        avg_inventory_value=inv_value / max(measured, 1),
        stockout_week_share=stockout_weeks / max(measured * n_s, 1),
        units_lost=lost_sum,
    )


def z_for_fill_rate(
    demand: np.ndarray,
    f1: np.ndarray,
    f2: np.ndarray,
    sigma: np.ndarray,
    unit_cost: np.ndarray,
    target: float,
    lo: float = 0.0,
    hi: float = 8.0,
    iters: int = 40,
) -> float:
    """Smallest z that reaches the target fill rate, by bisection (fill rate rises with z)."""
    if simulate(demand, f1, f2, sigma, unit_cost, hi).fill_rate < target:
        return float("nan")
    for _ in range(iters):
        mid = (lo + hi) / 2
        if simulate(demand, f1, f2, sigma, unit_cost, mid).fill_rate >= target:
            hi = mid
        else:
            lo = mid
    return hi
