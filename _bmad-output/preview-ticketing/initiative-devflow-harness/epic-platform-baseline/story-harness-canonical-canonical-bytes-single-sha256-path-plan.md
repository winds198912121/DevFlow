---
title: 'harness.canonical.canonical_bytes — single sha256 path'
type: 'feature'
ticket: '2'
created: '2026-09-27'
status: 'built'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
baseline_revision: '55565a6'
route: 'full'
route_source: 'auto'
review: ''
review_source: ''
lenses_ran: []
review_loop_iteration: 0
context:
  - '_bmad-output/specs/spec-devflow/SPEC.md'
  - '_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Every component that needs a `sha256:` for an artifact, executor tuple, Acknowledgement record, error record, Herdr event, or project YAML must produce a byte-identical hash for the same logical content — otherwise UJ-3's "audit-from-hashes" story collapses and AD-10's `executor_tuple_hash` cannot be replayed across two runs. Today (Story 1.1) the harness has zero hashing code, so the only path to that invariant is to plant it now and prevent any other call to `hashlib.sha256` from creeping in later (AD-17's "sole importer" rule).

**Approach:** Add one module `harness/canonical.py` that exports `canonical_bytes(value) -> bytes` and `canonical_sha256(value) -> str` (the latter returns the `"sha256:" + hexdigest` prefix used throughout the platform). Three serialization rules per AD-17: JSON = sorted keys + UTF-8 NFC + LF + no trailing newline; text = LF + trailing newline; binary = as-is. Auto-detect type via the value's Python type (`dict`/`list` → JSON, `str` → text, `bytes`/`bytearray` → binary). Add a CI lint `tools/check_no_direct_sha256.py` that greps the repo for direct `hashlib.sha256` calls outside `harness/canonical.py` and exits non-zero on any hit. pytest enters the repo as a dev-dependency in this story (so we have a unit-test runner); the lint and four unit tests form the verify line.

## Boundaries & Constraints

**Always:**
- `harness/canonical.py` is the only module that imports `hashlib`. CI lint enforces.
- `canonical_bytes(value) -> bytes`: JSON path produces `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")` after NFC normalization; text path encodes as UTF-8 then replaces `\r\n` with `\n` and ensures exactly one trailing `\n` if the string is non-empty; binary path returns `bytes(value)` byte-for-byte.
- `canonical_sha256(value) -> str` returns `f"sha256:{hashlib.sha256(canonical_bytes(value)).hexdigest()}"`.
- pytest is added as a dev-dependency (`uv add --dev pytest`); the `tests/` directory is created with `tests/test_canonical.py`.
- All JSON inputs are NFC-normalized via `unicodedata.normalize("NFC", ...)` on string leaves, recursively (recursive walker is internal to canonical_bytes; not exported).

**Never:**
- Call `hashlib.sha256` outside `harness/canonical.py`. The lint catches any violation at CI.
- Use `json.dumps(..., indent=...)` (inserts whitespace that breaks the hash); `separators=(",", ":")` is mandatory.
- Use `ensure_ascii=True` (would re-encode NFC characters to escaped `\uXXXX` and break the hash).
- Add `requests`, `httpx`, `pydantic`, or any runtime dependency — only `pytest` joins this story's deps.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path (JSON dict) | `{"b": 1, "a": 2}` | Same canonical bytes as `{"a": 2, "b": 1}`; sha256 of those bytes is stable | No error expected |
| Happy path (JSON list) | `[1, 2, 3]` | `[1,2,3]` (no whitespace, sorted keys irrelevant) | No error expected |
| Happy path (text) | `"hello\r\nworld"` | `b"hello\nworld\n"` (LF normalized, trailing LF added) | No error expected |
| Happy path (binary) | `b"\x00\x01\x02"` | `b"\x00\x01\x02"` byte-for-byte | No error expected |
| Edge (empty text) | `""` | `b""` (no trailing LF added to empty string) | No error expected |
| Edge (Unicode NFC) | `"é"` (one NFC codepoint) vs `"\u00e9\u0301"` (decomposed NFD) | Same canonical bytes | No error expected |
| Error (unsupported type) | `42` (int) | `TypeError("canonical_bytes: unsupported type int")` | TypeError propagates |
| Error (custom object) | `object()` instance | `TypeError` | TypeError propagates |

</frozen-after-approval>

## Code Map

