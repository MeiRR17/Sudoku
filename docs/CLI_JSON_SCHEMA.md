# Sudoku JSON CLI Contract — schema_version 1

Introduced in Sudoku **v0.4.0**. Intended for use by shell scripts and external tools; changes incompatible with this contract require a new `schema_version` or major release policy decision.

## Invocation

```sh
sudoku solve --file tests/fixtures/unique.txt --format json
sudoku count --stdin --format json < tests/fixtures/unique.txt
sudoku validate --puzzle 530070000600195000098000060800060003400803001700020006060000280000419005000080079 --format json
sudoku solve --file tests/fixtures/unique.txt --format json --output solution.json
```

One JSON object on one line, with a trailing newline, is printed on **stdout** (or saved to `--output` on success). Object keys are stable but consumers should not rely on key order. No BOM. Input puzzle and solution use 81 ASCII digits, with `0` for unfilled positions (solutions contain only 1–9). Numbers are JSON integers, booleans are JSON booleans; absent properties are intentionally omitted, not null.

**Successful `validate`:**

```json
{"schema_version":1,"command":"validate","status":"valid","puzzle":"530070000600195000098000060800060003400803001700020006060000280000419005000080079"}
```

`validate` checks only row/column/box contradictions. It does **not** establish that a puzzle has a solution.

**Successful `solve` (unique):**

```json
{"schema_version":1,"command":"solve","status":"unique","puzzle":"530070000600195000098000060800060003400803001700020006060000280000419005000080079","solution":"534678912672195348198342567859761423426853791713924856961537284287419635345286179","solutions_found":1}
```

`solve.status` is `unique` or `multiple`. On multiple solutions, `solution` is a **deterministic first solution**, `solutions_found` is `2` (the solver stops at two), and a warning appears on stderr unless `--quiet`. The result still exits 0 because a valid first solution was produced.

**Successful `count` (zero, unique, multiple):**

```json
{"schema_version":1,"command":"count","status":"none","puzzle":"531070000600195000098000060800060003400803001700020006060000280000419005000080079","solutions_found":0,"capped":false}
```

`count.status` is exactly one of `none`, `unique`, `multiple`; `solutions_found` is 0, 1 or 2. `capped` is true **only** when 2+ solutions were found: `solutions_found=2` means *at least two*, not precisely two. An unsolvable yet well-formed puzzle is a successful classification and `count` returns exit 0.

## Failure contract and exit codes

Errors are **not** JSON documents in v1: failures produce no JSON/standard-output payload. An actionable UTF-8-compatible diagnostic is written to **stderr**, and the exit code is nonzero. For a failed command `--output` is never created.

| Exit | Meaning | Typical example |
|---|---|---|
| 0 | successful validate/solve/count | `count` found 0 or 2+ solutions |
| 2 | CLI usage error | invalid command, option, format or conflicting sources |
| 3 | malformed or contradictory puzzle | wrong length, forbidden byte, duplicate clue, >1 MiB input |
| 4 | input/output I/O or internal solver error | cannot read input, output exists, cannot write result |
| 5 | `solve` of a well-formed but unsatisfiable puzzle | no solution; no output generated |

`--output PATH` creates a **new** result file only after successful parsing and solving. Existing paths and symlinks are not overwritten. `--output -` selects stdout. The file is removed if a newly created output file encounters a detected write/close failure. This is **not** a transactional/atomic file replacement protocol; a crash/power loss during output may leave partial data. No `--force` flag is implemented. Input may be selected via `--puzzle`, `--file PATH` (including `--file -`), or `--stdin` (exactly one source).

`--format compact` retains the preexisting output convention: one 81-digit board (validate/solve), or `0`, `1`, `2+` for count. `--format text` is intended for people; it is not a machine-readable contract.

## Compatibility and testing

- The contract is independent of local file-path syntax, native line endings and shell implementation. Paths are passed as a single CLI argument.
- `tests/cli_golden.py` checks byte-accurate JSON, schema semantics, stderr separation, exit codes, binary/oversized input, CRLF, stdin, output refusal and safe preservation of existing files.
- The CTest golden test is enabled when Python 3 is installed; core CTest checks remain available without Python.
- Compiler testing performed on Linux with Clang 17 (Release) and GCC 14 (ASan/UBSan). Windows and macOS **have not yet been validated**; platform-specific release support is planned for v0.8.0.


## v0.6.0 additive `generate` response

`generate` accepts required `--seed UINT32 --difficulty easy|medium|hard`, optional `--symmetry none|rotational` and resource budgets, instead of an input board. It introduces the following additive JSON **schema_version 1** success payload (key order is stable but consumers must not rely on it):

```json
{"schema_version":1,"command":"generate","status":"unique","puzzle":"650070080000500047430900100005730829740020061289015400004008015920006000010040098","solution":"651473982892561347437982156165734829743829561289615473374298615928156734516347298","solutions_found":1,"seed":42,"difficulty":"easy","symmetry":"rotational","clues":39,"naked_singles":42,"hidden_singles":0,"attempts":1,"checks":22}
```

The response is returned **only** after exact uniqueness verification. `solution` is present for external verification but should be concealed in player-facing interfaces. Difficulty is a deterministic, narrow naked/hidden singles rubric (see [GENERATION_AND_DIFFICULTY.md](GENERATION_AND_DIFFICULTY.md)), not a measured human solving-time rating. Budget exhaustion has **exit code 6**, stderr diagnostic, no stdout and no created output file. Limits are documented in the generator specification. No changes are made to existing command schemas.
