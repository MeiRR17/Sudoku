#if !defined(_WIN32)
#define _POSIX_C_SOURCE 200809L
#endif
#include "sudoku/game.h"
#include "sudoku/board.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#if !defined(_WIN32)
#include <sys/stat.h>
#include <unistd.h>
#endif
#define CHECK(x) do { if(!(x)){ fprintf(stderr,"FAIL at %s:%d: %s\n",__FILE__,__LINE__,#x);return 1;} }while(0)
static const char classic[]="530070000600195000098000060800060003400803001700020006060000280000419005000080079";
static const char filled[]="534678912672195348198342567859761423426853791713924856961537284287419635345286179";
/* Independent reference: reproduce the legacy nine-trial candidate
 * algorithm, so the optimized one-pass implementation has an oracle. */
static uint16_t reference_candidates(const SudokuBoard *board,
                                     unsigned row, unsigned col) {
    SudokuBoard trial = *board;
    unsigned index, digit;
    uint16_t allowed = 0u;
    if (row < 1u || row > 9u || col < 1u || col > 9u) return 0u;
    index = (row - 1u) * 9u + col - 1u;
    if (board->cells[index]) return 0u;
    for (digit = 1u; digit <= 9u; ++digit) {
        trial.cells[index] = (uint8_t)digit;
        if (sudoku_board_validate(&trial, NULL) == SUDOKU_OK)
            allowed = (uint16_t)(allowed | (uint16_t)(1u << digit));
    }
    return allowed;
}
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
    /* Pencil marks in the public C struct can be altered directly. Reject
     * malformed masks during ordinary edits, even when the board is legal;
     * explicit note cleanup and reset remain usable recovery operations. */
    {
        SudokuGame *probe = malloc(sizeof *probe);
        SudokuGameMove move = {1u, 3u, 4u};
        uint16_t masks[SUDOKU_CELL_COUNT] = {0};
        unsigned applied = 99u, removed = 99u;
        unsigned cursor, length;
        CHECK(probe != NULL);
        CHECK(sudoku_game_start(probe, &board) == SUDOKU_GAME_OK);
        cursor = probe->history_cursor;
        length = probe->history_len;
        probe->state.notes[0] = (uint16_t)(1u << 2); /* Note on a given. */
        CHECK(sudoku_game_set(probe, 1u, 3u, 4u) == SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_erase(probe, 1u, 3u) == SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_note(probe, 1u, 3u, 4u) == SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_set_many(probe, &move, 1u, &applied) ==
              SUDOKU_GAME_INVALID);
        CHECK(applied == 0u);
        CHECK(sudoku_game_eliminate_notes(probe, masks, &removed) ==
              SUDOKU_GAME_INVALID);
        CHECK(removed == 0u);
        CHECK(sudoku_game_clear_mistakes(probe) == SUDOKU_GAME_INVALID);
        CHECK(probe->state.notes[0] == (1u << 2));
        CHECK(probe->history_cursor == cursor && probe->history_len == length);
        CHECK(sudoku_game_auto_notes(probe) == SUDOKU_GAME_OK);
        CHECK(probe->state.notes[0] == 0u && probe->state.board.cells[0] == 5u);
        CHECK(probe->history_cursor == 1u && probe->history_len == 2u);
        CHECK(sudoku_game_undo(probe) == SUDOKU_GAME_OK);
        CHECK(probe->state.notes[0] == 0u); /* Snapshot remains restorable. */
        probe->state.notes[2] = 0x8000u; /* Illegal empty-cell note. */
        cursor = probe->history_cursor;
        length = probe->history_len;
        CHECK(sudoku_game_note(probe, 1u, 3u, 4u) == SUDOKU_GAME_INVALID);
        CHECK(probe->history_cursor == cursor && probe->history_len == length);
        CHECK(sudoku_game_prune_notes(probe) == SUDOKU_GAME_OK);
        CHECK(probe->state.notes[2] == 0u);
        probe->state.notes[0] = 1u; /* Illegal bit zero on a clue. */
        CHECK(sudoku_game_clear_notes(probe) == SUDOKU_GAME_OK);
        CHECK(probe->state.notes[0] == 0u);
        probe->state.notes[0] = 0x8000u;
        CHECK(sudoku_game_reset(probe) == SUDOKU_GAME_OK);
        CHECK(probe->state.notes[0] == 0u && probe->state.board.cells[0] == 5u);
        CHECK(sudoku_game_undo(probe) == SUDOKU_GAME_OK);
        CHECK(probe->state.notes[0] == 0u);
        free(probe);
    }
    /* Historical Undo/Redo targets can be tampered with through the public
     * C struct. A bad destination must not change the live board or cursor;
     * an intact target remains usable even if the current board is damaged. */
    {
        SudokuGame *probe = malloc(sizeof *probe);
        SudokuGameSnapshot original_undo, original_redo, live;
        unsigned cursor, length;
        CHECK(probe != NULL);
        CHECK(sudoku_game_start(probe, &board) == SUDOKU_GAME_OK);
        CHECK(sudoku_game_note(probe, 1u, 3u, 1u) == SUDOKU_GAME_OK);
        CHECK(sudoku_game_note(probe, 1u, 3u, 2u) == SUDOKU_GAME_OK);
        CHECK(probe->history_cursor == 2u && probe->history_len == 3u);
        original_undo = probe->history[1];
        original_redo = probe->history[2];
        live = probe->state;
        cursor = probe->history_cursor;
        length = probe->history_len;
        probe->history[1].board.cells[0] = 0u; /* Erased given. */
        CHECK(sudoku_game_undo(probe) == SUDOKU_GAME_INVALID);
        CHECK(probe->history_cursor == cursor &&
              probe->history_len == length);
        CHECK(memcmp(probe->state.board.cells, live.board.cells,
                     sizeof live.board.cells) == 0);
        CHECK(probe->state.notes[2] == live.notes[2]);
        probe->history[1] = original_undo;
        probe->history[1].board.cells[2] = 5u; /* Conflicts with row 1. */
        CHECK(sudoku_game_undo(probe) == SUDOKU_GAME_INVALID);
        probe->history[1] = original_undo;
        probe->history[1].board.cells[2] = 10u; /* Outside digit range. */
        CHECK(sudoku_game_undo(probe) == SUDOKU_GAME_INVALID);
        probe->history[1] = original_undo;
        probe->history[1].notes[2] = 1u; /* Illegal bit 0. */
        CHECK(sudoku_game_undo(probe) == SUDOKU_GAME_INVALID);
        probe->history[1] = original_undo;
        probe->history[1].notes[0] = (uint16_t)(1u << 3); /* Filled clue. */
        CHECK(sudoku_game_undo(probe) == SUDOKU_GAME_INVALID);
        probe->history[1] = original_undo;
        CHECK(probe->history_cursor == cursor &&
              probe->state.notes[2] == live.notes[2]);
        CHECK(sudoku_game_undo(probe) == SUDOKU_GAME_OK);
        CHECK(probe->history_cursor == 1u &&
              probe->state.notes[2] == (1u << 1));
        probe->history[2].notes[2] = 0x8000u; /* Illegal high pencil bit. */
        CHECK(sudoku_game_redo(probe) == SUDOKU_GAME_INVALID);
        CHECK(probe->history_cursor == 1u &&
              probe->state.notes[2] == (1u << 1));
        probe->history[2] = original_redo;
        CHECK(sudoku_game_redo(probe) == SUDOKU_GAME_OK);
        CHECK(probe->history_cursor == 2u &&
              probe->state.notes[2] == ((1u << 1) | (1u << 2)));
        /* A valid snapshot is an intentional recovery route for bad live
         * state; checking the destination must not require valid current. */
        probe->state.board.cells[0] = 0u;
        CHECK(sudoku_game_undo(probe) == SUDOKU_GAME_OK);
        CHECK(probe->state.board.cells[0] == board.cells[0]);
        /* Corrupted public givens make even sound history unsafe. */
        probe->givens.cells[2] = 5u;
        CHECK(sudoku_game_redo(probe) == SUDOKU_GAME_INVALID);
        CHECK(probe->history_cursor == 1u);
        free(probe);
    }
    /* Editing entry points must fail closed on erased original clues,
     * including no-op actions and bulk note/history mutators. */
    {
        SudokuGameSnapshot snapshot = game->state;
        SudokuBoard original_givens = game->givens;
        SudokuGameMove move = {1u, 3u, 4u};
        uint16_t masks[SUDOKU_CELL_COUNT] = {0};
        unsigned applied = 99u, removed = 99u;
        unsigned cursor = game->history_cursor, length = game->history_len;
        game->state.board.cells[0] = 0u; /* Original r1c1 clue erased. */
        game->state.notes[2] = (uint16_t)(1u << 4);
        masks[2] = (uint16_t)(1u << 4);
        CHECK(sudoku_game_set(game, 1u, 3u, 4u) == SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_erase(game, 1u, 3u) == SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_note(game, 1u, 3u, 4u) == SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_auto_notes(game) == SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_prune_notes(game) == SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_clear_notes(game) == SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_set_many(game, &move, 1u, &applied) == SUDOKU_GAME_INVALID);
        CHECK(applied == 0u);
        CHECK(sudoku_game_eliminate_notes(game, masks, &removed) == SUDOKU_GAME_INVALID);
        CHECK(removed == 0u);
        CHECK(sudoku_game_clear_mistakes(game) == SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_reset(game) == SUDOKU_GAME_INVALID);
        CHECK(game->state.board.cells[0] == 0u);
        CHECK(game->state.notes[2] == (1u << 4));
        CHECK(game->history_cursor == cursor && game->history_len == length);
        game->state = snapshot;
        game->givens.cells[2] = 5u; /* Invalid given: duplicate row one 5. */
        CHECK(sudoku_game_set(game, 1u, 3u, 4u) == SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_note(game, 1u, 3u, 4u) == SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_clear_notes(game) == SUDOKU_GAME_INVALID);
        CHECK(game->history_cursor == cursor && game->history_len == length);
        game->givens = original_givens;
        game->state = snapshot;
    }
    /* Reset must fail closed if a C caller alters the public game into
     * a conflicting/out-of-range board or erases an immutable clue.
     * Neither the snapshot nor the undo/redo cursor may change. */
    {
        SudokuGameSnapshot snapshot = game->state;
        SudokuBoard original_givens = game->givens;
        unsigned cursor = game->history_cursor, length = game->history_len;
        game->state.board.cells[0] = 0u; /* Given silently erased. */
        CHECK(sudoku_game_reset(game) == SUDOKU_GAME_INVALID);
        CHECK(game->state.board.cells[0] == 0u);
        game->state = snapshot;
        game->state.board.cells[2] = 5u; /* Duplicate in first row. */
        CHECK(sudoku_game_reset(game) == SUDOKU_GAME_INVALID);
        CHECK(game->state.board.cells[2] == 5u);
        game->state = snapshot;
        game->state.board.cells[2] = 10u; /* Out-of-range digit. */
        CHECK(sudoku_game_reset(game) == SUDOKU_GAME_INVALID);
        CHECK(game->state.board.cells[2] == 10u);
        game->state = snapshot;
        game->givens.cells[2] = 5u; /* Duplicate original clue. */
        CHECK(sudoku_game_reset(game) == SUDOKU_GAME_INVALID);
        CHECK(game->givens.cells[2] == 5u);
        game->givens = original_givens;
        game->state = snapshot;
        CHECK(game->history_cursor == cursor && game->history_len == length);
        CHECK(memcmp(game->state.board.cells, snapshot.board.cells,
                     sizeof snapshot.board.cells) == 0);
    }
    /* Atomic note replacement: one history step for any set of digits,
     * canonical bitmask checks, and no-op preservation of Redo. */
    {
        unsigned cursor=game->history_cursor, length=game->history_len;
        uint16_t chosen=(uint16_t)((1u<<1)|(1u<<3)|(1u<<9));
        CHECK(sudoku_game_set_notes(game,1u,3u,chosen)==SUDOKU_GAME_OK);
        CHECK(game->state.notes[2]==chosen);
        CHECK(game->history_cursor==cursor+1u &&
              game->history_len==length+1u);
        cursor=game->history_cursor;
        CHECK(sudoku_game_set_notes(game,1u,3u,chosen)==SUDOKU_GAME_OK);
        CHECK(game->history_cursor==cursor);
        CHECK(sudoku_game_set_notes(game,1u,3u,1u)==SUDOKU_GAME_RANGE);
        CHECK(sudoku_game_set_notes(game,1u,3u,0x8000u)==SUDOKU_GAME_RANGE);
        CHECK(sudoku_game_set_notes(game,0u,3u,chosen)==SUDOKU_GAME_RANGE);
        CHECK(sudoku_game_set_notes(game,1u,1u,chosen)==SUDOKU_GAME_GIVEN);
        CHECK(game->state.notes[2]==chosen && game->history_cursor==cursor);
        CHECK(sudoku_game_set_notes(game,1u,3u,0u)==SUDOKU_GAME_OK);
        CHECK(game->state.notes[2]==0u);
        CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
        CHECK(game->state.notes[2]==chosen);
        CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
        CHECK(game->state.notes[2]==0u);
        CHECK(sudoku_game_redo(game)==SUDOKU_GAME_OK);
        CHECK(game->state.notes[2]==chosen);
        cursor=game->history_cursor;
        length=game->history_len;
        CHECK(sudoku_game_set_notes(game,1u,3u,chosen)==SUDOKU_GAME_OK);
        CHECK(game->history_cursor==cursor && game->history_len==length);
        CHECK(sudoku_game_redo(game)==SUDOKU_GAME_OK);
        CHECK(game->state.notes[2]==0u);
        CHECK(sudoku_game_set(game,1u,3u,4u)==SUDOKU_GAME_OK);
        cursor=game->history_cursor;
        CHECK(sudoku_game_set_notes(game,1u,3u,chosen)==SUDOKU_GAME_NOT_EMPTY);
        CHECK(game->history_cursor==cursor);
        CHECK(sudoku_game_erase(game,1u,3u)==SUDOKU_GAME_OK);
        /* Corrupt public state cannot enter the history as new notes. */
        game->state.board.cells[0]=0u;
        CHECK(sudoku_game_set_notes(game,1u,3u,chosen)==SUDOKU_GAME_INVALID);
        game->state.board.cells[0]=game->givens.cells[0];
        game->state.notes[0]=(uint16_t)(1u<<3);
        CHECK(sudoku_game_set_notes(game,1u,3u,chosen)==SUDOKU_GAME_INVALID);
        game->state.notes[0]=0u;
        CHECK(sudoku_game_set_notes(game,1u,3u,chosen)==SUDOKU_GAME_OK);
        CHECK(game->state.notes[2]==chosen);
        /* Multi-bit add/remove is idempotent; illegal masks are rejected
         * even for removal, where invalid bits could otherwise vanish. */
        cursor=game->history_cursor;
        CHECK(sudoku_game_add_notes(game,1u,3u,(uint16_t)(1u<<5))==
              SUDOKU_GAME_OK);
        CHECK(game->state.notes[2]==(uint16_t)(chosen|(1u<<5)));
        CHECK(game->history_cursor==cursor+1u);
        cursor=game->history_cursor;
        CHECK(sudoku_game_add_notes(game,1u,3u,(uint16_t)(1u<<5))==
              SUDOKU_GAME_OK);
        CHECK(game->history_cursor==cursor);
        CHECK(sudoku_game_remove_notes(game,1u,3u,(uint16_t)(1u<<3))==
              SUDOKU_GAME_OK);
        CHECK(game->state.notes[2]==(uint16_t)((chosen|(1u<<5))&~(1u<<3)));
        cursor=game->history_cursor;
        CHECK(sudoku_game_remove_notes(game,1u,3u,(uint16_t)(1u<<3))==
              SUDOKU_GAME_OK);
        CHECK(game->history_cursor==cursor);
        CHECK(sudoku_game_remove_notes(game,1u,3u,1u)==SUDOKU_GAME_RANGE);
        CHECK(sudoku_game_add_notes(game,1u,3u,0x8000u)==SUDOKU_GAME_RANGE);
        CHECK(sudoku_game_remove_notes(game,1u,3u,0x8000u)==SUDOKU_GAME_RANGE);
        CHECK(sudoku_game_add_notes(game,1u,1u,(uint16_t)(1u<<3))==
              SUDOKU_GAME_GIVEN);
        CHECK(sudoku_game_remove_notes(game,1u,1u,(uint16_t)(1u<<3))==
              SUDOKU_GAME_GIVEN);
        CHECK(sudoku_game_add_notes(game,0u,3u,0u)==SUDOKU_GAME_RANGE);
        CHECK(sudoku_game_remove_notes(NULL,1u,3u,0u)==SUDOKU_GAME_INVALID);
        CHECK(game->history_cursor==cursor);
        CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
        CHECK(game->state.notes[2]==(uint16_t)(chosen|(1u<<5)));
        CHECK(sudoku_game_redo(game)==SUDOKU_GAME_OK);
        CHECK(game->state.notes[2]==(uint16_t)((chosen|(1u<<5))&~(1u<<3)));
        /* Reset this cell so the pre-existing single-toggle regression
         * below starts with no pencil marks, not stale notes. */
        CHECK(sudoku_game_set_notes(game,1u,3u,0u)==SUDOKU_GAME_OK);
        CHECK(game->state.notes[2]==0u);
    }
    /* Cell-scoped candidates: fill replaces pencil marks; prune only
     * intersects them with legal candidates. Both group into one Undo,
     * preserve Redo after no-ops, never read the cached solution, and
     * refuse clues, filled cells, invalid bounds or malformed public data. */
    {
        SudokuGame *probe = malloc(sizeof *probe);
        uint16_t legal=(uint16_t)((1u<<1)|(1u<<2)|(1u<<4));
        unsigned cursor,length;
        CHECK(probe!=NULL);
        CHECK(sudoku_game_start(probe,&board)==SUDOKU_GAME_OK);
        CHECK(sudoku_game_fill_cell_notes(probe,1u,3u)==SUDOKU_GAME_OK);
        CHECK(probe->state.notes[2]==legal && probe->history_cursor==1u);
        cursor=probe->history_cursor;
        CHECK(sudoku_game_fill_cell_notes(probe,1u,3u)==SUDOKU_GAME_OK);
        CHECK(probe->history_cursor==cursor);
        CHECK(sudoku_game_set_notes(probe,1u,3u,
              (uint16_t)((1u<<1)|(1u<<2)|(1u<<8)))==SUDOKU_GAME_OK);
        CHECK(sudoku_game_prune_cell_notes(probe,1u,3u)==SUDOKU_GAME_OK);
        CHECK(probe->state.notes[2]==((1u<<1)|(1u<<2)));
        CHECK(sudoku_game_undo(probe)==SUDOKU_GAME_OK);
        CHECK(probe->state.notes[2]==((1u<<1)|(1u<<2)|(1u<<8)));
        CHECK(sudoku_game_redo(probe)==SUDOKU_GAME_OK);
        CHECK(probe->state.notes[2]==((1u<<1)|(1u<<2)));
        CHECK(sudoku_game_undo(probe)==SUDOKU_GAME_OK);
        cursor=probe->history_cursor;
        length=probe->history_len;
        CHECK(sudoku_game_prune_cell_notes(probe,1u,3u)==SUDOKU_GAME_OK);
        CHECK(probe->state.notes[2]==((1u<<1)|(1u<<2)));
        CHECK(probe->history_cursor==cursor+1u);
        CHECK(probe->history_len==cursor+2u); /* Redo branch discarded. */
        CHECK(sudoku_game_prune_cell_notes(probe,1u,3u)==SUDOKU_GAME_OK);
        CHECK(probe->history_cursor==cursor+1u);
        CHECK(sudoku_game_fill_cell_notes(probe,0u,3u)==SUDOKU_GAME_RANGE);
        CHECK(sudoku_game_prune_cell_notes(probe,1u,10u)==SUDOKU_GAME_RANGE);
        CHECK(sudoku_game_fill_cell_notes(probe,1u,1u)==SUDOKU_GAME_GIVEN);
        CHECK(sudoku_game_prune_cell_notes(probe,1u,1u)==SUDOKU_GAME_GIVEN);
        CHECK(sudoku_game_fill_cell_notes(NULL,1u,3u)==SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_prune_cell_notes(NULL,1u,3u)==SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_set(probe,1u,3u,4u)==SUDOKU_GAME_OK);
        cursor=probe->history_cursor;
        CHECK(sudoku_game_fill_cell_notes(probe,1u,3u)==SUDOKU_GAME_NOT_EMPTY);
        CHECK(sudoku_game_prune_cell_notes(probe,1u,3u)==SUDOKU_GAME_NOT_EMPTY);
        CHECK(probe->history_cursor==cursor);
        CHECK(sudoku_game_erase(probe,1u,3u)==SUDOKU_GAME_OK);
        probe->state.board.cells[0]=0u; /* Clue corruption. */
        cursor=probe->history_cursor;
        CHECK(sudoku_game_fill_cell_notes(probe,1u,3u)==SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_prune_cell_notes(probe,1u,3u)==SUDOKU_GAME_INVALID);
        CHECK(probe->history_cursor==cursor);
        probe->state.board.cells[0]=probe->givens.cells[0];
        probe->state.notes[0]=(uint16_t)(1u<<1); /* Marks on filled clue. */
        CHECK(sudoku_game_fill_cell_notes(probe,1u,3u)==SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_prune_cell_notes(probe,1u,3u)==SUDOKU_GAME_INVALID);
        CHECK(probe->history_cursor==cursor);
        free(probe);
    }
    /* Unit-level fill/prune must change only the selected nine cells and
     * use one Undo for multiple notes, preserving Redo on no-op. */
    {
        SudokuGame *probe=malloc(sizeof *probe);
        uint16_t allowed=(uint16_t)((1u<<1)|(1u<<2)|(1u<<4));
        unsigned cursor;
        CHECK(probe!=NULL);
        CHECK(sudoku_game_start(probe,&board)==SUDOKU_GAME_OK);
        CHECK(sudoku_game_set_notes(probe,2u,2u,(uint16_t)(1u<<9))==
              SUDOKU_GAME_OK);
        CHECK(sudoku_game_fill_unit_notes(probe,SUDOKU_GAME_ROW,1u)==SUDOKU_GAME_OK);
        CHECK(probe->state.notes[2]==allowed);
        CHECK(probe->state.notes[10]==(1u<<9));
        CHECK(probe->history_cursor==2u);
        CHECK(sudoku_game_fill_unit_notes(probe,SUDOKU_GAME_ROW,1u)==SUDOKU_GAME_OK);
        CHECK(probe->history_cursor==2u);
        CHECK(sudoku_game_undo(probe)==SUDOKU_GAME_OK);
        CHECK(probe->state.notes[2]==0u&&probe->state.notes[10]==(1u<<9));
        cursor=probe->history_cursor;
        CHECK(sudoku_game_prune_unit_notes(probe,SUDOKU_GAME_ROW,1u)==SUDOKU_GAME_OK);
        CHECK(probe->history_cursor==cursor); /* No-op retains redo. */
        CHECK(sudoku_game_redo(probe)==SUDOKU_GAME_OK);
        CHECK(probe->state.notes[2]==allowed);
        CHECK(sudoku_game_set_notes(probe,1u,3u,
              (uint16_t)((1u<<1)|(1u<<9)))==SUDOKU_GAME_OK);
        CHECK(sudoku_game_prune_unit_notes(probe,SUDOKU_GAME_ROW,1u)==SUDOKU_GAME_OK);
        CHECK(probe->state.notes[2]==(1u<<1));
        CHECK(probe->state.notes[10]==(1u<<9));
        CHECK(sudoku_game_undo(probe)==SUDOKU_GAME_OK);
        CHECK(probe->state.notes[2]==((1u<<1)|(1u<<9)));
        CHECK(sudoku_game_redo(probe)==SUDOKU_GAME_OK);
        CHECK(probe->state.notes[2]==(1u<<1));
        CHECK(sudoku_game_start(probe,&board)==SUDOKU_GAME_OK);
        CHECK(sudoku_game_fill_unit_notes(probe,SUDOKU_GAME_COLUMN,3u)==SUDOKU_GAME_OK);
        CHECK(probe->state.notes[2]==allowed);
        CHECK(probe->state.notes[3]==0u); /* r1c4 outside column 3. */
        CHECK(sudoku_game_start(probe,&board)==SUDOKU_GAME_OK);
        CHECK(sudoku_game_fill_unit_notes(probe,SUDOKU_GAME_BOX,1u)==SUDOKU_GAME_OK);
        CHECK(probe->state.notes[2]==allowed);
        CHECK(probe->state.notes[3]==0u); /* r1c4 outside box 1. */
        CHECK(probe->state.notes[0]==0u); /* r1c1 is an immutable clue. */
        cursor=probe->history_cursor;
        CHECK(sudoku_game_fill_unit_notes(probe,SUDOKU_GAME_ROW,0u)==SUDOKU_GAME_RANGE);
        CHECK(sudoku_game_prune_unit_notes(probe,SUDOKU_GAME_COLUMN,10u)==SUDOKU_GAME_RANGE);
        CHECK(sudoku_game_fill_unit_notes(probe,(SudokuGameUnit)3,1u)==SUDOKU_GAME_RANGE);
        CHECK(sudoku_game_fill_unit_notes(NULL,SUDOKU_GAME_ROW,1u)==SUDOKU_GAME_INVALID);
        CHECK(probe->history_cursor==cursor);
        probe->state.board.cells[0]=0u;
        CHECK(sudoku_game_fill_unit_notes(probe,SUDOKU_GAME_BOX,1u)==SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_prune_unit_notes(probe,SUDOKU_GAME_ROW,1u)==SUDOKU_GAME_INVALID);
        CHECK(probe->history_cursor==cursor);
        probe->state.board.cells[0]=probe->givens.cells[0];
        probe->state.notes[0]=(uint16_t)(1u<<1);
        CHECK(sudoku_game_fill_unit_notes(probe,SUDOKU_GAME_COLUMN,3u)==SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_prune_unit_notes(probe,SUDOKU_GAME_BOX,1u)==SUDOKU_GAME_INVALID);
        CHECK(probe->history_cursor==cursor);
        free(probe);
    }
    /* Erase must clear pencil marks even when no digit is placed, while
     * preserving undo/redo history and avoiding phantom no-op edits. */
    CHECK(sudoku_game_note(game,1,3,4)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==(1u<<4));
    CHECK(sudoku_game_erase(game,1,3)==SUDOKU_GAME_OK);
    CHECK(game->state.board.cells[2]==0u && game->state.notes[2]==0u);
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==(1u<<4));
    CHECK(sudoku_game_redo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==0u);
    {
        unsigned cursor = game->history_cursor, length = game->history_len;
        CHECK(sudoku_game_erase(game,1,3)==SUDOKU_GAME_OK);
        CHECK(game->history_cursor==cursor && game->history_len==length);
    }
    /* One command clears notes in multiple cells; one undo restores both.
     * An already-cleared game must not create phantom undo history. */
    CHECK(sudoku_game_note(game,1,3,4)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_note(game,1,4,9)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_clear_notes(game)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==0u && game->state.notes[3]==0u);
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==(1u<<4) && game->state.notes[3]==(1u<<9));
    CHECK(sudoku_game_redo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==0u && game->state.notes[3]==0u);
    {
        unsigned cursor=game->history_cursor, length=game->history_len;
        CHECK(sudoku_game_clear_notes(game)==SUDOKU_GAME_OK);
        CHECK(game->history_cursor==cursor && game->history_len==length);
    }
    /* Canonical candidate masks come from the live board, not the solution. */
    CHECK(sudoku_game_candidates(game,1,3)==((1u<<1)|(1u<<2)|(1u<<4)));
    CHECK(sudoku_game_candidates(game,1,1)==0u);
    CHECK(sudoku_game_candidates(game,0,3)==0u);
    /* Bulk pencil operations must never silently wipe notes when a user of
     * the public C API corrupts the board. All checks are transactional,
     * including retained redo history and preexisting handwritten notes. */
    {
        SudokuGameSnapshot original_state = game->state;
        unsigned original_cursor = game->history_cursor;
        unsigned original_len = game->history_len;
        game->state.notes[2] = (uint16_t)((1u << 4) | (1u << 8));
        game->state.board.cells[2] = 5u; /* Duplicate given in row 1. */
        CHECK(sudoku_game_auto_notes(game) == SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_prune_notes(game) == SUDOKU_GAME_INVALID);
        CHECK(game->state.notes[2] == ((1u << 4) | (1u << 8)));
        CHECK(game->state.board.cells[2] == 5u);
        CHECK(game->history_cursor == original_cursor &&
              game->history_len == original_len);
        game->state.board.cells[2] = 10u; /* Out-of-range public byte. */
        CHECK(sudoku_game_auto_notes(game) == SUDOKU_GAME_INVALID);
        CHECK(sudoku_game_prune_notes(game) == SUDOKU_GAME_INVALID);
        CHECK(game->state.notes[2] == ((1u << 4) | (1u << 8)));
        CHECK(game->state.board.cells[2] == 10u);
        CHECK(game->history_cursor == original_cursor &&
              game->history_len == original_len);
        game->state = original_state;
    }
    /* Compare every cell against independent old nine-trial behavior on
     * several valid partially filled boards, not only one hand-picked cell.
     * The candidate API must also fail closed for public-struct corruption. */
    {
        SudokuBoard current = game->state.board, sample_board;
        unsigned sample, index;
        CHECK(sudoku_board_parse(&sample_board,
              (const unsigned char *)filled, 81u, NULL) == SUDOKU_OK);
        for (sample = 0u; sample < 23u; ++sample) {
            CHECK(sudoku_board_parse(&sample_board,
                  (const unsigned char *)filled, 81u, NULL) == SUDOKU_OK);
            for (index = 0u; index < 81u; ++index) {
                if (((index * 37u + sample * 19u) % 11u) < 7u)
                    sample_board.cells[index] = 0u;
            }
            game->state.board = sample_board;
            for (index = 0u; index < 81u; ++index) {
                unsigned row = index / 9u + 1u, col = index % 9u + 1u;
                CHECK(sudoku_game_candidates(game, row, col) ==
                      reference_candidates(&sample_board, row, col));
            }
        }
        game->state.board = current;
        game->state.board.cells[2] = 5u; /* Duplicate digit in row 1. */
        CHECK(sudoku_game_candidates(game, 4u, 4u) == 0u);
        game->state.board.cells[2] = 10u; /* Out-of-range public byte. */
        CHECK(sudoku_game_candidates(game, 4u, 4u) == 0u);
        game->state.board = current;
    }
    CHECK(sudoku_game_auto_notes(game)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==((1u<<1)|(1u<<2)|(1u<<4)));
    CHECK(game->state.notes[0]==0u && game->state.board.cells[2]==0u);
    {
        unsigned cursor=game->history_cursor, length=game->history_len;
        CHECK(sudoku_game_auto_notes(game)==SUDOKU_GAME_OK);
        CHECK(game->history_cursor==cursor && game->history_len==length);
    }
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==0u);
    CHECK(sudoku_game_redo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==((1u<<1)|(1u<<2)|(1u<<4)));
    /* Undo and redo above must restore exactly one state change. Clearing
     * auto-generated notes also needs to preserve the original behavior. */
    CHECK(sudoku_game_clear_notes(game)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==0u);
    CHECK(sudoku_game_note(game,1,3,4)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2] == (1u<<4));
    /* Prune only stale handwritten notes after a legal placement:
     * no added marks, exactly one history edit and an undoable result. */
    {
        unsigned cursor=game->history_cursor, length=game->history_len;
        CHECK(sudoku_game_prune_notes(game)==SUDOKU_GAME_OK);
        CHECK(game->history_cursor==cursor && game->history_len==length);
    }
    CHECK(sudoku_game_note(game,1,3,8)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_set(game,1,6,4)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_prune_notes(game)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==0u);
    {
        unsigned cursor=game->history_cursor, length=game->history_len;
        CHECK(sudoku_game_prune_notes(game)==SUDOKU_GAME_OK);
        CHECK(game->history_cursor==cursor && game->history_len==length);
    }
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==((1u<<4)|(1u<<8)));
    CHECK(sudoku_game_redo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==0u);
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==(1u<<4));
    CHECK(game->state.board.cells[5]==0u);
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
#if !defined(_WIN32)
    /* A user may accidentally pass a named pipe to --resume. The loader
     * must reject it immediately, even with no writer attached. It must
     * never block in fopen(), change the active game, or leave a pipe. */
    {
        SudokuGameSnapshot before=restored->state;
        unsigned cursor=restored->history_cursor;
        unsigned length=restored->history_len;
        (void)remove("game-unit.fifo");
        CHECK(mkfifo("game-unit.fifo",0600)==0);
        CHECK(sudoku_game_load(restored,"game-unit.fifo")==SUDOKU_GAME_IO);
        CHECK(memcmp(restored->state.board.cells,before.board.cells,
                     sizeof before.board.cells)==0);
        CHECK(memcmp(restored->state.notes,before.notes,sizeof before.notes)==0);
        CHECK(restored->history_cursor==cursor && restored->history_len==length);
        CHECK(remove("game-unit.fifo")==0);
        /* A character device is also rejected before reading its bytes. */
        CHECK(sudoku_game_load(restored,"/dev/null")==SUDOKU_GAME_IO);
    }
