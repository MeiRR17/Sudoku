# Sudoku — Production Roadmap (2026-11-09)

**Status:** approved scope for planning; implementation has NOT started under this roadmap.  
**Repository:** MeiRR17/Sudoku · **default branch:** master · **baseline inspected:** 2b8f43f80b2a791eeb69e2d9c344ced9d2d59bb7.  
**Product goal:** a trustworthy, offline-first, cross-platform Sudoku engine and command-line application written in portable C11.  
**Release target:** v1.0.0 production. **Version system:** SemVer; v0.x milestones are development milestones, not production releases.

> This document is the single source of truth for Sudoku product scope and release sequence. A historical source snapshot also exists at MeiRR17/Learning_Modules/tracks/languages/c/sudoku. Do not automatically edit or publish into the educational copy. Preserve its source provenance and leave that repository untouched.

## 1. Evidence-backed baseline

At the inspected commit the repository contains: sudoku.c, puzzle.c, row.c, box.c, square.c, CMakeLists.txt, README.md, .gitignore. There are no test sources, GitHub Actions workflows, release artifacts or license file in the inspected tree.

**Confirmed gaps from source inspection:**
1. sudoku.h is included by source files and referenced in CMakeLists.txt, but the header is absent in the repository; a clean build cannot currently succeed as defined.
2. sudoku.c relies on mutable global UNSOLVED, SIZE_ROWS and SIZE_COLUMNS and a single hardcoded board; its main loop has no defined error contract.
3. setUpPuzzle sets every square's solvable field to 9, then checks whether it equals 0 before propagating the fixed clues. This does not correctly initialize candidates for given cells.
4. updateSudoku indexes possible[number - 1] without validating number in 1..9. Invalid zero/out-of-range input risks undefined behavior.
5. row.c checks a Square* against 0 rather than the square's number, and later uses x after the inner loop as an index. Row-single logic is incorrect and can address outside the 9-entry arrays.
6. square.c has an int-returning function with no return value, and the current solving/update path has incomplete UNSOLVED accounting.
7. box.c uses dynamic allocation without a visible allocation-failure contract; free/destructor code is absent. The current code mixes candidate bookkeeping with puzzle mutation.
8. There is no external input, generator, deterministic automated test harness, documented platform support or reproducible release procedure.

These are inspection findings, **not results from running a build or tests**. Reconfirm with an actual clean local build as the first implementation task.

## 2. Product contract and boundaries

**Production v1.0 must provide:**
- Correct classic 9x9 Sudoku rules: digits 1..9; uniqueness in every row, column and 3x3 box; 0 denotes an empty cell.
- Import 81-character puzzle strings and text files; solve, validate, count up to two solutions, generate puzzles, and play in a terminal.
- Distinct outcomes for invalid input, contradictory givens, no solution, one solution and multiple solutions.
- Optional deterministic seed for generation; generation must check unique solution.
- Friendly CLI help, documented exit codes, scriptable machine-readable output and human-readable boards.
- Linux, macOS and Windows release builds, offline operation and source-build instructions.
- No user accounts, remote server, database, analytics or network access required for v1.0.

**Non-goals before v1.0:** web application, mobile application, leaderboards, cloud sync, login, AI-based solver, OCR, payments, mandatory GUI, and 16x16 Sudoku. Do not expand scope during stabilization.

**Ownership decision:** Sudoku is the production repository; Learning_Modules stays an educational reference snapshot. Any later consolidation needs a separate decision and explicit review.

## 3. Version-by-version implementation plan

### v0.1.0 — Build Recovery & Safety Baseline | 5–8 h
**Goal:** a reproducibly buildable, instrumentable starting point.
- Recover or author the missing sudoku.h with accurate public declarations and types; make file ownership explicit.
- Repair compilation errors, missing includes and required returns; make all functions' contracts explicit.
- Make CMake work from a fresh checkout (target realistic minimum CMake version; C11 required; no local IDE dependency).
- Add warnings for GCC/Clang/MSVC; define Debug/Release and address/undefined-behavior sanitizer configurations where supported.
- Add README build/run steps, a reproducible sample input and a minimal CTest smoke test.
- Keep the historic implementation accessible while refactoring; never assert it is a correct solver yet.
**Acceptance:** clean configure/build on Linux plus one second toolchain; documented smoke command passes; no missing header; no generated files committed. **Depends:** none.

### v0.2.0 — Safe Board Model, Parsing & Validation | 8–12 h
**Goal:** a well-defined data model with no implicit global state.
- Introduce fixed-size Board[81] representation (uint8_t) and documented API; separate immutable givens from mutable solution/game state.
- Replace mutable globals and error-prone heap graph in the engine with bounded, ownership-safe data.
- Parse exactly 81 digits (allow clearly documented whitespace/pretty grid input); reject malformed length, characters and digits outside 0..9.
- Validate initial row/column/box constraints and expose precise errors with cell coordinates.
- Support bounded file/stdin input with error handling; cap input size and prevent integer/index overflow.
- Add unit fixtures: empty, solved, valid partial, duplicate row/column/box, bad length and bad bytes.
**Acceptance:** invalid input never enters solver; zero out-of-bounds accesses under sanitizers; no memory leaks in engine; explicit status values. **Depends:** v0.1.

