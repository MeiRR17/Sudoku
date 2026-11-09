# Sudoku — C11 engine (`v0.2.0`, experimental)

A minimal **offline Sudoku validator** with a safe, fixed-size 9x9 board, ASCII puzzle input parsing and row/column/box constraint checks. This repository is still a **development prototype, not production-ready**. v0.3.0 adds the exact solver; current validation does **not** establish that a puzzle has a solution, much less a unique solution.

## Run

Requirements: a C11 compiler and CMake 3.16+; Ninja optional.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
ctest --test-dir build --output-on-failure
./build/sudoku --help
./build/sudoku --demo
./build/sudoku validate --file tests/fixtures/valid.txt
./build/sudoku validate --puzzle 000000000000000000000000000000000000000000000000000000000000000000000000000000000 --format compact
./build/sudoku validate --stdin < tests/fixtures/valid.txt
```

On Windows use the platform-specific executable path, e.g. `build/Release/sudoku.exe` for a multi-config CMake generator. Windows builds have **not** yet been verified by this project.

The CLI accepts **exactly 81 ASCII digits `0`–`9`**, with optional ASCII spaces/tabs/newlines. `0` means an empty cell. Every other byte (including `.` and UTF-8 characters) is invalid. Each file or stdin payload is bounded to **1 MiB**. A valid partial Sudoku may still be unsolvable; this limitation is intentional until v0.3.0.

Output:
- `--format text` (default): readable board and a non-conflict statement.
- `--format compact`: precisely 81 digits on stdout, suitable for scripts.
- Detailed input/constraint errors go to stderr. Duplicates include two 1-based cell coordinates.
- Exit codes: `0` valid, `2` command usage, `3` invalid puzzle/input, `4` I/O failure.

## Quality gate

```sh
cmake -S . -B build-sanitize -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Debug -DSUDOKU_ENABLE_SANITIZERS=ON
cmake --build build-sanitize
ctest --test-dir build-sanitize --output-on-failure
```

Requires supported GCC/Clang on a non-Windows host. CTest exercises library parsing/validation, CLI help/version/demo, file/stdin input, valid compact output and invalid row. The unit test additionally exercises invalid byte/length, all three duplicate types, out-of-range manually built boards, oversized input, and **no mutation of caller state on failure**. See [v0.2.0 verification](docs/VERIFICATION_v0.2.0.md).

## Architecture & history

The C11 core has no dynamic board allocation, global mutable solver state or dependency on terminal I/O. Public API: [`include/sudoku/board.h`](include/sudoku/board.h). CLI: [`src/cli/main.c`](src/cli/main.c).

In v0.2.0, the original experimental `sudoku.c`, `puzzle.c`, `box.c`, `row.c`, `square.c` and `sudoku.h` have been superseded by the bounded board architecture. They remain available in Git history (through v0.1.0) and the historical [Learning_Modules copy](https://github.com/MeiRR17/Learning_Modules/tree/main/tracks/languages/c/sudoku). The old solver was not proven reliable and is intentionally **not** compiled or exposed as a solver in this version.

- [Versioned production roadmap](ROADMAP.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Production acceptance gates](docs/PRODUCTION_READINESS.md)
- [v0.2.0 delivery evidence](docs/VERIFICATION_v0.2.0.md)

Production target: `v1.0.0`, after all correctness, cross-platform and release gates have been satisfied. No formal license has yet been selected.
