from __future__ import annotations

import csv
import datetime as dt
import gzip as gzip_module
import io
import ipaddress
import json
import logging
import pathlib
import re
import secrets
import socket
import ssl
import time
from html import unescape
from urllib.parse import urljoin, urlparse

import requests
import requests.adapters
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_firebase_user, invalidate_admin_cache
from app.db.session import get_db
from app.domains import STATUS_ERROR, STATUS_OK, lookup_domain, registrable_domain
from app.files import router as files_router
from app.models import AdminUser, BlockedWord, Domain, FileShare, ReservedCode, ShortLink, Tag
from app.pages import NOT_FOUND_HTML, redirect_to_not_found
from app.pins import verify_pin
from app.schemas import (
    AdminDeleteIn,
    AdminIn,
    AdminOut,
    BlockedWordOut,
    BlockedWordToggleIn,
    DisableOut,
    DomainOut,
    DomainRefreshOut,
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


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # url.taipei 只走 HTTPS（Cloud Run 終端），這裡補上瀏覽器端的安全宣告：
    # HSTS 鎖 HTTPS、nosniff 防 MIME 混淆、frame 兩式並用防點擊劫持。
    response = await call_next(request)
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response

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


def link_to_out(link: ShortLink, tag_name: str, domain: Domain | None = None) -> LinkOut:
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
        domain_name=link.domain_name,
        domain_status=domain.status if domain is not None else None,
        domain_expires_at=as_utc(domain.expires_at) if domain is not None else None,
        domain_checked_at=as_utc(domain.checked_at) if domain is not None else None,
        exceeds_domain_expiry=_exceeds_cap(expires_at, domain_cap(domain)),
        domain_suspect=bool(domain.suspect) if domain is not None else False,
        domain_suspect_detail=domain.suspect_detail if domain is not None and domain.suspect else "",
        domain_registered_at=as_utc(domain.registered_at) if domain is not None else None,
        domain_registrar=domain.registrar if domain is not None else "",
    )


def domain_to_out(domain: Domain) -> DomainOut:
    return DomainOut(
        name=domain.name,
        status=domain.status,
        expires_at=as_utc(domain.expires_at),
        checked_at=as_utc(domain.checked_at),
        detail=domain.detail,
        registered_at=as_utc(domain.registered_at),
        registrar=domain.registrar,
        nameservers=domain.nameservers,
        suspect=bool(domain.suspect),
        suspect_detail=domain.suspect_detail,
        suspect_at=as_utc(domain.suspect_at),
        suspect_expires_at=as_utc(domain.suspect_expires_at),
        suspect_registered_at=as_utc(domain.suspect_registered_at),
        suspect_registrar=domain.suspect_registrar,
        suspect_nameservers=domain.suspect_nameservers,
        suspect_dropped=bool(domain.suspect_dropped),
        confirmed_by=domain.confirmed_by,
        confirmed_at=as_utc(domain.confirmed_at),
    )


# ---- 網域註冊有效期防呆 ----
# 短網址的有效期不得超過目標網域的註冊有效期：網域一旦過期被他人搶註，
# 印出去的 QR Code 與已發布的短網址就會全部轉到別人手上。
# 這只是輸入時的防呆：短網址的到期日是它自己的，不隨網域連動、不自動延長；
# 網域續約後「刷新」只是把後台記錄的上限往後推，要延長短網址仍須手動改。
# 「永久有效」不擋、只警示（列表標記 exceeds_domain_expiry）。
_TAIPEI_TZ = dt.timezone(dt.timedelta(hours=8))


def _fmt_taipei(value: dt.datetime) -> str:
    return as_utc(value).astimezone(_TAIPEI_TZ).strftime("%Y-%m-%d %H:%M")


def _domain_check_is_fresh(domain: Domain) -> bool:
    settings = get_settings()
    hours = 1 if domain.status == STATUS_ERROR else settings.DOMAIN_CHECK_TTL_HOURS
    checked = as_utc(domain.checked_at)
    return checked is not None and now_utc() - checked < dt.timedelta(hours=hours)


