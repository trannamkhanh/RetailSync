# Video demo plan (PB-42-3 script and data, PB-42-4 recording)

**Owner:** Quang (machine S, recording and editing) · **Recorded:** 1/12/2026 · **Narration:** Kiệt
**Base:** the commit tagged `v1.0` (frozen 30/11). Video and report must use the same commit.
**Fills:** the path `docs/sprint-4/Video_Demo_Plan.md` that the 27/11 brief references but which did not exist in the repository before this file (`UAT_Capstone_1_List.md` §11.2).

---

## 1. What this document is

A step-by-step recording plan: machine setup, the order of acts, what is on screen at each moment, and what to do when something fails live. It is written against what is actually on `main` at `a5f509b`, so it contains **no** Dự báo tab in the Staff App and **no** 30-product Vietnamese catalogue — neither exists (`UAT_Capstone_1_List.md` §11.1). If PB-51/52/53 merge before the freeze, add their steps in §5 and re-record those acts.

---

## 2. Machine setup (do the night before, 30/11)

### 2.1 Machine S — the presenter machine, and what is filmed

1. `git checkout v1.0`, confirm `git describe --tags` prints `v1.0`, then `docker compose pull` / `build` **while still online**.
2. `.env`: `DB_NAME=RTS_DB_DEMO`, `SYNC_INTERVAL=3600`, `SYNC_RETRY_BASE_SECONDS=10`, `POS_BIND_ADDRESS` and `MIDDLEWARE_BIND_ADDRESS` set to S's static IP on the private network. Both values match `Sprint_3_Demo.md` §1.2 and the lines `reset_demo_db.ps1 -DemoMode` prints: `3600` keeps the scheduler from syncing in the middle of act 5, and `10` keeps a retry from waiting a full minute.
3. Certificates regenerated so the SAN contains S's IP. Do **not** recreate the CA — A and B hold copies of `ca.crt`.
4. `docker compose up -d --wait sqlserver` — the reset script needs the server up; it does not start it.
5. `powershell -File scripts/demo/reset_demo_db.ps1 -DemoMode` — resets the demo database and prints the demo-mode env lines.
6. `sprint2_smoke.py` twice, both all PASS.
7. **Reset `RTS_DB_DEMO` once more** — the smoke test writes sales into the database, so without this second reset act 2 starts on stock the smoke run already changed.
8. Open the demo console; confirm five tabs load with no red error lines: **Tồn và lô**, **Giao dịch và audit**, **Đồng bộ và HQ**, **Job**, **Doanh thu**.
9. Set display scaling so the console is readable at 1080p on the recording — `FontSize` **16–20** is the readable range; 20–24 crowds the wider grids at 1080p.
10. Agree the seating plan with Kiệt (who sits at A, B and S) — settle it by 1/12, not on the day.

### 2.2 Machines A and B

- A: Demo POS on `POS-DN1-01`, plus Staff App with `staff_dn1`.
- B: Demo POS on `POS-DN2-01`.
- Each machine has `ca.crt`, its own terminal certificate and key, and its token file. `appsettings.Local.json` points at `https://<S IP>:9443/api/v1`; the Staff App points at `https://<S IP>:8443/api/v1`.
- Both run from a path on drive C if the app fails to start from another drive — a known environment limit (see `Retest_Skipped_Cases.md` §4.1).

---

## 3. Recording setup

| Item | Setting |
|---|---|
| Recorder | Windows Game Bar (`Win+G`) on S, 1080p 30 fps, microphone on |
| Narration | Kiệt, live over the recording, not dubbed afterwards — a live voice matches the live clicks |
| Console | Full screen on S, not windowed, so tab labels are legible |
| A and B | Capture only when the act needs them; cut to them, do not split-screen (text becomes unreadable) |
| Clock | Show the console status line so timestamps in the video match the audit entries |

---

## 4. Shot list

Record in this order, in one take per act where possible. Name files `act-<n>-<take>.mp4`.

### 4.0 Slate (20 s)

Console full screen, all five tabs visible. Narration: three machines, one private WAN, what each plays. No clicking.

### 4.1 Act 1 — architecture (60 s)

Show the architecture diagram, then the console. State the three data locations: POS has no business database, middleware holds the region, HQ holds SKU totals only.

**There is no diagram asset in the repository** (`docs/` holds no `.png`, `.svg` or `.drawio`; the diagrams live inside the Word design documents, which are not committed). Before recording, export the architecture figure from `C1SE.24_ArchitectureDesign_v1.5_3.docx` to PNG and keep it outside the repo in a local `video/` folder. Do not plan a shot around a file that has to be produced on the day.

### 4.2 Act 2 — live selling (90 s)

1. A sells 2 × `SKU-0001`; cut to S: stock 40 → 38, the earliest-expiry batch reduced first, one audit line appears.
2. B sells a multi-item basket; cut to S: the Thanh Khê rows appear in the same grid.
3. A and B sell almost simultaneously; both `OK`, each store's stock independent.

**On-screen proof to hold for two seconds:** the `current_stock` value and the batch row.

### 4.3 Act 3 — reliability and security (90 s)

1. B presses **Gửi lại**: `200 DUPLICATE / DUPLICATE_IGNORED`, stock unchanged.
2. Resend with different content: `409 CONFLICT`.
3. Send with the other terminal's certificate: `403 FORBIDDEN`, and the `EVENT_REJECTED` audit line on S.
4. A returns one item: stock goes back up on the same batch.
5. A cancels a sale: batches restored.

