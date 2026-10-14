"""Outgoing email: the Taipei City mail relay first, Gmail SMTP as the fallback.

The city's mail relay is an HTTPS front for the internal SMTP relay. It only
accepts mail for RELAY_DOMAINS (currently just gov.taipei), only from
allow-listed source IPs (this service leaves through Cloud NAT for that), and
always sends as its own fixed address. Everything it cannot take - other
domains, or the relay being down - goes out through SMTP_* instead.

The relay address, token and CA certificate are deployment secrets and are
deliberately not written anywhere in this repository.
"""
from __future__ import annotations

import json
import logging
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from functools import lru_cache

from app.settings import get_settings

log = logging.getLogger(__name__)


class MailError(RuntimeError):
    pass


def _relay_domains() -> set[str]:
    raw = get_settings().RELAY_DOMAINS
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def relay_configured() -> bool:
    s = get_settings()
    return bool(s.RELAY_URL and s.RELAY_TOKEN and s.RELAY_CA_PEM)


def smtp_configured() -> bool:
    s = get_settings()
    return bool(s.SMTP_USER and s.SMTP_PASS)


@lru_cache
def _relay_context(ca_pem: str) -> ssl.SSLContext:
    # Trust only the relay's own self-signed certificate. VERIFY_X509_STRICT
    # (on by default since Python 3.13) is dropped because a hand-made CA cert
    # often lacks the extensions it insists on; chain and hostname (IP SAN)
    # checks stay on.
    ctx = ssl.create_default_context(cadata=ca_pem)
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


def _send_relay(to: str, subject: str, html: str) -> None:
    s = get_settings()
    body = json.dumps({"to": [to], "subject": subject, "html": html}).encode("utf-8")
    req = urllib.request.Request(
        f"{s.RELAY_URL.rstrip('/')}/send",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {s.RELAY_TOKEN.strip()}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=_relay_context(s.RELAY_CA_PEM)) as r:
            res = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read() or b"{}")
        except ValueError:
            detail = {}
        raise MailError(f"relay HTTP {e.code}: {detail.get('error')} source={detail.get('source')}") from e
    except (OSError, ValueError) as e:
        raise MailError(f"relay unreachable: {e}") from e

    if not res.get("ok"):
        raise MailError(f"relay refused: {res.get('error')}")
    if res.get("refused"):
        raise MailError(f"relay recipient refused: {res['refused']}")


def _send_smtp(to: str, subject: str, html: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = s.SMTP_FROM or s.SMTP_USER
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content("此信為 HTML 格式，請使用支援 HTML 的郵件軟體開啟。")
    msg.add_alternative(html, subtype="html")
    try:
        if s.SMTP_PORT == 465:
            with smtplib.SMTP_SSL(s.SMTP_HOST, s.SMTP_PORT, timeout=30) as smtp:
                smtp.login(s.SMTP_USER, s.SMTP_PASS)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(s.SMTP_HOST, s.SMTP_PORT, timeout=30) as smtp:
                smtp.starttls()
                smtp.login(s.SMTP_USER, s.SMTP_PASS)
                smtp.send_message(msg)
    except (OSError, smtplib.SMTPException) as e:
        raise MailError(f"smtp failed: {e}") from e


def send_mail(to: str, subject: str, html: str) -> str:
    """Send one HTML message to one recipient; return the route used."""
    domain = to.rsplit("@", 1)[-1].lower()
    if relay_configured() and domain in _relay_domains():
        try:
            _send_relay(to, subject, html)
            log.info("mail sent via relay to %s", domain)
            return "relay"
        except MailError as e:
            if not smtp_configured():
                raise
            log.error("mail relay failed, falling back to SMTP: %s", e)

    if not smtp_configured():
        raise MailError("no mail route configured for this recipient")
    _send_smtp(to, subject, html)
    log.info("mail sent via smtp to %s", domain)
    return "smtp"
