# Sudoku v0.8.4 — interactive save paths and retry semantics

Date: 2026-11-10. **Development patch only; release acceptance remains on HOLD.**

## Implemented

- The terminal `save PATH` parser consumes the remainder of the input line as a single path, allowing unquoted filenames containing spaces. Optional surrounding double quotes are removed. Empty, unterminated, stray and nested double quotes are rejected before file creation; only a bare `save` can reuse the configured default path. New E2E checks assert these invalid inputs neither create files nor overwrite the prior default.
- Interactive input permits paths up to 4096 bytes; overlong commands are discarded rather than partially executed.
- Gameplay `--file` now allocates its bounded 1 MiB + 1 byte read buffer on the heap instead of the function stack. Portable E2E checks include a valid puzzle file, NUL input, empty input, missing file and oversized file. All paths free the buffer on return. This is a portability fix, not a claim of native Windows/MSVC execution.
- POSIX save staging files are created atomically with mode `0600` using `open(O_WRONLY | O_CREAT | O_EXCL)` before the defensive `fchmod`, closing the creation-to-chmod exposure window. The Linux fault interposer adds `check-created-mode` to inspect the mode *as `fchmod` begins*, with `umask(000)` in the child. Existing E2E checks cover new creation and replacement of an existing `0666` file, and failure of `fchmod` without replacing the prior target. Windows ACLs remain unverified.
- The selected explicit path becomes the default after either a successful save or a post-rename directory-sync warning. A failed pre-rename save does not change that default.
- Added portable gameplay E2E scenarios for unquoted and quoted filenames with spaces, bare-save reuse and resume. Extended Linux-only `LD_PRELOAD` directory-fsync fault injection to verify default-path retention after the warning.
- Updated CMake, CLI, package manifest and version assertions to 0.8.4.

## Native platform acceptance command (new; not yet executed on the full repo)

```sh
# Run from a clean Git checkout of the PR SHA; select the actual host.
python3 scripts/platform_acceptance.py --expected ubuntu-latest
# Or on Windows x64/MSVC: python scripts/platform_acceptance.py --expected windows-latest
# Or on Apple Silicon: python3 scripts/platform_acceptance.py --expected macos-latest
```

The script runs the full fast CMake/CTest gate, verifies all four development archives, and writes an unsigned `dist/platform-receipt.json` bound to exact Git HEAD **only on success**. It requires the exact Actions `GITHUB_SHA` (or optional `--require-sha`), rejects tracked/untracked source changes, and rechecks the checkout after the build and package gates. Standard ignored build caches remain outside source tracking. Run `python -B -m unittest discover -s tests -p platform_acceptance_unit.py -v` for fast guard-unit checks. Existing receipts are not overwritten. On Windows, compiler identity **MSVC** is required. The manual-only Actions workflow calls this command; it has not been dispatched or run as part of this update. A receipt alone cannot authorize a release or establish authenticity.

**Observed isolated checks in this update:** `platform_acceptance.py` passed Python bytecode compilation, CLI help parsing, four C compiler identity fixture checks (MSVC, AppleClang, GNU and missing-identity rejection), and a negative guard refusing `--mode full` for Windows. **No Sudoku CMake/CTest or packaging execution occurred.**

## Executed isolated acceptance-guard tests — 2026-11-10

The **exact** Python source blobs from this PR were copied into an isolated local test directory and independently checked by `git hash-object` against their GitHub blob identifiers:

- `scripts/platform_acceptance.py`: `8bac0c0b3e812f05690f72b151cbb3545c6586da`
- `tests/platform_acceptance_unit.py`: `52a0b70a8b991b2923d7eb84fa55a276c9611c33`

Observed command: `python -B -m unittest discover -s tests -p platform_acceptance_unit.py -v`. Result: **9 tests passed in 0.004 s** (clean/mismatched/malformed SHA; tracked/untracked changes; invalid Git SHA; native compiler identity and missing-identity detection). `--help` completed successfully. Invalid command `python -B scripts/platform_acceptance.py --expected windows-latest --mode full` correctly exited with code **2** before attempting any project build.

**Scope restriction:** these are real Python unit tests on byte-identical source copies, not an assembled Git checkout. The project CMake build, Sudoku CTest, package creation/verifier, native Windows/MSVC and macOS arm64 tests have **not** executed in this environment. No platform acceptance receipt was produced; no release approval or merge is implied.

