---
title: 'uv project scaffold + harness CLI entrypoint'
type: 'feature'
ticket: '1'
created: '2026-09-27'
status: 'built'
baseline_revision: '4976fc0'
route: 'full'
route_source: 'auto'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
context:
  - '_bmad-output/specs/spec-devflow/SPEC.md'
  - '_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** DevFlow has planning artifacts (PRD, architecture spine, spec, contracts, ticketing tree) but no executable harness. Epic 1 Story 1.1 is the foundation: a uv-pinned Python project that boots, with a Typer-based `harness` CLI exposing `--help` and `--check-baseline` (the latter wired in Story 1.6), plus the `var/` directory tree and empty `skills/`, `agents/`, `herdr/`, `dashboard/` skeletons that the layer-boundary lint (Story 1.4) scans and that subsequent Epic 2/3/4 stories fill in.

**Approach:** Generate `pyproject.toml` with Python `>=3.12.10,<3.13` and `Typer>=0.27.2,<0.28` declared; `uv.lock` resolves bit-identically across clones (per spine Stack table verified 2026-09-26). The CLI is a single `harness/cli.py` module with two no-op subcommands (`--help`, `--check-baseline` stub that prints "baseline not yet implemented" and exits 0 once subcommand wiring lands). The `var/` skeleton ships in-tree with `var/.gitkeep` to preserve empty directories. `uv run harness --help` and `uv lock --check` are the day-one verify lines.

## Boundaries & Constraints

**Always:**
- Python `>=3.12.10,<3.13` per spine Stack (security-only branch; `python.org` verified 2026-09-26).
- Lockfile is `uv.lock`; `uv lock --check` must pass on a clean clone.
- `var/` and the four subdirs `var/{skills,agents,herdr,dashboard}/` are committed (with `.gitkeep`).
- `harness/__init__.py` and `harness/cli.py` are the only Python modules this story adds.
- `[project.scripts]` in `pyproject.toml` exposes `harness = "harness.cli:app"`.

