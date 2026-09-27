"""DevFlow harness CLI.

Epic 1 Story 1.1 stub: exposes `harness --help` and `harness check-baseline`.
The `check-baseline` command is a placeholder — the real baseline invariant
checks land in Story 1.6 (canonical_bytes / signing / lints / human adapter
all wired into one `--check-baseline` invocation).
"""

from __future__ import annotations

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
    """Run the Epic 1 baseline invariants (placeholder in Story 1.1).

    Story 1.6 wires the real checks; this stub returns exit 0 so that
    `uv run harness --help` lists the subcommand without error.
    """
    typer.echo("baseline not yet implemented (Story 1.1 stub)")
    raise typer.Exit()
