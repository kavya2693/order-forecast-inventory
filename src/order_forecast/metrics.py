"""Forecast accuracy metrics on volume, so big customers count for more than small ones."""

from __future__ import annotations

import numpy as np


def wape(actual: np.ndarray, forecast: np.ndarray) -> float:
    actual = np.asarray(actual, dtype=float)
    forecast = np.asarray(forecast, dtype=float)
    denom = np.abs(actual).sum()
    if denom == 0:
        return float("nan")
    return float(np.abs(actual - forecast).sum() / denom)


def accuracy(actual: np.ndarray, forecast: np.ndarray) -> float:
    """1 - WAPE. Can go negative when the forecast is worse than predicting zero everywhere."""
    return 1.0 - wape(actual, forecast)


def bias(actual: np.ndarray, forecast: np.ndarray) -> float:
    """Signed volume bias: positive means over-forecasting."""
    actual = np.asarray(actual, dtype=float)
    forecast = np.asarray(forecast, dtype=float)
    denom = actual.sum()
    if denom == 0:
        return float("nan")
    return float((forecast - actual).sum() / denom)
