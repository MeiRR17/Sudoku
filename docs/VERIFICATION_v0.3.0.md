# Sudoku v0.3.0 — build and correctness evidence

**Date:** 2026-11-09. **Scope:** exact deterministic solver and count-to-two; this is a development milestone, not a production release.

## Implemented

- New portable `SudokuSolveStatus` API: invalid givens, no solution, unique solution, multiple solutions; `sudoku_analyze`, `sudoku_solve_first`, `sudoku_count_solutions`.
- MRV exact search with row/column/box bitmasks and bounded recursion depth ≤81. Deterministic tie-break and digit ascending order; no global state.
- Output board unaffected on invalid/unsolvable, original givens preserved, second solution stops enumeration.
- CLI `solve` and `count` added alongside existing `validate`, with `--puzzle`, `--file`, `--stdin` and text/compact output; `--version` updated to 0.3.0.
- Tests include classic unique board with expected exact solution, AI-Escargot, diabolical difficulty board, already-solved board, zero-solution board with legal givens, empty/multiple board, and invalid boards. Independent test-only validator rechecks every returned solution and immutable givens.

## Verification on local Linux amd64

Run from repository root:

```sh
cmake -S . -B build-clang -G Ninja -DCMAKE_C_COMPILER=clang -DCMAKE_BUILD_TYPE=Release
cmake --build build-clang
ctest --test-dir build-clang --output-on-failure
cmake -S . -B build-gcc -G Ninja -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Debug -DSUDOKU_ENABLE_SANITIZERS=ON
cmake --build build-gcc
ctest --test-dir build-gcc --output-on-failure
```

- Clang 17.0.0 Release: **13/13 CTest PASS**, warnings-as-errors.
- GCC 14.2.0 Debug + ASan/UBSan: **13/13 CTest PASS**; no sanitizer findings in executed paths.
- Exact classic solution: `534678912672195348198342567859761423426853791713924856961537284287419635345286179`.
- `sudoku count --file tests/fixtures/unique.txt --format compact` → `1`.
- `sudoku count --file tests/fixtures/unsolvable.txt --format compact` → `0`.
- Empty board (81 zeros) count-to-two → `2+`.
- `sudoku solve` on a valid but unsolvable board returns **5** and does not produce a false solution.

## Known limitations and release gate

- Validating a board is not the same as checking solvability; use `count` or `solve`.
- Search may take exponential time for adversarial puzzles; exact count is intentionally capped at 2.
- No published cross-platform Windows/macOS builds, solver-performance budget, fuzz campaign, generator, JSON schema or production release.
- GitHub Actions are not claimed to have run; local test evidence is separate from hosted CI.
