#if !defined(_WIN32)
#define _POSIX_C_SOURCE 200809L
#endif
#include "sudoku/game.h"
#include "sudoku/solver.h"
#include <inttypes.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#if defined(_WIN32)
#include <windows.h>
#include <io.h>
#else
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#endif

static int cell_index(unsigned row, unsigned col) {
    if (row < 1u || row > 9u || col < 1u || col > 9u) return -1;
    return (int)((row - 1u) * 9u + col - 1u);
}
static int valid_game(const SudokuGame *game) {
    return game != NULL && game->history_len >= 1u &&
           game->history_len <= SUDOKU_GAME_HISTORY &&
           game->history_cursor < game->history_len;
}
/* SudokuGame is public and C callers may edit its fields directly.
 * Reject conflicting boards and any altered original clue before making
 * new undo snapshots, including edits that would otherwise be no-ops.
 * This check never consults the cached solution. */
static int valid_live_board(const SudokuGame *game) {
    unsigned i;
    if (!valid_game(game) ||
        sudoku_board_validate(&game->givens, NULL) != SUDOKU_OK ||
        sudoku_board_validate(&game->state.board, NULL) != SUDOKU_OK)
        return 0;
    for (i = 0u; i < SUDOKU_CELL_COUNT; ++i)
        if (game->givens.cells[i] &&
            game->state.board.cells[i] != game->givens.cells[i])
            return 0;
    return 1;
}
/* The public snapshot stores pencil marks as bits 1..9 only; filled cells
 * cannot have notes. Ordinary edits must not copy bad public notes into
 * a new, unrestorable Undo/Redo record. */
static int valid_snapshot_notes(const SudokuGameSnapshot *snapshot) {
    unsigned i;
    for (i = 0u; i < SUDOKU_CELL_COUNT; ++i)
        if ((snapshot->notes[i] & (uint16_t)~0x3feu) != 0u ||
            (snapshot->board.cells[i] && snapshot->notes[i]))
            return 0;
    return 1;
}
static int valid_live_state(const SudokuGame *game) {
    return valid_live_board(game) && valid_snapshot_notes(&game->state);
}
static void remember(SudokuGame *game) {
    if (game->history_cursor + 1u < game->history_len)
        game->history_len = game->history_cursor + 1u;
    if (game->history_len == SUDOKU_GAME_HISTORY) {
        memmove(game->history, game->history + 1,
                (SUDOKU_GAME_HISTORY - 1u) * sizeof game->history[0]);
        --game->history_len;
        --game->history_cursor;
    }
    game->history[game->history_len++] = game->state;
    game->history_cursor = game->history_len - 1u;
}
SudokuGameStatus sudoku_game_start(SudokuGame *game, const SudokuBoard *givens) {
    SudokuGame fresh;
    SudokuSolveStatus analyzed;
    if (!game || !givens) return SUDOKU_GAME_INVALID;
    if (sudoku_board_validate(givens, NULL) != SUDOKU_OK) return SUDOKU_GAME_INVALID;
    memset(&fresh, 0, sizeof fresh);
    analyzed = sudoku_solve_first(givens, &fresh.solution);
    if (analyzed == SUDOKU_SOLVE_UNSOLVABLE) return SUDOKU_GAME_UNSOLVABLE;
    if (analyzed == SUDOKU_SOLVE_MULTIPLE) return SUDOKU_GAME_MULTIPLE;
    if (analyzed != SUDOKU_SOLVE_UNIQUE) return SUDOKU_GAME_INVALID;
    fresh.givens = *givens;
    fresh.state.board = *givens;
    fresh.history[0] = fresh.state;
    fresh.history_len = 1;
    fresh.session_start = time(NULL);
    *game = fresh;
    return SUDOKU_GAME_OK;
}
SudokuGameStatus sudoku_game_set(SudokuGame *game, unsigned row, unsigned col, unsigned digit) {
    int idx = cell_index(row, col);
    SudokuBoard candidate;
    if (!valid_game(game)) return SUDOKU_GAME_INVALID;
    if (idx < 0 || digit < 1u || digit > 9u) return SUDOKU_GAME_RANGE;
    if (!valid_live_state(game)) return SUDOKU_GAME_INVALID;
    if (game->givens.cells[idx]) return SUDOKU_GAME_GIVEN;
    if (game->state.board.cells[idx] == digit) return SUDOKU_GAME_OK;
    candidate = game->state.board;
    candidate.cells[idx] = (uint8_t)digit;
    if (sudoku_board_validate(&candidate, NULL) != SUDOKU_OK) return SUDOKU_GAME_CONFLICT;
    game->state.board = candidate;
    game->state.notes[idx] = 0;
    remember(game);
    return SUDOKU_GAME_OK;
}
/* Verify the entire proposed batch before committing a single history edit.
 * A batch is a placement operation, not a way to replace existing entries.
 * Sudoku clues and the solution cache are never used to select new values. */
SudokuGameStatus sudoku_game_set_many(SudokuGame *game,
                                      const SudokuGameMove *moves,
                                      unsigned count, unsigned *applied) {
    SudokuGameSnapshot proposed;
    unsigned char seen[SUDOKU_CELL_COUNT] = {0};
    unsigned i;
    if (applied) *applied = 0u;
    if (!valid_game(game) || count > SUDOKU_CELL_COUNT ||
        (count != 0u && moves == NULL))
        return SUDOKU_GAME_INVALID;
    if (!valid_live_state(game)) return SUDOKU_GAME_INVALID;
    if (count == 0u) return SUDOKU_GAME_OK;
    proposed = game->state;
    for (i = 0u; i < count; ++i) {
        int index = cell_index(moves[i].row, moves[i].col);
        if (index < 0 || moves[i].digit < 1u || moves[i].digit > 9u)
            return SUDOKU_GAME_RANGE;
        if (seen[index]) return SUDOKU_GAME_INVALID;
        seen[index] = 1u;
        if (game->givens.cells[index]) return SUDOKU_GAME_GIVEN;
        if (game->state.board.cells[index]) return SUDOKU_GAME_NOT_EMPTY;
        proposed.board.cells[index] = (uint8_t)moves[i].digit;
        proposed.notes[index] = 0u;
    }
    if (sudoku_board_validate(&proposed.board, NULL) != SUDOKU_OK)
        return SUDOKU_GAME_CONFLICT;
    game->state = proposed;
    remember(game);
    if (applied) *applied = count;
    return SUDOKU_GAME_OK;
}
SudokuGameStatus sudoku_game_erase(SudokuGame *game, unsigned row, unsigned col) {
    int idx = cell_index(row, col);
    if (!valid_game(game)) return SUDOKU_GAME_INVALID;
    if (idx < 0) return SUDOKU_GAME_RANGE;
    if (!valid_live_state(game)) return SUDOKU_GAME_INVALID;
    if (game->givens.cells[idx]) return SUDOKU_GAME_GIVEN;
    /* Erasing an editable cell clears its value AND its pencil marks.
     * Previously 'erase' on an empty noted cell silently did nothing,
     * leaving no one-step way to clear its candidates. */
    if (game->state.board.cells[idx] == 0u &&
        game->state.notes[idx] == 0u) return SUDOKU_GAME_OK;
    game->state.board.cells[idx] = 0u;
    game->state.notes[idx] = 0u;
    remember(game);
    return SUDOKU_GAME_OK;
}
/* Erase a validated list as one transaction, including handwritten notes on
 * blank cells. The state is replaced only after every target has passed;
 * a wholly unchanged batch preserves even an existing Redo branch. */