def ensure_domain(db: Session, url: str, *, force: bool = False) -> Domain | None:
    """The Domain row for a target URL, looked up via RDAP when missing or stale.

    None when the URL has no registrable domain (IP literal etc.). Adds to the
    session but does not commit. A transient lookup failure never erases an
    expiry that was found earlier: a stale cap is the conservative outcome.
    """
    host = urlparse(url).hostname
    name = registrable_domain(host)
    if name is None:
        return None
    domain = db.get(Domain, name)
    if domain is not None and not force and _domain_check_is_fresh(domain):
        return domain
    result = lookup_domain(host)
    if domain is None:
        domain = Domain(name=name)
        db.add(domain)
    if result.status == STATUS_ERROR and domain.status == STATUS_OK:
        domain.detail = f"重新查詢失敗（{result.detail}），沿用先前查得的到期日"[:255]
    elif _looks_like_takeover(domain, result):
        _park_as_suspect(domain, result)
    else:
        _apply_lookup(domain, result)
    domain.checked_at = now_utc()
    # Flushed at once so a policy error raised right after (422) cannot leave
    # a second copy of the row pending in the same session.
    db.flush()
    return domain


# 註冊日期若相差不到這麼多，視為同一筆登記（部分註冊機構的時間戳會有秒級飄移）。
_REGISTRATION_JITTER = dt.timedelta(days=1)


def _looks_like_takeover(domain: Domain, result) -> bool:
    """Did the domain change hands since we last looked?

    RDAP only says how long the current registration runs, not whose it is.
    The registration date is the tell: a same-holder renewal keeps it, a lapse
    followed by someone else's registration resets it to a recent date. A
    domain that was registered and is now gone from the registry is the step
    before that -- anyone may pick it up -- and is flagged the same way.
    Only ever compares against a record we hold; the first lookup just fills.
    """
    if domain.status != STATUS_OK:
        return False
    if result.dropped:
        return True
    if result.status != STATUS_OK or result.registered_at is None:
        return False
    known = as_utc(domain.registered_at)
    return known is not None and result.registered_at > known + _REGISTRATION_JITTER


def _park_as_suspect(domain: Domain, result) -> None:
    """Hold a lookup's values aside instead of applying them; freezes the record."""
    known = as_utc(domain.registered_at)
    if result.dropped:
        detail = "註冊機構已查無此網域：原登記可能已被刪除，任何人都能重新註冊"
    else:
        detail = (
            f"註冊日期由 {_fmt_taipei(known) if known else '未知'} 變為 {_fmt_taipei(result.registered_at)}，"
            "網域可能已到期並被他人重新註冊"
        )
        if result.registrar and result.registrar != domain.registrar:
            detail += f"；註冊商由「{domain.registrar or '未知'}」變為「{result.registrar}」"
    # Keep the first sighting's timestamp so the flag's age is honest.
    if not domain.suspect:
        domain.suspect_at = now_utc()
    domain.suspect = True
    domain.suspect_detail = detail[:512]
    domain.suspect_dropped = bool(result.dropped)
    domain.suspect_expires_at = result.expires_at
    domain.suspect_registered_at = result.registered_at
    domain.suspect_registrar = result.registrar[:255]
    domain.suspect_nameservers = result.nameservers[:512]


def _apply_lookup(domain: Domain, result) -> None:
    domain.status = result.status
    domain.expires_at = result.expires_at
    domain.detail = result.detail[:255]
    domain.source = result.source[:255]
    if result.status == STATUS_OK:
        domain.registered_at = result.registered_at
        domain.registrar = result.registrar[:255]
        domain.nameservers = result.nameservers[:512]
    _clear_suspect(domain)


def _clear_suspect(domain: Domain) -> None:
    domain.suspect = False
    domain.suspect_detail = ""
    domain.suspect_at = None
    domain.suspect_dropped = False
    domain.suspect_expires_at = None
    domain.suspect_registered_at = None
    domain.suspect_registrar = ""
    domain.suspect_nameservers = ""


def refuse_if_suspect(domain: Domain | None) -> None:
    """No new links for (or moved onto) a domain that may have changed hands."""
    if domain is not None and domain.suspect:
        raise HTTPException(
            status_code=422,
            detail=(
                f"網域 {domain.name} 疑似已易主（{domain.suspect_detail}）。"
                "請先在管理頁確認該網域仍為本機關所有，再建立指向它的短網址"
            ),
        )