### v0.3.0 — Correct Exact Solver & Solution Counting | 10–16 h
**Goal:** dependable correctness independent of human-strategy rules.
- Implement candidate masks using row/column/box occupancy; choose minimum-remaining-values (MRV) next cell.
- Backtracking solver with finite depth <=81 and explicit failure/contradiction handling.
- Expose solve_first and count_solutions(limit=2); stop early when a second solution is found.
- Preserve all givens; never mutate caller state on failure without documented behavior.
- Classify INVALID / UNSOLVABLE / UNIQUE / MULTIPLE correctly.
- Add known-answer puzzles across easy/medium/hard/diabolical, unsolvable fixtures, multi-solution fixtures, and cross-check solved boards against an independent validator.
**Acceptance:** every fixture matches expected result; all reported solutions satisfy rules and clues; deterministic solve for identical input; no sanitizer findings. **Depends:** v0.2.

### v0.4.0 — Stable CLI & File Interoperability | 8–12 h
**Goal:** a usable standalone CLI for people and scripts.
- Subcommands: sudoku solve, sudoku validate, sudoku count, sudoku help; select puzzle using --puzzle, --file or stdin.
- Support --format text|compact|json and --output file; document stable JSON schema version and stderr/stdout separation.
- Explicit exit code contract: success, usage error, invalid puzzle, no solution, multiple solutions, I/O/internal failure.
- Add --version, examples, quiet mode, optional solver statistics; no terminal control sequences for redirected output.
- Add golden CLI tests for Linux/macOS/Windows path and line-ending behavior.
**Acceptance:** help/examples run exactly as documented; equivalent input yields identical machine-readable output; failures return nonzero with actionable messages. **Depends:** v0.3.

### v0.5.0 — Reliability, Coverage & CI Foundations | 9–14 h
**Goal:** prevent regressions before feature growth.
- CTest suite with unit, fixture, integration, property/metamorphic and negative tests; deterministic seeds for reproducibility.
- Check solver invariants on generated board transformations; add parser fuzz target where compiler supports it.
- Add warnings-as-errors in supported CI matrix, ASan/UBSan on compatible targets, plus a clean Release build.
- Add local one-command quality gates; GitHub Actions matrix when available and within account CI limits.
- Define baseline benchmarks and record toolchain/platform in the result.
- Start CHANGELOG.md, CONTRIBUTING.md, SECURITY.md; define issue and PR templates.
**Acceptance:** all core solver cases covered, >=90% line coverage for core/parser where measurable, 0 sanitizer findings, documented command can reproduce checks locally even if hosted CI quota is exhausted. **Depends:** v0.4.

### v0.6.0 — Generator, Uniqueness & Difficulty | 12–20 h
**Goal:** supply fresh, verified Sudoku puzzles.
- Generate complete valid 9x9 solutions using randomized seeded search.
- Remove clues while preserving exactly one solution; validate generated puzzle with independent solution count.
- Offer --seed, --difficulty and --symmetry where implemented; ensure seed reproduces identical output for the same version/platform.
- Difficulty labels must be backed by a documented human-technique rating model or defensible measured rubric; **do not infer difficulty solely from number of givens**.
- Place generation attempt/time limits and return an explicit failure rather than hanging.
- Store corpus of generated fixtures across difficulty levels; no copyrighted third-party puzzle database without licensing review.
**Acceptance:** every published puzzle is valid and uniquely solvable; deterministic seed cases pass; generation exits within configured limits; labels have documented measurable criteria. **Depends:** v0.3 + v0.5.

### v0.7.0 — Terminal Gameplay & Local Persistence | 10–16 h
**Goal:** playable offline Sudoku without a GUI dependency.
- sudoku play accepts a provided/generated puzzle; commands for place, erase, notes, reset, undo/redo, check and quit.
- Never permit edits to givens; distinguish pencil notes from placed values.
- Timer, progress display, completion validation, optional accessibility/high-contrast and no-color rendering.
- Explicit save/load schema with version field, robust file validation and atomic-save strategy.
- Add resume/corrupted-save/undo-boundary/keyboard-flow tests; ensure no hidden network activity.
**Acceptance:** start → play → save → resume → finish works end to end; invalid moves and corrupt saves do not crash; terminal and redirected-output modes behave as specified. **Depends:** v0.4 + v0.6.

### v0.8.0 — Cross-platform Packaging & Supply Chain | 8–14 h
**Goal:** repeatable distributable builds.
- Package Windows x64, Linux x64 and macOS arm64 first; expand targets only if builds are verified.
- Provide CMake install targets, release archives, checksums, license/notice (license choice requires owner decision), version metadata and source archive.
- Explicit static-analysis and dependency audit; prefer zero third-party runtime dependencies.
- Document reproducible local build and release workflow, supported platforms, CLI compatibility and rollback.
- Keep artifacts, build caches and credentials out of Git history; tag only verified commits.
**Acceptance:** fresh users can install/run from archives on all declared supported platforms; SHA-256 checksums match; builds and checks are reproducible from a tag. **Depends:** v0.5 + v0.7.

