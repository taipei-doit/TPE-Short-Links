"""PIN-protected file sharing.

An admin creates a share and puts one or more files in it. The share is one
link and one PIN, however many files it holds:

    GET  /f/{code}                     public landing page with the PIN form
    POST /f/{code}/verify              checks the PIN, returns the file list
    GET  /f/{code}/download/{file_id}  streams one file, given a download token

    /api/shares/*                      admin-only

Each file is uploaded in its own request, which is what lets a share hold more
data than Cloud Run will accept in one go. Cloud Run refuses request bodies
over 32 MiB at the edge -- measured, not assumed -- so anything larger cannot
be proxied through this service at all. Those files go straight from the
browser to object storage through a resumable upload session, and only their
metadata comes back here.

Downloads always stream through this service: the bucket is private and no
read URLs are ever handed out, so the PIN gate is the only route to the bytes.
Wrong PINs are counted per share and lock the link for a while, which is what
actually stops guessing -- the hash cost only slows a single attempt down.
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
from sqlalchemy.orm import Session, selectinload

from app.auth import get_firebase_user
from app.db.session import get_db
from app.i18n import HTML_LANG, LANGUAGE_NAMES, STRINGS, pick_language
from app.models import FileShare, SharedFile
from app.pages import PAGE_STYLE, redirect_to_not_found
from app.pins import PIN_LENGTH, generate_pin, hash_pin, validate_pin, verify_pin
from app.schemas import (
    DisableOut,
    EnableOut,
    FileShareCreatedOut,
    FileShareCreateIn,
    FileShareListOut,
    FileShareOut,
    FileShareUpdateIn,
    FileVerifyIn,
    FileVerifyOut,
    PinOut,
    SharedFileOut,
    UploadFinalizeIn,
    UploadSessionIn,
    UploadSessionOut,
    VerifiedFileOut,
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
# Signed tokens
# --------------------------------------------------------------------------


def _root_secret() -> bytes:
    """Key material for every token this module signs.

    Derived from INTERNAL_API_TOKEN when no dedicated secret is configured, so
    an existing deployment needs no extra setting. The random fallback only
    applies to local development, where a single process serves every request.
    """
    global _ephemeral_secret
    settings = get_settings()
    if settings.FILE_DOWNLOAD_SECRET:
        return settings.FILE_DOWNLOAD_SECRET.encode("utf-8")
    if settings.INTERNAL_API_TOKEN:
        return settings.INTERNAL_API_TOKEN.encode("utf-8")
    if _ephemeral_secret is None:
        logging.warning(
            "No FILE_DOWNLOAD_SECRET or INTERNAL_API_TOKEN set; using a per-process "
            "token secret. Tokens will not validate across instances."
        )
        _ephemeral_secret = secrets.token_bytes(32)
    return _ephemeral_secret


def _key(purpose: bytes) -> bytes:
    """Derive a per-purpose key, so a download token can never act as an upload token."""
    return hmac.new(_root_secret(), purpose, hashlib.sha256).digest()


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64u_decode(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def make_download_token(code: str, ttl_seconds: int) -> str:
    expires_at = int(time.time()) + ttl_seconds
    message = f"{code}:{expires_at}".encode()
    signature = hmac.new(_key(b"download"), message, hashlib.sha256).digest()
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
    expected = _b64u(hmac.new(_key(b"download"), message, hashlib.sha256).digest())
    return hmac.compare_digest(expected, signature)


def make_upload_token(payload: dict) -> str:
    """Carry the pending upload's details to the finalize call, unforgeably.

    Signing this instead of storing it means no pending-upload table, and an
    abandoned upload leaves nothing behind but a stray object.
    """
    body = _b64u(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _b64u(hmac.new(_key(b"upload"), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}"


def read_upload_token(token: str) -> dict | None:
    try:
        body, signature = token.split(".", 1)
    except (ValueError, AttributeError):
        return None
    expected = _b64u(hmac.new(_key(b"upload"), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        payload = json.loads(_b64u_decode(body))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("exp", 0) < int(time.time()):
        return None
    return payload


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


def active_files(share: FileShare) -> list[SharedFile]:
    return [f for f in share.files if f.status == "active"]


def file_to_out(record: SharedFile) -> SharedFileOut:
    return SharedFileOut(
        id=record.id,
        filename=record.filename,
        content_type=record.content_type,
        size_bytes=record.size_bytes,
        status=record.status,
        download_count=record.download_count,
        created_at=record.created_at,
    )


def share_to_out(share: FileShare) -> FileShareOut:
    expires_at = as_utc(share.expires_at)
    locked_until = as_utc(share.locked_until)
    now = now_utc()
    files = active_files(share)
    return FileShareOut(
        id=share.id,
        code=share.code,
        note=share.note,
        status=share.status,
        expires_at=expires_at,
        created_at=share.created_at,
        is_expired=expires_at is not None and expires_at <= now,
        is_locked=locked_until is not None and locked_until > now,
        uploaded_by=share.uploaded_by,
        share_url=share_url(share.code),
        files=[file_to_out(f) for f in share.files],
        file_count=len(files),
        total_bytes=sum(f.size_bytes for f in files),
        download_count=sum(f.download_count for f in share.files),
    )


def generate_share_code(db: Session) -> str:
    settings = get_settings()
    for _ in range(100):
        code = generate_code(settings.FILE_CODE_LENGTH)
        exists = db.execute(select(FileShare.code).where(FileShare.code == code)).first()
        if exists is None:
            return code
    raise HTTPException(status_code=500, detail="Failed to generate a unique code")


def storage_path_for(code: str) -> str:
    settings = get_settings()
    # Randomised object key: it cannot be derived from the share link, and the
    # original filename never has to be encoded into it.
    return f"{settings.FILE_STORAGE_PREFIX.strip('/')}/{code}/{secrets.token_hex(16)}"


def get_downloadable(code: str, db: Session) -> FileShare | None:
    """Return the share only if the public may currently reach it."""
    share = (
        db.execute(
            select(FileShare).options(selectinload(FileShare.files)).where(FileShare.code == code)
        )
        .scalars()
        .one_or_none()
    )
    if share is None or share.status != "active":
        return None
    expires_at = as_utc(share.expires_at)
    if expires_at is not None and expires_at <= now_utc():
        return None
    # An empty share is not yet shareable; failing it like a missing one keeps
    # the public surface uniform.
    if not active_files(share):
        return None
    return share


def load_for_admin(code: str, db: Session) -> FileShare:
    share = (
        db.execute(
            select(FileShare).options(selectinload(FileShare.files)).where(FileShare.code == code)
        )
        .scalars()
        .one_or_none()
    )
    if share is None:
        raise HTTPException(status_code=404, detail="Not found")
    return share


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def parse_expiry(raw: str | None) -> dt.datetime | None:
    """Parse an ISO-8601 expiry from a form field."""
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


def check_expiry(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise HTTPException(status_code=422, detail="expires_at must be timezone-aware")
    if value <= now_utc():
        raise HTTPException(status_code=422, detail="expires_at must be in the future")
    return value


def writable_share(code: str, db: Session) -> FileShare:
    share = load_for_admin(code, db)
    if share.status == "deleted":
        raise HTTPException(status_code=422, detail="分享已刪除，無法變更")
    return share


# --------------------------------------------------------------------------
# Admin API: the share itself
# --------------------------------------------------------------------------


@router.post("/api/shares", response_model=FileShareCreatedOut)
def create_share(
    payload: FileShareCreateIn,
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> FileShareCreatedOut:
    """Create an empty share and mint its link and PIN. Files are added after."""
    expires_at = check_expiry(payload.expires_at)

    if payload.pin:
        try:
            plain_pin = validate_pin(payload.pin)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    else:
        plain_pin = generate_pin()

    share = FileShare(
        code=generate_share_code(db),
        pin_hash=hash_pin(plain_pin),
        note=(payload.note or None),
        status="active",
        expires_at=expires_at,
        failed_attempts=0,
        uploaded_by=str(_auth.get("email") or "")[:320],
    )
    db.add(share)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail="Code already exists") from e

    db.refresh(share)
    return FileShareCreatedOut(**share_to_out(share).model_dump(), pin=plain_pin)


@router.get("/api/shares", response_model=FileShareListOut)
def list_shares(
    query: str | None = Query(default=None),
    status: Literal["active", "disabled", "expired", "deleted", "all"] | None = Query(default="all"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> FileShareListOut:
    now = now_utc()
    base = select(FileShare)
    where = []

    if query:
        q = f"%{query.lower()}%"
        matching_share_ids = select(SharedFile.share_id).where(func.lower(SharedFile.filename).like(q))
        where.append(
            or_(
                func.lower(FileShare.code).like(q),
                func.lower(func.coalesce(FileShare.note, "")).like(q),
                FileShare.id.in_(matching_share_ids),
            )
        )

    if status and status != "all":
        if status == "expired":
            where.append(and_(FileShare.expires_at.is_not(None), FileShare.expires_at <= now))
        else:
            where.append(FileShare.status == status)
            if status == "active":
                where.append(or_(FileShare.expires_at.is_(None), FileShare.expires_at > now))

    if where:
        base = base.where(and_(*where))

    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = (
        db.execute(
            base.options(selectinload(FileShare.files))
            .order_by(FileShare.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return FileShareListOut(
        items=[share_to_out(s) for s in rows], total=total, limit=limit, offset=offset
    )


@router.patch("/api/shares/{code}", response_model=FileShareOut)
def update_share(
    code: str = Path(..., min_length=1, max_length=32),
    payload: FileShareUpdateIn = ...,
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> FileShareOut:
    """Update expiry and/or note. Only fields present in the request are applied."""
    share = writable_share(code, db)

    fields = payload.model_fields_set
    if "expires_at" in fields:
        if payload.expires_at is not None and payload.expires_at.tzinfo is None:
            raise HTTPException(status_code=422, detail="expires_at must be timezone-aware")
        share.expires_at = payload.expires_at
    if "note" in fields:
        share.note = payload.note or None

    share.updated_at = now_utc()
    db.add(share)
    db.commit()
    db.refresh(share)
    return share_to_out(share)


@router.post("/api/shares/{code}/regenerate-pin", response_model=PinOut)
def regenerate_share_pin(
    code: str = Path(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> PinOut:
    """Issue a new PIN. The old one stops working immediately.

    This is the recovery path for a forgotten PIN -- stored hashes cannot be
    read back. It also clears any brute-force lockout.
    """
    share = writable_share(code, db)

    plain_pin = generate_pin()
    share.pin_hash = hash_pin(plain_pin)
    share.failed_attempts = 0
    share.locked_until = None
    share.updated_at = now_utc()
    db.add(share)
    db.commit()
    return PinOut(code=code, pin=plain_pin)


@router.post("/api/shares/{code}/disable", response_model=DisableOut)
def disable_share(
    code: str = Path(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> DisableOut:
    share = writable_share(code, db)
    share.status = "disabled"
    share.updated_at = now_utc()
    db.add(share)
    db.commit()
    return DisableOut(code=code, status=share.status)


@router.post("/api/shares/{code}/enable", response_model=EnableOut)
def enable_share(
    code: str = Path(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> EnableOut:
    share = writable_share(code, db)
    if share.status != "disabled":
        raise HTTPException(status_code=422, detail="Share is not disabled")
    share.status = "active"
    share.updated_at = now_utc()
    db.add(share)
    db.commit()
    return EnableOut(code=code, status=share.status)


def erase_object(record: SharedFile) -> None:
    try:
        get_storage().delete(record.storage_path)
    except Exception as e:
        logging.exception("Failed to delete shared file object")
        raise HTTPException(status_code=502, detail="檔案刪除失敗，請稍後再試") from e


@router.delete("/api/shares/{code}")
def delete_share(
    code: str = Path(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> dict[str, str]:
    """Erase every file in the share and mark it deleted.

    Unlike short links, the content really is removed -- shares can hold
    sensitive material and must not linger in the bucket. The rows stay for the
    audit trail, and the code is never reused.
    """
    share = load_for_admin(code, db)
    if share.status != "deleted":
        for record in share.files:
            if record.status == "active":
                erase_object(record)
                record.status = "deleted"
                db.add(record)
        share.status = "deleted"
        share.updated_at = now_utc()
        db.add(share)
        db.commit()
    return {"message": "Share deleted", "code": code}


# --------------------------------------------------------------------------
# Admin API: files within a share
# --------------------------------------------------------------------------


@router.post("/api/shares/{code}/upload-session", response_model=UploadSessionOut)
def create_upload_session(
    request: Request,
    payload: UploadSessionIn,
    code: str = Path(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> UploadSessionOut:
    """Tell the browser where to send a file's bytes.

    Large files cannot come through this service at all -- Cloud Run rejects
    request bodies over 32 MiB before they reach us -- so when object storage
    can issue a resumable session, the browser uploads straight there and only
    reports back. Otherwise it posts the bytes here.
    """
    settings = get_settings()
    share = writable_share(code, db)

    if payload.size_bytes > settings.MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413, detail=f"檔案超過上限 {settings.MAX_FILE_MB} MB"
        )

    filename = sanitize_filename(payload.filename)
    content_type = sanitize_content_type(payload.content_type, filename)
    path = storage_path_for(share.code)

    token = make_upload_token(
        {
            "code": share.code,
            "path": path,
            "name": filename,
            "type": content_type,
            "size": payload.size_bytes,
            "exp": int(time.time()) + settings.UPLOAD_SESSION_TTL_SECONDS,
        }
    )

    origin = request.headers.get("Origin", "")
    upload_url: str | None = None
    try:
        upload_url = get_storage().create_upload_session(path, content_type, payload.size_bytes, origin)
    except Exception:
        # Fall back to proxying rather than failing the upload outright; the
        # size check below still protects Cloud Run's limit.
        logging.exception("Could not open a resumable upload session")

    if upload_url:
        return UploadSessionOut(
            mode="resumable", upload_url=upload_url, upload_token=token, storage_path=path
        )

    if payload.size_bytes > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=(
                f"檔案超過 {settings.MAX_UPLOAD_MB} MB，且目前無法直接上傳至儲存空間，"
                "請聯絡系統管理員"
            ),
        )
    return UploadSessionOut(
        mode="proxy",
        upload_url=f"/api/shares/{quote(share.code)}/files",
        upload_token=token,
        storage_path=path,
    )


def attach_file(
    share: FileShare, claim: dict, size_bytes: int, content_type: str, db: Session
) -> SharedFile:
    record = SharedFile(
        share_id=share.id,
        filename=claim["name"],
        content_type=content_type,
        size_bytes=size_bytes,
        storage_path=claim["path"],
        status="active",
        download_count=0,
    )
    db.add(record)
    share.updated_at = now_utc()
    db.add(share)
    db.commit()
    db.refresh(record)
    return record


@router.post("/api/shares/{code}/files", response_model=SharedFileOut)
def upload_file_via_proxy(
    file: UploadFile = File(...),
    upload_token: str = Form(...),
    code: str = Path(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> SharedFileOut:
    """Receive a file's bytes and store them.

    Defined as a sync endpoint so FastAPI runs it in a worker thread: the
    storage write and the database session are both blocking.
    """
    settings = get_settings()
    share = writable_share(code, db)

    claim = read_upload_token(upload_token)
    if claim is None or claim.get("code") != share.code:
        raise HTTPException(status_code=400, detail="上傳工作階段已失效，請重新上傳")

    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    size_bytes = 0
    while chunk := file.file.read(CHUNK_SIZE):
        size_bytes += len(chunk)
        if size_bytes > max_bytes:
            raise HTTPException(status_code=413, detail=f"檔案超過上限 {settings.MAX_UPLOAD_MB} MB")
    if size_bytes == 0:
        raise HTTPException(status_code=422, detail="檔案是空的")
    file.file.seek(0)

    try:
        get_storage().save(claim["path"], file.file, claim["type"])
    except Exception as e:
        logging.exception("Failed to store shared file")
        raise HTTPException(status_code=502, detail="檔案儲存失敗，請稍後再試") from e

    return file_to_out(attach_file(share, claim, size_bytes, claim["type"], db))


@router.post("/api/shares/{code}/files/finalize", response_model=SharedFileOut)
def finalize_upload(
    payload: UploadFinalizeIn,
    code: str = Path(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> SharedFileOut:
    """Attach a file the browser uploaded straight to storage.

    The size and content type are read back from storage rather than trusted
    from the request, so what gets recorded is what actually landed.
    """
    settings = get_settings()
    share = writable_share(code, db)

    claim = read_upload_token(payload.upload_token)
    if claim is None or claim.get("code") != share.code:
        raise HTTPException(status_code=400, detail="上傳工作階段已失效，請重新上傳")

    stat = get_storage().stat(claim["path"])
    if stat is None:
        raise HTTPException(status_code=409, detail="找不到已上傳的檔案，請重新上傳")
    size_bytes, stored_type = stat

    if size_bytes == 0:
        get_storage().delete(claim["path"])
        raise HTTPException(status_code=422, detail="檔案是空的")
    if size_bytes > settings.MAX_FILE_MB * 1024 * 1024:
        get_storage().delete(claim["path"])
        raise HTTPException(status_code=413, detail=f"檔案超過上限 {settings.MAX_FILE_MB} MB")

    content_type = sanitize_content_type(stored_type or claim["type"], claim["name"])
    return file_to_out(attach_file(share, claim, size_bytes, content_type, db))


@router.delete("/api/shares/{code}/files/{file_id}")
def delete_share_file(
    code: str = Path(..., min_length=1, max_length=32),
    file_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> dict[str, str]:
    """Erase one file's bytes, leaving the rest of the share intact."""
    share = writable_share(code, db)
    record = next((f for f in share.files if f.id == file_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail="Not found")

    if record.status != "deleted":
        erase_object(record)
        record.status = "deleted"
        share.updated_at = now_utc()
        db.add(record)
        db.add(share)
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
      button[type="submit"], .allbtn { width:100%; margin-top:14px; padding:12px 16px; font-size:16px;
                              font-weight:600; color:#fff; background:#2563eb; border:0; border-radius:10px;
                              cursor:pointer; font-family:inherit; }
      button[type="submit"]:hover, .allbtn:hover { background:#1d4ed8; }
      button[type="submit"]:disabled { background:#94a3b8; cursor:not-allowed; }
      .msg { margin-top:14px; font-size:15px; min-height:22px; }
      .msg.error { color:#b91c1c; }
      .msg.ok { color:#15803d; }
      .hint { margin-top:16px; font-size:13px; color:#64748b; }
      .filelist { list-style:none; padding:0; margin:16px 0 0; }
      .filelist li { display:flex; align-items:center; gap:12px; padding:12px 14px; border:1px solid #e2e8f0;
                     border-radius:10px; margin-bottom:8px; }
      .filelist .fname { flex:1; word-break:break-all; font-size:15px; color:#0f172a; }
      .filelist .fsize { font-size:13px; color:#64748b; white-space:nowrap; }
      .filelist a { display:inline-block; padding:7px 14px; background:#2563eb; color:#fff; border-radius:8px;
                    text-decoration:none; font-size:14px; font-weight:600; white-space:nowrap; }
      .filelist a:hover { background:#1d4ed8; }
      .hidden { display:none; }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="card">
        <nav class="langbar" id="langbar" aria-label="__LANGUAGE_LABEL__">__LANGUAGE_BUTTONS__</nav>
        <h1 data-i18n="heading">__HEADING__</h1>
        <p id="intro" data-i18n="intro">__INTRO__</p>
        <div class="meta">
          <div><b data-i18n="label_files">__LABEL_FILES__</b><span class="sep" data-i18n="colon">__COLON__</span>__FILE_COUNT__</div>
          <div><b data-i18n="label_total_size">__LABEL_TOTAL_SIZE__</b><span class="sep" data-i18n="colon">__COLON__</span>__TOTAL_SIZE__</div>
          <div><b data-i18n="label_expiry">__LABEL_EXPIRY__</b><span class="sep" data-i18n="colon">__COLON__</span><span id="expiry">__EXPIRY_INITIAL__</span></div>
        </div>
        <form id="pin-form" autocomplete="off">
          <label for="pin" data-i18n="pin_label">__PIN_LABEL__</label>
          <input id="pin" name="pin" type="text" inputmode="latin" maxlength="__PIN_LENGTH__"
                 placeholder="__PIN_PLACEHOLDER__" autocomplete="off" spellcheck="false" required />
          <button type="submit" id="submit" data-i18n="submit">__SUBMIT__</button>
        </form>
        <div id="results" class="hidden">
          <h2 id="list-heading" style="font-size:18px;margin:8px 0 0;" data-i18n="list_heading">__LIST_HEADING__</h2>
          <ul class="filelist" id="filelist"></ul>
          <button type="button" class="allbtn hidden" id="downloadall" data-i18n="download_all">__DOWNLOAD_ALL__</button>
        </div>
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
        var results = document.getElementById('results');
        var filelist = document.getElementById('filelist');
        var downloadAll = document.getElementById('downloadall');
        var lastError = null;
        var files = [];

        function t(key) {
          var table = strings[lang] || strings['zh-Hant'];
          return table[key] || key;
        }

        function humanSize(bytes) {
          if (bytes < 1024) { return bytes + ' B'; }
          var units = ['KB', 'MB', 'GB'];
          var size = bytes / 1024;
          for (var i = 0; i < units.length; i++) {
            if (size < 1024 || i === units.length - 1) { return size.toFixed(1) + ' ' + units[i]; }
            size /= 1024;
          }
          return size.toFixed(1) + ' GB';
        }

        function renderFiles() {
          filelist.innerHTML = '';
          for (var i = 0; i < files.length; i++) {
            var file = files[i];
            var li = document.createElement('li');

            var name = document.createElement('span');
            name.className = 'fname';
            name.textContent = file.filename;

            var size = document.createElement('span');
            size.className = 'fsize';
            size.textContent = humanSize(file.size_bytes);

            var link = document.createElement('a');
            link.href = file.download_url;
            link.setAttribute('download', file.filename);
            link.textContent = t('download');

            li.appendChild(name);
            li.appendChild(size);
            li.appendChild(link);
            filelist.appendChild(li);
          }
          downloadAll.className = files.length > 1 ? 'allbtn' : 'allbtn hidden';
        }

        function renderError() {
          if (!lastError) { return; }
          var text = t(lastError.key);
          if (lastError.remaining !== undefined) { text = text.replace('{n}', lastError.remaining); }
          if (lastError.minutes !== undefined) { text = text.replace('{m}', lastError.minutes); }
          msg.className = 'msg error';
          msg.textContent = text;
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
          if (files.length) { renderFiles(); }
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

        downloadAll.addEventListener('click', function () {
          // Staggered: browsers drop downloads fired all at once.
          files.forEach(function (file, index) {
            setTimeout(function () {
              var link = document.createElement('a');
              link.href = file.download_url;
              link.setAttribute('download', file.filename);
              document.body.appendChild(link);
              link.click();
              link.remove();
            }, index * 700);
          });
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
              files = result.data.files || [];
              form.className = 'hidden';
              results.className = '';
              renderFiles();
              msg.className = 'msg ok';
              msg.textContent = t('unlocked');
            })
            .catch(function (error) {
              lastError = error && error.key ? error : { key: 'err_network' };
              renderError();
              button.disabled = false;
              button.textContent = t('submit');
              input.select();
            });
        });
      })();
    </script>
  </body>
</html>"""


def render_landing_page(share: FileShare, language: str, explicit_language: bool) -> str:
    """Render the public download page in the visitor's language.

    Only the file count, total size and expiry are shown before the PIN is
    entered -- filenames can be revealing, and anyone can reach this page.

    All four translations are embedded, so switching language is instant and
    needs no round trip. Everything interpolated is HTML-escaped or
    JSON-encoded.
    """
    strings = STRINGS[language]
    files = active_files(share)
    expires_at = as_utc(share.expires_at)
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
            "LABEL_FILES": html.escape(strings["label_files"]),
            "LABEL_TOTAL_SIZE": html.escape(strings["label_total_size"]),
            "LABEL_EXPIRY": html.escape(strings["label_expiry"]),
            "COLON": html.escape(strings["colon"]),
            "PIN_LABEL": html.escape(strings["pin_label"]),
            "SUBMIT": html.escape(strings["submit"]),
            "HINT": html.escape(strings["hint"]),
            "LIST_HEADING": html.escape(strings["list_heading"]),
            "DOWNLOAD_ALL": html.escape(strings["download_all"]),
            "LANGUAGE_LABEL": html.escape(strings["language_label"]),
            "LANGUAGE_BUTTONS": language_buttons,
            "FILE_COUNT": str(len(files)),
            "TOTAL_SIZE": html.escape(human_size(sum(f.size_bytes for f in files))),
            "EXPIRY_INITIAL": html.escape(expiry_initial),
            "PIN_LENGTH": str(PIN_LENGTH),
            "PIN_PLACEHOLDER": "●" * PIN_LENGTH,
            "CODE_JSON": json.dumps(share.code),
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
    """Public landing page. Unknown, disabled, empty and expired shares all go
    to /404.html.

    Failing them identically means the page cannot be used to probe which codes
    exist.
    """
    share = get_downloadable(code, db)
    if share is None:
        return redirect_to_not_found()

    language = pick_language(request.headers.get("Accept-Language"), lang)
    return HTMLResponse(
        content=render_landing_page(share, language, explicit_language=lang in STRINGS),
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
def verify_share_pin(
    payload: FileVerifyIn,
    code: str = Path(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
) -> FileVerifyOut:
    """Check a PIN and hand back the file list with short-lived download URLs.

    Errors carry a machine-readable `error` code alongside the Chinese text, so
    the page can render them in whichever of its four languages the visitor is
    reading.
    """
    settings = get_settings()
    share = get_downloadable(code, db)
    if share is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": "連結不存在或已失效"},
        )

    now = now_utc()
    locked_until = as_utc(share.locked_until)
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

    if not verify_pin(payload.pin, share.pin_hash):
        share.failed_attempts += 1
        locked = share.failed_attempts >= settings.FILE_PIN_MAX_ATTEMPTS
        if locked:
            minutes = settings.FILE_PIN_LOCKOUT_MINUTES
            share.locked_until = now + dt.timedelta(minutes=minutes)
            share.failed_attempts = 0
        remaining = settings.FILE_PIN_MAX_ATTEMPTS - share.failed_attempts
        db.add(share)
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

    share.failed_attempts = 0
    share.locked_until = None
    db.add(share)
    db.commit()

    ttl = settings.FILE_DOWNLOAD_TOKEN_TTL_SECONDS
    token = make_download_token(share.code, ttl)
    return FileVerifyOut(
        files=[
            VerifiedFileOut(
                id=f.id,
                filename=f.filename,
                size_bytes=f.size_bytes,
                download_url=f"/f/{quote(share.code)}/download/{f.id}?token={quote(token)}",
            )
            for f in active_files(share)
        ],
        expires_in=ttl,
    )


@router.get("/f/{code}/download/{file_id}")
def download_shared_file(
    code: str = Path(..., min_length=1, max_length=32),
    file_id: int = Path(..., ge=1),
    token: str = Query(..., min_length=1, max_length=256),
    db: Session = Depends(get_db),
):
    """Stream one file to a holder of a valid download token.

    Streamed through this service rather than via a signed bucket URL, so the
    bucket stays private and a leaked URL expires with the token.
    """
    if not check_download_token(code, token):
        raise HTTPException(status_code=403, detail="下載連結已失效，請重新輸入 PIN 碼")

    share = get_downloadable(code, db)
    if share is None:
        return redirect_to_not_found()

    record = next((f for f in active_files(share) if f.id == file_id), None)
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
