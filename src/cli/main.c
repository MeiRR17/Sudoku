#if !defined(_WIN32)
#define _POSIX_C_SOURCE 200809L
#endif
#include "sudoku/board.h"
#include "sudoku/solver.h"
#include "sudoku/generator.h"
#include "sudoku/play.h"
#include <inttypes.h>
#include <stdint.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#if defined(_WIN32)
#include <windows.h>
#include <io.h>
#else
#include <unistd.h>
#include <sys/stat.h>
#endif

typedef enum Command { CMD_VALIDATE, CMD_SOLVE, CMD_COUNT, CMD_GENERATE } Command;
typedef enum Format { FMT_TEXT, FMT_COMPACT, FMT_JSON } Format;

typedef struct Options {
    Command command;
    Format format;
    const char *puzzle;
    const char *input_path;
    const char *output_path;
    int quiet;
    SudokuGenerateOptions generation;
    int seed_supplied;
    int difficulty_supplied;
    int generation_option_supplied;
} Options;

typedef struct Result {
    SudokuBoard board;
    SudokuBoard solution;
    SudokuSolveStatus classification;
    unsigned count;
    SudokuGenerateResult generated;
} Result;

static const char demo[] =
    "300000020080432010050000600074860000000000008"
    "030100700000296871600000340190700006";

static void help(FILE *output) {
    fputs("Sudoku 0.8.4 (experimental): offline exact solver\n"
          "Usage: sudoku {validate|solve|count} (--puzzle DIGITS | --file PATH | --stdin) [OPTIONS]\n"
          "       sudoku generate --seed UINT32 --difficulty easy|medium|hard [OPTIONS]\n"
          "       sudoku play (--puzzle DIGITS | --file PATH | --resume SAVE | --seed UINT32 --difficulty easy|medium|hard) [--save PATH]\n"
          "       sudoku --demo | --version | --help\n"
          "Options:\n"
          "  --format text|compact|json  Result encoding (default text)\n"
          "  --output PATH               Save result to a NEW file, refuse overwrite; '-' is stdout\n"
          "  --quiet                     Suppress non-unique solution warning\n"
          "Generate: --symmetry none|rotational (default none)\n"
          "          --max-attempts 1..100 (default 20), --max-checks 1..10000 (default 2000)\n"
          "          --max-nodes 1..1000000 (default 50000), --max-ms 1..60000 (default 5000)\n"
          "Input: exactly 81 ASCII digits 0..9, optional ASCII whitespace; 0 is empty.\n"
          "       --file - is equivalent to --stdin. Input limit: 1 MiB.\n"
          "Exit: 0 success, 2 usage, 3 invalid input/board, 4 I/O error, 5 no solution, 6 generation budget.\n"
          "JSON success schema: docs/CLI_JSON_SCHEMA.md (schema_version=1).\n"
          "Errors go to stderr, never to JSON/stdout; count 0 is successful.\n",
          output);
}

static int usage_error(const char *detail) {
    fprintf(stderr, "Usage error: %s. Try 'sudoku --help'.\n", detail);
    return 2;
}

/* Strict, locale-independent unsigned decimal parsing: reject signs, overflow
 * and all trailing bytes. Bounded values are checked before casting. */
static int parse_unsigned(const char *value, uint64_t maximum, uint64_t *out) {
    uint64_t x = 0;
    const unsigned char *p = (const unsigned char *)value;
    if (!*p) return 0;
    while (*p) {
        unsigned digit;
        if (*p < '0' || *p > '9') return 0;
        digit = (unsigned)(*p++ - '0');
        if (x > (maximum - digit) / 10u) return 0;
        x = x * 10u + digit;
    }
    *out = x;
    return 1;
}

