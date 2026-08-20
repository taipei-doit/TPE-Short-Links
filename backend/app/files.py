"""PIN-protected file sharing.

Admins upload a file and get back a share link plus an 8-character PIN. Anyone
holding the link still has to enter the PIN before the bytes are released:

    GET  /f/{code}            public landing page with the PIN form
    POST /f/{code}/verify     checks the PIN, returns a short-lived download URL
    GET  /f/{code}/download   streams the file, given a valid download token

    /api/files/*              admin-only: upload, list, edit, disable, delete

The bucket is private and no signed URLs are ever handed out, so the PIN gate
is the only route to the content. Wrong PINs are counted per file and lock the
link for a while, which is what actually stops guessing -- the hash cost only
slows a single attempt down.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import html
import json
import logging
import mimetypes
import os
import re
import secrets
import time
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_firebase_user
from app.db.session import get_db
from app.i18n import HTML_LANG, LANGUAGE_NAMES, STRINGS, pick_language
from app.models import SharedFile
from app.pages import PAGE_STYLE, redirect_to_not_found
from app.pins import PIN_LENGTH, generate_pin, hash_pin, validate_pin, verify_pin
from app.schemas import (
    DisableOut,
    EnableOut,
    FileVerifyIn,
    FileVerifyOut,
    PinOut,
    SharedFileCreatedOut,
    SharedFileListOut,
    SharedFileOut,
    SharedFileUpdateIn,
)
from app.settings import get_settings
from app.storage import CHUNK_SIZE, get_storage
from app.utils import generate_code, now_utc

router = APIRouter()

TAIPEI_TZ = dt.timezone(dt.timedelta(hours=8))

# Filesystem-hostile and control characters are stripped from uploaded names.
_UNSAFE_FILENAME_CHARS = re.compile(r'[\x00-\x1f\x7f"\\/:*?<>|]')

_ephemeral_secret: bytes | None = None


# --------------------------------------------------------------------------
# Download tokens
# --------------------------------------------------------------------------


def _download_secret() -> bytes:
    """Key for signing download tokens.

    Derived from INTERNAL_API_TOKEN when no dedicated secret is configured, so
    an existing deployment needs no extra setting. The random fallback only
    applies to local development, where a single process serves every request.
    """
    global _ephemeral_secret
    settings = get_settings()
    if settings.FILE_DOWNLOAD_SECRET:
        return settings.FILE_DOWNLOAD_SECRET.encode("utf-8")
    if settings.INTERNAL_API_TOKEN:
        return hmac.new(
            settings.INTERNAL_API_TOKEN.encode("utf-8"),
            b"file-download-token",
            hashlib.sha256,
        ).digest()
    if _ephemeral_secret is None:
        logging.warning(
            "No FILE_DOWNLOAD_SECRET or INTERNAL_API_TOKEN set; using a per-process "
            "download token secret. Tokens will not validate across instances."
        )
        _ephemeral_secret = secrets.token_bytes(32)
    return _ephemeral_secret


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def make_download_token(code: str, ttl_seconds: int) -> str:
    expires_at = int(time.time()) + ttl_seconds
    message = f"{code}:{expires_at}".encode()
    signature = hmac.new(_download_secret(), message, hashlib.sha256).digest()
    return f"{expires_at}.{_b64u(signature)}"


def check_download_token(code: str, token: str) -> bool:
    try:
        raw_expiry, signature = token.split(".", 1)
        expires_at = int(raw_expiry)
    except (ValueError, AttributeError):
        return False
    if expires_at < int(time.time()):
        return False
    message = f"{code}:{expires_at}".encode()
    expected = _b64u(hmac.new(_download_secret(), message, hashlib.sha256).digest())
    return hmac.compare_digest(expected, signature)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def as_utc(value: dt.datetime | None) -> dt.datetime | None:
    """Normalize to timezone-aware UTC (SQLite hands back naive datetimes)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def share_url(code: str) -> str:
    settings = get_settings()
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/f/{code}"


def sanitize_filename(raw: str | None) -> str:
    name = os.path.basename((raw or "").strip().replace("\\", "/"))
    name = _UNSAFE_FILENAME_CHARS.sub("", name).strip(". ")
    if not name:
        name = "download"
    return name[:255]


