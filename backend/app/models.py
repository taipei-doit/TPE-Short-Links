from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
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