Do **not** script the "cancel a sale that has returns" case; it is API-only and would need a console moment the video does not have.

### 4.4 Act 4 — WAN outage (90 s)

1. Show A and B both selling, then pull B's cable on camera.
2. B sells 3 orders; each shows as queued.
3. A keeps selling; Hải Châu unaffected.
4. Plug the cable back; B drains 3 orders in order, same transaction ids.
5. Cut to S: exactly 3 transactions, none lost, none duplicated, Thanh Khê stock correct.

This act is the strongest segment. Do not cut the drain — the automatic catch-up is the point.

### 4.5 Act 5 — HQ sync (90 s)

1. Press **Chạy đồng bộ**: each store one batch `PENDING → SENT → ACKED`; HQ totals match.
2. Switch HQ `OFFLINE`; A and B sell more; batches stay `PENDING` with attempts and last error.
3. Switch HQ `ONLINE`; batches ACK oldest-first; totals right, nothing double-counted.
4. Send a snapshot from HQ: `422 SNAPSHOT_REJECTED`, stock unchanged, audit line.

### 4.6 Act 6 — near-expiry, forecast, recommendations (150 s)

1. Run the near-expiry job, then the recommendation job. Alerts for the Dairy/Bakery batches; proposals with reasons.
2. Lower the guardrail max discount, rerun: the over-limit proposal is `ADJUSTED` or `BLOCKED` and disappears from the staff list.
3. Cut to A, Staff App **Cảnh báo cận hạn**: `EXPIRED` first, then fewest days.
4. Barcode lookup of a product sold out at Hải Châu: own batches and expiry, then nearby stores **nearest first — Sơn Trà (~1.7 km) above Thanh Khê (~4.4 km)**, each row carrying its distance.
5. Open a proposal, read reason and guardrail result, **Chấp nhận**; reject another. Press Accept again: "already decided".
6. Staff App **Giảm giá**, switch *Cửa hàng của tôi* / *Tất cả cửa hàng*.

### 4.7 Act 7 — dashboard, audit and numbers (90 s)

1. **Doanh thu** tab (token `admin`), scope **Toàn hệ thống**, bucket **Ngày**: the three charts and the KPI. Say plainly that the 90-day history is simulated by `tools/history-generator`, not transactions from this demo.
2. Switch to one store: line and pie narrow, the bar chart still compares all three — say this is by design, so nobody reads it as a bug.
3. **Làm mới**: the status line reads "Làm mới lúc HH:mm:ss. Không có lỗi."
4. Audit log with the Auditor token: every change from acts 2–6 is there.
5. Show the measured-numbers table, reading each figure from `docs/reports/` — p95 latency 226.60 ms, 98.91% reduction, 100% ACK, WAPE vs seasonal naive, near-expiry 32/32, guardrail PASSED/ADJUSTED/BLOCKED, staff acceptance 60% (6/10), E2E reconciliation.

### 4.8 Outro (20 s)

Group shot, the tag `v1.0` on screen in a terminal.

---

## 5. If a new feature merges before the freeze

If PB-51/52/53 land before 12:00 30/11, add:

- a Vietnamese demo catalogue segment in act 2 (30 products, six categories) — but only after resetting `RTS_DB_DEMO` with the new seed, and only after re-running the forecast and recommendation jobs, because the report figures are measured on the 9-SKU seed;
- a Dự báo tab segment in act 6 — only if the tab and both charts exist and the table sorts shortage → surplus → balanced;
- the Vietnamese duplicate sentence in act 3 — replace the English `Transaction already recorded` shot.

Re-record affected acts entirely; do not splice half an act from before the change and half from after.

---

## 6. Contingencies

| Failure | Action |
|---|---|
| A or B cannot reach S | Check IP, firewall, network profile Private. Switch to the spare laptop already configured |
| Certificate error | Regenerate on S, copy to A/B, retry the act. Rehearsed, so unlikely |
| Docker or SQL Server on S dies | Cut to the rehearsal recording of that act and keep the narration live. Say so plainly |
| Console will not start | Fall back to the one-action scripts (`sync_run.ps1`, `hq_mode.ps1`, `run_job.ps1`, `cross_store.ps1`, `audit_tail.ps1`) and film the terminal |
| Out of time | Drop act 6 step 2 (guardrail) and act 2 step 3 (simultaneous sales) — this is the order Kiệt approved in `Demo_Plan.docx` |

---

## 7. Data rules for the recording

- Record on a **freshly reset** `RTS_DB_DEMO`: stock 40/25/15, clean alert set, clean proposal set, new forecast.
- Never record on the regression end-state from 30/11.
- Reset and re-seed **between takes** if a sale changed the numbers the narration reads.
- Never record against `RTS_DB`.

---

## 8. Editing

1. Cut by act; keep the act titles as lower-third text, Vietnamese.
2. Keep live narration; do not replace with text cards.
3. Blur or crop any token, certificate fingerprint, or password that appears.
4. Target 12–15 minutes final. Anything longer loses the viewer; the mentor Q&A is separate.
5. Export 1080p H.264, plus a 720p copy for upload.
6. Store the master outside the repo (a local `video/` folder) and put only the link in the report.

---

## 9. Done when

- Every act 2–7 has a recorded segment on the `v1.0` commit.
- The numbers spoken in act 7 match `docs/reports/` exactly.
- A dry review pass by Kiệt is done before 1/12 evening.
- The final cut exists in three places: local master, cloud copy, and the link in the report.
