"""Harness signing surface — `sign` and `verify` for any canonical-bytes input.

Per AD-5 / AD-10 / NFR-Sec-1 / NFR-Sec-2: every signature in the harness
goes through these two functions. The sign payload is `canonical_bytes(value)`
from `harness.canonical` (the sole serialization path established in Story 1.2),
so the same logical input always produces the same signature.

`verify` returns False on any failure (bad signature bytes, wrong key,
malformed signature, malformed value) — never raises — so consumers can
treat it as a single predicate without a try/except wrapper.
"""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from harness.canonical import canonical_bytes
from harness.secrets import load_or_generate

# Lazy-loaded, process-local cache. Signing operations are on the hot path
# (every Acknowledgement, every invocation token); re-reading the key file
# per call would add I/O latency.
_keypair: tuple[Ed25519PrivateKey, Ed25519PublicKey] | None = None


def _get_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    global _keypair
    if _keypair is None:
        _keypair = load_or_generate()
    return _keypair


def reset_cache() -> None:
    """Drop the in-process key cache. Test-only helper."""
    global _keypair
    _keypair = None


def sign(value: object) -> bytes:
    """Sign `value` (via canonical_bytes) with the harness private key."""
    priv, _ = _get_keypair()
    return priv.sign(canonical_bytes(value))


def verify(value: object, signature: bytes) -> bool:
    """Verify `signature` against canonical_bytes(value). Never raises."""
    if not isinstance(signature, (bytes, bytearray)) or len(signature) != 64:
        return False
    _, pub = _get_keypair()
    try:
        pub.verify(bytes(signature), canonical_bytes(value))
    except InvalidSignature:
        return False
    except Exception:
        # Any other cryptography error (malformed value, etc.) is also a verification failure.
        return False
    return True
