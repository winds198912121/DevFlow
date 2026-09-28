"""Tests for tools/check_dashboard_writes.py — covers the I/O Matrix in the 1.7 plan."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.conftest import PROJECT_ROOT

LINT = str(PROJECT_ROOT / "tools" / "check_dashboard_writes.py")


def _run_lint(tmp_path: Path, *extra_args: str) -> subprocess.CompletedProcess:
    """Run the lint against a per-test dashboard/. Pass the per-test tmp_path as the
    project root so the default --dashboard-root resolves to the test fixture.
    """
    return subprocess.run(
        [sys.executable, LINT, "--project-root", str(tmp_path), *extra_args],
        capture_output=True,
        text=True,
    )


def _build_dashboard(tmp_path: Path, files: dict[str, str]) -> None:
    """Create tmp_path/dashboard/ and write files mapping relative path → content."""
    dash = tmp_path / "dashboard"
    dash.mkdir()
    (dash / ".gitkeep").write_text("")
    for relpath, content in files.items():
        target = dash / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


# AC 1: empty dashboard → exit 0
def test_empty_dashboard_exits_0(tmp_path):
    _build_dashboard(tmp_path, {})
    result = _run_lint(tmp_path)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.stdout.strip() == ""


# AC 2: one allowed POST /acknowledgements → exit 0
def test_one_allowed_route_exits_0(tmp_path):
    _build_dashboard(tmp_path, {
        "main.py": "from fastapi import FastAPI\napp = FastAPI()\n"
                   "@app.post('/acknowledgements')\nasync def submit_ack(): pass\n",
    })
    result = _run_lint(tmp_path)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"


# AC 3: all seven AD-21 + AD-18 routes → exit 0
def test_all_seven_allowed_routes_exit_0(tmp_path):
    code = "from fastapi import FastAPI\napp = FastAPI()\n"
    routes = [
        "/acknowledgements",
        "/swap-executor",
        "/skill-bump-regression",
        "/skill-bump-promote",
        "/cost-overrun-ack",
        "/regression-set-remove",
        "/project-edit-lock",
    ]
    for idx, path in enumerate(routes):
        # Use a valid Python identifier (no slashes).
        code += f"@app.post('{path}')\nasync def route_{idx}(): pass\n"
    _build_dashboard(tmp_path, {"main.py": code})
    result = _run_lint(tmp_path)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"


# AC 4: unauthorized POST → exit 1 + dashboard_write_violation + POST /unknown
def test_unauthorized_post_exits_1(tmp_path):
    _build_dashboard(tmp_path, {
        "main.py": "from fastapi import FastAPI\napp = FastAPI()\n"
                   "@app.post('/unknown')\nasync def x(): pass\n",
    })
    result = _run_lint(tmp_path)
    assert result.returncode == 1
    assert "dashboard_write_violation" in result.stdout
    assert "POST /unknown" in result.stdout


# AC 5: unauthorized PUT → exit 1
def test_unauthorized_put_exits_1(tmp_path):
    _build_dashboard(tmp_path, {
        "main.py": "from fastapi import FastAPI\napp = FastAPI()\n"
                   "@app.put('/unknown')\nasync def x(): pass\n",
    })
    result = _run_lint(tmp_path)
    assert result.returncode == 1
    assert "PUT /unknown" in result.stdout


# AC 6: unauthorized PATCH → exit 1
def test_unauthorized_patch_exits_1(tmp_path):
    _build_dashboard(tmp_path, {
        "main.py": "from fastapi import FastAPI\napp = FastAPI()\n"
                   "@app.patch('/unknown')\nasync def x(): pass\n",
    })
    result = _run_lint(tmp_path)
    assert result.returncode == 1
    assert "PATCH /unknown" in result.stdout


# AC 7: unauthorized DELETE → exit 1
def test_unauthorized_delete_exits_1(tmp_path):
    _build_dashboard(tmp_path, {
        "main.py": "from fastapi import FastAPI\napp = FastAPI()\n"
                   "@app.delete('/unknown')\nasync def x(): pass\n",
    })
    result = _run_lint(tmp_path)
    assert result.returncode == 1
    assert "DELETE /unknown" in result.stdout


# AC 8: GET ignored
def test_get_route_ignored(tmp_path):
    _build_dashboard(tmp_path, {
        "main.py": "from fastapi import FastAPI\napp = FastAPI()\n"
                   "@app.get('/acknowledgements')\nasync def x(): pass\n",
    })
    result = _run_lint(tmp_path)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"


# AC 9: router decorator pattern
def test_router_decorator_exits_1_for_unauthorized(tmp_path):
    _build_dashboard(tmp_path, {
        "router.py": "from fastapi import APIRouter\nrouter = APIRouter()\n"
                     "@router.post('/foo')\nasync def x(): pass\n",
    })
    result = _run_lint(tmp_path)
    assert result.returncode == 1
    assert "POST /foo" in result.stdout


# AC 10: decorator stack (classmethod + app.post)
def test_decorator_stack_with_classmethod(tmp_path):
    _build_dashboard(tmp_path, {
        "views.py": "from fastapi import FastAPI\napp = FastAPI()\n"
                    "class V:\n"
                    "    @classmethod\n"
                    "    @app.post('/foo')\n"
                    "    async def cm(cls): pass\n",
    })
    result = _run_lint(tmp_path)
    assert result.returncode == 1
    assert "POST /foo" in result.stdout


# AC 11: empty path → exit 1 + empty_path
def test_empty_path_exits_1(tmp_path):
    _build_dashboard(tmp_path, {
        "main.py": "from fastapi import FastAPI\napp = FastAPI()\n"
                   "@app.post('')\nasync def x(): pass\n",
    })
    result = _run_lint(tmp_path)
    assert result.returncode == 1
    assert "empty_path" in result.stdout


# AC 12: non-string path → exit 1 + non_string_path
def test_non_string_path_exits_1(tmp_path):
    _build_dashboard(tmp_path, {
        "main.py": "from fastapi import FastAPI\napp = FastAPI()\n"
                   "SOME_CONSTANT = '/literal-path'\n"
                   "@app.post(SOME_CONSTANT)\nasync def x(): pass\n",
    })
    result = _run_lint(tmp_path)
    assert result.returncode == 1
    assert "non_string_path" in result.stdout


# Coverage: --allowlist override (empty list) catches all writes
def test_empty_allowlist_override_catches_everything(tmp_path):
    _build_dashboard(tmp_path, {
        "main.py": "from fastapi import FastAPI\napp = FastAPI()\n"
                   "@app.post('/acknowledgements')\nasync def x(): pass\n",
    })
    result = _run_lint(tmp_path, "--allowlist", "")
    assert result.returncode == 1
    assert "POST /acknowledgements" in result.stdout


# Coverage: missing dashboard directory → exit 0 (vacuously clean)
def test_missing_dashboard_dir_exits_0(tmp_path):
    # No dashboard/ in tmp_path at all.
    result = _run_lint(tmp_path)
    assert result.returncode == 0
