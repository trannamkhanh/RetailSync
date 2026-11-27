# PB-38-1 UAT list — Capstone 1

**Owner:** Quang · **Built:** 27/11/2026 · **Base:** main `a5f509b`
**Used at:** UAT 1 (27/11, with the mentor) and the final UAT (30/11)
**Source of the steps:** `docs/demo/Sprint_3_Demo.md` (acts 2–6, plus Màn 7 for the dashboard lines in act 7) with the act-7 audit additions from `Demo_Plan.docx` §5
**Where it goes:** the GitHub issue **"UAT Capstone 1"**, pasted as this checklist. **That issue is not open yet** — see §11.3.

---

## 1. How to read this list

One line per step: the action, the expected result, and the workbook test-case id when one exists.

The test-case ids come from `GROUP_08_Test case.xlsx` v1.1 (the 27/11 export, 269 cases). `—` means the step has no workbook case of its own; those steps are visually checked and are marked so in the issue.

Tick a line only when the expected result was seen on the machine named in the *where* column.

| Column | Meaning |
|---|---|
| `Act.step` | Act and step number, as in the demo plan |
| `Case` | Workbook test-case id, or `—` |
| `Where` | `S` console, `A` POS/Staff App, `B` POS |

---

## 2. Act 2 — Live selling (3 min)

| Act.step | Action | Expected result | Case | Where |
|---|---|---|---|---|
| 2.1 | A sells 2 × Fresh milk 1L (`SKU-0001`) | POS shows `OK`, `HTTP 200`, `current_stock` 38; console shows Hải Châu stock 40 → 38, earliest-expiry batch reduced first, one audit line | POS45-2, POS05-1, EXP20-1 | A, S |
| 2.2 | B sells a multi-item basket | The Thanh Khê transaction appears in the same console grid; Thanh Khê stock decreases per line | POS45-2, POS05-2 | B, S |
| 2.3 | A and B sell at nearly the same instant | Both return `OK`; each store's stock is correct and independent | INV10-4 | A, B, S |

---

## 3. Act 3 — Reliability and security (3 min)

| Act.step | Action | Expected result | Case | Where |
|---|---|---|---|---|
| 3.1 | B presses **Gửi lại** on the sale just made | `200` `DUPLICATE` / `DUPLICATE_IGNORED`; stock does not change | POS45-3, POS09-1, POS09-2 | B |
| 3.2 | Resend the same `transaction_id` with different content | `409` `CONFLICT`; nothing changes | POS09-4 | B |
| 3.3 | Send with another terminal's certificate | `403` `FORBIDDEN`; `EVENT_REJECTED` audit line | PS48-5 | B, S |
| 3.4 | A returns 1 item of the sale just made | `OK`; the exact batch that was reduced goes back up by 1 | POS06-1, EXP20-5 | A, S |
| 3.5 | A cancels another sale that has no returns | `OK`; batches return to their previous quantities | POS07-1, EXP20-6 | A, S |
| 3.6 | `POST /pos/events` a `CANCELLATION` for a sale that already has a `RETURN` | `409` `SALE_HAS_RETURNS`; the sale, its stock and its batches are unchanged (checked on the API, not on stage) | POS07-5 | API |

---

## 4. Act 4 — WAN outage (3 min)

| Act.step | Action | Expected result | Case | Where |
|---|---|---|---|---|
| 4.1 | S pulls B's network cable | B keeps selling; console shows no Thanh Khê traffic | POS45-6 | S, B |
| 4.2 | B sells 3 orders offline | B still sells; each shows as queued/pending send | POS45-6, SYNC17-1 | B |
| 4.3 | A keeps selling meanwhile | Hải Châu is unaffected | SYNC17-1 | A, S |
| 4.4 | S plugs the cable back in | B drains the 3 orders automatically, in order, same `transaction_id`s | POS45-6, SYNC17-4 | B, S |
| 4.5 | Look at the console | All 3 transactions are present, none lost or duplicated; Thanh Khê stock is correct | POS45-6, SYNC17-5 | S |

---

## 5. Act 5 — HQ sync (3 min)

