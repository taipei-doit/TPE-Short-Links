"""add enabled flag to blocked_words and reseed new words

Revision ID: 20260908_0002
Revises: 20260908_0001
Create Date: 2026-09-08

"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "20260908_0002"
down_revision = "20260908_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 每個字詞可個別停用（保留在清單、不參與代碼比對）。
    op.add_column(
        "blocked_words",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    # 以檔案重新種入（冪等），撿起新加入的字詞。
    blocked_words_file = Path(__file__).parent.parent.parent / "app" / "blocked_words.txt"
    if blocked_words_file.exists():
        words = []
        with open(blocked_words_file, "r", encoding="utf-8") as f:
            for line in f:
                word = line.strip().lower()
                if word and len(word) <= 6 and word.isalnum():
                    words.append(word)

        batch_size = 500
        for i in range(0, len(words), batch_size):
            batch = words[i : i + batch_size]
            values = ", ".join([f"('{w}')" for w in batch])
            op.execute(
                sa.text(f"INSERT INTO blocked_words (word) VALUES {values} ON CONFLICT (word) DO NOTHING")
            )


def downgrade() -> None:
    op.drop_column("blocked_words", "enabled")
