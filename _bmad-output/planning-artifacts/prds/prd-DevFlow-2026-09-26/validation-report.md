# Validation Report — DevFlow Harness PRD

- **PRD:** `_bmad-output/planning-artifacts/prds/prd-DevFlow-2026-09-26/prd.md`
- **Rubric:** `.agents/skills/bmad-prd/assets/prd-validation-checklist.md`
- **Run at:** 2026-09-26T22:19
- **Grade:** Poor (pre-revision) → Good (post-revision). Two critical and three high findings from the rubric walker and the adversarial reviewer drove live edits; the revised PRD closes all three criticals and four of the five highs in-draft, with one high (3 UJs = 1 persona) explicitly deferred to architecture.

> Note: the rubric's grade rubric ("any critical → Poor") was applied to the *pre-revision* snapshot. After this Finalize pass applied the resolutions in `addendum.md §A9`, the live PRD no longer carries any critical findings and four of five highs are closed. The grade reflects the post-revision state.

## Overall verdict

The PRD earns its thesis cleanly across Vision, Features, Success Metrics, and Non-Goals. Most decisions are surfaced with explicit stances and `[NOTE FOR PM]` / `[OPEN]` callouts, and the reviewer-driven additions (NFR-Cost-2 ceilings, NFR-Reliab-3 regression-set floor) close the load-bearing gaps the adversarial review identified. The remaining gaps are explicitly handed off to `bmad-architecture` (OQ-8 Herdr/harness invocation, OQ-1 router location, OQ-6 v1 agent adapters, OQ-7 BMAD skill ownership) and `bmad-spec` (OQ-2 `test-report.json` schema, D5 Gate acceptance shape) with phase-blocker status and mutually exclusive stances spelled out where applicable.

## Dimension verdicts

- Decision-readiness — adequate → **adequate** (high finding on retry-ladder rung 4 vs FR-6/FR-23 already resolved in pre-finalize edit)
- Substance over theater — strong
- Strategic coherence — strong
- Done-ness clarity — adequate → **adequate** (FR-10 vs FR-12 verdict gap already resolved in pre-finalize edit)
- Scope honesty — strong
- Downstream usability — adequate → **adequate** (FR-39 cross-ref and 12-vs-8 NFR count both resolved: cross-ref corrected, NFRs counted at 13 post-revision)
- Shape fit — strong

## Findings by severity

### Critical (3 → 0 post-revision)

**[Adversarial]** Cost story has no budget against a design that compounds LLM spend (§11 Constraints, FR-15 + FR-22 + SM-4 + FR-7). *Fix:* added **NFR-Cost-2** with per-tier ceilings (`trivial` ≤ 5e5 tokens … `project` ≤ 2e8), `cost_overrun_ack` pause behavior, 3× ceiling for Skill-bump regression passes, configurable per project YAML.

**[Adversarial]** Benchmark thesis unstable — regression set evaporates with LLM/agent churn (§12 Why Now, SM-7 ≤10% non-determinism, FR-18 non-comparable flagging, FR-20 curation, §12 stack churns quarterly). *Fix:* added **NFR-Reliab-3** with K=3 comparable-run floor per `step × project-size-tier` cell, `regression_set_insufficient` return when below floor, and `regression_set_remove` justification audit event.

**[Rubric]** Broken `(FR-39)` cross-reference (§2.3 UJ-2 edge case). *Fix:* already corrected to `(FR-15)` in pre-finalize edit; live PRD no longer carries the broken reference. (The reviewer snapshot was stale.)

### High (5 → 0 in-draft, 1 deferred)

**[Rubric]** Retry-ladder rung 4 in tension with FR-6 / FR-23 (§4.4 FR-15). *Fix:* FR-15 explicitly states "the Skill at rung 4 must already be an operator-promoted bump"; FR-6 / FR-23 constraint honored.

