/* Deterministic CPU-clock fault/rollback contract for the real generator.
 * Include the production translation unit under a substituted clock()
 * instead of requiring a production-only test hook in the public API.
 * Static-library resolution supplies board/solver, not a second generator.o. */
#include <stdio.h>
#include <string.h>
#include <time.h>

static volatile clock_t test_ticks;
static clock_t test_clock(void) { return test_ticks; }
#define clock test_clock
#include "../src/core/generator.c"
#undef clock

#define CHECK(e) do { if (!(e)) { \
    fprintf(stderr, "CLOCK TEST FAILED at line %d: %s\n", __LINE__, #e); \
    return 1; \
} } while (0)

int main(void) {
    SudokuGenerateOptions options = {
        42u, SUDOKU_DIFFICULTY_EASY, 0u, 20u, 2000u, 50000u, 5000u
    };
    SudokuGenerateResult result, before;

    test_ticks = 0;
    CHECK(!cpu_budget_exceeded(0, 1000u));
    test_ticks = (clock_t)CLOCKS_PER_SEC;
    CHECK(cpu_budget_exceeded(0, 1000u));
    CHECK(!cpu_budget_exceeded(0, 2000u));

    test_ticks = 0;
    CHECK(cpu_budget_exceeded((clock_t)CLOCKS_PER_SEC, 1000u));
    CHECK(cpu_budget_exceeded((clock_t)-1, 1000u));

    test_ticks = (clock_t)-1;
    CHECK(cpu_budget_exceeded(0, 1000u));

    /* No CPU timer: generation must not run and must preserve the caller's
     * output buffer. This also covers the actual public generator API. */
    memset(&result, 0xA6, sizeof result);
    before = result;
    CHECK(sudoku_generate(&options, &result) == SUDOKU_GENERATE_BUDGET);
    CHECK(memcmp(&before, &result, sizeof result) == 0);
    puts("GENERATOR CLOCK PASS: exact boundary, backwards clock, unavailable clock and transactional rejection");
    return 0;
}
