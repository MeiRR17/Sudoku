# Sudoku — C11 exact solver, CLI and quality gates (`v0.8.4`, experimental)

A fully offline Sudoku engine with deterministic exact solving, solution classification, validation and a scriptable CLI. The public solver API is input-preserving: passing the same `SudokuBoard` pointer as both puzzle and solution output now returns `SUDOKU_SOLVE_INVALID` without overwriting the puzzle; use a separate output board. POSIX game saves now stage through exclusive owner-only `mkstemp` paths rather than predictable timestamp/counter names; Windows game-save staging now uses an atomic Win32 counter and process ID alongside exclusive file creation; native Windows acceptance remains pending. v0.8.4 generation now fails closed if the CPU clock is unavailable or moves backwards, and rejects an expired generation deadline before returning success. **This is a development milestone, not a production release.** v0.7.0 added playable terminal Sudoku with notes, bounded undo/redo, check/reset, completion detection and checksummed atomic save/resume. The interactive game now supports read-only `candidates ROW COL` to list legal Sudoku digits for a cell without revealing the answer or affecting undo/redo. Use `auto-notes` to fill legal pencil candidates across the board in one undoable step; this action deliberately replaces any handwritten notes, and repeated unchanged calls do not create redundant history. Use `prune-notes` instead to remove only now-invalid handwritten candidate marks, preserving legal choices and the undo/redo history as one editable action. Candidate calculation is now a single validated row/column/box bitmask operation rather than nine separate full-board trial validations; this preserves behavior while reducing repeated checks for `candidates`, `hint`, `auto-notes`, and `prune-notes`. It also offers a read-only `hint` command for forced naked/hidden singles based on live Sudoku constraints (no stored-solution lookup), plus explicit `hint apply` to place one deduction through the standard undoable move system. Application is blocked while incorrect player entries remain. v0.8.0 added development packaging; v0.8.4 makes interactive save paths with spaces usable and retains the selected path after a post-rename durability warning; v0.8.3 added POSIX save-directory metadata syncing and Linux fault-injection regression tests; v0.8.2 hardens the input-stream lifecycle and makes the Clang static analyzer part of the full local quality gate. Native Windows/macOS validation, license approval and an official release remain pending. The manual CI workflow now fails if its actual OS/CPU architecture does not match the requested native platform. The quality gate additionally requires the complete CTest test inventory (23 Linux and Windows / 22 macOS native Release checks, 20 instrumented checks on Linux/macOS) before testing, so missing, disabled or skippable Python-dependent E2E tests cannot masquerade as a passing run.

## Build and use

