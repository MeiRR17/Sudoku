#ifndef SUDOKU_H
#define SUDOKU_H

/* Legacy data model. The v0.2.0 milestone will replace these heap graphs
 * with a bounded, validated board representation. */
typedef struct Box Box;

typedef struct Square {
    int number;
    int row;
    int column;
    int solvable;
    int possible[9];
    Box *box;
} Square;

struct Box {
    Square **squares;
    int numbers;
    int solvable;
    int possible[9];
};

typedef struct Sudoku {
    Square ***squares;
    Box **boxes;
} Sudoku;

extern int UNSOLVED;
extern int SIZE_ROWS;
extern int SIZE_COLUMNS;

int **createPuzzle(void);
void destroyPuzzle(int **puzzle);
Sudoku *createSudoku(Square ***squares, Box **boxes);
Sudoku *setUpPuzzle(int **puzzle);
void destroySudoku(Sudoku *sudoku);
int checkPuzzle(Square ***squares, Box **boxes);
int updateSudoku(Square ***squares, int row, int col);
void printPuzzle(Square ***squares);

Box **createBoxes(void);
void destroyBoxes(Box **boxes);
int updateBoxes(Square ***squares, int row, int column);
int boxSingles(Square ***squares, Box **boxes);
int checkRows(Square ***squares, Box **boxes);
int solveSquare(Square *square);

#endif
