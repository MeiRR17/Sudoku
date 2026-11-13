# v0.8.0–v0.8.1 packaging and portability — technical delivery, acceptance HOLD

**Status (2026-11-09):** local Linux packaging infrastructure implemented and tested. **Not an official production or public distribution release.** The exit criteria in GitHub issue #10 are **not met**: owner has not approved a license and native Windows x64 / macOS arm64 acceptance runs are missing.

## v0.8.4 — POSIX output directory durability (development only)

The noninteractive --output PATH command already publishes completed result bytes using an exclusive staging file and link(stage, target) to refuse overwrite. On POSIX, after the staged name is unlinked, the CLI now fsyncs the original parent directory as well. Its directory descriptor is pinned before the link, opened nonblockingly with a directory-only check, and verified against reopened parent identities both before and after sync. This covers publication and staging-cleanup metadata, rather than only syncing the file contents.

If publishing succeeded but syncing the parent directory or removing the stage fails, the CLI exits with code 4 and explicitly states: "Output published but directory synchronization or staging cleanup failed; durability uncertain." Users should inspect the already published target before retrying. A normal successful output remains byte-identical and existing targets are never overwritten. The directory check is best effort, not power-loss certification or a defense against all races. Windows retains its previous MoveFileExA write-through behavior pending actual native acceptance. Linux fault injection exercises a failed parent fsync and a parent-directory swap after sync.


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

- `sudoku-v0.8.4-{linux|windows|macos}-{x86_64|arm64}.tar.gz`
- `sudoku-v0.8.4-{linux|windows|macos}-{x86_64|arm64}.zip`
- `sudoku-v0.8.4-source.tar.gz`
- `sudoku-v0.8.4-source.zip`
- `SHA256SUMS` (four lowercase SHA-256 hex digests, sorted by filename)

The platform label is detected from the **actual packaging host**, not inferred from a remote target. Script rejects unsupported hosts. Source archive membership is explicit in `scripts/release_files.txt`; build outputs, personal saves, `.git` metadata and archives are not listed. Both archive formats use sorted file order, fixed 1980-01-01 timestamps, fixed owner/group IDs where available and deterministic compression settings. This guarantees **repackaging determinism when the staged bytes are identical**, NOT necessarily identical executable bytes across different compilers, machines, runtime linkers or build paths. We separately compare binary hashes for independent local builds when possible. `--verify-only` validates the SHA manifest and checks that archive member paths are safe and sorted; SHA-256 checks corruption, **not authenticity**. No signature/attestation exists.

A CPack TGZ/ZIP definition is also available via `cpack --config build/CPackConfig.cmake`; it is **not** the canonical deterministic archive with the checked manifest. The canonical command above uses Python standard library.

### Canonical checksum format and target-label gate (v0.8.4)

The v0.8.4 verifier accepts only four lowercase-SHA256 checksum records in **filename** order, using strict ASCII text and exactly one trailing LF for each record. Alternate CRLF/CR endings, missing final newline, reordered records, duplicate archive names and invalid digest syntax are rejected before archive validation. Only `linux-x86_64`, `windows-x86_64` and `macos-arm64` are recognized binary release labels. `target_platform()` refuses unsupported architecture combinations rather than producing a misleading platform label. This is a metadata safeguard, **not** a claim that any unexecuted target build passes.

### Cross-checking canonical checksums across all acceptance stages (v0.8.4)

`scripts/verify_receipt_matrix.py` now imports and calls the development packager's exact `canonical_checksum_records` validation routine when reading a platform's unsigned SHA256SUMS evidence. `scripts/platform_acceptance.py` now independently refuses CRLF, CR, nonterminated checksum lines and trailing blank lines before issuing a platform receipt. All three paths require the canonical four-file filename order and lowercase SHA-256. No native platform evidence is inferred from parser success; unsigned metadata is still not a release signature.

### Distribution executable save/resume smoke (v0.8.4)

The existing `sudoku_package_e2e` CTest now goes beyond version, solver and source-rebuild checks: it launches `play` from the ZIP-extracted native executable and **again** from the binary rebuilt from the delivered source ZIP. For each, a private temporary directory is used to create a save with spaces in the path, resume it and recover a pencil note, reject an intentionally corrupted saved file with exit status 3, and verify that `quit` does not implicitly create a save. These are standard-library subprocess calls in `tests/package_smoke.py`, executed by the existing native `quality_gate.py` CTest inventory. No user save paths or network calls are used.