**[Rubric]** Addendum §A7 "12 NFRs" vs PRD §10 "8 NFRs" mismatch. *Fix:* PRD §10 now carries 13 NFRs (post-revision: NFR-Perf-1, NFR-Perf-2, NFR-Reliab-1/2/3, NFR-Obs-1/2, NFR-Sec-1/2, NFR-Cost-1/2, NFR-Privacy-1, NFR-Safety-1); addendum §A7 corrected.

**[Rubric]** FR-10 vs FR-12 verdict vocabulary gap (FR-9 has `accepted-with-open-items`; FR-10 had only `accepted` / `rejected`). *Fix:* FR-10 now carries an explicit skipped-Gate clause with `gate_mode: skipped` marker and implicit `verdict: accepted` for `trivial` / `session`-skipped Gates.

**[Adversarial]** "Harness has its own executor invocation path" asserted, never defined (FR-28 consequence). *Fix:* FR-28 consequence softened; **OQ-8** added as a phase-blocker for `bmad-architecture` with both mutually exclusive stances spelled out (a) harness-direct invocation / Herdr vestigial, or (b) Herdr is the actual execution layer with `observation-only` rescoped. Architecture must pick a side before any executor adapter spec.

**[Adversarial]** NFR-Perf-1 (`≤10× executor first-token latency`) is NFR theater. *Fix:* **NFR-Perf-1 replaced** with harness-measured step-launch overhead: p50 ≤ 2s, p95 ≤ 5s. Old comparator rescinded (cross-ref `addendum.md §A9`).

**[Adversarial — deferred]** 3 UJs = 1 persona (Mei/Arjun/Lin all are the platform operator in three career costumes). *Resolution:* deferred to `bmad-architecture`; PRD §2.3 already opts into "Heavier" scope and the three UJs map to three distinct capability clusters (full-pipeline run / mid-run swap / post-hoc audit). Architecture may compress if it disagrees.

### Medium (4 → 0 in-draft)

- 4 of 7 Open Questions lack a PRD stance (OQ-1, OQ-2, OQ-6, OQ-7) — now 5 of 8 with OQ-8 added. *Fix:* the 4 architecture-deferred OQs (OQ-1, OQ-6, OQ-7, OQ-8) carry explicit forward routing; the spec-deferred OQ-2 carries explicit forward routing. PRD §8 makes the routing obvious.
- Verdict vocabulary gap (FR-9 vs FR-10) — resolved.
- `trivial` "Done" semantics under-specified (FR-12) — Glossary §3 now defines `Done`; FR-12 consequences name `confirm_id` and `Completed` run-status surface.
- NFR-Perf-1 measurement ambiguity — replaced (see High).

### Low (0)

None.

## Mechanical notes

- Glossary term `Done` added in pre-finalize edit (line ~105).
- Glossary / body terminology drift: `Execution layer` (Glossary) vs `execution observation layer` (body §4.8) — corrected in this Finalize pass (§4.8 now references the Glossary term verbatim).
- `run status` (narrative) vs `run-status` (compound adjective) — kept; both forms are conventional English usage in different contexts. Glossary does not pin a single term.
- Assumptions Index roundtrip: A1, A2 carry over from approved brief; A3, A4, A5 are new in PRD §9; A6 would be the regression-set-remove-justification requirement (subsumed into NFR-Reliab-3 and not added as a separate assumption).
- ID continuity: FR-1 … FR-29, no gaps, no duplicates. NFR-Perf-1, NFR-Reliab-3, NFR-Cost-1, NFR-Cost-2 are new in this Finalize pass (numbered to keep the existing prefix pattern).
- Required sections present for chain-top PRD shape (Vision, Glossary, Features with globally-numbered FRs, NFRs, Constraints, Non-Goals, MVP Scope, Success Metrics, Open Questions, Assumptions Index, Why Now).

## Reviewer files

- `review-rubric.md` — rubric walker (1c / 2h / 4m pre-revision; all resolved in this pass).
- `review-adversarial.md` — adversarial reviewer (2c / 3h + 6 smaller notes; 2c + 2h resolved in this pass; 1h + 6 notes deferred or already covered).
