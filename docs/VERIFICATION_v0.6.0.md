# Sudoku v0.6.0 — generator implementation and observed verification

Date: 2026-11-09. Scope: seeded generation, rotational clue symmetry, exact uniqueness verification, explicit resource budgets and a sound-but-limited human-technique difficulty proxy.

## Local Linux verification

Run from the source root:

```sh
python3 scripts/quality_gate.py --mode full
python3 scripts/quality_gate.py --mode fast
```

- Clang 17 Release CMake/CTest: **17/17 passed**.
- GCC 14 Debug ASan/UBSan: **17/17 passed**, no sanitizer report in executed tests.
- GCC 14 Debug gcov: **17/17 passed**.
- Full core line coverage (board+solver+generator): **343/357 = 96.08%**, exceeds the 90% gate; parser board 82/87 (94.25%), solver 91/94 (96.81%), generator 170/176 (96.59%).
- C unit tests: **72 deterministic generated puzzles** across easy/medium/hard, symmetry none/rotational, and six seeds per pair, with two equal-output runs, an independent solution validator and the exact solver reconfirming solution count = 1. All pass.
- CLI golden: deterministic generated puzzles, JSON schema semantics, `solve`/`count` round-trip, explicit budget-exhaustion (exit 6, stdout empty), error cases, and `--output` non-overwrite.
- Legacy v0.4 CLI golden and core property tests remain passing.

## Representative actual generated fixtures

All shown fixtures use seed 42 with `--symmetry rotational` and were independently solved/count-checked.

| Level | Clues | Naked singles | Hidden singles | Attempts | Exact checks |
|---|---:|---:|---:|---:|---:|
| easy | 39 | 42 | 0 | 1 | 22 |
| medium | 33 | 38 | 10 | 1 | 27 |
| hard | 26 | 4 | 14 | 13 | 532 |

Example reproduce:

```sh
./build/sudoku generate --seed 42 --difficulty easy --symmetry rotational --format json
./build/sudoku generate --seed 42 --difficulty medium --symmetry rotational --format json
./build/sudoku generate --seed 42 --difficulty hard --symmetry rotational --format json
./build/sudoku generate --seed 42 --difficulty hard --max-checks 1 --format compact  # exit 6; no stdout
```

The difficulty evaluation uses naked and hidden singles; it is *not* a user-study-calibrated subjective difficulty assessment. Source transformations are not copied static puzzles: randomized Sudoku-preserving digit, band, row, stack, column and transpose symmetries precede removal. At most one exact-count-to-two result with unique solution is emitted.

## Remaining production risks

- CPU time limit is best-effort process CPU time between solver calls; each uniqueness trial has a strict node budget. There is no preemptive hard wall-clock timeout.
- Generator coverage is based on measured Linux execution paths, not proof of correctness on every input. No Windows/macOS hosted CI claimed.
- Generation of some difficulty/seed/limit combinations may fail with exit 6, never silently changing difficulty.
- No portable packaged application release, user-facing gameplay, license decision, external security audit or production performance SLOs yet.
