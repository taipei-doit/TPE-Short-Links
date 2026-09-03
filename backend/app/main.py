from __future__ import annotations

import csv
import datetime as dt
import io
import json
import logging
import pathlib
import re
import secrets
import time

import requests
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_firebase_user, invalidate_admin_cache
from app.db.session import get_db
from app.files import router as files_router
from app.models import AdminUser, BlockedWord, FileShare, ReservedCode, ShortLink, Tag
from app.pages import NOT_FOUND_HTML, redirect_to_not_found
from app.pins import verify_pin
from app.schemas import (
    AdminIn,
    AdminOut,
    DisableOut,
    EnableOut,
    LinkCreateIn,
    LinkListOut,
    LinkOut,
    LinkUpdateIn,
    QrUnlockIn,
    TagOut,
    WhitelistCheckIn,
)
from app.settings import get_settings
from app.utils import (
    generate_code,
    load_seed_tags,
    now_utc,
    validate_expires_at,
    validate_original_url,
)

app = FastAPI(title="TPE Short Links")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://admin.url.taipei",
        "https://url-taipei.web.app",
        "https://url-taipei.firebaseapp.com",
        # The QR studio is proxied on the public domain and calls /api/qr-status.
        "https://url.taipei",
        "http://localhost:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# PIN-protected file sharing: /api/files/* for admins, /f/{code} for the public.
# Registered here so its routes are matched before the catch-all /{code}.
app.include_router(files_router)


