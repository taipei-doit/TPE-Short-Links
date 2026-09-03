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
    # Shown to admins so they can relay it to the owning agency; the public
    # QR studio requires it before unlocking.
    qr_pin: str


class QrUnlockIn(BaseModel):
    """PIN presented to unlock the public QR studio for one link."""

    pin: str = Field(..., min_length=1, max_length=16)


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
    filename: str
    content_type: str
    size_bytes: int
    status: str
    sort_order: int
    download_count: int
    created_at: dt.datetime


class FileShareOut(BaseModel):
    id: int
    code: str
    note: str | None
    status: str
    expires_at: dt.datetime | None
    created_at: dt.datetime
    is_expired: bool
    is_locked: bool
    uploaded_by: str
    share_url: str
    files: list[SharedFileOut]
    file_count: int
    total_bytes: int
    download_count: int


class FileShareCreatedOut(FileShareOut):
    """Returned once, when the share is created.

    ``pin`` is the only moment the PIN exists in readable form -- it is stored
    hashed, so it can be regenerated but never looked up again.
    """

    pin: str


class FileShareListOut(BaseModel):
    items: list[FileShareOut]
    total: int
    limit: int
    offset: int


class FileShareCreateIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
    expires_at: dt.datetime | None = None
    pin: str | None = Field(default=None, max_length=64)


class FileShareUpdateIn(BaseModel):
    """Partial update: only fields present in the request are applied."""

    expires_at: dt.datetime | None = None
    note: str | None = Field(default=None, max_length=2000)


class UploadSessionIn(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str | None = Field(default=None, max_length=128)
    size_bytes: int = Field(..., ge=1)


class UploadSessionOut(BaseModel):
    """Where the browser should send the bytes.

    ``mode`` is ``resumable`` when it can upload straight to object storage
    (the only way past Cloud Run's 32 MiB request limit), or ``proxy`` when it
    must post them through this service instead.
    """

    mode: str
    upload_url: str
    upload_token: str
    storage_path: str


class UploadFinalizeIn(BaseModel):
    upload_token: str = Field(..., min_length=1, max_length=512)


class FileOrderIn(BaseModel):
    """Every active file in the share, in the order they should appear."""

    file_ids: list[int] = Field(..., min_length=1)


class PinOut(BaseModel):
    code: str
    pin: str


class FileVerifyIn(BaseModel):
    pin: str = Field(..., min_length=1, max_length=64)


class VerifiedFileOut(BaseModel):
    id: int
    filename: str
    size_bytes: int
    download_url: str


class FileVerifyOut(BaseModel):
    files: list[VerifiedFileOut]
    download_all_url: str
    expires_in: int


class DisableOut(BaseModel):
    code: str
    status: str


class EnableOut(BaseModel):
    code: str
    status: str
