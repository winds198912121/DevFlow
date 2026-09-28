"""Tests for harness.checks + harness.cli -- the Epic 1 tracer bullet."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from harness.checks import (
    PROJECT_ROOT,
    CheckResult,
    check_adapters,
    check_canonical_path,
    check_dashboard_write_lint,
    check_keypair,
    check_layer_boundary_lint,
    check_signing_path,
    check_skeleton,
    run_all_checks,
)


# Per-test isolation: redirect KEY_PATH to a tempdir so the real key file is
# never touched and the test fixture can also exercise missing-file paths.
@pytest.fixture(autouse=True)
def isolated_key_path(tmp_path, monkeypatch):
    from harness import secrets
    test_key = tmp_path / "var" / "secrets" / "harness.key"
    monkeypatch.setattr(secrets, "KEY_PATH", test_key)  # already a Path via tmp_path
    from harness import signing
    monkeypatch.setattr(signing, "_keypair", None)
    yield test_key


# --- check_canonical_path / check_signing_path ------------------------------


def test_canonical_path_returns_ok():
    r = check_canonical_path()
    assert r.is_ok()


def test_signing_path_returns_ok():
    r = check_signing_path()
    assert r.is_ok()


# --- check_keypair ---------------------------------------------------------


def test_keypair_generates_and_returns_ok(tmp_path):
    r = check_keypair()
    assert r.is_ok()
    # The key file now exists at the (test-isolated) path.
    test_key = tmp_path / "var" / "secrets" / "harness.key"
    assert test_key.exists()
    assert test_key.stat().st_size == 64


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only mode check")
def test_keypair_wrong_mode_returns_fail(tmp_path, monkeypatch):
    # Generate the key, then chmod it to 0644.
    from harness import signing
    signing.sign({"_baseline": True})
    test_key = tmp_path / "var" / "secrets" / "harness.key"
    os.chmod(test_key, 0o644)
    r = check_keypair()
    assert not r.is_ok()
    assert "mode" in r.detail


# --- check_adapters --------------------------------------------------------


def test_adapters_returns_ok():
    r = check_adapters()
    assert r.is_ok()
    assert "human" in r.detail


# --- check_skeleton --------------------------------------------------------


def test_skeleton_returns_ok_on_real_repo():
    r = check_skeleton()
    assert r.is_ok()


# --- check_layer_boundary_lint --------------------------------------------


def test_layer_boundary_lint_returns_ok():
    r = check_layer_boundary_lint()
    assert r.is_ok()


# --- check_dashboard_write_lint (replaces stub from Story 1.6 in 1.7) ----


def test_dashboard_write_lint_returns_ok():
    r = check_dashboard_write_lint()
    assert r.is_ok()
    assert "clean" in r.detail or "AD-21" in r.detail


# --- run_all_checks + CLI subprocess ---------------------------------------


def test_run_all_checks_on_real_repo_all_ok():
    results = run_all_checks()
    for r in results:
        assert r.is_ok(), f"{r.name}: {r.detail}"
    # Assert the checks actually ran, not how many there are: pinning the count
    # breaks every time a check is added, without saying anything about whether
    # the repo is healthy.
    assert results, "run_all_checks returned nothing"
    assert {"keypair", "layer_boundary_lint", "terminal_status_lint"} <= {
        r.name for r in results
    }


def test_check_baseline_cli_exits_0_on_clean_repo(tmp_path):
    """Smoke: invoke the real CLI as a subprocess (mirrors the entry's verify)."""
    result = subprocess.run(
        [sys.executable, "-m", "harness", "check-baseline"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    # The summary line must report all checks passing at whatever the current
    # count is ("baseline: N/N OK").
    match = re.search(r"baseline: (\d+)/(\d+) OK", result.stdout)
    assert match, result.stdout
    assert match.group(1) == match.group(2)


def test_check_baseline_cli_idempotent(tmp_path):
    """Two runs produce the same summary line (idempotent contract)."""
    lines = []
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-m", "harness", "check-baseline"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0
        lines.append(result.stdout.strip())
    assert lines[0] == lines[1], f"first={lines[0]!r} second={lines[1]!r}"
