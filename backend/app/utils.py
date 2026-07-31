from __future__ import annotations

import datetime as dt
import secrets
import string
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException

ALPHABET = string.ascii_letters + string.digits  # A-Z a-z 0-9

# Load blocked words from text file
_BLOCKED_WORDS_FILE = Path(__file__).parent / "blocked_words.txt"
_TAGS_FILE = Path(__file__).parent / "tags.txt"


@lru_cache(maxsize=1)
def _load_blocked_words() -> set[str]:
    """Load blocked words from text file (cached)."""
    if not _BLOCKED_WORDS_FILE.exists():
        raise FileNotFoundError(f"Blocked words file not found: {_BLOCKED_WORDS_FILE}")
    words = set()
    with open(_BLOCKED_WORDS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            word = line.strip().lower()
            if word and len(word) <= 4:
                words.add(word)
    return words


def load_blocked_words() -> set[str]:
    """Public wrapper for loading blocked words."""
    return _load_blocked_words()


@lru_cache(maxsize=1)
def load_seed_tags() -> list[str]:
    """Load desired tag names from text file (cached).

    - One tag name per line
    - Empty lines are ignored
    - Lines starting with '#' are treated as comments
    - Names are trimmed; max length 64 (longer lines are ignored)
    - Duplicates are removed (case-sensitive) while preserving order
    """
    if not _TAGS_FILE.exists():
        return []

    seen: set[str] = set()
    out: list[str] = []
    with open(_TAGS_FILE, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if len(line) > 64:
                continue
            if line in seen:
                continue
            seen.add(line)
            out.append(line)
    return out


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def validate_original_url(url: str, *, allow_http: bool) -> None:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(status_code=422, detail="original_url must be an absolute URL")
    if parsed.scheme not in ("https", "http"):
        raise HTTPException(status_code=422, detail="original_url must be http(s)")
    if parsed.scheme == "http" and not allow_http:
        raise HTTPException(status_code=422, detail="http:// URLs are not allowed")


def validate_expires_at(expires_at: dt.datetime | None) -> None:
    if expires_at is None:
        return
    if expires_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="expires_at must be timezone-aware")
    if expires_at <= now_utc():
        raise HTTPException(status_code=422, detail="expires_at must be in the future")


def is_english_word(code: str) -> bool:
    """Check if code contains any blocked word (3-4 chars) as a substring (case-insensitive).
    
    DEPRECATED: This function uses file-based blocked words.
    Use is_blocked_word_db() instead for database-based checking.
    
    Words of length 1-2 are allowed to appear in codes, only 3-4 character words block.
    """
    code_lower = code.lower()
    blocked_words = _load_blocked_words()
    # Only block if code contains a blocked word of length 3-4 (allow 1-2 char words)
    return any(word in code_lower for word in blocked_words if len(word) >= 3)


def generate_code(length: int) -> str:
    """Generate a random code of exactly the specified length.
    
    Note: Blocked word checking should be done separately using the database.
    """
    return "".join(secrets.choice(ALPHABET) for _ in range(length))

