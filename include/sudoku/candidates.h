#ifndef SUDOKU_CANDIDATES_H
#define SUDOKU_CANDIDATES_H

#include "sudoku/board.h"
#include <stdint.h>

/*
 * Read-only candidate analysis for an already entered 9x9 board.
 * Bit d (1..9) is set when digit d does not occur in the same row,
 * column or 3x3 box. Bit 0 is never set.
 *
 * This is LOCAL CONSTRAINT ANALYSIS, not an exact solution, a proof of
 * uniqueness or a human hint that a placement is globally correct.
 * Empty cells with zero candidates can be a sign of contradiction even
 * when the initial board has no duplicated digits.
 */
typedef struct SudokuCandidateMap {
    uint16_t masks[SUDOKU_CELL_COUNT]; /* 0 for occupied cells */
    unsigned empty_count;
    unsigned naked_single_count;
    unsigned zero_candidate_count;
} SudokuCandidateMap;

/*
 * Validate the board before computing candidates. Return the existing
 * board-validation error on invalid input, or SUDOKU_ERR_ARGUMENT if
 * a pointer is NULL. On failure, *result is unchanged.
 *
 * Candidate positions use row*9 + column, with zero-based indices.
 * No input mutation, solver invocation, allocations or external I/O.
 */
SudokuStatus sudoku_candidate_map(const SudokuBoard *board,
                                  SudokuCandidateMap *result);

#endif
