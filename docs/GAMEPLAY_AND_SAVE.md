# v0.7.0 interactive terminal gameplay and save contract

Sudoku `play` is a local, plain-text terminal interface. It never makes network requests, requires no ANSI color, and can read scripted commands from stdin. A playable puzzle must have **exactly one solution**; invalid, unsatisfiable and non-unique puzzles are rejected before the session starts.

## Start a game

```sh
./build/sudoku play --file tests/fixtures/unique.txt
./build/sudoku play --puzzle 034678912672195348198342567859761423426853791713924856961537284287419635345286179
./build/sudoku play --seed 42 --difficulty easy --symmetry rotational --save my-game.save
./build/sudoku play --resume my-game.save
./build/sudoku play --help
```

The `--file` argument reads a puzzle file (max 1 MiB), not a saved game. `--resume` reads only versioned Sudoku game saves. For an interactive game, puzzle input through stdin is not supported because stdin is reserved for player commands. A generated game requires both `--seed` and `--difficulty`; `--symmetry` applies only to generated games. There is no network dependency.

## Interactive commands

| Command | Behavior |
|---|---|
| `show` | Print the complete board and progress. Zero cells appear as `.`. |
| `set ROW COL DIGIT` | Fill an editable cell, coordinates and digit 1–9. Sudoku rule conflicts are rejected. |
| `erase ROW COL` | Erase an editable cell. |
| `note ROW COL DIGIT` | Toggle a pencil note 1–9 on an empty editable cell. |
| `notes ROW COL` | List the pencil notes for one cell. |
| `undo`, `redo` | Revert or replay a placement, erasure, note or reset. New edits discard the redo branch. |
| `reset` | Restore original givens and clear notes. Can be undone while history remains. |
| `check` | Count empty and incorrect cells without printing the answer. |
| `status` | Filled cells, incorrect entries, time spent, available undo and redo steps. |
| `save [PATH]` | Persist state to a supplied path or the previous `--save`/`--resume` path. The rest of the command line is interpreted as a filename, so spaces work; optional surrounding double quotes are removed. Empty quoted filenames, unmatched opening quotes, and any stray or nested `"` characters are rejected without creating or overwriting save files. Literal double quotes in save filenames are unsupported. |
| `quit` / `exit` | Leave without an implicit save. |
| `help` | Show the interactive command summary. |

The game uses 1-based row/column coordinates. The givens are immutable. Pencil notes are intentionally independent of the authoritative engine candidates: they are personal annotations, not automatic hints. The player may enter an incorrect digit as long as it does not directly violate row, column or box constraints; `check` compares it with the **verified unique solution**. Completion is detected only when the board matches all 81 digits of that solution, not merely when all cells are nonempty.

Undo/redo in memory is bounded to the most recent **127 state transitions** (128 snapshots, one base state). Each snapshot contains board and notes; reset is a single undoable step. A freshly loaded game resumes the current board and notes with a **new undo history**; previous history is intentionally not serialized. Timer tracks active session wall-clock seconds and persists elapsed seconds on save. Time while the program is closed does **not** count; clock changes may affect elapsed seconds.

## Save file format: `SUDOKU_SAVE_V1`

A strictly parsed UTF-8-compatible **ASCII** document (maximum 1,024 bytes), with exactly these six lines and a final LF:

```text
SUDOKU_SAVE_V1
G=<exactly 81 ASCII digits, original givens>
B=<exactly 81 ASCII digits, current board>
N=<exactly 243 uppercase hex digits, 3 hex digits per 9-bit note mask>
E=<canonical decimal elapsed seconds, 0..315360000; no leading zeroes except exactly 0>
C=<16 uppercase hexadecimal digits: FNV-1a 64 of all bytes preceding the C line>
```

