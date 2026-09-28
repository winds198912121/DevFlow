"""Pipeline loader — the sole writer and reader of the pipelines/ directory.

Implements AD-1 (Pipeline Immutability), AD-15 (Six-Step Sequence Is Wired,
Not Configurable), and AD-16 (Pipeline Loading and Bump Boundary Are
Read-Only Filesystem Operations). Pipelines are loaded from
`pipelines/<name>@<version>.yaml` at boot, parsed via `ruamel.yaml`,
frozen into a `Pipeline` dataclass, and cached in a module-level registry.

The loader is the third "single-writer" surface in the harness (alongside
AD-4's error store and AD-22's Skill Bump Registry). All callers that
need a Pipeline go through `load_pipeline(name, version)`; the registry
is module-private.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

# Project root: this file is at harness/pipeline_loader.py, so the parent of
# the parent of __file__ is the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PIPELINES_DIR = PROJECT_ROOT / "pipelines"

# The single v1 pipeline's six steps (AD-15 + PRD §6.2).
_EXPECTED_STEPS = ("research", "design", "coding", "testing", "review", "delivery")


# --- Exceptions -----------------------------------------------------------


class PipelineError(Exception):
    """Base for all pipeline-loader errors."""


class PipelineNotFound(PipelineError):
    """No pipeline definition exists for the requested (name, version) tuple.

    Covers three sub-cases (the detail message names which one):
      - pipeline_not_found: no registration for the (name, version) tuple
      - pipeline_file_missing: the YAML file does not exist at PIPELINES_DIR
      - pipeline_version_unsupported: only `software-v1@1` is shipped in v1
    """

    def __init__(self, name: str, version: int, reason: str) -> None:
        detail = {
            "not_registered": f"pipeline_not_found: no pipeline named {name!r}@{version}",
            "file_missing": f"pipeline_file_missing: pipelines/{name}@{version}.yaml does not exist",
            "unsupported": f"pipeline_version_unsupported: harness ships only software-v1@1 in v1",
        }.get(reason, f"pipeline_not_found: {name}@{version} ({reason})")
        super().__init__(detail)
        self.name = name
        self.version = version
        self.reason = reason


class PipelineParseError(PipelineError):
    """The YAML file at pipelines/<name>@<version>.yaml could not be parsed."""


class PipelineSchemaInvalid(PipelineError):
    """The parsed YAML does not match the v1 schema (wrong step count, wrong order, etc.)."""


class PipelineAlreadyRegistered(PipelineError):
    """`register(name, version, ...)` was called twice for the same (name, version)."""


class PipelineImmutable(PipelineError):
    """Attempted mutation of a loaded Pipeline's fields (AD-1)."""


# --- Frozen dataclasses ----------------------------------------------------
#
# `dataclass(frozen=True)` overrides __setattr__ internally; defining a custom
# __setattr__ on a frozen dataclass raises "Cannot overwrite attribute
# __setattr__". So `Pipeline` uses a plain class with manual frozen
# semantics (private _frozen flag + custom __setattr__ that raises
# PipelineImmutable). `Step` uses the standard `@dataclass(frozen=True)` —
# it has no custom attribute logic and doesn't need a domain-specific error.


@dataclass(frozen=True)
class Step:
    """A single step in a pipeline. Frozen — fields are immutable post-load."""

    name: str
    contract: str
    description: str


class Pipeline:
    """A loaded pipeline. Frozen — fields are immutable post-load (AD-1).

    Plain class (not `@dataclass(frozen=True)`) so a custom `__setattr__`
    can raise `PipelineImmutable` (the v1 contract) instead of Python's
    built-in `FrozenInstanceError`. The `_frozen` guard ensures the
    instance is constructed first (`__init__` sets the fields, then sets
    `_frozen = True`); once set, any further `__setattr__` raises.
    """

    def __init__(self, name: str, version: int, description: str, steps: tuple[Step, ...]) -> None:
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, key: str, value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise PipelineImmutable(
                f"pipeline {self.name}@{self.version} is immutable (AD-1); "
                f"attempted to set {key}"
            )
        object.__setattr__(self, key, value)

    def __repr__(self) -> str:
        return (
            f"Pipeline(name={self.name!r}, version={self.version}, "
            f"steps={list(s.name for s in self.steps)})"
        )


# --- Registry ------------------------------------------------------------


_PIPELINES: dict[tuple[str, int], Pipeline] = {}


