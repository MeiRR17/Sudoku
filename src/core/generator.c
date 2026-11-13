#include "sudoku/generator.h"
#include "sudoku/solver.h"
#include <time.h>

#define ALL_BITS UINT16_C(0x03FE)

typedef struct RNG { uint32_t state; } RNG;

static uint32_t next_random(RNG *r) {
    uint32_t x = r->state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    r->state = x;
    return x;
}
static void shuffle(unsigned *items, unsigned count, RNG *r) {
    unsigned i;
    for (i = count; i > 1; --i) {
        unsigned j = next_random(r) % i;
        unsigned tmp = items[i - 1];
        items[i - 1] = items[j];
        items[j] = tmp;
    }
}
/* Sudoku symmetry automorphisms: digits, bands, rows within bands,
 * stacks, columns within stacks, and transpose. No static board is emitted. */
static void axis_permutation(unsigned out[9], RNG *r) {
    unsigned groups[3] = {0,1,2}, i, j;
    shuffle(groups, 3, r);
    for (i = 0; i < 3; ++i) {
        unsigned local[3] = {0,1,2};
        shuffle(local, 3, r);
        for (j = 0; j < 3; ++j) out[i * 3 + j] = groups[i] * 3 + local[j];
    }
}
static void complete_board(SudokuBoard *board, RNG *r) {
    unsigned rows[9], cols[9], digits[9] = {1,2,3,4,5,6,7,8,9};
    unsigned row, col, transpose = next_random(r) & 1u;
    axis_permutation(rows, r);
    axis_permutation(cols, r);
    shuffle(digits, 9, r);
    for (row = 0; row < 9; ++row) for (col = 0; col < 9; ++col) {
        unsigned source_row = transpose ? cols[col] : rows[row];
        unsigned source_col = transpose ? rows[row] : cols[col];
        unsigned index = (source_row * 3 + source_row / 3 + source_col) % 9u;
        board->cells[row * 9 + col] = (uint8_t)digits[index];
    }
}

static uint16_t candidates(const SudokuBoard *board, unsigned pos) {
    unsigned row = pos / 9u, col = pos % 9u, i, br, bc;
    uint16_t occupied = 0;
    for (i = 0; i < 9u; ++i) {
        unsigned a = board->cells[row * 9u + i], b = board->cells[i * 9u + col];
        if (a) occupied |= (uint16_t)(1u << a);
        if (b) occupied |= (uint16_t)(1u << b);
    }
    br = (row / 3u) * 3u;
    bc = (col / 3u) * 3u;
    for (i = 0; i < 9u; ++i) {
        unsigned d = board->cells[(br + i / 3u) * 9u + bc + i % 3u];
        if (d) occupied |= (uint16_t)(1u << d);
    }
    return (uint16_t)(ALL_BITS & (uint16_t)~occupied);
}
static unsigned bits_count(uint16_t bits) {
    unsigned count = 0;
    while (bits) { bits &= (uint16_t)(bits - 1u); ++count; }
    return count;
}
static unsigned only_digit(uint16_t one_bit) {
    unsigned digit;
    for (digit = 1; digit <= 9; ++digit)
        if ((one_bit & (uint16_t)(1u << digit)) != 0) return digit;
    return 0;
}
/* Row units 0..8, columns 9..17, boxes 18..26. */
static unsigned unit_cell(unsigned unit, unsigned offset) {
    if (unit < 9) return unit * 9u + offset;
    if (unit < 18) return offset * 9u + unit - 9u;
    return ((unit - 18u) / 3u * 3u + offset / 3u) * 9u +
           ((unit - 18u) % 3u * 3u + offset % 3u);
}
SudokuDifficulty sudoku_rate_difficulty(const SudokuBoard *board,
                                       unsigned *naked, unsigned *hidden) {
    SudokuBoard work;
    unsigned naked_count = 0, hidden_count = 0, loops;
    if (naked) *naked = 0;
    if (hidden) *hidden = 0;
    if (!board || sudoku_board_validate(board, NULL) != SUDOKU_OK)
        return SUDOKU_DIFFICULTY_INVALID;
    work = *board;
    for (loops = 0; loops <= 81u; ++loops) {
        unsigned pos, unit, d, offset, found = 0;
        unsigned empty = 0;
        for (pos = 0; pos < 81u; ++pos) {
            uint16_t mask;
            if (work.cells[pos]) continue;
            ++empty;
            mask = candidates(&work, pos);
            if (!mask) return SUDOKU_DIFFICULTY_INVALID;
            if (bits_count(mask) == 1u) {
                work.cells[pos] = (uint8_t)only_digit(mask);
                ++naked_count;
                found = 1;
                break;
            }
        }
        if (found) continue;
        if (!empty) {
            if (naked) *naked = naked_count;
            if (hidden) *hidden = hidden_count;
            return hidden_count ? SUDOKU_DIFFICULTY_MEDIUM : SUDOKU_DIFFICULTY_EASY;
        }
        for (unit = 0; unit < 27u && !found; ++unit) for (d = 1; d <= 9u && !found; ++d) {
            unsigned slot = 81u, count = 0, already = 0;
            for (offset = 0; offset < 9u; ++offset) {
                pos = unit_cell(unit, offset);
                if (work.cells[pos] == d) { already = 1; break; }
            }
            if (already) continue;
            for (offset = 0; offset < 9u; ++offset) {
                pos = unit_cell(unit, offset);
                if (work.cells[pos] == 0u && (candidates(&work, pos) & (uint16_t)(1u << d))) {
                    slot = pos;
                    ++count;
                    if (count > 1u) break;
                }
            }
            /* No candidate for a missing digit in a row, column or box
             * is a logical contradiction, not a "hard" puzzle. This can
             * happen even when every existing given passes validation. */
            if (count == 0u) return SUDOKU_DIFFICULTY_INVALID;
            if (count == 1u) {
                work.cells[slot] = (uint8_t)d;
                ++hidden_count;
                found = 1;
            }
        }
        if (!found) {
            if (naked) *naked = naked_count;
            if (hidden) *hidden = hidden_count;
            return SUDOKU_DIFFICULTY_HARD;
        }
    }
    return SUDOKU_DIFFICULTY_INVALID;
}
static unsigned clue_count(const SudokuBoard *board) {
    unsigned i, clues = 0;
    for (i = 0; i < 81; ++i) if (board->cells[i]) ++clues;
    return clues;
}
static int cpu_budget_exceeded(clock_t start, unsigned max_ms) {
    clock_t now = clock();
    double elapsed_ms;
    /* When the CPU clock is unavailable or wraps backwards, do not silently
     * disable the caller's time budget. Subtract as double: signed clock_t
     * arithmetic could otherwise overflow before the conversion. */
    if (start == (clock_t)-1 || now == (clock_t)-1) return 1;
    elapsed_ms = ((double)now - (double)start) * 1000.0 / CLOCKS_PER_SEC;
    return elapsed_ms < 0.0 || elapsed_ms >= (double)max_ms;
}

