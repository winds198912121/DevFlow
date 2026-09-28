# Glossary

Every term used in SPEC.md kernel fields, in their canonical form. Numbers in `[ ]` are PRD FR / NFR / spine AD references; same numbers you find in source documents. Where two sources name the same thing differently, this glossary picks one and cross-references the alias.

## Core nouns

- **Pipeline** — A named, versioned, immutable workflow definition. v1 ships exactly one: `software-v1`. The pipeline's six steps and their artifact contracts are fixed for the version. [FR-1, FR-2, AD-1]
- **Step** — One of `research | design | coding | testing | review | delivery`. A pipeline is an ordered sequence of steps. Each step has an artifact contract, a Gate, and an executor slot. [FR-3]
- **Project** — A single unit of work bound to one pipeline, one project-level YAML, and a run history. Identified by `project_id`. [FR-4]
- **Run** — One execution of a project's pipeline. A project has N runs over its lifetime. Identified by `run_id`. [FR-4]
- **Step output** — The artifact produced by a step in a run (e.g. `research.md`, `SPEC.md`, `test-report.json`). Content-hashed (`sha256:`) and version-locked at the Gate. [FR-11, FR-17]
- **Executor** — The runtime that performs a step. Either `mode: human` or an Agent + LLM + Skills tuple. [FR-5, FR-8]
- **Agent** — A coding / execution agent runtime (Pi / OMP / Codex / Claude Code / DSH). [PRD Glossary, AD-10]
- **LLM** — The large language model backing an Agent in `mode: agent` runs. [PRD Glossary]
- **Skill** — A BMAD Method skill pinned by version (e.g. `bmad-deep-recon@0.4.2`). Skills are pinned per-step in the project YAML; auto-upgrade is forbidden. [FR-6, AD-6]
- **Gate** — The handoff between two steps. Requires an Acknowledgement before the next step's input is unlocked. [FR-9, FR-10, AD-11]
- **Acknowledgement** — The signed record that a Gate was approved. Either human or automated; both use the same record shape. [FR-10, AD-5]
- **Artifact lock** — A step output that has cleared its Gate. Locked artifacts are immutable and content-addressed. [FR-11]
- **Artifact hash** — `sha256:` content hash of a step output. Stable across reads and re-renders with identical inputs and executor tuples. [FR-17, AD-17]
- **Artifact contract** — The schema a step output must satisfy to enter the Gate. Owned by the BMAD step skill (testing owns `test-report.json`; see `step-skill-map.md`). [FR-3]
- **Executor invocation token** — Harness-signed `{invocation_id, project_id, run_id, step, executor_tuple_hash, expires_at}` carried by every Step Executor Port call. Agent adapters validate the signature before reading locked inputs. [AD-10]

## Records & stores

- **Error record** — Append-only entry in the error store after a step fails. Has `category`, `root_cause`, `correction`, `retry`, `result`. Immutable post-write. [FR-13, FR-14, AD-4]
- **Error category** — Closed list: `requirement | research | design | coding | testing | review | agent | llm | skill | tool | environment | integration`. [PRD addendum §5]
- **Run event** — Append-only entry in the Run Event Log written by the harness on every state transition. Includes `event_id`, `project_id`, `run_id`, `step`, `executor_tuple`, `executor_tuple_hash`, timestamps, outcome, `gate_mode`, cost tokens, and optional pointers (`confirm_id?`, `error_record_id?`, `acknowledgement_id?`). Source of truth for NFR-Obs-1. [AD-14, NFR-Obs-1]
- **Cost ledger** — Append-only ledger of token usage per step, per run. Surfaced as per-run totals on the dashboard; ceiling enforcement reads here. [NFR-Cost-1, NFR-Cost-2, AD-20]
- **Regression set** — Curated set of past runs (artifacts + executor tuples + outcomes) used to benchmark new skills / agents / LLMs. Additions are append-only; removals require written justification. [FR-20, FR-21, AD-7]
- **Skill Bump Registry** — The only path to a new BMAD Skill version. Bumps sit in `pending_promotion` after regression passes; operator must manually promote. [FR-22, FR-23, AD-6]
- **Herdr mirror** — Read-only SQLite at `var/herdr_mirror.sqlite` that stores ingested Herdr events. Never joined to canonical stores; never contributes derived fields. [AD-19]

