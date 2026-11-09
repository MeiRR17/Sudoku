# Sudoku v0.8.2 — archive integrity hardening (development patch)

**Scope:** better detection of malformed or inconsistent development archives. The release approval remains **HOLD** pending native Windows x64/MSVC and macOS arm64 tests, owner license approval, artifact signing/attestation, and rollback acceptance.

## Changes

- The SHA256 verifier checks regular-file types, canonical single-root member paths, sorted unique entries, and bounded uncompressed size (64 MiB / 1,024 files per archive).
- Source and platform package ZIP/TAR.GZ must contain **identical relative paths and identical bytes**. Recomputing SHA256SUMS after changing only one format is insufficient for acceptance.
- A release manifest must contain exactly two archive formats for the source package and for one native platform build, with predictable versioned names and mandatory content.
- A new CTest negative test creates poisoned archives, including some with recomputed checksums, to test rejection of symlinks, non-canonical paths, altered bytes, duplicate entries, missing files and forged release names.
- This verifies **integrity and internal consistency, not authenticity**. SHA256SUMS is not a digital signature.

## Reproducible local checks

```sh
cmake -S . -B build-clang -G Ninja -DCMAKE_C_COMPILER=clang -DCMAKE_BUILD_TYPE=Release
cmake --build build-clang
ctest --test-dir build-clang --output-on-failure
python3 scripts/package_release.py --build build-clang --output dist
python3 scripts/package_release.py --verify-only --output dist
```

## Acceptance boundaries

- **Linux x86_64 local, 2026-11-09:** Clang 17 Release **21/21 CTest PASS**; GCC 14.2 Debug ASan/UBSan **19/19 PASS**; GCC 14.2 gcov **19/19 PASS**, with no sanitizer diagnostics observed in the exercised paths. Optional package tests are deliberately excluded from instrumented builds.
- **Clang static analyzer:** 6/6 active C translation units passed, no diagnostics.
- **Core line coverage:** 563/589 = **95.59%** (board 82/87, solver 91/94, generator 170/176, game 220/232).
- **Adversarial package suite:** 8/8 PASS (valid baseline plus tampered SHA, modified ZIP + recomputed SHA, symlink ZIP, unsafe path, duplicate ZIP, missing TAR, and forged filename).
- **Packaging/consumer/source rebuild:** the ZIP and TAR.GZ files matched byte-for-byte by relative member content; extracted native binary solved a known puzzle, a third-party CMake consumer linked successfully, and extracted source ZIP was independently configured, compiled and solved the same puzzle.
- **Reproducibility:** two independent Clang Release build folders produced executable SHA-256 `c7473d2d7bb057cff63dad8f3f8e4e32da28d3d5d7c07f742de1d3364935629f`; a repeat packager invocation generated **5/5 byte-identical files** (4 archives + SHA256SUMS) from the same staged bytes. This does **not** prove cross-machine reproducible binaries.
- **Platform boundary:** tests were executed on local Linux x86_64 only. Windows/MSVC and macOS/Apple Silicon tests are **not** claimed, and no hosted Actions workflow was run.
- No public GitHub Release or owner-approved LICENSE is created.
- Issue #10 remains open; v0.9.0 Release Candidate remains blocked.
