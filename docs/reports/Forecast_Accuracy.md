# Forecast accuracy

Model seed `42`. Source is simulated `HIST-` transactions in `RTS_DB_DEMO`.
Data range 2026-08-15 through 2026-11-12.
Results depend on the business date used to generate the demo history, which determines the training and holdout dates.
Training ends before 2026-10-30. The 14-day holdout starts on 2026-10-30.
Both models predict the holdout recursively using only training demand and earlier predictions.
WAPE is unavailable where total actual demand is zero.

| Category | Model | Observations | MAE (units) | WAPE |
| --- | --- | ---: | ---: | ---: |
| Bakery | hgb-v1 | 126 | 3.05 | 28.89% |
| Bakery | seasonal-naive-v1 | 126 | 4.09 | 38.75% |
| Dairy | hgb-v1 | 112 | 1.81 | 34.52% |
| Dairy | seasonal-naive-v1 | 112 | 2.45 | 46.60% |
| Dry goods | hgb-v1 | 126 | 2.73 | 28.86% |
| Dry goods | seasonal-naive-v1 | 126 | 3.63 | 38.31% |
