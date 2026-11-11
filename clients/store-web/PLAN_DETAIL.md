# Kế hoạch thi công chi tiết: Store Web (SPA + API riêng)

> Quan hệ với `PLAN.md`: `PLAN.md` giữ **phạm vi, quyết định và lý do** (mục 1–6, 8–12).
> File này thay mục 7 của `PLAN.md` bằng **kế hoạch thi công cụ thể**: từng file, từng câu SQL,
> từng component, từng test, từng lệnh kiểm. Khi thi công xong một task, chỉ đánh dấu ở đây.
>
> Trạng thái: **đã thi công xong 10/11/2026** (phase 0–6). Người làm: Quang. Nhánh: `Quang`.
> Ghi chú thi công: Python 3.12 không cài được trên máy này (winget lỗi, `py -0p` chỉ có 3.14/3.11)
> nên dùng **3.11.9** theo đúng phương án dự phòng của T0.0. Toàn bộ 35 test API + 20 test web xanh.
> Kiến trúc: **SPA React + TypeScript (Vite) + API FastAPI chỉ JSON** — chốt 10/11/2026.
> TDD Route: `off` → decision `skipped` (không có yêu cầu TDD rõ ràng); kiểm chứng bằng test sau
> mỗi task, cộng `verification-before-completion` trước khi báo xong.

---

## 0. Tóm tắt điều hành

- Khối lượng: **7 phase (0–6), 38 task nhỏ**, ~6 ngày (3 buổi: 0+1 / 2+3 / 4+5+6).
- Hai tiểu dự án: `api/` (Python, chỉ JSON) và `web/` (Node, SPA). Một lệnh `pnpm build` rồi
  `uvicorn` là có web hoàn chỉnh ở `http://127.0.0.1:5180`.
- **Bắt buộc nhớ:** API mount `web/dist`; chưa build thì `/` trả 404 kèm thông điệp hướng dẫn.
  Đây là rủi ro demo số 1, có log cảnh báo lúc khởi động và 1 dòng trong checklist.
- Điểm chặn môi trường: Docker daemon **chưa chạy**, **chưa có Python 3.12** (cài ở T0.0).
  Node 24.13 + pnpm 12.18 đã có, đủ cho Vite 8 (yêu cầu Node ≥20.19 hoặc ≥22.12).
- 4 chỗ sửa so với `PLAN.md` gốc: dạng lỗi JSON, tên biến DB test, cách viết truy vấn danh sách,
  và kiến trúc UI (Jinja2 → SPA). Xem mục 3.

---

## 1. Nền tảng đã kiểm tra trong repo (bằng chứng, không suy đoán)

### 1.1. Schema & dữ liệu

| Sự thật | Bằng chứng | Ảnh hưởng |
|---|---|---|
| `store(store_id varchar(10) PK, name nvarchar(100), latitude, longitude, region_id varchar(10), is_active bit)` | `database/migrations/001_core.sql:5-12` | Không có cột đếm; `product_count`/`sellable_units` phải tính |
| `product(sku varchar(20) PK, barcode, name nvarchar(150), category varchar(50), unit_price decimal(12,2))` | `001_core.sql:43-49` | `unit_price` → `Decimal` → format 2 chữ số |
| `inventory(store_id, sku) PK, quantity int, updated_at` | `001_core.sql:51-57` | PK đủ seek theo store |
| `product_batch(batch_id varchar(30) PK, sku, store_id, expiry_date date, quantity int)` + `ix_product_batch_fefo(store_id, sku, expiry_date)` | `002_batches_alerts_forecast.sql:5-13` | Index dùng được khi lọc theo store/SKU |
| 3 store `STORE-DN1..3`, 9 SKU, tồn 40/25/15 | `database/seed/001_demo_stores_pos.sql:2-19`, `002_demo_catalog.sql:3-31` | Số liệu đối chiếu `sqlcmd` |
| Seed batch: `-1` hết hạn `today+3` (~40% số lượng), `-2` hết hạn `+20/+10/+180` theo category | `database/seed/003_demo_batches.sql:14-58` | **Không có batch hết hạn** trong DB demo; test biên phải tự tạo fixture |

### 1.2. Quy tắc nghiệp vụ phải khớp

| Sự thật | Bằng chứng | Ảnh hưởng |
|---|---|---|
| "Bán được" = `expiry_date >= today_local()` (hết hạn **hôm nay vẫn bán được**) | `middleware/app/repositories/inventory.py:180,206`; `services/inventory.py:59-66` | `sellable` phải dùng `>=` |
| `today_local()` = `(now_utc + business_utc_offset_hours).date()`, mặc định 7 | `middleware/app/core/clock.py:19-22`; `core/config.py:33` | Chép nguyên, không `GETDATE()` |
| `inventory.quantity` = tổng `product_batch.quantity` (bất biến PB-20) | `middleware/app/domain/models.py:77` | `expired_quantity = quantity - sellable_quantity` là **sai** nếu có batch quantity 0; phải SUM riêng |

### 1.3. Khuôn code trong repo

| Sự thật | Bằng chứng | Ảnh hưởng |
|---|---|---|
| `middleware/pytest.ini` = `pythonpath=.`, `testpaths=tests` | `middleware/pytest.ini:1-3` | Suite nhóm không quét sang; `api/` cần file riêng cùng dạng |
| `hq-demo` là khuôn "app phụ FastAPI tự chứa" đúng nhất | `hq-demo/app/{config,db,main}.py`, `hq-demo/tests/conftest.py` | Chép `config.py`/`db.py`/`conftest.py` |
| Config đọc `.env` repo root qua `Path(__file__).parents[N]/".env"` | `middleware/app/core/config.py:15`; `hq-demo/app/config.py:11` | ⚠️ **Không chép số cấp**: `api/app/config.py` sâu hơn `middleware/app/core/config.py` hai cấp → `parents[3]` = `clients/`. Dùng `repo_root()` dò `compose.yaml` (mục T0.3) |
| Lỗi nhóm dùng dạng phẳng `{"outcome","code","message"}` | `middleware/app/core/errors.py:25-27` | Dùng đúng dạng này |
| Repo `.env.example` có `TEST_DB_NAME=RTS_DB_TEST` | `.env.example:10` | **Không** đọc `TEST_DB_NAME` (mục 3.2) |
| Layer SQL gom 1 chỗ, không N+1 | `middleware/app/repositories/stock_query.py:21-41`, `services/stock_query.py:36-41` | Cùng cách tổ chức trong `api/app/queries/` |

### 1.4. Trạng thái "web" hiện tại của repo (lý do SPA là bước nhảy có kiểm soát)

| Sự thật | Bằng chứng (đã kiểm) | Ảnh hưởng |
|---|---|---|
| **Chưa có trang web nào**: `middleware/` và `hq-demo/` chỉ trả JSON, không `templates/`, không `static/` | `grep Jinja2Templates\|StaticFiles\|HTMLResponse` trên toàn repo → 0 match trong code | store-web là app **đầu tiên** render giao diện; không có pattern HTML để tái dùng |
| Toàn repo có **1 file `.html`**: wireframe tài liệu | `docs/design/DS-08_Staff_App_Wireframes.html` (7 KB) | Dùng làm nguồn token màu/font, không phải code chạy |
| Wireframe dùng CSS thuần, biến `--ink:#222; --line:#777; --soft:#eee; --mid:#d8d8d8; --note:#555`, font `"Segoe UI",Arial,sans-serif` | `DS-08...html:6-13` | `web/src/styles/tokens.css` lấy đúng các biến này |
| Repo **không có** `package.json`, `node_modules/`, bundler nào | `Get-ChildItem -Recurse -Filter *.json` ở root | SPA là công nghệ mới trong repo → phải có README riêng, lockfile commit, `.gitignore` riêng |
| `.gitignore` gốc **không** ignore `node_modules/` hay `dist/` | `.gitignore:1-23` | Bắt buộc thêm `clients/store-web/.gitignore` |

### 1.5. Toolchain máy hiện tại (đã chạy lệnh kiểm)

