#include "sudoku.h"

int solveSquare(Square *square) {
    int i;
    if (!square || square->number != 0 || square->solvable != 1) return 0;
    for (i = 0; i < 9; ++i) {
        if (square->possible[i] == 0) {
            square->number = i + 1;
            square->solvable = 0;
            --UNSOLVED;
            return 1;
        }
    }
    return 0;
}
