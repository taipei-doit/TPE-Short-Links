# 臺北市短網址服務（TPE Short Links）

臺北市政府內部使用的短網址服務。

- **轉址**：`https://url.taipei/{代碼}` → 302 轉址至原始網址
- **檔案分享**：`https://url.taipei/f/{代碼}` → 輸入 PIN 碼後下載檔案

## 系統架構

| 元件 | 技術 | 部署位置 |
|---|---|---|
| 後端 API＋轉址 | Python / FastAPI | Cloud Run `tpe-shortlinks-api`（asia-east1），`url.taipei` 網域直接指向此服務 |
| 管理介面 | React / Vite / Mantine | Firebase Hosting |
| 資料庫 | PostgreSQL | Cloud SQL `tpe-shortlinks-db`（asia-east1） |
| 分享檔案儲存 | Cloud Storage | 私有儲存桶（`FILE_STORAGE_BUCKET`），僅後端以服務帳號存取 |
| 登入寄信 | Firebase Functions | `sendAdminLoginLink` 等（`functions/index.js`） |

## 功能與規則

- 建立短網址：`url.taipei/{代碼}`，代碼區分大小寫；可自動產生（預設 4 碼，避開封鎖字詞）或自訂（1–32 字元，可含中文）
- **代碼永不重用**：資料列永不刪除，代碼一經使用（含已停用）不再重新配發
- **可修改指向**：既有短網址可直接編輯原始網址（管理頁鉛筆按鈕），不需停用重建
- 無效、已過期、已停用、保留字的短網址，一律 302 轉址至 `/404.html` 中文友善頁
- 標籤為必填；有效期限可設為永久或指定時間
- 同一原始網址若已有使用中的短網址，重複建立會回 409 提示沿用
- 管理 API（`/api/*`）需 Firebase 管理員登入；管理員名單於管理介面「管理員」頁維護

### 檔案分享（PIN 碼保護）

一般雲端硬碟的分享連結無法加密碼，因此本服務提供需輸入 PIN 碼才能下載的檔案分享。

- **只有管理員能上傳**；拿到連結的人只能下載，不能瀏覽清單、修改或刪除任何東西
- **一個連結可放多個檔案**，共用同一組 PIN 碼；要分享七份文件就是一個連結一組 PIN，不是七個。事後還能再加入或移除檔案，連結與 PIN 都不變
- 分享連結為 `url.taipei/f/{代碼}`，與短網址各自獨立，代碼不會互相衝突，同樣**永不重用**
- **PIN 碼為 8 碼英數字組合**（可自訂或自動產生）。自動產生時會排除容易看錯的 `O`、`I`、`0`、`1`，並保證至少各含一個英文字母與數字；輸入時不分大小寫
- PIN 碼以 PBKDF2 雜湊儲存，**建立當下顯示一次後即無法再查看**；忘記時只能重新產生一組新的（舊的立即失效）
- 連續輸入錯誤 5 次，該連結鎖定 15 分鐘（次數記錄在資料庫，多台執行個體皆有效）
- 儲存桶為私有，**不對外發放任何讀取用的簽章網址**；檔案一律由後端在驗證 PIN 後串流輸出，輸入正確後取得的下載網址 5 分鐘後失效
- 下載頁在輸入 PIN 碼**之前只顯示檔案數量、總大小與有效期限**，不顯示檔名——任何人都能打開這一頁，而檔名本身可能就是敏感資訊
- 可設定有效期限（預設 7 天）、停用、重新啟用；**刪除會真正把檔案從儲存桶移除**（可整包刪或只刪其中一個檔案），僅保留紀錄供查核
- 失效、過期、停用、尚無檔案、不存在的分享連結，一律 302 轉址至 `/404.html`，無法用來探測哪些代碼存在
- **民眾端下載頁支援中／英／日／韓四語**：預設依瀏覽器 `Accept-Language` 判斷（不支援的語言退回正體中文），頁面右上角可即時切換（不需重新載入，選擇會記在瀏覽器），也可用 `?lang=zh-Hant|en|ja|ko` 指定。管理介面維持正體中文

#### 檔案大小與上傳路徑

Cloud Run **在邊緣就會擋掉超過 32 MiB 的請求主體**（實測：28 MB 通過、32 MB 回 413），大檔根本進不到本服務。因此上傳有兩條路，由後端決定：

| 情況 | 路徑 | 上限 |
|---|---|---|
| 有物件儲存（正式環境） | 後端開 resumable session，**瀏覽器直接傳到 Cloud Storage**，只把結果回報給後端 | `MAX_FILE_MB`（預設 2048 MB） |
| 無物件儲存（本機開發） | 位元組經由後端轉送 | `MAX_UPLOAD_MB`（預設 30 MB，須低於 Cloud Run 的 32 MiB） |

