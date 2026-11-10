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

The interactive command parser accepts entire save paths containing spaces, with optional surrounding double quotes. POSIX game saves now create temporary files with exclusive `open(..., 0600)` so their mode is private from creation; defensive `fchmod` runs before writing. This preserves privacy even under `umask(000)` and when replacing a previously world-readable file; permission-setting or stream-conversion failure aborts before rename. This does not imply Windows ACL hardening or validation. Gameplay `play --file` also avoids a >1 MiB stack frame, using a bounded heap buffer and releasing it on every outcome; this targets the unverified Windows/MSVC stack constraints. Successful replacement and post-rename durability warnings both retain explicitly chosen destinations for the next bare `save`; pre-rename failures do not change the default destination. Portable scripted game E2E and the Linux-only directory-fsync fault harness contain focused regressions. This does not establish durability under power loss or pass the pending Windows/macOS/license release gates.


### Exact-SHA platform acceptance receipts (v0.8.4, development only)

From a **clean, checked-out Git commit** on the actual target machine, run `python scripts/platform_acceptance.py --expected ubuntu-latest`, `--expected windows-latest` or `--expected macos-latest`. The optional `--mode full` is supported only for Linux x64; the default is `fast`. Each invocation checks the observed host OS/CPU, matches the exact `GITHUB_SHA` or explicit `--require-sha`, confirms that tracked and untracked files are clean, runs the CMake/CTest quality gate and the development archive packager/verifier, identifies the configured C compiler (Windows requires MSVC), checks all four SHA-256 hashes again, rechecks that HEAD and the working tree are still unchanged, then writes `dist/platform-receipt.json` atomically. An existing receipt is never overwritten. The manual-only GitHub Actions workflow calls the same script on the selected runner and prints its JSON result in the job log.

This receipt is **unsigned, self-reported execution evidence** for one exact Git SHA on one host only; it is not a cryptographic attestation, build provenance signature, owner license approval, proof of other platforms, or permission to publish a release. Failure at any gate prevents a *new* receipt. A reviewer must independently inspect the runner log, exact SHA, native platform and artifacts before treating a receipt as acceptance evidence.


#### Receipt publication integrity (v0.8.4)

Acceptance receipts are written locally through an exclusively created mode-0600 temporary file and fsynced before being published with a same-directory hard link. This refuses to overwrite an existing receipt even in a concurrent race, and refuses a pre-existing temporary file or symlink. Unsupported hard-link filesystems fail closed; there is no fallback that claims release readiness. The test-only Linux validation of this writer passed 14/14 targeted Python unit tests. The receipt remains unsigned, is neither an artifact signature nor full provenance, and native Windows/macOS filesystem behavior still requires acceptance.


#### Fail-closed CTest registration (v0.8.4)

The fast/full quality gate checks CTest's JSON test inventory **before running tests**. CMake can otherwise produce a passing exit code while silently omitting Python-dependent end-to-end tests on a misconfigured runner. Required counts: 22 Linux native Release; 21 Windows x64/MSVC and macOS arm64 native Release; 19 Linux sanitizer/coverage. Each required test is verified by exact name, not just a count. Malformed/missing/duplicate test entries, explicitly disabled tests and required tests configured to skip (`SKIP_RETURN_CODE` or `SKIP_REGULAR_EXPRESSION`) fail the gate. This source implementation is not evidence of native platform execution.


### v0.8.4 — Atomic, no-overwrite CLI result files

`sudoku validate|solve|count|generate ... --output PATH` now stages results in the destination's directory. On POSIX `mkstemp` exclusively creates a private (mode `0600`) temporary file, and a defensive `fchmod` runs before writing; `fflush`, `fsync` and `fclose` must succeed before an atomic no-clobber `link(temp, final)` publishes the result. On Windows, the temporary file uses exclusive `fopen(...,"wbx")`, `_commit` and `MoveFileExA` **without** `MOVEFILE_REPLACE_EXISTING`; native Windows acceptance remains outstanding. Failure removes the staging file and leaves any existing final output untouched. A sudden crash can leave an orphaned `*.tmp.*` file and cannot install a partially written final result; there is **no guaranteed cross-filesystem or power-loss durability** without verified directory metadata behavior. CLI golden regressions cover successful publication, no-overwrite, orphan isolation, and POSIX mode `0600` under `umask(000)`; Linux fault injection checks failed mode setting, file sync and no-overwrite hard-link publication. These executable regressions require a full Sudoku build and have not been run in this update.


#### Streaming TAR validation bounds (v0.8.4)