SudokuGameStatus sudoku_game_erase_many(SudokuGame *game,
                                         const SudokuGameCell *cells,
                                         unsigned count, unsigned *cleared) {
    SudokuGameSnapshot proposed;
    unsigned char seen[SUDOKU_CELL_COUNT] = {0};
    unsigned i, changed = 0u;
    if (cleared) *cleared = 0u;
    if (!valid_game(game) || count > SUDOKU_CELL_COUNT ||
        (count != 0u && cells == NULL))
        return SUDOKU_GAME_INVALID;
    if (!valid_live_state(game)) return SUDOKU_GAME_INVALID;
    if (count == 0u) return SUDOKU_GAME_OK;
    proposed = game->state;
    for (i = 0u; i < count; ++i) {
        int index = cell_index(cells[i].row, cells[i].col);
        if (index < 0) return SUDOKU_GAME_RANGE;
        if (seen[index]) return SUDOKU_GAME_INVALID;
        seen[index] = 1u;
        if (game->givens.cells[index]) return SUDOKU_GAME_GIVEN;
        if (proposed.board.cells[index] || proposed.notes[index]) {
            proposed.board.cells[index] = 0u;
            proposed.notes[index] = 0u;
            ++changed;
        }
    }
    if (changed == 0u) return SUDOKU_GAME_OK;
    game->state = proposed;
    remember(game);
    if (cleared) *cleared = changed;
    return SUDOKU_GAME_OK;
}
/* Current-board row/column/box candidates. Never consult game->solution.
 * Returns 0 for a filled cell, invalid coordinates or an invalid game. */
/* Requires a previously validated SudokuBoard, with row and column in 1..9.
 * Keeps one-shot bulk note operations from validating the board 81 times. */
static uint16_t validated_candidates(const SudokuBoard *board,
                                     unsigned row, unsigned col) {
    uint16_t used = 0u;
    unsigned k, base_row, base_col, index = (row - 1u) * 9u + col - 1u;
    if (board->cells[index]) return 0u;
    base_row = ((row - 1u) / 3u) * 3u;
    base_col = ((col - 1u) / 3u) * 3u;
    for (k = 0u; k < 9u; ++k) {
        used = (uint16_t)(used | (uint16_t)(1u << board->cells[(row - 1u) * 9u + k]));
        used = (uint16_t)(used | (uint16_t)(1u << board->cells[k * 9u + (col - 1u)]));
        used = (uint16_t)(used | (uint16_t)(1u << board->cells[
            (base_row + k / 3u) * 9u + base_col + k % 3u]));
    }
    return (uint16_t)(0x3feu & (unsigned)~used);
}
uint16_t sudoku_game_candidates(const SudokuGame *game, unsigned row, unsigned col) {
    int idx = cell_index(row, col);
    if (!valid_game(game) || idx < 0 || game->state.board.cells[idx])
        return 0u;
    /* This observational API intentionally accepts any independently valid
     * current board (including property-test boards with unrelated givens).
     * Unlike mutators, it does not require original-clue invariants. */
    if (sudoku_board_validate(&game->state.board, NULL) != SUDOKU_OK)
        return 0u;
    return validated_candidates(&game->state.board, row, col);
}
/* Recompute canonical pencil marks in one undoable snapshot: legal
 * candidates on empty cells and zero notes on every filled cell. This also
 * repairs malformed public notes without changing any board digit. Repeated
 * unchanged actions preserve Undo/Redo; no solution value is consulted. */
SudokuGameStatus sudoku_game_auto_notes(SudokuGame *game) {
    SudokuGameSnapshot proposed;
    unsigned index;
    int changed = 0;
    if (!valid_game(game)) return SUDOKU_GAME_INVALID;
    /* Reject bad public grids or altered clues without changing history. */
    if (!valid_live_board(game)) return SUDOKU_GAME_INVALID;
    proposed = game->state;
    for (index = 0u; index < SUDOKU_CELL_COUNT; ++index) {
        uint16_t mask;
        mask = game->state.board.cells[index] ? 0u :
            validated_candidates(&game->state.board,
                                 index / 9u + 1u, index % 9u + 1u);
        if (proposed.notes[index] != mask) {
            proposed.notes[index] = mask;
            changed = 1;
        }
    }
    if (!changed) return SUDOKU_GAME_OK;
    game->state = proposed;
    remember(game);
    return SUDOKU_GAME_OK;
}
/* Remove only stale pencil candidates while preserving the player's legal
 * manual notes. No marks are added. Commit one undoable history snapshot if
 * and only if an actual change occurred, preserving redo after no-op calls. */
