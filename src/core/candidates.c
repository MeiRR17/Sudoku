#include "sudoku/candidates.h"

SudokuStatus sudoku_candidate_map(const SudokuBoard *board,
                                  SudokuCandidateMap *result) {
    SudokuCandidateMap computed = {{0}, 0u, 0u, 0u};
    SudokuStatus status;
    unsigned row, col;

    if (board == NULL || result == NULL) return SUDOKU_ERR_ARGUMENT;
    status = sudoku_board_validate(board, NULL);
    if (status != SUDOKU_OK) return status;

    for (row = 0u; row < SUDOKU_SIDE; ++row) {
        for (col = 0u; col < SUDOKU_SIDE; ++col) {
            const unsigned index = row * SUDOKU_SIDE + col;
            unsigned i, j, digit;
            uint16_t used = 0u;
            uint16_t allowed;
            unsigned count = 0u;
            if (board->cells[index] != 0u) continue;
            computed.empty_count++;

            for (i = 0u; i < SUDOKU_SIDE; ++i) {
                digit = board->cells[row * SUDOKU_SIDE + i];
                if (digit != 0u) used = (uint16_t)(used | (1u << digit));
                digit = board->cells[i * SUDOKU_SIDE + col];
                if (digit != 0u) used = (uint16_t)(used | (1u << digit));
            }
            for (i = (row / 3u) * 3u; i < (row / 3u) * 3u + 3u; ++i) {
                for (j = (col / 3u) * 3u; j < (col / 3u) * 3u + 3u; ++j) {
                    digit = board->cells[i * SUDOKU_SIDE + j];
                    if (digit != 0u) used = (uint16_t)(used | (1u << digit));
                }
            }
            allowed = (uint16_t)(UINT16_C(0x3FE) & (uint16_t)(~used));
            computed.masks[index] = allowed;
            for (digit = 1u; digit <= 9u; ++digit) {
                if ((allowed & (1u << digit)) != 0u) count++;
            }
            if (count == 0u) computed.zero_candidate_count++;
            if (count == 1u) computed.naked_single_count++;
        }
    }

    *result = computed;
    return SUDOKU_OK;
}
