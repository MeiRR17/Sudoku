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
SudokuGameStatus sudoku_game_set(SudokuGame *game, unsigned row, unsigned col, unsigned digit);
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
/* Clear every pencil note as one undoable edit; empty note sets are a no-op. */
SudokuGameStatus sudoku_game_clear_notes(SudokuGame *game);
/* Remove all incorrect entered digits in one undoable move; never insert
 * solution digits or modify immutable clues. No-op if there are no mistakes.
 * Returns INVALID without mutation for inconsistent public game structs. */
SudokuGameStatus sudoku_game_clear_mistakes(SudokuGame *game);
SudokuGameStatus sudoku_game_undo(SudokuGame *game);
SudokuGameStatus sudoku_game_redo(SudokuGame *game);
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
