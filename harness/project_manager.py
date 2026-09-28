"""Project Manager — loads + validates a project YAML and produces a Project.

Implements FR-4 (project YAML shape), FR-5 (executor tuple resolution),
FR-6 (skill pin requirement), and FR-12 (project size tier for downstream
Gate-strictness logic in Story 2.7).

The loader is the third "single-writer" surface in the harness (after
Story 2.2's Artifact Store and Story 2.3's Pipeline Loader registry). It
is the sole writer of `Project` instances and the sole reader of
`var/projects/<project_id>/project.yaml`. Every consumer that needs a
Project (Story 2.5's Workflow Controller, Story 2.7's Quality Gate Engine,
Story 2.8's Acknowledgement writer) calls `load_project(project_id)`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ruamel.yaml import YAML

from harness.pipeline_loader import Pipeline, load_pipeline

# Project root: this file is at harness/project_manager.py, so the parent's
# parent is the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = PROJECT_ROOT / "var" / "projects"

_SKILL_PIN_RE = re.compile(r"^[a-z0-9-]+@[0-9]+\.[0-9]+\.[0-9]+$")
_VALID_MODES = ("human", "agent")


# --- Exceptions -----------------------------------------------------------


class ProjectManagerError(Exception):
    """Base for all project manager errors."""


class ProjectNotFound(ProjectManagerError):
    """No project file exists for the requested project_id."""

    def __init__(self, project_id: str) -> None:
        super().__init__(f"project_not_found: project {project_id!r} not found")
        self.project_id = project_id


class ProjectLoadError(ProjectManagerError):
    """The project file is missing, malformed, or fails validation.

    The `kind` attribute carries the specific failure category so callers can
    branch on it without parsing the message string.
    """

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


# --- Frozen dataclasses --------------------------------------------------


@dataclass(frozen=True)
class ExecutorTuple:
    """The (mode / agent / model / skills[]) tuple per FR-5.

    For `mode='human'`: agent=None, model=None, skills=().
    For `mode='agent'`: agent=str, model=str, skills=tuple of pinned skills.
    """

    mode: Literal["human", "agent"]
    agent: str | None
    model: str | None
    skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectStep:
    """One step of a loaded project: the pipeline step name + its executor tuple."""

    name: str
    executor: ExecutorTuple


@dataclass(frozen=True)
class Project:
    """A loaded project. Frozen (per FR-4 + AD-1 spirit: the YAML is the source
    of truth and the in-memory Project is a read-only view of it).
    """

    project_id: str
    pipeline_name: str
    pipeline_version: int
    size: Literal["trivial", "session", "epic", "project"]
    steps: tuple[ProjectStep, ...]
    notes: tuple[str, ...] = ()


# --- Loader -------------------------------------------------------------


def _yaml_path(project_id: str) -> Path:
    return PROJECTS_DIR / project_id / "project.yaml"


def _parse_executor(step_name: str, raw: Any) -> ExecutorTuple:
    """Validate and construct an `ExecutorTuple` from the per-step YAML dict."""
    if not isinstance(raw, dict):
        raise ProjectLoadError(
            "invalid_executor_tuple",
            f"step {step_name!r}: must be a mapping, got {type(raw).__name__}",
        )
    mode = raw.get("mode")
    if mode not in _VALID_MODES:
        raise ProjectLoadError(
            "invalid_executor_tuple",
            f"step {step_name!r}: unknown mode {mode!r}; expected one of {_VALID_MODES}",
        )
    agent = raw.get("agent")
    model = raw.get("model")
    skills_raw = raw.get("skills", [])

    if mode == "human":
        if agent is not None or model is not None:
            raise ProjectLoadError(
                "invalid_executor_tuple",
                f"step {step_name!r}: mode=human forbids agent/model fields "
                f"(found agent={agent!r}, model={model!r})",
            )
        return ExecutorTuple(mode="human", agent=None, model=None, skills=())

    # mode == "agent"
    if not isinstance(agent, str) or not agent.strip():
        raise ProjectLoadError(
            "invalid_executor_tuple",
            f"step {step_name!r}: mode=agent requires non-empty agent",
        )
    if not isinstance(model, str) or not model.strip():
        raise ProjectLoadError(
            "invalid_executor_tuple",
            f"step {step_name!r}: mode=agent requires non-empty model",
        )
    if not isinstance(skills_raw, list) or not skills_raw:
        raise ProjectLoadError(
            "invalid_executor_tuple",
            f"step {step_name!r}: mode=agent requires non-empty skills[]",
        )
    skills: list[str] = []
    for skill in skills_raw:
        if not isinstance(skill, str) or not _SKILL_PIN_RE.match(skill):
            raise ProjectLoadError(
                "skill_pin_required",
                f"step {step_name!r}: skill {skill!r} must be pinned as name@version",
            )
        skills.append(skill)
    return ExecutorTuple(mode="agent", agent=agent, model=model, skills=tuple(skills))


def _parse_yaml(project_id: str, path: Path) -> Project:
    """Read + validate the YAML at `path`, returning a frozen `Project`."""
    source = path.read_text(encoding="utf-8")
    yaml = YAML(typ="safe")
    try:
        data = yaml.load(source)
    except Exception as e:
        raise ProjectLoadError(
            "project_yaml_parse_error",
            f"{path}: YAML parse failed: {e}",
        ) from e
    if not isinstance(data, dict):
        raise ProjectLoadError(
            "project_yaml_parse_error",
            f"{path}: top-level must be a mapping, got {type(data).__name__}",
        )

    pipeline_name = data.get("pipeline")
    if not pipeline_name:
        raise ProjectLoadError(
            "pipeline_required",
            f"project {project_id!r}: top-level `pipeline` field is required",
        )
    if not isinstance(pipeline_name, str):
        raise ProjectLoadError(
            "pipeline_required",
            f"project {project_id!r}: `pipeline` must be a string",
        )

    pipeline_version = data.get("pipeline_version", 1)
    if not isinstance(pipeline_version, int) or pipeline_version < 1:
        raise ProjectLoadError(
            "pipeline_required",
            f"project {project_id!r}: `pipeline_version` must be a positive integer",
        )

    size = data.get("size", "session")
    if size not in ("trivial", "session", "epic", "project"):
        raise ProjectLoadError(
            "project_yaml_parse_error",
            f"project {project_id!r}: `size` must be one of (trivial, session, epic, project), got {size!r}",
        )

    steps_raw = data.get("steps", {})
    if not isinstance(steps_raw, dict):
        raise ProjectLoadError(
            "project_yaml_parse_error",
            f"project {project_id!r}: `steps` must be a mapping",
        )

    # Cross-reference the pipeline definition.
    try:
        pipeline = load_pipeline(pipeline_name, pipeline_version)
    except Exception as e:
        raise ProjectLoadError(
            "pipeline_not_found",
            f"{pipeline_name}@{pipeline_version}: {e}",
        ) from e

    pipeline_step_names = tuple(s.name for s in pipeline.steps)
    pipeline_step_set = set(pipeline_step_names)

    # Validate step keys.
    extras = set(steps_raw.keys()) - pipeline_step_set
    if extras:
        # Plan labels this `unknown_step` (the YAML has a step key that's
        # not in the pipeline); same underlying problem. Use the plan's
        # term for consistency with the verify line + the pipeline loader's
        # missing-step detection (which uses `missing_step` for the inverse).
        names = ", ".join(sorted(extras))
        raise ProjectLoadError(
            "unknown_step",
            f"project {project_id!r}: steps not in pipeline {pipeline_name}@{pipeline_version}: {names}",
        )
    unknown = pipeline_step_set - set(steps_raw.keys())
    if unknown:
        # Single missing key reported; multiple joined.
        names = ", ".join(sorted(unknown))
        raise ProjectLoadError(
            "missing_step",
            f"project {project_id!r}: missing steps for pipeline {pipeline_name}@{pipeline_version}: {names}",
        )

    # Build project steps in pipeline order (reorder if necessary).
    notes: list[str] = []
    yaml_order = list(steps_raw.keys())
    if yaml_order != list(pipeline_step_names):
        notes.append(
            f"reordered: project yaml step order {yaml_order} != pipeline order "
            f"{list(pipeline_step_names)}; using pipeline order"
        )

    project_steps: list[ProjectStep] = []
    for step_name in pipeline_step_names:
        raw = steps_raw[step_name]
        executor = _parse_executor(step_name, raw)
        project_steps.append(ProjectStep(name=step_name, executor=executor))

    return Project(
        project_id=project_id,
        pipeline_name=pipeline_name,
        pipeline_version=pipeline_version,
        size=size,
        steps=tuple(project_steps),
        notes=tuple(notes),
    )


def load_project(project_id: str) -> Project:
    """Load + validate the project at `var/projects/<project_id>/project.yaml`.

    Raises:
        ProjectNotFound: the project file does not exist.
        ProjectLoadError: the file is malformed or fails validation (kind
            attribute carries the specific failure category).
    """
    path = _yaml_path(project_id)
    if not path.exists():
        raise ProjectNotFound(project_id)
    return _parse_yaml(project_id, path)