#endif
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
/* A bulk correction must be explicit, reversible and never disclose the
 * expected solution. A history-neutral repeat must retain redo branches. */
static int check_mistake_clear(void) {
    SudokuBoard board;
    SudokuGame *game=malloc(sizeof *game);
    unsigned cursor, length;
    CHECK(game != NULL);
    CHECK(sudoku_board_parse(&board,(const unsigned char *)classic,81u,NULL)==SUDOKU_OK);
    CHECK(sudoku_game_start(game,&board)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_set(game,1,3,1)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_set(game,1,4,2)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_note(game,2,2,5)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_mistakes(game)==2u);
    cursor=game->history_cursor;
    CHECK(sudoku_game_clear_mistakes(game)==SUDOKU_GAME_OK);
    CHECK(game->state.board.cells[2]==0u && game->state.board.cells[3]==0u);
    CHECK(game->state.board.cells[0]==5u && game->state.board.cells[4]==7u);
    CHECK(game->state.notes[10]==(1u<<5));
    CHECK(sudoku_game_mistakes(game)==0u);
    CHECK(game->history_cursor==cursor+1u);
    cursor=game->history_cursor;length=game->history_len;
    CHECK(sudoku_game_clear_mistakes(game)==SUDOKU_GAME_OK);
    CHECK(game->history_cursor==cursor && game->history_len==length);
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.board.cells[2]==1u && game->state.board.cells[3]==2u);
    CHECK(game->state.notes[10]==(1u<<5));
    CHECK(sudoku_game_redo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.board.cells[2]==0u && game->state.board.cells[3]==0u);
    /* Undo to a clean snapshot with pending redo; a no-op must not erase it. */
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(game->history_cursor==0u);
    length=game->history_len;
    CHECK(sudoku_game_clear_mistakes(game)==SUDOKU_GAME_OK);
    CHECK(game->history_cursor==0u && game->history_len==length);
    CHECK(sudoku_game_redo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.board.cells[2]==1u);
    /* The public structure can be edited outside the mutators; refuse
     * corrupted givens/solution/current board without touching history. */
    cursor=game->history_cursor;length=game->history_len;
    game->state.board.cells[0]=0u;
    CHECK(sudoku_game_clear_mistakes(game)==SUDOKU_GAME_INVALID);
    CHECK(game->state.board.cells[0]==0u);
    CHECK(game->history_cursor==cursor && game->history_len==length);
    game->state.board.cells[0]=5u;
    game->solution.cells[0]=0u;
    CHECK(sudoku_game_clear_mistakes(game)==SUDOKU_GAME_INVALID);
    CHECK(game->history_cursor==cursor && game->history_len==length);
    game->solution.cells[0]=5u;
    game->state.board.cells[3]=5u; /* Duplicate existing row-1 given. */
    CHECK(sudoku_game_clear_mistakes(game)==SUDOKU_GAME_INVALID);
    CHECK(game->state.board.cells[3]==5u);
    CHECK(game->history_cursor==cursor && game->history_len==length);
    free(game);
    return 0;
}
static int check_batch_set(void) {
    SudokuBoard board;
    SudokuGame *game = malloc(sizeof *game);
    char two_blanks[sizeof filled];
    SudokuGameMove both[2] = {{1u,1u,5u},{9u,9u,9u}};
    SudokuGameMove bad_duplicate[2] = {{1u,1u,5u},{1u,1u,5u}};
    SudokuGameMove bad_conflict[2] = {{1u,1u,5u},{9u,9u,5u}};
    SudokuGameMove bad_given[2] = {{1u,1u,5u},{1u,2u,3u}};
    SudokuGameMove bad_range[2] = {{1u,1u,5u},{10u,9u,9u}};
    unsigned applied=123u, cursor, length;
    CHECK(game != NULL);
    memcpy(two_blanks,filled,sizeof two_blanks);
    two_blanks[0]='0';
    two_blanks[80]='0';
    CHECK(sudoku_board_parse(&board,(const unsigned char *)two_blanks,
                             81u,NULL)==SUDOKU_OK);
    CHECK(sudoku_game_start(game,&board)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_note(game,1u,1u,5u)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_note(game,9u,9u,9u)==SUDOKU_GAME_OK);
    cursor=game->history_cursor;
    CHECK(sudoku_game_set_many(game,both,2u,&applied)==SUDOKU_GAME_OK);
    CHECK(applied==2u && game->history_cursor==cursor+1u);
    CHECK(game->state.board.cells[0]==5u && game->state.board.cells[80]==9u);
    CHECK(game->state.notes[0]==0u && game->state.notes[80]==0u);
    CHECK(sudoku_game_won(game));
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.board.cells[0]==0u && game->state.board.cells[80]==0u);
    CHECK(game->state.notes[0]==(1u<<5) &&
          game->state.notes[80]==(1u<<9));
    cursor=game->history_cursor;
    length=game->history_len;
    applied=9u;
    CHECK(sudoku_game_set_many(game,NULL,0u,&applied)==SUDOKU_GAME_OK);
    CHECK(applied==0u && game->history_cursor==cursor &&
          game->history_len==length);
    CHECK(sudoku_game_set_many(game,bad_duplicate,2u,&applied)==SUDOKU_GAME_INVALID);
    CHECK(sudoku_game_set_many(game,bad_given,2u,&applied)==SUDOKU_GAME_GIVEN);
    CHECK(sudoku_game_set_many(game,bad_range,2u,&applied)==SUDOKU_GAME_RANGE);
    CHECK(sudoku_game_set_many(game,bad_conflict,2u,&applied)==SUDOKU_GAME_CONFLICT);
    CHECK(sudoku_game_set_many(game,NULL,1u,&applied)==SUDOKU_GAME_INVALID);
    CHECK(sudoku_game_set_many(game,both,82u,&applied)==SUDOKU_GAME_INVALID);
    CHECK(applied==0u && game->history_cursor==cursor &&
          game->history_len==length);
    CHECK(game->state.board.cells[0]==0u && game->state.board.cells[80]==0u);
    CHECK(game->state.notes[0]==(1u<<5) &&
          game->state.notes[80]==(1u<<9));
    /* The rejected batches leave a valid redo branch intact. */
    CHECK(sudoku_game_redo(game)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_won(game));
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_set_many(game,both,2u,&applied)==SUDOKU_GAME_OK);
    CHECK(applied==2u);
    /* Malformed public game data must fail without mutating history. */
    cursor=game->history_cursor;
    game->state.board.cells[1]=10u;
    CHECK(sudoku_game_set_many(game,both,2u,&applied)==SUDOKU_GAME_INVALID);
    CHECK(applied==0u && game->history_cursor==cursor);
    game->state.board.cells[1]=3u;
    free(game);
    return 0;
}
/* Multi-step history moves are atomic, including exhaustion and ring bound.
 * A failed request must retain the board, notes and redo branch exactly. */
