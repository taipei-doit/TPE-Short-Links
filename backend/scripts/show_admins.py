"""Print the admin whitelist. Useful as a Cloud Run Job when the database is
not reachable from your network.

    gcloud run jobs update db-migrate --region=asia-east1 \
      --command=python --args=scripts/show_admins.py
    gcloud run jobs execute db-migrate --region=asia-east1 --wait

Emails are masked by default so they are not written to Cloud Logging in full;
pass --full when you actually need to read them.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_engine
from app.models import AdminUser


def mask(email: str) -> str:
    local, _, domain = email.partition("@")
    shown = local[:2] if len(local) > 2 else local[:1]
    return f"{shown}{'*' * max(len(local) - len(shown), 1)}@{domain}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="print unmasked email addresses")
    args = parser.parse_args()

    with Session(get_engine()) as db:
        rows = db.execute(select(AdminUser).order_by(AdminUser.email.asc())).scalars().all()

    print(f"ADMIN_COUNT={len(rows)}")
    for a in rows:
        shown = a.email if args.full else mask(a.email)
        print(f"  {shown}  name={a.name or '-'}  title={a.title or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
