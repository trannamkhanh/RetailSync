# Khảo sát và kế hoạch: Dashboard doanh thu cho giao diện Middleware (v6)

- **Ngày khảo sát:** 2026-11-17 · **Bản:** v6 — sửa 6 lỗi đối chiếu source, chốt 7 điểm hợp đồng
- **Cơ sở:** source `main` tại `986b3d3`; đọc file trực tiếp, **không chạy ứng dụng, không chạy SQL**.
- **Trạng thái:** chờ duyệt. Không sửa source, DB, migration, dependency hay branch.
- **Giao diện đích:** `clients/demo-console` (WinForms .NET 8) — **Dashboard phục vụ trình diễn**, API thiết kế để tái dùng cho sản phẩm sau này.
- **Thay thế:** ma trận quyền API của v4 (Admin-only) được thay bằng Admin/Auditor/Manager theo yêu cầu; WinForms vẫn chỉ Admin.
- **Đã sửa ở v6:** (1) ngữ nghĩa `[from,to)` của `/audit-logs`; (2) bắt buộc cập nhật `test_auth_matrix.py`; (3) `/dashboard/stores` không dùng `resolve_scope`/`resolve_compare`; (4) quan hệ `occurred_at` (Dashboard) vs `created_at` (sync DS-05); (5) `is_active = 0` là ngoại lệ có chủ đích; (6) `CANCELLATION` không có dòng item riêng.

---

## 0. Quyết định đã chốt

| # | Quyết định | Hệ quả |
|---|---|---|
| 1 | **API-backed** | Dashboard chỉ gọi API; dùng được cả DB demo và DB thật |
| 2 | **WinForms chỉ Admin** (không chọn vai trò); **API giữ Admin/Auditor/Manager** | UI dùng token `admin`; API kiểm tra role + phạm vi từng request; HQ bị loại có chủ đích |
| 3 | **Doanh thu theo `occurred_at`** + phân loại độ tin cậy thời gian | Migration 004 (chưa thực hiện); không thay thế bằng giờ nhận |
| 4 | **Giữ 3 danh mục tiếng Anh**, nhãn tiếng Việt ở UI | Ánh xạ cấu hình ở client |
| 5 | **LiveCharts2** (đã xác minh package; còn 2 kiểm tra runtime) | Fallback OxyPlot |
| 6 | **Làm mới 30 s + Refresh thủ công**, nâng cấp được SSE/WS | Tách chu kỳ, đặt sau interface |
| 7 | **Tách "phạm vi xem" và "phạm vi so sánh"** | Biểu đồ đường/tròn theo phạm vi xem; biểu đồ cột so sánh tập chi nhánh riêng, trong giới hạn quyền |

**Kết luận nhanh:** không đổi kiến trúc, không đổi RBAC chung, không đổi schema ngoài migration 004. Dashboard là tab thứ 5 của console (chỉ Admin); API phục vụ Admin/Auditor/Manager; biểu đồ cột có bộ chọn so sánh độc lập với phạm vi xem nhưng không vượt quá quyền.

---

## 1. Giao diện đích và giới hạn demo

### 1.1 Giao diện hiện tại

| Thành phần | Hiện trạng | Tham chiếu |
|---|---|---|
| Nền tảng | C# / WinForms, `net8.0-windows` | `DemoConsole.csproj` |
| Runtime máy khảo sát | .NET 8 Desktop 8.0.33 | `dotnet --list-runtimes` |
| Điều hướng | `TabControl` 4 tab; **không sidebar/navbar/router** | `MainForm.cs:139-144` |
| Mỗi tab | status label + nội dung qua `Page()` | `MainForm.cs:829`, `:852` |
| Làm mới | timer 3 s → `RefreshAllAsync` song song, `Guard` từng tab | `:301-374` |
| 404 rule | `FeatureAvailability`, probe 30 s | `:628-664` |
| Kênh dữ liệu | API + SQL chỉ đọc (từ chối `RTS_DB`) | `DemoApiClient.cs:47-88`, `ReadOnlySql.cs:63-71` |
| Biểu đồ | **Chưa có thư viện nào** | — |

### 1.2 Đây là Dashboard demo hay Dashboard sản phẩm?

**Kết luận: Dashboard demo (công cụ trình diễn), không phải sản phẩm.**

Căn cứ:

- `clients/demo-console/README.md:3`: console là *presenter tool, not part of the product*, chạy trên máy S, giữ token Admin/Auditor/HQ.
- SRS v1.3 (đoạn 133–135): UI trong phạm vi chỉ có Staff App và demo POS; dashboard (PB-36) là mức **Could, chưa lên lịch** — và PB-36 là dashboard guardrail/acceptance, không phải dashboard doanh thu.
- Console là desktop một người dùng, đọc token từ `.tokens/demo_tokens.json`, đọc SQL bằng `sa` cho vài tab; không có login, không phân phối, không cập nhật từ xa.

**Giới hạn của phương án demo:**

| Giới hạn | Ảnh hưởng |
|---|---|
| Chỉ chạy trên máy trình chiếu, một người dùng | Không phải công cụ vận hành thật |
| Không có login/session; token phát sẵn | Không đáp ứng yêu cầu danh tính/audit của sản phẩm |
| UI chỉ Admin | Manager/Auditor không có giao diện Dashboard (chỉ API sẵn sàng) |
| Nhãn tiếng Việt hard-code | Không có i18n |
| Tab SQL đọc `RTS_DB_DEMO` bằng `sa` | Dữ liệu Dashboard (API) và tab SQL có thể khác nguồn |
| Lịch sử 90 ngày là dữ liệu mô phỏng `HIST-` | Không được nhầm với dữ liệu thật |

**Nếu muốn đưa Dashboard vào sản phẩm sau này** (không làm bây giờ, không đổi ứng dụng):

1. Chọn client sản phẩm (web console hay desktop) — quyết định riêng.
2. Đăng nhập/phiên thật + chính sách token (hiện chỉ phát sẵn).
3. UI theo vai trò Admin/Auditor/Manager và phạm vi cửa hàng.
4. Đóng gói/phân phối/cập nhật; giám sát, log truy cập Dashboard.
5. Hiệu năng khi dữ liệu lớn (index, phân trang, cache), i18n, kiểm thử tải.
6. Chốt lại hợp đồng API và mức chia sẻ dữ liệu với HQ.

