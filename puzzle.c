#include "sudoku.h"
#include <stdio.h>
#include <stdlib.h>

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

void printPuzzle(int** puzzle) {
    int i, j;

    printf("Puzzle:\n");
    printf("-------------------------------\n");
    for (i = 0; i < 9; i++) {
        printf("|");
        //print each row
        for (j = 0; j < 9; j++) {
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
