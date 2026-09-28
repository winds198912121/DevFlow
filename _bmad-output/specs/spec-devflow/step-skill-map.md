# Step ↔ BMAD Skill Map

Proposed ownership of each step's artifact contract by a BMAD Method skill. Sourced from PRD addendum §A6 and ratified by this spec as **proposed**, not final. Until a step's BMAD owner ratifies the contract schema, the harness treats the contract as the binding document (PRD FR-3).

| Step | Primary skill | Supporting skills | Output contract | Gate acceptance |
| --- | --- | --- | --- | --- |
| Research | `bmad-deep-recon` | `bmad-product-brief`, `bmad-forge-idea` | `research.md` (cited findings + recommendation); optional `brief.md` | Three-piece intention clear: what is true when done, what cannot change, what is out of scope |
| Design | `bmad-prd` → `bmad-architecture` → `bmad-spec` | `bmad-ux` | `prd.md`, `ARCHITECTURE-SPINE.md`, `SPEC.md` | Requirements covered; acceptance criteria measurable; architecture decisions enforced by spine ADs |
| Coding | `bmad-build` / `bmad-build-auto` | `bmad-preview-ticketing` | `tickets.toml` + code commits + `change-log.md` | Build + unit tests pass; key story sub-Gates acknowledged (FR-12 epic tier) |
| Testing | (no BMAD skill; project-defined `testing@n`) | none | `test-report.json` — schema source-of-truth: `_bmad-output/contracts/test-report.schema.json` (PRD A7, 2026-09-27) | All acceptance cases executed; E2E evidence attached in `cases[].evidence`; `acceptance_coverage.fr_passed / fr_total` meets the per-tier threshold |
| Review | `bmad-retrospective` | `bmad-code-review` (built into `bmad-build`) | `review.md` + retro doc | Verdict: accepted / accepted-with-open-items / rejected (PRD FR-9, AD-12) |
| Delivery | (no BMAD skill; harness-native) | none | `delivery.json` (signed) | Signature valid; no missing required field; references the locked Review artifact hash |

## Reading the map

- A step with **Primary skill** = "X" means BMAD Method supplies the procedure for that step; the harness invokes that skill's pinned version.
- A step with **Supporting skills** = list means those skills are referenced from the project YAML `steps.<step>.skills[]` alongside the primary.
- "No BMAD skill" means the harness supplies the procedure directly and the project defines the test / delivery skills with its own version pin.
- **Output contract** names the file the step writes; this spec does NOT redefine the format unless the harness owns the contract (testing, delivery).

## OQ-7 status

PRD OQ-7 ("BMAD Skill ownership per artifact contract") is **open** as of 2026-09-27. The table above is the **proposal** (PRD addendum §A6); the spec ratifies it as proposed. A consumer that needs the final ratification should:

1. Check this companion for the current proposed mapping.
2. Open an issue against `bmod-method` for whichever step's skill owner has not yet confirmed.
3. NOT silently change the mapping on the harness side — that requires a SPEC update, which updates this companion.

## Open Questions

- **OQ-7-proposed-vs-final:** Confirm each row's Primary skill is the actual upstream owner; in particular, "Design" is the row most likely to be split (research vs design contract ownership is fuzzy inside BMAD).
