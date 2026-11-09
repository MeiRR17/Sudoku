#include "sudoku/board.h"
#include "sudoku/solver.h"
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define CHECK(expr) do { if (!(expr)) { fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #expr); return 1; } } while (0)
/* Fixed seed makes every failure reproducible on every supported host. */
static uint32_t state = UINT32_C(0x5EED2026);
static uint32_t random32(void) {
    uint32_t x = state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    return state = x;
}
static const char solved[] =
    "534678912672195348198342567859761423426853791713924856961537284287419635345286179";
static int verify_independent(const SudokuBoard *givens, const SudokuBoard *result) {
    unsigned r, c, br, bc;
    for (r = 0; r < 9; ++r) {
        unsigned rows = 0, cols = 0;
        for (c = 0; c < 9; ++c) {
            unsigned idx = r * 9u + c, digit = result->cells[idx];
            unsigned other = result->cells[c * 9u + r];
            if (digit < 1u || digit > 9u || other < 1u || other > 9u) return 0;
            if (rows & (1u << digit) || cols & (1u << other)) return 0;
            rows |= 1u << digit;
            cols |= 1u << other;
            if (givens->cells[idx] != 0u && givens->cells[idx] != digit) return 0;
        }
        if (rows != 1022u || cols != 1022u) return 0;
    }
    for (br = 0; br < 9; br += 3) for (bc = 0; bc < 9; bc += 3) {
        unsigned used = 0, k;
        for (k = 0; k < 9; ++k) {
            unsigned digit = result->cells[(br + k / 3u) * 9u + bc + k % 3u];
            if (used & (1u << digit)) return 0;
            used |= 1u << digit;
        }
        if (used != 1022u) return 0;
    }
    return 1;
}
static int properties(void) {
    unsigned iteration;
    SudokuBoard complete;
    CHECK(sudoku_board_parse(&complete, (const unsigned char *)solved, 81, NULL) == SUDOKU_OK);
    /* Each generated board contains a subset of a known valid solution.
       It must be solvable, and the returned board must be independently valid. */
    for (iteration = 0; iteration < 320u; ++iteration) {
        SudokuBoard puzzle = complete, preserved, output = {{0}};
        unsigned i, solutions = 99;
        SudokuSolveStatus result;
        unsigned threshold = 20u + (random32() % 62u);
        for (i = 0; i < 81u; ++i) if ((random32() % 81u) >= threshold) puzzle.cells[i] = 0u;
        preserved = puzzle;
        CHECK(sudoku_board_validate(&puzzle, NULL) == SUDOKU_OK);
        result = sudoku_analyze(&puzzle, &output, &solutions);
        CHECK(result == SUDOKU_SOLVE_UNIQUE || result == SUDOKU_SOLVE_MULTIPLE);
        CHECK(solutions == 1u || solutions == 2u);
        CHECK(verify_independent(&puzzle, &output));
        CHECK(memcmp(&puzzle, &preserved, sizeof puzzle) == 0);
        {
            char bytes[82];
            SudokuBoard parsed;
            sudoku_board_compact(&puzzle, bytes);
            CHECK(sudoku_board_parse(&parsed, (const unsigned char *)bytes, 81, NULL) == SUDOKU_OK);
            CHECK(memcmp(&parsed, &puzzle, sizeof puzzle) == 0);
        }
    }
    /* Valid ASCII digits with an invalid clue must reject every time. */
    for (iteration = 0; iteration < 128u; ++iteration) {
        SudokuBoard puzzle = complete;
        unsigned row = random32() % 9u;
        unsigned col = random32() % 9u;
        unsigned other_col = (col + 1u + (random32() % 8u)) % 9u;
        SudokuBoard result = {{0}};
        unsigned count = 9;
        puzzle.cells[row * 9u + other_col] = puzzle.cells[row * 9u + col];
        CHECK(sudoku_board_validate(&puzzle, NULL) != SUDOKU_OK);
        CHECK(sudoku_analyze(&puzzle, &result, &count) == SUDOKU_SOLVE_INVALID);
        CHECK(count == 0u);
    }
    /* Byte-counted parser: random malformed and overlong bytes must never write
       to a caller-owned board unless the entire input is valid. */
    for (iteration = 0; iteration < 10000u; ++iteration) {
        unsigned char bytes[192];
        SudokuBoard output, before;
        SudokuError error;
        size_t length = random32() % (sizeof bytes + 1u);
        size_t i;
        SudokuStatus status;
        memset(&output, 0x5a, sizeof output);
        before = output;
        for (i = 0; i < length; ++i) bytes[i] = (unsigned char)random32();
        status = sudoku_board_parse(&output, bytes, length, &error);
        if (status == SUDOKU_OK) {
            CHECK(sudoku_board_validate(&output, NULL) == SUDOKU_OK);
        } else {
            CHECK(memcmp(&output, &before, sizeof output) == 0);
            CHECK(status == error.status);
        }
    }
    return 0;
}
int main(void) {
    int result = properties();
    if (result == 0) puts("PROPERTY PASS seed=0x5EED2026 generated=320 contradictory=128 parser_random=10000");
    return result;
}
