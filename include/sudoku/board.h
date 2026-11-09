#ifndef SUDOKU_BOARD_H
#define SUDOKU_BOARD_H
#include <stddef.h>
#include <stdint.h>

#define SUDOKU_SIDE 9u
#define SUDOKU_CELL_COUNT 81u
#define SUDOKU_MAX_INPUT_BYTES (1024u * 1024u)

/* Bounded value-based board. Values: 0 empty, 1..9 filled.
 * The engine does not mutate givens. Games will track clue positions separately. */
typedef struct SudokuBoard { uint8_t cells[SUDOKU_CELL_COUNT]; } SudokuBoard;

typedef enum SudokuStatus {
    SUDOKU_OK = 0, SUDOKU_ERR_ARGUMENT, SUDOKU_ERR_LENGTH,
    SUDOKU_ERR_CHARACTER, SUDOKU_ERR_RANGE, SUDOKU_ERR_ROW,
    SUDOKU_ERR_COLUMN, SUDOKU_ERR_BOX, SUDOKU_ERR_TOO_LARGE
} SudokuStatus;

/* 1-based coordinates; byte_offset is 0-based; unused fields are zero. */
typedef struct SudokuError {
    SudokuStatus status;
    size_t byte_offset, digits_seen;
    unsigned row, column, previous_row, previous_column, digit;
} SudokuError;

/* Exactly 81 ASCII digits 0..9; ASCII whitespace may separate digits.
 * Non-ASCII, NUL and oversized input are invalid. The input is byte-counted,
 * not required to be NUL-terminated. On failure, *out is unchanged. */
SudokuStatus sudoku_board_parse(SudokuBoard *out, const unsigned char *bytes,
                                size_t length, SudokuError *error);
SudokuStatus sudoku_board_validate(const SudokuBoard *board, SudokuError *error);
/* out must have room for 82 bytes; a NULL argument is ignored. */
void sudoku_board_compact(const SudokuBoard *board, char out[82]);
const char *sudoku_status_text(SudokuStatus status);
#endif
