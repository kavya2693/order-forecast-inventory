# Run report

Scale: {'customers': 400, 'skus': 150, 'weeks': 156}. Test window starts 2025-06-30 (26 weeks); validation for safety stock starts 2025-03-31.

## Source counts

| raw_order_lines | clean_order_lines | raw_app_events | dedup_app_events | shipments | pairs | panel_rows |
|---|---|---|---|---|---|---|
| 604527 | 592904 | 279330 | 271194 | 592904 | 8955 | 1337363 |

## Forecast accuracy (test weeks)

| horizon | method | accuracy_pair | bias_pair | accuracy_sku | weeks_better_than_ets | test_weeks | accuracy_frequent | bias_frequent | accuracy_intermittent | bias_intermittent |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | lgbm_two_stage | 0.121 | -0.021 | 0.808 | 26 | 26 | 0.304 | -0.044 | 0.006 | -0.007 |
| 1 | xgb_two_stage | 0.120 | -0.032 | 0.809 | 26 | 26 | 0.304 | -0.060 | 0.004 | -0.014 |
| 1 | lgbm_single_tweedie | 0.118 | -0.036 | 0.808 | 26 | 26 | 0.293 | -0.056 | 0.009 | -0.024 |
| 1 | lgbm_point | 0.214 | -0.141 | 0.761 | 26 | 26 | 0.303 | 0.042 | 0.159 | -0.255 |
| 1 | ets | -0.096 | -0.057 | 0.704 | 0 | 26 | 0.171 | -0.054 | -0.263 | -0.059 |
| 1 | moving_avg_4w | -0.188 | 0.008 | 0.698 | 0 | 26 | 0.105 | 0.006 | -0.372 | 0.010 |
| 2 | lgbm_two_stage | -0.030 | -0.035 | 0.795 | 26 | 26 | 0.226 | -0.054 | -0.190 | -0.024 |
| 2 | xgb_two_stage | -0.031 | -0.035 | 0.794 | 26 | 26 | 0.226 | -0.056 | -0.192 | -0.022 |
| 2 | lgbm_single_tweedie | -0.026 | -0.044 | 0.797 | 26 | 26 | 0.227 | -0.057 | -0.184 | -0.036 |
| 2 | lgbm_point | 0.047 | -0.252 | 0.674 | 26 | 26 | 0.164 | 0.294 | -0.027 | -0.595 |
| 2 | ets | -0.083 | -0.062 | 0.703 | 0 | 26 | 0.178 | -0.059 | -0.247 | -0.064 |
| 2 | moving_avg_4w | -0.129 | -0.001 | 0.705 | 1 | 26 | 0.141 | -0.004 | -0.299 | 0.000 |

## Inventory policy (test weeks, SKU level)

| method | fixed_z | fill_rate_fixed_z | holding_cost_fixed_z | safety_stock_value | z_for_98pct_fill | holding_cost_matched_fill | avg_inventory_value_matched | fill_rate_matched |
|---|---|---|---|---|---|---|---|---|
| lgbm_two_stage | 1.6500 | 0.9706 | 98,740.7025 | 390,258.7362 | 2.2303 | 129,047.0011 | 516,188.0044 | 0.9800 |
| xgb_two_stage | 1.6500 | 0.9714 | 97,645.5088 | 395,425.3131 | 2.1574 | 124,338.4754 | 497,353.9015 | 0.9800 |
| lgbm_single_tweedie | 1.6500 | 0.9707 | 95,013.9855 | 395,255.3567 | 2.1997 | 123,907.4399 | 495,629.7595 | 0.9800 |
| lgbm_point | 1.6500 | 0.9736 | 115,886.0191 | 731,788.2820 | 1.8599 | 136,464.1012 | 545,856.4047 | 0.9800 |
| ets | 1.6500 | 0.9481 | 131,066.0178 | 566,134.0777 | 3.0994 | 242,370.9256 | 969,483.7023 | 0.9800 |
| moving_avg_4w | 1.6500 | 0.9482 | 131,602.0829 | 465,294.2777 | 3.2344 | 230,047.4676 | 920,189.8704 | 0.9800 |
| perfect | 1.6500 | 1.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 1.0000 |

## Order-occurrence AUC (h=1)

| scorer | auc |
|---|---|
| ETS level (rank only) | 0.582 |
| lgbm_two_stage P(order) | 0.830 |
| xgb_two_stage P(order) | 0.830 |

## Source ablation (LightGBM two-stage, h=1)

| features | accuracy_pair | bias_pair |
|---|---|---|
| history only | 0.028 | -0.029 |
| history + field app | 0.113 | -0.020 |
| history + logistics | 0.036 | -0.022 |
| all three sources | 0.121 | -0.021 |

Runtime: 522.6 s
