# Kế hoạch triển khai Dashboard doanh thu — PB-49 (v2, sau review)

- **Ngày:** 2026-11-19 (v2) · **v1:** 2026-11-19
- **Cơ sở:** source `main` @ `0bdea8d`; đối chiếu `origin/Quang` (store-web), PR #59/#60/#61 đang mở.
- **Trạng thái:** kế hoạch đã điều chỉnh theo review của Kiệt ngày 19/11. **Chưa thực hiện thay đổi nào.**
- **Mã backlog:** **PB-49 "Revenue dashboard" (Could)** — không dùng PB-36 (PB-36 là bảng tỉ lệ guardrail và tỉ lệ chấp nhận cho Manager, nội dung khác).
- **Quyết định của Kiệt (19/11):** Quang làm PB-49 như một luồng song song với giai đoạn 7.
- **Tài liệu nguồn:** `Dashboard_Survey_and_Plan.md` (v6 — thiết kế), `Dashboard_Backend_Tasks.md`, `Dashboard_Data_Availability.md`, và `Dashboard_Review.md` (review của Kiệt).

---

## 0. Thay đổi so với v1 (tóm tắt để đối chiếu)

| # | Review yêu cầu | v2 thay đổi gì |
|---|---|---|
| 1 | Tách 3 PR, PR đụng POS merge sớm nhất | §2 chia **D1 / D2 / D3**, có hạn merge từng PR |
| 2 | Migration 004 sẽ lỗi vì batch | §5.1 viết lại SQL **tách batch bằng `GO`** cho từng `ALTER`/`CREATE INDEX` |
| 3 | Trùng số migration với store-web | §5.2 ghi rõ Dashboard giữ **004**, store-web đổi thành 005/006 khi merge sau |
| 4 | Dẫn tài liệu không có/ sai đường dẫn | §9 bỏ đường dẫn tuyệt đối, chỉ dùng tên tài liệu; commit kế hoạch trong D1 |
| 5 | Timestamp phải đổi về UTC, timestamp vô lý phải lưu + SUSPECT, không 503 | §6.4 thêm quy tắc UTC hoá + biên năm 1900/9999 |
| 6 | Chạy `test_concurrent_traffic.py` 3 lần | §8.1 thêm vào điều kiện merge D1 |
| 7 | LiveCharts2 cần Internet + native SkiaSharp | §7.4 thêm bước build sẵn trước demo |
| 8 | Giữ quy ước "nút mờ khi 404" | §7.3 ghi rõ |
| 9 | Xung đột PR #61 | §10 thêm ràng buộc thứ tự merge tài liệu |
| 10 | Chưa có test case trong `GROUP_08_Test case.xlsx` | §8.3 thêm mã **DSH49-n** và việc tạo sheet |
| 11 | Cắt P5 khỏi demo 27/11 | §3 thu gọn phạm vi demo; P5 chuyển Sprint 4 |
| 12 | 7 điểm chốt được duyệt | §12 chuyển thành "đã chốt", giữ nguyên nội dung |
| 13 | Đo lại hiệu năng sau D1 | §10 thêm ràng buộc với PB-39 (#60) |

---

## 1. Bài toán cần giải quyết

Hệ thống trả lời được "tồn kho bao nhiêu" và "giao dịch nào vừa xảy ra", nhưng **không trả lời được câu hỏi doanh thu**:

1. Không có cách nào, từ dữ liệu đang có, biết "kỳ này bán được bao nhiêu tiền" mà không mở SQL tự viết truy vấn.
2. Không có API đọc doanh thu → không client nào (kể cả tương lai) dùng lại được.
3. Không phân biệt **giờ bán** và **giờ nhận**: POS gửi bù offline hôm nay bị tính vào hôm nay thay vì ngày bán, sai lệch mà không có cảnh báo.
4. Buổi demo thiếu màn "nhìn thấy tiền"; hiện chỉ có bảng giao dịch và SQL.

**Mục đích:** thêm đường đọc doanh thu **qua API** (tái dùng cho sản phẩm sau này) và một tab trình diễn trong bảng điều khiển, đồng thời xử lý đúng ngữ nghĩa thời gian phát sinh.

**Lý do chọn API-backed:** nếu đọc thẳng SQL như tab "Job", nó là công cụ dùng một lần, không kiểm chứng được RBAC. API-backed biến phần khó (truy vấn + phân quyền + ngữ nghĩa thời gian) thành tài sản của sản phẩm; UI chỉ là vỏ.

---

## 2. Cách chia việc: 3 PR

| PR | Nhánh | Nội dung | Hạn merge | Rủi ro |
|---|---|---|---|---|
| **D1** | `feat/PB-49-occurred-at` | `openapi.yaml` (commit riêng trước code), migration 004, model, ghi `occurred_at`, `classify_time`, cấu hình ngưỡng, history generator, test | **24/11** | **Cao** — đụng luồng ghi POS |
| **D2** | `feat/PB-49-dashboard-api` | Repository, service, schema, 4 endpoint, `test_auth_matrix`, `test_dashboard.py` | 25/11 | Thấp — chỉ đọc, chỉ thêm route |
| **D3** | `feat/PB-49-console-revenue-tab` | Tab "Doanh thu", LiveCharts2, test .NET, README, runbook | **12:00 26/11** | Trung bình — code bảng điều khiển của Kiệt |

**Quy tắc cứng:**

- D1 trễ **24/11** → **hoãn cả D1 sang sau ngày nộp 3/12**, không làm vội cận demo.
- Phần nào không merge kịp **12:00 26/11** → **không đưa vào demo 27/11**.
- D2 và D3 không được làm chậm việc giai đoạn 7 của Quang (kiểm thử chéo phần Sang + tổng hợp số liệu, hạn 25/11).
- Kiệt xem trước thiết kế tab trước khi D3 mở PR (bảng điều khiển là code PB-42-6 của Kiệt).

---

## 3. Phạm vi — bản demo 27/11 và phần hoãn

### 3.1 Bắt buộc cho demo 27/11 (D1 + D2 + D3 tối thiểu)

- Migration 004 + ghi `occurred_at` + phân loại thời gian (D1).
- 4 endpoint đọc được (D2).
- Tab Doanh thu với: **biểu đồ đường theo ngày**, **KPI tổng**, **nhãn chất lượng thời gian**, dòng nguồn API, làm mới 30 s (D3).

> **Đã triển khai vượt phạm vi này (20/11):** tab hiện vẽ **đủ 3 biểu đồ** theo thiết kế
> `Dashboard_Survey_and_Plan.md` §6.5–6.7 — thêm biểu đồ **tròn theo danh mục** và biểu đồ
> **cột so sánh cửa hàng**. Hai endpoint đã nằm trong D2 nên chỉ thiếu phần UI. Hai dòng
> "hoãn" đầu tiên ở §3.2 vì thế **không còn đúng**.

### 3.2 Hoãn sang Sprint 4

| Hạng mục | Lý do |
|---|---|
| ~~Biểu đồ tròn theo danh mục (endpoint vẫn làm ở D2)~~ | **Đã làm ở D3.** Không cần cho kịch bản demo, nhưng thiết kế v6 yêu cầu và rẻ khi endpoint đã có |
| ~~Biểu đồ cột so sánh chi nhánh~~ | **Đã làm ở D3.** Lý do như trên |
| Multi-select tập cửa hàng so sánh | Phụ thuộc biểu đồ cột; nay cột đã có, chỉ còn phần chọn nhiều |
| Bảng SKU | v1 đã đề xuất cắt; chưa có thiết kế |

**Lưu ý:** D2 vẫn làm **đủ 4 endpoint** (kể cả `revenue-by-category` và `revenue-by-store`) vì chúng rẻ khi đã có repository, và để Sprint 4 chỉ cần làm UI. Chỉ **UI** bị cắt.

### 3.3 Ngoài phạm vi (cố định)

- Không đổi `security.py`, không thêm/bớt role, không đổi route hiện có.
- Không sửa migration 001–003, không có migration 005, không down migration.
- Không đổi `payload_hash` hay hợp đồng POS.
- Không làm SSE/WebSocket.
- Không làm UI cho Manager/Auditor.
- Không thêm đăng nhập cho bảng điều khiển.
- Không mở doanh thu chi tiết cho HQ.
- Không tạo tài liệu DS-10 mới (ghi vào DS-04/DS-05).

---

## 4. Ngân sách thời gian và tính khả thi

| Mục | Số |
|---|---|
| Thời gian Quang còn tới 26/11 | ~7 ngày × 4 giờ = **28 giờ** |
| Trừ kiểm thử chéo phần Sang + tổng hợp số liệu (giai đoạn 7) | ~6–8 giờ |
| Còn cho PB-49 | **~20–22 giờ** |
| Ước lượng v1 cho toàn bộ | 11,5–14,5 người-ngày (**46–58 giờ**) |

**Kết luận: không thể làm đủ v1 trong 28 giờ.** Vì vậy việc cắt ở §3.2 là **bắt buộc**, không phải tuỳ chọn.

Phân bổ mục tiêu:

| PR | Ước lượng | Ghi chú |
|---|---|---|
| D1 | 10–12 giờ | Nhiều rủi ro nhất, phải xong sớm để có thời gian sửa |
| D2 | 8–9 giờ | Chỉ đọc, làm sau khi D1 merge |
| D3 | 6–8 giờ (bản tối thiểu) | Đường + KPI + nhãn chất lượng |
| **Cộng** | **24–29 giờ** | Sát ngưỡng — nếu trượt, cắt D3 xuống mức tối thiểu hơn nữa, không cắt D1/D2 |

Lịch đề xuất:

| Ngày | Việc |
|---|---|
| 19–20/11 | D1: contract + migration + model + ghi `occurred_at` |
| 21/11 | D1: `classify_time` + config + history generator + test |
| 22/11 | D1: chạy 3 lần `test_concurrent_traffic`, mở PR, nhờ review |
| 23/11 | D1 sửa theo review + merge (chốt an toàn trước hạn 24/11) |
| 24/11 | D2: repository + service |
| 25/11 | D2: 4 endpoint + `test_auth_matrix` + merge; **đồng thời** hoàn tất kiểm thử chéo giai đoạn 7 |
| 26/11 | D3 trước 12:00; diễn tập trên 3 máy |

---

## 5. Thay đổi DB

### 5.1 Migration 004 — SQL đã sửa lỗi batch

File: `database/migrations/004_pos_transaction_occurred_at.sql`

```sql
-- PB-49: the time the sale happened, as the POS declared it.
-- Old rows keep NULL; effective_at falls back to received time.
SET XACT_ABORT ON;
BEGIN TRANSACTION;

ALTER TABLE dbo.pos_transaction ADD occurred_at datetime2 NULL;
GO

ALTER TABLE dbo.pos_transaction ADD effective_at AS (COALESCE(occurred_at, created_at)) PERSISTED;
GO

CREATE NONCLUSTERED INDEX ix_pos_transaction_effective_at ON dbo.pos_transaction(effective_at);
GO

COMMIT;
```

**Vì sao phải có `GO` (lỗi review chỉ ra ở v1):** SQL Server biên dịch **cả batch** trước khi chạy. Câu thêm `effective_at` tham chiếu `occurred_at` vừa thêm trong cùng batch → không phân giải được → migration lỗi. Tương tự, `CREATE INDEX` trên cột vừa thêm cũng phải ở batch riêng. `sqlcmd -i` (được `migrate.sh` dùng) hiểu `GO` là dấu phân batch, nên cách này chạy đúng; đây cũng là cách `004_store_address.sql` / `005_product_image.sql` bên store-web đang làm.

**Lưu ý về transaction qua `GO`:** các batch chia bằng `GO` nằm cùng một session của `sqlcmd`, nên `BEGIN TRANSACTION` … `COMMIT` vẫn bao trùm toàn bộ file. Nếu một batch lỗi, `SET XACT_ABORT ON` huỷ transaction.

| Thành phần | Lý do |
|---|---|
| `occurred_at NULL` | Không bịa giờ bán cho dữ liệu cũ; nullable để 11 chỗ tạo `PosTransaction` trong test không vỡ |
| `effective_at` computed persisted | Một cột duy nhất để lọc/nhóm/index; persisted để index được |
| Index | Truy vấn khoảng thời gian |
| Không backfill | Ghi đè `occurred_at` bằng `created_at` là làm sai dữ liệu có chủ đích |
| Không thêm cột chất lượng | Suy ra từ 2 mốc + ngưỡng, tránh hai nguồn sự thật |

### 5.2 Trùng số migration với nhánh store-web — bắt buộc ghi trong PR D1

Đã kiểm chứng `origin/Quang` có:

```
database/migrations/004_store_address.sql     ← store-web
database/migrations/005_product_image.sql     ← store-web
```

**Quyết định (theo review):** Dashboard giữ số **004** vì lên `main` trước. Khi store-web được merge sau, phải đổi thành **005** và **006**.

Việc phải làm trong PR D1:

- Ghi rõ trong mô tả PR: "004 thuộc về Dashboard; nhánh `origin/Quang` phải đổi `004_store_address.sql` → `005_…`, `005_product_image.sql` → `006_…` khi rebase".
- `migrate.sh` chạy theo **thứ tự tên file**, nên hai migration cùng số ở hai nhánh sẽ va nhau nếu cả hai cùng tồn tại — phải đổi số **trước** khi merge nhánh kia.

### 5.3 Ảnh hưởng model ORM

`middleware/app/domain/models.py`, `PosTransaction`:

- Thêm `occurred_at: Mapped[datetime | None]`.
- Map **cả** `effective_at` bằng `Computed("(COALESCE(occurred_at, created_at))", persisted=True)`.
- Lý do: `tests/test_database.py::test_model_matches_real_table` (:43-47) so **tập cột chính xác** giữa model và bảng. Không map computed → test đỏ. Map computed như cột thường → mọi INSERT lỗi *"cannot insert into computed column"*.
- Kiểm tra `is_nullable` thực tế của cột computed trong `sys.columns` để khai báo cho khớp.

### 5.4 Ghi `occurred_at`

| Nơi | Thay đổi |
|---|---|
| `repositories/idempotency.py::insert_transaction` | Thêm tham số `occurred_at` |
| `services/idempotency.py::claim_transaction` | Nhận + truyền xuống, **có default `None`** (2 chỗ gọi positional ở `test_idempotency.py:52`, `:115`) |
| `services/pos_events.py`, `pos_return.py`, `pos_cancellation.py` | Truyền `event.timestamp` đã UTC-hoá |
| `tools/history-generator/.../loader.py` | Ghi `occurred_at` = `created_at` của giao dịch `HIST-` |

### 5.5 Dữ liệu cũ và reset demo

- Migration viết lại `pos_transaction` ở **cả** `RTS_DB` và `RTS_DB_DEMO` (computed persisted).
- Dòng cũ có `occurred_at` NULL → hiện nhãn `UNKNOWN`.
- `scripts/demo/reset_demo_db.ps1` **đã** chạy lại history generator mỗi lần reset (bước "Loading 90 days of sales history", seed 42) → sau D1 chỉ cần **reset demo một lần**, không phải sửa script.

---

## 6. Thay đổi API

### 6.1 Bốn endpoint

| Endpoint | Query | Quyền |
|---|---|---|
| `GET /dashboard/stores` | — | Admin/Auditor: mọi cửa hàng; Manager: cửa hàng của mình |
| `GET /dashboard/revenue` | `store_id?`, `from`, `to`, `bucket`, `include_suspect?` | như trên, trong phạm vi |
| `GET /dashboard/revenue-by-category` | `store_id?`, `from`, `to`, `include_suspect?` | như trên |
| `GET /dashboard/revenue-by-store` | `compare_store_ids[]?`, `from`, `to`, `include_suspect?` | Admin/Auditor: mọi; Manager: tập con |

- `compare_store_ids` dùng **query lặp** `?compare_store_ids=DN1&compare_store_ids=HN1`.
- `bucket ∈ {hour, day, week}`; `from`/`to` ISO 8601; khoảng nửa mở `[from, to)`.
- `422 INVALID_STORE` khi mã cửa hàng không tồn tại; `422 VALIDATION_ERROR` khi `from >= to`, `bucket` lạ, khoảng > 366 ngày.

### 6.2 Hợp đồng phản hồi (đã chốt)

```jsonc
// GET /dashboard/stores
{ "stores": [ { "store_id": "STORE-DN1", "name": "Cửa hàng Hải Châu",
                "region_id": "DN", "is_active": true } ] }

// GET /dashboard/revenue
{
  "scope": { "store_id": null },
  "range": { "from": "2026-11-01T17:00:00Z", "to": "2026-11-30T17:00:00Z",
             "bucket": "day", "timezone": "Asia/Bangkok" },
  "points": [ { "bucket_start": "2026-11-01T17:00:00Z",
                "net_revenue": 1234000.00, "txn_count": 12 } ],
  "total":  { "net_revenue": 12345678.00, "txn_count": 1234 },
  "quality": { "on_time": 1200, "backfill": 20, "suspect_future": 0,
               "suspect_old": 2, "unknown": 0, "excluded": 0 },
  "time_policy": { "max_future_skew_seconds": 300, "max_backfill_days": 30 },
  "has_data": true,
  "data_from": "2026-08-15T17:00:00Z",
  "data_to": "2026-11-18T17:00:00Z"
}

// GET /dashboard/revenue-by-category
{
  "scope": { "store_id": null },
  "parts": [ { "category": "Dairy", "net_revenue": 5000000.00,
               "share": 0.452, "txn_count": 400 } ],
  "negative": [ { "category": "Bakery", "net_revenue": -12000.00 } ],
  "total": { "net_revenue": 12345678.00, "txn_count": 1234 },
  "quality": { "...": "như trên" },
  "has_data": true
}

// GET /dashboard/revenue-by-store
{
  "scope": { "compare_store_ids": ["STORE-DN1", "STORE-DN2"] },
  "columns": [ { "store_id": "STORE-DN1", "name": "Cửa hàng Hải Châu",
                 "net_revenue": 8000000.00, "txn_count": 700 } ],
  "quality": { "...": "như trên" },
  "has_data": true
}
```

Quy ước:

- Mọi timestamp trả về **UTC `Z`**; console đổi +07:00 khi hiển thị.
- `share` là phân số 0–1; UI định dạng `45,2%`.
- `quality` **luôn** trả về, kể cả `include_suspect=false`; khi đó `excluded` = số giao dịch bị loại.
- Cột cửa hàng "đang xem" do console đánh dấu, API không biết.

### 6.3 Tầng code

| File (mới) | Trách nhiệm |
|---|---|
| `middleware/app/repositories/dashboard.py` | 4 truy vấn; cast tham số varchar đúng kiểu (PB-10-5); `COUNT(DISTINCT txn_id)` |
| `middleware/app/services/dashboard.py` | `resolve_scope`, `resolve_compare`, validate query, zero-fill, gọi `classify_time` |
| `middleware/app/services/time_quality.py` | `classify_time(...)` hàm thuần, không import SQLAlchemy |
| `middleware/app/api/schemas/dashboard.py` | Pydantic response, `Decimal → number` 2 chữ số |
| `middleware/app/api/dashboard.py` | 4 route, `require_role("Admin","Auditor","Manager")` |
| `middleware/app/core/config.py` | `POS_MAX_FUTURE_SKEW_SECONDS=300`, `POS_MAX_BACKFILL_DAYS=30` |
| `middleware/app/main.py` | Đăng ký router |

### 6.4 Ngữ nghĩa thời gian — bổ sung theo review

**Quy tắc UTC hoá (bắt buộc trước khi ghi):**

- `timestamp` có offset (ví dụ `2026-11-14T10:15:00+07:00`) → **đổi về UTC** rồi bỏ tzinfo trước khi ghi, vì `datetime2` không lưu múi giờ.
- `timestamp` không có offset → hiểu là **UTC** (không phải UTC+7).
- Lưu **naive UTC** vào `occurred_at`; đọc ra luôn gắn `Z`.

**Timestamp vô lý (bổ sung mới):**

- Năm 1900, năm 9999, hoặc lệch tới mức phi thực tế → **vẫn lưu**, gắn nhãn `SUSPECT_FUTURE`/`SUSPECT_OLD`.
- **Tuyệt đối không** trả 503 hay chặn giao dịch (NFR02: không mất giao dịch).
- Chỉ `NaN`/không parse được mới 422 `INVALID_EVENT` như hiện tại.
- **Phải có test biên**: năm 1900, năm 9999, offset +07:00, không offset, đúng biên ±5 phút, đúng biên 30 ngày.

| Nhãn | Điều kiện so với `created_at` |
|---|---|
| `ON_TIME` | `-5 phút ≤ occurred − received ≤ +5 phút` |
| `BACKFILL` | trước > 5 phút và ≤ 30 ngày |
| `SUSPECT_FUTURE` | `occurred > received + 5 phút` |
| `SUSPECT_OLD` | trước > 30 ngày |
| `UNKNOWN` | `occurred_at IS NULL` (dữ liệu trước migration 004) |

---

## 7. Thay đổi bảng điều khiển demo

### 7.1 File

| File | Loại | Nội dung |
|---|---|---|
| `DemoConsole/UI/DashboardTab.cs` | mới | Hàng lọc, KPI, khung biểu đồ đường, dòng nguồn |
| `DemoConsole/UI/MainForm.cs` | sửa | Tab thứ 5, `Guard`, timer 30 s riêng, handler đổi bộ lọc |
| `DemoConsole/Services/DemoApiClient.cs` | sửa | 4 method, token `admin` |
| `DemoConsole/Services/ApiParsers.cs` | sửa | Parse response; tiền number, thời gian UTC |
| `DemoConsole/Models/ApiModels.cs` | sửa | Record response |
| `DemoConsole/Configuration/ConsoleConfig.cs`, `appsettings.json` | sửa | `DashboardRefreshSeconds: 30`; nhãn danh mục |
| `DemoConsole/DemoConsole.csproj` | sửa | `LiveChartsCore.SkiaSharpView.WinForms 2.0.5` |
| `DemoConsole.Tests/DashboardTests.cs` | mới | Parser, dựng query, map nhãn |
| `clients/demo-console/README.md` | sửa | Dòng tab Doanh thu |

### 7.2 Phạm vi D3 (bản demo 27/11)

- Biểu đồ **đường theo ngày**, KPI tổng (doanh thu, số giao dịch), **badge chất lượng thời gian**, dòng "Nguồn: `<MiddlewareBaseUrl>`".
- Bộ lọc: phạm vi xem (toàn hệ thống / một cửa hàng), mốc (Ngày/Tuần/Tháng/Quý), nút Làm mới.
- **Không** làm tròn, cột, multi-select so sánh (Sprint 4).

### 7.3 Quyết định thiết kế

- **Timer riêng 30 s.** `RefreshAllAsync` hiện quét cả 4 tab mỗi 3 s; nhét Dashboard vào đó sẽ bắn request nặng mỗi 3 s. Không thêm vào mảng song song ở `MainForm.cs:330-333`.
- **Giữ pattern `Page(title, status, content)`**; `DashboardTab` trả content, `MainForm` tạo tab.
- **Giữ quy ước "nút mờ khi API trả 404"** đã có (`FeatureAvailability`), không tạo cơ chế mới.
- Chỉ Admin (token `admin`), không có bộ chọn vai trò.
- Không đọc SQL trong tab này — khác tab "Job"/"Đồng bộ" có chủ đích.

### 7.4 LiveCharts2 — chuẩn bị cho demo không Internet

- LiveCharts2 cần **Internet khi restore NuGet**, và kéo theo thư viện **native SkiaSharp**.
- **Phải `dotnet build` sẵn** trên máy S trước buổi demo; kiểm tra thư mục `bin/` có đủ native `.dll` của SkiaSharp.
- Kiểm tra **font tiếng Việt có dấu** và **DPI PerMonitorV2** (P0 của v1) trên máy trình chiếu thật.
- Thất bại → **OxyPlot (GDI+)**, không hoãn demo.

---

## 8. Kiểm thử

### 8.1 Test hiện có sẽ đỏ — biết trước

| Test | Nguyên nhân | Cách xử lý |
|---|---|---|
| `test_database.py::test_model_matches_real_table` (:43-47) | So tập cột chính xác | Map đủ 2 cột bằng `Computed` (không sửa test) |
| `test_auth_matrix.py::test_matrix_allows_exactly_the_ds04_roles` (:313) | Duyệt `app.routes` | Thêm 4 route × 7 cột vào `MATRIX` |
| `test_auth_matrix.py::test_matrix_covers_every_protected_route` (:339) | Bắt route thiếu `require_role` | Mọi route dashboard phải có `require_role` |
| `test_idempotency.py` (:52, :115) | Gọi positional 7 tham số | Tham số `occurred_at` có default |

**Điều kiện merge D1 (theo review):**

- Chạy `tests/test_concurrent_traffic.py` **3 lần** để chắc luồng đồng thời không đổi.
- Chạy `test_database.py`, `test_auth_matrix.py`, `test_idempotency.py`.
- Chạy full suite middleware trên `RTS_DB_TEST`.
- Chạy `dotnet test clients/demo-console/DemoConsole.sln` (D3).

Lưu ý môi trường: `tests/conftest.py` **không tạo schema** → migration 004 phải áp lên `RTS_DB_TEST` trước.

### 8.2 Test mới

| Nhóm | Nội dung |
|---|---|
| Thời gian | 4 nhãn + `UNKNOWN` đúng biên; naive = UTC; offset +07:00 → UTC; năm 1900/9999 vẫn lưu + SUSPECT; DUPLICATE giữ bản đầu |
| Phân quyền | 401; 403 HQ/Staff/POS; Manager ngoài phạm vi → 403; compare vượt quyền → 403; mã lạ → 422 |
| Số liệu | Tổng hệ thống = tổng các cửa hàng; huỷ + trả triệt tiêu; zero-fill; `COUNT(DISTINCT txn_id)` |
| Hợp đồng | `[from,to)`; tiền là number; `from >= to` → 422; `include_suspect=false` loại tiền nhưng giữ `quality` |
| Đối chiếu DS-05 | `Σ batch` = `Σ Dashboard` khi cùng `from/to` |

### 8.3 Test case chính thức — mã `DSH49-n`

- PB-49 **chưa có** test case trong `GROUP_08_Test case.xlsx`.
- Cần **sheet mới** `PB-49 Revenue Dashboard`, mã dạng **`DSH49-1`, `DSH49-2`, …** để tên test và báo cáo khớp nhau như các backlog khác.
- Kiệt tạo sheet hoặc giao Quang tạo — **phải chốt trước khi viết test** để mã không lệch.
- DS-09 cũng cần thêm dòng PB-49 vào bảng phạm vi (mục 2 hoặc 3).

---

## 9. Tài liệu cần sửa

### 9.1 Trong repo (theo PR)

| Tài liệu | PR | Nội dung |
|---|---|---|
| `docs/design/openapi.yaml` (DS-04) | **D1, commit đầu** | 4 path + schema; `timestamp` không kèm múi giờ hiểu là UTC và được lưu vào `occurred_at`; sửa mô tả `/audit-logs` đang ghi "inclusive" (code dùng `[from, to)`); ghi ngoại lệ `is_active = 0` |
| `docs/design/DS-05_Sync_Consistency_Design.md` | D1 | Dashboard dùng `effective_at`, batch dùng `created_at`; chỉ đối chiếu tổng cả kỳ |
| `docs/design/DS-09_Test_Strategy_and_Simulator.md` | D2 | Thêm dòng PB-49 vào bảng phạm vi |
| `docs/plans/Dashboard_*.md` (3 file) | D1 | **Commit** sau khi sửa; hiện đang **untracked** |
| `docs/plans/Sprint_3_Plan.md` | D1 hoặc nhánh docs của Kiệt | Thêm PB-49, người làm, hạn |
| `clients/demo-console/README.md` | D3 | Tab Doanh thu, nguồn API |
| `docs/demo/Sprint_3_Demo.md` | D3 | Bước demo màn doanh thu; ghi rõ số liệu 90 ngày là lịch sử mô phỏng |
| `docs/Deployment_Guide.md` | **sau D1, Khánh** | Migration 004, reset demo sau nâng cấp. File chưa có trên `main` — đang ở PR #61 |

### 9.2 Sửa lỗi trong chính các file kế hoạch (trước khi commit ở D1)

| File | Lỗi cần sửa |
|---|---|
| `Dashboard_Survey_and_Plan.md` (v6) | §5.2: "net_revenue của một `txn_id` đã huỷ = 0" **sai** — CANCELLATION copy item sang `txn_id` mới, tổng **theo cặp** mới bằng 0. §3: "11 router" → nay 13. §8.2/§11: `test_auth_matrix.py:288/:310` → nay `:313/:339`. §9.5: 3 điểm "còn mở" đã chốt ở nơi khác |
| `Dashboard_Backend_Tasks.md` | Đồng bộ mã PB-49, tách D1/D2/D3, bỏ mô tả `docs/document/…` |
| `Dashboard_Implementation_Plan.md` | File này (v2) |

**Về đường dẫn tài liệu baseline:** không ghi đường dẫn tuyệt đối hay tên thư mục chưa kiểm chứng. Trên máy này thư mục là `docs/document/` và **untracked**; review của Kiệt gọi tên khác trên bản sao của Kiệt. Cách an toàn: viết **"tài liệu baseline giữ ngoài git"** và liệt kê tên tài liệu, không kèm đường dẫn.

### 9.3 Ngoài repo (Kiệt hoặc người viết báo cáo)

| Tài liệu | Nội dung |
|---|---|
| Google Sheet — Product Backlog | PB-49 (Could), câu chuyện người dùng, tiêu chí chấp nhận |
| Google Sheet — Sprint 3 Backlog | Dòng D1–D3, người làm Quang |
| Google Sheet — Sprint 4 Backlog | Phần hoãn ở §3.2 |
| Google Sheet — SRS Alignment Log | Ghi việc bổ sung SRS |
| SRS v1.3 | Sửa câu "dashboard (PB-36) is Could and unscheduled"; thêm PB-49; mô tả Manager/Auditor xem doanh thu; thêm yêu cầu chức năng; mục giao diện ghi rõ tab demo không phải giao diện sản phẩm |
| Database Design v1.3 | Bảng 10 `pos_transaction`: thêm `occurred_at`, `effective_at` (computed persisted), index |
| Architecture Design | Một câu: Dashboard API trong middleware + tab doanh thu trong bảng điều khiển demo |
| Test Plan | Phạm vi kiểm thử có PB-49 |
| `GROUP_08_Test case.xlsx` | Sheet mới `PB-49 Revenue Dashboard`, mã `DSH49-n` |

---

## 10. Ràng buộc với các PR đang mở

| PR / nhánh | Ảnh hưởng | Xử lý |
|---|---|---|
| **#61** (Deployment Guide + Simulation Scenarios, Khánh) | `README.md` và `docs/demo/Sprint_3_Demo.md` có thể đụng D3 | D3 rebase sau khi #61 merge; nếu chưa, sửa file ở nhánh riêng và giải quyết conflict khi merge |
| **#61** — `docs/Deployment_Guide.md` | Cần thêm mục migration 004 | Sau D1, Khánh bổ sung (không làm trong D1 để tránh conflict) |
| **#60** (PB-39 hiệu năng, Sang) | Cột computed + index mới có thể làm số đo cũ không còn đại diện | Sau D1 **đo lại POS** và ghi rõ commit đã đo; nếu #60 merge sau D1 thì báo Sang |
| **#59** (PB-25 recommendations) | `test_auth_matrix.py` cũng bị sửa | D2 rebase; chú ý số dòng `MATRIX` — đã trôi từ `:288/:310` lên `:313/:339` |
| **`origin/Quang`** (store-web) | Trùng số migration 004/005 | §5.2 |
| **`origin/Khanh`**, **`PB-45-6-lan`** | Không đụng file của PB-49 | Không cần xử lý |

---

## 11. Rủi ro

| Rủi ro | Mức | Ứng phó |
|---|---|---|
| Migration 004 lỗi batch | **Cao** (đã xảy ra ở v1) | `GO` từng câu; chạy thử trên `RTS_DB_TEST` trước |
| Trùng số migration với store-web | **Cao** | Dashboard giữ 004; ghi yêu cầu đổi số trong PR D1 |
| Map `effective_at` thiếu `Computed` → INSERT POS lỗi | Cao | Test POS chạy ngay sau migrate; review model |
| `test_auth_matrix` đỏ vì route mới | Cao | Sửa cùng commit với `main.py` |
| D1 trễ 24/11 | Cao | Hoãn cả D1 sau 3/12; không làm vội |
| Không kịp 28 giờ | Cao | Cắt D3 xuống tối thiểu; P5 đã hoãn Sprint 4 |
| Timestamp vô lý gây 503 | Trung bình | Lưu + SUSPECT, không chặn; test biên 1900/9999 |
| Lệch số Dashboard vs sync DS-05 bị coi là lỗi | Trung bình | Ghi DS-05; chỉ đối chiếu tổng |
| `is_active=0` bị coi là mâu thuẫn | Trung bình | Ghi ngoại lệ trong `openapi.yaml` |
| LiveCharts2 lỗi font/DPI/native | Trung bình | P0 + build sẵn trước demo; fallback OxyPlot |
| Nhầm số liệu demo với thật | Trung bình | Tab hiện `MiddlewareBaseUrl`; runbook ghi rõ `HIST-` |
| Conflict với #61 | Thấp | Rebase D3 sau #61 |

---

## 12. Điểm đã chốt (không còn mở)

| # | Nội dung | Chốt |
|---|---|---|
| 1 | API role matrix | Giữ Admin/Auditor/Manager; UI chỉ Admin |
| 2 | Doanh thu giao dịch bị huỷ ghi ngày nào | **Ngày huỷ** — khớp DS-05 (một đơn huỷ có thể nằm ở batch sau đơn bán) |
| 3 | `occurred_at IS NULL` | Nhãn **`UNKNOWN`** riêng, không gộp vào 4 nhãn kia |
| 4 | Tài liệu thiết kế | **Không** tạo DS-10; ghi vào DS-04/DS-05 |
| 5 | Cửa hàng `is_active = 0` | Có trong danh sách, nhãn "đã đóng", ghi ngoại lệ vào `openapi.yaml` |
| 6 | F3 bảng SKU | **Cắt** khỏi v1 |
| 7 | M0 thất bại LiveCharts2 | Chuyển OxyPlot ngay, không hoãn demo |

**Còn cần Kiệt/Quang chốt (chưa có trong review):**

- Ai tạo sheet `PB-49 Revenue Dashboard` trong `GROUP_08_Test case.xlsx` (Kiệt tạo hay giao Quang)?
- Số giờ thực tế của giai đoạn 7 mà Quang phải giữ (review ghi Sprint 3 là 372 giờ/166%, kế hoạch Sprint 3 trong repo ghi 213,5 giờ/95%) — cần một con số thống nhất để biết chính xác ngân sách còn lại cho PB-49.

---

## 13. Định nghĩa hoàn thành

**D1 (24/11):**

- [ ] Migration 004 chạy sạch trên `RTS_DB_TEST` và `RTS_DB_DEMO`; `schema_migration` ghi nhận; không mất dòng.
- [ ] `openapi.yaml` commit **trước** code, trong cùng PR.
- [ ] `occurred_at` được ghi cho SALE/RETURN/CANCELLATION, đã UTC-hoá; DUPLICATE giữ bản đầu.
- [ ] Timestamp vô lý vẫn lưu + SUSPECT, không 503; có test biên năm 1900/9999.
- [ ] `test_concurrent_traffic.py` chạy 3 lần, xanh.
- [ ] PR ghi rõ yêu cầu đổi số migration của `origin/Quang`.
- [ ] Các file kế hoạch đã commit và hết mâu thuẫn.

**D2 (25/11):**

- [ ] 4 endpoint trả đúng hợp đồng; RBAC đúng; `test_auth_matrix` xanh.
- [ ] Toàn bộ test middleware xanh trên `RTS_DB_TEST`.
- [ ] DS-09 có dòng PB-49.

**D3 (12:00 26/11):**

- [ ] Tab Doanh thu: đường theo ngày + KPI + nhãn chất lượng + nguồn API, làm mới 30 s.
- [ ] Nút mờ khi 404 giữ đúng quy ước.
- [ ] Build sẵn offline, font tiếng Việt và DPI đã kiểm trên máy S.
- [ ] README console + runbook demo đã cập nhật.
- [ ] Test .NET xanh.

---

## 14. Phụ lục — Cây thư mục và điểm chạm

Chú thích: `+` mới · `~` sửa · `•` không đổi · `?` tuỳ quyết định · `[D1/D2/D3]` PR chứa thay đổi.

```text
RetailSync/
├── database/
│   ├── migrate.sh                                          •
│   ├── migrations/
│   │   ├── 001_core.sql                                    •
│   │   ├── 002_batches_alerts_forecast.sql                 •
│   │   ├── 003_recommendations.sql                         •
│   │   └── 004_pos_transaction_occurred_at.sql              +  [D1]  GO từng batch
│   └── seed/001..004_demo_*.sql                            •
│
├── middleware/
│   ├── app/
│   │   ├── main.py                                         ~  [D2] router
│   │   ├── core/config.py                                  ~  [D1] 2 ngưỡng
│   │   ├── domain/models.py                                ~  [D1] occurred_at + effective_at
│   │   ├── api/
│   │   │   ├── dashboard.py                                 +  [D2] 4 route
│   │   │   └── schemas/dashboard.py                         +  [D2]
│   │   ├── services/
│   │   │   ├── dashboard.py                                 +  [D2]
│   │   │   ├── time_quality.py                              +  [D1] hàm thuần
│   │   │   ├── idempotency.py                              ~  [D1] claim_transaction
│   │   │   ├── pos_events.py                               ~  [D1]
│   │   │   ├── pos_return.py                               ~  [D1]
│   │   │   └── pos_cancellation.py                         ~  [D1]
│   │   └── repositories/
│   │       ├── dashboard.py                                 +  [D2]
│   │       └── idempotency.py                              ~  [D1] insert_transaction
│   └── tests/
│       ├── test_dashboard.py                                +  [D2]
│       ├── test_time_quality.py                             +  [D1]
│       ├── test_auth_matrix.py                             ~  [D2]
│       ├── test_idempotency.py                             ~  [D1]
│       └── test_concurrent_traffic.py                       •  [D1] chạy 3 lần, không sửa
│
├── tools/
│   └── history-generator/history_generator/loader.py       ~  [D1] occurred_at cho HIST-
│
├── clients/
│   ├── demo-pos/                                           •  không đụng
│   └── demo-console/
│       ├── DemoConsole/DemoConsole.csproj                  ~  [D3] LiveCharts2
│       ├── DemoConsole/appsettings.json                    ~  [D3]
│       ├── DemoConsole/Configuration/ConsoleConfig.cs      ~  [D3]
│       ├── DemoConsole/Models/ApiModels.cs                 ~  [D3]
│       ├── DemoConsole/Services/ApiParsers.cs              ~  [D3]
│       ├── DemoConsole/Services/DemoApiClient.cs           ~  [D3]
│       ├── DemoConsole/UI/MainForm.cs                      ~  [D3] tab 5, timer 30 s
│       ├── DemoConsole/UI/DashboardTab.cs                   +  [D3]
│       ├── DemoConsole.Tests/DashboardTests.cs               +  [D3]
│       └── README.md                                       ~  [D3]
│
├── docs/
│   ├── design/
│   │   ├── openapi.yaml                                    ~  [D1] commit đầu
│   │   ├── DS-05_Sync_Consistency_Design.md                ~  [D1]
│   │   └── DS-09_Test_Strategy_and_Simulator.md            ~  [D2]
│   ├── demo/Sprint_3_Demo.md                               ~  [D3] cẩn thận #61
│   ├── Deployment_Guide.md                                 ?  sau D1, Khánh (#61)
│   └── plans/
│       ├── Dashboard_Survey_and_Plan.md                    ~  [D1] sửa §5.2, refs, §9.5
│       ├── Dashboard_Backend_Tasks.md                      ~  [D1]
│       ├── Dashboard_Data_Availability.md                  ~  [D1] commit
│       ├── Dashboard_Implementation_Plan.md                ~  [D1] file này
│       └── Sprint_3_Plan.md                                ~  [D1] hoặc nhánh Kiệt
│
├── README.md                                               ?  cẩn thận #61
└── hq-demo/, deploy/                                       •  không đụng
```

**Tổng hợp:** D1 = 1 file mới + 11 sửa; D2 = 4 mới + 3 sửa; D3 = 3 mới + 7 sửa.

**Không đụng:** `security.py`, migration 001–003, `database/seed/*`, `clients/demo-pos/`, `hq-demo/`, `deploy/`, hợp đồng POS (`payload_hash`, `POST /pos/events`), `tests/test_concurrent_traffic.py` (chỉ chạy).