SudokuGameStatus sudoku_game_prune_notes(SudokuGame *game) {
    SudokuGameSnapshot proposed;
    unsigned index;
    int changed = 0;
    if (!valid_live_board(game)) return SUDOKU_GAME_INVALID;
    proposed = game->state;
    for (index = 0u; index < SUDOKU_CELL_COUNT; ++index) {
        uint16_t allowed, retained;
        if (!proposed.notes[index]) continue;
        allowed = validated_candidates(&game->state.board,
                                       index / 9u + 1u, index % 9u + 1u);
        retained = (uint16_t)(proposed.notes[index] & allowed);
        if (retained != proposed.notes[index]) {
            proposed.notes[index] = retained;
            changed = 1;
        }
    }
    if (!changed) return SUDOKU_GAME_OK;
    game->state = proposed;
    remember(game);
    return SUDOKU_GAME_OK;
}
SudokuGameStatus sudoku_game_note(SudokuGame *game, unsigned row, unsigned col, unsigned digit) {
    int idx = cell_index(row, col);
    if (!valid_game(game)) return SUDOKU_GAME_INVALID;
    if (idx < 0 || digit < 1u || digit > 9u) return SUDOKU_GAME_RANGE;
    if (!valid_live_state(game)) return SUDOKU_GAME_INVALID;
    if (game->givens.cells[idx]) return SUDOKU_GAME_GIVEN;
    if (game->state.board.cells[idx]) return SUDOKU_GAME_NOT_EMPTY;
    game->state.notes[idx] ^= (uint16_t)(1u << digit);
    remember(game);
    return SUDOKU_GAME_OK;
}
/* Replace all pencil marks in a single editable cell as one undoable move.
 * Unlike toggling notes one by one, this is idempotent and preserves redo
 * when the requested set already matches the live set. Manual pencil notes
 * need not be currently legal candidates, consistent with sudoku_game_note. */
SudokuGameStatus sudoku_game_set_notes(SudokuGame *game,
                                      unsigned row,unsigned col,uint16_t mask) {
    int idx=cell_index(row,col);
    if (!valid_game(game)) return SUDOKU_GAME_INVALID;
    if (idx<0 || (mask & (uint16_t)~0x3feu)!=0u) return SUDOKU_GAME_RANGE;
    if (!valid_live_state(game)) return SUDOKU_GAME_INVALID;
    if (game->givens.cells[idx]) return SUDOKU_GAME_GIVEN;
    if (game->state.board.cells[idx]) return SUDOKU_GAME_NOT_EMPTY;
    if (game->state.notes[idx]==mask) return SUDOKU_GAME_OK;
    game->state.notes[idx]=mask;
    remember(game);
    return SUDOKU_GAME_OK;
}
/* Atomically set explicit pencil masks on distinct editable empty cells.
 * No live state or history changes until every requested edit validates. */
SudokuGameStatus sudoku_game_set_notes_many(SudokuGame *game,
                                           const SudokuGameNoteEdit *edits,
                                           unsigned count,unsigned *changed) {
    SudokuGameSnapshot proposed;
    unsigned char seen[SUDOKU_CELL_COUNT]={0};
    unsigned i,updates=0u;
    if(changed)*changed=0u;
    if(!valid_game(game)||count>SUDOKU_CELL_COUNT||
       (count!=0u && edits==NULL))return SUDOKU_GAME_INVALID;
    if(!valid_live_state(game))return SUDOKU_GAME_INVALID;
    if(count==0u)return SUDOKU_GAME_OK;
    proposed=game->state;
    for(i=0u;i<count;++i){
        int idx=cell_index(edits[i].row,edits[i].col);
        uint16_t mask=edits[i].mask;
        if(idx<0||(mask&(uint16_t)~0x3feu)!=0u)return SUDOKU_GAME_RANGE;
        if(seen[idx])return SUDOKU_GAME_INVALID;
        seen[idx]=1u;
        if(game->givens.cells[idx])return SUDOKU_GAME_GIVEN;
        if(game->state.board.cells[idx])return SUDOKU_GAME_NOT_EMPTY;
        if(proposed.notes[idx]!=mask){proposed.notes[idx]=mask;++updates;}
    }
    if(!updates)return SUDOKU_GAME_OK;
    game->state=proposed;
    remember(game);
    if(changed)*changed=updates;
    return SUDOKU_GAME_OK;
}
/* Apply additions/removals of pencil marks across multiple editable cells.
 * Transform every mask against the same validated live snapshot, then use
 * the all-or-nothing setter to detect duplicate/given/filled targets. */
static SudokuGameStatus modify_notes_many(SudokuGame *game,
                                         const SudokuGameNoteEdit *edits,
                                         unsigned count,unsigned *changed,
                                         int mode) {
    SudokuGameNoteEdit proposed[SUDOKU_CELL_COUNT];
    unsigned i;
    if(changed)*changed=0u;
    if(!valid_game(game)||count>SUDOKU_CELL_COUNT||
       (count!=0u&&edits==NULL))return SUDOKU_GAME_INVALID;
    if(!valid_live_state(game))return SUDOKU_GAME_INVALID;
    for(i=0u;i<count;++i){
        int idx=cell_index(edits[i].row,edits[i].col);
        if(idx<0||(edits[i].mask&(uint16_t)~0x3feu)!=0u)
            return SUDOKU_GAME_RANGE;
        proposed[i]=edits[i];
        proposed[i].mask=mode==1 ?
            (uint16_t)(game->state.notes[idx]|edits[i].mask) :
            mode==0 ? (uint16_t)(game->state.notes[idx]&(uint16_t)~edits[i].mask) :
                      (uint16_t)(game->state.notes[idx]^edits[i].mask);
    }
    return sudoku_game_set_notes_many(game,proposed,count,changed);
}
SudokuGameStatus sudoku_game_add_notes_many(SudokuGame *game,
                                           const SudokuGameNoteEdit *edits,
                                           unsigned count,unsigned *changed) {
    return modify_notes_many(game,edits,count,changed,1);
}
SudokuGameStatus sudoku_game_remove_notes_many(SudokuGame *game,
                                              const SudokuGameNoteEdit *edits,
                                              unsigned count,unsigned *changed) {
    return modify_notes_many(game,edits,count,changed,0);
}
SudokuGameStatus sudoku_game_toggle_notes_many(SudokuGame *game,
                                              const SudokuGameNoteEdit *edits,
                                              unsigned count,unsigned *changed) {
    return modify_notes_many(game,edits,count,changed,2);
}
/* Add or remove a group of pencil digits in one undoable edit. Compute
 * the desired mask, then let set_notes enforce all public-board, clue and
 * pencil-integrity invariants before touching live history. Note that
 * removal must validate the supplied mask BEFORE applying complement:
 * otherwise an illegal bit would silently disappear as a no-op. */
