# Sudoku v0.8.3 — POSIX save crash-consistency hardening

Date: 2026-11-09. **Technical development patch only; official release remains on HOLD.**

## Change

- Game save now syncs the containing directory after successful POSIX rename, following a flushed/fsynced temporary file.
- A new C API status `SUDOKU_GAME_DURABILITY_UNCERTAIN` distinguishes a post-rename directory sync error from pre-rename failures. The interactive CLI warns explicitly that the new file may already be present.
- Linux test-only `LD_PRELOAD` interposer injects file sync, rename and directory sync failures; the harness is not part of the shipping CLI/core.
- New CTest `sudoku_save_fault_injection` registered only for native Linux, uninstrumented Release builds; the Python harness builds its tiny interposer with the active C compiler. Existing gameplay/packaging/CLI tests remain.

## Repeatable checks

```sh
cmake -S . -B build-clang -G Ninja -DCMAKE_C_COMPILER=clang -DCMAKE_BUILD_TYPE=Release
cmake --build build-clang
ctest --test-dir build-clang --output-on-failure
cmake -S . -B build-gcc -G Ninja -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Debug -DSUDOKU_ENABLE_SANITIZERS=ON
cmake --build build-gcc
ctest --test-dir build-gcc --output-on-failure
python3 scripts/static_analysis.py
```

Tests distinguish pre-rename failures (old file unchanged/no leaked staging file) from post-rename directory-sync failure (new file present/readable and an explicit warning). They **do not** simulate an actual crash or guarantee durable hardware writes. The parent `fsync` is requested on POSIX systems only. Windows uses `_commit` and `MoveFileExA(WRITE_THROUGH)` unchanged; native Windows and macOS verification remain pending.

## Observed local results

Linux x86_64, 2026-11-09, Clang 17.0.0 and GCC 14.2.0:

| Verification | Actual local result |
|---|---|
| Clang Release CMake/CTest | **22/22 PASS** (includes Linux-only fault injection and packaging) |
| GCC Debug ASan/UBSan CMake/CTest | **19/19 PASS**, no reported sanitizer findings in executed paths |
| GCC gcov Debug CMake/CTest | **19/19 PASS** |
| Clang Static Analyzer | **6/6 production C translation units PASS**, zero diagnostics |
| Measured core line coverage | **580/607 = 95.55%** (board 82/87, solver 91/94, generator 170/176, game 237/250) |
| Save failure injection E2E | **7 assertions/checkpoints PASS** across pre-rename fsync failure, rename failure, post-rename directory fsync failure and recovery |
| Archive integrity/packaging | **4/4** ZIP/TAR.GZ types and parity / SHA256 verification PASS |
| Package extraction | **14 files** in each Linux native archive, **69 source files** in each source archive; compiled and executed the extracted source archive via independent CMake build |

Packaging run (development only):

```sh
python3 scripts/package_release.py --build build-clang --output dist
python3 scripts/package_release.py --verify-only --output dist
```

The fault injector is a test-only shared library built at runtime by `tests/save_faults.py`, and not shipped as a runtime dependency. It tests **return-status semantics and local file contents**, not physical media durability; therefore no release-grade crash-consistency certification is claimed.

**Remaining HOLD gates:** owner-approved license, clean Windows x64/MSVC package/save/rollback tests, macOS arm64 package/save/rollback tests, signed provenance/authenticity and a verified official GitHub Release. GitHub Actions has not been triggered to validate other platforms. The issue #10 stays OPEN. Do not promote to v0.9.0 RC or call this Production.

