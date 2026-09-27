"""Harness signing key — the sole writer to var/secrets/harness.key.

AD-10 / NFR-Sec-1 / NFR-Sec-2: the harness signs Acknowledgement records,
invocation tokens, and artifact hashes on lock with Ed25519. The key lives
at var/secrets/harness.key in the layout:

    [0:32]   32-byte Ed25519 seed (little-endian, Ed25519PrivateKey.private_bytes_raw())
    [32:64]  32-byte Ed25519 public key (Ed25519PrivateKey.public_key().public_bytes_raw())

Total 64 bytes. Layout documented inline so future maintainers do not need
to re-derive it. The file mode is 0600 on POSIX; chmod is best-effort on
Windows where read-only bits behave differently.

Per AD-22's "Skill Bump Registry has exactly two writers" pattern, this
module is the sole writer and reader for the harness signing key. Every
other module that needs signing goes through `harness.signing.sign(...)`
and `harness.signing.verify(...)`.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

# Project root: the directory containing pyproject.toml.
# This file is at harness/secrets.py, so the root is the parent's parent.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
KEY_PATH = PROJECT_ROOT / "var" / "secrets" / "harness.key"

# Layout constants — enforced by read_key; exported so tests can assert.
SEED_LEN = 32
PUBKEY_LEN = 32
KEY_FILE_LEN = SEED_LEN + PUBKEY_LEN  # 64


class InvalidKeyFile(Exception):
    """Raised when the key file exists but has the wrong size or can't be parsed."""


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _chmod_0600(path: Path) -> None:
    """Best-effort POSIX chmod; no-op on Windows where mode bits differ."""
    if os.name == "posix":
        os.chmod(path, 0o600)


def _generate() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def write_key(private_key: Ed25519PrivateKey) -> None:
    """Persist `private_key` at KEY_PATH in the 64-byte layout. Idempotent."""
    _ensure_dir(KEY_PATH)
    seed = private_key.private_bytes_raw()  # 32 bytes
    pub = private_key.public_key().public_bytes_raw()  # 32 bytes
    assert len(seed) == SEED_LEN
    assert len(pub) == PUBKEY_LEN
    KEY_PATH.write_bytes(seed + pub)
    _chmod_0600(KEY_PATH)


def read_key() -> Ed25519PrivateKey:
    """Read the private key from KEY_PATH. Raises InvalidKeyFile on size mismatch
    or on a seed that Ed25519 cannot parse (malformed 32 bytes)."""
    raw = KEY_PATH.read_bytes()
    if len(raw) != KEY_FILE_LEN:
        raise InvalidKeyFile(
            f"{KEY_PATH}: expected {KEY_FILE_LEN} bytes (32 seed + 32 pubkey), "
            f"got {len(raw)}"
        )
    seed = raw[:SEED_LEN]
    try:
        return Ed25519PrivateKey.from_private_bytes(seed)
    except (ValueError, TypeError) as e:
        # cryptography raises ValueError for malformed seeds (right size, wrong
        # bytes). Wrap so callers see a single exception type.
        raise InvalidKeyFile(f"{KEY_PATH}: malformed seed ({e})") from e


def load_or_generate() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Return (private_key, public_key). Generate + persist if the file is missing."""
    if KEY_PATH.exists():
        priv = read_key()
    else:
        priv = _generate()
        write_key(priv)
    return priv, priv.public_key()


def public_key_bytes() -> bytes:
    """Return the 32-byte public key (always derivable from the private key file)."""
    priv, _ = load_or_generate()
    return priv.public_key().public_bytes_raw()
