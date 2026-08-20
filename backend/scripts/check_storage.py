"""Verify the shared-file storage backend really works.

Writes a small object, streams it back, compares the bytes, then deletes it.
This exercises the exact code path an upload and a download take, so it catches
a missing bucket, a missing IAM binding or a misconfigured backend before a
user hits it.

Run as a Cloud Run Job so it uses the service's own identity and network:

    gcloud run jobs update db-migrate --region=asia-east1 \
      --command=python --args=scripts/check_storage.py
    gcloud run jobs execute db-migrate --region=asia-east1 --wait

Safe to run against production: it only touches its own throwaway object under
a `_healthcheck/` prefix.
"""

from __future__ import annotations

import secrets
import sys

from app.settings import get_settings
from app.storage import get_storage


def main() -> int:
    settings = get_settings()
    backend = "gcs" if settings.FILE_STORAGE_BUCKET else "local"
    print(f"BACKEND={backend} BUCKET={settings.FILE_STORAGE_BUCKET or '(local disk)'}")

    storage = get_storage()
    path = f"{settings.FILE_STORAGE_PREFIX.strip('/')}/_healthcheck/{secrets.token_hex(8)}"
    payload = b"tpe-short-links storage healthcheck " + secrets.token_bytes(32)

    try:
        import io

        storage.save(path, io.BytesIO(payload), "application/octet-stream")
        print(f"WRITE ok ({len(payload)} bytes) -> {path}")

        received = b"".join(storage.stream(path))
        if received != payload:
            print(f"READ MISMATCH: expected {len(payload)} bytes, got {len(received)}")
            return 1
        print("READ ok, bytes match")

        stat = storage.stat(path)
        print(f"STAT ok: {stat}")
    finally:
        try:
            storage.delete(path)
            print("DELETE ok")
        except Exception as e:  # noqa: BLE001 - report, don't mask an earlier failure
            print(f"DELETE FAILED: {e}")

    # The browser-direct route is what carries anything Cloud Run would refuse,
    # so prove it end to end rather than assuming the SDK call is enough.
    resumable_path = f"{settings.FILE_STORAGE_PREFIX.strip('/')}/_healthcheck/{secrets.token_hex(8)}"
    resumable_payload = b"resumable " + secrets.token_bytes(32)
    try:
        session_url = storage.create_upload_session(
            resumable_path, "application/octet-stream", len(resumable_payload), "https://admin.url.taipei"
        )
        if not session_url:
            print("RESUMABLE unavailable on this backend (expected for local disk)")
        else:
            import urllib.request

            request = urllib.request.Request(
                session_url,
                data=resumable_payload,
                method="PUT",
                headers={"Content-Type": "application/octet-stream"},
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                print(f"RESUMABLE PUT ok, HTTP {response.status}")

            back = b"".join(storage.stream(resumable_path))
            if back != resumable_payload:
                print("RESUMABLE MISMATCH")
                return 1
            print(f"RESUMABLE read-back ok, {len(back)} bytes match")
    except Exception as e:  # noqa: BLE001 - this check exists to report failures
        print(f"RESUMABLE FAILED: {type(e).__name__}: {e}")
        return 1
    finally:
        try:
            storage.delete(resumable_path)
        except Exception:  # noqa: BLE001
            pass

    print("STORAGE_HEALTHCHECK=pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
