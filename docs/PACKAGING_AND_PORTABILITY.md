# v0.8.0–v0.8.1 packaging and portability — technical delivery, acceptance HOLD

**Status (2026-11-09):** local Linux packaging infrastructure implemented and tested. **Not an official production or public distribution release.** The exit criteria in GitHub issue #10 are **not met**: owner has not approved a license and native Windows x64 / macOS arm64 acceptance runs are missing.

## Local build, installation and rollback

Requirements: CMake >=3.16, C11 compiler, Python >=3.9 for deterministic archive tooling, and a native host. Windows builds require MSVC in a developer prompt (or another explicitly selected toolchain); macOS builds require Apple Clang.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure
cmake --install build --config Release --prefix ./stage
./stage/bin/sudoku --version   # On Windows use stage\\bin\\sudoku.exe
python3 scripts/package_release.py --build build --output dist
python3 scripts/package_release.py --verify-only --output dist
```

Use a non-system `--prefix` for staging and install; no administrator rights are required. The stage contains a native CLI binary, the static `sudoku_core` library, public `include/sudoku/*.h` headers, `lib/cmake/Sudoku/SudokuTargets.cmake`, `SudokuConfig.cmake`, `SudokuConfigVersion.cmake`, and README/CHANGELOG/SECURITY files. `find_package(Sudoku 0.8 CONFIG REQUIRED)` and linking `Sudoku::sudoku_core` are tested from an **independently configured** consumer project. `Sudoku::sudoku` is also exported as an executable target. Import paths must remain relocatable.

To uninstall an **isolated** custom prefix, remove that prefix directory. For a shared/system prefix, removal is not managed by the project; do not delete an entire system directory. For a rollback, install a prior **verified and licensed** release to a fresh prefix and select its executable; none is published yet.

## Artifacts and provenance

`package_release.py` writes five items to `dist/` on each host:

- `sudoku-v0.8.1-{linux|windows|macos}-{x86_64|arm64}.tar.gz`
- `sudoku-v0.8.1-{linux|windows|macos}-{x86_64|arm64}.zip`
- `sudoku-v0.8.1-source.tar.gz`
- `sudoku-v0.8.1-source.zip`
- `SHA256SUMS` (four lowercase SHA-256 hex digests, sorted by filename)

The platform label is detected from the **actual packaging host**, not inferred from a remote target. Script rejects unsupported hosts. Source archive membership is explicit in `scripts/release_files.txt`; build outputs, personal saves, `.git` metadata and archives are not listed. Both archive formats use sorted file order, fixed 1980-01-01 timestamps, fixed owner/group IDs where available and deterministic compression settings. This guarantees **repackaging determinism when the staged bytes are identical**, NOT necessarily identical executable bytes across different compilers, machines, runtime linkers or build paths. We separately compare binary hashes for independent local builds when possible. `--verify-only` validates the SHA manifest and checks that archive member paths are safe and sorted; SHA-256 checks corruption, **not authenticity**. No signature/attestation exists.

A CPack TGZ/ZIP definition is also available via `cpack --config build/CPackConfig.cmake`; it is **not** the canonical deterministic archive with the checked manifest. The canonical command above uses Python standard library.

## Required but missing native acceptance gates

Before checking off issue #10 and publishing any release:

1. **Linux x86_64 clean host:** build with GCC and Clang, `ctest`, install from the ZIP/TGZ into a fresh empty directory, verify `SHA256SUMS`, solve a known puzzle, and test corrupted save/resume handling.
2. **Windows x86_64 (native MSVC):** use a clean Windows runner with `/W4 /WX`, run `ctest` including `sudoku_package_e2e` and `sudoku_game_e2e`, package and extract `windows-x86_64` artifacts, check program file extension, path-with-spaces input and save/resume/replace behavior. Record compiler version, OS build, workflow run URL, exact artifact SHA-256. **Not run as of 2026-11-09.**
3. **macOS arm64 (native Apple Clang):** use a genuine Apple Silicon runner, run `ctest` including package/game tests, extract into a clean prefix, test save/resume with malformed save, verify SHA-256 and collect CPU/OS/toolchain and binary hashes. `macos-latest` by itself does **not** prove an arm64 run; record the actual machine architecture. **Not run as of 2026-11-09.**
4. **Licensing:** the owner must explicitly choose and approve a license after checking intellectual-property ownership and third-party notices. See [LICENSE_DECISION_PENDING.md](LICENSE_DECISION_PENDING.md). No LICENSE file is auto-created by v0.8.0.
5. **Release engineering:** check static-analysis/security review; verify clean builds from the exact merged commit, download artifact hashes, document reproducibility conditions and rollback, consider signing and a formal tag/release only after all blockers close.

The v0.8.1 input-stream repair resolves the three previously reported Clang `unix.Stream` warnings in the six production translation units. Evidence and reproduction commands: [v0.8.1 verification](VERIFICATION_v0.8.1.md). This does **not** substitute for native Windows/macOS testing.

The manual workflow checks the actual OS/architecture against the selected runner. A macOS runner that reports Intel/x86-64 **fails** the arm64 gate instead of being counted as Apple Silicon evidence. An appropriately labeled workflow is **not** a substitute for a completed run.

The existing GitHub workflow `.github/workflows/manual-quality.yml` is **manual-only**, deliberately without push/PR/cron triggers to conserve Actions quota. To obtain native evidence, run it **separately** on Windows and Apple Silicon runners after confirming their actual platform. Merely adding a workflow is not evidence that tests ran.

## Security boundaries

- ZIP/TAR members have paths restricted to a single expected package root, with duplicate/unsafe entries rejected before shipping.
- No dependency downloads, tokens or secrets are needed to create local packages. Never commit binary artifacts or user game saves to the repository.
- Untrusted save files are checksummed for integrity but not authenticated. See [GAMEPLAY_AND_SAVE.md](GAMEPLAY_AND_SAVE.md); atomic replacement is not a cross-platform power-loss durability guarantee.
- Source remains **copyrighted with no approved public reuse license**; an artifact existing locally does not grant redistribution rights to third parties.

## v0.8.2 — malicious-archive rejection and ZIP/TAR parity

The packager performs strict verification of canonical file paths, safe regular-file metadata (including no ZIP symlinks), uniqueness/sort ordering, bounded extraction memory and exact byte-for-byte parity between source ZIP/TAR.GZ and platform ZIP/TAR.GZ. `SHA256SUMS` must contain the expected four versioned archives, each with mandatory content; rebuilding checksums after one ZIP file is modified no longer yields a valid package. `tests/package_integrity.py` exercises several forged/tampered packages with recomputed checksums.

This is an **integrity gate, not a signature**: a party able to replace both archive formats and the unsigned manifest can still forge a self-consistent package. Production requires provenance/authentication and the owner's explicit license decision. Native Windows and Apple Silicon testing remain separate open gates.

The v0.8.2 extracted-source ZIP is also configured and built in an independent temporary directory by `tests/package_smoke.py`, with `BUILD_TESTING=OFF`; a known puzzle must solve correctly from that fresh build. Packaging parity tests execute only for uninstrumented Release builds; GCC sanitizer/coverage builds retain their usual 19 unit/integration checks.


## v0.8.3 — POSIX save-directory metadata sync and rollback fault evidence

Linux test-only `LD_PRELOAD` interposition induces file-`fsync`, rename and directory-`fsync` failures during an interactive save. Before rename, the previous save remains byte-for-byte unchanged and staging files are removed. A failure after rename produces a **durability uncertainty warning**, not a claim that the older save survived; the new target remains loadable. The parent directory is synced following successful POSIX renames. This is not a real power-loss/fault-tolerant filesystem certification; disk-controller caches, mount options and non-POSIX hosts remain outside the evidence. Native Windows/macOS package and save E2E, license decision and official release acceptance stay OPEN.

## v0.8.4 — interactive save path recovery (development only)

The interactive command parser accepts entire save paths containing spaces, with optional surrounding double quotes. Successful replacement and post-rename durability warnings both retain explicitly chosen destinations for the next bare `save`; pre-rename failures do not change the default destination. Portable scripted game E2E and the Linux-only directory-fsync fault harness contain focused regressions. This does not establish durability under power loss or pass the pending Windows/macOS/license release gates.
