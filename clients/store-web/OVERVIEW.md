# Store Web — mô tả và phạm vi thay đổi

> Tài liệu tổng hợp cho nhóm review. Trả lời hai câu hỏi: **web này là gì** và **đã sửa gì ngoài
> `clients/store-web/`**. Mọi số liệu dưới đây lấy từ nhánh `Quang` tại commit `8765ad6`
> (ngày 11/11/2026), không phải từ kế hoạch.

---

## 1. Tóm tắt một đoạn

Store Web là một ứng dụng **độc lập** trong repo, đặt tại `clients/store-web/`, cùng mô hình với
`clients/demo-pos/` và `hq-demo/`: chạy bằng lệnh riêng, không phải service của `compose.yaml`,
không sửa `middleware/`. Nó cho khách xem danh mục sản phẩm, tìm món hàng và được chỉ tới cửa hàng
gần nhất còn hàng; cho nhân viên tra tồn kho chi tiết theo lô tại từng chi nhánh.

Gồm hai tiểu dự án:

| Thư mục | Công nghệ | Vai trò |
|---|---|---|
| `api/` | FastAPI (Python), chỉ JSON | Đọc CSDL cửa hàng (chỉ đọc), quản lý tài khoản khách (CSDL riêng), phục vụ luôn bản build SPA |
| `web/` | React 19 + TypeScript + Vite | Giao diện SPA, gọi `/api/*` |

Ở chế độ demo: `pnpm build` một lần, sau đó `uvicorn` → **1 tiến trình, 1 cổng 5180**. Không CORS,
không hai server, không cần mạng.

```text
web/ (React SPA) ──/api/*──> api/ (FastAPI) ──SELECT──> SQL Server (RTS_DB_DEMO, chỉ đọc)
                                     └──────────INSERT──> SQL Server (RTS_CUSTOMER, ghi được)
```

---

## 2. Vì sao có app này

Middleware sẵn có **không đủ** để dựng một web tra cứu:

| API của middleware | Thiếu gì |
|---|---|
| `GET /api/v1/stores/{store_id}/inventory` | Không trả `name`, `unit_price`, `category`; token Staff chỉ đọc đúng store của mình (403 nếu khác); không có endpoint liệt kê cửa hàng |
| `GET /api/v1/products/barcode/{barcode}` | Tra theo barcode chứ không theo SKU; chỉ role Staff; không có batch |
| `POST /api/v1/admin/stores` | Là POST, cần role Admin; không có GET tương ứng |

Sửa `middleware/` cho mục đích cá nhân là việc không được phép trong task này, nên app tự đọc CSDL
và tự định nghĩa API. Đường lui đã ghi trong `PLAN.md` mục 11: nếu nhóm đồng ý thêm endpoint vào
middleware với **cùng shape JSON** thì chỉ đổi base URL, không phải viết lại giao diện.

---

## 3. Chức năng đã có

### 3.1. Với khách hàng

- **Tìm món hàng** (`GET /api/shop/search`): gõ tên, nhận danh sách sản phẩm kèm **cửa hàng gần nhất
  còn hàng** và khoảng cách.
- **Khoảng cách là quãng đường đi thực tế** (OSRM), không phải đường chim bay. OSRM lỗi/timeout/không
  cấu hình → tự rơi về haversine và gắn cờ `distance_kind = "straight"`; web hiện nhãn
  "(đường chim bay)" để không đánh tráo hai loại số.
- **Tài khoản khách**: đăng ký, đăng nhập, đăng xuất, xem thông tin. Mật khẩu PBKDF2-HMAC-SHA256
  210.000 vòng; session token 32 byte ngẫu nhiên, **CSDL chỉ lưu SHA-256 của token**, cookie httpOnly.
- **Sổ địa chỉ**: lưu tối đa 20 địa chỉ để tìm lại nhanh; danh sách địa chỉ mẫu cho người không
  chia sẻ vị trí.

### 3.2. Với nhân viên / người xem danh mục

