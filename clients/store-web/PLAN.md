# Kế hoạch: Store Web — xem sản phẩm theo từng cửa hàng

> Ứng dụng phụ **nằm trong repo** tại `clients/store-web/`, cùng mô hình với `clients/demo-pos/`:
> một app độc lập, chạy riêng, team xem được, **không sửa `middleware/`**.
> Kiến trúc: **SPA + API riêng** — `api/` FastAPI chỉ trả JSON, `web/` React + TypeScript (Vite).
> Trạng thái: bản kế hoạch, chưa code. Người làm: Quang. Nhánh: `Quang` → `main` (qua PR khi nhóm duyệt).

---

## 1. Mục tiêu & phạm vi

**Mục tiêu.** Web đọc (read-only): danh sách cửa hàng → chọn cửa hàng → xem sản phẩm đang có tại cửa hàng đó, kèm giá, danh mục, số lượng bán được và hạn dùng gần nhất.

**Trong phạm vi**
- `clients/store-web/api/`: FastAPI, **chỉ JSON**, không template HTML. Đọc dữ liệu do repo đã migrate/seed sẵn (`store`, `product`, `inventory`, `product_batch`).
- `clients/store-web/web/`: SPA React 19 + TypeScript + Vite; router client-side; gọi `/api/*`.
- Ở chế độ demo, API phục vụ luôn bundle tĩnh của `web/dist` → **1 tiến trình, 1 cổng 5180**.
- Chế độ dev: Vite dev server 5173 proxy `/api` sang API 5180 → không cần CORS khi dev bình thường.

**Ngoài phạm vi**
- Không bán hàng, không giỏ hàng, không thanh toán.
- **Không ghi DB**: không INSERT/UPDATE/DELETE, không migration.
- Không đăng nhập, không JWT, không đụng `staff_user`.
- **Không sửa** `middleware/`, `compose.yaml`, `docs/design/openapi.yaml`, `database/`, `README.md` (ngoài 1 dòng Layout + 1 mục Run).
- Không thêm service vào `compose.yaml` ở phase đầu (giống `demo-pos`: chạy bằng lệnh riêng).
- Không SSR/Next.js, không auth, không state toàn cục phức tạp, không codegen OpenAPI.

**Tiêu chí thành công**
1. `pnpm build` một lần, sau đó `uvicorn` → mở `http://127.0.0.1:5180` là dùng được (1 tiến trình). Dev thì 2 terminal, có script ghi trong README.
2. 3 cửa hàng demo hiện đúng; bấm vào thấy đúng sản phẩm, khớp số liệu `sqlcmd`.
3. `pytest` của `middleware/` vẫn **không** quét vào `clients/store-web` (đã kiểm: `testpaths = tests`, chạy từ `middleware/`); `pytest` của API cũng không quét sang `middleware/`.
4. Toàn bộ thay đổi là **file mới** + 2 dòng sửa trong `README.md`; `git diff` trên file cũ tối thiểu.

---

## 2. Vị trí & cấu trúc

**`clients/store-web/`** — ngang cấp `clients/demo-pos/`, đúng chỗ README đã dự kiến cho client app, và `staff-app/` cũng sẽ nằm cùng cấp.

