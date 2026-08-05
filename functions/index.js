const functions = require('firebase-functions');
const admin = require('firebase-admin');
const nodemailer = require('nodemailer');

// v2 (2nd Gen) does not support functions.config(); use env vars only.
// Load .env from this directory (works for emulator and for deploy if .env is included in the bundle).
require('dotenv').config();

admin.initializeApp();

/**
 * Ask the backend whether an email is on the admin whitelist.
 *
 * The whitelist lives in the application database (table `admin_users`), which
 * is also what the backend API checks on every /api/* request. This function
 * runs before anyone is signed in, so it cannot present an ID token and
 * authenticates with a shared secret instead; the backend only ever answers
 * true/false, so the whitelist is never exposed.
 *
 * Fails closed: any error means "not allowed".
 */
async function isWhitelisted(email) {
  const baseUrl = process.env.API_BASE_URL;
  const token = process.env.INTERNAL_API_TOKEN;
  if (!baseUrl || !token) {
    throw new functions.https.HttpsError(
      'failed-precondition',
      'Whitelist lookup not configured: set API_BASE_URL and INTERNAL_API_TOKEN'
    );
  }

  const res = await fetch(`${baseUrl.replace(/\/$/, '')}/api/internal/whitelist-check`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Internal-Token': token },
    body: JSON.stringify({ email }),
  });

  if (!res.ok) {
    console.error('whitelist-check failed', { status: res.status });
    throw new functions.https.HttpsError('internal', 'Whitelist lookup failed');
  }
  const data = await res.json();
  return data?.allowed === true;
}

/**
 * App URL where users land after clicking the magic link
 * (must match a Firebase Auth authorized domain). Set env var APP_URL.
 */
function getAppUrl() {
  return process.env.APP_URL || 'https://url.taipei';
}

/**
 * Create nodemailer transport. Env vars: SMTP_USER, SMTP_PASS,
 * optional SMTP_HOST, SMTP_PORT, SMTP_FROM.
 */
function getMailTransport() {
  const user = process.env.SMTP_USER;
  const pass = process.env.SMTP_PASS;
  const host = process.env.SMTP_HOST || 'smtp.gmail.com';
  const port = Number(process.env.SMTP_PORT || '587');
  if (!user || !pass) {
    throw new Error('SMTP not configured: set SMTP_USER and SMTP_PASS env vars');
  }
  return nodemailer.createTransport({
    host,
    port,
    secure: port === 465,
    auth: { user, pass },
  });
}

/**
 * Send admin magic-link email. Callable from the frontend.
 * 1. Checks the email against the admin whitelist (via the backend).
 * 2. Generates a sign-in link with Firebase Auth.
 * 3. Emails the link.
 *
 * Admin CRUD is handled by the backend API (`/api/admins`), not here.
 */
exports.sendAdminLoginLink = functions.https.onCall(async (data, context) => {
  // Callable can receive payload as data.email (1st gen) or data.data.email (2nd gen / wrapped)
  const rawEmail = data?.email ?? data?.data?.email;
  const email = typeof rawEmail === 'string' ? rawEmail.trim().toLowerCase() : '';
  if (!email) {
    throw new functions.https.HttpsError('invalid-argument', 'Email is required');
  }

  if (!(await isWhitelisted(email))) {
    throw new functions.https.HttpsError('permission-denied', 'Unauthorized');
  }

  const link = await admin.auth().generateSignInWithEmailLink(email, {
    url: getAppUrl(),
    handleCodeInApp: true,
  });

  const from = process.env.SMTP_FROM || process.env.SMTP_USER;
  await getMailTransport().sendMail({
    from,
    to: email,
    subject: '臺北市短網址服務 - 管理員登入連結',
    html: `
      <p>您申請了臺北市短網址服務的管理員登入連結。</p>
      <p><a href="${link}">請點此登入</a></p>
      <p>此連結僅能使用一次。若您並未提出此申請，請忽略本郵件。</p>
    `,
  });

  return { success: true };
});