| Act.step | Action | Expected result | Case | Where |
|---|---|---|---|---|
| 5.1 | Press **Chạy đồng bộ** | Each store gets one batch `PENDING` → `SENT` → `ACKED`; the HQ page totals match the transactions | SYNC15-5, SYNC14-1, SYNC14-2 | S |
| 5.2 | Switch HQ to `OFFLINE`, then A and B sell more | Stores keep selling; new batches stay `PENDING` with attempts and last error | SYNC17-1, SYNC17-3 | S, A, B |
| 5.3 | Switch HQ back to `ONLINE` | Queued batches are sent oldest first and become `ACKED`; HQ totals are right, nothing counted twice | SYNC17-4, SYNC16-2 | S |
| 5.4 | Send an inventory snapshot from HQ | `422` `SNAPSHOT_REJECTED`; store stock unchanged; audit line written | INV13-1, INV13-2, INV13-3 | S |

---

## 6. Act 6 — Near-expiry, forecast, recommendations (4 min)

| Act.step | Action | Expected result | Case | Where |
|---|---|---|---|---|
| 6.1 | Run the near-expiry job, then the recommendation job (forecast already seeded) | Open near-expiry alerts for the Dairy/Bakery batches; discount / clearance / redistribution proposals with reasons | EXP21-4, REC25-1, REC25-7 | S |
| 6.2 | Lower the guardrail maximum discount, rerun recommendations | The over-limit proposal is `ADJUSTED` to the limit, or `BLOCKED` and hidden from staff | REC27-2, REC27-3, REC28-2 | S |
| 6.3 | Open Staff App → **Cảnh báo cận hạn** | Alerts ordered most urgent first: `EXPIRED` first, then fewest days left | STF34-1, STF46-4 | A |
| 6.4 | Look up a barcode sold out at Hải Châu | Own store's batches and expiry dates; nearby stores with stock, **nearest first: Sơn Trà (~1.7 km) above Thanh Khê (~4.4 km)**, each row with its distance | STF31-1, STF35-1, STF46-1 | A |
| 6.5 | Open one proposal, read reason and guardrail result, **Chấp nhận**; reject another | Decision saved with user and time, audit written; pressing again answers "already decided" | STF33-1, STF33-2, STF33-3, STF47-3 | A, S |
| 6.6 | Staff App → **Giảm giá**, switch *Cửa hàng của tôi* / *Tất cả cửa hàng* | Same rows as the API, read-only, with the sold-at-discount marker | DSH50-11, DSH50-4 | A |

---

## 7. Act 7 — Dashboard, audit and measured numbers (3 min)

| Act.step | Action | Expected result | Case | Where |
|---|---|---|---|---|
| 7.1 | Open **Doanh thu** (token `admin`), scope **Toàn hệ thống**, bucket **Ngày** | Three charts: revenue by day, category share, three-store comparison; the KPI "Doanh thu thuần" and the transaction count; the time-quality badge is green or orange as `Sprint_3_Demo.md` §4 Màn 7 describes | — (PB-49 has no workbook case) | S |
| 7.2 | Switch the scope to one store, then the bucket to **Tuần**, then press **Làm mới** | The line and pie narrow to that store while the bar chart still compares all three; the week bucket has fewer points for the same total; the status line reads "Làm mới lúc HH:mm:ss. Không có lỗi." | — (PB-49 has no workbook case) | S |
| 7.3 | Open the audit log with the Auditor token | Every change just made is listed: sales, rejection, duplicate, sync, guardrail, decisions | POS05-2, REC27-4 | S |
| 7.4 | Show the measured-numbers table | Every figure comes from `docs/reports/` and matches the numbers in §9 below | PB-39/40/24/43/44 cases | S |

---

## 8. Test-case re-check lines (added 28/11)

After the 18:00 28/11 re-check, add one line per `[TestCase]` issue to this same issue, in the form:

```
- [ ] [TestCase] <case id> <short title> — <what failed>
```

Then paste the totals from §10 for the report.

---

## 9. Numbers act 7 must show

Taken from the committed reports on `a5f509b`; the presenter must read them from `docs/reports/`, not from memory.