TAR verification now uses streaming `r|gz` iteration rather than `getmembers()`. It checks the 1,024-member limit **before loading another entry's content**, rejects duplicates immediately, and retains the 64 MiB decompressed-data budget and strict regular-file/path/order enforcement. This reduces memory exposure to malformed archives with very large numbers of header records. The eight isolated Python regression cases passed on extracted exact source functions; this does not establish platform acceptance.


### v0.8.4 — retain manual-run acceptance evidence and verify a three-host matrix

The manual-only GitHub Actions workflow uploads **only** `dist/platform-receipt.json` and `dist/SHA256SUMS` after a successful `platform_acceptance.py --require-sha <40-hex SHA>` run. The upload action is pinned to its full commit SHA; `if-no-files-found: error` prevents a false-success missing artifact. Its name records the platform, exact commit and run attempt. Retention is seven days to minimize storage. **No ZIP/TAR binaries, GitHub Release, tag, automatic CI or licensing decision are produced.** All three platform runs must be triggered manually and the real native toolchains/architectures checked by the acceptance script. A workflow run has **not** been started on this commit.

After manually collecting each run's evidence artifact into three separate folders with its original two filenames, check the consistency matrix:

```sh
python3 scripts/verify_receipt_matrix.py \
  --require-sha <exact-40-character-commit-SHA> \
  --linux ./evidence/linux \
  --windows ./evidence/windows \
  --macos ./evidence/macos
```

The matrix requires `status=passed`, receipt schema v2, one exact Git SHA and project version, the correct observed OS/CPU/actual compiler, mandatory test/package checks, exactly four canonical archive SHA-256 entries per host matching their own `SHA256SUMS`, and the same **canonical extracted source-tree SHA-256** across all three runs. Independent ZIP/TAR compression may differ by host without changing the actual source code. It rejects duplicate JSON keys and missing/duplicate/unsorted manifests. A consistent matrix shows agreement among **unsigned, self-reported files only**: it cannot prove that a runner was trustworthy, that binary artifacts exist or were downloaded and installed, that a license is approved, or that cryptographic release attestation/rollback gates passed. Do not close issue #10, tag, merge, or promote a release on matrix consistency alone.


#### Source-content identity independent of archive compression (v0.8.4)

Platform receipts now use **schema version 2**, with a required `source_tree_sha256`. After the existing package verifier checks regular-file entries, safe paths, size/count limits, SHA-256 manifests and **ZIP/TAR content parity on that host**, `platform_acceptance.py` extracts the verified source ZIP's member map and hashes it canonically: SHA-256 over the domain separator `Sudoku-source-content-v1\\0` followed by sorted, UTF-8 pathname lengths (4-byte big endian), pathnames, payload lengths (8-byte big endian) and raw payload bytes. `verify_receipt_matrix.py` requires this content hash to match across Linux, Windows and macOS. Differences in GZip/DEFLATE compressed bytes across zlib/toolchain versions no longer falsely block matching source trees. The four compressed archive digests **still must match each corresponding host's manifest**; differing *contents* still fail. Legacy schema-v1 receipts are deliberately rejected rather than silently accepted. The digests and receipts are **unsigned and not an attestation**. No live native receipt or platform acceptance has been collected for the new schema yet.


#### Source-manifest path containment (v0.8.4)

`scripts/package_release.py:source_paths()` validates source archive inputs *before reading them*. It refuses a symlinked `release_files.txt`, any symlink within a listed path (including intermediate parent directories), Windows backslash aliases, drive prefixes and NTFS alternate data stream syntax (`:`), noncanonical POSIX paths, duplicates, missing/nonregular files and empty manifests. These checks prevent a directory symlink in an otherwise trusted-looking relative path from pulling bytes **outside the checkout** into a development source package. Validation must also work on Windows, where `\\` is a path separator and `:` has platform-specific semantics. This is source-package hardening, **not** a substitute for real release artifact inspection or the open native Windows/macOS gate.


#### Bounds enforced before source/installed-file reads (v0.8.4)

Archive verification already rejects more than **1,024 members** or **64 MiB unpacked content**, but generation previously built a list of in-memory byte strings using `read_bytes()` before those checks ran. `scripts/package_release.py` now uses `bounded_file_bytes` in **both** `source_paths()` and `installed_paths()`: each file's declared size must fit the remaining 64 MiB budget before opening it; a subsequent read is capped to `size+1` and rejects changed file lengths. Each path list stops after 1,024 files. The source manifest is read with a 256 KiB cap before UTF-8 decoding or parsing. This protects against accidental or malicious oversized/sparse files during *package construction*, not only inspection. These limits are intentionally identical to the archive verifier's existing bounds. Concurrent modifications preserving the same byte length are not detected by these checks; a clean exact-SHA checkout and package verification remain mandatory.

