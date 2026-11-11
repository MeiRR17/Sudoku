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
| `erase ROW COL` | Clear the placed digit **and all pencil notes** from an editable cell. Erasing a blank cell with notes is undoable; repeating erase on a blank note-free cell is a no-op. |
| `note ROW COL DIGIT` | Toggle a pencil note 1–9 on an empty editable cell. |
| `notes ROW COL` | List the pencil notes for one cell. |
| `candidates ROW COL` | Show digits currently legal under Sudoku row/column/box rules in an **empty** cell, without consulting the hidden solution or changing notes/history. A filled cell reports its current digit. |
| `hint` | Preview the first naked or hidden single without changing the board, notes, save destination or undo/redo. Takes no arguments. |
| `hint apply` | Explicitly place **one** such logical single through the normal, undoable move API. Does not act if the game has incorrect player entries, no simple hint exists or the game is solved. No implicit save. |
| `auto-notes` | Replace pencil marks on every empty editable cell with all currently legal candidate digits, using one undoable action. Does not place digits, change givens or reveal the stored solution; repeating it without board changes is a no-op. Takes no arguments. |
| `prune-notes` | Remove only pencil marks now ruled out by the live grid; preserve legal manual marks without auto-adding missing candidates. One undoable operation if notes change, otherwise a no-op. Takes no arguments. |
| `clear-notes` | Remove all pencil notes from the whole board as **one undoable action**, retaining every placed digit. If no notes remain, no history entry is created. Takes no arguments. |
| `undo`, `redo` | Revert or replay a placement, erasure, note or reset. New edits discard the redo branch. |
| `reset` | Restore original givens and clear notes. Can be undone while history remains. |
| `check` | Count empty and incorrect cells without printing the answer. |
| `status` | Filled cells, incorrect entries, time spent, available undo and redo steps. |
| `save [PATH]` | Persist state to a supplied path or the previous `--save`/`--resume` path. The rest of the command line is interpreted as a filename, so spaces work; optional surrounding double quotes are removed. Empty quoted filenames, unmatched opening quotes, and any stray or nested `"` characters are rejected without creating or overwriting save files. Literal double quotes in save filenames are unsupported. |
| `quit` / `exit` | Leave without an implicit save. |
| `help` | Show the interactive command summary. |

The game uses 1-based row/column coordinates. The givens are immutable. `hint` offers a limited logical deduction rather than looking up the stored solution: it searches single-candidate cells in row-major order, then scans row, column and box constraints for a single place to put a digit. It prints the chosen row/column, digit and reason, but does not insert that digit or edit any pencil marks. Use `hint apply` to place the first offered deduction as one undoable move; unlike preview, this explicit mode checks the game's known mistake count against its verified solution and refuses to act until incorrect entries are fixed. It never auto-saves, and a single invocation never fills multiple cells. If no simple deduction is available, it reports this honestly rather than guessing; a fully completed board reports that no hint is needed. Wrong nonconflicting user entries can make a logical deduction misleading, so hints are about **current Sudoku constraints**, not a guaranteed correct answer. Invalid `hint` arguments other than the single literal `apply` are rejected without altering game state. `candidates` calculates currently legal values from the **live board**, not the puzzle's verified solution; therefore it cannot spoil the answer and can list multiple options. Its output is read-only and does not depend on pencil notes, create an undo state, clear redo or modify a save. For example, with the standard sample puzzle, `candidates 1 3` prints `Candidates for row 1 col 3: 1 2 4`; `candidates 1 1` reports that the original clue is already filled. Invalid coordinates, a third argument or a missing coordinate are rejected. Pencil notes are intentionally independent of the authoritative engine candidates: they are personal annotations, not automatic hints. Manual `note` continues to toggle any 1–9 pencil mark; `auto-notes` is an explicitly requested bulk replacement of those personal marks with legal row/column/box candidates for the *current* filled grid. It uses the shared `sudoku_game_candidates` engine function, not the stored solved grid, and writes one history snapshot only when at least one note changes. A subsequent `undo` restores the player's previous manual notes, `redo` restores the generated notes, and `save` persists the generated masks in the existing version-1 save format. Auto-notes does not automatically recalculate after every future move: run it again to refresh candidates. Alternatively, run `prune-notes` after filling cells to discard **only** newly illegal pencil marks, preserving the player's selected subset of still-legal candidates. Pruning is an explicit one-step undoable edit when it changes anything; repeating it unchanged is history-neutral. Neither command consults the stored completed solution. The player may enter an incorrect digit as long as it does not directly violate row, column or box constraints; `check` compares it with the **verified unique solution**. Completion is detected only when the board matches all 81 digits of that solution, not merely when all cells are nonempty.

Erasing an editable cell now clears **both** any placed digit and its note mask. This fixes the former no-op behavior when an empty cell still contained pencil marks, without adding a second command: `undo` restores the erased notes, `redo` clears them again, and no history step is created if there was nothing to erase. Given cells remain immutable.

Undo/redo in memory is bounded to the most recent **127 state transitions** (128 snapshots, one base state). Each snapshot contains board and notes; reset is a single undoable step **only when the board or notes actually change**. Repeating reset on an already-cleared board creates no new undo/redo history. A freshly loaded game resumes the current board and notes with a **new undo history**; previous history is intentionally not serialized. Timer tracks active session wall-clock seconds and persists elapsed seconds on save. Time while the program is closed does **not** count; clock changes may affect elapsed seconds.

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

