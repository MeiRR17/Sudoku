#include "sudoku.h"
#include <stdio.h>
#include <stdlib.h>

static void destroySquares(Square ***squares) {
    int i, j;
    if (!squares) return;
    for (i = 0; i < 9; ++i) {
        if (!squares[i]) continue;
        for (j = 0; j < 9; ++j) free(squares[i][j]);
        free(squares[i]);
    }
    free(squares);
}

Sudoku *createSudoku(Square ***squares, Box **boxes) {
    Sudoku *sudoku = malloc(sizeof(*sudoku));
    if (!sudoku) return NULL;
    sudoku->squares = squares;
    sudoku->boxes = boxes;
    return sudoku;
}

void destroySudoku(Sudoku *sudoku) {
    if (!sudoku) return;
    destroySquares(sudoku->squares);
    destroyBoxes(sudoku->boxes);
    free(sudoku);
}

Sudoku *setUpPuzzle(int **puzzle) {
    Square ***squares = NULL;
    Box **boxes = NULL;
    Sudoku *sudoku = NULL;
    int i, j, x;
    if (!puzzle) return NULL;

    squares = calloc(9, sizeof(*squares));
    boxes = createBoxes();
    if (!squares || !boxes) goto fail;

    for (i = 0; i < 9; ++i) {
        int currentBox = (i / 3) * 3;
        if (!puzzle[i]) goto fail;
        squares[i] = calloc(9, sizeof(*squares[i]));
        if (!squares[i]) goto fail;
        for (j = 0; j < 9; ++j) {
            Square *square;
            int boxIndex = currentBox + j / 3;
            if (puzzle[i][j] < 0 || puzzle[i][j] > 9) goto fail;
            square = calloc(1, sizeof(*square));
            if (!square) goto fail;
            square->number = puzzle[i][j];
            square->row = i;
            square->column = j;
            square->solvable = square->number == 0 ? 9 : 0;
            square->box = boxes[boxIndex];
            for (x = 0; x < 9; ++x) square->possible[x] = 0;
            squares[i][j] = square;
            boxes[boxIndex]->squares[boxes[boxIndex]->numbers++] = square;
        }
    }

    UNSOLVED = 81;
    for (i = 0; i < 9; ++i) {
        for (j = 0; j < 9; ++j) {
            if (squares[i][j]->number != 0) {
                --UNSOLVED;
                updateSudoku(squares, i, j);
                updateBoxes(squares, i, j);
            }
        }
    }
    sudoku = createSudoku(squares, boxes);
    if (!sudoku) goto fail;
    return sudoku;

fail:
    destroySquares(squares);
    destroyBoxes(boxes);
    return NULL;
}

int checkPuzzle(Square ***squares, Box **boxes) {
    int i, j;
    for (i = 0; i < 9; ++i) {
        for (j = 0; j < 9; ++j) {
            if (squares[i][j]->number == 0 && squares[i][j]->solvable == 1) {
                if (!solveSquare(squares[i][j])) return 0;
                updateSudoku(squares, i, j);
                updateBoxes(squares, i, j);
                return 1;
            }
        }
    }
    if (boxSingles(squares, boxes)) return 1;
    return checkRows(squares, boxes);
}

int **createPuzzle(void) {
    static const int arr[9][9] = {
        {3, 0, 0, 0, 0, 0, 0, 2, 0},
        {0, 8, 0, 4, 3, 2, 0, 1, 0},
        {0, 5, 0, 0, 0, 0, 6, 0, 0},
        {0, 7, 4, 8, 6, 0, 0, 0, 0},
        {0, 0, 0, 0, 0, 0, 0, 0, 8},
        {0, 3, 0, 1, 0, 0, 7, 0, 0},
        {0, 0, 0, 2, 9, 6, 8, 7, 1},
        {6, 0, 0, 0, 0, 0, 3, 4, 0},
        {1, 9, 0, 7, 0, 0, 0, 0, 6}
    };
    int **puzzle = calloc(9, sizeof(*puzzle));
    int i, j;
    if (!puzzle) return NULL;
    for (i = 0; i < 9; ++i) {
        puzzle[i] = malloc(9 * sizeof(**puzzle));
        if (!puzzle[i]) {
            destroyPuzzle(puzzle);
            return NULL;
        }
        for (j = 0; j < 9; ++j) puzzle[i][j] = arr[i][j];
    }
    return puzzle;
}

void destroyPuzzle(int **puzzle) {
    int i;
    if (!puzzle) return;
    for (i = 0; i < 9; ++i) free(puzzle[i]);
    free(puzzle);
}

int updateSudoku(Square ***squares, int row, int col) {
    int x, number;
    if (!squares || row < 0 || row >= 9 || col < 0 || col >= 9 || !squares[row] || !squares[row][col]) return 0;
    number = squares[row][col]->number;
    if (number < 1 || number > 9) return 0;
    for (x = 0; x < 9; ++x) {
        Square *columnPeer = squares[x][col];
        Square *rowPeer = squares[row][x];
        if (columnPeer->number == 0 && columnPeer->possible[number - 1] == 0) {
            columnPeer->possible[number - 1] = 1;
            --columnPeer->solvable;
        }
        if (rowPeer->number == 0 && rowPeer->possible[number - 1] == 0) {
            rowPeer->possible[number - 1] = 1;
            --rowPeer->solvable;
        }
    }
    return 1;
}

void printPuzzle(Square ***puzzle) {
    int i, j;
    puts("Puzzle:");
    puts("-------------------------------");
    for (i = 0; i < 9; ++i) {
        putchar('|');
        for (j = 0; j < 9; ++j) {
            printf(" %d ", puzzle[i][j]->number);
            if ((j + 1) % 3 == 0) putchar('|');
        }
        putchar('\n');
        if ((i + 1) % 3 == 0) puts("-------------------------------");
    }
}
