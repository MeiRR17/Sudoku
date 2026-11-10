# Sudoku v0.8.4 — interactive save paths and retry semantics

Date: 2026-11-10. **Development patch only; release acceptance remains on HOLD.**

## Implemented

- The terminal `save PATH` parser consumes the remainder of the input line as a single path, allowing unquoted filenames containing spaces. Optional surrounding double quotes are removed. Empty or unterminated opening quotes are rejected before file creation; only a bare `save` can reuse the configured default path.
- Interactive input permits paths up to 4096 bytes; overlong commands are discarded rather than partially executed.
- Gameplay `--file` now allocates its bounded 1 MiB + 1 byte read buffer on the heap instead of the function stack. Portable E2E checks include a valid puzzle file, NUL input, empty input, missing file and oversized file. All paths free the buffer on return. This is a portability fix, not a claim of native Windows/MSVC execution.
- POSIX save staging files are created atomically with mode `0600` using `open(O_WRONLY | O_CREAT | O_EXCL)` before the defensive `fchmod`, closing the creation-to-chmod exposure window. The Linux fault interposer adds `check-created-mode` to inspect the mode *as `fchmod` begins*, with `umask(000)` in the child. Existing E2E checks cover new creation and replacement of an existing `0666` file, and failure of `fchmod` without replacing the prior target. Windows ACLs remain unverified.
- The selected explicit path becomes the default after either a successful save or a post-rename directory-sync warning. A failed pre-rename save does not change that default.
- Added portable gameplay E2E scenarios for unquoted and quoted filenames with spaces, bare-save reuse and resume. Extended Linux-only `LD_PRELOAD` directory-fsync fault injection to verify default-path retention after the warning.
- Updated CMake, CLI, package manifest and version assertions to 0.8.4.

## Focused checks to run from this exact branch/commit

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
ctest --test-dir build --output-on-failure -R 'sudoku_(game_e2e|save_fault_injection|cli_golden|package_e2e)'
python3 scripts/package_release.py --build build --output dist
python3 scripts/package_release.py --verify-only --output dist
```

### Additional isolated POSIX creation-mode smoke

On Linux, a minimal standalone C11 reproducer using the exact mode-setting calls in `src/core/game.c` (`open(..., O_WRONLY|O_CREAT|O_EXCL, S_IRUSR|S_IWUSR)`, `fdopen`, `fchmod`, `fwrite`, `fclose`) compiled with GCC `-std=c11 -Wall -Wextra -Werror -pedantic`. Under `umask(000)`, it confirmed mode `0600` **before** `fchmod`, preserved mode `0600` after close, and wrote the expected 15-byte header. This exercises **only the isolated system-call sequence**; it is not an execution of Sudoku or its updated CTest suite.

## Observed isolated check on 2026-11-10

The earlier version of the test-only Linux `tests/fault_inject.c` source was compiled separately using `gcc -std=c11 -Wall -Wextra -Werror -shared -fPIC -O0`. The resulting interposer returned `EPERM` when `SUDOKU_TEST_FAULT=file-mode` was set and succeeded after that fault was cleared. This establishes **only** the isolated fault-interposer behavior. No Sudoku executable was compiled or executed, and no project CTest gate, source package, Windows/MSVC or macOS check is claimed. All remaining target-specific acceptance gates remain pending.

**Evidence status:** these commands are reproducible instructions, **not claimed observed executions** in this update. The GitHub write/PR confirms source delivery, not compilation or cross-platform acceptance. Windows x64/MSVC and macOS arm64 native tests, owner-approved licensing, artifact authenticity and release-grade rollback remain open in [issue #10](https://github.com/MeiRR17/Sudoku/issues/10). No v0.9 Release Candidate, v1.0 release, hosted CI run or official tag is claimed.
