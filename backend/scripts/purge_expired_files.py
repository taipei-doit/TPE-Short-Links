"""Erase the stored bytes of shared files that are past their expiry.

Expiry only makes a share link unreachable -- the object itself stays in the
bucket. For files that may hold sensitive material, "unreachable" is not the
same as "gone", so this sweeps them for real. The database row survives with
status=deleted so the audit trail is intact and the code is never reused.

Run as a Cloud Run Job (the Cloud SQL instance is not reachable from the
office network):

    gcloud run jobs update db-migrate --region=asia-east1 \
      --command=python --args=scripts/purge_expired_files.py
    gcloud run jobs execute db-migrate --region=asia-east1 --wait

Add --grace-days N to keep files for a while after they expire, and
--dry-run to see what would be removed without touching anything.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_engine
from app.models import SharedFile
from app.storage import get_storage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--grace-days",
        type=int,
        default=0,
        help="keep expired files for this many extra days before erasing",
    )
    parser.add_argument("--dry-run", action="store_true", help="report only, change nothing")
    args = parser.parse_args()

    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=args.grace_days)
    storage = get_storage()

    with Session(get_engine()) as db:
        rows = (
            db.execute(
                select(SharedFile).where(
                    SharedFile.status != "deleted",
                    SharedFile.expires_at.is_not(None),
                    SharedFile.expires_at <= cutoff,
                )
            )
            .scalars()
            .all()
        )

        print(f"EXPIRED_FILES={len(rows)} cutoff={cutoff.isoformat()} dry_run={args.dry_run}")
        purged = 0
        failed = 0

        for record in rows:
            label = f"{record.code} ({record.size_bytes} bytes, expired {record.expires_at})"
            if args.dry_run:
                print(f"  would purge {label}")
                continue
            try:
                storage.delete(record.storage_path)
            except Exception as e:  # noqa: BLE001 - one bad object must not stop the sweep
                failed += 1
                print(f"  FAILED {label}: {e}")
                continue
            record.status = "deleted"
            record.updated_at = dt.datetime.now(dt.UTC)
            db.add(record)
            purged += 1
            print(f"  purged {label}")

        if not args.dry_run:
            db.commit()

    print(f"PURGED={purged} FAILED={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
