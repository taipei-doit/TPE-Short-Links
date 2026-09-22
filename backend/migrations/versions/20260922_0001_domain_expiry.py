"""cap link lifetimes at the target domain's registration expiry

Revision ID: 20260922_0001
Revises: 20260908_0002
Create Date: 2026-09-22

Adds the `domains` table (one RDAP record per registrable domain) and links
each short link to it. Existing links are left with domain_name NULL: the
lookups need the network and can take seconds each, so they run from
`scripts/refresh_domains.py --backfill` rather than inside this migration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260922_0001"
down_revision = "20260908_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "domains",
        sa.Column("name", sa.String(253), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail", sa.String(255), nullable=False, server_default=""),
        sa.Column("source", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("short_links", sa.Column("domain_name", sa.String(253), nullable=True))
    op.create_index("ix_short_links_domain_name", "short_links", ["domain_name"])


def downgrade() -> None:
    op.drop_index("ix_short_links_domain_name", table_name="short_links")
    op.drop_column("short_links", "domain_name")
    op.drop_table("domains")
