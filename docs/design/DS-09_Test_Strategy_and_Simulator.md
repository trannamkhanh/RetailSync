# DS-09: Test Strategy and Simulator Specification

Status: approved, 1 Nov 2026.
Baseline: SRS v1.3 (section 4.4), DS-05, Sprint Backlog v1.4. Traces to PB-03, PB-24, PB-28, PB-37 to PB-40, PB-43, PB-44.

## 1. Test levels

| Level | Scope | Tool | When |
|---|---|---|---|
| Unit | Business rules: FEFO, hashes, guardrails, recommendation rules | pytest | Every pull request |
| API | Endpoints against the OpenAPI contract, including 401, 403, 404, 409, 422, 503 | pytest, FastAPI TestClient | Every pull request |
| Database | Migrations on a clean database; constraints | sqlcmd, pytest | When migrations change |
| Integration | POS to Middleware to HQ demo, using DS-05 scenarios | pytest, Docker Compose | From Sprint 3 |
| Performance | POS API and cross-store lookup | Locust | Sprint 4 |
| UAT | Main workflows with the Product Owner | Test-case list | Sprint 4 |

API and integration tests use a real SQL Server database, because idempotency and concurrency depend on its constraints.

## 2. Environment

- Docker Compose: SQL Server, Middleware, HQ demo. Seed: 3 stores, 2 POS terminals each.
- Test data is reset between test runs. Simulated data only; no customer data.
- Performance runs use TLS and mutual TLS, with 50 ms of added round-trip time.

## 3. Requirement coverage

| Requirement | Main tests | Backlog |
|---|---|---|
| FR01 | SALE, RETURN, CANCELLATION; stock never negative; return limit; sale with returns cannot be cancelled | PB-05 to PB-10 |
| FR02 | Aggregated totals match transactions; hourly run; no batch without transactions | PB-14, PB-15 |
| FR03 | Duplicate, CONFLICT, concurrent events; repeated batch | PB-09, PB-16, PB-18 |
| FR04 | FEFO, expired batches skipped, alerts, EXPIRED and RESOLVED, thresholds | PB-20, PB-21, PB-34 |
| FR05 | Forecast, too little history, failure rollback, surplus results | PB-22 to PB-24 |
| FR06 | Rules N0 to N5 and S1 to S3; PASSED, ADJUSTED, BLOCKED; DS-07 boundaries | PB-25 to PB-28 |
| FR07 | List, details, Accept, Reject, already decided, other store, expired | PB-32, PB-33 |
| FR08 | Distance order, same Middleware only, no store, none in stock, unknown barcode | PB-35 |
| FR09 | Sales continue while HQ is offline; ordered resend | PB-17, PB-37 |
| NFR01 | Latency under load | PB-39 |
| NFR02 | DS-05 scenarios 1 to 14 | PB-37 |
| NFR03 | Local operations during an HQ outage | PB-37 |
| NFR04 | TLS version, mutual TLS, JWT, roles, audit entries | PB-02, PB-04, PB-48 |
| NFR05 | Snapshot rejected during sales | PB-13 |

## 4. Metrics

| Metric | Method | Target |
|---|---|---|
| POS API latency | Locust, 30 minutes at normal load | p95 under 500 ms |
| Cross-store lookup time | Locust | 500 ms |
| Sync success rate | Share of batches reaching ACKED in the scenario runs | Reported |
| Data reduction | `1 − Σ payload_bytes / Σ raw_bytes` | At least 90% |
| Near-expiry accuracy | Flagged batches against known expiry dates | Reported |
| Forecast accuracy | WAPE and MAE on held-out data (DS-06) | Better than seasonal naive |
| Guardrail pass/reject rate | Share of PASSED, ADJUSTED, BLOCKED | Reported |
| Staff acceptance rate | Share of ACCEPT decisions | Reported |

Normal load is 2 events per second per POS terminal, 12 per second in total. Peak load is 3 times that rate; report it, but NFR01 is measured at normal load.

## 5. POS event simulator (PB-03)

A command-line tool that sends events through the real POS API.

```yaml
seed: 42
duration_minutes: 30
base_url: https://middleware.retailsync.local/api/v1
stores:
  - store_id: STORE-DN1
    pos: [POS-DN1-01, POS-DN1-02]
rate_per_pos_per_second: 2
mix: {SALE: 0.92, RETURN: 0.05, CANCELLATION: 0.03}
items_per_sale: {min: 1, max: 5}
fault_injection:
  duplicate_rate: 0.02
  conflict_rate: 0.001
  timeout_retry_rate: 0.01
```

Rules:

- The same seed and configuration produce the same event sequence.
- RETURN and CANCELLATION refer to earlier sales of the same store.
- Fault injection resends with the same `transaction_id`; the conflict case changes the items.
- The tool writes a summary: sent, OK, duplicate, rejected, and p50, p95 and p99 latency.

## 6. Historical data generator (PB-22)

Creates 90 days of sales for forecasting and direct-to-database loading, marked as simulated.

- `daily_demand = base(sku) × weekday_factor × store_factor × promotion_factor + noise`.
- Weekday factors: Monday to Thursday 1.0, Friday 1.1, Saturday 1.3, Sunday 1.2.
- Noise is Poisson-distributed, and the seed makes the data reproducible.
- About 10% of SKUs are slow-moving and 5% have fewer than 28 days of history, to test that branch.
- Products cover at least 3 categories with short, medium and long shelf life.
- Batches include known expiry dates, for the PB-43 measurement.

## 7. Simulation scenarios

| # | Scenario | Setup | Pass condition |
|---|---|---|---|
| 1 | Normal day | Simulator, HQ `ONLINE` | Batches ACKED; totals match transactions |
| 2 | HQ outage | HQ `OFFLINE` for 3 sync cycles | Sales continue; ordered resend; no loss |
| 3 | Slow HQ | HQ `SLOW` | Timeout, retry with backoff |
| 4 | Lost ACK | HQ `DROP_ACK` | ACKED; no double count |
| 5 | HQ errors | HQ `ERROR` | Batches stay PENDING, then ACKED |
| 6 | WAN outage | Block POS to Middleware for 5 minutes | Ordered resend; no loss |
| 7 | Duplicate storm | `duplicate_rate: 0.3` | Stock changes once per transaction |
| 8 | Stale snapshot | Snapshot during sales | 422; stock correct |

After each scenario, the reconciliation script checks:

- Stock in each store equals opening stock plus all movements.
- HQ totals equal the sum of all transactions in ACKED batches.
- Each transaction is in at most one batch.

## 8. Entry and exit criteria

Integration testing starts when the skeleton runs in Compose and the POS flow is merged.

Release needs all of these:

- All Must stories pass, and DS-05 scenarios 1 to 14 pass.
- Simulation scenarios 1 to 8 pass reconciliation.
- p95 latency and data reduction meet their targets.
- No open Critical or High defect.

## 9. Defects

| Severity | Meaning | Handling |
|---|---|---|
| Critical | Data loss, double count, security bypass | Fix before other work |
| High | Main flow blocked | Fix in the sprint |
| Medium | Workaround exists | Plan a fix |
| Low | Cosmetic | Fix if time remains |

Record defects as GitHub Issues with steps, expected result, actual result and severity.