```
clients/store-web/
├─ README.md                  # theo khuôn clients/demo-pos/README.md (10 mục)
├─ .gitignore                 # node_modules/, dist/, .venv/, coverage/
├─ api\                       # FastAPI, JSON only
│  ├─ requirements.txt
│  ├─ requirements-dev.txt
│  ├─ pytest.ini              # testpaths = tests  (cô lập khỏi suite middleware)
│  ├─ app\
│  │  ├─ __init__.py
│  │  ├─ main.py              # CORS cho dev, router /api/*, phục vụ web/dist
│  │  ├─ config.py            # đọc .env của repo, prefix STORE_WEB_
│  │  ├─ db.py                # engine read-only, giống hq-demo/app/db.py
│  │  ├─ clock.py             # today_local() theo business_utc_offset_hours
│  │  ├─ errors.py            # ApiError + handler dạng phẳng
│  │  ├─ schemas.py
│  │  ├─ queries\
│  │  │  ├─ stores.py
│  │  │  └─ products.py
│  │  └─ api\
│  │     ├─ health.py         # GET /api/health
│  │     ├─ stores.py         # GET /api/stores, /api/stores/{id}
│  │     ├─ products.py       # GET /api/stores/{id}/products, /{sku}
│  │     └─ meta.py           # GET /api/categories
│  └─ tests\
│     ├─ conftest.py
│     ├─ test_stores_api.py
│     ├─ test_products_api.py
│     ├─ test_business_rules.py
│     └─ test_read_only.py
├─ web\                       # SPA
│  ├─ package.json            # react 19, react-router 7, @tanstack/react-query 5, vite 8
│  ├─ pnpm-lock.yaml          # commit (không commit node_modules)
│  ├─ tsconfig.json
│  ├─ vite.config.ts          # port 5173, proxy /api → 5180
│  ├─ index.html
│  ├─ .env.example            # VITE_API_BASE_URL (mặc định rỗng = same-origin)
│  ├─ src\
│  │  ├─ main.tsx
│  │  ├─ App.tsx              # router + providers
│  │  ├─ api\
│  │  │  ├─ client.ts         # fetch wrapper, parse lỗi {outcome,code,message}
│  │  │  ├─ types.ts          # khớp hợp đồng mục 4 (unit_price: string)
│  │  │  └─ queries.ts        # useStores, useStore, useProducts, useProduct, useCategories
│  │  ├─ pages\
│  │  │  ├─ StoresPage.tsx
│  │  │  ├─ StorePage.tsx
│  │  │  ├─ ProductPage.tsx
│  │  │  └─ NotFoundPage.tsx
│  │  ├─ components\
│  │  │  ├─ Layout.tsx        # header, breadcrumb, focus management
│  │  │  ├─ FilterBar.tsx     # q, category, in_stock, sort
│  │  │  ├─ ProductTable.tsx
│  │  │  ├─ BatchTable.tsx
│  │  │  ├─ Pagination.tsx
│  │  │  └─ StateBlock.tsx    # loading / empty / error + nút thử lại
│  │  ├─ lib\
│  │  │  ├─ format.ts         # tiền "32000.00" → "32.000 ₫" (chỉ để hiển thị)
│  │  │  └─ filters.ts        # đọc/ghi bộ lọc từ URLSearchParams
│  │  ├─ styles\
│  │  │  ├─ tokens.css        # bảng màu lấy từ docs/design/DS-08
│  │  │  └─ app.css
│  │  └─ test\
│  │     ├─ setup.ts
│  │     ├─ server.ts         # msw
│  │     └─ fixtures.ts
│  └─ tests\                  # *.test.tsx (vitest)
│     ├─ stores-page.test.tsx
│     ├─ store-page.test.tsx
│     ├─ product-page.test.tsx
│     └─ states.test.tsx
└─ tools\
   └─ db_report.py            # (tuỳ chọn) đối chiếu số liệu, chỉ SELECT
```

**Công nghệ:** React + TypeScript + Vite (SPA), TanStack Query, React Router; API FastAPI + Pydantic; CSS thuần theo token của `docs/design/DS-08`.

**Vì sao SPA (và đánh đổi đã chấp nhận):**
- Lợi: tương tác mượt (lọc/sort/phân trang không reload), tách bạch rõ API/view, đúng kỹ năng frontend hiện đại, giữ nguyên `/api/*` khi sau này chuyển sang gọi `middleware/`.
- Mất: thêm Node + build + `node_modules` + lockfile; 2 tiến trình khi dev; CORS phải cấu hình cho dev; test web cần jsdom + msw; người review phải đọc cả TSX.
- Chặn: **bắt buộc `pnpm build` trước khi demo** nếu muốn 1 tiến trình. README phải ghi đúng thứ tự.

---

## 3. Cách app tách khỏi phần còn lại

| Điểm | Cách làm | Vì sao an toàn |
|---|---|---|
| Chạy API | `uvicorn app.main:app --port 5180` từ `api/` | Không là compose service, không ảnh hưởng stack của nhóm |
| Chạy web (dev) | `pnpm dev` từ `web/` → 5173, proxy `/api` → 5180 | Không đụng cổng 8000/8443/9000/9443 |
| Build web | `pnpm build` → `web/dist`; API mount thư mục này | Không cần nginx, không thêm service |
| CORS | Chỉ bật cho `http://127.0.0.1:5173` và `http://localhost:5173` (đọc từ `STORE_WEB_CORS_ORIGINS`) | Dev có proxy nên bình thường không cần; prod same-origin nên CORS tắt hẳn |
| Test API | `pytest` chạy **trong** `api/` với `pytest.ini` riêng | `middleware/pytest.ini` đặt `testpaths = tests` nên không quét sang |
| Test web | `pnpm test` (Vitest + jsdom + msw), không cần DB, không cần API thật | Test web độc lập hoàn toàn với SQL Server |
| DB access | Tự tạo engine trong `api/app/db.py`, đọc `.env` của repo | Không import `app.core.db`; không phụ thuộc code nội bộ |
| Config | Biến mới `STORE_WEB_*` trong `.env` | Không đụng tên biến của middleware |
| Không sửa contract | `docs/design/openapi.yaml` không đổi | API này là API của app, không phải của middleware |
| `.gitignore` | `clients/store-web/.gitignore` cho `node_modules/`, `dist/`, `coverage/`, `.venv/` | Repo `.gitignore` hiện chỉ có `.venv/`, `__pycache__/` |

