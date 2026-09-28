"""Quality Gate Engine — per-step contract verification + AD-24 step_status
resolver + Verdict enum.

Public surface (Story 2.7):
- `Verdict` Literal (`accepted | accepted-with-open-items | rejected`, AD-12).
- `GateMode` Literal re-exported from `harness.workflow_controller` for
  convenience (no second definition; AD-24 (d) forbids it).
- `VerifyResult` frozen dataclass: `{ok, error_code, message, contract_path}`.
- `ArtifactContract` Protocol — published in `harness/ports/__init__.py`;
  the concrete `IdentityContract` and `PydanticSchemaContract` live here.
- `ContractRegistry` module-level dict + `register(contract)` /
  `lookup(pipeline, version, step)` / `register_all_v1_contracts()`.
- `verify_artifact(db, project_id, run_id, step, artifact_hash) -> VerifyResult`.
- `gate_mode_for(project_size) -> GateMode`.
- `step_status(db, project_id, run_id, step, *, project_size) -> StepStatus`
  — re-exported from `harness.workflow_controller` after the Story 2.5
  stub is upgraded with the full AD-24 logic (rejected → Failed).

AD-11 + AD-12 + AD-24 + AD-27 are the binding rules:
- AD-11: `Done` (skipped Gate) and `Locked` (Acknowledged) are distinct.
- AD-12: Verdict is the closed three-valued enum.
- AD-24: One resolver for terminal status; logic per spine.
- AD-27: Every pipeline pins per-step contract versions; bumps are pipeline
  bumps, not skill bumps.

The Gate Engine is the sole writer/reader of the contract registry and the
sole caller of `(pipeline, pipeline_version, step) -> ArtifactContract`
lookups (mirrors AD-22's "exactly two writers" pattern).
"""

from __future__ import annotations

import sqlite3
import warnings
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from harness import artifact_store
from harness.workflow_controller import GateMode, step_status as _workflow_step_status


# --- Pydantic models (canonical runtime validators) ------------------------
#
# The JSON Schema files under `_bmad-output/contracts/*.json` are the
# human-readable source of truth. These Pydantic models are the runtime
# validators — Pydantic's compiled TypeAdapter is fast and produces
# structured ValidationErrors. A drift between the JSON Schema and the
# Pydantic model is a tooling defect, caught by a future "schema drift"
# CI hook (deferred; not v1).


class _ExecutorTuple(BaseModel):
    """PRD FR-5 tuple (subset relevant to a test-report)."""

    model_config = ConfigDict(extra="forbid")

    agent: Literal["pi", "omp", "codex", "claude-code", "dsh", "human"]
    model: str
    skills: list[str] = Field(default_factory=list)


class _TestCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = Field(min_length=1, max_length=200)
    acceptance_ref: str
    status: Literal["pass", "fail", "skip", "error"]
    evidence: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)


class _AcceptanceCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fr_total: int = Field(ge=0)
    fr_passed: int = Field(ge=0)


class TestReportModel(BaseModel):
    """The Testing step's output artifact (PRD A7, locked fields).

    Mirrors `_bmad-output/contracts/test-report.schema.json`. The schema
    file is the human-readable source of truth; this Pydantic model is
    the runtime validator.

    `__test__ = False` tells pytest not to collect this Pydantic model
    as a test class (it has an `__init__` constructor from Pydantic).
    """

    model_config = ConfigDict(extra="forbid")
    __test__ = False

    step: Literal["testing"]
    run_id: str
    project_id: str
    executor_tuple: _ExecutorTuple
    started_at: str
    ended_at: str
    outcome: Literal["pass", "fail", "error"]
    cases: list[_TestCase]
    acceptance_coverage: _AcceptanceCoverage


# --- Verdict (AD-12) --------------------------------------------------------

Verdict = Literal["accepted", "accepted-with-open-items", "rejected"]
_VERDICT_VALUES: frozenset[str] = frozenset({"accepted", "accepted-with-open-items", "rejected"})