直傳的 session 是用服務帳號自己的憑證開的，**不需要簽章金鑰**，所以在 Cloud Run 預設身分下就能運作。它只是「可寫入某一個物件名稱」的權限，只發給已登入的管理員；檔案落地後，後端會**從儲存空間回讀實際大小與型別**再登錄，不採信前端宣稱的值。瀏覽器直傳需要儲存桶的 CORS 設定，見 `backend/gcs-cors.json`。

下載一律走後端串流（回應串流不受 32 MiB 限制，該限制只管請求），這樣儲存桶才能保持私有、PIN 也才是唯一的關卡。

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

### 資料庫 schema 變更

機關網路封鎖 Cloud SQL 的 3307 埠，無法用 `cloud-sql-proxy` 直連，因此 migration 一律在 GCP 內部以 Cloud Run Job 執行：

```bash
gcloud run jobs execute db-migrate --region=asia-east1 --wait
```

### 檔案分享功能的一次性建置

```bash
# 1) 建立私有儲存桶（統一儲存桶層級存取、封鎖所有公開存取）
gcloud storage buckets create gs://tpe-shortlinks-files \
  --location=asia-east1 \
  --uniform-bucket-level-access --public-access-prevention

# 2) 讓瀏覽器能直傳（大檔唯一的路徑）
gcloud storage buckets update gs://tpe-shortlinks-files --cors-file=backend/gcs-cors.json

# 3) 讓 Cloud Run 服務帳號可讀寫該桶
gcloud storage buckets add-iam-policy-binding gs://tpe-shortlinks-files \
  --member=serviceAccount:<CLOUD_RUN_SA> --role=roles/storage.objectAdmin

# 4) 告訴後端要用哪個桶，並放寬逾時（大檔下載可能超過預設 300 秒）
gcloud run services update tpe-shortlinks-api --region=asia-east1 \
  --update-env-vars=FILE_STORAGE_BUCKET=tpe-shortlinks-files --timeout=900
```

過期檔案的清理由 Cloud Run Job `purge-expired-files` 負責（`scripts/purge_expired_files.py`），
Cloud Scheduler `purge-expired-files-daily` 每日 03:00 觸發，預設過期後再保留 30 天才真正抹除。
先加 `--dry-run` 可以只看會刪哪些、不動任何東西。

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
| `POST /api/shares` | 建立分享（`note`、`expires_at`、`pin`），回傳連結與 PIN 碼（PIN 僅此一次） |
| `GET /api/shares?query=&status=&limit=&offset=` | 分享清單（含各自的檔案） |
| `PATCH /api/shares/{code}` | 修改有效期限與／或備註 |
| `POST /api/shares/{code}/upload-session` | 詢問該把檔案位元組送到哪裡，回傳 `mode=resumable\|proxy` 與上傳網址 |
| `POST /api/shares/{code}/files` | 經後端轉送上傳（`file`＋`upload_token`；受 32 MiB 限制） |
| `POST /api/shares/{code}/files/finalize` | 瀏覽器直傳完成後登錄檔案（`upload_token`） |
| `DELETE /api/shares/{code}/files/{file_id}` | 永久刪除單一檔案，其餘不受影響 |
| `POST /api/shares/{code}/regenerate-pin` | 重新產生 PIN 碼（舊碼立即失效，並解除鎖定） |
| `POST /api/shares/{code}/disable`、`/enable` | 停用／重新啟用分享 |
| `DELETE /api/shares/{code}` | 永久刪除整包檔案內容（保留紀錄） |
| `GET /404.html` | 失效連結的中文提示頁 |
| `GET /f/{code}?lang=` | 檔案下載頁（民眾端，無需登入；中／英／日／韓） |
| `POST /f/{code}/verify` | 驗證 PIN 碼，回傳檔案清單與 5 分鐘有效的下載網址（民眾端）；錯誤回傳 `{"detail":{"error":"wrong_pin\|locked\|not_found",…}}` 供前端翻譯 |
| `GET /f/{code}/download/{file_id}?token=` | 下載單一檔案（民眾端，需有效下載權杖） |
| `GET /{code}` | 轉址（民眾端，無需登入） |

## 相關文件

- [`DEPLOYMENT.md`](DEPLOYMENT.md) — 完整部署與初始建置指南（Cloud SQL、網域、Functions 設定）
- [`STATUS_EXPLANATION.md`](STATUS_EXPLANATION.md) — 短網址狀態（使用中／過期／停用）與轉址行為說明
- [`AUTH_SETUP.md`](AUTH_SETUP.md) — 管理員魔術連結登入設定
- [`TAGS_AND_WORDS.md`](TAGS_AND_WORDS.md) — 標籤與封鎖字詞維護說明
