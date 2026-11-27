# PB-38-3: UAT bug list and test-case issues

**Owner:** Quang · **Opened:** 27/11/2026 · **Base:** main `a5f509b`
**Issue title (GitHub):** "UAT Capstone 1" — this file is the body's bug-list section
**Issue state:** **not opened yet.** A title search finds no such issue; opening it needs repository write access. Steps are in `UAT_Capstone_1_List.md` §11.3.
**Triage:** Kiệt, 28/11, PB-41-1

---

## 1. The three kinds of entry

| Kind | Title format | Opened when | Goes into |
|---|---|---|---|
| UAT failure | `[UAT] <act>.<step>: <short symptom>` | a UAT checklist line fails during the 27/11 or 30/11 run | the UAT issue checklist |
| Test-case failure | `[TestCase] <case id> <short title>` | the 28/11 re-check finds a case at FAIL in column J or L | the same UAT issue checklist |
| Blocker | `[UAT] <act>.<step>: BLOCKER <symptom>` | the failure stops the demo of that act | the top of the UAT issue, and Kiệt is pinged directly |

Nothing else is a bug-list entry. A missing feature that the demo plan never claimed is **not** a UAT failure — it is recorded in `UAT_Capstone_1_List.md` §11.1 and in the report's known limitations. Opening a `[UAT]` issue for a feature that was never on `main` would turn a scope decision into a fake defect.

---

## 2. Issue body template

```markdown
**Act.step:** 4.2
**Found on:** 27/11/2026, UAT 1, machine B (Thanh Khê POS)
**Base:** main a5f509b
**Test-case id:** POS45-6 (if the step has one)
**Severity:** blocker / major / minor

**Steps to reproduce**
1. …
2. …

**Expected**
…

**Actual**
… (paste the on-screen text, HTTP status and code, and the row that proves it)

**Evidence**
- screenshot: …
- command + output: …
```

Severity, so triage is mechanical:

- **blocker** — the act cannot be demonstrated at all (crash, cannot log in, wrong store's data, console will not open).
- **major** — the act demonstrates but the result contradicts the demo plan, and a viewer would notice.
- **minor** — cosmetic, a wording or layout problem that the viewer would not notice.

---

## 3. Triage rules for Kiệt (PB-41-1)

1. Anything with severity **blocker** is fixed before 18:00 29/11 (đợt A).
2. A `[TestCase]` issue whose case is already fixed on `main` is closed with the commit hash, not silently dropped.
3. A failure caused by demo data (stock already sold, alert already resolved) is closed as "data, reset and retry", with the reset command in the comment.
4. After 12:00 30/11 only blockers and submission blockers may merge, and only with Kiệt's approval in the group chat (`Huong_Dan_Trien_Khai.md` §1).

---

## 4. Bug list itself

**Status at 27/11, before the UAT run: empty.** The UAT has not been run yet at the time this file is committed, so there is nothing to list. This is the honest state: the list is created by the run, not before it.

The rows are added here as the run happens, then pasted into the issue.

| # | Act.step | Title | Severity | Owner | Issue | State |
|---|---|---|---|---|---|---|
| — | — | *no entries until the 27/11 run* | — | — | — | — |

---

## 5. What the test-case re-check contributes

The 28/11 re-check (TC-KH, TC-SA) writes FAIL into column J or L of `GROUP_08_Test case.xlsx`. Each such case becomes one `[TestCase]` issue. The workbook export used for the totals in `UAT_Capstone_1_List.md` §10 has **0 FAIL across all 269 cases**, so on that export this section adds nothing — but the export is from before the re-check, so it must be re-run after 18:00 28/11 and this section updated from the new numbers.

Two entries are already known as **not implemented** rather than failed, and they are not `[TestCase]` issues:

- `TST38-1..4` — this UAT itself, run today.
- `TST44-1..3` — PB-44 measurements exist (`docs/reports/Guardrail_Metrics.md`) but the sheet rows are still "Not Implemented"; Sang updates them.

---

## 6. After triage

- Every fixed issue gets the fixing commit in a comment.
- The UAT issue's checklist is updated so the mentor can see the pass rate, not just the defects.
- Anything not fixed by 12:00 30/11 moves to the report's known limitations, with the issue number, so the report never claims a clean run over an open defect.