### v0.9.0 — Release Candidate, UX & Risk Closure | 6–10 h
**Goal:** freeze scope and prove readiness.
- Freeze v1 scope; triage all open bugs; resolve all P0/P1 and document accepted lower-severity exceptions.
- Run complete end-to-end regression (solve/count/generate/play/save/load), randomized corpus and bounded fuzz pass.
- Run platform-specific smoke tests from clean checkout/install, check documentation and accessibility.
- Verify performance, resource bounds, error handling, supply-chain metadata and release checklist.
- Produce signed-off release candidate evidence with exact commit SHA and per-platform results.
**Acceptance:** no open release-blocking bug, full required quality gates pass, all release documentation accurate; RC tag is not called production. **Depends:** v0.8.

### v1.0.0 — Production Release | 4–8 h
**Goal:** deliver a public, supportable production release.
- Confirm acceptance and document the approved license, supported OS/toolchain matrix and known limitations.
- Tag v1.0.0 after the required gates pass, publish change log, binaries/source archives and checksums.
- Verify downloading and running the exact uploaded release artifacts on supported systems.
- Publish upgrade/support/bug-report process; test rollback to previous known-good artifact.
- Mark the milestone complete only after verifying the GitHub release and its assets.
**Acceptance:** v1.0.0 tag and public release are present, artifacts verified, documented use cases all pass, no P0/P1 known issue. **Depends:** v0.9.

## 4. Post-production roadmap (not release blockers)

- **v1.1.0 — Hints and explainability (12–24 h):** candidate annotations, human solving techniques (naked/hidden singles, pairs and others as validated), non-spoiler hints, explainable move trace; verify against exact solver.
- **v1.2.0 — Polish and integration (10–20 h):** richer local statistics, export/shareable formats, accessibility improvements, optional embeddable library/API stability. No telemetry by default.
- **v2.0.0 — Optional graphical experience (30–70 h, separate decision):** choose web/PWA versus desktop native from product requirements, reuse C engine via clear API/binding, responsive/mobile/RTL considerations, visual regression and deployment/security. This is **not** assumed part of v1.0.

## 5. Sequencing, estimates and risk

**Critical path:** v0.1 → v0.2 → v0.3 → v0.4 → v0.5 → v0.6 → v0.7 → v0.8 → v0.9 → v1.0.  
**Estimated active engineering effort to v1.0:** **80–130 hours**, single developer, excluding optional v1.1+ and external wait times. This is a planning range, not a guarantee.
- At 5 h/week: ~16–26 weeks.
- At 10 h/week: ~8–13 weeks.
- At 20 h/week: ~4–7 weeks.
Time may increase for toolchain/OS access, generator rating calibration, or unexpected core rewrites; capture actual time per issue and revise after v0.3.

**Primary risks and mitigations:**
- Missing header and undefined behavior → rebuild architecture, strict C11 compiler diagnostics and sanitizers.
- Solver misclassification or corruption → independent constraint validator, count-to-two and fixed test corpus.
- Generator emits ambiguous puzzles → enforce uniqueness in final-output gate.
- Difficulty misleading → publish transparent measured rubric, or ship fewer difficulty labels.
- GitHub Actions quota → use local reproducible gate scripts; require traceable evidence before release.
- Split copy in Learning_Modules → leave as historical reference; make this repository canonical for new product changes.
- License absent → explicitly choose/approve licensing before public release packages.
- Scope creep to web/mobile → defer to v2.0 decision rather than threaten v1 delivery.

## 6. Rules for every future "continue development" cycle

1. Read this roadmap, the latest GitHub issues/PRs and current master before coding. Choose the **next incomplete milestone**, not a speculative version.
2. Develop on a feature branch; keep commits and PRs small enough to review, and include issue links.
3. Prefer shipping actual product code over repeated broad audits. Run only focused tests during implementation; **never skip necessary correctness, safety or release gates**.
4. Push every actual change to GitHub; do not describe local changes as pushed until GitHub confirms the SHA.
5. Merge to **master** when the branch's scoped acceptance checks pass and no blocker remains; the repository uses master, not main.
6. After a UI-visible change, attach an **actual screenshot** taken from the working build when available. A planned mockup must be explicitly labeled as illustrative and not as evidence of shipped code.
7. Report version, commit SHA, branch/PR, completed acceptance criteria, remaining defects, actual tested platforms and next planned version.
8. Never mark v1.0 production-ready based solely on code review or documentation.

## 7. Immediate next task

Open the **v0.1.0** implementation issue. Start with reconstructing sudoku.h and a clean CMake build; instrument diagnostics before attempting the solver rewrite. Do not claim v0.1 is complete merely because the source files exist.

See **docs/ARCHITECTURE.md** for planned interfaces, and **docs/PRODUCTION_READINESS.md** for mandatory verification/release gates.
