#ifndef SUDOKU_GENERATOR_H
#define SUDOKU_GENERATOR_H

#include "sudoku/board.h"
#include <stdint.h>

typedef enum SudokuDifficulty {
    SUDOKU_DIFFICULTY_INVALID = 0,
    SUDOKU_DIFFICULTY_EASY,
    SUDOKU_DIFFICULTY_MEDIUM,
    SUDOKU_DIFFICULTY_HARD
} SudokuDifficulty;

typedef enum SudokuGenerateStatus {
    SUDOKU_GENERATE_OK = 0,
    SUDOKU_GENERATE_INVALID,
    SUDOKU_GENERATE_BUDGET
} SudokuGenerateStatus;

typedef struct SudokuGenerateOptions {
    uint32_t seed;             /* all 32-bit values, including zero, are valid */
    SudokuDifficulty difficulty;
    unsigned rotational;      /* 1 = rotational 180-degree clue symmetry */
    unsigned max_attempts;    /* max randomized complete boards, 1..100 */
    unsigned max_checks;      /* total uniqueness checks, 1..10000 */
    uint64_t max_nodes;       /* per uniqueness test, 1..1000000 */
    unsigned max_cpu_ms;      /* best-effort CPU deadline, 1..60000 */
} SudokuGenerateOptions;

typedef struct SudokuGenerateResult {
    SudokuBoard puzzle;
    SudokuBoard solution;
    SudokuDifficulty rated;
    unsigned clues;
    unsigned naked_singles;
    unsigned hidden_singles;
    unsigned attempts;
    unsigned checks;
} SudokuGenerateResult;

/* Human-technique rubric: EASY can finish using naked singles alone;
 * MEDIUM requires hidden singles but nothing beyond naked/hidden singles;
 * HARD stalls with cells remaining after naked+hidden singles.
 * This is an explicitly limited, deterministic human-technique proxy, NOT
 * a validated estimate of a person's solving time. Does not ensure unique
 * solvability: call exact sudoku_analyze to validate uniqueness separately. */
SudokuDifficulty sudoku_rate_difficulty(const SudokuBoard *board,
                                       unsigned *naked, unsigned *hidden);

/* Transactional: output is untouched on invalid options / exhausted budget.
 * Every successful emitted puzzle is checked with an exact count-to-two
 * solver, under per-check node budget. Exhaustion never implies uniqueness.
 * A best-effort CPU budget is checked between trials; a single bounded exact
 * search can exceed the limit before returning. */
SudokuGenerateStatus sudoku_generate(const SudokuGenerateOptions *options,
                                     SudokuGenerateResult *out);
const char *sudoku_difficulty_text(SudokuDifficulty difficulty);
const char *sudoku_generate_status_text(SudokuGenerateStatus status);

#endif
