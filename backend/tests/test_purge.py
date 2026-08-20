"""Tests for the scheduled cleanup of expired shares.

The sweep runs unattended once a day, so a mistake in it is invisible until
someone goes looking. It once queried a column that had moved to another table
and failed on every run for weeks; these tests exist so that cannot recur.
"""

from __future__ import annotations

import datetime as dt
import io
import sys
from pathlib import Path

import pytest

from app import storage as storage_mod
from app.models import FileShare, SharedFile
from app.settings import get_settings

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.purge_expired_files import purge  # noqa: E402


@pytest.fixture()
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv("FILE_STORAGE_BUCKET", "")
    monkeypatch.setenv("FILE_STORAGE_LOCAL_DIR", str(tmp_path / "shared-files"))
    get_settings.cache_clear()
    storage_mod.reset_storage()
    yield storage_mod.get_storage()
    get_settings.cache_clear()
    storage_mod.reset_storage()


def make_share(db, storage, *, code, expires_at, filenames=("a.pdf", "b.pdf")):
    share = FileShare(code=code, pin_hash="x", status="active", expires_at=expires_at)
    db.add(share)
    db.flush()
    for index, name in enumerate(filenames, start=1):
        path = f"shared-files/{code}/{name}"
        storage.save(path, io.BytesIO(name.encode()), "application/octet-stream")
        db.add(
            SharedFile(
                share_id=share.id,
                filename=name,
                content_type="application/octet-stream",
                size_bytes=len(name),
                storage_path=path,
                status="active",
                sort_order=index,
            )
        )
    db.commit()
    return share


def test_expired_shares_are_erased(db_session, storage):
    now = dt.datetime.now(dt.UTC)
    expired = make_share(db_session, storage, code="OLD001", expires_at=now - dt.timedelta(days=40))
    live = make_share(db_session, storage, code="NEW001", expires_at=now + dt.timedelta(days=5))
    forever = make_share(db_session, storage, code="FOREVR", expires_at=None)

    purged, failed = purge(db_session, storage, now - dt.timedelta(days=30), dry_run=False)
    assert (purged, failed) == (2, 0)

    db_session.refresh(expired)
    assert expired.status == "deleted"
    assert all(f.status == "deleted" for f in expired.files)
    assert not any(storage._full(f.storage_path).exists() for f in expired.files)

    # Everything else is untouched.
    for share in (live, forever):
        db_session.refresh(share)
        assert share.status == "active"
        assert all(storage._full(f.storage_path).exists() for f in share.files)


def test_grace_period_is_respected(db_session, storage):
    now = dt.datetime.now(dt.UTC)
    recent = make_share(db_session, storage, code="RCNT01", expires_at=now - dt.timedelta(days=5))

    # Expired, but not yet past the 30-day grace window.
    purged, failed = purge(db_session, storage, now - dt.timedelta(days=30), dry_run=False)
    assert (purged, failed) == (0, 0)
    db_session.refresh(recent)
    assert recent.status == "active"
    assert all(storage._full(f.storage_path).exists() for f in recent.files)


def test_dry_run_changes_nothing(db_session, storage):
    now = dt.datetime.now(dt.UTC)
    share = make_share(db_session, storage, code="DRY001", expires_at=now - dt.timedelta(days=40))

    purged, failed = purge(db_session, storage, now, dry_run=True)
    assert (purged, failed) == (0, 0)

    db_session.refresh(share)
    assert share.status == "active"
    assert all(storage._full(f.storage_path).exists() for f in share.files)


def test_already_deleted_shares_are_skipped(db_session, storage):
    now = dt.datetime.now(dt.UTC)
    share = make_share(db_session, storage, code="GONE01", expires_at=now - dt.timedelta(days=40))
    share.status = "deleted"
    db_session.commit()

    purged, failed = purge(db_session, storage, now, dry_run=False)
    assert (purged, failed) == (0, 0)


def test_a_failing_object_leaves_the_share_open_for_a_retry(db_session, storage):
    """A partial failure must not mark the share done.

    Otherwise the files that could not be erased would never be attempted
    again, and would sit in the bucket indefinitely.
    """
    now = dt.datetime.now(dt.UTC)
    share = make_share(db_session, storage, code="HALF01", expires_at=now - dt.timedelta(days=40))

    class OneBadObject:
        def __init__(self, inner, doomed):
            self.inner = inner
            self.doomed = doomed

        def delete(self, path):
            if path.endswith(self.doomed):
                raise RuntimeError("storage is having a bad day")
            self.inner.delete(path)

    purged, failed = purge(db_session, storage, now, dry_run=False)  # sanity: normally clean
    assert (purged, failed) == (2, 0)

    # Now the same scenario with one object refusing to go.
    share2 = make_share(db_session, storage, code="HALF02", expires_at=now - dt.timedelta(days=40))
    purged, failed = purge(db_session, OneBadObject(storage, "b.pdf"), now, dry_run=False)
    assert (purged, failed) == (1, 1)

    db_session.refresh(share2)
    assert share2.status == "active", "share must stay open so the next run retries it"
    assert share.status == "deleted"