**So sánh với `demo-pos`:** demo-pos gọi middleware qua HTTPS; store-web đọc thẳng DB. Đây là **khác biệt có chủ ý** vì middleware không có endpoint trả `name`/`unit_price`/`category` (xem Phụ lục). Cả hai đều là app ngoài, tự lo cấu hình, không sửa lõi.

**Đánh đổi.** App phụ thuộc schema 4 bảng. Giảm thiểu: SQL gom trong `api/app/queries/`; test đỏ ngay khi schema đổi; mục 11 là đường lui.

---

## 4. API (do app này định nghĩa)

Tiền tố `/api`, chỉ `GET`, không auth. JSON `snake_case`, `unit_price` là **string 2 chữ số thập phân** (không dùng float cho tiền).

Same-origin khi chạy bản build (web gọi `/api/...`). Dev dùng proxy của Vite nên URL tương đối cũng chạy.

### 4.1 `GET /api/health`
```json
{ "status": "ok", "database": "RTS_DB_DEMO" }
```

### 4.2 `GET /api/stores`
```json
{ "stores": [
  { "store_id": "STORE-DN1", "name": "Cửa hàng Hải Châu",
    "region_id": "DN", "product_count": 9, "sellable_units": 216 }
] }
```
`product_count` = số SKU có dòng `inventory`; `sellable_units` = tổng batch còn hạn. Chỉ `store.is_active = 1`.

### 4.3 `GET /api/stores/{store_id}`
Chi tiết cửa hàng + thống kê tổng (`product_count`, `sellable_units`, `expired_units`). `404 NOT_FOUND` nếu không có hoặc `is_active = 0`.

### 4.4 `GET /api/stores/{store_id}/products` — endpoint chính
Tham số: `q` (tên/SKU, ≤100 ký tự), `category`, `in_stock` (`true|false`), `sort` (`name|price|sellable`), `limit` (mặc định 50, tối đa 200), `offset`.

```json
{
  "store_id": "STORE-DN1",
  "total": 9,
  "limit": 50,
  "offset": 0,
  "items": [{
    "sku": "SKU-0001",
    "barcode": "8930000000011",
    "name": "Fresh milk 1L",
    "category": "Dairy",
    "unit_price": "32000.00",
    "quantity": 40,
    "sellable_quantity": 16,
    "expired_quantity": 24,
    "nearest_expiry": "2026-11-12",
    "batches": [
      { "batch_id": "B-STORE-DN1-SKU-0001-1", "expiry_date": "2026-11-12", "quantity": 16, "sellable": false }
    ]
  }]
}
```
`quantity` = `inventory.quantity` (gồm hàng hết hạn). `sellable_quantity` = tổng batch còn hạn.

SQL: trang sản phẩm 1 câu `product × inventory OUTER APPLY product_batch` (lọc/sort/đếm đúng), `total` 1 câu `COUNT(*)` cùng `WHERE`, batch của trang 1 câu `IN (...)` — 3 câu cố định, không N+1.

### 4.5 `GET /api/stores/{store_id}/products/{sku}`
Một sản phẩm, cùng schema, `batches` đầy đủ (kèm `?include_empty=true`). `404` nếu SKU không có trong catalog.

### 4.6 `GET /api/categories`
```json
{ "categories": ["Bakery", "Dairy", "Dry goods"] }
```

**Lỗi:** `{ "outcome": "REJECTED", "code": "...", "message": "..." }` với `NOT_FOUND` (404), `VALIDATION_ERROR` (422), `STORE_WEB_UNAVAILABLE` (503) — cùng dạng phẳng với middleware để dễ đối chiếu và để `web` chỉ cần một hàm parse lỗi.

---

## 5. Quy tắc dữ liệu (dễ sai nhất)