SudokuGenerateStatus sudoku_generate(const SudokuGenerateOptions *opts,
                                     SudokuGenerateResult *out) {
    RNG rng;
    unsigned attempt, checks = 0;
    clock_t start;
    if (!out || !opts || opts->difficulty < SUDOKU_DIFFICULTY_EASY ||
        opts->difficulty > SUDOKU_DIFFICULTY_HARD || opts->rotational > 1 ||
        opts->max_attempts < 1 || opts->max_attempts > 100 ||
        opts->max_checks < 1 || opts->max_checks > 10000 ||
        opts->max_nodes < 1 || opts->max_nodes > UINT64_C(1000000) ||
        opts->max_cpu_ms < 1 || opts->max_cpu_ms > 60000)
        return SUDOKU_GENERATE_INVALID;
    rng.state = opts->seed ^ UINT32_C(0xA5A5A5A5);
    if (!rng.state) rng.state = UINT32_C(0x9E3779B9);
    start = clock();
    for (attempt = 1; attempt <= opts->max_attempts; ++attempt) {
        SudokuBoard full, puzzle;
        unsigned order[81], groups = opts->rotational ? 41u : 81u;
        unsigned idx;
        if (cpu_budget_exceeded(start, opts->max_cpu_ms)) break;
        complete_board(&full, &rng);
        puzzle = full;
        for (idx = 0; idx < groups; ++idx) order[idx] = idx;
        shuffle(order, groups, &rng);
        for (idx = 0; idx < groups; ++idx) {
            SudokuBoard candidate = puzzle;
            unsigned pos = order[idx], mirror = 80u - pos;
            unsigned count;
            SudokuSolveStatus status;
            SudokuDifficulty rated;
            unsigned naked = 0, hidden = 0, clues;
            if (checks >= opts->max_checks || cpu_budget_exceeded(start, opts->max_cpu_ms))
                return SUDOKU_GENERATE_BUDGET;
            if (!candidate.cells[pos]) continue;
            candidate.cells[pos] = 0u;
            if (opts->rotational) candidate.cells[mirror] = 0u;
            ++checks;
            status = sudoku_analyze_bounded(&candidate, NULL, &count, opts->max_nodes, NULL);
            if (status != SUDOKU_SOLVE_UNIQUE) continue;
            puzzle = candidate;
            clues = clue_count(&puzzle);
            /* Cosmetic minimum blank counts avoid an uninteresting 80-clue
             * 'easy' board; classification itself uses logic only. */
            if (clues > (opts->difficulty == SUDOKU_DIFFICULTY_EASY ? 40u :
                         opts->difficulty == SUDOKU_DIFFICULTY_MEDIUM ? 36u : 32u))
                continue;
            rated = sudoku_rate_difficulty(&puzzle, &naked, &hidden);
            /* A bounded solver/rating pass can itself consume the deadline.
             * Never report success after observing an exhausted CPU budget. */
            if (cpu_budget_exceeded(start, opts->max_cpu_ms))
                return SUDOKU_GENERATE_BUDGET;
            if (rated == opts->difficulty) {
                SudokuGenerateResult result = {0};
                result.puzzle = puzzle;
                result.solution = full;
                result.rated = rated;
                result.clues = clues;
                result.naked_singles = naked;
                result.hidden_singles = hidden;
                result.attempts = attempt;
                result.checks = checks;
                *out = result;
                return SUDOKU_GENERATE_OK;
            }
        }
    }
    return SUDOKU_GENERATE_BUDGET;
}
const char *sudoku_difficulty_text(SudokuDifficulty d) {
    switch (d) {
        case SUDOKU_DIFFICULTY_EASY: return "easy";
        case SUDOKU_DIFFICULTY_MEDIUM: return "medium";
        case SUDOKU_DIFFICULTY_HARD: return "hard";
        default: return "invalid";
    }
}
const char *sudoku_generate_status_text(SudokuGenerateStatus s) {
    switch (s) {
        case SUDOKU_GENERATE_OK: return "generated";
        case SUDOKU_GENERATE_INVALID: return "invalid generation options";
        case SUDOKU_GENERATE_BUDGET: return "generation budget exhausted";
        default: return "unknown generation status";
    }
}
