# DS-07: Guardrail Rules

Status: draft, 1 Nov 2026. Default values need Product Owner approval.
Baseline: SRS v1.3 (UC.06, BR06), Database Design v1.3 (`guardrail_rule`, `guardrail_result`). Traces to FR06; PB-26, 27, 28.

## Rules

| Order | Rule | Applies to | Meaning | Violation | Default (draft) |
|---|---|---|---|---|---|
| 1 | `MIN_SHELF_LIFE` | Recommendations with a batch | Days left must be at least the threshold | BLOCKED | 1 day |
| 2 | `MAX_DISCOUNT` | DISCOUNT | `discount_pct` must not exceed the threshold (0 to 100) | ADJUSTED down to the threshold | 50% |
| 3 | `MIN_PRICE` | DISCOUNT | `unit_price × (1 − discount_pct / 100)` must not fall below the threshold | ADJUSTED to the largest discount that keeps the minimum price; BLOCKED if the list price is already below it | 1,000 VND |

Rule 1 runs first, so a blocked recommendation is not adjusted. Rule 3 uses the value left by rule 2. One `guardrail_result` is stored per rule checked.

## Choosing between rules

- A rule with a `category` applies to that category; a rule with an empty `category` applies to all.
- If several active rules of one type match a product, the stricter one applies: the lowest `MAX_DISCOUNT`, the highest `MIN_PRICE`, the highest `MIN_SHELF_LIFE`.
- A category rule can only tighten the all-category rule.

## Results

- All rules passed or adjusted: recommendation status PENDING, visible to staff.
- Any rule BLOCKED: status BLOCKED, never shown.
- Rules cannot be loaded: nothing is released; status stays GENERATED until the next run.

## Boundary tests (PB-28)

| # | Rule threshold | Input | Expected |
|---|---|---|---|
| 1 | MIN_SHELF_LIFE 1 | 1 day left | PASSED |
| 2 | MIN_SHELF_LIFE 1 | 0 days left | BLOCKED |
| 3 | MAX_DISCOUNT 50 | 49.99% | PASSED |
| 4 | MAX_DISCOUNT 50 | 50.00% | PASSED |
| 5 | MAX_DISCOUNT 50 | 50.01% | ADJUSTED to 50% |
| 6 | MIN_PRICE 1,000; price 2,000 | 50% (result 1,000) | PASSED |
| 7 | MIN_PRICE 1,000; price 2,000 | 51% | ADJUSTED to 50% |
| 8 | MIN_PRICE 1,000; price 900 | Any discount | BLOCKED |
| 9 | Category MAX_DISCOUNT 30, all-category 50 | 40% in that category | ADJUSTED to 30% |