| Công cụ | Kết quả | Ghi chú |
|---|---|---|
| Node | `v24.13.0` | Vite 8 yêu cầu `^20.19.0 \|\| >=22.12.0` → đạt |
| npm | `11.6.2` | |
| pnpm | `12.18.0` | Có sẵn; dùng pnpm để cài nhanh và lockfile gọn |
| git | `2.52.0.windows.1` | |
| Python | `3.14.2` (mặc định), `3.11`, **chưa có 3.12** | Cài ở T0.0; `pyodbc==5.2.0` không có wheel cho 3.14 |
| ODBC Driver 18 (64-bit) | Có | `pyodbc` chạy được |
| Docker daemon | **Chưa chạy**; `127.0.0.1:14333` và `8443` đóng | Chặn T0.6 trở đi phần DB; xem mục 11 |
| Registry npm | `https://registry.npmjs.org/` | Cài package được |

Bản package đã tra tại thời điểm lập kế hoạch (dùng để biết trước, **không pin mù**):

| Package | Bản mới nhất |
|---|---|
| react | 19.3.1 |
| vite | 8.3.7 |
| typescript | 7.0.2 |
| react-router-dom | 7.18.5 |
| @tanstack/react-query | 5.107.1 |
| vitest | 5.1.0 |
| @vitejs/plugin-react | 6.3.0 |
| @testing-library/react | 16.3.3 |
| @testing-library/jest-dom | 7.0.1 |
| jsdom | 31.0.0 |
| msw | 3.0.4 |

> Không tự viết `package.json` bằng tay với các số trên. Dùng `pnpm create vite@latest web --template react-ts`
> để scaffolder chọn bộ version **tương thích với nhau**, rồi thêm từng package đúng như T2.1 ghi.
> Lý do: `@vitejs/plugin-react` 6.x khai báo peer `vite: ^8`, tự ghép số dễ ra cặp lệch.
> TypeScript: npm có 7.0.2 nhưng template thường pin 5.x — **giữ theo template**, không nâng mù
> (TypeScript 7 là bản viết lại, chưa chắc tương thích mọi plugin; `typecheck` sẽ là nơi phát hiện).
> Ghi lại version thực tế vào `README.md` sau khi cài xong.

---

## 2. Quyết định kỹ thuật đã chốt

| # | Hạng mục | Chốt | Lý do |
|---|---|---|---|
| D1 | Kiến trúc | **SPA + API riêng**: `web/` React 19 + TS + Vite, `api/` FastAPI chỉ JSON | Quang chốt 10/11; tách hợp đồng để sau này đổi view hoặc trỏ sang middleware mà không viết lại |
| D2 | Python | **3.12**, cài `winget install -e --id Python.Python.3.12` (3.12.10), venv riêng `api/.venv` | Khớp README repo + middleware; `pyodbc==5.2.0` có wheel cp312 |
| D3 | API deps | `fastapi==0.115.6`, `uvicorn[standard]==0.34.0`, `pydantic-settings==2.7.1`, `sqlalchemy==2.0.36`, `pyodbc==5.2.0` | Khớp middleware; **không** cần `jinja2` nữa (vì không render server) |
| D4 | API dev deps | `pytest==8.3.4`, `httpx==0.28.1` | Khớp middleware |
| D5 | DB đọc | `STORE_WEB_DB_NAME` nếu có, mặc định `DB_NAME` từ `.env` repo | Không thêm biến bắt buộc |
| D6 | DB test | `STORE_WEB_TEST_DB_NAME`, mặc định `RTS_WEB_TEST` | Tránh dẫm `TEST_DB_NAME=RTS_DB_TEST` của nhóm |
| D7 | Dạng lỗi | `{"outcome":"REJECTED|ERROR","code","message"}` | Giống middleware; web chỉ cần 1 hàm parse |
| D8 | Truy vấn | 3 câu SQL/request (trang + total + batch của trang), `sellable` bằng `OUTER APPLY` | Lọc/sort/đếm/phân trang đúng trong SQL, không N+1 (mục 3.3) |
| D9 | State/HTTP client | TanStack Query 5 (`useQuery`), không Redux/Zustand | Server state là chính; cache + retry + loading có sẵn, ít code |
| D10 | Router | `react-router-dom` 7, dùng `useSearchParams` cho bộ lọc | Bộ lọc nằm trong URL → chia sẻ/back-forward đúng |
| D11 | Style | CSS thuần + token lấy từ `DS-08`; **không** Tailwind ở phase này | Ít phụ thuộc, không build thêm, đúng tài liệu nhóm |
| D12 | Deploy | `pnpm build` → `web/dist`; **API mount luôn thư mục đó** | 1 tiến trình, 1 cổng, không nginx, không compose service |
| D13 | Dev | Vite 5173 + proxy `/api` → 5180; CORS chỉ mở cho 5173 (dự phòng) | Không cần CORS khi dùng proxy; vẫn chạy được nếu ai đó tắt proxy |
| D14 | Test web | Vitest + jsdom + msw 3; không e2e Playwright | Không cần DB/API thật; chạy trong CI nhóm |
| D15 | Package manager | pnpm 12, commit `pnpm-lock.yaml`, **không** commit `node_modules/` | Lockfile = tái lập được; pnpm đã có trên máy |
| D16 | Port | `127.0.0.1:5180` (API+web), `5173` (Vite dev) | Không đụng 8000/8443/9000/9443 |
| D17 | Cổng vào | Chỉ `GET`, không auth | Read-only demo nội bộ |

### Đã chốt (10/11/2026)
1. Python **3.12** (D2) — cài ở T0.0 trước khi tạo venv.
2. Kiến trúc **SPA + API riêng** (D1) — thay phương án FastAPI + Jinja2 của `PLAN.md` gốc.
3. Có **route chi tiết riêng** `/stores/:storeId/products/:sku`, không modal.

---

## 3. Bốn điểm sửa so với `PLAN.md` gốc

### 3.1. Dạng lỗi
`PLAN.md` gốc ghi `{"error": {"code","message"}}` nhưng lại nói "cùng dạng với middleware". Middleware
dùng dạng phẳng (`errors.py:25-27`). Chốt dạng phẳng:

```json
{ "outcome": "REJECTED", "code": "NOT_FOUND", "message": "Store 'STORE-XX' does not exist." }
```

Mã: `NOT_FOUND` (404), `VALIDATION_ERROR` (422), `STORE_WEB_UNAVAILABLE` (503).
(Không dùng `DATABASE_UNAVAILABLE` để khỏi lẫn với `SERVICE_UNAVAILABLE` của middleware.)

### 3.2. Biến môi trường test
`PLAN.md` gốc viết `$env:TEST_DB_NAME="RTS_WEB_TEST"`, nhưng `.env` repo đã có
`TEST_DB_NAME=RTS_DB_TEST` → dễ ghi nhầm vào DB test của nhóm. Dùng tên riêng:

```powershell
$env:STORE_WEB_TEST_DB_NAME = "RTS_WEB_TEST"
```

`conftest.py` phải **fail cứng** nếu tên DB không kết thúc `_TEST` hoặc trùng `database_name`
(chép `middleware/tests/conftest.py:20-23`).

### 3.3. Truy vấn danh sách sản phẩm
`PLAN.md` gốc nói "1 câu product × inventory + 1 câu batch gom theo store, ghép trong Python". Làm vậy
không phân trang/sort/lọc `in_stock` đúng được (phải kéo toàn bộ batch của store rồi lọc trong
Python; `total` và `OFFSET/FETCH` sai). Chốt: `OUTER APPLY` gom batch **trong SQL** cho đúng trang;
batch chi tiết chỉ lấy cho SKU của trang. Vẫn 3 câu cố định, không N+1.

### 3.4. Kiến trúc UI: Jinja2 → SPA
`PLAN.md` gốc: "FastAPI + Jinja2 + HTMX, không `node_modules`, không build, không CORS, một tiến trình."
Nay thay bằng SPA. Ghi lại đầy đủ hệ quả để không ai bất ngờ:

