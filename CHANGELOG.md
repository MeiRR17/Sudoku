# Changelog

Versions under 1.0 are development milestones, **not** supported Production releases. Dates follow ISO 8601.

## [Unreleased]

- Upcoming v0.6.0: seeded generation of uniqueness-checked puzzles and difficulty calibration.

## [0.5.0] — 2026-11-09

- Added deterministic solver/property tests and bounded random/parser negative corpus checks.
- Added optional libFuzzer harnesses for parser and solver, with reproducible seed corpora.
- Added GCC gcov JSON line-coverage gate (minimum 90% across board/solver), CLI performance baseline script, and portable `quality_gate.py` for a one-command local check.
- Added manual-only opt-in GitHub Actions quality workflow with configurable OS, with no automatic scheduled/PR/push triggers.
- Added contribution, security, release evidence, and PR documentation.

## [0.4.0] — 2026-11-09

- Stable JSON schema v1 for `validate`, `solve`, `count`; safe exclusive-create `--output` and clear status codes.
- Golden CLI integration suite.

## [0.3.0] — 2026-11-09

- Deterministic exact Sudoku solver, unique/multiple/no-solution classification, independent tests.

## [0.2.0] — 2026-11-09

- New fixed-size C11 board, strict parser, constraint validation and input CLI.

## [0.1.0] — 2026-11-09

- Restored missing header, working CMake build and basic smoke tests.
