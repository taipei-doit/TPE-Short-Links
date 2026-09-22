from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import ReservedCode, Tag


@pytest.fixture()
def db_session() -> Session:
    # Use StaticPool so the in-memory DB persists across connections/threads (TestClient uses threads).
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()

    # Seed required tag + a reserved code for tests.
    db.add(Tag(id=1, name="General", is_active=True, created_at=dt.datetime.now(dt.UTC)))
    db.add(ReservedCode(code="reserved", reason="test", type="reserved", created_at=dt.datetime.now(dt.UTC)))
    db.commit()

    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def no_rdap_network(monkeypatch):
    """Tests never reach RDAP servers. Default answer: registry publishes
    nothing (status "unknown"), so no link lifetime is capped unless a test
    installs its own fake via tests/test_domains.py::use_domains."""
    import app.domains as domains_mod
    import app.main as main_mod

    def fake(host: str | None) -> domains_mod.DomainLookup:
        name = domains_mod.registrable_domain(host)
        if name is None:
            return domains_mod.DomainLookup(name=None, status="not_applicable", detail="stub")
        return domains_mod.DomainLookup(name=name, status="unknown", detail="stub")

    monkeypatch.setattr(main_mod, "lookup_domain", fake)
    monkeypatch.setattr(domains_mod, "lookup_domain", fake)


@pytest.fixture()
def client(db_session: Session) -> TestClient:
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

