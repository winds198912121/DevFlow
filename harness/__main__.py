"""`python -m harness` entry point — delegates to the Typer CLI."""

from harness.cli import app

if __name__ == "__main__":
    app()
