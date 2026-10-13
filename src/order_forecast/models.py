"""Two-stage order models: will this customer order this SKU next week, and if so how much.

Stage one is a classifier on ``y > 0``. Stage two is a gamma regressor fitted only on weeks
with an order, so it predicts the conditional mean directly and needs no log back-transform.
The forecast is P(order) x E[qty | order], which is the unconditional mean.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb

HISTORY = [
    "history_weeks", "qty_l0", "qty_l1", "qty_l2", "qty_l3", "qty_ly",
    "qty_mean_4w", "qty_mean_13w", "qty_mean_26w", "qty_std_13w",
    "order_rate_13w", "order_rate_52w", "size_when_ordered_26w", "weeks_since_order",
    "cust_qty_4w", "cust_qty_26w", "sku_qty_4w", "sku_qty_26w",
    "target_woy", "category", "segment",
]  # fmt: skip
FIELD_APP = ["quotes_l0", "quotes_l1", "quotes_4w", "views_l0", "visits_l0", "visits_l1", "cust_events_l0"]
LOGISTICS = ["partial_l0", "qty_short_l0", "missing_pod_l0", "late_lines_4w", "transit_days_8w"]
ALL_FEATURES = HISTORY + FIELD_APP + LOGISTICS

N_JOBS = 4  # the machine is shared; four threads keeps a full run to a few minutes


def horizon_frame(df: pd.DataFrame, h: int) -> pd.DataFrame:
    """Map the horizon-specific columns (seasonal lag, target week) onto common names."""
    out = df.rename(columns={f"qty_ly_h{h}": "qty_ly", f"target_woy_h{h}": "target_woy", f"y_h{h}": "y"})
    return out


def _lgb_clf(seed: int) -> Any:
    return lgb.LGBMClassifier(
        n_estimators=300, learning_rate=0.05, num_leaves=63, min_child_samples=100,
        subsample=0.8, subsample_freq=1, colsample_bytree=0.8, n_jobs=N_JOBS, random_state=seed, verbose=-1,
    )  # fmt: skip


def _lgb_reg(seed: int, objective: str = "gamma") -> Any:
    extra = {"tweedie_variance_power": 1.3} if objective == "tweedie" else {}
    return lgb.LGBMRegressor(
        objective=objective, n_estimators=400, learning_rate=0.05, num_leaves=63, min_child_samples=100,
        subsample=0.8, subsample_freq=1, colsample_bytree=0.8, n_jobs=N_JOBS, random_state=seed, verbose=-1,
        **extra,
    )  # fmt: skip


def _xgb_clf(seed: int) -> Any:
    return xgb.XGBClassifier(
        n_estimators=300, learning_rate=0.05, max_depth=7, min_child_weight=20, subsample=0.8,
        colsample_bytree=0.8, tree_method="hist", enable_categorical=True, n_jobs=N_JOBS, random_state=seed,
    )  # fmt: skip


def _xgb_reg(seed: int) -> Any:
    return xgb.XGBRegressor(
        objective="reg:gamma", n_estimators=400, learning_rate=0.05, max_depth=7, min_child_weight=20,
        subsample=0.8, colsample_bytree=0.8, tree_method="hist", enable_categorical=True, n_jobs=N_JOBS,
        random_state=seed,
    )  # fmt: skip


@dataclass
class TwoStage:
    library: str = "lightgbm"
    features: list[str] = field(default_factory=lambda: list(ALL_FEATURES))
    seed: int = 0
    clf: Any = None
    reg: Any = None

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> TwoStage:
        y = np.asarray(y, dtype=float)
        ordered = y > 0
        Xf = X[self.features]
        self.clf = _lgb_clf(self.seed) if self.library == "lightgbm" else _xgb_clf(self.seed)
        self.reg = _lgb_reg(self.seed) if self.library == "lightgbm" else _xgb_reg(self.seed)
        self.clf.fit(Xf, ordered.astype(int))
        self.reg.fit(Xf[ordered], y[ordered])
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return np.asarray(self.clf.predict_proba(X[self.features])[:, 1])

    def predict_size(self, X: pd.DataFrame) -> np.ndarray:
        return np.clip(np.asarray(self.reg.predict(X[self.features])), 0, None)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.predict_proba(X) * self.predict_size(X)


@dataclass
class SingleStage:
    """One Tweedie regressor on all weeks, zeros included: the check on whether two stages pay."""

    features: list[str] = field(default_factory=lambda: list(ALL_FEATURES))
    seed: int = 0
    model: Any = None

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> SingleStage:
        self.model = _lgb_reg(self.seed, objective="tweedie")
        self.model.fit(X[self.features], np.asarray(y, dtype=float))
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.clip(np.asarray(self.model.predict(X[self.features])), 0, None)
