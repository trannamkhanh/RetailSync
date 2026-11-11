# Store Web — xem sản phẩm theo từng cửa hàng

Web bán hàng/tra cứu của RetailSync. Khách hàng tìm món hàng và được chỉ tới **cửa hàng gần nhất
còn sẵn hàng**; nhân viên vẫn tra cứu được danh mục và tồn kho chi tiết theo từng chi nhánh.

```text
web/ (React SPA) ──/api/*──> api/ (FastAPI) ──SELECT──> SQL Server (RTS_DB_DEMO)
                                    └──────────INSERT──> SQL Server (RTS_CUSTOMER)
```

Kiến trúc: **SPA + API riêng**. `api/` trả JSON, `web/` là React 19 + TypeScript + Vite.
Chạy bản build thì API phục vụ luôn `web/dist` → **1 tiến trình, 1 cổng 5180**.

Hai vùng dữ liệu tách biệt: dữ liệu cửa hàng **chỉ đọc**, tài khoản khách hàng nằm ở database
riêng `RTS_CUSTOMER` (ghi được). Không sửa `middleware/`, không thêm service vào `compose.yaml`.

## 1. Yêu cầu

| Thành phần | Ghi chú |
|---|---|
| Python | 3.12 khuyến nghị; 3.11 cũng chạy (đã kiểm trên máy này). `pyodbc==5.2.0` có wheel cho cả hai |
| Node | ≥ 20.19 hoặc ≥ 22.12 (Vite 8). Máy đã kiểm: **Node 24.13.0**, **pnpm 12.18.0** |
| pnpm | `pnpm --version` phải chạy được; lockfile đã commit |
| Docker Desktop | Chạy SQL Server và `migrate` |
| ODBC Driver 18 (64-bit) | Cho `pyodbc` khi chạy Python native |
| Microsoft Edge/Chrome | Mở `http://127.0.0.1:5180` |

Phiên bản đã cài thực tế khi dựng app: React 19.3.1, react-router-dom 7.18.5,
@tanstack/react-query 5.107.1, Vite 8.3.6, TypeScript 7.0.2, Vitest 5.1.0, msw 3.0.4, jsdom 31.0.0.

## 2. Chuẩn bị cơ sở dữ liệu (một lần)

Từ thư mục gốc repo:

```powershell
docker compose up -d --wait sqlserver
docker compose run --rm migrate
```

CSDL demo mặc định là `RTS_DB_DEMO` (đọc `DB_NAME` trong `.env`). Seed cho 3 cửa hàng; mỗi cửa
hàng bán 9 SKU chung `SKU-0001..0009`, cộng thêm mặt hàng riêng theo ngành:
`STORE-DN1` rau/trứng, `STORE-DN2` đồ uống, `STORE-DN3` đồ gia dụng
(`database/seed/005_demo_store_assortment.sql`).
Tồn 40/25/15 mỗi SKU chung, và mỗi `(store, sku)` có 2 lô: một hết hạn sau 3 ngày (~40% số lượng),
một hết hạn +10/+20/+180 ngày theo danh mục. Vì vậy bản demo **không có lô hết hạn** —
`expired_units = 0`; trường hợp hết hạn được kiểm bằng fixture của test.

Sau đó tạo CSDL tài khoản khách hàng (một lần, idempotent):

```powershell
cd clients/store-web/api
.\.venv\Scripts\python.exe tools\init_customer_db.py
```

Lệnh này tạo database `RTS_CUSTOMER` và 3 bảng `customer`, `customer_session`,
`customer_address`. API cũng tự tạo bảng khi khởi động nếu thiếu, nhưng database phải tồn tại.

## 3. Chạy bản demo (1 tiến trình, 1 cổng)

**Bắt buộc build web trước**, nếu không `GET /` trả 404 kèm hướng dẫn trong log:

```powershell
cd clients/store-web/api
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

cd ..\web
pnpm install
pnpm build

cd ..\api
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 5180
```

Mở `http://127.0.0.1:5180`.

> Đổi `py -3.12` thành `py -3.11` nếu máy chưa có 3.12.

## 4. Chạy ở chế độ phát triển (2 tiến trình, hot reload)

```powershell
# Terminal 1 — API
cd clients/store-web/api
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 5180 --reload

# Terminal 2 — SPA
cd clients/store-web/web
pnpm dev            # http://127.0.0.1:5173, /api proxy sang 5180
```

Vite proxy `/api` sang 5180 nên không cần CORS khi dev bình thường. CORS chỉ mở khi
`STORE_WEB_CORS_ORIGINS` có giá trị.