After a successful on-host gate, the unsigned `platform-receipt.json` now includes `packaged_game_save_resume` in its checks array; the cross-host metadata/full matrix requires the same marker. Older receipts from a prior SHA cannot be carried into this acceptance cycle. **A marker is not an attestation:** do not claim Windows/MSVC or macOS arm64 acceptance before that exact native test genuinely runs there. Owner license, provenance and rollback decisions remain open.

## Required but missing native acceptance gates

Before checking off issue #10 and publishing any release:

1. **Linux x86_64 clean host:** build with GCC and Clang, `ctest`, install from the ZIP/TGZ into a fresh empty directory, verify `SHA256SUMS`, solve a known puzzle, and test corrupted save/resume handling.
2. **Windows x86_64 (native MSVC):** use a clean Windows runner with `/W4 /WX`, run `ctest` including `sudoku_package_e2e` and `sudoku_game_e2e`, package and extract `windows-x86_64` artifacts, check program file extension, path-with-spaces input and save/resume/replace behavior. Record compiler version, OS build, workflow run URL, exact artifact SHA-256. **Not run as of 2026-11-09.**
3. **macOS arm64 (native Apple Clang):** use a genuine Apple Silicon runner, run `ctest` including package/game tests, extract into a clean prefix, test save/resume with malformed save, verify SHA-256 and collect CPU/OS/toolchain and binary hashes. `macos-latest` by itself does **not** prove an arm64 run; record the actual machine architecture. **Not run as of 2026-11-09.**
4. **Licensing:** the owner must explicitly choose and approve a license after checking intellectual-property ownership and third-party notices. See [LICENSE_DECISION_PENDING.md](LICENSE_DECISION_PENDING.md). No LICENSE file is auto-created by v0.8.0.
5. **Release engineering:** check static-analysis/security review; verify clean builds from the exact merged commit, download artifact hashes, document reproducibility conditions and rollback, consider signing and a formal tag/release only after all blockers close.

The v0.8.1 input-stream repair resolves the three previously reported Clang `unix.Stream` warnings in the six production translation units. Evidence and reproduction commands: [v0.8.1 verification](VERIFICATION_v0.8.1.md). This does **not** substitute for native Windows/macOS testing.

The manual workflow checks the actual OS/architecture against the selected runner. A macOS runner that reports Intel/x86-64 **fails** the arm64 gate instead of being counted as Apple Silicon evidence. An appropriately labeled workflow is **not** a substitute for a completed run.

The existing GitHub workflow `.github/workflows/manual-quality.yml` is **manual-only**, deliberately without push/PR/cron triggers to conserve Actions quota. By default it runs just the selected host; choose `runner_os: all` only when ready to spend minutes on Linux x64, Windows x64/MSVC and Apple Silicon macOS arm64 together. The three native jobs enforce the platform guard and full local package validation independently. A fourth Linux review job executes only after all three succeed and compares the three unsigned receipt/manifest claims from that same workflow run. Merely adding this workflow is not evidence that any test ran.

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

Acceptance receipts are written locally through a fresh, unpredictable, exclusively created mode-0600 `tempfile.mkstemp` stage in the destination directory, fsynced before publication with a same-directory hard link. The hard link still **refuses to overwrite** an existing receipt even if another process creates it concurrently. Unlike the earlier fixed `platform-receipt.json.tmp` path, stale orphan files from a crash and a symlink at that old predictable path are ignored rather than followed or accidentally removed. Failure removes only the new stage; unsupported hard-link filesystems fail closed. Local focused regression tests cover prior orphan isolation, symlink isolation, concurrent publication and stage cleanup. The receipt remains unsigned, is neither an artifact signature nor full provenance, and native Windows/macOS filesystem behavior still requires acceptance.


#### Fail-closed CTest registration (v0.8.4)

The fast/full quality gate checks CTest's JSON test inventory **before running tests**. CMake can otherwise produce a passing exit code while silently omitting Python-dependent end-to-end tests on a misconfigured runner. Required counts: 22 Linux native Release; 21 Windows x64/MSVC and macOS arm64 native Release; 19 Linux sanitizer/coverage. Each required test is verified by exact name, not just a count. Malformed/missing/duplicate test entries, explicitly disabled tests and required tests configured to skip (`SKIP_RETURN_CODE` or `SKIP_REGULAR_EXPRESSION`) fail the gate. This source implementation is not evidence of native platform execution.


