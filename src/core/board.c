#include "sudoku/board.h"

static void set_error(SudokuError *out, SudokuStatus status, size_t offset,
                      size_t count, unsigned row, unsigned col,
                      unsigned prev_row, unsigned prev_col, unsigned digit) {
    if (out != NULL) {
        SudokuError value = {0};
        value.status = status;
        value.byte_offset = offset;
        value.digits_seen = count;
        value.row = row;
        value.column = col;
        value.previous_row = prev_row;
        value.previous_column = prev_col;
        value.digit = digit;
        *out = value;
    }
}
static int ascii_space(unsigned char byte) {
    return byte == ' ' || byte == '\t' || byte == '\r' ||
           byte == '\n' || byte == '\v' || byte == '\f';
}

SudokuStatus sudoku_board_validate(const SudokuBoard *board, SudokuError *error) {
    /* Stored positions are index+1, where 0 means unseen. */
    unsigned rows[9][10] = {{0}}, cols[9][10] = {{0}}, boxes[9][10] = {{0}};
    size_t i;
    set_error(error, SUDOKU_OK, 0, 0, 0, 0, 0, 0, 0);
    if (board == NULL) {
        set_error(error, SUDOKU_ERR_ARGUMENT, 0, 0, 0, 0, 0, 0, 0);
        return SUDOKU_ERR_ARGUMENT;
    }
    for (i = 0; i < SUDOKU_CELL_COUNT; ++i) {
        unsigned row = (unsigned)(i / 9u), col = (unsigned)(i % 9u);
        unsigned box = (row / 3u) * 3u + col / 3u;
        unsigned digit = board->cells[i];
        unsigned previous = 0;
        SudokuStatus status = SUDOKU_OK;
        if (digit > 9u) {
            set_error(error, SUDOKU_ERR_RANGE, i, i, row + 1u, col + 1u, 0, 0, digit);
            return SUDOKU_ERR_RANGE;
        }
        if (digit == 0u) continue;
        if (rows[row][digit]) { previous = rows[row][digit] - 1u; status = SUDOKU_ERR_ROW; }
        else if (cols[col][digit]) { previous = cols[col][digit] - 1u; status = SUDOKU_ERR_COLUMN; }
        else if (boxes[box][digit]) { previous = boxes[box][digit] - 1u; status = SUDOKU_ERR_BOX; }
        if (status != SUDOKU_OK) {
            set_error(error, status, i, i, row + 1u, col + 1u,
                      previous / 9u + 1u, previous % 9u + 1u, digit);
            return status;
        }
        rows[row][digit] = (unsigned)i + 1u;
        cols[col][digit] = (unsigned)i + 1u;
        boxes[box][digit] = (unsigned)i + 1u;
    }
    return SUDOKU_OK;
}

SudokuStatus sudoku_board_parse(SudokuBoard *out, const unsigned char *bytes,
                                size_t length, SudokuError *error) {
    SudokuBoard candidate = {{0}};
    size_t i, digits = 0;
    SudokuStatus status;
    set_error(error, SUDOKU_OK, 0, 0, 0, 0, 0, 0, 0);
    if (out == NULL || bytes == NULL) {
        set_error(error, SUDOKU_ERR_ARGUMENT, 0, 0, 0, 0, 0, 0, 0);
        return SUDOKU_ERR_ARGUMENT;
    }
    if (length > SUDOKU_MAX_INPUT_BYTES) {
        set_error(error, SUDOKU_ERR_TOO_LARGE, SUDOKU_MAX_INPUT_BYTES, 0, 0, 0, 0, 0, 0);
        return SUDOKU_ERR_TOO_LARGE;
    }
    for (i = 0; i < length; ++i) {
        unsigned char ch = bytes[i];
        if (ascii_space(ch)) continue;
        if (ch < '0' || ch > '9') {
            set_error(error, SUDOKU_ERR_CHARACTER, i, digits, 0, 0, 0, 0, 0);
            return SUDOKU_ERR_CHARACTER;
        }
        if (digits == SUDOKU_CELL_COUNT) {
            set_error(error, SUDOKU_ERR_LENGTH, i, digits + 1u, 0, 0, 0, 0, 0);
            return SUDOKU_ERR_LENGTH;
        }
        candidate.cells[digits++] = (uint8_t)(ch - '0');
    }
    if (digits != SUDOKU_CELL_COUNT) {
        set_error(error, SUDOKU_ERR_LENGTH, length, digits, 0, 0, 0, 0, 0);
        return SUDOKU_ERR_LENGTH;
    }
    status = sudoku_board_validate(&candidate, error);
    if (status == SUDOKU_OK) *out = candidate;
    return status;
}

void sudoku_board_compact(const SudokuBoard *board, char out[82]) {
    size_t i;
    if (board == NULL || out == NULL) return;
    for (i = 0; i < SUDOKU_CELL_COUNT; ++i) {
        unsigned value = board->cells[i];
        out[i] = value <= 9u ? (char)('0' + value) : '?';
    }
    out[SUDOKU_CELL_COUNT] = '\0';
}

const char *sudoku_status_text(SudokuStatus status) {
    switch (status) {
    case SUDOKU_OK: return "valid";
    case SUDOKU_ERR_ARGUMENT: return "invalid argument";
    case SUDOKU_ERR_LENGTH: return "expected exactly 81 digits";
    case SUDOKU_ERR_CHARACTER: return "non-digit character in input";
    case SUDOKU_ERR_RANGE: return "board digit outside 0..9";
    case SUDOKU_ERR_ROW: return "duplicate given in row";
    case SUDOKU_ERR_COLUMN: return "duplicate given in column";
    case SUDOKU_ERR_BOX: return "duplicate given in 3x3 box";
    case SUDOKU_ERR_TOO_LARGE: return "input exceeds 1 MiB limit";
    default: return "unknown validation status";
    }
}
