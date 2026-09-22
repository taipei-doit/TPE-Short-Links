"""Re-check domain registration expiries.

A short link may not be set to outlive its target domain's registration (see
app/domains.py). The check only guards input: no link's expiry is ever moved
by a lookup. This script keeps the recorded caps current in bulk -- so the
management page shows fresh dates and renewed domains stop blocking longer
expiries -- and records the domain of links created before the check existed.

It never accepts a change of holder on its own: a later registration date or
a domain gone from the registry is parked as "suspect" (printed here, red in
the admin UI) until an admin confirms it. Same-holder renewals apply directly.

Run as a Cloud Run Job (the Cloud SQL instance is not reachable from the
office network), e.g. daily alongside purge-expired-files:

    gcloud run jobs execute refresh-domains --region=asia-east1 --wait

Options:
  --backfill        record the domain of links that have none yet (network
                    lookups: one per distinct domain)
  --due-days N      refresh domains expiring within N days, or last checked
                    more than N days ago (default 60)
  --all             refresh every domain regardless of dates
  --dry-run         report only, change nothing
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from urllib.parse import urlparse

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.session import get_engine
from app.domains import registrable_domain
from app.main import as_utc, count_links_over_cap, ensure_domain
from app.models import Domain, ShortLink


def backfill(db: Session, *, dry_run: bool) -> int:
    """Attach a domain to every link that predates domain checks."""
    links = db.execute(select(ShortLink).where(ShortLink.domain_name.is_(None))).scalars().all()
    touched = 0
    for link in links:
        name = registrable_domain(urlparse(link.original_url).hostname)
        if name is None:
            continue
        print(f"  backfill {link.code} -> {name}")
        touched += 1
        if dry_run:
            continue
        ensure_domain(db, link.original_url)  # cached per domain within the run
        link.domain_name = name
        db.add(link)
    if not dry_run:
        db.commit()
    return touched


def refresh(db: Session, *, due_days: int, everything: bool, dry_run: bool) -> tuple[int, int]:
    """Re-query due domains. Returns (domains refreshed, links now over their cap)."""
    now = dt.datetime.now(dt.UTC)
    stmt = select(Domain)
    if not everything:
        stmt = stmt.where(
            or_(
                Domain.checked_at.is_(None),
                Domain.checked_at <= now - dt.timedelta(days=due_days),
                Domain.expires_at <= now + dt.timedelta(days=due_days),
                # Rows from before the takeover guard have no identity anchor yet.
                and_(Domain.status == "ok", Domain.registered_at.is_(None)),
            )
        )
    domains = db.execute(stmt.order_by(Domain.name)).scalars().all()
    print(f"DUE_DOMAINS={len(domains)} due_days={due_days} all={everything} dry_run={dry_run}")

    refreshed = 0
    over_cap = 0
    for domain in domains:
        before = (domain.status, as_utc(domain.expires_at))
        if dry_run:
            print(f"  would refresh {domain.name} (status={before[0]} expires={before[1]})")
            continue
        # Any link on the domain carries a URL to look up with.
        link = db.execute(select(ShortLink).where(ShortLink.domain_name == domain.name)).scalars().first()
        url = link.original_url if link is not None else f"https://{domain.name}/"
        ensure_domain(db, url, force=True)
        db.commit()
        refreshed += 1
        over = count_links_over_cap(db, domain)
        over_cap += over
        print(
            f"  {domain.name}: {before[0]} {before[1]} -> {domain.status} {as_utc(domain.expires_at)}"
            + (f"  WARNING {over} link(s) outlive the registration" if over else "")
            + (f"  SUSPECT {domain.suspect_detail}" if domain.suspect else "")
        )
    return refreshed, over_cap


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backfill", action="store_true", help="record the domain of links that have none yet")
    parser.add_argument("--due-days", type=int, default=60, help="refresh domains expiring or unchecked within N days")
    parser.add_argument("--all", action="store_true", help="refresh every domain")
    parser.add_argument("--dry-run", action="store_true", help="report only, change nothing")
    args = parser.parse_args()

    with Session(get_engine()) as db:
        backfilled = backfill(db, dry_run=args.dry_run) if args.backfill else 0
        refreshed, over_cap = refresh(db, due_days=args.due_days, everything=args.all, dry_run=args.dry_run)

    print(f"BACKFILLED={backfilled} REFRESHED={refreshed} LINKS_OVER_CAP={over_cap}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
