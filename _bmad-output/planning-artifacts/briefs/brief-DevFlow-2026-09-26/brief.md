# Product Brief: DevFlow

**Status:** draft (headless)
**Generated:** 2026-09-26
**Workspace:** `_bmad-output/planning-artifacts/briefs/brief-DevFlow-2026-09-26/`

> Headless draft derived from the user's 5 stated goals (G1–G5) and the two local documents `DevFlow_BMAD_Herdr_Design_v1.0.md` (v1.0 Draft) and `BMAD 对比提案.md` (Sep 26 2026). Not yet reviewed by the user. Items inferred from sparse inputs are tagged `[ASSUMPTION]`.

---

## Executive Summary

DevFlow is a long-lived AI agent platform for software development in which the **development workflow stays fixed while the agents, LLMs and skills behind each step can be swapped and benchmarked across projects**. The workflow runs six steps — Research → Design → Coding → Testing → Review → Delivery — and treats every artifact (`research.md`, `design.md`, code, `test-report.json`, `review.md`) as a versioned contract that makes runs comparable and re-runnable.

The platform exists because today's AI coding agents are interchangeable for the user but opaque underneath: which agent + which LLM + which skill wins on which step of which project? DevFlow answers that by collecting structured runs, structured errors, and per-step success rates, then feeding the lessons back into Skills and step routing.

It is **not** a coding agent itself and **not** a BMAD replacement — it sits one layer up as the **harness / control plane**, with **BMAD Method as the method layer** that supplies per-step skills (`bmad-deep-recon`, `bmad-spec`, `bmad-build`, `bmad-retrospective`, …), and a runtime called **Herdr** underneath as an optional execution observation layer.

## The Problem

Today, an engineer who wants to use AI for a software project has to choose, per step, among many agents (Pi, OMP, Codex, Claude Code, …), many LLMs (GPT, Claude, Gemini, MiniMax, DeepSeek, Qwen, Ollama), and many skills. None of those choices are repeatable: switching agent mid-project loses context, switching LLM resets the prompt tuning, and switching skill breaks the workflow shape. Three concrete pains:

1. **The workflow drifts.** Teams keep redefining "design" and "review" every time a new agent shows up. There is no fixed spine, so artifacts stop being comparable.
2. **Errors are lost.** When a step fails, the failure mode (wrong requirement, wrong skill, bad test coverage, …) lives in a Slack thread and dies.
3. **There is no learning loop.** Even after ten projects, the team still does not know which Agent/LLM/Skill combo wins on which step. Recommendations are vibes, not data.

## The Solution

A fixed **software-v1** workflow that any Project runs, plus a project-level config that names the Agent, LLM and Skills per step:

```yaml
project: P3-sap-btp-app
pipeline: software-v1
size: epic          # trivial | session | epic | project
steps:
  research: { mode: agent,  agent: pi,    model: <id>, skills: [bmad-deep-recon@x, sap-integration@1] }
  design:   { mode: agent,  agent: omp,   model: <id>, skills: [bmad-prd@x, bmad-architecture@x, bmad-spec@x] }
  coding:
    mode: agent
    agent: codex
    model: <id>
    skills: [bmad-preview-ticketing@x, bmad-build@x, business-logic-review@1]
    human_first_stories: 2
    story_gates: [S1, S3]
  testing:  { mode: agent,  agent: pi,    model: <id>, skills: [testing@2] }
  review:   { mode: human,                   skills: [bmad-retrospective@x] }
  delivery: { mode: human }
```

The same workflow can be run by a human or by an Agent (`mode: human | agent`). Artifacts are content-hashed and locked at each Gate. Errors are appended to a structured store. Across projects, a benchmark picks the best Agent/LLM/Skill on the regression set, not on raw success rate.

## What Makes This Different

Three honest differentiators — no fabricated moats:

- **Fixed workflow, swappable execution.** Most platforms either fix both workflow and execution (rigid) or fix neither (chaotic). DevFlow fixes the workflow at version `software-v1` and lets execution vary per step, per project.
- **Artifact-as-contract.** Each step's output is the next step's input. A `SPEC.md` approved in Design gates Coding; a `test-report.json` gates Review. Replacing an Agent mid-run does not break the chain.
- **Per-step BMAD skills, locked by version.** BMAD supplies how each step is done (deep-recon, spec, prd, architecture, build, retrospective). The harness owns the version (`@x`) and treats a BMAD upgrade as a Skill bump that must pass the regression suite.

`[ASSUMPTION]` What it is **not**: not a single-agent wrapper, not a UI product, not a chat tool. The UI surface — if any — is operator dashboards (run status, error store, regression diffs), not an end-user product.

## Who This Serves