**Phần đã sẵn sàng cho sản phẩm:** hợp đồng API, RBAC Admin/Auditor/Manager, phạm vi cửa hàng, công thức doanh thu, test. Vì vậy không cần viết lại backend khi chuyển client.

**Không chuyển sang ứng dụng khác trong kế hoạch này.**

---

## 2. RBAC hiện tại và phạm vi Dashboard

### 2.1 Hiện trạng (không thay đổi)

| Điểm kiểm tra | Kết quả | Tham chiếu |
|---|---|---|
| Role API | `POS, Staff, Manager, HQ, Admin, Auditor` | `security.py:21-28` |
| `Manager` | Có (`STORE_MANAGER`), gắn `staff_user.store_id` | `:23`, `:76-84` |
| Ép phạm vi hiện có | `require_own_store` (inventory) | `inventory.py:19-28` |
| Admin | `admin`, không gắn cửa hàng | `seed/002_demo_catalog.sql:41-42` |
| HQ | `hq_operator`, không gắn cửa hàng; chỉ có route `POST /hq/snapshot` (luôn bị từ chối) | `security.py:24`, `api/hq_snapshot.py` |
| Token demo | `admin`, `auditor`, `manager_dn1`, `hq_operator` | `scripts/issue_demo_tokens.py:22-30` |

**Không sửa** `security.py`, không thêm/bớt role, không đổi route hiện có.

### 2.2 Ma trận quyền Dashboard

| Endpoint | Admin | Auditor | Manager | HQ, Staff, POS |
|---|---|---|---|---|
| `GET /dashboard/stores` | mọi cửa hàng | mọi cửa hàng | cửa hàng của mình | 403 |
| `GET /dashboard/revenue` | toàn hệ thống hoặc 1 cửa hàng | toàn hệ thống hoặc 1 cửa hàng | chỉ cửa hàng của mình | 403 |
| `GET /dashboard/revenue-by-category` | như trên | như trên | chỉ cửa hàng của mình | 403 |
| `GET /dashboard/revenue-by-store` | so sánh mọi cửa hàng | so sánh mọi cửa hàng | so sánh trong phạm vi được cấp | 403 |

- WinForms **chỉ dùng token Admin** (không có bộ chọn vai trò). API vẫn kiểm tra role từng request để sẵn sàng cho client khác.
- Manager chỉ một cửa hàng theo schema hiện tại; nhiều cửa hàng/Manager cần bảng ánh xạ (ngoài kế hoạch).

### 2.3 Vì sao HQ không có Dashboard (giới hạn có chủ đích)

- HQ hiện **không có quyền đọc toàn hệ thống**: nó không gắn cửa hàng, nhưng chỉ có một route `POST /hq/snapshot` (luôn trả 422) — là đầu nhận của mô phỏng HQ, không phải client phân tích.
- Vai trò HQ trong SRS là **mock/stub** cho đồng bộ; "read-only surplus/shortage insight" (PB-29) là Could, chưa làm.
- Mở doanh thu chi tiết theo cửa hàng cho HQ sẽ **thay đổi ranh giới chia sẻ dữ liệu**: hiện Middleware chỉ gửi batch tổng hợp lên HQ theo DS-05; lộ doanh thu chi tiết là quyết định nghiệp vụ, không phải kỹ thuật.
- Không có UI HQ nào để hiển thị Dashboard.
- **Kết luận:** loại HQ là có chủ đích; nếu sau này HQ cần, phải có quyết định nghiệp vụ + sửa DS-04 + test riêng.

### 2.4 WinForms Admin-only vs API 3 role

- Yêu cầu "WinForms chỉ Admin" được đáp ứng ở UI: không có bộ chọn vai trò, chỉ dùng token `admin`.
- Yêu cầu "giữ Admin, Auditor, Manager" được đáp ứng ở API: hợp đồng và kiểm tra quyền sẵn sàng cho client khác.
- Không có luồng UI Manager/Auditor trong WinForms (đúng yêu cầu trước).
- Nếu muốn API cũng Admin-only, chỉ cần đổi danh sách role trong `require_role` và hợp đồng — một dòng, nhưng phải quyết định lại (xem mục 9.5).

---

## 3. Backend hiện có

- FastAPI thuần API, 4 tầng `api → services → repositories → domain`; router commit, service/repository không.
- 11 router dưới `/api/v1`; không có endpoint doanh thu.
- `require_role` đối chiếu `staff_user` mỗi request.
- Scheduler nền (aggregation mỗi `SYNC_INTERVAL`); Dashboard đọc bảng gốc, không phụ thuộc job.
- Không WebSocket/SSE/CORS → polling.

---

## 4. Luồng POS và kiểm soát `occurred_at`

### 4.1 Luồng hiện tại

```
POS --mTLS--> pos-gateway --> POST /pos/events
  require_gateway → require_role("POS") → parse → require_terminal_certificate
  → validate_event_source → claim_transaction → transaction_item
  → deduct_items (FEFO) → audit → commit
```

- `timestamp` của POS (bắt buộc) **bị bỏ**; chỉ có `created_at` = `SYSUTCDATETIME()`.
- `payload_hash` không chứa timestamp → gửi lại vẫn DUPLICATE.

### 4.2 Nguyên tắc thời gian

| Trường | Nghĩa | Nguồn | Có ghi đè? |
|---|---|---|---|
| `occurred_at` | Thời điểm giao dịch thực tế (POS khai báo) | `PosEvent.timestamp` | **Không bao giờ** bị thay bằng giờ server |
| `created_at` (received_at) | Thời điểm Middleware nhận | `SYSUTCDATETIME()` | Không đổi |
| `effective_at` | Mốc dùng cho Dashboard | `COALESCE(occurred_at, created_at)` | — |

- Dữ liệu cũ không có `occurred_at` → `effective_at` lùi về `created_at` (ghi rõ là xấp xỉ).
- **Không** tự thay `occurred_at` bằng giờ nhận trong bất kỳ trường hợp nào.

### 4.3 Phân loại độ tin cậy thời gian

