#include "sudoku/board.h"
#include "sudoku/solver.h"
#include <stdio.h>
#include <string.h>

#define CHECK(e) do { if (!(e)) { fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #e); return 1; } } while (0)
static const char classic[] = "530070000600195000098000060800060003400803001700020006060000280000419005000080079";
static const char solution[] = "534678912672195348198342567859761423426853791713924856961537284287419635345286179";
static const char escargot[] = "100007090030020008009600500005300900010080002600004000300000010040000007007000300";
static const char diabolical[] = "800000000003600000070090200050007000000045700000100030001000068008500010090000400";

/* Independent checking, without invoking the engine's validator. */
static int verify_solution(const SudokuBoard *givens, const SudokuBoard *result) {
    unsigned r, c, br, bc, k;
    for (r = 0; r < 9; ++r) {
        unsigned row = 0, col = 0;
        for (c = 0; c < 9; ++c) {
            unsigned a = result->cells[r * 9 + c], b = result->cells[c * 9 + r];
            if (a < 1 || a > 9 || b < 1 || b > 9) return 0;
            if (row & (1u << a) || col & (1u << b)) return 0;
            row |= 1u << a;
            col |= 1u << b;
            if (givens->cells[r * 9 + c] != 0 && givens->cells[r * 9 + c] != a) return 0;
        }
        if (row != 1022u || col != 1022u) return 0;
    }
    for (br = 0; br < 9; br += 3) for (bc = 0; bc < 9; bc += 3) {
        unsigned bits = 0;
        for (k = 0; k < 9; ++k) {
            unsigned digit = result->cells[(br + k / 3) * 9 + bc + k % 3];
            if (bits & (1u << digit)) return 0;
            bits |= 1u << digit;
        }
        if (bits != 1022u) return 0;
    }
    return 1;
}
static int check_unique(const char *input, const char *expected) {
    SudokuBoard board, before, output, repeated;
    unsigned count = 9;
    SudokuSolveStatus status;
    char compact[82];
    CHECK(strlen(input) == 81);
    CHECK(sudoku_board_parse(&board, (const unsigned char *)input, 81, NULL) == SUDOKU_OK);
    before = board;
    status = sudoku_analyze(&board, &output, &count);
    CHECK(status == SUDOKU_SOLVE_UNIQUE && count == 1);
    CHECK(memcmp(&board, &before, sizeof board) == 0);
    CHECK(verify_solution(&board, &output));
    sudoku_board_compact(&output, compact);
    if (expected) CHECK(strcmp(compact, expected) == 0);
    CHECK(sudoku_solve_first(&board, &repeated) == SUDOKU_SOLVE_UNIQUE);
    CHECK(memcmp(&repeated, &output, sizeof output) == 0);
    CHECK(sudoku_count_solutions(&board, &count) == SUDOKU_SOLVE_UNIQUE && count == 1);
    return 0;
}
static int test_all(void) {
    SudokuBoard board = {{0}}, output = {{0}}, before, solved;
    unsigned count = 99, i, digit;
    char zeros[82];
    CHECK(check_unique(classic, solution) == 0);
    CHECK(check_unique(escargot, NULL) == 0);
    CHECK(check_unique(diabolical, NULL) == 0);
    CHECK(sudoku_board_parse(&board, (const unsigned char *)solution, 81, NULL) == SUDOKU_OK);
    CHECK(sudoku_analyze(&board, &solved, &count) == SUDOKU_SOLVE_UNIQUE && count == 1);
    CHECK(memcmp(&board, &solved, sizeof board) == 0);
    memset(zeros, '0', 81); zeros[81] = '\0';
    CHECK(sudoku_board_parse(&board, (const unsigned char *)zeros, 81, NULL) == SUDOKU_OK);
    CHECK(sudoku_analyze(&board, &output, &count) == SUDOKU_SOLVE_MULTIPLE && count == 2);
    CHECK(verify_solution(&board, &output));
    before = output;
    CHECK(sudoku_solve_first(&board, &solved) == SUDOKU_SOLVE_MULTIPLE);
    CHECK(memcmp(&before, &solved, sizeof solved) == 0);
    CHECK(sudoku_count_solutions(&board, &count) == SUDOKU_SOLVE_MULTIPLE && count == 2);
    CHECK(sudoku_count_solutions(&board, NULL) == SUDOKU_SOLVE_INVALID);
    CHECK(sudoku_analyze(NULL, &output, &count) == SUDOKU_SOLVE_INVALID && count == 0);
    CHECK(memcmp(&before, &output, sizeof output) == 0);
    board.cells[0] = 5; board.cells[1] = 5;
    CHECK(sudoku_analyze(&board, &output, &count) == SUDOKU_SOLVE_INVALID && count == 0);
    CHECK(memcmp(&before, &output, sizeof output) == 0);
    board.cells[1] = 15;
    CHECK(sudoku_analyze(&board, &output, &count) == SUDOKU_SOLVE_INVALID);
    CHECK(memcmp(&before, &output, sizeof output) == 0);
    /* Find a valid-but-unsatisfiable board by injecting a false clue in a
       classic puzzle. This also independently tests no-solution classification. */
    CHECK(sudoku_board_parse(&board, (const unsigned char *)classic, 81, NULL) == SUDOKU_OK);
    for (i = 0; i < 81; ++i) {
        int found = 0;
        if (board.cells[i] != 0) continue;
        for (digit = 1; digit <= 9; ++digit) {
            SudokuBoard candidate = board;
            candidate.cells[i] = (uint8_t)digit;
            if (digit == (unsigned)(solution[i] - '0')) continue;
            if (sudoku_board_validate(&candidate, NULL) != SUDOKU_OK) continue;
            if (sudoku_analyze(&candidate, &output, &count) == SUDOKU_SOLVE_UNSOLVABLE) {
                CHECK(count == 0);
                CHECK(memcmp(&before, &output, sizeof output) == 0);
                found = 1;
                break;
            }
        }
        if (found) break;
    }
    CHECK(i < 81);
    CHECK(strcmp(sudoku_solve_status_text(SUDOKU_SOLVE_MULTIPLE), "multiple solutions") == 0);
    return 0;
}
int main(void) { int result = test_all(); if (!result) puts("Exact Sudoku solver fixtures and invariants PASS"); return result; }
