"""PIN generation, hashing and verification for shared files.

PINs are 8 characters of mixed letters and digits. They are normalised to
upper case, and generated from an alphabet with the visually ambiguous
characters removed (no O/0, no I/1/l), because these get read aloud, typed on
phones and pasted out of chat messages.

Stored as PBKDF2-HMAC-SHA256 so a database dump does not hand over the files.
The verification cost (~100ms) doubles as a natural throttle on guessing; the
per-file lockout in the API is the real defence.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

PIN_LENGTH = 8

# Ambiguous characters removed: O, I, 0, 1.
PIN_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
PIN_DIGITS = "23456789"
PIN_ALPHABET = PIN_LETTERS + PIN_DIGITS

_PBKDF2_ITERATIONS = 210_000
_SALT_BYTES = 16


def generate_pin() -> str:
    """Return a random 8-character PIN containing at least one letter and one digit."""
    while True:
        pin = "".join(secrets.choice(PIN_ALPHABET) for _ in range(PIN_LENGTH))
        if any(c in PIN_LETTERS for c in pin) and any(c in PIN_DIGITS for c in pin):
            return pin


def normalize_pin(pin: str) -> str:
    """Upper-case and strip a PIN so entry is forgiving of case and stray spaces."""
    return "".join(pin.split()).upper()


def validate_pin(pin: str) -> str:
    """Validate an admin-supplied PIN and return it normalised.

    Raises ValueError with a Chinese message suitable for showing to the admin.
    """
    normalized = normalize_pin(pin)
    if len(normalized) != PIN_LENGTH:
        raise ValueError(f"PIN 必須為 {PIN_LENGTH} 碼")
    if not normalized.isalnum() or not normalized.isascii():
        raise ValueError("PIN 只能使用英文字母與數字")
    if not any(c.isalpha() for c in normalized):
        raise ValueError("PIN 必須至少包含一個英文字母")
    if not any(c.isdigit() for c in normalized):
        raise ValueError("PIN 必須至少包含一個數字")
    return normalized


def hash_pin(pin: str) -> str:
    """Hash a PIN into the storable `pbkdf2_sha256$iters$salt$hash` format."""
    normalized = normalize_pin(pin)
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", normalized.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return "$".join(
        [
            "pbkdf2_sha256",
            str(_PBKDF2_ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_pin(pin: str, stored: str) -> bool:
    """Constant-time check of a submitted PIN against a stored hash."""
    try:
        algorithm, raw_iterations, raw_salt, raw_digest = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(raw_iterations)
        salt = base64.b64decode(raw_salt)
        expected = base64.b64decode(raw_digest)
    except (ValueError, TypeError):
        return False

    candidate = hashlib.pbkdf2_hmac("sha256", normalize_pin(pin).encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)
