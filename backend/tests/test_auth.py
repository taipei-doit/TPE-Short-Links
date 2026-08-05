from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.auth as auth_mod
import app.db.session as session_mod
from app.db.base import Base
from app.models import AdminUser


class _Settings:
    FIREBASE_PROJECT_ID = "test-project"
    FIREBASE_APP_ID = ""
    INTERNAL_API_TOKEN = ""


class _Request:
    def __init__(self, token: str | None):
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}


@pytest.fixture()
def admin_db(monkeypatch):
    """In-memory database that `is_admin_email` will read the whitelist from."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(session_mod, "get_engine", lambda: engine)
    auth_mod.invalidate_admin_cache()
    monkeypatch.delenv("ADMIN_WHITELIST", raising=False)
    yield engine
    auth_mod.invalidate_admin_cache()


def add_admin(engine, email: str) -> None:
    with Session(engine) as db:
        db.add(AdminUser(email=email))
        db.commit()


def test_is_admin_email_reads_from_database(admin_db):
    add_admin(admin_db, "admin@gov.taipei")
    assert auth_mod.is_admin_email("admin@gov.taipei") is True
    assert auth_mod.is_admin_email("evil@example.com") is False


def test_env_whitelist_used_only_when_table_is_empty(admin_db, monkeypatch):
    monkeypatch.setenv("ADMIN_WHITELIST", "bootstrap@gov.taipei")

    # Table empty -> env acts as the bootstrap whitelist.
    assert auth_mod.is_admin_email("bootstrap@gov.taipei") is True

    # Once real rows exist the env var must no longer grant access.
    add_admin(admin_db, "admin@gov.taipei")
    auth_mod.invalidate_admin_cache()
    assert auth_mod.is_admin_email("bootstrap@gov.taipei") is False
    assert auth_mod.is_admin_email("admin@gov.taipei") is True


def test_cache_invalidation_picks_up_new_admin(admin_db):
    add_admin(admin_db, "first@gov.taipei")
    assert auth_mod.is_admin_email("later@gov.taipei") is False

    add_admin(admin_db, "later@gov.taipei")
    auth_mod.invalidate_admin_cache("later@gov.taipei")
    assert auth_mod.is_admin_email("later@gov.taipei") is True


def test_whitelisted_user_passes(admin_db, monkeypatch):
    add_admin(admin_db, "admin@gov.taipei")
    monkeypatch.setattr(auth_mod, "get_settings", _Settings)
    monkeypatch.setattr(
        auth_mod.id_token,
        "verify_firebase_token",
        lambda *_a, **_k: {"email": "admin@gov.taipei", "email_verified": True},
    )
    claims = auth_mod.get_firebase_user(_Request("some-token"))
    assert claims["email"] == "admin@gov.taipei"


def test_valid_token_but_not_whitelisted_is_403(admin_db, monkeypatch):
    add_admin(admin_db, "admin@gov.taipei")
    monkeypatch.setattr(auth_mod, "get_settings", _Settings)
    monkeypatch.setattr(
        auth_mod.id_token,
        "verify_firebase_token",
        lambda *_a, **_k: {"email": "attacker@example.com", "email_verified": True},
    )
    with pytest.raises(HTTPException) as exc:
        auth_mod.get_firebase_user(_Request("some-token"))
    assert exc.value.status_code == 403


def test_unverified_email_is_401(admin_db, monkeypatch):
    monkeypatch.setattr(auth_mod, "get_settings", _Settings)
    monkeypatch.setattr(
        auth_mod.id_token,
        "verify_firebase_token",
        lambda *_a, **_k: {"email": "admin@gov.taipei", "email_verified": False},
    )
    with pytest.raises(HTTPException) as exc:
        auth_mod.get_firebase_user(_Request("some-token"))
    assert exc.value.status_code == 401


def test_missing_authorization_header_is_401(admin_db, monkeypatch):
    monkeypatch.setattr(auth_mod, "get_settings", _Settings)
    with pytest.raises(HTTPException) as exc:
        auth_mod.get_firebase_user(_Request(None))
    assert exc.value.status_code == 401


def test_whitelist_unavailable_fails_closed(monkeypatch):
    """If the whitelist cannot be read at all, deny rather than allow."""
    auth_mod.invalidate_admin_cache()
    monkeypatch.setattr(auth_mod, "get_settings", _Settings)
    monkeypatch.setattr(
        session_mod,
        "get_engine",
        lambda: (_ for _ in ()).throw(RuntimeError("database unreachable")),
    )
    monkeypatch.setattr(
        auth_mod.id_token,
        "verify_firebase_token",
        lambda *_a, **_k: {"email": "admin@gov.taipei", "email_verified": True},
    )
    with pytest.raises(HTTPException) as exc:
        auth_mod.get_firebase_user(_Request("some-token"))
    assert exc.value.status_code == 503