static int check_history_steps(void) {
    SudokuBoard board;
    SudokuGame *game = malloc(sizeof *game);
    unsigned cursor, length, i;
    CHECK(game != NULL);
    CHECK(sudoku_board_parse(&board,(const unsigned char *)classic,81u,NULL)==SUDOKU_OK);
    CHECK(sudoku_game_start(game,&board)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_note(game,1u,3u,1u)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_note(game,1u,3u,2u)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_note(game,1u,3u,4u)==SUDOKU_GAME_OK);
    CHECK(game->history_cursor==3u && game->history_len==4u);
    CHECK(game->state.notes[2]==((1u<<1)|(1u<<2)|(1u<<4)));
    CHECK(sudoku_game_undo_steps(game,2u)==SUDOKU_GAME_OK);
    CHECK(game->history_cursor==1u && game->state.notes[2]==(1u<<1));
    CHECK(sudoku_game_redo_steps(game,2u)==SUDOKU_GAME_OK);
    CHECK(game->history_cursor==3u &&
          game->state.notes[2]==((1u<<1)|(1u<<2)|(1u<<4)));
    cursor=game->history_cursor;
    length=game->history_len;
    CHECK(sudoku_game_undo_steps(game,4u)==SUDOKU_GAME_NO_HISTORY);
    CHECK(sudoku_game_redo_steps(game,1u)==SUDOKU_GAME_NO_HISTORY);
    CHECK(sudoku_game_undo_steps(game,0u)==SUDOKU_GAME_RANGE);
    CHECK(sudoku_game_redo_steps(game,0u)==SUDOKU_GAME_RANGE);
    CHECK(sudoku_game_undo_steps(game,128u)==SUDOKU_GAME_RANGE);
    CHECK(sudoku_game_redo_steps(game,128u)==SUDOKU_GAME_RANGE);
    CHECK(game->history_cursor==cursor && game->history_len==length);
    CHECK(game->state.notes[2]==((1u<<1)|(1u<<2)|(1u<<4)));
    CHECK(sudoku_game_undo_steps(game,3u)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==0u && game->history_cursor==0u);
    CHECK(sudoku_game_redo_steps(game,4u)==SUDOKU_GAME_NO_HISTORY);
    CHECK(game->state.notes[2]==0u && game->history_cursor==0u);
    CHECK(sudoku_game_redo_steps(game,3u)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_undo_steps(game,2u)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_note(game,1u,3u,7u)==SUDOKU_GAME_OK);
    CHECK(game->history_cursor==2u && game->history_len==3u);
    CHECK(sudoku_game_redo_steps(game,1u)==SUDOKU_GAME_NO_HISTORY);
    CHECK(game->state.notes[2]==((1u<<1)|(1u<<7)));
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_redo(game)==SUDOKU_GAME_OK);
    /* Oldest records are evicted when the 128-state history fills. */
    CHECK(sudoku_game_start(game,&board)==SUDOKU_GAME_OK);
    for(i=0u;i<130u;++i)
        CHECK(sudoku_game_note(game,1u,3u,1u)==SUDOKU_GAME_OK);
    CHECK(game->history_len==SUDOKU_GAME_HISTORY &&
          game->history_cursor==SUDOKU_GAME_HISTORY-1u);
    CHECK(sudoku_game_undo_steps(game,SUDOKU_GAME_HISTORY-1u)==SUDOKU_GAME_OK);
    CHECK(game->history_cursor==0u);
    CHECK(sudoku_game_redo_steps(game,SUDOKU_GAME_HISTORY-1u)==SUDOKU_GAME_OK);
    CHECK(game->history_cursor==SUDOKU_GAME_HISTORY-1u);
    CHECK(game->state.notes[2]==0u);
    free(game);
    return 0;
}
/* Selective pencil elimination must preflight all inputs and record at
 * most one Undo step even when several notes in different cells change. */