**Primary:** Platform / DevEx engineers inside a small team (1–5 people) who run 3+ AI-assisted software projects and want to stop re-deciding their stack per run. Success for them is: same workflow, different Agent/LLM/Skill combinations, every project adds one comparable data point.

**Secondary:**
- Tech leads who need a defensible way to recommend an Agent/LLM to their org (data, not opinion).
- Solo consultants whose client engagements are short enough that workflow churn costs real hours.

**Explicitly not for:** teams that have already standardized on one agent stack and do not plan to benchmark alternatives.

## Success Criteria

| # | Signal | Target |
|---|--------|--------|
| S1 | A new project goes from `pipeline: software-v1` config to first `delivery` artifact with the same six steps in the same order, regardless of which Agent/LLM/Skill combination runs each step | 100% of runs use the fixed workflow |
| S2 | Per-step Agent/LLM/Skill swap mid-project without re-running prior steps | supported by versioned artifacts + content hash |
| S3 | Every failed step lands in the error store with category, root cause, correction, retry outcome | ≥ 95% of failures logged |
| S4 | After ≥ 3 projects, the platform picks a step's Agent/LLM/Skill from a regression set, not from "vibes" | one benchmark-driven recommendation per step |
| S5 | BMAD Skill upgrades pass regression before they are promoted | 0 promoted regressions |

## Scope

**In for v1 (this brief):**
- Six-step `software-v1` workflow with content-hashed artifact contracts
- Project-level YAML config naming Agent, LLM, Skills (with `@version`) per step
- Step-level Gate (human approval) and Artifact locking
- Structured error store (category / root cause / correction / retry / result)
- Static Agent/LLM router for v1; **deferred** dynamic router (success-rate-based selection)
- BMAD Method (`bmod-method`) skills wired in as the per-step "how"
- Herdr runtime as an **optional** execution observation layer, not the control plane

**Explicitly out for v1:**
- End-user UI / chat product
- Cross-org multi-tenant
- Auto-promotion of BMAD Skill upgrades (manual promotion only)
- A custom fine-tune of any underlying LLM
- Native integration with every Agent (Pi / OMP / Codex / Claude Code / DSH) — start with 1–2, add as adapters

## Goals (verbatim from user)

| ID  | Goal                       | Mechanism in this design                          |
| --- | -------------------------- | ------------------------------------------------- |
| G1  | Development workflow fixed | Workflow definition versioned (`software-v1`); immutable at runtime |
| G2  | Each step manual or auto   | Uniform step contract; executor selectable: `human` or `Agent` |
| G3  | Each step can swap Agent / LLM / Skills | Project config + executor adapter; swap executor, keep workflow |
| G4  | Step linkage, human ack, controllable | Artifact version lock + Acknowledgement Gate + state machine |
| G5  | Error accumulation, review, change      | Error case store + improvement proposals + regression evaluation |

## Open Questions

- [ ] Where does the static v1 router live — in this repo or as a sidecar?
- [ ] What is the smallest v1 artifact schema for `test-report.json`? (BMAD does not ship one — must be designed here.)
- [ ] Herdr: observation only, or also process lifecycle (start/stop/restart agents)? The design doc says optional; need a v1 stance.
- [ ] BMAD Skill version pin: pin in project YAML (`@x`) or follow latest with regression gate? Document suggests pin + regression.
- [ ] What is the v1 acceptance for "human approval Gate"? Comment on a commit, signed approval on the artifact, or a separate approval record?

## Vision

Two to three years out: DevFlow is the harness a small AI-native team uses the way a JFrog / Buildkite user uses CI today — they open it, pick the pipeline (`software-v1`, then probably `data-v1`, `ml-v1`), point it at a repo, and forget which Agent ran it. The benchmark data lives in the open; third parties publish Agent/LLM/Skill packs that pass the regression set. BMAD ships core method skills; DevFlow is one of several harnesses that consume them.

`[ASSUMPTION]` Long-tail risk: if a single dominant Agent+LLM stack wins and the team standardizes on it, the value of swappable execution collapses. Mitigation: keep the workflow fixed and the artifact contract clean even when only one stack is in use; the platform stays useful as an audit + reproducibility layer.

---

## Handoff Status

```json
{
  "status": "complete",
  "intent": "create",
  "brief": "_bmad-output/planning-artifacts/briefs/brief-DevFlow-2026-09-26/brief.md",
  "addendum": "_bmad-output/planning-artifacts/briefs/brief-DevFlow-2026-09-26/addendum.md",
  "memlog": "_bmad-output/planning-artifacts/briefs/brief-DevFlow-2026-09-26/.memlog.md",
  "open_questions": [
    "Static v1 router location",
    "test-report.json v1 schema",
    "Herdr v1 scope (observe vs lifecycle)",
    "BMAD Skill version pin policy",
    "Human Gate acceptance shape"
  ],
  "external_handoffs": []
}
```