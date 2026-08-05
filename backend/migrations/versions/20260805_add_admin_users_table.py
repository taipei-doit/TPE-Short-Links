"""add admin_users table (admin whitelist moved from Firestore)

Revision ID: 20260805_0001
Revises: 20260130_0001
Create Date: 2026-08-05

The whitelist rows themselves are copied over by
`backend/scripts/migrate_admins_from_firestore.py`, which is run once against
production. This migration only creates the table so it stays reproducible on a
fresh database.
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

revision = "20260805_0001"
down_revision = "20260130_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_users",
        sa.Column("email", sa.String(length=320), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Bootstrap: seed from ADMIN_WHITELIST so a fresh deployment is never left
    # without a way in. Existing installs get their rows from the migration
    # script instead; ON CONFLICT keeps this idempotent either way.
    raw = os.environ.get("ADMIN_WHITELIST", "")
    emails = sorted({e.strip().lower() for e in raw.split(",") if e.strip()})
    if emails:
        op.execute(
            sa.text(
                "INSERT INTO admin_users (email) VALUES "
                + ", ".join(f"(:e{i})" for i in range(len(emails)))
                + " ON CONFLICT (email) DO NOTHING"
            ).bindparams(*[sa.bindparam(f"e{i}", emails[i]) for i in range(len(emails))])
        )


def downgrade() -> None:
    op.drop_table("admin_users")
