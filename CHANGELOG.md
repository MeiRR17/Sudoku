# Changelog

Versions under 1.0 are development milestones, **not** supported Production releases. Dates follow ISO 8601.

## [0.8.4] — 2026-11-10 (development patch; release HOLD)

- Integrated real archive receipt re-verification into **manual** GitHub Actions without publishing unlicensed development ZIP/TAR binaries: new `verify_receipt_matrix.py --local dist --expected RUNNER --require-sha SHA` verifies all four present archives on that host *after* packaging and *before* metadata upload. Matrix mode with all three host folders remains supported. Added five CLI regression methods and a workflow ordering guard; metadata-only artifacts remain intentionally insufficient for an external archive recheck. Focused isolated mode-dispatch suite 9/9 PASS; full project and native CI not run this cycle.

- Bind unsigned cross-platform acceptance receipts to **actual extracted source members**: the matrix now verifies canonical source ZIP and TAR.GZ contents and exact embedded `release_files.txt` membership, then recalculates the receipt's canonical source-tree SHA-256. Reject forged matching receipt digests, ZIP/TAR divergence and undeclared source members even when archive SHA256SUMS values were regenerated. Added four regression cases, and adjusted test fixtures to real deterministic archives. An isolated six-case archive/control-flow harness passed; full project tests and native acceptance are still pending.

- Harden the v0.8.4 three-platform evidence matrix: read and SHA-256 hash all 12 locally supplied archives rather than comparing two unsigned text records; reject missing, symlinked or >80 MiB archives, plus >16 KiB receipt JSON and >4 KiB checksum manifests. Six negative regressions added. This is consistency validation, not publisher authentication or native acceptance.

- Add an offline `clear-notes` command to erase every pencil annotation in one undoable operation, preserving placed digits; an empty note set causes no history change. Extend game API, C unit checks, terminal E2E and gameplay documentation. Isolated GCC/Clang C11 + UBSan behavior checks passed; full Sudoku CMake/CTest and native platform acceptance are still pending.

- Close remaining pre-verification size gaps: cap untrusted `SHA256SUMS` at **4 KiB** before ASCII decode, reject compressed TAR.GZ above **80 MiB** before streaming it, and apply the 80 MiB container cap to all four release archives **before calculating SHA-256**, not only while extracting. Add nine focused standard-library unit scenarios (including real four-archive positive verification and sparse oversized TAR negatives) plus two integrated E2E negative scenarios. Locally ran all 9 scenarios against reconstructed exact updated verification/archive functions; full CMake/CTest and native platform acceptance are still pending.

- Preserve the exact solver's documented immutable-givens contract under an aliased in-place API call. `sudoku_analyze_bounded`, `sudoku_analyze` and `sudoku_solve_first` now return `SUDOKU_SOLVE_INVALID` if `first_solution == givens`, without changing the caller's board. Optional solution count and visited-node outputs reset to zero. Add regression assertions in `tests/test_solver.c` and document the explicit requirement for a distinct output board. The extracted production function passed GCC/Clang C11 UBSan isolated alias checks (13/13 each); full native build and release evidence remain HOLD.

- Verify ZIP end-of-central-directory structure and stream-count actual central-directory records **before** constructing Python `ZipFile` and its eager in-memory member list. Enforce 1–1,024 records, an 8 MiB central-directory budget, an 80 MiB total ZIP bound, single-disk canonical ZIP format and no ZIP64/extra trailing data. Add 15 ZIP preflight unit tests, include them in the development source manifest and add a forged-entry-count negative case to package-integrity E2E. 16/16 local source-extracted focused checks passed; full native release tests remain HOLD.

- Fix playable `erase ROW COL` semantics for empty editable cells: erase now clears their pencil notes as well as placed digits, creating one undoable history state; repeated erase on a blank, note-free cell remains a true no-op. Added engine and CLI E2E regressions for notes/erase/undo/redo. Isolated exact-function GCC and Clang C11/UBSan checks passed 20/20 each; complete CMake/CTest and native target acceptance are still pending.

- Remove the Windows game-save **global counter data race**: increment the staging-file serial with Win32 `InterlockedIncrement`, include the process ID alongside the timestamp/counter in `PATH.tmp.*` names, and retain exclusive `fopen("wbx")` creation and post-write `_commit`/atomic replacement. Add a native Windows-only 12-thread concurrent-save CTest that verifies a final resumable solved game and no leaked staging files. Require this check in the Windows quality-gate inventory (23 native Release tests on Windows, 23 on Linux, 22 on macOS). Linux GCC/Clang simulations of the naming algorithm each created 256 unique stage names; native Windows execution is still pending.

- Replace predictable, process-global serial/timestamp **POSIX game-save staging filenames** with `mkstemp("PATH.tmp.XXXXXX")`. This creates an unpredictable exclusive same-directory inode at mode 0600 without a shared mutable serial or a race across concurrent writers. Retain fsync/rename/parent-directory fsync behavior and Windows' existing exclusive-create path. Extend the Linux LD_PRELOAD fault suite with an injected `mkstemp` failure; local focused GCC and Clang UBSan smoke each demonstrated 32/32 unique concurrent private stages.

