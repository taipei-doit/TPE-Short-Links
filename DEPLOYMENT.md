# Deployment Guide

This guide covers deploying the TPE Short Links application with:
- **Frontend**: Firebase Hosting (url.taipei)
- **Backend**: Cloud Run
- **Database**: Cloud SQL PostgreSQL

## Prerequisites

- Google Cloud CLI (`gcloud`) installed and authenticated
- Firebase CLI (`firebase`) installed
- Access to the `doit-dic-itteam` GCP project

```bash
# Install CLIs if needed
npm install -g firebase-tools
brew install google-cloud-sdk  # or see https://cloud.google.com/sdk/docs/install

# Login to both
gcloud auth login
firebase login
```

---

## Part 1: Cloud SQL PostgreSQL Setup

### 1.1 Create Cloud SQL Instance

```bash
# Set your project
gcloud config set project doit-dic-itteam

# Create PostgreSQL instance (this takes ~10 minutes)
gcloud sql instances create tpe-shortlinks-db \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=asia-east1 \
  --root-password=YOUR_ROOT_PASSWORD \
  --storage-type=SSD \
  --storage-size=10GB \
  --availability-type=zonal
```

### 1.2 Create Database and User

```bash
# Create database
gcloud sql databases create tpe_short_links --instance=tpe-shortlinks-db

# Create application user
gcloud sql users create tpe_admin \
  --instance=tpe-shortlinks-db \
  --password=YOUR_SECURE_PASSWORD
```

### 1.3 Get Connection Details

```bash
# Get connection name (needed for Cloud Run)
gcloud sql instances describe tpe-shortlinks-db --format='value(connectionName)'
# Output: doit-dic-itteam:asia-east1:tpe-shortlinks-db

# Get public IP (needed for local migration)
gcloud sql instances describe tpe-shortlinks-db --format='value(ipAddresses[0].ipAddress)'
```

---

## Part 2: Database Migration

### Option A: Using Cloud SQL Proxy (Recommended)

```bash
# Download Cloud SQL Proxy
curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.8.2/cloud-sql-proxy.darwin.arm64
chmod +x cloud-sql-proxy

# Start proxy in background (connects to localhost:5432)
./cloud-sql-proxy doit-dic-itteam:asia-east1:tpe-shortlinks-db &

# Create backend/.env.production
cat > backend/.env.production << 'EOF'
DATABASE_URL=postgresql+psycopg://tpe_admin:YOUR_SECURE_PASSWORD@localhost:5432/tpe_short_links
ALLOW_HTTP_URLS=false
SHORTLINK_CODE_LENGTH=4
RESERVED_CODES=api,docs,admin,health,metrics
PUBLIC_BASE_URL=https://YOUR_CLOUD_RUN_URL
EOF

# Run migrations
cd backend
source .venv/bin/activate  # or create venv if not exists
pip install -r requirements.txt

# Point to production env
export $(cat .env.production | xargs)
alembic upgrade head
```

### Option B: Using Public IP (Requires Authorized Network)

```bash
# Add your IP to authorized networks
MY_IP=$(curl -s ifconfig.me)
gcloud sql instances patch tpe-shortlinks-db --authorized-networks=$MY_IP

# Get public IP
PUBLIC_IP=$(gcloud sql instances describe tpe-shortlinks-db --format='value(ipAddresses[0].ipAddress)')

# Create .env.production with public IP
cat > backend/.env.production << EOF
DATABASE_URL=postgresql+psycopg://tpe_admin:YOUR_SECURE_PASSWORD@$PUBLIC_IP:5432/tpe_short_links
ALLOW_HTTP_URLS=false
SHORTLINK_CODE_LENGTH=4
RESERVED_CODES=api,docs,admin,health,metrics
PUBLIC_BASE_URL=https://YOUR_CLOUD_RUN_URL
EOF

# Run migrations
cd backend
source .venv/bin/activate
export $(cat .env.production | xargs)
alembic upgrade head
```

---

## Part 3: Backend Deployment (Cloud Run)

### 3.1 Build and Push Docker Image

```bash
# Enable required APIs
gcloud services enable run.googleapis.com
gcloud services enable sqladmin.googleapis.com
gcloud services enable artifactregistry.googleapis.com

# Create Artifact Registry repository
gcloud artifacts repositories create tpe-shortlinks \
  --repository-format=docker \
  --location=asia-east1

# Configure Docker authentication
gcloud auth configure-docker asia-east1-docker.pkg.dev

# Build and push
cd backend
docker build -t asia-east1-docker.pkg.dev/doit-dic-itteam/tpe-shortlinks/api:latest .
docker push asia-east1-docker.pkg.dev/doit-dic-itteam/tpe-shortlinks/api:latest
```