| Hệ quả | Cụ thể | Ai phải biết |
|---|---|---|
| **Thêm bước build** | `pnpm install && pnpm build` trước khi demo; không build thì `/` 404 | Người demo, người review, README |
| **`node_modules`** | ~200–400 MB, không commit; `.gitignore` riêng bắt buộc | Người clone repo |
| **2 tiến trình khi dev** | API 5180 + Vite 5173 | Người code |
| **CORS** | Chỉ cần khi dev không dùng proxy; prod same-origin nên tắt | Người code |
| **Test chia hai** | `pytest` cho API (cần DB test), `pnpm test` cho web (không cần DB) | Người review |
| **Review nặng hơn** | Đọc TSX + hook + test msw, không chỉ Jinja | Nhóm review |
| **Cộng ~1,5 ngày** | Phase 2–5 dài hơn bản Jinja2 | Quang |
| **Đường lui sạch hơn** | Chỉ đổi base URL khi chuyển sang middleware; `web/` không sửa | Tương lai |

**Vì sao vẫn chọn:** `PLAN.md` mục 11 (đường lui) yêu cầu "giữ cùng shape JSON → frontend không
đổi". Tách API/view ngay từ đầu làm điều đó **đúng theo thiết kế**, không phải refactor sau. Ngoài ra
`/api/*` là thứ duy nhất nhóm cần kiểm bằng `pytest`, còn giao diện kiểm bằng Vitest không cần DB —
hợp với môi trường Docker hay trục trặc của máy demo.

**Điều KHÔNG được hy sinh khi chuyển sang SPA** (giữ nguyên từ bản trước):
- Không tự tính "hết hạn" ở client: API trả cờ `sellable` cho từng batch (mục 5.8).
- `quantity` không bao giờ hiển thị như "còn bán".
- 3 trạng thái rỗng/lỗi/đang tải đều có, lỗi 503 có nút "Thử lại".
- Bộ lọc nằm trong URL, back/forward và chia sẻ link đúng.
- `aria-live` cho số kết quả, `<th scope="col">`, focus về `<h1>` khi đổi route.

---

## 4. Cấu trúc file cuối cùng (đích đến)

```
clients/store-web/
├─ PLAN.md                     # phạm vi/quyết định (đã cập nhật sang SPA)
├─ PLAN_DETAIL.md              # file này
├─ README.md                   # 10 mục, viết ở T6.1
├─ .gitignore                  # node_modules/, dist/, coverage/, .venv/, *.tsbuildinfo
├─ api/
│  ├─ requirements.txt         # D3
│  ├─ requirements-dev.txt     # -r requirements.txt + pytest + httpx
│  ├─ pytest.ini               # pythonpath = . / testpaths = tests
│  ├─ app/
│  │  ├─ __init__.py
│  │  ├─ config.py             # Settings, repo root, STORE_WEB_*
│  │  ├─ clock.py              # today_local()
│  │  ├─ db.py                 # engine read-only, SessionLocal, get_db
│  │  ├─ errors.py             # ApiError + handler dạng phẳng
│  │  ├─ schemas.py            # Pydantic response models
│  │  ├─ static_site.py        # mount web/dist + SPA fallback + cảnh báo thiếu dist
│  │  ├─ queries/
│  │  │  ├─ __init__.py
│  │  │  ├─ stores.py
│  │  │  └─ products.py
│  │  ├─ api/
│  │  │  ├─ __init__.py
│  │  │  ├─ health.py
│  │  │  ├─ stores.py
│  │  │  ├─ products.py
│  │  │  └─ meta.py
│  │  └─ main.py               # app, CORS (dev), routers, static_site
│  └─ tests/
│     ├─ conftest.py
│     ├─ test_stores_api.py
│     ├─ test_products_api.py
│     ├─ test_business_rules.py
│     ├─ test_read_only.py
│     └─ test_static_site.py
├─ web/
│  ├─ package.json             # scripts: dev, build, preview, test, typecheck, lint
│  ├─ pnpm-lock.yaml           # COMMIT
│  ├─ tsconfig.json
│  ├─ tsconfig.node.json
│  ├─ vite.config.ts           # port 5173, proxy /api → 5180, test config
│  ├─ index.html               # <html lang="vi">
│  ├─ .env.example             # VITE_API_BASE_URL=
│  ├─ src/
│  │  ├─ main.tsx
│  │  ├─ App.tsx               # Router + QueryClientProvider
│  │  ├─ api/
│  │  │  ├─ client.ts          # fetch wrapper + ApiError
│  │  │  ├─ types.ts           # khớp mục 5
│  │  │  └─ queries.ts         # hooks useStores/useStore/useProducts/useProduct/useCategories
│  │  ├─ pages/
│  │  │  ├─ StoresPage.tsx
│  │  │  ├─ StorePage.tsx
│  │  │  ├─ ProductPage.tsx
│  │  │  └─ NotFoundPage.tsx
│  │  ├─ components/
│  │  │  ├─ Layout.tsx
│  │  │  ├─ StateBlock.tsx     # loading / empty / error(+retry)
│  │  │  ├─ FilterBar.tsx
│  │  │  ├─ ProductTable.tsx
│  │  │  ├─ BatchTable.tsx
│  │  │  └─ Pagination.tsx
│  │  ├─ lib/
│  │  │  ├─ format.ts          # tiền, ngày
│  │  │  └─ filters.ts         # parse/serialize URLSearchParams
│  │  ├─ styles/
│  │  │  ├─ tokens.css
│  │  │  └─ app.css
│  │  └─ test/
│  │     ├─ setup.ts           # jest-dom + msw server lifecycle
│  │     ├─ server.ts          # setupServer
│  │     └─ fixtures.ts        # stores/products/batches mẫu
│  └─ tests/
│     ├─ stores-page.test.tsx
│     ├─ store-page.test.tsx
│     ├─ product-page.test.tsx
│     └─ states.test.tsx
└─ tools/
   └─ db_report.py             # (tuỳ chọn) đối chiếu số liệu, chỉ SELECT
```

Không tạo: `Dockerfile`, compose service, `templates/`, `htmx.min.js`, e2e Playwright, Storybook.

---

## 5. Hợp đồng API chốt (dùng để viết `web/src/api/types.ts` và test)

Chung: tiền tố `/api`, chỉ `GET`, `unit_price` là **string** `"32000.00"`, ngày `YYYY-MM-DD`.

| Endpoint | Tham số | 200 | Lỗi |
|---|---|---|---|
| `GET /api/health` | — | `{"status":"ok","database":"RTS_DB_DEMO"}` | 503 `STORE_WEB_UNAVAILABLE` |
| `GET /api/stores` | — | `{"stores":[{store_id,name,region_id,product_count,sellable_units}]}` | 503 |
| `GET /api/stores/{store_id}` | path `^[A-Za-z0-9-]{1,10}$` | `{store_id,name,region_id,product_count,sellable_units,expired_units}` | 404, 422, 503 |
| `GET /api/stores/{store_id}/products` | `q` ≤100, `category` ≤50, `in_stock` bool, `sort` ∈ `name\|price\|sellable`, `limit` 1–200 (50), `offset` ≥0 | `{store_id,total,limit,offset,items:[...]}` | 404 store, 422, 503 |
| `GET /api/stores/{store_id}/products/{sku}` | path sku ≤20, `include_empty` bool | `{store_id,item}` | 404, 422, 503 |
| `GET /api/categories` | — | `{"categories":["Bakery","Dairy","Dry goods"]}` | 503 |

`items[]`:

```json
{
  "sku": "SKU-0001",
  "barcode": "8930000000011",
  "name": "Fresh milk 1L",
  "category": "Dairy",
  "unit_price": "32000.00",
  "quantity": 40,
  "sellable_quantity": 16,
  "expired_quantity": 24,
  "nearest_expiry": "2026-11-13",
  "batches": [
    {"batch_id": "B-STORE-DN1-SKU-0001-1", "expiry_date": "2026-11-13", "quantity": 16, "sellable": true}
  ]
}
```