def domain_cap(domain: Domain | None) -> dt.datetime | None:
    """The latest moment a link into this domain may stay valid, if known."""
    if domain is None or domain.status != STATUS_OK:
        return None
    return as_utc(domain.expires_at)


def _exceeds_cap(expires_at: dt.datetime | None, cap: dt.datetime | None) -> bool:
    """Does this expiry (None = permanent) outlive the domain's registration?"""
    if cap is None:
        return False
    return expires_at is None or as_utc(expires_at) > cap


def enforce_domain_cap(requested: dt.datetime | None, domain: Domain | None) -> None:
    """Refuse an explicit expiry that would outlive the domain's registration.

    "Permanent" (None) is allowed on purpose -- the UI shows a warning and
    the list flags the link -- because plenty of agency targets are meant to
    live as long as the domain does. Registries that publish no expiry
    impose nothing.
    """
    cap = domain_cap(domain)
    if cap is None or requested is None:
        return
    assert domain is not None
    if cap <= now_utc():
        raise HTTPException(
            status_code=422,
            detail=(
                f"網域 {domain.name} 的註冊已於 {_fmt_taipei(cap)} 到期，短網址不得指向可能已易主的網域；"
                "若該網域已續約，請刷新網域資訊後再試"
            ),
        )
    if requested > cap:
        raise HTTPException(
            status_code=422,
            detail=(
                f"短網址有效期不得晚於網域註冊有效期：{domain.name} 至 {_fmt_taipei(cap)}；"
                "若該網域已續約，請先刷新網域資訊"
            ),
        )


def count_links_over_cap(db: Session, domain: Domain) -> int:
    """Links on this domain whose expiry (or permanence) outlives its registration."""
    cap = domain_cap(domain)
    if cap is None:
        return 0
    return db.execute(
        select(func.count())
        .select_from(ShortLink)
        .where(
            ShortLink.domain_name == domain.name,
            or_(ShortLink.expires_at.is_(None), ShortLink.expires_at > cap),
        )
    ).scalar_one()


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
            detail=f"此網址已建立過短網址：{existing.short_url}",
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
        # Pre-fetch enabled blocked words (words shorter than 3 chars never match)
        blocked_words = set(
            db.execute(
                select(BlockedWord.word).where(
                    func.length(BlockedWord.word) >= 3, BlockedWord.enabled.is_(True)
                )
            )
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

    # 網域註冊有效期：查（或沿用一天內的查詢結果），再據以決定實際到期時間。
    # 查詢結果先入庫：就算這次建立被政策擋下，下一次也不必再問一次 RDAP。
    domain = ensure_domain(db, str(payload.original_url))
    db.commit()
    refuse_if_suspect(domain)
    enforce_domain_cap(payload.expires_at, domain)

    link = ShortLink(
        code=code,
        original_url=str(payload.original_url),
        tag_id=payload.tag_id,
        expires_at=payload.expires_at,
        note=payload.note,
        status="active",
        click_count=0,
        domain_name=domain.name if domain is not None else None,
    )
    db.add(link)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=422, detail="Code already exists")
    db.refresh(link)
    return link_to_out(link, tag.name, domain)