### v0.8.4 — Atomic, no-overwrite CLI result files

`sudoku validate|solve|count|generate ... --output PATH` now stages results in the destination's directory. On POSIX `mkstemp` exclusively creates a private (mode `0600`) temporary file, and a defensive `fchmod` runs before writing; `fflush`, `fsync` and `fclose` must succeed before an atomic no-clobber `link(temp, final)` publishes the result. On Windows, the temporary file uses exclusive `fopen(...,"wbx")`, `_commit` and `MoveFileExA` **without** `MOVEFILE_REPLACE_EXISTING`; native Windows acceptance remains outstanding. Failure removes the staging file and leaves any existing final output untouched. A sudden crash can leave an orphaned `*.tmp.*` file and cannot install a partially written final result; there is **no guaranteed cross-filesystem or power-loss durability** without verified directory metadata behavior. CLI golden regressions cover successful publication, no-overwrite, orphan isolation, and POSIX mode `0600` under `umask(000)`; Linux fault injection checks failed mode setting, file sync and no-overwrite hard-link publication. These executable regressions require a full Sudoku build and have not been run in this update.


#### Streaming TAR validation bounds (v0.8.4)

TAR verification now uses streaming `r|gz` iteration rather than `getmembers()`. It checks the 1,024-member limit **before loading another entry's content**, rejects duplicates immediately, and retains the 64 MiB decompressed-data budget and strict regular-file/path/order enforcement. This reduces memory exposure to malformed archives with very large numbers of header records. The eight isolated Python regression cases passed on extracted exact source functions; this does not establish platform acceptance.


### v0.8.4 — retain manual-run acceptance evidence and verify a three-host matrix

The manual-only GitHub Actions workflow uploads **only** `dist/platform-receipt.json` and `dist/SHA256SUMS` after a successful `platform_acceptance.py --require-sha <40-hex SHA>` run. The upload action is pinned to its full commit SHA; `if-no-files-found: error` prevents a false-success missing artifact. Its name records the platform, exact commit and run attempt. Retention is seven days to minimize storage. **No ZIP/TAR binaries, GitHub Release, tag, automatic CI or licensing decision are produced.** The owner may trigger each host separately, or select the new `all` input to request all three hosts in a **single manual dispatch**. Each native job checks its actual platform and toolchain through the acceptance script; the all-host review downloads only its own run/attempt's unsigned text artifacts and invokes `verify_receipt_matrix.py --metadata-only`. A workflow run has **not** been started on this commit.

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

### Exact-hash source-content snapshots for acceptance receipts (v0.8.4)

The native acceptance runner and offline full receipt-matrix verifier now bind source-content checks to the **same bounded private archive snapshot** that is SHA-256-checked against the corresponding `SHA256SUMS` claim. They no longer hash an archive pathname and separately reopen that pathname later to decode it. Both source ZIP and TAR.GZ are verified by the shared safe snapshot parser before comparing their extracted members; the canonical source tree hash remains independent of ZIP/GZip compression differences across OSes.

This closes a time-of-check/time-of-use **pathname substitution** window, rather than providing an immutable filesystem or signed evidence. No origin authenticity is implied by unsigned checksums or receipts. Native Windows x64/MSVC, macOS arm64, licensing, provenance and rollback acceptance remain mandatory before publishing a release. Focused local checks passed for the changed functions; the new tracked tests and complete CTest/native platform gates have not been run here.

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


### Physical archive hash checks in three-platform evidence matrix — v0.8.4

`scripts/verify_receipt_matrix.py` previously compared the archive digest *strings* in `platform-receipt.json` and `SHA256SUMS` without opening the claimed files. A copied distribution could therefore pass the matrix even when an archive was deleted or modified. Now it requires all four locally present ZIP/TAR.GZ files for each supplied Linux x64, Windows x64 and macOS arm64 folder, checks each local archive's SHA-256 in a bounded streaming pass, rejects symbolic links and non-regular files, and enforces the package verifier's 80 MiB per-archive limit. Receipt JSON is capped at **16 KiB** and SHA256SUMS at **4 KiB** before decode. The test fixture uses real on-disk byte content and covers tampering, missing files, links, oversized artifacts and oversized text metadata. Different cross-platform compressed bytes remain valid if each platform's own digests match and the canonical source digest agrees. This checks **internal consistency of unsigned evidence**, not provenance, signature authenticity, archive format correctness or native binary execution. Those independent v0.8 platform/license/release checks remain outstanding.


