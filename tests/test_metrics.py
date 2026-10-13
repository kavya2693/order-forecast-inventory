from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from order_forecast.baseline import ets_forecasts
from order_forecast.metrics import accuracy, bias, wape


def test_wape_and_bias_on_known_values() -> None:
    a = np.array([10.0, 0.0, 30.0])
    f = np.array([12.0, 5.0, 20.0])
    assert wape(a, f) == pytest.approx(17 / 40)
    assert accuracy(a, f) == pytest.approx(1 - 17 / 40)
    assert bias(a, f) == pytest.approx(-3 / 40)


def test_forecasting_zero_everywhere_scores_zero_accuracy() -> None:
    a = np.array([3.0, 0.0, 7.0])
    assert accuracy(a, np.zeros(3)) == pytest.approx(0.0)
    assert bias(a, np.zeros(3)) == pytest.approx(-1.0)


def test_ets_level_matches_hand_recursion() -> None:
    # A constant series is fitted perfectly by any alpha, so the level must stay at the constant.
    weeks = pd.date_range("2024-01-01", periods=20, freq="7D")
    df = pd.DataFrame({"customer_id": "C1", "sku_id": "S1", "week_start": weeks, "qty_l0": 5.0})
    out = ets_forecasts(df, weeks[15])
    assert np.allclose(out["ets"], 5.0)

    # A step change: the level after the step follows l_t = a*y_t + (1-a)*l_{t-1}.
    y = np.array([4.0] * 10 + [8.0] * 10)
    df["qty_l0"] = y
    out = ets_forecasts(df, weeks[15])
    a = out["ets_alpha"].iloc[0]
    level = 4.0
    for v in y:
        level = a * v + (1 - a) * level
    assert out["ets"].iloc[-1] == pytest.approx(level)