@app.get("/api/links", response_model=LinkListOut)
def list_links(
    _auth: dict = Depends(get_firebase_user),
    query: str | None = Query(default=None),
    tag_id: int | None = Query(default=None, ge=1),
    status: Literal["active", "disabled", "expired", "all"] | None = Query(default="all"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort: Literal["created_at", "click_count", "expires_at", "code"] = Query(default="created_at"),
    order: Literal["asc", "desc"] = Query(default="desc"),
    db: Session = Depends(get_db),
) -> LinkListOut:
    now = now_utc()

    base = (
        select(ShortLink, Tag.name, Domain)
        .join(Tag, Tag.id == ShortLink.tag_id)
        .outerjoin(Domain, Domain.name == ShortLink.domain_name)
    )
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

    sort_column = {
        "created_at": ShortLink.created_at,
        "click_count": ShortLink.click_count,
        "expires_at": ShortLink.expires_at,
        "code": ShortLink.code,
    }[sort]
    order_by = sort_column.asc() if order == "asc" else sort_column.desc()
    rows = (
        db.execute(base.order_by(order_by, ShortLink.id.desc()).limit(limit).offset(offset))
        .all()
    )
    items = [link_to_out(link, tag_name, domain) for (link, tag_name, domain) in rows]
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

    base = (
        select(ShortLink, Tag.name, Domain)
        .join(Tag, Tag.id == ShortLink.tag_id)
        .outerjoin(Domain, Domain.name == ShortLink.domain_name)
    )
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
            "domain_name",
            "domain_status",
            "domain_expires_at",
            "exceeds_domain_expiry",
        ]
    )

    for link, tag_name, domain in rows:
        expires_at = as_utc(link.expires_at)
        is_expired = expires_at is not None and expires_at <= now
        short_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/{link.code}"
        domain_expires_at = as_utc(domain.expires_at) if domain is not None else None
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
                link.domain_name or "",
                domain.status if domain is not None else "",
                domain_expires_at.isoformat() if domain_expires_at is not None else "",
                "true" if _exceeds_cap(expires_at, domain_cap(domain)) else "false",
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


@app.get("/api/check/{target:path}")
def check_target(target: str, db: Session = Depends(get_db)) -> dict:
    """民眾防詐查核：回報短網址現況，僅有效連結才揭露目標網址。

    A link disabled for cause must not keep advertising where it used to go,
    so anything but an active link returns its state only.
    """
    if target.startswith("f/"):
        share = db.execute(select(FileShare).where(FileShare.code == target[2:])).scalar_one_or_none()
        if share is None or share.status == "deleted":
            return {"kind": "file_share", "state": "not_found", "original_url": None}
        if share.status == "disabled":
            return {"kind": "file_share", "state": "disabled", "original_url": None}
        share_expiry = as_utc(share.expires_at)
        if share_expiry is not None and share_expiry <= now_utc():
            return {"kind": "file_share", "state": "expired", "original_url": None}
        return {"kind": "file_share", "state": "active", "original_url": None}

    if is_reserved(target, db):
        return {"kind": "link", "state": "not_found", "original_url": None}
    link = db.execute(select(ShortLink).where(ShortLink.code == target)).scalar_one_or_none()
    if link is None:
        return {"kind": "link", "state": "not_found", "original_url": None}
    if link.status == "disabled":
        return {"kind": "link", "state": "disabled", "original_url": None}
    expires_at = as_utc(link.expires_at)
    if expires_at is not None and expires_at <= now_utc():
        return {"kind": "link", "state": "expired", "original_url": None}
    return {"kind": "link", "state": "active", "original_url": link.original_url}


# ---- 目標網站連結卡片（查核頁用） ----
_PREVIEW_TTL_SECONDS = 24 * 3600
_PREVIEW_MAX_BYTES = 512 * 1024
_preview_cache: dict[str, tuple[float, dict]] = {}


class _PreviewAdapter(requests.adapters.HTTPAdapter):
    """TLS verification without Python 3.13's VERIFY_X509_STRICT.

    Strict mode rejects certificates missing a Subject Key Identifier, which
    several government CA (GCA/GTLSCA) certs lack — the very sites we preview
    most. Chain and hostname verification stay fully enabled; this is the same
    level browsers and Python <=3.12 apply.
    """

    def init_poolmanager(self, *args, **kwargs):  # type: ignore[override]
        ctx = ssl.create_default_context()
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


_preview_session = requests.Session()
_preview_session.mount("https://", _PreviewAdapter())


