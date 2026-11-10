# Changelog

Versions under 1.0 are development milestones, **not** supported Production releases. Dates follow ISO 8601.

## [0.8.4] — 2026-11-10 (development patch; release HOLD)

- Stream TAR.GZ verification one member at a time instead of collecting all archive headers in memory. Enforce a maximum of 1,024 members before reading the next payload; reject duplicate member names early. Added 8 executable Python unit tests (normal, exact limit, one over limit, empty, duplicates, unsorted, symlink, traversal). Measured 8/8 passing in isolated exact-function validation; full native Sudoku CTest is still outstanding.

- Fix `sudoku play` reset idempotence: compare the 81 board cells and 81 pencil-note masks, not the snapshot's ABI padding bytes. A reset of an untouched/already-cleared game no longer creates phantom undo steps. Add core unit and scripted gameplay regressions for repeat resets and undo restoration.

- Strictly validate the save-file elapsed-time field: only canonical decimal numbers (no leading zeroes) are accepted, even when a tampered file carries a correctly recalculated FNV checksum. Saturate elapsed-time arithmetic before subtraction and perform clock differences without signed `time_t` overflow. Add game E2E tamper and core timer-boundary regressions.

- Publish CLI `validate`/`solve`/`count`/`generate --output` files only after a complete staged write, file flush and sync. POSIX uses private `mkstemp(0600)` and atomic no-replace `link`; Windows uses exclusive staging plus no-replace `MoveFileExA` (native Windows check pending). Refuse existing destination, leave the previous output untouched, and remove transient staging on errors. Add portable golden and Linux fault-injection regressions for permission/file-sync/link failures.

- Require all mandatory CTest names, and reject required tests explicitly DISABLED or configured to skip; CTest's own exit status may otherwise be green for incomplete/disabled suites. Actual local Python gate regressions 13/13 PASS, plus synthetic CTest JSON discovery and real CTest disabled-property rejection; these do not replace a full Sudoku native build.

- Enforce CTest test-discovery completeness before running any test: native Release requires 22 named checks on Linux and 21 on Windows/macOS; sanitizer/coverage modes require 19. Previously, missing Python E2E registration could leave CTest green without the intended regressions. Added 13 focused unit tests and wired them into the manual Actions gate.

- Reject unpaired or embedded double quotes in interactive `save` filenames; only an optional matched outer quote pair is accepted. Add regression coverage proving malformed paths do not create unexpected files or overwrite the configured default save.

- Harden local platform-receipt publication: exclusive mode-0600 staging, flushed and fsynced JSON, and atomic no-overwrite publication via same-directory hard link. Existing receipt or staging symlink cannot be clobbered; unsupported hard links fail closed. Added five isolated regressions (14/14 total Python acceptance-guard unit tests passed on Linux); native platform release gates remain open.

- Bind native platform evidence to an explicitly required Git SHA (`GITHUB_SHA` in manual Actions), reject untracked/modified source files before and after the gate, and add fast stdlib guard tests for incorrect SHAs, dirty trees and compiler identities.

- Add a fail-closed per-platform acceptance runner (`scripts/platform_acceptance.py`): it invokes the scoped CMake/CTest gate and deterministic packaging verification, checks the actual host architecture and C compiler (MSVC on Windows), and emits a local unsigned JSON receipt bound to the clean Git HEAD and four archive SHA-256 hashes **only after success**. Replace duplicated manual Actions steps with the runner; no automatic CI triggers or official release publishing.

- Create POSIX save staging files using exclusive `open(..., O_CREAT | O_EXCL, 0600)` so they are private **from creation**, not only after `fchmod`. Preserve atomic replacement, fail-closed mode checks, and add Linux fault-injection that verifies the inode starts private even under `umask(000)`. Windows ACLs remain unverified.

- Allow interactive `save PATH` to accept paths containing spaces, with or without enclosing double quotes; reject overlong commands instead of splitting one path into separate arguments. Reject empty or unterminated quoted paths rather than unexpectedly reusing an existing save destination.
- Remember a new explicit save destination even when POSIX directory sync fails **after** a successful rename, so the next bare `save` retries the new destination rather than reporting no configured path.
- Move gameplay `--file` puzzle loading from a >1 MiB automatic stack buffer to bounded heap memory; release the buffer on every I/O and parsing outcome to improve compatibility with smaller Windows process stacks.
- Add gameplay E2E for valid files with spaces, empty/binary/oversized files and missing paths, in addition to portable scripted save and Linux fault-injection regressions. No native Windows/macOS acceptance or user-approved license is asserted; issue #10 remains open.

## [0.8.3] — 2026-11-09