## 5. Cấu hình

Đọc `.env` ở repo root (biến có sẵn của repo, không thêm biến bắt buộc):

| Biến | Ý nghĩa |
|---|---|
| `DB_HOST`, `SQLSERVER_PORT` | Địa chỉ SQL Server (mặc định `127.0.0.1`, `14333`) |
| `DB_NAME` | CSDL đọc khi không có `STORE_WEB_DB_NAME` (demo: `RTS_DB_DEMO`) |
| `MSSQL_SA_PASSWORD` | Mật khẩu `sa`; bắt buộc để kết nối |
| `BUSINESS_UTC_OFFSET_HOURS` | Múi giờ nghiệp vụ, mặc định 7 |

Biến riêng của app (đều tuỳ chọn):

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `STORE_WEB_DB_NAME` | `DB_NAME` | CSDL cửa hàng app đọc (chỉ đọc) |
| `STORE_WEB_CUSTOMER_DB_NAME` | `RTS_CUSTOMER` | CSDL tài khoản khách hàng (ghi được) |
| `STORE_WEB_TEST_DB_NAME` | `RTS_WEB_TEST` | CSDL cửa hàng cho `pytest`; **phải** kết thúc `_TEST` |
| `STORE_WEB_TEST_CUSTOMER_DB_NAME` | `RTS_CUSTOMER_TEST` | CSDL khách cho `pytest` |
| `STORE_WEB_SESSION_HOURS` | `168` (7 ngày) | Thời hạn phiên đăng nhập, 1–720 giờ |
| `STORE_WEB_CORS_ORIGINS` | rỗng | Danh sách origin cho dev, cách nhau dấu phẩy |
| `STORE_WEB_OSRM_URL` | `https://router.project-osrm.org` | Máy chủ OSRM tính quãng đường đi. Rỗng = tắt routing, luôn dùng đường chim bay |
| `STORE_WEB_OSRM_TIMEOUT_SECONDS` | `2` | Timeout mỗi request routing (0–15 giây); quá hạn thì fallback |

`web/.env.example` có `VITE_API_BASE_URL` (rỗng = same-origin, dùng proxy hoặc bản build).

## 6. Giao diện

Hướng dẫn dùng giao diện (từng màn hình, bộ lọc, trạng thái, sự cố) nằm ở **`web/README.md`**.
Tóm tắt route:

| Route | Nội dung |
|---|---|
| `/` | Shop: tìm món hàng, gợi ý **cửa hàng gần nhất còn hàng** |
| `/login`, `/register` | Đăng nhập / tạo tài khoản khách |
| `/account` | Thông tin khách + sổ địa chỉ đã lưu |
| `/stores` | 3 thẻ cửa hàng: tên, khu vực, số SKU, tổng đơn vị bán được |
| `/stores/:storeId` | Tìm kiếm, danh mục, "chỉ còn hàng", sắp xếp; bảng sản phẩm; phân trang |
| `/stores/:storeId/products/:sku` | Thẻ sản phẩm + bảng lô; lô hết hạn gạch ngang |
| `*` | "Không tìm thấy trang" + link về danh sách cửa hàng |

## 7. Dữ liệu và quy tắc

- **`quantity` không phải "còn bán".** `inventory.quantity` gồm cả hàng đã hết hạn. Cột "Còn bán"
  hiển thị `sellable_quantity` = tổng batch có `expiry_date >= today_local`.
- **`today_local()`**, không `GETDATE()`: `(now_utc + BUSINESS_UTC_OFFSET_HOURS).date()`.
  Lô hết hạn **đúng hôm nay vẫn bán được** (`>=`), giống `middleware/`.
- **Cờ `sellable` do API quyết** cho từng lô. Web không tự so `expiry_date` với `new Date()` —
  làm vậy máy người xem sai múi giờ/giờ hệ thống là hiển thị sai ngay.
- `expired_quantity` = tổng batch riêng, **không** suy ra từ `quantity - sellable_quantity`.
- SKU có trong danh mục nhưng không có dòng `inventory` tại cửa hàng → 0, không phải lỗi.
  Trang `/stores/:storeId` liệt kê **toàn bộ danh mục**, kèm cột "Gần nhất còn hàng": cửa hàng đang
  xem nếu nó có hàng (`tại đây`), ngược lại là cửa hàng gần nhất còn `sellable_quantity > 0`. Nhờ
  vậy khách thấy được món mình cần dù chi nhánh đang xem không bán. `product_count` ở header là số
  SKU **cửa hàng này** nhập, khác với `total` của trang.
