# Sudoku — Proposed Architecture (design; NOT yet implemented)

Updated: 2026-11-09. Baseline: master @ 2b8f43f80b2a791eeb69e2d9c344ced9d2d59bb7.

## ADR-001: Preserve the C11 core and ship an offline CLI first

**Decision:** keep portable C11; target a reusable Sudoku core library plus a small command-line application. Defer web/mobile/GUI to later explicit product decisions. Do not introduce a backend for an offline puzzle.

**Why:** existing sources already use C; the product can be independently packaged, tested and embedded. Separating core algorithms from I/O minimizes failure modes and allows future interfaces.

**Source of truth:** this repository becomes the product implementation. The copy under MeiRR17/Learning_Modules/tracks/languages/c/sudoku remains a historical learning snapshot; it must not silently receive changes or be treated as an upstream dependency. No repository move/rename/archive is approved by this document.

## ADR-002: Board state is bounded and value-based

Proposed public model:
- SudokuBoard contains 81 uint8_t values (0 = empty, 1..9 = clues/filled). Index = row * 9 + col, row/col in 0..8.
- SudokuGame records the original clue mask, current board, note bitsets and bounded undo stack separately from the solver.
- Solver state contains occupancy/candidate bitsets local to an invocation; no process-wide mutable globals (UNSOLVED etc.).
- Explicit enum values for OK, INVALID, UNSOLVABLE, UNIQUE, MULTIPLE, IO_ERROR, LIMIT_REACHED and INTERNAL_ERROR. Exact public names are finalized during v0.2.

**Invariants:** all values within 0..9; no duplicate nonzero value in any unit for valid partial boards; clue positions are immutable during gameplay; solver never reports success with unsatisfied constraints. Exact solving also preserves the caller-owned givens board: an output pointer aliasing the input board is an invalid API call and must fail without modifying the puzzle.

**Ownership:** engine should prefer stack allocation and fixed-size arrays. Any buffer allocated for CLI input or gameplay save state has an explicit owner, maximum length and cleanup path. Bounded recursion in exact solver, maximum 81 placements. A canceled/failed operation leaves externally visible state unchanged unless documented.

## ADR-003: Exact solving and human hints are independent

- Core constraint function: board validity and candidate mask computed from row/column/box.
- Exact solver: MRV selection plus bounded backtracking; optional count limit of 2 distinguishes 0, 1 and 2+ solutions.
- Keep inference/pencil-note and human-technique explanations outside the correctness-critical solver path.
- Generator: start from complete randomized valid board; remove givens only when count_solutions(limit=2) == 1; use a configurable cap on retries. Use explicit PRNG seed and document compatibility limitations.
- Difficulty: require a human-technique rating specification and calibrated fixture set. Clue count alone is not a difficulty score.

## ADR-004: Separate input/output from core

Planned directory structure after incremental migration:

    include/sudoku/board.h
    include/sudoku/solver.h
    include/sudoku/generator.h
    src/core/board.c
    src/core/solver.c
    src/core/generator.c
    src/cli/main.c
    src/cli/commands.c
    src/cli/input.c
    src/cli/output.c
    src/game/game.c
    src/game/save.c
    tests/unit/
    tests/fixtures/
    tests/integration/
    cmake/
    docs/
    CMakeLists.txt

**Important:** this is a proposed target layout, not a claim that these paths exist today. Migration must be incremental and historically traceable.

CLI contract proposed:
- sudoku validate --puzzle BOARD
- sudoku solve --puzzle BOARD [--format text|compact|json]
- sudoku count --file PATH
- sudoku generate --seed INTEGER [--difficulty LEVEL]
- sudoku play [--file PATH] [--save PATH]
- sudoku --version / --help

Standard output is reserved for results, standard error for diagnostics. No data is sent over a network. Machine-readable JSON must be versioned and tested for backward compatibility. Define explicit exit codes in v0.4 and maintain them within v1.x.

## ADR-005: CMake, platform support and quality

- C11, standard library by default, CMake minimum chosen to support common environments (current root requires 3.29; reconsider in v0.1).
- Build targets: sudoku_core library, sudoku CLI executable, optional test executables; Debug, Release and sanitizer profiles.
- CTest local suite runnable without GitHub Actions; supported GCC, Clang and MSVC check matrix.
- Sanitizers on supported host/toolchains, static analysis where available, compiler warnings elevated.
- No hidden generated source files; no IDE output in version control.
- Versioned release artifacts: Linux x64, Windows x64, macOS arm64 as initial support candidates; no supported-platform claim before testing an actual build.
- CI may automate gates when available, but local reproducible evidence is the fallback if Actions quota is exhausted.

## ADR-006: Security, data and release boundaries

- No credentials, external accounts, telemetry or embedded network stack for v1.0.
- Validate every untrusted puzzle/save input before indexing arrays; set a bounded maximum file size (proposed 1 MiB; revise if a documented scenario requires larger files).
- Atomic save strategy (write temporary file, flush/check result, replace on success); future changes must consider platform-specific rename semantics.
- License selection requires owner approval, as the inspected repository has no LICENSE file. Do not silently assign an open-source license.
- Use third-party puzzle corpora only with verified reuse permissions; synthetic/independently constructed fixtures preferred.
- The release process includes tag, exact commit SHA, build recipe, checksums, platform tests, signed-off acceptance and rollback instructions.

## Implementation dependency map

v0.1 build and interface recovery
→ v0.2 board and validation
→ v0.3 exact solver
→ v0.4 CLI
→ v0.5 tests and quality
→ v0.6 generator
→ v0.7 game and persistence
→ v0.8 packaging
→ v0.9 RC
→ v1.0 release.

Small parallel work is allowed (documentation and fixture collection), but no early release of generator or gameplay before solver correctness is established.

## Open decisions (non-blocking until stated release gate)

1. **License (must resolve by v0.8)** — private/internal-only versus explicit permissive/open-source licensing; repository visibility being public does not itself grant a license.
2. **v2 GUI platform** — web/PWA, native, or none; choose only when v1 feedback supports it.
3. **Difficulty rubric (must resolve by v0.6)** — technique-based model, verified tests and language of labels.
4. **Performance budgets (must resolve by v0.5/0.9)** — record machine, datasets and p50/p95; commit thresholds after baseline measurement.
5. **Cross-platform seed consistency** — pin algorithm/PRNG and document whether equal seeds must match on all architectures.

Any material change in scope or API requires a short follow-up architecture decision and roadmap revision.
