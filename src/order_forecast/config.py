"""Shared constants: calendar, split points and inventory policy."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Scale:
    n_customers: int = 400
    n_skus: int = 150
    n_weeks: int = 156
    start: date = date(2023, 1, 2)  # a Monday, so ISO weeks line up with date_trunc('week')
    seed: int = 7


FULL = Scale()
# Small enough for CI and the Docker smoke run; same code path.
SMALL = Scale(n_customers=80, n_skus=40, n_weeks=130)

# The last TEST_WEEKS weeks are held out; the VAL_WEEKS before them estimate forecast error
# for safety stock. Models never see a target inside either window during fitting.
TEST_WEEKS = 26
VAL_WEEKS = 13
MIN_HISTORY_WEEKS = 8

HORIZONS = (1, 2)

# Inventory policy: weekly review, an order placed at the end of week t arrives at the start
# of week t+2, so each decision has to cover two weeks of demand.
LEAD_TIME_WEEKS = 1
REVIEW_WEEKS = 1
ANNUAL_HOLDING_RATE = 0.25
SERVICE_Z = 1.65  # ~95% cycle service under normal errors
TARGET_FILL_RATE = 0.98
WARMUP_WEEKS = 2