Không chặn giao dịch vì lý do thời gian (NFR02: không mất giao dịch). Phân loại để Dashboard cảnh báo và cho phép lọc:

| Loại | Điều kiện (so với `received_at`) | Ý nghĩa | Dashboard mặc định |
|---|---|---|---|
| `ON_TIME` | `-5 phút ≤ occurred − received ≤ +5 phút` | Bình thường, lệch đồng hồ nhỏ | Hiển thị |
| `BACKFILL` | Xảy ra trước khi nhận > 5 phút và ≤ 30 ngày | POS gửi bù offline — **đáng tin** | Hiển thị |
| `SUSPECT_FUTURE` | `occurred > received + 5 phút` | Đồng hồ POS chạy nhanh / dữ liệu bất thường | Hiển thị + cảnh báo |
| `SUSPECT_OLD` | Xảy ra trước khi nhận > 30 ngày | Gửi bù quá cũ / dữ liệu nhập tay | Hiển thị + cảnh báo |

- Ngưỡng cấu hình: `POS_MAX_FUTURE_SKEW_SECONDS` (mặc định 300), `POS_MAX_BACKFILL_DAYS` (mặc định 30).
- Phân loại tính từ `occurred_at` và `created_at`, **không thêm cột**.
- **Chốt (v6): phân loại là hàm thuần `classify_time(occurred_at, created_at, policy) -> label` đặt ở `app/services/`, không chạm DB.** API gọi hàm này để trả `quality`/`time_policy`; **console không tự phân loại**, chỉ hiển thị nhãn + ngưỡng do server trả về (tránh 2 nguồn sự thật).
- `NaN`/thiếu timestamp/không parse được → 422 `INVALID_EVENT` như hiện tại; timestamp naive hiểu là UTC (ghi rõ trong DS-04).
- **Chốt (v6): `occurred_at` naive = UTC, không phải UTC+7.** `schemas/pos.py:33` hiện là `datetime` không bắt buộc tz, còn `ApiParsers.cs:198-207` dùng `AssumeUniversal`. Quy tắc duy nhất cho DS-04: *naive = UTC; có offset thì quy về UTC rồi mới so sánh/lưu.* Không suy diễn theo giờ Việt Nam.
- **Chốt (v6): khi DUPLICATE, `quality` được tính từ bản ghi đầu tiên**, không phải từ lần gửi lại — `services/idempotency.py:42-45` trả về trước khi so timestamp, nên `occurred_at` của lần sau không bao giờ được ghi.

### 4.4 Ảnh hưởng Dashboard

- Ba endpoint biểu đồ trả thêm `quality: {on_time, backfill, suspect_future, suspect_old}` cho khoảng đã chọn và `time_policy` (ngưỡng đang áp dụng).
- Tham số `include_suspect` (mặc định `true`): `false` loại `SUSPECT_*` khỏi số liệu (dùng khi cần số "sạch").
- UI hiện badge: *"12 giao dịch có thời gian cần kiểm tra"* + tooltip giải thích; mặc định vẫn tính vào doanh thu để không understate.
- Với chế độ "Hôm nay", `to = now` (không vẽ điểm tương lai); giao dịch `SUSPECT_FUTURE` chỉ xuất hiện khi thời gian thực vượt qua mốc đó.
- Không đặc cách dữ liệu `HIST-` trong API; đó là dữ liệu mô phỏng của DB demo, xử lý ở tài liệu/runbook (mục 6.10).

---

## 5. Database

### 5.1 Bảng dùng cho Dashboard

`store` · `pos_transaction` (`store_id`, `txn_type`, `status`, `created_at`, `occurred_at` sau migration) · `transaction_item` · `product` · `sync_batch`/`sales_summary_line` (đối chiếu).

### 5.2 Công thức doanh thu (không đổi)

`Σ(SALE qty×price) − Σ(RETURN + CANCELLATION qty×price)`, **không lọc status** (`repositories/aggregation.py:43-57`). Không được vừa lọc `status <> 'CANCELLED'` vừa trừ CANCELLATION.

**Chốt (v6) — `CANCELLATION` không có dòng `transaction_item` riêng:** `services/pos_cancellation.py:44` gọi `add_transaction_items(session, event.transaction_id, sale_items(...))`, tức **sao chép item của SALE gốc** sang `txn_id` của yêu cầu huỷ; dòng SALE gốc chỉ bị `mark_cancelled` đặt `status='CANCELLED'` (`:53`). Vì vậy:

- `JOIN transaction_item` rồi `GROUP BY txn_id` là đủ; **không** viết `WHERE txn_type = 'SALE'` khi tính doanh thu.
- Đối chiếu: `net_revenue` của một `txn_id` đã huỷ = `qty×price − qty×price = 0`.

Doanh thu ròng theo kỳ có thể âm → đường/cột chịu âm; tròn loại phần âm.

### 5.3 Dữ liệu lịch sử

`RTS_DB` không có lịch sử; `RTS_DB_DEMO` có 90 ngày mô phỏng (`HIST-`, mỗi SKU một giao dịch 12:00, 2,5% trả hàng, không huỷ).

### 5.4 Phân loại mức đáp ứng

| # | Tiêu chí | Phân loại | Ghi chú |
|---|---|---|---|
| 1 | Bảng lịch sử giao dịch | **Đã đáp ứng** | `pos_transaction` + `transaction_item` |
| 2 | Thời gian phát sinh | **Chưa đáp ứng** | Sẽ đáp ứng bằng migration 004 |
| 3 | Tổng tiền + chi tiết | **Đã đáp ứng** | Tính từ `qty × unit_price` |
| 4 | Danh mục sản phẩm | **Đã đáp ứng** | Giữ DB, nhãn tiếng Việt ở UI |
| 5 | Chi nhánh + liên kết | **Đã đáp ứng** | `store` + FK |
| 6 | OK / huỷ / hoàn trả | **Đã đáp ứng** | `txn_type`, `status`, `ref_txn_id` |
| 7 | Ngày/tuần/tháng/quý | **Đã đáp ứng** | Sau migration dùng `effective_at` |
| 8 | So sánh chi nhánh | **Đã đáp ứng** | `store_id` + tên |

