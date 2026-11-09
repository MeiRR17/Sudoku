# Sudoku v0.8.1 — static-analysis and packaging hardening evidence

**Date:** 2026-11-09. **Status:** local technical patch only, **release approval HOLD**.

## Change and threat model

The prior v0.8.0 CLI incurred three reproducible `clang --analyze` `unix.Stream` warnings:

1. `fread` may be retried after the stream entered EOF state.
2. `fread` may be retried after a failed I/O operation.
3. The file-open/close ownership path was not established as leak-free by the analyzer.

In v0.8.1 the bounded file/stdin reader uses **one** `fread` for at most 1 MiB+1 byte, immediately checks `ferror`, and a separate file reader owns the `fopen`/`fclose` lifecycle. The byte-counting parser still rejects NUL and non-ASCII bytes and reports the exact size limit. `stdin` is never closed by the CLI. No change is made to the JSON v1 success schema, solve/count algorithms, game save format, or exit code contract.

## Reproduce locally

```sh
python3 scripts/static_analysis.py
cmake -S . -B build-release -G Ninja -DCMAKE_C_COMPILER=clang -DCMAKE_BUILD_TYPE=Release
cmake --build build-release
ctest --test-dir build-release --output-on-failure
cmake -S . -B build-gcc-sanitize -G Ninja -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Debug -DSUDOKU_ENABLE_SANITIZERS=ON
cmake --build build-gcc-sanitize
ctest --test-dir build-gcc-sanitize --output-on-failure
python3 scripts/quality_gate.py --mode full
python3 scripts/package_release.py --build build-release --output dist
python3 scripts/package_release.py --verify-only --output dist
```

`scripts/static_analysis.py` scans all six active C translation units and **fails even when Clang prints warnings but exits with zero**, preventing analyzer warnings from being mistaken for a successful scan. The full quality gate now invokes it. Additional CLI tests cover zero-byte files, embedded NUL, the exact 1 MiB byte limit, 1 MiB+1 rejection, missing files and failure to create result files on input error.

## Runner architecture gate

The manual GitHub Actions workflow includes a guard that rejects an OS/CPU mismatch before building or testing. A macOS Intel runner cannot be certified as macOS arm64. Local Linux positive and intentionally failing negative checks can be reproduced with:

```sh
python3 scripts/verify_runner_platform.py --expected ubuntu-latest
python3 scripts/verify_runner_platform.py --expected macos-latest  # expected failure on Linux
```

No actual hosted Windows/macOS workflow run is claimed. The guard is preparation for native acceptance, not an acceptance result.

## Observations and acceptance limitations

- **Clang 17 Static Analyzer:** 6/6 translation units, zero diagnostics (local Linux).
- **Clang 17 Release CTest:** **20/20 PASS**, including package E2E, JSON golden and gameplay save/resume. A complete re-run after adding this source manifest entry also passed.
- **GCC 14.2 Debug ASan/UBSan CTest:** **19/19 PASS**; packaging test intentionally excluded from sanitizer build; no sanitizer findings observed in executed paths.
- **GCC 14.2 gcov Debug CTest:** **19/19 PASS**. Executed core line coverage **563/589 (95.59%)**, over the 90% threshold: board 82/87, solver 91/94, generator 170/176, game 220/232.
- **CLI golden regression:** **63 checks PASS**, including seven newly added file/error checks.
- **Development packaging:** all four deterministic archive types, SHA256SUMS, isolated install / external consumer / uninstall checks **PASS** on Linux x86_64. Binary ZIP/TAR.GZ have 14 files each; source ZIP/TAR.GZ have 64 files each. Repackaging identical staging bytes was validated by package E2E.
- **Local runner architecture check:** Linux x86_64 expected pass; macOS-ARM expectation intentionally fails on Linux, demonstrating a fail-closed guard.
- **Native macOS arm64:** NOT RUN.
- **Native Windows x64/MSVC:** NOT RUN.
- **License selection:** NO OWNER APPROVAL; NO LICENSE FILE.
- **Signed artifact / GitHub Release / clean-host rollback:** NOT DONE.

This is a maintenance patch to the **technical v0.8.0 delivery**, not a release candidate. Issue #10 must remain **open**, and `v0.9.0` must remain blocked until the platform and licensing gates are met.

## Exact evidence boundaries

- The Clang analyzer warning count was **3 before** the stream-lifecycle change and **0 after**, for the six production translation units. This is a static audit on Linux, not an assertion of memory safety on all possible inputs.
- The local Linux packaging checks establish archive integrity and installation. They do **not** establish authenticity, signed provenance, portability to older glibc systems, or any Windows/macOS result.
- The GitHub Actions workflow remains manual-only and was **not triggered** by this patch. No cloud CI status is represented as PASS.
- The exact HEAD SHA for this work must be recorded in GitHub issue #10 **after** the patch is merged. No license has been chosen; the release remains on HOLD.