### Verify canonical source content against each platform receipt (v0.8.4)

The previous receipt-matrix hardening confirmed that all twelve archive *files* matched their recorded SHA-256 values but still trusted each unsigned `source_tree_sha256` claim. The matrix now reuses the project's strict `package_release.ensure_safe_archive` reader on **both** development source ZIP and TAR.GZ in each platform folder, requires exact member-byte equality and validates complete embedded `scripts/release_files.txt` membership. It calculates the canonical path-and-content SHA-256 using the same `platform_acceptance.source_tree_digest` function as the native receipt producer and rejects a mismatched receipt. Different compression outputs are allowed so long as verified extracted source members agree.

This adds a second content-level binding to the existing bounded archive hashing, without expanding v1 scope or changing receipt schema v2. It still does not prove publisher identity: an adversary who can replace every receipt, manifest and archive could create another self-consistent unsigned bundle. Signed provenance, real native platform tests, owner-selected license and production approval remain outstanding. `tests/receipt_matrix_unit.py` now creates real synthetic ZIP/TAR.GZ archives and adds regressions for coordinated digest forgery, source alteration with recomputed unsigned hashes, format disagreement and embedded-manifest mismatch.


### Manual GitHub Actions integration: validate archives *before* metadata-only upload (v0.8.4)

The three-platform matrix now checks physical archive files and canonical source contents, but the public repository's manual Actions workflow deliberately retains **only** `dist/platform-receipt.json` and `dist/SHA256SUMS`: uploading unlicensed development binaries while the owner has not chosen a license is explicitly out of scope. Rather than weaken the archive verifier or silently publish ZIP/TAR, the same `scripts/verify_receipt_matrix.py` now has an additive, strict **single-platform local mode**:

```sh
python scripts/verify_receipt_matrix.py --require-sha "$COMMIT_SHA" --local dist --expected ubuntu-latest
```

The `--expected` label must match the accepted native runner and the receipt; `--require-sha` must be an exact lowercase 40-character commit ID. `--local` forbids `--linux/--windows/--macos` arguments; the original three-host matrix still requires all three folders. The existing `verify_one` implementation checks platform/arch/compiler, exact SHA, receipt and manifest, presence and SHA-256 of four actual on-disk archives, source ZIP/TAR member parity, source manifest completeness and recomputed canonical source digest. The workflow invokes that mode **after** `platform_acceptance.py` and **before** `upload-artifact`, while files still exist on the runner. No push, PR or scheduled Actions trigger was added, retaining deliberate manual-only CI usage.

**Evidence scope:** An Actions run can now independently verify its complete private development package before uploading unsigned metadata; the uploaded two text files alone still cannot support a later off-runner full three-host archive verification. That check requires separately and privately available original ZIP/TAR files from all three hosts. The workflow retains the seven-day metadata-only policy. This is not evidence of a completed run, permission to distribute artifacts, cryptographic provenance or release sign-off.


### Complete binary package validation during offline receipt review (v0.8.4)

The receipt verifier already streamed SHA-256 over all twelve actual ZIP/TAR.GZ archives and validated canonical **source** ZIP/TAR byte equivalence and source manifest membership. However, it did **not** verify the *binary* ZIP/TAR structure and content agreement on external review: an adversary could modify the binary ZIP, update both unsigned `SHA256SUMS` and `platform-receipt.json`, then pass the matrix despite a missing executable, replaced header, a symlink member or inconsistent binary ZIP/TAR content.

After validating each receipt's canonical source digest, `verify_one` now invokes the project's existing bounded `package_release.verify_packages(folder)`. That verifier rechecks each archive SHA-256 and canonical packaging rules, all four physical archive contents, ZIP/TAR parity for **both** source and binary platform variants, all required install assets and file types. This applies to both the workflow's one-host `--local` mode and the three-host matrix. Its extra archive pass is intentional for independent post-transfer integrity checking, although it is not proof of signer authenticity or functional binary execution. The matrix tests now stage real synthetic binary archives with the required executable and header files, including the Windows `bin/sudoku.exe` naming. Three new negative scenarios rewrite corrupt binary archives and regenerate their unsigned digest records to prove the structural package check rejects them. This remains experimental development packaging: no automatic artifact publication or release approval.


### Normalize invalid ZIP/TAR.GZ decoder exceptions (v0.8.4)