static int parse_options(int argc, char **argv, Options *opt) {
    int i;
    int format_seen = 0;
    int output_seen = 0;
    int symmetry_seen = 0, attempts_seen = 0, checks_seen = 0, nodes_seen = 0, ms_seen = 0;
    opt->generation.max_attempts = 20u;
    opt->generation.max_checks = 2000u;
    opt->generation.max_nodes = UINT64_C(50000);
    opt->generation.max_cpu_ms = 5000u;
    if (argc < 3) return usage_error("missing command or input");
    if (strcmp(argv[1], "validate") == 0) opt->command = CMD_VALIDATE;
    else if (strcmp(argv[1], "solve") == 0) opt->command = CMD_SOLVE;
    else if (strcmp(argv[1], "count") == 0) opt->command = CMD_COUNT;
    else if (strcmp(argv[1], "generate") == 0) opt->command = CMD_GENERATE;
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
        } else if (strcmp(arg, "--seed") == 0 ||
                   strcmp(arg, "--max-attempts") == 0 ||
                   strcmp(arg, "--max-checks") == 0 ||
                   strcmp(arg, "--max-nodes") == 0 ||
                   strcmp(arg, "--max-ms") == 0) {
            uint64_t parsed;
            unsigned is_seed = strcmp(arg, "--seed") == 0;
            unsigned is_attempts = strcmp(arg, "--max-attempts") == 0;
            unsigned is_checks = strcmp(arg, "--max-checks") == 0;
            unsigned is_nodes = strcmp(arg, "--max-nodes") == 0;
            unsigned is_ms = strcmp(arg, "--max-ms") == 0;
            uint64_t max = is_seed ? UINT32_MAX : is_attempts ? 100u : is_checks ? 10000u : is_nodes ? 1000000u : 60000u;
            if ((is_seed && opt->seed_supplied) || (is_attempts && attempts_seen) ||
                (is_checks && checks_seen) || (is_nodes && nodes_seen) || (is_ms && ms_seen) ||
                ++i >= argc || !parse_unsigned(argv[i], max, &parsed))
                return usage_error("invalid or repeated generation limit/seed");
            if (!is_seed && parsed == 0u) return usage_error("generation limits must be positive");
            if (is_seed) { opt->seed_supplied = 1; opt->generation.seed = (uint32_t)parsed; }
            if (is_attempts) { attempts_seen = 1; opt->generation.max_attempts = (unsigned)parsed; }
            if (is_checks) { checks_seen = 1; opt->generation.max_checks = (unsigned)parsed; }
            if (is_nodes) { nodes_seen = 1; opt->generation.max_nodes = parsed; }
            if (is_ms) { ms_seen = 1; opt->generation.max_cpu_ms = (unsigned)parsed; }
            opt->generation_option_supplied = 1;
        } else if (strcmp(arg, "--difficulty") == 0) {
            if (opt->difficulty_supplied || ++i >= argc) return usage_error("missing or repeated difficulty");
            opt->difficulty_supplied = 1;
            if (strcmp(argv[i], "easy") == 0) opt->generation.difficulty = SUDOKU_DIFFICULTY_EASY;
            else if (strcmp(argv[i], "medium") == 0) opt->generation.difficulty = SUDOKU_DIFFICULTY_MEDIUM;
            else if (strcmp(argv[i], "hard") == 0) opt->generation.difficulty = SUDOKU_DIFFICULTY_HARD;
            else return usage_error("difficulty must be easy, medium or hard");
            opt->generation_option_supplied = 1;
        } else if (strcmp(arg, "--symmetry") == 0) {
            if (symmetry_seen || ++i >= argc) return usage_error("missing or repeated symmetry");
            symmetry_seen = 1;
            if (strcmp(argv[i], "none") == 0) opt->generation.rotational = 0;
            else if (strcmp(argv[i], "rotational") == 0) opt->generation.rotational = 1;
            else return usage_error("symmetry must be none or rotational");
            opt->generation_option_supplied = 1;
        } else if (strcmp(arg, "--quiet") == 0) {
            if (opt->quiet) return usage_error("repeated --quiet");
            opt->quiet = 1;
        } else return usage_error("unknown option");
    }
    if (opt->command == CMD_GENERATE) {
        if (opt->puzzle != NULL || opt->input_path != NULL || opt->quiet)
            return usage_error("generate takes no puzzle input or --quiet");
        if (!opt->seed_supplied || !opt->difficulty_supplied)
            return usage_error("generate requires --seed and --difficulty");
    } else {
        if (opt->generation_option_supplied)
            return usage_error("generation options are valid only for generate");
        if (opt->puzzle == NULL && opt->input_path == NULL)
            return usage_error("specify --puzzle, --file or --stdin");
    }
    return 0;
}

