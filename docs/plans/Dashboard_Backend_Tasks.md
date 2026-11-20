# Dashboard doanh thu — danh sách việc Backend

- **Ngày:** 2026-11-17
- **Cơ sở:** `docs/plans/Dashboard_Survey_and_Plan.md` (v6) — đọc file trực tiếp, **không chạy ứng dụng, không chạy SQL**.
- **Trạng thái:** lập kế hoạch. Chưa sửa source, chưa tạo migration, chưa chạy migration, chưa cài dependency, chưa đổi branch.
- **Phạm vi:** chỉ backend (`middleware/`, `database/`, `tools/`, `docs/design/`). UI console nằm ở tài liệu chính, không thuộc danh sách này.

## Thứ tự phụ thuộc bắt buộc

```
B1 (contract)  →  M1..M8 (migration + ghi occurred_at)  →  B2..B8 (API)  →  F3 (runbook/DS-04/DS-05)
```

Không viết `repositories/dashboard.py` trước khi migration 004 đã áp lên `RTS_DB_TEST`. Không sửa `main.py` trước khi có contract (B1).

---

## Giai đoạn M — Migration và ghi `occurred_at`

| # | Việc | File | Done khi |
|---|---|---|---|
| M1 | Viết migration 004: thêm `occurred_at datetime2 NULL`; cột computed `effective_at AS COALESCE(occurred_at, created_at) PERSISTED`; index nonclustered trên `effective_at`; không backfill, không sửa 001–003, không down migration | `database/migrations/004_pos_transaction_occurred_at.sql` (mới) | `database/migrate.sh` chạy sạch trên `RTS_DB_TEST` và `RTS_DB_DEMO`; `schema_migration` ghi nhận tên file; bảng cũ không mất dòng |
| M2 | Thêm `occurred_at` vào model `PosTransaction`; **không** map `effective_at` (cột computed do DB quản) | `middleware/app/domain/models.py:119-129` | Model map đủ cột; test import không lỗi |
| M3 | Nhận + ghi `occurred_at` (UTC, naive = UTC) từ POS | `middleware/app/repositories/idempotency.py:15-23` (`insert_transaction`), `middleware/app/services/idempotency.py:38-55` (`claim_transaction`) | `insert_transaction` có tham số `occurred_at`; `claim_transaction` truyền xuống; test idempotency xanh |
| M4 | Truyền `event.timestamp` qua 3 handler | `middleware/app/services/pos_events.py:64-72`, `services/pos_return.py:68`, `services/pos_cancellation.py:32` | SALE / RETURN / CANCELLATION đều ghi `occurred_at` đúng |
| M5 | Hàm phân loại thời gian (thuần, **không chạm DB**): `classify_time(occurred_at, created_at, policy) -> label` trả `ON_TIME` / `BACKFILL` / `SUSPECT_FUTURE` / `SUSPECT_OLD` | `middleware/app/services/time_quality.py` (mới) | Unit test 4 nhãn + đúng biên `-5 phút`, `+5 phút`, `30 ngày`; không import `sqlalchemy` |
| M6 | Thêm cấu hình ngưỡng: `POS_MAX_FUTURE_SKEW_SECONDS` (mặc định 300), `POS_MAX_BACKFILL_DAYS` (mặc định 30) | `middleware/app/core/config.py` | 2 field mới trong `Settings`; default đúng; đọc được từ `.env` |
| M7 | Tool lịch sử ghi `occurred_at` khi sinh `HIST-` | `tools/history-generator/history_generator/loader.py:37-72` | Chạy lại sinh lịch sử có `occurred_at`; dữ liệu demo không đổi hình dạng |
| M8 | Test: `occurred_at` NULL không vỡ; 11 điểm tạo `PosTransaction(...)` trong test vẫn xanh; DUPLICATE giữ `occurred_at` bản đầu | `middleware/tests/` | Toàn bộ test POS/idempotency xanh; có ít nhất 1 test cho DUPLICATE |

**Ước lượng M: 2,5 – 3,5 người-ngày.**

---

## Giai đoạn B — Hợp đồng và API

