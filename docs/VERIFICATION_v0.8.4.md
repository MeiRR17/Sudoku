# Sudoku v0.8.4 — interactive save paths and retry semantics

Date: 2026-11-10. **Development patch only; release acceptance remains on HOLD.**

## Implemented

- The terminal `save PATH` parser consumes the remainder of the input line as a single path, allowing unquoted filenames containing spaces. Optional surrounding double quotes are removed. Empty or unterminated opening quotes are rejected before file creation; only a bare `save` can reuse the configured default path.
- Interactive input permits paths up to 4096 bytes; overlong commands are discarded rather than partially executed.
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

**Evidence status:** these commands are reproducible instructions, **not claimed observed executions** in this update. The GitHub write/PR confirms source delivery, not compilation or cross-platform acceptance. Windows x64/MSVC and macOS arm64 native tests, owner-approved licensing, artifact authenticity and release-grade rollback remain open in [issue #10](https://github.com/MeiRR17/Sudoku/issues/10). No v0.9 Release Candidate, v1.0 release, hosted CI run or official tag is claimed.