static SudokuGameStatus modify_notes(SudokuGame *game,unsigned row,
                                      unsigned col,uint16_t mask,int add) {
    int idx=cell_index(row,col);
    uint16_t next;
    if (!game) return SUDOKU_GAME_INVALID;
    if (idx<0 || (mask & (uint16_t)~0x3feu)!=0u) return SUDOKU_GAME_RANGE;
    next=add ? (uint16_t)(game->state.notes[idx]|mask) :
               (uint16_t)(game->state.notes[idx]&(uint16_t)~mask);
    return sudoku_game_set_notes(game,row,col,next);
}
SudokuGameStatus sudoku_game_add_notes(SudokuGame *game,
                                     unsigned row,unsigned col,uint16_t mask) {
    return modify_notes(game,row,col,mask,1);
}
SudokuGameStatus sudoku_game_remove_notes(SudokuGame *game,
                                        unsigned row,unsigned col,uint16_t mask) {
    return modify_notes(game,row,col,mask,0);
}
/* Refresh one cell from the live row/column/box constraints, never the
 * cached solved grid. 'fill' replaces that cell's pencil marks with all
 * currently legal candidates; 'prune' intersects existing marks with them.
 * Verify public game state before computing or committing any new snapshot.
 * Repeated identical operations retain both Undo and Redo history. */
static SudokuGameStatus refresh_cell_notes(SudokuGame *game,
                                            unsigned row,unsigned col,
                                            int prune) {
    int idx=cell_index(row,col);
    uint16_t legal,mask;
    if (!valid_game(game)) return SUDOKU_GAME_INVALID;
    if (idx<0) return SUDOKU_GAME_RANGE;
    if (!valid_live_state(game)) return SUDOKU_GAME_INVALID;
    if (game->givens.cells[idx]) return SUDOKU_GAME_GIVEN;
    if (game->state.board.cells[idx]) return SUDOKU_GAME_NOT_EMPTY;
    legal=validated_candidates(&game->state.board,row,col);
    mask=prune ? (uint16_t)(game->state.notes[idx]&legal) : legal;
    return sudoku_game_set_notes(game,row,col,mask);
}
SudokuGameStatus sudoku_game_fill_cell_notes(SudokuGame *game,
                                              unsigned row,unsigned col) {
    return refresh_cell_notes(game,row,col,0);
}
SudokuGameStatus sudoku_game_prune_cell_notes(SudokuGame *game,
                                               unsigned row,unsigned col) {
    return refresh_cell_notes(game,row,col,1);
}
/* Refresh one row, column or box as a single undoable pencil-note edit.
 * Only editable blanks in the chosen unit change. Live candidates are used,
 * never the cached solution; invalid public state fails before mutation. */
static SudokuGameStatus refresh_unit_notes(SudokuGame *game,
                                            SudokuGameUnit unit,
                                            unsigned number,int prune) {
    SudokuGameSnapshot next;
    unsigned slot;
    int changed=0;
    if(!valid_game(game))return SUDOKU_GAME_INVALID;
    if(number<1u||number>9u||
       (unit!=SUDOKU_GAME_ROW&&unit!=SUDOKU_GAME_COLUMN&&
        unit!=SUDOKU_GAME_BOX))return SUDOKU_GAME_RANGE;
    if(!valid_live_state(game))return SUDOKU_GAME_INVALID;
    next=game->state;
    for(slot=0u;slot<9u;++slot){
        unsigned index,row,col;
        uint16_t allowed,mask;
        if(unit==SUDOKU_GAME_ROW)
            index=(number-1u)*9u+slot;
        else if(unit==SUDOKU_GAME_COLUMN)
            index=slot*9u+number-1u;
        else {
            unsigned box=number-1u;
            index=((box/3u)*3u+slot/3u)*9u+(box%3u)*3u+slot%3u;
        }
        if(next.board.cells[index])continue;
        row=index/9u+1u;
        col=index%9u+1u;
        allowed=validated_candidates(&game->state.board,row,col);
        mask=prune?(uint16_t)(game->state.notes[index]&allowed):allowed;
        if(next.notes[index]!=mask){
            next.notes[index]=mask;
            changed=1;
        }
    }
    if(!changed)return SUDOKU_GAME_OK;
    game->state=next;
    remember(game);
    return SUDOKU_GAME_OK;
}
SudokuGameStatus sudoku_game_fill_unit_notes(SudokuGame *game,
                                              SudokuGameUnit unit,unsigned number) {
    return refresh_unit_notes(game,unit,number,0);
}
SudokuGameStatus sudoku_game_prune_unit_notes(SudokuGame *game,
                                               SudokuGameUnit unit,unsigned number) {
    return refresh_unit_notes(game,unit,number,1);
}
/* Validate the entire proposed elimination before changing one note bit.
 * This is a general-purpose, solution-blind pencil-mark operation. */
SudokuGameStatus sudoku_game_eliminate_notes(
    SudokuGame *game, const uint16_t masks[SUDOKU_CELL_COUNT], unsigned *removed) {
    SudokuGameSnapshot proposed;
    unsigned i, d, total=0u;
    if (removed) *removed=0u;
    if (!valid_game(game) || !masks) return SUDOKU_GAME_INVALID;
    if (!valid_live_state(game)) return SUDOKU_GAME_INVALID;
    for (i=0u;i<SUDOKU_CELL_COUNT;++i) {
        if ((masks[i] & (uint16_t)~0x3feu)!=0u)
            return SUDOKU_GAME_RANGE;
        if (masks[i] && game->state.board.cells[i])
            return SUDOKU_GAME_NOT_EMPTY;
    }
    proposed=game->state;
    for (i=0u;i<SUDOKU_CELL_COUNT;++i) {
        uint16_t deleted=(uint16_t)(proposed.notes[i]&masks[i]);
        if (!deleted)continue;
        proposed.notes[i]=(uint16_t)(proposed.notes[i]&(uint16_t)~deleted);
        for (d=1u;d<=9u;++d)
            if (deleted & (uint16_t)(1u<<d))++total;
    }
    if (total) {
        game->state=proposed;
        remember(game);
    }
    if (removed)*removed=total;
    return SUDOKU_GAME_OK;
}
/* Clear all pencil marks in one undoable step, without changing placed
 * digits or givens. A second clear is history-neutral. */