static int check_note_elimination(void){
    SudokuBoard board;
    SudokuGame *game=malloc(sizeof *game);
    uint16_t masks[SUDOKU_CELL_COUNT]={0};
    unsigned removed=99u,cursor,length;
    CHECK(game!=NULL);
    CHECK(sudoku_board_parse(&board,(const unsigned char*)classic,81u,NULL)==SUDOKU_OK);
    CHECK(sudoku_game_start(game,&board)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_note(game,1u,3u,1u)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_note(game,1u,3u,2u)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_note(game,1u,3u,4u)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_note(game,1u,4u,2u)==SUDOKU_GAME_OK);
    cursor=game->history_cursor;
    masks[2]=(uint16_t)((1u<<1)|(1u<<4));
    masks[3]=(uint16_t)(1u<<2);
    CHECK(sudoku_game_eliminate_notes(game,masks,&removed)==SUDOKU_GAME_OK);
    CHECK(removed==3u && game->history_cursor==cursor+1u);
    CHECK(game->state.notes[2]==(1u<<2) && game->state.notes[3]==0u);
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==((1u<<1)|(1u<<2)|(1u<<4)));
    CHECK(game->state.notes[3]==(1u<<2));
    CHECK(sudoku_game_redo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==(1u<<2) && game->state.notes[3]==0u);
    cursor=game->history_cursor;
    length=game->history_len;
    CHECK(sudoku_game_eliminate_notes(game,masks,&removed)==SUDOKU_GAME_OK);
    CHECK(removed==0u && game->history_cursor==cursor &&
          game->history_len==length);
    /* An invalid request or a no-op preserves an existing redo branch. */
    CHECK(sudoku_game_undo(game)==SUDOKU_GAME_OK);
    cursor=game->history_cursor;
    length=game->history_len;
    masks[0]=(uint16_t)(1u<<5); /* immutable original clue */
    CHECK(sudoku_game_eliminate_notes(game,masks,&removed)==SUDOKU_GAME_NOT_EMPTY);
    CHECK(removed==0u && game->history_cursor==cursor &&
          game->history_len==length);
    masks[0]=0u;
    masks[2]=1u; /* bit zero is never a legal Sudoku pencil digit */
    CHECK(sudoku_game_eliminate_notes(game,masks,&removed)==SUDOKU_GAME_RANGE);
    CHECK(removed==0u && game->history_cursor==cursor);
    masks[2]=0u;
    masks[3]=0u;
    CHECK(sudoku_game_eliminate_notes(game,NULL,&removed)==SUDOKU_GAME_INVALID);
    CHECK(removed==0u);
    CHECK(sudoku_game_eliminate_notes(game,masks,&removed)==SUDOKU_GAME_OK);
    CHECK(removed==0u && game->history_cursor==cursor &&
          game->history_len==length);
    CHECK(sudoku_game_redo(game)==SUDOKU_GAME_OK);
    CHECK(game->state.notes[2]==(1u<<2));
    /* External corruption must fail without updating any history entry. */
    masks[2]=(uint16_t)(1u<<2);
    game->state.board.cells[2]=10u;
    cursor=game->history_cursor;
    CHECK(sudoku_game_eliminate_notes(game,masks,&removed)==SUDOKU_GAME_INVALID);
    CHECK(removed==0u && game->history_cursor==cursor);
    free(game);
    return 0;
}
/* Absolute history navigation is atomic, validates the destination,
 * preserves redo, and can recover from a malformed current public board. */