Quy ước bắt buộc:
- `quantity` = `inventory.quantity` (gồm hàng hết hạn), 0 nếu không có dòng inventory.
- `sellable_quantity` = `SUM(quantity)` các batch có `expiry_date >= today` **và** `quantity > 0`.
- `expired_quantity` = `SUM(quantity)` các batch có `expiry_date < today` **và** `quantity > 0`.
- **Không** suy ra `expired_quantity = quantity - sellable_quantity` (sai khi có batch quantity 0 hoặc
  khi `inventory` lệch batch trong dữ liệu cũ) — luôn SUM riêng trong SQL.
- `nearest_expiry` = `MIN(expiry_date)` trong các batch bán được; `null` nếu không có.
- `batches` ở danh sách: chỉ `quantity > 0`, sort `(expiry_date, batch_id)`; endpoint chi tiết thêm
  batch `quantity = 0` khi `include_empty=true`.
- `sellable` mỗi batch do **API** quyết (`expiry_date >= today`), web không tự so ngày.
- `in_stock=true` ⟺ `sellable_quantity > 0`; `in_stock=false` ⟺ `sellable_quantity = 0`.
- `total` = số SKU sau lọc (trước phân trang). `offset` > `total` → 200 với `items: []`.
- Header: mọi response JSON là `application/json`; lỗi luôn cùng shape, không HTML.

---

## 6. SQL chuẩn (nguồn duy nhất: `api/app/queries/`)