A malformed file that passes the preliminary filename and container-size checks can still make Python's `tarfile`, `zipfile`, `gzip` or `zlib` APIs raise a library-specific exception (for example, truncated gzip data, invalid TAR headers or ZIP member CRC mismatch). The command-line verifier's normal error contract is a bounded, clear `ValueError`-based failure; before this patch, selected decoding exceptions escaped that contract as an unhandled traceback. The public `ensure_safe_archive` entry point now delegates to `_ensure_safe_archive` for all existing bounded parsing and portability checks, translating only `tarfile.TarError`, `zipfile.BadZipFile`, `gzip.BadGzipFile`, `zlib.error`, `EOFError` and `struct.error` to `ValueError('malformed archive container')` with their original exception available as the cause. Semantic validation errors remain unchanged; the archive contents are not repaired or partly accepted. Both the development package verifier and the cross-platform receipt verifier use this shared entry point.

`tests/archive_stream_unit.py` includes corrupted (yet valid gzip) non-TAR headers and truncated gzip streams. `tests/zip_preflight_unit.py` includes a canonical ZIP whose stored member contents were modified to produce a real CRC mismatch while leaving the central-directory preflight intact. These three cases require the uniform `ValueError` result. This error-contract correction does not authenticate unsigned archives or complete native platform acceptance.


### Fail closed on encrypted and unsupported-compressor ZIP members (v0.8.4)

The bounded central-directory preflight validates record counts and offsets, but intentionally does not inspect ZIP entry encryption or compression flags. Before this hardening, a crafted archive with otherwise valid ZIP metadata could set its entry's traditional/strong encryption flags or switch its compression method to an unsupported ID. Python's `zipfile` reader can then raise an unhandled `RuntimeError` (password required) or `NotImplementedError` (unsupported compressor) during member extraction. The project only produces ordinary DEFLATE ZIPs, and its verifier also supports stored entries for legitimate alternate compression results.

`scripts/package_release.py: _ensure_safe_archive` now checks `item.flag_bits & 0x41` and limits `item.compress_type` to `ZIP_STORED` or `ZIP_DEFLATED` **before** opening the member stream. It emits a canonical `ValueError` for both cases, leaving existing size, path, regular-file and ZIP CRC validation intact. Three new `tests/zip_preflight_unit.py` regressions forge both the local and central directory header fields, ensure structural preflight still passes, then demand the fail-closed verifier result. The added tests make no network calls. This is format hardening, not cryptographic signature validation or general ZIP format support.


### Complete gzip footer verification and bounded TAR padding (v0.8.4)

The previous `tarfile.open(path, 'r|gz')` pipeline stopped at the TAR end-of-archive marker, but on Python's streaming decoder that is **not guaranteed to consume the surrounding GZIP footer**. A TAR.GZ file with intact regular-file members but its last eight GZIP footer bytes removed could therefore be accepted by `ensure_safe_archive`; the missing CRC32 and ISIZE were never checked. This was reproduced with a real gzip/tarfile archive on Linux before the change.

The reader now creates a `gzip.GzipFile` and supplies it through `_BoundedTarGzipReader` to `tarfile.open(fileobj=..., mode='r|')`. The adapter bounds **total decoded bytes**, not just bytes of file payloads, using `MAX_TAR_DECODED_BYTES = MAX_UNPACKED_BYTES + MAX_ARCHIVE_FILES * 8192 + 16384` to accommodate bounded TAR/PAX headers and zero padding. After all TAR members pass the existing file-count, path, regular-file and per-content limits, the gzip decoder is drained in bounded 64 KiB chunks. This forces Python's gzip CRC32/ISIZE validation and rejects nonzero trailing decoded TAR data. Decoder-specific EOF, malformed gzip and CRC errors follow the existing `ValueError('malformed archive container')` exception contract. The tar reader remains streaming; member data is never extracted to disk or read without bounds.

Four new `tests/archive_stream_unit.py` cases cover a GZIP footer removed while member data remains intact, a flipped CRC32 footer bit, a concatenated GZIP member with nonzero trailing TAR bytes, and a lowered decoded-byte ceiling. The existing archive output is unmodified and supported across Linux, Windows and macOS, but the real native platform matrix still requires acceptance.


### Canonical executable and file permission verification (v0.8.4)