- On POSIX, game saves now fsync their **parent directory after successful rename**, in addition to syncing the temporary file first.
- Distinguish pre-rename save failure (previous valid save preserved) from **post-rename directory-sync failure** (target replaced; crash durability uncertain). The terminal reports a warning instead of incorrectly promising that the old file survived.
- Add Linux-only LD_PRELOAD fault-injection E2E covering file fsync failure, rename failure, directory fsync failure, rollback preservation, and successful reload.
- Keep Windows/macOS/native runner evidence, signed provenance and owner-approved LICENSE explicitly unfulfilled; no RC or Production release.

## [Unreleased]

- Pending: cross-platform acceptance on Windows x64 and macOS arm64, license decision by owner, signing and official release.

## [0.8.2] — 2026-11-09 (development patch; release HOLD)

- Strengthen ZIP/TAR.GZ verifier: validate canonical paths, regular files, size/count budgets and identical source/binary contents across archive formats.
- Validate expected release filenames, required file inventory and signed-independent SHA-256 consistency; add adversarial archive tests that mutate packages and regenerate SHA256SUMS.
- Continue **without** a license choice, official GitHub Release or unsupported native Windows/macOS acceptance claims.

## [0.8.1] — 2026-11-09 (hardening patch; acceptance HOLD)

- Fixed three reproducible Clang static-analyzer findings in the CLI's file/stdin stream lifecycle: eliminate repeated `fread` after EOF/error, close owned file streams on all paths and retain precise error handling.
- Added a portable, strict Clang analyzer gate across all six production C translation units and integrated it into the opt-in full quality gate.
- Expanded CLI golden tests for empty files, embedded NUL, maximum-length input, oversized files, nonexistent files and failure-to-create-output behavior.
- Added a native runner architecture guard for manually invoked GitHub Actions: macOS acceptance requires actual Apple Silicon arm64, Windows acceptance x64; mislabeled/Intel runners fail closed.
- Refreshed development package metadata to `0.8.1` and included analyzer+patch evidence in the reproducible source manifest.
- **No official release or license was approved.** Native Windows/MSVC and macOS arm64 acceptance checks remain OPEN in issue #10.

## [0.8.0] — 2026-11-09 (technical delivery, acceptance HOLD)

- Added relocatable CMake install/export and version metadata for CLI and core library.
- Added deterministic development ZIP/TGZ packaging, SHA-256 manifest, secure archive verification and install/extract/smoke regression tests.
- Added packaging documentation and a license decision record. **No license was selected; no official Release was published.**
- Platform verification **remains open** on Windows x64 / MSVC and macOS arm64 / Clang, including player save/resume behavior.

## [0.7.0] — 2026-11-09

- Added `sudoku play` for uniquely solvable imported or seeded puzzles: move/erase, pencil notes, undo/redo, reset, check, status and win detection.
- Added bounded 128-snapshot in-memory history and persisted elapsed time, progress and notes.
- Added checksummed `SUDOKU_SAVE_V1` with strict validation and atomic same-directory temporary-write/replace; corrupt saves fail without modifying game state.
- Added C game engine tests and Python scripted save/resume/win/corruption tests; expanded coverage to all four engine components.

## [0.6.0] — 2026-11-09

- Added deterministic seed-driven fully solved grid randomization, clue removal with exact unique-solution checks and optional rotational clue symmetry.
- Added a transparent technique-based difficulty proxy (naked singles, hidden singles, and beyond-single fallback) with bounded generation attempts, checks, solver nodes and a best-effort CPU deadline.
- Extended the CLI with `generate`, JSON schema v1 success output and code 6 for exhausted generation budgets. Output files are created only on success.
- Added 72 generator property fixtures, independent solver cross-checks and CLI golden fixtures. Extended coverage collection to include generator core.

## [0.5.0] — 2026-11-09

- Added deterministic solver/property tests and bounded random/parser negative corpus checks.
- Added optional libFuzzer harnesses for parser and solver, with reproducible seed corpora.
- Added GCC gcov JSON line-coverage gate (minimum 90% across board/solver), CLI performance baseline script, and portable `quality_gate.py` for a one-command local check.
- Added manual-only opt-in GitHub Actions quality workflow with configurable OS, with no automatic scheduled/PR/push triggers.
- Added contribution, security, release evidence, and PR documentation.

## [0.4.0] — 2026-11-09

- Stable JSON schema v1 for `validate`, `solve`, `count`; safe exclusive-create `--output` and clear status codes.
- Golden CLI integration suite.

## [0.3.0] — 2026-11-09

- Deterministic exact Sudoku solver, unique/multiple/no-solution classification, independent tests.

## [0.2.0] — 2026-11-09

- New fixed-size C11 board, strict parser, constraint validation and input CLI.

## [0.1.0] — 2026-11-09

- Restored missing header, working CMake build and basic smoke tests.
