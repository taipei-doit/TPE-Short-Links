"""let admins order the files within a share

Revision ID: 20260820_0003
Revises: 20260820_0002
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260820_0003"
down_revision = "20260820_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shared_files",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    # Seed the existing order so the first reorder has something to move around
    # rather than every file claiming position 0.
    op.execute(
        sa.text(
            """
            UPDATE shared_files SET sort_order = ranked.position
            FROM (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY share_id ORDER BY id) AS position
                FROM shared_files
            ) AS ranked
            WHERE shared_files.id = ranked.id
            """
        )
    )
    op.create_index(
        "ix_shared_files_share_id_sort_order", "shared_files", ["share_id", "sort_order"]
    )


def downgrade() -> None:
    op.drop_index("ix_shared_files_share_id_sort_order", table_name="shared_files")
    op.drop_column("shared_files", "sort_order")