Requires CMake 3.16+, a C11 compiler and (optionally) Python 3 for golden CLI tests.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
ctest --test-dir build --output-on-failure
./build/sudoku --help
./build/sudoku --version
./build/sudoku solve --file tests/fixtures/unique.txt --format json
./build/sudoku count --file tests/fixtures/unsolvable.txt --format compact
./build/sudoku solve --stdin --format compact < tests/fixtures/unique.txt
./build/sudoku solve --file tests/fixtures/unique.txt --format json --output solution.json
./build/sudoku generate --seed 42 --difficulty medium --symmetry rotational --format json
./build/sudoku play --file tests/fixtures/unique.txt
./build/sudoku play --seed 42 --difficulty easy --save my-game.save
./build/sudoku play --resume my-game.save
```

On Windows with a multi-config generator, use `build/Release/sudoku.exe` or the appropriate target configuration. Windows and macOS have **not** yet been verified by this project.

Supported actions are `validate`, `solve`, `count`, `generate`, **`play`**, `--demo`, `--help`, `--version`. `generate` takes required `--seed` and `--difficulty easy|medium|hard` (no input board), optional `--symmetry none|rotational`, `--max-attempts`, `--max-checks`, `--max-nodes` and `--max-ms`. It **only emits uniquely solvable puzzles** and exits **6** with no puzzle on budget exhaustion; the CPU-time check is best-effort between node-bounded solver calls. [Generator and difficulty rubric](docs/GENERATION_AND_DIFFICULTY.md) defines algorithmic difficulty via naked/hidden singles, NOT human solving time. For `validate`, `solve` or `count`, exactly one puzzle source is required: `--puzzle DIGITS`, `--file PATH`, or `--stdin`; `--file -` means stdin. Each puzzle contains exactly **81 ASCII digits** (`0` is empty) with optional ASCII whitespace. Non-ASCII/binary bytes, conflicting clues, invalid length and inputs >1 MiB are rejected. Validating givens does *not* prove the puzzle is solvable.

`solve` prints the first deterministic valid solution and warns about multiple solutions. `count` returns exact classifications `0`, `1`, `2+` (two or more, search stops at the second). `--format text|compact|json` selects output; the JSON v1 schema and examples are defined in [docs/CLI_JSON_SCHEMA.md](docs/CLI_JSON_SCHEMA.md). `--quiet` suppresses a non-unique warning. `--output PATH` creates a **new** file only after successful processing and refuses to overwrite an existing file or symlink. It never replaces an existing destination. CLI `--output PATH` now stages and syncs the complete result before atomically publishing the new filename without overwriting an existing destination; POSIX output files are mode `0600` from creation even under a permissive umask. A crash may leave an orphaned `*.tmp.*` file; directory metadata durability after power loss and native Windows behavior are not claimed. 

Exit codes: **0** successful validation/solving/counting (including count=0), **2** incorrect invocation, **3** invalid puzzle, **4** I/O/internal error, **5** valid-but-unsolvable board requested by `solve`, **6** generator budget exhausted. Errors go to stderr and produce no JSON success output.

## Offline interactive play and saves

Start a uniquely solvable imported puzzle (`sudoku play --file tests/fixtures/unique.txt`), a generated puzzle (`sudoku play --seed 42 --difficulty easy`) or resume a saved session (`sudoku play --resume my-game.save`). Gameplay `play --file` now reads the bounded 1 MiB puzzle input from heap storage, avoiding a >1 MiB stack allocation on Windows/MSVC. Interactive `save PATH` accepts spaces in filenames (with or without surrounding double quotes); empty, unclosed, stray or nested double quotes are rejected rather than falling back to an existing save or creating an unintended filename. Once a save has replaced its destination, including with a durability warning, that path becomes the default for subsequent `save`. Type `help` for ASCII-only commands including `set ROW COL DIGIT`, `erase ROW COL`, `note ROW COL DIGIT`, `notes ROW COL`, `clear-notes`, `undo`, `redo`, `reset`, `check`, `status`, `show`, `save [PATH]`, `quit`. Use `--save PATH` when starting a game to establish its default save destination. **Quitting never implicitly saves.** The current board and notes persist, but the previous undo/redo history intentionally resets on load. The `erase ROW COL` command also clears pencil notes from an empty editable cell; this is one undoable change, and repeating erase on an already-empty note-free cell is a no-op. A `reset` of a board with unchanged givens and no notes is now idempotent and does not insert an undo step. For packaging acceptance on a native Linux x64, Windows x64/MSVC or macOS arm64 runner, run `python scripts/platform_acceptance.py --expected ubuntu-latest|windows-latest|macos-latest` with exactly one actual runner option; a successful run requires a clean checkout (including untracked files), can enforce an explicit `--require-sha`, and writes an unsigned exact-SHA local receipt and does **not** publish a release. Save files use the checksummed `SUDOKU_SAVE_V1` format with same-directory temporary write and atomic replace. On POSIX, new save staging files are created atomically with owner-only permissions (`mkstemp`, `0600`) **from the outset**, followed by a defensive `fchmod` before writing, even with a permissive umask; native Windows file ACL validation remains pending. The save writer also rejects malformed externally edited C game states, nonunique original clues and stale cached solutions before opening a temporary file, preserving earlier valid saves. Rechecking uniqueness adds work to each explicit save. The checksum is not authentication. On POSIX v0.8.3 now also fsyncs the parent directory after a successful rename; if this last step fails, the game prints a dedicated **durability uncertainty warning**, because the target may already have been replaced. Power-loss durability is still **not guaranteed** across all filesystems, hardware or unverified Windows/macOS targets. The save format and complete terminal command contract are described in [Gameplay and save format](docs/GAMEPLAY_AND_SAVE.md).

## Stage and verify a development package

`v0.8.0` and `v0.8.2` include relocatable CMake install/export metadata, deterministic ZIP/TGZ packaging,
SHA-256 checksums and local install/extract/smoke tests. These are **development
artifacts only**, not an official GitHub Release. They are not signed; no owner-approved
open-source license exists and native Windows x64 / macOS arm64 acceptance is pending.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
python3 scripts/package_release.py --build build --output dist
python3 scripts/package_release.py --verify-only --output dist
```

