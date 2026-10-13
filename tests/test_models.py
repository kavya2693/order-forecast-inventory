from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from order_forecast.models import ALL_FEATURES, FIELD_APP, HISTORY, TwoStage, horizon_frame


def _frame(n: int, seed: int) -> pd.DataFrame:
    """Rows where a quote request is what drives next week's order, as in the field app."""
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({c: rng.normal(size=n) for c in ALL_FEATURES})
    df["category"] = pd.Categorical(rng.choice(["a", "b"], n))
    df["segment"] = pd.Categorical(rng.choice(["x", "y"], n))
    df["quotes_l0"] = (rng.random(n) < 0.3).astype(float)
    ordered = rng.random(n) < np.where(df["quotes_l0"] > 0, 0.8, 0.15)
    df["y"] = np.where(ordered, rng.gamma(4.0, 5.0, n), 0.0)
    return df


def test_two_stage_learns_the_leading_signal_and_stays_non_negative() -> None:
    train, test = _frame(4000, 0), _frame(2000, 1)
    m = TwoStage("lightgbm").fit(train, train["y"].to_numpy())
    p = m.predict(test)
    assert (p >= 0).all()
    assert roc_auc_score(test["y"] > 0, m.predict_proba(test)) > 0.75
    # The mean forecast should be close in volume to the actual total.
    assert abs(p.sum() / test["y"].sum() - 1) < 0.15


def test_without_field_app_features_the_signal_is_lost() -> None:
    train, test = _frame(4000, 0), _frame(2000, 1)
    m = TwoStage("lightgbm", features=list(HISTORY)).fit(train, train["y"].to_numpy())
    assert not set(FIELD_APP) & set(m.features)
    assert roc_auc_score(test["y"] > 0, m.predict_proba(test)) < 0.6


def test_xgboost_variant_runs_on_the_same_frame() -> None:
    train = _frame(1500, 2)
    m = TwoStage("xgboost").fit(train, train["y"].to_numpy())
    assert m.predict(train).shape == (1500,)


def test_horizon_frame_maps_horizon_columns() -> None:
    df = pd.DataFrame({"qty_ly_h2": [1], "target_woy_h2": [5], "y_h2": [3.0], "y_h1": [9.0]})
    out = horizon_frame(df, 2)
    assert {"qty_ly", "target_woy", "y"} <= set(out.columns)
    assert out["y"].item() == 3.0
