#ifndef SUDOKU_SOLVER_H
#define SUDOKU_SOLVER_H

#include "sudoku/board.h"

/* Every result is exact for a well-formed board: invalid givens, zero,
 * exactly one, or at least two solutions. Counting stops after 2.
 * No global solver state. On INVALID/UNSOLVABLE, first_solution is unchanged.
 * On success it contains the deterministic first solution; givens are never
 * modified. count is optional and set to 0/1/2 when supplied. */
typedef enum SudokuSolveStatus {
    SUDOKU_SOLVE_INVALID = 0,
    SUDOKU_SOLVE_UNSOLVABLE,
    SUDOKU_SOLVE_UNIQUE,
    SUDOKU_SOLVE_MULTIPLE
} SudokuSolveStatus;

SudokuSolveStatus sudoku_analyze(const SudokuBoard *givens,
                                 SudokuBoard *first_solution,
                                 unsigned *solutions_up_to_two);
SudokuSolveStatus sudoku_solve_first(const SudokuBoard *givens,
                                     SudokuBoard *first_solution);
SudokuSolveStatus sudoku_count_solutions(const SudokuBoard *givens,
                                         unsigned *solutions_up_to_two);
const char *sudoku_solve_status_text(SudokuSolveStatus result);

#endif
