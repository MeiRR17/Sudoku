#include "sudoku/game.h"
#include "sudoku/board.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if(!(x)){ fprintf(stderr,"FAIL at %s:%d: %s\n",__FILE__,__LINE__,#x);return 1;} }while(0)
static const char classic[]="530070000600195000098000060800060003400803001700020006060000280000419005000080079";
static const char filled[]="534678912672195348198342567859761423426853791713924856961537284287419635345286179";
static int check_game(void){
    SudokuBoard board;
    SudokuGame *game=malloc(sizeof(SudokuGame));
    SudokuGame *restored=malloc(sizeof(SudokuGame));
    SudokuGame *orig=malloc(sizeof(SudokuGame));
    FILE *f;
    int i;
    CHECK(game && restored && orig);
    CHECK(sudoku_board_parse(&board,(const unsigned char*)classic,81,NULL)==SUDOKU_OK);
    CHECK(sudoku_game_start(game,&board)==SUDOKU_GAME_OK);
    CHECK(game->history_len==1u && game->history_cursor==0u);
    CHECK(sudoku_game_reset(game)==SUDOKU_GAME_OK);
    CHECK(game->history_len==1u && game->history_cursor==0u);
    CHECK(sudoku_game_empty(game)>0u);
    CHECK(sudoku_game_set(game,1,1,4)==SUDOKU_GAME_GIVEN);
    CHECK(sudoku_game_erase(game,1,1)==SUDOKU_GAME_GIVEN);
    CHECK(sudoku_game_note(game,1,1,4)==SUDOKU_GAME_GIVEN);
    CHECK(sudoku_game_set(game,0,1,4)==SUDOKU_GAME_RANGE);
    CHECK(sudoku_game_set(game,1,3,0)==SUDOKU_GAME_RANGE);
    CHECK(sudoku_game_set(game,1,3,5)==SUDOKU_GAME_CONFLICT);
    CHECK(sudoku_game_note(game,1,3,4)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2] == (1u<<4));
    CHECK(sudoku_game_note(game,1,3,8)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==((1u<<4)|(1u<<8)));
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==(1u<<4));
    CHECK(sudoku_game_redo(game)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_set(game,1,3,4)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==0 && game->state.board.cells[2]==4);
    CHECK(sudoku_game_note(game,1,3,1)==SUDOKU_GAME_NOT_EMPTY);
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==((1u<<4)|(1u<<8)));
    CHECK(sudoku_game_set(game,1,3,4)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_erase(game,1,3)==SUDOKU_GAME_OK);
    CHECK(game->state.board.cells[2]==0);
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.board.cells[2]==4);
    CHECK(sudoku_game_redo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.board.cells[2]==0);
    CHECK(sudoku_game_erase(game,1,3)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_redo(game)==SUDOKU_GAME_NO_HISTORY);
    CHECK(sudoku_game_reset(game)==SUDOKU_GAME_OK);
    CHECK(game->state.board.cells[2]==0&&game->state.notes[2]==0);
    {
        unsigned cursor = game->history_cursor, length = game->history_len;
        CHECK(sudoku_game_reset(game)==SUDOKU_GAME_OK);
        CHECK(game->history_cursor==cursor && game->history_len==length);
    }
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.board.cells[2]==4);
    CHECK(sudoku_game_redo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.board.cells[2]==0);
    CHECK(sudoku_game_note(game,1,3,7)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_save(game,"game-unit.save")==SUDOKU_GAME_OK);
    /* Public C structs may be modified without going through the safe
     * mutators. Never replace a valid save with a checksummed record
     * that the loader must reject. */
    *orig=*game;
    game->state.board.cells[0]=0; /* Erased original clue. */
    CHECK(sudoku_game_save(game,"game-unit.save")==SUDOKU_GAME_INVALID);
    *game=*orig;
    game->state.board.cells[2]=5; /* Duplicate digit in first row. */
    CHECK(sudoku_game_save(game,"game-unit.save")==SUDOKU_GAME_INVALID);
    *game=*orig;
    game->state.board.cells[2]=10; /* Out-of-range mutable cell. */
    CHECK(sudoku_game_save(game,"game-unit.save")==SUDOKU_GAME_INVALID);
    *game=*orig;
    game->state.notes[0]=(uint16_t)(1u<<2); /* Note on filled clue. */
    CHECK(sudoku_game_save(game,"game-unit.save")==SUDOKU_GAME_INVALID);
    *game=*orig;
    game->state.board.cells[2]=4; /* Filled editable cell with notes. */
    CHECK(sudoku_game_save(game,"game-unit.save")==SUDOKU_GAME_INVALID);
    *game=*orig;
    game->givens.cells[2]=5; /* Invalid original clue configuration. */
    CHECK(sudoku_game_save(game,"game-unit.save")==SUDOKU_GAME_INVALID);
    *game=*orig;
    /* An empty givens board is locally legal, but nonunique and cannot
     * be resumed by the strict loader, even if the current board is valid. */
    memset(&game->givens,0,sizeof game->givens);
    CHECK(sudoku_board_validate(&game->givens,NULL)==SUDOKU_OK);
    CHECK(sudoku_game_save(game,"game-unit.save")==SUDOKU_GAME_INVALID);
    *game=*orig;
    /* Reject a stale or caller-mutated solution cache even though the
     * original clues and all placed digits still validate. */
    game->solution.cells[0]=(uint8_t)(game->solution.cells[0]==9u?8u:9u);
    CHECK(sudoku_game_save(game,"game-unit.save")==SUDOKU_GAME_INVALID);
    *game=*orig;
    memset(restored,0xA6,sizeof *restored);
    CHECK(sudoku_game_load(restored,"game-unit.save")==SUDOKU_GAME_OK);
    CHECK(restored->state.notes[2]==(1u<<7));
    CHECK(restored->state.board.cells[2]==0);
    CHECK(restored->history_cursor==0 && restored->history_len==1);
    CHECK(sudoku_game_elapsed(restored)<=SUDOKU_MAX_ELAPSED_SECONDS);
    /* Corrupted public struct fields must not underflow the saturation
     * expression or report time beyond the documented 10-year limit. */
    restored->elapsed_base = UINT64_MAX;
    CHECK(sudoku_game_elapsed(restored)==SUDOKU_MAX_ELAPSED_SECONDS);
    restored->elapsed_base = SUDOKU_MAX_ELAPSED_SECONDS;
    restored->session_start = (time_t)0;
    CHECK(sudoku_game_elapsed(restored)==SUDOKU_MAX_ELAPSED_SECONDS);
    /* Reload canonical data before verifying no-mutation on corrupt loads. */
    CHECK(sudoku_game_load(restored,"game-unit.save")==SUDOKU_GAME_OK);
    *orig=*restored;
    f=fopen("game-unit.save","ab");CHECK(f!=NULL);
    CHECK(fputc('x',f)=='x');CHECK(fclose(f)==0);
    CHECK(sudoku_game_load(restored,"game-unit.save")==SUDOKU_GAME_CORRUPT);
    CHECK(memcmp(orig,restored,sizeof *orig)==0);
    f=fopen("game-unit.save","wb");CHECK(f!=NULL);
    CHECK(fputs("SUDOKU_SAVE_V1\nG=",f)>=0);CHECK(fclose(f)==0);
    CHECK(sudoku_game_load(restored,"game-unit.save")==SUDOKU_GAME_CORRUPT);
    CHECK(memcmp(orig,restored,sizeof *orig)==0);
    /* Restore and force many edits, exercising bounded history eviction. */
    CHECK(sudoku_game_save(game,"game-unit.save")==SUDOKU_GAME_OK);
    CHECK(sudoku_game_load(restored,"game-unit.save")==SUDOKU_GAME_OK);
    for(i=0;i<150;++i){
        CHECK(sudoku_game_note(restored,1,3,4)==SUDOKU_GAME_OK);
        CHECK(restored->history_len<=SUDOKU_GAME_HISTORY);
    }
    CHECK(restored->history_len==SUDOKU_GAME_HISTORY);
    CHECK(restored->history_cursor==SUDOKU_GAME_HISTORY-1u);
    /* Known solved board and one blank: win detection and undo. */
    CHECK(sudoku_board_parse(&board,(const unsigned char*)filled,81,NULL)==SUDOKU_OK);
    board.cells[0]=0;
    CHECK(sudoku_game_start(game,&board)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_empty(game)==1u && !sudoku_game_won(game));
    CHECK(sudoku_game_set(game,1,1,5)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_won(game) && sudoku_game_empty(game)==0u && sudoku_game_mistakes(game)==0u);
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK && !sudoku_game_won(game));
    CHECK(sudoku_game_redo(game)==SUDOKU_GAME_OK && sudoku_game_won(game));
    CHECK(sudoku_game_save(game,"game-unit.save")==SUDOKU_GAME_OK);
    CHECK(sudoku_game_load(restored,"game-unit.save")==SUDOKU_GAME_OK);
    CHECK(sudoku_game_won(restored));
    CHECK(remove("game-unit.save")==0);
    free(orig);free(restored);free(game);
    return 0;
}
int main(void){int result=check_game();if(!result)puts("GAME ENGINE PASS: unique, givens, notes, history, reset, save/load/corruption, win");return result;}