def validate_verdict(verdict: str) -> None:
    """Raise `ValueError` if `verdict` is not in the AD-12 closed enum.

    The Verdict type is a `Literal` at the type level; runtime callers
    (e.g. the future Story 2.8 Acknowledgement writer) call this helper
    before persisting the value. Mirrors the spine error envelope's
    "12 PRD categories + harness codes" closed-enum convention.
    """
    if verdict not in _VERDICT_VALUES:
        raise ValueError(
            f"verdict_invalid: {verdict!r} not in {sorted(_VERDICT_VALUES)}"
        )


# --- Exceptions ------------------------------------------------------------


class GateEngineError(Exception):
    """Base for all gate-engine errors."""


class ContractAlreadyRegistered(GateEngineError):
    """`register_contract(...)` was called twice for the same
    `(pipeline, pipeline_version, step)` tuple (mirrors Story 2.3's
    `PipelineAlreadyRegistered`)."""


class ContractLookupMiss(GateEngineError):
    """`lookup_contract(...)` was called for a tuple with no registered
    contract. Raised for unknown step names or unregistered pipeline
    versions."""


class UnsignedContractWarning(UserWarning):
    """A step's contract is not yet ratified by its BMAD skill; the gate
    accepts the artifact at lock time. Per the Story 2.7 ticket notes,
    the v1 contract policy is: testing enforces the PRD A7 schema; the
    other five steps use `IdentityContract` and emit this warning.
    """


# --- ArtifactContract Protocol + concrete contracts -----------------------


class ArtifactContract(Protocol):
    """A step's artifact contract (published in `harness/ports/__init__.py`).

    AD-27: contracts are pinned per `(pipeline, pipeline_version, step)`.
    Bumping a contract is a pipeline bump, not a skill bump.
    """

    contract_path: str | None

    def validate(self, payload: bytes) -> VerifyResult:
        """Validate `payload` (the locked artifact's bytes). Return a
        `VerifyResult`; raise only on infrastructure errors (e.g. the
        schema file is unreadable)."""
        ...


@dataclass(frozen=True)
class VerifyResult:
    """The result of `verify_artifact(...)`.

    `ok == True` means the artifact passes the step's contract.
    `error_code` and `message` are populated on failure; on success, both
    are None.
    """

    ok: bool
    error_code: str | None
    message: str | None
    contract_path: str | None


@dataclass(frozen=True)
class IdentityContract:
    """The placeholder contract for steps whose BMAD skill has not yet
    ratified a schema.

    Accepts any payload. The story's "unsigned-contract marker on the run
    event" path is deferred to the Run Event Log story (likely 2.10's
    tracer bullet); v1 emits a `warnings.warn(UnsignedContractWarning(...))`
    at lock time. The warning is one-shot per `(project_id, run_id, step)`
    per process — see `_warned` set.
    """

    contract_path: str | None = None

    def validate(self, payload: bytes) -> VerifyResult:
        return VerifyResult(ok=True, error_code=None, message=None, contract_path=None)


