from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    links: Mapped[list["ShortLink"]] = relationship(back_populates="tag")


class ReservedCode(Base):
    __tablename__ = "reserved_codes"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False, server_default="reserved")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ShortLink(Base):
    __tablename__ = "short_links"

    # Use Integer PK for broad DB compatibility (SQLite tests + Postgres prod).
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=False)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    tag_id: Mapped[int] = mapped_column(Integer, ForeignKey("tags.id", ondelete="RESTRICT"), nullable=False)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    click_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    tag: Mapped[Tag] = relationship(back_populates="links")


class BlockedWord(Base):
    __tablename__ = "blocked_words"

    word: Mapped[str] = mapped_column(String(4), primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FileShare(Base):
    """One PIN-protected share link at PUBLIC_BASE_URL/f/{code}.

    A share holds one or more files: sending seven documents should mean one
    link and one PIN, not seven of each. It also means each file is uploaded in
    its own request, so the total size of a share is unbounded.

    Only admins upload. Anyone holding the link must still enter the PIN to
    download, and can never modify or list anything. The PIN is stored as a
    PBKDF2 hash (see app/pins.py), so it cannot be read back out of the
    database -- a lost PIN is regenerated, not recovered.

    Codes live in their own /f/ namespace, so they never collide with short
    link codes. As with short links, a code is never reused.
    """

    __tablename__ = "file_shares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    pin_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # active | disabled | deleted ("deleted" keeps the audit row after the
    # bytes are removed from storage).
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Brute-force throttle, kept in the database so it holds across the
    # multiple Cloud Run instances a single share link may be spread over.
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uploaded_by: Mapped[str] = mapped_column(String(320), nullable=False, server_default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    files: Mapped[list["SharedFile"]] = relationship(
        back_populates="share",
        cascade="all, delete-orphan",
        # Admin-defined order, falling back to upload order for anything that
        # has never been reordered.
        order_by="SharedFile.sort_order, SharedFile.id",
    )


class SharedFile(Base):
    """One file inside a share."""

    __tablename__ = "shared_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    share_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("file_shares.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False, server_default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    # Object key in the storage backend. Randomised, so the object name cannot
    # be guessed from the share link.
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    # active | deleted (bytes erased, row kept for the audit trail)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    # Position within the share. New files get one past the current maximum, so
    # they append; reordering rewrites the whole run as 1..N.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    share: Mapped[FileShare] = relationship(back_populates="files")


class AdminUser(Base):
    """Admin whitelist: the single source of truth for who may use /api/*.

    Previously stored in Firestore; moved here so the service depends on one
    datastore only (and to keep the system portable off GCP).
    """

    __tablename__ = "admin_users"

    email: Mapped[str] = mapped_column(String(320), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, server_default="")
    title: Mapped[str] = mapped_column(String(100), nullable=False, server_default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