Archive content parity and SHA-256 do not preserve the permission bits a user will receive when extracting a package. Prior to this change the TAR reader verified regular-file types and payload bytes, while the ZIP reader verified regular-file types, but neither verified that a packaged `bin/sudoku` executable retained its Unix execute permissions. A package with the same bytes and updated unsigned hash manifest could pass despite a `bin/sudoku` mode of `0644` and an unusable Linux/macOS installation.

The packager already writes platform-independent canonical modes: installed files under `bin/` use `0755`, while non-bin installation assets and all source archive files use `0644`. The shared `canonical_archive_mode` helper now defines that invariant for both verification paths. TAR entries must have exactly the expected `TarInfo.mode`; ZIP entries must have the exact POSIX regular-file type plus expected mode in `ZipInfo.external_attr`, preventing stray setuid/setgid bits as well. This rejects damaged or substituted distributions before they pass `package_release.verify_packages` or the cross-platform receipt verifier. This is canonical package validation, not a filesystem permission change or a license to redistribute packages.

Added regression cases to `tests/archive_stream_unit.py` for over-permissive source TAR files and binary TAR files missing their executable bit; added three cases to `tests/zip_preflight_unit.py` covering restricted source ZIP mode, non-executable binary ZIP, and a positive binary ZIP with an executable and correctly marked header. Existing legitimate writer-produced archives retain their generated permission modes unchanged. Native Windows/MSVC and macOS arm64 extraction, actual installed binary launch and full CTest remain required.


### Reject extra zero TAR padding and concatenated GZIP streams (2026-11-11)

Prior hardening drained `gzip.GzipFile` to EOF, validated member CRC32/ISIZE and rejected **nonzero** decoded data beyond the TAR end marker. However, Python transparently accepts concatenated GZIP members and may ignore raw zero bytes appended after the final GZIP footer. A second member containing only zeros, or additional TAR zero records in a single valid gzip stream, could therefore be accepted without altering archive members. The deterministic Sudoku TAR writer emits exactly one GZIP member over a TAR payload padded to complete 10 KiB records.

The bounded decompression adapter now computes CRC32 incrementally across **all** decoded bytes. After ordinary member validation and complete gzip decoding, the reader requires exactly `ceil((tar_offset + 2 * tarfile.BLOCKSIZE) / tarfile.RECORDSIZE) * tarfile.RECORDSIZE` decoded bytes, where `tarfile.RECORDSIZE = 10240`. This enforces the writer's canonical zero-padding length without forbidding valid long-name PAX records. It also checks the final eight **physical** GZIP file bytes (CRC32 and ISIZE) against the entire decoded stream. Together these conditions reject zero-only concatenated GZIP streams, empty appended GZIP members, arbitrary raw zeros after the original footer, and a valid recompressed GZIP payload containing extra TAR zero records. Existing bounds on compressed size, total decoded size, individual files, portable paths and file modes still apply.

Five regressions in `tests/archive_stream_unit.py` cover the four appendage variants and a long PAX-name positive control. The existing ZIP archive path is unchanged. These format-consistency checks are not cryptographic signatures and cannot prove artifact publisher identity; license approval and full platform acceptance are still required.


### Stream and bound native acceptance archive checks (2026-11-11)

`scripts/platform_acceptance.py` generates the per-host development receipt only after building and verifying all four ZIP/TAR.GZ archives. The former second-pass SHA-256 step used `Path.read_bytes()`, which loads each complete archive into RAM and did not independently enforce its maximum compressed size or exact platform-specific membership if the artifact was changed between the package verifier and receipt creation.

The new `verified_archive_hashes(dist, version, expected)` performs a separate fail-closed second-pass check before issuing any receipt. It reads `SHA256SUMS` with a 4 KiB limit, enforces exactly four distinct sorted records with canonical lowercase SHA-256 digests and the expected current version/platform archive names (two source formats and two native binary formats), rejects symlinked or missing input files, checks that the opened file descriptor references a regular file, enforces an 80 MiB per-archive cap and streams SHA-256 in 64 KiB chunks. Only those fresh digest results are included in the unsigned native receipt. The existing full `package_release.py --verify-only` structure, extracted content, mode and source-manifest checks still run immediately beforehand; this step is a second physical-integrity check, not a substitute.

Seven new `tests/platform_acceptance_unit.py` cases cover valid four-archive manifests, changed bytes after packaging, sparse over-limit archives, symlink substitution, oversized checksum input, duplicate/unsorted records and a wrong-platform filename. These fixtures use small synthetic files to validate this helper, not full Sudoku release builds. License approval, exact-SHA native Windows/macOS evidence, issuer authenticity and rollback acceptance are still mandatory.


