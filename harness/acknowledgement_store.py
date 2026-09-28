"""Acknowledgement Store — the second single-writer surface in Epic 2.

Writes signed JSON records at `acknowledgements/<project_id>/<run_id>/<step>/
<acknowledgement_id>.json` (the spine AD-5 nested-ULID stance; PRD A8's
flat-by-hash-prefix stance is REJECTED per spec-devflow/contracts.md
L60-L63).

Public surface (Story 2.8):
- `AcknowledgementRecord` frozen dataclass carrying the spine AD-5 shape:
  `acknowledgement_id` (ULID), `project_id`, `run_id`, `step`,
  `acknowledger`, `acknowledger_kind` (Literal `human | check`),
  `verdict` (AD-12 closed enum), `open_items` (optional list),
  `rejection_reason` (optional str), `artifact_ref` (frozen dataclass with
  `step`, `project_id`, `run_id`, `hash`), `signature` (64-byte Ed25519),
  `timestamp` (ISO 8601 UTC).
- `write(...)` — validates verdict + verdict-specific required fields,
  signs over `{path_triple, body}` per AD-23, writes the file.
- `read(acknowledgement_id)` — reads the file, recomputes signature,
  verifies; raises `AcknowledgementUnsigned` or `AcknowledgementPathMismatch`.
- `read_latest(project_id, run_id, step)` — used by `step_status`.
- `list_for(project_id, run_id, step)` — used by the future dashboard.

AD-5 + AD-23 are the binding rules:
- AD-5: every Acknowledgement is signed Ed25519 via `harness.signing`.
- AD-23: signature covers the path triple `(project_id, run_id, step)` as
  it appears in the storage path. Cross-project copy-paste forgery is
  rejected with `AcknowledgementPathMismatch`.
"""

from __future__ import annotations

import json
import re
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import ulid

from harness import signing
from harness.workflow_controller import STEP_ORDER

# Verdict enum (AD-12). Duplicated here rather than imported from
# `harness.gate_engine` to break a circular import:
# `acknowledgement_store` -> `gate_engine` -> `workflow_controller`
# (for `step_status` re-export) -> `acknowledgement_store`. The closed
# enum is small enough to inline; the canonical home remains
# `harness.gate_engine.validate_verdict` (the Story 2.7 helper).
_VERDICT_VALUES = frozenset(
    {"accepted", "accepted-with-open-items", "rejected"}
)


def validate_verdict(verdict: str) -> None:
    """Raise `ValueError` if `verdict` is not in the AD-12 closed enum.

    Inline copy of `harness.gate_engine.validate_verdict`; see that
    helper for the canonical home. The duplication breaks a circular
    import (acknowledgement_store -> gate_engine -> workflow_controller
    for the step_status re-export -> acknowledgement_store).
    """
    if verdict not in _VERDICT_VALUES:
        raise ValueError(
            f"verdict_invalid: {verdict!r} not in {sorted(_VERDICT_VALUES)}"
        )


# --- Storage path -----------------------------------------------------------

# This file lives at harness/acknowledgement_store.py — the parent's parent
# is the project root. Acknowledgements live under the project root, NOT
# under `var/` (they are part of the audit trail, not runtime state).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ACKNOWLEDGEMENTS_DIR = PROJECT_ROOT / "acknowledgements"


# --- Acknowledgement record (AD-5 shape) -----------------------------------


AcknowledgerKind = Literal["human", "check"]


@dataclass(frozen=True)
class ArtifactRef:
    """The artifact the Acknowledgement gates. AD-5 inner object."""

    step: str
    project_id: str
    run_id: str
    hash: str  # "sha256:<64 hex>"

    def to_dict(self) -> dict[str, str]:
        return {
            "step": self.step,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "hash": self.hash,
        }


_OPEN_ITEM_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _assert_safe_id(value: str, kind: str) -> None:
    """Refuse path-traversal segments in storage-path identifiers.

    AD-23 forensics depend on the path triple being well-formed; a
    malicious `project_id="../../etc"` would escape `acknowledgements/`
    and the signature would still verify. v1 is CLI / single-process so
    this is defense-in-depth, not a primary threat model.
    """
    if not _SAFE_ID_RE.fullmatch(value):
        raise AcknowledgementStoreError(
            f"{kind}_invalid: {value!r} must match {_SAFE_ID_RE.pattern}"
        )


