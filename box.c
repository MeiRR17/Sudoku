#include "sudoku.h"
#include <stdlib.h>

Box **createBoxes(void) {
    int i;
    Box **boxes = calloc(9, sizeof(*boxes));
    if (!boxes) return NULL;
    for (i = 0; i < 9; ++i) {
        boxes[i] = calloc(1, sizeof(*boxes[i]));
        if (!boxes[i]) { destroyBoxes(boxes); return NULL; }
        boxes[i]->squares = calloc(9, sizeof(*boxes[i]->squares));
        if (!boxes[i]->squares) { destroyBoxes(boxes); return NULL; }
        boxes[i]->numbers = 0;
        boxes[i]->solvable = 9;
    }
    return boxes;
}

void destroyBoxes(Box **boxes) {
    int i;
    if (!boxes) return;
    for (i = 0; i < 9; ++i) {
        if (boxes[i]) {
            free(boxes[i]->squares);
            free(boxes[i]);
        }
    }
    free(boxes);
}

int updateBoxes(Square ***squares, int row, int column) {
    Box *box;
    int number, i;
    if (!squares || row < 0 || row >= 9 || column < 0 || column >= 9 || !squares[row] || !squares[row][column]) return 0;
    number = squares[row][column]->number;
    if (number < 1 || number > 9) return 0;
    box = squares[row][column]->box;
    if (!box) return 0;
    for (i = 0; i < 9; ++i) {
        Square *peer = box->squares[i];
        if (peer && peer->number == 0 && peer->possible[number - 1] == 0) {
            peer->possible[number - 1] = 1;
            --peer->solvable;
        }
    }
    return 1;
}

int boxSingles(Square ***squares, Box **boxes) {
    int i, j, x;
    for (i = 0; i < 9; ++i) {
        for (j = 0; j < 9; ++j) {
            int count = 0, index = -1;
            int alreadyPlaced = 0;
            for (x = 0; x < 9; ++x) {
                Square *square = boxes[i]->squares[x];
                if (square->number == j + 1) { alreadyPlaced = 1; break; }
            }
            if (alreadyPlaced) continue;
            for (x = 0; x < 9; ++x) {
                Square *square = boxes[i]->squares[x];
                if (square->number == 0 && square->possible[j] == 0) {
                    ++count;
                    index = x;
                    if (count >= 2) break;
                }
            }
            if (count == 1) {
                Square *square = boxes[i]->squares[index];
                square->number = j + 1;
                square->solvable = 0;
                --UNSOLVED;
                updateSudoku(squares, square->row, square->column);
                updateBoxes(squares, square->row, square->column);
                return 1;
            }
        }
    }
    return 0;
}
