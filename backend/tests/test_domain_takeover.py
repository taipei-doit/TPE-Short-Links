"""Takeover guard: a change of holder is never accepted without an admin.

RDAP says how long the current registration runs, not whose it is. The
registration date tells the two apart: a same-holder renewal keeps it, a lapse
followed by someone else's registration resets it.
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from app.domains import DomainLookup, registrable_domain


def days(n: int) -> dt.datetime:
    return (dt.datetime.now(dt.UTC) + dt.timedelta(days=n)).replace(microsecond=0)


def use_rdap(monkeypatch, table: dict[str, DomainLookup]) -> None:
    """Fake RDAP keyed by registrable domain; unlisted domains answer "unknown"."""
    import app.domains as domains_mod
    import app.main as main_mod

    def fake(host: str | None) -> DomainLookup:
        name = registrable_domain(host)
        if name is None:
            return DomainLookup(name=None, status="not_applicable", detail="stub")
        hit = table.get(name)
        if hit is None:
            return DomainLookup(name=name, status="unknown", detail="stub")
        return DomainLookup(**{**hit.__dict__, "name": name})

    monkeypatch.setattr(main_mod, "lookup_domain", fake)
    monkeypatch.setattr(domains_mod, "lookup_domain", fake)


def ok(expires_at: dt.datetime, registered_at: dt.datetime | None, registrar: str = "TWNIC", dropped=False):
    return DomainLookup(
        name=None,
        status="ok" if not dropped else "unknown",
        expires_at=None if dropped else expires_at,
        detail="fake",
        registered_at=None if dropped else registered_at,
        registrar="" if dropped else registrar,
        nameservers="" if dropped else "ns1.example, ns2.example",
        dropped=dropped,
    )


def create(client: TestClient, url: str, code: str, expires_at: dt.datetime | None = None):
    return client.post(
        "/api/links",
        json={
            "original_url": url,
            "tag_id": 1,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "note": None,
            "code": code,
        },
    )


def test_same_holder_renewal_is_applied_directly(client: TestClient, monkeypatch):
    born = days(-3000)
    renewed = days(930)
    use_rdap(monkeypatch, {"agency.example": ok(days(200), born)})
    body = create(client, "https://www.agency.example/a", "TK01", days(10)).json()
    assert body["domain_registered_at"] is not None
    assert body["domain_registrar"] == "TWNIC"
    assert body["domain_suspect"] is False

    # Renewed for two more years: the registration date is unchanged, so the
    # new expiry is adopted without ceremony.
    use_rdap(monkeypatch, {"agency.example": ok(renewed, born)})
    res = client.post("/api/links/TK01/refresh-domain")
    assert res.status_code == 200, res.text
    d = res.json()["domain"]
    assert d["suspect"] is False
    assert dt.datetime.fromisoformat(d["expires_at"]) == renewed


def test_later_registration_date_is_parked_until_confirmed(client: TestClient, monkeypatch):
    born = days(-3000)
    old_cap, new_cap, reborn = days(30), days(365), days(-2)
    use_rdap(monkeypatch, {"lost.example": ok(old_cap, born)})
    create(client, "https://lost.example/", "TK02", days(10))

    # Someone else registered it after a lapse: new date, new registrar.
    use_rdap(monkeypatch, {"lost.example": ok(new_cap, reborn, registrar="Cheap Domains Inc")})
    res = client.post("/api/links/TK02/refresh-domain")
    assert res.status_code == 200, res.text
    d = res.json()["domain"]
    assert d["suspect"] is True
    assert "註冊日期" in d["suspect_detail"] and "Cheap Domains Inc" in d["suspect_detail"]
    # Recorded values are frozen; the new ones wait in suspect_*.
    assert dt.datetime.fromisoformat(d["expires_at"]) == old_cap
    assert d["registrar"] == "TWNIC"
    assert dt.datetime.fromisoformat(d["suspect_expires_at"]) == new_cap
    assert d["suspect_registrar"] == "Cheap Domains Inc"
    assert res.json()["link"]["domain_suspect"] is True

    # No new links for, or moved onto, a suspect domain.
    res = create(client, "https://lost.example/new", "TK03", days(5))
    assert res.status_code == 422
    assert "疑似已易主" in res.json()["detail"]
    create(client, "https://elsewhere.example/", "TK04")
    res = client.patch("/api/links/TK04", json={"original_url": "https://lost.example/moved"})
    assert res.status_code == 422

    # A repeat lookup while flagged keeps the original sighting time and stays frozen.
    first_seen = d["suspect_at"]
    res = client.post("/api/links/TK02/refresh-domain")
    assert res.json()["domain"]["suspect_at"] == first_seen
    assert dt.datetime.fromisoformat(res.json()["domain"]["expires_at"]) == old_cap

    # An admin confirms: parked values become the record, with an audit trail.
    res = client.post("/api/domains/lost.example/confirm")
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["suspect"] is False
    assert dt.datetime.fromisoformat(d["expires_at"]) == new_cap
    assert dt.datetime.fromisoformat(d["registered_at"]) == reborn
    assert d["registrar"] == "Cheap Domains Inc"
    assert d["confirmed_at"] is not None
    assert create(client, "https://lost.example/new", "TK03", days(5)).status_code == 200

    # Nothing left to confirm.
    assert client.post("/api/domains/lost.example/confirm").status_code == 422
    assert client.post("/api/domains/never.example/confirm").status_code == 404


def test_dropped_domain_is_flagged(client: TestClient, monkeypatch):
    use_rdap(monkeypatch, {"gone.example": ok(days(5), days(-900))})
    create(client, "https://gone.example/", "TK05", days(2))

    use_rdap(monkeypatch, {"gone.example": ok(days(5), None, dropped=True)})
    res = client.post("/api/links/TK05/refresh-domain")
    d = res.json()["domain"]
    assert d["suspect"] is True and d["suspect_dropped"] is True
    assert "查無此網域" in d["suspect_detail"]
    # The last known registration stays on record until confirmed.
    assert d["status"] == "ok"

    res = client.post("/api/domains/gone.example/confirm")
    assert res.status_code == 200, res.text
    assert res.json()["suspect"] is False
    assert res.json()["status"] == "unknown"


def test_first_lookup_fills_identity_without_flagging(client: TestClient, monkeypatch):
    # Rows from before the guard existed have no registration date recorded.
    use_rdap(monkeypatch, {"legacy.example": DomainLookup(name=None, status="ok", expires_at=days(100), detail="f")})
    create(client, "https://legacy.example/", "TK06", days(1))
    assert client.get("/api/links?query=legacy.example").json()["items"][0]["domain_registered_at"] is None

    born = days(-2000)
    use_rdap(monkeypatch, {"legacy.example": ok(days(100), born)})
    res = client.post("/api/links/TK06/refresh-domain")
    d = res.json()["domain"]
    assert d["suspect"] is False
    assert dt.datetime.fromisoformat(d["registered_at"]) == born


def test_registration_timestamp_jitter_is_tolerated(client: TestClient, monkeypatch):
    born = days(-1000)
    use_rdap(monkeypatch, {"jitter.example": ok(days(100), born)})
    create(client, "https://jitter.example/", "TK07", days(1))

    use_rdap(monkeypatch, {"jitter.example": ok(days(100), born + dt.timedelta(hours=5))})
    assert client.post("/api/links/TK07/refresh-domain").json()["domain"]["suspect"] is False
