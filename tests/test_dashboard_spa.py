"""Operator Dashboard SPA tests — Story 4.4.

The SPA is TypeScript built by Bun, so most of its coverage lives in
`dashboard/src/views.test.ts` (run by `bun test`). This module covers what
Python can prove about the SPA and cannot be proven there:

  * the built bundle exists and is served by the real app,
  * the AD-24 (d) lint rejects a view that computes status inline,
  * end-to-end agreement — a payload fetched from the real HTTP endpoint
    renders values that came from the endpoint, not from a fixture.

Bun is a documented build dependency (spine: Bun 1.4.2). Tests that need it
skip, rather than fail, when it is absent, so a Python-only environment can
still run the suite.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from harness import acknowledgement_store, error_store, run_event_log, skill_bump_registry
from tests.conftest import EPIC_YAML

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = PROJECT_ROOT / "dashboard"
TERMINAL_STATUS_LINT = PROJECT_ROOT / "tools" / "check_terminal_status.py"

needs_bun = pytest.mark.skipif(
    shutil.which("bun") is None, reason="bun (SPA build tool) is not installed"
)


def _run_bun(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bun", *args],
        cwd=str(DASHBOARD),
        capture_output=True,
        text=True,
        input=stdin,
    )


def _render(view: str, payload: dict) -> str:
    """Render a view from a payload through the real TypeScript module."""
    result = _run_bun("run", "render-cli.ts", view, stdin=json.dumps(payload))
    assert result.returncode == 0, result.stderr
    return result.stdout


# --- Build -----------------------------------------------------------------


@needs_bun
def test_spa_view_tests_pass():
    """The Story 4.4 verify line: the four views render what they are given."""
    result = _run_bun("test")
    assert result.returncode == 0, result.stdout + result.stderr
    # Bun prints its summary to stderr; assert on both streams.
    combined = result.stdout + result.stderr
    assert "0 fail" in combined
    assert "pass" in combined


@needs_bun
def test_build_emits_a_servable_bundle():
    result = _run_bun("run", "build")
    assert result.returncode == 0, result.stdout + result.stderr
    dist = DASHBOARD / "dist"
    assert (dist / "main.js").is_file()
    assert (dist / "index.html").is_file()
    assert (dist / "main.js").stat().st_size > 0


@needs_bun
def test_every_element_the_shell_looks_up_exists_in_index_html():
    """The shell's DOM lookups must match index.html.

    Derived from `REQUIRED_ELEMENTS` rather than a duplicated list: a renamed
    input otherwise fails only at click time in one tab, which is exactly how
    the filter inputs were first broken (the shell read
    `#input-filter-run_id` while the page declared `#filter-run_id`).
    """
    result = _run_bun(
        "-e",
        'const m = await import("./src/main.ts");'
        " console.log(JSON.stringify(m.REQUIRED_ELEMENTS));",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    required = json.loads(result.stdout)
    assert len(required) > 10, required  # the list must not silently shrink

    index = (DASHBOARD / "index.html").read_text(encoding="utf-8")
    present = set(re.findall(r'id="([^"]+)"', index))
    missing = sorted(set(required) - present)
    assert missing == [], f"index.html is missing element id(s): {missing}"


@needs_bun
def test_the_app_serves_the_built_spa(tmp_path, monkeypatch):
    """`dashboard_serve.build_app` mounts `dist/` at `/` (read the shell)."""
    from fastapi.testclient import TestClient

    _run_bun("run", "build")
    from tools.dashboard_serve import build_app

    app = build_app()
    client = TestClient(app)
    index = client.get("/")
    assert index.status_code == 200
    assert "DevFlow Operator Dashboard" in index.text
    # The four view tabs the shell wires up must be present.
    for tab in ("run-status", "error-store", "regression-diff", "benchmark-output"):
        assert f'id="tab-{tab}"' in index.text
    bundle = client.get("/main.js")
    assert bundle.status_code == 200
    assert len(bundle.text) > 0


# --- AD-24 (d) lint --------------------------------------------------------


def test_terminal_status_lint_passes_on_the_real_dashboard():
    result = subprocess.run(
        [sys.executable, str(TERMINAL_STATUS_LINT)],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_terminal_status_lint_rejects_a_view_that_computes_status(tmp_path):
    """The lint must fail both ways AD-24 (d) names, not just import the wrong thing."""
    view = tmp_path / "dashboard" / "src" / "bad-view.ts"
    view.parent.mkdir(parents=True)
    view.write_text(
        'import { resolveStatusInline } from "./gate-engine";\n'
        "export function render(row: { verdict: string }) {\n"
        '  return row.verdict === "accepted" ? "Locked" : "Pending";\n'
        "}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(TERMINAL_STATUS_LINT), "--project-root", str(tmp_path)],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "second status resolver" in result.stdout
    assert "raw status input 'verdict'" in result.stdout


def test_terminal_status_lint_ignores_comments_and_test_modules(tmp_path):
    """A view may *describe* the rule; a test module may build raw payloads."""
    src = tmp_path / "dashboard" / "src"
    src.mkdir(parents=True)
    (src / "views.test.ts").write_text(
        "const payload = { outcome: 'pass', verdict: 'accepted' };\n", encoding="utf-8"
    )
    (src / "view.ts").write_text(
        "// This view never reads verdict or outcome — it renders `terminal`.\n"
        "export const x = 1;\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(TERMINAL_STATUS_LINT), "--project-root", str(tmp_path)],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# --- End-to-end: endpoint payload -> view render --------------------------


@needs_bun
def test_run_status_view_renders_the_endpoints_own_values(dashboard):
    client = dashboard.client
    dashboard.add_project("python-hello", EPIC_YAML)
    dashboard.add_run("python-hello", "R1", steps=(
        "research", "design", "coding", "testing", "review", "delivery",
    ))
    acknowledgement_store.write(
        "python-hello", "R1", "research", "mei@team", "human", "accepted",
        acknowledgement_store.ArtifactRef(
            step="research", project_id="python-hello", run_id="R1",
            hash="sha256:" + "a" * 64,
        ),
    )

    payload = client.get("/runs/R1", params={"project_id": "python-hello"}).json()
    html = _render("run-status", payload)

    for status in payload["steps"]:
        assert status["step"] in html
        assert status["terminal"] in html
    # The acknowledgement the resolver saw is what the view shows.
    assert "Locked" in html


@needs_bun
def test_benchmark_output_view_renders_the_endpoints_own_values(dashboard):
    """Ticket 4.7: 'the dashboard's benchmark-output view renders the same'."""
    _seed_regression_fixture(dashboard.core_db)

    payload = dashboard.client.get(
        "/bench/coding", params={"tier": "trivial", "contract": "v1"}
    ).json()
    html = _render("benchmark-output", payload)

    assert payload["metric_definition"] in html
    assert str(payload["metric_summary"]) in html
    for run in payload["contributing_runs"]:
        assert run["run_event_id"] in html