Each note mask uses only digit bits 1–9 (`0x000`–`0x3FE`); bit zero must be clear. Original clues and filled cells must not have notes. The current board must be Sudoku-rule-consistent and must preserve all givens. The original puzzle must have a unique exact solution. **The checksum detects accidental truncation or corruption; it is not cryptographic authentication** and does not defend against deliberate malicious modification. The parser rejects any extra or missing byte, invalid checksum, illegal note bit, contradictory number or altered original clue. It also rejects noncanonical elapsed-time decimal encodings such as `E=00` or `E=0012`, **even with an otherwise valid checksum**. The elapsed-time getter clamps unexpected out-of-range public structure values to the documented 315360000-second bound. Failed loading leaves any caller-owned game unchanged. There is no compatibility promise for unknown future save versions.

### Atomic save strategy

1. Render an entire canonical, checksummed save in memory before writing.
2. Create a fresh, exclusive temporary file **in the same directory** as the destination. POSIX uses `open(..., O_WRONLY | O_CREAT | O_EXCL, 0600)` followed by `fdopen`, which makes the temporary file private **from birth**, including with a permissive `umask(000)`; a defensive `fchmod(0600)` also runs before writing any save bytes. Windows retains exclusive `fopen(..., "wbx")` until native Windows validation is completed. Failed `fchmod` or `fdopen` aborts and cleans up without replacing the old target. An atomic rename installs the new file's permissions, so the POSIX replacement remains private.
3. Write the entire record, `fflush`, `fsync` (POSIX) or `_commit` (Windows), then verify `fclose` succeeded.
4. Replace the target with same-filesystem `rename` (POSIX) or `MoveFileExA` with replacement/write-through (Windows). If file write, file sync or rename fails, the temporary file is deleted and the previous target remains unchanged.
5. **POSIX only:** open the containing directory and call `fsync` on the directory file descriptor, then check `close`. This requests persistence of the rename's directory metadata. The destination is never changed again after this step.

If directory `fsync` fails **after a successful rename**, the game returns a distinct `SUDOKU_GAME_DURABILITY_UNCERTAIN` status. In v0.8.4 the terminal also retains an explicitly supplied save destination as the default for a later bare `save`, because the rename already succeeded. The terminal prints a warning that the **target was already replaced but survival of sudden power loss cannot be promised**; this is not a pre-rename failure and does not claim the previous file survived. The newly written save can normally be loaded immediately; this still does not establish durability after a hardware failure.

An unexpected crash before rename can leave an orphaned temporary file; the old save remains intact, provided the filesystem honors same-directory rename semantics. A power loss at any phase, especially on a filesystem without reliable `fsync`/write barriers, may lose the latest version, so **durability is not formally guaranteed**. Windows uses `_commit` and `MoveFileExA(...WRITE_THROUGH)` but has not been verified on a native Windows runner. POSIX directory `fsync` is a best-effort metadata durability step, not a portable hardware guarantee. This is distinct from the other CLI commands' exclusive-create `--output`, which intentionally refuses overwrite. Do not manually rename a `.tmp.*` file to `.save`; recover from an earlier verified save instead. Tests simulate an orphan and verify that it cannot silently replace the verified save.

**Security scope:** Local paths are user-selected, so only save to trusted directories. Game files are not authenticated or encrypted. Save file corruption must never crash the program or cause a partially validated state to be accepted; test cases exercise wrong checksum, truncated file, and oversized input.

## Exit codes and limitations

`0` successful session/quit; `2` incorrect CLI options; `3` invalid/non-unique/unsatisfiable puzzle or corrupt save; `4` I/O failure; `6` generator budget exhaustion. Errors while using an interactive command are shown in-session, allowing correction and continuation. **Interactive save errors do not terminate the running game**; always confirm a successful `Saved to ...` message before quitting. The program is intentionally non-graphical, not a full-screen TUI.

Windows/macOS native builds and atomic replace behavior have **not** been tested yet. The manual CI workflow is available but no hosted run is claimed. Cross-platform release verification remains required for v0.8.0.
