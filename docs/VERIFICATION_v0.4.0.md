# Sudoku v0.4.0 — delivery and verification

**Scope:** stable offline CLI contract for validate/solve/count, JSON schema version 1, safe new-file output, explicit exit statuses and portable golden tests. **Development release only; not Production.**

## Code delivered

- `src/cli/main.c`: explicit command/format/source parsing, JSON result renderer, file/stdin handling, `--quiet`, safe `--output PATH` with C11 exclusive-create `wbx`, and exit-code/diagnostic routing. No existing output file is overwritten.
- `tests/cli_golden.py`: stdlib-only Python test runner; validates exact serialized JSON, old compact output, CLI argument errors, stderr/stdout separation, files including CRLF, oversized binary input, safe output refusal, symlink protection where supported, and failure not creating output files.
- `docs/CLI_JSON_SCHEMA.md`: versioned JSON success schemas, error contract, compatibility details and examples.
- `CMakeLists.txt`: bump to 0.4.0, use Python 3 golden tests when present, fix the previously misplaced CTest registration for unsolvable puzzles so `BUILD_TESTING=OFF` works.
- `README.md`: actual usage, contract details and limitations.

## Reproducible local evidence

Linux amd64, 2026-11-09:

```sh
cmake -S . -B build-clang -G Ninja -DCMAKE_C_COMPILER=clang -DCMAKE_BUILD_TYPE=Release
cmake --build build-clang
ctest --test-dir build-clang --output-on-failure
cmake -S . -B build-gcc -G Ninja -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Debug -DSUDOKU_ENABLE_SANITIZERS=ON
cmake --build build-gcc
ctest --test-dir build-gcc --output-on-failure
python3 tests/cli_golden.py build-clang/sudoku tests/fixtures
```

- **Clang 17.0.0 Release**: 14/14 CTest PASS, no compiler warning failure.
- **GCC 14.2.0 Debug ASan/UBSan**: 14/14 CTest PASS, no sanitizer findings in executed tests.
- **Golden CLI suite**: 56 checks PASS, including stable exact JSON payloads, no-output-on-failure and exclusive output file creation.
- Sample unique solution matches `534678912672195348198342567859761423426853791713924856961537284287419635345286179`.
- `count` on unsolvable fixture emits JSON `status=none`, `solutions_found=0`, `capped=false` and exits 0.

## Known limitations

- JSON v1 covers **successes only**. Invalid, I/O-failing or unsolvable solve operations intentionally emit stderr and nonzero exit codes, with stdout empty.
- `--output` creates exclusive new files, not atomic replace; crash/power loss may leave an incomplete newly created file. No overwrite flag.
- Linux was tested; Windows/macOS have not been run. The test script uses portable Python stdlib and normalizes CRLF; actual platform acceptance is still pending.
- Hosted GitHub CI, exact performance budgets, fuzz testing, generator, gameplay, and release packages are future milestones.
