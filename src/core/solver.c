#include "sudoku/solver.h"
#include <stdint.h>

#define ALL_DIGITS UINT16_C(0x03FE)

typedef struct Search {
    SudokuBoard board;
    SudokuBoard first;
    uint16_t rows[9];
    uint16_t cols[9];
    uint16_t boxes[9];
    unsigned solutions;
} Search;

static unsigned box_of(unsigned row, unsigned col) {
    return (row / 3u) * 3u + col / 3u;
}

static unsigned popcount9(uint16_t bits) {
    unsigned count = 0;
    while (bits) {
        bits &= (uint16_t)(bits - 1u);
        ++count;
    }
    return count;
}

/* Select the least-constrained branching point with a deterministic tie-break.
 * -1: complete; -2: contradiction; otherwise the next board index. */
static int choose_cell(const Search *search, uint16_t *allowed) {
    unsigned best_count = 10;
    int best = -1;
    unsigned i;
    for (i = 0; i < SUDOKU_CELL_COUNT; ++i) {
        unsigned row, col, box, options;
        uint16_t blocked, candidates;
        if (search->board.cells[i] != 0u) continue;
        row = i / 9u;
        col = i % 9u;
        box = box_of(row, col);
        blocked = (uint16_t)(search->rows[row] |
                             search->cols[col] | search->boxes[box]);
        candidates = (uint16_t)(ALL_DIGITS & (uint16_t)~blocked);
        options = popcount9(candidates);
        if (options == 0u) return -2;
        if (options < best_count) {
            best_count = options;
            best = (int)i;
            *allowed = candidates;
            if (options == 1u) break;
        }
    }
    return best;
}

/* At most 81 placements: one position becomes fixed on each descent. */
static void search_solutions(Search *search) {
    uint16_t allowed = 0;
    int pos;
    unsigned row, col, box, digit;
    if (search->solutions >= 2u) return;
    pos = choose_cell(search, &allowed);
    if (pos == -2) return;
    if (pos == -1) {
        if (search->solutions == 0u) search->first = search->board;
        ++search->solutions;
        return;
    }
    row = (unsigned)pos / 9u;
    col = (unsigned)pos % 9u;
    box = box_of(row, col);
    for (digit = 1; digit <= 9u; ++digit) {
        uint16_t bit = (uint16_t)(1u << digit);
        if ((allowed & bit) == 0u) continue;
        search->board.cells[pos] = (uint8_t)digit;
        search->rows[row] |= bit;
        search->cols[col] |= bit;
        search->boxes[box] |= bit;
        search_solutions(search);
        search->board.cells[pos] = 0u;
        search->rows[row] &= (uint16_t)~bit;
        search->cols[col] &= (uint16_t)~bit;
        search->boxes[box] &= (uint16_t)~bit;
        if (search->solutions >= 2u) return;
    }
}

SudokuSolveStatus sudoku_analyze(const SudokuBoard *givens,
                                 SudokuBoard *first_solution,
                                 unsigned *solutions_up_to_two) {
    Search search = {0};
    unsigned i;
    if (solutions_up_to_two != NULL) *solutions_up_to_two = 0;
    if (givens == NULL || sudoku_board_validate(givens, NULL) != SUDOKU_OK)
        return SUDOKU_SOLVE_INVALID;
    search.board = *givens;
    for (i = 0; i < SUDOKU_CELL_COUNT; ++i) {
        uint8_t digit = givens->cells[i];
        unsigned row, col, box;
        uint16_t bit;
        if (digit == 0u) continue;
        row = i / 9u;
        col = i % 9u;
        box = box_of(row, col);
        bit = (uint16_t)(1u << digit);
        search.rows[row] |= bit;
        search.cols[col] |= bit;
        search.boxes[box] |= bit;
    }
    search_solutions(&search);
    if (solutions_up_to_two != NULL) *solutions_up_to_two = search.solutions;
    if (search.solutions == 0u) return SUDOKU_SOLVE_UNSOLVABLE;
    if (first_solution != NULL) *first_solution = search.first;
    return search.solutions == 1u ? SUDOKU_SOLVE_UNIQUE : SUDOKU_SOLVE_MULTIPLE;
}

SudokuSolveStatus sudoku_solve_first(const SudokuBoard *givens,
                                     SudokuBoard *first_solution) {
    return sudoku_analyze(givens, first_solution, NULL);
}

SudokuSolveStatus sudoku_count_solutions(const SudokuBoard *givens,
                                         unsigned *solutions_up_to_two) {
    if (solutions_up_to_two == NULL) return SUDOKU_SOLVE_INVALID;
    return sudoku_analyze(givens, NULL, solutions_up_to_two);
}

const char *sudoku_solve_status_text(SudokuSolveStatus result) {
    switch (result) {
        case SUDOKU_SOLVE_INVALID: return "invalid givens";
        case SUDOKU_SOLVE_UNSOLVABLE: return "no solution";
        case SUDOKU_SOLVE_UNIQUE: return "unique solution";
        case SUDOKU_SOLVE_MULTIPLE: return "multiple solutions";
        default: return "unknown solver status";
    }
}