### 3.2 Deploy to Cloud Run

```bash
gcloud run deploy tpe-shortlinks-api \
  --image=asia-east1-docker.pkg.dev/doit-dic-itteam/tpe-shortlinks/api:latest \
  --platform=managed \
  --region=asia-east1 \
  --allow-unauthenticated \
  --add-cloudsql-instances=doit-dic-itteam:asia-east1:tpe-shortlinks-db \
  --set-env-vars="DATABASE_URL=postgresql+psycopg://tpe_admin:YOUR_SECURE_PASSWORD@/tpe_short_links?host=/cloudsql/doit-dic-itteam:asia-east1:tpe-shortlinks-db" \
  --set-env-vars="ALLOW_HTTP_URLS=false" \
  --set-env-vars="SHORTLINK_CODE_LENGTH=4" \
  --set-env-vars="RESERVED_CODES=api,docs,admin,health,metrics" \
  --set-env-vars="PUBLIC_BASE_URL=https://tpe-shortlinks-api-HASH-de.a.run.app" \
  --set-env-vars="FIREBASE_PROJECT_ID=your-firebase-project-id"
```

**Note**: After deployment, get the Cloud Run URL and update `PUBLIC_BASE_URL`:
```bash
gcloud run services describe tpe-shortlinks-api --region=asia-east1 --format='value(status.url)'
```

---

## Part 4: Frontend Deployment (Firebase Hosting)

### 4.1 Configure Frontend Environment

```bash
# Create production environment file
cat > frontend/.env.production << 'EOF'
VITE_API_BASE_URL=https://YOUR_CLOUD_RUN_URL
VITE_FIREBASE_API_KEY=your-api-key
VITE_FIREBASE_AUTH_DOMAIN=your-project-id.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=your-project-id
VITE_FIREBASE_APP_ID=1:123456789:web:abcdef
EOF

# Example:
# VITE_API_BASE_URL=https://tpe-shortlinks-api-abc123-de.a.run.app
```

### 4.2 Build and Deploy

```bash
cd frontend
npm install
npm run build

# Deploy to Firebase
cd ..
firebase deploy --only hosting
```

The frontend will be available at:
- https://url-taipei.web.app
- https://url-taipei.firebaseapp.com
- https://url.taipei (custom domain)

---

## Part 5: Custom Domain Setup (url.taipei)

The custom domain `url.taipei` is already connected in Firebase Console. If you need to verify:

1. Go to [Firebase Console](https://console.firebase.google.com)
2. Select project `doit-dic-itteam`
3. Go to Hosting > url-taipei site
4. Verify domain status is "Connected"

### DNS Records Required

At your domain registrar, ensure these records exist:
- **A record**: `@` → Firebase IP addresses
- **TXT record**: For domain verification

Firebase provides the exact values in the console.

---

## Environment Variables Summary

### Backend (.env.production)

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | Cloud SQL connection string | `postgresql+psycopg://user:pass@/db?host=/cloudsql/...` |
| `ALLOW_HTTP_URLS` | Allow non-HTTPS URLs | `false` |
| `SHORTLINK_CODE_LENGTH` | Short code length | `4` |
| `RESERVED_CODES` | Blocked codes | `api,docs,admin,health,metrics` |
| `PUBLIC_BASE_URL` | Backend public URL | `https://api.url.taipei` |
| `FIREBASE_PROJECT_ID` | Enforce/verify Firebase ID tokens | `doit-dic-itteam` |

### Frontend (.env.production)

| Variable | Description | Example |
|----------|-------------|---------|
| `VITE_API_BASE_URL` | Backend API URL | `https://tpe-shortlinks-api-xxx.a.run.app` |
| `VITE_FIREBASE_API_KEY` | Firebase web API key | `...` |
| `VITE_FIREBASE_AUTH_DOMAIN` | Firebase auth domain | `your-project-id.firebaseapp.com` |
| `VITE_FIREBASE_PROJECT_ID` | Firebase Project ID | `your-project-id` |
| `VITE_FIREBASE_APP_ID` | Firebase Web App ID | `1:...:web:...` |

---

## Part 6: Admin login email

The backend sends the magic link itself (`POST /api/auth/login-link`); there is
no Cloud Function any more. Only whitelisted admins (`admin_users` table) get
mail, at most one per address per `LOGIN_LINK_COOLDOWN_SECONDS`.

Routes, tried in order until one succeeds:

1. **City mail relay** for `RELAY_DOMAINS` (default `gov.taipei`): needs
   `RELAY_URL`, `RELAY_TOKEN`, `RELAY_CA_PEM`, and the service's fixed egress IP
   on the relay's allow list.
2. **SMTP** (Gmail app password): `SMTP_USER`, `SMTP_PASS`, optional
   `SMTP_FROM` / `SMTP_HOST` / `SMTP_PORT`. Used for other domains and whenever
   the relay fails.
3. **Firebase Auth's own email** (its template and mail servers, no extra
   setting): last resort when both of the above fail, so admins can always sign
   in. Edit its wording/language under Authentication → Templates → Email link.