- `store.is_active = 0` → không có trong `/api/stores`, và 404 ở mọi route chi tiết.
- Tiền là **string** `"32000.00"` trong JSON; web chỉ format để hiển thị.
- **Ảnh sản phẩm** là cột `dbo.product.image_url` (nullable), chứa **URL tương đối** như
  `/products/fresh-milk.jpg`. File nằm ở `web/public/products/` nên `pnpm build` chép sang
  `web/dist/products/` và API phục vụ luôn — không gọi dịch vụ ảnh bên ngoài, không cần mạng.
  Ảnh là **ảnh thật** tải từ Wikimedia Commons bằng `python tools\fetch_product_photos.py`
  trong `api/`; tác giả và giấy phép của từng file nằm ở
  `web/public/products/ATTRIBUTION.md`. `tools\generate_product_images.py` vẫn sinh được
  bộ minh hoạ SVG phẳng, nhưng seed không còn trỏ tới chúng.
  Sản phẩm không có ảnh (hoặc file hỏng) hiện ô chữ cái đầu thay vì icon ảnh lỗi.
- **Gợi ý cửa hàng** chỉ xét cửa hàng còn `sellable_quantity > 0`; khoảng cách là **quãng đường đi
  thực tế** lấy từ OSRM (`STORE_WEB_OSRM_URL`), làm tròn 100 m, tính ở API. Một request `table`
  cho mỗi lần tìm kiếm: một điểm gốc, mọi cửa hàng ứng viên cùng lúc. Không có cửa hàng nào còn
  hàng → `nearest = null`.
- Mỗi gợi ý mang theo `distance_kind`: `"road"` là quãng đường đi, `"straight"` là **phương án dự
  phòng** (đường chim bay). OSRM lỗi, timeout, hoặc URL rỗng → API vẫn trả lời bằng haversine và
  ghi `"straight"`; web hiện thêm nhãn "(đường chim bay)" để không đánh tráo hai loại số này.
- **Tài khoản khách** nằm ở CSDL riêng `RTS_CUSTOMER`: mật khẩu PBKDF2-SHA256 (210.000 vòng),
  session token ngẫu nhiên 32 byte và CSDL chỉ lưu SHA-256 của token.

Đây là **bản sao chỉ đọc** của tồn kho; nguồn sự thật vẫn là `middleware/app/services/inventory.py`.

## 8. Kiểm thử

**API** cần SQL Server và 2 CSDL test riêng `RTS_WEB_TEST` + `RTS_CUSTOMER_TEST`
(không dùng `RTS_DB_TEST` của nhóm):

```powershell
cd G:\RetailSync
$env:DB_NAME = "RTS_WEB_TEST"; docker compose run --rm migrate; Remove-Item Env:DB_NAME

cd clients/store-web/api
$env:STORE_WEB_TEST_DB_NAME = "RTS_WEB_TEST"
$env:STORE_WEB_TEST_CUSTOMER_DB_NAME = "RTS_CUSTOMER_TEST"
.\.venv\Scripts\python.exe -m pytest -q
```

`conftest.py` **fail cứng** nếu tên CSDL test không kết thúc `_TEST` hoặc trùng CSDL ứng dụng.
Mỗi test chạy trong transaction và rollback, nên không để lại dữ liệu.

Kiểm tra luồng khách hàng trên server đang chạy (đăng ký → địa chỉ → tìm kiếm → đăng xuất):

```powershell
.\.venv\Scripts\python.exe tools\smoke_customer_flow.py
```

**Web** không cần DB và không cần API thật (Vitest + jsdom + msw):

```powershell
cd clients/store-web/web
pnpm test           # 30 test
pnpm typecheck      # tsc --noEmit
pnpm lint           # oxlint
```

Kết quả đã kiểm: `pytest` **58 passed**, `pnpm test` **38 passed**, `typecheck` và `lint` sạch,
cộng 18 kiểm tra luồng khách hàng qua HTTP thật (`tools/smoke_customer_flow.py`).

Suite không gọi mạng: `conftest.py` trỏ `STORE_WEB_OSRM_URL` vào một cổng đóng, nên mọi test
đi qua nhánh fallback `"straight"`. Test của `app/routing.py` dùng `httpx.MockTransport` để kiểm
cả nhánh `"road"` lẫn các kiểu lỗi (500, timeout, payload sai).

`middleware/pytest.ini` đặt `testpaths = tests` nên suite của middleware không quét vào app này,
và `api/pytest.ini` cũng chỉ quét `api/tests`.