SudokuGameStatus sudoku_game_clear_notes(SudokuGame *game) {
    unsigned i;
    if (!valid_live_board(game)) return SUDOKU_GAME_INVALID;
    for (i = 0u; i < SUDOKU_CELL_COUNT; ++i)
        if (game->state.notes[i] != 0u) break;
    if (i == SUDOKU_CELL_COUNT) return SUDOKU_GAME_OK;
    memset(game->state.notes, 0, sizeof game->state.notes);
    remember(game);
    return SUDOKU_GAME_OK;
}
/* Discard wrong player-entered digits without exposing or inserting any
 * solution digit. Commit the whole cleanup as one undoable change. Public
 * game structs may be mutated externally, so refuse an inconsistent puzzle,
 * current board or cached solved grid before changing any state. */
SudokuGameStatus sudoku_game_clear_mistakes(SudokuGame *game) {
    SudokuGameSnapshot proposed;
    unsigned index;
    int changed = 0;
    if (!valid_live_state(game) ||
        sudoku_board_validate(&game->solution, NULL) != SUDOKU_OK)
        return SUDOKU_GAME_INVALID;
    for (index = 0u; index < SUDOKU_CELL_COUNT; ++index) {
        if (game->solution.cells[index] < 1u ||
            game->solution.cells[index] > 9u ||
            (game->givens.cells[index] &&
             (game->solution.cells[index] != game->givens.cells[index] ||
              game->state.board.cells[index] != game->givens.cells[index])))
            return SUDOKU_GAME_INVALID;
    }
    proposed = game->state;
    for (index = 0u; index < SUDOKU_CELL_COUNT; ++index) {
        if (proposed.board.cells[index] != 0u &&
            proposed.board.cells[index] != game->solution.cells[index]) {
            proposed.board.cells[index] = 0u;
            proposed.notes[index] = 0u;
            changed = 1;
        }
    }
    if (!changed) return SUDOKU_GAME_OK;
    game->state = proposed;
    remember(game);
    return SUDOKU_GAME_OK;
}
/* Historical snapshots are public fields too. Do not restore a tampered
 * snapshot with invalid clues, out-of-range or conflicting values, illegal
 * pencil bits, or notes on filled cells. Validate only the destination:
 * Undo can still recover a corrupted *current* board when history is sound. */
static int valid_history_target(const SudokuGame *game,
                                const SudokuGameSnapshot *target) {
    unsigned i;
    if (sudoku_board_validate(&game->givens, NULL) != SUDOKU_OK ||
        sudoku_board_validate(&target->board, NULL) != SUDOKU_OK)
        return 0;
    for (i = 0u; i < SUDOKU_CELL_COUNT; ++i)
        if (game->givens.cells[i] &&
            target->board.cells[i] != game->givens.cells[i])
            return 0;
    return valid_snapshot_notes(target);
}
/* Bounds and destination integrity are checked before changing the
 * history cursor or live board; failed multi-step actions are atomic. */
SudokuGameStatus sudoku_game_undo_steps(SudokuGame *game, unsigned steps) {
    unsigned target;
    if (!valid_game(game)) return SUDOKU_GAME_INVALID;
    if (steps == 0u || steps >= SUDOKU_GAME_HISTORY) return SUDOKU_GAME_RANGE;
    if (steps > game->history_cursor) return SUDOKU_GAME_NO_HISTORY;
    target = game->history_cursor - steps;
    if (!valid_history_target(game, &game->history[target]))
        return SUDOKU_GAME_INVALID;
    game->history_cursor = target;
    game->state = game->history[target];
    return SUDOKU_GAME_OK;
}
SudokuGameStatus sudoku_game_redo_steps(SudokuGame *game, unsigned steps) {
    unsigned target;
    if (!valid_game(game)) return SUDOKU_GAME_INVALID;
    if (steps == 0u || steps >= SUDOKU_GAME_HISTORY) return SUDOKU_GAME_RANGE;
    if (steps > game->history_len - 1u - game->history_cursor)
        return SUDOKU_GAME_NO_HISTORY;
    target = game->history_cursor + steps;
    if (!valid_history_target(game, &game->history[target]))
        return SUDOKU_GAME_INVALID;
    game->history_cursor = target;
    game->state = game->history[target];
    return SUDOKU_GAME_OK;
}
/* Seek a retained history snapshot by its absolute zero-based step.
 * Unlike a sequence of Undo/Redo calls, validate the destination before
 * changing either cursor or state; preserve the entire redo branch.
 * A corrupted current live board may be recovered from a valid target.
 * Re-seeking the current step is a history-neutral validated no-op. */