def _host_is_public(hostname: str) -> bool:
    """Refuse to preview anything that resolves to a private/internal address.

    Target URLs are admin-registered, so this is defence in depth (the Cloud
    Run metadata server being the classic target), not the primary gate.
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
            return False
    return True


def _fetch_url_html(url: str) -> tuple[str, str]:
    """GET a registered target URL, capped in size and time. Split out for tests.

    Returns (html, final_url). Raises on anything non-HTML or non-public.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or not _host_is_public(parsed.hostname):
        raise ValueError("not previewable")
    # 相容型 UA：部分機關網站的 WAF 會擋掉陌生的純 bot 字串。
    r = _preview_session.get(
        url,
        timeout=(5, 8),
        stream=True,
        allow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; TPE-ShortLinks-LinkPreview/1.0; +https://url.taipei/check)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-TW,zh;q=0.9",
        },
    )
    final = urlparse(r.url)
    if final.scheme not in ("http", "https") or not final.hostname or not _host_is_public(final.hostname):
        raise ValueError("not previewable")
    if "text/html" not in r.headers.get("content-type", ""):
        raise ValueError("not html")
    raw = b""
    for chunk in r.iter_content(65536):
        raw += chunk
        if len(raw) >= _PREVIEW_MAX_BYTES:
            break
    enc = r.encoding
    if not enc or enc.lower() == "iso-8859-1":
        # 沒宣告 charset 時對「已讀入的位元組」自行偵測 —— 不能用
        # r.apparent_encoding，它會去讀已被串流消耗掉的 r.content。
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        enc = best.encoding if best else "utf-8"
    try:
        return raw.decode(enc, errors="replace"), r.url
    except LookupError:
        return raw.decode("utf-8", errors="replace"), r.url


