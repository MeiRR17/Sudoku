# Sudoku — C11 solver (revival planned)

**Current state:** historical C learning exercise; **not production ready**. The checked-in source has known build and correctness gaps, including a missing sudoku.h. The roadmap is a proposal for future implementation, not a statement that its features are already shipped.

## Production development plan

- [Version-by-version roadmap through v1.0.0](ROADMAP.md)
- [Planned architecture and technical decisions](docs/ARCHITECTURE.md)
- [Production readiness and release checklist](docs/PRODUCTION_READINESS.md)

The proposed v1.0 target is an offline, cross-platform C11 Sudoku engine with a command-line interface, validation, exact solving, generation, terminal gameplay, tests and distributable binaries. Development begins with **v0.1.0 — Build Recovery & Safety Baseline**.

## History and source provenance

This repository preserves the original C project's Git history. Its original six source/build-definition files were also copied to [Learning_Modules/tracks/languages/c/sudoku](https://github.com/MeiRR17/Learning_Modules/tree/main/tracks/languages/c/sudoku) for learning purposes. The educational copy remains an independent historical snapshot; this repository is the intended canonical production-development location. No archive, move, deletion or automatic synchronization is implied.

The prior cleanup removed tracked IDE metadata and compiled artifacts. Do not reintroduce them. Build and runtime verification of the original code were pending at the start of this roadmap. Refer to the first milestone before attempting to use the solver for real puzzles.
