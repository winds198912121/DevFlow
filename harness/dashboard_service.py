"""Harness-side implementation of the dashboard port (AD-13, AD-21, AD-24, AD-26).

This module is the *only* place that knows how the Operator Dashboard's data is
projected. It lives in the harness layer, so it may import any harness store;
`dashboard/` sees only `harness.ports.DashboardPort` (AD-26).

Division of responsibility:

  * This module — reads canonical stores, shapes JSON payloads, enforces the
    AD-21 write allowlist semantics, and maps domain refusals to a code + HTTP
    status. It is transport-agnostic: the same object is used by the FastAPI
    app and by tests calling it directly.
  * `dashboard/main.py` — HTTP transport only: request models, status codes,
    and the raw-body signature gate.
  * `tools/dashboard_serve.py` — the composition root that binds the two.

AD-24 (a) — the single-resolver rule — is honoured by construction: every step
terminal status in this module's payloads comes from
`harness.workflow_controller.step_status`. Nothing here recomputes it from
artifacts or acknowledgements, and the dashboard cannot, because it never sees
those stores.
"""

from __future__ import annotations

import ast
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from harness import (
    acknowledgement_store,
    cost_guard,
    error_store,
    executor_swap,
    project_edit_lock,
    project_manager,
    regression_set,
    run_event_log,
    signing,
    skill_bump_registry,
)
from harness.canonical import canonical_sha256
from harness.ports.dashboard import DashboardRefusal
from harness.workflow_controller import STEP_ORDER, step_status


PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: The FR-25 filter keys the error view accepts. An unrecognised key is a
#: client bug, so it is refused rather than ignored — a silently-dropped
#: filter would render as "no errors" and hide real failures.
_ERROR_FILTER_KEYS = frozenset(
    {"run_id", "step", "category", "executor_tuple", "since", "until"}
)

#: Outcomes a run-event can carry, split by how the regression diff counts them.
_PASS_OUTCOMES = frozenset({"pass"})
_FAIL_OUTCOMES = frozenset({"fail", "error"})


