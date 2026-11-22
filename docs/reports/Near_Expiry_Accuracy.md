# Near-expiry accuracy

PB-43, DS-09 section 6, EXP43-1 to EXP43-3. Measured with
`scripts/metrics/near_expiry_accuracy.py` on branch
`test/PB-43-near-expiry-accuracy`, commit `42a1c5e` (the script and its
tests; this report is the next commit).

Re-run for audit #11b (2026-11-21) on `main` `998bfc3` with the fix that stops
writing a `near_expiry_config` row for the DEFAULT category: the earlier run
below measured the DEFAULT bands with a config row present, so the fallback to
`NEAR_EXPIRY_DEFAULT_DAYS` was never taken. Section "Audit #11b re-run" holds the
new output.

- Database: `RTS_DB_TEST` (the script writes only to `RTS_DB_DEMO` or a database
  whose name ends in `_TEST`; every other name, `RTS_DB` included, is refused).
- Business date: 2026-11-17, from `clock.today_local()` (UTC+7).
- Seed: none. The script creates its own store `TEST-PB43`, 32 products and
  batches of quantity 5, and the threshold rows of its own categories; it
  deletes exactly those rows again on the next run, so no seed data is touched.
- Dataset: for every threshold T in {3, 7, 14} and for the default window
  (`NEAR_EXPIRY_DEFAULT_DAYS` = 3, one category without a config row), one
  batch at T+2, T+1, T, T-1, 1, 0, -1 and -3 days left. Expected result: no
  alert above T, NEAR_EXPIRY from T down to 0, EXPIRED below 0.

Command, from the repository root:

```
docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo middleware python scripts/metrics/near_expiry_accuracy.py --db RTS_DB_TEST
```

Output of the run:

```
Near-expiry accuracy on RTS_DB_TEST, business date 2026-11-17
  TEST-PB43-DEFAULT (threshold 3): 8 correct, 0 missed, 0 false of 8
  TEST-PB43-T14 (threshold 14): 8 correct, 0 missed, 0 false of 8
  TEST-PB43-T3 (threshold 3): 8 correct, 0 missed, 0 false of 8
  TEST-PB43-T7 (threshold 7): 8 correct, 0 missed, 0 false of 8
TOTAL: 32 correct, 0 missed, 0 false of 32 batches (100.0% correct)
NEAR-EXPIRY ACCURACY PASS
```

| Category | Correct | Missed | False | Batches |
| --- | ---: | ---: | ---: | ---: |
| TEST-PB43-DEFAULT (threshold 3) | 8 | 0 | 0 | 8 |
| TEST-PB43-T3 (threshold 3) | 8 | 0 | 0 | 8 |
| TEST-PB43-T7 (threshold 7) | 8 | 0 | 0 | 8 |
| TEST-PB43-T14 (threshold 14) | 8 | 0 | 0 | 8 |
| Total | 32 | 0 | 0 | 32 |

Correctly flagged batches: 100.0%. On every band around every threshold, the
daily check flags each batch at or below its category threshold as
NEAR_EXPIRY, flags every expired batch as EXPIRED whatever the threshold is,
and leaves fresher batches alone. A wrong alert type counts as missed; none
occurred. No near-expiry defect to report.

The same command with `--db RTS_DB_DEMO` on the same date gave the same
totals: 32 correct, 0 missed, 0 false of 32 batches (100.0% correct), with the
seed stores of the demo database untouched.

The run leaves the store `TEST-PB43` with its 32 batches and alerts in the
database. On `RTS_DB_DEMO` the daily recommendation job would then create
recommendations for those batches, so reset the demo database after a
measurement there (`scripts/demo/reset_demo_db.ps1`). Adding `--cleanup`
deletes the store again and leaves the database as it was.

Rerun: the command above works on `RTS_DB_TEST` or `RTS_DB_DEMO` at any date;
the bands move with the business date of the run.

## Audit #11b re-run

Audit finding #11b: `load_dataset` merged the DEFAULT category into the same
dictionary it wrote `near_expiry_config` rows from, so the fallback branch of
`check_store` was never exercised and the run above measured a configured
window while claiming to measure the default one. `load_dataset` now writes
`THRESHOLDS` only; the DEFAULT category keeps its 8 batches and its bands, and
gets no config row, so `NEAR_EXPIRY_DEFAULT_DAYS` is what judges it.
`middleware/tests/test_audit11b_accuracy_default.py` pins that: no
`near_expiry_config` row for the fallback category, the dataset still covers it,
the DEFAULT bands still come out right, and a configured category keeps its own
threshold.

- Branch: `fix/audit-11b-accuracy-default`, based on `main` `998bfc3`.
- Database: `RTS_DB_TEST` (a `_TEST` database, as DS-09 requires).
- Business date: 2026-11-21, from `clock.today_local()` (UTC+7).
- `--cleanup` used, so the store and its rows were removed again.

```
docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo middleware \
    python scripts/metrics/near_expiry_accuracy.py --db RTS_DB_TEST --cleanup
```

```
Near-expiry accuracy on RTS_DB_TEST, business date 2026-11-21
  TEST-PB43-DEFAULT (threshold 3): 8 correct, 0 missed, 0 false of 8
  TEST-PB43-T14 (threshold 14): 8 correct, 0 missed, 0 false of 8
  TEST-PB43-T3 (threshold 3): 8 correct, 0 missed, 0 false of 8
  TEST-PB43-T7 (threshold 7): 8 correct, 0 missed, 0 false of 8
TOTAL: 32 correct, 0 missed, 0 false of 32 batches (100.0% correct)
Cleaned up store TEST-PB43
NEAR-EXPIRY ACCURACY PASS
```

| Category | Correct | Missed | False | Batches |
| --- | ---: | ---: | ---: | ---: |
| TEST-PB43-DEFAULT (threshold 3, no config row) | 8 | 0 | 0 | 8 |
| TEST-PB43-T3 (threshold 3) | 8 | 0 | 0 | 8 |
| TEST-PB43-T7 (threshold 7) | 8 | 0 | 0 | 8 |
| TEST-PB43-T14 (threshold 14) | 8 | 0 | 0 | 8 |
| Total | 32 | 0 | 0 | 32 |

Correctly flagged batches: 100.0%, now including the fallback branch. The
dataset and the count are unchanged from the run above, which is what a fix to
the *setup* of a measurement should show: the default window and T3 are both 3
days here, so a run that mislabelled one as the other could not be told apart by
totals alone -- which is exactly why the test asserts the absence of the config
row rather than only the score. The other markdown of this report (`RTS_DB_DEMO`
figures) is from the earlier commit and was not re-run for this audit.
