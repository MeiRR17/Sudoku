#include "sudoku/board.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(expr) do { if (!(expr)) { fprintf(stderr, "FAIL %s:%d %s\n", __FILE__, __LINE__, #expr); return 1; } } while (0)

static const char sample[] =
    "300000020080432010050000600074860000000000008"
    "030100700000296871600000340190700006";

static int test_all(void) {
    SudokuBoard board = {{0}}, saved = {{0}};
    SudokuError error;
    char text[82];
    unsigned char spaced[100], invalid[81], extra[82];
    unsigned char *large;
    size_t i, n = 0;
    CHECK(strlen(sample) == 81);
    CHECK(sudoku_board_parse(&board, (const unsigned char *)sample, 81, &error) == SUDOKU_OK);
    CHECK(error.status == SUDOKU_OK);
    CHECK(board.cells[0] == 3 && board.cells[7] == 2 && board.cells[80] == 6);
    sudoku_board_compact(&board, text);
    CHECK(strcmp(text, sample) == 0);
    CHECK(sudoku_board_validate(&board, &error) == SUDOKU_OK);
    CHECK(sudoku_board_parse(NULL, (const unsigned char *)sample, 81, &error) == SUDOKU_ERR_ARGUMENT);
    CHECK(sudoku_board_parse(&board, NULL, 1, &error) == SUDOKU_ERR_ARGUMENT);
    CHECK(sudoku_board_validate(NULL, &error) == SUDOKU_ERR_ARGUMENT);

    for (i = 0; i < 81; ++i) {
        spaced[n++] = (unsigned char)sample[i];
        if (i % 9u == 8u) spaced[n++] = '\n';
    }
    CHECK(sudoku_board_parse(&board, spaced, n, &error) == SUDOKU_OK);
    CHECK(sudoku_board_parse(&board, (const unsigned char *)sample, 80, &error) == SUDOKU_ERR_LENGTH);
    CHECK(error.digits_seen == 80);
    memcpy(extra, sample, 81); extra[81] = '1';
    CHECK(sudoku_board_parse(&board, extra, 82, &error) == SUDOKU_ERR_LENGTH);
    CHECK(error.digits_seen == 82);

    saved = board;
    memcpy(invalid, sample, 81); invalid[18] = '.';
    CHECK(sudoku_board_parse(&board, invalid, 81, &error) == SUDOKU_ERR_CHARACTER);
    CHECK(error.byte_offset == 18);
    CHECK(memcmp(&board, &saved, sizeof(board)) == 0);
    invalid[18] = '\0';
    CHECK(sudoku_board_parse(&board, invalid, 81, &error) == SUDOKU_ERR_CHARACTER);
    invalid[18] = 255;
    CHECK(sudoku_board_parse(&board, invalid, 81, &error) == SUDOKU_ERR_CHARACTER);

    memset(invalid, '0', 81); invalid[0] = invalid[1] = '5';
    CHECK(sudoku_board_parse(&board, invalid, 81, &error) == SUDOKU_ERR_ROW);
    CHECK(error.row == 1 && error.column == 2 && error.previous_column == 1 && error.digit == 5);
    CHECK(memcmp(&board, &saved, sizeof(board)) == 0);
    memset(invalid, '0', 81); invalid[0] = invalid[9] = '5';
    CHECK(sudoku_board_parse(&board, invalid, 81, &error) == SUDOKU_ERR_COLUMN);
    memset(invalid, '0', 81); invalid[0] = invalid[10] = '5';
    CHECK(sudoku_board_parse(&board, invalid, 81, &error) == SUDOKU_ERR_BOX);
    board.cells[0] = 10;
    CHECK(sudoku_board_validate(&board, &error) == SUDOKU_ERR_RANGE);
    CHECK(error.row == 1 && error.column == 1 && error.digit == 10);

    large = malloc(SUDOKU_MAX_INPUT_BYTES + 1u);
    CHECK(large != NULL);
    memset(large, '0', SUDOKU_MAX_INPUT_BYTES + 1u);
    CHECK(sudoku_board_parse(&board, large, SUDOKU_MAX_INPUT_BYTES + 1u, &error) == SUDOKU_ERR_TOO_LARGE);
    free(large);
    CHECK(strcmp(sudoku_status_text(SUDOKU_ERR_BOX), "duplicate given in 3x3 box") == 0);
    return 0;
}
int main(void) { int rc = test_all(); if (rc == 0) puts("Board parser/validator tests PASS"); return rc; }
