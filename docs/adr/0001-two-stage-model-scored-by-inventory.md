# ADR-0001: Two-stage order model, judged by the inventory it implies

## Status
Accepted

## Context
A distributor's customer x SKU weekly order series is mostly zeros: the median pair orders
in about four weeks out of ten, and some pairs once a quarter. Whether an order happens and
how big it is have different drivers. A quote request in the reps' app says something about
whether an order is coming next week and little about its size; customer size and season say
more about size.

Forecast accuracy measured as 1 - WAPE at customer x SKU level rewards forecasts near the
median, and the median of a mostly-zero week is zero. A model tuned to that number learns to
under-forecast, which shows up later as stock-outs. The forecast is consumed by replenishment
at SKU level, so that is where it has to be judged.

## Decision
- Join the three sources in SQL (DuckDB, kept close to BigQuery) into one weekly panel with
  explicit zero weeks. Every shipment fact is attributed to the week it became known
  (ship date for short shipments, delivery date for lateness), not to the order week.
- Forecast each pair with two stages: a classifier for P(order next week) and a gamma
  regressor for the quantity given an order, multiplied into a mean forecast. Fit the same
  structure with LightGBM and XGBoost.
- Keep a single-stage Tweedie LightGBM as a check on whether the split earns its complexity,
  and a "point" variant that forecasts zero unless P(order) >= 0.5 to show what WAPE rewards.
- Baseline is ETS(A,N,N) per pair with the smoothing weight chosen on training weeks.
- Score every forecaster by an order-up-to simulation at SKU level, with safety stock sized
  from each forecaster's own validation error, compared at a fixed z and at a matched fill
  rate. Holding cost at matched fill rate is the deciding number.

## Alternatives rejected
- **Croston / SBA for intermittent demand.** Fits the zeros but cannot use the app or
  logistics signals, which is the reason to join the sources at all.
- **One global time-series model (DeepAR-style).** Heavier to run and explain, and the
  question here is whether joined operational signals help; gradient boosting answers that
  with a clean ablation.
- **Choosing the model on pair-level 1 - WAPE.** Picks the model that under-forecasts.

## Consequences
- The headline comparison is holding cost at equal fill rate, not a single accuracy number.
- Pairs that place their first ever order inside the test window are invisible to every
  forecaster; their demand still hits the simulated stock, so all methods pay for it equally.