Mọi tham số chuỗi cast về đúng kiểu cột để không mất index seek (issue #25), giống
`middleware/app/repositories/inventory.py:186-187`.

### 6.1. `queries/stores.py`

```python
STORE_LIST = text("""
    SELECT store_id, name, region_id
    FROM dbo.store
    WHERE is_active = 1
    ORDER BY store_id
""")

STORE_ONE = text("""
    SELECT store_id, name, region_id
    FROM dbo.store
    WHERE store_id = CAST(:store_id AS varchar(10))
      AND is_active = 1
""")

INVENTORY_COUNTS = text("""
    SELECT store_id, COUNT(*) AS product_count
    FROM dbo.inventory
    GROUP BY store_id
""")

BATCH_TOTALS = text("""
    SELECT store_id,
           SUM(CASE WHEN expiry_date >= CAST(:today AS date) THEN quantity ELSE 0 END) AS sellable_units,
           SUM(CASE WHEN expiry_date <  CAST(:today AS date) THEN quantity ELSE 0 END) AS expired_units
    FROM dbo.product_batch
    WHERE quantity > 0
    GROUP BY store_id
""")
```

Ghép trong Python theo `store_id` (3 round trip, không N+1). `product_count` = số dòng inventory
của store (đúng định nghĩa mục 4.2 của `PLAN.md`), không phải số SKU có hàng.

Hàm:
```python
def list_stores(session, today) -> list[dict]
def get_store(session, store_id, today) -> dict | None      # None khi không có/không active
def store_exists_active(session, store_id) -> bool          # dùng chung cho 404 của /products
```

### 6.2. `queries/products.py` — trang sản phẩm

```python
PRODUCT_PAGE = text("""
    SELECT p.sku, p.barcode, p.name, p.category, p.unit_price,
           COALESCE(i.quantity, 0) AS quantity,
           COALESCE(b.sellable_quantity, 0) AS sellable_quantity,
           COALESCE(b.expired_quantity, 0) AS expired_quantity,
           b.nearest_expiry
    FROM dbo.product AS p
    LEFT JOIN dbo.inventory AS i
           ON i.sku = p.sku
          AND i.store_id = CAST(:store_id AS varchar(10))
    OUTER APPLY (
        SELECT SUM(CASE WHEN bb.expiry_date >= CAST(:today AS date) THEN bb.quantity ELSE 0 END) AS sellable_quantity,
               SUM(CASE WHEN bb.expiry_date <  CAST(:today AS date) THEN bb.quantity ELSE 0 END) AS expired_quantity,
               MIN(CASE WHEN bb.expiry_date >= CAST(:today AS date) THEN bb.expiry_date END) AS nearest_expiry
        FROM dbo.product_batch AS bb
        WHERE bb.store_id = CAST(:store_id AS varchar(10))
          AND bb.sku = p.sku
          AND bb.quantity > 0
    ) AS b
    WHERE (:q IS NULL
           OR p.name LIKE :q_like ESCAPE '\\'
           OR p.sku LIKE CAST(:q_like AS varchar(120)) ESCAPE '\\')
      AND (:category IS NULL OR p.category = CAST(:category AS varchar(50)))
      AND (:in_stock IS NULL
           OR (:in_stock = 1 AND COALESCE(b.sellable_quantity, 0) > 0)
           OR (:in_stock = 0 AND COALESCE(b.sellable_quantity, 0) = 0))
    ORDER BY __ORDER__
    OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
""")
```

- `__ORDER__` thay bằng **một trong ba hằng đã viết sẵn** trong code (không nội suy tham số người dùng):
  - `name`: `p.name, p.sku`
  - `price`: `p.unit_price, p.sku`
  - `sellable`: `COALESCE(b.sellable_quantity, 0) DESC, p.sku`
- `q_like` do Python dựng: `f"%{escape_like(q)}%"`, `escape_like` thay `\` → `\\`, `%` → `\%`, `_` → `\_`.
- `total`: cùng mệnh đề `FROM ... WHERE ...` với `SELECT COUNT(*)`, cùng tham số.
- Tên/số: `name` sort theo `p.name` (không dùng collation tiếng Việt đặc biệt; ghi chú trong README).

### 6.3. `queries/products.py` — batch của trang

```python
BATCHES_FOR_SKUS = text("""
    SELECT sku, batch_id, expiry_date, quantity
    FROM dbo.product_batch
    WHERE store_id = CAST(:store_id AS varchar(10))
      AND quantity > 0
      AND sku IN :skus
    ORDER BY sku, expiry_date, batch_id
""").bindparams(bindparam("skus", expanding=True))
```

Trang rỗng thì **bỏ qua** câu này (không gửi `IN ()`, SQL Server lỗi cú pháp).

### 6.4. Chi tiết một SKU

Câu riêng `WHERE p.sku = CAST(:sku AS varchar(20))` (không `LIKE`), rồi lấy **toàn bộ** batch của SKU
đó; `include_empty=false` lọc `quantity > 0`, `true` giữ cả `quantity = 0`; `ORDER BY expiry_date, batch_id`.

`/api/categories`: `SELECT DISTINCT category FROM dbo.product ORDER BY category`.

---

## 7. Task thi công

Mỗi task: file → việc → lệnh kiểm → điều kiện xong.

### Phase 0 — Khung API (buổi 1, ~3 giờ)

**T0.0 Cài Python 3.12** (một lần, ~5 phút)
```powershell
winget install -e --id Python.Python.3.12     # bản 3.12.10, đã kiểm có trong winget
# mở PowerShell MỚI:
py -0p                                        # phải thấy -V:3.12
py -3.12 --version
```
- Cài theo user, không ghi đè 3.14/3.11.
- Nếu winget bị chặn: installer "Windows installer (64-bit)" từ python.org, "Install for me only",
  **không** tick "Add to PATH" (để `py` launcher tự thấy).
- Xong khi `py -3.12 -m venv --help` chạy. Không cài được → dùng 3.11, ghi lý do vào PR.

**T0.1 Venv + deps**
```powershell
cd G:\RetailSync\clients\store-web\api
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
```
Xong khi `.\.venv\Scripts\python.exe -V` in `3.12.x`.

**T0.2 `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `app/__init__.py`, `.gitignore`**
- `requirements.txt`: 5 dòng như D3 (không `jinja2`).
- `requirements-dev.txt`: `-r requirements.txt`, `pytest==8.3.4`, `httpx==0.28.1`.
- `pytest.ini`:
  ```ini
  [pytest]
  pythonpath = .
  testpaths = tests
  ```
- `.gitignore` (ở `clients/store-web/`):
  ```gitignore
  node_modules/
  dist/
  coverage/
  .venv/
  __pycache__/
  *.tsbuildinfo
  .pytest_cache/
  ```
- Kiểm: `cd middleware; pytest --collect-only -q` → vẫn 0 test của store-web.
  `.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt` → OK.

**T0.3 `app/config.py`**
```python
def repo_root() -> Path:
    """Nearest ancestor holding compose.yaml (same idea as demo-pos)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "compose.yaml").is_file():
            return parent
    raise RuntimeError("Repository root not found: no compose.yaml above api/app/config.py.")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    model_config.update(
        env_file=(repo_root() / ".env", ".env"),
        env_file_encoding="utf-8",
    )

    store_web_db_name: str | None = None
    store_web_test_db_name: str = "RTS_WEB_TEST"
    store_web_cors_origins: str = ""
    db_name: str = "RTS_DB"
    db_host: str = "127.0.0.1"
    sqlserver_port: int = 14333
    mssql_sa_password: SecretStr | None = None
    business_utc_offset_hours: int = Field(default=7, ge=-12, le=14)

    @property
    def database_name(self) -> str: ...      # store_web_db_name or db_name
    @property
    def cors_origins(self) -> list[str]: ...  # split ",", bỏ rỗng
```

> **Độ sâu đường dẫn — dễ sai, đã tính:** file này ở `clients/store-web/api/app/config.py`, tức **sâu
> hơn `middleware/app/core/config.py` hai cấp**. Đếm `Path(...).parents`:
> `[0]=app`, `[1]=api`, `[2]=store-web`, `[3]=clients`, `[4]=RetailSync`.
> Vì vậy **`parents[3]` là `clients/`, KHÔNG phải repo root** — chép nguyên `parents[3]` của
> middleware sang đây sẽ đọc sai file `.env` và app im lặng dùng `DB_NAME=RTS_DB` mặc định.
> Dùng `repo_root()` dò ngược theo `compose.yaml` (giống demo-pos) và **không** dựa vào số cấp cố định.
> `tests/test_business_rules.py::test_settings_read_repo_env` phải khẳng định
> `repo_root() / "compose.yaml"` tồn tại và `repo_root().name == "RetailSync"`-kiểu kiểm
> (so `(repo_root() / "database").is_dir()`), để lỗi này không tái diễn.

- Xong khi `python -c "from app.config import settings, repo_root; print(repo_root()); print(settings.database_name)"`
  in đúng repo root và đúng DB trong `.env` (không in mật khẩu).

**T0.4 `app/clock.py`** — chép logic `middleware/app/core/clock.py`; docstring ghi rõ test thay
`app.clock.today_local`; caller phải gọi `clock.today_local()` lúc chạy, không bind sớm.

**T0.5 `app/db.py`** — chép `hq-demo/app/db.py`, `database=... settings.database_name`,
`pool_pre_ping=True`, `hide_parameters=True`, `connect_args={"timeout": 5}`. Không thêm model ORM.

**T0.6 `app/errors.py` + `app/api/health.py` + `app/main.py`**
- `ApiError(status, code, message)`; handler phẳng; `RequestValidationError` → `VALIDATION_ERROR`;
  `Exception` → log + `503 STORE_WEB_UNAVAILABLE`.
- `health.py`: `SELECT DB_NAME()` → `{"status":"ok","database":...}`.
- `main.py`: `FastAPI(title="RetailSync Store Web API")`, CORS nếu `settings.cors_origins`,
  `include_router(health, prefix="/api")`. Chưa mount static (làm ở T4.2).
- Kiểm (cần Docker): `curl.exe http://127.0.0.1:5180/api/health`.

**Điều kiện xong Phase 0:** `/api/health` OK; `pytest` trong `api/` chạy; suite `middleware/` không đổi.

### Phase 1 — Tầng đọc DB + 6 endpoint (buổi 1, ~5 giờ)

**T1.1 `app/schemas.py`** — `StoreCard`, `StoreDetail`, `BatchItem` (có `sellable: bool`),
`ProductItem`, `ProductPage`, `Categories`, `Health`, `ErrorBody`. `unit_price: str` (dựng bằng
`f"{Decimal(v):.2f}"`), `nearest_expiry: date | None`.

**T1.2 `app/queries/stores.py`** — §6.1 + 3 hàm.

**T1.3 `app/queries/products.py`** — §6.2–6.4 + `escape_like` + 3 hằng ORDER BY:
```python
def product_page(session, store_id, today, *, q, category, in_stock, sort, limit, offset) -> tuple[list[dict], int]
def product_detail(session, store_id, sku, today, *, include_empty) -> dict | None
def categories(session) -> list[str]
```

**T1.4 `app/api/stores.py`, `app/api/products.py`, `app/api/meta.py`**
- Validate: path `pattern=ID_PATTERN`, `sort: Literal["name","price","sellable"]`, `limit: int = Query(50, ge=1, le=200)`, `offset: int = Query(0, ge=0)`, `q: str|None = Query(None, max_length=100)`.
- Store không tồn tại/không active → `404 NOT_FOUND` (cả ở `/products`); SKU không có catalog → 404;
  SKU có catalog nhưng không inventory → 200 với `quantity=0`, `sellable_quantity=0`.
- `sort` dựng câu SQL bằng cách chọn hằng theo dict `{"name": ..., "price": ..., "sellable": ...}`.

**T1.5 Đối chiếu số liệu (nghiệm thu Phase 1)**
```powershell
cd G:\RetailSync
docker compose up -d --wait sqlserver
docker compose run --rm migrate
docker compose run --rm --no-deps sqlserver /opt/mssql-tools18/bin/sqlcmd -S sqlserver -U sa -C -d RTS_DB_DEMO -Q "SELECT store_id, COUNT(*), SUM(quantity) FROM dbo.inventory GROUP BY store_id"
```
Kỳ vọng seed: mỗi store 9 SKU; batch `-1` hết hạn `today+3`, `-2` hết hạn `+10/+20/+180` → **tất cả
còn hạn** → `sellable_units` = tổng batch của store (DN1 360, DN2 225, DN3 135), `expired_units = 0`.
DB demo **không có** batch hết hạn — đừng kỳ vọng thấy "hết hạn" trên UI demo; đó là việc của
fixture `RTS_WEB_TEST` (T5.1).

**Điều kiện xong Phase 1:** 6 endpoint đúng shape §5; 3 store khớp `sqlcmd`; 404/422 đúng mã.

### Phase 2 — Khung SPA (buổi 2, ~4 giờ)

**T2.1 Scaffold**
```powershell
cd G:\RetailSync\clients\store-web
pnpm create vite@latest web --template react-ts
cd web
pnpm install
pnpm add react-router-dom @tanstack/react-query
pnpm add -D vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event msw
```
- Giữ version do scaffolder chọn (template có thể pin TypeScript 5.x dù npm có 7.x — **cứ giữ**;
  chỉ nâng khi có lý do). Ghi lại `node -v`, `pnpm -v`, và version thực tế vào `README.md` (T6.1).
- Scripts trong `package.json`:
  ```json
  {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "typecheck": "tsc -p tsconfig.app.json --noEmit",
    "test": "vitest run",
    "test:watch": "vitest"
  }
  ```
  `typecheck` trỏ `tsconfig.app.json` (không dùng `tsc --noEmit` trần vì root `tsconfig.json` là
  solution-style có `references`, sẽ báo lỗi emit). Nếu template không có `tsconfig.app.json` thì
  dùng `tsc --noEmit` sau khi kiểm nó chạy được.
- Xong khi `pnpm dev` mở được trang Vite mặc định.

**T2.2 `vite.config.ts` + `tsconfig.json` + `index.html` + `.env.example`**
```ts
server: {
  port: 5173,
  proxy: { "/api": { target: "http://127.0.0.1:5180", changeOrigin: false } },
},
test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"], include: ["tests/**/*.test.tsx"] },
```
- `index.html`: `<html lang="vi">`, `<title>RetailSync — Sản phẩm theo cửa hàng</title>`.
- `.env.example`: `VITE_API_BASE_URL=` (rỗng = same-origin, dùng proxy/bản build).
- Xong khi `pnpm typecheck` sạch trên code scaffold.

**T2.3 `src/api/client.ts` + `src/api/types.ts`**
```ts
const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}

async function get<T>(path: string, params?: Record<string, string|number|boolean|undefined>): Promise<T>
```
- Bỏ tham số `undefined`/`""`; `in_stock` gửi `"true"/"false"`.
- `res.ok` false → parse `{outcome,code,message}`; parse lỗi → `ApiError(status, "INVALID_RESPONSE", ...)`.
- 503 → `ApiError.code === "STORE_WEB_UNAVAILABLE"`.
- `types.ts`: interface khớp §5 (**`unit_price: string`**, `batches: Batch[]`, `sellable: boolean`).
- Xong khi `pnpm typecheck` sạch.

**T2.4 `src/api/queries.ts`** — hooks TanStack Query:
```ts
useStores()                    // ["stores"]
useStore(id)                   // ["store", id]
useCategories()                // ["categories"]
useProducts(id, filters)       // ["products", id, filters]
useProduct(id, sku, includeEmpty) // ["product", id, sku, includeEmpty]
```
- `filters` là object đã normalize (mục 3.6 `lib/filters.ts`) và được đưa nguyên vào `queryKey`.
- `QueryClient` mặc định: `retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 1`,
  `staleTime: 30_000`.

**T2.5 `src/App.tsx`, `src/main.tsx`, `src/components/Layout.tsx`, `src/styles/tokens.css`, `app.css`**
- Router: `/`, `/stores/:storeId`, `/stores/:storeId/products/:sku`, `*` → `NotFoundPage`.
- `Layout`: header "RetailSync", breadcrumb theo route, `<main id="main">`, skip-link.
- `tokens.css` lấy từ DS-08: `--ink:#222; --line:#777; --soft:#eee; --mid:#d8d8d8; --note:#555;`
  font `"Segoe UI", Arial, sans-serif`, `* { box-sizing: border-box }`.
- `app.css`: bảng gọn, badge "hết hàng", `.expired { text-decoration: line-through; opacity:.6 }`,
  responsive ≤720px (bảng cuộn ngang trong `overflow-x:auto`).
- Focus về `<h1>` khi đổi route (dùng `useEffect` + `ref`, chỉ khi path đổi).

**T2.6 `src/components/StateBlock.tsx`** — 3 biến thể:
- `loading`: 5 dòng skeleton, `aria-busy="true"`.
- `empty`: thông điệp tuỳ ngữ cảnh ("Chưa có cửa hàng nào đang hoạt động." / "Không có sản phẩm khớp bộ lọc." / "Không tìm thấy sản phẩm.").
- `error`: mã lỗi + thông điệp tiếng Việt + nút **"Thử lại"** gọi `refetch()`; 503 ghi rõ "Không kết nối được cơ sở dữ liệu".

**T2.7 Smoke 3 route** — `pnpm dev` + API chạy; `/` gọi `/api/stores` thành công; gõ tay
`/stores/STORE-DN1` chưa có nội dung (page trống ở phase này) nhưng không crash; 404 route hiện trang.

**Điều kiện xong Phase 2:** app chạy, gọi được API thật, `typecheck` sạch, có Layout + StateBlock.

### Phase 3 — Màn hình (buổi 2, ~8 giờ)

**T3.1 `src/lib/filters.ts`**
```ts
type Filters = { q: string; category: string; inStock: boolean; sort: "name"|"price"|"sellable"; limit: number; offset: number };
parseFilters(search: URLSearchParams): Filters      // mặc định thuần, bỏ giá trị rác
serializeFilters(f: Filters): URLSearchParams       // bỏ key mặc định để URL gọn
```
- Giá trị rác (`sort=abc`, `limit=9999`) → quay về mặc định, **không** crash; API vẫn validate lần nữa.

**T3.2 `src/pages/StoresPage.tsx`** — 3 thẻ: tên, khu vực, "9 SKU", "360 đơn vị bán được", link
`/stores/{id}`. Dùng `useStores()`; StateBlock cho loading/empty/error.

**T3.3 `src/components/FilterBar.tsx`** — 4 điều khiển + nút "Xoá lọc":
- ô `q` (debounce 300ms, `useDeferredValue` hoặc timer), `select` danh mục (`useCategories()`),
  `checkbox` "Chỉ còn hàng", `select` sắp xếp (Tên / Giá / Còn bán).
- Mọi thay đổi ghi URL qua `setSearchParams(serializeFilters(...))` và **reset `offset=0`**.
- `aria-live="polite"` hiện "N sản phẩm" cạnh tiêu đề.

**T3.4 `src/components/ProductTable.tsx`** — cột Tên | SKU | Danh mục | Giá | Còn bán | Hạn gần nhất.
- `<table>` + `<caption class="sr-only">`, `<th scope="col">`.
- Hàng có `sellable_quantity === 0` → badge "hết hàng" màu cảnh báo; **không** hiện `quantity` ở cột
  "Còn bán" (nếu cần hiện tổng tồn thì đặt tooltip/cột phụ, không trộn).
- Tên là link tới `/stores/{id}/products/{sku}`.
- Giá từ `format.ts`: `"32000.00"` → `32.000 ₫` (`Intl.NumberFormat("vi-VN", {style:"currency", currency:"VND", maximumFractionDigits:0})`).

**T3.5 `src/components/Pagination.tsx`** — "(offset+1)–(offset+n) / total", nút Trước/Sau là `<button>`
hoặc `<a href>` theo `serializeFilters`; disable khi ở biên; đổi trang giữ nguyên bộ lọc.

**T3.6 `src/pages/StorePage.tsx`** — ghép: `useStore(id)` (tên cửa hàng + thống kê tổng),
`FilterBar`, `ProductTable`, `Pagination`; đọc/ghi bộ lọc từ URL.
- 404 store → StateBlock error "Không tìm thấy cửa hàng" + link về `/` (không phải màn hình trắng).

**T3.7 `src/pages/ProductPage.tsx` + `src/components/BatchTable.tsx`**
- Thẻ: tên, SKU, barcode, danh mục, giá, "Còn bán", "Tổng tồn", "Sắp hết hạn".
- Bảng batch: mã lô, hạn, số lượng, trạng thái. `sellable === false` → gạch ngang + nhãn "hết hạn".
- Link "← Về cửa hàng".

**T3.8 `src/pages/NotFoundPage.tsx` + `src/lib/format.ts` hoàn chỉnh**
- 404 route: "Không tìm thấy trang" + link `/`.
- `format.ts`: `formatMoney(unitPrice: string): string`, `formatDate(iso: string|null): string`
  ("—" khi null), `formatCount(n)`.

**Điều kiện xong Phase 3:** đi hết `/` → store → product; lọc/sort/phân trang **không reload** và URL
đổi; back/forward đúng; 503 có "Thử lại"; tiếng Việt có dấu.

### Phase 4 — Build + phục vụ 1 tiến trình (buổi 3, ~2 giờ)

**T4.1 `pnpm build`** — tạo `web/dist` gồm `index.html` + `assets/*-[hash].js|css`.
- Xong khi `web/dist/index.html` tồn tại và `assets/` có ít nhất 1 file `.js`.
- (`pnpm preview` ở bước này chỉ mở bản build **chưa có API**; dùng để kiểm bundle tải được, không
  phải kiểm dữ liệu — việc đó ở T4.3.)

**T4.2 `api/app/static_site.py`**
```python
DIST = Path(__file__).resolve().parents[2] / "web" / "dist"   # store-web/web/dist

def mount_spa(app: FastAPI) -> None:
    dist = DIST                        # đọc lúc gọi, để test monkeypatch được
    if not (dist / "index.html").is_file():
        logger.warning("web/dist is missing; run `pnpm build` in clients/store-web/web. "
                       "GET / will return 404 until then.")
        return
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise ApiError(404, "NOT_FOUND", f"No API route for /{full_path}.")
        target = (dist / full_path).resolve()
        if full_path and target.is_file() and dist.resolve() in target.parents:
            return FileResponse(target, headers={"Cache-Control": "public, max-age=31536000, immutable"})
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})
```
- Gọi `mount_spa(app)` trong `main.py` **sau** khi include hết router `/api`.
- `/api/*` không tồn tại → dùng `ApiError` để ra **đúng shape lỗi phẳng** (không `{"detail":...}`,
  không `index.html`).
- `dist.resolve() in target.parents` chặn path traversal (`/..%2f..`).
- Thiếu `dist` → log WARNING rõ ràng, không crash; `/` trả 404 JSON có thông điệp hướng dẫn.

**T4.3 Kiểm 1 tiến trình**
```powershell
cd clients/store-web/api
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 5180
# mở http://127.0.0.1:5180  → trang chủ SPA
# mở http://127.0.0.1:5180/api/stores → JSON
# mở http://127.0.0.1:5180/stores/STORE-DN1 (gõ tay) → trả index.html, SPA route đúng
# mở http://127.0.0.1:5180/api/unknown → 404 JSON, KHÔNG phải index.html
```

**Điều kiện xong Phase 4:** 1 tiến trình phục vụ cả web và API; refresh ở route con không 404.

### Phase 5 — Kiểm thử (buổi 3, ~6 giờ)

**T5.1 Tạo DB test + `api/tests/conftest.py`**
```powershell
cd G:\RetailSync
$env:DB_NAME = "RTS_WEB_TEST"; docker compose run --rm migrate; Remove-Item Env:DB_NAME
```
- Guard: `settings.store_web_test_db_name` phải kết thúc `_TEST` và khác `database_name` →
  `pytest.fail(..., pytrace=False)`.
- `test_engine` (session scope, `hide_parameters=True`), `db_session` (transaction + rollback),
  `client` (override `get_db`, `TestClient`).
- Fixture `seeded` (function scope, trong transaction): `WEB-A` active, `WEB-B` active, `WEB-C` inactive;
  `WEB-P1` có batch hết hạn hôm qua + **đúng hôm nay** + `+30`; `WEB-P2` chỉ hết hạn hôm qua;
  `WEB-P3` có catalog không có inventory; `WEB-P4` quantity 0.
- Fixture `today` monkeypatch `app.clock.today_local` = `date(2026,11,10)` cho test biên ổn định.

**T5.2 `api/tests/` — 5 file, 26 test**
- `test_stores_api.py` (6): chỉ store active; `product_count`/`sellable_units`; detail fields;
  404 unknown; 404 inactive; `/products` của store inactive → 404.
- `test_products_api.py` (10): shape + giá 2 chữ số; `total` trước phân trang; `q` theo tên/SKU;
  `q` escape `%`/`_`; `category`; `in_stock=true` dùng `sellable`; `in_stock=false` trả SKU hết hạn;
  `sort` price/sellable; `limit=201`/`sort=abc`/`q` 101 ký tự → 422; SKU không inventory → 0;
  `include_empty`.
- `test_business_rules.py` (6): **batch hết hạn đúng hôm nay vẫn `sellable`**; batch hết hạn không
  tính `sellable` nhưng vào `expired_quantity`; `quantity` = tổng batch; `nearest_expiry` bỏ qua batch
  hết hạn/quantity 0; `today_local` theo offset; `repo_root()` trỏ đúng thư mục có `compose.yaml`.
- `test_read_only.py` (3): mọi `text(...)` bắt đầu `SELECT`, không có
  `INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|TRUNCATE`; không endpoint nào `commit()`/`rollback()`;
  `COUNT(*)` 4 bảng trước/sau bằng nhau.
- `test_static_site.py` (2): dựng `FastAPI` tạm + `register_error_handlers`, `monkeypatch.setattr(static_site, "DIST", tmp_path)`
  với `index.html` giả → `/stores/STORE-DN1` trả `index.html`; `/api/unknown` trả **JSON 404**
  (`{"outcome":"REJECTED","code":"NOT_FOUND",...}`), không trả `index.html`.
  Test này **không cần `pnpm build`** và không cần DB.
- Chạy: `$env:STORE_WEB_TEST_DB_NAME="RTS_WEB_TEST"; .\.venv\Scripts\python.exe -m pytest -q`

**T5.3 `web/src/test/setup.ts`, `server.ts`, `fixtures.ts`**
- `setup.ts`: import `@testing-library/jest-dom/vitest`; `beforeAll(server.listen({onUnhandledRequest:"error"}))`,
  `afterEach(server.resetHandlers)`, `afterAll(server.close)`.
- `server.ts`: `setupServer()` (msw 3).
- `fixtures.ts`: 3 store, 9 product, 1 product có batch hết hạn + **batch hết hạn đúng hôm nay**
  (sellable `true`), 1 product `sellable_quantity: 0`.
- Xong khi `pnpm test` chạy (0 test cũng được, miễn setup không lỗi).

**T5.4 `web/tests/` — 4 file, 15 test**
- `stores-page.test.tsx` (4): render 3 thẻ đúng tên/khu vực/số; link đúng href; loading → skeleton;
  503 → "Thử lại".
- `store-page.test.tsx` (5): render bảng 9 dòng; gõ `q` → request có `q=`; chọn danh mục → `category=`;
  tick "chỉ còn hàng" → `in_stock=true`; đổi sort → `sort=price`; đổi bộ lọc **reset offset**.
- `product-page.test.tsx` (3): batch hết hạn có nhãn + class gạch ngang; "Còn bán" = `sellable_quantity`
  (không phải `quantity`); giá hiển thị `32.000 ₫` từ `"32000.00"`.
- `states.test.tsx` (3): empty → thông điệp rỗng không phải lỗi; 404 store → "Không tìm thấy cửa hàng";
  lỗi 422 → thông điệp chung, không lộ JSON thô.

**T5.5 `pnpm typecheck` + `pnpm test` + `pytest`** — cả ba xanh.
- Nếu có ESLint từ scaffolder: `pnpm lint` sạch, hoặc tắt lint trong script nếu chưa cấu hình
  (ghi rõ trong README).

**Điều kiện xong Phase 5:** `pytest` xanh (cần `RTS_WEB_TEST`), `pnpm test` xanh (không cần DB),
`pnpm typecheck` sạch.

### Phase 6 — README + tích hợp repo (buổi 3, ~2 giờ)

**T6.1 `clients/store-web/README.md`** — 10 mục theo khuôn `clients/demo-pos/README.md`:
1. Yêu cầu: Python 3.12, Node ≥20.19/22.12, pnpm, Docker Desktop, ODBC 18.
2. Chuẩn bị: `docker compose up -d --wait sqlserver` + `docker compose run --rm migrate`.
3. Chạy: **build trước** (`pnpm install && pnpm build`), rồi `uvicorn` → `http://127.0.0.1:5180`.
4. Chạy dev: 2 terminal (API 5180 + `pnpm dev` 5173, proxy `/api`).
5. Cấu hình: biến `.env` dùng lại; `STORE_WEB_DB_NAME`, `STORE_WEB_TEST_DB_NAME`, `STORE_WEB_CORS_ORIGINS`.
6. Màn hình: 3 route + ảnh chụp.
7. Dữ liệu & quy tắc: `sellable` vs `quantity`, `today_local`, cờ `sellable` do API quyết.
8. Kiểm thử: tạo `RTS_WEB_TEST`; `pytest`; `pnpm test`; `pnpm typecheck`.
9. Xử lý sự cố: **`/` 404 → chưa `pnpm build`**; CORS; ODBC; port bận; `node_modules` lỗi → `pnpm install --force`.
10. Ghi chú kỹ thuật: chỉ đọc, không sửa middleware, version thực tế đã cài; đường lui `PLAN.md` mục 11.

**T6.2 `README.md` repo — đúng 2 chỗ**
- Layout: thêm
  `| clients/store-web/ | SPA + read-only API: store list → products at that store |`
- Run: mục con `### Store web app` — 4 dòng lệnh (build web, chạy API, URL, test).

**T6.3 Rà soát cuối**
- `git status` chỉ có `clients/store-web/**` (mới, **không** có `node_modules/`, `dist/`, `.venv/`)
  + `README.md` (2 chỗ).
- `middleware/`, `compose.yaml`, `docs/design/openapi.yaml`, `database/`, `.env` không đổi.
- Chụp ảnh 3 màn hình + output `pytest -q` / `pnpm test` / `pnpm typecheck`.
- Commit nhánh `Quang` (chỉ khi Quang yêu cầu) + PR nháp mô tả: app độc lập, không sửa middleware,
  đọc thẳng DB, **có bước build**.

---

## 8. Lịch 3 buổi

| Buổi | Task | Sản phẩm kiểm được | ~Giờ |
|---|---|---|---|
| 1 | T0.0–T0.6, T1.1–T1.5 | 6 endpoint JSON, số liệu khớp `sqlcmd` | 8 |
| 2 | T2.1–T2.7, T3.1–T3.8 | 3 màn hình SPA, lọc/sort/phân trang qua URL | 12 |
| 3 | T4.1–T4.3, T5.1–T5.5, T6.1–T6.3 | 1 tiến trình, `pytest`+`pnpm test` xanh, README, PR | 10 |

Tổng ~30 giờ ≈ **6 ngày × 5 giờ**. Buổi 2 nặng nhất; nếu trượt, cắt theo thứ tự:
`BatchTable` chi tiết → `Pagination` (dùng `limit=200` tạm) → `FilterBar` debounce (dùng nút "Lọc").
**Không cắt**: cờ `sellable`, 3 trạng thái, `typecheck`.

Nếu buổi 1 trượt vì Docker: làm T0.0–T0.6 + T1.1–T1.4 (code không cần DB), dồn T1.5 sang buổi 2.

---

## 9. Checklist nghiệm thu (đối chiếu `PLAN.md` mục 1)

**Chạy**
- [ ] `pnpm build` một lần; `uvicorn` từ `api/`; `http://127.0.0.1:5180` hiện SPA (không 404).
- [ ] Refresh tại `/stores/STORE-DN1/products/SKU-0001` không 404 (SPA fallback đúng).
- [ ] `/api/unknown` trả **JSON 404**, không trả `index.html`.
- [ ] Chế độ dev: `pnpm dev` 5173 proxy `/api` sang 5180 hoạt động.

**Dữ liệu**
- [ ] `/` hiện 3 store; `/stores/STORE-DN1` hiện 9 SKU.
- [ ] "Còn bán" khớp `SELECT SUM(quantity) FROM dbo.product_batch WHERE store_id='STORE-DN1' AND expiry_date >= CAST(DATEADD(hour,7,SYSUTCDATETIME()) AS date)`.
- [ ] Batch hết hạn đúng hôm nay vẫn tính bán được (test + kiểm tay bằng fixture).
- [ ] `quantity` không xuất hiện ở cột "Còn bán".

**Kiểm thử**
- [ ] `pytest` trong `api/` xanh; `middleware/pytest` không đổi số test.
- [ ] `pnpm test` xanh (không cần DB); `pnpm typecheck` sạch.

**Vệ sinh repo**
- [ ] `git status` không có `node_modules/`, `dist/`, `.venv/`, `.env`, `__pycache__`.
- [ ] `git diff README.md` = 2 chỗ; file khác là mới trong `clients/store-web/`.
- [ ] `compose.yaml`, `middleware/`, `database/`, `openapi.yaml` không đổi.

**Trải nghiệm**
- [ ] Tiếng Việt có dấu; loading/empty/error(503 + "Thử lại")/404 đều có.
- [ ] Lọc/sort/phân trang không reload; URL đổi; back/forward đúng.
- [ ] Bảng có `<caption>`, `<th scope>`, `aria-live` cho số kết quả; focus về `<h1>` khi đổi route.

---

## 10. Rủi ro cụ thể + cách phát hiện sớm

| Rủi ro | Phát hiện sớm | Giảm thiểu |
|---|---|---|
| **Quên `pnpm build` → `/` 404 ngay lúc demo** | Log WARNING lúc khởi động API; checklist | README bước 1 là build; T4.3 kiểm 4 URL; `dist/` đã bị ignore nên không ai tải nhầm bản cũ |
| **`node_modules`/`dist` bị commit** | `git status` ở T6.3 | `clients/store-web/.gitignore`; review trước commit |
| Node/pnpm lệch giữa máy | `pnpm install` lỗi engine | Ghi `engines` + `packageManager`; README ghi Node ≥20.19/22.12 |
| Version React/Vite lệch nhau | Build/typecheck đỏ ngay | Scaffold bằng `pnpm create vite`, không tự ghép số; commit lockfile |
| SPA fallback nuốt `/api/*` | Test T5.2 cuối | Kiểm `full_path.startswith("api/")` trước khi trả `index.html` |
| Client tự tính hết hạn (sai múi giờ máy người xem) | Test `BatchTable` + review | API trả `sellable`; web chỉ hiển thị |
| `quantity` hiển thị như "còn bán" | Test `product-page.test.tsx` | Cột "Còn bán" đọc `sellable_quantity` |
| `total`/phân trang sai khi lọc `in_stock` | Test `total` + `in_stock_*` (API) | Lọc/sort/đếm trong cùng SQL |
| Sai múi giờ server | `test_batch_expiring_today_is_sellable` | `today_local()` + `:today`, không `GETDATE()` |
| `q` chứa `%`/`_` khớp sai | `test_q_escapes_wildcards` | `ESCAPE '\'` + `escape_like` |
| `pytest` store-web ghi vào `RTS_DB_TEST` của nhóm | Guard fail cứng trong conftest | `STORE_WEB_TEST_DB_NAME` |
| CORS dev cấu hình sai | Mở 5173 thấy lỗi CORS | CORS chỉ cho 5173; mặc định dùng proxy |
| Review nặng vì SPA | PR mô tả rõ + ảnh | Chia commit: api → web → build/docs |
| Schema nhóm đổi | Suite API đỏ ngay | SQL gom `queries/`; đường lui mục 11 |

---

## 11. Trạng thái môi trường (cần xử lý trước T0.6)

Đã kiểm trên máy này (10/11/2026):
- `docker version` → **daemon chưa chạy**; `127.0.0.1:14333` và `8443` đóng → **chưa có DB demo/test**.
- Python: có `3.14` (mặc định) và `3.11`; **chưa có 3.12** → cài ở T0.0 bằng winget (3.12.10).
- Node 24.13, npm 11.6.2, pnpm 12.18, git 2.52 → đủ cho Vite 8.
- ODBC Driver 18 (64-bit) đã cài (và 17).
- Port 5180/5173 chưa kiểm; kiểm ở T0.6/T2.1.

Bắt đầu buổi 1: T0.0 (cài 3.12) → bật Docker Desktop → `docker compose up -d --wait sqlserver` +
`docker compose run --rm migrate` → T0.1.

Lưu ý: Phase 2 (khung SPA) **không cần DB**, chỉ cần API chạy được `/api/health` hoặc mock msw —
nên Docker trục trặc vẫn tiến được T2.1–T2.6.

---

## 12. Việc không làm trong kế hoạch này

- Không sửa `middleware/`, `compose.yaml`, `docs/design/openapi.yaml`, `database/`, `README.md`
  ngoài 2 chỗ ở T6.2.
- Không thêm compose service, `Dockerfile`, auth, bán hàng, ghi DB, migration.
- Không SSR/Next.js, không Tailwind (phase này), không Storybook, không e2e Playwright.
- Không codegen OpenAPI → TS; `types.ts` viết tay theo §5, có test API làm lưới an toàn.
- Không dùng CDN; mọi asset nằm trong bundle Vite.
- Không tạo `tools/db_report.py` trước khi 3 màn hình xong (tuỳ chọn sau, chỉ `SELECT`).
