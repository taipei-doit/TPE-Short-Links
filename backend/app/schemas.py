from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field, HttpUrl


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


class DisableOut(BaseModel):
    code: str
    status: str


class EnableOut(BaseModel):
    code: str
    status: str