| Metric | Target | Measured | Source |
|---|---|---|---|
| p95 POS API latency (mTLS, 50 ms RTT, sustained 30 min) | < 500 ms | **226.60 ms** (p50 186.94, p99 248.04; 21,600/21,600 accepted, 0% error) | `docs/reports/Performance.md` |
| p95 POS API latency (peak, 36/s) | < 500 ms | **193.51 ms** (p50 159.51, p99 217.63; 1,080/1,080, 0% error) | `docs/reports/Performance.md` |
| Cross-store lookup latency | ≤ 500 ms | **p95 136.85 ms**, max 206.56 ms, 1,805/1,805 HTTP 200, 0 errors | `docs/reports/Performance.md` |
| Data reduction to HQ | ≥ 90% | 98.91% | `docs/reports/Sync_Metrics.md` |
| Batch ACK rate | report | 100% (93/93, 129/129) | `docs/reports/Sync_Metrics.md` |
| Forecast WAPE vs seasonal naive | better | hgb-v1 better in every category | `docs/reports/Forecast_Accuracy.md` |
| Near-expiry detection accuracy | report | **100.0% — 32/32 batches, 0 missed, 0 false** | `docs/reports/Near_Expiry_Accuracy.md` |
| Guardrail PASSED/ADJUSTED/BLOCKED | report | 31.25% / 31.25% / 37.50% (5 / 5 / 6 of 16) | `docs/reports/Guardrail_Metrics.md` |
| Staff acceptance rate | report | **60.00% — 6/10** (6 ACCEPT, 4 REJECT); DISCOUNT 55.56% (5/9), CLEARANCE 100% (1/1), REDISTRIBUTION n/a | `docs/reports/Guardrail_Metrics.md` |
| E2E POS → HQ reconciliation | PASS | PASS | `docs/reports/E2E_Integration.md` |

---

## 10. Cross-test totals (for the UAT issue)

The script's defaults point at `docs/document/`, which **does not exist** on `main` at `a5f509b` — no `.xlsx` is committed to the repository at all. Both workbooks are passed explicitly:

```powershell
python scripts/metrics/cross_test_totals.py `
  --cases  "<the Google Sheet downloaded as .xlsx>" `
  --backlog "C1SE_24_RetailSync_Sprint_Backlog_v1.4.xlsx"
```

Two practical notes from the 27/11 run:

- Any Python with `openpyxl` works (`pip install openpyxl`); the repo has no venv requirement for this script.
- The script fails with `InvalidFileException` if the backlog argument is the `.docx` project plan instead of the `.xlsx` backlog, and with `FileNotFoundError` on a non-ASCII path. Copy both workbooks to an ASCII path first.

Result of that run (v1.1 case-workbook export, 27/11):

| Bucket | Total | PASS | FAIL | Not Implemented | SKIPPED |
|---|---:|---:|---:|---:|---:|
| Sprint 2 | 87 | 87 | 0 | 0 | 0 |
| Sprint 3 | 87 | 87 | 0 | 0 | 0 |
| Sprint 4 | 71 | 64 | 0 | 7 | 0 |
| Not mapped to a sprint (PB-49, PB-50) | 24 | 12 | 0 | 12 | 0 |
| **All four statistical rows** | **269** | **250** | **0** | **19** | **0** |

- **0 FAIL** anywhere, so no `[TestCase]` issue is opened from the workbook.
- The 7 not-implemented in Sprint 4 are `TST38-1..4` (this UAT, run today) and `TST44-1..3` (PB-44, see below).
- The 12 not-implemented of PB-50 are the only other gap.
- `PB-49` and `PB-50` map to no sprint because the backlog workbook has no Sprint 5 sheet; the script prints them as `unknown`.
- The script's closing "No failed cases." is about one count row per sheet: it reads `Re-test Status` when the sheet has that row and only falls back to `Status` when it does not (`scripts/metrics/cross_test_totals.py`, `failed_sheets`). A sheet with an empty `Re-test Status` is therefore judged by that empty row, so a FAIL recorded only under `Status` can be missed.

