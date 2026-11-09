# Sudoku — C11 exact solver, CLI and quality gates (`v0.5.0`, experimental)

A fully offline Sudoku engine with deterministic exact solving, solution classification, validation and a scriptable CLI. **This is a development milestone, not a production release.** v0.5.0 adds reproducible quality controls, including deterministic property tests, fuzzing harnesses, measured coverage and benchmarks. Puzzle generation, interactive gameplay and verified release packages remain future milestones.

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
```

On Windows with a multi-config generator, use `build/Release/sudoku.exe` or the appropriate target configuration. Windows and macOS have **not** yet been verified by this project.

Supported actions are `validate`, `solve`, `count`, `--demo`, `--help`, `--version`. Exactly one puzzle source is required: `--puzzle DIGITS`, `--file PATH`, or `--stdin`; `--file -` means stdin. Each puzzle contains exactly **81 ASCII digits** (`0` is empty) with optional ASCII whitespace. Non-ASCII/binary bytes, conflicting clues, invalid length and inputs >1 MiB are rejected. Validating givens does *not* prove the puzzle is solvable.

`solve` prints the first deterministic valid solution and warns about multiple solutions. `count` returns exact classifications `0`, `1`, `2+` (two or more, search stops at the second). `--format text|compact|json` selects output; the JSON v1 schema and examples are defined in [docs/CLI_JSON_SCHEMA.md](docs/CLI_JSON_SCHEMA.md). `--quiet` suppresses a non-unique warning. `--output PATH` creates a **new** file only after successful processing and refuses to overwrite an existing file or symlink. It is not a crash-atomic replace operation.

Exit codes: **0** successful validation/solving/counting (including count=0), **2** incorrect invocation, **3** invalid puzzle, **4** I/O/internal error, **5** valid-but-unsolvable board requested by `solve`. Errors go to stderr and produce no JSON success output.

## Run quality checks

For the current platform (including Windows with MSVC, provided CMake/CTest/Python and a compiler are installed):

```sh
python3 scripts/quality_gate.py --mode fast
```

Full local Linux/macOS gate with GCC/Clang/GCC AddressSanitizer/UndefinedBehaviorSanitizer, GCC line coverage threshold **90%** and deterministic CLI benchmark:

```sh
python3 scripts/quality_gate.py --mode full
```

No external Python packages are required. The output and benchmark JSON are written to `.quality-build` by default. The property test has fixed random seed `0x5EED2026`, 320 valid partially blanked boards, 128 contradictory boards, and **10,000 random parser inputs**. Tests also contain an independently written solution checker. Optional [libFuzzer](https://llvm.org/docs/LibFuzzer.html) harnesses in `tests/fuzz_parser.c` and `tests/fuzz_solver.c` are not included in normal builds. Execute a bounded, opt-in reproducible campaign with `python3 scripts/run_fuzz.py --runs 3000` (requires Clang/libFuzzer); the script copies the seed corpus so the repository stays clean. See [quality evidence](docs/VERIFICATION_v0.5.0.md) for explicit commands and limits.

A GitHub Actions quality gate is available through **manual `workflow_dispatch` only**, selectable for Ubuntu, Windows or macOS, and does not automatically run on push, PR or a schedule. Running it manually consumes CI minutes. **No hosted CI run is claimed until observed.**

## Project docs

- [Versioned roadmap through v1.0.0](ROADMAP.md)
- [Architecture and ownership](docs/ARCHITECTURE.md)
- [Production release requirements](docs/PRODUCTION_READINESS.md)
- [CLI JSON and exit-code contract](docs/CLI_JSON_SCHEMA.md)
- [v0.5.0 verification and benchmark](docs/VERIFICATION_v0.5.0.md)
- [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

The active engine lives in `src/core` and its API in `include/sudoku`. The legacy experimental solver is preserved in Git history and the historical [Learning_Modules copy](https://github.com/MeiRR17/Learning_Modules/tree/main/tracks/languages/c/sudoku), which is not automatically modified. No formal license is selected; public visibility is **not** permission to reuse the code.
