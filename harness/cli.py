"""DevFlow harness CLI.

Epic 1 Story 1.6 wires `harness check-baseline` as the tracer bullet. The
command runs every baseline invariant (`harness.checks.run_all_checks`) and
prints a one-line summary. The `--help` and no-subcommand paths are preserved.
"""

from __future__ import annotations

import sys

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
