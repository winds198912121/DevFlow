"""Dashboard backend tests — Stories 4.3, 4.5, 4.6, 4.7, 4.11.

Almost every test drives the real FastAPI app through `TestClient` rather than
calling `HarnessDashboardService` directly: the ACs are stated in terms of the
HTTP surface (status codes, 401 on unsigned writes, refusal codes), and the
transport is where the signature gate lives. A handful of tests reach for the
service object directly to prove the port is usable without HTTP.

Each test builds its own stores under `tmp_path`. The dashboard must never be
tested against the real `var/` tree: `serve --demo` and the CLI share it, so a
test that wrote there would corrupt unrelated state.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness import (
    acknowledgement_store,
    error_store,
    project_manager,
    run_event_log,
    signing,
    skill_bump_registry,
)
from harness.dashboard_service import HarnessDashboardService

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PROJECT = Path("tests/fixtures/sample-projects/python-hello/project.yaml")
REGRESSION_FIXTURE = Path("tests/fixtures/regression-set/python-hello-4-runs/load.py")

TRIVIAL_YAML = """
pipeline: software-v1
pipeline_version: 1
size: trivial
steps:
  research:
    mode: human
  design:
    mode: human
  coding:
    mode: human
  testing:
    mode: human
  review:
    mode: human
  delivery:
    mode: human
