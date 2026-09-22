"""Domain registration expiry guard: a link may not be set to outlive its domain.

The guard acts on input only. A link's expiry is its own -- never moved by a
lookup or a refresh -- so renewing a domain raises the cap and nothing else.
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from app.domains import DomainLookup, registrable_domain


def use_domains(monkeypatch, table: dict[str, tuple[str, dt.datetime | None]]) -> None:
    """Install a fake RDAP: {registrable domain: (status, expires_at)}.
    Domains not listed answer "unknown" (no cap)."""
    import app.domains as domains_mod
    import app.main as main_mod

    def fake(host: str | None) -> DomainLookup:
        name = registrable_domain(host)
        if name is None:
            return DomainLookup(name=None, status="not_applicable", detail="stub")
        status, expires_at = table.get(name, ("unknown", None))
        return DomainLookup(name=name, status=status, expires_at=expires_at, detail="fake")

    monkeypatch.setattr(main_mod, "lookup_domain", fake)
    monkeypatch.setattr(domains_mod, "lookup_domain", fake)


def days(n: int) -> dt.datetime:
    return (dt.datetime.now(dt.UTC) + dt.timedelta(days=n)).replace(microsecond=0)


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


def test_registrable_domain_uses_public_suffix_list():
    assert registrable_domain("www.doit.gov.taipei") == "gov.taipei"
    assert registrable_domain("abc.taipei.gov.tw") == "taipei.gov.tw"
    assert registrable_domain("a.b.example.com") == "example.com"
    assert registrable_domain("EXAMPLE.COM.") == "example.com"
    assert registrable_domain("中文.台灣") == "xn--fiq228c.xn--kpry57d"
    # Not registrable: IP literals, localhost, bare public suffixes.
    assert registrable_domain("1.2.3.4") is None
    assert registrable_domain("[::1]") is None
    assert registrable_domain("localhost") is None
    assert registrable_domain("gov.tw") is None
    assert registrable_domain(None) is None


def test_expiry_within_domain_cap_is_recorded_as_given(client: TestClient, monkeypatch):
    cap = days(400)
    use_domains(monkeypatch, {"example.com": ("ok", cap)})

    res = create(client, "https://www.example.com/a", "DOM01", days(100))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["domain_name"] == "example.com"
    assert body["domain_status"] == "ok"
    assert dt.datetime.fromisoformat(body["domain_expires_at"]) == cap
    # The link keeps its own date; nothing is rewritten to the cap.
    assert dt.datetime.fromisoformat(body["expires_at"]) == days(100)
    assert body["exceeds_domain_expiry"] is False

    # Exactly on the cap is fine too.
    assert create(client, "https://example.com/edge", "DOM01b", cap).status_code == 200


def test_expiry_past_domain_cap_is_refused(client: TestClient, monkeypatch):
    cap = days(400)
    use_domains(monkeypatch, {"example.com": ("ok", cap)})

    res = create(client, "https://example.com/late", "DOM02", days(500))
    assert res.status_code == 422
    assert "網域註冊有效期" in res.json()["detail"]


def test_permanent_is_refused_when_domain_expiry_known(client: TestClient, monkeypatch):
    use_domains(monkeypatch, {"example.com": ("ok", days(400))})

    res = create(client, "https://example.com/forever", "DOM03")
    assert res.status_code == 422
    assert "不得設為永久有效" in res.json()["detail"]


def test_unknown_domain_imposes_no_cap(client: TestClient):
    # Default stub: registry publishes nothing (gov.tw and friends).
    res = create(client, "https://www.taipei.gov.tw/x", "DOM04")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["expires_at"] is None
    assert body["domain_name"] == "taipei.gov.tw"
    assert body["domain_status"] == "unknown"
    assert body["exceeds_domain_expiry"] is False


def test_lapsed_domain_is_refused(client: TestClient, monkeypatch):
    use_domains(monkeypatch, {"lapsed.example": ("ok", days(-1))})
    res = create(client, "https://lapsed.example/", "DOM05", days(1))
    assert res.status_code == 422
    assert "已於" in res.json()["detail"]


def test_refresh_raises_cap_but_moves_no_link(client: TestClient, monkeypatch):
    old_cap = days(300)
    use_domains(monkeypatch, {"renew.example": ("ok", old_cap)})
    create(client, "https://renew.example/a", "DOM06", days(300))
    create(client, "https://renew.example/b", "DOM07", days(30))

    # Setting a date past the cap is refused until the domain is refreshed...
    res = client.patch("/api/links/DOM06", json={"expires_at": days(600).isoformat()})
    assert res.status_code == 422

    # ...the agency renews, one refresh raises the cap for the whole domain...
    new_cap = days(1000)
    use_domains(monkeypatch, {"renew.example": ("ok", new_cap)})
    res = client.post("/api/links/DOM06/refresh-domain")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["domain"]["status"] == "ok"
    assert dt.datetime.fromisoformat(body["domain"]["expires_at"]) == new_cap
    assert body["over_cap_links"] == 0
    # ...and no link's own expiry moved.
    assert dt.datetime.fromisoformat(body["link"]["expires_at"]) == days(300)
    listed = {i["code"]: i for i in client.get("/api/links?query=renew.example").json()["items"]}
    assert dt.datetime.fromisoformat(listed["DOM06"]["expires_at"]) == days(300)
    assert dt.datetime.fromisoformat(listed["DOM07"]["expires_at"]) == days(30)

    # Extending is now a deliberate, manual step.
    res = client.patch("/api/links/DOM06", json={"expires_at": days(600).isoformat()})
    assert res.status_code == 200, res.text


def test_refresh_flags_legacy_links_over_the_cap(client: TestClient, monkeypatch):
    # Created while the registry published nothing: a truly permanent link.
    legacy = create(client, "https://legacy.example/", "DOM08").json()
    assert legacy["expires_at"] is None

    cap = days(200)
    use_domains(monkeypatch, {"legacy.example": ("ok", cap)})
    res = client.post("/api/links/DOM08/refresh-domain")
    assert res.status_code == 200, res.text
    # Reported, not rewritten.
    assert res.json()["over_cap_links"] == 1
    link = res.json()["link"]
    assert link["expires_at"] is None
    assert link["exceeds_domain_expiry"] is True

    listed = client.get("/api/links?query=legacy.example").json()["items"][0]
    assert listed["exceeds_domain_expiry"] is True


def test_refresh_after_transient_error_keeps_previous_cap(client: TestClient, monkeypatch):
    cap = days(150)
    use_domains(monkeypatch, {"flaky.example": ("ok", cap)})
    create(client, "https://flaky.example/", "DOM09", days(10))

    use_domains(monkeypatch, {"flaky.example": ("error", None)})
    res = client.post("/api/links/DOM09/refresh-domain")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["domain"]["status"] == "ok"
    assert dt.datetime.fromisoformat(body["domain"]["expires_at"]) == cap
    assert "沿用" in body["domain"]["detail"]


def test_patch_expiry_respects_domain_cap(client: TestClient, monkeypatch):
    cap = days(90)
    use_domains(monkeypatch, {"patch.example": ("ok", cap)})
    create(client, "https://patch.example/", "DOM10", days(10))

    assert client.patch("/api/links/DOM10", json={"expires_at": days(120).isoformat()}).status_code == 422
    assert client.patch("/api/links/DOM10", json={"expires_at": None}).status_code == 422

    res = client.patch("/api/links/DOM10", json={"expires_at": days(60).isoformat()})
    assert res.status_code == 200, res.text
    assert dt.datetime.fromisoformat(res.json()["expires_at"]) == days(60)


def test_url_change_must_pass_new_domain_cap(client: TestClient, monkeypatch):
    cap = days(60)
    use_domains(monkeypatch, {"capped.example": ("ok", cap)})

    # A permanent link cannot simply be pointed at a domain with a known expiry.
    create(client, "https://open.example/", "DOM11")
    res = client.patch("/api/links/DOM11", json={"original_url": "https://capped.example/new"})
    assert res.status_code == 422
    assert "永久" in res.json()["detail"]

    # Nor can one whose own date overshoots it; shorten first, then move.
    create(client, "https://open.example/2", "DOM12", days(365))
    res = client.patch("/api/links/DOM12", json={"original_url": "https://capped.example/2"})
    assert res.status_code == 422
    assert client.patch("/api/links/DOM12", json={"expires_at": days(30).isoformat()}).status_code == 200
    res = client.patch("/api/links/DOM12", json={"original_url": "https://capped.example/2"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["domain_name"] == "capped.example"
    assert dt.datetime.fromisoformat(body["expires_at"]) == days(30)

    # Moving to a domain without a published expiry is always allowed.
    res = client.patch("/api/links/DOM12", json={"original_url": "https://open.example/back"})
    assert res.status_code == 200, res.text
    assert res.json()["domain_status"] == "unknown"


def test_lookup_endpoint(client: TestClient, monkeypatch):
    cap = days(365)
    use_domains(monkeypatch, {"example.org": ("ok", cap)})

    res = client.get("/api/domains/lookup", params={"url": "https://www.example.org/page"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "example.org"
    assert body["status"] == "ok"
    assert dt.datetime.fromisoformat(body["expires_at"]) == cap

    res = client.get("/api/domains/lookup", params={"url": "https://10.0.0.1/x"})
    assert res.status_code == 200
    assert res.json()["status"] == "not_applicable"

    assert client.get("/api/domains/lookup", params={"url": "not a url"}).status_code == 422


def test_export_includes_domain_columns(client: TestClient, monkeypatch):
    cap = days(365)
    use_domains(monkeypatch, {"csv.example": ("ok", cap)})
    create(client, "https://csv.example/", "DOM13", days(30))

    body = client.get("/api/links/export?status=all").content.decode("utf-8")
    assert "domain_name,domain_status,domain_expires_at,exceeds_domain_expiry" in body
    assert "csv.example,ok," in body
