"""record who holds a domain and flag suspected takeovers

Revision ID: 20260922_0002
Revises: 20260922_0001
Create Date: 2026-09-22

RDAP only says how long the current registration runs, not whether the
holder is still the agency. So the registration date (which a same-holder
renewal keeps and a takeover resets) is recorded, and a lookup that moves it
later -- or finds the domain gone -- parks its result in suspect_* until an
admin confirms.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260922_0002"
down_revision = "20260922_0001"
branch_labels = None
depends_on = None

_COLUMNS = [
    sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("registrar", sa.String(255), nullable=False, server_default=""),
    sa.Column("nameservers", sa.String(512), nullable=False, server_default=""),
    sa.Column("suspect", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    sa.Column("suspect_detail", sa.String(512), nullable=False, server_default=""),
    sa.Column("suspect_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("suspect_expires_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("suspect_registered_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("suspect_registrar", sa.String(255), nullable=False, server_default=""),
    sa.Column("suspect_nameservers", sa.String(512), nullable=False, server_default=""),
    sa.Column("suspect_dropped", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    sa.Column("confirmed_by", sa.String(320), nullable=False, server_default=""),
    sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
]


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column("domains", column)


def downgrade() -> None:
    for column in reversed(_COLUMNS):
        op.drop_column("domains", column.name)