## Topology & ownership

- **Harness** — DevFlow itself. Owns pipeline definition, project state, Gates, locks, error store, regression set, benchmark, cost ledger, run event log. The control plane. [PRD Glossary, spine Scope]
- **Method layer** — BMAD Method skills (`bmod-method`). Owns the per-step "how" — pinned versions are treated as Skill bumps that must pass the regression set. [PRD Glossary]
- **Execution layer** — Agent adapters under `agents/<adapter>/`. Each adapter declares its auth mode (`bearer | oauth | cli-resident`) in its adapter manifest, not in the harness. [AD-10]
- **Herdr** — Out-of-process observability feed (PRD A6, OQ-8 stance a). Optional. NOT the control plane. Forwards events to operator dashboards / audit / replay; advisory only. [AD-9]
- **ExecutorAdapter** — Harness-internal port that owns auth + lifecycle + error mapping for one Agent. Implementations live under `agents/<adapter>/`. Spine contract: `start(capability) / cancel(id) / status(id) → outcome`. [AD-10, PRD A6]

## Status values

- **Done** — Terminal state of a `trivial`-tier step or a `session`-tier step whose Gate was skipped (FR-10). Distinct from `Locked`: `Done` does not carry an Acknowledgement; the run event carries `gate_mode: skipped`. [FR-10, FR-12, AD-11]
- **Locked** — Terminal state of a step whose Gate was enforced and Acknowledged. Artifact is content-hashed and immutable. [FR-11, AD-11]
- **Pending** — Step is in flight or awaiting Acknowledgement. [AD-24]
- **Failed** — Step errored; an error record exists; retry ladder is engaged or paused for human intervention. [FR-13, AD-24]

## Size tiers & policy

- **Project size tier** — One of `trivial | session | epic | project`. Drives Gate strictness (FR-12). [FR-12, addendum §4]
- **Bench query** — `bench <step>` returns a recommended Agent / LLM / Skills tuple from the regression set. Refuses (`regression_set_insufficient`) below K comparable runs. [FR-21, NFR-Reliab-3]
- **Retry ladder** — Five rungs in fixed order: same → same LLM → better LLM → different agent + promoted skill → human. Each rung persisted. [FR-15]
- **Cost overrun ack** — Operator acknowledgement that lifts a per-tier cost-ceiling pause. [AD-8, NFR-Cost-2]
- **Operator dashboard** — v1 UI surface. Read model over the canonical stores; six allowed writes per AD-21. Not an end-user surface. [FR-24..27, AD-13, AD-21]

## Security / hashing

- **Canonical bytes** — The single function `harness.canonical.canonical_bytes(value) -> bytes`. Only path to `sha256:` for any value (artifacts, executor tuples, run events, Acknowledgement records, error records, Herdr events, project YAML). [AD-17]
- **Harness signing key** — Ed25519 key at `var/secrets/harness.key` (0600). Signs Acknowledgements (AD-5), invocation tokens (AD-10), and artifact hashes on lock (NFR-Sec-1). [NFR-Sec-1, NFR-Sec-2]
- **Path triple** — The `(project_id, run_id, step)` triple in the storage path of an Acknowledgement record. Covered by the Acknowledgement signature to defeat cross-project copy-paste forgery. [AD-23]

## Aliases

- `BMAD Skill pin` ≡ Skill (the version suffix is the pinning).
- `Run Event Log` ≡ Run event store.
- `ExecutorAdapter` ≡ Step Executor Port implementation; both refer to the same contract from different perspectives (architectural port vs adapter pattern).
- `Herdr Event Port` is the harness-side ingestion interface; `Herdr mirror` is the storage; both refer to the same observability stream.
