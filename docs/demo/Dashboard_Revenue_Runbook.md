# Runbook — Dashboard doanh thu (backend)

Áp dụng cho: `docs/design/openapi.yaml` (`/dashboard/*`) và migration
`database/migrations/004_pos_transaction_occurred_at.sql`.
Kế hoạch gốc: `docs/plans/Dashboard_Backend_Tasks.md`.

---

## 1. Chạy migration 004

004 thêm vào `pos_transaction`:

| Cột | Kiểu | Nghĩa |
|---|---|---|
| `occurred_at` | `datetime2 NULL` | Thời điểm POS khai báo giao dịch đã xảy ra. `NULL` với dữ liệu cũ. |
| `effective_at` | `datetime2` computed `PERSISTED`, `COALESCE(occurred_at, created_at)` | Mốc Dashboard dùng để lọc và nhóm. |

Kèm index `ix_pos_transaction_effective_at` trên `effective_at`.

**Không backfill.** Dòng cũ giữ `occurred_at = NULL`, nên `effective_at` lùi về
`created_at` (giờ Middleware nhận) và Dashboard đếm chúng vào nhóm `unknown`.

**Forward-only.** Không sửa 001–003, không có migration down.

### 1.1 Trên môi trường compose

```powershell
docker compose up -d --wait sqlserver
docker compose run --rm migrate
```

Runner áp từng file `database/migrations/*.sql` đúng một lần theo thứ tự tên và ghi
tên file vào `dbo.schema_migration`, nên 004 chỉ chạy khi chưa có bản ghi
`004_pos_transaction_occurred_at.sql`.

### 1.2 CSDL test

`RTS_DB_TEST` cần 004 trước khi chạy test tích hợp Dashboard:

```powershell
$previousDbName = $env:DB_NAME
try {
    $env:DB_NAME = 'RTS_DB_TEST'
    docker compose run --rm migrate
    if ($LASTEXITCODE -ne 0) { throw 'Test database migration failed' }
} finally {
    if ($null -eq $previousDbName) { Remove-Item Env:DB_NAME -ErrorAction SilentlyContinue }
    else { $env:DB_NAME = $previousDbName }
}
```

### 1.3 CSDL demo

`RTS_DB_DEMO` cũng cần 004, nếu không mọi biểu đồ sẽ lỗi vì thiếu `effective_at`:

```powershell
$env:DB_NAME = 'RTS_DB_DEMO'; docker compose run --rm migrate; Remove-Item Env:DB_NAME
```

### 1.4 Kiểm tra sau khi áp

```powershell
docker compose exec sqlserver bash -c '/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -C -b -d RTS_DB_TEST -Q "SET NOCOUNT ON; SELECT version FROM dbo.schema_migration ORDER BY version; SELECT name, is_computed, is_persisted FROM sys.columns WHERE object_id = OBJECT_ID(N''dbo.pos_transaction'') AND name IN (''occurred_at'',''effective_at'');"'
```

Mong đợi: có bản ghi `004_pos_transaction_occurred_at.sql`; `effective_at` có
`is_computed = 1` và `is_persisted = 1`; `occurred_at` không computed.

> **Lưu ý vận hành:** thêm cột computed `PERSISTED` sẽ viết lại bảng
> `pos_transaction`. Với DB demo (~2.400 dòng) việc này tức thời; với dữ liệu lớn
> nên chạy ngoài giờ.

---

## 2. Reset demo để lịch sử có `occurred_at`

Tool `tools/history-generator` đã ghi `occurred_at` khi sinh dòng `HIST-`, nên phải
sinh lại lịch sử **sau** khi áp 004. Compose không có service riêng cho tool này, nên
chạy nó trong image middleware (image đã có sẵn `sqlalchemy` và `pyodbc`):

```powershell
docker compose run --rm -e DB_HOST=sqlserver -e DB_NAME=RTS_DB_DEMO `
  --volume "${PWD}/tools/history-generator:/app" --workdir /app middleware `
  sh -c 'pip install -q -r requirements.txt && python -m history_generator --days 90 --seed 42'
```

Chạy trực tiếp bằng Python trên máy cũng được, miễn `DB_NAME=RTS_DB_DEMO` và đã cài
`middleware/requirements.txt`.

Lịch sử sinh ra là **dữ liệu mô phỏng**, không phải doanh thu thật. Mỗi dòng có
`occurred_at` bằng đúng thời điểm mô phỏng và `created_at` giữ nguyên giá trị cũ
(bằng `occurred_at`), nên Dashboard phân loại chúng là `ON_TIME` chứ không phải
`BACKFILL`, và hình dạng dữ liệu demo không đổi.

Kiểm tra nhanh sau khi reset:

```sql
SELECT COUNT(*)                                        AS total,
       SUM(CASE WHEN occurred_at IS NULL THEN 1 ELSE 0 END) AS without_occurred_at
FROM dbo.pos_transaction;
```

`without_occurred_at` phải là 0 với dữ liệu `HIST-` vừa sinh.

---

## 3. Đối chiếu Dashboard với đồng bộ HQ (DS-05)

**Dashboard và batch dùng hai mốc thời gian khác nhau — có chủ đích:**

| | Dashboard | Batch (DS-05) |
|---|---|---|
| Mốc xếp dữ liệu | `effective_at = COALESCE(occurred_at, created_at)` | Tập giao dịch chưa có `sync_batch_id` tại lúc job claim |
| Ý nghĩa | Ngày **phát sinh** doanh thu | Vận hành đồng bộ |
| `period_start`/`period_end` | không áp dụng | min/max `created_at` của các giao dịch được claim |
| Bucket | Ngày/giờ theo giờ nghiệp vụ (UTC+7) | Không gom theo thời gian |

