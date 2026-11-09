# Sudoku v0.5.0 — measured quality gate and local delivery evidence

Date: **2026-11-09**. Release status: **development milestone only; NOT production**.

## Implementation summary

- Deterministic property-based C tests (`tests/test_properties.c`) with seed `0x5EED2026`: **320** partial boards made from a known valid complete grid, **128** contradictory boards and **10,000** random byte/length parser cases. Independent completed-board oracle checks row, column, box and original-clue invariants.
- Optional libFuzzer parser and solver harnesses. Input corpus under `tests/corpus/`; normal builds do not require LLVM/libFuzzer.
- `scripts/quality_gate.py --mode full`: checks Clang Release, GCC Debug with ASan/UBSan, GCC instrumentation and 90% core line-coverage threshold. `--mode fast` works with the platform's CMake generator/compiler. No network packages required.
- `scripts/coverage.py`: GCC gcov compressed JSON analysis of **only** `src/core/board.c` and `src/core/solver.c`. Ignores non-code lines. Strict threshold, returns error on missing files/low coverage.
- `scripts/benchmark_solver.py`: fixed fixture set, two warm-up runs and 25 measured CLI subprocess samples/case, p50/p95/max by wall clock; captures process start overhead and is not an engine-only microbenchmark.
- Changelog, contribution guide, security policy, PR template and manual-only CI workflow.

## Actual reproduced local tests (Linux x86_64)

Compilers: **Clang 17.0.0**, **GCC 14.2.0**. Kernel **Linux 6.18.57**, libc **glibc 2.41**, Python **3.13.5**. Machine details and load affect benchmark timings.

| Check | Observed result |
|---|---|
| Clang 17 Release, strict compiler flags | **15/15 CTest PASS** |
| GCC 14.2 Debug, ASan/UBSan | **15/15 CTest PASS**; no sanitizer errors in executed paths |
| GCC 14.2 Debug with gcov instrumentation | **15/15 CTest PASS** |
| `board.c` line coverage | **82/87, 94.25%** |
| `solver.c` line coverage | **82/85, 96.47%** |
| Core aggregate line coverage | **164/172, 95.35%**; gate >=90% PASS |
| Python CLI golden suite | **56 checks PASS**, included as a CTest test |
| Property regression suite | **10,448** deterministic cases plus invariants PASS |

Commands (repo root):

```sh
python3 scripts/quality_gate.py --mode full
python3 scripts/quality_gate.py --mode fast
```

### Local CLI subprocess performance baseline (Clang Release)

25 measured runs per scenario, after two warm-up runs, Linux x86_64. Sample CLI process startup included. p50 and p95 are descriptive, not production SLOs.

| Scenario | p50 | p95 |
|---|---:|---:|
| Classic unique | 0.685 ms | 0.787 ms |
| AI Escargot | 0.897 ms | 1.177 ms |
| Diabolical | 3.716 ms | 4.052 ms |
| Empty puzzle, count stops at 2 | 0.634 ms | 0.788 ms |
| Valid but unsolvable | 0.592 ms | 0.700 ms |

These numbers are from a local CI-like container and **must not be generalized** to a typical laptop or all possible puzzles. The benchmark object is regenerated to `.quality-build/benchmark.json` by the gate. All listed benchmark numbers below are from the final `Sudoku 0.5.0` source state.

## Security and portability boundaries

- Random test input is deterministic, not an exhaustive fuzz proof. Clang/libFuzzer smoke campaigns were executed locally: **8,000 parser** cases and **2,000 solver** cases, both with seed `1770`, ASan/UBSan, no reported sanitizer crash. Some corpus files were generated as a side effect; they were not committed. Re-run via `python3 scripts/run_fuzz.py --runs 3000` (copies seeds to a temporary directory). These small campaigns are **not** evidence of exhaustive fuzzing.
- ASan/UBSan evidence applies only to executed paths. No claim of no future vulnerability.
- CMake MSVC warnings configuration exists, but Windows/MSVC and macOS have **not** been locally executed. A manual CI workflow can be triggered on those hosts, but no hosted run is claimed.
- Solver search can be exponential for adversarial valid puzzles; node/time budgets and production performance SLOs are future work.
- No full production packaging, checksums, license approval, external pentest or release candidate yet.