### Nonblocking, descriptor-checked acceptance evidence inputs (2026-11-11)

The local acceptance generator and three-platform receipt matrix both consume untrusted on-disk SHA256SUMS, archives and receipt JSON. Previous checks such as `Path.is_symlink()`, `Path.is_file()` and `Path.stat()` occurred **before** `Path.open()`, allowing a race if another process swapped a regular input for a symlink or named pipe between those calls. A no-writer FIFO could block in the open operation; a swapped symlink could refer to unrelated content. Even after the verifier confirmed a path's file type, an attacker could change that path before the next open.

`scripts/platform_acceptance.py` now exposes `open_regular_input(path, kind)`, which uses `os.open` with `O_NONBLOCK`, `O_NOFOLLOW`, `O_CLOEXEC` where supported, a Windows no-inherit/binary flag where available, and validates `S_ISREG(os.fstat(fd).st_mode)` on the resulting descriptor. It refuses a final-component symlink (portable preflight, plus kernel-enforced `O_NOFOLLOW` where available), FIFO, device, directory or missing file before attempting to parse or hash it. The caller receives the already-open descriptor as a binary stream, with explicit ownership/close semantics. Archive size caps now use `fstat` of that descriptor, and the streaming byte caps remain in place. The cross-platform matrix imports the same helper rather than duplicating an unsafe path preflight. This is a **local artifact-integrity hardening**; Windows reparse-point race semantics and all native platform acceptance remain unverified.

Five regressions were committed to `tests/platform_acceptance_unit.py` and `tests/receipt_matrix_unit.py`: FIFO manifest, FIFO archive, final-component symlink substitution between precheck and open (POSIX `O_NOFOLLOW`), FIFO platform receipt and FIFO matrix archive. The new tests use real named pipes and do not depend on a native Sudoku binary. No signed/independently authenticated artifact or accepted release is asserted.


### Compare three unsigned Actions evidence bundles without publishing binaries (2026-11-11)

The manual GitHub Actions workflow intentionally **does not upload unlicensed development ZIP/TAR.GZ archives**. It retains only `dist/platform-receipt.json` and `dist/SHA256SUMS` per runner. A full three-platform verification requires the archive bytes and therefore cannot be run on downloaded metadata alone. Do not mistake the absence of binaries for evidence that they were tested on another machine.

A new strictly scoped `--metadata-only` mode on `scripts/verify_receipt_matrix.py` solves the separate administrative problem of comparing these **unsigned text claims** after downloading all three evidence artifacts. Unpack each into a separate directory containing `platform-receipt.json` and `SHA256SUMS`, then run:

```sh
python scripts/verify_receipt_matrix.py \
  --require-sha 0123456789abcdef0123456789abcdef01234567 \
  --metadata-only \
  --linux evidence/linux \
  --windows evidence/windows \
  --macos evidence/macos
```

Replace the example SHA with the **actual exact 40-character commit SHA** tested by each host. The command rejects any missing/mismatched platform, architecture, compiler identity, required checks, timestamps lacking timezones, altered or duplicated JSON keys, missing checksum manifest, wrong archive filename set, changed manifest digests and conflicting source-tree claims. When run in GitHub Actions, receipts now include both `github_run_id` (a decimal string) and `github_run_attempt` (a positive integer). A same-run review adds `--require-run-id ID --require-run-attempt N` to reject metadata from different Actions executions or attempts. Offline or separately triggered platform receipts may omit these flags; they cannot claim that their runs matched. It does **not** inspect or prove the existence of any ZIP/TAR.GZ bytes, the actual source content, authenticity of a host or signer, native application execution, rollback or license compliance. A malicious party can forge self-consistent unsigned claims. Output is conspicuously labeled `UNSIGNED METADATA MATRIX CONSISTENT` and `NOT ARTIFACT VERIFICATION OR RELEASE ACCEPTANCE`.

The **default** three-platform mode and single-host `--local --expected` mode have not been weakened: they still require actual physical archives and perform streaming SHA-256, ZIP/TAR file type/mode/content checks, source membership and binary/source parity. Combining `--metadata-only` with `--local` is rejected as a command-line usage error. The new mode is an intermediate administrative aid while issue #10 and native release approval remain HOLD, not an alternative exit criterion.

