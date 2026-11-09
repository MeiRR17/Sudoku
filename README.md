# Sudoku — C11 exact solver and CLI (`v0.4.0`, experimental)

An offline Sudoku engine written in portable C11, with deterministic exact solving, solution classification, puzzle validation, and a scriptable command-line interface. **This repository is in development and is not yet production-ready.** v0.4.0 adds a machine-readable JSON contract and safe file output. Puzzle generation and interactive terminal play remain future milestones.

## Build and run

Requires a C11 compiler and CMake 3.16+. Python 3 is optional for additional CLI golden tests.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
ctest --test-dir build --output-on-failure
./build/sudoku --version
./build/sudoku --help
./build/sudoku --demo
./build/sudoku validate --file tests/fixtures/unique.txt
./build/sudoku solve --file tests/fixtures/unique.txt
./build/sudoku solve --file tests/fixtures/unique.txt --format json
./build/sudoku count --file tests/fixtures/unsolvable.txt --format compact
./build/sudoku solve --stdin --format compact < tests/fixtures/unique.txt
./build/sudoku solve --file tests/fixtures/unique.txt --format json --output solution.json
```

On multi-configuration CMake generators, the executable path may be `build/Release/sudoku.exe`. No Windows/macOS build verification has been performed yet.

## Commands

| Command | Behavior |
|---|---|
| `sudoku validate` | Rejects malformed or conflicting givens; does **not** test solvability. |
| `sudoku solve` | Finds a complete valid board or reports no solution. Warns if multiple solutions exist. |
| `sudoku count` | Classifies zero, one or **at least two** solutions, stopping after the second. |
| `sudoku --demo` | Shows a built-in sample board and its solved result. |
| `sudoku --help` / `--version` | Usage documentation and binary version. |

Exactly one input source is required: `--puzzle DIGITS`, `--file PATH` or `--stdin`. `--file -` also means stdin. Exactly **81 ASCII digits** `0`–`9` (0 empty) are required; ASCII whitespace is permitted. All other bytes are rejected. Maximum input size: **1 MiB**.

`--format text|compact|json` selects human-readable display, a compact 81-digit string / solution count (`0`, `1`, `2+`), or a JSON object. `--output PATH` writes successful output to a **new file**; it refuses to overwrite an existing file or symlink. `--output -` prints to stdout. `--quiet` suppresses the warning about multiple solutions; actual errors remain on stderr. JSON failures deliberately produce no JSON payload.

Exit codes: `0` success (including `count` returning 0), `2` usage error, `3` invalid puzzle/input, `4` I/O/internal error, `5` well-formed unsolvable board requested with `solve`.

**Detailed stable schema and examples:** [CLI JSON contract](docs/CLI_JSON_SCHEMA.md).

## Test locally

```sh
cmake -S . -B build-debug -G Ninja -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Debug -DSUDOKU_ENABLE_SANITIZERS=ON
cmake --build build-debug
ctest --test-dir build-debug --output-on-failure
```

The core tests independently verify solver correctness, immutable givens, invalid puzzles, unsolvable boards, and multiple solutions. The Python 3 CLI golden test (enabled automatically when Python 3 exists) verifies JSON content, stderr/stdout, exit statuses, file output refusal, CRLF, and malformed inputs. See [v0.4.0 verification](docs/VERIFICATION_v0.4.0.md). **Local Linux testing does not establish cross-platform support**.

## Technical architecture and roadmap

- [Board model and strict parser](include/sudoku/board.h)
- [Exact deterministic solver](include/sudoku/solver.h)
- [CLI implementation](src/cli/main.c)
- [Planned product versions through v1.0.0](ROADMAP.md)
- [Architecture decisions](docs/ARCHITECTURE.md)
- [Production acceptance gates](docs/PRODUCTION_READINESS.md)

**Next: v0.5.0** expands regression, fuzzing, coverage, CI and reproducible quality gates. Generator, interactive play, binaries, and a public production release are planned for subsequent versions.

The historical exploratory solver is preserved in the Git history and [Learning_Modules](https://github.com/MeiRR17/Learning_Modules/tree/main/tracks/languages/c/sudoku), not automatically synchronized. No open-source license has yet been selected; do not infer any license grant from public visibility.
