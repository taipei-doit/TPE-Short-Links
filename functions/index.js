const functions = require('firebase-functions');
const admin = require('firebase-admin');
const nodemailer = require('nodemailer');

// v2 (2nd Gen) does not support functions.config(); use env vars only.
// Load .env from this directory (works for emulator and for deploy if .env is included in the bundle).
require('dotenv').config();

admin.initializeApp();

const ADMIN_EMAILS_COLLECTION = 'admin_emails';

function normalizeEmail(email) {
  return typeof email === 'string' ? email.trim().toLowerCase() : '';
}

/** Trim a free-text profile field (name / job title) and cap its length. */
function normalizeProfileField(value) {
  return typeof value === 'string' ? value.trim().slice(0, 100) : '';
}

/**
 * Admin whitelist: from Firestore collection admin_emails (doc id = email).
 * If Firestore has no docs, fall back to env ADMIN_WHITELIST.
 */
async function getAdminWhitelist() {
  const db = admin.firestore();
  const snapshot = await db.collection(ADMIN_EMAILS_COLLECTION).get();
  if (!snapshot.empty) {
    return snapshot.docs.map((d) => d.id);
  }
  const raw = process.env.ADMIN_WHITELIST || '';
  return raw
    .split(',')
    .map((e) => e.trim().toLowerCase())
    .filter(Boolean);
}

/**
 * When sending a link, ensure the whitelist is reflected in Firestore.
 * If Firestore is empty, migrate the full current whitelist (from env) into Firestore.
 * Otherwise ensure this email is in Firestore.
 */
async function migrateAdminToFirestore(whitelist, emailJustAllowed) {
  const db = admin.firestore();
  const snapshot = await db.collection(ADMIN_EMAILS_COLLECTION).get();
  if (snapshot.empty) {
    for (const e of whitelist) {
      if (!e) continue;
      await db.collection(ADMIN_EMAILS_COLLECTION).doc(e).set(
        { email: e, createdAt: admin.firestore.FieldValue.serverTimestamp() },
        { merge: true }
      );
    }
    return;
  }
  const normalized = normalizeEmail(emailJustAllowed);
  if (!normalized) return;
  const ref = db.collection(ADMIN_EMAILS_COLLECTION).doc(normalized);
  await ref.set(
    { email: normalized, updatedAt: admin.firestore.FieldValue.serverTimestamp() },
    { merge: true }
  );
}

/**
 * App URL where users land after clicking the magic link (must match Firebase Auth authorized domains).
 * In v2 set env var APP_URL.
 */
function getAppUrl() {
  return process.env.APP_URL || 'https://url.taipei';
}

/**
 * Create nodemailer transport. In v2 set env vars: SMTP_USER, SMTP_PASS, optional SMTP_HOST, SMTP_PORT, SMTP_FROM.
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
 * 1. Checks email against admin whitelist.
 * 2. Generates sign-in link with Firebase Auth.
 * 3. Sends email with the link.
 */
exports.sendAdminLoginLink = functions.https.onCall(async (data, context) => {
  // Callable can receive payload as data.email (1st gen) or data.data.email (2nd gen / wrapped)
  const rawEmail = data?.email ?? data?.data?.email;
  const email = typeof rawEmail === 'string' ? rawEmail.trim().toLowerCase() : '';
  if (!email) {
    throw new functions.https.HttpsError('invalid-argument', 'Email is required');
  }

  const whitelist = await getAdminWhitelist();
  if (whitelist.length === 0) {
    throw new functions.https.HttpsError('failed-precondition', 'Admin whitelist not configured');
  }
  if (!whitelist.includes(email)) {
    throw new functions.https.HttpsError('permission-denied', 'Unauthorized');
  }

  await migrateAdminToFirestore(whitelist, email);

  const appUrl = getAppUrl();
  const actionCodeSettings = {
    url: appUrl,
    handleCodeInApp: true,
  };
  const link = await admin.auth().generateSignInWithEmailLink(email, actionCodeSettings);

  const from = process.env.SMTP_FROM || process.env.SMTP_USER;
  const transport = getMailTransport();
  await transport.sendMail({
    from: from,
    to: email,
    subject: 'TPE Short Links – Admin login link',
    html: `
      <p>You requested an admin login link for TPE Short Links.</p>
      <p><a href="${link}">Click here to sign in</a></p>
      <p>This link is one-time use. If you did not request this, you can ignore this email.</p>
    `,
  });

  return { success: true };
});

