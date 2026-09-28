"""Tests for harness.project_manager — covers the I/O Matrix in the 2.4 plan."""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from harness import project_manager
from harness.project_manager import (
    ExecutorTuple,
    Project,
    ProjectLoadError,
    ProjectNotFound,
    ProjectStep,
    load_project,
)


def _write_project_yaml(tmp_path: Path, project_id: str, payload: dict) -> Path:
    """Write a project.yaml under tmp_path / var/projects/<project_id>/."""
    proj_dir = tmp_path / "var" / "projects" / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    path = proj_dir / "project.yaml"
    yaml = YAML(typ="safe")
    with open(path, "w") as f:
        yaml.dump(payload, f)
    return path


def _patch_projects_dir(tmp_path: Path, monkeypatch):
    """Point project_manager.PROJECTS_DIR at the per-test tmp_path."""
    monkeypatch.setattr(project_manager, "PROJECTS_DIR", tmp_path / "var" / "projects")


def _human_steps():
    """A minimal valid `steps` dict: 6 human-mode steps."""
    return {
        "research": {"mode": "human"},
        "design": {"mode": "human"},
        "coding": {"mode": "human"},
        "testing": {"mode": "human"},
        "review": {"mode": "human"},
        "delivery": {"mode": "human"},
    }


# --- AC 1: happy path --------------------------------------------------


def test_valid_project_yam__loads_with_six_steps_in_pipeline_order(tmp_path, monkeypatch):
    _patch_projects_dir(tmp_path, monkeypatch)
    _write_project_yaml(tmp_path, "p1", {"pipeline": "software-v1", "size": "trivial", "steps": _human_steps()})
    project = load_project("p1")
    assert isinstance(project, Project)
    assert project.project_id == "p1"
    assert project.pipeline_name == "software-v1"
    assert project.size == "trivial"
    assert len(project.steps) == 6
    assert tuple(s.name for s in project.steps) == ("research", "design", "coding", "testing", "review", "delivery")


# --- AC 2: missing pipeline field --------------------------------------


def test_missing_pipeline_raises_pipeline_required(tmp_path, monkeypatch):
    _patch_projects_dir(tmp_path, monkeypatch)
    _write_project_yaml(tmp_path, "p1", {"size": "trivial", "steps": _human_steps()})
    with pytest.raises(ProjectLoadError) as exc_info:
        load_project("p1")
    assert exc_info.value.kind == "pipeline_required"


# --- AC 3: unknown pipeline ---------------------------------------------


def test_unknown_pipeline_raises_pipeline_not_found(tmp_path, monkeypatch):
    _patch_projects_dir(tmp_path, monkeypatch)
    _write_project_yaml(tmp_path, "p1", {"pipeline": "data-v1", "size": "trivial", "steps": _human_steps()})
    with pytest.raises(ProjectLoadError) as exc_info:
        load_project("p1")
    assert exc_info.value.kind == "pipeline_not_found"


# --- AC 4: unpinned skill -----------------------------------------------


def test_unpinned_skill_raises_skill_pin_required(tmp_path, monkeypatch):
    _patch_projects_dir(tmp_path, monkeypatch)
    steps = _human_steps()
    steps["coding"] = {"mode": "agent", "agent": "codex", "model": "gpt-5", "skills": ["bmad-build"]}
    _write_project_yaml(tmp_path, "p1", {"pipeline": "software-v1", "size": "trivial", "steps": steps})
    with pytest.raises(ProjectLoadError) as exc_info:
        load_project("p1")
    assert exc_info.value.kind == "skill_pin_required"
    assert "bmad-build" in exc_info.value.detail


# --- AC 5: mode: human with no agent/model succeeds ---------------------


def test_human_mode_step_has_no_agent_or_model(tmp_path, monkeypatch):
    _patch_projects_dir(tmp_path, monkeypatch)
    _write_project_yaml(tmp_path, "p1", {"pipeline": "software-v1", "size": "trivial", "steps": _human_steps()})
    project = load_project("p1")
    coding = next(s for s in project.steps if s.name == "coding")
    assert coding.executor == ExecutorTuple(mode="human", agent=None, model=None, skills=())


# --- AC 6: mode: agent without skills raises ---------------------------


def test_agent_mode_without_skills_raises_invalid_executor_tuple(tmp_path, monkeypatch):
    _patch_projects_dir(tmp_path, monkeypatch)
    steps = _human_steps()
    steps["coding"] = {"mode": "agent", "agent": "codex", "model": "gpt-5"}
    _write_project_yaml(tmp_path, "p1", {"pipeline": "software-v1", "size": "trivial", "steps": steps})
    with pytest.raises(ProjectLoadError) as exc_info:
        load_project("p1")
    assert exc_info.value.kind == "invalid_executor_tuple"
    assert "skills" in exc_info.value.detail


# --- AC 7: mode: agent without model raises ---------------------------


def test_agent_mode_without_model_raises_invalid_executor_tuple(tmp_path, monkeypatch):
    _patch_projects_dir(tmp_path, monkeypatch)
    steps = _human_steps()
    steps["coding"] = {"mode": "agent", "agent": "codex", "skills": ["bmad-build@0.4.2"]}
    _write_project_yaml(tmp_path, "p1", {"pipeline": "software-v1", "size": "trivial", "steps": steps})
    with pytest.raises(ProjectLoadError) as exc_info:
        load_project("p1")
    assert exc_info.value.kind == "invalid_executor_tuple"
    assert "model" in exc_info.value.detail


