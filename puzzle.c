#include "sudoku.h"
#include <stdio.h>
#include <stdlib.h>

Square*** setUpPuzzle(int** puzzle) {
    Square***  sudoku;
    int i, j, x;

    sudoku = (Square***)malloc(sizeof(Square**)*9);

    for (i = 0; i < SIZE_ROWS; i++) {
        sudoku[i] = (Square**)malloc(sizeof(Square*)*9);

        for (j = 0; j < SIZE_COLUMNS; j++) {
            sudoku[i][j] = (Square*)malloc(sizeof(Square)*9);
            sudoku[i][j] -> number = puzzle[i][j];
            sudoku[i][j] -> row = i;
            sudoku[i][j] -> col = j;

            for (j = 0; j < SIZE_ROWS; j++) {
                sudoku[i][j] -> possible[x] = 0;
            }
        }
    }
    for (i = 0; i < SIZE_ROWS; i++) {
        for (j = 0; j < SIZE_COLUMNS; j++) {
            if (sudoku[i][j] -> number != 0) {
                sudoku[i][j] -> solavable = 0;
                updateSudoku(sudoku, i, j);
                UNSOLVED--;
            }
        }
    }
}

int ** createPuzzle() {
    int ** puzzle;
    int i, j;

    int arr[9][9] = {0, 0, 0,   0, 0, 0,    0, 0, 0,
                     0, 0, 0,   0, 0, 0,    0, 0, 0,
                     0, 0, 0,   0, 0, 0,    0, 0, 0,

                     0, 0, 0,   0, 0, 0,    0, 0, 0,
                     0, 0, 0,   0, 0, 0,    0, 0, 0,
                     0, 0, 0,   0, 0, 0,    0, 0, 0,

                     0, 0, 0,   0, 0, 0,    0, 0, 0,
                     0, 0, 0,   0, 0, 0,    0, 0, 0,
                     0, 0, 0,   0, 0, 0,    0, 0, 0,};

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
            sudoku[x][col] -> possible[number - 1]--;
        }
        sudoku[x][col] -> possible[number] = 1;
    }

    for (x = 0; x < SIZE_COLUMNS; x++) {
        if (sudoku[row][x] -> possible[number - 1] == 0) {
            sudoku[row][x] -> possible[number - 1]--;
        }
        sudoku[x][col] -> possible[number] = 1;
    }
    return 1;
}

void printPuzzle(int** puzzle) {
    int i, j;

    printf("Puzzle:\n");
    printf("-------------------------------\n");
    for (i = 0; i < SIZE_ROWS; i++) {
        printf("|");
        //print each row
        for (j = 0; j < SIZE_COLUMNS; j++) {
            printf(" %d ", puzzle[i][j]);
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
