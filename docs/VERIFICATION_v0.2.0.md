# v0.2.0 — Implementation and verification (2026-11-09)

## Implementation

- Added value-based `SudokuBoard.cells[81]`, public API `include/sudoku/board.h`.
- Implemented bounded ASCII parsing, 81-digit length checks, and row/column/box validation with informative errors.
- Parsing leaves caller's board unchanged on failure; no heap-owned board graph or global solver state.
- Added offline CLI `validate` supporting command string, file and stdin, with text/compact output and exit codes.
- Removed the prior unsafe experimental solver sources from the active tree; original history is retained in Git and in Learning_Modules. `--demo` now prints sample givens without claiming a solution.

## Verification — local Linux amd64

- Clang 17.0.0, C11 Release, warnings-as-errors: clean CMake build; CTest **8/8 passed**.
- GCC 14.2.0, C11 Debug, ASan/UBSan, warnings-as-errors: clean CMake build; CTest **8/8 passed**; no sanitizer finding in executed paths.
- Targeted CLI error-path checks are included in the release evidence and issue report.

Commands:

```sh
cmake -S . -B build-clang -G Ninja -DCMAKE_C_COMPILER=clang -DCMAKE_BUILD_TYPE=Release
cmake --build build-clang
ctest --test-dir build-clang --output-on-failure
cmake -S . -B build-gcc -G Ninja -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Debug -DSUDOKU_ENABLE_SANITIZERS=ON
cmake --build build-gcc
ctest --test-dir build-gcc --output-on-failure
```

## Remaining limitations

No solver, solution counting, generator, gameplay, JSON, CI matrix or verified Windows/macOS binary yet. Current validation establishes only that givens do not conflict; some otherwise-valid boards may be unsolvable. This is a development milestone, **not Production**.
