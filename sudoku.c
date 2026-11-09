#include <stdio.h>
#include <string.h>
#include "sudoku.h"

int UNSOLVED = 81;
int SIZE_ROWS = 9;
int SIZE_COLUMNS = 9;

static void usage(const char *program) {
    printf("Usage: %s [--help | --version | --demo]\n", program);
    printf("  --help       Show build-recovery usage information\n");
    printf("  --version    Print the development version\n");
    printf("  --demo       Run the historical, incomplete solver demo\n");
    puts("No arguments also run --demo for backward compatibility.");
    puts("This v0.1.0 prototype is not a validated Sudoku solver.");
}

int main(int argc, char **argv) {
    int **puzzle;
    Sudoku *sudoku;
    int progress;
    int steps = 0;

    if (argc > 2) {
        usage(argv[0]);
        return 2;
    }
    if (argc == 2) {
        if (strcmp(argv[1], "--help") == 0) {
            usage(argv[0]);
            return 0;
        }
        if (strcmp(argv[1], "--version") == 0) {
            puts("Sudoku 0.1.0 (experimental)");
            return 0;
        }
        if (strcmp(argv[1], "--demo") != 0) {
            fprintf(stderr, "Unsupported option: %s\n", argv[1]);
            usage(argv[0]);
            return 2;
        }
    }

    UNSOLVED = 81;
    puzzle = createPuzzle();
    if (!puzzle) {
        fputs("Failed to allocate example puzzle\n", stderr);
        return 1;
    }
    sudoku = setUpPuzzle(puzzle);
    destroyPuzzle(puzzle);
    if (!sudoku) {
        fputs("Failed to initialize example puzzle\n", stderr);
        return 1;
    }

    puts("Experimental demonstration; solutions are not verified in v0.1.0.");
    printPuzzle(sudoku->squares);

    while (UNSOLVED > 0 && steps < 81) {
        progress = checkPuzzle(sudoku->squares, sudoku->boxes);
        if (progress == 0) {
            puts("\nThe historical solver could not complete this puzzle.");
            break;
        }
        ++steps;
    }

    if (UNSOLVED > 0 && steps >= 81) {
        puts("Historical solver stopped after its move safety limit.");
    }
    printPuzzle(sudoku->squares);
    destroySudoku(sudoku);
    return 0;
}
