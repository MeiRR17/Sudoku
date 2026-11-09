# v0.1.0 — Verification Report

**Tested implementation:** local working copy matching the files proposed in `feat/v0.1.0-build-recovery-20261109`.  
**Scope:** C11 compile recovery, smoke paths, sample-puzzle runtime. This is not a production qualification or CI result.  
**Executed:** 2026-11-09 in a Linux x86_64 container.

## Commands and observed results

### GCC Debug + AddressSanitizer + UndefinedBehaviorSanitizer

```sh
cmake -S . -B ../build-gcc -G Ninja -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Debug -DSUDOKU_ENABLE_SANITIZERS=ON
cmake --build ../build-gcc
ctest --test-dir ../build-gcc --output-on-failure
```

- GCC 14.2.0, CMake 3.31.6.
- Configure/build: **PASS**.
- CTest: **3/3 PASS** (help, version, demo).
- No sanitizer error observed in tested paths.
- No compiler warnings observed with `-Wall -Wextra -Wpedantic`.

### Clang Release

```sh
cmake -S . -B ../build-clang -G Ninja -DCMAKE_C_COMPILER=clang -DCMAKE_BUILD_TYPE=Release
cmake --build ../build-clang
ctest --test-dir ../build-clang --output-on-failure
```

- Clang 17.0.0, CMake 3.31.6.
- Configure/build: **PASS**.
- CTest: **3/3 PASS** (help, version, demo).
- No compiler warnings observed.

### Independent sample-grid check

The CLI `sudoku --demo` produced a filled 9×9 grid. An independent Python check of the **final nine rows only** verified each row, column and 3×3 subgrid contains exactly digits 1–9: **PASS**.

This checks one embedded example and **does not** prove correct handling of arbitrary puzzles, contradictory clues, lack of a solution, multiple solutions, or crashes on malicious input.

## Not yet tested

- Windows/MSVC and macOS builds.
- Arbitrary input, systematic correctness fixtures and parser error paths (not implemented).
- Allocation-failure injection, large-scale fuzzing and full code coverage.
- GitHub Actions CI (no workflow introduced).
- Published binaries or a verified release tag (none published).

## Release acceptance

**v0.1.0 planned gates satisfied locally:** restore header, compile with GCC and Clang, enable sanitizer build, run smoke tests, document reproducibility.  
**Remaining follow-up:** source in GitHub must be checked against the local tested implementation at merged SHA; additional OS coverage is a later gate.  
**Production status:** NOT READY. Continue with v0.2.0 and v0.3.0 before general-purpose use.