def sanitize_content_type(raw: str | None, filename: str) -> str:
    value = (raw or "").split(";")[0].strip().lower()
    if not re.fullmatch(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+", value or ""):
        value = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return value[:128]


def content_disposition(filename: str) -> str:
    """Build a Content-Disposition header that survives non-ASCII filenames.

    The plain `filename=` is an ASCII fallback for old clients; `filename*`
    carries the real (usually Chinese) name per RFC 5987.
    """
    ascii_fallback = filename.encode("ascii", "replace").decode("ascii").replace('"', "")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def file_to_out(record: SharedFile) -> SharedFileOut:
    expires_at = as_utc(record.expires_at)
    locked_until = as_utc(record.locked_until)
    now = now_utc()
    return SharedFileOut(
        id=record.id,
        code=record.code,
        filename=record.filename,
        content_type=record.content_type,
        size_bytes=record.size_bytes,
        note=record.note,
        status=record.status,
        expires_at=expires_at,
        created_at=record.created_at,
        is_expired=expires_at is not None and expires_at <= now,
        download_count=record.download_count,
        is_locked=locked_until is not None and locked_until > now,
        uploaded_by=record.uploaded_by,
        share_url=share_url(record.code),
    )


def generate_file_code(db: Session) -> str:
    settings = get_settings()
    for _ in range(100):
        code = generate_code(settings.FILE_CODE_LENGTH)
        exists = db.execute(select(SharedFile.code).where(SharedFile.code == code)).first()
        if exists is None:
            return code
    raise HTTPException(status_code=500, detail="Failed to generate a unique code")


def get_downloadable(code: str, db: Session) -> SharedFile | None:
    """Return the file only if the public may currently reach it."""
    record = db.execute(select(SharedFile).where(SharedFile.code == code)).scalar_one_or_none()
    if record is None or record.status != "active":
        return None
    expires_at = as_utc(record.expires_at)
    if expires_at is not None and expires_at <= now_utc():
        return None
    return record


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


# --------------------------------------------------------------------------
# Admin API
# --------------------------------------------------------------------------


@router.post("/api/files", response_model=SharedFileCreatedOut)
def create_shared_file(
    file: UploadFile = File(...),
    note: str | None = Form(default=None),
    expires_at: str | None = Form(default=None),
    pin: str | None = Form(default=None),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> SharedFileCreatedOut:
    """Upload a file and mint its share link and PIN.

    Defined as a sync endpoint so FastAPI runs it in a worker thread: the
    storage upload and the database session are both blocking.
    """
    settings = get_settings()
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024

    filename = sanitize_filename(file.filename)
    content_type = sanitize_content_type(file.content_type, filename)

    parsed_expiry = parse_expiry(expires_at)

    if pin:
        try:
            plain_pin = validate_pin(pin)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    else:
        plain_pin = generate_pin()

    # Measure before storing so an oversized upload is rejected without ever
    # reaching the bucket.
    size_bytes = 0
    while chunk := file.file.read(CHUNK_SIZE):
        size_bytes += len(chunk)
        if size_bytes > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"檔案超過上限 {settings.MAX_UPLOAD_MB} MB",
            )
    if size_bytes == 0:
        raise HTTPException(status_code=422, detail="檔案是空的")
    file.file.seek(0)

    code = generate_file_code(db)
    # Randomised object key: the storage path cannot be derived from the share
    # link, and the original filename never has to be encoded into it.
    storage_path = f"{settings.FILE_STORAGE_PREFIX.strip('/')}/{code}/{secrets.token_hex(16)}"

    record = SharedFile(
        code=code,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        storage_path=storage_path,
        pin_hash=hash_pin(plain_pin),
        note=(note or None),
        status="active",
        expires_at=parsed_expiry,
        download_count=0,
        failed_attempts=0,
        uploaded_by=str(_auth.get("email") or "")[:320],
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail="Code already exists") from e

    try:
        get_storage().save(storage_path, file.file, content_type)
    except Exception as e:
        # Don't leave a row pointing at bytes that were never written.
        db.delete(record)
        db.commit()
        logging.exception("Failed to store shared file")
        raise HTTPException(status_code=502, detail="檔案儲存失敗，請稍後再試") from e

    db.refresh(record)
    return SharedFileCreatedOut(**file_to_out(record).model_dump(), pin=plain_pin)


def parse_expiry(raw: str | None) -> dt.datetime | None:
    """Parse an ISO-8601 expiry from a multipart form field."""
    if raw is None or not raw.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError as e:
        raise HTTPException(status_code=422, detail="expires_at must be ISO-8601") from e
    if parsed.tzinfo is None:
        raise HTTPException(status_code=422, detail="expires_at must be timezone-aware")
    if parsed <= now_utc():
        raise HTTPException(status_code=422, detail="expires_at must be in the future")
    return parsed


@router.get("/api/files", response_model=SharedFileListOut)
def list_shared_files(
    query: str | None = Query(default=None),
    status: Literal["active", "disabled", "expired", "deleted", "all"] | None = Query(default="all"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> SharedFileListOut:
    now = now_utc()
    base = select(SharedFile)
    where = []

    if query:
        q = f"%{query.lower()}%"
        where.append(
            or_(
                func.lower(SharedFile.code).like(q),
                func.lower(SharedFile.filename).like(q),
                func.lower(func.coalesce(SharedFile.note, "")).like(q),
            )
        )

    if status and status != "all":
        if status == "expired":
            where.append(and_(SharedFile.expires_at.is_not(None), SharedFile.expires_at <= now))
        else:
            where.append(SharedFile.status == status)
            if status == "active":
                where.append(or_(SharedFile.expires_at.is_(None), SharedFile.expires_at > now))

    if where:
        base = base.where(and_(*where))

    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = (
        db.execute(base.order_by(SharedFile.created_at.desc()).limit(limit).offset(offset))
        .scalars()
        .all()
    )
    return SharedFileListOut(
        items=[file_to_out(r) for r in rows], total=total, limit=limit, offset=offset
    )


def load_for_admin(code: str, db: Session) -> SharedFile:
    record = db.execute(select(SharedFile).where(SharedFile.code == code)).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Not found")
    return record


@router.patch("/api/files/{code}", response_model=SharedFileOut)
def update_shared_file(
    code: str = Path(..., min_length=1, max_length=32),
    payload: SharedFileUpdateIn = ...,
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> SharedFileOut:
    """Update expiry and/or note. Only fields present in the request are applied."""
    record = load_for_admin(code, db)
    if record.status == "deleted":
        raise HTTPException(status_code=422, detail="檔案已刪除，無法修改")

    fields = payload.model_fields_set
    if "expires_at" in fields:
        if payload.expires_at is not None and payload.expires_at.tzinfo is None:
            raise HTTPException(status_code=422, detail="expires_at must be timezone-aware")
        record.expires_at = payload.expires_at
    if "note" in fields:
        record.note = payload.note or None

    record.updated_at = now_utc()
    db.add(record)
    db.commit()
    db.refresh(record)
    return file_to_out(record)


@router.post("/api/files/{code}/regenerate-pin", response_model=PinOut)
def regenerate_shared_file_pin(
    code: str = Path(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> PinOut:
    """Issue a new PIN. The old one stops working immediately.

    This is the recovery path for a forgotten PIN -- stored hashes cannot be
    read back. It also clears any brute-force lockout.
    """
    record = load_for_admin(code, db)
    if record.status == "deleted":
        raise HTTPException(status_code=422, detail="檔案已刪除，無法變更 PIN")

    plain_pin = generate_pin()
    record.pin_hash = hash_pin(plain_pin)
    record.failed_attempts = 0
    record.locked_until = None
    record.updated_at = now_utc()
    db.add(record)
    db.commit()
    return PinOut(code=code, pin=plain_pin)


@router.post("/api/files/{code}/disable", response_model=DisableOut)
def disable_shared_file(
    code: str = Path(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> DisableOut:
    record = load_for_admin(code, db)
    if record.status == "deleted":
        raise HTTPException(status_code=422, detail="檔案已刪除")
    record.status = "disabled"
    record.updated_at = now_utc()
    db.add(record)
    db.commit()
    return DisableOut(code=code, status=record.status)


@router.post("/api/files/{code}/enable", response_model=EnableOut)
def enable_shared_file(
    code: str = Path(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> EnableOut:
    record = load_for_admin(code, db)
    if record.status == "deleted":
        raise HTTPException(status_code=422, detail="檔案已刪除，無法重新啟用")
    if record.status != "disabled":
        raise HTTPException(status_code=422, detail="File is not disabled")
    record.status = "active"
    record.updated_at = now_utc()
    db.add(record)
    db.commit()
    return EnableOut(code=code, status=record.status)


@router.delete("/api/files/{code}")
def delete_shared_file(
    code: str = Path(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> dict[str, str]:
    """Erase the stored bytes and mark the row deleted.

    Unlike short links, the content really is removed -- shared files can hold
    sensitive material and must not linger in the bucket. The row stays for the
    audit trail, and the code is never reused.
    """
    record = load_for_admin(code, db)
    if record.status != "deleted":
        try:
            get_storage().delete(record.storage_path)
        except Exception as e:
            logging.exception("Failed to delete shared file object")
            raise HTTPException(status_code=502, detail="檔案刪除失敗，請稍後再試") from e
        record.status = "deleted"
        record.updated_at = now_utc()
        db.add(record)
        db.commit()
    return {"message": "File deleted", "code": code}


# --------------------------------------------------------------------------
# Public: landing page, PIN check, download
# --------------------------------------------------------------------------


_TOKEN = re.compile(r"__([A-Z0-9_]+)__")


def _fill(template: str, values: dict[str, str]) -> str:
    """Substitute __TOKEN__ placeholders in one pass.

    A single pass matters: a value that happens to contain something looking
    like a token (a filename, say) must not itself be substituted.
    """
    return _TOKEN.sub(lambda match: values[match.group(1)], template)


# Not an f-string: the block contains CSS and JavaScript braces. Values are
# injected through _fill above.
LANDING_TEMPLATE = """<!doctype html>
<html lang="__HTML_LANG__">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="robots" content="noindex, nofollow" />
    <title>__TITLE__</title>
    <style>__PAGE_STYLE__
      .card { position: relative; }
      .langbar { display:flex; gap:6px; justify-content:flex-end; flex-wrap:wrap; margin-bottom:14px; }
      .langbar button { background:transparent; border:1px solid #cbd5e1; color:#475569; border-radius:999px;
                        padding:5px 12px; font-size:13px; cursor:pointer; font-family:inherit; }
      .langbar button:hover { border-color:#94a3b8; color:#0f172a; }
      .langbar button.active { background:#2563eb; border-color:#2563eb; color:#fff; font-weight:600; }
      .meta { margin: 18px 0 22px; padding: 16px; background:#f1f5f9; border-radius:12px; }
      .meta div { font-size: 15px; color:#334155; margin-bottom: 6px; }
      .meta div:last-child { margin-bottom: 0; }
      .meta b { color:#0f172a; font-weight:600; }
      .meta .sep { margin-right: 4px; }
      label { display:block; font-size:15px; font-weight:600; margin-bottom:8px; }
      input { width:100%; padding:12px 14px; font-size:20px; letter-spacing:4px; text-align:center;
              font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
              border:1px solid #cbd5e1; border-radius:10px; text-transform:uppercase; }
      input:focus { outline:none; border-color:#2563eb; box-shadow:0 0 0 3px rgba(37,99,235,0.15); }
      button[type="submit"] { width:100%; margin-top:14px; padding:12px 16px; font-size:16px; font-weight:600;
                              color:#fff; background:#2563eb; border:0; border-radius:10px; cursor:pointer;
                              font-family:inherit; }
      button[type="submit"]:hover { background:#1d4ed8; }
      button[type="submit"]:disabled { background:#94a3b8; cursor:not-allowed; }
      .msg { margin-top:14px; font-size:15px; min-height:22px; }
      .msg.error { color:#b91c1c; }
      .msg.ok { color:#15803d; }
      .hint { margin-top:16px; font-size:13px; color:#64748b; }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="card">
        <nav class="langbar" id="langbar" aria-label="__LANGUAGE_LABEL__">__LANGUAGE_BUTTONS__</nav>
        <h1 data-i18n="heading">__HEADING__</h1>
        <p data-i18n="intro">__INTRO__</p>
        <div class="meta">
          <div><b data-i18n="label_filename">__LABEL_FILENAME__</b><span class="sep" data-i18n="colon">__COLON__</span>__FILENAME__</div>
          <div><b data-i18n="label_size">__LABEL_SIZE__</b><span class="sep" data-i18n="colon">__COLON__</span>__SIZE__</div>
          <div><b data-i18n="label_expiry">__LABEL_EXPIRY__</b><span class="sep" data-i18n="colon">__COLON__</span><span id="expiry">__EXPIRY_INITIAL__</span></div>
        </div>
        <form id="pin-form" autocomplete="off">
          <label for="pin" data-i18n="pin_label">__PIN_LABEL__</label>
          <input id="pin" name="pin" type="text" inputmode="latin" maxlength="__PIN_LENGTH__"
                 placeholder="__PIN_PLACEHOLDER__" autocomplete="off" spellcheck="false" required />
          <button type="submit" id="submit" data-i18n="submit">__SUBMIT__</button>
        </form>
        <div class="msg" id="msg" role="status" aria-live="polite"></div>
        <p class="hint" data-i18n="hint">__HINT__</p>
      </div>
    </div>
    <script>
      (function () {
        var code = __CODE_JSON__;
        var strings = __STRINGS_JSON__;
        var htmlLangs = __HTML_LANGS_JSON__;
        var expiryStamp = __EXPIRY_JSON__;
        var lang = __LANGUAGE_JSON__;
        var explicitLang = __EXPLICIT_LANGUAGE_JSON__;
        var storageKey = 'tpe-share-lang';

        var form = document.getElementById('pin-form');
        var input = document.getElementById('pin');
        var button = document.getElementById('submit');
        var msg = document.getElementById('msg');
        var expiryEl = document.getElementById('expiry');
        var langbar = document.getElementById('langbar');
        var lastError = null;

        function t(key) {
          var table = strings[lang] || strings['zh-Hant'];
          return table[key] || key;
        }

        function renderError() {
          if (!lastError) { return; }
          var text = t(lastError.key);
          if (lastError.remaining !== undefined) { text = text.replace('{n}', lastError.remaining); }
          if (lastError.minutes !== undefined) { text = text.replace('{m}', lastError.minutes); }
          msg.className = 'msg error';
          msg.textContent = text;
        }

        function showError(error) {
          lastError = error;
          renderError();
        }

        function applyLanguage(next, remember) {
          if (!strings[next]) { return; }
          lang = next;
          document.documentElement.lang = htmlLangs[lang];
          document.title = t('title');
          var nodes = document.querySelectorAll('[data-i18n]');
          for (var i = 0; i < nodes.length; i++) {
            nodes[i].textContent = t(nodes[i].getAttribute('data-i18n'));
          }
          expiryEl.textContent = expiryStamp ? expiryStamp + ' ' + t('time_zone_note') : t('no_expiry');
          var buttons = langbar.querySelectorAll('button');
          for (var j = 0; j < buttons.length; j++) {
            var isActive = buttons[j].getAttribute('data-lang') === lang;
            buttons[j].className = isActive ? 'active' : '';
            buttons[j].setAttribute('aria-pressed', isActive ? 'true' : 'false');
          }
          renderError();
          if (remember) {
            try { localStorage.setItem(storageKey, lang); } catch (e) { /* private mode */ }
          }
        }

        langbar.addEventListener('click', function (event) {
          var target = event.target.closest('button[data-lang]');
          if (target) { applyLanguage(target.getAttribute('data-lang'), true); }
        });

        // An explicit ?lang= wins; otherwise a previous choice beats the
        // browser's Accept-Language header.
        if (explicitLang) {
          try { localStorage.setItem(storageKey, lang); } catch (e) { /* private mode */ }
        } else {
          var stored = null;
          try { stored = localStorage.getItem(storageKey); } catch (e) { /* private mode */ }
          if (stored && stored !== lang) { applyLanguage(stored, false); }
        }

        input.addEventListener('input', function () {
          input.value = input.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
        });

        form.addEventListener('submit', function (event) {
          event.preventDefault();
          lastError = null;
          msg.className = 'msg';
          msg.textContent = '';
          button.disabled = true;
          button.textContent = t('verifying');

          fetch('/f/' + encodeURIComponent(code) + '/verify', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ pin: input.value })
          })
            .then(function (res) {
              return res.json()
                .catch(function () { return {}; })
                .then(function (data) { return { ok: res.ok, data: data }; });
            })
            .then(function (result) {
              if (!result.ok) {
                var detail = result.data && result.data.detail;
                if (detail && typeof detail === 'object' && detail.error) {
                  throw { key: 'err_' + detail.error, remaining: detail.remaining, minutes: detail.minutes };
                }
                throw { key: 'err_generic' };
              }
              msg.className = 'msg ok';
              msg.textContent = t('verified');
              button.textContent = t('downloading');
              window.location.href = result.data.download_url;
              setTimeout(function () {
                button.disabled = false;
                button.textContent = t('download_again');
              }, 3000);
            })
            .catch(function (error) {
              showError(error && error.key ? error : { key: 'err_network' });
              button.disabled = false;
              button.textContent = t('submit');
              input.select();
            });
        });
      })();
    </script>
  </body>
</html>"""


def render_landing_page(record: SharedFile, language: str, explicit_language: bool) -> str:
    """Render the public download page in the visitor's language.

    All four translations are embedded, so switching language is instant and
    needs no round trip. Everything interpolated is HTML-escaped or JSON-encoded
    -- the filename is user-supplied and must never reach the markup raw.
    """
    strings = STRINGS[language]
    expires_at = as_utc(record.expires_at)
    expiry_stamp = (
        expires_at.astimezone(TAIPEI_TZ).strftime("%Y/%m/%d %H:%M") if expires_at is not None else None
    )
    expiry_initial = (
        f"{expiry_stamp} {strings['time_zone_note']}" if expiry_stamp else strings["no_expiry"]
    )

    language_buttons = "".join(
        '<button type="button" class="lang{active}" data-lang="{code}" aria-pressed="{pressed}">{name}</button>'.format(
            active=" active" if code == language else "",
            code=html.escape(code, quote=True),
            pressed="true" if code == language else "false",
            name=html.escape(name),
        )
        for code, name in LANGUAGE_NAMES.items()
    )

    return _fill(
        LANDING_TEMPLATE,
        {
            "PAGE_STYLE": PAGE_STYLE,
            "HTML_LANG": html.escape(HTML_LANG[language], quote=True),
            "TITLE": html.escape(strings["title"]),
            "HEADING": html.escape(strings["heading"]),
            "INTRO": html.escape(strings["intro"]),
            "LABEL_FILENAME": html.escape(strings["label_filename"]),
            "LABEL_SIZE": html.escape(strings["label_size"]),
            "LABEL_EXPIRY": html.escape(strings["label_expiry"]),
            "COLON": html.escape(strings["colon"]),
            "PIN_LABEL": html.escape(strings["pin_label"]),
            "SUBMIT": html.escape(strings["submit"]),
            "HINT": html.escape(strings["hint"]),
            "LANGUAGE_LABEL": html.escape(strings["language_label"]),
            "LANGUAGE_BUTTONS": language_buttons,
            "FILENAME": html.escape(record.filename),
            "SIZE": html.escape(human_size(record.size_bytes)),
            "EXPIRY_INITIAL": html.escape(expiry_initial),
            "PIN_LENGTH": str(PIN_LENGTH),
            "PIN_PLACEHOLDER": "●" * PIN_LENGTH,
            "CODE_JSON": json.dumps(record.code),
            "STRINGS_JSON": json.dumps(STRINGS, ensure_ascii=False),
            "HTML_LANGS_JSON": json.dumps(HTML_LANG, ensure_ascii=False),
            "EXPIRY_JSON": json.dumps(expiry_stamp),
            "LANGUAGE_JSON": json.dumps(language),
            "EXPLICIT_LANGUAGE_JSON": json.dumps(explicit_language),
        },
    )


@router.get("/f/{code}")
def shared_file_page(
    request: Request,
    code: str = Path(..., min_length=1, max_length=32),
    lang: str | None = Query(default=None, max_length=16),
    db: Session = Depends(get_db),
):
    """Public landing page. Unknown, disabled and expired links all go to /404.html.

    Failing them identically means the page cannot be used to probe which codes
    exist.
    """
    record = get_downloadable(code, db)
    if record is None:
        return redirect_to_not_found()

    language = pick_language(request.headers.get("Accept-Language"), lang)
    return HTMLResponse(
        content=render_landing_page(record, language, explicit_language=lang in STRINGS),
        status_code=200,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            # The page picks a language from Accept-Language, so caches must
            # not serve one visitor's language to another.
            "Vary": "Accept-Language",
        },
    )


@router.post("/f/{code}/verify", response_model=FileVerifyOut)
def verify_shared_file_pin(
    payload: FileVerifyIn,
    code: str = Path(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
) -> FileVerifyOut:
    """Check a PIN and hand back a short-lived download URL.

    Errors carry a machine-readable `error` code alongside the Chinese text, so
    the page can render them in whichever of its four languages the visitor is
    reading.
    """
    settings = get_settings()
    record = get_downloadable(code, db)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": "連結不存在或已失效"},
        )

    now = now_utc()
    locked_until = as_utc(record.locked_until)
    if locked_until is not None and locked_until > now:
        minutes = max(1, int((locked_until - now).total_seconds() // 60) + 1)
        raise HTTPException(
            status_code=429,
            detail={
                "error": "locked",
                "minutes": minutes,
                "message": f"嘗試次數過多，請於 {minutes} 分鐘後再試",
            },
        )

    if not verify_pin(payload.pin, record.pin_hash):
        record.failed_attempts += 1
        locked = record.failed_attempts >= settings.FILE_PIN_MAX_ATTEMPTS
        if locked:
            minutes = settings.FILE_PIN_LOCKOUT_MINUTES
            record.locked_until = now + dt.timedelta(minutes=minutes)
            record.failed_attempts = 0
        remaining = settings.FILE_PIN_MAX_ATTEMPTS - record.failed_attempts
        db.add(record)
        db.commit()

        if locked:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "locked",
                    "minutes": minutes,
                    "message": f"嘗試次數過多，請於 {minutes} 分鐘後再試",
                },
            )
        raise HTTPException(
            status_code=401,
            detail={
                "error": "wrong_pin",
                "remaining": remaining,
                "message": f"PIN 碼錯誤，尚可嘗試 {remaining} 次",
            },
        )

    record.failed_attempts = 0
    record.locked_until = None
    db.add(record)
    db.commit()

    ttl = settings.FILE_DOWNLOAD_TOKEN_TTL_SECONDS
    token = make_download_token(code, ttl)
    return FileVerifyOut(
        filename=record.filename,
        size_bytes=record.size_bytes,
        download_url=f"/f/{quote(code)}/download?token={quote(token)}",
        expires_in=ttl,
    )


@router.get("/f/{code}/download")
def download_shared_file(
    code: str = Path(..., min_length=1, max_length=32),
    token: str = Query(..., min_length=1, max_length=256),
    db: Session = Depends(get_db),
):
    """Stream the file to a holder of a valid download token.

    Streamed through this service rather than via a signed bucket URL, so the
    bucket stays private and a leaked URL expires with the token.
    """
    if not check_download_token(code, token):
        raise HTTPException(status_code=403, detail="下載連結已失效，請重新輸入 PIN 碼")

    record = get_downloadable(code, db)
    if record is None:
        return redirect_to_not_found()

    record.download_count += 1
    db.add(record)
    db.commit()

    storage_path = record.storage_path
    filename = record.filename
    content_type = record.content_type
    size_bytes = record.size_bytes

    return StreamingResponse(
        get_storage().stream(storage_path),
        media_type=content_type,
        headers={
            "Content-Disposition": content_disposition(filename),
            "Content-Length": str(size_bytes),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
