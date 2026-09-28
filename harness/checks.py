"""Baseline invariants — the checks that `harness check-baseline` runs.

Each check returns a `CheckResult(status, name, detail)`. The CLI aggregates
them and prints a single one-line summary. The checks are intentionally
read-only against the repo (one side effect: `check_keypair` may generate
the harness signing key on first run via `harness.signing.sign`, since the
key's existence is itself an invariant).
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from harness.executor import ADAPTER_REGISTRY
from harness import secrets as _secrets

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _key_path() -> Path:
    """Return the current value of the harness signing key path.

    Indirect through the module attribute so test fixtures that monkeypatch
    `harness.secrets.KEY_PATH` are picked up.
    """
    return _secrets.KEY_PATH


CheckStatus = Literal["ok", "fail"]


@dataclass(frozen=True)
class CheckResult:
    status: CheckStatus
    name: str
    detail: str

    @classmethod
    def ok(cls, name: str, detail: str = "") -> "CheckResult":
        return cls(status="ok", name=name, detail=detail)

    @classmethod
    def fail(cls, name: str, detail: str) -> "CheckResult":
        return cls(status="fail", name=name, detail=detail)

    def is_ok(self) -> bool:
        return self.status == "ok"


# --- Individual checks -------------------------------------------------------


def check_keypair() -> CheckResult:
    """The Ed25519 signing key exists with mode 0600."""
    key_path = _key_path()
    if not key_path.exists():
        # Generate it via the signing path (single side effect of this check).
        from harness.signing import sign
        sign({"_baseline_init": True})
    if not key_path.exists():
        return CheckResult.fail("keypair", f"{key_path} not found after generation")
    if os.name == "posix":
        mode = key_path.stat().st_mode & 0o777
        if mode != 0o600:
            return CheckResult.fail("keypair", f"mode expected 0o600, got {oct(mode)}")
    size = key_path.stat().st_size
    return CheckResult.ok("keypair", f"{key_path} mode={'0o600' if os.name == 'posix' else 'n/a'} size={size}")


def check_canonical_path() -> CheckResult:
    """The sole sha256 path (harness.canonical) is importable and returns the expected surface."""
    from harness.canonical import canonical_bytes, canonical_sha256  # noqa: F401
    out = canonical_sha256(b"")
    if not out.startswith("sha256:"):
        return CheckResult.fail("canonical_path", f"unexpected sha256 prefix: {out!r}")
    return CheckResult.ok("canonical_path", f"surface ok (empty digest {out[:20]}...)")


def check_signing_path() -> CheckResult:
    """The signing surface (harness.signing.sign + verify) roundtrips."""
    from harness.signing import sign, verify
    sig = sign({"_baseline": True})
    if not isinstance(sig, (bytes, bytearray)) or len(sig) != 64:
        return CheckResult.fail("signing_path", f"signature shape wrong: {type(sig).__name__} len={len(sig)}")
    if not verify({"_baseline": True}, sig):
        return CheckResult.fail("signing_path", "roundtrip verify returned False")
    return CheckResult.ok("signing_path", "sign+verify roundtrip ok")


def check_layer_boundary_lint() -> CheckResult:
    """Subprocess-run tools/check_layer_boundaries.py; pass = exit 0."""
    lint = PROJECT_ROOT / "tools" / "check_layer_boundaries.py"
    if not lint.exists():
        return CheckResult.fail("layer_boundary_lint", f"{lint} not found")
    result = subprocess.run(
        [sys.executable, str(lint), "--ports-path", str(PROJECT_ROOT / "harness" / "ports" / "__init__.py")],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    if result.returncode == 0:
        return CheckResult.ok("layer_boundary_lint", "clean")
    return CheckResult.fail("layer_boundary_lint", (result.stderr or result.stdout).strip().splitlines()[0] if (result.stderr or result.stdout).strip() else "exit 1")


def check_dashboard_write_lint() -> CheckResult:
    """Subprocess-run tools/check_dashboard_writes.py. Story 1.6 ships the stub
    (prints `deferred (Story 1.7)` and exits 0); Story 1.7 replaces the body.
    """
    lint = PROJECT_ROOT / "tools" / "check_dashboard_writes.py"
    if not lint.exists():
        return CheckResult.fail(
            "dashboard_write_lint",
            f"deferred ({lint} not found — Story 1.7)",
        )
    result = subprocess.run(
        [sys.executable, str(lint)],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    if result.returncode == 0:
        out = (result.stdout or "").strip()
        return CheckResult.ok("dashboard_write_lint", out or "clean")
    return CheckResult.fail(
        "dashboard_write_lint",
        (result.stderr or result.stdout).strip().splitlines()[0] if (result.stderr or result.stdout).strip() else "exit 1",
    )


def check_adapters() -> CheckResult:
    """At least one adapter is registered, and the human adapter is one of them."""
    names = ADAPTER_REGISTRY.list()
    if not names:
        return CheckResult.fail("adapters", "no adapters registered")
    if "human" not in names:
        return CheckResult.fail("adapters", f"human adapter missing; got {names}")
    return CheckResult.ok("adapters", f"{len(names)} adapter(s): {','.join(names)}")


def check_skeleton() -> CheckResult:
    """The four layer roots + four var/<layer>/ skeletons exist."""
    missing: list[str] = []
    for layer in ("skills", "agents", "herdr", "dashboard"):
        if not (PROJECT_ROOT / layer).exists():
            missing.append(f"layer root: {layer}")
        if not (PROJECT_ROOT / "var" / layer).exists():
            missing.append(f"var/{layer}")
    if missing:
        return CheckResult.fail("skeleton", "missing " + ", ".join(missing))
    return CheckResult.ok("skeleton", "8 paths present")


# --- Aggregate --------------------------------------------------------------


def run_all_checks() -> list[CheckResult]:
    """Run every check in deterministic order. Each runs unconditionally so
    the operator sees every problem at once instead of one-at-a-time.
    """
    return [
        check_keypair(),
        check_canonical_path(),
        check_signing_path(),
        check_layer_boundary_lint(),
        check_dashboard_write_lint(),
        check_adapters(),
        check_skeleton(),
    ]
