# Dashboard doanh thu — dữ liệu cần, đã có, còn thiếu

- **Ngày:** 2026-11-19
- **Cơ sở:** source `main` @ `0bdea8d` (sau PR #58); đối chiếu thêm commit khảo sát gốc `986b3d3`. Đọc file trực tiếp, **không chạy ứng dụng, không chạy SQL**.
- **Phạm vi:** dữ liệu phục vụ Dashboard theo `docs/plans/Dashboard_Survey_and_Plan.md` (v6). Không sửa source, DB, migration hay dependency.
- **Trạng thái:** tài liệu phân tích, chưa triển khai.

---

## 1. Kết luận ngắn

Dữ liệu gốc cho Dashboard **gần như đã đủ**: bảng giao dịch, dòng hàng, sản phẩm, cửa hàng và phân quyền đều có sẵn, đủ để tính công thức doanh thu `Σ(SALE qty×price) − Σ(RETURN + CANCELLATION qty×price)`.

Thiếu đúng ba nhóm:

1. **Một cột thời gian**: `occurred_at` (thời điểm bán do POS khai báo) và cột computed `effective_at` + index — đây là migration 004, chưa làm.
2. **Tầng API**: không có endpoint doanh thu nào, không có repository/service tổng hợp.
3. **Phía hiển thị**: nhãn tiếng Việt cho danh mục, thư viện biểu đồ, tab Dashboard.

Điểm cần lưu ý: với **dữ liệu demo**, có thể vẽ Dashboard ngay bằng `created_at` mà không cần migration 004, vì history generator đã ghi `created_at` đúng giờ bán. Nhưng cách đó **sai ngay khi POS thật gửi bù** (offline backlog), nên chỉ dùng được cho mục đích trình diễn.

---

## 2. Bảng tổng hợp

| Nhu cầu dữ liệu | Nguồn | Trạng thái |
|---|---|---|
| Danh sách cửa hàng (bộ lọc, so sánh) | `store.store_id, name, region_id, is_active` | ✅ có |
| Phạm vi theo vai trò | `staff_user.role`, `staff_user.store_id` + claim token | ✅ có |
| Doanh thu (tiền) | `transaction_item.qty`, `unit_price` | ✅ có |
| Phân biệt bán / trả / huỷ | `pos_transaction.txn_type` (`SALE`/`RETURN`/`CANCELLATION`) | ✅ có |
| Trạng thái giao dịch | `pos_transaction.status` (`OK`/`CANCELLED`) | ✅ có (cố ý không lọc) |
| Liên kết trả/huỷ về giao dịch gốc | `pos_transaction.ref_txn_id` | ✅ có |
| Nhóm theo danh mục | `product.category` | ✅ có (free-text; nhãn VI làm ở client) |
| Chi nhánh | `store_id` có trên mọi giao dịch | ✅ có |
| **Thời điểm phát sinh doanh thu** | **`pos_transaction.occurred_at`** | ❌ **chưa có cột** |
| **Mốc lọc/nhóm dùng chung** | `effective_at = COALESCE(occurred_at, created_at)` | ❌ chưa có |
| **Index theo thời gian** | — | ❌ chưa; chỉ có index lọc `(store_id, created_at) WHERE sync_batch_id IS NULL` |
| Chất lượng thời gian (on-time/backfill/suspect) | 2 mốc `occurred_at` + `created_at` | ❌ chưa có mốc thứ nhất |
| Ngưỡng phân loại | `POS_MAX_FUTURE_SKEW_SECONDS`, `POS_MAX_BACKFILL_DAYS` | ❌ chưa có trong config |
| Đối chiếu với đồng bộ | `sync_batch.period_start/end/txn_count`, `sales_summary_line.sold_qty/returned_qty/net_revenue` | ✅ có (chỉ để kiểm tra) |
| API trả số liệu | `/dashboard/*` | ❌ 0 endpoint |

---

## 3. Dữ liệu cho từng thành phần UI

### 3.1 Bộ lọc và phạm vi

- Nguồn: `store` (`store_id`, `name`, `region_id`, `is_active`), `staff_user` (`role`, `store_id`).
- Đã đủ. Không cần bảng ánh xạ mới vì mỗi Manager gắn đúng một `store_id`.
- Lưu ý: `region_id` là chuỗi tự do, **không có bảng `region`** — nếu sau này cần lọc theo vùng phải thêm bảng.

### 3.2 KPI tổng và biểu đồ đường

- Nguồn: `pos_transaction` (mốc thời gian, `store_id`, `txn_type`) join `transaction_item` (`qty`, `unit_price`).
- Đã đủ **trừ mốc thời gian**: hiện chỉ có `created_at` (giờ nhận), không có `occurred_at` (giờ bán).
- Đếm số giao dịch phải là `COUNT(DISTINCT txn_id)` vì query join ở mức dòng hàng.

### 3.3 Biểu đồ tròn theo danh mục

- Nguồn: `transaction_item` join `product.category`.
- Đã đủ. `category` là `varchar(50) NOT NULL`, dữ liệu demo có đúng 3 giá trị: `Dairy`, `Bakery`, `Dry goods`.
- Chưa có: bảng nhãn tiếng Việt ở client (kế hoạch đặt trong `appsettings.json`, không đổi DB).

### 3.4 Biểu đồ cột so sánh chi nhánh

- Nguồn: `store` join doanh thu theo `store_id`.
- Đã đủ; tập so sánh chỉ là `store_id IN (...)` trên cùng khoảng thời gian.

### 3.5 Badge chất lượng thời gian

- Cần **hai** mốc: `occurred_at` và `created_at`, cộng ngưỡng cấu hình.
- Hiện chỉ có một mốc → **chưa làm được**. Đây là lý do chính phải có migration 004.

### 3.6 Trạng thái dữ liệu (rỗng, ngoài khoảng)

- `has_data`, `data_from`, `data_to` suy ra bằng `MIN/MAX(effective_at)` trên cùng bộ lọc; không cần cột mới, nhưng phụ thuộc `effective_at`.

---

## 4. Cái chưa có, theo mức độ chặn

### 4.1 Chặn về ngữ nghĩa — `occurred_at`

`pos_transaction` hiện chỉ có `created_at` = `SYSUTCDATETIME()` lúc Middleware nhận. Không có `occurred_at` thì:

- giao dịch POS gửi bù (offline) bị tính vào **ngày nhận**, không phải ngày bán;
- không phân loại được `ON_TIME` / `BACKFILL` / `SUSPECT_FUTURE` / `SUSPECT_OLD`;
- không có badge "N giao dịch có thời gian cần kiểm tra".

Đáng chú ý: `PosEvent.timestamp` **có khai báo trong schema nhưng không được dùng ở bất kỳ đâu** trong `app/` — timestamp của POS đang bị bỏ.

Cần: migration 004 (`occurred_at datetime2 NULL`, `effective_at` computed persisted, index nonclustered) + ghi `event.timestamp` ở 3 handler SALE/RETURN/CANCELLATION.

### 4.2 Chặn về truy vấn — API và repository

- 13 router hiện tại, **không có** `/dashboard/*`; contract `openapi.yaml` cũng không có.
- Chưa có `resolve_scope` / `resolve_compare`; chỉ có `require_own_store` cho inventory.
- Chưa có repository/service/schema nào cho doanh thu.

### 4.3 Chặn về hiển thị

- Nhãn tiếng Việt cho 3 danh mục (map ở client).
- Thư viện biểu đồ (LiveCharts2 chưa cài; `DemoConsole.csproj` chỉ có `Microsoft.Data.SqlClient`).
- Tab thứ 5 trong console (hiện 4 tab).
- Các cột "Giờ bán"/"Giờ nhận" ở tab giao dịch — chỉ có sau khi có `occurred_at`.

### 4.4 Không chặn triển khai

- Index `effective_at`: demo ~2.400 giao dịch (ước lượng trong kế hoạch) vẫn chạy được không index (chậm hơn khi dữ liệu lớn).
- `has_data` / `data_from` / `data_to`: suy ra khi query, không cần cột.
- Đối chiếu `sales_summary_line`: chỉ dùng cho test, không cần cho Dashboard.

---

## 5. Dữ liệu demo cụ thể

- **Cửa hàng:** 3 store, cùng region `DN` — Hải Châu (`STORE-DN1`), Thanh Khê (`STORE-DN2`), Sơn Trà (`STORE-DN3`). Mockup "Đà Nẵng / Hà Nội / HCM" trong kế hoạch là minh hoạ, **không khớp seed**.
- **Sản phẩm:** 9 SKU, 3 danh mục × 3 SKU.
- **Lịch sử:** 90 ngày `HIST-`, mỗi SKU **một giao dịch/ngày lúc 12:00 giờ VN** (05:00Z), 2,5% có RETURN lúc 13:00, **không có CANCELLATION**.
- Vì `created_at` của history đã là giờ bán, fallback `effective_at = created_at` cho biểu đồ trông vẫn đúng trên demo.
- Bucket "giờ" trên history sẽ dồn hết vào một điểm 12:00 mỗi ngày → gần như vô nghĩa với dữ liệu mô phỏng; nên mặc định Ngày cho chế độ Tháng/Quý.
- Seed không có CANCELLATION → test "huỷ triệt tiêu" phải tự tạo dữ liệu, không dựa vào seed.

---

## 6. Cần quyết định trước khi code

1. **Demo bằng `created_at` hay làm đúng `occurred_at`?**
   - `created_at`: không cần migration, làm được ngay, nhưng sai khi POS gửi bù; API sau này phải đổi hợp đồng.
   - `occurred_at`: đúng ngữ nghĩa, cần migration 004 + sửa 3 handler + test; tốn thêm 2,5–3,5 người-ngày.
2. **Doanh thu của một giao dịch bị huỷ nằm ở ngày nào?** Vì CANCELLATION là giao dịch riêng (copy item từ SALE gốc), bucket theo ngày sẽ cho +X ở ngày bán và −X ở ngày huỷ. Cần chốt đây là hành vi mong muốn hay phải gộp về ngày bán.
3. **Cửa hàng `is_active = 0`** có xuất hiện trong bộ lọc/so sánh không (kế hoạch đang mâu thuẫn giữa §7.2 và §9.5).

---

## 7. Tham chiếu

| Nội dung | Vị trí |
|---|---|
| Bảng `store` | `database/migrations/001_core.sql:5` |
| Bảng `product` | `database/migrations/001_core.sql:43` |
| Bảng `sync_batch` | `database/migrations/001_core.sql:59` |
| Bảng `pos_transaction` (không có `occurred_at`) | `database/migrations/001_core.sql:76` |
| Index lọc `(store_id, created_at)` | `database/migrations/001_core.sql:87` |
| Bảng `transaction_item` | `database/migrations/001_core.sql:90` |
| Bảng `sales_summary_line` | `database/migrations/002_batches_alerts_forecast.sql:17` |
| Model `PosTransaction` | `middleware/app/domain/models.py` |
| `PosEvent.timestamp` (khai báo, không dùng) | `middleware/app/api/schemas/pos.py:33` |
| History generator | `tools/history-generator/history_generator/loader.py` |
| Seed cửa hàng | `database/seed/001_demo_stores_pos.sql` |
| Seed sản phẩm | `database/seed/002_demo_catalog.sql` |
| Kế hoạch gốc | `docs/plans/Dashboard_Survey_and_Plan.md` |