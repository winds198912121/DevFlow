"""Tests for tools/check_layer_boundaries.py — covers the I/O Matrix in the 1.4 plan."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import PROJECT_ROOT

LINT = str(PROJECT_ROOT / "tools" / "check_layer_boundaries.py")
REAL_PORTS = str(PROJECT_ROOT / "harness" / "ports" / "__init__.py")


def _run_lint(
    tmp_path: Path,
    *extra_args: str,
    ports_path: str = REAL_PORTS,
) -> subprocess.CompletedProcess:
    """Run the lint. By default points --layer-dir and --var-dir at the
    per-test tmp_path; --ports-path stays at the real repo's ports stub.
    """
    return subprocess.run(
        [
            sys.executable, LINT,
            "--ports-path", ports_path,
            "--layer-dir", str(tmp_path),
            "--var-dir", str(tmp_path / "var"),
            *extra_args,
        ],
        capture_output=True,
        text=True,
    )


def _build_layer_dirs(tmp_path: Path, *layers: str) -> None:
    """Create empty var/<layer>/ skeleton."""
    for layer in layers:
        d = tmp_path / "var" / layer
        d.mkdir(parents=True, exist_ok=True)
        (d / ".gitkeep").write_text("")


def _build_layer_roots(tmp_path: Path, *layers: str) -> None:
    """Create empty skills/agents/herdr/dashboard/ roots under tmp_path."""
    for layer in layers:
        d = tmp_path / layer
        d.mkdir(parents=True, exist_ok=True)
        (d / "__init__.py").write_text("")


# AC 1: clean repo → exit 0
def test_clean_repo_exits_0(tmp_path):
    _build_layer_dirs(tmp_path, "skills", "agents", "herdr", "dashboard")
    _build_layer_roots(tmp_path, "skills", "agents", "herdr", "dashboard")
    result = _run_lint(tmp_path)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.stdout.strip() == ""


# AC 2: allowed port import → exit 0
def test_allowed_port_import_exits_0(tmp_path):
    _build_layer_dirs(tmp_path, "skills", "agents", "herdr", "dashboard")
    _build_layer_roots(tmp_path, "skills", "agents", "herdr", "dashboard")
    (tmp_path / "skills" / "foo").mkdir()
    (tmp_path / "skills" / "foo" / "__init__.py").write_text("")
    (tmp_path / "skills" / "foo" / "bar.py").write_text(
        "from harness.ports import StepExecutorPort\n"
    )
    result = _run_lint(tmp_path)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"


# AC 3: forbidden canonical import → exit 1 + names offender
def test_forbidden_canonical_import_exits_1(tmp_path):
    _build_layer_dirs(tmp_path, "skills", "agents", "herdr", "dashboard")
    _build_layer_roots(tmp_path, "skills", "agents", "herdr", "dashboard")
    (tmp_path / "skills" / "foo").mkdir()
    (tmp_path / "skills" / "foo" / "__init__.py").write_text("")
    (tmp_path / "skills" / "foo" / "bar.py").write_text(
        "from harness.canonical import canonical_bytes\n"
    )
    result = _run_lint(tmp_path)
    assert result.returncode == 1
    assert "canonical_bytes" in result.stdout
    assert "not in harness/ports allowlist" in result.stdout


# AC 4: bare `import harness` → exit 1
def test_bare_harness_import_exits_1(tmp_path):
    _build_layer_dirs(tmp_path, "skills", "agents", "herdr", "dashboard")
    _build_layer_roots(tmp_path, "skills", "agents", "herdr", "dashboard")
    (tmp_path / "agents" / "x_pkg").mkdir()
    (tmp_path / "agents" / "x_pkg" / "__init__.py").write_text("")
    (tmp_path / "agents" / "x_pkg" / "y.py").write_text("import harness\n")
    result = _run_lint(tmp_path)
    assert result.returncode == 1
    assert "bare 'harness' import" in result.stdout


# AC 5: missing var/<layer>/ subdirs → exit 1
def test_missing_var_root_exits_1(tmp_path):
    _build_layer_roots(tmp_path, "skills", "agents", "herdr", "dashboard")
    # Do NOT build var/<layer>/ — the lint should flag all four.
    result = _run_lint(tmp_path)
    assert result.returncode == 1
    for layer in ("skills", "agents", "herdr", "dashboard"):
        assert f"missing_layer_root:" in result.stdout
        assert f"var/{layer}" in result.stdout


# AC 6: empty allowlist → exit 1
def test_empty_allowlist_exits_1(tmp_path, tmp_path_factory):
    # Build a custom ports stub with no __all__ in a per-test tmp_path.
    custom_ports = tmp_path / "empty_ports.py"
    custom_ports.write_text("# no __all__\n")
    _build_layer_dirs(tmp_path, "skills", "agents", "herdr", "dashboard")
    _build_layer_roots(tmp_path, "skills", "agents", "herdr", "dashboard")
    result = _run_lint(tmp_path, ports_path=str(custom_ports))
    assert result.returncode == 1
    assert "allowlist_empty" in result.stdout


# AC 7: harness.secrets import → exit 1
def test_forbidden_secrets_import_exits_1(tmp_path):
    _build_layer_dirs(tmp_path, "skills", "agents", "herdr", "dashboard")
    _build_layer_roots(tmp_path, "skills", "agents", "herdr", "dashboard")
    (tmp_path / "agents" / "x_pkg").mkdir()
    (tmp_path / "agents" / "x_pkg" / "__init__.py").write_text("")
    (tmp_path / "agents" / "x_pkg" / "y.py").write_text(
        "from harness.secrets import KEY_PATH\n"
    )
    result = _run_lint(tmp_path)
    assert result.returncode == 1
    assert "secrets" in result.stdout
    assert "not in harness/ports allowlist" in result.stdout


# AC 8: empty allowlist even when a real import statement is present
def test_empty_allowlist_blocks_allowed_import_shape(tmp_path):
    custom_ports = tmp_path / "empty_ports.py"
    custom_ports.write_text("# empty allowlist\n")
    _build_layer_dirs(tmp_path, "skills", "agents", "herdr", "dashboard")
    _build_layer_roots(tmp_path, "skills", "agents", "herdr", "dashboard")
    (tmp_path / "herdr" / "y_pkg").mkdir()
    (tmp_path / "herdr" / "y_pkg" / "__init__.py").write_text("")
    (tmp_path / "herdr" / "y_pkg" / "z.py").write_text(
        "from harness.ports import StepExecutorPort\n"
    )
    result = _run_lint(tmp_path, ports_path=str(custom_ports))
    assert result.returncode == 1
    # Either the empty-allowlist flag OR the not-in-allowlist flag triggers.
    assert "allowlist_empty" in result.stdout or "not in harness/ports allowlist" in result.stdout


# AC 9: smoke — pytest infrastructure runs the lint cleanly
def test_layer_boundaries_pytest_smoke(tmp_path):
    _build_layer_dirs(tmp_path, "skills", "agents", "herdr", "dashboard")
    _build_layer_roots(tmp_path, "skills", "agents", "herdr", "dashboard")
    result = _run_lint(tmp_path)
    assert result.returncode == 0