**Chỉ đối chiếu tổng toàn kỳ.** Không so từng batch với từng ngày, và không so
`period_start/period_end` với bucket Dashboard.

Ví dụ dễ kiểm chứng: SALE lúc 10/10 20:00 nhưng POS gửi bù 12/10 09:00 → Dashboard
ghi doanh thu vào **10/10**; giao dịch vào batch ở chu kỳ aggregation kế tiếp và
`period_start/period_end` phản ánh giờ nhận 12/10.

Cách kiểm tra tổng:

1. Gọi `GET /api/v1/dashboard/revenue` với `from`/`to` phủ toàn kỳ, cộng
   `total_revenue` (hoặc đọc `total_revenue`).
2. Cộng `SUM(net_revenue)` của mọi `sales_summary_line` thuộc các batch đã ACK trong
   cùng kỳ (**theo `effective_at` của giao dịch**, không theo `period_start`).
3. Hai tổng phải bằng nhau khi **mọi** giao dịch trong kỳ đã được đưa vào batch.

Nếu còn giao dịch chưa đồng bộ (`sync_batch_id IS NULL`), chênh lệch đúng bằng phần
chưa gửi — đó là trạng thái vận hành bình thường, không phải lỗi số liệu.

Nếu cần khớp 100% với HQ, phải chọn một trong hai (đều là thay đổi hợp đồng, **ngoài
phạm vi hiện tại**): Dashboard xếp theo `created_at`, hoặc sync xếp theo
`effective_at`.

---

## 4. Điểm cần biết khi vận hành

### 4.1 `is_active = 0` vẫn xuất hiện ở `/dashboard/stores`

Đây là **ngoại lệ có chủ đích**: Admin cần xem doanh thu lịch sử của cửa hàng đã
đóng. Các API danh sách cửa hàng khác vẫn loại cửa hàng không active. Reviewer không
nên coi đây là mâu thuẫn.

### 4.2 Thời gian "cần kiểm tra"

Mỗi phản hồi biểu đồ kèm `quality` và `time_policy`:

| Nhãn | Điều kiện | Ngưỡng |
|---|---|---|
| `ON_TIME` | `-skew ≤ occurred − received ≤ +skew` | `POS_MAX_FUTURE_SKEW_SECONDS`, mặc định 300 |
| `BACKFILL` | cũ hơn `skew` nhưng không quá `POS_MAX_BACKFILL_DAYS` | mặc định 30 ngày |
| `SUSPECT_FUTURE` | `occurred > received + skew` | |
| `SUSPECT_OLD` | `occurred ≤ received − backfill` | |
| `unknown` | `occurred_at IS NULL` (dữ liệu cũ) | |

`include_suspect=false` loại `SUSPECT_*` khỏi **số tiền và điểm**, nhưng `quality`
vẫn đếm **toàn bộ khoảng** đã chọn. Vì vậy badge "đã loại N giao dịch cần kiểm tra"
có thể lớn hơn 0 trong khi tổng doanh thu chỉ còn phần sạch; hai con số này khác
nhau theo thiết kế.

Không chặn giao dịch vì lý do thời gian (NFR02: không mất giao dịch). `occurred_at`
không bao giờ bị ghi đè bằng giờ server; khi gửi lại (`DUPLICATE`), bản ghi đầu giữ
nguyên giá trị của nó.

### 4.3 Phân quyền

| Endpoint | Admin | Auditor | Manager | POS/Staff/HQ |
|---|---|---|---|---|
| `GET /dashboard/stores` | mọi cửa hàng | mọi cửa hàng | cửa hàng của mình | 403 |
| `GET /dashboard/revenue` | toàn hệ thống hoặc 1 cửa hàng | như Admin | chỉ cửa hàng của mình | 403 |
| `GET /dashboard/revenue-by-category` | như trên | như trên | chỉ cửa hàng của mình | 403 |
| `GET /dashboard/revenue-by-store` | so sánh mọi cửa hàng | như Admin | so sánh trong phạm vi được cấp | 403 |

Manager bỏ trống `store_id` sẽ nhận **chính cửa hàng của mình**, không phải toàn hệ
thống. Manager yêu cầu cửa hàng ngoài phạm vi → 403 (không tiết lộ cửa hàng có tồn
tại hay không); Admin/Auditor nêu mã cửa hàng không tồn tại → 422 `INVALID_STORE`.

### 4.4 Cú pháp tham số

- Khoảng thời gian nửa mở: `?from=2026-11-01T00:00:00Z&to=2026-12-01T00:00:00Z`.
  `from` được tính, `to` không.
- Tập so sánh lặp khóa, **không** dùng dấu phẩy:
  `?compare_store_ids=DN1&compare_store_ids=HN1`.
- `bucket` ∈ `hour`, `day`, `week`, `month`; mặc định `day`.
- Tiền là JSON number 2 chữ số thập phân, không phải chuỗi.

### 4.5 Dữ liệu demo không bị "đặc cách"

API không có nhánh xử lý riêng cho mã `HIST-`. Dữ liệu 90 ngày của `RTS_DB_DEMO` là
mô phỏng; tab Dashboard của console hiển thị nguồn Middleware đang trỏ tới. Khi trình
diễn, phải nói rõ biểu đồ 90 ngày là dữ liệu mô phỏng.

---

## 5. Chạy test

```powershell
cd middleware
python -m pytest -q
```

Test Dashboard cần `RTS_DB_TEST` đã áp 004; test thuần (phân loại thời gian, căn
bucket, zero-fill, serialize) không cần DB.