@dataclass(frozen=True)
class OpenItem:
    """An open item attached to an `accepted-with-open-items` Acknowledgement.

    The schema's required fields are `id` + `description`; `owner` and `due`
    are optional. v1 enforces `id` matches a sane identifier pattern.
    """

    id: str
    description: str
    owner: str | None = None
    due: str | None = None  # ISO 8601 UTC

    def __post_init__(self) -> None:
        if not _OPEN_ITEM_RE.match(self.id):
            raise ValueError(
                f"open_item.id_invalid: {self.id!r} "
                f"must match {_OPEN_ITEM_RE.pattern}"
            )
        if not self.description:
            raise ValueError("open_item.description_required")

    def to_dict(self) -> dict[str, str]:
        out: dict[str, str] = {"id": self.id, "description": self.description}
        if self.owner is not None:
            out["owner"] = self.owner
        if self.due is not None:
            out["due"] = self.due
        return out


@dataclass(frozen=True)
class AcknowledgementRecord:
    """A signed Acknowledgement record (AD-5).

    `body` is the JSON-serializable form minus the `signature` field;
    the signature is computed over `canonical_bytes({path_triple, body})`
    per AD-23.
    """

    acknowledgement_id: str  # ULID
    project_id: str
    run_id: str
    step: str
    acknowledger: str
    acknowledger_kind: AcknowledgerKind
    verdict: Literal["accepted", "accepted-with-open-items", "rejected"]
    artifact_ref: ArtifactRef
    signature: bytes  # 64-byte Ed25519
    timestamp: str  # ISO 8601 UTC
    open_items: tuple[OpenItem, ...] = field(default_factory=tuple)
    rejection_reason: str | None = None

    def to_body_dict(self) -> dict[str, Any]:
        """The body that was signed (and what gets re-signed by `read`)."""
        out: dict[str, Any] = {
            "acknowledgement_id": self.acknowledgement_id,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "step": self.step,
            "acknowledger": self.acknowledger,
            "acknowledger_kind": self.acknowledger_kind,
            "verdict": self.verdict,
            "artifact_ref": self.artifact_ref.to_dict(),
            "timestamp": self.timestamp,
        }
        if self.open_items:
            out["open_items"] = [oi.to_dict() for oi in self.open_items]
        if self.rejection_reason is not None:
            out["rejection_reason"] = self.rejection_reason
        return out

    def to_file_dict(self) -> dict[str, Any]:
        """The full on-disk JSON form (body + signature)."""
        body = self.to_body_dict()
        body["signature"] = self.signature.hex()
        return body

    @classmethod
    def from_file_dict(cls, data: dict[str, Any]) -> "AcknowledgementRecord":
        """Reconstruct from the on-disk JSON form (signature is hex)."""
        sig_hex = data["signature"]
        if not isinstance(sig_hex, str):
            raise AcknowledgementStoreError("signature_invalid_format")
        try:
            sig = bytes.fromhex(sig_hex)
        except ValueError as e:
            raise AcknowledgementStoreError(
                f"signature_hex_decode: {e}"
            ) from e
        if len(sig) != 64:
            raise AcknowledgementStoreError("signature_invalid_length")
        artifact_ref_data = data["artifact_ref"]
        open_items_data = data.get("open_items", [])
        return cls(
            acknowledgement_id=data["acknowledgement_id"],
            project_id=data["project_id"],
            run_id=data["run_id"],
            step=data["step"],
            acknowledger=data["acknowledger"],
            acknowledger_kind=data["acknowledger_kind"],
            verdict=data["verdict"],
            artifact_ref=ArtifactRef(
                step=artifact_ref_data["step"],
                project_id=artifact_ref_data["project_id"],
                run_id=artifact_ref_data["run_id"],
                hash=artifact_ref_data["hash"],
            ),
            signature=sig,
            timestamp=data["timestamp"],
            open_items=tuple(
                OpenItem(
                    id=oi["id"],
                    description=oi["description"],
                    owner=oi.get("owner"),
                    due=oi.get("due"),
                )
                for oi in open_items_data
            ),
            rejection_reason=data.get("rejection_reason"),
        )