**Note for the report:** the "Re-test Status" row is 0/269 in this export. That is not a defect — the cross-testers fill columns K and L, and `Re-test Status` stays empty until they do. The totals above are the `Status` row.

---

## 11. Known gaps to state in the issue

These are real and must not be silently ticked off.

1. **PB-44 (TST44-1..3) is still "Not Implemented" in the workbook.** The measurements exist (`docs/reports/Guardrail_Metrics.md`, merged 27/11 as PR #92) and Sang owns updating the sheet. Act 7 may show the numbers, but the workbook row must be updated by Sang before freeze.
2. **PB-49 and PB-50 map to no sprint** in `C1SE_24_RetailSync_Sprint_Backlog_v1.4.xlsx` (no Sprint 5 sheet). The report must say so rather than quote a Sprint 5 total.
3. **`docs/Demo_Plan.md` does not exist** in the repo at any commit. The acts above come from `docs/demo/Sprint_3_Demo.md` (acts 2–6) plus `Demo_Plan.docx` §5 (act 7); the brief's path should be corrected or the file added.

### 11.1 The 27/11 "Add lines" list cannot be fully ticked today

The 27/11 brief says these features are new (PB-51/PB-52/PB-53) and that Khanh's and Sang's briefs for them are in `docs/mentor-review-27-11/`. **That folder is not in the repository**, and the features are not on `main`. What was checked, on `origin/main` at `a5f509b`:

| Check | Command | Result |
|---|---|---|
| Any commit mentioning the ids | `git log --all --oneline --grep='PB-5[123]'` | no matches |
| Any file mentioning the ids | `git grep -l -i 'PB-51\|PB-52\|PB-53'` on `origin/main`, `origin/Khanh`, `origin/Sang`, `origin/Kiet`, `origin/Quang` | no matches |
| The brief folder | `git ls-tree -r --name-only origin/main docs` | no `docs/mentor-review-27-11/` |

Scope of the check: git history and the remote working trees. An unpushed local branch would not appear in `git log --all`; that is the one way this conclusion could be wrong, and one `git branch -a` on Khanh's and Sang's machines settles it.

Point by point, what can and cannot be ticked:

| 27/11 line | Can it be ticked on `main`? | Evidence |
|---|---|---|
| Every screen in Vietnamese | **Yes, as behaviour.** Console tabs are `Tồn và lô / Giao dịch và audit / Đồng bộ và HQ / Job / Doanh thu`; Staff App tabs are `Tra cứu / Cảnh báo cận hạn / Đề xuất / Giảm giá`. This is pre-existing, not a PB-51 delivery | `MainForm.cs` (both clients) |
| Duplicate shows code `DUPLICATE_IGNORED` | **Yes** | `MockPosBackend.cs:137`, and the same code on the server in `middleware/app/services/pos_events.py:43`, `pos_return.py:29`, `pos_cancellation.py:39` |
| Duplicate shows the exact sentence "Giao dịch đã được ghi trước đó" | **No.** The message is English: `"Transaction already recorded"` (`MockPosBackend.cs:138`); the sentence appears nowhere in `clients/` | same |
| Staff App statuses/alerts/rules/categories/reasons in Vietnamese | **Partly.** Vietnamese UI text exists (`Chấp nhận`, `Từ chối`, `Đã tải đề xuất.`); no dedicated enum/status mapping layer, and no commit claims one | `StaffApp/UI/MainForm.cs` |
| Dự báo tab with two charts | **No.** `git grep -i 'Dự báo\|forecast\|chart'` over `clients/staff-app` is empty; the Staff App has four tabs and no forecast tab. The only forecast view is a **grid** in the *demo console* (`MainForm.cs:316`, `ReadOnlySql.cs:42`), with no charts and no shortage→surplus→balanced sort | git grep |
| 30 products, six categories, Vietnamese names | **No.** The seed inserts **9 products in 3 categories** (`Dairy`, `Bakery`, `Dry goods`) with English names (`Fresh milk 1L`, `Bread 400g`, …) | `database/seed/002_demo_catalog.sql` |
| The 9 old SKUs still have stock 40/25/15 | **Yes** | same seed: `CASE s.store_id WHEN 'STORE-DN1' THEN 40 WHEN 'STORE-DN2' THEN 25 ELSE 15 END` |

Consequence: the act tables in §2–§7 use only what is on `main`. Ticking the three "No" lines would put a false claim in front of the mentor.

### 11.1b Checklist to paste into the UAT issue

These are the lines at stake, as checkboxes, so the 30/11 UAT can tick them or leave them with a stated reason. The "No" lines cannot be ticked until PB-51/PB-52/PB-53 merge; **waiting on that merge before the freeze at 12:00 30/11.**

```
- [x] Duplicate sale shows code DUPLICATE_IGNORED — checked on main a5f509b (POS45-3)
- [x] Every screen in Vietnamese, as it stands on main — behaviour only, not a PB-51 delivery
- [ ] Duplicate sale shows the sentence "Giao dịch đã được ghi trước đó" — waiting on the PB-51 merge before the 12:00 30/11 freeze; main shows the English "Transaction already recorded"
- [ ] Staff App has a Dự báo tab with two charts, sorted shortage → surplus → balanced — waiting on the PB-53 merge before the 12:00 30/11 freeze; not on main (four tabs, no forecast tab)
- [ ] Demo catalogue is 30 products in six categories with Vietnamese names — waiting on the PB-52 merge before the 12:00 30/11 freeze; main seeds 9 products in three categories
```

If the three do not merge by 12:00 30/11, they are left unticked with that sentence as the reason, and §6 of `Report_Technical_Part.md` records the gap.

Before the freeze, Khanh and Sang must say in the team chat which branch, if any, carries PB-51/52/53; if none does, those lines are dropped from the UAT and the report records the gap (§6 of `Report_Technical_Part.md`).

### 11.2 Other documents the briefs reference that the repo does not have

| Path as written in the brief | Referenced by | In repo? |
|---|---|---|
| `docs/Demo_Plan.md` | `Huong_Dan_Trien_Khai.md`, `Quang.md` | No, at any commit |
| `docs/sprint-4/Video_Demo_Plan.md` | `Quang.md` | No — written fresh as part of this deliverable |
| `docs/mentor-review-27-11/` | `Quang.md` (27 Nov) | No |
| `docs/Demo_Setup_14-11.md` | `Quang.md` (27 Nov, "step 7") | No; `docs/demo/Sprint_3_Demo.md` §1.4 covers reset + smoke |
| `Kiem_Thu_Test_Case.md` | `Huong_Dan_Trien_Khai.md`, `Quang.md` | No — it exists only in a local working folder outside the repository |
| `scripts/demo/run_client_tests.ps1` | Quang's own `Retest_Skipped_Cases.md` §3 | No; only `run_console_tests.ps1`, hard-coded to the demo console |

The three Sprint 4 notes Quang already wrote (`Bao_Cao_Kiem_Thu_Sang_26-11.md`, `Retest_Skipped_Cases.md`, `Review_Test_Case_Sprint2-3.md`) exist only in the old checkout on `docs/no-deps-and-audit-followups` and have never been merged; they are copied into this branch under `docs/sprint-4/` so the report can cite them. Each carries a banner saying it is a 26/11 historical record, and that its `evidence/` files and helper scripts are not in the repository.

### 11.3 The UAT issue itself is not open yet

The 27/11 brief asks for a GitHub issue titled **"UAT Capstone 1"**, due 27/11, to hold this checklist and the bug list. As of this commit the repository has no such issue — a title search returns no match, and the only issues are the PRs and the `[TestCase]` reports.

Opening it needs repository write access, which a docs branch cannot grant itself, so it is the one item in this deliverable that must be done by hand:

1. Open the issue titled `UAT Capstone 1`, label/assign it to Quang, reference this file.
2. Paste §2–§7 as the checklist body, then §11.1b under a "27/11 add lines" heading.
3. Paste `Bug_List_PB-38-3.md` as the bug-list section of the same issue, per that file's header.

Until it exists, the pass/fail record lives only in this file and in `Regression_v1.0_Runbook.md` §7.
