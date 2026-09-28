"""Delivery — write `delivery.json` for the final step of a run.

Public surface (Story 2.10):
- `DeliveryReceipt` frozen dataclass (the spine's `delivery.json` envelope).
- `write_delivery(project_id, run_id, *, executor_tuple_hash,
  artifact_hashes, acknowledgement_hashes) -> DeliveryReceipt` —
  computes the body + signature (AD-5 + AD-17) and writes to
  `var/projects/<project_id>/runs/<run_id>/delivery.json`.
- `read_delivery(project_id, run_id) -> DeliveryReceipt` — reads +
  verifies the signature.
- `DeliveryError` exception.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from harness import signing


PROJECT_ROOT = Path(__file__).resolve().parent.parent


# --- Exceptions -----------------------------------------------------------


class DeliveryError(Exception):
    """Base for all delivery errors."""


class DeliveryNotFound(DeliveryError):
    """No `delivery.json` exists for the (project_id, run_id) pair."""


class DeliverySignatureInvalid(DeliveryError):
    """The on-disk signature does not verify (delivery.json tampered)."""


# --- Dataclass ------------------------------------------------------------


@dataclass(frozen=True)
class DeliveryReceipt:
    """The full on-disk JSON form (body + signature)."""

    project_id: str
    run_id: str
    executor_tuple_hash: str
    total_artifacts: tuple[str, ...]
    total_acknowledgements: tuple[str, ...]
    delivered_at: str  # ISO 8601 UTC
    signature: bytes  # 64-byte Ed25519

    def to_body_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "run_id": self.run_id,
            "executor_tuple_hash": self.executor_tuple_hash,
            "total_artifacts": list(self.total_artifacts),
            "total_acknowledgements": list(self.total_acknowledgements),
            "delivered_at": self.delivered_at,
        }

    def to_file_dict(self) -> dict:
        body = self.to_body_dict()
        body["signature"] = self.signature.hex()
        return body

    @classmethod
    def from_file_dict(cls, data: dict) -> "DeliveryReceipt":
        return cls(
            project_id=data["project_id"],
            run_id=data["run_id"],
            executor_tuple_hash=data["executor_tuple_hash"],
            total_artifacts=tuple(data["total_artifacts"]),
            total_acknowledgements=tuple(data["total_acknowledgements"]),
            delivered_at=data["delivered_at"],
            signature=bytes.fromhex(data["signature"]),
        )


# --- Helpers --------------------------------------------------------------


def _delivery_path(project_id: str, run_id: str) -> Path:
    return (
        PROJECT_ROOT / "var" / "projects" / project_id
        / "runs" / run_id / "delivery.json"
    )


# --- Public API ------------------------------------------------------------


def write_delivery(
    project_id: str,
    run_id: str,
    *,
    executor_tuple_hash: str,
    artifact_hashes: list[str] | tuple[str, ...],
    acknowledgement_hashes: list[str] | tuple[str, ...],
) -> DeliveryReceipt:
    """Compute the body + signature and write `delivery.json`.

    The signature is over `canonical_bytes(body)` (AD-17 + AD-5).
    """
    receipt = DeliveryReceipt(
        project_id=project_id,
        run_id=run_id,
        executor_tuple_hash=executor_tuple_hash,
        total_artifacts=tuple(artifact_hashes),
        total_acknowledgements=tuple(acknowledgement_hashes),
        delivered_at=datetime.now(timezone.utc).isoformat(),
        signature=b"",  # placeholder; replaced below
    )
    body = receipt.to_body_dict()
    signature = signing.sign(body)
    receipt = DeliveryReceipt(
        project_id=project_id,
        run_id=run_id,
        executor_tuple_hash=executor_tuple_hash,
        total_artifacts=tuple(artifact_hashes),
        total_acknowledgements=tuple(acknowledgement_hashes),
        delivered_at=receipt.delivered_at,
        signature=signature,
    )
    path = _delivery_path(project_id, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(receipt.to_file_dict(), sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return receipt


def read_delivery(
    project_id: str, run_id: str
) -> DeliveryReceipt:
    """Read + verify `delivery.json`."""
    path = _delivery_path(project_id, run_id)
    if not path.exists():
        raise DeliveryNotFound(f"delivery not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    receipt = DeliveryReceipt.from_file_dict(data)
    body = receipt.to_body_dict()
    if not signing.verify(body, receipt.signature):
        raise DeliverySignatureInvalid(
            f"signature verification failed for {path}"
        )
    return receipt


__all__ = [
    "DeliveryReceipt",
    "DeliveryError",
    "DeliveryNotFound",
    "DeliverySignatureInvalid",
    "write_delivery",
    "read_delivery",
]