Added `tests/package_budget_unit.py` to the development source manifest and manual-only `*_unit.py` preflight. It covers exact size budget acceptance, over-budget sparse files, cumulative size limits, oversized manifest, file-count limits, and changes in file length between metadata preflight and reading. **Measured local isolated tests: 10/10 PASS** for the three exact extracted GitHub functions, plus **9/9 existing** path-containment scenarios. These are not a complete Sudoku build or proof of cross-platform packaging acceptance.


#### Bounded path enumeration for installed packages (v0.8.4)

The previous installation collector used `sorted(prefix.rglob('*'))` *before* checking the 1,024-file budget. This eagerly allocates path objects for the entire installation tree, even if the eventual archive is small. `installed_paths()` now consumes the directory walk lazily, aborting after **4,096 total visited entries** (including directories) or **1,024 regular files**. It also rejects symlinks during the walk. Only the final verified, bounded list is sorted, maintaining reproducible ZIP/TAR member order irrespective of filesystem enumeration order. This is a conservative v0.8.4 development-package bound; unusual installs with thousands of empty directories are refused, not partially packaged.

`tests/package_budget_unit.py` now includes four additional cases: deterministic sorted output, an intentionally *unbounded* file iterator, an unbounded directory iterator, and symlink rejection. The two unbounded iterators specifically detect a regression to eager `sorted(rglob(...))` without requiring creation of millions of on-disk files. On a Linux isolated extraction of the exact modified function, **14/14** budget tests and **9/9** previous path-safety tests passed. Full native package creation, platform matrix and CTest remain unexecuted in this environment.


#### Cross-platform member name policy — v0.8.4

