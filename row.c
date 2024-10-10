#include "sudoku.h"

int checkRows(Square*** sudoku, Box** boxes) {
    int i, j, x;

    int sum[9];
    int place[9];

    for (i = 0; i < 9; i++) {
        for (j = 0; j < 9; j++) {
            place[j] = 0;
            sum[j] = 0;
        }


        for (j = 0; j < 9; j++) {
            if (sudoku[i][j] != 0) {
                continue;
            }
            for (x = 0; x < 9; x++) {
                if (sudoku[i][j]->possible[x] == 0) {
                    sum[x]++;
                    place[x] = j;
                }
            }
        }
        for (j = 0; j < 9; j++) {
            if (sum[j] == 1) {
                sudoku[i][place[x]]->number = x + 1;
                sudoku[i][place[x]]->solvable = 0;

                updateSudoku(sudoku, i, place[x]);
                updateBoxes(sudoku, i, place[x]);

                return 1;
            }
        }

    }
    return 0;
}