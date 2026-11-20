# Dashboard PB-49 — các thay đổi cần làm với tài liệu baseline

- **Ngày:** 2026-11-19
- **Cơ sở:** 5 tài liệu baseline trong `D:\NCKH\doc\New folder\`, tất cả là bản chụp tại `main-986b3d3`:
  - `C1SE.24_ArchitectureDesign_v1.2`
  - `C1SE.24_Database_Design_and_Data_Mapping_Document_v1.3`
  - `C1SE.24_Project_Plan_v1.2`
  - `C1SE_24_RetailSync_Sprint_Backlog_v1.4` (.xlsx)
  - `C1SE_24_Software_Requirement_Specification_v1.3`
- **Phương pháp:** trích toàn bộ text + bảng của 5 file, đối chiếu với code `main` @ `0bdea8d` và kế hoạch PB-49 v2. **Không sửa file nào.**
- **Giới hạn:** đọc nội dung, không đọc hình/sơ đồ (Figure 2–4 của Architecture là ảnh, không trích được). Các sơ đồ cần người xem trực tiếp.

---

## 0. Bảng tổng hợp mức độ

| # | Tài liệu | Mức | Số chỗ phải sửa |
|---|---|---|---|
| 1 | Sprint Backlog v1.4 (.xlsx) | 🔴 Bắt buộc | 7 sheet + 1 file riêng |
| 2 | Database Design v1.3 (.docx) | 🔴 Bắt buộc | 2 chỗ |
| 3 | SRS v1.3 (.docx) | 🟠 Quan trọng | 5 câu + 1 FR |
| 4 | Architecture v1.2 (.docx) | 🟠 Quan trọng | 3 chỗ + 1 sơ đồ |
| 5 | Project Plan v1.2 (.docx) | 🟡 Nhẹ | 2 mục |

**Không phải sửa:** con số "19 tables" ở Database Design §3.1 — migration 004 **không thêm bảng**, chỉ thêm 2 cột + 1 index.

---

## 1. Sprint Backlog v1.4 — bắt buộc, nhiều nhất

File: `C1SE_24_RetailSync_Sprint_Backlog_v1.4_main-986b3d3.xlsx`
14 sheet: Main, Product Backlog, Sprint 1–4 Backlog, Sprint 1–4 Reports, Sprint Summary, Traceability, SRS Alignment Log, Main Branch Progress.

**Hiện trạng: chuỗi "PB-49" xuất hiện 0 lần trong toàn bộ workbook.**

### 1.1 Product Backlog — thêm dòng PB-49

Hiện có 58 item, item cao nhất là PB-48. Dòng PB-36 ở đây là:

> `PB-36 | Guardrail & acceptance dashboard | Store manager | A dashboard of guardrail outcomes and acceptance rate | I can review the system's behavior | ... | Traces to: Metrics | Could | To Do | E7. Staff API, Staff App UI & Cross-Store | 1 | ... | 5`

**Thêm dòng mới** (giữ PB-36 nguyên vẹn — nội dung khác hẳn):

| Cột | Giá trị đề xuất |
|---|---|
| Backlog ID | `PB-49` |
| Title | Revenue dashboard |
| Persona | Store manager / Business admin |
| Story | A revenue dashboard over the Middleware API |
| Benefit | I can see sales revenue by day, category and store |
| AC | Xem §1.2 |
| Traces to | `NFR01` (read path), hoặc ghi rõ "ngoài SRS — bổ sung" |
| Priority | `Could` |
| Status | `To Do` |
| Epic | Epic mới **E9. Reporting & Dashboards**, hoặc gắn `E8. Testing, Evaluation & Docs` nếu không muốn thêm epic |
| SP | 5 |
| Notes | "Bổ sung 19/11/2026 theo quyết định của Kiệt. Không trùng PB-36 (guardrail dashboard)." |

### 1.2 Acceptance criteria cho PB-49 (để dán vào ô AC)