## 9. Xử lý sự cố

| Hiện tượng | Việc cần làm |
|---|---|
| **`/` trả 404** | Chưa `pnpm build`. Chạy `pnpm build` trong `web/` rồi khởi động lại API; log có WARNING nói đúng việc này |
| Đăng nhập/đăng ký lỗi máy chủ | Chưa có CSDL khách: chạy `python tools\init_customer_db.py` |
| `IM002` / "Can't open lib" | Cài ODBC Driver 18 (64-bit), hoặc chạy trong container |
| Login failed | Sai `MSSQL_SA_PASSWORD`; đổi mật khẩu trong `.env` không đổi mật khẩu của volume đã tạo |
| CORS khi dev | Dùng đúng `pnpm dev` (proxy `/api`); hoặc đặt `STORE_WEB_CORS_ORIGINS=http://127.0.0.1:5173` |
| Port 5180/5173 bận | Đổi cổng uvicorn và `server.proxy` trong `vite.config.ts` |
| `pytest` fail vì không kết nối được DB test | Chạy lại bước tạo `RTS_WEB_TEST` ở mục 8 |
| Chữ Việt hiện dấu `?` trong CSDL khách | Cột phải là `nvarchar`; model ORM dùng `Unicode`, không dùng `String` |
| Khoảng cách hiện "(đường chim bay)" | OSRM không truy cập được: kiểm `STORE_WEB_OSRM_URL`, mạng ra ngoài, hoặc tăng `STORE_WEB_OSRM_TIMEOUT_SECONDS`. Đặt URL rỗng nếu muốn luôn dùng đường chim bay |

Sự cố phía giao diện (trang trắng, GPS, tải asset lỗi): xem `web/README.md` mục 8.

## 10. Ghi chú kỹ thuật

- **Hai vùng ghi tách biệt**: `api/app/queries/` chỉ đọc CSDL cửa hàng; chỉ `auth`/`shop` ghi vào
  `RTS_CUSTOMER`. `tests/test_read_only.py` kiểm cả tĩnh (chuỗi SQL) lẫn động (`COUNT(*)` trước/sau).
- **Unicode**: model ORM của khách dùng `sqlalchemy.Unicode`, không dùng `String`. Trên SQL Server
  `String` bind thành `VARCHAR` theo code page cp1252, làm mất dấu tiếng Việt; `Unicode` bind
  `NVARCHAR` khớp cột `nvarchar` mà DDL tạo ra.
- Không sửa `middleware/`, `compose.yaml`, `database/`, `docs/design/openapi.yaml`.
- **Khoảng cách đi đường** nằm ở `api/app/routing.py`, tách khỏi `app/recommend.py` (xếp hạng) và
  `app/geo.py` (haversine). Routing là best-effort: `httpx` gọi OSRM `table` với timeout ngắn,
  mọi lỗi đều rơi về haversine và gắn cờ `distance_kind`, nên một dịch vụ ngoài chết không làm
  hỏng trang bán hàng. Thứ tự xếp hạng giữ nguyên: `(distance_km, store_id)`.
- Địa chỉ cửa hàng là cột `dbo.store.address_text` (`nvarchar(300)`, nullable) thêm bởi
  `database/migrations/004_store_address.sql`; seed ở `database/seed/004_demo_store_addresses.sql`.
  Cột nullable để nhánh chưa có migration vẫn INSERT được và code cũ không đổi hành vi.
- Ảnh sản phẩm là cột `dbo.product.image_url` (`nvarchar(300)`, nullable) thêm bởi
  `database/migrations/005_product_image.sql`; seed ở `database/seed/006_demo_product_images.sql`.
  Giá trị là URL tương đối, file SVG nằm trong `web/public/products/`.
- Truy vấn danh sách là **3 câu cố định** (trang + `COUNT(*)` + batch của trang), không N+1;
  `sellable`/`expired`/`nearest_expiry` tính bằng `OUTER APPLY` trong cùng câu để lọc và sắp xếp đúng.
- Tham số chuỗi được `CAST` về đúng kiểu cột (`varchar(10)`/`varchar(50)`) để không mất index seek
  do `CONVERT_IMPLICIT` (issue #25). Không dùng `NOLOCK`.
- Tên sản phẩm sắp xếp theo `p.name` với collation mặc định của SQL Server; không thêm collation
  tiếng Việt riêng ở phase này.
- API của app này **không** phải API của middleware. Đường lui (khi nhóm duyệt thêm endpoint vào
  middleware) chỉ đổi base URL: xem `PLAN.md` mục 11.