SudokuGameStatus sudoku_game_history_goto(SudokuGame *game,unsigned step) {
    if (!valid_game(game)) return SUDOKU_GAME_INVALID;
    if (step >= SUDOKU_GAME_HISTORY) return SUDOKU_GAME_RANGE;
    if (step >= game->history_len) return SUDOKU_GAME_NO_HISTORY;
    if (!valid_history_target(game,&game->history[step]))
        return SUDOKU_GAME_INVALID;
    game->history_cursor=step;
    game->state=game->history[step];
    return SUDOKU_GAME_OK;
}
SudokuGameStatus sudoku_game_undo(SudokuGame *game) {
    return sudoku_game_undo_steps(game, 1u);
}
SudokuGameStatus sudoku_game_redo(SudokuGame *game) {
    return sudoku_game_redo_steps(game, 1u);
}
SudokuGameStatus sudoku_game_reset(SudokuGame *game) {
    SudokuGameSnapshot cleared = {0};
    unsigned i;
    if (!valid_game(game)) return SUDOKU_GAME_INVALID;
    /* Share the same original-clue and valid-board invariant as all edits. */
    if (!valid_live_board(game)) return SUDOKU_GAME_INVALID;
    cleared.board = game->givens;
    /* Compare meaningful state rather than struct bytes: the snapshot
     * contains ABI padding between the 81-byte board and uint16_t notes.
     * Comparing padding can turn an already-cleared reset into an undo step. */
    if (memcmp(game->state.board.cells, game->givens.cells,
               sizeof game->givens.cells) == 0) {
        for (i = 0; i < SUDOKU_CELL_COUNT; ++i)
            if (game->state.notes[i] != 0u) break;
        if (i == SUDOKU_CELL_COUNT) return SUDOKU_GAME_OK;
    }
    game->state = cleared;
    remember(game);
    return SUDOKU_GAME_OK;
}
unsigned sudoku_game_empty(const SudokuGame *game) {
    unsigned i, n = 0;
    if (!valid_game(game)) return 0;
    for (i = 0; i < 81u; ++i) n += game->state.board.cells[i] == 0u;
    return n;
}
unsigned sudoku_game_mistakes(const SudokuGame *game) {
    unsigned i, n = 0;
    if (!valid_game(game)) return 0;
    for (i = 0; i < 81u; ++i)
        n += game->state.board.cells[i] != 0u &&
             game->state.board.cells[i] != game->solution.cells[i];
    return n;
}
int sudoku_game_won(const SudokuGame *game) {
    return valid_game(game) &&
           memcmp(&game->state.board, &game->solution, sizeof game->solution) == 0;
}
uint64_t sudoku_game_elapsed(const SudokuGame *game) {
    time_t now;
    uint64_t secs;
    if (!valid_game(game)) return 0;
    now = time(NULL);
    /* The struct is public: a caller may supply an out-of-range base.
     * Clamp before subtraction so unsigned saturation cannot wrap around.
     * Compute the delta in unsigned arithmetic to avoid time_t signed
     * subtraction overflow for an extreme forward clock adjustment. */
    secs = game->elapsed_base > SUDOKU_MAX_ELAPSED_SECONDS
         ? SUDOKU_MAX_ELAPSED_SECONDS : game->elapsed_base;
    if (now != (time_t)-1 && game->session_start != (time_t)-1 && now > game->session_start) {
        uint64_t delta = (uint64_t)now - (uint64_t)game->session_start;
        secs = delta > SUDOKU_MAX_ELAPSED_SECONDS - secs
             ? SUDOKU_MAX_ELAPSED_SECONDS : secs + delta;
    }
    return secs;
}
const char *sudoku_game_status_text(SudokuGameStatus status) {
    switch(status) {
    case SUDOKU_GAME_OK: return "ok";
    case SUDOKU_GAME_INVALID: return "invalid puzzle or game";
    case SUDOKU_GAME_UNSOLVABLE: return "puzzle has no solution";
    case SUDOKU_GAME_MULTIPLE: return "puzzle must have a unique solution";
    case SUDOKU_GAME_GIVEN: return "cannot modify an original clue";
    case SUDOKU_GAME_CONFLICT: return "placement conflicts with Sudoku rules";
    case SUDOKU_GAME_RANGE: return "row, column and digit must be in 1..9";
    case SUDOKU_GAME_NOT_EMPTY: return "pencil notes only allowed in empty cells";
    case SUDOKU_GAME_NO_HISTORY: return "no action to undo or redo";
    case SUDOKU_GAME_CORRUPT: return "invalid or corrupted save file";
    case SUDOKU_GAME_IO: return "file operation failed";
    case SUDOKU_GAME_DURABILITY_UNCERTAIN: return "save replaced target, but parent directory sync failed; power-loss durability is unconfirmed";
    default: return "unknown game status";
    }
}

static uint64_t checksum(const unsigned char *bytes, size_t length) {
    uint64_t value = UINT64_C(14695981039346656037);
    size_t i;
    for(i=0;i<length;++i){ value ^= bytes[i]; value *= UINT64_C(1099511628211); }
    return value;
}
static char hex_digit(unsigned x) { return "0123456789ABCDEF"[x & 15u]; }
static int hex_value(unsigned char ch) {
    if (ch >= '0' && ch <= '9') return ch - '0';
    if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
    return -1;
}
/* A canonical, strictly bounded wire representation with a checksum.
 * The checksum detects accidental corruption; it is NOT authentication. */
