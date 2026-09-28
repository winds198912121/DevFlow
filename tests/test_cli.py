"""Tests for harness.cli (Story 2.10 tracer bullet).

The CLI is thin: every command line calls into existing modules. These
tests run the verify-line command end-to-end via Typer's `CliRunner`.
"""

from __future__ import annotations

import shutil

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.delivery import PROJECT_ROOT


runner = CliRunner()


@pytest.fixture(autouse=True)
def _stub_input(monkeypatch: pytest.MonkeyPatch):
    """Stub `builtins.input` so the human adapter's `start()` doesn't block."""
    monkeypatch.setattr("builtins.input", lambda prompt="": "cli-input")


@pytest.fixture(autouse=True)
def _clean_var():
    """Reset var/ between CLI tests."""
    projects = PROJECT_ROOT / "var" / "projects"
    if projects.exists():
        shutil.rmtree(projects)
    yield
    if projects.exists():
        shutil.rmtree(projects)


def test_check_baseline_exits_zero():
    result = runner.invoke(app, ["check-baseline"])
    assert result.exit_code == 0, result.stdout


def test_run_command_exits_zero_on_python_hello():
    result = runner.invoke(
        app,
        [
            "run",
            "--project", "tests/fixtures/sample-projects/python-hello",
            "--run-id", "R_CLI_1",
        ],
    )
    assert result.exit_code == 0, result.stdout
    # Six locked artifacts in the artifacts table.
    import sqlite3
    db = sqlite3.connect(":memory:")
    from harness.migrate import run_migrations
    run_migrations(db)
    # Re-run the project to read the artifacts table — but the in-memory DB
    # the CLI used is gone. Instead, check the disk-side state.
    run_dir = PROJECT_ROOT / "var" / "projects" / "python-hello" / "runs" / "R_CLI_1"
    assert run_dir.exists()
    markers = list(run_dir.glob("*/.locked"))
    assert len(markers) == 6
    # Acknowledgements written.
    ack_root = PROJECT_ROOT / "acknowledgements" / "python-hello" / "R_CLI_1"
    if ack_root.exists():
        ack_files = list(ack_root.glob("*/*.json"))
        assert len(ack_files) == 6
    # delivery.json written.
    delivery_path = run_dir / "delivery.json"
    assert delivery_path.exists()


def test_run_command_cross_invocation_idempotency():
    """A second `harness run` with the same --run-id short-circuits all steps."""
    args1 = [
        "run",
        "--project", "tests/fixtures/sample-projects/python-hello",
        "--run-id", "R_CLI_2",
    ]
    args2 = list(args1)  # same --run-id

    r1 = runner.invoke(app, args1)
    assert r1.exit_code == 0, r1.stdout

    # Capture the artifact hashes after the first run.
    run_dir = PROJECT_ROOT / "var" / "projects" / "python-hello" / "runs" / "R_CLI_2"
    assert run_dir.exists()
    hashes_after_first = {
        (p.parent.name, p.read_text(encoding="utf-8"))
        for p in run_dir.glob("*/.locked")
    }

    r2 = runner.invoke(app, args2)
    assert r2.exit_code == 0, r2.stdout
    # The marker files were not re-written (same content).
    hashes_after_second = {
        (p.parent.name, p.read_text(encoding="utf-8"))
        for p in run_dir.glob("*/.locked")
    }
    assert hashes_after_first == hashes_after_second


def test_run_command_missing_project_exits_nonzero():
    result = runner.invoke(
        app,
        [
            "run",
            "--project", "/nonexistent/path",
            "--run-id", "R_CLI_3",
        ],
    )
    assert result.exit_code != 0
    assert "project_not_found" in (result.stdout + (result.stderr or ""))


def test_swap_command_happy_path():
    import json
    prev = json.dumps({"mode": "human", "agent": None, "model": None, "skills": []})
    new = json.dumps({"mode": "agent", "agent": "codex", "model": "gpt-5", "skills": []})
    result = runner.invoke(
        app,
        [
            "swap",
            "--project", "p_swap_cli",
            "--prev", prev,
            "--new", new,
            "--intent", "cli test",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "swap OK" in result.stdout



# --- --inject-failure-at: the retry ladder's only production caller --------


@pytest.fixture
def _clean_error_store():
    """Reset the Error Store so rung assertions see only this test's rows."""
    from harness.error_store import DEFAULT_DB

    def _wipe():
        for p in (DEFAULT_DB, DEFAULT_DB.with_suffix(".sqlite-wal"),
                  DEFAULT_DB.with_suffix(".sqlite-shm")):
            if p.exists():
                p.unlink()

    _wipe()
    yield
    _wipe()


def test_inject_failure_at_records_a_rung_and_still_exits_zero(_clean_error_store):
    """Story 3.10's first verify clause.

    Injecting a failure at `coding` must not abort the run: the ladder absorbs
    it and the command still exits 0, having recorded the attempt.
    """
    from harness.error_store import query

    result = runner.invoke(
        app,
        [
            "run",
            "--project", "tests/fixtures/sample-projects/python-hello",
            "--run-id", "R_INJECT_1",
            "--inject-failure-at", "coding",
        ],
    )
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    assert "injected failure at coding" in result.stdout
    # The run completed all six steps despite the injected failure.
    assert "steps=6 OK" in result.stdout

    records = query("python-hello")
    assert len(records) == 1
    record = records[0]
    assert record.step == "coding"
    assert record.retry[0]["rung"] == 1
    assert record.retry[0]["result"] == "fail"


def test_inject_failure_at_delivery_records_a_valid_category(_clean_error_store):
    """The `delivery` step must reach the Error Store, not raise.

    Regression guard for the step→category mapping: the hand-copied map returned
    `delivery`, which is a pipeline step but not one of the closed Error Store
    categories, so the ladder raised `InvalidErrorCategory` for the last step.
    """
    from harness.error_store import _VALID_CATEGORIES, query

    result = runner.invoke(
        app,
        [
            "run",
            "--project", "tests/fixtures/sample-projects/python-hello",
            "--run-id", "R_INJECT_2",
            "--inject-failure-at", "delivery",
        ],
    )
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    records = query("python-hello")
    assert len(records) == 1
    assert records[0].step == "delivery"
    assert records[0].category in _VALID_CATEGORIES


def test_inject_failure_at_does_nothing_without_the_flag(_clean_error_store):
    from harness.error_store import query

    result = runner.invoke(
        app,
        [
            "run",
            "--project", "tests/fixtures/sample-projects/python-hello",
            "--run-id", "R_INJECT_3",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "injected failure" not in result.stdout
    assert query("python-hello") == ()


def test_inject_failure_at_unknown_step_is_refused(_clean_error_store):
    result = runner.invoke(
        app,
        [
            "run",
            "--project", "tests/fixtures/sample-projects/python-hello",
            "--run-id", "R_INJECT_4",
            "--inject-failure-at", "nope",
        ],
    )
    assert result.exit_code == 2
    combined = result.stdout + (result.stderr or "")
    assert "unknown_step" in combined