# --- Exceptions ------------------------------------------------------------


class AcknowledgementStoreError(Exception):
    """Base for all acknowledgement-store errors."""


class AcknowledgementUnsigned(AcknowledgementStoreError):
    """Signature verification failed (bad signature, wrong key, malformed)."""


class AcknowledgementPathMismatch(AcknowledgementStoreError):
    """Body's path triple doesn't match the file's storage path (AD-23)."""


class AcknowledgementAlreadyExists(AcknowledgementStoreError):
    """A write tried to overwrite an existing acknowledgement_id."""


# --- Helpers ---------------------------------------------------------------


def _path_triple(project_id: str, run_id: str, step: str) -> dict[str, str]:
    """The (project_id, run_id, step) triple signed by AD-23.

    The order of keys matters — `canonical_bytes` uses `sort_keys=True`,
    but pinning the order here makes the signed payload predictable for
    debugging.
    """
    return {"project_id": project_id, "run_id": run_id, "step": step}


def _storage_path(
    project_id: str, run_id: str, step: str, acknowledgement_id: str
) -> Path:
    """Compute the on-disk path per spine AD-5 (nested ULID)."""
    return (
        ACKNOWLEDGEMENTS_DIR
        / project_id
        / run_id
        / step
        / f"{acknowledgement_id}.json"
    )


def _find_acknowledgement_by_id(acknowledgement_id: str) -> Path | None:
    """Locate an acknowledgement file by its ULID across all project dirs.

    Used by `read` to handle the AD-23 case where the caller's path triple
    does not match the file's actual storage path: the caller is
    potentially lying, so we don't trust the path; we search by id and
    then verify the body.
    """
    target = f"{acknowledgement_id}.json"
    if not ACKNOWLEDGEMENTS_DIR.exists():
        return None
    for path in ACKNOWLEDGEMENTS_DIR.rglob(target):
        return path
    return None


def _sign_payload(
    project_id: str, run_id: str, step: str, body: dict[str, Any]
) -> bytes:
    """Sign `canonical_bytes({path_triple, body})` per AD-23.

    The path triple MUST come first (sorted-key determinism) so that a
    debugger can re-derive the signed bytes from the body alone.
    """
    signed = {**_path_triple(project_id, run_id, step), "body": body}
    return signing.sign(signed)


# --- Write path ------------------------------------------------------------


