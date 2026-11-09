/* Optional libFuzzer harness; not linked into normal builds.
 * Invoke with clang -fsanitize=fuzzer,address,undefined and seed corpus.
 * Deterministic parser invariants are also exercised in test_properties.c. */
#include "sudoku/board.h"
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    SudokuBoard board;
    SudokuBoard original;
    SudokuError error;
    SudokuStatus status;
    char compact[82];
    memset(&board, 0xa5, sizeof board);
    original = board;
    status = sudoku_board_parse(&board, data, size, &error);
    if (status != error.status) abort();
    if (status == SUDOKU_OK) {
        SudokuBoard again;
        if (sudoku_board_validate(&board, NULL) != SUDOKU_OK) abort();
        sudoku_board_compact(&board, compact);
        if (sudoku_board_parse(&again, (const uint8_t *)compact, 81, NULL) != SUDOKU_OK) abort();
        if (memcmp(&again, &board, sizeof board) != 0) abort();
    } else if (memcmp(&board, &original, sizeof board) != 0) abort();
    return 0;
}
