#include "sudoku/board.h"
#include "sudoku/solver.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char demo[] =
    "300000020080432010050000600074860000000000008"
    "030100700000296871600000340190700006";

static void help(void) {
    puts("Sudoku v0.3.0 — exact solver, solution counting and validation");
    puts("Usage: sudoku {validate|solve|count} (--puzzle DIGITS | --file PATH | --stdin) [--format text|compact]");
    puts("       sudoku --demo | --version | --help");
    puts("Input: 81 ASCII digits 0..9; optional ASCII whitespace; 0 = empty.");
    puts("       File/stdin limit: 1 MiB. All other bytes are rejected.");
    puts("Exit: 0 success; 2 usage error; 3 invalid input/board; 4 I/O failure; 5 no solution.");
    puts("solve: print deterministic first solution; warn when non-unique.");
    puts("count: print 0, 1 or 2+ (search stops after second solution).");
    puts("validate checks givens only; solve/count check solvability.");
}

static void display(const SudokuBoard *board) {
    unsigned r, c;
    puts("+-------+-------+-------+");
    for (r = 0; r < SUDOKU_SIDE; ++r) {
        putchar('|');
        for (c = 0; c < SUDOKU_SIDE; ++c) {
            unsigned v = board->cells[r * SUDOKU_SIDE + c];
            putchar(' ');
            putchar(v ? (int)('0' + v) : '.');
            if (c % 3u == 2u) { putchar(' '); putchar('|'); }
        }
        putchar('\n');
        if (r % 3u == 2u) puts("+-------+-------+-------+");
    }
}

static int read_all(FILE *stream, unsigned char **out, size_t *length) {
    const size_t capacity = SUDOKU_MAX_INPUT_BYTES + 1u;
    unsigned char *data = malloc(capacity);
    size_t len = 0;
    if (!data) return -1;
    while (len < capacity) {
        size_t n = fread(data + len, 1u, capacity - len, stream);
        len += n;
        if (n == 0u) {
            if (ferror(stream)) { free(data); return -1; }
            break;
        }
    }
    *out = data;
    *length = len;
    return 0;
}

static int invalid(SudokuStatus status, const SudokuError *error) {
    fprintf(stderr, "Invalid puzzle: %s", sudoku_status_text(status));
    if (status == SUDOKU_ERR_ROW || status == SUDOKU_ERR_COLUMN || status == SUDOKU_ERR_BOX) {
        fprintf(stderr, " (digit %u at row %u col %u conflicts with row %u col %u)",
                error->digit, error->row, error->column,
                error->previous_row, error->previous_column);
    } else if (status == SUDOKU_ERR_RANGE) {
        fprintf(stderr, " (value %u at row %u col %u)",
                error->digit, error->row, error->column);
    } else if (status == SUDOKU_ERR_CHARACTER) {
        fprintf(stderr, " (byte offset %zu)", error->byte_offset);
    } else if (status == SUDOKU_ERR_LENGTH) {
        fprintf(stderr, " (found %zu digits)", error->digits_seen);
    }
    fputc('\n', stderr);
    return 3;
}