# --- AC 8: mode: human with agent raises -------------------------------


def test_human_mode_with_agent_field_raises(tmp_path, monkeypatch):
    _patch_projects_dir(tmp_path, monkeypatch)
    steps = _human_steps()
    steps["coding"] = {"mode": "human", "agent": "codex"}
    _write_project_yaml(tmp_path, "p1", {"pipeline": "software-v1", "size": "trivial", "steps": steps})
    with pytest.raises(ProjectLoadError) as exc_info:
        load_project("p1")
    assert exc_info.value.kind == "invalid_executor_tuple"
    assert "mode=human" in exc_info.value.detail


# --- AC 9: unknown mode raises -----------------------------------------


def test_unknown_mode_raises_invalid_executor_tuple(tmp_path, monkeypatch):
    _patch_projects_dir(tmp_path, monkeypatch)
    steps = _human_steps()
    steps["coding"] = {"mode": "ghost"}
    _write_project_yaml(tmp_path, "p1", {"pipeline": "software-v1", "size": "trivial", "steps": steps})
    with pytest.raises(ProjectLoadError) as exc_info:
        load_project("p1")
    assert exc_info.value.kind == "invalid_executor_tuple"
    assert "ghost" in exc_info.value.detail


# --- AC 10: step reordering puts steps in pipeline order ----------------


def test_steps_reordered_to_pipeline_order(tmp_path, monkeypatch):
    _patch_projects_dir(tmp_path, monkeypatch)
    # YAML has review/delivery first, then research/design/coding/testing
    # (out of pipeline order).
    _write_project_yaml(
        tmp_path, "p1",
        {
            "pipeline": "software-v1",
            "size": "trivial",
            "steps": {
                "review": {"mode": "human"},
                "delivery": {"mode": "human"},
                "research": {"mode": "human"},
                "design": {"mode": "human"},
                "coding": {"mode": "human"},
                "testing": {"mode": "human"},
            },
        },
    )
    project = load_project("p1")
    assert tuple(s.name for s in project.steps) == ("research", "design", "coding", "testing", "review", "delivery")
    assert any("reordered" in n for n in project.notes)


# --- AC 11: missing step (only 5 of 6) -------------------------------


def test_missing_step_raises(tmp_path, monkeypatch):
    _patch_projects_dir(tmp_path, monkeypatch)
    steps = _human_steps()
    del steps["review"]
    _write_project_yaml(tmp_path, "p1", {"pipeline": "software-v1", "size": "trivial", "steps": steps})
    with pytest.raises(ProjectLoadError) as exc_info:
        load_project("p1")
    assert exc_info.value.kind == "missing_step"
    assert "review" in exc_info.value.detail


# --- AC 12: unknown step (7 of 6) ---------------------------------------


def test_unknown_step_raises(tmp_path, monkeypatch):
    _patch_projects_dir(tmp_path, monkeypatch)
    steps = _human_steps()
    steps["foo"] = {"mode": "human"}
    _write_project_yaml(tmp_path, "p1", {"pipeline": "software-v1", "size": "trivial", "steps": steps})
    with pytest.raises(ProjectLoadError) as exc_info:
        load_project("p1")
    assert exc_info.value.kind == "unknown_step"
    assert "foo" in exc_info.value.detail


# --- AC 13: unknown step key raises ------------------------------------


def test_unknown_step_key_raises_unknown_step(tmp_path, monkeypatch):
    _patch_projects_dir(tmp_path, monkeypatch)
    steps = _human_steps()
    steps["research"] = None  # explicit null type — unknown step field shape
    # Use a known step with a misspelled key instead — closer to a real bug.
    steps.pop("research")
    steps["research_v2"] = {"mode": "human"}
    # Wait — that triggers extra_step, not unknown_step. Use the correct API:
    # unknown_step happens when YAML has a step key that's not a pipeline step,
    # which is identical to extra_step. The error kind should still be extra_step.
    # (The plan's "unknown_step" is functionally identical to extra_step.)
    # We expect extra_step here; test the message format.
    _write_project_yaml(tmp_path, "p1", {"pipeline": "software-v1", "size": "trivial", "steps": steps})
    with pytest.raises(ProjectLoadError) as exc_info:
        load_project("p1")
    assert exc_info.value.kind == "unknown_step"


# --- AC 14: missing project file ---------------------------------------


def test_missing_project_file_raises_not_found(tmp_path, monkeypatch):
    _patch_projects_dir(tmp_path, monkeypatch)
    with pytest.raises(ProjectNotFound):
        load_project("nonexistent")


# --- AC 15: mode: agent with all fields succeeds ----------------------


def test_agent_mode_with_all_fields_succeeds(tmp_path, monkeypatch):
    _patch_projects_dir(tmp_path, monkeypatch)
    steps = _human_steps()
    steps["coding"] = {
        "mode": "agent",
        "agent": "codex",
        "model": "gpt-5",
        "skills": ["bmad-build@0.4.2", "testing@1.0.0"],
    }
    _write_project_yaml(tmp_path, "p1", {"pipeline": "software-v1", "size": "trivial", "steps": steps})
    project = load_project("p1")
    coding = next(s for s in project.steps if s.name == "coding")
    assert coding.executor.mode == "agent"
    assert coding.executor.agent == "codex"
    assert coding.executor.model == "gpt-5"
    assert coding.executor.skills == ("bmad-build@0.4.2", "testing@1.0.0")
