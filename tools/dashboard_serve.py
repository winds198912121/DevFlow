#!/usr/bin/env python3
"""Composition root for the Operator Dashboard backend (AD-13, AD-26).

Serves the dashboard API:

    uv run uvicorn tools.dashboard_serve:app --port 8137

Why this file exists rather than an app in `dashboard/`
------------------------------------------------------
The dashboard needs data from the canonical harness stores, and the harness
needs to hand it over. AD-26 forbids `dashboard/` from importing `harness.*`
internals, so neither side may wire the other up directly:

  * `dashboard/main.py`  exports a factory and binds only `harness.ports`,
    so it cannot construct a service.
  * `harness/dashboard_service.py` constructs one, but importing `dashboard.*`
    from the harness would invert the dependency.

This module sits outside the four layer roots that AD-26 governs (`skills/`,
`agents/`, `herdr/`, `dashboard/`) and is therefore the one place allowed to
import both. Both arrows point here, and the runtime dependency still runs
dashboard -> port -> harness.

The built SPA (`dashboard/dist/`) is mounted at `/` when present, so one
process serves both the API and the UI.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from dashboard.main import create_app
from harness.dashboard_service import HarnessDashboardService

DIST_DIR = Path(__file__).resolve().parent.parent / "dashboard" / "dist"


def build_app() -> FastAPI:
    """Wire the harness read model into the dashboard app and mount the SPA."""
    app = create_app(HarnessDashboardService())
    if DIST_DIR.is_dir():
        # Mounted last so it cannot shadow an API route; `html=True` serves
        # index.html for `/`.
        app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="spa")
    return app


app = build_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8137)
