#ifndef SUDOKU_SOLVER_H
#define SUDOKU_SOLVER_H

#include "sudoku/board.h"
#include <stdint.h>

/* Every result is exact for a well-formed board: invalid givens, zero,
 * exactly one, or at least two solutions. Counting stops after 2.
 * No global solver state. On INVALID/UNSOLVABLE, first_solution is unchanged.
 * On success it contains the deterministic first solution; givens are never
 * modified. If first_solution aliases givens, INVALID is returned without
 * searching or changing the puzzle; optional count and node outputs are zero.
 * count is otherwise optional and set to 0/1/2 when supplied. */
typedef enum SudokuSolveStatus {
    SUDOKU_SOLVE_INVALID = 0,
    SUDOKU_SOLVE_UNSOLVABLE,
    SUDOKU_SOLVE_UNIQUE,
    SUDOKU_SOLVE_MULTIPLE,
    SUDOKU_SOLVE_BUDGET
} SudokuSolveStatus;

SudokuSolveStatus sudoku_analyze(const SudokuBoard *givens,
                                 SudokuBoard *first_solution,
                                 unsigned *solutions_up_to_two);
SudokuSolveStatus sudoku_solve_first(const SudokuBoard *givens,
                                     SudokuBoard *first_solution);
SudokuSolveStatus sudoku_count_solutions(const SudokuBoard *givens,
                                         unsigned *solutions_up_to_two);
/* Exact classification if search completes within max_nodes; when the budget is
 * reached, return BUDGET (never claim uniqueness). No caller board is changed
 * on BUDGET; count is zero. Each recursive search node counts as one unit. */
SudokuSolveStatus sudoku_analyze_bounded(const SudokuBoard *givens,
                                        SudokuBoard *first_solution,
                                        unsigned *solutions_up_to_two,
                                        uint64_t max_nodes,
                                        uint64_t *nodes_visited);
const char *sudoku_solve_status_text(SudokuSolveStatus result);

#endif
