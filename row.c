#include "sudoku.h"

int checkRows(Square ***squares, Box **boxes) {
    int i, j, x;
    (void)boxes;
    for (i = 0; i < 9; ++i) {
        int sum[9] = {0};
        int place[9] = {0};
        for (j = 0; j < 9; ++j) {
            if (squares[i][j]->number != 0) continue;
            for (x = 0; x < 9; ++x) {
                if (squares[i][j]->possible[x] == 0) {
                    ++sum[x];
                    place[x] = j;
                }
            }
        }
        for (j = 0; j < 9; ++j) {
            if (sum[j] == 1) {
                Square *square = squares[i][place[j]];
                square->number = j + 1;
                square->solvable = 0;
                --UNSOLVED;
                updateSudoku(squares, i, place[j]);
                updateBoxes(squares, i, place[j]);
                return 1;
            }
        }
    }
    return 0;
}