int main(int argc, char **argv) {
    const unsigned char *source = NULL;
    unsigned char *allocated = NULL;
    const char *path = NULL;
    size_t length = 0;
    SudokuBoard board;
    SudokuError error;
    SudokuStatus status;
    int compact = 0;
    const char *action;
    int i;
    FILE *stream;

    if (argc == 2 && strcmp(argv[1], "--help") == 0) { help(); return 0; }
    if (argc == 2 && strcmp(argv[1], "--version") == 0) {
        puts("Sudoku 0.3.0 (experimental)"); return 0;
    }
    if (argc == 2 && strcmp(argv[1], "--demo") == 0) {
        status = sudoku_board_parse(&board, (const unsigned char *)demo,
                                    sizeof(demo) - 1u, &error);
        if (status != SUDOKU_OK) return invalid(status, &error);
        SudokuBoard solution;
        SudokuSolveStatus solved;
        puts("Built-in example (original givens):");
        display(&board);
        solved = sudoku_solve_first(&board, &solution);
        printf("Solver result: %s\n", sudoku_solve_status_text(solved));
        if (solved == SUDOKU_SOLVE_UNIQUE || solved == SUDOKU_SOLVE_MULTIPLE) display(&solution);
        return solved == SUDOKU_SOLVE_UNSOLVABLE ? 5 : 0;
    }
    if (argc < 3 || (strcmp(argv[1], "validate") != 0 &&
                     strcmp(argv[1], "solve") != 0 &&
                     strcmp(argv[1], "count") != 0)) { help(); return 2; }
    action = argv[1];
    for (i = 2; i < argc; ++i) {
        if (strcmp(argv[i], "--puzzle") == 0 || strcmp(argv[i], "--file") == 0) {
            int is_puzzle = strcmp(argv[i], "--puzzle") == 0;
            if (source != NULL || path != NULL || i + 1 >= argc || !argv[i + 1][0]) {
                help(); return 2;
            }
            if (is_puzzle) {
                source = (const unsigned char *)argv[++i];
                length = strlen((const char *)source);
            } else path = argv[++i];
        } else if (strcmp(argv[i], "--stdin") == 0) {
            if (source != NULL || path != NULL) { help(); return 2; }
            path = "-";
        } else if (strcmp(argv[i], "--format") == 0 && i + 1 < argc) {
            const char *format = argv[++i];
            if (strcmp(format, "compact") == 0) compact = 1;
            else if (strcmp(format, "text") == 0) compact = 0;
            else { help(); return 2; }
        } else { help(); return 2; }
    }
    if (source == NULL && path == NULL) { help(); return 2; }
    if (path != NULL) {
        stream = strcmp(path, "-") == 0 ? stdin : fopen(path, "rb");
        if (stream == NULL) { fprintf(stderr, "Cannot open input: %s\n", strerror(errno)); return 4; }
        if (read_all(stream, &allocated, &length) != 0) {
            fprintf(stderr, "Cannot read input: %s\n", strerror(errno));
            if (stream != stdin) fclose(stream);
            return 4;
        }
        if (stream != stdin && fclose(stream) != 0) {
            fputs("Cannot close input file\n", stderr);
            free(allocated);
            return 4;
        }
        source = allocated;
    }
    status = sudoku_board_parse(&board, source, length, &error);
    free(allocated);
    if (status != SUDOKU_OK) return invalid(status, &error);
    if (strcmp(action, "count") == 0) {
        unsigned count;
        SudokuSolveStatus result = sudoku_count_solutions(&board, &count);
        if (result == SUDOKU_SOLVE_INVALID) return invalid(SUDOKU_ERR_ARGUMENT, &error);
        if (compact) puts(count >= 2u ? "2+" : (count == 1u ? "1" : "0"));
        else printf("Solutions: %s (counted %u%s)\n", sudoku_solve_status_text(result),
                    count, count == 2u ? "+" : "");
        return 0;
    }
    if (strcmp(action, "solve") == 0) {
        SudokuBoard solution;
        SudokuSolveStatus result = sudoku_solve_first(&board, &solution);
        if (result == SUDOKU_SOLVE_UNSOLVABLE) {
            fputs("Puzzle has no solution\n", stderr);
            return 5;
        }
        if (result == SUDOKU_SOLVE_INVALID) return invalid(SUDOKU_ERR_ARGUMENT, &error);
        if (result == SUDOKU_SOLVE_MULTIPLE)
            fputs("Warning: puzzle has multiple solutions; displaying deterministic first\n", stderr);
        if (compact) {
            char solved[82];
            sudoku_board_compact(&solution, solved);
            puts(solved);
        } else {
            printf("Solved puzzle (%s):\n", sudoku_solve_status_text(result));
            display(&solution);
        }
        return 0;
    }
    if (compact) {
        char result[82];
        sudoku_board_compact(&board, result);
        puts(result);
    } else {
        puts("Valid puzzle: givens do not conflict (solvability not checked).");
        display(&board);
    }
    return 0;
}
