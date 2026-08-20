"""Erase the stored bytes of shares that are past their expiry.

Expiry only makes a share link unreachable -- the objects themselves stay in
the bucket. For files that may hold sensitive material, "unreachable" is not
the same as "gone", so this sweeps them for real. The rows survive with
status=deleted so the audit trail is intact and codes are never reused.

Run as a Cloud Run Job (the Cloud SQL instance is not reachable from the
office network); `purge-expired-files` is scheduled daily:

    gcloud run jobs execute purge-expired-files --region=asia-east1 --wait

Add --grace-days N to keep shares for a while after they expire, and
--dry-run to see what would be removed without touching anything.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_engine
from app.models import FileShare
from app.storage import get_storage


def purge(db: Session, storage, cutoff: dt.datetime, *, dry_run: bool) -> tuple[int, int]:
    """Erase the files of every share that expired on or before `cutoff`.

    Split out of main() so it can be tested. An earlier version queried a
    column that had since moved to another table, and because nothing exercised
    it, the scheduled sweep failed silently for weeks.

    Returns (files purged, failures).
    """
    # Expiry lives on the share, and every file it holds goes with it.
    shares = (
        db.execute(
            select(FileShare)
            .options(selectinload(FileShare.files))
            .where(
                FileShare.status != "deleted",
                FileShare.expires_at.is_not(None),
                FileShare.expires_at <= cutoff,
            )
        )
        .scalars()
        .all()
    )

    pending = [(s, [f for f in s.files if f.status == "active"]) for s in shares]
    print(
        f"EXPIRED_SHARES={len(shares)} "
        f"EXPIRED_FILES={sum(len(files) for _, files in pending)} "
        f"cutoff={cutoff.isoformat()} dry_run={dry_run}"
    )

    purged = 0
    failed = 0

    for share, files in pending:
        label = f"{share.code} ({len(files)} files, expired {share.expires_at})"
        if dry_run:
            print(f"  would purge {label}")
            continue

        share_failed = False
        for record in files:
            try:
                storage.delete(record.storage_path)
            except Exception as e:  # noqa: BLE001 - one bad object must not stop the sweep
                failed += 1
                share_failed = True
                print(f"  FAILED {share.code}/{record.filename}: {e}")
                continue
            record.status = "deleted"
            db.add(record)
            purged += 1

        # Only close the share once every one of its files is really gone, so a
        # partial failure is retried on the next run instead of being buried.
        if not share_failed:
            share.status = "deleted"
            share.updated_at = dt.datetime.now(dt.UTC)
            db.add(share)
            print(f"  purged {label}")

    if not dry_run:
        db.commit()

    return purged, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--grace-days",
        type=int,
        default=0,
        help="keep expired shares for this many extra days before erasing",
    )
    parser.add_argument("--dry-run", action="store_true", help="report only, change nothing")
    args = parser.parse_args()

    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=args.grace_days)

    with Session(get_engine()) as db:
        purged, failed = purge(db, get_storage(), cutoff, dry_run=args.dry_run)

    print(f"PURGED={purged} FAILED={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
