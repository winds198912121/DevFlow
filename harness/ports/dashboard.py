"""Published dashboard port (AD-13, AD-21, AD-24, AD-26).

This is the **only** `harness.*` module the FastAPI backend under
`dashboard/` may import, and `DashboardPort` + `DashboardRefusal` are the
only names it may bind (AD-26, enforced by `tools/check_layer_boundaries.py`).

Why a port and not direct store access
--------------------------------------
AD-13 makes the dashboard a *read model* that projects from the canonical
stores; it never holds state of its own. AD-26 forbids the layer roots from
importing `harness.*` internals. AD-24 (a) requires that step terminal status
come from exactly one resolver (`harness.workflow_controller.step_status`) so
no view can compute it inline. All three constraints are satisfied by putting
the projection on the harness side and handing the dashboard an opaque
interface:

    dashboard/main.py  --(DashboardPort)-->  harness/dashboard_service.py
                                                      |
                                        canonical harness stores

The dependency arrow points *into* the harness; the dashboard never learns how
the projection is built. `harness.dashboard_service` may import any harness
module it likes because it lives in the harness layer.

Payload contract
----------------
Every method returns a JSON-ready `dict` (str keys; no `datetime`, `Path`,
tuples, or dataclass instances). The harness side owns the projection shape,
the dashboard owns the HTTP transport, and neither has to publish its DTO
types across the boundary. Shapes are documented per method below and pinned
by `tests/test_dashboard_api.py`.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class DashboardRefusal(Exception):
    """A domain refusal from the read model, carrying its HTTP mapping.

    The dashboard translates this into `status` + `{"error": code}`. Domain
    refusals are *not* transport errors, so the mapping lives with the port
    rather than in the FastAPI layer: the same refusal must render identically
    whether it is reached over HTTP or by a test calling the service directly.

    `status` is the HTTP status the dashboard must use:
      400 — the request named something that does not exist (`category_not_found`)
      404 — the addressed run / project / bump does not exist
      409 — a state conflict (`project_edit_lock_held`)
      422 — the request was well-formed but semantically unusable
    """

    def __init__(self, code: str, *, status: int, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.status = status
        self.message = message


@runtime_checkable
class DashboardPort(Protocol):
    """The dashboard read model + the seven AD-21 write paths."""

    # --- Reads (AD-13: projections of the canonical stores) ---------------

    def list_runs(self) -> dict[str, Any]:
        """Every run known to the harness.

        Shape: `{"runs": [{"project_id", "run_id", "steps": [step_status, ...]}]}`
        where each `step_status` is the `step_status()` shape below.
        """
        ...

    def get_run(self, run_id: str, *, project_id: str | None = None) -> dict[str, Any]:
        """One run's detail.

        Shape: `{"project_id", "run_id", "size", "steps": [step_status, ...]}`.

        `step_status` shape (AD-24 — produced *only* by
        `harness.workflow_controller.step_status`, never recomputed here):
        `{"step", "terminal", "gate_mode"}` with `terminal` in
        `Done|Locked|Pending|Failed` and `gate_mode` in `enforced|skipped`.

        Raises `DashboardRefusal` with code `run_not_found` (404) when the run
        is unknown, or `run_ambiguous` (409) when `project_id` is omitted and
        the `run_id` exists under more than one project.
        """
        ...

    def list_errors(self, project_id: str, *, filters: dict[str, Any]) -> dict[str, Any]:
        """FR-25 filter surface over the Error Store (Story 4.5).

        `filters` keys, all optional and composed with AND:
          `run_id`, `step`, `category`, `executor_tuple`, `since`, `until`.
        An empty filter set returns every error for the project.

        Shape: `{"project_id", "count", "filters", "errors": [error, ...]}`
        where `error` is the `ErrorRecord.to_dict()` shape.

        Raises `DashboardRefusal` with code `category_not_found` (400) when
        `category` is outside the closed AD-4 enum.
        """
        ...

    def regression_diff(self, project_id: str, bump_id: str) -> dict[str, Any]:
        """Per-step pass/fail counts for a Skill-bump regression run (Story 4.6).

        Shape: `{"project_id", "bump_id", "skill_name", "new_version",
        "previous_version", "state", "regression_run_id", "comparable",
        "non_comparable_reason", "steps": [{"step", "passed", "failed",
        "total"}]}`.

        `comparable` is False for a step whose `(project_size_tier,
        artifact_contract_version)` does not match the bump's regression cell;
        `non_comparable_reason` then names why (FR-18).
        """
        ...

    def bench(self, step: str, *, tier: str, contract: str | None = None) -> dict[str, Any]:
        """The benchmark recommendation for a `(step, tier, contract)` cell (Story 4.7).

        Shape: `{"step", "project_size_tier", "artifact_contract_version",
        "metric_definition", "metric_summary", "contributing_runs":
        [{"run_event_id", "metric_value", "hash"}]}`.

        Raises `DashboardRefusal` with code `regression_set_insufficient` (409)
        when the K=3 floor is not met (NFR-Reliab-3), or
        `non_comparable_set` (409) when the cell mixes tiers or contracts.
        """
        ...

    # --- Write authorization (AD-10) -------------------------------------

    def verify_write_signature(self, payload: dict[str, Any], signature_hex: str) -> bool:
        """True iff `signature_hex` is the harness signature over `payload`.

        Every AD-21 write is gated on this; the dashboard returns 401 when it
        is False. `harness.signing.verify` is the single signature path
        (NFR-Sec-1), so the dashboard never sees key material.
        """
        ...

    # --- Writes (AD-21: the closed allowlist) ----------------------------

    def submit_acknowledgement(self, payload: dict[str, Any]) -> dict[str, Any]:
        """AD-5 / AD-21 route 1. Shape: the `AcknowledgementRecord` as a dict."""
        ...

    def swap_executor(self, payload: dict[str, Any]) -> dict[str, Any]:
        """AD-18 / AD-21 route 2. Shape: `{"receipt": {...}}`."""
        ...

    def skill_bump_regression(self, payload: dict[str, Any]) -> dict[str, Any]:
        """FR-22 / AD-21 route 3. Shape: `{"bump_id", "state"}`."""
        ...

    def skill_bump_promote(self, payload: dict[str, Any]) -> dict[str, Any]:
        """FR-23 / AD-21 route 4. Requires `regression_run_id` (AD-6)."""
        ...

    def cost_overrun_ack(self, payload: dict[str, Any]) -> dict[str, Any]:
        """AD-8 / AD-21 route 5. Shape: `{"project_id", "paused": False}`."""
        ...

    def regression_set_remove(self, payload: dict[str, Any]) -> dict[str, Any]:
        """AD-7 / AD-21 route 6. `reason` is required (NFR-Reliab-3)."""
        ...

    def project_edit_lock(self, payload: dict[str, Any]) -> dict[str, Any]:
        """AD-17 / AD-18 / AD-21 route 7 (Story 4.11).

        Shape: `{"project_id", "prev_yaml_hash", "new_yaml_hash"}`.

        Raises `DashboardRefusal` with code `project_edit_lock_held` (409) when
        a concurrent edit holds the lock.
        """
        ...


__all__ = ["DashboardPort", "DashboardRefusal"]