Khoảng trống: `occurred_at`/`effective_at` (**Chưa tồn tại** → migration 004); API doanh thu (**Chưa tồn tại**); `GET /dashboard/stores` (**Chưa tồn tại**); thư viện biểu đồ (**Chưa tồn tại**); index thời gian (**Chưa tồn tại**).

---

## 6. Thiết kế Dashboard (UI)

### 6.1 Vị trí

Tab thứ 5 **"Doanh thu"**, trong `UI/DashboardTab.cs`; `MainForm` gắn tab + `Guard` + `Tick`. Không có bộ chọn vai trò.

### 6.2 Bố cục

```
┌ Tab "Doanh thu" ─────────────────────────────────────────────────────────────┐
│ Nguồn: https://middleware.../api/v1 (token admin)                            │
│ Phạm vi xem: [Toàn bộ hệ thống ▾]   Mốc: [Tháng ▾] [10/2026 ▾]   [Làm mới]   │
│ Độ chi tiết: [Ngày ▾]   Tổng: 12.345.678 đ   1.234 giao dịch   ⚠ 12 cần KT   │
│ ┌ Đường: Tổng doanh thu theo thời gian ───────────────────────────────────┐ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│ ┌ Tròn: Tỷ lệ theo danh mục ──────────┐ ┌ Cột: So sánh chi nhánh ─────────┐ │
│ │                                     │ │ So sánh: [Đà Nẵng][Hà Nội][HCM] │ │
│ └─────────────────────────────────────┘ └─────────────────────────────────┘ │
│ Làm mới lúc 18:42:10. Không có lỗi.                                          │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 6.3 Hai phạm vi độc lập

| Phạm vi | Áp dụng | Ý nghĩa |
|---|---|---|
| **Phạm vi xem** (`store_id`) | Biểu đồ đường + tròn | Toàn hệ thống hoặc một chi nhánh; quyết định số liệu của 2 biểu đồ này |
| **Phạm vi so sánh** (`compare_store_ids`) | Biểu đồ cột | Tập chi nhánh đưa vào so sánh, độc lập với phạm vi xem |

Ví dụ: Admin xem Dashboard của Đà Nẵng (đường/tròn = Đà Nẵng), biểu đồ cột vẫn so sánh Đà Nẵng với Hà Nội và TP.HCM trong cùng khoảng thời gian.

- Đổi phạm vi xem **không** làm mất tập so sánh đã chọn.
- Tập so sánh mặc định = tất cả cửa hàng **trong phạm vi quyền** (Admin/Auditor: tất cả; Manager: cửa hàng của mình).
- Tập so sánh **không mở rộng quyền**: Manager chỉ chọn được trong cửa hàng được cấp; API trả 403 nếu vượt.
- Cột của cửa hàng đang xem được đánh dấu (ví dụ viền đậm/nhãn "đang xem") để không nhầm.

### 6.4 Bộ lọc thời gian — một trạng thái dùng chung

```
DashboardQuery {
  StoreId            // null = toàn hệ thống (charts 1-2)
  CompareStoreIds    // null/rỗng = toàn bộ phạm vi (chart 3)
  Mode               // Day | Week | Month | Quarter | Custom
  Period             // 2026-10-15 | 2026-W42 | 2026-10 | 2026-Q4
  From, To           // suy ra từ Mode+Period
  Bucket             // Hour | Day | Week (chỉ chart 1)
  IncludeSuspect     // true mặc định
}
```

- Cả 3 biểu đồ dùng chung `From/To`; đổi mốc → tải lại 3 kết quả với cùng khoảng thời gian.
- "Hôm nay" → `To = now`; ngày quá khứ → hết ngày.
- Đổi phạm vi xem → 3 request cùng `StoreId` (chart 3 vẫn dùng `CompareStoreIds`).

### 6.5 Biểu đồ đường

- Net revenue theo `effective_at`, zero-fill.
- Bucket mặc định: Ngày → giờ; Tuần → ngày; Tháng → ngày; Quý → tuần.
- Tooltip: `"15/11 14:00 — 1.234.000 đ (12 giao dịch)"`.
- Khoảng vượt `data_from` → kẹp + ghi chú.
- Badge chất lượng thời gian khi có `SUSPECT_*`.

### 6.6 Biểu đồ tròn

- Nhóm theo `product.category` trong phạm vi xem + khoảng thời gian.
- Nhãn ngoài `"Sản phẩm từ sữa 45,2%"`; tooltip đầy đủ.
- Chỉ vẽ phần dương; danh mục âm ghi chú; tổng 0 → trạng thái rỗng.

**Ánh xạ nhãn (`appsettings.json`, không đổi DB):**

| `product.category` | Nhãn UI |
|---|---|
| `Dairy` | Sản phẩm từ sữa |
| `Bakery` | Bánh nướng |
| `Dry goods` | Thực phẩm khô |
| khác / rỗng | giữ nguyên / "Khác" |

### 6.7 Biểu đồ cột — so sánh độc lập

- Trục X: các cửa hàng trong tập so sánh; một cột/chi nhánh; cùng `From/To`.
- `So sánh` là multi-select (CheckBox), mặc định toàn bộ phạm vi.
- Khi phạm vi xem = một cửa hàng, cột đó vẫn nằm trong tập so sánh mặc định và được đánh dấu; **không** ép biểu đồ còn 1 cột.
- Cửa hàng doanh thu 0 vẫn hiện nếu được chọn.
- Sort giảm dần mặc định; toggle theo tên.
- Bỏ chọn cột chỉ là lọc hiển thị phía client trên dữ liệu đã tải; không tạo truy vấn mới.

### 6.8 Trạng thái rỗng/lỗi

| Tình huống | Hiển thị |
|---|---|
| 404 route | Tab vô hiệu + lý do |
| Chưa có giao dịch | Chữ giữa khung + KPI 0 |
| Ngoài khoảng dữ liệu | Kẹp + ghi chú |
| API lỗi | Status đỏ, giữ biểu đồ cũ |
| 401/403 | "Không có quyền xem dữ liệu này"; không vẽ dữ liệu |
| Thiếu token `admin` | Dòng lỗi "thiếu token 'admin'" |
| Có `SUSPECT_*` | Badge "N giao dịch có thời gian cần kiểm tra" |

### 6.9 Thư viện biểu đồ

**LiveCharts2 `LiveChartsCore.SkiaSharpView.WinForms` 2.0.5** — nuspec: asset `net8.0-windows7.0`, `frameworkReference Microsoft.WindowsDesktop.App.WindowsForms`, MIT, deps SkiaSharp 3.119.0. Runtime .NET 8 Desktop có trên máy.

**Kiểm tra runtime bắt buộc (M0):** chữ tiếng Việt có dấu; DPI `PerMonitorV2`. Thất bại → OxyPlot (GDI+).

### 6.10 Demo vs dữ liệu thật — không nhầm lẫn

- Dashboard không phân biệt cứng demo/thật; nó hiển thị đúng dữ liệu của Middleware mà console trỏ tới.
- Tab hiển thị **Nguồn: `<MiddlewareBaseUrl>`** để người xem biết đang xem hệ thống nào.
- Trong demo, `RTS_DB_DEMO` chứa 90 ngày **dữ liệu mô phỏng** (`HIST-`); biểu đồ 90 ngày là mô phỏng, không phải doanh thu thật. Runbook phải ghi rõ.
- Không thêm logic `HIST-` vào API/Dashboard (tránh logic demo trong đường sản phẩm). Tab "Giao dịch và audit" tiếp tục ẩn `HIST-` như hiện tại — đây là điểm khác biệt đã biết giữa 2 tab; ghi trong tài liệu.
- Tab hiển thị riêng nguồn API (`MiddlewareBaseUrl`) và nguồn SQL (`SqlServer`/`Database`); `MainForm` hiện đã đưa tên database vào tiêu đề và dòng trạng thái. URL API không chứa tên database nên console không thể tự xác định hai kết nối có cùng DB chỉ bằng cách so URL với `Database`. Ghi chú tĩnh rằng Dashboard lấy dữ liệu từ Middleware còn tab SQL dùng cấu hình SQL; hai nguồn có thể khác nhau. Không tuyên bố tự phát hiện mismatch nếu chưa có metadata đáng tin từ Middleware.

---

## 7. Thiết kế Backend

### 7.1 Bốn endpoint

| Endpoint | Query | Trả về |
|---|---|---|
| `GET /dashboard/stores` | — | `{stores:[{store_id,name,region_id,is_active}]}` trong phạm vi |
| `GET /dashboard/revenue` | `store_id?`, `from`, `to`, `bucket`, `include_suspect?` | điểm + tổng + số giao dịch + `quality` + `time_policy` + `has_data` + `data_from/to` + `scope` |
| `GET /dashboard/revenue-by-category` | `store_id?`, `from`, `to`, `include_suspect?` | phần + % + danh mục âm + tổng + `quality` + `scope` |
| `GET /dashboard/revenue-by-store` | `compare_store_ids[]?`, `from`, `to`, `include_suspect?` | cột/chi nhánh + tên + % + `scope` + `quality` |

- `store_id` vắng mặt = toàn hệ thống (Admin/Auditor) hoặc toàn phạm vi (Manager).
- `compare_store_ids` vắng mặt/rỗng = toàn bộ phạm vi quyền.
- **Chốt (v6) — cú pháp mảng:** `?compare_store_ids=DN1&compare_store_ids=HN1` (query lặp, không dùng dấu phẩy). Pydantic khai báo `list[str] | None`; console dựng query bằng cách nối từng giá trị đã encode. Lý do: `ID_PATTERN = ^[A-Za-z0-9_-]+$` (`schemas/registry.py:10`) chỉ cho phép chữ, số, `_` và `-`, nên dấu phẩy không bao giờ xuất hiện trong mã hợp lệ — nhưng vẫn chọn query lặp để tránh mơ hồ khi trim/encode và để khớp thói quen của FastAPI (`Query(default=None)` + `list[str]`).
- **Chốt (v6) — ngữ nghĩa thời gian:** khoảng **nửa mở `[from, to)`**. `/audit-logs` cũng là nửa mở trên thực tế: `repositories/audit.py:11-26` dùng `created_at >= from` và `created_at < to + 1µs` (cộng 1µs để phủ hết `datetime2(7)`). Tài liệu `openapi.yaml:677` mô tả "inclusive" là cách nói theo microsecond cuối; **không** được hiểu là `BETWEEN`. Dashboard và audit vì vậy **cùng một ngữ nghĩa**, chỉ khác độ phân giải.
- Tiền là JSON number 2 chữ số thập phân (Pydantic v2 serialize `Decimal` thành chuỗi — đã kiểm tra).

### 7.2 Xác thực và phạm vi trong từng API

**Chốt (v6) — endpoint nào cần hàm nào:**

| Endpoint | `require_role` | `resolve_scope` | `resolve_compare` |
|---|---|---|---|
| `GET /dashboard/stores` | Có | Không (chỉ lọc theo vai trò) | Không |
| `GET /dashboard/revenue` | Có | Có (`store_id`) | Không |
| `GET /dashboard/revenue-by-category` | Có | Có (`store_id`) | Không |
| `GET /dashboard/revenue-by-store` | Có | Không | Có (`compare_store_ids`) |

Mỗi endpoint có `require_role`, theo thứ tự:

1. `require_role("Admin", "Auditor", "Manager")` — thiếu/sai token → 401; role khác → 403; tài khoản inactive → 403.
2. `resolve_scope(principal, store_id)` (chỉ charts 1-2) — Admin/Auditor: mọi cửa hàng; Manager: chỉ `principal.store_id`; Manager không có `store_id` ở cả DB lẫn token → 403; yêu cầu ngoài phạm vi → 403.
3. `resolve_compare(principal, compare_store_ids)` (chỉ chart 3) — Admin/Auditor: mọi cửa hàng; Manager: tập con của `{principal.store_id}`; vượt → 403; mã không tồn tại → 422.
4. Truy vấn thêm `store_id = @store` (charts 1-2) hoặc `store_id IN @compare` (chart 3).

**`GET /dashboard/stores`** chỉ lọc danh sách theo vai trò (Admin/Auditor: mọi cửa hàng; Manager: `principal.store_id`, lấy từ DB trước rồi fallback sang claim token theo `security.py:84`; nếu không có `store_id` ở cả DB lẫn token → 403 `FORBIDDEN`). Không nhận `store_id`, không gọi `resolve_scope`/`resolve_compare`.

Quy tắc lỗi:

| Tình huống | Kết quả |
|---|---|
| Không token / hết hạn | 401 |
| Role HQ/Staff/POS | 403 |
| Manager yêu cầu cửa hàng ngoài phạm vi | 403 (không tiết lộ tồn tại) |
| Admin/Auditor `store_id` không tồn tại | 422 `INVALID_STORE` |
| `compare_store_ids` có mã lạ (Admin) | 422 `INVALID_STORE` |
| Cửa hàng `is_active = 0` | 200 (xem lịch sử) — **ngoại lệ có chủ đích**, xem ghi chú dưới |
| `include_suspect` sai kiểu | 422 `VALIDATION_ERROR` |

**Chốt (v6) — `is_active = 0` là ngoại lệ có chủ đích của Dashboard.** Các API hiện có loại cửa hàng không active: `test_cross_store_api.py:174` (`test_stf35_2_only_active_stores_of_this_middleware_are_listed`). Dashboard **cố ý** giữ lại `is_active = 0` vì Admin cần xem doanh thu lịch sử của cửa hàng đã đóng. Đây là khác biệt **được phép**, không phải lỗi; phải ghi vào `openapi.yaml` và runbook để reviewer không coi là mâu thuẫn.

**Không thay đổi RBAC chung:** không sửa `security.py`, không đổi route hiện có; test quyền hiện có phải tiếp tục xanh.

### 7.3 Truy vấn

- Lọc `effective_at ∈ [from, to)`; charts 1-2 thêm `store_id = @store`; chart 3 thêm `store_id IN @compare`.
- Join `transaction_item`; nhóm bucket sau khi dịch `+7h`; công thức doanh thu mục 5.2.
- `quality`: đếm theo phân loại mục 4.3 bằng `CASE` trên `occurred_at`/`created_at`; **luôn trả về**, kể cả khi `include_suspect=false` (khi đó nó phản ánh toàn bộ khoảng đã chọn, còn số tiền/điểm đã loại `SUSPECT_*`; UI phải nói rõ hai con số khác nhau — badge "đã loại N giao dịch cần kiểm tra").
- Danh mục: join `product`, gom rỗng → "Khác"; `share` trên tổng.
- Cột: `GROUP BY store_id`, join `store`, sort giảm dần.
- Zero-fill ở service; tham số chuỗi `CAST` đúng kiểu (PB-10-5).

### 7.4 Cập nhật 30 s và đường nâng cấp

- `DashboardRefreshSeconds` mặc định 30 (5–3600); timer 3 s chỉ gọi `Tick(now)`.
- `IDashboardSource.FetchAsync(query, ct)`; hiện polling; sau này SSE/WS chỉ là tín hiệu "đã đổi" rồi vẫn gọi REST (snapshot) → UI/parser không đổi.

### 7.5 Hiệu năng

Demo ~2.400 giao dịch. Index `effective_at` trong migration 004; cân nhắc `(store_id, effective_at)` khi lớn. Không cache v1.

### 7.6 Quan hệ với đồng bộ DS-05 (bắt buộc hiểu đúng)

**Chốt (v6) — Dashboard và sync cố tình dùng hai mốc thời gian khác nhau:**

| | Dashboard | Sync / batch (DS-05) |
|---|---|---|
| Mốc xếp dữ liệu | `effective_at = COALESCE(occurred_at, created_at)` | Batch lấy mọi giao dịch của cửa hàng đang có `sync_batch_id IS NULL` tại lúc job claim; không lọc/gom theo khoảng `created_at` hay `occurred_at` |
| Mốc thời gian batch | Bucket Dashboard theo ngày/giờ `Asia/Bangkok` (UTC+7) | `period_start/period_end` là min/max `created_at` của các giao dịch được claim (giờ Middleware nhận); `sync_batch_id` được tạo theo thời điểm chạy aggregation UTC |
| Nguồn | `repositories/dashboard.py` | `repositories/aggregation.py:21-40`, `services/aggregation.py:24, 68-70` |

**Múi giờ:** Dashboard quy đổi bucket sang UTC+7; sync giữ timestamp UTC. Việc batch claim giao dịch chưa đồng bộ là theo trạng thái `sync_batch_id`, không phải nhóm theo giờ nhận hay theo ngày.

Hệ quả phải chấp nhận: **tổng `net_revenue` của một `sync_batch` không bằng phần đóng góp của batch đó vào Dashboard theo ngày**, vì batch chứa tập giao dịch chưa đồng bộ tại lần chạy, còn Dashboard xếp từng giao dịch theo `occurred_at` (hoặc fallback `created_at`). Đây là **hai góc nhìn có chủ đích** (batch = vận hành/đồng bộ; Dashboard = ngày phát sinh doanh thu), không phải sai số.

Ví dụ dễ kiểm chứng: một SALE xảy ra 10/10 20:00 nhưng POS gửi bù 12/10 09:00 → Dashboard ghi doanh thu vào **10/10**, còn giao dịch được claim vào batch ở chu kỳ aggregation kế tiếp; `period_start/period_end` phản ánh giờ nhận 12/10, còn `sync_batch_id` phản ánh giờ chạy aggregation.

Vì vậy:
- Test đối chiếu chỉ so **tổng toàn kỳ** (`Σ mọi batch` = `Σ Dashboard` khi cùng `from/to`), không so từng batch với từng ngày.
- Ghi vào DS-04 (ngữ nghĩa Dashboard) + DS-05 (batch theo `created_at`) + runbook.
- Nếu sau này cần khớp 100% với HQ, phải chọn một trong hai: (a) Dashboard cũng xếp theo `created_at`, hoặc (b) sync xếp theo `effective_at` — cả hai đều là thay đổi hợp đồng, **ngoài phạm vi này**.

---

## 8. Migration 004 — `occurred_at` (chưa thực hiện)

### 8.1 Thiết kế

| Thành phần | Đề xuất | Lý do |
|---|---|---|
| `pos_transaction.occurred_at` | `datetime2 NULL` | NULL = dữ liệu cũ không xác định |
| `created_at` | Giữ nguyên, nghĩa received | Đổi tên vỡ nhiều nơi |
| `effective_at` | `COALESCE(occurred_at, created_at) PERSISTED` | Một cột lọc/nhóm, index được |
| Index | nonclustered trên `effective_at` | Truy vấn khoảng |
| Backfill | Không ghi đè `occurred_at` | Trung thực |
| Cột chất lượng thời gian | **Không thêm** | Phân loại suy ra từ 2 mốc + ngưỡng cấu hình |

### 8.2 Thứ tự phụ thuộc (duy nhất)

1. Sửa `docs/design/openapi.yaml` (hợp đồng Dashboard; POS không đổi).
2. Migration 004 trên `RTS_DB_TEST` và `RTS_DB_DEMO` (004 phụ thuộc 001–003 đã áp).
3. Code ghi `occurred_at` + phân loại thời gian + test.
4. **Cập nhật `middleware/tests/test_auth_matrix.py` cùng lúc với `app/main.py`:** thêm 4 route vào `MATRIX` (kèm cột POS/Staff/Manager/HQ/Admin/Auditor/no-token), thêm `REQUESTS` cho từng route, thêm `ALLOWED_STATUS` nếu có mã 2xx khác thường. Không có bước này thì `test_matrix_allows_exactly_the_ds04_roles` (`:288`) và `test_matrix_covers_every_protected_route` (`:310`) **đỏ ngay**.
5. Endpoint Dashboard + test.
6. UI + test.
7. Reset demo để lịch sử có `occurred_at`.

Không có migration 005 trong kế hoạch này. Không sửa 001–003; không down migration.

### 8.3 Ripple

| Nơi | Thay đổi |
|---|---|
| `idempotency` (service + repository) | Ghi `occurred_at` (UTC, naive = UTC) |
| `pos_events`, `pos_return`, `pos_cancellation` | Truyền `event.timestamp` |
| `domain/models.py` | Thêm `occurred_at` (không map computed) |
| `repositories/dashboard.py` (mới) | `effective_at` + `store_id` + quality |
| `tools/history-generator` | Ghi `occurred_at` |
| Console `ReadOnlySql` + lưới giao dịch | Hiện "Giờ bán"/"Giờ nhận" (nên có) |
| Test (11 điểm tạo `PosTransaction`) | Không vỡ vì nullable |

### 8.4 Rủi ro migration

Computed persisted column viết lại bảng (demo nhỏ; production ngoài giờ); dữ liệu cũ NULL (ghi rõ); đồng hồ POS sai (phân loại, không chặn); gửi lại khác timestamp → DUPLICATE (đúng).

---

## 9. Kế hoạch triển khai

### 9.1 TDD route

Mode `off`, decision `skipped`; test hồi quy viết cùng code. Backend test SQL Server thật (`RTS_DB_TEST`); bucket/period/thời gian unit test không DB; console xUnit.

### 9.2 Các pha

| Pha | Nội dung | Ước lượng |
|---|---|---|
| **M0** | Kiểm tra LiveCharts2: font tiếng Việt + DPI | 0,5 |
| **M** | Migration 004 + ghi `occurred_at` + phân loại thời gian + tool + test | 2,5 – 3,5 |
| **B** | Contract + 4 endpoint + RBAC/scope + compare set + **cập nhật `test_auth_matrix.py`** + test | 3 – 4 |
| **F1** | Tab + nguồn dữ liệu + đường + 30 s + nhãn danh mục + badge thời gian | 2 – 2,5 |
| **F2** | Tròn + cột + 2 bộ lọc phạm vi + multi-select so sánh | 2 – 2,5 |
| **F3** | Hoàn thiện: KPI, bảng SKU, tài liệu, runbook | 1 – 1,5 |
| | **Tổng** | **11 – 14** |

Thứ tự: M0 → hợp đồng → M → B → F1 → F2 → F3.

### 9.3 Kiểm thử

| Loại | Nội dung |
|---|---|
| RBAC | 401 không token; 403 cho HQ/Staff/POS; Admin/Auditor/Manager đúng quyền; Manager ngoài phạm vi → 403 |
| **Ma trận quyền (bắt buộc)** | `test_auth_matrix.py`: `MATRIX` có đủ 4 route × 7 cột; `REQUESTS` gọi được từng route; `test_matrix_allows_exactly_the_ds04_roles` và `test_matrix_covers_every_protected_route` xanh |
| Compare set | Admin chọn mọi cửa hàng; Manager chọn ngoài phạm vi → 403; rỗng → toàn phạm vi; mã lạ → 422; cú pháp `?compare_store_ids=A&compare_store_ids=B` |
| Phạm vi | Đổi phạm vi xem → charts 1-2 đổi, chart 3 giữ tập so sánh; đổi mốc → 3 request cùng `from/to`; `/dashboard/stores` không nhận `store_id` |
| Thời gian | `ON_TIME`, `BACKFILL`, `SUSPECT_FUTURE`, `SUSPECT_OLD` đúng ngưỡng; `include_suspect=false` loại đúng khỏi số tiền nhưng giữ `quality`; naive = UTC; không ghi đè `occurred_at`; DUPLICATE giữ bản đầu |
| Số liệu | Tổng theo cửa hàng + toàn hệ thống = tổng các cửa hàng; huỷ + trả triệt tiêu (`net_revenue = 0` cho txn đã huỷ); zero-fill |
| Đối chiếu DS-05 | `Σ net_revenue mọi batch` = `Σ Dashboard` khi cùng `from/to` (không so từng batch với từng ngày — xem §7.6) |
| Bucket | Biên 16:59:59Z/17:00:00Z; tuần ISO; tháng; quý |
| Contract | `[from,to)`; `/audit-logs` cùng ngữ nghĩa; tiền là number; 422 |
| Console | 3 request song song; `Tick` 30 s; 401/403 không vẽ dữ liệu; cảnh báo khác nguồn |
| RBAC hồi quy | Test quyền hiện có vẫn xanh |

### 9.4 Rủi ro

| Rủi ro | Mức | Ứng phó |
|---|---|---|
| Manager/Auditor gọi API ngoài phạm vi | Cao | `resolve_scope`/`resolve_compare` + test 403 |
| Compare set vô tình mở quyền | Cao | Compare chỉ là bộ lọc trên tập authorized; test |
| **`test_auth_matrix.py` đỏ vì route mới** | Cao | Cập nhật `MATRIX`/`REQUESTS`/`ALLOWED_STATUS` cùng lúc với `main.py` (§8.2 bước 4) |
| **Lệch số Dashboard vs sync DS-05** | Trung bình | Ghi rõ §7.6; chỉ đối chiếu tổng toàn kỳ |
| **`is_active = 0` bị coi là mâu thuẫn** | Trung bình | Ghi rõ là ngoại lệ có chủ đích (§7.2); ghi vào `openapi.yaml` |
| Nhầm dữ liệu demo với thật | Trung bình | Hiện nguồn API; runbook; không special-case `HIST-` |
| Timestamp sai làm lệch biểu đồ | Trung bình | Phân loại + badge + `include_suspect`; không ghi đè |
| LiveCharts2 font/DPI | Trung bình | M0; fallback OxyPlot |
| Migration khoá bảng | Trung bình | Chạy ngoài giờ |
| Hiểu nhầm Admin-only | Thấp | Ghi rõ UI Admin-only, API 3 role |

### 9.5 Đã chốt và còn mở

**Đã chốt (v6):** API-backed; WinForms Admin-only, API Admin/Auditor/Manager; HQ loại có chủ đích; `occurred_at` + phân loại (hàm thuần ở `services/`, console không tự phân loại); 3 danh mục + nhãn UI; LiveCharts2; 30 s; tách phạm vi xem/so sánh; `[from,to)`; naive = UTC; `compare_store_ids` lặp; DUPLICATE giữ bản đầu; `quality` giữ khi `include_suspect=false`; `is_active=0` là ngoại lệ; DS-05 đối chiếu ở mức tổng.

**Còn mở:**
1. **API role matrix:** giữ Admin/Auditor/Manager (theo điểm 3) hay Admin-only (theo v4)? Kế hoạch đang theo hướng đầu.
2. Cửa hàng `is_active = 0` có trong bộ lọc/so sánh không? (đề xuất: có, nhãn "đã đóng" — đã ghi là ngoại lệ §7.2)
3. Tab "Giao dịch và audit" hiện cả "Giờ bán"/"Giờ nhận"?
4. Nhãn `Bakery` → "Bánh nướng"?
5. Nếu M0 thất bại với LiveCharts2: OxyPlot hay xem demo trước?

---

## 10. Rà soát nhất quán

| Điểm kiểm tra | Kết quả |
|---|---|
| UI vs API quyền | UI chỉ Admin (token admin); API Admin/Auditor/Manager — khác nhau **có chủ đích**, ghi rõ mục 2.4 |
| 3 biểu đồ đúng phạm vi | Đường/tròn = phạm vi xem; cột = tập so sánh trong quyền; cùng `From/To` |
| API nào bỏ qua phân quyền | Không: cả 4 endpoint gọi `require_role`; charts 1-2 gọi `resolve_scope`; chart 3 gọi `resolve_compare`; `/dashboard/stores` lọc theo vai trò (bảng §7.2) |
| Demo vs thật | Mục 6.10: hiện nguồn, runbook, không special-case `HIST-` |
| Migration | Chỉ 004, sau 001–003; không 005; thứ tự mục 8.2 (có bước cập nhật `test_auth_matrix.py`) |
| Công thức doanh thu | Một công thức, không lọc status; `CANCELLATION` dùng lại item của SALE gốc (§5.2); test đối chiếu `sales_summary_line` |
| Tiền | JSON number 2 chữ số thập phân |
| Thời gian | `[from,to)`; `/audit-logs` cùng ngữ nghĩa; naive = UTC; UTC+7; `occurred_at` không bị ghi đè |
| Dashboard vs DS-05 | Hai mốc khác nhau **có chủ đích**; chỉ đối chiếu tổng toàn kỳ (§7.6) |
| `is_active = 0` | Ngoại lệ có chủ đích của Dashboard (§7.2); các API khác vẫn loại |
| RBAC chung | Không sửa `security.py`/route cũ |

---

## 11. Phụ lục — tham chiếu

| Nội dung | Vị trí |
|---|---|
| Tab/refresh/Guard | `MainForm.cs:139-144`, `:301-374`, `:829-860` |
| 404 rule | `MainForm.cs:628-664`; `FeatureAvailability.cs` |
| API client / SQL guard | `DemoApiClient.cs:47-88`; `ReadOnlySql.cs:63-71` |
| RBAC | `security.py:21-28`, `:76-99`; `inventory.py:19-28` |
| Ghi giao dịch | `repositories/idempotency.py:19-22`; `services/idempotency.py:15-29` |
| Công thức doanh thu | `repositories/aggregation.py:43-57` |
| Schema | `001_core.sql:5,43,59,76,90`; `002:17` |
| Seed Admin | `seed/002_demo_catalog.sql:41-42` |
| Token demo | `scripts/issue_demo_tokens.py:22-30` |
| Lịch sử | `history_generator/loader.py:37-72` |
| Runner migration | `database/migrate.sh` |
| LiveCharts2 2.0.5 | `https://api.nuget.org/v3-flatcontainer/livechartscore.skiasharpview.winforms/2.0.5/livechartscore.skiasharpview.winforms.nuspec` |
| Contract-first | `README.md:264` |
| Console là công cụ demo | `clients/demo-console/README.md:3` |
| RBAC matrix test (bắt buộc cập nhật) | `middleware/tests/test_auth_matrix.py:288`, `:310` |
| Ngữ nghĩa audit `[from,to)` | `middleware/app/repositories/audit.py:11-26` |
| CANCELLATION dùng lại item SALE | `middleware/app/services/pos_cancellation.py:44`, `:53` |
| Sync theo `created_at` | `middleware/app/repositories/aggregation.py:21-40`; `services/aggregation.py:24`; `docs/design/DS-05_Sync_Consistency_Design.md:59` |