static int render_save(const SudokuGame *game, char out[SUDOKU_SAVE_MAX_BYTES], size_t *length) {
    char givens[82], current[82], notes[244];
    SudokuBoard verified_solution;
    uint64_t elapsed;
    int n, tail;
    unsigned i;
    if (!valid_game(game)) return 0;
    /* The C game structure is public: callers can bypass the mutator APIs.
     * Do not publish a checksummed file that our own loader must reject.
     * Validate the full source and current board before opening any file. */
    if (sudoku_board_validate(&game->givens, NULL) != SUDOKU_OK ||
        sudoku_board_validate(&game->state.board, NULL) != SUDOKU_OK)
        return 0;
    /* Valid Sudoku constraints do not imply a uniquely solvable puzzle:
     * a caller can replace givens with an empty or unsatisfiable board.
     * Loading always demands UNIQUE, so require the same invariant on
     * saving and reject a stale/corrupted cached solution as well. */
    if (sudoku_solve_first(&game->givens, &verified_solution) != SUDOKU_SOLVE_UNIQUE ||
        memcmp(verified_solution.cells, game->solution.cells,
               sizeof verified_solution.cells) != 0)
        return 0;
    sudoku_board_compact(&game->givens, givens);
    sudoku_board_compact(&game->state.board, current);
    for (i=0;i<81u;++i) {
        unsigned note = game->state.notes[i];
        if ((game->givens.cells[i] != 0u &&
             game->state.board.cells[i] != game->givens.cells[i]) ||
            (game->state.board.cells[i] != 0u && note != 0u) ||
            note > 0x3feu || (note & 1u))
            return 0;
        notes[i*3] = hex_digit(note >> 8);
        notes[i*3+1] = hex_digit(note >> 4);
        notes[i*3+2] = hex_digit(note);
    }
    notes[243] = '\0';
    elapsed = sudoku_game_elapsed(game);
    n = snprintf(out, SUDOKU_SAVE_MAX_BYTES,
             "SUDOKU_SAVE_V1\nG=%s\nB=%s\nN=%s\nE=%" PRIu64 "\n",
             givens,current,notes,elapsed);
    if (n < 0 || (size_t)n + 20u >= SUDOKU_SAVE_MAX_BYTES) return 0;
    tail = snprintf(out+n, SUDOKU_SAVE_MAX_BYTES-(size_t)n,"C=%016" PRIX64 "\n",
                    checksum((const unsigned char*)out,(size_t)n));
    if (tail != 19) return 0;
    *length = (size_t)n+(size_t)tail;
    return 1;
}
static int parse_save(SudokuGame *out, const char *data, size_t size) {
    static const char prefix[] = "SUDOKU_SAVE_V1\nG=";
    char g[82], b[82];
    uint16_t notes[81];
    uint64_t elapsed=0, recorded=0;
    size_t p=0, i, body_size;
    SudokuBoard puzzle, board;
    SudokuGame candidate;
    if (size < sizeof prefix-1u+81u+3u+81u+3u+243u+3u+1u+3u+16u+1u) return 0;
    if (memcmp(data,prefix,sizeof prefix-1u)!=0) return 0;
    p=sizeof prefix-1u;
    memcpy(g,data+p,81);g[81]='\0'; p+=81;
    if (memcmp(data+p,"\nB=",3)!=0)return 0;
    p+=3;
    memcpy(b,data+p,81);b[81]='\0'; p+=81;
    if (memcmp(data+p,"\nN=",3)!=0)return 0;
    p+=3;
    for(i=0;i<81u;++i){
        int a=hex_value((unsigned char)data[p++]);
        int c=hex_value((unsigned char)data[p++]);
        int d=hex_value((unsigned char)data[p++]);
        if(a<0||c<0||d<0)return 0;
        notes[i]=(uint16_t)((unsigned)a*256u+(unsigned)c*16u+(unsigned)d);
        if(notes[i] > 0x3feu || (notes[i]&1u))return 0;
    }
    if(memcmp(data+p,"\nE=",3)!=0)return 0;
    p+=3;
    if(p>=size||data[p]<'0'||data[p]>'9')return 0;
    /* The writer emits one canonical decimal representation: zero is "0",
     * never "00", and positive values have no leading zeroes. */
    if(data[p]=='0' && p+1u<size && data[p+1u]>='0' && data[p+1u]<='9')return 0;
    while(p<size&&data[p]>='0'&&data[p]<='9'){
        unsigned d=(unsigned)(data[p++]-'0');
        if(elapsed > (SUDOKU_MAX_ELAPSED_SECONDS-d)/10u) return 0;
        elapsed=elapsed*10u+d;
    }
    if(p+3u+16u+1u!=size || memcmp(data+p,"\nC=",3)!=0)return 0;
    body_size=p+1u;
    p+=3;
    for(i=0;i<16u;++i){
        int digit=hex_value((unsigned char)data[p++]);
        if(digit<0)return 0;
        recorded=(recorded<<4u)|(unsigned)digit;
    }
    if(data[p]!='\n'||recorded!=checksum((const unsigned char*)data,body_size))return 0;
    if(sudoku_board_parse(&puzzle,(const unsigned char*)g,81,NULL)!=SUDOKU_OK)return 0;
    if(sudoku_board_parse(&board,(const unsigned char*)b,81,NULL)!=SUDOKU_OK)return 0;
    for(i=0;i<81u;++i){
        if(puzzle.cells[i] && board.cells[i]!=puzzle.cells[i])return 0;
        if(board.cells[i] && notes[i])return 0;
    }
    if(sudoku_game_start(&candidate,&puzzle)!=SUDOKU_GAME_OK)return 0;
    candidate.state.board=board;
    memcpy(candidate.state.notes,notes,sizeof notes);
    candidate.history[0]=candidate.state;
    candidate.elapsed_base=elapsed;
    candidate.session_start=time(NULL);
    *out=candidate;
    return 1;
}
#if !defined(_WIN32)
/* Never overwrite a nonregular directory entry with an atomic game save.
 * lstat deliberately does not follow symlinks (even those to regular files),
 * because rename would replace the link itself, not its target. The check is
 * repeated just before rename to narrow accidental path-replacement races;
 * it is not an atomic security guarantee against hostile concurrent writers. */
static int save_target_is_regular_or_absent(const char *path) {
    struct stat metadata;
    if (lstat(path, &metadata) == 0)
        return S_ISREG(metadata.st_mode);
    return errno == ENOENT;
}
/* Hold an identity for the parent directory *before* the file rename. An
 * independent reopen after rename must refer to the same directory inode,
 * not merely another directory occupying the same pathname. */
static int open_parent_directory(const char *path) {
    const char *slash = strrchr(path, '/');
    size_t length = slash == NULL ? 1u : (slash == path ? 1u : (size_t)(slash - path));
    char *parent = malloc(length + 1u);
    int fd, flags = O_RDONLY | O_NONBLOCK;
    struct stat metadata;
    if (parent == NULL) return -1;
    if (slash == NULL) parent[0] = '.';
    else if (slash == path) parent[0] = '/';
    else memcpy(parent, path, length);
    parent[length] = '\0';
#ifdef O_DIRECTORY
    flags |= O_DIRECTORY;
#endif
#ifdef O_CLOEXEC
    flags |= O_CLOEXEC;
#endif
    fd = open(parent, flags);
    free(parent);
    if (fd < 0) return -1;
    if (fstat(fd, &metadata) != 0 || !S_ISDIR(metadata.st_mode)) {
        (void)close(fd);
        return -1;
    }
    return fd;
}
/* A post-rename path may refer to an unrelated directory if it has been
 * atomically replaced. Syncing that replacement is NOT evidence that the
 * directory containing the saved file reached durable storage. Close both
 * descriptors whether verification succeeds or fails. */
static int sync_parent_directory(const char *path, int original_fd) {
    int current_fd = open_parent_directory(path);
    int ok = 0;
    struct stat original, current, after;
    if (current_fd >= 0) {
        ok = original_fd >= 0 &&
             fstat(original_fd, &original) == 0 &&
             fstat(current_fd, &current) == 0 &&
             original.st_dev == current.st_dev &&
             original.st_ino == current.st_ino;
        if (ok) ok = fsync(current_fd) == 0;
        /* fsync may race with another rename of the parent pathname.
         * Reopen after synchronization so a disappeared/replaced directory
         * is never reported as a durable save at the requested path. */
        if (ok) {
            int final_fd = open_parent_directory(path);
            ok = final_fd >= 0 &&
                 fstat(final_fd, &after) == 0 &&
                 original.st_dev == after.st_dev &&
                 original.st_ino == after.st_ino;
            if (final_fd >= 0 && close(final_fd) != 0) ok = 0;
        }
        if (close(current_fd) != 0) ok = 0;
    }
    if (original_fd >= 0 && close(original_fd) != 0) ok = 0;
    return ok;
}
#endif

