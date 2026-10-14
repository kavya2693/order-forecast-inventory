# order-forecast-inventory

[![ci](https://github.com/kavya2693/order-forecast-inventory/actions/workflows/ci.yml/badge.svg)](https://github.com/kavya2693/order-forecast-inventory/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.11-blue)
![license](https://img.shields.io/badge/license-MIT-green)

Weekly order forecasts for every customer x SKU line of a B2B distributor, built by joining
shipments, the field-sales app and sales orders in SQL, and judged by how much stock they let
the warehouse hold at the same fill rate.

## The problem

A wholesale distributor sells 150 SKUs to 400 retail customers. Each customer buys a few dozen
lines, some every week, some once a month, a few once a quarter. Every Friday the replenishment
planner has to decide how much of each SKU to bring into the warehouse for the week after next.
Order too little and a customer's order ships short; order too much and cash sits on the shelf
at a 25% annual carrying cost.

The planner's forecast today is a smoothed history of each customer's orders. It knows nothing
the other systems know: that a sales rep logged a quote request for that SKU on Tuesday, that
the customer's last delivery arrived short and they will reorder, that a key account was just
visited. Those facts live in three systems (the ERP, the warehouse and transport system, and the
reps' mobile app) that nobody joins until after the fact. The cost shows up as safety stock: the
less a forecast knows, the larger the buffer needed to hit the same fill rate.

## Why it is hard

Most customer x SKU weeks are zero: 60% of line-weeks have no order, the median line orders in
39% of its weeks, and three lines in four order in fewer than half of them
([`outputs/data_profile.json`](outputs/data_profile.json)). So
the usual accuracy number, 1 - WAPE at the line level, rewards a forecast that says "no order"
whenever it is unsure, which then runs the warehouse short. A model can look better on that
number and be worse for stock ([ADR-0001](docs/adr/0001-two-stage-model-scored-by-inventory.md)).

The joins are the other half. App events arrive through an API that retries on timeouts, so the
log carries duplicates, and two regional outages drop whole weeks of events. Order lines are
cancelled and re-keyed. A shipment fact (short ship, late delivery, missing proof of delivery)
has to be dated to the week it became known, not the week of the order, or the features leak.

## The approach

Three SQL stages in DuckDB ([`src/order_forecast/sql/`](src/order_forecast/sql/), written close
to BigQuery; the mapping is in [`docs/BIGQUERY.md`](docs/BIGQUERY.md)) clean and deduplicate the
sources, build a weekly customer x SKU panel with explicit zero weeks, and compute lag, rolling,
app and logistics features as of each week.

Each line is then forecast one and two weeks ahead with two stages: a classifier for "will this
customer order this SKU next week" and a gamma regressor for "how much, given an order", multiplied
into a mean forecast. The same structure is fitted with LightGBM and with XGBoost. Two checks sit
beside it: a single-stage Tweedie LightGBM (does the split earn its complexity?) and a "point"
variant that forecasts zero unless P(order) >= 0.5 (what chasing line-level WAPE looks like).
Baselines are ETS(A,N,N) per line with its smoothing weight fitted on training weeks, and a 4-week
moving average.

The key decision is the scoring. Every forecaster's line forecasts are summed to SKU level and
fed to the same weekly order-up-to policy (one week lead time, safety stock = z x that
forecaster's own two-week error on 13 validation weeks). The deciding number is annual holding
cost when each forecaster's z is tuned to reach the same 98% fill rate on the 26 test weeks.

## The result

Full run: 400 customers, 150 SKUs, 156 weeks, 8,955 active lines, 1,337,363 line-weeks. Test
window is the last 26 weeks (from 2025-06-30). Report: [`outputs/results.md`](outputs/results.md),
log: [`outputs/run_log.txt`](outputs/run_log.txt), all numbers in [`outputs/`](outputs/).

**Inventory at the same 98% fill rate (SKU level, test weeks)**

| Forecaster | 1 - WAPE, SKU, h=1 | Fill rate at z=1.65 | z for 98% fill | Holding cost / yr at 98% fill | vs ETS |
|---|---:|---:|---:|---:|---:|
| ETS(A,N,N) per line | 0.704 | 94.8% | 3.10 | 242,371 | - |
| 4-week moving average | 0.698 | 94.8% | 3.23 | 230,047 | -5.1% |
| LightGBM two-stage | 0.808 | 97.1% | 2.23 | 129,047 | -46.8% |
| XGBoost two-stage | 0.809 | 97.1% | 2.16 | 124,338 | -48.7% |
| LightGBM single-stage Tweedie | 0.808 | 97.1% | 2.20 | 123,907 | -48.9% |
| LightGBM "point" (zero unless P >= 0.5) | 0.761 | 97.4% | 1.86 | 136,464 | -43.7% |

The gradient-boosted forecasts roughly halve the carrying cost of hitting 98% fill, and at the
textbook z = 1.65 they also fill more (97.1% vs 94.8%). Costs are in the same currency units as
the generated unit costs.

**Line-level accuracy, one week ahead (test weeks)**

| Forecaster | 1 - WAPE | Bias | Frequent lines | Intermittent lines | Weeks better than ETS |
|---|---:|---:|---:|---:|---:|
| ETS | -0.096 | -5.7% | 0.171 | -0.263 | - |
| 4-week moving average | -0.188 | +0.8% | 0.105 | -0.372 | 0 / 26 |
| LightGBM two-stage | 0.121 | -2.1% | 0.304 | 0.006 | 26 / 26 |
| XGBoost two-stage | 0.120 | -3.2% | 0.304 | 0.004 | 26 / 26 |
| LightGBM Tweedie | 0.118 | -3.6% | 0.293 | 0.009 | 26 / 26 |
| LightGBM "point" | **0.214** | **-14.1%** | 0.303 | 0.159 | 26 / 26 |

What the numbers say, including the parts I did not want:

1. **Line-level accuracy is low for everyone.** 1 - WAPE of 0.12 means the absolute error is 88%
   of the volume. ETS is below zero, which means forecasting zero everywhere would have scored
   better on this metric. On intermittent lines (ordered in fewer than half of training weeks)
   no model beats the all-zero forecast in a meaningful way (0.006). At two weeks ahead every
   method is below zero at line level (two-stage -0.030, ETS -0.083). The forecast is only
   useful once it is summed to SKU level, where it reaches 0.81.
2. **The metric that is easiest to report picks the wrong model.** The "point" variant has the
   best line-level accuracy by a wide margin (0.214) and the worst inventory result among the
   boosted models: it under-forecasts by 14%, its validation error is larger, and it needs
   136,464 a year to reach 98% fill against 124,000-129,000 for the mean forecasts. This is why
   ADR-0001 scores on inventory.
3. **The two-stage split does not earn its complexity here.** The single-stage Tweedie LightGBM
   matches it on every number and is slightly cheaper on stock (123,907 vs 129,047). XGBoost and
   LightGBM are indistinguishable (AUC 0.830 for both order classifiers). The two-stage model is
   still the one I would explain to a planner, because P(order) is a number a rep can act on, but
   the accuracy case for it is not there.
4. **The field app carries almost all of the lift; logistics adds little.** Ablation on the
   LightGBM two-stage model, one week ahead:

   | Features | 1 - WAPE, line | Bias |
   |---|---:|---:|
   | Order history only | 0.028 | -2.9% |
   | History + field app | 0.113 | -2.0% |
   | History + logistics | 0.036 | -2.2% |
   | All three sources | 0.121 | -2.1% |

   The most important feature by gain is last week's quote requests (28% of gain), ahead of the
   52-week order rate (23%). The shipment features (short ships, late lines, missing proof of
   delivery) add 0.008. Short shipments are rare (5% of order lines) so they move few weeks.
5. **Order-occurrence ranking.** ROC-AUC for "will this line order next week": 0.830 for both
   classifiers against 0.582 for ranking by the ETS level.

## How it works

```
sales_orders.parquet ─┐                       01_staging.sql   drop cancelled lines, dedupe API retries,
shipments.parquet ────┼──► DuckDB views ──►                   date shipment facts to when they are known
field_app_events ─────┘                       02_panel.sql     customer x SKU x week, zero weeks explicit
                                              03_features.sql  lags, rolling means, app + logistics as of week t
                                                     │
                     ┌───────────────────────────────┼────────────────────────────┐
                     ▼                               ▼                            ▼
          ETS per line, 4-wk MA     P(order) x E[qty | order]  (LGBM, XGB)    Tweedie LGBM
                     └───────────────┬───────────────┴────────────────────────────┘
                                     ▼  sum to SKU, h=1 and h=2
              order-up-to S = F1 + F2 + z * sigma(validation)   ──►  fill rate, holding cost
              z searched by bisection to hit 98% fill            ──►  holding cost at matched fill
```

- `data.py` generates the five source tables with the causal links described under The data.
- `pipeline.py` runs the three SQL stages and returns the feature panel.
- `baseline.py` fits ETS per line on a grid of smoothing weights, vectorised across lines.
- `models.py` holds the two-stage and single-stage models and the feature groups for the ablation.
- `inventory.py` simulates the weekly order-up-to policy with lost sales and a two-week warm-up.
- `evaluate.py` runs the backtest: train on weeks before validation, size safety stock on
  validation, score on test. `cli.py` is the one command.

## Running it

```bash
uv sync
make check                          # ruff, format, mypy, pytest
uv run order-forecast --small       # 80 customers x 40 SKUs, about a minute
make run                            # full scale, about nine minutes on a laptop, writes outputs/
make data                           # regenerate the source tables only
make profile                        # how intermittent the lines are, writes outputs/data_profile.json
docker build -t order-forecast . && docker run --rm order-forecast
```

No API keys, model servers or downloads beyond the Python packages. Set
`ORDER_FORECAST_THREADS` to the number of free cores; it defaults to 1 because OpenMP threads
spin-wait badly on a shared machine.

## The data

The dataset is generated by the seeded script `scripts/generate_data.py` (`make data`) and sized
to the production problem: 400 customers, 150 SKUs, three years of weeks, 604,527 order lines,
592,904 shipment lines and 279,330 field-app events. The production data is proprietary.

What the generator builds in, so that each source has something to say: customers buy on a
weekly, fortnightly or four-weekly cycle with drift in size; a quote request in the app precedes
an order with a stated probability; a rep visit raises next week's order probability; a short
shipment makes the customer reorder the next week at a larger size; categories have their own
seasonality; Christmas and early August have stock-up and shutdown weeks; 1.2% of order weeks
are 4-8x outliers; 5% of customers churn and 15% of lines start mid-history. The mess is built
in too: 2% of order lines are cancelled and re-keyed, 3% of app events are retry duplicates,
three regional app outages drop 1-2 weeks of events, 3% of deliveries have no proof-of-delivery
scan, and 30% of customers never adopt the app.

## Tests

`make check` runs 15 tests. The two that matter most:

- `test_features_do_not_see_the_future` changes one week's orders and checks that no feature at
  any earlier origin moves, only the targets. Every accuracy and inventory number depends on the
  SQL not leaking.
- `test_matched_z_reaches_the_target_fill_rate` checks that the bisection on z lands on the
  target fill rate, because the headline comparison is holding cost at that matched rate.

Others cover the cleaning (cancelled lines and API retries are not counted), shipment facts
landing in the week they become known, the panel's zero weeks, WAPE and bias on hand-computed
values, ETS against a hand recursion, the inventory simulation's perfect-forecast and flat-forecast
cases, and that the two-stage model loses the quote signal when the app features are removed.

## Known limitations

- **Biggest gap: the field-app lift is a property of the generator.** A quote request precedes
  an order because the generator says so, at a rate I chose. The pipeline finds the signal and
  the ablation measures it, but how much a real rep's quote log predicts real orders has to be
  measured on real data before the 47% holding-cost number means anything. The same applies,
  more weakly, to the short-shipment reorder effect.
- Line-level accuracy is poor for every method and negative two weeks ahead. The result rests on
  aggregation to SKU level; a use case that needs line-level forecasts (customer-specific
  allocation, rep call lists beyond P(order)) is not served.
- One backtest origin split (train / 13 validation / 26 test weeks), not a rolling-origin
  evaluation, so there is no interval on the holding-cost gap. The three mean-forecast boosted models land
  within about 4% of each other, which is inside what a second split could move.
- Lost sales, one lead time for every SKU, no supplier minimums, case packs or warehouse
  capacity in the inventory policy. Safety stock uses a single sigma per SKU, not one per season.
- Lines that first order inside the test window are invisible to every forecaster; their demand
  still hits stock, so all methods pay for it equally and none of the fill rates reach 100%.
- Models are trained once; no retraining cadence, drift monitoring or hyperparameter search.
- No Croston/TSB baseline. ADR-0001 explains why it was left out (it cannot use the joined
  signals), but it would be a stronger intermittent-line baseline than ETS.

## Insights and learning

I picked this because order forecasting projects usually stop at a WAPE table, and the person
who uses the forecast, the replenishment planner, never sees WAPE; they see stock and stock-outs.
Putting both in one table is what made it interesting: the forecast with the best line-level
accuracy was the one I would least want to buy stock from.

The surprise was how little the two-stage structure bought. I expected splitting "whether" from
"how much" to beat a single Tweedie model on lumpy lines, and it tied. Gradient boosting with a
Tweedie loss already handles the zero mass well when the features that predict occurrence are
present. The split is still worth keeping for the planner and the reps, because P(order) is
something a rep can call about, but that is an interpretability argument, not an accuracy one.

What I got wrong at first: I expected the logistics feed to matter about as much as the app,
since a short shipment directly causes a reorder. It barely moves the result. My best guess is
that short ships touch only 5% of order lines, so they change few line-weeks; I have not tested
that. The first full run also crashed after the SQL stage: the ETS output's week column came
back as an object after a reshape and would not join onto the panel. A test now pins that dtype.

Next: a rolling-origin backtest so the holding-cost gap has an interval, a Croston/TSB baseline
for intermittent lines, per-SKU lead times and case packs in the policy, and measuring the
quote-to-order rate on real app logs before trusting the field-app lift.

## License

MIT