```
- GET /dashboard/revenue trả net_revenue theo bucket day/week và tổng kỳ, với [from, to) nửa mở
- GET /dashboard/revenue-by-category trả phần theo product.category
- GET /dashboard/revenue-by-store trả cột theo store_id trong tập so sánh, không vượt quyền
- GET /dashboard/stores trả cửa hàng trong phạm vi vai trò, gồm cả is_active = 0
- Admin và Auditor xem mọi cửa hàng; Manager chỉ cửa hàng của mình (403 nếu vượt)
- Chỉ Admin, Auditor, Manager gọi được; HQ/Staff/POS nhận 403; không token 401
- Doanh thu tính từ occurred_at (fallback created_at), không ghi đè bằng giờ nhận
- Phản hồi trả quality {on_time, backfill, suspect_future, suspect_old, unknown} và time_policy
- include_suspect=false loại SUSPECT_* khỏi số tiền nhưng vẫn trả quality
- Tiền là JSON number 2 chữ số thập phân; thời gian là ISO 8601 UTC
```

### 1.3 Sprint 3 Backlog — quyết định về năng lực

Số liệu thật của sheet (dòng tổng):

| Dòng | Giá trị |
|---|---|
| Product Backlog estimate of this sprint's items | 205,19 |
| Sprint tasks linked to backlog items | 206,5 |
| Meetings / overhead | 2,5 |
| **Total sprint estimate** | **209** |
| **Capacity (4 × 4 h × 14 ngày)** | **224** |
| **Load** | **0,933 (93,3%)** |

Thêm D1–D3 (24–29 giờ) → **233–238 giờ / 224 = 104–106%**.

**Ba lựa chọn, phải chọn một:**

| Lựa chọn | Hệ quả |
|---|---|
| **A. Thêm hết D1–D3 vào Sprint 3** | Load 104–106%; vượt capacity; phải ghi lý do vào Notes và chấp nhận rủi ro |
| **B. Chỉ thêm D1–D2 (18–21 h)** | Load 101–103%; D3 chuyển Sprint 4 → nhưng D3 mới là thứ demo cần |
| **C. Chỉ thêm D1–D3 bản tối thiểu (16–18 h)** | Load ~100%; cắt đường+KPI+tối thiểu, đúng §3.2 của kế hoạch v2 |

**Đề xuất: C** — thêm đúng các dòng task của D1/D2/D3-tối-thiểu, không thêm phần P5.

Các dòng cần thêm vào Sprint 3 Backlog (Owner = Quang):

| Backlog Id | Description | Estimate (h) |
|---|---|---|
| PB-49-1 | Contract DS-04 cho 4 endpoint dashboard | 2 |
| PB-49-2 | Migration 004 + model + ghi occurred_at | 4 |
| PB-49-3 | classify_time + cấu hình ngưỡng + test biên | 3 |
| PB-49-4 | Repository + service cho 4 endpoint | 4 |
| PB-49-5 | 4 route + test_auth_matrix + test_dashboard | 4 |
| PB-49-6 | Tab doanh thu (đường + KPI + nhãn chất lượng) | 4 |
| **Cộng** | | **21** |

Với 21 giờ: 209 + 21 = **230 / 224 = 102,7%**. Nếu muốn ở mức ≤100% thì giảm PB-49-1 xuống 1 h và PB-49-5 xuống 3 h → 19 giờ → 101,8%; hoặc chuyển PB-49-6 sang Sprint 4 và chấp nhận demo không có tab.

### 1.4 Sprint 4 Backlog — nhận phần hoãn

Thêm các dòng cho phần P5 đã cắt khỏi demo 27/11:

| Backlog Id | Description | Estimate (h) |
|---|---|---|
| PB-49-7 | Biểu đồ tròn theo danh mục | 3 |
| PB-49-8 | Biểu đồ cột so sánh chi nhánh | 3 |
| PB-49-9 | Multi-select tập cửa hàng so sánh | 2 |
| **Cộng** | | **8** |

### 1.5 Sprint Summary — cập nhật 3 chỗ

