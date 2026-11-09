/* Optional coverage-guided solver harness for constrained run budgets. */
#include "sudoku/board.h"
#include "sudoku/solver.h"
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>

int LLVMFuzzerTestOneInput(const uint8_t *bytes, size_t size) {
    SudokuBoard board = {{0}}, solution;
    size_t i;
    unsigned count = 0;
    SudokuSolveStatus result;
    if (size != 81u) return 0;
    for (i = 0; i < 81u; ++i) board.cells[i] = (uint8_t)(bytes[i] % 10u);
    if (sudoku_board_validate(&board, NULL) != SUDOKU_OK) return 0;
    result = sudoku_analyze(&board, &solution, &count);
    if (result == SUDOKU_SOLVE_UNIQUE || result == SUDOKU_SOLVE_MULTIPLE) {
        if (sudoku_board_validate(&solution, NULL) != SUDOKU_OK) abort();
        for (i = 0; i < 81; ++i) {
            if (solution.cells[i] == 0) abort();
            if (board.cells[i] != 0 && board.cells[i] != solution.cells[i]) abort();
        }
    }
    return 0;
}
