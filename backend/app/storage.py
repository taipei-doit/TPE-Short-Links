"""Object storage for shared files.

Two backends behind one small interface:

- ``gcs``   Google Cloud Storage, used in production. Accessed server-side with
            the Cloud Run service account; the bucket stays private and is never
            reachable from a browser. No signed URLs are handed out, so the PIN
            gate is always the only way to the bytes.
- ``local`` A directory on disk, used by tests and local development.

Everything GCP-specific is confined to this file. Moving to S3 or Azure Blob
means adding a third class here and changing one setting -- nothing else in the
application touches a storage SDK.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, Protocol

from app.settings import get_settings

# Chunk size for streaming downloads. Large enough to keep syscall overhead
# down, small enough that many concurrent downloads do not blow up memory.
CHUNK_SIZE = 256 * 1024

# How much of a GCS object to hold in memory at once. Left to itself the client
# buffers 40 MiB per reader, which several concurrent large downloads would turn
# into an out-of-memory kill on a small container. Must be a multiple of 256 KiB.
GCS_READ_BUFFER = 8 * 1024 * 1024


class Storage(Protocol):
    def save(self, path: str, source: BinaryIO, content_type: str) -> None: ...

    def stream(self, path: str) -> Iterator[bytes]: ...

    def delete(self, path: str) -> None: ...

    def stat(self, path: str) -> tuple[int, str] | None:
        """Return (size_bytes, content_type), or None if the object is absent."""
        ...

    def create_upload_session(self, path: str, content_type: str, size: int, origin: str) -> str | None:
        """Return a URL the browser can upload straight to, or None.

        None means this backend has no such capability and the caller must fall
        back to sending the bytes through the application.
        """
        ...


class LocalStorage:
    """Filesystem-backed storage for tests and local development."""

    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def _full(self, path: str) -> Path:
        # Resolve and confine: a crafted path must not escape the root.
        full = (self.root / path).resolve()
        root = self.root.resolve()
        if not str(full).startswith(str(root)):
            raise ValueError("Invalid storage path")
        return full

    def save(self, path: str, source: BinaryIO, content_type: str) -> None:
        full = self._full(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        with open(full, "wb") as dest:
            shutil.copyfileobj(source, dest, CHUNK_SIZE)

    def stream(self, path: str) -> Iterator[bytes]:
        full = self._full(path)
        with open(full, "rb") as fh:
            while chunk := fh.read(CHUNK_SIZE):
                yield chunk

    def delete(self, path: str) -> None:
        full = self._full(path)
        if full.exists():
            full.unlink()

    def stat(self, path: str) -> tuple[int, str] | None:
        full = self._full(path)
        if not full.exists():
            return None
        return full.stat().st_size, "application/octet-stream"

    def create_upload_session(self, path: str, content_type: str, size: int, origin: str) -> str | None:
        # Local disk has no browser-reachable upload endpoint; callers fall
        # back to posting the bytes through the application.
        return None


class GcsStorage:
    """Google Cloud Storage backend."""

    def __init__(self, bucket_name: str) -> None:
        self.bucket_name = bucket_name
        self._bucket = None

    def _get_bucket(self):
        # Imported lazily so the app still starts (and tests still run) without
        # credentials or the storage SDK present.
        if self._bucket is None:
            from google.cloud import storage as gcs

            self._bucket = gcs.Client().bucket(self.bucket_name)
        return self._bucket

    def save(self, path: str, source: BinaryIO, content_type: str) -> None:
        blob = self._get_bucket().blob(path)
        blob.upload_from_file(source, content_type=content_type, rewind=True)

    def stream(self, path: str) -> Iterator[bytes]:
        blob = self._get_bucket().blob(path)
        with blob.open("rb", chunk_size=GCS_READ_BUFFER) as fh:
            while chunk := fh.read(CHUNK_SIZE):
                yield chunk

    def delete(self, path: str) -> None:
        from google.api_core import exceptions as gcp_exceptions

        blob = self._get_bucket().blob(path)
        try:
            blob.delete()
        except gcp_exceptions.NotFound:
            # The row is the source of truth; an object already gone (e.g. a
            # previous partial delete) still counts as deleted.
            pass

    def stat(self, path: str) -> tuple[int, str] | None:
        blob = self._get_bucket().get_blob(path)
        if blob is None:
            return None
        return int(blob.size or 0), blob.content_type or "application/octet-stream"

    def create_upload_session(self, path: str, content_type: str, size: int, origin: str) -> str | None:
        """Open a GCS resumable upload session for the browser to PUT into.

        Cloud Run refuses request bodies over 32 MiB at the edge, so anything
        larger can never be proxied through this service. The session URI is a
        capability for exactly one object name and nothing else; it is only
        ever handed to an authenticated admin, and the resulting object is
        checked (and its real size recorded) before it is attached to a share.

        This needs no signing key -- the session is opened with the service
        account's own credentials, which is why it works on Cloud Run's default
        identity.
        """
        blob = self._get_bucket().blob(path)
        return blob.create_resumable_upload_session(
            content_type=content_type,
            size=size,
            origin=origin,
        )


_storage: Storage | None = None


def get_storage() -> Storage:
    """Return the configured storage backend (GCS when a bucket is set)."""
    global _storage
    if _storage is None:
        settings = get_settings()
        if settings.FILE_STORAGE_BUCKET:
            _storage = GcsStorage(settings.FILE_STORAGE_BUCKET)
        else:
            root = settings.FILE_STORAGE_LOCAL_DIR or os.path.join(os.getcwd(), "var", "shared-files")
            _storage = LocalStorage(root)
    return _storage


def reset_storage() -> None:
    """Drop the cached backend. Used by tests."""
    global _storage
    _storage = None
