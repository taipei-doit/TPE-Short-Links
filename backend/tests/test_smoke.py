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


def test_bare_root_redirects_to_404_page(client: TestClient):
    res = client.get("/", follow_redirects=False)
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


def test_qr_studio_proxies_frontend(client: TestClient, monkeypatch):
    import app.main as main_module

    fetched: list[str] = []

    def fake_fetch(path: str) -> tuple[int, bytes, str]:
        fetched.append(path)
        if path == "/qr":
            return 200, b"<html>studio</html>", "text/html; charset=utf-8"
        if path == "/assets/ok.js":
            return 200, b"console.log(1)", "text/javascript"
        return 404, b"", "text/plain"

    monkeypatch.setattr(main_module, "_fetch_frontend", fake_fetch)
    main_module._studio_index_cache.clear()
    main_module._frontend_asset_cache.clear()

    # Only existing links get the studio page; the address bar stays on us.
    create_link(client, "https://example.com/qr-proxy", code="QP123")
    for path in ("/qr/QP123", "/qr/QP123"):
        res = client.get(path)
        assert res.status_code == 200
        assert "studio" in res.text

    # The index is cached, so repeat views cost one upstream fetch.
    assert fetched.count("/qr") == 1

    # Bare /qr, unknown codes and reserved codes are dead ends by design.
    for path in ("/qr", "/qr/NOPE99", "/qr/qr", "/qr/f/NOSHARE"):
        res = client.get(path, follow_redirects=False)
        assert res.status_code == 302, path
        assert res.headers["location"].endswith("/404.html"), path

    res = client.get("/assets/ok.js")
    assert res.status_code == 200
    assert res.headers["cache-control"].startswith("public")
    client.get("/assets/ok.js")
    assert fetched.count("/assets/ok.js") == 1

    assert client.get("/assets/missing.js").status_code == 404

    main_module._studio_index_cache.clear()
    main_module._frontend_asset_cache.clear()


def test_qr_unlock_pin_flow(client: TestClient):
    link = create_link(client, "https://example.com/qr-pin", code="QPIN1")
    pin = link["qr_pin"]
    assert len(pin) == 4 and pin.isdigit()

    # Wrong PIN counts down, right PIN hands over the emblem.
    res = client.post("/api/qr-unlock/QPIN1", json={"pin": "no"})
    assert res.status_code == 401
    assert res.json()["detail"]["remaining"] == 4

    res = client.post("/api/qr-unlock/QPIN1", json={"pin": pin})
    assert res.status_code == 200
    assert res.json()["mark"]["viewBox"]

    # A successful unlock resets the counter; five straight misses lock it.
    for _ in range(4):
        assert client.post("/api/qr-unlock/QPIN1", json={"pin": "no"}).status_code == 401
    res = client.post("/api/qr-unlock/QPIN1", json={"pin": "no"})
    assert res.status_code == 429
    # Locked means locked, even with the right PIN.
    assert client.post("/api/qr-unlock/QPIN1", json={"pin": pin}).status_code == 429

    assert client.post("/api/qr-unlock/NOPE99", json={"pin": "0000"}).status_code == 404


def test_qr_mark_requires_admin_or_unlock(client: TestClient):
    res = client.get("/api/qr-mark")
    assert res.status_code == 200
    assert res.json()["mark"]["viewBox"]


def test_qr_status_public_lookup(client: TestClient):
    create_link(client, "https://example.com/qrs", code="QS123")
    assert client.get("/api/qr-status/QS123").json() == {"state": "active"}
    assert client.get("/api/qr-status/QS404").json() == {"state": "not_found"}
    assert client.get("/api/qr-status/qr").json() == {"state": "not_found"}

    assert client.post("/api/links/QS123/disable").status_code == 200
    assert client.get("/api/qr-status/QS123").json() == {"state": "disabled"}


def test_public_check_endpoint(client: TestClient):
    create_link(client, "https://example.com/checkme", code="CHK01")

    res = client.get("/api/check/CHK01").json()
    assert res == {"kind": "link", "state": "active", "original_url": "https://example.com/checkme"}

    # Anything but an active link reveals its state only, never the target.
    assert client.post("/api/links/CHK01/disable").status_code == 200
    res = client.get("/api/check/CHK01").json()
    assert res["state"] == "disabled"
    assert res["original_url"] is None

    assert client.get("/api/check/NOPE99").json()["state"] == "not_found"
    assert client.get("/api/check/check").json()["state"] == "not_found"
    assert client.get("/api/check/f/NOSHARE").json() == {
        "kind": "file_share",
        "state": "not_found",
        "original_url": None,
    }


def test_check_page_is_open(client: TestClient, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(
        main_module, "_fetch_frontend", lambda path: (200, b"<html>studio</html>", "text/html")
    )
    main_module._studio_index_cache.clear()

    # Unlike /qr, the check page serves for any target and even bare /check.
    for path in ("/check", "/check/ANY9", "/check/f/WHATEVER"):
        res = client.get(path)
        assert res.status_code == 200, path
        assert "studio" in res.text

    main_module._studio_index_cache.clear()
    payload = {"original_url": "https://example.com/qr", "tag_id": 1, "expires_at": None, "note": None, "code": "qr"}
    res = client.post("/api/links", json=payload)
    assert res.status_code == 422
    assert "reserved" in res.text


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


def test_export_csv_starts_with_bom_and_lists_links(client: TestClient):
    create_link(client, "https://example.com/csv", code="J123")

    res = client.get("/api/links/export?status=all")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert 'filename="short_links.csv"' in res.headers["content-disposition"]

    body = res.content.decode("utf-8")
    # Excel on Windows needs the BOM to detect UTF-8 (Chinese tags/notes).
    assert body.startswith("﻿")
    assert "code,short_url" in body
    assert "J123" in body


def test_code_never_reused_even_after_disable(client: TestClient):
    create_link(client, "https://example.com/i", code="I123")
    client.post("/api/links/I123/disable")

    res = client.post(
        "/api/links",
        json={"original_url": "https://example.com/i2", "tag_id": 1, "expires_at": None, "note": None, "code": "I123"},
    )
    assert res.status_code == 422
