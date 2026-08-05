"""Firebase ID token verification for admin-only API access.

This API expects a Firebase **ID token** (from the frontend) in:
  Authorization: Bearer <token>

Important:
- The Firebase ID token `aud` claim is the Firebase **Project ID**, not the Web App ID.
- We therefore verify with `FIREBASE_PROJECT_ID`.
"""
from __future__ import annotations

import os
import time
from typing import Any

from fastapi import HTTPException, Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.settings import get_settings

# Admin whitelist lives in Firestore collection `admin_emails` (doc id = email),
# the same source the Firebase Functions use for magic-link sending. Verifying a
# Firebase ID token alone is NOT enough: with the public web apiKey anyone may be
# able to self-provision an account in this project, so every /api/* request must
# also prove the signed-in email is a whitelisted admin.
ADMIN_EMAILS_COLLECTION = "admin_emails"
_ADMIN_CACHE_TTL_SECONDS = 60.0

_admin_cache: dict[str, tuple[bool, float]] = {}
_firestore_client: Any = None


def _env_whitelist() -> set[str]:
    raw = os.environ.get("ADMIN_WHITELIST", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_admin_email(email: str) -> bool:
    """Return True if the email is a whitelisted admin (Firestore, env fallback)."""
    now = time.monotonic()
    cached = _admin_cache.get(email)
    if cached is not None and now - cached[1] < _ADMIN_CACHE_TTL_SECONDS:
        return cached[0]

    global _firestore_client
    if _firestore_client is None:
        from google.cloud import firestore  # Lazy import: not needed in local dev/tests

        _firestore_client = firestore.Client()

    ok = _firestore_client.collection(ADMIN_EMAILS_COLLECTION).document(email).get().exists
    if not ok:
        ok = email in _env_whitelist()

    _admin_cache[email] = (ok, now)
    return ok


def get_firebase_user(
    request: Request,
) -> dict[str, Any]:
    """
    Verify Authorization Bearer token as Firebase ID token and return decoded claims.
    If FIREBASE_PROJECT_ID is not set (e.g. local dev), skip verification and return a dummy dict.
    """
    settings = get_settings()
    if not settings.FIREBASE_PROJECT_ID:
        # If someone set the old/incorrect setting, fail fast instead of silently
        # bypassing auth in a misconfigured production environment.
        if settings.FIREBASE_APP_ID:
            raise HTTPException(
                status_code=500,
                detail="Server misconfigured: set FIREBASE_PROJECT_ID (Firebase Project ID) for auth enforcement",
            )
        return {"sub": "dev", "email": "dev@local"}

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = auth_header[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    try:
        req = google_requests.Request()
        claims = id_token.verify_firebase_token(
            token,
            req,
            audience=settings.FIREBASE_PROJECT_ID,
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail="Invalid token") from e

    email = str(claims.get("email") or "").strip().lower()
    if not email or not claims.get("email_verified", False):
        raise HTTPException(status_code=401, detail="Verified email required")

    try:
        allowed = is_admin_email(email)
    except Exception as e:
        # Fail closed: if the whitelist cannot be read, do not grant access.
        raise HTTPException(status_code=503, detail="Admin verification unavailable") from e
    if not allowed:
        raise HTTPException(status_code=403, detail="Not an admin")

    return claims
