from __future__ import annotations

import pytest
from fastapi import HTTPException

import app.auth as auth_mod


class _FakeDoc:
    def __init__(self, exists: bool):
        self.exists = exists


class _FakeFirestore:
    def __init__(self, admin_emails: set[str]):
        self._admins = admin_emails

    def collection(self, _name):
        return self

    def document(self, email):
        self._current = email
        return self

    def get(self):
        return _FakeDoc(self._current in self._admins)


class _Settings:
    FIREBASE_PROJECT_ID = "test-project"
    FIREBASE_APP_ID = ""


class _Request:
    def __init__(self, token: str | None):
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}


@pytest.fixture(autouse=True)
def _reset_admin_cache(monkeypatch):
    monkeypatch.setattr(auth_mod, "_admin_cache", {})
    monkeypatch.setattr(auth_mod, "_firestore_client", None)


def test_is_admin_email_firestore_hit(monkeypatch):
    monkeypatch.setattr(auth_mod, "_firestore_client", _FakeFirestore({"admin@gov.taipei"}))
    assert auth_mod.is_admin_email("admin@gov.taipei") is True
    assert auth_mod.is_admin_email("evil@example.com") is False


def test_is_admin_email_env_fallback(monkeypatch):
    monkeypatch.setattr(auth_mod, "_firestore_client", _FakeFirestore(set()))
    monkeypatch.setenv("ADMIN_WHITELIST", "backup@gov.taipei, other@gov.taipei")
    assert auth_mod.is_admin_email("backup@gov.taipei") is True
    assert auth_mod.is_admin_email("evil@example.com") is False


def test_whitelisted_user_passes(monkeypatch):
    monkeypatch.setattr(auth_mod, "get_settings", _Settings)
    monkeypatch.setattr(auth_mod, "_firestore_client", _FakeFirestore({"admin@gov.taipei"}))
    monkeypatch.setattr(
        auth_mod.id_token,
        "verify_firebase_token",
        lambda *_a, **_k: {"email": "admin@gov.taipei", "email_verified": True},
    )
    claims = auth_mod.get_firebase_user(_Request("some-token"))
    assert claims["email"] == "admin@gov.taipei"


def test_valid_token_but_not_whitelisted_is_403(monkeypatch):
    monkeypatch.setattr(auth_mod, "get_settings", _Settings)
    monkeypatch.setattr(auth_mod, "_firestore_client", _FakeFirestore({"admin@gov.taipei"}))
    monkeypatch.setattr(
        auth_mod.id_token,
        "verify_firebase_token",
        lambda *_a, **_k: {"email": "attacker@example.com", "email_verified": True},
    )
    with pytest.raises(HTTPException) as exc:
        auth_mod.get_firebase_user(_Request("some-token"))
    assert exc.value.status_code == 403


def test_unverified_email_is_401(monkeypatch):
    monkeypatch.setattr(auth_mod, "get_settings", _Settings)
    monkeypatch.setattr(
        auth_mod.id_token,
        "verify_firebase_token",
        lambda *_a, **_k: {"email": "admin@gov.taipei", "email_verified": False},
    )
    with pytest.raises(HTTPException) as exc:
        auth_mod.get_firebase_user(_Request("some-token"))
    assert exc.value.status_code == 401


def test_whitelist_unavailable_fails_closed(monkeypatch):
    class _Boom:
        def collection(self, _name):
            raise RuntimeError("firestore down")

    monkeypatch.setattr(auth_mod, "get_settings", _Settings)
    monkeypatch.setattr(auth_mod, "_firestore_client", _Boom())
    monkeypatch.setattr(
        auth_mod.id_token,
        "verify_firebase_token",
        lambda *_a, **_k: {"email": "admin@gov.taipei", "email_verified": True},
    )
    with pytest.raises(HTTPException) as exc:
        auth_mod.get_firebase_user(_Request("some-token"))
    assert exc.value.status_code == 503
