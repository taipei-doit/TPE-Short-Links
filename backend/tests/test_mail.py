from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app import mailer
from app.settings import get_settings


@pytest.fixture
def mail_env(monkeypatch):
    """Both routes configured; the actual senders are recorded, not run."""
    s = get_settings()
    for k, v in {
        "RELAY_URL": "https://relay.invalid",
        "RELAY_TOKEN": "t",
        "RELAY_CA_PEM": "pem",
        "SMTP_USER": "u@gmail.com",
        "SMTP_PASS": "p",
    }.items():
        monkeypatch.setattr(s, k, v)
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(mailer, "_send_relay", lambda to, *_: sent.append(("relay", to)))
    monkeypatch.setattr(mailer, "_send_smtp", lambda to, *_: sent.append(("smtp", to)))
    return sent


def test_gov_taipei_goes_through_relay(mail_env):
    assert mailer.send_mail("a@gov.taipei", "s", "<p>x</p>") == "relay"
    assert mail_env == [("relay", "a@gov.taipei")]


def test_other_domains_go_through_smtp(mail_env):
    assert mailer.send_mail("a@gmail.com", "s", "<p>x</p>") == "smtp"
    assert mailer.send_mail("a@mail.taipei.gov.tw", "s", "<p>x</p>") == "smtp"
    assert [r for r, _ in mail_env] == ["smtp", "smtp"]


def test_relay_failure_falls_back_to_smtp(mail_env, monkeypatch):
    def boom(*_):
        raise mailer.MailError("relay HTTP 403")

    monkeypatch.setattr(mailer, "_send_relay", boom)
    assert mailer.send_mail("a@gov.taipei", "s", "<p>x</p>") == "smtp"


def test_unconfigured_relay_uses_smtp(mail_env, monkeypatch):
    monkeypatch.setattr(get_settings(), "RELAY_TOKEN", "")
    assert mailer.send_mail("a@gov.taipei", "s", "<p>x</p>") == "smtp"


def test_no_route_raises(mail_env, monkeypatch):
    monkeypatch.setattr(get_settings(), "SMTP_PASS", "")
    with pytest.raises(mailer.MailError):
        mailer.send_mail("a@gmail.com", "s", "<p>x</p>")


@pytest.fixture
def login_env(monkeypatch):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(main_module, "is_admin_email", lambda e: e == "admin@gov.taipei")
    monkeypatch.setattr(main_module, "generate_sign_in_link", lambda e: "https://x/?oob=1&a=2")
    monkeypatch.setattr(main_module, "send_mail", lambda to, subject, html: sent.append((to, html)))
    main_module._login_link_sent.clear()
    return sent


def test_login_link_sent_to_admin(client: TestClient, login_env):
    res = client.post("/api/auth/login-link", json={"email": " Admin@gov.taipei "})
    assert res.status_code == 200, res.text
    assert login_env[0][0] == "admin@gov.taipei"
    assert 'href="https://x/?oob=1&amp;a=2"' in login_env[0][1]


def test_login_link_refused_for_non_admin(client: TestClient, login_env):
    res = client.post("/api/auth/login-link", json={"email": "who@gov.taipei"})
    assert res.status_code == 403
    assert login_env == []


def test_login_link_cooldown(client: TestClient, login_env):
    assert client.post("/api/auth/login-link", json={"email": "admin@gov.taipei"}).status_code == 200
    assert client.post("/api/auth/login-link", json={"email": "admin@gov.taipei"}).status_code == 429
    assert len(login_env) == 1


def test_login_link_send_failure_is_502_and_retryable(client: TestClient, login_env, monkeypatch):
    def boom(*_):
        raise mailer.MailError("down")

    monkeypatch.setattr(main_module, "send_mail", boom)
    assert client.post("/api/auth/login-link", json={"email": "admin@gov.taipei"}).status_code == 502
    # A failed send must not start the cooldown.
    assert main_module._login_link_sent == {}
