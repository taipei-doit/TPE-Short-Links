"""gate the public QR studio behind a per-link 4-digit PIN

Revision ID: 20260903_0001
Revises: 20260820_0003
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260903_0001"
down_revision = "20260820_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "short_links",
        sa.Column("qr_pin", sa.String(4), nullable=False, server_default="0000"),
    )
    op.add_column(
        "short_links",
        sa.Column("qr_pin_failed_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "short_links",
        sa.Column("qr_pin_locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    # Every existing link gets its own random PIN; "0000" must never survive.
    op.execute(
        sa.text(
            "UPDATE short_links SET qr_pin = lpad((floor(random() * 10000))::int::text, 4, '0')"
        )
    )


def downgrade() -> None:
    op.drop_column("short_links", "qr_pin_locked_until")
    op.drop_column("short_links", "qr_pin_failed_attempts")
    op.drop_column("short_links", "qr_pin")