static int check_history_goto(void){
    SudokuBoard board;
    SudokuGame *game=(SudokuGame *)malloc(sizeof *game);
    unsigned cursor,length;
    CHECK(game!=NULL);
    CHECK(sudoku_board_parse(&board,(const unsigned char *)classic,81u,NULL)==SUDOKU_OK);
    CHECK(sudoku_game_start(game,&board)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_history_goto(game,0u)==SUDOKU_GAME_OK);
    CHECK(game->history_cursor==0u&&game->history_len==1u);
    CHECK(sudoku_game_history_goto(game,1u)==SUDOKU_GAME_NO_HISTORY);
    CHECK(sudoku_game_history_goto(game,128u)==SUDOKU_GAME_RANGE);
    CHECK(sudoku_game_history_goto(game,UINT32_MAX)==SUDOKU_GAME_RANGE);
    CHECK(sudoku_game_history_goto(NULL,0u)==SUDOKU_GAME_INVALID);
    CHECK(sudoku_game_set(game,1u,3u,4u)==SUDOKU_GAME_OK);
    CHECK(sudoku_game_set_notes(game,1u,4u,
          (uint16_t)((1u<<1)|(1u<<9)))==SUDOKU_GAME_OK);
    CHECK(game->history_len==3u&&game->history_cursor==2u);
    CHECK(game->state.board.cells[2]==4u);
    CHECK(game->state.notes[3]==((1u<<1)|(1u<<9)));
    CHECK(sudoku_game_history_goto(game,0u)==SUDOKU_GAME_OK);
    CHECK(game->history_len==3u&&game->history_cursor==0u);
    CHECK(game->state.board.cells[2]==0u&&game->state.notes[3]==0u);
    CHECK(sudoku_game_history_goto(game,2u)==SUDOKU_GAME_OK);
    CHECK(game->state.board.cells[2]==4u);
    CHECK(game->state.notes[3]==((1u<<1)|(1u<<9)));
    CHECK(sudoku_game_history_goto(game,1u)==SUDOKU_GAME_OK);
    CHECK(game->state.board.cells[2]==4u&&game->state.notes[3]==0u);
    cursor=game->history_cursor;
    length=game->history_len;
    CHECK(sudoku_game_history_goto(game,1u)==SUDOKU_GAME_OK);
    CHECK(game->history_cursor==cursor&&game->history_len==length);
    CHECK(sudoku_game_history_goto(game,3u)==SUDOKU_GAME_NO_HISTORY);
    CHECK(game->history_cursor==cursor&&game->history_len==length);
    /* Invalid target clue and note masks must reject atomically. */
    game->history[0].board.cells[0]=0u;
    CHECK(sudoku_game_history_goto(game,0u)==SUDOKU_GAME_INVALID);
    CHECK(game->history_cursor==cursor&&game->state.board.cells[2]==4u);
    game->history[0].board.cells[0]=5u;
    game->history[0].notes[2]=1u;
    CHECK(sudoku_game_history_goto(game,0u)==SUDOKU_GAME_INVALID);
    CHECK(game->history_cursor==cursor&&game->state.board.cells[2]==4u);
    game->history[0].notes[2]=0u;
    /* A valid snapshot is a recovery point for corrupted live state. */
    game->state.board.cells[2]=10u;
    CHECK(sudoku_game_history_goto(game,0u)==SUDOKU_GAME_OK);
    CHECK(game->history_cursor==0u&&game->state.board.cells[2]==0u);
    CHECK(sudoku_game_history_goto(game,1u)==SUDOKU_GAME_OK);
    /* Editing after seeking to the middle discards prior redo branch. */
    CHECK(sudoku_game_set(game,1u,4u,6u)==SUDOKU_GAME_OK);
    CHECK(game->history_cursor==2u&&game->history_len==3u);
    CHECK(game->state.board.cells[3]==6u&&game->state.notes[3]==0u);
    CHECK(sudoku_game_history_goto(game,3u)==SUDOKU_GAME_NO_HISTORY);
    CHECK(sudoku_game_history_goto(game,2u)==SUDOKU_GAME_OK);
    CHECK(game->state.board.cells[3]==6u);
    free(game);
    return 0;
}
int main(void){
    int result=check_game();
    if(result)return result;
    result=check_mistake_clear();
    if(result)return result;
    result=check_batch_set();
    if(result)return result;
    result=check_history_steps();
    if(result)return result;
    result=check_history_goto();
    if(result)return result;
    result=check_note_elimination();
    if(!result)puts("GAME ENGINE PASS: unique, givens, notes, history, reset, save/load/corruption, win, check-clear, batch-set, multi-step undo/redo, selective note elimination");
    return result;
}