See [Packaging and platform gates](docs/PACKAGING_AND_PORTABILITY.md),
[local packaging verification](docs/VERIFICATION_v0.8.0.md), and
[license decision record](docs/LICENSE_DECISION_PENDING.md).

### Manual platform evidence review (development only)

Run the **manual** GitHub Actions Sudoku quality gate on the exact development branch, choosing each native runner separately (no automatic CI minutes). After `platform_acceptance.py` builds and verifies its four development archives, the runner now independently checks them with `verify_receipt_matrix.py --local` before retaining the unsigned receipt. The workflow uploads **only** `platform-receipt.json` and `SHA256SUMS` for seven days: no unlicensed development binaries or archives are published by Actions. These metadata-only downloads are **not sufficient** to rerun the complete three-platform archive matrix elsewhere. If the owner has independently obtained each runner's original four archives in private folders, verify all three together with:

```sh
python3 scripts/verify_receipt_matrix.py --require-sha "$COMMIT_SHA" \
  --linux ./evidence/linux --windows ./evidence/windows --macos ./evidence/macos
```

For a local pre-upload validation on the real runner or clean checkout, use `python scripts/verify_receipt_matrix.py --require-sha "$COMMIT_SHA" --local dist --expected ubuntu-latest` (substitute the native runner label). **All checks validate unsigned internal consistency, not publisher identity**, license approval or production readiness.

## Run quality checks

For the current platform (including Windows with MSVC, provided CMake/CTest/Python and a compiler are installed):

```sh
python3 scripts/quality_gate.py --mode fast
```

Full local Linux/macOS gate with GCC/Clang/GCC AddressSanitizer/UndefinedBehaviorSanitizer, GCC line coverage threshold **90%** and deterministic CLI benchmark:

```sh
python3 scripts/quality_gate.py --mode full
```

