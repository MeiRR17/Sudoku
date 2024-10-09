#include <stdio.h>
#include "sudoku.h"

int UNSOLVED = 81;
int SIZE_ROWS = 9;
int SIZE_COLUMNS = 9;

int main() {
    int ** puzzle;
    Square *** sudoku;

    puzzle = createPuzzle();  // Initialize the puzzle

    sudoku = setUpPuzzle(puzzle);  // Convert puzzle to the sudoku structure

    printPuzzle(sudoku);  // Print the initial state of the puzzle

    checkPuzzle(sudoku);  // Check the puzzle and attempt to solve it

    printf("\n\n");  // Correctly print two new lines instead of passing to printPuzzle

    printPuzzle(sudoku);  // Print the updated puzzle after solving

    return 0;
}
