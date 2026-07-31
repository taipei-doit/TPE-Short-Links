from __future__ import annotations

import os
from typing import Generator
from urllib.parse import parse_qs, unquote, urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.settings import get_settings

_engine = None
_SessionLocal = None
_connector = None


def get_engine():
    global _engine, _SessionLocal, _connector
    if _engine is None:
        settings = get_settings()
        db_url = settings.DATABASE_URL

        # Check for Cloud SQL connection via env var or URL pattern
        cloud_sql_connection = os.environ.get("CLOUD_SQL_CONNECTION_NAME", "")

        # Also try to extract from DATABASE_URL if not set explicitly
        if not cloud_sql_connection and "cloudsql" in db_url.lower():
            # Try to parse from URL - handle both encoded and non-encoded
            decoded_url = unquote(db_url)
            if "?host=/cloudsql/" in decoded_url:
                parsed = urlparse(decoded_url)
                query_params = parse_qs(parsed.query)
                if "host" in query_params:
                    socket_path = query_params["host"][0]
                    if socket_path.startswith("/cloudsql/"):
                        cloud_sql_connection = socket_path[len("/cloudsql/"):]

        if cloud_sql_connection:
            # Use Cloud SQL Python Connector
            from google.cloud.sql.connector import Connector

            # Parse credentials from URL
            decoded_url = unquote(db_url)
            parsed = urlparse(decoded_url.split("?")[0])  # Remove query string
            db_user = parsed.username or ""
            db_pass = parsed.password or ""
            db_name = parsed.path.lstrip("/").split("?")[0] if parsed.path else ""

            _connector = Connector()

            def getconn():
                return _connector.connect(
                    cloud_sql_connection,
                    "pg8000",
                    user=db_user,
                    password=db_pass,
                    db=db_name,
                )

            _engine = create_engine(
                "postgresql+pg8000://",
                creator=getconn,
                pool_pre_ping=True,
            )
        else:
            # Standard connection (local development)
            _engine = create_engine(db_url, pool_pre_ping=True)

        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return _engine


def get_db() -> Generator[Session, None, None]:
    global _SessionLocal
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
