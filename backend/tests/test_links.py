from __future__ import annotations

import datetime as dt

import pytest


def test_create_rejects_http_by_default(client, monkeypatch):
    monkeypatch.setenv("ALLOW_HTTP_URLS", "false")
    r = client.post(
        "/api/links",
        json={"original_url": "http://example.com", "tag_id": 1, "expires_at": None, "note": None},
    )
    assert r.status_code == 422


def test_create_retries_on_reserved_code(client, monkeypatch):
    # First return a reserved code (exists in DB), then a usable one.
    import app.main as main_mod

    codes = iter(["reserved", "Aa0Bb1C"])
    monkeypatch.setattr(main_mod, "generate_code", lambda _n: next(codes))

    r = client.post(
        "/api/links",
        json={"original_url": "https://example.com", "tag_id": 1, "expires_at": None, "note": "x"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["code"] == "Aa0Bb1C"


def test_create_retries_on_unique_violation(client, monkeypatch):
    import app.main as main_mod

    # Create first link with code "DUPLICAT"
    monkeypatch.setattr(main_mod, "generate_code", lambda _n: "DUPLICAT")
    r1 = client.post("/api/links", json={"original_url": "https://a.example", "tag_id": 1, "expires_at": None, "note": None})
    assert r1.status_code == 200

    # Second create: return same code twice (causes unique violation), then a new code
    codes = iter(["DUPLICAT", "DUPLICAT", "NEWCODE1"])
    monkeypatch.setattr(main_mod, "generate_code", lambda _n: next(codes))
    r2 = client.post("/api/links", json={"original_url": "https://b.example", "tag_id": 1, "expires_at": None, "note": None})
    assert r2.status_code == 200
    assert r2.json()["code"] == "NEWCODE1"


def test_redirect_reserved_goes_to_404_page(client):
    r = client.get("/reserved", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/404.html")


def test_redirect_expired_goes_to_404_page(client, monkeypatch):
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "generate_code", lambda _n: "EXPIRE1")
    expires_at = (dt.datetime.now(dt.UTC) + dt.timedelta(minutes=1)).isoformat()
    r = client.post("/api/links", json={"original_url": "https://example.com", "tag_id": 1, "expires_at": expires_at, "note": None})
    assert r.status_code == 200

    # Travel forward by patching now_utc used by redirect
    monkeypatch.setattr(main_mod, "now_utc", lambda: dt.datetime.now(dt.UTC) + dt.timedelta(days=1))
    rr = client.get("/EXPIRE1", follow_redirects=False)
    assert rr.status_code == 302
    assert rr.headers["location"].endswith("/404.html")


def test_disable_makes_redirect_go_to_404_page(client, monkeypatch):
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "generate_code", lambda _n: "DISABLE1")
    r = client.post("/api/links", json={"original_url": "https://example.com", "tag_id": 1, "expires_at": None, "note": None})
    assert r.status_code == 200

    d = client.post("/api/links/DISABLE1/disable")
    assert d.status_code == 200

    rr = client.get("/DISABLE1", follow_redirects=False)
    assert rr.status_code == 302
    assert rr.headers["location"].endswith("/404.html")