1. Before rendering, validate the caller-owned `SudokuGame` state: both boards must obey Sudoku rules; the original givens must **still have exactly one solution** matching the cached solved board; all givens must remain unchanged; no filled cell may retain notes; and note masks must be legal. This repeat-solve verification occurs on explicit save, including for consumers that mutate the public C struct directly. This guards clients of the public C API that modify the exposed struct without using safe mutators. Invalid state is rejected *without creating any temporary file or replacing an earlier valid save*. Then render the canonical, checksummed record in memory.
2. Create a fresh, exclusive temporary file **in the same directory** as the destination. POSIX now uses `mkstemp` with a same-directory `.tmp.XXXXXX` suffix, creating an exclusive owner-only (0600) stage without a process-global serial, followed by `fdopen`, which makes the temporary file private **from birth**, including with a permissive `umask(000)`; a defensive `fchmod(0600)` also runs before writing any save bytes. Windows uses exclusive `fopen(..., "wbx")` with an atomic per-process `InterlockedIncrement` serial and process ID in the staging name; native Windows validation is still required. Failed `fchmod` or `fdopen` aborts and cleans up without replacing the old target. An atomic rename installs the new file's permissions, so the POSIX replacement remains private.
3. Write the entire record, `fflush`, `fsync` (POSIX) or `_commit` (Windows), then verify `fclose` succeeded.
4. Replace the target with same-filesystem `rename` (POSIX) or `MoveFileExA` with replacement/write-through (Windows). If file write, file sync or rename fails, the temporary file is deleted and the previous target remains unchanged.
5. **POSIX only:** open the containing directory and call `fsync` on the directory file descriptor, then check `close`. This requests persistence of the rename's directory metadata. The destination is never changed again after this step.

If directory `fsync` fails **after a successful rename**, the game returns a distinct `SUDOKU_GAME_DURABILITY_UNCERTAIN` status. In v0.8.4 the terminal also retains an explicitly supplied save destination as the default for a later bare `save`, because the rename already succeeded. The terminal prints a warning that the **target was already replaced but survival of sudden power loss cannot be promised**; this is not a pre-rename failure and does not claim the previous file survived. The newly written save can normally be loaded immediately; this still does not establish durability after a hardware failure.

An unexpected crash before rename can leave an orphaned temporary file; the old save remains intact, provided the filesystem honors same-directory rename semantics. A power loss at any phase, especially on a filesystem without reliable `fsync`/write barriers, may lose the latest version, so **durability is not formally guaranteed**. Windows uses `_commit` and `MoveFileExA(...WRITE_THROUGH)` but has not been verified on a native Windows runner. POSIX directory `fsync` is a best-effort metadata durability step, not a portable hardware guarantee. This is distinct from the other CLI commands' exclusive-create `--output`, which intentionally refuses overwrite. Do not manually rename a `.tmp.*` file to `.save`; recover from an earlier verified save instead. Tests simulate an orphan and verify that it cannot silently replace the verified save.

**Security scope:** Local paths are user-selected, so only save to trusted directories. Game files are not authenticated or encrypted. Save file corruption must never crash the program or cause a partially validated state to be accepted; test cases exercise wrong checksum, truncated file, and oversized input.

## Exit codes and limitations

`0` successful session/quit; `2` incorrect CLI options; `3` invalid/non-unique/unsatisfiable puzzle or corrupt save; `4` I/O failure; `6` generator budget exhaustion. Errors while using an interactive command are shown in-session, allowing correction and continuation. **Interactive save errors do not terminate the running game**; always confirm a successful `Saved to ...` message before quitting. The program is intentionally non-graphical, not a full-screen TUI.

Windows/macOS native builds and atomic replace behavior have **not** been tested yet. The manual CI workflow is available but no hosted run is claimed. Cross-platform release verification remains required for v0.8.0.


### v0.8.4 — POSIX concurrent staging filenames

The previous game save writer derived the temporary filename from `time(NULL)` and a mutable `static unsigned serial`. That made names predictable and introduced a data race if multiple threads invoked the public API concurrently. On POSIX, `sudoku_game_save` now uses `mkstemp("...tmp.XXXXXX")` to atomically create an exclusive, unpredictable, owner-only staging inode alongside the destination. The existing defensive `fchmod(0600)`, file `fflush/fsync`, same-directory `rename` and containing-directory `fsync` remain unchanged. A stage-creation failure returns `SUDOKU_GAME_IO` without replacing an earlier save. The Windows `fopen("wbx")` branch has now also been hardened with an atomic `InterlockedIncrement` counter and process ID in staging names; its native multi-thread behavior remains unverified until the Windows CTest gate executes.

The Linux `tests/fault_inject.c` interposer now supports `SUDOKU_TEST_FAULT=stage-create`; `tests/save_faults.py` checks that the previous save survives the injected failure and that no temporary file remains. This full fault-injection CTest still requires an actual Sudoku binary and has not been run in this cycle.


### v0.8.4 — Windows concurrent save staging

The Windows implementation retains exclusive `fopen("wbx")` creation and atomic `MoveFileExA` replacement, but replaces the shared non-atomic `static unsigned serial` with a `volatile LONG` incremented using Win32 `InterlockedIncrement`. Staging paths include `time(NULL)`, `GetCurrentProcessId()`, and the incremented serial. These changes reduce process and thread collisions without modifying the v1 save-file format, overwrite contract or failure cleanup. The exclusive-open `x` mode is still the final collision guard. They do **not** establish Windows file-ACL equivalence with POSIX 0600 or durable power-loss semantics.

A native Windows-only CTest (`sudoku_windows_save_concurrency`) starts 12 threads that concurrently attempt eight writes each to one solved game destination. Some transient `SUDOKU_GAME_IO` outcomes during competing replacement attempts are allowed; the suite must observe at least one successful save, zero unexpected result codes, a final valid solved game on reload and no leftover `*.tmp.*` staging files. It runs only on Windows, not in Linux CTest. Native Windows/MSVC execution is **still pending**.
