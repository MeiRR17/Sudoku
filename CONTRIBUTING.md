# Contributing to Sudoku

Development target: portable C11 engine, predictable offline CLI and verifiable releases. This is an experimental repository; production acceptance criteria are in [ROADMAP.md](ROADMAP.md) and [docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md).

1. Open an issue before a behavior-changing contribution. Identify which numbered release gate the change implements. Keep the historical `Learning_Modules` copy untouched.
2. Make focused changes on a branch from `master`; avoid changing unrelated files.
3. Compile with strict C11 warnings-as-errors and run `python3 scripts/quality_gate.py --mode fast` (cross-platform). For core/CLI changes on Linux, run `python3 scripts/quality_gate.py --mode full (includes `python3 scripts/static_analysis.py`, which fails on any compiler diagnostic)` (GCC/Clang, ASan/UBSan, >=90% core coverage, benchmarks).
4. If the parser or solver changes, expand the deterministic property tests in `tests/test_properties.c`, independent oracle in `tests/test_solver.c`, and fuzz corpora/harnesses where relevant. Do not change expected solution classifications without explaining why.
5. Document CLI JSON changes in [docs/CLI_JSON_SCHEMA.md](docs/CLI_JSON_SCHEMA.md). A breaking schema change requires a versioning decision. Maintain stdout/stderr discipline and exit statuses.
6. Submit a PR with a concise change summary, risk assessment, exact platform/compiler/test evidence and any known limitations. Merge only after the relevant acceptance checks pass.

The CI workflow is **manual-only** and does not automatically consume GitHub Actions minutes. Use `Actions > Sudoku manual quality gate > Run workflow`; the selected OS is tested only after someone triggers it. A local pass does not substitute for Windows/macOS verification.

No license has been selected. Copyright and reuse rights must be clarified before accepting outside contributions. Do not submit secrets, personal data, or unlicensed third-party code.
