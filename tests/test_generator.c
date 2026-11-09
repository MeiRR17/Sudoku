#include "sudoku/generator.h"
#include "sudoku/solver.h"
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define CHECK(e) do { if (!(e)) { fprintf(stderr, "FAIL %s:%d %s\n", __FILE__, __LINE__, #e); return 1; } } while (0)

static int independent_solution(const SudokuBoard *puzzle, const SudokuBoard *answer) {
    unsigned i, row, col, br, bc;
    for (row=0; row<9; ++row) {
        unsigned rm=0,cm=0;
        for(col=0; col<9; ++col) {
            unsigned a=answer->cells[row*9+col], b=answer->cells[col*9+row];
            if(a<1||a>9||b<1||b>9) return 0;
            if((rm&(1u<<a))||(cm&(1u<<b))) return 0;
            rm|=(1u<<a); cm|=(1u<<b);
            if(puzzle->cells[row*9+col] && puzzle->cells[row*9+col]!=a) return 0;
        }
        if(rm!=1022u||cm!=1022u) return 0;
    }
    for(br=0;br<9;br+=3)for(bc=0;bc<9;bc+=3) {
        unsigned m=0;
        for(i=0;i<9;++i) {
            unsigned a=answer->cells[(br+i/3)*9+bc+i%3];
            if(m&(1u<<a)) return 0;
            m|=(1u<<a);
        }
        if(m!=1022u) return 0;
    }
    return 1;
}
static int one(uint32_t seed, SudokuDifficulty difficulty, unsigned rotational) {
    SudokuGenerateOptions opts = {seed,difficulty,rotational,35u,3000u,50000u,10000u};
    SudokuGenerateResult result, repeated;
    SudokuBoard first;
    unsigned count = 9, naked = 0, hidden = 0, clues = 0, i;
    CHECK(sudoku_generate(&opts,&result)==SUDOKU_GENERATE_OK);
    CHECK(sudoku_generate(&opts,&repeated)==SUDOKU_GENERATE_OK);
    CHECK(memcmp(&result,&repeated,sizeof result)==0);
    CHECK(sudoku_board_validate(&result.puzzle,NULL)==SUDOKU_OK);
    CHECK(sudoku_board_validate(&result.solution,NULL)==SUDOKU_OK);
    CHECK(independent_solution(&result.puzzle,&result.solution));
    CHECK(sudoku_analyze(&result.puzzle,&first,&count)==SUDOKU_SOLVE_UNIQUE);
    CHECK(count==1u && memcmp(&first,&result.solution,sizeof first)==0);
    CHECK(sudoku_rate_difficulty(&result.puzzle,&naked,&hidden)==difficulty);
    CHECK(result.rated==difficulty && result.naked_singles==naked && result.hidden_singles==hidden);
    if(difficulty==SUDOKU_DIFFICULTY_EASY) CHECK(hidden==0);
    if(difficulty==SUDOKU_DIFFICULTY_MEDIUM) CHECK(hidden>0);
    for(i=0;i<81;++i) {
        clues+=result.puzzle.cells[i]!=0;
        if(rotational) CHECK((result.puzzle.cells[i]==0)==(result.puzzle.cells[80-i]==0));
    }
    CHECK(clues==result.clues);
    CHECK(result.checks>0 && result.checks<=opts.max_checks);
    CHECK(result.attempts>0 && result.attempts<=opts.max_attempts);
    return 0;
}
static int checks(void) {
    SudokuGenerateOptions opts={42u,SUDOKU_DIFFICULTY_EASY,0u,20u,2000u,50000u,5000u};
    SudokuGenerateResult output;
    SudokuGenerateResult snapshot;
    SudokuBoard board={{0}};
    unsigned count=9;
    unsigned seed, d, sym;
    for(d=1; d<=3u;++d) for(sym=0; sym<=1u; ++sym) for(seed=1; seed<=6u;++seed)
        CHECK(one(seed*17u,(SudokuDifficulty)d,sym)==0);
    CHECK(sudoku_generate(&opts,&output)==SUDOKU_GENERATE_OK);
    snapshot=output;
    opts.max_checks=1u;
    CHECK(sudoku_generate(&opts,&output)==SUDOKU_GENERATE_BUDGET);
    CHECK(memcmp(&output,&snapshot,sizeof output)==0);
    opts.max_checks=2000u;
    opts.max_nodes=1u;
    CHECK(sudoku_generate(&opts,&output)==SUDOKU_GENERATE_BUDGET);
    CHECK(memcmp(&output,&snapshot,sizeof output)==0);
    opts.max_nodes=50000u;
    opts.max_attempts=0u;
    CHECK(sudoku_generate(&opts,&output)==SUDOKU_GENERATE_INVALID);
    CHECK(memcmp(&output,&snapshot,sizeof output)==0);
    opts.max_attempts=20u;
    opts.difficulty=SUDOKU_DIFFICULTY_INVALID;
    CHECK(sudoku_generate(&opts,&output)==SUDOKU_GENERATE_INVALID);
    opts.difficulty=SUDOKU_DIFFICULTY_EASY;
    CHECK(sudoku_generate(NULL,&output)==SUDOKU_GENERATE_INVALID);
    CHECK(sudoku_generate(&opts,NULL)==SUDOKU_GENERATE_INVALID);
    CHECK(memcmp(&output,&snapshot,sizeof output)==0);
    CHECK(sudoku_rate_difficulty(NULL,NULL,NULL)==SUDOKU_DIFFICULTY_INVALID);
    board.cells[0]=10u;
    CHECK(sudoku_rate_difficulty(&board,NULL,NULL)==SUDOKU_DIFFICULTY_INVALID);
    CHECK(sudoku_analyze_bounded(&board,NULL,&count,10,NULL)==SUDOKU_SOLVE_INVALID && count==0);
    memset(&board,0,sizeof board);
    {
        SudokuBoard keep=output.solution;
        uint64_t nodes=0;
        CHECK(sudoku_analyze_bounded(&board,&output.solution,&count,1u,&nodes)==SUDOKU_SOLVE_BUDGET);
        CHECK(nodes==1 && count==0);
        CHECK(memcmp(&keep,&output.solution,sizeof keep)==0);
    }
    CHECK(strcmp(sudoku_generate_status_text(SUDOKU_GENERATE_BUDGET),"generation budget exhausted")==0);
    CHECK(strcmp(sudoku_solve_status_text(SUDOKU_SOLVE_BUDGET),"search node budget exhausted")==0);
    return 0;
}
int main(void) {int rc=checks();if(rc==0)puts("GENERATOR PASS: 72 uniquely-solvable seeded fixtures, 2 symmetry modes, 3 difficulty levels, budget invariants");return rc;}