`LOGIN_CONTINUE_URL` is where the link opens and must be a Firebase Auth
authorized domain.

---

## Credentials Checklist

The following credentials are needed (keep these secure and in `.gitignore`):

1. **Cloud SQL Password** (`tpe_admin` user password)
2. **GCP Service Account** (if using CI/CD)
3. **Firebase token** (if using CI/CD: `firebase login:ci`)

All `.env*` files (except `.env.example`) are in `.gitignore`.

---

## Quick Commands Reference

```bash
# Check Cloud SQL status
gcloud sql instances describe tpe-shortlinks-db

# View Cloud Run logs
gcloud run services logs read tpe-shortlinks-api --region=asia-east1

# Redeploy backend (image only; keeps existing env vars and Cloud SQL)
docker build -t asia-east1-docker.pkg.dev/doit-dic-itteam/tpe-shortlinks/api:latest backend/
docker push asia-east1-docker.pkg.dev/doit-dic-itteam/tpe-shortlinks/api:latest
gcloud run deploy tpe-shortlinks-api --image=asia-east1-docker.pkg.dev/doit-dic-itteam/tpe-shortlinks/api:latest --region=asia-east1

# Redeploy frontend
cd frontend && npm run build && cd .. && firebase deploy --only hosting

# Run migrations
cd backend && export $(cat .env.production | xargs) && alembic upgrade head
```

---

## Redeploy with env vars (first deploy or when changing env)

If you need to pass env vars again (e.g. first deploy or changing `PUBLIC_BASE_URL`), avoid inline `--set-env-vars` in zsh:

- **Double quotes** let zsh interpret `^` (history expansion), so `"^#^..."` can break and cause `unrecognized arguments`.
- **Trailing space after `\`** breaks line continuation; the next line runs as a separate command (`no such file or directory: --image=...`).

**Option A – Use an env file (recommended)**

Create `backend/env.yaml` (add to `.gitignore`; do not commit secrets):

```yaml
CLOUD_SQL_CONNECTION_NAME: "doit-dic-itteam:asia-east1:tpe-shortlinks-db"
DATABASE_URL: "postgresql+psycopg://tpe_admin:YOUR_PASSWORD@/tpe_short_links?host=/cloudsql/doit-dic-itteam:asia-east1:tpe-shortlinks-db"
ALLOW_HTTP_URLS: "false"
SHORTLINK_CODE_LENGTH: "4"
RESERVED_CODES: "api,docs,admin,health,metrics"
PUBLIC_BASE_URL: "https://url.taipei"
```

Then deploy (no commas/special chars in the shell):

```bash
gcloud run deploy tpe-shortlinks-api \
  --image=asia-east1-docker.pkg.dev/doit-dic-itteam/tpe-shortlinks/api:latest \
  --platform=managed \
  --region=asia-east1 \
  --allow-unauthenticated \
  --add-cloudsql-instances=doit-dic-itteam:asia-east1:tpe-shortlinks-db \
  --env-vars-file=backend/env.yaml
```

**Option B – Inline with single quotes**

Use **single quotes** so zsh does not touch `^` or other chars, and ensure **no space after the backslash** at the end of each line:

```bash
gcloud run deploy tpe-shortlinks-api \
  --image=asia-east1-docker.pkg.dev/doit-dic-itteam/tpe-shortlinks/api:latest \
  --platform=managed \
  --region=asia-east1 \
  --allow-unauthenticated \
  --add-cloudsql-instances=doit-dic-itteam:asia-east1:tpe-shortlinks-db \
  --set-env-vars='^#^CLOUD_SQL_CONNECTION_NAME=doit-dic-itteam:asia-east1:tpe-shortlinks-db#DATABASE_URL=postgresql+psycopg://tpe_admin:YOUR_PASSWORD@/tpe_short_links#ALLOW_HTTP_URLS=false#SHORTLINK_CODE_LENGTH=4#RESERVED_CODES=api,docs,admin,health,metrics#PUBLIC_BASE_URL=https://url.taipei'
```
