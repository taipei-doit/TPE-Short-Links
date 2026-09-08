"""expand blocked_words.word to 6 chars and reseed from blocked_words.txt

Revision ID: 20260908_0001
Revises: 20260903_0001
Create Date: 2026-09-08

"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "20260908_0001"
down_revision = "20260903_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 檔案分享代碼為 6 碼，封鎖字詞須涵蓋 5-6 字元才有意義。
    op.alter_column(
        "blocked_words",
        "word",
        type_=sa.String(length=6),
        existing_type=sa.String(length=4),
        existing_nullable=False,
    )

    # 以檔案重新種入（冪等）：撿起新加入的 1-6 字元字詞，既有列不受影響。
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
    op.execute(sa.text("DELETE FROM blocked_words WHERE length(word) > 4"))
    op.alter_column(
        "blocked_words",
        "word",
        type_=sa.String(length=4),
        existing_type=sa.String(length=6),
        existing_nullable=False,
    )