def write(
    project_id: str,
    run_id: str,
    step: str,
    acknowledger: str,
    acknowledger_kind: AcknowledgerKind,
    verdict: str,
    artifact_ref: ArtifactRef,
    *,
    open_items: tuple[OpenItem, ...] | list[OpenItem] = (),
    rejection_reason: str | None = None,
    signature: bytes | None = None,
) -> AcknowledgementRecord:
    """Write a signed Acknowledgement record.

    Args:
        project_id, run_id, step: the path triple (must match `artifact_ref`'s
            own triple; mismatch raises `AcknowledgementStoreError`).
        acknowledger: a human user id (`mei@team`) or `'check:<name>'` for
            automated checks per AD-5.
        acknowledger_kind: `human` or `check`.
        verdict: one of the AD-12 closed enum values.
        artifact_ref: the locked artifact being gated.
        open_items: required when `verdict == 'accepted-with-open-items'`.
        rejection_reason: required when `verdict == 'rejected'`.
        signature: caller-supplied override (test-only). The production
            path signs internally via `harness.signing.sign`.

    Returns the constructed `AcknowledgementRecord`. Raises:
        `AcknowledgementStoreError` (or subclass) on any validation or
        storage failure.
    """
    # 1. Verdict enum check (AD-12) — happens BEFORE any signature or
    #    file write.
    validate_verdict(verdict)

    # 2. Step must be in STEP_ORDER.
    if step not in STEP_ORDER:
        raise AcknowledgementStoreError(f"unknown_step: {step}")

    # 2b. Path-triple identifiers must be safe (no traversal segments).
    _assert_safe_id(project_id, "project_id")
    _assert_safe_id(run_id, "run_id")
    _assert_safe_id(step, "step")

    # 3. artifact_ref's path triple MUST match the write arguments
    #    (else the signature would cover a different project/run/step
    #    than the file path).
    if (
        artifact_ref.project_id != project_id
        or artifact_ref.run_id != run_id
        or artifact_ref.step != step
    ):
        raise AcknowledgementStoreError(
            "artifact_ref_path_mismatch: "
            f"write arguments ({project_id}, {run_id}, {step}) != "
            f"artifact_ref ({artifact_ref.project_id}, {artifact_ref.run_id}, "
            f"{artifact_ref.step})"
        )

    # 4. Verdict-specific required fields.
    if verdict == "accepted-with-open-items" and not open_items:
        raise AcknowledgementStoreError("open_items_required")
    if verdict == "rejected" and not rejection_reason:
        raise AcknowledgementStoreError("rejection_reason_required")

    # 5. acknowledger_kind must be one of the two literal values; we
    #    rely on the Literal type at the call site but the format() check
    #    below catches a string passed through *args/**kwargs.
    if acknowledger_kind not in ("human", "check"):
        raise AcknowledgementStoreError(
            f"acknowledger_kind_invalid: {acknowledger_kind!r}"
        )

    # 6. Build the body + sign.
    now = datetime.now(timezone.utc)
    acknowledgement_id = str(ulid.ULID.from_datetime(now))
    timestamp = now.isoformat()
    open_items_tuple = (
        tuple(open_items) if not isinstance(open_items, tuple) else open_items
    )
    record = AcknowledgementRecord(
        acknowledgement_id=acknowledgement_id,
        project_id=project_id,
        run_id=run_id,
        step=step,
        acknowledger=acknowledger,
        acknowledger_kind=acknowledger_kind,
        verdict=verdict,
        artifact_ref=artifact_ref,
        signature=b"\x00" * 64 if signature is None else signature,
        # placeholder; replaced below
        timestamp=timestamp,
        open_items=open_items_tuple,
        rejection_reason=rejection_reason,
    )
    body = record.to_body_dict()
    actual_sig = signature if signature is not None else _sign_payload(
        project_id, run_id, step, body
    )
    # Replace the placeholder with the actual signature.
    record = AcknowledgementRecord(
        acknowledgement_id=acknowledgement_id,
        project_id=project_id,
        run_id=run_id,
        step=step,
        acknowledger=acknowledger,
        acknowledger_kind=acknowledger_kind,
        verdict=verdict,
        artifact_ref=artifact_ref,
        signature=actual_sig,
        timestamp=timestamp,
        open_items=open_items_tuple,
        rejection_reason=rejection_reason,
    )

    # 7. Atomic write: refuse to overwrite an existing record. ULID
    #    collisions are vanishingly rare (122 bits of entropy) but
    #    possible across processes; the writer must surface them.
    path = _storage_path(project_id, run_id, step, acknowledgement_id)
    if path.exists():
        raise AcknowledgementAlreadyExists(
            f"acknowledgement_id collision: {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record.to_file_dict(), sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return record


# --- Read path -------------------------------------------------------------


def read(
    acknowledgement_id: str, *, project_id: str, run_id: str, step: str
) -> AcknowledgementRecord:
    """Read + verify an Acknowledgement record by its storage path.

    The caller MUST supply the path triple (so the reader knows where to
    look). The body is verified against the path triple per AD-23; a
    mismatch raises `AcknowledgementPathMismatch`.

    Raises:
        `AcknowledgementStoreError("acknowledgement_not_found")` if the
        file is missing.
        `AcknowledgementUnsigned` if the signature doesn't verify.
        `AcknowledgementPathMismatch` if the body's `project_id` /
        `run_id` / `step` doesn't match the file's storage path.
    """
    path = _storage_path(project_id, run_id, step, acknowledgement_id)
    # AD-23: the caller's path triple may not match the storage path.
    # We must locate the file by acknowledgement_id alone first (the
    # body claims are untrusted until verified), THEN check the body
    # claims against the caller's claim.
    if not path.exists():
        # Search all top-level project dirs for the acknowledgement_id.
        found_path = _find_acknowledgement_by_id(acknowledgement_id)
        if found_path is None:
            raise AcknowledgementStoreError(
                f"acknowledgement_not_found: {path}"
            )
        path = found_path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise AcknowledgementStoreError(
            f"acknowledgement_malformed: {path}: {e}"
        ) from e
    try:
        record = AcknowledgementRecord.from_file_dict(data)
    except (KeyError, TypeError, ValueError) as e:
        # Missing required field, wrong type, or malformed open_items
        # entry. Surface as a structured AcknowledgementStoreError so
        # callers (the dashboard, the resolver) don't have to catch
        # raw exceptions.
        raise AcknowledgementStoreError(
            f"acknowledgement_malformed: {path}: {e}"
        ) from e

    # AD-23 path-triple check: the body's claims must match the call.
    # Verify signature against the BODY's path triple (the one the writer
    # signed against), then check that the body's triple matches the
    # caller's triple. A caller who supplies a different triple sees
    # `AcknowledgementPathMismatch` (AD-23 forgery guard); a caller who
    # has the right triple sees a clean read.
    body = record.to_body_dict()
    body_path_triple = _path_triple(
        record.project_id, record.run_id, record.step
    )
    signed_payload = {**body_path_triple, "body": body}
    if not signing.verify(signed_payload, record.signature):
        raise AcknowledgementUnsigned("signature verification failed")
    call_path_triple = _path_triple(project_id, run_id, step)
    if body_path_triple != call_path_triple:
        raise AcknowledgementPathMismatch(
            f"body triple {body_path_triple} != call triple {call_path_triple}"
        )

    return record


def read_latest(
    project_id: str, run_id: str, step: str
) -> AcknowledgementRecord | None:
    """Return the latest Acknowledgement for `(project_id, run_id, step)` or
    `None` if no Acknowledgement exists.

    "Latest" = lexicographically maximum `acknowledgement_id` (ULIDs sort
    chronologically — the spine's determinism story).
    """
    step_dir = ACKNOWLEDGEMENTS_DIR / project_id / run_id / step
    if not step_dir.exists():
        return None
    candidates = sorted(p.stem for p in step_dir.glob("*.json"))
    if not candidates:
        return None
    latest_id = candidates[-1]
    return read(latest_id, project_id=project_id, run_id=run_id, step=step)


def list_for(
    project_id: str, run_id: str, step: str
) -> tuple[AcknowledgementRecord, ...]:
    """Return all Acknowledgements for `(project_id, run_id, step)` sorted
    chronologically (ULID-lexicographic ascending).

    Tolerates corrupted records on disk: a tampered or malformed JSON
    file is skipped with a `warnings.warn(...)` so the dashboard (Story
    4.x) doesn't crash on the first corrupted entry. The list always
    returns the successfully-parsed records in chronological order.
    """
    step_dir = ACKNOWLEDGEMENTS_DIR / project_id / run_id / step
    if not step_dir.exists():
        return ()
    out: list[AcknowledgementRecord] = []
    for path in sorted(step_dir.glob("*.json")):
        try:
            record = read(
                path.stem,
                project_id=project_id,
                run_id=run_id,
                step=step,
            )
            out.append(record)
        except AcknowledgementStoreError as e:
            # Skip the corrupted record and warn the operator. The audit
            # trail still has the file; the dashboard will surface the
            # warning in a future step.
            warnings.warn(
                f"acknowledgement_skipped: {path}: {e}",
                UserWarning,
                stacklevel=2,
            )
    return tuple(out)


__all__ = [
    "AcknowledgementRecord",
    "ArtifactRef",
    "OpenItem",
    "AcknowledgerKind",
    "AcknowledgementStoreError",
    "AcknowledgementUnsigned",
    "AcknowledgementPathMismatch",
    "AcknowledgementAlreadyExists",
    "write",
    "read",
    "read_latest",
    "list_for",
    "ACKNOWLEDGEMENTS_DIR",
]



