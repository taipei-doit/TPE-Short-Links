from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, EmailStr, Field, HttpUrl


class AdminOut(BaseModel):
    email: str
    name: str
    title: str


class AdminIn(BaseModel):
    email: EmailStr
    name: str = Field(default="", max_length=100)
    title: str = Field(default="", max_length=100)


class WhitelistCheckIn(BaseModel):
    email: EmailStr


class TagOut(BaseModel):
    id: int
    name: str
    is_active: bool


class LinkCreateIn(BaseModel):
    original_url: HttpUrl
    tag_id: int = Field(..., ge=1)
    expires_at: dt.datetime | None = None
    note: str | None = Field(default=None, max_length=2000)
    code: str | None = Field(default=None, min_length=1, max_length=32)


class LinkOut(BaseModel):
    id: int
    code: str
    original_url: str
    tag_id: int
    tag_name: str
    expires_at: dt.datetime | None
    note: str | None
    status: str
    created_at: dt.datetime
    is_expired: bool
    short_url: str
    click_count: int


class LinkListOut(BaseModel):
    items: list[LinkOut]
    total: int
    limit: int
    offset: int


class LinkUpdateIn(BaseModel):
    """Partial update: only fields present in the request are applied.

    Allowed only when status is active or expired (not disabled).
    """

    original_url: HttpUrl | None = None
    expires_at: dt.datetime | None = None


class SharedFileOut(BaseModel):
    id: int
    code: str
    filename: str
    content_type: str
    size_bytes: int
    note: str | None
    status: str
    expires_at: dt.datetime | None
    created_at: dt.datetime
    is_expired: bool
    download_count: int
    is_locked: bool
    uploaded_by: str
    share_url: str


class SharedFileCreatedOut(SharedFileOut):
    """Returned once, at upload time.

    ``pin`` is the only moment the PIN exists in readable form -- it is stored
    hashed, so it can be regenerated but never looked up again.
    """

    pin: str


class SharedFileListOut(BaseModel):
    items: list[SharedFileOut]
    total: int
    limit: int
    offset: int


class SharedFileUpdateIn(BaseModel):
    """Partial update: only fields present in the request are applied."""

    expires_at: dt.datetime | None = None
    note: str | None = Field(default=None, max_length=2000)


class PinOut(BaseModel):
    code: str
    pin: str


class FileVerifyIn(BaseModel):
    pin: str = Field(..., min_length=1, max_length=64)


class FileVerifyOut(BaseModel):
    filename: str
    size_bytes: int
    download_url: str
    expires_in: int


class DisableOut(BaseModel):
    code: str
    status: str


class EnableOut(BaseModel):
    code: str
    status: str
