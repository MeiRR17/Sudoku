#include "sudoku/board.h"
#include "sudoku/candidates.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct CandidateOptions {
    const char *puzzle;
    const char *path;
    int json;
    int singles_only;
} CandidateOptions;

static int usage(const char *message) {
    if (message != NULL) fprintf(stderr, "Usage error: %s\n", message);
    fputs("Usage: sudoku-candidates (--puzzle DIGITS | --file PATH)"
          " [--format text|json] [--singles-only]\n", stderr);
    return 2;
}

static int parse(int argc, char **argv, CandidateOptions *options) {
    int i, format_seen = 0;
    if (argc < 3) return usage("specify one puzzle source");
    for (i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--puzzle") == 0 || strcmp(argv[i], "--file") == 0) {
            const int is_puzzle = strcmp(argv[i], "--puzzle") == 0;
            if (options->puzzle != NULL || options->path != NULL
                || i + 1 >= argc || argv[i + 1][0] == '\0') {
                return usage("specify exactly one nonempty source");
            }
            ++i;
            if (is_puzzle) options->puzzle = argv[i];
            else options->path = argv[i];
        } else if (strcmp(argv[i], "--format") == 0) {
            if (format_seen || i + 1 >= argc) return usage("missing or repeated format");
            ++i;
            format_seen = 1;
            if (strcmp(argv[i], "json") == 0) options->json = 1;
            else if (strcmp(argv[i], "text") == 0) options->json = 0;
            else return usage("format must be text or json");
        } else if (strcmp(argv[i], "--singles-only") == 0) {
            if (options->singles_only) return usage("repeated --singles-only");
            options->singles_only = 1;
        } else {
            return usage("unknown argument");
        }
    }
    if (options->path == NULL && options->puzzle == NULL) {
        return usage("missing puzzle source");
    }
    return 0;
}

static int read_puzzle(const CandidateOptions *options, SudokuBoard *board) {
    SudokuError error;
    SudokuStatus result;
    const unsigned char *bytes;
    unsigned char *buffer = NULL;
    size_t count;
    FILE *input;

    if (options->puzzle != NULL) {
        bytes = (const unsigned char *)options->puzzle;
        count = strlen(options->puzzle);
    } else {
        buffer = (unsigned char *)malloc(SUDOKU_MAX_INPUT_BYTES + 1u);
        if (buffer == NULL) {
            fputs("Memory allocation failed\n", stderr);
            return 4;
        }
        input = fopen(options->path, "rb");
        if (input == NULL) {
            fputs("Cannot open puzzle file\n", stderr);
            free(buffer);
            return 4;
        }
        count = fread(buffer, 1u, SUDOKU_MAX_INPUT_BYTES + 1u, input);
        if (ferror(input)) {
            fputs("Cannot read puzzle file\n", stderr);
            (void)fclose(input);
            free(buffer);
            return 4;
        }
        if (fclose(input) != 0) {
            fputs("Cannot close puzzle file\n", stderr);
            free(buffer);
            return 4;
        }
        bytes = buffer;
    }

    result = sudoku_board_parse(board, bytes, count, &error);
    free(buffer);
    if (result != SUDOKU_OK) {
        fprintf(stderr, "Invalid puzzle: %s\n", sudoku_status_text(result));
        return 3;
    }
    return 0;
}

static unsigned digits_for_mask(uint16_t mask, char digits[10]) {
    unsigned digit, used = 0u;
    for (digit = 1u; digit <= 9u; ++digit) {
        if ((mask & (1u << digit)) != 0u) digits[used++] = (char)('0' + digit);
    }
    digits[used] = '\0';
    return used;
}

static void print_json(const SudokuBoard *board, const SudokuCandidateMap *map,
                       int singles_only) {
    unsigned row, col, emitted = 0u;
    printf("{\"schema_version\":1,\"kind\":\"local_candidates\","
           "\"solvability\":\"not_checked\",\"empty_cells\":%u,"
           "\"naked_singles\":%u,\"zero_candidate_cells\":%u,"
           "\"singles_only\":%s,\"cells\":[",
           map->empty_count, map->naked_single_count, map->zero_candidate_count,
           singles_only ? "true" : "false");

    for (row = 0u; row < SUDOKU_SIDE; ++row) {
        for (col = 0u; col < SUDOKU_SIDE; ++col) {
            const unsigned index = row * SUDOKU_SIDE + col;
            uint16_t mask;
            unsigned count;
            char digits[10];
            if (board->cells[index] != 0u) continue;
            mask = map->masks[index];
            count = digits_for_mask(mask, digits);
            if (singles_only && count != 1u && count != 0u) continue;
            if (emitted++) putchar(',');
            printf("{\"row\":%u,\"column\":%u,\"candidates\":\"%s\","
                   "\"candidate_count\":%u,\"naked_single\":%s}",
                   row + 1u, col + 1u, digits, count, count == 1u ? "true" : "false");
        }
    }
    puts("],\"note\":\"Candidate legality alone cannot prove solvability or uniqueness.\"}");
}

static void print_text(const SudokuBoard *board, const SudokuCandidateMap *map,
                       int singles_only) {
    unsigned row, col;
    printf("LOCAL CANDIDATES (not a solution): empty=%u, singles=%u,"
           " zero-candidate=%u\n", map->empty_count,
           map->naked_single_count, map->zero_candidate_count);
    for (row = 0u; row < SUDOKU_SIDE; ++row) {
        for (col = 0u; col < SUDOKU_SIDE; ++col) {
            const unsigned index = row * SUDOKU_SIDE + col;
            char digits[10];
            unsigned count;
            if (board->cells[index] != 0u) continue;
            count = digits_for_mask(map->masks[index], digits);
            if (singles_only && count != 1u && count != 0u) continue;
            printf("R%uC%u: %s%s\n", row + 1u, col + 1u,
                   count == 0u ? "(none)" : digits,
                   count == 1u ? " (single)" : count == 0u ? " (local contradiction)" : "");
        }
    }
    puts("No exact solver was run; local candidates are not global proof.");
}

int main(int argc, char **argv) {
    CandidateOptions options = {0};
    SudokuBoard board = {{0}};
    SudokuCandidateMap map;
    SudokuStatus status;
    int result = parse(argc, argv, &options);
    if (result != 0) return result;
    result = read_puzzle(&options, &board);
    if (result != 0) return result;
    status = sudoku_candidate_map(&board, &map);
    if (status != SUDOKU_OK) {
        fprintf(stderr, "Invalid puzzle: %s\n", sudoku_status_text(status));
        return 3;
    }
    if (options.json) print_json(&board, &map, options.singles_only);
    else print_text(&board, &map, options.singles_only);
    return 0;
}