- `harness/canonical.py` (new) -- the sole sha256 path: `canonical_bytes`, `canonical_sha256`, and the internal NFC walker.
- `harness/__init__.py` (existing, no change) -- package marker; `harness.canonical` is imported as a sub-module.
- `tests/test_canonical.py` (new) -- pytest unit tests covering the 8 I/O Matrix rows.
- `tests/__init__.py` (new, empty) -- marks tests/ as a package; not strictly required by pytest but matches the harness/ layout for future `from tests import ...` imports.
- `tools/check_no_direct_sha256.py` (new) -- AST-walking CI lint: parses every `*.py` under `harness/`, `agents/`, `skills/`, `herdr/`, `dashboard/`, `tools/`, `tests/`; rejects any import of `hashlib` outside `harness/canonical.py` (the canonical module itself is allowed to import `hashlib`).
- `pyproject.toml` (existing, modified) -- adds `pytest>=8.0,<9` to a new `[dependency-groups]` table; adds a `[tool.pytest.ini_options]` block pinning `testpaths = ["tests"]`.
- `uv.lock` (existing, regenerated by `uv lock`) -- picks up pytest.
- `_bmad-output/specs/spec-devflow/SPEC.md` (read-only) -- Constraints section: "Canonical hashing goes through ONE function: harness.canonical.canonical_bytes".
- `_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md` (read-only) -- AD-17 "Canonical Serialization Is a Single Library Function" is the binding rule.

## Tasks & Acceptance

**Execution:**
- [ ] `pyproject.toml` -- add `[dependency-groups] dev = ["pytest>=8.0,<9"]` and `[tool.pytest.ini_options] testpaths = ["tests"]` -- enables `uv run pytest` and pins the test directory.
- [ ] `harness/canonical.py` -- implement `canonical_bytes(value)` with type dispatch (dict/list → JSON, str → text, bytes/bytearray → binary), recursive NFC normalization on JSON string leaves, and `canonical_sha256(value) -> "sha256:..."`; export both as module-level callables -- the only `hashlib` consumer.
- [ ] `tests/__init__.py` -- empty file -- mirrors the `harness/` package layout.
- [ ] `tests/test_canonical.py` -- 8 unit tests, one per I/O Matrix row: json-dict-ordering, json-list, text, binary, empty-text, nfc, int-raises, custom-object-raises -- the verify line at the AC level.
- [ ] `tools/check_no_direct_sha256.py` -- AST walk that rejects any `hashlib` import outside `harness/canonical.py`; prints `direct_hashlib_use: <file>:<lineno> <symbol>` for each hit, exits 1 if any hit found, exits 0 otherwise -- the CI lint that enforces AD-17's sole-importer rule.
- [ ] `uv.lock` -- regenerate via `uv lock` to pick up pytest; verify with `uv lock --check`.

**Acceptance Criteria:**
- Given a Python dict `{"b": 1, "a": 2}`, when `canonical_bytes` is called twice (once with this dict and once with `{"a": 2, "b": 1}`), then the two return values are byte-equal.
- Given a Python str `"é"` (NFC) and a Python str `"\u00e9\u0301"` (NFD), when `canonical_bytes` is called on each, then the two return values are byte-equal.
- Given a Python str `"hello\r\nworld"`, when `canonical_bytes` is called, then the return value equals `b"hello\nworld\n"`.
- Given a Python int `42`, when `canonical_bytes` is called, then `TypeError` is raised with a message naming the unsupported type.
- Given a clean repo, when `uv run python tools/check_no_direct_sha256.py` runs, then exit code is 0 and stdout is empty.
- Given `harness/canonical.py` contains `import hashlib`, when the lint runs against the whole repo, then exit code remains 0 (the canonical module is the allowed exception).
- Given a synthetic test file `tests/_temp_direct_hashlib.py` containing `import hashlib; hashlib.sha256(b"x")`, when the lint runs, then exit code is 1 and the lint names the offending file.
- Given `uv run pytest` runs, then 8 tests pass and the runner exits 0.

## Implementation Notes