@needs_bun
def test_regression_diff_view_renders_the_endpoints_own_values(dashboard):
    from datetime import datetime, timezone

    dashboard.add_project("python-hello", EPIC_YAML)
    bump = skill_bump_registry.register(
        "bmad-build", "2.0", "1.0", registered_by="test", db=dashboard.core_db
    )
    import sqlite3

    conn = sqlite3.connect(dashboard.core_db)
    conn.execute("UPDATE skill_bumps SET regression_run_id = ? WHERE bump_id = ?",
                 ("REGRUN", bump.bump_id))
    conn.commit()
    conn.close()
    for idx, outcome in enumerate(["pass", "pass", "fail"]):
        run_event_log.write(
            run_event_log.RunEvent(
                event_id=f"EV{idx}", project_id="python-hello", run_id="REGRUN",
                step="coding", executor_tuple="{}",
                executor_tuple_hash="sha256:" + "b" * 64,
                started_at=datetime.now(timezone.utc).isoformat(),
                ended_at=datetime.now(timezone.utc).isoformat(),
                outcome=outcome,
            ),
            db=dashboard.devflow_db,
        )

    payload = dashboard.client.get(
        f"/projects/python-hello/regression-diff/{bump.bump_id}"
    ).json()
    html = _render("regression-diff", payload)

    step = payload["steps"][0]
    assert step["step"] in html
    assert payload["skill_name"] in html
    assert payload["new_version"] in html
    assert "not comparable" in html  # tier=epic with no regression rows


@needs_bun
def test_error_store_view_renders_the_endpoints_own_values(dashboard):
    error_store.append(
        error_store.ErrorRecord(
            record_id="rec1", project_id="python-hello", run_id="R1", step="coding",
            attempt=1, category="coding", root_cause=("assertion failed",),
            correction=(), result="fail", recorded_at="2026-01-01T00:00:00+00:00",
            retry=(),
        ),
        db=dashboard.core_db,
    )
    payload = dashboard.client.get("/projects/python-hello/errors").json()
    html = _render("error-store", payload)

    assert "rec1" in html
    assert "assertion failed" in html
    assert "1 error(s)" in html


def _seed_regression_fixture(core_db: Path) -> None:
    """Load the Story 3.8 fixture into this harness's core store."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_regression_fixture_loader",
        PROJECT_ROOT / "tests/fixtures/regression-set/python-hello-4-runs/load.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.load(db=core_db)
