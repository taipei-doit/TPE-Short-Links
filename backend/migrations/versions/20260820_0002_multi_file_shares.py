"""split shared_files into file_shares (the link) + shared_files (its files)

Revision ID: 20260820_0002
Revises: 20260820_0001
Create Date: 2026-08-20

A share link now holds any number of files, so the code, PIN, expiry and
lockout state move up to a parent row. Each file is uploaded in its own
request, which is also what lifts the total size of a share above the 32 MiB
Cloud Run caps a single request at.

Existing rows are carried over: every file that was its own share becomes a
share containing exactly one file, keeping its code, PIN and expiry.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260820_0002"
down_revision = "20260820_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_shares",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=32), nullable=False, unique=True),
        sa.Column("pin_hash", sa.String(length=255), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_by", sa.String(length=320), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.add_column("shared_files", sa.Column("share_id", sa.Integer(), nullable=True))

    # Carry existing single-file shares over. `id` is reused as the new parent
    # id so the mapping back to each file is unambiguous.
    op.execute(
        sa.text(
            """
            INSERT INTO file_shares (
                id, code, pin_hash, note, status, expires_at,
                failed_attempts, locked_until, uploaded_by, created_at, updated_at
            )
            SELECT
                id, code, pin_hash, note, status, expires_at,
                failed_attempts, locked_until, uploaded_by, created_at, updated_at
            FROM shared_files
            """
        )
    )
    op.execute(sa.text("UPDATE shared_files SET share_id = id"))

    # Postgres sequences do not follow explicit ids, so move it past what we
    # just inserted or the next share would collide.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "SELECT setval(pg_get_serial_sequence('file_shares', 'id'), "
                "COALESCE((SELECT MAX(id) FROM file_shares), 1))"
            )
        )

    op.alter_column("shared_files", "share_id", nullable=False)
    op.create_index("ix_shared_files_share_id", "shared_files", ["share_id"])
    op.create_foreign_key(
        "fk_shared_files_share_id",
        "shared_files",
        "file_shares",
        ["share_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Everything below now lives on the parent.
    for column in (
        "code",
        "pin_hash",
        "note",
        "expires_at",
        "failed_attempts",
        "locked_until",
        "uploaded_by",
        "updated_at",
    ):
        op.drop_column("shared_files", column)


def downgrade() -> None:
    op.add_column("shared_files", sa.Column("code", sa.String(length=32), nullable=True))
    op.add_column("shared_files", sa.Column("pin_hash", sa.String(length=255), nullable=True))
    op.add_column("shared_files", sa.Column("note", sa.Text(), nullable=True))
    op.add_column("shared_files", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "shared_files", sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("shared_files", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "shared_files", sa.Column("uploaded_by", sa.String(length=320), nullable=False, server_default="")
    )
    op.add_column(
        "shared_files",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Only the first file of each share can be represented in the old shape;
    # any additional files would have no code of their own.
    op.execute(
        sa.text(
            """
            UPDATE shared_files SET
                code = s.code,
                pin_hash = s.pin_hash,
                note = s.note,
                expires_at = s.expires_at,
                failed_attempts = s.failed_attempts,
                locked_until = s.locked_until,
                uploaded_by = s.uploaded_by,
                updated_at = s.updated_at
            FROM file_shares s
            WHERE shared_files.share_id = s.id
            """
        )
    )

    op.drop_constraint("fk_shared_files_share_id", "shared_files", type_="foreignkey")
    op.drop_index("ix_shared_files_share_id", table_name="shared_files")
    op.drop_column("shared_files", "share_id")
    op.drop_table("file_shares")