@dataclass(frozen=True)
class PydanticSchemaContract:
    """A contract backed by a Pydantic 2.13 model.

    v1 policy (spine Stack table pins Pydantic 2.13.5 for schema
    validation): the contract validates a payload by parsing JSON and
    feeding it to a Pydantic `TypeAdapter` compiled against a Pydantic
    `BaseModel` subclass.

    The JSON Schema file (e.g. `_bmad-output/contracts/test-report.schema.json`)
    is the canonical human-readable source of truth; the Pydantic model
    is the runtime validator. A drift between the two is a tooling
    defect, not a runtime failure — caught by the future "schema drift"
    CI hook (deferred; not v1).

    The contract is keyed by the schema path (for the diagnostic
    `contract_path` field on `VerifyResult`).
    """

    schema_path: str
    model: type[BaseModel]
    _adapter: TypeAdapter = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Eagerly build the TypeAdapter so `validate()` is hot-loop cheap.
        # `TypeAdapter(...)` itself can raise TypeError if `model` is not
        # a `BaseModel` subclass; we let that propagate at construction
        # time (it's a programming error, not a runtime validation
        # failure) and `validate()` catches `TypeError` as a fallback for
        # misconfigured subclass shenanigans.
        object.__setattr__(self, "_adapter", TypeAdapter(self.model))

    @property
    def contract_path(self) -> str:
        return self.schema_path

    def validate(self, payload: bytes) -> VerifyResult:
        try:
            self._adapter.validate_json(payload)
        except ValidationError as e:
            return VerifyResult(
                ok=False,
                error_code="artifact_contract_mismatch",
                message=_format_validation_errors(e),
                contract_path=self.contract_path,
            )
        except TypeError as e:
            # Misconfigured contract: e.g. a subclass override that
            # broke TypeAdapter's binding. Surface as a structured
            # failure rather than crashing the caller.
            return VerifyResult(
                ok=False,
                error_code="artifact_contract_mismatch",
                message=f"contract misconfigured: {e}",
                contract_path=self.contract_path,
            )
        return VerifyResult(
            ok=True, error_code=None, message=None, contract_path=self.contract_path
        )


def _format_validation_errors(error: ValidationError) -> str:
    """Render a `pydantic.ValidationError` as a one-line message.

    The dashboard / run-event viewer can render the structured form
    (`error.errors()`) when needed; for the v1 surface a compact summary
    is enough.
    """
    parts = []
    for err in error.errors()[:5]:
        loc = ".".join(str(p) for p in err.get("loc", ()))
        msg = err.get("msg", "invalid")
        parts.append(f"{loc}: {msg}" if loc else msg)
    suffix = f" (and {len(error.errors()) - 5} more)" if len(error.errors()) > 5 else ""
    return "; ".join(parts) + suffix


# --- Contract Registry ----------------------------------------------------


_REGISTRY: dict[tuple[str, int, str], ArtifactContract] = {}


def register_contract(contract: ArtifactContract, *, pipeline: str, pipeline_version: int, step: str) -> None:
    """Register `contract` for `(pipeline, pipeline_version, step)`.

    Raises `ContractAlreadyRegistered` if a contract is already registered
    for the same triple. Mirrors `Pipeline.register` from Story 2.3.
    """
    key = (pipeline, pipeline_version, step)
    if key in _REGISTRY:
        raise ContractAlreadyRegistered(f"contract for {key} already registered")
    _REGISTRY[key] = contract


def lookup_contract(pipeline: str, pipeline_version: int, step: str) -> ArtifactContract:
    """Return the contract for `(pipeline, pipeline_version, step)`.

    Raises `ContractLookupMiss` if no contract is registered. The
    Workflow Controller (Story 2.5) catches this and surfaces it as
    `ExecutorNotSupported` or similar; the gate engine raises the bare
    error so callers can decide how to handle it.
    """
    try:
        return _REGISTRY[(pipeline, pipeline_version, step)]
    except KeyError:
        raise ContractLookupMiss(
            f"no contract for ({pipeline}@{pipeline_version}, {step})"
        ) from None


def get_registered_contracts() -> tuple[ArtifactContract, ...]:
    """Diagnostic: return every registered contract (in registration order)."""
    return tuple(_REGISTRY.values())


# --- boot-time registration -----------------------------------------------


def register_all_v1_contracts() -> None:
    """Register the six step contracts for `software-v1@1`.

    v1 contract policy (Story 2.7 notes):
    - `testing` enforces the PRD A7 schema (`test-report.schema.json`).
    - The other five steps use `IdentityContract` and emit a
      `UnsignedContractWarning` at lock time.

    Call this once at boot, after the Workflow Controller's boot-time
    pipeline validation (the two are sibling boot steps). A future story
    that ratifies a step's contract (e.g. `research-contract@1`) would
    add a new `PydanticSchemaContract` here, not modify this function's
    existing registrations.
    """
    schema_path = "_bmad-output/contracts/test-report.schema.json"
    _register_for_v1(
        "testing", PydanticSchemaContract(schema_path=schema_path, model=TestReportModel)
    )
    for step in ("research", "design", "coding", "review", "delivery"):
        _register_for_v1(step, IdentityContract())