| Dòng hiện tại | Sửa thành |
|---|---|
| `3 \| 14 Nov - 27 Nov \| ... 80 SP ... 205.19083969465646 h \| 224 \| 0.916 \| Within capacity` | Cộng SP (nếu chọn A/B/C) và hours (209 → 230 hoặc mức bạn chọn), Load 1,027 |
| `4 \| 28 Nov - 11 Dec \| ... 79 SP ... 202.62595419847327` | Cộng 8 giờ của PB-49-7..9 → ~211 h, Load ~0,94 |
| `Unplanned \| — \| Not scheduled (PB-11, 19, 29, 30, 36) \| 21 \| 5` | Giữ nguyên — **PB-49 không thuộc Unplanned** nếu đã xếp vào Sprint 3/4 |
| `Total \| ... 278 \| 58 \| ... 713.0381679389313 \| 1024 \| 0.6437261450381679` | Cộng SP và giờ của PB-49 vào tổng |

### 1.6 SRS Alignment Log — thêm 1 dòng

Sheet hiện có 18 dòng (#1–#18). Thêm **#19**:

| Cột | Giá trị |
|---|---|
| Category | `Gap` |
| Issue | "SRS chỉ có dashboard guardrail (PB-36, Could). Không có yêu cầu nào cho dashboard doanh thu, nhưng kế hoạch Sprint 3 cần một màn doanh thu cho demo và một API đọc doanh thu tái dùng được." |
| Resolution in backlog | "Thêm PB-49 (Could) như luồng song song; UI chỉ Admin; API giữ Admin/Auditor/Manager; doanh thu theo `occurred_at`." |
| Backlog items changed | `PB-49` |
| SRS follow-up | "Thêm FR10 (hoặc ghi PB-49 là bổ sung ngoài SRS) ở §4.1; cập nhật §3.4 và §3.5 – xem file `Dashboard_Baseline_Docs_Changes.md` §3." |

### 1.7 Traceability — thêm 1 dòng

| Requirement / Metric | Description | Covered by | SRS use case / rule / BFD |
|---|---|---|---|
| `FR10` (nếu thêm) | "Revenue reporting read API over occurred_at" | `PB-49, DS-04, DS-05` | "Ngoài SRS v1.3 — bổ sung 19/11/2026" |

Nếu **không** muốn thêm FR10 thì ghi rõ ô "SRS use case" là `—` và note "ngoài phạm vi SRS".

### 1.8 Main Branch Progress — thêm 1 dòng sau khi merge

Sheet chụp tại `986b3d3`. Sau khi D1–D3 merge:

| Backlog ID | Main evidence | Notes | Merged PRs |
|---|---|---|---|
| `PB-49` | `Merged` | "4 dashboard endpoints over occurred_at/effective_at; classify_time; revenue tab in demo console. Half-open [from,to). Dashboard and sync use different time anchors — totals only reconcile over a whole period." | `#D1, #D2, #D3` |

### 1.9 `GROUP_08_Test case.xlsx` — file riêng, tạo sheet mới

Không nằm trong 5 file trên nhưng là tài liệu kiểm thử chính thức. Cần sheet **`PB-49 Revenue Dashboard`**, mã test **`DSH49-1 … DSH49-n`**, tối thiểu:

| Mã | Nội dung |
|---|---|
| DSH49-1 | Admin gọi 4 endpoint → 200, đúng shape |
| DSH49-2 | Auditor gọi → 200, mọi cửa hàng |
| DSH49-3 | Manager gọi cửa hàng mình → 200; cửa hàng khác → 403 |
| DSH49-4 | HQ/Staff/POS → 403; không token → 401 |
| DSH49-5 | `from >= to` → 422; `bucket` lạ → 422; khoảng > 366 ngày → 422 |
| DSH49-6 | `[from, to)` — bản ghi đúng mốc `to` không được tính |
| DSH49-7 | `occurred_at` NULL → quality.unknown; vẫn tính vào doanh thu qua `created_at` |
| DSH49-8 | `include_suspect=false` → loại SUSPECT_* khỏi tiền, giữ `quality`, `excluded` > 0 |
| DSH49-9 | SALE + CANCELLATION cùng kỳ → triệt tiêu; SALE ở kỳ trước, huỷ ở kỳ sau → kỳ sau âm |
| DSH49-10 | Timestamp offset +07:00 → lưu UTC; không offset → hiểu UTC; năm 1900/9999 → lưu + SUSPECT (không 503) |
| DSH49-11 | DUPLICATE gửi lại với timestamp khác → `occurred_at` giữ bản đầu |
| DSH49-12 | `is_active = 0` vẫn xuất hiện ở `/dashboard/stores` |
| DSH49-13 | Tổng toàn hệ thống = tổng các cửa hàng |
| DSH49-14 | `Σ net_revenue` mọi `sync_batch` = `Σ Dashboard` cùng `from/to` |

---

## 2. Database Design v1.3 — bắt buộc, 2 chỗ

File: `C1SE.24_Database_Design_and_Data_Mapping_Document_v1.3_main-986b3d3.docx`

### 2.1 §3.4 Transaction Tables → Table 10: `pos_transaction`

Hiện có đúng 9 cột, kết thúc bằng (nguyên văn):

> `created_at | DATETIME2 | | Time the Middleware received the event`

**Thêm 2 dòng ngay sau `created_at`:**

| Field Name | Data Type | Key | Description |
|---|---|---|---|
| `occurred_at` | `DATETIME2` (nullable) | | Time the POS declared the sale, stored as UTC without an offset. NULL for rows written before PB-49; it is never overwritten by the receipt time. |
| `effective_at` | `DATETIME2` computed, persisted | | `COALESCE(occurred_at, created_at)`. The single column revenue queries filter and group by; persisted so that it can be indexed. |

**Thêm ghi chú ngay dưới bảng Table 10** (giữ giọng văn hiện có):

> Revenue reporting reads this table through `effective_at`. The column is computed and persisted by the database, so application code never writes it. An index on `effective_at` supports the range filter. The count of tables in §3.1 does not change: PB-49 adds columns, not a table.

### 2.2 §4.1 POS Event Mapping

Bảng mapping hiện có 12 dòng, **không có dòng nào cho `timestamp`** — đây là bằng chứng timestamp đang bị bỏ ở code.

**Thêm 1 dòng** (đặt sau dòng `original_transaction_id` / trước dòng `payload_hash`):

| Source | Field | Target Table | Field | Mapping Description |
|---|---|---|---|---|
| POS event | `timestamp` | `pos_transaction` | `occurred_at` | Direct copy, stored as UTC: a value with an offset is converted to UTC, a value without an offset is read as UTC. It is kept exactly as declared and is never replaced by the receipt time, so a POS that sends its backlog late still books revenue on the day of the sale. An implausible value is stored and classified, not rejected. |

### 2.3 Những chỗ **không** phải sửa (đã kiểm)

| Vị trí | Hiện tại | Vì sao vẫn đúng |
|---|---|---|
| §3.1 Middleware Database Overview | "It contains **19 tables** in five groups" | PB-49 không thêm bảng |
| Table 1: Tables of RTS_DB by group | 19 dòng | Không đổi |
| §4.1 dòng `created_at` | "Derived: set by the Middleware (UTC)" | Vẫn đúng — `created_at` giữ nghĩa "giờ nhận" |

---

## 3. SRS v1.3 — 5 câu + 1 FR

File: `C1SE_24_Software_Requirement_Specification_v1.3_main-986b3d3.docx`

### 3.1 §3.5 Constraints → mục **Frontend** (3 câu liên tiếp)

**Câu hiện tại (dòng 117):**
> Besides the Staff App UI, the only other UI in scope is the demo POS terminal's sales interface or CLI (PB-45), used for demonstration and not part of the product.

**Vấn đề:** sai **trước cả PB-49**. Demo console (PB-42-6) đã merge nhưng SRS **không nhắc chữ "console" lần nào** trong toàn bộ file.

**Sửa thành:**
> Besides the Staff App UI, two presenter-only tools are in scope: the demo POS terminal's sales interface or CLI (PB-45) and the demo console (PB-42-6), a WinForms window on the presenter machine that reads the Middleware API and the demo database. Neither is part of the delivered product.

**Thêm câu mới ngay sau đó:**
> The demo console also shows a revenue tab (PB-49, Could). It reads the Middleware API with the Admin token only and is a presenter tool, not a product interface. The revenue API behind it is designed for reuse: Admin and Auditor read every store, Store Manager reads only the assigned store.

**Câu 118 giữ nguyên, không sửa:**
> The dashboard (PB-36) is Could and unscheduled.

→ PB-36 là dashboard **guardrail/acceptance rate** cho Manager, khác hẳn PB-49. Sửa câu này sẽ làm sai nghĩa.

### 3.2 §3.5 Constraints → mục **Out of scope**

Hiện liệt kê 6 mục (customer segmentation, advanced ML, label printing, event streaming, observability, transfer orders).

**Không cần thêm PB-49 vào đây**, nhưng nên thêm 1 câu ngay sau danh sách để tránh hiểu nhầm:

> Revenue reporting is not out of scope; it is a Could item delivered as PB-49 (see §3.5 Frontend and FR10).

### 3.3 §3.4 User Characteristics → **Store Manager**

**Câu hiện tại:**
> Oversees store performance through the stock query. Stock movements (PB-11) and the review of recommendations and guardrail outcomes (PB-36) are outside the MVP.

**Sửa thành:**
> Oversees store performance through the stock query and, for the assigned store only, the revenue API (PB-49). Stock movements (PB-11) and the review of recommendations and guardrail outcomes (PB-36) are outside the MVP.

### 3.4 §3.4 User Characteristics → **Auditor**

**Câu hiện tại:**
> Reviews audit logs. Read-only access (PB-04). Sync history (PB-19) is a Could item outside the MVP.

**Sửa thành:**
> Reviews audit logs. Read-only access (PB-04). Reads the revenue API of every store (PB-49). Sync history (PB-19) is a Could item outside the MVP.

### 3.5 §4.1 Functional Requirements — thêm **FR10**

Hiện có FR01–FR09. Thêm:

> **FR10 (PB-49): Report sales revenue**
> The system exposes a read-only revenue API over the transactions it already stores. Revenue is net: sales minus returns minus cancellations, computed with no status filter. Transactions are placed by `occurred_at` (the time the POS declared), falling back to `created_at` when absent. The API answers by day, week or month bucket; by product category; per store; and for a chosen set of stores. Access follows the role: Admin and Auditor read every store, Store Manager only the assigned store. Each response reports how many transactions are on time, backfilled, or suspect on time quality, so a reader can tell whether the figures are trustworthy.

### 3.6 §4.4 Evaluation Metrics — **không sửa**

Bảng hiện có 8 metric (PB-40 ×2, PB-39 ×2, PB-43, PB-24, PB-44 ×2). PB-49 **không tạo metric mới**; doanh thu là chức năng, không phải chỉ số đánh giá đồ án. Nếu muốn ghi nhận thì thêm 1 dòng tùy chọn:

| Metric (backlog item) | Definition and target |
|---|---|
| Revenue reconciliation (PB-49) | For the same half-open period, the sum of `net_revenue` over every `sync_batch` equals the sum reported by the revenue API. |

### 3.7 §2.2 Scope of the System — kiểm và có thể sửa 1 câu

Mục này nêu phạm vi hệ thống. Nếu có câu liệt kê chức năng mà không nhắc báo cáo doanh thu, thêm một mệnh đề ngắn; nếu không, bỏ qua — FR10 ở §4.1 là đủ.

### 3.8 §5.1 BFD / §5.2 List of Use Case — quyết định

| Lựa chọn | Hệ quả |
|---|---|
| **Không thêm UC** | Nhanh; nhưng FR10 sẽ không có use case, giống tình trạng PB-11 đã bị SRS Alignment Log ghi là "Gap" (#6) |
| **Thêm UC.10** cho doanh thu | Nhất quán với các FR khác, nhưng phải vẽ use case diagram → tốn thời gian sát hạn |

**Đề xuất:** thêm **UC.10** dạng rút gọn (một bảng use case, không vẽ lại sơ đồ), hoặc ghi vào SRS Alignment Log rằng FR10 không có UC — giống cách đã xử lý PB-11 (#6) và PB-31 (#14).

---

## 4. Architecture Design v1.2 — 3 chỗ + 1 sơ đồ

File: `C1SE.24_ArchitectureDesign_v1.2_main-986b3d3.docx`

### 4.1 §5.1 C&C View → câu mở đầu (sai từ trước)

**Câu hiện tại:**
> The system has **two kinds of clients**: the POS terminals and the Staff App.

**Vấn đề:** thực tế có 3 (POS terminals, Staff App, demo console). Sai này có từ trước PB-49.

**Sửa thành:**
> The system has two kinds of **product** clients, the POS terminals and the Staff App, plus one **presenter** client, the demo console (PB-42-6) that runs on the presenter machine and is not part of the product.

### 4.2 §4 Constraints → mục **Environments**

**Câu hiện tại:**
> The Staff App and the demo POS are thin WinForms desktop clients.

**Sửa thành:**
> The Staff App, the demo POS and the demo console are thin WinForms desktop clients; the console runs only on the presenter machine.

### 4.3 §5.1.2 Role and Responsibility of Elements — thêm 1 thành phần

Danh sách hiện có 14 mục: POS Terminals, Staff App, API layer, POS Integration Service, Inventory Service, Cross-Store Service, Audit Service, Aggregation Service, Sync Service + background worker, Near-Expiry Service, Forecast Engine, Recommendation Engine, Guardrail Service, SQL Server, HQ.

**Thêm 1 mục** (đặt sau "Cross-Store Service", cùng nhóm dịch vụ chỉ đọc):

> **Revenue Service**
> Read-only aggregation of stored transactions for the revenue dashboard (PB-49). It filters and groups by `effective_at`, assigns transactions to the period in which they occurred using the declared POS time, and returns how many transactions carry a suspect timestamp. It never writes. Access follows the role: Admin and Auditor read every store, Store Manager only the assigned store.

**Sửa thêm 1 câu ở "API layer"** nếu muốn gọn thay vì thêm thành phần:
> ... validates every request, writes the audit log and enforces per-store scope on read endpoints.

### 4.4 §5.1.1 Figure 2 (Component and Connector view) — sơ đồ ảnh

Đây là **ảnh**, không trích được. Cần người xem trực tiếp và quyết định:

| Lựa chọn | Công sức |
|---|---|
| Không vẽ lại | Thêm 1 câu ở prose "§5.1.2 Revenue Service" là đủ; sơ đồ giữ nguyên |
| Vẽ lại | Thêm 1 hộp "Revenue Service" cạnh Cross-Store Service, nối vào API layer và SQL Server |

**Đề xuất: không vẽ lại.** Cùng cách đã xử lý khi thêm Service khác — prose là đủ cho đồ án.

### 4.5 Những chỗ **không** phải sửa

| Vị trí | Vì sao |
|---|---|
| §5.3 Allocation View | PB-49 không thêm node, không thêm container; vẫn 1 Docker host + SQL Server + HQ mock |
| §5.2 Module View (layer packages) | `api/dashboard.py`, `services/dashboard.py`, `repositories/dashboard.py` nằm đúng 4 tầng đã mô tả — không đổi cấu trúc |
| Change log (1.0 / 1.2) | Thêm dòng 1.3 nếu bạn muốn ghi phiên bản mới; nội dung kỹ thuật không đổi |

---

## 5. Project Plan v1.2 — nhẹ, 2 mục

File: `C1SE.24_Project_Plan_v1.2_main-986b3d3.docx`

### 5.1 Mục **"Main Branch Implementation Update"** (supplement tại `986b3d3`)

Hiện có 3 đoạn: câu giới thiệu capacity, phân công Sprint 3 theo người, demo preparation, acceptance evidence pending.

**Thêm 1 đoạn** (đặt sau đoạn phân công Sprint 3):

> **PB-49 revenue dashboard (Could, added 19 November 2026).** A parallel thread to Sprint 3 phase 7, split into three pull requests: contract and `occurred_at` capture, the read-only dashboard API, and the revenue tab in the demo console. The first pull request touches the POS write path and carries the highest risk; it is merged first. Scope for the 27 November demo is limited to the daily revenue line, the totals and the time-quality label; the category pie, the store comparison and the multi-store selector move to Sprint 4.

### 5.2 Mục **"Demo preparation"**

**Câu hiện tại:**
> The team has a merged runbook, Windows demo console, paired terminal setup and script fallbacks for live stock, WAN recovery, HQ outage and recovery, snapshot rejection, alerts, cross-store lookup and forecasting.

**Sửa thành:** thêm "revenue by day" vào danh sách cuối:

> ... snapshot rejection, alerts, cross-store lookup, forecasting and revenue by day.

### 5.3 Table 9: Deliverables — tùy chọn

Nếu PB-49 được merge trước 11/12 thì thêm 1 dòng vào bảng deliverable. Nếu chỉ là Could item không kịp, ghi vào "Acceptance evidence pending" là đủ.

### 5.4 Kiểm tra mốc thời gian — **không sửa nhưng phải biết**

| Nguồn | Mốc |
|---|---|
| Project Plan | End Date **13 Dec 2026** |
| SRS §3.5 | Final deliverables **11 Dec 2026**; Sprints 1–4 = 64 ngày (22+14+14+14) |
| Review của Kiệt | "sau ngày nộp **3/12**" |

**Hai tài liệu chính thức thống nhất 11–13/12, không phải 3/12.** Cần hỏi lại Kiệt mốc 3/12 lấy từ đâu trước khi đưa vào kế hoạch.

---

## 6. Ba con số mâu thuẫn — chốt trước khi sửa file

| # | Review của Kiệt | Tài liệu baseline thực tế | Xử lý |
|---|---|---|---|
| 1 | "Sprint 3 đã **372 giờ (166%)**" | Sprint 3 Backlog: **209 h / 224 = 93,3%**. Chuỗi "372" **không tồn tại** trong workbook (1 kết quả duy nhất là `0.643726...` khớp ngẫu nhiên) | Hỏi lại Kiệt; dùng 209 h để tính |
| 2 | "hoãn sang sau ngày nộp **3/12**" | Project Plan: **13/12**; SRS: **11/12** | Hỏi lại Kiệt |
| 3 | "thư mục thật là `docs/project document/`" | Máy này: `docs/document/`; thư mục này còn **untracked** trên git | Trong tài liệu viết chung "tài liệu baseline giữ ngoài git", không ghi đường dẫn tuyệt đối |

---

## 7. Thứ tự thực hiện

| Bước | Việc | Vì sao thứ tự này |
|---|---|---|
| 1 | Chốt 3 con số ở §6 với Kiệt | Chặn mọi bước sau; ảnh hưởng trực tiếp đến PB-49 có làm được hay không |
| 2 | **Sprint Backlog**: §1.1 (PB-49), §1.3 (Sprint 3), §1.4 (Sprint 4), §1.5–§1.8 | Đây là nơi quyết định phân bổ; sửa trước để D1 có căn cứ |
| 3 | **Database Design**: §2.1, §2.2 | D1 cần contract DB đúng trước khi viết migration 004 |
| 4 | **GROUP_08_Test case.xlsx**: §1.9 | Cần mã `DSH49-n` trước khi viết test |
| 5 | **SRS**: §3.1–§3.5 | Sau khi D1/D2 ổn, vì FR10 phải khớp hợp đồng thật |
| 6 | **Architecture**: §4.1–§4.3 | Cùng lúc với SRS |
| 7 | **Project Plan**: §5.1–§5.2 | Cuối cùng, sau khi merge để ghi đúng thực tế |

---

## 8. Phụ lục — Đối chiếu nhanh với code

| Điều tài liệu nói | Code thực tế | Kết luận |
|---|---|---|
| DB §3.1: 19 bảng | Migration 001–003 tạo 19 bảng | ✅ đúng |
| DB Table 10: 9 cột | `models.PosTransaction` 9 cột | ✅ đúng, sẽ thành 11 |
| DB §4.1: không map `timestamp` | `PosEvent.timestamp` khai báo nhưng không dùng ở đâu | ✅ đúng — chính là gap D1 sửa |
| SRS §3.5: chỉ có Staff App + demo POS là UI | `clients/demo-console` đã merge (PB-42-6, PR #47/#48/#50) | ❌ SRS thiếu console |
| Arch §5.1: "two kinds of clients" | 3 client: POS, Staff App, demo console | ❌ sai |
| Arch §5.1.2: 14 thành phần | 13 router, không có revenue | ❌ thiếu |
| Backlog: PB-36 = guardrail dashboard (Could) | Không có code nào | ✅ đúng — khác PB-49 |
| Backlog: PB-49 | Không tồn tại | ❌ phải thêm |
| Plan: End 13/12, SRS: 11/12 | `main` không có gì ràng buộc | ⚠️ hai tài liệu lệch nhau 2 ngày |
