"""Published-port allowlist — the one `harness.*` surface the four layer roots
(skills/, agents/, herdr/, dashboard/) may import.

AD-26: every import under skills/, agents/, herdr/, dashboard/ whose module
path begins with `harness.` is rejected by `tools/check_layer_boundaries.py`
unless the imported symbol is listed in this module's `__all__`. This
module defines the eight spine-named Protocol stubs at runtime so that
`from harness.ports import StepExecutorPort` returns a usable type (not a
string), which lets downstream code write `isinstance(x, StepExecutorPort)`.

The allowlist `__all__` is what the lint reads — not the runtime-importable
symbols — so a stub here continues to authorize the import even before the
concrete type lands (future stories replace these with rich Protocols).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class StepExecutorPort(Protocol):
    """Adapter contract for executor invocation (AD-10)."""

    def start(self, capability: str) -> Any: ...
    def cancel(self, invocation_id: str) -> None: ...
    def status(self, invocation_id: str) -> Any: ...


@runtime_checkable
class HerdrEventPort(Protocol):
    """Observer interface for Herdr events (AD-9, AD-19)."""

    def emit(self, event: dict) -> None: ...


@runtime_checkable
class ExecutorTuple(Protocol):
    """The (agent, model, skills[]) tuple named in FR-5."""

    agent: str
    model: str
    skills: tuple[str, ...]


@runtime_checkable
class SkillManifest(Protocol):
    """Pinned Skill descriptor (FR-6, AD-6)."""

    name: str
    version: str


@runtime_checkable
class ArtifactContract(Protocol):
    """Schema reference for a step's input/output (FR-3, AD-27).

    The full Protocol is realized by `harness.gate_engine.ArtifactContract`
    (with `contract_path: str | None` + `validate(payload: bytes) -> Any`).
    This stub preserves the AD-26 allowlist so that layer-root code may
    `from harness.ports import ArtifactContract` without triggering the
    layer-boundary lint. The two definitions are structurally compatible
    (`contract_path` is the renamed `schema_path`).
    """

    contract_path: str | None

    def validate(self, payload: bytes) -> Any:
        """Validate `payload` (the locked artifact's bytes)."""


@runtime_checkable
class Acknowledgement(Protocol):
    """Gate Acknowledgement record (FR-10, AD-5, PRD A8)."""

    acknowledger: str
    timestamp: str
    verdict: str


@runtime_checkable
class ErrorRecord(Protocol):
    """Append-only error store record (FR-13, AD-4, PRD addendum §5)."""

    record_id: str
    category: str


@runtime_checkable
class RunEvent(Protocol):
    """Run Event Log entry (NFR-Obs-1, AD-14)."""

    event_id: str
    project_id: str
    run_id: str
    step: str


__all__ = [
    "StepExecutorPort",
    "HerdrEventPort",
    "ExecutorTuple",
    "SkillManifest",
    "ArtifactContract",
    "Acknowledgement",
    "ErrorRecord",
    "RunEvent",
]

