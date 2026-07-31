# 臺北市短網址服務（TPE Short Links）

臺北市政府內部使用的短網址服務。

- **民眾端（轉址）**：`https://url.taipei/{代碼}` → 302 轉址至原始網址
- **管理介面**：網址不對外公開，請向團隊索取（管理員以電子郵件魔術連結登入）

## 系統架構

| 元件 | 技術 | 部署位置 |
|---|---|---|
| 後端 API＋轉址 | Python / FastAPI | Cloud Run `tpe-shortlinks-api`（asia-east1），`url.taipei` 網域直接指向此服務 |
| 管理介面 | React / Vite / Mantine | Firebase Hosting |
| 資料庫 | PostgreSQL | Cloud SQL `tpe-shortlinks-db`（asia-east1） |
| 登入寄信 | Firebase Functions | `sendAdminLoginLink` 等（`functions/index.js`） |

GCP／Firebase 專案：`doit-dic-itteam`

## 功能與規則

- 建立短網址：`url.taipei/{代碼}`，代碼區分大小寫；可自動產生（預設 4 碼，避開封鎖字詞）或自訂（1–32 字元，可含中文）
- **代碼永不重用**：資料列永不刪除，代碼一經使用（含已停用）不再重新配發
- **可修改指向**：既有短網址可直接編輯原始網址（管理頁鉛筆按鈕），不需停用重建
- 無效、已過期、已停用、保留字的短網址，一律 302 轉址至 `/404.html` 中文友善頁
- 標籤為必填；有效期限可設為永久或指定時間
- 同一原始網址若已有使用中的短網址，重複建立會回 409 提示沿用
- 管理 API（`/api/*`）需 Firebase 管理員登入；管理員名單於管理介面「管理員」頁維護

## 本機開發

### 1) 啟動 PostgreSQL（僅跑完整後端需要；單純跑測試可跳過）

```bash
docker compose up -d
```

### 2) 後端

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows（macOS/Linux 用 source .venv/bin/activate）
pip install -r requirements.txt -r requirements-dev.txt
copy .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

後端跑在 `http://localhost:8000`。未設定 `FIREBASE_PROJECT_ID` 時會略過登入驗證（方便本機開發）。

### 3) 前端

```bash
cd frontend
npm install
copy .env.example .env
npm run dev
```

前端跑在 `http://localhost:5173`。

## 測試

後端測試使用記憶體內 SQLite，**不需要 Docker 與資料庫**：

```bash
cd backend
.venv\Scripts\python -m pytest tests/
```

前端型別檢查＋打包驗證：

```bash
cd frontend
npm run build
```

## 部署（零停機）

改後端就部署後端、改前端就部署前端，兩者互相獨立。建議順序：先後端、後前端。

### 後端（Cloud Run，本機不需 Docker）

```bash
gcloud builds submit backend --tag asia-east1-docker.pkg.dev/doit-dic-itteam/tpe-shortlinks/api:latest
gcloud run deploy tpe-shortlinks-api ^
  --image=asia-east1-docker.pkg.dev/doit-dic-itteam/tpe-shortlinks/api:latest ^
  --region=asia-east1
```

環境變數與 Cloud SQL 連線會自動沿用既有設定。Cloud Run 會等新版本健康檢查通過才切換流量，服務不中斷。

### 前端（Firebase Hosting）

```bash
cd frontend && npm run build && cd ..
firebase deploy --only hosting
```

需要根目錄 `.firebaserc` 與 `frontend/.env.production`（皆已 gitignore，不在版本庫內；新機器設定時向團隊索取，或參考 `DEPLOYMENT.md`）。

## API 一覽

| 方法與路徑 | 說明 |
|---|---|
| `POST /api/links` | 建立短網址（可帶自訂 `code`） |
| `GET /api/links?query=&tag_id=&status=&limit=&offset=` | 查詢清單 |
| `PATCH /api/links/{code}` | 修改原始網址與／或有效期限（只更新有傳的欄位；已停用者須先啟用） |
| `POST /api/links/{code}/disable` | 停用 |
| `POST /api/links/{code}/enable` | 重新啟用 |
| `GET /api/links/export` | 匯出 CSV |
| `GET /api/links/{code}/qrcode` | 下載 QR Code PNG |
| `GET /api/tags`、`POST /api/tags`、`DELETE /api/tags/{id}` | 標籤管理 |
| `GET/POST/DELETE /api/blocked-words` | 封鎖字詞管理 |
| `GET /404.html` | 失效連結的中文提示頁 |
| `GET /{code}` | 轉址（民眾端，無需登入） |

## 相關文件

- [`DEPLOYMENT.md`](DEPLOYMENT.md) — 完整部署與初始建置指南（Cloud SQL、網域、Functions 設定）
- [`STATUS_EXPLANATION.md`](STATUS_EXPLANATION.md) — 短網址狀態（使用中／過期／停用）與轉址行為說明
- [`AUTH_SETUP.md`](AUTH_SETUP.md) — 管理員魔術連結登入設定
- [`TAGS_AND_WORDS.md`](TAGS_AND_WORDS.md) — 標籤與封鎖字詞維護說明