def as_utc(value: dt.datetime | None) -> dt.datetime | None:
    """
    Normalize datetimes to timezone-aware UTC.

    Note: SQLite may return naive datetimes even if the column is timezone=True.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def is_reserved(code: str, db: Session) -> bool:
    settings = get_settings()
    if code in settings.reserved_codes_set():
        return True
    exists = db.execute(select(ReservedCode.code).where(ReservedCode.code == code)).first()
    return exists is not None


def sync_seed_tags(db: Session) -> None:
    """Ensure seed tags from `backend/app/tags.txt` exist in DB.

    - Inserts missing seed tags (active)
    - Reactivates seed tags that exist but were inactive
    - Does NOT deactivate user-created tags (allows API-created tags to persist)
    """
    desired = load_seed_tags()
    if not desired:
        return

    existing = db.execute(select(Tag)).scalars().all()
    by_name = {t.name: t for t in existing}

    changed = False

    for name in desired:
        t = by_name.get(name)
        if t is None:
            db.add(Tag(name=name, is_active=True))
            changed = True
        elif not t.is_active:
            t.is_active = True
            changed = True

    # Note: We intentionally do NOT deactivate tags not in the seed file.
    # This allows users to create custom tags via the API that persist.

    if changed:
        try:
            db.commit()
        except Exception as e:
            logging.error(f"Error committing tags: {e}")
            db.rollback()
            raise


def link_to_out(link: ShortLink, tag_name: str) -> LinkOut:
    settings = get_settings()
    expires_at = as_utc(link.expires_at)
    is_expired = expires_at is not None and expires_at <= now_utc()
    return LinkOut(
        id=link.id,
        code=link.code,
        original_url=link.original_url,
        tag_id=link.tag_id,
        tag_name=tag_name,
        expires_at=expires_at,
        note=link.note,
        status=link.status,
        created_at=link.created_at,
        is_expired=is_expired,
        short_url=f"{settings.PUBLIC_BASE_URL.rstrip('/')}/{link.code}",
        click_count=link.click_count,
        qr_pin=link.qr_pin,
    )


@app.get("/api/tags", response_model=list[TagOut])
def get_tags(
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> list[TagOut]:
    try:
        # Clear cache to ensure fresh load
        load_seed_tags.cache_clear()

        sync_seed_tags(db)
        rows = db.execute(select(Tag).where(Tag.is_active == True).order_by(Tag.name.asc())).scalars().all()  # noqa: E712
        return [TagOut(id=t.id, name=t.name, is_active=t.is_active) for t in rows]
    except Exception as e:
        # Log error but don't fail - return empty list if sync fails
        logging.error(f"Error syncing tags: {e}", exc_info=True)
        # Try to return existing tags even if sync failed
        try:
            rows = db.execute(select(Tag).where(Tag.is_active == True).order_by(Tag.name.asc())).scalars().all()  # noqa: E712
            return [TagOut(id=t.id, name=t.name, is_active=t.is_active) for t in rows]
        except Exception:
            # Catch Exception (not BaseException) so KeyboardInterrupt/SystemExit
            # still propagate instead of being swallowed here.
            logging.exception("Falling back to an empty tag list")
            return []


@app.post("/api/links", response_model=LinkOut)
def create_link(
    payload: LinkCreateIn,
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> LinkOut:
    settings = get_settings()
    sync_seed_tags(db)

    # Avoid logging full URL in error logs; validate explicitly with minimal messages.
    validate_original_url(str(payload.original_url), allow_http=settings.ALLOW_HTTP_URLS)
    validate_expires_at(payload.expires_at)

    tag = db.get(Tag, payload.tag_id)
    if tag is None or not tag.is_active:
        raise HTTPException(status_code=422, detail="tag_id is invalid")

    # If an active (non-expired) short link already exists for this URL, warn instead of silently creating a new one.
    now = now_utc()
    existing_row = (
        db.execute(
            select(ShortLink, Tag.name)
            .join(Tag, Tag.id == ShortLink.tag_id)
            .where(
                ShortLink.original_url == str(payload.original_url),
                ShortLink.status == "active",
                or_(ShortLink.expires_at.is_(None), ShortLink.expires_at > now),
            )
        ).first()
    )
    if existing_row is not None:
        existing_link, existing_tag_name = existing_row
        existing = link_to_out(existing_link, existing_tag_name)
        raise HTTPException(
            status_code=409,
            detail=f"A short link already exists for this URL: {existing.short_url}",
        )

    # Handle manual code or auto-generate
    if payload.code:
        # Manual code provided - relaxed validation (only check uniqueness and reserved)
        code = payload.code
        # Only check if code is reserved (system codes like 'api', 'docs' should still be blocked)
        if is_reserved(code, db):
            raise HTTPException(status_code=422, detail="Code is reserved")
        # Check if code already exists (uniqueness is still required)
        existing_link = db.execute(select(ShortLink).where(ShortLink.code == code)).scalar_one_or_none()
        if existing_link is not None:
            raise HTTPException(status_code=422, detail="Code already exists")
        # Note: Blocked word check and exact length requirement removed for custom codes
    else:
        # Auto-generate code
        code = None
        # Pre-fetch blocked words for efficiency (only 3-4 char words matter for blocking)
        blocked_words = set(
            db.execute(select(BlockedWord.word).where(func.length(BlockedWord.word) >= 3))
            .scalars()
            .all()
        )
        
        for _ in range(100):
            code = generate_code(settings.SHORTLINK_CODE_LENGTH)
            if is_reserved(code, db):
                continue
            # Check if code contains any blocked word as substring
            code_lower = code.lower()
            if any(word in code_lower for word in blocked_words):
                continue
            existing_link = db.execute(select(ShortLink).where(ShortLink.code == code)).scalar_one_or_none()
            if existing_link is None:
                break
        if code is None:
            raise HTTPException(status_code=500, detail="Failed to generate a unique code")

    link = ShortLink(
        code=code,
        original_url=str(payload.original_url),
        tag_id=payload.tag_id,
        expires_at=payload.expires_at,
        note=payload.note,
        status="active",
        click_count=0,
    )
    db.add(link)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=422, detail="Code already exists")
    db.refresh(link)
    return link_to_out(link, tag.name)


@app.get("/api/links", response_model=LinkListOut)
def list_links(
    _auth: dict = Depends(get_firebase_user),
    query: str | None = Query(default=None),
    tag_id: int | None = Query(default=None, ge=1),
    status: Literal["active", "disabled", "expired", "all"] | None = Query(default="all"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> LinkListOut:
    now = now_utc()

    base = select(ShortLink, Tag.name).join(Tag, Tag.id == ShortLink.tag_id)
    where = []

    if query:
        q = f"%{query.lower()}%"
        where.append(
            or_(
                func.lower(ShortLink.code).like(q),
                func.lower(ShortLink.original_url).like(q),
                func.lower(func.coalesce(ShortLink.note, "")).like(q),
            )
        )
    if tag_id:
        where.append(ShortLink.tag_id == tag_id)

    if status and status != "all":
        if status == "expired":
            where.append(and_(ShortLink.expires_at.is_not(None), ShortLink.expires_at <= now))
        else:
            where.append(ShortLink.status == status)
            # Exclude expired links from "active" by default (active means redirectable)
            if status == "active":
                where.append(or_(ShortLink.expires_at.is_(None), ShortLink.expires_at > now))

    if where:
        base = base.where(and_(*where))

    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()

    rows = (
        db.execute(base.order_by(ShortLink.created_at.desc()).limit(limit).offset(offset))
        .all()
    )
    items = [link_to_out(link, tag_name) for (link, tag_name) in rows]
    return LinkListOut(items=items, total=total, limit=limit, offset=offset)


@app.get("/api/links/export")
def export_links_csv(
    query: str | None = Query(default=None),
    tag_id: int | None = Query(default=None, ge=1),
    status: Literal["active", "disabled", "expired", "all"] | None = Query(default="all"),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> Response:
    """Export links as CSV (applies same filters as list_links, but no pagination)."""
    settings = get_settings()
    now = now_utc()

    base = select(ShortLink, Tag.name).join(Tag, Tag.id == ShortLink.tag_id)
    where = []

    if query:
        q = f"%{query.lower()}%"
        where.append(
            or_(
                func.lower(ShortLink.code).like(q),
                func.lower(ShortLink.original_url).like(q),
                func.lower(func.coalesce(ShortLink.note, "")).like(q),
            )
        )
    if tag_id:
        where.append(ShortLink.tag_id == tag_id)

    if status and status != "all":
        if status == "expired":
            where.append(and_(ShortLink.expires_at.is_not(None), ShortLink.expires_at <= now))
        else:
            where.append(ShortLink.status == status)
            if status == "active":
                where.append(or_(ShortLink.expires_at.is_(None), ShortLink.expires_at > now))

    if where:
        base = base.where(and_(*where))

    rows = db.execute(base.order_by(ShortLink.created_at.desc())).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "code",
            "short_url",
            "original_url",
            "tag_id",
            "tag_name",
            "status",
            "is_expired",
            "created_at",
            "expires_at",
            "note",
            "click_count",
        ]
    )

    for link, tag_name in rows:
        expires_at = as_utc(link.expires_at)
        is_expired = expires_at is not None and expires_at <= now
        short_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/{link.code}"
        writer.writerow(
            [
                link.id,
                link.code,
                short_url,
                link.original_url,
                link.tag_id,
                tag_name,
                link.status,
                "true" if is_expired else "false",
                link.created_at.isoformat(),
                expires_at.isoformat() if expires_at is not None else "",
                (link.note or "").replace("\n", " ").replace("\r", " "),
                link.click_count,
            ]
        )

    # Prepend a UTF-8 BOM so Excel on Windows detects the encoding and shows
    # Chinese tags/notes correctly instead of mojibake.
    content = "\ufeff" + output.getvalue()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="short_links.csv"'},
    )


@app.get("/api/links/{code}/qrcode")
def get_qrcode(
    code: str = Path(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> Response:
    """Generate QR code PNG for a short link."""
    import qrcode  # Lazy import so app starts without PIL in slim images (e.g. Cloud Run)

    settings = get_settings()
    link = db.execute(select(ShortLink).where(ShortLink.code == code)).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="Not found")

    short_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/{link.code}"
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(short_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    img_buffer = io.BytesIO()
    img.save(img_buffer, format="PNG")
    img_buffer.seek(0)

    return Response(
        content=img_buffer.getvalue(),
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="qrcode_{code}.png"'},
    )


_qr_mark_cache: dict[str, str] | None = None


def _qr_mark() -> dict[str, str]:
    """The official city emblem vector, served only after a PIN unlock (or to a
    signed-in admin). Kept out of the frontend bundle on purpose — that is the
    one gate devtools cannot route around."""
    global _qr_mark_cache
    if _qr_mark_cache is None:
        path = pathlib.Path(__file__).parent / "qr_mark.json"
        _qr_mark_cache = json.loads(path.read_text(encoding="utf-8"))
    return _qr_mark_cache


def _qr_pin_locked_message(locked_until: dt.datetime, now: dt.datetime) -> HTTPException:
    minutes = max(1, int((locked_until - now).total_seconds() // 60) + 1)
    return HTTPException(
        status_code=429,
        detail={"error": "locked", "minutes": minutes, "message": f"嘗試次數過多，請於 {minutes} 分鐘後再試"},
    )


@app.post("/api/qr-unlock/{target:path}")
def qr_unlock(
    payload: QrUnlockIn,
    target: str = Path(..., min_length=1, max_length=64),
    db: Session = Depends(get_db),
) -> dict:
    """Public PIN check that unlocks the QR studio for one link.

    Short links use their plaintext 4-digit qr_pin; f/ file shares reuse their
    own hashed download PIN. Both mirror the file-share lockout so a 4-digit
    space cannot be brute-forced.
    """
    settings = get_settings()
    now = now_utc()
    max_attempts = settings.FILE_PIN_MAX_ATTEMPTS
    lockout_minutes = settings.FILE_PIN_LOCKOUT_MINUTES

    if target.startswith("f/"):
        row = db.execute(select(FileShare).where(FileShare.code == target[2:])).scalar_one_or_none()
        if row is None or row.status == "deleted":
            raise HTTPException(status_code=404, detail={"error": "not_found", "message": "連結不存在"})
        pin_ok = lambda: verify_pin(payload.pin, row.pin_hash)  # noqa: E731
    else:
        if is_reserved(target, db):
            raise HTTPException(status_code=404, detail={"error": "not_found", "message": "連結不存在"})
        row = db.execute(select(ShortLink).where(ShortLink.code == target)).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail={"error": "not_found", "message": "連結不存在"})
        pin_ok = lambda: secrets.compare_digest(payload.pin.strip(), row.qr_pin)  # noqa: E731

    attempts_field = "failed_attempts" if target.startswith("f/") else "qr_pin_failed_attempts"
    locked_field = "locked_until" if target.startswith("f/") else "qr_pin_locked_until"

    locked_until = as_utc(getattr(row, locked_field))
    if locked_until is not None and locked_until > now:
        raise _qr_pin_locked_message(locked_until, now)

    if not pin_ok():
        attempts = getattr(row, attempts_field) + 1
        if attempts >= max_attempts:
            setattr(row, locked_field, now + dt.timedelta(minutes=lockout_minutes))
            setattr(row, attempts_field, 0)
            db.add(row)
            db.commit()
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "locked",
                    "minutes": lockout_minutes,
                    "message": f"嘗試次數過多，請於 {lockout_minutes} 分鐘後再試",
                },
            )
        setattr(row, attempts_field, attempts)
        db.add(row)
        db.commit()
        remaining = max_attempts - attempts
        raise HTTPException(
            status_code=401,
            detail={"error": "wrong_pin", "remaining": remaining, "message": f"PIN 碼錯誤，尚可嘗試 {remaining} 次"},
        )

    setattr(row, attempts_field, 0)
    setattr(row, locked_field, None)
    db.add(row)
    db.commit()
    return {"mark": _qr_mark()}


@app.get("/api/qr-mark")
def qr_mark_for_admins(_auth: dict = Depends(get_firebase_user)) -> dict:
    """Signed-in admins get the emblem without a PIN (used by the admin dialog)."""
    return {"mark": _qr_mark()}


@app.get("/api/qr-status/{target:path}")
def qr_status(target: str, db: Session = Depends(get_db)) -> dict[str, str]:
    """Minimal link-state lookup so the QR studio can warn about typos.

    Deliberately unauthenticated: it reveals nothing beyond what visiting the
    link already would (does it currently resolve). States: active, disabled,
    expired, not_found.
    """
    if target.startswith("f/"):
        share = db.execute(select(FileShare).where(FileShare.code == target[2:])).scalar_one_or_none()
        if share is None or share.status == "deleted":
            return {"state": "not_found"}
        if share.status == "disabled":
            return {"state": "disabled"}
        share_expiry = as_utc(share.expires_at)
        if share_expiry is not None and share_expiry <= now_utc():
            return {"state": "expired"}
        return {"state": "active"}

    if is_reserved(target, db):
        return {"state": "not_found"}
    link = db.execute(select(ShortLink).where(ShortLink.code == target)).scalar_one_or_none()
    if link is None:
        return {"state": "not_found"}
    if link.status == "disabled":
        return {"state": "disabled"}
    expires_at = as_utc(link.expires_at)
    if expires_at is not None and expires_at <= now_utc():
        return {"state": "expired"}
    return {"state": "active"}


@app.get("/api/blocked-words", response_model=list[str])
def list_blocked_words(
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> list[str]:
    """List all blocked words from database."""
    words = db.execute(select(BlockedWord.word).order_by(BlockedWord.word)).scalars().all()
    return list(words)


@app.post("/api/blocked-words")
def add_blocked_word(
    word: str = Query(..., min_length=1, max_length=4),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> dict[str, str]:
    """Add a word to the blocked list."""
    word_lower = word.strip().lower()
    if not word_lower or len(word_lower) > 4:
        raise HTTPException(status_code=422, detail="Word must be 1-4 characters")

    # Check if already exists
    existing = db.execute(select(BlockedWord).where(BlockedWord.word == word_lower)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Word already exists")

    # Add new word
    blocked_word = BlockedWord(word=word_lower)
    db.add(blocked_word)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Word already exists")

    return {"message": "Word added", "word": word_lower}


@app.delete("/api/blocked-words/{word}")
def delete_blocked_word(
    word: str = Path(..., min_length=1, max_length=4),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> dict[str, str]:
    """Remove a word from the blocked list."""
    word_lower = word.strip().lower()

    # Find and delete
    blocked_word = db.execute(select(BlockedWord).where(BlockedWord.word == word_lower)).scalar_one_or_none()
    if not blocked_word:
        raise HTTPException(status_code=404, detail="Word not found")

    db.delete(blocked_word)
    db.commit()

    return {"message": "Word removed", "word": word_lower}


@app.post("/api/internal/whitelist-check")
def internal_whitelist_check(
    request: Request,
    payload: WhitelistCheckIn,
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    """Whitelist lookup for the magic-link sender (Cloud Function).

    That function runs before anyone is signed in, so it cannot present an ID
    token; it authenticates with a shared secret instead. Only ever returns a
    boolean, so the whitelist itself is never exposed.
    """
    settings = get_settings()
    expected = settings.INTERNAL_API_TOKEN
    if not expected:
        raise HTTPException(status_code=404, detail="Not found")

    provided = request.headers.get("X-Internal-Token", "")
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid internal token")

    email = str(payload.email).strip().lower()
    exists = db.execute(select(AdminUser.email).where(AdminUser.email == email)).first() is not None
    return {"allowed": exists}


@app.get("/api/admins", response_model=list[AdminOut])
def list_admins(
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> list[AdminOut]:
    rows = db.execute(select(AdminUser).order_by(AdminUser.email.asc())).scalars().all()
    return [AdminOut(email=a.email, name=a.name, title=a.title) for a in rows]


@app.post("/api/admins", response_model=AdminOut)
def upsert_admin(
    payload: AdminIn,
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> AdminOut:
    """Create an admin, or update an existing one's name/title."""
    email = str(payload.email).strip().lower()
    name = payload.name.strip()
    title = payload.title.strip()

    existing = db.get(AdminUser, email)
    if existing is None:
        db.add(AdminUser(email=email, name=name, title=title))
    else:
        existing.name = name
        existing.title = title
        existing.updated_at = now_utc()
    db.commit()

    invalidate_admin_cache(email)
    return AdminOut(email=email, name=name, title=title)


