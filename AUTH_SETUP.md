# Firebase Admin Authentication Setup

This app uses **Option 1: Magic Link** from `firebase_authentication.md`. Only whitelisted admin emails can request a login link; clicking the link signs them in with Firebase Auth. All `/api/*` routes require a valid Firebase ID token when `FIREBASE_APP_ID` is set.

---

## 1. Firebase Console

1. **Create or use a Firebase project** and note the **Project ID** and **Web app** (if you don’t have one, add a Web app in Project settings).

2. **Enable Email/Password sign-in method**
   - Authentication → Sign-in method → Email/Password → Enable, then **Save**.
   - Under “Email link (passwordless sign-in)”, enable **Email link** so magic links work.

3. **Authorized domains**
   - Authentication → Settings → Authorized domains.
   - Add your frontend origin (e.g. `url.taipei`, `url-taipei.web.app`, `localhost` for dev).

4. **Get Web app config**
   - Project settings → Your apps → Web app → copy:
     - `apiKey`, `authDomain`, `projectId`, `appId`.
   - Use these in the frontend `.env` (see below). The **appId** is also used in the backend as `FIREBASE_APP_ID` for token verification.

---

## 2. Frontend environment

In `frontend/.env` (and `frontend/.env.production` for production build):

```env
VITE_API_BASE_URL=https://your-backend-url
VITE_FIREBASE_API_KEY=your-api-key
VITE_FIREBASE_AUTH_DOMAIN=your-project-id.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=your-project-id
VITE_FIREBASE_APP_ID=1:123456789:web:abcdef
```

---

## 3. Backend environment

- **Local dev (no auth):** Leave `FIREBASE_APP_ID` unset. API calls are not checked.
- **Production (auth required):** Set the same Web app **App ID** as in the frontend:

```env
FIREBASE_APP_ID=1:123456789:web:abcdef
# Optional, for reference:
# FIREBASE_PROJECT_ID=your-project-id
```

---

## 4. Login email (backend)

`POST /api/auth/login-link` checks the email against the admin whitelist
(PostgreSQL `admin_users`, managed on the **Admins** page; `ADMIN_WHITELIST`
env only bootstraps an empty table), creates the Firebase sign-in link, and
mails it. Delivery falls through three independent routes: city mail relay →
SMTP → Firebase Auth's own template email. Settings are listed in
[`DEPLOYMENT.md`](DEPLOYMENT.md) Part 6.

---

## 5. Deploy

1. **Backend:** Set `FIREBASE_APP_ID` and the mail settings in production env and redeploy (Cloud Run).

2. **Frontend:** Set the Firebase env vars, build, then:
   ```bash
   firebase deploy --only hosting
   ```

---

## 6. Flow summary

- User opens the app → if not signed in, they are sent to **/login**.
- On **/login**, they enter their email and click “Send login link”.
- Frontend calls **`POST /api/auth/login-link`**; the backend checks the whitelist, generates the link, and sends the email (relay → SMTP → Firebase fallback).
- User clicks the link in the email → they land on your app → Firebase completes sign-in (`signInWithEmailLink`).
- After sign-in, the frontend sends the Firebase ID token in `Authorization: Bearer <token>` on every API request.
- Backend (when `FIREBASE_APP_ID` is set) verifies the token with `google.oauth2.id_token.verify_firebase_token` and rejects unauthenticated requests with 401.
