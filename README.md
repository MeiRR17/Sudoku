# Sudoku — portable C11 solver (`v0.3.0`, experimental)

This project provides an **offline, deterministic, exact 9×9 Sudoku solver** using constraint bitmasks, minimum-remaining-values (MRV) selection, and backtracking. It distinguishes **invalid givens, zero solutions, exactly one solution, and multiple solutions** (counts stop after the second). The engine preserves every original clue and never changes the caller's board on failure.

**Development status:** v0.3.0 implementation milestone; **not production-ready**. Web/mobile, puzzle generation, saving, structured JSON, and cross-platform release packages are future milestones; do not assume those features exist yet.

## Build and run

CMake 3.16+ and a C11 compiler are required; Ninja is optional.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
ctest --test-dir build --output-on-failure
./build/sudoku --version
./build/sudoku --demo
./build/sudoku validate --file tests/fixtures/unique.txt
./build/sudoku solve --file tests/fixtures/unique.txt
./build/sudoku solve --file tests/fixtures/unique.txt --format compact
./build/sudoku count --file tests/fixtures/unique.txt --format compact
./build/sudoku count --file tests/fixtures/unsolvable.txt
./build/sudoku solve --stdin < tests/fixtures/unique.txt
```

**Note:** The executable may be `build/Release/sudoku.exe` for multi-config CMake on Windows; Windows and macOS builds have not yet been verified.

## Commands and output

- `sudoku validate --puzzle DIGITS`, `--file PATH`, or `--stdin`: checks only the givens (no duplicates in rows, columns, or 3×3 boxes). Does *not* guarantee a solution exists.
- `sudoku solve ...`: finds a valid completed grid. On multiple solutions it prints the deterministic **first** solution and warns on stderr. On an unsolvable board it prints an error and returns 5, leaving stdout empty.
- `sudoku count ...`: prints the classification `no solution`, `unique solution`, or `multiple solutions`; `--format compact` prints `0`, `1`, or `2+` respectively. **2+ means at least two**, not an exact enumeration of all solutions.
- `--format text|compact`: human-readable board or machine-readable digits. `--format json` is intentionally deferred to v0.4. `--demo` prints the built-in puzzle and solver outcome.
- Exit codes: 0 valid/completed (including a non-unique first solution); 2 invalid CLI invocation; 3 invalid puzzle data; 4 file I/O error; 5 well-formed but unsolvable puzzle during `solve`.

Input must contain **exactly 81 ASCII digits** `0`–`9` (0 is blank), with optional ASCII whitespace. Invalid bytes, extra digits, conflicting givens, or data longer than **1 MiB** are rejected. No network connections, telemetry, accounts or external dependencies.

## Engine API

- [`include/sudoku/board.h`](include/sudoku/board.h): `SudokuBoard` value type (81 bytes), strict parser, constraint validation, compact serialization.
- [`include/sudoku/solver.h`](include/sudoku/solver.h): `sudoku_analyze`, `sudoku_solve_first`, `sudoku_count_solutions` and exact outcome enum.
- [`src/core/solver.c`](src/core/solver.c): per-invocation state with row/column/box 9-bit occupancy masks, MRV, bounded recursion (depth ≤81), and stable ascending digit order. Search terminates at two solutions, so `multiple` is never claimed unique.

**Ownership contract:** the caller owns the input and output structures. Invalid or unsolvable boards do not overwrite `first_solution`. A successful unique or multiple-solution result writes a valid first solution while leaving `givens` unchanged. No global mutable solver state. The exact search is potentially exponential on hard inputs; a configurable search budget is deferred to a later milestone.

## Verification

```sh
cmake -S . -B build-gcc -G Ninja -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Debug -DSUDOKU_ENABLE_SANITIZERS=ON
cmake --build build-gcc
ctest --test-dir build-gcc --output-on-failure
```

Unit fixtures include an easy classic puzzle, a difficult AI-Escargot puzzle, a very difficult puzzle, a fully solved board, a valid but unsolvable puzzle, an empty/multiple-solution board, and invalid givens. An **independent validator in the test executable** checks row/column/box uniqueness and clue preservation without reusing production validation code. See [v0.3.0 test evidence](docs/VERIFICATION_v0.3.0.md).

## Roadmap and provenance

- [Roadmap through v1.0.0](ROADMAP.md) — next v0.4.0 stable CLI and JSON output.
- [Architecture](docs/ARCHITECTURE.md) and [release criteria](docs/PRODUCTION_READINESS.md).
- Legacy exploratory solver files are retained in Git history but are no longer active. Educational copy: [Learning_Modules](https://github.com/MeiRR17/Learning_Modules/tree/main/tracks/languages/c/sudoku); it is **not** auto-synchronized.
- No open-source license has yet been approved. Do not interpret public visibility as a license grant.