@app.delete("/api/admins/{email}")
def delete_admin(
    email: str = Path(..., min_length=3, max_length=320),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> dict[str, str]:
    """Remove an admin. Refuses to remove yourself or the last remaining admin."""
    target = email.strip().lower()
    caller = str(_auth.get("email") or "").strip().lower()

    admin_user = db.get(AdminUser, target)
    if admin_user is None:
        raise HTTPException(status_code=404, detail="Admin not found")
    if caller and target == caller:
        raise HTTPException(status_code=422, detail="Cannot remove yourself")

    total = db.execute(select(func.count()).select_from(AdminUser)).scalar_one()
    if total <= 1:
        raise HTTPException(status_code=422, detail="Cannot remove the last admin")

    db.delete(admin_user)
    db.commit()

    invalidate_admin_cache(target)
    return {"message": "Admin removed", "email": target}


@app.post("/api/tags", response_model=TagOut)
def create_tag(
    name: str = Query(..., min_length=1, max_length=64),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> TagOut:
    """Create a new tag."""
    name_trimmed = name.strip()
    if not name_trimmed:
        raise HTTPException(status_code=422, detail="Tag name cannot be empty")

    # Check if exists
    existing = db.execute(select(Tag).where(Tag.name == name_trimmed)).scalar_one_or_none()
    if existing is not None:
        if existing.is_active:
            raise HTTPException(status_code=409, detail="Tag already exists")
        # Reactivate
        existing.is_active = True
        db.commit()
        db.refresh(existing)
        return TagOut(id=existing.id, name=existing.name, is_active=existing.is_active)

    # Create new
    tag = Tag(name=name_trimmed, is_active=True)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return TagOut(id=tag.id, name=tag.name, is_active=tag.is_active)


@app.delete("/api/tags/{tag_id}")
def delete_tag(
    tag_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> dict[str, str]:
    """Deactivate a tag (soft delete - doesn't delete rows)."""
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")

    # Check if tag is used by any links
    link_count = db.execute(select(func.count()).select_from(ShortLink).where(ShortLink.tag_id == tag_id)).scalar_one()
    if link_count > 0:
        raise HTTPException(status_code=409, detail=f"Cannot delete tag: {link_count} link(s) still use it")

    tag.is_active = False
    db.commit()
    return {"message": "Tag deactivated", "tag_id": tag_id}


@app.post("/api/links/{code}/disable", response_model=DisableOut)
def disable_link(
    code: str = Path(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> DisableOut:
    # Even if present in DB, reserved codes should not be manageable via this API (treat as not found).
    if is_reserved(code, db):
        raise HTTPException(status_code=404, detail="Not found")
    link = db.execute(select(ShortLink).where(ShortLink.code == code)).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="Not found")
    link.status = "disabled"
    db.add(link)
    db.commit()
    return DisableOut(code=code, status=link.status)


@app.post("/api/links/{code}/enable", response_model=EnableOut)
def enable_link(
    code: str = Path(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> EnableOut:
    """Revive a disabled link. Status becomes active; if expires_at is in the past it will display as expired until expiry is extended."""
    if is_reserved(code, db):
        raise HTTPException(status_code=404, detail="Not found")
    link = db.execute(select(ShortLink).where(ShortLink.code == code)).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="Not found")
    if link.status != "disabled":
        raise HTTPException(status_code=422, detail="Link is not disabled")
    link.status = "active"
    db.add(link)
    db.commit()
    return EnableOut(code=code, status=link.status)


@app.patch("/api/links/{code}", response_model=LinkOut)
def update_link(
    code: str = Path(..., min_length=1, max_length=32),
    payload: LinkUpdateIn = ...,
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> LinkOut:
    """Update original URL and/or expiry. Only fields present in the request are applied.

    Only allowed when status is active or expired (not disabled).
    """
    settings = get_settings()
    if is_reserved(code, db):
        raise HTTPException(status_code=404, detail="Not found")
    link = db.execute(select(ShortLink).where(ShortLink.code == code)).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="Not found")
    if link.status == "disabled":
        raise HTTPException(status_code=422, detail="Cannot modify a disabled link; enable it first")

    fields = payload.model_fields_set

    if "original_url" in fields:
        if payload.original_url is None:
            raise HTTPException(status_code=422, detail="original_url cannot be empty")
        new_url = str(payload.original_url)
        validate_original_url(new_url, allow_http=settings.ALLOW_HTTP_URLS)
        now = now_utc()
        existing_row = (
            db.execute(
                select(ShortLink, Tag.name)
                .join(Tag, Tag.id == ShortLink.tag_id)
                .where(
                    ShortLink.original_url == new_url,
                    ShortLink.id != link.id,
                    ShortLink.status == "active",
                    or_(ShortLink.expires_at.is_(None), ShortLink.expires_at > now),
                )
            ).first()
        )
        if existing_row is not None:
            existing_link, existing_tag_name = existing_row
            existing = link_to_out(existing_link, existing_tag_name)
            raise HTTPException(
                status_code=409,
                detail=f"A short link already exists for this URL: {existing.short_url}",
            )
        link.original_url = new_url

    if "expires_at" in fields:
        if payload.expires_at is not None and payload.expires_at.tzinfo is None:
            raise HTTPException(status_code=422, detail="expires_at must be timezone-aware")
        link.expires_at = payload.expires_at

    db.add(link)
    db.commit()
    db.refresh(link)
    tag = db.get(Tag, link.tag_id)
    assert tag is not None
    return link_to_out(link, tag.name)


# Must be declared before the catch-all /{code} route so "404.html" is never
# treated as a short code (which would redirect to itself in a loop when the
# public domain points at this service).
@app.get("/404.html")
def not_found_page() -> HTMLResponse:
    return HTMLResponse(content=NOT_FOUND_HTML, status_code=200)


# Bare url.taipei/ matches no route (the catch-all needs a non-empty code),
# which used to leak FastAPI's raw JSON 404. Send people to the same page
# every other dead end uses.
@app.get("/")
def root() -> Response:
    return redirect_to_not_found()


# The QR style studio is a public, unauthenticated page in the static frontend.
# It is proxied rather than redirected so the address bar stays on url.taipei;
# the hashed /assets bundles the page references are proxied (and cached) too.
# All QR generation still happens client-side. Declared before /{code}; the
# codes "qr" and "assets" are reserved (see Settings).
_ASSET_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_STUDIO_INDEX_TTL_SECONDS = 60.0
_studio_index_cache: dict[str, tuple[float, bytes]] = {}
_frontend_asset_cache: dict[str, tuple[bytes, str]] = {}


def _fetch_frontend(path: str) -> tuple[int, bytes, str]:
    """GET a path from the static frontend hosting. Split out so tests can stub it."""
    settings = get_settings()
    resp = requests.get(f"{settings.FRONTEND_BASE_URL.rstrip('/')}{path}", timeout=10)
    return resp.status_code, resp.content, resp.headers.get("content-type", "application/octet-stream")


_QR_TARGET_RE = re.compile(r"^(f/)?[A-Za-z0-9_-]{1,32}$")


def _qr_target_exists(target: str, db: Session) -> bool:
    """Does this studio target name a real link? Deleted shares and reserved
    codes don't count; disabled/expired ones do (their print material may need
    reprinting, and reactivation revives the same QR)."""
    if not _QR_TARGET_RE.match(target):
        return False
    if target.startswith("f/"):
        share = db.execute(select(FileShare).where(FileShare.code == target[2:])).scalar_one_or_none()
        return share is not None and share.status != "deleted"
    if is_reserved(target, db):
        return False
    link = db.execute(select(ShortLink).where(ShortLink.code == target)).scalar_one_or_none()
    return link is not None


@app.get("/qr")
def qr_studio_root() -> Response:
    # Deliberately closed: the studio only opens for a specific existing link,
    # never as a free-standing generator.
    return redirect_to_not_found()


@app.get("/qr/{target:path}")
def qr_studio(target: str, db: Session = Depends(get_db)) -> Response:
    # Server-side existence check — devtools can't talk a 404 into a page.
    if not _qr_target_exists(target, db):
        return redirect_to_not_found()
    now = time.monotonic()
    cached = _studio_index_cache.get("index")
    if cached is not None and now - cached[0] < _STUDIO_INDEX_TTL_SECONDS:
        return HTMLResponse(content=cached[1], headers={"Cache-Control": "no-cache"})
    try:
        status, body, _ = _fetch_frontend("/qr")
    except requests.RequestException:
        status, body = 0, b""
    if status == 200 and body:
        _studio_index_cache["index"] = (now, body)
    elif cached is not None:
        body = cached[1]  # stale beats broken while hosting hiccups
    else:
        raise HTTPException(status_code=503, detail="QR studio temporarily unavailable")
    return HTMLResponse(content=body, headers={"Cache-Control": "no-cache"})


@app.get("/assets/{filename}")
def frontend_asset(filename: str = Path(..., min_length=1, max_length=128)) -> Response:
    if not _ASSET_NAME_RE.match(filename):
        raise HTTPException(status_code=404, detail="Not found")
    hit = _frontend_asset_cache.get(filename)
    if hit is None:
        try:
            status, body, ctype = _fetch_frontend(f"/assets/{filename}")
        except requests.RequestException:
            raise HTTPException(status_code=502, detail="Upstream fetch failed")
        if status != 200:
            raise HTTPException(status_code=404, detail="Not found")
        # Filenames are content-hashed and immutable; cache them so a page view
        # costs one upstream fetch at most. Reset wholesale if it ever grows.
        if len(_frontend_asset_cache) > 64:
            _frontend_asset_cache.clear()
        _frontend_asset_cache[filename] = (body, ctype)
        hit = _frontend_asset_cache[filename]
    return Response(
        content=hit[0],
        media_type=hit[1],
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/{code}")
def redirect(
    code: str = Path(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
) -> Response:
    # Reserved codes must never resolve, even if present in DB.
    if is_reserved(code, db):
        return redirect_to_not_found()

    link = db.execute(select(ShortLink).where(ShortLink.code == code)).scalar_one_or_none()
    if link is None:
        return redirect_to_not_found()

    if link.status == "disabled":
        return redirect_to_not_found()

    expires_at = as_utc(link.expires_at)
    if expires_at is not None and expires_at <= now_utc():
        return redirect_to_not_found()

    # Increment click count (only count successful redirects for active, non-expired links)
    link.click_count += 1
    db.add(link)
    db.commit()

    return RedirectResponse(
        url=link.original_url,
        status_code=302,
        headers={"Cache-Control": "no-store"},
    )