async function getCallerEmail(context, data) {
  // Lightweight debug to understand why callers appear unauthenticated in production.
  const headers = context?.rawRequest?.headers || {};
  console.log('requireAdmin:getCallerEmail:received', {
    hasAuth: !!context?.auth,
    uid: context?.auth?.uid || null,
    tokenEmailPresent: !!context?.auth?.token?.email,
    hasRawAuthHeader: typeof headers.authorization === 'string',
    headerNames: Object.keys(headers),
  });

  // Normalize callable payload shape (2nd gen may wrap the payload under data.data.*).
  const directPayload = data && typeof data === 'object' ? data : {};
  const nestedPayload =
    directPayload && typeof directPayload.data === 'object' ? directPayload.data : null;

  // 0) First, if the client explicitly sent an ID token, verify it and use its email.
  const tokenFromData =
    (nestedPayload && typeof nestedPayload.idToken === 'string' && nestedPayload.idToken) ||
    (nestedPayload && typeof nestedPayload.token === 'string' && nestedPayload.token) ||
    (typeof directPayload.idToken === 'string' && directPayload.idToken) ||
    (typeof directPayload.token === 'string' && directPayload.token) ||
    '';
  if (tokenFromData) {
    try {
      const decodedFromData = await admin.auth().verifyIdToken(tokenFromData);
      const emailFromData = normalizeEmail(decodedFromData?.email || '');
      if (emailFromData) {
        console.log('requireAdmin:getCallerEmail:usingDataTokenEmail', { email: emailFromData });
        return emailFromData;
      }
    } catch (e) {
      console.log('requireAdmin:getCallerEmail:dataTokenVerifyFailed', {
        name: e?.name || null,
        code: e?.code || null,
      });
    }
  }

  // 1) Try email from callable auth context (most common path)
  const fromContext = normalizeEmail(context?.auth?.token?.email || '');
  if (fromContext) {
    console.log('requireAdmin:getCallerEmail:usingContextEmail', { email: fromContext });
    return fromContext;
  }

  // 2) Some tokens may omit the email claim but still have a UID.
  //    In that case, look up the user record by UID and use its email.
  const uid = context?.auth?.uid;
  if (uid) {
    try {
      const userRecord = await admin.auth().getUser(uid);
      const fromUserRecord = normalizeEmail(
        userRecord.email ||
          (Array.isArray(userRecord.providerData)
            ? userRecord.providerData.find((p) => p && p.email)?.email || ''
            : '')
      );
      if (fromUserRecord) {
        console.log('requireAdmin:getCallerEmail:usingUserRecordEmail', { email: fromUserRecord });
        return fromUserRecord;
      }
    } catch (e) {
      // If this lookup fails, fall through to the header-based fallback below.
    }
  }

  // 3) Fallback: some deployments may not populate context.auth even though the client is signed in.
  //    Verify the bearer token manually from headers.
  const rawAuth = context?.rawRequest?.headers?.authorization;
  if (typeof rawAuth !== 'string' || !rawAuth.startsWith('Bearer ')) return '';
  const token = rawAuth.slice('Bearer '.length).trim();
  if (!token) return '';
  try {
    const decoded = await admin.auth().verifyIdToken(token);
    const emailFromToken = normalizeEmail(decoded?.email || '');
    if (emailFromToken) {
      console.log('requireAdmin:getCallerEmail:usingHeaderTokenEmail', { email: emailFromToken });
    } else {
      console.log('requireAdmin:getCallerEmail:headerTokenNoEmailClaim', {
        hasUid: !!decoded?.uid,
        providerId: decoded?.firebase?.sign_in_provider || null,
      });
    }
    return emailFromToken;
  } catch {
    return '';
  }
}

/** Require caller to be an existing admin (based on the same whitelist used for magic links). Returns caller's normalized email. */
async function requireAdmin(context, data) {
  const email = await getCallerEmail(context, data);
  if (!email) {
    throw new functions.https.HttpsError('unauthenticated', 'Must be signed in');
  }
  const whitelist = await getAdminWhitelist();
  if (!whitelist.includes(email)) {
    throw new functions.https.HttpsError('permission-denied', 'Not an admin');
  }
  return email;
}

/** List all admins (email, name, title). Caller must be an admin. */
exports.listAdmins = functions.https.onCall(async (data, context) => {
  await requireAdmin(context, data);
  const db = admin.firestore();
  const snapshot = await db.collection(ADMIN_EMAILS_COLLECTION).get();
  const admins = snapshot.docs
    .map((d) => {
      const v = d.data() || {};
      return {
        email: d.id,
        name: normalizeProfileField(v.name),
        title: normalizeProfileField(v.title),
      };
    })
    .sort((a, b) => a.email.localeCompare(b.email));
  // `emails` is kept so a client running the previous build keeps working
  // while the new frontend rolls out.
  return { admins, emails: admins.map((a) => a.email) };
});

/**
 * Add or update an admin (email + name + job title). Caller must be an admin.
 * Acts as an upsert: calling it with an existing email updates that admin's
 * name/title, which is also how pre-existing admins get their profile filled in.
 */
exports.addAdmin = functions.https.onCall(async (data, context) => {
  await requireAdmin(context, data);
  const payload = (data && typeof data.data === 'object' && data.data) || data || {};
  const email = normalizeEmail(payload.email);
  if (!email) {
    throw new functions.https.HttpsError('invalid-argument', 'Email is required');
  }
  const name = normalizeProfileField(payload.name);
  const title = normalizeProfileField(payload.title);

  const db = admin.firestore();
  const ref = db.collection(ADMIN_EMAILS_COLLECTION).doc(email);
  const existing = await ref.get();

  const update = { email, name, title, updatedAt: admin.firestore.FieldValue.serverTimestamp() };
  if (!existing.exists) {
    update.createdAt = admin.firestore.FieldValue.serverTimestamp();
  }
  await ref.set(update, { merge: true });
  return { email, name, title };
});

/** Remove an admin email. Caller must be an admin. Cannot remove self; cannot remove last admin. */
exports.removeAdmin = functions.https.onCall(async (data, context) => {
  const callerEmail = await requireAdmin(context, data);
  const rawEmail = data?.email ?? data?.data?.email;
  const email = normalizeEmail(rawEmail);
  if (!email) {
    throw new functions.https.HttpsError('invalid-argument', 'Email is required');
  }
  if (email === callerEmail) {
    throw new functions.https.HttpsError('invalid-argument', 'Cannot remove yourself');
  }
  const db = admin.firestore();
  const snapshot = await db.collection(ADMIN_EMAILS_COLLECTION).get();
  if (snapshot.size <= 1) {
    throw new functions.https.HttpsError('failed-precondition', 'Cannot remove the last admin');
  }
  const ref = db.collection(ADMIN_EMAILS_COLLECTION).doc(email);
  const doc = await ref.get();
  if (!doc.exists) {
    throw new functions.https.HttpsError('not-found', 'Admin not found');
  }
  await ref.delete();
  return { email };
});