- **Danh sách cửa hàng**: tên, khu vực, số SKU cửa hàng đó nhập, tổng đơn vị bán được.
- **Danh mục theo cửa hàng**: tìm theo tên/SKU, lọc danh mục, lọc "chỉ còn hàng", sắp xếp theo
  tên/giá/còn bán, phân trang.
- **Cột "Gần nhất còn hàng"**: trang cửa hàng liệt kê **toàn bộ danh mục**, kèm chỉ dẫn nơi khác
  còn hàng — nhờ vậy khách vẫn thấy món mình cần dù chi nhánh đang xem không bán.
- **Chi tiết sản phẩm**: thẻ sản phẩm + bảng lô (mã lô, hạn dùng, số lượng); lô hết hạn gạch ngang,
  có nhãn.
- **Ảnh sản phẩm thật** (Wikimedia Commons), phục vụ từ chính SPA; tác giả và giấy phép ghi trong
  `web/public/products/ATTRIBUTION.md`. Sản phẩm không có ảnh → ô chữ cái đầu.

### 3.3. Route

| Giao diện | API |
|---|---|
| `/` — shop, tìm kiếm | `GET /api/shop/search`, `GET /api/shop/addresses` |
| `/login`, `/register` | `POST /api/auth/login`, `POST /api/auth/register` |
| `/account` — thông tin + địa chỉ | `GET /api/auth/me`, `GET/POST/DELETE /api/shop/addresses/mine` |
| `/stores` | `GET /api/stores` |
| `/stores/:storeId` | `GET /api/stores/{id}`, `GET /api/stores/{id}/products`, `GET /api/categories` |
| `/stores/:storeId/products/:sku` | `GET /api/stores/{id}/products/{sku}` |
| `*` — không tìm thấy | — |
| — | `GET /api/health` |

Chi tiết từng field: `PLAN_DETAIL.md` mục 5. Hướng dẫn dùng giao diện: `web/README.md`.

---

## 4. Quy tắc dữ liệu (những chỗ dễ sai nhất)

1. **`inventory.quantity` không phải "còn bán".** Nó gồm cả hàng đã hết hạn. Cột "Còn bán" dùng
   `sellable_quantity` = tổng batch có `expiry_date >= today_local`.
2. **`today_local()`, không `GETDATE()`.** `(now_utc + BUSINESS_UTC_OFFSET_HOURS).date()`. Lô hết hạn
   **đúng hôm nay vẫn bán được** (`>=`), giống middleware.
3. **Cờ `sellable` do API quyết** cho từng lô; web không tự so `expiry_date` với `new Date()` của
   máy người xem.
4. `expired_quantity` tính riêng, **không** suy ra từ `quantity - sellable_quantity`.
5. SKU có trong danh mục nhưng không có `inventory` tại cửa hàng → 0, không phải lỗi.
6. `store.is_active = 0` → không có trong `/api/stores`, 404 ở mọi route chi tiết.
7. Tiền là **string** `"32000.00"` trong JSON; web chỉ format để hiển thị.
8. **Hai vùng ghi tách biệt**: `api/app/queries/` chỉ SELECT trên CSDL cửa hàng; chỉ `auth`/`shop`
   INSERT vào `RTS_CUSTOMER`. `api/tests/test_read_only.py` kiểm cả tĩnh (chuỗi SQL) lẫn động
   (`COUNT(*)` trước/sau).

Đây là **bản sao chỉ đọc** của tồn kho; nguồn sự thật vẫn là `middleware/app/services/inventory.py`.

---

## 5. Kiểm chứng (chạy lại trong phiên này)

| Bộ kiểm | Lệnh | Kết quả |
|---|---|---|
| API (cần SQL Server + `RTS_WEB_TEST`, `RTS_CUSTOMER_TEST`) | `pytest -q` trong `api/` | **58 passed** |
| Giao diện (không cần DB, dùng msw) | `pnpm test` trong `web/` | **38 passed** / 7 file |
| Kiểu | `pnpm typecheck` | exit 0 |
| Lint | `pnpm lint` (oxlint) | sạch, 41 file / 116 rule |
| Test seed của middleware bị ảnh hưởng | `pytest tests/test_seed_demo_catalog.py` | **6 passed** |

