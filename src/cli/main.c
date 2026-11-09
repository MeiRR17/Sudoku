#include "sudoku/board.h"
#include "sudoku/solver.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef enum Command { CMD_VALIDATE, CMD_SOLVE, CMD_COUNT } Command;
typedef enum Format { FMT_TEXT, FMT_COMPACT, FMT_JSON } Format;

typedef struct Options {
    Command command;
    Format format;
    const char *puzzle;
    const char *input_path;
    const char *output_path;
    int quiet;
} Options;

typedef struct Result {
    SudokuBoard board;
    SudokuBoard solution;
    SudokuSolveStatus classification;
    unsigned count;
} Result;

static const char demo[] =
    "300000020080432010050000600074860000000000008"
    "030100700000296871600000340190700006";

static void help(FILE *output) {
    fputs("Sudoku 0.4.0 (experimental): offline exact solver\n"
          "Usage: sudoku {validate|solve|count} (--puzzle DIGITS | --file PATH | --stdin) [OPTIONS]\n"
          "       sudoku --demo | --version | --help\n"
          "Options:\n"
          "  --format text|compact|json  Result encoding (default text)\n"
          "  --output PATH               Save result to a NEW file, refuse overwrite; '-' is stdout\n"
          "  --quiet                     Suppress non-unique solution warning\n"
          "Input: exactly 81 ASCII digits 0..9, optional ASCII whitespace; 0 is empty.\n"
          "       --file - is equivalent to --stdin. Input limit: 1 MiB.\n"
          "Exit: 0 success, 2 usage, 3 invalid input/board, 4 I/O error, 5 no solution for solve.\n"
          "JSON success schema: docs/CLI_JSON_SCHEMA.md (schema_version=1).\n"
          "Errors go to stderr, never to JSON/stdout; count 0 is successful.\n",
          output);
}

static int usage_error(const char *detail) {
    fprintf(stderr, "Usage error: %s. Try 'sudoku --help'.\n", detail);
    return 2;
}

static int parse_options(int argc, char **argv, Options *opt) {
    int i;
    int format_seen = 0;
    int output_seen = 0;
    if (argc < 3) return usage_error("missing command or input");
    if (strcmp(argv[1], "validate") == 0) opt->command = CMD_VALIDATE;
    else if (strcmp(argv[1], "solve") == 0) opt->command = CMD_SOLVE;
    else if (strcmp(argv[1], "count") == 0) opt->command = CMD_COUNT;
    else return usage_error("unknown command");
    for (i = 2; i < argc; ++i) {
        const char *arg = argv[i];
        if (strcmp(arg, "--help") == 0 && argc == 3) {
            help(stdout);
            return -1;
        }
        if (strcmp(arg, "--puzzle") == 0 || strcmp(arg, "--file") == 0) {
            int is_puzzle = strcmp(arg, "--puzzle") == 0;
            const char *value;
            if (opt->puzzle != NULL || opt->input_path != NULL)
                return usage_error("specify exactly one input source");
            if (++i >= argc || argv[i][0] == '\0') return usage_error("missing input argument");
            value = argv[i];
            if (is_puzzle) opt->puzzle = value;
            else opt->input_path = value;
        } else if (strcmp(arg, "--stdin") == 0) {
            if (opt->puzzle != NULL || opt->input_path != NULL)
                return usage_error("specify exactly one input source");
            opt->input_path = "-";
        } else if (strcmp(arg, "--format") == 0) {
            if (format_seen || ++i >= argc) return usage_error("missing or repeated format");
            format_seen = 1;
            if (strcmp(argv[i], "text") == 0) opt->format = FMT_TEXT;
            else if (strcmp(argv[i], "compact") == 0) opt->format = FMT_COMPACT;
            else if (strcmp(argv[i], "json") == 0) opt->format = FMT_JSON;
            else return usage_error("format must be text, compact or json");
        } else if (strcmp(arg, "--output") == 0) {
            if (output_seen || ++i >= argc || argv[i][0] == '\0')
                return usage_error("missing or repeated output path");
            output_seen = 1;
            opt->output_path = argv[i];
        } else if (strcmp(arg, "--quiet") == 0) {
            if (opt->quiet) return usage_error("repeated --quiet");
            opt->quiet = 1;
        } else return usage_error("unknown option");
    }
    if (opt->puzzle == NULL && opt->input_path == NULL)
        return usage_error("specify --puzzle, --file or --stdin");
    return 0;
}

