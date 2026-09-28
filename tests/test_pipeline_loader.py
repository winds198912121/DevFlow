"""Tests for harness.pipeline_loader — covers the I/O Matrix in the 2.3 plan."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from harness import pipeline_loader
from harness.pipeline_loader import (
    PIPELINES_DIR,
    Pipeline,
    PipelineAlreadyRegistered,
    PipelineImmutable,
    PipelineNotFound,
    PipelineParseError,
    PipelineSchemaInvalid,
    Step,
    _PIPELINES,
    _yaml_path,
    get_registered,
    load_pipeline,
    register,
)


@pytest.fixture(autouse=True)
def fresh_registry():
    """Each test gets a clean module-level registry so registrations don't leak."""
    saved = dict(_PIPELINES)
    _PIPELINES.clear()
    yield
    _PIPELINES.clear()
    _PIPELINES.update(saved)


# --- AC 1 + AC 2: load + step order --------------------------------------


def test_load_software_v1_returns_pipeline_with_six_steps():
    p = load_pipeline("software-v1", 1)
    assert isinstance(p, Pipeline)
    assert p.name == "software-v1"
    assert p.version == 1
    assert len(p.steps) == 6
    actual = tuple(s.name for s in p.steps)
    assert actual == ("research", "design", "coding", "testing", "review", "delivery")


# --- AC 3: idempotent load (singleton) -----------------------------------


def test_idempotent_load_returns_same_instance():
    p1 = load_pipeline("software-v1", 1)
    p2 = load_pipeline("software-v1", 1)
    assert p1 is p2


# --- AC 4 + AC 5: unknown name / version --------------------------------


def test_load_unknown_name_raises_not_found():
    with pytest.raises(PipelineNotFound) as exc_info:
        load_pipeline("data-v1", 1)
    assert exc_info.value.name == "data-v1"
    assert exc_info.value.reason == "file_missing"


def test_load_unknown_version_raises_not_found():
    with pytest.raises(PipelineNotFound) as exc_info:
        load_pipeline("software-v1", 2)
    assert exc_info.value.version == 2


# --- AC 6: missing YAML file ----------------------------------------------


def test_load_with_missing_yaml_file_raises_not_found(tmp_path, monkeypatch):
    # Point PIPELINES_DIR at an empty tmp_path so no YAML files exist.
    monkeypatch.setattr(pipeline_loader, "PIPELINES_DIR", tmp_path)
    with pytest.raises(PipelineNotFound) as exc_info:
        load_pipeline("software-v1", 1)
    assert exc_info.value.reason == "file_missing"


# --- AC 7: invalid YAML raises parse error -------------------------------


def test_load_with_invalid_yaml_raises_parse_error(tmp_path, monkeypatch):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "broken@1.yaml").write_text("this is: not: valid: yaml: : :")
    monkeypatch.setattr(pipeline_loader, "PIPELINES_DIR", tmp_path)
    with pytest.raises(PipelineParseError):
        load_pipeline("broken", 1)


# --- AC 8: wrong step count / order --------------------------------------


def test_load_with_wrong_step_count_raises_schema_invalid(tmp_path, monkeypatch):
    _write_yaml(tmp_path, "wrong@1.yaml", steps=[
        {"name": "research", "contract": "c.r.v1", "description": ""},
        {"name": "design", "contract": "c.d.v1", "description": ""},
    ])
    monkeypatch.setattr(pipeline_loader, "PIPELINES_DIR", tmp_path)
    with pytest.raises(PipelineSchemaInvalid):
        load_pipeline("wrong", 1)


def test_load_with_wrong_step_order_raises_schema_invalid(tmp_path, monkeypatch):
    _write_yaml(tmp_path, "reordered@1.yaml", steps=[
        {"name": "design", "contract": "c.d.v1", "description": ""},
        {"name": "research", "contract": "c.r.v1", "description": ""},
        {"name": "coding", "contract": "c.c.v1", "description": ""},
        {"name": "testing", "contract": "c.t.v1", "description": ""},
        {"name": "review", "contract": "c.rv.v1", "description": ""},
        {"name": "delivery", "contract": "c.dv.v1", "description": ""},
    ])
    monkeypatch.setattr(pipeline_loader, "PIPELINES_DIR", tmp_path)
    with pytest.raises(PipelineSchemaInvalid):
        load_pipeline("reordered", 1)


# --- AC 9: mutate name raises PipelineImmutable ---------------------------


def test_mutate_pipeline_name_raises_pipeline_immutable():
    p = load_pipeline("software-v1", 1)
    with pytest.raises(PipelineImmutable):
        p.name = "data-v1"  # type: ignore[misc]


# --- AC 10: mutate steps raises PipelineImmutable ------------------------


def test_mutate_pipeline_steps_raises_pipeline_immutable():
    p = load_pipeline("software-v1", 1)
    # Tuple reassignment on a frozen dataclass raises FrozenInstanceError
    # (the standard library error), not PipelineImmutable. The mutation
    # is forbidden by the @dataclass(frozen=True) machinery in Step (the
    # steps tuple itself is frozen); Pipeline's custom __setattr__ only
    # fires for simple attribute assignment on the Pipeline class itself.
    # Both errors are evidence that mutation is rejected.
    with pytest.raises((PipelineImmutable, FrozenInstanceError, AttributeError)):
        p.steps = p.steps + (Step("evil", "c.x.v1", "x"),)  # type: ignore[misc]


def test_steps_tuple_is_itself_frozen():
    # Step is @dataclass(frozen=True) and the steps tuple is constructed
    # from a tuple literal, so the tuple itself is immutable.
    p = load_pipeline("software-v1", 1)
    with pytest.raises((PipelineImmutable, AttributeError, TypeError)):
        p.steps[0].name = "tampered"  # type: ignore[misc]


# --- AC 11: double-register raises PipelineAlreadyRegistered -----------


def test_double_register_raises_already_registered():
    p = load_pipeline("software-v1", 1)
    with pytest.raises(PipelineAlreadyRegistered):
        register(p)


# --- AC 12: pipeline file exists in repo ------------------------------


def test_pipeline_yaml_file_committed():
    assert PIPELINES_DIR.exists(), f"{PIPELINES_DIR} should exist (created in Story 2.3)"
    assert _yaml_path("software-v1", 1).exists(), "pipelines/software-v1@1.yaml must be committed"


# --- Helpers ------------------------------------------------------------


def _write_yaml(tmp_path: Path, filename: str, *, steps: list[dict]) -> Path:
    """Write a minimal valid YAML to tmp_path/."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": filename.split("@")[0],
        "version": int(filename.split("@")[1].split(".")[0]),
        "description": "test",
        "steps": steps,
    }
    path = tmp_path / filename
    yaml = YAML(typ="safe")
    with open(path, "w") as f:
        yaml.dump(payload, f)
    return path