SudokuGameStatus sudoku_game_save(const SudokuGame *game, const char *path) {
#if defined(_WIN32)
    /* InterlockedIncrement avoids a data race across simultaneous saves.
     * A process ID also distinguishes filenames created by other processes
     * in the same second; fopen("wbx") remains the exclusive-create guard. */
    static volatile LONG serial=0;
#endif
    char bytes[SUDOKU_SAVE_MAX_BYTES];
    char *temp;
    size_t n,len;
    FILE *file=NULL;
#if defined(_WIN32)
    unsigned attempt;
#else
    int parent_fd = -1;
#endif
    int ok;
    if(!valid_game(game)||!path||!*path)return SUDOKU_GAME_INVALID;
    if(!render_save(game,bytes,&n))return SUDOKU_GAME_INVALID;
    len=strlen(path);
    if(len>4096u)return SUDOKU_GAME_IO;
#if !defined(_WIN32)
    /* Do not stage a save destined to replace a special filesystem entry. */
    if(!save_target_is_regular_or_absent(path))return SUDOKU_GAME_IO;
#endif
    temp=malloc(len+64u);
    if(!temp)return SUDOKU_GAME_IO;
#if defined(_WIN32)
    for(attempt=0;attempt<64u;++attempt){
        unsigned long id=(unsigned long)(DWORD)InterlockedIncrement(&serial);
        (void)snprintf(temp,len+64u,"%s.tmp.%08lX.%08lX.%08lX",path,
                       (unsigned long)time(NULL),
                       (unsigned long)GetCurrentProcessId(),id);
        file=fopen(temp,"wbx");
        if(file)break;
        if(errno!=EEXIST){free(temp);return SUDOKU_GAME_IO;}
    }
    if(!file){free(temp);return SUDOKU_GAME_IO;}
#else
    /* mkstemp creates an unpredictable, exclusive, owner-only file next to
     * the destination. Unlike a process-global serial, this is safe across
     * concurrent callers and unrelated processes, without a retry race. */
    {
        int fd;
        (void)snprintf(temp,len+64u,"%s.tmp.XXXXXX",path);
        fd=mkstemp(temp);
        if(fd<0){free(temp);return SUDOKU_GAME_IO;}
        file=fdopen(fd,"wb");
        if(!file){
            (void)close(fd);
            (void)remove(temp);
            free(temp);
            return SUDOKU_GAME_IO;
        }
    }
#endif
    ok=1;
#if !defined(_WIN32)
    /* mkstemp creates mode 0600 even under umask(000). Reassert the
     * owner-only mode before writing; any failure preserves the old save. */
    ok=fchmod(fileno(file), S_IRUSR | S_IWUSR)==0;
#endif
    if(ok)ok=fwrite(bytes,1u,n,file)==n;
    if(ok)ok=fflush(file)==0;
#if defined(_WIN32)
    if(ok)ok=_commit(_fileno(file))==0;
#else
    if(ok)ok=fsync(fileno(file))==0;
#endif
    if(fclose(file)!=0)ok=0;
#if !defined(_WIN32)
    /* Pin the parent identity before publishing the staged save. If the
     * pathname resolves elsewhere afterward, never sync an unrelated dir. */
    if(ok){
        parent_fd=open_parent_directory(path);
        if(parent_fd<0)ok=0;
    }
    /* Catch special files installed while the staged save was being synced.
     * This narrows, but cannot eliminate, concurrent pathname races. */
    if(ok&&!save_target_is_regular_or_absent(path))ok=0;
#endif
    if(ok){
#if defined(_WIN32)
        ok=MoveFileExA(temp,path,MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)!=0;
#else
        ok=rename(temp,path)==0;
#endif
    }
#if !defined(_WIN32)
    if(!ok && parent_fd>=0)(void)close(parent_fd);
#endif
    if(!ok)(void)remove(temp);
    free(temp);
    if(!ok)return SUDOKU_GAME_IO;
#if !defined(_WIN32)
    /* A parent pathname that resolves to a different inode AFTER the
     * replacement cannot establish directory-metadata durability. */
    if(!sync_parent_directory(path,parent_fd))
        return SUDOKU_GAME_DURABILITY_UNCERTAIN;
#endif
    return SUDOKU_GAME_OK;
}
SudokuGameStatus sudoku_game_load(SudokuGame *game, const char *path) {
    char bytes[SUDOKU_SAVE_MAX_BYTES+1u];
    size_t n;
    FILE *file;
    SudokuGame *candidate;
    if(!game||!path||!*path)return SUDOKU_GAME_INVALID;
#if defined(_WIN32)
    file=fopen(path,"rb");
    if(!file)return SUDOKU_GAME_IO;
#else
    /* fopen(path, "rb") can block indefinitely before returning when path
     * refers to a FIFO with no writer. Open nonblocking and reject nonregular
     * file descriptors *before* any read; ordinary save files are unaffected.
     * A symlink to an ordinary regular save is still supported. */
    {
        int fd=open(path,O_RDONLY|O_NONBLOCK);
        struct stat metadata;
        if(fd<0)return SUDOKU_GAME_IO;
        if(fstat(fd,&metadata)!=0 || !S_ISREG(metadata.st_mode)){
            (void)close(fd);
            return SUDOKU_GAME_IO;
        }
        file=fdopen(fd,"rb");
        if(!file){
            (void)close(fd);
            return SUDOKU_GAME_IO;
        }
    }
#endif
    n=fread(bytes,1u,sizeof bytes,file);
    if(ferror(file)){fclose(file);return SUDOKU_GAME_IO;}
    if(fclose(file)!=0)return SUDOKU_GAME_IO;
    if(n>=sizeof bytes)return SUDOKU_GAME_CORRUPT;
    candidate=malloc(sizeof *candidate);
    if(!candidate)return SUDOKU_GAME_IO;
    if(!parse_save(candidate,bytes,n)){free(candidate);return SUDOKU_GAME_CORRUPT;}
    *game=*candidate;
    free(candidate);
    return SUDOKU_GAME_OK;
}