def _register_for_v1(step: str, contract: ArtifactContract) -> None:
    register_contract(contract, pipeline="software-v1", pipeline_version=1, step=step)


# Run boot-time registration when the module is imported. Mirrors the
# Story 2.3 pipeline registration pattern (`load_pipeline` is called at
# module top level for the boot-time invariant check) and the Story 1.5
# human-adapter registration pattern (`_register_human` at the bottom of
# `harness/executor.py`).
register_all_v1_contracts()


# --- gate_mode_for (FR-12) --------------------------------------------------


def gate_mode_for(project_size: str) -> GateMode:
    """Return the gate mode for a project's size tier.

    FR-12: trivial/session tiers bypass the Gate (`gate_mode: skipped`).
    Epic/project tiers require the Gate (`gate_mode: enforced`).
    """
    if project_size in ("trivial", "session"):
        return "skipped"
    return "enforced"


# --- verify_artifact -------------------------------------------------------


def verify_artifact(
    db: sqlite3.Connection,
    project_id: str,
    run_id: str,
    step: str,
    artifact_hash: str,
    *,
    pipeline: str = "software-v1",
    pipeline_version: int = 1,
) -> VerifyResult:
    """Verify a locked artifact against the step's contract.

    Returns a `VerifyResult`. Raises:
    - `ContractLookupMiss` if no contract is registered for the step.
    - `artifact_store.ArtifactNotFound` / `ArtifactCorrupt` /
      `ArtifactCorrupted` if the artifact can't be read.

    IdentityContract calls emit a `warnings.warn(UnsignedContractWarning)`
    (one-shot per `(project_id, run_id, step)` per process) — the v1
    contract policy documented in the Story 2.7 notes.
    """
    contract = lookup_contract(pipeline, pipeline_version, step)
    if isinstance(contract, IdentityContract):
        _emit_unsigned_contract_warning_once(pipeline, pipeline_version, step, project_id, run_id)
    payload = artifact_store.read(db, artifact_hash)
    return contract.validate(payload)


_warned_keys: set[str] = set()


def _emit_unsigned_contract_warning_once(
    pipeline: str, pipeline_version: int, step: str, project_id: str, run_id: str
) -> None:
    key = (pipeline, pipeline_version, step, project_id, run_id)
    if key in _warned_keys:
        return
    _warned_keys.add(key)
    warnings.warn(
        f"unsigned contract for {pipeline}@{pipeline_version} ({step}); "
        f"project_id={project_id!r} run_id={run_id!r}; "
        "the gate accepts any payload until the BMAD skill ratifies a schema.",
        UnsignedContractWarning,
        stacklevel=3,
    )


# --- step_status (AD-24 resolver upgrade) ---------------------------------

# Re-export the resolver from the Workflow Controller (which now holds the
# full AD-24 logic — see `harness/workflow_controller.py:step_status`).
# The Workflow Controller is the canonical home; the gate engine is a
# re-export so callers can `from harness.gate_engine import step_status`
# per AD-24 (a) ("every dashboard view MUST call this function").
step_status = _workflow_step_status


__all__ = [
    "Verdict",
    "validate_verdict",
    "VerifyResult",
    "ArtifactContract",
    "IdentityContract",
    "PydanticSchemaContract",
    "ContractAlreadyRegistered",
    "ContractLookupMiss",
    "GateEngineError",
    "UnsignedContractWarning",
    "register_contract",
    "lookup_contract",
    "get_registered_contracts",
    "register_all_v1_contracts",
    "gate_mode_for",
    "verify_artifact",
    "step_status",
]





