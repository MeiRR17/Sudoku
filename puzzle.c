#include "sudoku.h"
#include <stdio.h>
#include <stdlib.h>

Sudoku* createSudoku(Square*** squares, Box** boxes) {
    Sudoku* sudoku;
    sudoku = malloc(sizeof(Sudoku));

    sudoku->squares = squares;
    sudoku->boxes = boxes;

    return sudoku;
}

Sudoku* setUpPuzzle(int** puzzle) {
    Square***  squares = (Square***)malloc(sizeof(Square**)*9);
    Box** boxes = createBoxes();  // Declare boxes
    int i, j, x;
    int currentBox = 0;

    for (i = 0; i < SIZE_ROWS; i++) {
        squares[i] = (Square**)malloc(sizeof(Square*)*9);
        for (j = 0; j < SIZE_COLUMNS; j++) {
            squares[i][j] = (Square*)malloc(sizeof(Square));
            squares[i][j]->number = puzzle[i][j];
            squares[i][j]->row = i;
            squares[i][j]->column = j;
            squares[i][j]->solvable = 9;  // Fix typo

            // Associate square with box
            boxes[currentBox]->squares[boxes[currentBox]->numbers] = squares[i][j];
            squares[i][j]->box = boxes[currentBox];
            boxes[currentBox]->numbers++;

            // Initialize possible numbers
            for (x = 0; x < SIZE_ROWS; x++) {
                squares[i][j]->possible[x] = 0;
            }

            // Adjust currentBox index
            if (j == 2 || j == 5) {
                currentBox++;
            }
        }
        currentBox -= 2;
        if (i == 2 || i == 5) {
            currentBox += 3;
        }
    }

    // Update Sudoku after setup
    for (i = 0; i < SIZE_ROWS; i++) {
        for (j = 0; j < SIZE_COLUMNS; j++) {
            if (squares[i][j]->solvable == 0) {  // Fix comparison
                updateSudoku(squares, i, j);
                updateBoxes(squares, i, j);
                UNSOLVED--;
            }
        }
    }
    return createSudoku(squares, boxes);  // Return Sudoku structure
}

int checkPuzzle(Square*** sudoku, Box** boxes) {
    int i, j;
    for (i = 0; i < SIZE_ROWS; i++) {
        for (j = 0; j < SIZE_COLUMNS; j++) {
            if(sudoku[i][j] -> solvable == 1) {
                solveSquare(sudoku[i][j]);
                updateSudoku(sudoku, i, j);
                updateBoxes(sudoku, i, j);
                return 1;
            }
        }
    }
    if (boxSingles(sudoku, boxes)) {
        return 1;
    }
    return checkRows(sudoku, boxes);
}

int ** createPuzzle() {
    int ** puzzle;
    int i, j;

    int arr[9][9] = {3, 0, 0,   0, 0, 0,    0, 2, 0,
                     0, 8, 0,   4, 3, 2,    0, 1, 0,
                     0, 5, 0,   0, 0, 0,    6, 0, 0,

                     0, 7, 4,   8, 6, 0,    0, 0, 0,
                     0, 0, 0,   0, 0, 0,    0, 0, 8,
                     0, 3, 0,   1, 0, 0,    7, 0, 0,

                     0, 0, 0,   2, 9, 6,    8, 7, 1,
                     6, 0, 0,   0, 0, 0,    3, 4, 0,
                     1, 9, 0,   7, 0, 0,    0, 0, 6,};

    puzzle = (int**)malloc(sizeof(int*)*9);
    for (i = 0; i < 9; i++) {
        puzzle[i] = (int*)malloc(sizeof(int)*9);

        for (j = 0; j < 9; j++) {
            puzzle[i][j] = arr[i][j];
        }
    }
    return puzzle;
}

int updateSudoku(Square*** sudoku, int row, int col) {
    int x;
    int number = sudoku[row][col] -> number;

    for (x = 0; x < SIZE_ROWS; x++) {
        if (sudoku[x][col] -> possible[number - 1] == 0) {
            sudoku[x][col] -> solvable--;
        }
        sudoku[x][col] -> possible[number - 1] = 1;
    }

    for (x = 0; x < SIZE_COLUMNS; x++) {
        if (sudoku[row][x] -> possible[number - 1] == 0) {
            sudoku[row][x] -> solvable--;
        }
        sudoku[row][x] -> possible[number - 1] = 1;
    }
    return 1;
}

void printPuzzle(Square*** puzzle) {
    int i, j;

    printf("Puzzle:\n");
    printf("-------------------------------\n");
    for (i = 0; i < SIZE_ROWS; i++) {
        printf("|");
        //print each row
        for (j = 0; j < SIZE_COLUMNS; j++) {
            printf(" %d ", puzzle[i][j] -> number);
            if((j +1) % 3 == 0) {
                printf("|");
            }
        }
        printf("\n");
        if ((i + 1) % 3 == 0) {
            printf("-------------------------------\n");
        }
    }
}