class HarnessDashboardService:
    """The dashboard read model + the seven AD-21 write paths."""

    def __init__(
        self,
        *,
        projects_root: Path | None = None,
        core_db: Path | None = None,
        devflow_db: Path | None = None,
    ) -> None:
        """Bind the service to a set of stores.

        All three default to the real repo layout. Tests pass temp paths; the
        harness uses two SQLite files (`var/harness.sqlite` for the ledger
        family, `var/devflow.sqlite` for run events and the edit lock), which
        is why two db knobs exist rather than one.
        """
        self._projects_root = projects_root or project_manager.PROJECTS_DIR
        self._core_db = core_db or error_store.DEFAULT_DB
        self._devflow_db = devflow_db or run_event_log.DEFAULT_DB

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def list_runs(self) -> dict[str, Any]:
        runs = [
            {
                "project_id": project_id,
                "run_id": run_id,
                "steps": self._step_statuses(project_id, run_id),
            }
            for project_id, run_id in self._discover_runs()
        ]
        return {"runs": runs}

    def get_run(self, run_id: str, *, project_id: str | None = None) -> dict[str, Any]:
        matches = [
            (pid, rid)
            for pid, rid in self._discover_runs()
            if rid == run_id and (project_id is None or pid == project_id)
        ]
        if not matches:
            raise DashboardRefusal("run_not_found", status=404, message=run_id)
        if len(matches) > 1:
            raise DashboardRefusal(
                "run_ambiguous",
                status=409,
                message=(
                    f"run_id {run_id!r} exists under "
                    f"{sorted(pid for pid, _ in matches)}; pass project_id"
                ),
            )
        pid, rid = matches[0]
        return {
            "project_id": pid,
            "run_id": rid,
            "size": self._project_size(pid),
            "steps": self._step_statuses(pid, rid),
        }

    def list_errors(self, project_id: str, *, filters: dict[str, Any]) -> dict[str, Any]:
        unknown = set(filters) - _ERROR_FILTER_KEYS
        if unknown:
            raise DashboardRefusal(
                "unknown_filter",
                status=400,
                message=f"unknown filter(s): {sorted(unknown)}",
            )
        applied = {k: v for k, v in filters.items() if v is not None}
        try:
            records = error_store.query(
                project_id,
                run_id=applied.get("run_id"),
                step=applied.get("step"),
                category=applied.get("category"),
                since=applied.get("since"),
                until=applied.get("until"),
                db=self._core_db,
            )
        except error_store.InvalidErrorCategory as e:
            # Story 4.5: a category outside the closed AD-4 enum is named,
            # not silently treated as an empty result.
            raise DashboardRefusal(
                "category_not_found", status=400, message=str(e)
            ) from e

        executor_tuple = applied.get("executor_tuple")
        if executor_tuple:
            records = tuple(
                r for r in records if _executor_tuple_matches(r, executor_tuple)
            )
        return {
            "project_id": project_id,
            "count": len(records),
            "filters": applied,
            "errors": [r.to_dict() for r in records],
        }

    def regression_diff(self, project_id: str, bump_id: str) -> dict[str, Any]:
        bump = skill_bump_registry.read(bump_id, db=self._core_db)
        if bump is None:
            raise DashboardRefusal("bump_not_found", status=404, message=bump_id)

        tier = self._project_size(project_id)
        events = (
            run_event_log.list_for_run(bump.regression_run_id, db=self._devflow_db)
            if bump.regression_run_id
            else ()
        )

        # Per-step pass/fail counts, plus FR-18 comparability. A step is
        # comparable when the regression set holds at least one live run in the
        # step's (tier, contract) cell — the same query Epic 3's bench uses, so
        # the diff and the bench can never disagree about comparability.
        steps: list[dict[str, Any]] = []
        seen: list[str] = []
        for event in events:
            if event.step is None or event.step not in STEP_ORDER:
                continue
            if event.step not in seen:
                seen.append(event.step)
        for step in seen:
            step_events = [e for e in events if e.step == step]
            passed = sum(1 for e in step_events if e.outcome in _PASS_OUTCOMES)
            failed = sum(1 for e in step_events if e.outcome in _FAIL_OUTCOMES)
            skipped = len(step_events) - passed - failed
            comparable, reason = self._comparability(step, tier)
            steps.append(
                {
                    "step": step,
                    "passed": passed,
                    "failed": failed,
                    "skipped": skipped,
                    "total": len(step_events),
                    "comparable": comparable,
                    "non_comparable_reason": reason,
                }
            )
        return {
            "project_id": project_id,
            "bump_id": bump.bump_id,
            "skill_name": bump.skill_name,
            "new_version": bump.new_version,
            "previous_version": bump.previous_version,
            "state": bump.state,
            "regression_run_id": bump.regression_run_id,
            "comparable": all(s["comparable"] for s in steps) if steps else False,
            "steps": steps,
        }

    def bench(self, step: str, *, tier: str, contract: str | None = None) -> dict[str, Any]:
        try:
            rec = regression_set.bench_query(
                step, tier, contract, k=3, db=self._core_db
            )
        except regression_set.BenchInsufficient as e:
            raise DashboardRefusal(
                "regression_set_insufficient", status=409, message=str(e)
            ) from e
        except regression_set.NonComparableSet as e:
            raise DashboardRefusal(
                "non_comparable_set", status=409, message=str(e)
            ) from e
        except regression_set.RegressionSetError as e:
            raise DashboardRefusal("bench_failed", status=400, message=str(e)) from e

        return {
            "step": rec.step,
            "project_size_tier": rec.project_size_tier,
            "artifact_contract_version": rec.artifact_contract_version,
            "metric_definition": rec.metric_definition,
            "metric_summary": rec.metric_summary,
            "contributing_runs": [
                self._contributing_run(run_event_id)
                for run_event_id in rec.contributing_runs
            ],
        }

    # ------------------------------------------------------------------
    # Write authorization
    # ------------------------------------------------------------------

    def verify_write_signature(self, payload: dict[str, Any], signature_hex: str) -> bool:
        try:
            signature = bytes.fromhex(signature_hex)
        except (ValueError, TypeError):
            return False
        return signing.verify(payload, signature)

    # ------------------------------------------------------------------
    # Writes (AD-21 allowlist)
    # ------------------------------------------------------------------

    def submit_acknowledgement(self, payload: dict[str, Any]) -> dict[str, Any]:
        ref = payload.get("artifact_ref") or {}
        record = acknowledgement_store.write(
            payload["project_id"],
            payload["run_id"],
            payload["step"],
            payload["acknowledger"],
            payload["acknowledger_kind"],
            payload["verdict"],
            acknowledgement_store.ArtifactRef(
                step=ref["step"],
                project_id=ref["project_id"],
                run_id=ref["run_id"],
                hash=ref["hash"],
            ),
            open_items=tuple(
                acknowledgement_store.OpenItem(
                    id=item["id"],
                    description=item["description"],
                    owner=item.get("owner"),
                    due=item.get("due"),
                )
                for item in payload.get("open_items") or ()
            ),
            rejection_reason=payload.get("rejection_reason"),
        )
        return {"acknowledgement": record.to_file_dict()}

    def swap_executor(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            receipt = executor_swap.swap_executor_take_lock(
                payload["project_id"],
                payload["edited_by"],
                prev_executor_tuple=payload["prev_executor_tuple"],
                new_executor_tuple=payload["new_executor_tuple"],
                intent=payload["intent"],
                db=self._devflow_db,
            )
        except executor_swap.SwapUnderLockHeld as e:
            raise DashboardRefusal(
                "project_edit_lock_held", status=409, message=str(e)
            ) from e
        except executor_swap.SwapRefused as e:
            raise DashboardRefusal("swap_refused", status=400, message=str(e)) from e
        return {"receipt": asdict(receipt)}

    def skill_bump_regression(self, payload: dict[str, Any]) -> dict[str, Any]:
        bump = skill_bump_registry.register(
            payload["skill_name"],
            payload["new_version"],
            payload["previous_version"],
            registered_by=payload.get("registered_by", "dashboard"),
            db=self._core_db,
        )
        return {"bump_id": bump.bump_id, "state": bump.state,
                "skill_name": bump.skill_name, "new_version": bump.new_version}

    def skill_bump_promote(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            bump = skill_bump_registry.promote(
                payload["bump_id"],
                regression_run_id=payload["regression_run_id"],
                regression_result=payload.get("regression_result", "pass"),
                promoted_by=payload.get("promoted_by", "dashboard"),
                db=self._core_db,
            )
        except skill_bump_registry.SkillBumpRegistryImmutable as e:
            raise DashboardRefusal("skill_bump_immutable", status=409, message=str(e)) from e
        except skill_bump_registry.SkillBumpRegistryError as e:
            raise DashboardRefusal("skill_bump_refused", status=400, message=str(e)) from e
        return {"bump_id": bump.bump_id, "state": bump.state,
                "regression_run_id": bump.regression_run_id}

    def cost_overrun_ack(self, payload: dict[str, Any]) -> dict[str, Any]:
        project_id = payload["project_id"]
        cost_guard.ack_pause(project_id, db=self._core_db)
        return {"project_id": project_id,
                "paused": cost_guard.is_paused(project_id, db=self._core_db)}

    def regression_set_remove(self, payload: dict[str, Any]) -> dict[str, Any]:
        removed = regression_set.remove(
            payload["run_event_id"],
            reason=payload.get("reason"),
            removed_by=payload.get("removed_by", "dashboard"),
            db=self._core_db,
        )
        return {"run_event_id": payload["run_event_id"], "removed": removed}

    def project_edit_lock(self, payload: dict[str, Any]) -> dict[str, Any]:
        """AD-17 / AD-18: edit the project YAML under the single-writer lock.

        Order matters: the new YAML is validated *before* the lock is taken
        (so a malformed body never holds the lock), and the lock is taken
        *before* the current YAML is read (so `prev_yaml_hash` cannot be
        computed against a file another writer is midway through replacing).
        """
        project_id = payload["project_id"]
        edited_by = payload["edited_by"]
        new_yaml = payload["new_yaml"]

        _validate_project_yaml(new_yaml)

        target = self._projects_root / project_id / "project.yaml"
        if not target.exists():
            raise DashboardRefusal("project_not_found", status=404, message=project_id)

        try:
            project_edit_lock.acquire(project_id, edited_by, db=self._devflow_db)
        except project_edit_lock.LockHeld as e:
            raise DashboardRefusal(
                "project_edit_lock_held", status=409, message=str(e)
            ) from e
        try:
            prev_yaml_hash = canonical_sha256(target.read_text(encoding="utf-8"))
            target.write_text(new_yaml, encoding="utf-8")
            new_yaml_hash = canonical_sha256(target.read_text(encoding="utf-8"))
        finally:
            project_edit_lock.release(
                project_id, acquired_by=edited_by, db=self._devflow_db
            )
        return {
            "project_id": project_id,
            "prev_yaml_hash": prev_yaml_hash,
            "new_yaml_hash": new_yaml_hash,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _discover_runs(self) -> list[tuple[str, str]]:
        """Every `(project_id, run_id)` under `var/projects/<pid>/runs/<rid>/`.

        The filesystem *is* the run registry in v1 — `launch_step` creates the
        run directory and `run_event_log` records transitions. Discovery is
        therefore a directory walk, sorted so the dashboard renders a stable
        order across calls.
        """
        found: list[tuple[str, str]] = []
        if not self._projects_root.is_dir():
            return found
        for project_dir in sorted(self._projects_root.iterdir()):
            runs_dir = project_dir / "runs"
            if not runs_dir.is_dir():
                continue
            for run_dir in sorted(runs_dir.iterdir()):
                if run_dir.is_dir():
                    found.append((project_dir.name, run_dir.name))
        return found

    def _status_conn(self) -> sqlite3.Connection:
        """A connection for `step_status`, opened read-only and never created.

        `step_status` takes a connection for its AD-24 signature but currently
        resolves from the acknowledgement store on disk. Opening the real store
        read-only keeps the call correct if a later story starts consulting it,
        and `:memory:` avoids creating a stray file when it does not exist yet.
        """
        if self._devflow_db.exists():
            return sqlite3.connect(f"file:{self._devflow_db}?mode=ro", uri=True)
        return sqlite3.connect(":memory:")

    def _step_statuses(self, project_id: str, run_id: str) -> list[dict[str, Any]]:
        size = self._project_size(project_id)
        conn = self._status_conn()
        try:
            return [
                {
                    "step": (status := step_status(
                        conn, project_id, run_id, step, project_size=size
                    )).step,
                    "terminal": status.terminal,
                    "gate_mode": status.gate_mode,
                }
                for step in STEP_ORDER
            ]
        finally:
            conn.close()

    def _project_size(self, project_id: str) -> str:
        """The project's size tier, or `epic` when the YAML is unreadable.

        `epic` is the strictest tier (the Gate is enforced), so an unreadable
        project degrades to "requires acknowledgement" rather than silently
        skipping the Gate for a trivial/session tier.
        """
        try:
            return project_manager.load_project(project_id).size
        except project_manager.ProjectManagerError:
            return "epic"

    def _comparability(self, step: str, tier: str) -> tuple[bool, str | None]:
        try:
            regression_set.bench_query(step, tier, None, k=1, db=self._core_db)
        except regression_set.BenchInsufficient:
            return False, f"insufficient_comparable_runs_at_tier:{tier}"
        except regression_set.NonComparableSet as e:
            return False, f"non_comparable_set:{e}"
        except regression_set.RegressionSetError as e:
            return False, f"bench_failed:{e}"
        return True, None

    def _contributing_run(self, run_event_id: str) -> dict[str, Any]:
        """One contributing run, joined to its run event for the FR-21 hash.

        The regression-set row stores only the run *event* id and its metric.
        The hash that identifies what actually ran lives on the run event, so
        it is joined in here. A row whose event is absent (the Story 3.8
        fixture seeds metrics without run events) reports an empty hash rather
        than failing the whole bench — the metric is still valid.
        """
        event = run_event_log.read(run_event_id, db=self._devflow_db)
        return {
            "run_event_id": run_event_id,
            "run_id": event.run_id if event else None,
            "executor_tuple_hash": event.executor_tuple_hash if event else "",
            "outcome": event.outcome if event else None,
        }


def _executor_tuple_matches(record: error_store.ErrorRecord, needle: str) -> bool:
    """True when `needle` names an executor tuple recorded on `record`.

    Executor tuples are not a column on the Error Store: `retry_ladder` writes
    them into the `retry` JSON blob as `str(executor_dict)` per rung. So the
    FR-25 "by Agent/LLM/Skill tuple" dimension is a match against those.

    A needle matches when it equals the tuple's `agent` or `model`, or appears
    in the tuple rendered as `agent model skill skill...` (all lowercase). So
    `claude` matches `{'agent': 'claude', ...}` and `claude opus` matches an
    agent/model pair, while `claude-opus` matches neither.
    """
    want = needle.strip().lower()
    if not want:
        return False
    for row in record.retry:
        if not isinstance(row, dict):
            continue
        raw = row.get("executor_tuple")
        if not raw:
            continue
        spec: Any
        try:
            spec = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            spec = None
        if not isinstance(spec, dict):
            if want in str(raw).lower():
                return True
            continue
        agent = str(spec.get("agent") or "").lower()
        model = str(spec.get("model") or "").lower()
        skills = [str(s).lower() for s in (spec.get("skills") or ())]
        if want in {agent, model}:
            return True
        if want in " ".join([agent, model, *skills]):
            return True
    return False


def _validate_project_yaml(new_yaml: str) -> None:
    """Refuse a body that is not a loadable project YAML.

    Runs before the lock is taken so a malformed edit cannot occupy it. The
    check is deliberately shallow — `project.yaml`'s full schema is owned by
    `harness.project_manager`, and re-implementing it here would let the two
    drift. This only guarantees the file will not be unparseable on write.
    """
    try:
        parsed = YAML(typ="safe").load(new_yaml)
    except Exception as e:  # ruamel raises a family of parser errors
        raise DashboardRefusal(
            "project_yaml_invalid", status=422, message=str(e)
        ) from e
    if not isinstance(parsed, dict) or "steps" not in parsed:
        raise DashboardRefusal(
            "project_yaml_invalid",
            status=422,
            message="project YAML must be a mapping containing 'steps'",
        )


__all__ = ["HarnessDashboardService"]
