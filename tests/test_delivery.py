"""Tests for harness.delivery (Story 2.10)."""

from __future__ import annotations

import shutil

import pytest

from harness.delivery import (
    PROJECT_ROOT,
    DeliveryNotFound,
    DeliverySignatureInvalid,
    read_delivery,
    write_delivery,
)


@pytest.fixture(autouse=True)
def _clean_delivery():
    """Remove var/projects between tests."""
    root = PROJECT_ROOT / "var" / "projects"
    if root.exists():
        shutil.rmtree(root)
    yield
    if root.exists():
        shutil.rmtree(root)


def test_write_delivery_writes_file():
    receipt = write_delivery(
        "p1", "R1",
        executor_tuple_json="{}",
        artifact_hashes=["sha256:" + "a" * 64],
        acknowledgement_hashes=["sha256:" + "b" * 64],
    )
    assert receipt.project_id == "p1"
    assert receipt.run_id == "R1"
    assert len(receipt.total_artifacts) == 1
    assert receipt.signature  # 64 bytes

    path = PROJECT_ROOT / "var" / "projects" / "p1" / "runs" / "R1" / "delivery.json"
    assert path.exists()


def test_read_delivery_roundtrips():
    write_delivery(
        "p1", "R1",
        executor_tuple_json="{}",
        artifact_hashes=["sha256:" + "a" * 64],
        acknowledgement_hashes=["sha256:" + "b" * 64],
    )
    read_back = read_delivery("p1", "R1")
    assert read_back.project_id == "p1"
    assert read_back.run_id == "R1"


def test_read_delivery_missing_raises():
    with pytest.raises(DeliveryNotFound):
        read_delivery("p1", "R1")


def test_read_delivery_tampered_signature_raises():
    """Flip the signature on disk; read raises DeliverySignatureInvalid."""
    import json as _json
    write_delivery(
        "p1", "R1",
        executor_tuple_json="{}",
        artifact_hashes=["sha256:" + "a" * 64],
        acknowledgement_hashes=["sha256:" + "b" * 64],
    )
    path = PROJECT_ROOT / "var" / "projects" / "p1" / "runs" / "R1" / "delivery.json"
    data = _json.loads(path.read_text(encoding="utf-8"))
    sig_bytes = bytearray(bytes.fromhex(data["signature"]))
    sig_bytes[0] ^= 0xFF
    data["signature"] = sig_bytes.hex()
    path.write_text(_json.dumps(data), encoding="utf-8")

    with pytest.raises(DeliverySignatureInvalid):
        read_delivery("p1", "R1")

