"""Shared encryption/decryption utilities for autish export/import commands.

Uses AES-256-GCM with PBKDF2-HMAC-SHA256 key derivation.

File format (binary):
  [4]  magic  = b"AUTX"
  [1]  version = 0x01
  [16] salt   (random)
  [12] nonce  (random)
  [remaining] AES-256-GCM ciphertext + 16-byte tag (appended by AESGCM)
"""

from __future__ import annotations

import os
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_MAGIC = b"AUTX"
_VERSION = b"\x01"
_SALT_LEN = 16
_NONCE_LEN = 12
_KEY_LEN = 32   # 256 bits
_KDF_ITERS = 480_000  # OWASP-recommended minimum for PBKDF2-SHA256

_STRONG_PW_RE = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$"
)


# ──────────────────────────────────────────────────────────────────────────────
# Password policy
# ──────────────────────────────────────────────────────────────────────────────


def validate_strong_password(password: str) -> str | None:
    """Return an error message if *password* does not meet policy, else None."""
    if len(password) < 8:
        return "Pasvorto devas havi almenaŭ 8 signojn."
    if not re.search(r"[A-Z]", password):
        return "Pasvorto devas havi almenaŭ unu majusklan literon."
    if not re.search(r"[a-z]", password):
        return "Pasvorto devas havi almenaŭ unu minusklan literon."
    if not re.search(r"\d", password):
        return "Pasvorto devas havi almenaŭ unu ciferon."
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Key derivation
# ──────────────────────────────────────────────────────────────────────────────


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=SHA256(),
        length=_KEY_LEN,
        salt=salt,
        iterations=_KDF_ITERS,
    )
    return kdf.derive(password.encode("utf-8"))


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


def encrypt(plaintext: bytes, password: str) -> bytes:
    """Encrypt *plaintext* with *password*. Returns opaque encrypted bytes."""
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return _MAGIC + _VERSION + salt + nonce + ciphertext


def decrypt(data: bytes, password: str) -> bytes:
    """Decrypt *data* with *password*. Raises ValueError on bad password/data."""
    hdr_len = len(_MAGIC) + len(_VERSION) + _SALT_LEN + _NONCE_LEN
    if len(data) < hdr_len + 16:
        raise ValueError("Malĝusta dosierformato (tro mallonga).")
    magic = data[: len(_MAGIC)]
    if magic != _MAGIC:
        raise ValueError("Malĝusta dosierformato (malĝusta magio).")
    version = data[len(_MAGIC) : len(_MAGIC) + 1]
    if version != _VERSION:
        raise ValueError(f"Nekonata versio: {version!r}.")
    offset = len(_MAGIC) + 1
    salt = data[offset : offset + _SALT_LEN]
    offset += _SALT_LEN
    nonce = data[offset : offset + _NONCE_LEN]
    offset += _NONCE_LEN
    ciphertext = data[offset:]
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    try:
        return aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as exc:
        raise ValueError(
            "Malĝusta pasvorto aŭ koruptitaj datumoj."
        ) from exc


def is_encrypted(data: bytes) -> bool:
    """Return True if *data* looks like an autish encrypted blob."""
    return data[: len(_MAGIC)] == _MAGIC