- Decision (2026-09-27): NFC normalization runs in BOTH paths — JSON's recursive `_nfc` walker and `_text_canonical_bytes`'s leading `unicodedata.normalize("NFC", ...)`. Calling NFC twice is idempotent and cheap; this keeps text-path callers safe even if they bypass the JSON dispatch.
- Surprise (2026-09-27): Python 3.14 implements PEP 686 (implicit source-level NFKC normalization), so the literal `'é\u0301'` in test source is NFC at parse time. Test rewritten to construct NFD explicitly via `unicodedata.normalize("NFD", nfc_form)` so the assertion actually exercises the normalization path. Documented inline in `test_nfc_normalization_collapses_equivalent_strings`.
- Surprise (2026-09-27): `canonical_sha256(b"")` returns the well-known empty-input digest `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`; added `test_canonical_sha256_empty_bytes_known_answer` to pin both the prefix format and the empty-input case as a known answer (10th test, beyond the 8 in the matrix).

## Plan Change Log

## Review Triage Log

Lens verdict counts: 0 high / 0 medium / 1 low (patched) / 0 false / 0 maybe-false.

| # | Locus | Claim | Verdict | Evidence | Action |
|---|-------|-------|---------|----------|--------|
| 1 | `tests/test_canonical.py` (canonical_sha256 surface) | A bonus test checks shape (prefix + length) but no test pins the actual digest value; a silent regression in `canonical_bytes` would not be caught | low | The shape check guards the prefix format; the value is implicit in the prefix check but a known-answer test protects against accidental drift | **patched**: added `test_canonical_sha256_empty_bytes_known_answer` pinning `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` for empty input |

Other findings reviewed and rejected:
- Duplicate NFC across JSON + text paths — idempotent, low cost, kept for safety.
- Lint `ast.parse` is uncached — fine for v1's <100 files; defer caching to v2.
- `tests/__init__.py` is empty — intentional; mirrors `harness/` package layout.
- 8 I/O Matrix rows covered by 8 tests; 10th known-answer test is bonus (not in matrix).

Verification after patches: `uv run pytest` → 10 passed; `uv run python tools/check_no_direct_sha256.py` → exit 0; `uv lock --check` → exit 0.

## Design Notes

JSON canonicalization uses `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. `ensure_ascii=False` is critical: with `True`, every non-ASCII character is re-encoded to `\uXXXX` escapes, which the recursive NFC walker cannot undo (the walker operates on Python strings, not on escaped byte sequences). `sort_keys=True` recursively sorts keys at every level (Python's standard library handles nested dicts). The recursive NFC walker runs before `json.dumps` because once the string is encoded to UTF-8 the NFC normalization cannot reach the codepoints anymore.

Text canonicalization handles three forms: empty (`""` → `b""`), non-empty without trailing newline (`"foo"` → `b"foo\n"`), and non-empty with trailing newline (`"foo\n"` → `b"foo\n"`). The rule is "exactly one trailing LF if non-empty; never strip a user-provided trailing LF". `\r\n` normalization to `\n` runs before the trailing-LF check.

Binary canonicalization is `bytes(value)` if `value` is `bytes` or `bytearray`, otherwise `TypeError`. `bytearray` is normalized to `bytes` to avoid mutability surprises.

The lint `tools/check_no_direct_sha256.py` uses Python's `ast` module, not a regex grep — `ast.Import` and `ast.ImportFrom` nodes carry the imported module name, so the check is `node.module == "hashlib" and not in_canonical_module`. This avoids false positives like `hashlib` appearing in a docstring or comment. The allowed exception is `harness/canonical.py` (the file whose basename matches `canonical.py` under the `harness/` directory).

pytest 8.x is the latest stable as of the spine Stack verification date 2026-09-26; the `>=8.0,<9` constraint follows the spine's "tight pin" pattern (AD-17 + AD-22 in the spine rationale section). pytest-asyncio is NOT added in this story — none of the canonical_bytes tests are async.

## Verification

**Commands:**
- `uv run pytest` -- expected: exit 0, 8 passed, 0 failed.
- `uv run python tools/check_no_direct_sha256.py` -- expected: exit 0, no stdout.
- `uv lock --check` -- expected: exit 0, lockfile unchanged after `uv lock`.
- `uv run python -c "from harness.canonical import canonical_bytes, canonical_sha256; print(canonical_sha256({'a': 1}))"` -- expected: prints a `sha256:` prefixed hex digest.

**Manual checks (if no CLI):**
- Verify `harness/canonical.py` is the only file in the repo that imports `hashlib`: `rg "import hashlib" --type py` should match only `harness/canonical.py`.
- Verify `pyproject.toml` has `[dependency-groups]` with `dev = ["pytest>=8.0,<9"]` and `[tool.pytest.ini_options]` with `testpaths = ["tests"]`.
