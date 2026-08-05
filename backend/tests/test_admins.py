from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import AdminUser


def seed(db: Session, email: str, name: str = "", title: str = "") -> None:
    db.add(AdminUser(email=email, name=name, title=title))
    db.commit()


def test_list_admins_empty(client: TestClient):
    res = client.get("/api/admins")
    assert res.status_code == 200
    assert res.json() == []


def test_create_and_list_admin(client: TestClient):
    res = client.post(
        "/api/admins",
        json={"email": "New.Admin@gov.taipei", "name": "王小明", "title": "資訊室 科員"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"email": "new.admin@gov.taipei", "name": "王小明", "title": "資訊室 科員"}

    listed = client.get("/api/admins").json()
    assert listed == [{"email": "new.admin@gov.taipei", "name": "王小明", "title": "資訊室 科員"}]


def test_upsert_updates_existing_profile(client: TestClient, db_session: Session):
    seed(db_session, "a@gov.taipei")

    res = client.post("/api/admins", json={"email": "a@gov.taipei", "name": "陳大文", "title": "股長"})
    assert res.status_code == 200

    listed = client.get("/api/admins").json()
    assert len(listed) == 1
    assert listed[0]["name"] == "陳大文"
    assert listed[0]["title"] == "股長"


def test_delete_admin(client: TestClient, db_session: Session):
    seed(db_session, "keep@gov.taipei")
    seed(db_session, "remove@gov.taipei")

    res = client.delete("/api/admins/remove@gov.taipei")
    assert res.status_code == 200

    remaining = [a["email"] for a in client.get("/api/admins").json()]
    assert remaining == ["keep@gov.taipei"]


def test_cannot_delete_last_admin(client: TestClient, db_session: Session):
    seed(db_session, "only@gov.taipei")

    res = client.delete("/api/admins/only@gov.taipei")
    assert res.status_code == 422
    assert "last admin" in res.json()["detail"]


def test_delete_unknown_admin_is_404(client: TestClient, db_session: Session):
    seed(db_session, "someone@gov.taipei")

    res = client.delete("/api/admins/ghost@gov.taipei")
    assert res.status_code == 404


def test_invalid_email_rejected(client: TestClient):
    res = client.post("/api/admins", json={"email": "not-an-email", "name": "", "title": ""})
    assert res.status_code == 422


def test_internal_whitelist_check_requires_token(client: TestClient, db_session: Session, monkeypatch):
    seed(db_session, "admin@gov.taipei")

    from app.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "INTERNAL_API_TOKEN", "s3cret", raising=False)

    # No token -> 401
    assert client.post("/api/internal/whitelist-check", json={"email": "admin@gov.taipei"}).status_code == 401

    # Wrong token -> 401
    res = client.post(
        "/api/internal/whitelist-check",
        json={"email": "admin@gov.taipei"},
        headers={"X-Internal-Token": "wrong"},
    )
    assert res.status_code == 401

    # Correct token -> boolean answer only
    res = client.post(
        "/api/internal/whitelist-check",
        json={"email": "admin@gov.taipei"},
        headers={"X-Internal-Token": "s3cret"},
    )
    assert res.status_code == 200
    assert res.json() == {"allowed": True}

    res = client.post(
        "/api/internal/whitelist-check",
        json={"email": "outsider@example.com"},
        headers={"X-Internal-Token": "s3cret"},
    )
    assert res.json() == {"allowed": False}


def test_internal_endpoint_disabled_without_configured_token(client: TestClient):
    res = client.post(
        "/api/internal/whitelist-check",
        json={"email": "admin@gov.taipei"},
        headers={"X-Internal-Token": "anything"},
    )
    assert res.status_code == 404
