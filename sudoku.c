#include <stdio.h>
#include "sudoku.h"

int UNSOLVED = 81;
int SIZE_ROWS = 9;
int SIZE_COLUMNS = 9;

int main() {
    int ** puzzle;
    int progress;
    Sudoku * sudoku;  // Change to Sudoku*

    puzzle = createPuzzle();  // Initialize the puzzle

    sudoku = setUpPuzzle(puzzle);  // Convert puzzle to the sudoku structure

    printPuzzle(sudoku->squares);  // Print the initial state of the puzzle

    while (UNSOLVED > 0) {
        progress = checkPuzzle(sudoku->squares, sudoku->boxes);

        if (progress == 0) {
            printf("\nFailed to solve puzzle\n");
            break;
        }
    }

    printPuzzle(sudoku->squares);  // Print the updated puzzle after solving

    return 0;
}
