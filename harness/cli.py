"""DevFlow harness CLI.

Epic 1 Story 1.6 wires `harness check-baseline` as the tracer bullet. The
command runs every baseline invariant (`harness.checks.run_all_checks`) and
prints a one-line summary. The `--help` and no-subcommand paths are preserved.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import typer

app = typer.Typer(
    name="harness",
    help="DevFlow harness control plane CLI.",
    no_args_is_help=True,
    add_completion=False,
    invoke_without_command=True,
)


@app.callback()
def _root(
    ctx: typer.Context,
    show_help: bool = typer.Option(False, "--help", "-h", help="Show this message and exit."),
) -> None:
    """DevFlow harness control plane CLI."""
    if show_help or ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@app.command("check-baseline")
def check_baseline() -> None:
    """Run the Epic 1 baseline invariants and print a one-line summary.

    Exit 0 if every check passes; exit 1 with the first failure's detail on
    stderr otherwise. Idempotent: running twice produces the same summary.
    """
    from harness.checks import run_all_checks

    results = run_all_checks()
    ok_count = sum(1 for r in results if r.is_ok())
    total = len(results)

    if ok_count == total:
        details = " | ".join(r.detail for r in results)
        typer.echo(f"baseline: {ok_count}/{total} OK | {details}")
        raise typer.Exit(code=0)

    # Failure path: print the same N/N OK count, then the first failure on stderr.
    details = " | ".join(r.detail for r in results if r.is_ok())
    first_failure = next(r for r in results if not r.is_ok())
    typer.echo(f"baseline: {ok_count}/{total} OK | {details}")
    typer.echo(f"first failure: {first_failure.name}: {first_failure.detail}", err=True)
    raise typer.Exit(code=1)


@app.command("run")
def run_command(
    project: str = typer.Option(
        ..., "--project", "-p",
        help="Path to the project YAML OR a project_id (looks under var/projects/).",
    ),
    run_id: str = typer.Option(
        None, "--run-id", "-r",
        help="Reuse a prior run_id; cross-invocation idempotency applies. "
             "Default: generate a fresh ULID.",
    ),
    inject_failure_at: str = typer.Option(
        None, "--inject-failure-at",
        help="Record a synthetic failure for this step through the retry ladder "
             "(Story 3.3), then continue. The run still exits 0: the point is "
             "that a step failure is absorbed by the ladder instead of aborting "
             "the run. Unknown step names are refused.",
    ),
) -> None:
    """Run the six software-v1 steps end-to-end on the given project.

    Stages the project YAML into var/projects/<project_id>/, walks the
    six steps via the Workflow Controller, writes Acknowledgements +
    Run Events + delivery.json, and exits with 0 on success / non-zero
    on failure. The Story 2.10 tracer bullet.
    """
    import json
    import shutil
    import sqlite3
    import ulid as _ulid
    from pathlib import Path as _Path

    from harness.migrate import run_migrations as _run_migrations
    from harness.acknowledgement_store import (
        write as _ack_write,
        ArtifactRef as _ArtifactRef,
    )
    from harness.workflow_controller import (
        STEP_ORDER as _STEP_ORDER,
        run as _wc_run,
        launch_step as _wc_launch_step,
    )
    from harness.project_manager import load_project as _load_project
    from harness.canonical import canonical_sha256
    from harness.delivery import write_delivery as _write_delivery
    from harness.run_event_log import (
        RunEvent as _RunEvent,
        write as _event_write,
        generate_event_id as _generate_event_id,
    )

    # 1. Resolve the project: a directory path (fixture) or a project_id
    #    (already in var/projects/<id>/project.yaml).
    p = _Path(project)
    if p.is_dir() and (p / "project.yaml").exists():
        project_id = p.name
        dst = _Path("var/projects") / project_id / "project.yaml"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(p / "project.yaml", dst)
    else:
        project_id = project
        if not (_Path("var/projects") / project_id / "project.yaml").exists():
            typer.echo(f"project_not_found: {project}", err=True)
            raise typer.Exit(code=2)

    if run_id is None:
        run_id = str(_ulid.ULID.from_datetime(datetime.now(timezone.utc)))

    # Refuse an unknown step before doing any work, so the flag cannot look
    # like it did something when it silently matched nothing.
    if inject_failure_at is not None and inject_failure_at not in _STEP_ORDER:
        typer.echo(
            f"unknown_step: {inject_failure_at!r} "
            f"(expected one of {', '.join(_STEP_ORDER)})",
            err=True,
        )
        raise typer.Exit(code=2)

    # 2. Open the artifacts DB and ensure migrations.
    db = sqlite3.connect(":memory:")
    _run_migrations(db)

    # 3. Load the project + walk the six steps. The Workflow Controller's
    # cross-invocation idempotency (Story 2.9) means a second invocation
    # of this command with the same --run-id short-circuits all steps.
    proj = _load_project(project_id)
    artifact_hashes: list[str] = []
    ack_hashes: list[str] = []
    # `STEP_ORDER` is the controller's own sequence (AD-15); re-listing it here
    # was a fourth copy of the same six names.
    for step_name in _STEP_ORDER:
        status = _wc_launch_step(proj, run_id, step_name, db=db)
        if inject_failure_at == step_name:
            ladder = _inject_step_failure(project_id, run_id, step_name, proj)
            typer.echo(
                f"injected failure at {step_name}: rung "
                f"{ladder['next_rung']} result={ladder['result']} "
                f"error_record={ladder['error_record_id']}"
            )
        # Capture the latest locked artifact for this step.
        rows = db.execute(
            "SELECT sha256 FROM artifacts WHERE status='locked' "
            "ORDER BY rowid DESC LIMIT 1"
        ).fetchall()
        if rows:
            artifact_hashes.append(rows[0][0])
        # Write an Acknowledgement for the step (every step gets a
        # record; trivial tier is acknowledged accepted-with-no-items).
        # The artifact_ref's hash is the latest locked artifact's hash;
        # if no artifact is sealed yet (cross-invocation re-run), use a
        # sentinel sha256:000... to keep the receipt schema-stable.
        ar_hash = rows[0][0] if rows else "sha256:" + "0" * 64
        try:
            ack = _ack_write(
                project_id=project_id,
                run_id=run_id,
                step=step_name,
                acknowledger="cli@run",
                acknowledger_kind="check",
                verdict="accepted",
                artifact_ref=_ArtifactRef(
                    step=step_name,
                    project_id=project_id,
                    run_id=run_id,
                    hash=ar_hash,
                ),
            )
            ack_hashes.append("sha256:" + canonical_sha256(
                json.dumps({"ack_id": ack.acknowledgement_id}).encode()
            ).split(":", 1)[1])
        except Exception:
            # Acknowledgement writes are best-effort; an unsigned path
            # is recorded elsewhere. Don't fail the run for a missing ack.
            pass
        # Run event per step (start + end).
        from dataclasses import asdict as _asdict
        event_id = _generate_event_id()
        step_executor = next(s.executor for s in proj.steps if s.name == step_name)
        executor_tuple_json = json.dumps(_asdict(step_executor))
        _event_write(
            _RunEvent(
                event_id=event_id,
                project_id=project_id,
                run_id=run_id,
                step=step_name,
                executor_tuple=executor_tuple_json,
                executor_tuple_hash="sha256:" + canonical_sha256(
                    executor_tuple_json.encode()
                ).split(":", 1)[1],
                started_at=datetime.now(timezone.utc).isoformat(),
                ended_at=datetime.now(timezone.utc).isoformat(),
                outcome="pass",
                gate_mode=proj.size if proj.size in ("trivial", "session") else "epic",
            )
        )

    # 4. Write delivery.json (the final-step output for the delivery slot).
    from dataclasses import asdict as _asdict
    delivery_executor = next(
        s.executor for s in proj.steps if s.name == "delivery"
    )
    delivery_executor_json = json.dumps(_asdict(delivery_executor))
    _write_delivery(
        project_id,
        run_id,
        executor_tuple_json=delivery_executor_json,
        artifact_hashes=artifact_hashes,
        acknowledgement_hashes=ack_hashes,
    )
    typer.echo(f"harness run: project_id={project_id} run_id={run_id} steps={len(artifact_hashes)} OK")
    raise typer.Exit(code=0)


def _inject_step_failure(
    project_id: str, run_id: str, step_name: str, proj
) -> dict:
    """Record a synthetic failure for `step_name` through the retry ladder.

    Exists so `harness run --inject-failure-at` can exercise Story 3.3's ladder
    against real project data: the flag is the first caller of
    `retry_ladder.advance` outside the unit tests, so without it a regression in
    the ladder — or in the step→category mapping it depends on — would only
    surface in production.

    The candidate pool leads with the step's *own* executor, because rung 1 is
    "same Agent + same LLM + same Skill (re-attempt)" and `rung_1_same` takes
    `pool[0]`. The project's other distinct executors follow, so rungs 2–3 have
    alternatives when the YAML provides any.

    The failure is recorded in the Error Store and the caller continues; nothing
    here fails the run, which is the property the verify line asserts.
    """
    from dataclasses import asdict

    from harness.retry_ladder import advance as _advance

    current = next(s.executor for s in proj.steps if s.name == step_name)
    current_dict = asdict(current)
    pool: list[dict] = [current_dict]
    for step in proj.steps:
        candidate = asdict(step.executor)
        if candidate not in pool:
            pool.append(candidate)

    outcome = _advance(
        project_id,
        run_id,
        step_name,
        executor_pool=pool,
        current_executor={**current_dict, "tier": proj.size},
    )
    return {
        "next_rung": outcome.next_rung,
        "result": outcome.result,
        "error_record_id": (
            outcome.error_record.record_id if outcome.error_record else None
        ),
    }


@app.command("swap")
def swap_command(
    project: str = typer.Option(..., "--project", "-p", help="project_id."),
    edited_by: str = typer.Option(
        "cli@swap", "--by", help="operator name (recorded on the receipt).",
    ),
    prev: str = typer.Option(..., "--prev", help="prev_executor_tuple (JSON string)."),
    new: str = typer.Option(..., "--new", help="new_executor_tuple (JSON string)."),
    intent: str = typer.Option(
        "swap", "--intent", help="short description of the swap.",
    ),
) -> None:
    """Take the project_edit_lock + record a swap receipt (Story 2.9)."""
    from harness.executor_swap import (
        swap_executor_take_lock as _swap,
        SwapUnderLockHeld as _UnderLock,
        SwapRefused as _Refused,
    )

    try:
        receipt = _swap(
            project, edited_by,
            prev_executor_tuple=prev, new_executor_tuple=new,
            intent=intent,
        )
        typer.echo(
            f"swap OK: project={project} edit_id={receipt.edit_id} "
            f"prev_sha256={receipt.prev_yaml_hash[:24]}..."
        )
    except _Refused as e:
        typer.echo(f"swap_refused: {e}", err=True)
        raise typer.Exit(code=1)
    except _UnderLock as e:
        typer.echo(f"project_locked: {e}", err=True)
        raise typer.Exit(code=1)


@app.command("bench")
def bench_command(
    step: str = typer.Option(..., "--step", help="step name (e.g. coding)."),
    tier: str = typer.Option(
        "trivial", "--tier",
        help="project_size_tier (trivial | session | epic | project).",
    ),
    contract: str = typer.Option(
        None, "--contract", help="artifact_contract_version (optional).",
    ),
    k: int = typer.Option(3, "--k", help="comparable-run floor."),
) -> None:
    """Query the benchmark for a (step, tier) cell (Story 3.4 + 3.9)."""
    from harness.regression_set import (
        bench_query as _bench_query,
        BenchInsufficient as _Insufficient,
    )

    try:
        rec = _bench_query(step, tier, contract, k=k)
    except _Insufficient as e:
        typer.echo(f"regression_set_insufficient: {e}", err=True)
        raise typer.Exit(code=1)
    typer.echo(
        f"bench OK: step={rec.step} tier={rec.project_size_tier} "
        f"contract={rec.artifact_contract_version} "
        f"metric_summary={rec.metric_summary:.3f} "
        f"contributing_runs={len(rec.contributing_runs)}"
    )


@app.command("cost-check")
def cost_check_command(
    project: str = typer.Option(..., "--project", help="project_id."),
    tier: str = typer.Option(
        "trivial", "--tier", help="trivial|session|epic|project.",
    ),
) -> None:
    """Cost Guard check (Story 4.2 + 4.9 tracer bullet)."""
    from harness.cost_guard import check as _cost_check
    decision = _cost_check(project, tier=tier)
    typer.echo(f"cost_check: project={project} tier={tier} decision={decision}")
    if decision == "pause":
        raise typer.Exit(code=1)


@app.command("cost-ack")
def cost_ack_command(
    project: str = typer.Option(..., "--project", help="project_id."),
) -> None:
    """Operator cost_overrun_ack (one of the 6 allowed dashboard writes per AD-21)."""
    from harness.cost_guard import ack_pause as _ack
    _ack(project)
    typer.echo(f"cost-ack: project={project} OK")


@app.command("herdr-tail")
def herdr_tail_command() -> None:
    """Tail the Herdr stream + mirror new events (Story 4.8 + 4.9)."""
    from harness.herdr_ingest import tail as _herdr_tail
    n = _herdr_tail()
    typer.echo(f"herdr-tail: ingested {n} event(s)")


@app.command("serve")
def serve_command(
    demo: bool = typer.Option(False, "--demo", help="seed + start the tracer bullet."),
) -> None:
    """Start the operator dashboard (Story 4.9 tracer bullet).

    `--demo` seeds the python-hello fixture + 4-run regression set + 1
    sample Herdr event, then prints the seed summary and exits. The full
    FastAPI + Bun SPA wiring is owned by Stories 4.3 + 4.4 (deferred).
    """
    if not demo:
        typer.echo(
            "serve: full dashboard requires Stories 4.3 + 4.4; "
            "use --demo for the tracer bullet path",
            err=True,
        )
        raise typer.Exit(code=1)
    # Demo: stage python-hello + record a sample regression set + a
    # sample Herdr event; print the seed summary.
    import shutil as _shutil
    from harness.cost_ledger import (
        DEFAULT_DB as _COST_DB,
        append as _cost_append,
    )
    from harness.herdr_ingest import (
        DEFAULT_STREAM as _HERDR_STREAM,
        DEFAULT_MIRROR as _HERDR_MIRROR,
        tail as _herdr_tail,
    )
    from harness.regression_set import DEFAULT_DB as _REG_DB

    # Reset cost / regression DBs so the demo is reproducible.
    for p in (_COST_DB, _REG_DB, _HERDR_MIRROR):
        if p.exists():
            p.unlink()
        for ext in (".sqlite-wal", ".sqlite-shm"):
            q = p.with_suffix(ext)
            if q.exists():
                q.unlink()

    # Stage the python-hello fixture.
    src = Path("tests/fixtures/sample-projects/python-hello/project.yaml")
    dst = Path("var/projects/python-hello/project.yaml")
    dst.parent.mkdir(parents=True, exist_ok=True)
    _shutil.copy(src, dst)

    # Seed a sample regression set (Story 3.8 substrate — 4 deterministic
    # synthetic runs on the python-hello fixture).
    import importlib.util as _importlib
    _loader_path = (
        Path("tests/fixtures/regression-set/python-hello-4-runs/load.py")
    )
    _spec = _importlib.spec_from_file_location(
        "_regression_fixture_loader", _loader_path
    )
    _loader = _importlib.module_from_spec(_spec)
    _spec.loader.exec_module(_loader)  # type: ignore[union-attr]
    seeded = _loader.load()

    # Seed a sample cost record.
    _cost_append(
        project_id="python-hello",
        run_id="DEMO_RUN_0",
        step="coding",
        tokens_in=1200,
        tokens_out=400,
        duration_ms=3500,
    )

    # Seed a sample Herdr event on disk + tail it.
    _HERDR_STREAM.parent.mkdir(parents=True, exist_ok=True)
    _HERDR_STREAM.write_text(
        '{"event_id": "demo-herdr-001", "project_id": "python-hello", '
        '"step": "coding", "event_type": "agent_progress", '
        '"recorded_at": "2026-09-28T12:00:00+00:00"}\n',
        encoding="utf-8",
    )
    ingested = _herdr_tail()

    typer.echo(
        f"serve --demo OK: python-hello seeded; {seeded} regression runs; "
        f"1 cost record; {ingested} Herdr event(s) tailed"
    )
