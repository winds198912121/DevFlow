"""Shared fixtures for the test suite."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# Ensure the project root is on sys.path so `from harness...` resolves.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest  # noqa: E402  (after the sys.path bootstrap)


# --- Project YAML fixtures -------------------------------------------------


#: `size: trivial` — FR-12's skipped-Gate tier: every step resolves to
#: Done/gate_mode=skipped without an Acknowledgement.
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

#: `size: epic` — the Gate is enforced, so steps stay Pending until an
#: Acknowledgement locks them.
EPIC_YAML = TRIVIAL_YAML.replace("size: trivial", "size: epic")


# --- Dashboard harness -----------------------------------------------------


@dataclass
class DashboardHarness:
    """A dashboard wired to isolated stores, plus a client over the real app.

    The dashboard suites (API + SPA) share this. Each test gets its own temp
    stores: `serve --demo` and the CLI write to the real `var/` tree, so a test
    that reused it would corrupt unrelated state.
    """

    client: object  # fastapi.testclient.TestClient
    service: object  # HarnessDashboardService
    projects_root: Path
    core_db: Path
    devflow_db: Path

    def add_project(self, project_id: str, yaml_text: str = TRIVIAL_YAML) -> None:
        target = self.projects_root / project_id
        target.mkdir(parents=True, exist_ok=True)
        (target / "project.yaml").write_text(yaml_text, encoding="utf-8")

    def add_run(self, project_id: str, run_id: str,
                steps: tuple[str, ...] = ("research",)) -> None:
        for step in steps:
            (self.projects_root / project_id / "runs" / run_id / step).mkdir(
                parents=True, exist_ok=True
            )

    def post(self, url: str, payload: dict, *, sign: bool = True,
             signature: str | None = None):
        """POST a write path, signing the payload with the harness key."""
        from harness import signing

        headers = {}
        if signature is not None:
            headers["X-Harness-Signature"] = signature
        elif sign:
            headers["X-Harness-Signature"] = signing.sign(payload).hex()
        return self.client.post(url, json=payload, headers=headers)


@pytest.fixture
def dashboard(tmp_path, monkeypatch) -> DashboardHarness:
    from fastapi.testclient import TestClient

    from dashboard.main import create_app
    from harness import acknowledgement_store, project_manager
    from harness.dashboard_service import HarnessDashboardService

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
    return DashboardHarness(
        client=TestClient(create_app(service)),
        service=service,
        projects_root=projects_root,
        core_db=core_db,
        devflow_db=devflow_db,
    )
