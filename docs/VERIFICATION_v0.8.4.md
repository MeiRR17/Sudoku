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
