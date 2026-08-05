"""One-off: copy the admin whitelist from Firestore `admin_emails` into `admin_users`.

Run once against production while both stores still exist:

    cd backend
    # DATABASE_URL must point at the target database (Cloud SQL proxy is fine)
    .venv/Scripts/python scripts/migrate_admins_from_firestore.py --dry-run
    .venv/Scripts/python scripts/migrate_admins_from_firestore.py

Idempotent: existing rows are left untouched unless --overwrite is passed.
Firestore documents are never modified or deleted, so this can be re-run and
the old store stays available as a fallback until the switch is confirmed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.session import get_engine
from app.models import AdminUser

FIRESTORE_COLLECTION = "admin_emails"


def _normalize(rows: list[dict]) -> list[dict[str, str]]:
    out = [
        {
            "email": str(r.get("email") or "").strip().lower(),
            "name": str(r.get("name") or "").strip()[:100],
            "title": str(r.get("title") or "").strip()[:100],
        }
        for r in rows
    ]
    return sorted([r for r in out if r["email"]], key=lambda a: a["email"])


def fetch_firestore_admins() -> list[dict[str, str]]:
    """Read directly from Firestore (needs application default credentials)."""
    from google.cloud import firestore

    client = firestore.Client()
    rows = []
    for doc in client.collection(FIRESTORE_COLLECTION).stream():
        data = doc.to_dict() or {}
        rows.append({"email": doc.id, "name": data.get("name"), "title": data.get("title")})
    return _normalize(rows)


def load_admins_from_json(path: Path) -> list[dict[str, str]]:
    """Read from a JSON export - avoids needing GCP credentials on this machine."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        data = [data]
    return _normalize(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    parser.add_argument("--overwrite", action="store_true", help="also update name/title of existing rows")
    parser.add_argument(
        "--from-json",
        type=Path,
        help="read admins from a JSON export instead of querying Firestore",
    )
    args = parser.parse_args()

    admins = load_admins_from_json(args.from_json) if args.from_json else fetch_firestore_admins()
    if not admins:
        print("Source returned no admins - aborting so an empty whitelist is never written.")
        return 1

    print(f"Source admins: {len(admins)}")

    inserted = updated = skipped = 0
    with Session(get_engine()) as db:
        for a in admins:
            existing = db.get(AdminUser, a["email"])
            if existing is None:
                print(f"  + {a['email']}  name={a['name'] or '-'}  title={a['title'] or '-'}")
                if not args.dry_run:
                    db.add(AdminUser(email=a["email"], name=a["name"], title=a["title"]))
                inserted += 1
            elif args.overwrite:
                print(f"  ~ {a['email']} (overwrite name/title)")
                if not args.dry_run:
                    existing.name = a["name"]
                    existing.title = a["title"]
                updated += 1
            else:
                print(f"  = {a['email']} (already present, unchanged)")
                skipped += 1

        if args.dry_run:
            db.rollback()
            print(f"\nDRY RUN - nothing written. would insert {inserted}, update {updated}, skip {skipped}")
        else:
            db.commit()
            total = db.query(AdminUser).count()
            print(f"\nDone. inserted {inserted}, updated {updated}, skipped {skipped}. admin_users now has {total} rows.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
