# Near-expiry accuracy

PB-43, DS-09 section 6, EXP43-1 to EXP43-3. Measured with
`scripts/metrics/near_expiry_accuracy.py` on branch
`test/PB-43-near-expiry-accuracy`, commit `42a1c5e` (the script and its
tests; this report is the next commit).

- Database: `RTS_DB_TEST` (the script refuses `RTS_DB`; `RTS_DB_DEMO` is allowed too).
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
docker compose run --rm --volume "${PWD}:/repo" --workdir /repo middleware python scripts/metrics/near_expiry_accuracy.py --db RTS_DB_TEST
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

Rerun: the command above works on `RTS_DB_TEST` or `RTS_DB_DEMO` at any date;
the bands move with the business date of the run.
