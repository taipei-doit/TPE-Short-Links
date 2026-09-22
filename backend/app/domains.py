"""Domain registration expiry lookups (RDAP).

Why this exists: a short link that outlives its target's domain registration
is a hijack waiting to happen. Once the domain lapses, anyone can register it,
and every printed QR code and published url.taipei link starts sending people
to them. So a link's expiry is capped at its domain's registration expiry,
and the cap is re-checked on demand ("refresh") when the agency renews.

Only RDAP is used -- the IANA-bootstrapped, JSON successor to WHOIS -- so
there is no text scraping. Registries that publish no RDAP data come back as
``unknown`` and impose no cap: .gov.tw / .edu.tw are registered outside
TWNIC's public RDAP, and .jp / .cn / .hk have no RDAP service at all.

Two things learned the hard way, kept here so they are not re-learned:
- TWNIC's .tw server answers ``426 Upgrade Required`` to HTTP/1.1 clients
  (i.e. ``requests``); it needs HTTP/2, hence ``httpx`` with ``http2=True``.
- The registrable domain is not "the last two labels": ``abc.taipei.gov.tw``
  is registered as ``taipei.gov.tw`` while ``www.doit.gov.taipei`` is
  ``gov.taipei``. The Public Suffix List decides, via ``publicsuffixlist``
  (bundled snapshot, no network).
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import logging
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

IANA_BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
_BOOTSTRAP_TTL_SECONDS = 24 * 3600
_BOOTSTRAP_RETRY_SECONDS = 3600
# Used only if the IANA bootstrap file has never been fetched successfully.
_BOOTSTRAP_FALLBACK = {
    "taipei": "https://rdap.nic.taipei/",
    "tw": "https://ccrdap.twnic.tw/tw/",
    "com": "https://rdap.verisign.com/com/v1/",
    "net": "https://rdap.verisign.com/net/v1/",
    "org": "https://rdap.publicinterestregistry.org/rdap/",
}
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$"
)
_TIMEOUT = httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0)
_HEADERS = {
    "Accept": "application/rdap+json, application/json",
    "User-Agent": "TPE-ShortLinks-DomainCheck/1.0 (+https://url.taipei)",
}

# Lookup outcomes. ``ok`` is the only one that yields a cap.
STATUS_OK = "ok"  # registry answered with an expiry date
STATUS_UNKNOWN = "unknown"  # registry publishes no expiry for this domain / TLD has no RDAP
STATUS_ERROR = "error"  # transient: network, timeout, 5xx
STATUS_NOT_APPLICABLE = "not_applicable"  # IP literal, localhost, no public suffix


@dataclass(frozen=True)
class DomainLookup:
    name: str | None
    status: str
    expires_at: dt.datetime | None = None
    detail: str = ""
    source: str = ""
    # Identity signals. A renewal by the same holder keeps the registration
    # date; a lapse followed by someone else's registration resets it. That
    # is what the takeover check in app/main.py compares.
    registered_at: dt.datetime | None = None
    registrar: str = ""
    nameservers: str = ""
    # True when the registry answered but has no such domain any more -- the
    # domain was dropped and anyone may register it.
    dropped: bool = False


class RdapUnsupported(Exception):
    """No RDAP service exists for this TLD. Permanent, not worth retrying soon."""


class RdapUnavailable(Exception):
    """The RDAP server exists but did not answer usefully. Transient."""


_psl = None
_psl_lock = threading.Lock()


def _public_suffix_list():
    global _psl
    if _psl is None:
        with _psl_lock:
            if _psl is None:
                from publicsuffixlist import PublicSuffixList

                _psl = PublicSuffixList()  # bundled snapshot, no network
    return _psl


def registrable_domain(host: str | None) -> str | None:
    """The domain somebody actually registered for this hostname, in ASCII form.

    ``www.doit.gov.taipei`` -> ``gov.taipei``; ``abc.taipei.gov.tw`` ->
    ``taipei.gov.tw``. None for IP literals, ``localhost``, bare public
    suffixes and anything that is not a hostname.
    """
    if not host:
        return None
    host = host.strip().rstrip(".").lower()
    if not host or host.startswith("["):
        return None
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    if not _HOSTNAME_RE.match(ascii_host):
        return None
    name = _public_suffix_list().privatesuffix(ascii_host)
    return name.lower() if name else None


_bootstrap_lock = threading.Lock()
_bootstrap: tuple[float, dict[str, str]] | None = None


def _rdap_base_url(tld: str) -> str | None:
    """RDAP base URL for a TLD from the IANA bootstrap registry (cached a day).

    A failed refresh keeps the previous table and backs off for an hour; the
    hard-coded fallback only ever serves a process that has never fetched it.
    """
    global _bootstrap
    with _bootstrap_lock:
        now = time.monotonic()
        if _bootstrap is None or now - _bootstrap[0] >= _BOOTSTRAP_TTL_SECONDS:
            try:
                r = httpx.get(IANA_BOOTSTRAP_URL, timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS)
                r.raise_for_status()
                table: dict[str, str] = {}
                for tlds, urls in r.json()["services"]:
                    https = [u for u in urls if u.startswith("https://")] or list(urls)
                    if not https:
                        continue
                    for t in tlds:
                        table[str(t).lower()] = https[0]
                _bootstrap = (now, table)
            except Exception as exc:  # noqa: BLE001 - stale beats nothing
                log.warning("RDAP bootstrap fetch failed: %r", exc)
                if _bootstrap is None:
                    return _BOOTSTRAP_FALLBACK.get(tld)
                _bootstrap = (now - _BOOTSTRAP_TTL_SECONDS + _BOOTSTRAP_RETRY_SECONDS, _bootstrap[1])
        return _bootstrap[1].get(tld)


def fetch_rdap_domain(name: str) -> tuple[dict | None, str]:
    """Network call. Returns (RDAP domain object or None when the registry has
    no such domain, server base URL). Split out so tests can stub it."""
    tld = name.rsplit(".", 1)[-1]
    base = _rdap_base_url(tld)
    if not base:
        raise RdapUnsupported(f"頂級網域 .{tld} 未提供 RDAP 查詢服務")
    url = base.rstrip("/") + "/domain/" + quote(name, safe="")
    try:
        # http2=True: TWNIC (.tw) answers 426 Upgrade Required to HTTP/1.1.
        with httpx.Client(http2=True, timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as client:
            r = client.get(url)
    except httpx.HTTPError as exc:
        raise RdapUnavailable(f"RDAP 連線失敗（{type(exc).__name__}）") from exc
    if r.status_code == 404:
        return None, base
    if r.status_code != 200:
        raise RdapUnavailable(f"RDAP 伺服器回應 HTTP {r.status_code}")
    try:
        return r.json(), base
    except ValueError as exc:
        raise RdapUnavailable("RDAP 回應不是有效的 JSON") from exc


def _event_date(record: dict, action: str) -> dt.datetime | None:
    for event in record.get("events") or []:
        if str(event.get("eventAction", "")).lower() != action:
            continue
        raw = event.get("eventDate")
        if not raw:
            return None
        try:
            parsed = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
    return None


def _expiration_from(record: dict) -> dt.datetime | None:
    return _event_date(record, "expiration")


def _registration_from(record: dict) -> dt.datetime | None:
    return _event_date(record, "registration")


def _registrar_from(record: dict) -> str:
    """Registrar name from the entity with the "registrar" role (jCard fn)."""
    for entity in record.get("entities") or []:
        roles = [str(r).lower() for r in (entity.get("roles") or [])]
        if "registrar" not in roles:
            continue
        vcard = entity.get("vcardArray")
        if isinstance(vcard, list) and len(vcard) > 1:
            for prop in vcard[1] or []:
                if isinstance(prop, list) and len(prop) >= 4 and str(prop[0]).lower() == "fn" and prop[3]:
                    return str(prop[3]).strip()
        if entity.get("handle"):
            return str(entity["handle"]).strip()
    return ""


def _nameservers_from(record: dict) -> str:
    names = sorted(
        {str(ns.get("ldhName") or "").lower() for ns in (record.get("nameservers") or []) if ns.get("ldhName")}
    )
    return ", ".join(names)


def lookup_domain(host: str | None) -> DomainLookup:
    """Registration expiry for the registrable domain of ``host``. Never raises."""
    name = registrable_domain(host)
    if name is None:
        return DomainLookup(
            name=None,
            status=STATUS_NOT_APPLICABLE,
            detail="IP 位址或無法辨識的主機名稱，不適用網域註冊查詢",
        )
    try:
        record, base = fetch_rdap_domain(name)
    except RdapUnsupported as exc:
        return DomainLookup(name=name, status=STATUS_UNKNOWN, detail=str(exc))
    except RdapUnavailable as exc:
        log.warning("RDAP lookup failed for %s: %s", name, exc)
        return DomainLookup(name=name, status=STATUS_ERROR, detail=str(exc))
    if record is None:
        return DomainLookup(
            name=name,
            status=STATUS_UNKNOWN,
            detail="註冊機構未公開此網域的登記資料（政府 gov.tw、學術 edu.tw 等網域不在公開 RDAP 內）",
            source=base,
            dropped=True,
        )
    expires_at = _expiration_from(record)
    if expires_at is None:
        return DomainLookup(name=name, status=STATUS_UNKNOWN, detail="註冊機構未公開此網域的到期日", source=base)
    ldh = str(record.get("ldhName") or name).lower()
    return DomainLookup(
        name=name,
        status=STATUS_OK,
        expires_at=expires_at,
        detail=f"RDAP：{ldh}",
        source=base,
        registered_at=_registration_from(record),
        registrar=_registrar_from(record)[:255],
        nameservers=_nameservers_from(record)[:512],
    )
