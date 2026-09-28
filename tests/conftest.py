"""Shared fixtures for the test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the project root is on sys.path so `from harness...` resolves.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def layer_root_builder(tmp_path):
    """Build a per-test var/<root>/ skeleton with __init__.py + .gitkeep."""

    def _build(var_root_name: str = "var", *layers: str) -> dict[str, Path]:
        var_root = tmp_path / var_root_name
        result: dict[str, Path] = {}
        for layer in layers:
            layer_dir = var_root / layer
            layer_dir.mkdir(parents=True, exist_ok=True)
            (layer_dir / "__init__.py").write_text("")
            (layer_dir / ".gitkeep").write_text("")
            result[layer] = layer_dir
        return result

    return _build


@pytest.fixture
def project_with_layer_layout(tmp_path, monkeypatch):
    """Build a per-test project tree with `var/<layer>/` skeletons + a copy
    of `harness/ports/__init__.py` from the real project. Tests that need to
    inject a fake `harness/ports` override use this fixture.
    """
    real_ports = (PROJECT_ROOT / "harness" / "ports" / "__init__.py").read_text()
    project_root = tmp_path
    (project_root / "harness" / "ports").mkdir(parents=True)
    (project_root / "harness" / "ports" / "__init__.py").write_text(real_ports)
    return project_root