A canonical POSIX archive member can still be unsafe when extracted on Windows. The release verifier and both collection stages now share `portable_relative_name`, rejecting every path component with Windows DOS device-name stems (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`, superscript digits ¹/²/³, `CONIN$` and `CONOUT$`), `:` (NTFS alternate data streams), Windows-illegal punctuation, ASCII control/DEL characters, trailing dots/spaces and noncanonical `.`/`..`/empty components. Matching is case insensitive for device stems including a file extension. Paths such as `.github/workflows/manual-quality.yml`, `src/core/board.c` and `bin/sudoku.exe` remain valid. The check is applied before reading either source or installed payloads and when verifying both TAR.GZ and ZIP entries, so a new portable artifact cannot carry an ambiguous Windows name. This is deliberately conservative for a cross-platform source archive; the exact native Windows extraction gate is still outstanding.

Added regression scenarios to `tests/source_manifest_unit.py`, `tests/archive_stream_unit.py` and `tests/package_budget_unit.py`. Windows-invalid test filenames are physically created only on POSIX; the pure name checker runs on every host. This mechanism is not a substitute for native Windows x64/MSVC or macOS arm64 release acceptance.

### Cross-platform casefold and Unicode path collision preflight (v0.8.4)

A ZIP or TAR.GZ can be POSIX-canonical and still contain two distinct names that alias when extracted on a case-insensitive filesystem, e.g., `README.md` and `readme.md`, or `Docs/a.txt` and `docs/b.txt`. Mac and Windows may also disagree on Unicode normalization. `scripts/package_release.py:claim_portable_path` now tracks every file **and parent directory prefix**, keyed by NFC-normalized `casefold()` spellings. It rejects differently spelled prefixes, a file used as a directory, or a directory used as a file. A repeated *exact* archive member retains the existing explicit duplicate error. The same registry is enforced in source manifest collection, staged install enumeration, streaming TAR.GZ validation and ZIP validation **before loading each member's payload**. The output remains deterministically sorted after bounded input collection. The registry is constrained by existing 1,024-file archive budgets.

To bound worst-case time and memory from a deeply nested archive entry, `portable_relative_name` refuses relative names longer than **4,096 UTF-8 bytes**, or with more than **64 path components**. This is a conservative development-package portability policy, not a statement of filesystem-specific maximum path support.

New `tests/portable_collision_unit.py` (included in `scripts/release_files.txt`) covers casefold collisions at file/parent-directory level, Unicode casefold and NFC equivalence, file-versus-directory conflicts, valid shared prefixes, exact duplicates, source/install collectors, and path length/depth boundaries. A prior infinite-iterator test now accepts an **earlier** duplicate-path rejection as an equally valid fail-closed outcome. True native Windows/macOS extraction remains a release gate.

### Complete source archive membership cross-check (v0.8.4)

Previously, `verify_packages` validated four archive SHA-256 records, ZIP/TAR.GZ content parity and a limited required-file subset. It did **not** verify that every file listed in the source archive's own `scripts/release_files.txt` was actually shipped. Thus ZIP and TAR.GZ could both omit an optional-but-declared test file and pass verification after recomputing `SHA256SUMS`.

The offline verifier now invokes `verify_source_membership`: it extracts the embedded source manifest (maximum 256 KiB, strict UTF-8), verifies its entries have canonical portable paths, no duplicates or casefold/Unicode collisions, a maximum of 1,024 files, and requires **exact equality** between declared paths and extracted archive member names. The source manifest file itself must be present and declared. ZIP/TAR.GZ parity and per-archive SHA-256 verification remain mandatory. This is a *self-consistency* check: an attacker able to rewrite the manifest, all archives and unsigned checksums could still forge a mutually consistent package. **It does not authenticate origin** or remove the existing owner-license and signed-provenance blockers.

`tests/source_membership_unit.py` builds real synthetic ZIP/TAR.GZ source and binary archives with freshly generated `SHA256SUMS` records to exercise complete acceptance and ten rejection cases without a native Sudoku build. `tests/package_integrity.py` now additionally exercises the real packaged source: delete `tests/source_membership_unit.py` from both archives, recompute both archive hashes, then confirm `source archive manifest mismatch`. The latter integration scenario is registered with existing CTest and awaits a full clean build.


### Bounded ZIP central-directory preflight (v0.8.4)

Python's `zipfile.ZipFile` eagerly parses the central directory and constructs `ZipInfo` objects before the caller can inspect `infolist()` or apply a member-count limit. The existing TAR.GZ verifier already used streaming `r|gz`; ZIP was missing an equivalent pre-allocation guard. `scripts/package_release.py:preflight_zip_directory` now checks the **22-byte canonical ZIP end-of-central-directory trailer** before opening ZipFile, bounding total ZIP file size to **80 MiB** (64 MiB unpacked plus 16 MiB overhead), central-directory size to **8 MiB**, and declared entry count to **1–1,024**. It refuses multi-disk metadata, ZIP64 size/offset sentinel values, archive comments, forged directory offsets and any trailing data. The Sudoku development packager deliberately writes zero-comment, single-disk, non-ZIP64 archives; these restrictions do not claim to validate arbitrary third-party ZIP formats.

The trailer's entry count is untrusted too, so the preflight **walks each central-directory record before ZipFile allocation**: read only the fixed 46-byte record header, check the central-file signature and forbidden ZIP64 sentinels, skip variable-length name/extra/comment data with a bounded seek, and demand that exactly the declared number of records occupies exactly the declared central-directory bytes. A forged small count cannot hide a very large directory. Each record is consumed with constant working memory; full canonical names, regular-file modes, archive parity, SHA-256, and unpacked byte limits are still validated by the existing later verifier. This is a resource and structural-integrity control, **not archive authenticity**.

New `tests/zip_preflight_unit.py` provides **15 standard-library unittest methods** with real ZIP files and forged EOCD/central-directory headers, included in `scripts/release_files.txt` for the project's manual Python unittest preflight. The already-registered full-package `tests/package_integrity.py` now forges an entry count larger than 1,024 and recomputes `SHA256SUMS`, requiring preflight rejection. That complete package integration scenario is committed but has **not** been executed on a complete checkout here.


### Bounded checksum manifest and compressed archive preflight (v0.8.4)

The earlier `verify_packages` used `SHA256SUMS.read_text(...)` with no size limit, then performed streaming SHA-256 on each claimed archive **before** enforcing its container budget. A maliciously large checksum manifest could cause excessive decoding/allocation, and an oversized sparse/compressed TAR or ZIP could consume unbounded hashing I/O. The TAR reader was streaming and bounded member contents, but did not cap the *compressed* archive itself.

The verifier now reads at most **4,097 bytes**, rejecting a `SHA256SUMS` over **4 KiB** before strict ASCII decoding and canonical four-record validation. Each expected release archive must pass a **compressed on-disk size limit of 80 MiB** before any SHA-256 pass. Direct TAR.GZ member verification enforces the same 80 MiB limit before opening the TAR decoder; ZIP continues to enforce its own 80 MiB bound and 8 MiB central-directory limit before `ZipFile` allocation. The 64 MiB uncompressed payload and 1,024-file budgets remain unchanged. These are conservative development-distribution resource bounds, not signatures or origin authentication.

`tests/container_budget_unit.py` (nine unittest methods, registered in the release source manifest) covers a valid real four-archive ZIP/TAR.GZ distribution with regenerated hashes, malformed or oversized checksum manifests, an oversized sparse TAR, the exact boundary reaching the TAR reader, and rejecting an oversized archive *before* calling the checksum routine. `tests/package_integrity.py` adds two full-distribution negative scenarios for oversized `SHA256SUMS` and oversized TAR. The latter full-build E2E scenarios remain unexecuted locally pending full clean Sudoku checkout and CMake/CTest.
