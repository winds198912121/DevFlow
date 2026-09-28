"""Operator Dashboard backend — FastAPI transport over `DashboardPort` (AD-13, AD-21).

Boundary rules that shape this file
-----------------------------------
AD-26 forbids anything under `dashboard/` from importing `harness.*` except the
published ports, so every symbol this module binds from the harness is one of
`DashboardPort` / `DashboardRefusal`. It therefore owns **transport only**:
request parsing, the raw-body signature gate, status codes, and the refusal
mapping. All projection happens on the harness side.

The app is a factory (`create_app(service)`) rather than a module-level
singleton because the service must be injected: the composition root lives in
`tools/dashboard_serve.py`, which is outside the four layer roots and may
import both sides. That keeps the dependency arrow pointing into the harness.

AD-21 (the write allowlist) is enforced twice: the router below declares
exactly the seven permitted write paths, and `tools/check_dashboard_writes.py`
fails CI if any write decorator appears under `dashboard/` that is not in the
allowlist. Adding an eighth write here is therefore a build break, not a
review catch.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from harness.ports import DashboardPort, DashboardRefusal


def create_app(service: DashboardPort) -> FastAPI:
    """Build the dashboard app around an injected read model."""
    app = FastAPI(
        title="DevFlow Operator Dashboard",
        version="1.0",
        description=(
            "Read model over the canonical harness stores (AD-13). Every write "
            "path is one of the AD-21 seven and requires a harness signature."
        ),
    )
    app.state.service = service

    @app.exception_handler(DashboardRefusal)
    def _on_refusal(request: Request, exc: DashboardRefusal) -> JSONResponse:
        """Domain refusals carry their own HTTP mapping (see `DashboardRefusal`)."""
        return JSONResponse(
            status_code=exc.status,
            content={"error": exc.code, "message": exc.message},
        )

    # --- Reads -----------------------------------------------------------

    @app.get("/runs")
    def list_runs(request: Request) -> dict[str, Any]:
        return _service(request).list_runs()

    @app.get("/runs/{run_id}")
    def get_run(
        request: Request,
        run_id: str,
        project_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return _service(request).get_run(run_id, project_id=project_id)

    @app.get("/projects/{project_id}/errors")
    def list_errors(request: Request, project_id: str) -> dict[str, Any]:
        # FR-25: filters compose with AND. Every query parameter is forwarded,
        # including unrecognised ones, so the port can refuse a misspelled
        # filter. Declaring the six filters as typed parameters instead would
        # let FastAPI silently drop `?catagory=coding`, and the caller would
        # receive unfiltered results believing they were filtered.
        return _service(request).list_errors(
            project_id, filters=dict(request.query_params)
        )

    @app.get("/projects/{project_id}/regression-diff/{bump_id}")
    def regression_diff(request: Request, project_id: str, bump_id: str) -> dict[str, Any]:
        return _service(request).regression_diff(project_id, bump_id)

    @app.get("/bench/{step}")
    def bench(
        request: Request,
        step: str,
        tier: str = Query(default="epic"),
        contract: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return _service(request).bench(step, tier=tier, contract=contract)

    # --- Writes (AD-21: the closed allowlist) ----------------------------

    @app.post("/acknowledgements")
    async def submit_acknowledgement(request: Request) -> dict[str, Any]:
        return _service(request).submit_acknowledgement(await _authorized(request))

    @app.post("/swap-executor")
    async def swap_executor(request: Request) -> dict[str, Any]:
        return _service(request).swap_executor(await _authorized(request))

    @app.post("/skill-bump-regression")
    async def skill_bump_regression(request: Request) -> dict[str, Any]:
        return _service(request).skill_bump_regression(await _authorized(request))

    @app.post("/skill-bump-promote")
    async def skill_bump_promote(request: Request) -> dict[str, Any]:
        return _service(request).skill_bump_promote(await _authorized(request))

    @app.post("/cost-overrun-ack")
    async def cost_overrun_ack(request: Request) -> dict[str, Any]:
        return _service(request).cost_overrun_ack(await _authorized(request))

    @app.post("/regression-set-remove")
    async def regression_set_remove(request: Request) -> dict[str, Any]:
        return _service(request).regression_set_remove(await _authorized(request))

    @app.post("/project-edit-lock")
    async def project_edit_lock(request: Request) -> dict[str, Any]:
        return _service(request).project_edit_lock(await _authorized(request))

    return app


def _service(request: Request) -> DashboardPort:
    return request.app.state.service


async def _authorized(request: Request) -> dict[str, Any]:
    """Return the signed payload, or raise 401 / 400.

    Verification runs against the **raw parsed JSON**, not a validated model, so
    the dict the signature was computed over is byte-identical to the dict the
    port receives. A pydantic model would be free to apply defaults or coerce
    values between the two, which would make a valid signature unverifiable.
    """
    raw = await request.body()
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail={"error": "malformed_json",
                                                     "message": str(e)}) from e
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400,
                            detail={"error": "payload_must_be_object"})
    signature = request.headers.get("X-Harness-Signature", "")
    if not signature or not _service(request).verify_write_signature(payload, signature):
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_harness_signature"},
        )
    return payload


__all__ = ["create_app"]