Suite của middleware **không** bị ảnh hưởng cơ chế: `middleware/pytest.ini` đặt `testpaths = tests`,
và `api/pytest.ini` cũng chỉ quét `api/tests`.

Số liệu trong repo: 165 file được track trong `clients/store-web/`, gồm 25 file `.py` của API,
8 file test API, 7 file test giao diện, 42 ảnh sản phẩm (1.3 MB) và 19 ảnh chụp màn hình (3.1 MB).

---

## 6. Đã thay đổi gì ngoài `clients/store-web/`

**9 file, +224 / −5 dòng.** Không có file nào của `middleware/app/`, không có `compose.yaml`,
không có `openapi.yaml`.

### 6.1. Migration mới (2 file)

| File | Nội dung | Vì sao an toàn |
|---|---|---|
| `database/migrations/004_store_address.sql` | Thêm cột `dbo.store.address_text nvarchar(300) NULL` + CHECK độ dài 1–300 | Cột **nullable**; nhánh/branch chưa có migration vẫn INSERT được, code cũ không đổi hành vi. Mỗi `ALTER` là một batch riêng vì SQL Server biên dịch cả batch trước khi chạy |
| `database/migrations/005_product_image.sql` | Thêm cột `dbo.product.image_url nvarchar(300) NULL` + CHECK độ dài 1–300 | Như trên; sản phẩm không có ảnh vẫn render (placeholder) |

Cả hai **forward-only**, không sửa migration đã áp dụng.

### 6.2. Seed mới (3 file) và một seed bị sửa (1 file)

| File | Thay đổi |
|---|---|
| `database/seed/004_demo_store_addresses.sql` | **Mới.** Địa chỉ đường cho 3 cửa hàng demo; chỉ điền khi `address_text IS NULL` nên chạy lại vô hại |
| `database/seed/005_demo_store_assortment.sql` | **Mới.** Thêm 12 SKU (`SKU-0010..0021`: rau/trái cây, đồ uống, đồ gia dụng, trứng, sữa chua, sandwich) + dòng `inventory` **chỉ cho cửa hàng tương ứng** + lô hàng cho dòng mới. Idempotent: chỉ thêm khi chưa có |
| `database/seed/006_demo_product_images.sql` | **Mới.** Gán `image_url` tương đối (`/products/<tên>.jpg`) cho từng SKU; chỉ điền khi trống hoặc còn trỏ ảnh SVG cũ |
| `database/seed/002_demo_catalog.sql` | **Sửa 7/1.** `SKU-0007` đổi `Rice 5kg / 120000` → `Rice 50kg / 1250000` cho khớp ảnh; thêm `UPDATE` có điều kiện `AND name = N'Rice 5kg'` để nâng cấp CSDL đã seed mà **không ghi đè** chỉnh sửa tay của người vận hành |

### 6.3. Ba file cập nhật theo tên SKU-0007 (1/1 mỗi file)

| File | Thay đổi |
|---|---|
| `middleware/tests/test_seed_demo_catalog.py` | Giá trị kỳ vọng của `SKU-0007` trong dict `PRODUCTS`: `("Rice 50kg", 1250000)` |
| `clients/demo-pos/DemoPos/appsettings.json` | Danh mục mock của Demo POS: `Rice 50kg`, `1250000` |
| `docs/design/DS-08_Staff_App_Wireframes.html` | Một dòng bảng mẫu trong wireframe: `Rice 50kg` |

Ba thay đổi này là hệ quả trực tiếp của việc seed đổi tên; không đổi logic, không đổi hợp đồng.

### 6.4. Những file **không** bị đụng tới (đã kiểm bằng `git diff`)

`README.md` (gốc), `.gitignore`, `.env.example`, `compose.yaml`, `database/migrate.sh`,
`middleware/app/**` (toàn bộ mã nguồn middleware), `docs/design/openapi.yaml`, `scripts/**`.

Vì vậy app **không** thêm service vào stack chung và **không** làm thay đổi API của middleware.

