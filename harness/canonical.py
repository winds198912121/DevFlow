"""Canonical serialization — the sole sha256 path in the harness.

AD-17: All sha256 hashing in the harness goes through canonical_bytes. CI lint
rejects any direct hashlib import outside this module. See
_bmad-output/specs/spec-devflow/SPEC.md (Constraints) and the architecture
spine's AD-17 for the binding rules.

Three serialization shapes, dispatched by Python type:
- dict / list: JSON with sorted keys, UTF-8 NFC, no whitespace, no trailing newline
- str: UTF-8 text, line endings normalized to LF, exactly one trailing LF if non-empty
- bytes / bytearray: as-is
Other types raise TypeError.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any


def _nfc(obj: Any) -> Any:
    """Recursively NFC-normalize all str leaves in a JSON-shaped value."""
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, list):
        return [_nfc(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _nfc(v) for k, v in obj.items()}
    return obj


def _json_canonical_bytes(value: Any) -> bytes:
    normalized = _nfc(value)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _text_canonical_bytes(value: str) -> bytes:
    # NFC-normalize first so decomposed forms (e.g. "\u00e9\u0301") collapse
    # before LF normalization. Then CRLF / CR → LF, then exactly one trailing
    # LF if non-empty (never strip a user-provided trailing LF).
    nfc = unicodedata.normalize("NFC", value)
    normalized = nfc.replace("\r\n", "\n").replace("\r", "\n")
    if normalized and not normalized.endswith("\n"):
        normalized = normalized + "\n"
    return normalized.encode("utf-8")


def _binary_canonical_bytes(value: bytes | bytearray) -> bytes:
    if isinstance(value, bytearray):
        return bytes(value)
    return value


def canonical_bytes(value: Any) -> bytes:
    """Serialize `value` to bytes per AD-17 canonicalization rules."""
    if isinstance(value, (dict, list)):
        return _json_canonical_bytes(value)
    if isinstance(value, str):
        return _text_canonical_bytes(value)
    if isinstance(value, (bytes, bytearray)):
        return _binary_canonical_bytes(value)
    raise TypeError(f"canonical_bytes: unsupported type {type(value).__name__}")


def canonical_sha256(value: Any) -> str:
    """sha256 of canonical_bytes, returned as the platform's `"sha256:<hex>"` form."""
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()