No external Python packages are required. The output and benchmark JSON are written to `.quality-build` by default. The property test has fixed random seed `0x5EED2026`, 320 valid partially blanked boards, 128 contradictory boards, and **10,000 random parser inputs**. The generator unit test additionally checks 72 reproducible, uniquely solvable fixtures across three difficulty categories and two symmetry options. The game engine unit tests and interactive E2E script cover save/resume, malformed saves, immutable givens, undo/redo and completion. Tests also contain an independently written solution checker. Optional [libFuzzer](https://llvm.org/docs/LibFuzzer.html) harnesses in `tests/fuzz_parser.c` and `tests/fuzz_solver.c` are not included in normal builds. Execute a bounded, opt-in reproducible campaign with `python3 scripts/run_fuzz.py --runs 3000` (requires Clang/libFuzzer); the script copies the seed corpus so the repository stays clean. See [quality evidence](docs/VERIFICATION_v0.7.0.md) for explicit commands and limits.

A GitHub Actions quality gate is available through **manual `workflow_dispatch` only**, selectable for Ubuntu, Windows or macOS, and does not automatically run on push, PR or a schedule. Running it manually consumes CI minutes. **No hosted CI run is claimed until observed.**

## Project docs

- [Versioned roadmap through v1.0.0](ROADMAP.md)
- [Architecture and ownership](docs/ARCHITECTURE.md)
- [Production release requirements](docs/PRODUCTION_READINESS.md)
- [CLI JSON and exit-code contract](docs/CLI_JSON_SCHEMA.md)
- [v0.7.0 gameplay verification](docs/VERIFICATION_v0.7.0.md)
- [v0.8.0 technical packaging verification](docs/VERIFICATION_v0.8.0.md)
- [v0.8.2 input-safety and static-analysis verification](docs/VERIFICATION_v0.8.2.md)
- [v0.8.3 save durability and failure injection verification](docs/VERIFICATION_v0.8.3.md)
- [Interactive gameplay, commands and versioned save format](docs/GAMEPLAY_AND_SAVE.md)
- [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

The active engine lives in `src/core` and its API in `include/sudoku`. The legacy experimental solver is preserved in Git history and the historical [Learning_Modules copy](https://github.com/MeiRR17/Learning_Modules/tree/main/tracks/languages/c/sudoku), which is not automatically modified. No formal license is selected; public visibility is **not** permission to reuse the code.

### v0.8.2 integrity hardening (development only)

Release verification now limits the unsigned `SHA256SUMS` input to 4 KiB before decoding, and refuses compressed TAR.GZ/ZIP archives larger than 80 MiB **before** streaming their SHA-256 digest or parsing archive entries. ZIP archive verification now preflights the canonical central directory (member count, record bounds, offset, size, and no ZIP64) before Python allocates member metadata, rejecting malformed or oversized archives. Source distribution verification now also requires an exact match between archived source files and the bundled `scripts/release_files.txt`, so dropping or adding a file cannot be hidden by recomputing an unsigned checksum manifest. Development archives also reject case-insensitive and Unicode-normalization filename/directory collisions before reading file payloads; path names are bounded to 4 KiB and 64 components. Portable archive member checks now also reject Windows device-name aliases, NTFS alternate stream colons, forbidden punctuation and trailing spaces/dots in source and installed paths. Development package construction now caps the source manifest at 256 KiB and source/install payload collections at 1,024 files / 64 MiB before reading contents into memory. Installation file paths are now enumerated incrementally, capped at 4,096 visited entries, then sorted only after bounded collection. Source-package manifests now reject symlinked parent directories and Windows-ambiguous `\\` or `:` path spellings, preventing external files from being included through directory aliases. The TAR verifier also streams member metadata under a strict 1,024-file limit rather than preloading an unbounded member list. Cross-platform evidence now compares canonical source-file contents via schema-v2 receipts; it does not require independently compressed ZIP/TAR bytes to be identical across different hosts. Per-platform archive SHA-256 checks remain mandatory, and all evidence remains unsigned and non-release-grade. The native development package verifier now checks archive content consistency **across both ZIP and TAR.GZ**, not just their SHA-256 manifest, and rejects symlink, traversal, duplicate and oversized archive records. Run `ctest` on an uninstrumented Release build to execute the adversarial packaging tests; see [v0.8.2 evidence](docs/VERIFICATION_v0.8.2.md). These checks do not authenticate the publisher or substitute for Windows/macOS validation and an owner-approved license.


**v0.8.4 receipt verifier detail:** Both `--local` and the three-platform matrix validate all four actual ZIP/TAR.GZ archives, not only receipt hash strings: the existing package verifier enforces regular files, canonical paths, binary ZIP/TAR content equality, required executable/header files and source archive membership. These are offline structural checks of unsigned files, not origin authentication. The manual workflow retains only the metadata files; a later full archive matrix still needs copies of the original archives from each host.


**v0.8.4 canonical archive modes:** The development package verifier checks ZIP/TAR file permissions as well as their contents. Source files and non-executable installed assets require `0644`, while installed `bin/` files require `0755` on all platforms, so a Linux/macOS binary cannot silently lose its executable bit and still pass verification. These are archive metadata checks, not proof that the binary runs on supported native hosts.
