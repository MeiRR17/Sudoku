# Generator and difficulty rubric — v0.6.0

The new C11 API `include/sudoku/generator.h` and `sudoku generate` CLI produce classic 9x9 Sudoku puzzles. The generator is fully offline, deterministic for a fixed 32-bit seed and the same options, and **never emits a puzzle without an exact one-solution proof**. A seed is required on the CLI. This is a development feature, not a production release.

## Algorithm and reproducibility

1. Create a *different complete valid grid* from a canonical Sudoku Latin-pattern solution using seeded PRNG digit permutations, band/stack permutations, rows/columns within bands/stacks, and an optional transpose. Each transformation preserves all Sudoku constraints. PRNG is defined in C11 fixed-width unsigned arithmetic and has no host-global state.
2. Seeded Fisher–Yates shuffles determine cell-removal order. With `--symmetry rotational`, removals operate on paired cells mirrored through the center, including the center cell by itself. Symmetry concerns **clue positions**, not identical clue digits.
3. Tentatively remove one or two clues. Keep the new board **only if** the exact backtracking solver proves exactly one solution before reaching its per-check node budget. A node-budget exhaustion is never accepted as proof of uniqueness.
4. Evaluate the still-unique candidate using the following **logic-based rubric**, until the specified difficulty is found or limits expire.
5. On an unsuccessful attempt, begin with another shuffled full solution. The generator never substitutes a different difficulty silently.

## Difficulty classification

The evaluator repeatedly applies *naked singles* first, then *hidden singles* in rows, columns and boxes. Both are sound human Sudoku techniques. It does **not** use clue count to assign difficulty:

| Requested level | Algorithmic certificate | Limitations |
|---|---|---|
| `easy` | Entire puzzle solvable using only naked singles | No attempt to estimate solving time |
| `medium` | Entire puzzle solvable using naked and hidden singles, **at least one** hidden single required in the deterministic technique order | Other human solving orders may differ |
| `hard` | The naked/hidden singles strategy **stalls** with remaining empties; nevertheless exact backtracking proves there is exactly one valid solution | Does **not** certify a particular advanced human technique or human difficulty |

To avoid trivial puzzles, generation also requires at most **40, 36, or 32 clues** for easy, medium and hard, respectively. This *presentation constraint* is separate from the actual difficulty category. A human rating study and broader strategy model are not yet included; these classifications should be labeled as *algorithmic proxy difficulty*.

## CLI

```sh
./build/sudoku generate --seed 42 --difficulty easy --format text
./build/sudoku generate --seed 42 --difficulty medium --symmetry rotational --format json
./build/sudoku generate --seed 42 --difficulty hard --format compact
./build/sudoku generate --seed 1770 --difficulty hard --symmetry none --max-attempts 30 --max-checks 3000 --max-nodes 50000 --max-ms 10000
./build/sudoku generate --seed 42 --difficulty easy --format json --output generated.json
```

- `--seed`: an unsigned decimal integer 0..4294967295, required. No implicit random/clock seed.
- `--difficulty`: `easy|medium|hard`, required. No silent downgrade or substitution.
- `--symmetry`: `none` (default) or `rotational` (180° clue-location symmetry).
- `--max-attempts`: 1..100, default 20 randomized complete-grid attempts.
- `--max-checks`: 1..10000, default 2000 exact uniqueness checks **total**.
- `--max-nodes`: 1..1000000, default 50000 backtracking nodes **per check**.
- `--max-ms`: 1..60000, default 5000 milliseconds of **best-effort process CPU time**, checked **between** exact solver calls, not a strict wall-time deadline. A slow node-bounded call may overrun. This is not a production-grade hard timeout.
- `--format text|compact|json` and `--output PATH` behave as in v0.4. The output file is exclusive-create and refuses overwrite. `--quiet` is deliberately not accepted for `generate`.

If any budget prevents achieving exactly the requested difficulty, the command exits **6**, writes an actionable error on stderr, and emits **no puzzle or output file**. Syntax/limit errors return 2.

## JSON contract

`--format json` is an additive **schema_version 1** success response:

```json
{"schema_version":1,"command":"generate","status":"unique","puzzle":"650070080000500047430900100005730829740020061289015400004008015920006000010040098","solution":"651473982892561347437982156165734829743829561289615473374298615928156734516347298","solutions_found":1,"seed":42,"difficulty":"easy","symmetry":"rotational","clues":39,"naked_singles":42,"hidden_singles":0,"attempts":1,"checks":22}
```

All returned boards are 81 digits. `solutions_found:1` means the solver established uniqueness, not just that one solution was found. `solution` is included for verification/programmatic consumers; a client presenting a puzzle to a player should keep the solution concealed. For failure contracts see [CLI_JSON_SCHEMA.md](CLI_JSON_SCHEMA.md).

## Limitations

- No security claims for cryptographic randomness: xorshift PRNG is **not cryptographically secure**. This is a deterministic puzzle generator, not an unpredictable secret source.
- Fixed seed/options produce the same puzzle within this implementation; algorithm/PRNG version changes might change the output in a future release. Golden fixtures detect unintended drift.
- A hard puzzle can still have a short human trick not implemented by the rubric, and a medium puzzle may feel easier or harder to different people.
- The bounded solver ensures **sound results** on success, but generous user limits may still involve nontrivial CPU usage. Hard real-time preemption is not supplied.
- Windows and macOS generator execution has not yet been verified. Production release requirements remain open.