### One manual dispatch for three native acceptance receipts — 2026-11-11

The existing `.github/workflows/manual-quality.yml` has one additional `runner_os` choice, `all`. It uses a **dynamic GitHub Actions matrix**, expanding to one runner by default (Ubuntu, Windows or macOS) or exactly the three target native runner labels when `all` is explicitly selected. The 20-minute per-runner timeout, platform architecture guard, Python acceptance tests, CMake/CTest and complete **local** package/receipt verification remain in every native job. `fail-fast: false` ensures the other native environments continue collecting diagnostic results if one fails; it is not a pass waiver.

In all-host mode, a follow-up Ubuntu job runs **only after all three native jobs succeed**. Using the built-in `gh run download`, a read-only `GH_TOKEN`, the exact `GITHUB_RUN_ID`, commit SHA and `github.run_attempt`, it fetches the three existing **unsigned** receipt metadata artifacts into separate directories. It then runs:

```sh
python scripts/verify_receipt_matrix.py --metadata-only \
  --require-sha "$COMMIT_SHA" \
  --linux evidence/ubuntu-latest \
  --windows evidence/windows-latest \
  --macos evidence/macos-latest
```

This **does not re-verify unavailable archive bytes** and is not release certification; it checks only the internally consistent claims in unsigned JSON and SHA256SUMS. Development ZIP/TAR.GZ archives remain on their originating runners and are not uploaded; the native runner's separate `--local` check already validates them before metadata publication. The review job does not issue a license, tag, release or merge. A default one-host run skips the review job and incurs no extra Linux aggregator charge. The workflow is still manual-only and currently has **no observed run evidence for this commit**.

The workflow input can be selected in GitHub Actions once the updated file is available on the selected ref. On GitHub CLI, an owner can request `gh workflow run manual-quality.yml --ref fix/v0.8.4-save-path-resilience-20261110 -f runner_os=all -f full_linux_gate=false` (subject to GitHub's workflow dispatch and repository permission requirements). Choose `runner_os=ubuntu-latest` to minimize quota. On any failure, keep issue #10 and the release HOLD.


### Bind same-run multi-host evidence to one Actions run and attempt (2026-11-11)

`scripts/platform_acceptance.py` now records the decimal GitHub Actions run ID and positive run-attempt number alongside the exact Git SHA **only if both `GITHUB_RUN_ID` and `GITHUB_RUN_ATTEMPT` are present and strictly valid**; an ordinary offline invocation stores neither field. Partial, zero, leading-zero, nondecimal or excessively long workflow IDs cause a fail-closed error before receipt issuance. These are unsigned administrative identifiers, **not a cryptographic attestation or trust guarantee**.

`verify_receipt_matrix.py` validates that a receipt either omits both optional Actions identity fields or contains a correctly typed and formatted pair. An explicitly supplied null value does not count as omission. For a known combined three-host Actions run, the `--metadata-only --require-run-id ID --require-run-attempt N` flags require every uploaded native receipt to claim **that exact ID and attempt**. This prevents accidental mixing of successful old-run data with new-run data sharing the same Git SHA. Both flags must appear together; neither is accepted in the full local or single-host modes. The opt-in `all` GitHub workflow passes `${{ github.run_id }}` and `${{ github.run_attempt }}` explicitly. Separately executed platform evidence can still be compared without a same-run requirement, but must not be described as a same-run cohort.

No use of these fields proves that GitHub genuinely issued or signed the evidence, or that the downloaded binaries were executed. The actual required clean native builds, package bytes, license approval, signed provenance and rollback gates remain outstanding.


### v0.8.4 development-package publication (no overwrite)

The packager stages all four archives plus `SHA256SUMS` inside a private directory under the output folder on the **same filesystem**. It validates the complete set, including SHA-256 and ZIP/TAR content parity, **before** exposing any final package files. Publication uses exclusive hard links, so a stale verified package or an artifact created by a competing writer is never silently overwritten. If publication fails normally, the packager removes only its newly created links that still point to its private staged file inodes, and leaves unrelated and competing files intact.

**Limitations:** a crash/power loss between links can still leave an incomplete multi-file set, and there is no signed release or power-loss durability guarantee. The `SHA256SUMS` link is written last; consumers must always run `--verify-only` and must never treat the mere presence of files as certification. Native Windows filesystem/link semantics still require real Windows acceptance. Re-run into a **fresh output directory** instead of overwriting previously published files.