| # | Việc | File | Done khi |
|---|---|---|---|
| B1 | Khai báo 4 endpoint trong contract: query (`store_id?`, `from`, `to`, `bucket`, `include_suspect?`, `compare_store_ids[]?`), response (`quality`, `time_policy`, `scope`, `data_from/to`, `has_data`); ghi rõ quy ước **`[from, to)`**; tiền là JSON number | `docs/design/openapi.yaml` | File merge được; `x-roles: [Admin, Auditor, Manager]` cho cả 4; ghi chú "Dashboard half-open" |
| B2 | Repository: truy vấn doanh thu theo `effective_at ∈ [from, to)`; `store_id = @store` (charts 1-2) hoặc `store_id IN @compare` (chart 3); `quality` bằng `CASE` trên `occurred_at`/`created_at`; `GROUP BY` cho bucket / danh mục / cửa hàng; `CAST` tham số đúng kiểu cột | `middleware/app/repositories/dashboard.py` (mới) | 4 hàm repo trả đúng shape; không commit; tham số `varchar`/`nvarchar` cast đúng (PB-10-5) |
| B3 | Service: `resolve_scope(principal, store_id)`, `resolve_compare(principal, compare_store_ids)`, parse/validate `DashboardQuery`, zero-fill bucket, gọi `classify_time` | `middleware/app/services/dashboard.py` (mới) | Unit test scope/compare/thời gian; không DB; lỗi đúng mã (403 / 422) |
| B4 | Pydantic schemas cho response; `field_serializer` cho `Decimal` → JSON number 2 chữ số thập phân và `datetime` → ISO UTC | `middleware/app/api/schemas/dashboard.py` (mới) | Serialize đúng hợp đồng; không trả `Decimal` dạng chuỗi |
| B5 | API: 4 route; mọi route `Depends(require_role("Admin","Auditor","Manager"))`; charts 1-2 gọi `resolve_scope`; chart 3 gọi `resolve_compare`; `/dashboard/stores` chỉ lọc theo vai trò (không `resolve_scope`/`resolve_compare`) | `middleware/app/api/dashboard.py` (mới) | 401 không token; 403 HQ/Staff/POS; 422 `INVALID_STORE` / `VALIDATION_ERROR`; `/stores` Manager chỉ thấy cửa hàng của mình |
| B6 | Đăng ký router | `middleware/app/main.py:37-47` | `app.include_router(dashboard_router, prefix=API_PREFIX)` |
| B7 | **Cập nhật `test_auth_matrix.py`** — bắt buộc, cùng lúc với B6: thêm 4 route vào `MATRIX` (đủ 7 cột POS/Staff/Manager/HQ/Admin/Auditor/no-token), thêm `REQUESTS` cho từng route, thêm `ALLOWED_STATUS` nếu có mã 2xx khác thường | `middleware/tests/test_auth_matrix.py:48-183` | `test_matrix_allows_exactly_the_ds04_roles` (`:288`) và `test_matrix_covers_every_protected_route` (`:310`) xanh |
| B8 | Test tích hợp DB thật (`RTS_DB_TEST`): RBAC 3 vai trò; scope; compare set; `[from,to)`; `quality` + `include_suspect=false`; zero-fill; huỷ triệt tiêu; `Σ cửa hàng = tổng hệ thống` | `middleware/tests/test_dashboard.py` (mới) | Toàn bộ xanh |

**Ước lượng B: 3 – 4 người-ngày.**

---

## Sau B — hoàn tất backend

| # | Việc | Ghi chú |
|---|---|---|
| F3-a | Runbook: cách chạy migration 004, cách reset demo, cảnh báo "Dashboard vs DS-05 dùng hai mốc khác nhau — chỉ đối chiếu tổng toàn kỳ" | Tài liệu |
| F3-b | Cập nhật `docs/design/DS-04` (ngữ nghĩa `occurred_at` + `effective_at`, naive = UTC) và `DS-05` (batch theo `created_at`, không theo khoảng thời gian) | Tài liệu thiết kế |
| F3-c | (Tùy chọn, **ngoài phạm vi v6**) `GET /dashboard/stream` (SSE) — chỉ là đường nâng cấp đã chốt ở §7.4, không làm bây giờ | Nếu sau này cần push thay polling |

---

## Tổng kết

- **16 đầu việc** (8 M + 8 B) + 2 việc tài liệu.
- **Ước lượng: 5,5 – 7,5 người-ngày** (M: 2,5–3,5; B: 3–4).
- **File mới (7):** `004_pos_transaction_occurred_at.sql`, `services/time_quality.py`, `repositories/dashboard.py`, `services/dashboard.py`, `api/dashboard.py`, `api/schemas/dashboard.py`, `tests/test_dashboard.py`.
- **File sửa (5):** `domain/models.py`, `core/config.py`, `tools/history-generator/loader.py`, `main.py`, `tests/test_auth_matrix.py`.
- **Không làm trong phạm vi này:** sửa `security.py`, thêm/bớt role, đổi route hiện có, migration 005, sửa migration 001–003, đổi `payload_hash`.

## Ràng buộc cần nhớ khi triển khai

1. **Contract trước code** (`README.md:264`): B1 phải xong trước B2–B5.
2. **Migration trước repository**: M1 áp lên `RTS_DB_TEST` trước khi B2 chạy được.
3. **`main.py` và `test_auth_matrix.py` sửa cùng một commit** — nếu không, `test_auth_matrix` đỏ ngay.
4. **`occurred_at` không bao giờ bị ghi đè** bằng giờ server; DUPLICATE giữ bản đầu.
5. **Không đặc cách `HIST-`** trong API; đây là dữ liệu mô phỏng của DB demo, xử lý ở runbook.