""".lstrip()

EPIC_YAML = TRIVIAL_YAML.replace("size: trivial", "size: epic")

STEP_ORDER = ("research", "design", "coding", "testing", "review", "delivery")
AD21_WRITE_ROUTES = frozenset(
    {
        ("POST", "/acknowledgements"),
        ("POST", "/swap-executor"),
        ("POST", "/skill-bump-regression"),
        ("POST", "/skill-bump-promote"),
        ("POST", "/cost-overrun-ack"),
        ("POST", "/regression-set-remove"),
        ("POST", "/project-edit-lock"),
    }
)


# --- Fixtures --------------------------------------------------------------


class Dashboard:
    """A wired dashboard over isolated stores."""

    def __init__(self, client: TestClient, service: HarnessDashboardService,
                 projects_root: Path, core_db: Path, devflow_db: Path) -> None:
        self.client = client
        self.service = service
        self.projects_root = projects_root
        self.core_db = core_db
        self.devflow_db = devflow_db

    def add_project(self, project_id: str, yaml_text: str = TRIVIAL_YAML) -> None:
        target = self.projects_root / project_id
        target.mkdir(parents=True, exist_ok=True)
        (target / "project.yaml").write_text(yaml_text, encoding="utf-8")

    def add_run(self, project_id: str, run_id: str, steps: tuple[str, ...] = ("research",)) -> None:
        for step in steps:
            (self.projects_root / project_id / "runs" / run_id / step).mkdir(
                parents=True, exist_ok=True
            )

    def post(self, url: str, payload: dict, *, sign: bool = True,
             signature: str | None = None) -> object:
        headers = {}
        if signature is not None:
            headers["X-Harness-Signature"] = signature
        elif sign:
            headers["X-Harness-Signature"] = signing.sign(payload).hex()
        return self.client.post(url, json=payload, headers=headers)


@pytest.fixture
def dash(tmp_path, monkeypatch) -> Dashboard:
    from dashboard.main import create_app

    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    # `project_manager` resolves project YAML through a module global, so the
    # read model's size lookup only sees the temp tree if it is patched too.
    monkeypatch.setattr(project_manager, "PROJECTS_DIR", projects_root)
    # The Acknowledgement store is filesystem-backed with a module-global root.
    monkeypatch.setattr(
        acknowledgement_store, "ACKNOWLEDGEMENTS_DIR", tmp_path / "acknowledgements"
    )
    core_db = tmp_path / "harness.sqlite"
    devflow_db = tmp_path / "devflow.sqlite"
    service = HarnessDashboardService(
        projects_root=projects_root, core_db=core_db, devflow_db=devflow_db
    )
    client = TestClient(create_app(service))
    return Dashboard(client, service, projects_root, core_db, devflow_db)


# --- Story 4.3: read endpoints --------------------------------------------


def test_runs_is_empty_when_no_run_directories_exist(dash):
    assert dash.client.get("/runs").json() == {"runs": []}


def test_list_and_get_run_return_the_ad24_step_status_shape(dash):
    dash.add_project("python-hello")
    dash.add_run("python-hello", "R1")

    listing = dash.client.get("/runs").json()
    assert [r["run_id"] for r in listing["runs"]] == ["R1"]

    detail = dash.client.get("/runs/R1", params={"project_id": "python-hello"}).json()
    assert detail["project_id"] == "python-hello"
    assert detail["size"] == "trivial"
    assert [s["step"] for s in detail["steps"]] == list(STEP_ORDER)
    for status in detail["steps"]:
        assert status["terminal"] in {"Done", "Locked", "Pending", "Failed"}
        assert status["gate_mode"] in {"enforced", "skipped"}


def test_step_status_comes_from_the_single_ad24_resolver(dash):
    """AD-24 (a): the dashboard must not compute terminal status itself.

    Asserted by equivalence against the resolver, not by pinning a literal: if
    the API ever grew its own rule, the two would diverge on some input.
    """
    from harness.workflow_controller import step_status

    dash.add_project("python-hello", EPIC_YAML)
    dash.add_run("python-hello", "R1")

    detail = dash.client.get("/runs/R1", params={"project_id": "python-hello"}).json()
    conn = sqlite3.connect(":memory:")
    expected = {s: step_status(conn, "python-hello", "R1", s, project_size="epic")
                for s in STEP_ORDER}
    conn.close()
    for status in detail["steps"]:
        want = expected[status["step"]]
        assert (status["terminal"], status["gate_mode"]) == (want.terminal, want.gate_mode)
    # An epic-size project with no Acknowledgement is Pending under the Gate.
    assert {s["terminal"] for s in detail["steps"]} == {"Pending"}


def test_acknowledgement_locks_the_step_through_the_run_endpoint(dash):
    dash.add_project("python-hello", EPIC_YAML)
    dash.add_run("python-hello", "R1")
    acknowledgement_store.write(
        "python-hello", "R1", "research", "mei@team", "human", "accepted",
        acknowledgement_store.ArtifactRef(
            step="research", project_id="python-hello", run_id="R1",
            hash="sha256:" + "a" * 64,
        ),
    )
    detail = dash.client.get("/runs/R1", params={"project_id": "python-hello"}).json()
    by_step = {s["step"]: s for s in detail["steps"]}
    assert by_step["research"]["terminal"] == "Locked"
    assert by_step["design"]["terminal"] == "Pending"


def test_trivial_tier_skips_the_gate(dash):
    dash.add_project("python-hello")
    dash.add_run("python-hello", "R1")
    detail = dash.client.get("/runs/R1", params={"project_id": "python-hello"}).json()
    assert {s["terminal"] for s in detail["steps"]} == {"Done"}
    assert {s["gate_mode"] for s in detail["steps"]} == {"skipped"}


def test_unknown_run_id_returns_404(dash):
    response = dash.client.get("/runs/nope")
    assert response.status_code == 404
    assert response.json()["error"] == "run_not_found"


def test_run_id_in_two_projects_is_ambiguous_without_project_id(dash):
    dash.add_project("alpha")
    dash.add_project("beta")
    dash.add_run("alpha", "R1")
    dash.add_run("beta", "R1")
    ambiguous = dash.client.get("/runs/R1")
    assert ambiguous.status_code == 409
    assert ambiguous.json()["error"] == "run_ambiguous"
    # Naming the project disambiguates.
    assert dash.client.get("/runs/R1", params={"project_id": "beta"}).json()["project_id"] == "beta"


def test_read_endpoints_return_expected_shapes_on_the_fixture(dash):
    """The Story 4.3 verify line: each read endpoint answers on python-hello."""
    dash.add_project("python-hello", EPIC_YAML)
    dash.add_run("python-hello", "R1", steps=STEP_ORDER)
    _seed_regression_fixture(dash.core_db)

    assert dash.client.get("/runs").status_code == 200
    assert dash.client.get("/runs/R1", params={"project_id": "python-hello"}).status_code == 200
    errors = dash.client.get("/projects/python-hello/errors").json()
    assert errors["project_id"] == "python-hello"
    assert errors["errors"] == []
    bench = dash.client.get(
        "/bench/coding", params={"tier": "trivial", "contract": "v1"}
    ).json()
    assert set(bench) == {
        "step", "project_size_tier", "artifact_contract_version",
        "metric_definition", "metric_summary", "contributing_runs",
    }


# --- Story 4.3: write endpoint surface + signature gate -------------------


def test_write_route_surface_is_exactly_the_ad21_seven(dash):
    registered = set()
    for route in dash.service and dash.client.app.routes:
        methods = getattr(route, "methods", set()) or set()
        for method in methods & {"POST", "PUT", "PATCH", "DELETE"}:
            registered.add((method, route.path))
    assert registered == AD21_WRITE_ROUTES


@pytest.mark.parametrize(
    "url,payload",
    [
        ("/cost-overrun-ack", {"project_id": "python-hello"}),
        ("/skill-bump-regression", {"skill_name": "bmad-build", "new_version": "2",
                                    "previous_version": "1"}),
        ("/regression-set-remove", {"run_event_id": "does-not-exist",
                                    "reason": "not comparable"}),
        ("/swap-executor", {"project_id": "python-hello", "edited_by": "mei@team",
                            "prev_executor_tuple": "a", "new_executor_tuple": "b",
                            "intent": "swap"}),
        ("/project-edit-lock", {"project_id": "python-hello", "edited_by": "mei@team",
                                "new_yaml": TRIVIAL_YAML}),
        ("/acknowledgements", {
            "project_id": "python-hello", "run_id": "R1", "step": "research",
            "acknowledger": "mei@team", "acknowledger_kind": "human",
            "verdict": "accepted",
            "artifact_ref": {"step": "research", "project_id": "python-hello",
                             "run_id": "R1", "hash": "sha256:" + "a" * 64},
        }),
        ("/skill-bump-promote", {"bump_id": "nope", "regression_run_id": "R"}),
    ],
)
def test_each_write_endpoint_accepts_a_valid_signed_request(dash, url, payload):
    dash.add_project("python-hello", EPIC_YAML)
    dash.add_run("python-hello", "R1")
    if url == "/swap-executor":
        # The swap refuses identical tuples; give it a real YAML to hash.
        payload["prev_executor_tuple"] = '{"agent": "human"}'
        payload["new_executor_tuple"] = '{"agent": "pi"}'
    response = dash.post(url, payload)
    assert response.status_code != 401, response.text
    # A signed, well-formed request reaches the handler: it either succeeds or
    # fails for a domain reason (never for transport/auth reasons).
    assert response.status_code in {200, 400, 404, 409, 422}, response.text


def test_write_without_a_signature_returns_401(dash):
    dash.add_project("python-hello")
    response = dash.post("/cost-overrun-ack", {"project_id": "python-hello"}, sign=False)
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "invalid_harness_signature"


def test_write_with_a_garbage_signature_returns_401(dash):
    response = dash.post("/cost-overrun-ack", {"project_id": "python-hello"},
                         signature="not-hex")
    assert response.status_code == 401


def test_signature_is_bound_to_the_exact_payload(dash):
    """A signature over one body must not authorize a different body."""
    signed = {"project_id": "python-hello"}
    signature = signing.sign(signed).hex()
    tampered = {"project_id": "some-other-project"}
    response = dash.post("/cost-overrun-ack", tampered, signature=signature)
    assert response.status_code == 401


def test_cost_overrun_ack_clears_the_pause(dash):
    """AD-8: the ack is what resumes a cost-paused project."""
    from harness import cost_guard
    from harness.cost_ledger import append as cost_append

    cost_guard.set_override("python-hello", 1, db=dash.core_db)
    cost_append("python-hello", run_id="R1", step="coding", tokens_in=10,
                tokens_out=10, db=dash.core_db)
    assert cost_guard.check("python-hello", db=dash.core_db) == "pause"
    assert cost_guard.is_paused("python-hello", db=dash.core_db) is True

    response = dash.post("/cost-overrun-ack", {"project_id": "python-hello"})
    assert response.status_code == 200, response.text
    assert response.json() == {"project_id": "python-hello", "paused": False}
    assert cost_guard.is_paused("python-hello", db=dash.core_db) is False


# --- Story 4.11: project_edit_lock ----------------------------------------


def test_project_edit_returns_both_hashes_and_commits_the_new_yaml(dash):
    dash.add_project("python-hello")
    edited = TRIVIAL_YAML.replace("size: trivial", "size: session")
    response = dash.post("/project-edit-lock", {
        "project_id": "python-hello", "edited_by": "mei@team", "new_yaml": edited,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["prev_yaml_hash"].startswith("sha256:")
    assert body["new_yaml_hash"].startswith("sha256:")
    assert body["prev_yaml_hash"] != body["new_yaml_hash"]
    assert (dash.projects_root / "python-hello" / "project.yaml").read_text() == edited
    assert project_manager.load_project("python-hello").size == "session"


def test_concurrent_edit_is_refused_and_leaves_the_prior_yaml_untouched(dash):
    from harness import project_edit_lock

    dash.add_project("python-hello")
    original = (dash.projects_root / "python-hello" / "project.yaml").read_text()
    # Hold the lock, as a concurrent editor would for the edit's duration.
    project_edit_lock.acquire("python-hello", "other@team", db=dash.devflow_db)

    response = dash.post("/project-edit-lock", {
        "project_id": "python-hello", "edited_by": "mei@team",
        "new_yaml": TRIVIAL_YAML.replace("size: trivial", "size: session"),
    })
    assert response.status_code == 409
    assert response.json()["error"] == "project_edit_lock_held"
    assert (dash.projects_root / "python-hello" / "project.yaml").read_text() == original


def test_project_edit_releases_the_lock_on_success(dash):
    from harness import project_edit_lock

    dash.add_project("python-hello")
    dash.post("/project-edit-lock", {
        "project_id": "python-hello", "edited_by": "mei@team", "new_yaml": TRIVIAL_YAML,
    })
    # A second edit must be able to acquire; if the first leaked the lock this
    # raises LockHeld.
    project_edit_lock.acquire("python-hello", "mei@team", db=dash.devflow_db)


def test_project_edit_refuses_malformed_yaml_without_taking_the_lock(dash):
    from harness import project_edit_lock

    dash.add_project("python-hello")
    response = dash.post("/project-edit-lock", {
        "project_id": "python-hello", "edited_by": "mei@team",
        "new_yaml": "this: is: not: valid: yaml:",
    })
    assert response.status_code == 422
    assert response.json()["error"] == "project_yaml_invalid"
    # The refusal happened before acquisition, so the lock is still free.
    project_edit_lock.acquire("python-hello", "mei@team", db=dash.devflow_db)


def test_project_edit_unknown_project_returns_404(dash):
    response = dash.post("/project-edit-lock", {
        "project_id": "ghost", "edited_by": "mei@team", "new_yaml": TRIVIAL_YAML,
    })
    assert response.status_code == 404
    assert response.json()["error"] == "project_not_found"


# --- Story 4.5: error filters --------------------------------------------


def _seed_errors(dash) -> None:
    dash.add_project("python-hello", EPIC_YAML)
    dash.add_run("python-hello", "R1", steps=STEP_ORDER)
    for idx, (run_id, step, category, recorded_at, executor) in enumerate([
        ("R1", "coding", "coding", "2026-01-01T00:00:00+00:00", "claude"),
        ("R1", "testing", "testing", "2026-02-01T00:00:00+00:00", "gemini"),
        ("R2", "coding", "llm", "2026-03-01T00:00:00+00:00", "claude"),
    ]):
        error_store.append(
            error_store.ErrorRecord(
                record_id=f"rec{idx}", project_id="python-hello", run_id=run_id,
                step=step, attempt=1, category=category, root_cause=("cause",),
                correction=(), result="fail", recorded_at=recorded_at,
                retry=({"rung": 1, "executor_tuple": str({"agent": executor,
                                                          "model": "large",
                                                          "skills": ["bmad-build"]}),
                        "result": "failed", "timestamp": recorded_at},),
            ),
            db=dash.core_db,
        )


def test_empty_filter_set_returns_every_error_for_the_project(dash):
    _seed_errors(dash)
    body = dash.client.get("/projects/python-hello/errors").json()
    assert body["count"] == 3
    assert len(body["errors"]) == 3


def test_error_filters_compose_with_and_not_or(dash):
    _seed_errors(dash)
    both = dash.client.get(
        "/projects/python-hello/errors", params={"step": "coding", "run_id": "R1"}
    ).json()
    assert both["count"] == 1
    assert both["errors"][0]["step"] == "coding"
    # The OR reading would have returned 3 (two coding rows, two R1 rows).
    assert both["count"] != 3


def test_single_dimension_filters(dash):
    _seed_errors(dash)
    by_step = dash.client.get(
        "/projects/python-hello/errors", params={"step": "coding"}
    ).json()
    assert by_step["count"] == 2
    by_category = dash.client.get(
        "/projects/python-hello/errors", params={"category": "llm"}
    ).json()
    assert by_category["count"] == 1
    by_run = dash.client.get(
        "/projects/python-hello/errors", params={"run_id": "R2"}
    ).json()
    assert by_run["count"] == 1


def test_date_range_filter_is_inclusive(dash):
    _seed_errors(dash)
    windowed = dash.client.get(
        "/projects/python-hello/errors",
        params={"since": "2026-02-01T00:00:00+00:00", "until": "2026-03-01T00:00:00+00:00"},
    ).json()
    assert windowed["count"] == 2
    assert {e["recorded_at"] for e in windowed["errors"]} == {
        "2026-02-01T00:00:00+00:00", "2026-03-01T00:00:00+00:00"
    }


def test_executor_tuple_filter_matches_agent_and_model(dash):
    _seed_errors(dash)
    by_agent = dash.client.get(
        "/projects/python-hello/errors", params={"executor_tuple": "claude"}
    ).json()
    assert by_agent["count"] == 2
    by_model = dash.client.get(
        "/projects/python-hello/errors", params={"executor_tuple": "large"}
    ).json()
    assert by_model["count"] == 3
    by_skill = dash.client.get(
        "/projects/python-hello/errors", params={"executor_tuple": "bmad-build"}
    ).json()
    assert by_skill["count"] == 3
    no_match = dash.client.get(
        "/projects/python-hello/errors", params={"executor_tuple": "gpt5"}
    ).json()
    assert no_match["count"] == 0


def test_category_outside_the_closed_enum_is_named_not_silently_empty(dash):
    response = dash.client.get(
        "/projects/python-hello/errors", params={"category": "typo"}
    )
    assert response.status_code == 400
    assert response.json()["error"] == "category_not_found"


def test_unknown_filter_key_is_refused(dash):
    response = dash.client.get(
        "/projects/python-hello/errors", params={"catagory": "coding"}
    )
    assert response.status_code == 400
    assert response.json()["error"] == "unknown_filter"


def test_ten_thousand_errors_answer_within_the_perf_budget(dash):
    """NFR-Perf-2: the filter surface answers in <= 1s for 10,000 records."""
    import time

    dash.add_project("python-hello", EPIC_YAML)
    conn = sqlite3.connect(dash.core_db)
    error_store._ensure_table(conn)  # match the store's own DDL
    conn.executemany(
        "INSERT INTO error_records (record_id, project_id, run_id, step, attempt, "
        "category, root_cause_json, correction_json, retry_json, result, "
        "recorded_at, hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (f"rec{i:06d}", "python-hello", "R1", "coding", 1, "coding",
             '["c"]', "[]",
             '[{"rung": 1, "executor_tuple": "{\'agent\': \'claude\', '
             '\'model\': \'large\', \'skills\': []}", "result": "failed"}]',
             "fail", f"2026-01-01T00:00:{i % 60:02d}+00:00", "sha256:x")
            for i in range(10_000)
        ],
    )
    conn.commit()
    conn.close()

    start = time.perf_counter()
    body = dash.client.get(
        "/projects/python-hello/errors", params={"step": "coding"}
    ).json()
    elapsed = time.perf_counter() - start
    assert body["count"] == 10_000
    assert elapsed <= 1.0, f"filter surface took {elapsed:.3f}s for 10k records"


# --- Story 4.6: regression diff ------------------------------------------


def _seed_bump(dash, regression_run_id: str | None) -> str:
    bump = skill_bump_registry.register(
        "bmad-build", "2.0", "1.0", registered_by="test", db=dash.core_db
    )
    if regression_run_id is not None:
        conn = sqlite3.connect(dash.core_db)
        conn.execute("UPDATE skill_bumps SET regression_run_id = ? WHERE bump_id = ?",
                     (regression_run_id, bump.bump_id))
        conn.commit()
        conn.close()
    return bump.bump_id


def _seed_run_events(dash, run_id: str, outcomes: dict[str, list[str]]) -> None:
    from datetime import datetime, timezone

    for step, step_outcomes in outcomes.items():
        for idx, outcome in enumerate(step_outcomes):
            run_event_log.write(
                run_event_log.RunEvent(
                    event_id=f"{step}-{idx}".upper(), project_id="python-hello",
                    run_id=run_id, step=step, executor_tuple="{}",
                    executor_tuple_hash="sha256:" + "b" * 64,
                    started_at=datetime.now(timezone.utc).isoformat(),
                    ended_at=datetime.now(timezone.utc).isoformat(),
                    outcome=outcome,
                ),
                db=dash.devflow_db,
            )


def test_regression_diff_renders_per_step_pass_fail_counts(dash):
    dash.add_project("python-hello", EPIC_YAML)
    bump_id = _seed_bump(dash, "REGRUN")
    _seed_run_events(dash, "REGRUN", {"coding": ["pass", "pass", "fail"],
                                      "testing": ["pass"]})
    body = dash.client.get(
        f"/projects/python-hello/regression-diff/{bump_id}"
    ).json()
    assert body["skill_name"] == "bmad-build"
    assert body["new_version"] == "2.0"
    by_step = {s["step"]: s for s in body["steps"]}
    assert (by_step["coding"]["passed"], by_step["coding"]["failed"]) == (2, 1)
    assert by_step["coding"]["total"] == 3
    assert (by_step["testing"]["passed"], by_step["testing"]["failed"]) == (1, 0)


def test_regression_diff_flags_non_comparable_steps(dash):
    """FR-18: a step with no live comparable run in the cell is flagged."""
    dash.add_project("python-hello", EPIC_YAML)  # tier=epic, no regression rows
    bump_id = _seed_bump(dash, "REGRUN")
    _seed_run_events(dash, "REGRUN", {"coding": ["pass"]})
    body = dash.client.get(
        f"/projects/python-hello/regression-diff/{bump_id}"
    ).json()
    assert body["comparable"] is False
    step = body["steps"][0]
    assert step["comparable"] is False
    assert step["non_comparable_reason"].startswith("insufficient_comparable_runs_at_tier")


def test_regression_diff_marks_comparable_when_the_cell_is_populated(dash):
    dash.add_project("python-hello")  # tier=trivial
    _seed_regression_fixture(dash.core_db)  # (coding, trivial, v1) x4
    bump_id = _seed_bump(dash, "REGRUN")
    _seed_run_events(dash, "REGRUN", {"coding": ["pass"]})
    body = dash.client.get(
        f"/projects/python-hello/regression-diff/{bump_id}"
    ).json()
    assert body["steps"][0]["comparable"] is True
    assert body["steps"][0]["non_comparable_reason"] is None


def test_regression_diff_unknown_bump_returns_404(dash):
    response = dash.client.get("/projects/python-hello/regression-diff/nope")
    assert response.status_code == 404
    assert response.json()["error"] == "bump_not_found"


# --- Story 4.7: benchmark output -----------------------------------------


def test_bench_returns_recommendation_metric_and_contributing_runs(dash):
    dash.add_project("python-hello")
    _seed_regression_fixture(dash.core_db)
    body = dash.client.get(
        "/bench/coding", params={"tier": "trivial", "contract": "v1"}
    ).json()
    assert body["step"] == "coding"
    assert body["project_size_tier"] == "trivial"
    assert body["artifact_contract_version"] == "v1"
    assert body["metric_definition"]
    assert body["metric_summary"] == pytest.approx(0.915)
    assert len(body["contributing_runs"]) == 4
    assert all("run_event_id" in r and "executor_tuple_hash" in r
               for r in body["contributing_runs"])


def test_bench_refuses_with_regression_set_insufficient_on_a_fresh_store(dash):
    response = dash.client.get("/bench/coding", params={"tier": "epic"})
    assert response.status_code == 409
    assert response.json()["error"] == "regression_set_insufficient"


# --- Helpers --------------------------------------------------------------


def _seed_regression_fixture(core_db: Path) -> None:
    """Load the Story 3.8 fixture into this dashboard's core store."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_regression_fixture_loader", PROJECT_ROOT / REGRESSION_FIXTURE
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.load(db=core_db)


# --- Story 4.3 verify: the CI lint rejects an eighth write ---------------


def test_an_eighth_write_route_fails_the_ci_lint(tmp_path):
    """The Story 4.3 verify line: the allowlist is enforced, not documented."""
    dashboard = tmp_path / "dashboard"
    dashboard.mkdir()
    (dashboard / "extra.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "\n"
        "@router.post('/not-allowed')\n"
        "def sneaky() -> None:\n"
        "    return None\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "tools/check_dashboard_writes.py",
         "--project-root", str(tmp_path), "--dashboard-root", "dashboard"],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "POST /not-allowed not in allowlist" in result.stdout
