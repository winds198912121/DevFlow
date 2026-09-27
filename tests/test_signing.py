"""Tests for harness.signing + harness.secrets — covers the I/O Matrix in the 1.3 plan."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from harness import secrets as harness_secrets
from harness import signing as harness_signing


@pytest.fixture(autouse=True)
def isolated_key_path(tmp_path, monkeypatch):
    """Point KEY_PATH at a per-test tempdir; reset the signing module's cache."""
    test_key = tmp_path / "var" / "secrets" / "harness.key"
    monkeypatch.setattr(harness_secrets, "KEY_PATH", test_key)
    monkeypatch.setattr(harness_signing, "_keypair", None)
    return test_key


def test_sign_verify_roundtrip():
    s = harness_signing.sign({"a": 1, "b": 2})
    assert harness_signing.verify({"a": 1, "b": 2}, s) is True


def test_sign_is_deterministic_for_same_value():
    s1 = harness_signing.sign({"a": 1, "b": 2})
    s2 = harness_signing.sign({"a": 1, "b": 2})
    assert s1 == s2


def test_verify_rejects_tampered_value():
    s = harness_signing.sign({"a": 1})
    assert harness_signing.verify({"a": 2}, s) is False


def test_verify_rejects_signature_from_different_key():
    # Use an unrelated second keypair — sign with it, verify with our harness key.
    foreign = Ed25519PrivateKey.generate()
    foreign_sig = foreign.sign(b"not the canonical bytes we expect")
    assert harness_signing.verify({"a": 1}, foreign_sig) is False


def test_verify_rejects_malformed_signature():
    # 10 bytes — Ed25519 signatures are 64 bytes.
    assert harness_signing.verify({"a": 1}, b"\x00" * 10) is False


def test_missing_key_file_creates_one(tmp_path):
    test_key = tmp_path / "var" / "secrets" / "harness.key"
    assert not test_key.exists()
    s = harness_signing.sign({"a": 1})
    assert test_key.exists()
    assert test_key.stat().st_size == 64
    # Verify still works.
    assert harness_signing.verify({"a": 1}, s) is True


def test_pre_existing_key_file_is_loaded_not_regenerated(tmp_path):
    test_key = tmp_path / "var" / "secrets" / "harness.key"
    test_key.parent.mkdir(parents=True)
    # First call writes the key.
    harness_signing.sign({"a": 1})
    mtime_before = test_key.stat().st_mtime_ns
    # Second call should NOT regenerate.
    harness_signing.sign({"a": 1})
    mtime_after = test_key.stat().st_mtime_ns
    assert mtime_before == mtime_after


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only file mode check")
def test_key_file_mode_is_0600_on_posix(tmp_path):
    harness_signing.sign({"a": 1})
    test_key = tmp_path / "var" / "secrets" / "harness.key"
    mode = test_key.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"
