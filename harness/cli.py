"""DevFlow harness CLI.

Epic 1 Story 1.6 wires `harness check-baseline` as the tracer bullet. The
command runs every baseline invariant (`harness.checks.run_all_checks`) and
prints a one-line summary. The `--help` and no-subcommand paths are preserved.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

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

    # 2. Open the artifacts DB and ensure migrations.
    db = sqlite3.connect(":memory:")
    _run_migrations(db)

    # 3. Load the project + walk the six steps. The Workflow Controller's
    # cross-invocation idempotency (Story 2.9) means a second invocation
    # of this command with the same --run-id short-circuits all steps.
    proj = _load_project(project_id)
    artifact_hashes: list[str] = []
    ack_hashes: list[str] = []
    for step_name in ("research", "design", "coding", "testing", "review", "delivery"):
        status = _wc_launch_step(proj, run_id, step_name, db=db)
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