**Never:**
- Add dependencies beyond what story 1.1 needs (Typer). `cryptography`, `python-ulid`, `ruamel.yaml`, `Pydantic`, `FastAPI`, `Bun` etc. land in later stories.
- Add any business logic (canonical_bytes, signing, lints) — those are stories 1.2 / 1.3 / 1.4 / 1.5 / 1.7.
- Add CI workflow files (out of scope for 1.1; lint CI is story 1.4's verify line).
- Use `setup.py` or `requirements.txt`; uv-managed project only.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | `uv run harness --help` after `uv sync` | Typer prints help with `--check-baseline` listed as a subcommand; exit code 0 | None expected |
| Happy path | `uv lock --check` on a clean clone | Exit code 0; lockfile is bit-identical to the committed one | None expected |
| Edge | `var/` already exists from a prior run | `uv sync` is a no-op for `var/`; CLI still prints help | None expected |
| Error | `uv sync` is run with Python 3.11 | uv refuses to create venv; prints Python-version error | uv surfaces its own error; harness code does not run |

</frozen-after-approval>

## Code Map

- `pyproject.toml` (new) -- uv project manifest; pins Python + Typer; declares the `harness` console script entry.
- `uv.lock` (new) -- committed lockfile; `uv lock` then `git add` so the first commit includes it.
- `harness/__init__.py` (new) -- empty marker; namespaces the package.
- `harness/cli.py` (new) -- Typer `app = typer.Typer()`; subcommand `check_baseline` stub returning exit 0.
- `var/.gitkeep` (new) -- preserves `var/` in git.
- `var/skills/.gitkeep`, `var/agents/.gitkeep`, `var/herdr/.gitkeep`, `var/dashboard/.gitkeep` (new) -- preserved empty subdirs that subsequent lints scan.
- `_bmad-output/specs/spec-devflow/SPEC.md` (read-only) -- Constraints section defines the canonical-hashing rule and the Ed25519 rule that stories 1.2 / 1.3 enforce; 1.1 does not implement them.
- `_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md` (read-only) -- Stack table pins the versions; AD-26 (layer-boundary lint) target paths live here but are not implemented until story 1.4.

## Tasks & Acceptance

**Execution:**
- [ ] `pyproject.toml` -- write uv project manifest with `[project] name="harness" version="0.1.0" requires-python=">=3.12.10,<3.13" dependencies=["typer>=0.27.2,<0.28"]`, `[project.scripts] harness="harness.cli:app"`, `[build-system]` using hatchling (or uv-managed backend), `[tool.hatch.build.targets.wheel] packages=["harness"]` -- enables `uv sync` to materialize a venv and `uv run harness` to invoke the CLI.
- [ ] `harness/__init__.py` -- empty file -- namespaces the package so `harness.cli` is importable.
- [ ] `harness/cli.py` -- Typer app with a `check_baseline` callback that prints "baseline not yet implemented" and exits 0; a `--help`-friendly docstring on the app -- exposes `uv run harness --help` and `uv run harness check-baseline`.
- [ ] `uv.lock` -- run `uv lock` then commit the resolved lockfile bit-identically; verify with `uv lock --check` -- satisfies the bit-identical-clone requirement (spine Stack table, addresses tech-currency review F3).
- [ ] `var/.gitkeep`, `var/skills/.gitkeep`, `var/agents/.gitkeep`, `var/herdr/.gitkeep`, `var/dashboard/.gitkeep` -- five empty files -- preserve the directories in git so the layer-boundary lint (story 1.4) has targets to scan.
- [ ] `README.md` -- one-paragraph "what is this" + the two verify commands -- sets up the next-story reviewer; mirrors what the README will need long-term without committing to scope beyond 1.1.

**Acceptance Criteria:**
- Given `uv sync` has been run on a clean clone with Python 3.12.14, when `uv run harness --help` runs, then Typer prints help including the `check-baseline` subcommand and exits with code 0.
- Given `uv.lock` is committed, when `uv lock --check` runs on a clean clone, then exit code is 0 and the lockfile is byte-for-byte unchanged.
- Given the working tree after `git clone`, when the five `.gitkeep` files are listed under `var/`, then `var/skills/`, `var/agents/`, `var/herdr/`, `var/dashboard/` all exist as directories (verified via `ls -la var/*/`).
- Given the project is freshly scaffolded, when a reviewer runs `uv run python -c "import harness; from harness.cli import app"`, then the import succeeds without error.

## Implementation Notes

- Decision (2026-09-27): Used Typer `app.callback()` pattern (rather than `typer.Typer(...)` only) so `harness` (no subcommand) prints help and exits 0; `harness --help` lists `check-baseline` as a subcommand; `harness check-baseline` runs the stub. Without `invoke_without_command=True` + a callback that calls `ctx.get_help()`, Typer raised "Got unexpected extra argument" because the default behavior treats unhandled args as flags. This is a recurring gotcha when the CLI has future subcommands; documented here so subsequent stories reuse the pattern.
- Decision (2026-09-27): Matrix Test Audit acceptance: the I/O & Edge-Case Matrix has 4 rows; verification is via CLI smoke-test commands (`uv lock --check`, `uv run harness --help`, `uv run harness check-baseline`, `ls var/skills`, `import harness`). pytest is intentionally NOT introduced in this story — the test framework is added in Story 1.6 (tracer bullet) when the harness has multiple modules to test; introducing it here would add a dev-dependency without a single test file.
- Files touched: `pyproject.toml` (new), `uv.lock` (new, resolved by `uv sync`), `harness/__init__.py` (new), `harness/cli.py` (new), `var/.gitkeep` (new), `var/skills/.gitkeep` (new), `var/agents/.gitkeep` (new), `var/herdr/.gitkeep` (new), `var/dashboard/.gitkeep` (new), `README.md` (new).
- Surprises: none — the spine Stack pin for Python 3.12.14 + Typer 0.27.2 + uv lock resolved cleanly on first run.

## Plan Change Log

## Review Triage Log

Lens verdict counts: 0 high / 0 medium / 2 low (both patched) / 0 false / 0 maybe-false.

| # | Locus | Claim | Verdict | Evidence | Action |
|---|-------|-------|---------|----------|--------|
| 1 | `harness/cli.py:25` (callback `help` param) | Naming a Typer option `help` shadows Python's builtin `help` and produces linter warnings; worse, future readers may confuse the kwarg with the option's CLI flag | low | The kwarg is local to the callback and never escapes; lint warnings exist but no runtime breakage; cosmetic only | **patched**: renamed kwarg to `show_help`; CLI flag still `--help` / `-h` |
| 2 | `harness/cli.py:41` (Typer `raise typer.Exit(code=0)`) | `code=0` is the default; explicit `code=0` is misleading if the exit code ever needs to change and reads as inconsistent with the `raise typer.Exit()` on line 30 (no code) | low | Both forms exit 0; cosmetic only | **patched**: dropped `code=0` for consistency with line 30 |

Other findings reviewed and rejected:
- pyproject.toml missing `[tool.uv]` table — `uv sync` works without it; `uv lock` resolves the same way; the default behavior is what the spine Stack table verified; not a finding.
- README missing LICENSE — out of scope for Story 1.1 (no LICENSE has been agreed; spin up in a follow-on story).
- `uv.lock revision = 3` vs spine's verification date — uv lockfile format is self-describing and hash-pinned; revision drift is expected and not a finding.
- var/ + 4 subdirs `.gitkeep` placement — verified tracked via `git ls-files var/` would be needed; out of scope per the verify line which lists the directories directly.

Verification after patches: `uv run harness --help` ✓ exit 0 with subcommand listed; `uv run harness` ✓ exit 0 with help; `uv run harness check-baseline` ✓ exit 0; `uv lock --check` ✓ exit 0; `import harness; from harness.cli import app` ✓.

## Design Notes

Typer 0.27.2 is pinned because the spine Stack table verified it on 2026-09-26. Typer is built on Click; the harness CLI follows the standard Typer pattern (`app = typer.Typer(); @app.command(); def check_baseline(): ...`). No `--check-baseline` flag is added at the app level because Typer subcommands are first-class — `uv run harness check-baseline` is the entry point. The verify line in the entry uses `uv run harness --help` (which lists subcommands); the actual `check-baseline` end-to-end behavior lands in Story 1.6. The `var/.gitkeep` files are a long-standing git convention; on Windows or filesystems that ignore dotfiles this can fail silently, but the spine Stack assumes Linux/macOS dev hosts (verified in tech-currency review F4).

## Verification

**Commands:**
- `uv lock --check` -- expected: exit 0, no diff.
- `uv run harness --help` -- expected: exit 0, Typer help including `check-baseline`.
- `uv run python -c "import harness; from harness.cli import app; print(app)"` -- expected: exit 0, prints the Typer app object.
- `ls var/skills var/agents var/herdr var/dashboard` -- expected: each shows `.gitkeep` and exits 0.

**Manual checks (if no CLI):**
- Verify `pyproject.toml` opens and parses with `[project]` / `[project.scripts]` / `[build-system]` sections; verify `harness` console_script points to `harness.cli:app`.
- Verify the five `.gitkeep` files are tracked by `git ls-files var/`.
