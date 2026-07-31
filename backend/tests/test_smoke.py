from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ShortLink


def create_link(client: TestClient, url: str, code: str | None = None, expires_at: str | None = None) -> dict:
    payload = {"original_url": url, "tag_id": 1, "expires_at": expires_at, "note": None, "code": code}
    res = client.post("/api/links", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


def test_create_and_redirect(client: TestClient):
    link = create_link(client, "https://example.com/a", code="X123")
    assert link["code"] == "X123"

    res = client.get("/X123", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "https://example.com/a"


def test_unknown_code_redirects_to_404_page(client: TestClient):
    res = client.get("/nope", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"].endswith("/404.html")


def test_disabled_code_redirects_to_404_page(client: TestClient):
    create_link(client, "https://example.com/b", code="B123")
    assert client.post("/api/links/B123/disable").status_code == 200

    res = client.get("/B123", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"].endswith("/404.html")


def test_expired_code_redirects_to_404_page(client: TestClient, db_session: Session):
    create_link(client, "https://example.com/c", code="C123")
    link = db_session.execute(select(ShortLink).where(ShortLink.code == "C123")).scalar_one()
    link.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    db_session.commit()

    res = client.get("/C123", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"].endswith("/404.html")


def test_reserved_code_redirects_to_404_page(client: TestClient):
    res = client.get("/reserved", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"].endswith("/404.html")


def test_404_page_served_directly_no_loop(client: TestClient):
    res = client.get("/404.html", follow_redirects=False)
    assert res.status_code == 200
    assert "找不到您要找的頁面" in res.text


def test_patch_original_url(client: TestClient):
    future = (dt.datetime.now(dt.UTC) + dt.timedelta(days=30)).isoformat()
    create_link(client, "https://example.com/old", code="D123", expires_at=future)

    res = client.patch("/api/links/D123", json={"original_url": "https://example.com/new"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["original_url"] == "https://example.com/new"
    # expiry must be untouched by a URL-only update
    assert body["expires_at"] is not None

    res = client.get("/D123", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "https://example.com/new"


def test_patch_original_url_conflict_with_active_link(client: TestClient):
    create_link(client, "https://example.com/taken", code="E123")
    create_link(client, "https://example.com/other", code="E124")

    res = client.patch("/api/links/E124", json={"original_url": "https://example.com/taken"})
    assert res.status_code == 409
    assert res.json()["detail"].startswith("A short link already exists for this URL:")


def test_patch_expiry_only_keeps_url(client: TestClient):
    create_link(client, "https://example.com/keep", code="F123")
    future = (dt.datetime.now(dt.UTC) + dt.timedelta(days=7)).isoformat()

    res = client.patch("/api/links/F123", json={"expires_at": future})
    assert res.status_code == 200, res.text
    assert res.json()["original_url"] == "https://example.com/keep"


def test_patch_disabled_link_rejected(client: TestClient):
    create_link(client, "https://example.com/g", code="G123")
    client.post("/api/links/G123/disable")

    res = client.patch("/api/links/G123", json={"original_url": "https://example.com/g2"})
    assert res.status_code == 422


def test_duplicate_url_blocked_then_allowed_after_disable(client: TestClient):
    create_link(client, "https://example.com/dup", code="H123")

    res = client.post(
        "/api/links",
        json={"original_url": "https://example.com/dup", "tag_id": 1, "expires_at": None, "note": None, "code": "H124"},
    )
    assert res.status_code == 409

    client.post("/api/links/H123/disable")
    created = create_link(client, "https://example.com/dup", code="H124")
    assert created["code"] == "H124"


def test_code_never_reused_even_after_disable(client: TestClient):
    create_link(client, "https://example.com/i", code="I123")
    client.post("/api/links/I123/disable")

    res = client.post(
        "/api/links",
        json={"original_url": "https://example.com/i2", "tag_id": 1, "expires_at": None, "note": None, "code": "I123"},
    )
    assert res.status_code == 422
