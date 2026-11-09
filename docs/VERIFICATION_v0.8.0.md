# Sudoku v0.8.0 — technical implementation evidence (acceptance HOLD)

**Date:** 2026-11-09. **Scope:** native Linux packaging and portable tooling. **Status:** delivery complete for the packaging code; issue #10 remains OPEN until the owner approves a license and Windows x64/MSVC + macOS arm64/Clang clean-host verification is recorded. **No public GitHub Release and no claimed signed artifacts.**

## Changes

- Relocatable CMake export for `Sudoku::sudoku_core` and `Sudoku::sudoku`, versioned `SudokuConfigVersion.cmake`, installable headers and project docs.
- CPack TGZ/ZIP development packaging definitions, plus canonical Python stdlib deterministic ZIP/TGZ packager for binary and source artifacts with `SHA256SUMS` and archive traversal checks.
- Source manifest enumerates tracked source paths; build outputs, game saves and `.git` are excluded.
- `tests/package_smoke.py` runs two independent packaging attempts of the **same compiled artifacts** and compares four archive hashes byte for byte; extracts ZIP into temporary isolated prefix and runs real installed `sudoku --version`, `--help`, `solve`; configures an external CMake `find_package(Sudoku 0.8 CONFIG REQUIRED)` consumer, builds and executes it; checks source archive members and removes staging prefix.
- No GPL/MIT/Apache license selected. Native Windows/MSVC and Apple Silicon macOS runs are outstanding, not waived.

## Local Linux build and smoke commands

```sh
cmake -S . -B build-release -G Ninja -DCMAKE_C_COMPILER=clang -DCMAKE_BUILD_TYPE=Release
cmake --build build-release --parallel 2
ctest --test-dir build-release --output-on-failure
python3 scripts/package_release.py --build build-release --output dist
python3 scripts/package_release.py --verify-only --output dist
python3 scripts/quality_gate.py --mode fast
```

The report below should only be updated with **actually observed** command results and artifact hashes. No hypothetical platform check is a pass. See [PACKAGING_AND_PORTABILITY.md](PACKAGING_AND_PORTABILITY.md) for the Windows/macOS acceptance matrix, reproducibility limits and distribution hold.

## Observed local results — Linux x86_64, 2026-11-09

- Compiler: **Clang 17.0.0**, Release, CMake 3.31.6, Ninja; **20/20 CTest PASS** (includes package E2E, golden CLI, full game save/resume and core regression).
- Second **independently configured and compiled** Clang Release build: **20/20 CTest PASS**; both binaries SHA-256 **`bc747806cf29278756cd2f46a3e9435430fb28134de70346c8327dd2493b80bc`** (identical bytes). This is a *single-host/toolchain* reproducibility observation only.
- GCC 14.2.0 Debug ASan/UBSan: **19/19 CTest PASS**; package export smoke is intentionally omitted from instrumented builds, which are not intended for distribution. No sanitizer findings in executed tests.
- `tests/package_smoke.py` created two complete ZIP/TGZ+source+SHA256SUMS sets from the same native Release build, independently compared bytes, extracted the ZIP and ran `sudoku --version`, help and known unique solution, then built and executed a separate CMake consumer importing `Sudoku::sudoku_core`. All checks **PASS**.
- `scripts/package_release.py --verify-only --output dist`: **4/4 archives** with expected sorted, safe members, SHA256 matches **PASS**.
- CPack TGZ developer archive test: **PASS**, SHA256 sidecar generated. This is not the canonical deterministic package.
- Native binary dynamic dependencies on tested host: glibc (`libc.so.6`) and Linux runtime loader; no external network client library required. This is **not** a portability guarantee across older glibc distributions.
- `clang --analyze` generated **three `unix.Stream` warnings in the preexisting CLI input stream logic** (two potential stream EOF-state paths and one possible open-stream leak path). These require triage before production. The E2E and sanitizer tests did not reproduce a crash, but a warning is *not* automatically dismissed as false positive. Static review is **not signed off**.

### Artifact checksums

The canonical authoritative checksum list is the generated `dist/SHA256SUMS` in each verified packaging run; it is not committed because the binary bytes depend on the native build. Do not reuse these exact values on a different host/toolchain. All files were generated locally; no official GitHub Release has been published.

### Open v0.8.0 acceptance blockers

1. Native Windows x64/MSVC warnings-as-errors + package/game E2E: **NOT RUN**.
2. Native macOS arm64/Clang + package/game E2E: **NOT RUN**.
3. Owner-selected and approved software license and third-party notices: **NOT APPROVED**.
4. Static analyzer findings: **TRIAGE PENDING**.
5. Signed public release, clean-host download verification and rollback: **NOT DONE**.

Until these items are actually complete, GitHub issue #10 must remain **open**, even if the packaging source is merged to `master`.

The deterministic source archive is based on the explicit **buildable-source manifest** and includes the C11 source, CMake configuration, tests and selected documentation. Legacy planning documents that remain available in the GitHub repository but are not in this manifest are not silently reconstructed. For the full repository and its entire issue history, consult GitHub `master` at the merged commit.