def _yaml_path(name: str, version: int) -> Path:
    """Compute `pipelines/<name>@<version>.yaml` from the project root."""
    return PIPELINES_DIR / f"{name}@{version}.yaml"


def _validate_steps(steps_data: list[Any], source_path: Path) -> tuple[Step, ...]:
    """Validate the parsed `steps` list against the v1 schema.

    Steps must be exactly six, in the order `research, design, coding,
    testing, review, delivery` (AD-15 + PRD §6.2). Each step must be a
    dict with `name`, `contract`, `description` keys.
    """
    if not isinstance(steps_data, list):
        raise PipelineSchemaInvalid(f"{source_path}: `steps` must be a list, got {type(steps_data).__name__}")
    if len(steps_data) != 6:
        raise PipelineSchemaInvalid(
            f"{source_path}: `steps` must have exactly 6 entries (research, design, coding, testing, review, delivery); got {len(steps_data)}"
        )
    steps: list[Step] = []
    for idx, step_data in enumerate(steps_data):
        if not isinstance(step_data, dict):
            raise PipelineSchemaInvalid(
                f"{source_path}: step {idx} must be a dict, got {type(step_data).__name__}"
            )
        name = step_data.get("name")
        contract = step_data.get("contract")
        description = step_data.get("description", "")
        if name != _EXPECTED_STEPS[idx]:
            raise PipelineSchemaInvalid(
                f"{source_path}: step {idx} must be named {_EXPECTED_STEPS[idx]!r}, got {name!r}"
            )
        if not isinstance(contract, str) or not contract.strip():
            raise PipelineSchemaInvalid(
                f"{source_path}: step {idx} contract must be a non-empty string"
            )
        if not isinstance(description, str):
            raise PipelineSchemaInvalid(
                f"{source_path}: step {idx} description must be a string"
            )
        steps.append(Step(name=name, contract=contract, description=description))
    return tuple(steps)


def _parse_yaml(path: Path) -> Pipeline:
    """Read and validate the YAML at `path`, returning a frozen `Pipeline`."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as e:
        raise PipelineNotFound(path.stem.split("@")[0], int(path.stem.split("@")[1]), "file_missing") from e
    yaml = YAML(typ="safe")  # safe load — no arbitrary object instantiation
    try:
        data = yaml.load(source)
    except Exception as e:
        raise PipelineParseError(f"{path}: YAML parse failed: {e}") from e
    if not isinstance(data, dict):
        raise PipelineParseError(f"{path}: top-level must be a mapping, got {type(data).__name__}")
    name = data.get("name")
    version = data.get("version")
    description = data.get("description", "")
    steps_data = data.get("steps")
    if not isinstance(name, str) or not name.strip():
        raise PipelineSchemaInvalid(f"{path}: top-level `name` must be a non-empty string")
    if not isinstance(version, int) or version < 1:
        raise PipelineSchemaInvalid(f"{path}: top-level `version` must be a positive integer")
    if not isinstance(description, str):
        raise PipelineSchemaInvalid(f"{path}: top-level `description` must be a string")
    steps = _validate_steps(steps_data, path)
    return Pipeline(name=name, version=version, description=description, steps=steps)


def register(pipeline: Pipeline) -> None:
    """Register `pipeline` in the module-level registry.

    Sole writer pattern (mirrors AD-4 + AD-22). Raises `PipelineAlreadyRegistered`
    if the same `(name, version)` is already registered.
    """
    key = (pipeline.name, pipeline.version)
    if key in _PIPELINES:
        raise PipelineAlreadyRegistered(f"pipeline {key[0]}@{key[1]} is already registered")
    _PIPELINES[key] = pipeline


def get_registered() -> tuple[Pipeline, ...]:
    """Return all registered pipelines in registration order. Diagnostic only."""
    return tuple(_PIPELINES.values())


def load_pipeline(name: str, version: int) -> Pipeline:
    """Return the cached `Pipeline` for `(name, version)`, or load + cache + register.

    Caching: a second call returns the same `Pipeline` instance (AD-16's
    "load only happens once at boot"). If `register` was called explicitly
    first, the registered instance is returned (so callers that pre-load
    get the same singleton).
    """
    key = (name, version)
    if key in _PIPELINES:
        return _PIPELINES[key]
    path = _yaml_path(name, version)
    if not path.exists():
        raise PipelineNotFound(name, version, "file_missing")
    pipeline = _parse_yaml(path)
    register(pipeline)
    return pipeline
