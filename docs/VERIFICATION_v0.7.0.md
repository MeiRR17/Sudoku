# Sudoku v0.7.0 — implementation, local tests and limitations

**Development milestone (2026-11-09), not Production.** The feature adds playable offline terminal Sudoku, notes, in-memory undo/redo, reset, completion/progress/time and versioned atomic save/resume. No Windows/macOS build or hosted CI run is claimed.

## Evidence from reproducible Linux x86_64 tests

```sh
python3 scripts/quality_gate.py --mode full
python3 scripts/quality_gate.py --mode fast
```

| Quality check | Observed result |
|---|---:|
| Clang 17 Release CMake/CTest | 19/19 PASS |
| GCC 14.2 Debug with ASan/UBSan | 19/19 PASS, no sanitizer report |
| GCC 14.2 Debug with gcov | 19/19 PASS |
| Core `board.c` | 82/87 lines (94.25%) |
| Core `solver.c` | 91/94 lines (96.81%) |
| Core `generator.c` | 170/176 lines (96.59%) |
| New `game.c` | 220/232 lines (94.83%) |
| **All four core C files together** | **563/589 executable lines (95.59%)** |
| Full coverage acceptance threshold | >=90% PASS |
| Existing CLI golden, generator fixture, property and solver tests | PASS |
| New C game unit + Python CLI game E2E | PASS |

The new unit and scripted integration tests cover a unique puzzle from string/file/generator, rejection of non-unique puzzles, immutable givens, invalid placements, pencil notes, undo/redo, redo-branch invalidation, reset and undo-reset, bounded history eviction, one-move win, canonical saved puzzle, save/resume, wrong checksum, truncated/oversized saves, simulated orphaned atomic temp file, and I/O errors. A new session loaded from disk intentionally starts with a fresh undo/redo history. Tests run fully offline with no ANSI/terminal dependence.

Local CLI benchmark from Clang Release with 25 measured runs/case (process startup included; only indicative):

| Scenario | p50 | p95 |
|---|---:|---:|
| Classic unique | 0.762 ms | 1.089 ms |
| AI Escargot | 0.971 ms | 1.631 ms |
| Diabolical | 3.963 ms | 5.223 ms |
| Empty count-to-two | 0.699 ms | 0.887 ms |
| Valid-but-unsolvable count | 0.688 ms | 0.891 ms |

## Files modified/added

- `include/sudoku/game.h`, `src/core/game.c`: private undo stack, notes and versioned save parser/writer.
- `include/sudoku/play.h`, `src/cli/play.c`: accessible terminal UI and input parser.
- `src/cli/main.c`: add `play` dispatch and version, preserve previous JSON/compact contracts.
- `tests/test_game.c`, `tests/game_e2e.py`: direct game-unit and scripted save/resume/win/corruption regressions.
- `CMakeLists.txt`: core and CLI integration, test and sanitizer/coverage wiring.
- `tests/cli_golden.py`: CLI version golden remains accurate.
- `scripts/coverage.py`: include the new game engine in the >=90% threshold.
- `docs/GAMEPLAY_AND_SAVE.md`: command and save-format semantics, actual durability limitations.
- `README.md`, `CHANGELOG.md`, this report: usage and release status.

## Known limitations and follow-ups

- Save checksum is for **accidental corruption detection, not tamper protection**. No encryption or account/private-data handling.
- POSIX rename and Windows MoveFileExA are intended to be atomic same-directory replacements. Linux executed; Windows/MSVC and macOS remain unverified pending v0.8.0.
- Save writes are synced before rename, but parent-directory fsync is not implemented, so crash/power-loss durability cannot be guaranteed on all filesystems. Orphaned temp files after a crash require manual cleanup.
- Undo/redo history is intentionally **not persisted** across save/resume; the board, notes and elapsed seconds are.
- The 128-snapshot history is intentionally bounded and does not retain unlimited actions; note hints are manual, not adaptive automatic hints.
- Terminal gameplay accepts ASCII commands; color, graphics, mouse, accessibility screen reader testing and internationalization are outside v0.7.0. Input and timer behavior under Windows/macOS has not been validated.
- Hosted GitHub Actions remains manual-only to conserve quota, and was not run as part of this verification.
- Production packaging, cross-platform binary smoke tests, license owner approval, downloadable releases and release candidate remain future milestones.