## Focused checks to run from this exact branch/commit

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
ctest --test-dir build --output-on-failure -R 'sudoku_(game_e2e|save_fault_injection|cli_golden|package_e2e)'
python3 scripts/package_release.py --build build --output dist
python3 scripts/package_release.py --verify-only --output dist
```

### Additional isolated POSIX creation-mode smoke

On Linux, a minimal standalone C11 reproducer using the exact mode-setting calls in `src/core/game.c` (`open(..., O_WRONLY|O_CREAT|O_EXCL, S_IRUSR|S_IWUSR)`, `fdopen`, `fchmod`, `fwrite`, `fclose`) compiled with GCC `-std=c11 -Wall -Wextra -Werror -pedantic`. Under `umask(000)`, it confirmed mode `0600` **before** `fchmod`, preserved mode `0600` after close, and wrote the expected 15-byte header. This exercises **only the isolated system-call sequence**; it is not an execution of Sudoku or its updated CTest suite.

## Observed isolated check on 2026-11-10

The earlier version of the test-only Linux `tests/fault_inject.c` source was compiled separately using `gcc -std=c11 -Wall -Wextra -Werror -shared -fPIC -O0`. The resulting interposer returned `EPERM` when `SUDOKU_TEST_FAULT=file-mode` was set and succeeded after that fault was cleared. This establishes **only** the isolated fault-interposer behavior. No Sudoku executable was compiled or executed, and no project CTest gate, source package, Windows/MSVC or macOS check is claimed. All remaining target-specific acceptance gates remain pending.

**Evidence status:** these commands are reproducible instructions, **not claimed observed executions** in this update. The GitHub write/PR confirms source delivery, not compilation or cross-platform acceptance. Windows x64/MSVC and macOS arm64 native tests, owner-approved licensing, artifact authenticity and release-grade rollback remain open in [issue #10](https://github.com/MeiRR17/Sudoku/issues/10). No v0.9 Release Candidate, v1.0 release, hosted CI run or official tag is claimed.


### Measured isolated receipt publication tests — 2026-11-10

The acceptance receipt writer now creates the local staging file with `os.open(O_CREAT | O_EXCL, 0600)`, flushes and `fsync`s the complete JSON, then uses a same-directory hard link to publish it **without replacing an existing destination**. A pre-existing temporary symlink is not followed. If the filesystem cannot create a hard link, evidence publication fails closed and leaves no success receipt. No other release metadata or official artifact is produced.

**Observed Linux tests:** `python -B -m unittest discover -s tests -p platform_acceptance_unit.py -v` ran **14 tests; all passed** (0.006 seconds on the measured repeat). The five new cases check private file mode, no-overwrite behavior, symlink refusal, hardlink-not-supported cleanup and failed-serialization cleanup. Source copies match the exact GitHub Git blob hashes `207bc0c6cd28a4234e75a1da835d3f7cfe41e7ad` for `scripts/platform_acceptance.py` and `273fc5b478565855697c21900e7353cc23097534` for `tests/platform_acceptance_unit.py`.

These tests validate the **Python receipt writer only** on Linux. No Sudoku C11 project compilation/CTest, full platform acceptance receipt, macOS arm64 or Windows/MSVC test was performed. Receipt-file hardlink behavior on those native platforms remains unverified.


### Strict save-quote parser focused check (2026-11-10)

An isolated C11 harness using the relevant source normalization/quote validation logic was compiled locally with `cc -std=c11 -Wall -Wextra -Wpedantic -Werror -O2` and executed: **10/10 focused cases PASS** (unquoted/quoted paths with spaces, empty/unclosed/nested/stray quotes, CRLF and whitespace). This is an isolated *extraction*, **not** a build of `src/cli/play.c` or the complete Sudoku application. The actual `tests/game_e2e.py` was extended with three subprocess-driven malformed-save regressions, but these full executable tests have **not** been run. No Windows/macOS native acceptance or CTest is claimed.


## CTest inventory fail-closed gate (source implementation; native run pending)

`scripts/quality_gate.py` now obtains a machine-readable `ctest --show-only=json-v1` inventory after configuring/building and before running `ctest --output-on-failure`. It refuses success when any required named unit, CLI, golden, gameplay or packaging test is missing (e.g. because CMake failed to discover Python). Native Release requires **22 Linux checks** or **21 Windows/macOS checks**; sanitizer and coverage builds require **19** because instrumented packaging is intentionally excluded. Malformed JSON, duplicate names and unnamed tests also fail. `tests/quality_gate_unit.py` exercises these invariants without a C compiler. The manual-only workflow runs both Python `*_unit.py` test modules before the build. This gate does **not** constitute a successful native CMake/CTest run until it is actually executed against this PR SHA.


### Measured CTest inventory guard checks — 2026-11-10

Local copies of `scripts/quality_gate.py` and `tests/quality_gate_unit.py` matched the exact GitHub Git blob identifiers `a5f1c3d11f21f89a263a22343492934825d9d164` and `2993fd8c29cd1b569f65487ee55c4ffb785970c2`. The command `python -B -m unittest discover -s tests -p quality_gate_unit.py -v` **executed and passed 13/13 tests** (0.001 s). Verified mandatory inventories are 22 Linux native, 21 Windows/macOS native and 19 instrumented; missing/duplicate/unnamed tests, disabled tests and CTest skip policies fail closed.

The CTest CLI was also executed against a **synthetic, single-test CMake project**: `ctest --show-only=json-v1` returned a real JSON listing, which the new guard correctly rejected as incomplete. A second synthetic CMake project declared `DISABLED TRUE`; its real CTest JSON `DISABLED` property was correctly rejected by the guard even after the rest of the mandatory names were simulated. These are real tool-integration checks of the gate, **not** Sudoku's full CMake build or CTest acceptance. No acceptance receipt, Windows x64/MSVC or macOS arm64 native result is claimed.


### Observed isolated C11 atomic CLI output smoke — 2026-11-10

Changed `src/cli/main.c` functions `open_result_stage` and `publish_result` were **extracted without modification** into a standalone stub harness supplying only the CLI result formatter. The locally extracted functions match the GitHub source span by length (**3,250 bytes**) and a deterministic FNV-1a checksum (`312cd717`); the overall uploaded source file is Git blob `1ce03adb1ac1b74b0121d9b66f1bbdd6f3775849`. The harness compiled with GCC `-std=c11 -Wall -Wextra -Wpedantic -Werror -O2`, and **8/8 isolated cases passed**: complete final result, owner-only `0600` permissions under `umask(000)`, existing-target preservation, no residual temporary file, simulated `fchmod` failure, `fsync` failure, atomic `link` failure, and orphan isolation. The Linux `LD_PRELOAD` interposer source exactly matched GitHub blob `b248065061bcc9d6db142b3948589c704969ec77`, compiled under `gcc -std=c11 -Wall -Wextra -Werror -shared -fPIC -O0` and confirmed that injected link errors do not publish, whereas successful links publish and existing targets cannot be overwritten.

Added `tests/cli_golden.py` and `tests/save_faults.py` regressions will exercise the full Sudoku CLI after a native build. **They were not executed in this cycle**, and the standalone stub does not establish full CMake/CTest, Windows x64/MSVC or macOS arm64 acceptance. No release or `master` merge is authorized on this evidence alone.


### Canonical elapsed-time save and overflow hardening — 2026-11-10

`src/core/game.c` now rejects leading zeroes in the `E=` field of a version-1 save, even if the checksum was recomputed to match the noncanonical record. `sudoku_game_elapsed` clamps an externally corrupted `elapsed_base` before saturation arithmetic, and computes forward clock differences in unsigned arithmetic rather than risking signed `time_t` subtraction overflow. Added `tests/game_e2e.py` corruption input with a correctly recalculated FNV-1a checksum and `tests/test_game.c` extreme-base tests.

**Observed focused tests:** a C11 isolated harness exercising the changed elapsed and timestamp parsing logic compiled with GCC `-std=c11 -Wall -Wextra -Wpedantic -Werror -fsanitize=undefined` and passed **19/19 cases**, including maximum elapsed value, unsigned saturation, backwards clock, clock failure, extreme signed clock values, zero/positive canonical timestamps and rejection of leading zeroes/overflow. A separate Python verification generated a checksum-valid `E=00` game-save mutation (original 452 bytes, mutated 453 bytes) and confirmed FNV-1a recomputation was consistent. **These were isolated checks, not the full Sudoku binary or CTest suite.** No Windows/macOS native acceptance is claimed.


### Reset idempotence and ABI-padding correction — 2026-11-10

`src/core/game.c` previously determined whether reset was a no-op with `memcmp` over an entire `SudokuGameSnapshot`. The 81-byte board precedes an array of `uint16_t` pencil notes, so ABIs may add a padding byte before the notes. Comparing this padding can spuriously record a reset as a new undo step. The fix compares only `board.cells` against the givens, then scans the 81 note masks for nonzero entries. `tests/test_game.c` now asserts initial and repeated resets preserve history length/cursor, and `tests/game_e2e.py` adds scripted scenarios asserting an untouched reset cannot be undone and a repeated reset does not obscure undo restoration of notes.

**Observed isolated C11 check:** the exact `sudoku_game_reset` function span in GitHub blob `bc473ff8e6fdcc319b0b4f529ed4dba4209c6395` measured **774 characters and FNV-1a 32-bit `f3126498`**, matching the local harness source. The function was compiled with both GCC and Clang, `-std=c11 -O1 -Wall -Wextra -Wpedantic -Werror -fsanitize=undefined`, and the isolated harness **passed with both compilers** for a padding-only discrepancy, unchanged reset, note clearing and repeat reset, cell clearing, and invalid game. A separate reproduction showed the old full-struct `memcmp` reports a difference when only the padding byte differs. **Neither the complete `Sudoku` program nor the new full CTest/E2E regressions have been run in this environment**. Windows/macOS native acceptance, licensing and formal release gates remain OPEN.


### Bounded streaming TAR integrity validation — 2026-11-10

`scripts/package_release.py:ensure_safe_archive` now opens TAR.GZ in streaming `r|gz` mode and enforces `MAX_ARCHIVE_FILES=1024` while iterating members. Unlike `tarfile.getmembers()`, it does not allocate an unlimited list of archive metadata before verifying the count. The existing 64 MiB total decompressed-content budget and canonical paths, member type, order, and ZIP/TAR parity checks remain in place; duplicate TAR names are rejected before reading another payload.

Added `tests/archive_stream_unit.py` (included in the source archive and in manual-only CI's existing `*_unit.py` preflight) to cover a valid two-entry TAR, an exact 1,024-entry TAR, an oversized 1,025-entry TAR, empty TAR, duplicate names, noncanonical ordering, a symbolic link, and a parent-directory traversal. **Actual local run:** `python -B -m unittest discover -s tests -p archive_stream_unit.py -v`: **8/8 PASS, 0.125s** on a local harness containing the *exact* `_safe_member_name` and `ensure_safe_archive` GitHub function bodies plus their required imports/constants, not the full package module. The extracted 3,562-character span matched GitHub source FNV-1a 32 `40494d97`; the test file Git blob matched `ee7c5b42bf74905e4ad75f3b69560ef6b659609b`. Full source-package generation, Sudoku native CMake/CTest, and Windows/macOS acceptance were **not executed** in this update.


### Native acceptance evidence retention / cross-host consistency — 2026-11-10

Added one manual-workflow step **after** exact-SHA `platform_acceptance.py` succeeds to retain the unsigned per-host receipt and `SHA256SUMS` as a seven-day GitHub Actions artifact. The workflow still has no automatic triggers, keeps `contents: read`, uses a full-SHA pinned `actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02` (v4.6.2), and names each artifact using runner, SHA and run attempt. Archives/binaries are deliberately excluded because the license decision and release approvals remain open.

Added `scripts/verify_receipt_matrix.py` and `tests/receipt_matrix_unit.py` for offline three-host checksum-manifest consistency, exact SHA/version/host checks, real-toolchain label validation, duplicate-key refusal and cross-platform source-archive digest equality; added `tests/workflow_evidence_unit.py` to require manual-only workflow dispatch and the non-binary, short-retention upload behavior. **Observed local tests:** `python -B -m unittest discover -s tests -p '*_unit.py' -v` in a scoped exact-source copy ran **16/16 PASS**: 12 matrix tests and 4 workflow tests. The standalone matrix CLI was also invoked twice against **synthetic fixtures**: one three-host set returned `EVIDENCE MATRIX CONSISTENT` with an explicit nonrelease warning; a deliberately changed Windows SHA returned exit code 1 with `EVIDENCE MATRIX FAIL`. A local YAML parser loaded the actual workflow with six steps, confirming upload inputs. Git blobs matched the tested copies: workflow `8388f9ec0312644ef2c3f31dea18228b56a07de5`, workflow tests `5438be3ed9817aa9a686d4f3fd724e895325725f`, matrix tool `5dcf1269a1d40e11fe36c5ea5f9868de07c91891`, matrix tests `b56a3cbc2686cc9f22a2c226e94234534d9d587b`.

**Scope limitation:** all receipt fixtures were generated solely for tests, and are **not** real Windows, macOS or Linux platform acceptance receipts. No GitHub Actions workflow was triggered, no complete Sudoku CMake/CTest run was performed on this branch, and no production release was approved or published.


### Cross-platform source identity without compression-byte assumptions — 2026-11-10

The native receipt writer now records `schema_version: 2` and `source_tree_sha256`: a domain-separated SHA-256 of the **validated, decompressed source archive entries** with unambiguous length-framed UTF-8 member paths and payloads, sorted by path. Each host still validates its compressed ZIP/TAR.GZ and the exact `SHA256SUMS`; the matrix now checks canonical source-content agreement rather than requiring compressed ZIP/TAR bit-for-bit agreement across different operating systems. The change fixes a false-negative portability risk when system compression libraries differ, while retaining rejection of a truly modified source tree. Schema-v1 receipts are intentionally incompatible; all new native runs must use the same schema-v2 commit.

**Measured focused tests (Linux, 2026-11-10):** local copies of `scripts/verify_receipt_matrix.py` and `tests/receipt_matrix_unit.py` passed **16/16** unit tests, including compressed-archive digest differences with matching source content, missing/malformed/source-content-mismatch digests and rejection of schema v1. The new `tests/source_tree_unit.py` passed **5/5** tests for ordering, changed bytes/pathnames, length framing, domain separation and real GZip compression variants. Total **21/21 PASS** in ~0.03 s. A pair of real source TAR.GZ files compressed at levels 1 and 9 had **different compressed SHA-256 values** but exactly the same canonical extracted source-tree hash, reproducing the false-negative scenario this fixes. Locally tested matrix Git blobs exactly matched pushed Git blobs `bfb9480be7c6ffd1ffd7f96c9f9314408366edb2` and `ec62222e4d866f076687ba6ddc5550c36c9fa653`; source-tree unit test blob `9820f1199b843e1c5cd73a96766875bb7d038f26` matched. Extracted canonical hashing function (620 characters; FNV-1a 32 `92e7fee3`) matched `scripts/platform_acceptance.py` source. **No full Sudoku CMake/CTest, GitHub Actions run or native Windows/macOS acceptance was performed.**


### Source-manifest directory-symlink and Windows-path containment — 2026-11-10

The source packager now rejects symlinks at *every* path component, not only the leaf; an intermediate directory symlink could otherwise read external files despite the existing regular-leaf check. It additionally rejects symlinked source manifests and Windows-ambiguous `\\` and `:` paths. The new `tests/source_manifest_unit.py` (included in the development source package and the existing manual-only `*_unit.py` preflight) covers nine cases: valid sorting/content, Windows separators/drives/NTFS ADS, absolute/traversal/noncanonical paths, symlinked parent directory, symlinked leaf, symlinked manifest, missing file, duplicate and empty manifest.

**Executed locally:** nine focused filesystem checks **9/9 PASS** on the *exact* `source_paths()` function copied from GitHub source blob `33712938ed72a3e7e1fc13d337e18910a344c50b`: 1,497 characters, FNV-1a 32 `fc8e9327`, identical to the local extracted function. New test source blob in GitHub: `8ea7ff970d21c690822ba8b61ade1a90cb6682b9`. This was an isolated function harness, **not** a checkout or complete execution of `tests/source_manifest_unit.py` within the full Sudoku project; it is not full Sudoku CMake/CTest, package-acceptance or Windows/macOS evidence. Release HOLD remains.


### Public C game-state validation before save — 2026-11-10

`src/core/game.c:render_save` now validates both original-clue and in-progress boards via `sudoku_board_validate`, then explicitly rejects changed given cells, nonzero notes on filled cells, and invalid note masks before rendering or staging a save. This closes a public-API gap: callers may mutate `SudokuGame` members directly and previously could replace a valid save with a checksummed but unloadable record. Added six scenarios to `tests/test_game.c` (altered clue, row conflict, out-of-range cell, note on given, note on filled edit, invalid givens), followed by an existing assertion that the original saved notes load correctly.

**Observed isolated C11 harness:** exact `render_save` source from GitHub blob `c3ea2aae92f77604d1b31ec6aac7381bd34bdb77` (1,691 characters, FNV-1a 32 `9a793092`) compiled with **both GCC and Clang** using `-std=c11 -Wall -Wextra -Wpedantic -Werror -O1 -fsanitize=undefined`. An independent Sudoku row/column/box validator supplied the small harness dependency; **12/12 focused cases passed with each compiler** (24 individual compiler executions), including valid canonical serialization, two note-mask rejection cases, six corrupted state cases and null input. The harness uses stubs for unrelated engine dependencies and was **not** a complete Sudoku checkout, full native CMake/CTest, package run or native Windows/macOS execution. Issue #10 and release HOLD remain open.