/* Read at most 1MiB plus one byte for reliable over-limit detection. */
static int read_all(FILE *stream, unsigned char **out, size_t *length) {
    const size_t capacity = SUDOKU_MAX_INPUT_BYTES + 1u;
    unsigned char *data = malloc(capacity);
    size_t len = 0;
    if (data == NULL) { errno = ENOMEM; return -1; }
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
    if (status == SUDOKU_ERR_ROW || status == SUDOKU_ERR_COLUMN || status == SUDOKU_ERR_BOX)
        fprintf(stderr, " (digit %u at row %u col %u conflicts with row %u col %u)",
                error->digit, error->row, error->column,
                error->previous_row, error->previous_column);
    else if (status == SUDOKU_ERR_RANGE)
        fprintf(stderr, " (value %u at row %u col %u)", error->digit, error->row, error->column);
    else if (status == SUDOKU_ERR_CHARACTER)
        fprintf(stderr, " (byte offset %zu)", error->byte_offset);
    else if (status == SUDOKU_ERR_LENGTH)
        fprintf(stderr, " (found %zu digits)", error->digits_seen);
    fputc('\n', stderr);
    return 3;
}

static int load_puzzle(const Options *opt, SudokuBoard *board) {
    unsigned char *data = NULL;
    const unsigned char *source = NULL;
    size_t length = 0;
    SudokuError error;
    SudokuStatus status;
    if (opt->puzzle != NULL) {
        source = (const unsigned char *)opt->puzzle;
        length = strlen(opt->puzzle);
    } else {
        FILE *input = strcmp(opt->input_path, "-") == 0 ? stdin : fopen(opt->input_path, "rb");
        if (input == NULL) { fprintf(stderr, "Input open failed: %s\n", strerror(errno)); return 4; }
        if (read_all(input, &data, &length) != 0) {
            fprintf(stderr, "Input read failed: %s\n", strerror(errno));
            if (input != stdin) (void)fclose(input);
            return 4;
        }
        if (input != stdin && fclose(input) != 0) {
            fputs("Input close failed\n", stderr);
            free(data);
            return 4;
        }
        source = data;
    }
    status = sudoku_board_parse(board, source, length, &error);
    free(data);
    if (status != SUDOKU_OK) return invalid(status, &error);
    return 0;
}

static void display(FILE *stream, const SudokuBoard *board) {
    unsigned r, c;
    fputs("+-------+-------+-------+\n", stream);
    for (r = 0; r < SUDOKU_SIDE; ++r) {
        fputc('|', stream);
        for (c = 0; c < SUDOKU_SIDE; ++c) {
            unsigned v = board->cells[r * SUDOKU_SIDE + c];
            fputc(' ', stream);
            fputc(v ? (int)('0' + v) : '.', stream);
            if (c % 3u == 2u) fputs(" |", stream);
        }
        fputc('\n', stream);
        if (r % 3u == 2u) fputs("+-------+-------+-------+\n", stream);
    }
}

static const char *classification(SudokuSolveStatus status) {
    if (status == SUDOKU_SOLVE_UNIQUE) return "unique";
    if (status == SUDOKU_SOLVE_MULTIPLE) return "multiple";
    return "none";
}

/* JSON v1: fixed key order for reproducible golden output; no dynamic strings. */
static void print_json(FILE *stream, const Options *opt, const Result *result) {
    char puzzle[82], solution[82];
    sudoku_board_compact(&result->board, puzzle);
    if (opt->command == CMD_VALIDATE) {
        fprintf(stream, "{\"schema_version\":1,\"command\":\"validate\",\"status\":\"valid\",\"puzzle\":\"%s\"}\n", puzzle);
    } else if (opt->command == CMD_SOLVE) {
        sudoku_board_compact(&result->solution, solution);
        fprintf(stream, "{\"schema_version\":1,\"command\":\"solve\",\"status\":\"%s\",\"puzzle\":\"%s\",\"solution\":\"%s\",\"solutions_found\":%u}\n",
                classification(result->classification), puzzle, solution, result->count);
    } else {
        fprintf(stream, "{\"schema_version\":1,\"command\":\"count\",\"status\":\"%s\",\"puzzle\":\"%s\",\"solutions_found\":%u,\"capped\":%s}\n",
                classification(result->classification), puzzle, result->count,
                result->count == 2u ? "true" : "false");
    }
}