1. **`inventory.quantity` gồm cả hàng hết hạn.** Bất biến PB-20: `inventory.quantity` = tổng `product_batch.quantity` cùng `(store_id, sku)`. **Không** hiển thị `quantity` như "còn bán được"; phải tính `sellable_quantity`.
2. **`today_local()` không phải `GETDATE()`.** Dùng `business_utc_offset_hours` (mặc định 7): `(now_utc + offset).date()`, truyền vào SQL là `:today`. Dùng `GETDATE()` sẽ lệch 7 giờ và sai đúng batch hết hạn trong ngày.
3. **Batch hết hạn vẫn có `quantity > 0`** → hiện ở chi tiết với nhãn "hết hạn", không tính vào `sellable_quantity`.
4. **`store.is_active = 0`** → ẩn khỏi danh sách, 404 ở chi tiết.
5. **SKU có trong catalog nhưng không có `inventory`** tại cửa hàng → 0, không phải lỗi (`LEFT JOIN` từ `product`).
6. **So sánh chuỗi:** cột `varchar`, tham số pyodbc mặc định `nvarchar` → `CONVERT_IMPLICIT`, mất index seek (đúng lỗi #25 của nhóm). Chỉ đọc nên không cấp bách; nếu chậm thì `CAST(:store_id AS varchar(10))`. **Không** dùng `NOLOCK`.
7. **Phân trang:** `total` là tổng sau lọc, không phải số dòng trả về.
8. **Client không tự tính "hết hạn".** API trả cờ `sellable` cho từng batch; web chỉ hiển thị. Nếu để web so `expiry_date` với `new Date()`, máy người xem sai múi giờ/giờ hệ thống là hiển thị sai ngay — đây là lỗi đã gặp ở mục 2.
9. **Tiền là string trong JSON.** Web chỉ format để hiển thị, không `parseFloat` để tính toán.

---

## 6. Màn hình

SPA giữ **bộ lọc trong URL** (`?q=&category=&in_stock=1&sort=name&limit=25&offset=0`) nên chia sẻ link và back/forward đều đúng.

| Route (client) | API dùng | Nội dung |
|---|---|---|
| `/` | `/api/stores` | Thẻ 3 cửa hàng: tên, khu vực, số SKU, tổng đơn vị bán được |
| `/stores/:storeId` | `/api/stores/{id}`, `/api/stores/{id}/products`, `/api/categories` | Ô tìm kiếm, dropdown danh mục, toggle "chỉ còn hàng", bảng sản phẩm (Tên, SKU, Danh mục, Giá, Còn bán, Hạn gần nhất) |
| `/stores/:storeId/products/:sku` | `/api/stores/{id}/products/{sku}` | Thẻ sản phẩm + bảng batch (mã lô, hạn, số lượng); lô hết hạn gạch ngang |
| `*` | — | Trang "Không tìm thấy" + link về `/` |

Cần có: trạng thái đang tải (skeleton hoặc chữ), trạng thái rỗng, trạng thái lỗi DB (503) kèm nút "Thử lại" gọi lại query, tiếng Việt có dấu, ảnh là placeholder chữ cái, `aria-live` cho số kết quả, `<th scope="col">`, focus chuyển tới `<h1>` khi đổi route.

---

## 7. Lộ trình

| Phase | Việc | Ước lượng | Nghiệm thu |
|---|---|---|---|
| **0. Khung** | `clients/store-web/`, venv 3.12, FastAPI hello, `.env` vars, `pytest.ini`, `.gitignore` | 0.5 ngày | `/api/health` OK; `pytest` trong `api/` chạy; suite `middleware/` không đổi |
| **1. Tầng đọc DB** | `db.py`, `clock.py`, `queries/`, `schemas.py`, 6 endpoint, CORS dev | 1 ngày | Số liệu khớp `sqlcmd` cho 3 store |
| **2. Khung SPA** | `pnpm create vite`, router, provider, `api/client.ts` + types, layout, token CSS | 1 ngày | 3 route render, gọi API thật, lỗi 503 có nút thử lại |
| **3. Màn hình** | `FilterBar`, `ProductTable`, `BatchTable`, `Pagination`, `StateBlock`, bộ lọc trong URL | 1.5 ngày | Đi hết store → list → detail; lọc/sort/phân trang không reload |
| **4. Build + tiêm vào API** | `pnpm build`, mount `dist`, fallback SPA, cache header | 0.5 ngày | 1 tiến trình ở 5180 phục vụ cả web lẫn API |
| **5. Kiểm thử** | `api/tests` (API, nghiệp vụ, read-only) + `web/tests` (vitest + msw) | 1 ngày | `pytest` và `pnpm test` xanh; `pnpm typecheck` sạch |
| **6. Tích hợp repo** | 1 dòng Layout + 1 mục Run trong `README.md`; commit `Quang`; PR nháp | 0.5 ngày | Nhóm review được |

Tổng **~6 ngày**, chia 3 buổi: (0+1), (2+3), (4+5+6). SPA cộng ~1,5 ngày so với bản Jinja2.

---

## 8. Kiểm thử

**API** — DB test riêng `RTS_WEB_TEST` (không dùng `RTS_DB_TEST` của nhóm — họ xoá/tạo dòng `TEST-` liên tục, test của mình sẽ flaky). Tạo bằng `sqlcmd` chạy `database/migrations/*.sql` + `database/seed/*.sql` với `DB_NAME=RTS_WEB_TEST`: chỉ **đọc** file SQL của nhóm.

- **Fixture tự tạo** trong `RTS_WEB_TEST`: 2 store (1 active, 1 inactive), 3 SKU, batch gồm còn hạn / hết hạn hôm qua / hết hạn **đúng hôm nay** / quantity 0.
- **Test bắt buộc:**
  - `sellable_quantity` bỏ batch hết hạn; batch hết hạn đúng hôm nay **vẫn** bán được (biên quan trọng nhất).
  - `quantity` vẫn bằng tổng batch.
  - `is_active = 0` → 404 và không có trong `/api/stores`.
  - SKU không có inventory → 0, không 404.
  - `q`, `category`, `in_stock`, `sort`, `limit/offset` + `total`.
  - Giá đúng 2 chữ số thập phân dạng string.
  - `test_read_only.py`: (a) test tĩnh — mọi SQL trong `queries/` bắt đầu bằng `SELECT`; (b) test động — so `COUNT(*)` 4 bảng trước/sau khi chạy hết endpoint.

**Web** — Vitest + jsdom + msw, **không cần API thật và không cần DB**:
- Danh sách 3 store render đúng tên/khu vực/số liệu.
- Đổi bộ lọc → URL đổi và request mới mang đúng query (`q`, `category`, `in_stock`, `sort`).
- Batch hết hạn có nhãn và gạch ngang; không cộng vào "Còn bán".
- 503 → hiện thông báo + nút "Thử lại", bấm thì gọi lại.
- Rỗng → thông báo rỗng, không phải lỗi.
- Giá hiển thị `32.000 ₫` từ string `"32000.00"`.
- `pnpm typecheck` (`tsc --noEmit`) sạch.

**Không test:** pixel/CSS, e2e Playwright (tuỳ chọn sau), mTLS, HQ.

---

## 9. Rủi ro

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Schema đổi ở repo nhóm → app gãy | Cao | SQL gom 1 chỗ; test đỏ ngay; mục 11 |
| Sai múi giờ làm ẩn batch hết hạn hôm nay | Cao | `today_local()` + test biên; **client không tự so ngày** |
| Hiển thị `quantity` như "còn hàng" | Cao | UI chỉ dùng `sellable_quantity`, cột tên "Còn bán" |
| **Quên `pnpm build` trước khi demo → 404 ở `/`** | Cao | API log cảnh báo khi thiếu `web/dist`; README bước 1; checklist nghiệm thu |
| **CORS/proxy sai khi dev** | Trung bình | Proxy `/api` trong `vite.config.ts`; CORS chỉ mở localhost:5173; README |
| **`node_modules`/`dist` bị commit** | Trung bình | `.gitignore` riêng trong `clients/store-web/`; kiểm `git status` ở bước cuối |
| Vô tình commit `.env`/secret | Trung bình | `.gitignore` đã có `.env`; chỉ commit `.env.example` |
| Nhóm thấy thêm folder là phạm vi lạ | Trung bình | PR nháp, mô tả rõ "app độc lập, không sửa middleware"; có thể rút khỏi PR nếu nhóm không muốn |
| Hai nguồn sự thật "tồn kho" | Trung bình | README ghi rõ web là **bản sao chỉ đọc**; công thức `sellable` tham chiếu `app/services/inventory.py` |
| Node version lệch giữa máy | Thấp | `engines` + `packageManager` trong `package.json`; ghi Node ≥20.19/22.12 trong README |

---

## 10. Chạy local

**Lần đầu**
```powershell
# Từ thư mục gốc repo, sau khi đã có .env và DB đã migrate
cd clients/store-web/api
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

cd ..\web
pnpm install
pnpm build          # tạo web\dist
```

**Demo (1 tiến trình)**
```powershell
cd clients/store-web/api
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 5180
# Mở http://127.0.0.1:5180
```

**Phát triển (2 tiến trình, hot reload)**
```powershell
# Terminal 1
cd clients/store-web/api
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 5180 --reload
# Terminal 2
cd clients/store-web/web
pnpm dev            # http://127.0.0.1:5173, /api proxy sang 5180
```

Đọc cấu hình từ `.env` ở repo root (giống cách `demo-pos` tự tìm repo root): dùng `DB_HOST`, `SQLSERVER_PORT`, `DB_NAME`, `MSSQL_SA_PASSWORD`, `BUSINESS_UTC_OFFSET_HOURS` — **không** thêm biến mới bắt buộc. Biến riêng của app (nếu cần) đặt tiền tố `STORE_WEB_`:
`STORE_WEB_DB_NAME` (mặc định = `DB_NAME`), `STORE_WEB_TEST_DB_NAME` (mặc định `RTS_WEB_TEST`), `STORE_WEB_CORS_ORIGINS`.

**Test**
```powershell
# API
cd clients/store-web/api
$env:STORE_WEB_TEST_DB_NAME="RTS_WEB_TEST"; .\.venv\Scripts\python.exe -m pytest -q

# Web (không cần DB)
cd clients/store-web/web
pnpm test
pnpm typecheck
```

---

## 11. Đường lui khi nhóm duyệt

1. Thêm `GET /stores` và `GET /stores/{store_id}/products` vào `middleware/` (join `product` + `inventory` + `product_batch`), theo quy ước "sửa `openapi.yaml` trước".
2. Giữ **cùng shape JSON** với mục 4 → **`web/` không đổi gì**, chỉ đổi base URL.
3. Đổi `VITE_API_BASE_URL` (hoặc proxy) sang `https://localhost:8443/api/v1`; bật CORS/proxy.
4. Xoá `api/app/queries/`, `api/app/db.py`, `api/app/clock.py`; giữ `web/`, `api/app/api/` nếu muốn giữ lớp adapter.

Công sức phase 2–5 vẫn dùng được — đây là lợi ích chính của việc tách API/view ngay từ đầu.

---

## 12. Quyết định cần chốt trước khi code

| # | Câu hỏi | Mặc định |
|---|---|---|
| 1 | Chỉ local hay cho LAN truy cập? | Local `127.0.0.1` trước |
| 2 | Có đăng nhập không? | Không (tài liệu tính năng công khai, không có dữ liệu nhạy cảm ngoài giá) |
| 3 | Hiển thị giá? | Có |
| 4 | Hiển thị lô hết hạn? | Có, ở trang chi tiết, có nhãn |
| 5 | DB khi dev | `RTS_DB_DEMO`; test `RTS_WEB_TEST` |
| 6 | Tên folder | `clients/store-web/api` + `clients/store-web/web` |
| 7 | Commit lên đâu | `Quang`, PR nháp khi phase 5 xanh |
| 8 | Kiến trúc UI | **SPA + API riêng** (đã chốt 10/11) |
| 9 | CSS | CSS thuần theo token DS-08; không Tailwind (nếu nhóm muốn thì thêm 1 lệnh) |
| 10 | Test web | Vitest + msw, không e2e Playwright ở phase này |
| 11 | Package manager | pnpm (đã có 12.18 trên máy); commit `pnpm-lock.yaml` |

---

## Phụ lục: vì sao không gọi API có sẵn của middleware

| API hiện có | Thiếu gì |
|---|---|
| `GET /api/v1/stores/{store_id}/inventory` | Không có `name`, `unit_price`, `category`; bắt buộc token Staff đúng store; không list được cửa hàng |
| `GET /api/v1/products/barcode/{barcode}` | Tra theo barcode, không theo SKU; chỉ role Staff; không có batch |
| `POST /api/v1/admin/stores` | Là POST, role Admin; không có GET tương ứng |
| Không tồn tại | `GET /stores`, sản phẩm theo cửa hàng, tổng hợp bán được |

Các khoảng trống đều nằm trong `middleware/` — không được sửa trong task này. Vì vậy app đọc thẳng DB, giữ hợp đồng JSON tương thích để thay thế về sau (mục 11).
