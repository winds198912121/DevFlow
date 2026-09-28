"""Artifact Store — content-addressed canonical storage for step outputs.

The sole writer and reader of the `artifacts` table (mirrors AD-22's
"Skill Bump Registry has exactly two writers" pattern). Every step in
the Workflow Controller (Story 2.5) calls `put_pending` to register an
artifact, then `lock` to seal it; downstream steps call `read(sha256)`
to consume it. Locked artifacts are immutable (the read path verifies
both the content hash and the Ed25519 signature on every call, per
NFR-Reliab-1 + NFR-Sec-1).

The hash goes through `harness.canonical.canonical_sha256` (AD-17's sole
sha256 path); the signature goes through `harness.signing.sign/verify`
(AD-5 / AD-10 / NFR-Sec-2). The CI lint (`tools/check_no_direct_sha256.py`)
enforces no direct `hashlib` imports outside `harness/canonical.py`.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from ulid import ULID

from harness.canonical import canonical_sha256
from harness.signing import sign, verify


# --- Exceptions -----------------------------------------------------------


class ArtifactStoreError(Exception):
    """Base for all artifact store errors."""


class ArtifactNotFound(ArtifactStoreError):
    """No locked artifact has the requested sha256_hash, or the row exists
    but is still pending (lock has not been called)."""


class ArtifactCorrupt(ArtifactStoreError):
    """The stored payload's sha256 does not match the row's recorded
    `sha256` column. The payload has been modified after lock (tampered or
    disk-level corruption)."""


class ArtifactCorrupted(ArtifactStoreError):
    """The stored signature does not verify against the harness public key.
    The signature column was modified after lock.

    Note: distinct from `ArtifactCorrupt`. The recovery paths differ:
    `ArtifactCorrupt` → restore the payload from another source;
    `ArtifactCorrupted` → re-lock with a fresh signature.
    """


# --- Write path -----------------------------------------------------------


def put_pending(db: sqlite3.Connection, payload: bytes) -> str:
    """Write `payload` as a pending artifact and return its ULID.

    The artifact is addressable only by its ULID at this stage; `lock`
    computes the canonical sha256 + Ed25519 signature, populates the
    `sha256`, `signature`, `status='locked'`, and `locked_at` columns, and
    the artifact becomes addressable by hash via `read(sha256)`.
    """
    artifact_id = str(ULID.from_datetime(datetime.now(timezone.utc)))
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        """
        INSERT INTO artifacts (id, sha256, payload, status, created_at)
        VALUES (?, '', ?, 'pending', ?)
        """.strip(),
        (artifact_id, payload, now),
    )
    db.commit()
    return artifact_id


def lock(db: sqlite3.Connection, artifact_id: str) -> str:
    """Compute canonical_sha256 + sign; persist on the artifact row.

    Idempotent: a second call on the same artifact_id returns the same
    `sha256_hash` without raising. Only re-lock attempts that would change
    the hash (e.g. someone manually edited `payload` in the DB) raise.

    Returns the canonical sha256 hash as `"sha256:<hexdigest>"`.
    """
    row = db.execute(
        "SELECT payload, status, sha256, signature FROM artifacts WHERE id = ?",
        (artifact_id,),
    ).fetchone()
    if row is None:
        raise ArtifactNotFound(f"artifact {artifact_id!r} not found")
    payload, status, existing_hash, existing_signature = row
    # Idempotent: if the row is already locked, the hash matches the current
    # payload, AND the signature is present, return the existing hash without
    # re-signing. The signature check defends against a DB row that was
    # manually edited to `status='locked'` without a signature — a subsequent
    # `read()` would raise `ArtifactCorrupted` otherwise.
    current_hash = canonical_sha256(payload)
    if status == "locked" and existing_hash == current_hash and existing_signature:
        return current_hash
    if status == "locked" and existing_hash != current_hash:
        # The payload changed after lock; refuse to sign a tampered artifact.
        raise ArtifactCorrupt(
            f"artifact {artifact_id!r} payload changed after lock "
            f"(recorded {existing_hash!r}, current {current_hash!r})"
        )
    # status == 'pending' — compute and persist.
    signature = sign(payload)
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        """
        UPDATE artifacts
        SET sha256 = ?, status = 'locked', locked_at = ?, signature = ?
        WHERE id = ?
        """.strip(),
        (current_hash, now, signature, artifact_id),
    )
    db.commit()
    return current_hash


# --- Read path -----------------------------------------------------------


def read(db: sqlite3.Connection, sha256_hash: str) -> bytes:
    """Return the locked payload for `sha256_hash`.

    Verifies:
      1. The row exists with `status = 'locked'`.
      2. The stored signature is valid for the payload.
      3. The stored payload's sha256 equals `sha256_hash`.

    Raises `ArtifactNotFound` / `ArtifactCorrupted` / `ArtifactCorrupt`
    on any failure (per the I/O Matrix contract).
    """
    row = db.execute(
        """
        SELECT id, payload, sha256, status, signature
        FROM artifacts
        WHERE sha256 = ? AND status = 'locked'
        """.strip(),
        (sha256_hash,),
    ).fetchone()
    if row is None:
        raise ArtifactNotFound(f"no locked artifact with sha256 {sha256_hash!r}")
    _id, payload, stored_hash, _status, signature = row
    # 2. Hash check FIRST: a tampered payload is the most common failure
    # mode (disk-level corruption, hand-edit). Surface this before the
    # signature check because the operator's actionable fix is "restore the
    # payload from another source" rather than "re-sign".
    if canonical_sha256(payload) != stored_hash:
        raise ArtifactCorrupt(
            f"hash mismatch for {sha256_hash!r} (payload modified after lock)"
        )
    # 3. Signature check.
    if not signature or not verify(payload, signature):
        raise ArtifactCorrupted(
            f"signature verification failed for {sha256_hash!r}"
        )
    return payload


def is_locked(db: sqlite3.Connection, sha256_hash: str) -> bool:
    """Cheap check: does a locked artifact with this hash exist?

    Does NOT verify the signature or re-hash the payload. Use `read` for
    full verification.
    """
    row = db.execute(
        "SELECT 1 FROM artifacts WHERE sha256 = ? AND status = 'locked'",
        (sha256_hash,),
    ).fetchone()
    return row is not None
