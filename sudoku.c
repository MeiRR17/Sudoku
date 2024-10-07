#include <stdio.h>
#include "sudoku.h"

int main() {
    int ** puzzle;

    puzzle = createPuzzle();

    printPuzzle(puzzle);

    return 0;
}