- Enforce source development archive **manifest completeness**, not just four valid SHA256SUMS records, ZIP/TAR byte-for-byte parity and a small mandatory-file subset. The verifier now reads the embedded `scripts/release_files.txt` and requires an exact equality between listed source paths and archived source members, rejecting missing/extra files, invalid/oversized UTF-8 manifests, duplicates and nonportable aliases. Added 11 unittest regressions using real four-archive synthetic distributions and a full-package E2E negative case that removes an optional source file from both formats, then recomputes both digests.

- Reject case-insensitive and Unicode-normalized *path collisions* before source/installed package collection and ZIP/TAR.GZ verification: two distinct spellings such as `README.md` / `readme.md`, `Assets/` / `assets/` or NFC/NFD equivalents must not alias on extraction. File/directory aliasing is also refused. New bounded per-prefix registry rejects duplicates before reading archive payloads; portable names are limited to 4 KiB UTF-8 and 64 components to avoid pathological prefix expansion. Add 12 regression unit tests and preserve previous unbounded-enumeration fail-closed behavior (duplicate names are now rejected earlier).

- Enforce Windows-portable path components consistently across source manifest inputs, staged install paths and ZIP/TAR.GZ archive verification. Reject DOS device basenames (CON, PRN, AUX, NUL, COM1–9, LPT1–9, CONIN$/CONOUT$), NTFS alternate-stream colons, invalid punctuation/control characters and trailing dots/spaces. Preserve normal nested relative paths and deterministic archive order. Add cross-platform and POSIX-only regression coverage; focused exact-source checks 29/29 PASS.

- Fix unbounded **installation-tree path enumeration** in the packager: `sorted(prefix.rglob('*'))` previously materialized every path before the 1,024-file limit. Iterate lazily, refuse more than 4,096 directory/file entries or 1,024 regular files, and sort only the bounded output for deterministic archives. Four additional regressions cover true deterministic ordering, unbounded file/directory iterators and symlink rejection; all 14 package-budget cases plus nine manifest-path cases passed in an isolated exact-function harness.

- Fail closed when the portable C generator CPU clock is unavailable or runs backward; perform clock subtraction as floating-point values to avoid signed `clock_t` subtraction overflow. Check elapsed CPU budget after the expensive solver/rating call before publishing a generated puzzle. Add a deterministic C clock fault test in CMake/CTest, enforced by `quality_gate.py` across native/sanitized/coverage builds; scoped GCC and Clang UBSan checks passed 6/6 each. This is development hardening, not native release approval.

- Bound development packaging **before file contents enter memory**, not only during archive verification: both listed source files and staged installation files now respect 1,024 entries and a cumulative 64 MiB limit, while source manifests are capped at 256 KiB before decoding. A size-preflight plus bounded `size+1` read detects growth/truncation during collection. Add ten stdlib regression cases, including a sparse 64 MiB+1 file; isolated exact-function checks 10/10 PASS, prior source-path checks 9/9 PASS.

- Strengthen explicit game-save preflight: recheck that the caller-owned givens have exactly one solution and their cached solution still matches the deterministic solver. The earlier board/notes check was insufficient for a valid-but-ambiguous givens board, allowing a checksum-valid file that the strict resume loader would reject. Add C-game regression cases for nonunique givens and stale solution, preserving the prior save; exact-function isolated C11 UBSan checks 14/14 PASS under both GCC and Clang. Full Sudoku CTest still pending.

- Validate all public `SudokuGame` state before serializing a checksum-valid save: givens/current board must satisfy Sudoku constraints, original clues must be preserved, and filled cells must not carry notes. A corrupted caller-owned struct now fails **before staging or overwriting** an existing save, instead of creating a checksum-valid but unloadable file. Add six C unit regression scenarios; isolated strict-GCC and Clang+UBSan harness 12/12 PASS per compiler; full engine tests pending.

- Harden source archive manifest containment: reject a symlinked manifest, symlinks in **any** source path component (including parent directories), Windows-ambiguous backslashes and drive/alternate-stream colons, before reading bytes into source ZIP/TAR. Add nine focused file-system regression cases; all nine passed against the exact extracted source-path function, without claiming full release acceptance.

- Fix cross-host release-evidence false negatives: use schema-v2 platform receipts with a canonical length-framed SHA-256 of **validated source file contents**, not raw compressed source ZIP/TAR digests, for Linux/Windows/macOS comparison. Preserve per-host archive SHA256SUMS checks and reject real source content drift. Add five canonical-hash tests (including actual GZip compression variants) and extend matrix tests to 16 cases; 21/21 focused local tests PASS. No platform acceptance or release status implied.

- Retain unsigned exact-SHA per-platform acceptance receipt plus SHA256SUMS as a seven-day GitHub Actions artifact **only after** manual quality/packaging gates pass; do not distribute unlicensed binaries or trigger CI automatically. Pin the upload action by immutable SHA, use unique runner/commit/attempt names, and add workflow-configuration guard tests.
- Add offline `verify_receipt_matrix.py` to reconcile native Linux/Windows/macOS receipt JSON and checksum manifests: reject mismatched Git commits, OS/CPU/compiler, missing checks, duplicate receipt keys, unexpected artifacts and cross-platform source-archive hash disagreement. 12 negative/positive unit tests and 4 workflow tests passed locally; synthetic receipts are **not** evidence of native host execution.

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
