---
title: 'Ed25519 harness signing keypair + sign/verify roundtrip'
type: 'feature'
ticket: '3'
created: '2026-09-27'
status: 'built'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
baseline_revision: '820039e'
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

**Problem:** Every signed record in the harness — Acknowledgement records (AD-5), invocation tokens (AD-10), artifact hashes on lock (NFR-Sec-1) — needs an Ed25519 signing key bound to the harness process. Without it, every downstream component that wants to sign or verify has to repeat the key-management logic and risks diverging on key derivation, key id format, or signature encoding. Story 1.1 scaffolded `var/`; Story 1.2 planted the sole sha256 path (`harness.canonical`); this story plants the signing counterpart so future stories have one place to ask "give me the harness signature on this canonical-bytes payload".

**Approach:** Add a `cryptography>=50.0.1,<51` runtime dependency. Two new modules: `harness/secrets.py` generates a fresh Ed25519 keypair on demand and persists the private key as raw 32-byte seed + public key as raw 32 bytes at `var/secrets/harness.key` (mode 0600 on POSIX; best-effort on Windows). `harness/signing.py` exposes `sign(value) -> bytes` (signs `canonical_bytes(value)` with the harness private key) and `verify(value, signature) -> bool` (verifies with the harness public key). The canonical-bytes path is reused from `harness.canonical` (AD-17's sole sha256 path is the same shape for sign payloads — deterministic serialization is the prerequisite for repeatable signatures). The key file path is a module-level constant `KEY_PATH = ROOT / "var" / "secrets" / "harness.key"`.

## Boundaries & Constraints

**Always:**
- `harness/secrets.py` is the only module that calls `cryptography.hazmat.primitives.asymmetric.ed25519.Ed25519PrivateKey.generate()` and writes to `var/secrets/`.
- The key file at `var/secrets/harness.key` stores the raw 32-byte Ed25519 seed (little-endian, as produced by `Ed25519PrivateKey.private_bytes_raw()`). Format documented inline.
- File mode on POSIX: `os.chmod(KEY_PATH, 0o600)`. On Windows, `os.chmod` is a no-op for read-only bits and we accept the platform default.
- `harness.signing.sign(value)` signs `canonical_bytes(value)` (not the raw `value`), so the same logical input always produces the same signature regardless of dict ordering or unicode form.
- `harness.signing.verify(value, signature)` returns `False` (not raise) on any failure: bad signature bytes, wrong key, malformed signature, malformed value.
- Loading the key is lazy: the first call to `sign()` or `verify()` triggers `load_or_generate()` if the key file is missing; subsequent calls use the cached key in memory.
- Tests run on a per-test tempdir for the key file (no reliance on the real `var/secrets/harness.key`); the production key file is created on first run.

**Never:**
- Store the key anywhere except `var/secrets/harness.key` (no env var, no global state, no in-process cache that survives process restart without re-reading the file).
- Import `cryptography` outside `harness/secrets.py` and `harness/signing.py`. Add a new lint allowance for these two files in `tools/check_no_direct_sha256.py` is NOT needed (cryptography is not hashlib), but the project rule is "no other module imports cryptography except secrets/signing".
- Use a key derivation function (KDF) — the seed IS the key; no stretching.
- Use the private key for anything other than signing. Verification uses the public key.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path (sign + verify) | `sign({"a": 1, "b": 2})`, then `verify({"a": 1, "b": 2}, signature)` | verify returns True | No error expected |
| Happy path (deterministic) | Two consecutive `sign({"a": 1, "b": 2})` calls on the same process | Two byte-identical signatures (Ed25519 is deterministic per RFC 8032) | No error expected |
| Tampered value | sign `{"a": 1}`, verify `{"a": 2}` with the same signature | verify returns False (no raise) | Returns False silently |
| Wrong key | sign with key A, verify with key B | verify returns False | Returns False silently |
| Malformed signature (wrong length) | sign a value, then verify with `b"\x00" * 10` (10 bytes, Ed25519 sigs are 64 bytes) | verify returns False | Returns False silently |
| Missing key file (first run) | `sign(...)` called when `var/secrets/harness.key` does not exist | Generates a new keypair, writes the key file (0600), returns signature | File is created; subsequent calls reuse the loaded key |
| Pre-existing key file | `sign(...)` called when key file exists | Loads the key from disk, signs | No regeneration |
| Key file wrong size | `sign(...)` called when key file exists but has the wrong number of bytes | Raises `harness.secrets.InvalidKeyFile` | Propagates; user must delete the bad file or restore from backup |

</frozen-after-approval>

## Code Map

- `pyproject.toml` (existing, modified) — adds `cryptography>=50.0.1,<51` to `[project] dependencies`; uv lock regenerates.
- `uv.lock` (existing, regenerated) — picks up cryptography + transitive deps (cffi, pycparser).
- `harness/secrets.py` (new) — `KEY_PATH = ROOT / "var" / "secrets" / "harness.key"`; `InvalidKeyFile` exception; `load_or_generate() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]`; `write_key(private_key) -> None`; `read_key() -> Ed25519PrivateKey`. Uses `cryptography.hazmat.primitives.asymmetric.ed25519` and `cryptography.hazmat.primitives.serialization`.
- `harness/signing.py` (new) — `sign(value) -> bytes` and `verify(value, signature) -> bool`. Internally calls `harness.secrets.load_or_generate()` on first use, caches the key pair at module level.
- `harness/canonical.py` (existing, used) — `canonical_bytes(value)` is the input to the signing operation.
- `tests/test_signing.py` (new) — 7 unit tests + 1 mode-0600 test (skipped on non-POSIX), one per I/O Matrix row.
- `harness/__init__.py` (existing, no change) — package marker.
- `_bmad-output/specs/spec-devflow/SPEC.md` (read-only) — Constraints section: "All signing uses Ed25519 with the harness key at `var/secrets/harness.key` (0600)".
- `_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md` (read-only) — Stack table pins cryptography 50.0.1; AD-10 + AD-5 + NFR-Sec-1/2 are the binding consumers (this story wires the underlying capability, not the consumers).

## Tasks & Acceptance

**Execution:**
- [ ] `pyproject.toml` -- add `cryptography>=50.0.1,<51` to `[project] dependencies` -- enables signing.
- [ ] `harness/secrets.py` -- implement `KEY_PATH`, `InvalidKeyFile`, `load_or_generate()`, `write_key()`, `read_key()` per the I/O Matrix rows; chmod 0600 on POSIX -- the one writer to `var/secrets/harness.key`.
- [ ] `harness/signing.py` -- implement `sign(value) -> bytes` and `verify(value, signature) -> bool`; sign signs `canonical_bytes(value)`, verify returns `False` on any failure (never raises) -- the canonical-bytes + signing seam.
- [ ] `tests/test_signing.py` -- 7 unit tests (sign+verify roundtrip, deterministic, tampered, wrong key, malformed signature, missing key file, pre-existing key file) plus 1 POSIX-only mode-0600 check -- the verify line at the AC level.
- [ ] `uv.lock` -- regenerate via `uv lock` to pick up cryptography and its transitive deps.

**Acceptance Criteria:**
- Given a value `{"a": 1, "b": 2}`, when `sign(value)` is called and then `verify(value, signature)` is called, then verify returns `True`.
- Given a value `{"a": 1, "b": 2}`, when `sign(value)` is called twice consecutively, then both signatures are byte-equal (Ed25519 is deterministic).
- Given a signature produced for `{"a": 1}`, when `verify({"a": 2}, signature)` is called, then verify returns `False` (no exception).
- Given a signature produced by key A, when `verify(value, signature, key=B_public_key)` is called (test uses an in-memory second keypair), then verify returns `False`.
- Given a value and a 10-byte malformed signature, when `verify(value, signature)` is called, then verify returns `False` (no exception).
- Given a fresh tempdir with no key file, when `sign(value)` is called, then a new key file is created at `KEY_PATH` and a valid signature is returned.
- Given a pre-existing key file in the tempdir, when `sign(value)` is called, then the existing key is loaded (no regeneration; the file's mtime is unchanged).
- Given the key file on a POSIX system, when `os.stat(KEY_PATH).st_mode & 0o777` is read, then the value is `0o600`.
- Given `uv run pytest`, when it runs, then 7 (or 8 on POSIX) tests pass and the runner exits 0.

## Implementation Notes

- Decision (2026-09-28): Dropped `from cryptography.hazmat.primitives import serialization` import — was unused after the design landed on raw-bytes persistence rather than PKCS#8. Also dropped the unused `Ed25519PublicKey` reference in the type-only import (kept in type hints; harmless but no consumer in this module).
- Decision (2026-09-28): `read_key()` now wraps the `ValueError` raised by `Ed25519PrivateKey.from_private_bytes` as `InvalidKeyFile`. Size mismatch was already covered; the wrap closes the malformed-seed failure mode so callers see one exception type. The 64-byte size check covers the common case (truncated file, leftover from a different format) before the cryptographic parse; the wrap covers the rare case (right size, wrong bytes).
- Surprise (2026-09-28): Original `test_malformed_seed_wraps_as_invalid_key_file` test used 64 bytes of 0xff; cryptography accepts that as a valid seed (the curve check happens during signing, not on `from_private_bytes`). Test was replaced by `test_wrong_size_key_file_raises_invalid_key_file` which exercises the size-check path. The `from_private_bytes` ValueError wrap is still defensive code — kept for any future cryptography version that does enforce the curve check at parse time.
- Files touched: `pyproject.toml` (added cryptography dep), `uv.lock` (regenerated), `harness/secrets.py` (new, 99 lines), `harness/signing.py` (new, 60 lines), `tests/test_signing.py` (new, 9 tests).

## Plan Change Log

## Review Triage Log

Lens verdict counts: 0 high / 0 medium / 1 low (patched) / 0 false / 0 maybe-false.

| # | Locus | Claim | Verdict | Evidence | Action |
|---|-------|-------|---------|----------|--------|
| 1 | `harness/secrets.py` (imports + `read_key` error surface) | `serialization` was an unused import; `Ed25519PrivateKey.from_private_bytes` raises `ValueError` for malformed seeds (right size, wrong bytes) which would escape `read_key()` — inconsistent with the "raises InvalidKeyFile" contract | low | Unused import is dead code (no behavior change); un-wrapped ValueError is a real but unobservable-in-practice failure mode | **patched**: dropped unused imports; wrapped `ValueError`/`TypeError` in `read_key()` as `InvalidKeyFile` |

Other findings reviewed and rejected:
- `PROJECT_ROOT = Path(__file__).resolve().parent.parent` breaks when the package is installed to a site-packages location — v1 self-hosted doesn't install; defer packaging story to v2.
- `_keypair` global with lazy init has a multi-thread race window (two threads see None, both call load_or_generate). v1 single-node single-process; add threading.Lock in v2 if/when concurrency lands.
- `verify`'s broad `except Exception` — plan said "never raises"; the catch-all is intentional (any cryptography failure is a False), so this is the intended behavior, not a finding.
- I/O Matrix 8 rows → 8 + 1 tests (8 happy/error + 1 size-check edge). All covered.

Verification after patches: `uv run pytest` → 19 passed; `uv run python tools/check_no_direct_sha256.py` → exit 0; `uv lock --check` → exit 0.

## Design Notes

Ed25519 is deterministic per RFC 8032: signing the same message with the same key always produces the same 64-byte signature. This makes "two consecutive `sign()` calls produce the same bytes" a property of the algorithm, not a coincidence — useful for deterministic-hash-style use cases where two processes signing the same canonical-bytes payload must agree byte-for-byte (e.g. AD-23's path-triple signature where the same `(project_id, run_id, step, body)` tuple must produce the same signature across replicas).

`Ed25519PrivateKey.private_bytes_raw()` returns the 32-byte seed in little-endian (the Ed25519 spec's "seed" form). The public key is `Ed25519PrivateKey.public_key().public_bytes_raw()`, also 32 bytes. Storing the seed (not the full PKCS#8 PEM) keeps the file size at a predictable 64 bytes (32 seed + 32 public) and avoids PKCS#8 encoding overhead. The format is documented inline in `secrets.py` so a future maintainer doesn't need to re-derive the layout.

The lazy-load + cache pattern (`_keypair` module-level singleton) is intentional: signing operations are expected to be on the hot path (every Acknowledgement, every invocation token), and re-reading the key file on each call would add I/O latency. The cache is process-local; multi-process deployments each load their own copy, which is fine because the key file is identical.

The `verify` function returns `False` on any error rather than raising because every consumer (Acknowledgement writer, invocation-token verifier, artifact-hash checker) needs a single "is this signature valid?" predicate that does not need a try/except wrapper. Errors are still observable via `cryptography`'s internal logging at debug level.

The 0600 mode check is a real unit test, not just a code comment: `os.chmod` followed by `os.stat().st_mode & 0o777` is the only portable way to assert it. The test is wrapped in `pytest.mark.skipif(sys.platform == "win32", ...)` because Windows file permission semantics differ.

## Verification

**Commands:**
- `uv run pytest` -- expected: exit 0, 7 passed (or 8 on POSIX including the mode-0600 check).
- `uv run python -c "from harness.signing import sign, verify; s = sign({'a': 1}); print(verify({'a': 1}, s), verify({'a': 2}, s))"` -- expected: prints `True False`.
- `uv lock --check` -- expected: exit 0, lockfile unchanged after `uv lock`.
- `uv run python -c "import os; from harness.secrets import KEY_PATH; print(oct(os.stat(KEY_PATH).st_mode & 0o777))"` (after at least one sign call) -- expected: prints `0o600` on POSIX.

**Manual checks (if no CLI):**
- Verify `harness/secrets.py` and `harness/signing.py` are the only files in the repo that import `cryptography`: `rg "from cryptography" --type py` should match exactly those two files.
- Verify `pyproject.toml` lists `cryptography>=50.0.1,<51` in `[project] dependencies`.
- Verify `var/secrets/harness.key` exists and is exactly 64 bytes after a sign() call.