static void print_result(FILE *stream, const Options *opt, const Result *result) {
    char compact[82];
    if (opt->format == FMT_JSON) { print_json(stream, opt, result); return; }
    if (opt->format == FMT_COMPACT) {
        if (opt->command == CMD_COUNT) {
            fputs(result->count == 2u ? "2+\n" : (result->count == 1u ? "1\n" : "0\n"), stream);
            return;
        }
        sudoku_board_compact(opt->command == CMD_SOLVE ? &result->solution : &result->board, compact);
        fprintf(stream, "%s\n", compact);
        return;
    }
    if (opt->command == CMD_COUNT) {
        fprintf(stream, "Solutions: %s (counted %u%s)\n",
                sudoku_solve_status_text(result->classification), result->count,
                result->count == 2u ? "+" : "");
    } else if (opt->command == CMD_SOLVE) {
        fprintf(stream, "Solved puzzle (%s):\n", sudoku_solve_status_text(result->classification));
        display(stream, &result->solution);
    } else {
        fputs("Valid puzzle: givens do not conflict (solvability not checked).\n", stream);
        display(stream, &result->board);
    }
}

/* Refuse to overwrite an existing file; only publish results after the command succeeds.
 * C11 'x' mode creates exclusively, including failure for an existing symlink.
 * Delete newly created file if an output write/close fails. */
static int publish_result(const Options *opt, const Result *result) {
    FILE *output = stdout;
    int failure;
    int new_file = 0;
    if (opt->output_path != NULL && strcmp(opt->output_path, "-") != 0) {
        output = fopen(opt->output_path, "wbx");
        if (output == NULL) {
            fprintf(stderr, "Output create failed (existing files are never overwritten): %s\n", strerror(errno));
            return 4;
        }
        new_file = 1;
    }
    print_result(output, opt, result);
    failure = ferror(output) != 0;
    if (new_file) {
        if (fclose(output) != 0) failure = 1;
        if (failure) (void)remove(opt->output_path);
    } else if (fflush(output) != 0) failure = 1;
    if (failure) { fputs("Output write failed\n", stderr); return 4; }
    return 0;
}

int main(int argc, char **argv) {
    Options opt = {0};
    Result result = {0};
    int parsed, status;
    if (argc == 2 && strcmp(argv[1], "--help") == 0) { help(stdout); return 0; }
    if (argc == 2 && strcmp(argv[1], "--version") == 0) {
        puts("Sudoku 0.4.0 (experimental)"); return 0;
    }
    if (argc == 2 && strcmp(argv[1], "--demo") == 0) {
        SudokuBoard example, solution;
        SudokuSolveStatus solved;
        SudokuError error;
        if (sudoku_board_parse(&example, (const unsigned char *)demo,
                               sizeof demo - 1u, &error) != SUDOKU_OK)
            return invalid(error.status, &error);
        puts("Built-in example (original givens):");
        display(stdout, &example);
        solved = sudoku_solve_first(&example, &solution);
        printf("Solver result: %s\n", sudoku_solve_status_text(solved));
        if (solved == SUDOKU_SOLVE_UNIQUE || solved == SUDOKU_SOLVE_MULTIPLE)
            display(stdout, &solution);
        return solved == SUDOKU_SOLVE_UNSOLVABLE ? 5 : 0;
    }
    parsed = parse_options(argc, argv, &opt);
    if (parsed == -1) return 0;
    if (parsed != 0) return parsed;
    status = load_puzzle(&opt, &result.board);
    if (status != 0) return status;
    if (opt.command != CMD_VALIDATE) {
        result.classification = sudoku_analyze(&result.board,
                        opt.command == CMD_SOLVE ? &result.solution : NULL, &result.count);
        if (result.classification == SUDOKU_SOLVE_INVALID) {
            fputs("Internal solver error: validated puzzle was rejected\n", stderr);
            return 4;
        }
        if (opt.command == CMD_SOLVE && result.classification == SUDOKU_SOLVE_UNSOLVABLE) {
            fputs("Puzzle has no solution\n", stderr);
            return 5;
        }
        if (opt.command == CMD_SOLVE && result.classification == SUDOKU_SOLVE_MULTIPLE && !opt.quiet)
            fputs("Warning: multiple solutions; printing deterministic first solution\n", stderr);
    }
    return publish_result(&opt, &result);
}
