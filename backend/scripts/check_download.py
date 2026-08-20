"""Download the largest shared file through the public URL and check it arrives.

Cloud Run applies a 32 MiB ceiling to fixed-length responses, so a large file
can upload perfectly and still fail to download. Storage-level checks cannot
catch that -- only a real request through the public edge can. This mints its
own download token using the service's own secret, so it needs no PIN and
exposes nothing.

    gcloud run jobs update db-migrate --region=asia-east1 \
      --command=python --args=scripts/check_download.py
    gcloud run jobs execute db-migrate --region=asia-east1 --wait

Reads only; nothing is modified beyond the file's download counter.
"""

from __future__ import annotations

import argparse
import sys

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_engine
from app.files import make_download_token
from app.models import FileShare, SharedFile
from app.settings import get_settings


def check_archive(code: str | None) -> int:
    """Pull a whole share as one zip and confirm the archive is intact.

    The "download all" button is a single streamed response built on the fly,
    so this is the only way to know it survives the trip through the edge.
    """
    import io
    import zipfile

    settings = get_settings()
    base = settings.PUBLIC_BASE_URL.rstrip("/")

    with Session(get_engine()) as db:
        query = select(FileShare).where(FileShare.status == "active")
        if code:
            query = query.where(FileShare.code == code)
        share = db.execute(query.order_by(FileShare.created_at.desc())).scalars().first()
        if share is None:
            print("NO_SHARES=1 (nothing to check)")
            return 0
        expected = [(f.filename, f.size_bytes) for f in share.files if f.status == "active"]
        share_code = share.code

    if not expected:
        print(f"SHARE {share_code} has no files")
        return 0

    print(f"CHECKING archive for code={share_code}, {len(expected)} files")
    token = make_download_token(share_code, 600)
    url = f"{base}/f/{share_code}/download-all?token={token}"

    buffer = io.BytesIO()
    try:
        with requests.get(url, stream=True, timeout=900) as response:
            print(f"HTTP {response.status_code}")
            print(f"  content-type: {response.headers.get('Content-Type')}")
            print(f"  transfer-encoding: {response.headers.get('Transfer-Encoding', '(none)')}")
            if response.status_code != 200:
                print(f"  body: {response.text[:300]}")
                return 1
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                buffer.write(chunk)
    except Exception as e:  # noqa: BLE001 - this check exists to report failures
        print(f"ARCHIVE FAILED after {buffer.tell()} bytes: {type(e).__name__}: {e}")
        return 1

    print(f"ARCHIVE_BYTES={buffer.tell()}")
    buffer.seek(0)
    try:
        with zipfile.ZipFile(buffer) as archive:
            bad = archive.testzip()
            if bad is not None:
                print(f"ARCHIVE CORRUPT at {bad}")
                return 1
            sizes = {info.filename: info.file_size for info in archive.infolist()}
    except zipfile.BadZipFile as e:
        print(f"ARCHIVE UNREADABLE: {e}")
        return 1

    print(f"  entries: {list(sizes)}")
    for name, size in expected:
        if sizes.get(name) != size:
            print(f"  MISMATCH {name}: expected {size}, archive has {sizes.get(name)}")
            return 1
    print("ARCHIVE_CHECK=pass")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", help="check this share instead of the largest file overall")
    parser.add_argument(
        "--archive",
        action="store_true",
        help="pull the whole share as one zip instead of a single file",
    )
    args = parser.parse_args()

    if args.archive:
        return check_archive(args.code)

    settings = get_settings()
    base = settings.PUBLIC_BASE_URL.rstrip("/")

    with Session(get_engine()) as db:
        query = (
            select(SharedFile, FileShare.code)
            .join(FileShare, FileShare.id == SharedFile.share_id)
            .where(SharedFile.status == "active", FileShare.status == "active")
            .order_by(SharedFile.size_bytes.desc())
        )
        if args.code:
            query = query.where(FileShare.code == args.code)
        row = db.execute(query).first()

    if row is None:
        print("NO_FILES=1 (nothing to check)")
        return 0

    record, code = row
    print(f"CHECKING code={code} file_id={record.id} name={record.filename} size={record.size_bytes}")

    token = make_download_token(code, 300)
    url = f"{base}/f/{code}/download/{record.id}?token={token}"

    received = 0
    try:
        with requests.get(url, stream=True, timeout=900) as response:
            print(f"HTTP {response.status_code}")
            print(f"  content-length: {response.headers.get('Content-Length', '(absent, chunked)')}")
            print(f"  transfer-encoding: {response.headers.get('Transfer-Encoding', '(none)')}")
            if response.status_code != 200:
                print(f"  body: {response.text[:300]}")
                return 1
            for chunk in response.iter_content(chunk_size=256 * 1024):
                received += len(chunk)
    except Exception as e:  # noqa: BLE001 - this check exists to report failures
        print(f"DOWNLOAD FAILED after {received} bytes: {type(e).__name__}: {e}")
        return 1

    print(f"RECEIVED={received} EXPECTED={record.size_bytes}")
    if received != record.size_bytes:
        print("DOWNLOAD_CHECK=fail (size mismatch)")
        return 1
    print("DOWNLOAD_CHECK=pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