def _meta_content(html_text: str, key: str) -> str | None:
    for pat in (
        rf'<meta[^>]+(?:property|name)=["\']{key}["\'][^>]*?content=["\']([^"\']*)["\']',
        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*?(?:property|name)=["\']{key}["\']',
    ):
        m = re.search(pat, html_text, re.IGNORECASE)
        if m:
            value = unescape(m.group(1)).strip()
            if value:
                return value
    return None


@app.get("/api/check-preview/{target:path}")
def check_preview(target: str, db: Session = Depends(get_db)) -> dict:
    """查核頁的目標網站連結卡片：標題／描述／代表圖，取自目標網頁的公開 meta 標籤。

    Only ever fetches URLs registered in the database — this must never become
    a free fetch-anything proxy — and only for links that currently resolve.
    """
    if target.startswith("f/") or is_reserved(target, db):
        raise HTTPException(status_code=404, detail="No preview")
    link = db.execute(select(ShortLink).where(ShortLink.code == target)).scalar_one_or_none()
    if link is None or link.status != "active":
        raise HTTPException(status_code=404, detail="No preview")
    expires_at = as_utc(link.expires_at)
    if expires_at is not None and expires_at <= now_utc():
        raise HTTPException(status_code=404, detail="No preview")

    url = link.original_url
    now = time.monotonic()
    cached = _preview_cache.get(url)
    if cached is not None and now - cached[0] < _PREVIEW_TTL_SECONDS:
        return cached[1]

    try:
        html_text, final_url = _fetch_url_html(url)
    except Exception as exc:  # a broken preview must degrade to "no card", never a 500
        logging.warning("link preview fetch failed for %s: %r", url, exc)
        raise HTTPException(status_code=404, detail="No preview")

    title_match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    image = _meta_content(html_text, "og:image")
    preview = {
        "title": _meta_content(html_text, "og:title")
        or (unescape(title_match.group(1)).strip() if title_match else None),
        "description": _meta_content(html_text, "og:description") or _meta_content(html_text, "description"),
        "image": urljoin(final_url, image) if image else None,
        "site_name": _meta_content(html_text, "og:site_name"),
    }
    if not any(preview.values()):
        raise HTTPException(status_code=404, detail="No preview")
    if len(_preview_cache) > 256:
        _preview_cache.clear()
    _preview_cache[url] = (now, preview)
    return preview


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


@app.get("/api/blocked-words", response_model=list[BlockedWordOut])
def list_blocked_words(
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> list[BlockedWordOut]:
    """List all blocked words from database."""
    rows = db.execute(select(BlockedWord).order_by(BlockedWord.word)).scalars().all()
    return [BlockedWordOut(word=row.word, enabled=row.enabled) for row in rows]


@app.post("/api/blocked-words")
def add_blocked_word(
    word: str = Query(..., min_length=1, max_length=6),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> dict[str, str]:
    """Add a word to the blocked list."""
    word_lower = word.strip().lower()
    if not word_lower or len(word_lower) > 6:
        raise HTTPException(status_code=422, detail="Word must be 1-6 characters")

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


@app.patch("/api/blocked-words/{word}")
def toggle_blocked_word(
    payload: BlockedWordToggleIn,
    word: str = Path(..., min_length=1, max_length=6),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> dict[str, str | bool]:
    """Enable or disable a blocked word without removing it from the list."""
    word_lower = word.strip().lower()
    blocked_word = db.execute(select(BlockedWord).where(BlockedWord.word == word_lower)).scalar_one_or_none()
    if not blocked_word:
        raise HTTPException(status_code=404, detail="Word not found")

    blocked_word.enabled = payload.enabled
    db.commit()

    return {"message": "Word updated", "word": word_lower, "enabled": payload.enabled}


@app.delete("/api/blocked-words/{word}")
def delete_blocked_word(
    word: str = Path(..., min_length=1, max_length=6),
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


@app.delete("/api/admins")
def delete_admin(
    payload: AdminDeleteIn,
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> dict[str, str]:
    """Remove an admin. Refuses to remove yourself or the last remaining admin.

    Email 由 request body 帶入而非 URL 路徑，個資不落入存取紀錄。
    """
    target = payload.email.strip().lower()
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
    domain = db.get(Domain, link.domain_name) if link.domain_name else None
    url_changed = False

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
                detail=f"此網址已建立過短網址：{existing.short_url}",
            )
        url_changed = new_url != link.original_url
        link.original_url = new_url
        if url_changed:
            domain = ensure_domain(db, new_url)
            refuse_if_suspect(domain)
            link.domain_name = domain.name if domain is not None else None

    if "expires_at" in fields:
        if payload.expires_at is not None and payload.expires_at.tzinfo is None:
            raise HTTPException(status_code=422, detail="expires_at must be timezone-aware")
        enforce_domain_cap(payload.expires_at, domain)
        link.expires_at = payload.expires_at
    elif url_changed:
        # 換到別的網域時，現有的到期日（或永久）也得過新網域的關；不合就擋下，
        # 由管理員先把有效期限改到新網域的註冊期限內再換網址。
        enforce_domain_cap(as_utc(link.expires_at), domain)

    db.add(link)
    db.commit()
    db.refresh(link)
    tag = db.get(Tag, link.tag_id)
    assert tag is not None
    return link_to_out(link, tag.name, domain)


@app.get("/api/domains/lookup", response_model=DomainOut)
def lookup_domain_for_url(
    url: str = Query(..., min_length=1, max_length=2048),
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> DomainOut:
    """建立頁預查：這個目標網址的網域註冊到什麼時候？結果與建立時用的相同（同一份快取）。"""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=422, detail="url must be an absolute http(s) URL")
    domain = ensure_domain(db, url.strip(), force=refresh)
    if domain is None:
        return DomainOut(
            name=None,
            status="not_applicable",
            expires_at=None,
            checked_at=None,
            detail="IP 位址或無法辨識的主機名稱，不適用網域註冊查詢",
        )
    db.commit()
    return domain_to_out(domain)


@app.post("/api/links/{code}/refresh-domain", response_model=DomainRefreshOut)
def refresh_link_domain(
    code: str = Path(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> DomainRefreshOut:
    """重新查詢這條短網址目標網域的註冊有效期（同網域共用一筆記錄）。

    只更新後台記錄的上限，不動任何短網址的到期日：網域續約後要延長短網址，
    仍由管理員手動修改。也用來補查本功能上線前建立、尚未登記網域的舊短網址。
    """
    if is_reserved(code, db):
        raise HTTPException(status_code=404, detail="Not found")
    link = db.execute(select(ShortLink).where(ShortLink.code == code)).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="Not found")
    domain = ensure_domain(db, link.original_url, force=True)
    if domain is None:
        raise HTTPException(status_code=422, detail="此網址為 IP 位址或無法辨識的主機名稱，不適用網域註冊查詢")
    link.domain_name = domain.name
    db.add(link)
    db.commit()
    db.refresh(link)
    tag = db.get(Tag, link.tag_id)
    assert tag is not None
    return DomainRefreshOut(
        domain=domain_to_out(domain),
        over_cap_links=count_links_over_cap(db, domain),
        link=link_to_out(link, tag.name, domain),
    )


@app.post("/api/domains/{name}/confirm", response_model=DomainOut)
def confirm_domain(
    name: str = Path(..., min_length=1, max_length=253),
    db: Session = Depends(get_db),
    _auth: dict = Depends(get_firebase_user),
) -> DomainOut:
    """管理員確認「疑似易主」的網域仍為本機關所有：採用擱置中的新登記資料、解除標記。

    Recorded with who confirmed and when; the only way a flagged domain
    becomes usable again, and a deliberate one.
    """
    domain = db.get(Domain, name.strip().lower())
    if domain is None:
        raise HTTPException(status_code=404, detail="Not found")
    if not domain.suspect:
        raise HTTPException(status_code=422, detail="此網域目前沒有待確認的變更")
    if domain.suspect_dropped:
        # Nothing to adopt: the registry has no record. Clear the flag but
        # keep the last known registration; the next lookup starts afresh.
        domain.status = "unknown"
        domain.expires_at = None
        domain.detail = "管理員確認：註冊機構查無此網域，視同未公開到期日"
    else:
        domain.status = STATUS_OK
        domain.expires_at = domain.suspect_expires_at
        domain.registered_at = domain.suspect_registered_at
        domain.registrar = domain.suspect_registrar
        domain.nameservers = domain.suspect_nameservers
        domain.detail = "管理員確認登記變更後採用的 RDAP 資料"
    _clear_suspect(domain)
    domain.confirmed_by = str(_auth.get("email") or "").strip().lower()[:320]
    domain.confirmed_at = now_utc()
    db.add(domain)
    db.commit()
    return domain_to_out(domain)


# Must be declared before the catch-all /{code} route so "404.html" is never
# treated as a short code (which would redirect to itself in a loop when the
# public domain points at this service).
@app.get("/404.html")
def not_found_page() -> HTMLResponse:
    return HTMLResponse(content=NOT_FOUND_HTML, status_code=200)


# Bare url.taipei/ serves the public landing page (official statement,
# privacy notice, link-check entry) instead of a dead end — someone who
# trims the code off a link should learn what this service is.
@app.get("/")
def root() -> Response:
    return _serve_spa_index()


# The QR style studio is a public, unauthenticated page in the static frontend.
# It is proxied rather than redirected so the address bar stays on url.taipei;
# the hashed /assets bundles the page references are proxied (and cached) too.
# All QR generation still happens client-side. Declared before /{code}; the
# codes "qr" and "assets" are reserved (see Settings).
# 開頭必須是英數（擋掉 "."、".." 與隱藏檔形式），其餘限白名單字元。
_ASSET_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_STUDIO_INDEX_TTL_SECONDS = 60.0
_studio_index_cache: dict[str, tuple[float, bytes]] = {}
_frontend_asset_cache: dict[str, tuple[bytes, str, bytes | None]] = {}


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


def _serve_spa_index() -> HTMLResponse:
    """Serve the SPA index proxied from the static hosting (cached, stale-on-error)."""
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
        raise HTTPException(status_code=503, detail="Page temporarily unavailable")
    return HTMLResponse(content=body, headers={"Cache-Control": "no-cache"})


@app.get("/qr/{target:path}")
def qr_studio(target: str, db: Session = Depends(get_db)) -> Response:
    # Server-side existence check — devtools can't talk a 404 into a page.
    if not _qr_target_exists(target, db):
        return redirect_to_not_found()
    return _serve_spa_index()


# 民眾查核頁：與 /qr 相反，刻意全開放（含裸路徑的輸入框），
# 讓民眾在點擊前就能確認短網址會轉去哪裡。
@app.get("/check")
@app.get("/check/{target:path}")
def check_page(target: str = "") -> Response:
    return _serve_spa_index()


# 無障礙聲明頁（標章申請要件：每頁頁尾都連得到）。
@app.get("/accessibility")
def accessibility_page() -> Response:
    return _serve_spa_index()


# 沒有這條，/robots.txt 會落進 /{code} 轉去 404 頁，爬蟲就把 404 的
# HTML 當 robots.txt 解析。內部工具（QR 產生器）與檔案分享不進索引。
_ROBOTS_TXT = """User-agent: *
Disallow: /qr
Disallow: /qr/
Disallow: /f/
Disallow: /assets/
"""


@app.get("/robots.txt")
def robots_txt() -> Response:
    return Response(content=_ROBOTS_TXT, media_type="text/plain; charset=utf-8")


# llms.txt（llmstxt.org 格式）：給大型語言模型讀的網站簡介。
# 與 robots.txt 同病：沒有這條就會掉進 /{code} 的 404 轉址鏈。
_LLMS_TXT = """# 臺北市短網址服務 url.taipei

> url.taipei 是臺北市政府資訊局建置與維運的官方短網址服務。凡是以 url.taipei \
開頭的連結與 QR Code，都由臺北市政府各機關建立並受市府控管，用於市政宣導、\
活動通知與便民服務。代碼一經使用即永久封存、不再重複配發。

## 主要頁面

- [服務聲明與隱私權宣告](https://url.taipei/)：本服務的官方說明、服務承諾與隱私權宣告
- [短網址查核](https://url.taipei/check)：輸入短網址或代碼，在開啟前確認該連結是否為市府所發、以及它將前往的網站
- [無障礙聲明](https://url.taipei/accessibility)：快速鍵設定、鍵盤操作說明與適用範圍

## 給模型的提示

- 民眾詢問 url.taipei 連結真偽時，請引導至查核頁 https://url.taipei/check
- 短網址（https://url.taipei/代碼）為轉址用途，失效連結一律導向官方說明頁
"""


@app.get("/llms.txt")
def llms_txt() -> Response:
    return Response(content=_LLMS_TXT, media_type="text/markdown; charset=utf-8")


@app.get("/favicon.ico")
def favicon() -> Response:
    # 瀏覽器都會自動要，回 204 免得又落進 /{code} 的 404 轉址鏈。
    return Response(status_code=204)


_COMPRESSIBLE_PREFIXES = ("text/", "application/javascript", "application/json", "image/svg")


@app.get("/assets/{filename}")
def frontend_asset(request: Request, filename: str = Path(..., min_length=1, max_length=128)) -> Response:
    if not _ASSET_NAME_RE.match(filename) or ".." in filename:
        raise HTTPException(status_code=404, detail="Not found")
    hit = _frontend_asset_cache.get(filename)
    if hit is None:
        try:
            status, body, ctype = _fetch_frontend(f"/assets/{filename}")
        except requests.RequestException:
            raise HTTPException(status_code=502, detail="Upstream fetch failed")
        if status != 200:
            raise HTTPException(status_code=404, detail="Not found")
        # requests 會自動解壓上游的回應，不重新壓縮就會把 200KB 的 CSS/JS
        # 原樣吐給使用者——壓縮版與原版一起進快取，各服務各的。
        gz = (
            gzip_module.compress(body, 6)
            if ctype.startswith(_COMPRESSIBLE_PREFIXES) and len(body) > 1024
            else None
        )
        # Filenames are content-hashed and immutable; cache them so a page view
        # costs one upstream fetch at most. Reset wholesale if it ever grows.
        if len(_frontend_asset_cache) > 64:
            _frontend_asset_cache.clear()
        _frontend_asset_cache[filename] = (body, ctype, gz)
        hit = _frontend_asset_cache[filename]
    body, ctype, gz = hit
    base_headers = {"Cache-Control": "public, max-age=31536000, immutable", "Vary": "Accept-Encoding"}
    if gz is not None and "gzip" in request.headers.get("accept-encoding", "").lower():
        return Response(
            content=gz,
            media_type=ctype,
            headers={**base_headers, "Content-Encoding": "gzip"},
        )
    return Response(content=body, media_type=ctype, headers=base_headers)


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

    # 縱深防禦：目的網址建立時已驗證過，但轉址前再確認一次只放行 http(s)，
    # 資料庫內容即使被繞道竄改也絕不轉向 javascript:/data: 之類的 URL。
    if not str(link.original_url).lower().startswith(("http://", "https://")):
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