---

## 7. Ảnh hưởng cần nhóm biết

### 7.1. Seed làm đổi số dòng tồn kho của 3 cửa hàng demo

`005_demo_store_assortment.sql` thêm dòng `inventory` riêng theo ngành. Đo trên `RTS_DB_DEMO`
bằng `sqlcmd` sau khi migrate:

| Cửa hàng | Số SKU trước | Số SKU sau |
|---|---|---|
| `STORE-DN1` | 9 | **14** |
| `STORE-DN2` | 9 | **14** |
| `STORE-DN3` | 9 | **13** |

**Hệ quả có thật:** `scripts/demo/sprint2_smoke.py:280` khẳng định
`len(body["items"]) == 9` cho `GET /stores/STORE-DN1/inventory`. Trên CSDL demo vừa migrate, con số
thật là **14**, nên **kiểm tra số 10 của smoke test Sprint 2 sẽ fail**. File này không bị sửa trong
nhánh này (đúng phạm vi), nên cần một trong hai: sửa assertion thành so với số dòng thực của
`inventory`, hoặc chấp nhận smoke test chỉ đúng trên CSDL seed cũ.

Ngược lại, `middleware/tests/test_seed_demo_catalog.py` **vẫn xanh** vì nó đếm trong phạm vi 9 SKU
của `PRODUCTS` (27 dòng), không đếm toàn bộ bảng — đã chạy lại: 6 passed.

### 7.2. Tài liệu còn nói 9 SKU

Các chỗ sau vẫn mô tả danh mục là "9 SKU"; vẫn đúng với 9 SKU chung nhưng không còn là tổng:

- `clients/demo-pos/README.md:112` — "9 SKU đúng seed"
- `docs/demo/Sprint_2_Demo.md:71` — "`200` (9 SKU)" cho check Staff đọc `STORE-DN1`
- `database/seed/002_demo_catalog.sql:28` — comment "27 rows: 3 stores x 9 SKUs" (đúng với câu lệnh đó)

### 7.3. `PLAN.md` đã lỗi thời ở dòng trạng thái

`clients/store-web/PLAN.md:6` vẫn ghi "bản kế hoạch, chưa code" trong khi app đã thi công xong
(`PLAN_DETAIL.md:7` ghi "đã thi công xong 10/11/2026"). Nên sửa dòng đó hoặc gộp hai file.

### 7.4. Nhánh chưa push

`origin/Quang` vẫn ở `3925b22`; commit `8765ad6` chỉ có ở máy local. Muốn nhóm xem trên GitHub thì
phải push.

---

## 8. Đường lui

Nếu nhóm quyết định đưa tính năng vào sản phẩm chính:

1. Thêm `GET /stores` và `GET /stores/{store_id}/products` vào `middleware/`, theo quy ước
   "sửa `openapi.yaml` trước".
2. Giữ **cùng shape JSON** với `PLAN_DETAIL.md` mục 5 → giao diện không phải sửa.
3. Đổi base URL của SPA sang `https://localhost:8443/api/v1`; bật CORS hoặc dùng proxy.
4. Xoá `api/app/queries/` và `api/app/db.py`; giữ `web/`.

Nếu nhóm **không** muốn app trong repo: xoá nguyên thư mục `clients/store-web/` và 9 file ở mục 6.
Hai migration đã áp dụng thì để nguyên (cột nullable, không ai đọc là vô hại); ba seed mới có thể
giữ hoặc bỏ, đều idempotent.

---

## 9. Đọc thêm

| File | Nội dung |
|---|---|
| `PLAN.md` | Phạm vi, quyết định, lý do, đường lui |
| `PLAN_DETAIL.md` | Kế hoạch thi công từng task + hợp đồng API chốt |
| `README.md` | Cài đặt, cấu hình, chạy, kiểm thử, xử lý sự cố |
| `web/README.md` | Hướng dẫn dùng giao diện, bộ lọc trong URL, trạng thái |
| `screenshots/` | 19 ảnh chụp từng màn hình |
