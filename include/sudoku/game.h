#ifndef SUDOKU_GAME_H
#define SUDOKU_GAME_H
#include "sudoku/board.h"
#include <stdint.h>
#include <time.h>

#define SUDOKU_GAME_HISTORY 128u
#define SUDOKU_SAVE_MAX_BYTES 1024u
#define SUDOKU_MAX_ELAPSED_SECONDS UINT64_C(315360000)

typedef enum SudokuGameStatus {
    SUDOKU_GAME_OK = 0, SUDOKU_GAME_INVALID, SUDOKU_GAME_UNSOLVABLE,
    SUDOKU_GAME_MULTIPLE, SUDOKU_GAME_GIVEN, SUDOKU_GAME_CONFLICT,
    SUDOKU_GAME_RANGE, SUDOKU_GAME_NOT_EMPTY, SUDOKU_GAME_NO_HISTORY,
    SUDOKU_GAME_CORRUPT, SUDOKU_GAME_IO,
    SUDOKU_GAME_DURABILITY_UNCERTAIN
} SudokuGameStatus;

typedef struct SudokuGameSnapshot {
    SudokuBoard board;
    uint16_t notes[SUDOKU_CELL_COUNT];
} SudokuGameSnapshot;

typedef struct SudokuGame {
    SudokuBoard givens;
    SudokuBoard solution;
    SudokuGameSnapshot state;
    SudokuGameSnapshot history[SUDOKU_GAME_HISTORY];
    unsigned history_len;
    unsigned history_cursor;
    uint64_t elapsed_base;
    time_t session_start;
} SudokuGame;

/* Unique-solution puzzles only; transactional on error. */
SudokuGameStatus sudoku_game_start(SudokuGame *game, const SudokuBoard *givens);
/* Direct placement, erase, pencil-note and bulk edit operations validate
 * the live board and original clues before committing a snapshot. Rejected
 * edits do not change state or Undo/Redo; observational candidate lookup
 * deliberately accepts independently valid boards. */
SudokuGameStatus sudoku_game_set(SudokuGame *game, unsigned row, unsigned col, unsigned digit);
/* Apply 0..81 distinct placements as one atomic, undoable edit.
 * Every target must be an empty non-given cell; malformed/duplicate/conflicting
 * batches fail without changing state or history. A zero count is a no-op.
 * Does NOT consult the cached solution; callers decide which moves to propose.
 * When provided, applied is set to the number of committed placements. */
typedef struct SudokuGameMove {
    unsigned row, col, digit;
} SudokuGameMove;
SudokuGameStatus sudoku_game_set_many(SudokuGame *game,
                                      const SudokuGameMove *moves,
                                      unsigned count, unsigned *applied);
SudokuGameStatus sudoku_game_erase(SudokuGame *game, unsigned row, unsigned col);
SudokuGameStatus sudoku_game_note(SudokuGame *game, unsigned row, unsigned col, unsigned digit);
/* 1 << digit bitmask (digits 1..9), based only on the current board.
 * Returns 0 on invalid arguments or a filled cell. Observational. */
uint16_t sudoku_game_candidates(const SudokuGame *game, unsigned row, unsigned col);
/* Fill candidate notes on all empty editable cells in one undoable step.
 * Replaces existing pencil notes; repeated unchanged action is a no-op. */
SudokuGameStatus sudoku_game_auto_notes(SudokuGame *game);
/* Remove pencil notes that conflict with the current board, but never add
 * missing marks. One undoable state change, or no history change if unchanged. */
SudokuGameStatus sudoku_game_prune_notes(SudokuGame *game);
/* Clear selected existing pencil-mark bits from each of 81 cells, never
 * placing digits or changing the immutable clues. Validate every requested
 * mask and target before changing any notes. Count removed pencil digits,
 * not cells; one history snapshot only if at least one bit was removed.
 * A no-op leaves both Undo and Redo history intact. The caller must derive
 * logical eliminations; this API does not consult the solved board. */
SudokuGameStatus sudoku_game_eliminate_notes(
    SudokuGame *game, const uint16_t masks[SUDOKU_CELL_COUNT], unsigned *removed);
/* Clear every pencil note as one undoable edit; empty note sets are a no-op. */
SudokuGameStatus sudoku_game_clear_notes(SudokuGame *game);
/* Remove all incorrect entered digits in one undoable move; never insert
 * solution digits or modify immutable clues. No-op if there are no mistakes.
 * Returns INVALID without mutation for inconsistent public game structs. */
SudokuGameStatus sudoku_game_clear_mistakes(SudokuGame *game);
/* Move 1..127 existing history steps atomically. If fewer steps are
 * available, return NO_HISTORY without modifying board, notes or cursor.
 * No new history entries are created; zero/out-of-range counts are RANGE. */
SudokuGameStatus sudoku_game_undo_steps(SudokuGame *game, unsigned steps);
SudokuGameStatus sudoku_game_redo_steps(SudokuGame *game, unsigned steps);
SudokuGameStatus sudoku_game_undo(SudokuGame *game);
SudokuGameStatus sudoku_game_redo(SudokuGame *game);
/* Restore immutable clues and clear editable digits/notes in one Undo step.
 * No-op when already reset. Reject invalid public givens/current boards or
 * altered clue cells without mutating state or history. */
SudokuGameStatus sudoku_game_reset(SudokuGame *game);
unsigned sudoku_game_empty(const SudokuGame *game);
unsigned sudoku_game_mistakes(const SudokuGame *game);
int sudoku_game_won(const SudokuGame *game);
uint64_t sudoku_game_elapsed(const SudokuGame *game);
const char *sudoku_game_status_text(SudokuGameStatus status);

/* Versioned checksummed ASCII save, same-directory staging and rename.
 * On POSIX, both file contents and parent-directory metadata are fsynced.
 * On DURABILITY_UNCERTAIN the rename DID succeed but the subsequent parent
 * directory fsync failed: check the target; no power-loss promise is made.
 * The caller-owned game is never changed by saving. Undo history is not saved.
 * Windows uses _commit and MoveFileExA(WRITE_THROUGH), still unverified. */
SudokuGameStatus sudoku_game_save(const SudokuGame *game, const char *path);
SudokuGameStatus sudoku_game_load(SudokuGame *game, const char *path);
#endif
