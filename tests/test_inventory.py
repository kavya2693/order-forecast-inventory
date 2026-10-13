from __future__ import annotations

import numpy as np
import pytest

from order_forecast.inventory import simulate, z_for_fill_rate


def _demand(seed: int = 0, n_s: int = 5, n_w: int = 30) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.poisson(20, (n_s, n_w)).astype(float)


def _shift(d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    nxt = np.concatenate([d, np.zeros((d.shape[0], 2))], axis=1)
    n = d.shape[1] + 1
    return nxt[:, 0:n], nxt[:, 1 : n + 1]


def test_perfect_forecast_fills_everything_and_holds_nothing() -> None:
    d = _demand()
    f1, f2 = _shift(d)
    r = simulate(d, f1, f2, np.zeros(5), np.ones(5), z=0.0)
    assert r.fill_rate == pytest.approx(1.0)
    assert r.holding_cost_annual == pytest.approx(0.0)
    assert r.units_lost == pytest.approx(0.0)


def test_flat_forecast_trades_holding_cost_for_fill_rate() -> None:
    d = _demand(1)
    f = np.full((5, d.shape[1] + 1), 20.0)
    sigma = np.full(5, np.sqrt(2 * 20.0))
    low = simulate(d, f, f, sigma, np.ones(5), z=0.0)
    high = simulate(d, f, f, sigma, np.ones(5), z=2.0)
    assert high.fill_rate > low.fill_rate
    assert high.holding_cost_annual > low.holding_cost_annual


def test_matched_z_reaches_the_target_fill_rate() -> None:
    d = _demand(2)
    f = np.full((5, d.shape[1] + 1), 20.0)
    sigma = np.full(5, 6.0)
    z = z_for_fill_rate(d, f, f, sigma, np.ones(5), target=0.98)
    assert simulate(d, f, f, sigma, np.ones(5), z).fill_rate >= 0.98
    assert simulate(d, f, f, sigma, np.ones(5), max(z - 0.05, 0)).fill_rate < 0.98
