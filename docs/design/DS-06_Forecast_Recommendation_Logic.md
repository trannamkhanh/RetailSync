# DS-06: Forecast, Near-Expiry and Recommendation Logic

Status: approved, 1 Nov 2026.
Baseline: SRS v1.3 (UC.04, UC.05, UC.06), Database Design v1.3, DS-07. Traces to FR04, FR05, FR06; PB-20 to PB-25.

Numeric parameters in this document are approved starting values. Keep them in one configuration module so the team can tune them after the first evaluation.

## 1. Daily job order

| Time (store local) | Job | Output |
|---|---|---|
| 00:30 | `checkNearExpiry` | `near_expiry_alert` |
| 01:00 | `ForecastService.run` | `forecast` |
| 02:00 | `RecommendationEngine.generate` | `recommendation`, `guardrail_result` |

Each job can run alone. If forecast fails, the recommendation job uses the latest forecast not older than 2 days.

## 2. FEFO and sellable stock

- Sales deduct non-expired batches, earliest `expiry_date` first. A batch is sellable through its expiry date.
- RETURN and CANCELLATION restore the batches the sale deducted, using `inventory_movement`.
- If the restored batch has expired, the stock is restored but is not sellable, and the alert job flags it.
- `sellable_stock` is the sum of non-expired `product_batch.quantity` for a store and SKU. Forecast comparisons use it, not `inventory.quantity`.

## 3. Baseline forecast

**Target:** units sold per store, SKU and day, with a horizon of 7 days (`horizon_days = 7`).

**Daily demand:** SALE quantity minus RETURN and CANCELLATION quantity, floored at 0. Days without sales count as 0.

**Minimum history:** 28 days for the store and SKU. With less, no forecast is created and the case is logged.

**Models:**

| Name | Definition | Use |
|---|---|---|
| Seasonal naive | Demand of the same weekday in the previous week | Benchmark and fallback |
| `hgb-v1` | scikit-learn `HistGradientBoostingRegressor`, one global model | Main baseline |

XGBoost is not needed at this stage; scikit-learn alone satisfies the SRS stack and keeps the dependency small.

**Features:** day of week, weekend flag, day of month, lags of 1, 7 and 14 days, rolling means of 7 and 28 days, store id, SKU id, category, unit price.

**Prediction:** forecast 7 days ahead one day at a time, feeding each prediction into the lag features. Floor each day at 0. `predicted_demand` is the sum, rounded to a whole unit.

**Choice of model:** use `hgb-v1` only if its WAPE on held-out data is lower than seasonal naive. Otherwise use seasonal naive. `model_version` stores the name used, for example `hgb-v1` or `seasonal-naive-v1`.

**Failure:** a failure rolls back the current store's forecasts, keeps the earlier ones, logs the error and continues with the next store.

## 4. Surplus and shortage

`surplus_shortage = sellable_stock − predicted_demand`

| Result | `balance_status` |
|---|---|
| Above 0 | SURPLUS |
| Below 0 | SHORTAGE |
| 0 | BALANCED |

## 5. Accuracy

Hold out the last 14 days. Train on earlier data and predict each held-out day.

- `MAE = Σ|actual − forecast| / n`
- `WAPE = Σ|actual − forecast| / Σ actual`

Report both per model and per category. The SRS sets no accuracy target; the required result is the comparison with seasonal naive.

## 6. Recommendation rules

Run for each store. Evaluate rules in order; the first match creates the recommendation for that batch or SKU. Skip a batch or SKU that already has a PENDING recommendation.

`daily_demand = predicted_demand / horizon_days`

### Near-expiry batches

For each OPEN alert:

`at_risk_qty = remaining_qty − daily_demand × (days_to_expiry + 1)`, rounded up and floored at 0. Without a forecast, `at_risk_qty = remaining_qty`.

| Rule | Condition | Action | Level |
|---|---|---|---|
| N0 | Alert type EXPIRED | None | Expired stock is not sold; the alert stays visible |
| N1 | `at_risk_qty = 0` | None | Expected sales will clear the batch |
| N2 | `days_to_expiry ≤ 1` and `at_risk_qty ≥ 80%` of `remaining_qty` | CLEARANCE | `proposed_qty = at_risk_qty` |
| N3 | `days_to_expiry ≤ 1` | DISCOUNT | 50% |
| N4 | `days_to_expiry` is 2 or 3 | DISCOUNT | 30% |
| N5 | `days_to_expiry ≥ 4` | DISCOUNT | 15% |

### Surplus without a near-expiry alert

| Rule | Condition | Action | Level |
|---|---|---|---|
| S1 | SURPLUS, and another store of the Middleware has SHORTAGE for the SKU | REDISTRIBUTION | `proposed_qty = min(surplus, shortage)` of the store with the largest shortage |
| S2 | SURPLUS of at least 100% of `predicted_demand` | DISCOUNT | 10% |
| S3 | Otherwise | None | |

REDISTRIBUTION is only advice. It creates no transfer order.

### Reason text

| Source | Template |
|---|---|
| Near expiry | `Batch {batch_id} expires in {days} day(s); {at_risk} of {remaining} units may not sell in time.` |
| Surplus | `Forecast demand is {demand} units for 7 days; stock is {stock}.` |
| Redistribution | `{other_store} is short of {shortage} units; this store has {surplus} extra.` |

### Guardrails and status

New recommendations have status GENERATED. DS-07 then sets BLOCKED or PENDING. The source is stored in `alert_id` or `forecast_id`.

### Validity at decision time

A recommendation is no longer valid when its batch has no sellable quantity left or has expired.

- A decision on it is refused with `RECOMMENDATION_EXPIRED`, and its status changes to EXPIRED.
- The daily recommendation run changes such PENDING rows to EXPIRED.
- The list and detail endpoints do not change data, so they hide invalid rows until one of the two steps above runs.
- EXPIRED recommendations do not count in the staff acceptance rate.
