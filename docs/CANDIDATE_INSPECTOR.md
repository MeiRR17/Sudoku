# Development-only Sudoku candidate inspector (unverified)

The separate `sudoku-candidates` executable and `sudoku_candidate_map` C11 API show the **locally legal digits** for each empty cell in a classic 9×9 board. They do not guess, count solutions, reveal the exact solution or modify the active game. This is an early, non-spoiler helper toward the *post-v1.0 explainability track*; it is **not** a change to the shipped `sudoku` subcommands or to versioned save files.

## Interface

Source:

- `include/sudoku/candidates.h` — public `SudokuCandidateMap` structure with masks for 81 positions and aggregate counts.
- `src/core/candidates.c` — validates the original board, then derives candidate masks from row, column and box occupancy, without heap allocation or solver invocation.
- `src/cli/candidates.c` — isolated, human-readable or JSON inspector.

This development target is compiled by CMake but **not installed or included in release archives**, which remain limited to the existing `sudoku` executable and core library. Build commands below are for later owner acceptance, not evidence of a build that has already run:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target sudoku-candidates
./build/sudoku-candidates --file tests/fixtures/unique.txt
./build/sudoku-candidates --file tests/fixtures/unique.txt --singles-only
./build/sudoku-candidates --file tests/fixtures/unique.txt --format json
```

On Windows multi-config generators, the executable may be under `build/Release/`.

To use inline input, provide exactly 81 digits (zero means empty):

```sh
./build/sudoku-candidates --puzzle 530070000600195000098000060800060003400803001700020006060000280000419005000080079 --singles-only
```

The CLI accepts precisely one `--file PATH` or `--puzzle DIGITS` source. Like the main parser, it rejects an input longer than 1 MiB and validates exactly 81 ASCII digits with optional ASCII whitespace. `--file` expects a real local file path; no network, stdin input, save-file, archive processing or output-file writes are supported.

## Contract

A filled cell has mask zero. For an empty cell, candidate digit `d` is encoded in **bit d** of `uint16_t`, with bit zero unused. Only `1` through `9` can be set. The row-major output uses `row * 9 + column` for zero-based C indices.

`sudoku_candidate_map(board, result)` validates the entire board first. On a validation failure or a null argument, the result structure is left unchanged. On success it sets `empty_count`, `naked_single_count`, `zero_candidate_count` and all 81 candidate masks. A `naked single` is a cell with exactly one currently legal digit under the simple Sudoku rules. The function does not change the input board.

The CLI prints row/column coordinates starting at 1. With `--singles-only`, it prints naked singles **and** zero-candidate cells (the latter are an important warning, not a move). With `--format json`, the output object has `schema_version:1`, `kind:local_candidates`, `solvability:not_checked`, the three aggregate counts, a `singles_only` boolean and an array of cell observations. Each observation contains `row`, `column`, `candidates` (ordered ASCII digit string), `candidate_count` and `naked_single`. No solver result is implied.

Error codes are: **0** for a successfully validated candidate report (even if some cells have no candidates); **2** for incorrect invocation; **3** for malformed/contradictory board input; **4** for an I/O or allocation failure. Errors are printed to stderr; no success JSON is produced. The executable is independent of the existing main CLI's JSON schema.

## Cautions

This is **local legality**, not exact Sudoku solving. A valid-looking partial board may have zero global solutions despite every empty cell having at least one locally legal candidate; likewise, a single candidate is not an authorization to mutate a saved game. Use `sudoku count` and the solver to classify solution existence/uniqueness independently. This module does not implement hidden singles, pairs, guessing, solve traces or a complete human technique rating.

Avoid treating generated output as a source of verified difficulty labels. No puzzle publisher, license decision, portable binary release, user account, analytics, or network integration has been added. **No tests, builds, CLI runs, sanitizer checks or native Windows/macOS acceptance were executed for this draft branch.** Existing production/release gates remain blocked pending owner review.