/* Read at most 1MiB plus one byte for reliable over-limit detection. */
/* A single bounded fread avoids retrying a stream after EOF or an I/O error.
 * Requesting 1 MiB + 1 byte permits exact oversized-input classification. */
static int read_all(FILE *stream, unsigned char **out, size_t *length) {
    const size_t capacity = SUDOKU_MAX_INPUT_BYTES + 1u;
    unsigned char *data = malloc(capacity);
    size_t count;
    if (data == NULL) { errno = ENOMEM; return -1; }
    count = fread(data, 1u, capacity, stream);
    if (ferror(stream)) { free(data); return -1; }
    *out = data;
    *length = count;
    return 0;
}

/* Keep ownership of a newly opened stream inside a dedicated helper.
 * fclose runs on both successful and failed reads; stdin is not closed. */
static int read_from_path(const char *path, unsigned char **out, size_t *length) {
    FILE *input = fopen(path, "rb");
    int result, close_result;
    int read_errno;
    if (input == NULL) {
        fprintf(stderr, "Input open failed: %s\n", strerror(errno));
        return 4;
    }
    result = read_all(input, out, length);
    read_errno = errno;
    close_result = fclose(input);
    if (result != 0) {
        fprintf(stderr, "Input read failed: %s\n", strerror(read_errno));
        return 4;
    }
    if (close_result != 0) {
        free(*out);
        *out = NULL;
        fputs("Input close failed\n", stderr);
        return 4;
    }
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
        int result;
        if (strcmp(opt->input_path, "-") == 0) {
            if (read_all(stdin, &data, &length) != 0) {
                fprintf(stderr, "Input read failed: %s\n", strerror(errno));
                return 4;
            }
        } else {
            result = read_from_path(opt->input_path, &data, &length);
            if (result != 0) return result;
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
    if (opt->command == CMD_GENERATE) {
        sudoku_board_compact(&result->generated.solution, solution);
        fprintf(stream, "{\"schema_version\":1,\"command\":\"generate\",\"status\":\"unique\",\"puzzle\":\"%s\",\"solution\":\"%s\",\"solutions_found\":1,\"seed\":%" PRIu32 ",\"difficulty\":\"%s\",\"symmetry\":\"%s\",\"clues\":%u,\"naked_singles\":%u,\"hidden_singles\":%u,\"attempts\":%u,\"checks\":%u}\n",
                puzzle, solution, opt->generation.seed,
                sudoku_difficulty_text(result->generated.rated),
                opt->generation.rotational ? "rotational" : "none",
                result->generated.clues, result->generated.naked_singles,
                result->generated.hidden_singles, result->generated.attempts,
                result->generated.checks);
    } else if (opt->command == CMD_VALIDATE) {
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
    if (opt->command == CMD_GENERATE) {
        fprintf(stream, "Generated puzzle (seed=%" PRIu32 ", difficulty=%s, clues=%u, symmetry=%s, checks=%u):\n",
                opt->generation.seed, sudoku_difficulty_text(result->generated.rated),
                result->generated.clues, opt->generation.rotational ? "rotational" : "none",
                result->generated.checks);
        display(stream, &result->board);
    } else if (opt->command == CMD_COUNT) {
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

/* Stage complete CLI output before an atomic, no-overwrite publication.
 * POSIX mkstemp creates a mode-0600 sibling; link refuses any existing
 * destination including symlinks. Windows MoveFileEx without REPLACE_EXISTING
 * similarly rejects an existing destination. A crash before publication can
 * leave an orphaned temp file, but never a partial final output. */
static FILE *open_result_stage(const char *path, char *stage, size_t capacity) {
#if defined(_WIN32)
    static unsigned serial = 0;
    unsigned attempt;
    for (attempt = 0; attempt < 64u; ++attempt) {
        FILE *file;
        (void)snprintf(stage, capacity, "%s.tmp.%08lX.%08X",
                       path, (unsigned long)time(NULL), ++serial);
        file = fopen(stage, "wbx");
        if (file != NULL) return file;
        if (errno != EEXIST) return NULL;
    }
    errno = EEXIST;
    return NULL;
#else
    int fd;
    FILE *file;
    (void)snprintf(stage, capacity, "%s.tmp.XXXXXX", path);
    fd = mkstemp(stage);
    if (fd < 0) return NULL;
    file = fdopen(fd, "wb");
    if (file == NULL) {
        int reason = errno;
        (void)close(fd);
        (void)remove(stage);
        errno = reason;
        return NULL;
    }
    /* mkstemp creates an owner-only inode; reassert mode 0600 even
     * if umask removed the owner's access, before writing result bytes. */
    if (fchmod(fileno(file), S_IRUSR | S_IWUSR) != 0) {
        int reason = errno;
        (void)fclose(file);
        (void)remove(stage);
        errno = reason;
        return NULL;
    }
    return file;
#endif
}

static int publish_result(const Options *opt, const Result *result) {
    FILE *output = stdout;
    char *stage = NULL;
    int failure, publish_failed = 0;
    int new_file = opt->output_path != NULL && strcmp(opt->output_path, "-") != 0;
    if (new_file) {
        size_t length = strlen(opt->output_path);
        if (length > 4096u) {
            fputs("Output create failed: path too long\n", stderr);
            return 4;
        }
        stage = malloc(length + 64u);
        if (stage == NULL) {
            fputs("Output create failed: out of memory\n", stderr);
            return 4;
        }
        output = open_result_stage(opt->output_path, stage, length + 64u);
        if (output == NULL) {
            fprintf(stderr, "Output create failed (existing files are never overwritten): %s\n",
                    strerror(errno));
            free(stage);
            return 4;
        }
    }
    print_result(output, opt, result);
    failure = ferror(output) != 0;
    if (new_file) {
        if (!failure && fflush(output) != 0) failure = 1;
#if defined(_WIN32)
        if (!failure && _commit(_fileno(output)) != 0) failure = 1;
#else
        if (!failure && fsync(fileno(output)) != 0) failure = 1;
#endif
        if (fclose(output) != 0) failure = 1;
        if (!failure) {
#if defined(_WIN32)
            /* No MOVEFILE_REPLACE_EXISTING: never clobber a concurrent writer. */
            publish_failed = MoveFileExA(stage, opt->output_path,
                                        MOVEFILE_WRITE_THROUGH) == 0;
#else
            /* An atomic link cannot replace a concurrent destination. */
            publish_failed = link(stage, opt->output_path) != 0;
#endif
        }
        (void)remove(stage);
        free(stage);
    } else if (fflush(output) != 0) {
        failure = 1;
    }
    if (publish_failed) {
        fputs("Output create failed (existing files are never overwritten)\n", stderr);
        return 4;
    }
    if (failure) { fputs("Output write failed\n", stderr); return 4; }
    return 0;
}

int main(int argc, char **argv) {
    Options opt = {0};
    Result result = {0};
    int parsed, status;
    if (argc >= 2 && strcmp(argv[1], "play") == 0) return sudoku_play_main(argc,argv);
    if (argc == 2 && strcmp(argv[1], "--help") == 0) { help(stdout); return 0; }
    if (argc == 2 && strcmp(argv[1], "--version") == 0) {
        puts("Sudoku 0.8.4 (experimental)"); return 0;
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
    if (opt.command == CMD_GENERATE) {
        SudokuGenerateStatus generated = sudoku_generate(&opt.generation, &result.generated);
        if (generated != SUDOKU_GENERATE_OK) {
            fprintf(stderr, "Generation failed: %s\n", sudoku_generate_status_text(generated));
            return generated == SUDOKU_GENERATE_INVALID ? 2 : 6;
        }
        result.board = result.generated.puzzle;
        result.solution = result.generated.solution;
        result.count = 1;
        result.classification = SUDOKU_SOLVE_UNIQUE;
        return publish_result(&opt, &result);
    }
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
