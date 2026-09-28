# Operator Dashboard

The AD-13 read-model surface: four read-only views over the canonical harness
stores, plus the seven AD-21 write paths. TypeScript, built with Bun, served by
FastAPI.

```bash
cd dashboard
bun install                 # once
bun test                    # view tests
bunx tsc --noEmit           # typecheck
bun run build               # -> dist/{main.js,index.html}

cd ..                       # run it (build first; dist/ is not committed)
uv run harness serve --demo                     # seed demo data
uv run uvicorn tools.dashboard_serve:app --port 8137
```

Every `uv run pytest` run also covers this directory (the SPA tests shell out to
`bun` and skip if it is absent).

## Layout

| Path | Role |
| --- | --- |
| `index.html` | Shell markup: the four tabs, the shared input row, the filter row |
| `src/api.ts` | Payload types + the HTTP client. The **only** module that names the raw status vocabulary |
| `src/run-status.ts` | View 1 — step terminal status (FR-24) |
| `src/error-store.ts` | View 2 — errors with the FR-25 filter surface + pagination |
| `src/regression-diff.ts` | View 3 — per-step pass/fail, FR-18 comparability |
| `src/benchmark-output.ts` | View 4 — recommendation, metric, contributing runs (FR-21) |
| `src/main.ts` | Shell: fetches, holds the page cursor, mounts the views |
| `render-cli.ts` | Render one view from a JSON payload on stdin (used by the Python tests) |
| `dist/` | Build output; mounted at `/` by `tools/dashboard_serve.py` |

## Rules that shape the code

**Views are pure.** Each view exports `render*(payload)` returning an HTML
string: no fetching, no module state, no clock. `src/main.ts` owns all I/O and
the single piece of permitted state (the pagination cursor, AD-13). This is what
lets the Python suite pipe a real endpoint response through a real view
(`render-cli.ts`) and assert the two agree.

**AD-24 — one terminal-status resolver.** A step's terminal status comes from
`/runs/{id}`, which delegates to `harness.workflow_controller.step_status`.
Views may render the resolver's *outputs* (`terminal`, `gate_mode`) and must not
read its *inputs* (`verdict`, `outcome`, `confirm_id`, `acknowledgement_id`) —
reading those is one `if` away from a second, divergent status rule.
`tools/check_terminal_status.py` enforces both clauses (AD-24 (d)) and runs in
`harness check-baseline`. `src/api.ts` is the one exempt module: it declares the
payload types, so it must name those fields.

**AD-21 — the write allowlist.** The API's write routes live in
`dashboard/main.py`, where `tools/check_dashboard_writes.py` scans them.
Registering an eighth write breaks CI.

**AD-26 — layer boundary.** `dashboard/**/*.py` may import `harness.*` only
through `harness.ports`. That is why the SPA talks HTTP to a harness-side read
model (`harness/dashboard_service.py`) instead of importing stores, and why the
composition root is `tools/dashboard_serve.py` — outside the four layer roots,
the only place allowed to bind both sides.

**Shell element ids.** `src/main.ts` exports `REQUIRED_ELEMENTS`, derived from
the same constants it uses for lookups; `mount` refuses to start if any is
missing from `index.html`, and a test pins the list against the markup. Renaming
an input without renaming its lookup fails loudly at boot instead of in one tab.
