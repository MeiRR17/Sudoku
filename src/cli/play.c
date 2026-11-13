#if !defined(_WIN32)
#define _POSIX_C_SOURCE 200809L
#endif
#include "sudoku/play.h"
#include "sudoku/board.h"
#include "sudoku/game.h"
#include "sudoku/generator.h"
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#if !defined(_WIN32)
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#endif

typedef struct PlayOptions {
    const char *puzzle;
    const char *file;
    const char *resume;
    const char *save;
    SudokuGenerateOptions generated;
    int has_seed;
    int has_difficulty;
    int has_symmetry;
} PlayOptions;
static int decimal(const char *s,uint64_t maximum,uint64_t *out){
    uint64_t n=0;
    if(!s||!*s)return 0;
    for(;*s;++s){
        unsigned d;
        if(*s<'0'||*s>'9')return 0;
        d=(unsigned)(*s-'0');
        if(n>(maximum-d)/10u)return 0;
        n=n*10u+d;
    }
    *out=n;
    return 1;
}
static int use(const char *message){
    fprintf(stderr,"Play usage error: %s\n",message);
    fputs("Usage: sudoku play (--puzzle DIGITS | --file FILE | --resume SAVE | --seed UINT32 --difficulty easy|medium|hard) [--symmetry none|rotational] [--save PATH]\n",stderr);
    return 2;
}
/* Non-mutating history timeline. Snapshot differences are derived from
 * actual board and pencil marks, not guesses about the command that
 * produced them. Steps above the current cursor are redoable snapshots. */
static unsigned history_bit_count(uint16_t mask){
    unsigned n=0u;
    while(mask){mask=(uint16_t)(mask&(uint16_t)(mask-1u));++n;}
    return n;
}
static void history_mask(uint16_t mask){
    unsigned d,shown=0u;
    for(d=1u;d<=9u;++d)
        if(mask&(uint16_t)(1u<<d))
            printf("%s%u",shown++?",":"",d);
    if(!shown)putchar('-');
}
static int history_valid(const SudokuGame *game){
    if(!game||game->history_len==0u||
       game->history_len>SUDOKU_GAME_HISTORY||
       game->history_cursor>=game->history_len){
        puts("History unavailable: invalid timeline metadata.");
        return 0;
    }
    return 1;
}
static void history_list(const SudokuGame *game,unsigned limit){
    unsigned count,first,step;
    if(!history_valid(game))return;
    count=game->history_len-1u;
    printf("History: %u recorded actions; cursor %u; undo %u; redo %u.\n",
           count,game->history_cursor,game->history_cursor,
           count-game->history_cursor);
    if(!count){
        puts("No history entries yet.");
        return;
    }
    first=count>limit?count-limit+1u:1u;
    for(step=first;step<=count;++step){
        const SudokuGameSnapshot *before=&game->history[step-1u];
        const SudokuGameSnapshot *after=&game->history[step];
        unsigned i,placed=0u,erased=0u,replaced=0u;
        unsigned notes_added=0u,notes_removed=0u;
        unsigned changed_cells=0u,single=0u;
        for(i=0u;i<SUDOKU_CELL_COUNT;++i){
            unsigned prior=before->board.cells[i],next=after->board.cells[i];
            uint16_t old_notes=before->notes[i],new_notes=after->notes[i];
            if(prior!=next){
                if(!prior)++placed;
                else if(!next)++erased;
                else ++replaced;
            }
            notes_added+=history_bit_count((uint16_t)(new_notes&(uint16_t)~old_notes));
            notes_removed+=history_bit_count((uint16_t)(old_notes&(uint16_t)~new_notes));
            if(prior!=next||old_notes!=new_notes){
                ++changed_cells;
                single=i;
            }
        }
        printf("History step %u [%s]: %u placed, %u erased, %u replaced; "
               "%u note marks added, %u removed",
               step,step<=game->history_cursor?"DONE":"REDO",
               placed,erased,replaced,notes_added,notes_removed);
        if(changed_cells==1u)
            printf("; r%uc%u",single/9u+1u,single%9u+1u);
        else
            printf("; %u changed cells",changed_cells);
        putchar('\n');
    }
    if(first>1u)
        printf("%u earlier actions hidden (raise history limit).\n",first-1u);
}
static void history_inspect(const SudokuGame *game,unsigned step){
    const SudokuGameSnapshot *before,*after;
    unsigned index,changed=0u;
    if(!history_valid(game))return;
    if(step>=game->history_len){
        printf("History step %u is not recorded.\n",step);
        return;
    }
    before=&game->history[step-1u];
    after=&game->history[step];
    printf("History inspect step %u [%s]:\n",step,
           step<=game->history_cursor?"DONE":"REDO");
    for(index=0u;index<SUDOKU_CELL_COUNT;++index){
        unsigned r=index/9u+1u,c=index%9u+1u;
        unsigned old_digit=before->board.cells[index];
        unsigned new_digit=after->board.cells[index];
        if(old_digit!=new_digit){
            printf("  Board r%uc%u: ",r,c);
            if(old_digit)printf("%u",old_digit);else putchar('-');
            fputs(" -> ",stdout);
            if(new_digit)printf("%u",new_digit);else putchar('-');
            putchar('\n');
            ++changed;
        }
        if(before->notes[index]!=after->notes[index]){
            printf("  Notes r%uc%u: ",r,c);
            history_mask(before->notes[index]);
            fputs(" -> ",stdout);
            history_mask(after->notes[index]);
            putchar('\n');
            ++changed;
        }
    }
    if(!changed)puts("  No observable board or pencil-note changes.");
}
/* Compare any two retained snapshots, including the original state and
 * redoable future. The direction is intentional: FROM -> TO. No game state,
 * solution cache, history cursor, elapsed time or saved file is modified. */
static void history_diff(const SudokuGame *game,unsigned from,unsigned to){
    const SudokuGameSnapshot *before,*after;
    unsigned index,changed=0u,placed=0u,erased=0u,replaced=0u;
    unsigned notes_added=0u,notes_removed=0u;
    if(!history_valid(game))return;
    if(from>=game->history_len||to>=game->history_len){
        printf("History diff unavailable: recorded steps are 0..%u.\n",
               game->history_len-1u);
        return;
    }
    before=&game->history[from];
    after=&game->history[to];
    printf("History diff %u -> %u:\n",from,to);
    for(index=0u;index<SUDOKU_CELL_COUNT;++index){
        unsigned old_digit=before->board.cells[index];
        unsigned new_digit=after->board.cells[index];
        uint16_t old_notes=before->notes[index];
        uint16_t new_notes=after->notes[index];
        if(old_digit==new_digit&&old_notes==new_notes)continue;
        ++changed;
        if(old_digit!=new_digit){
            if(!old_digit)++placed;
            else if(!new_digit)++erased;
            else ++replaced;
            printf("  Board r%uc%u: ",index/9u+1u,index%9u+1u);
            if(old_digit)printf("%u",old_digit);else putchar('-');
            fputs(" -> ",stdout);
            if(new_digit)printf("%u",new_digit);else putchar('-');
            putchar('\n');
        }
        if(old_notes!=new_notes){
            notes_added+=history_bit_count((uint16_t)(new_notes&(uint16_t)~old_notes));
            notes_removed+=history_bit_count((uint16_t)(old_notes&(uint16_t)~new_notes));
            printf("  Notes r%uc%u: ",index/9u+1u,index%9u+1u);
            history_mask(old_notes);
            fputs(" -> ",stdout);
            history_mask(new_notes);
            putchar('\n');
        }
    }
    printf("History diff summary: %u cells changed; %u placed, %u erased, "
           "%u replaced; %u marks added, %u removed.\n",
           changed,placed,erased,replaced,notes_added,notes_removed);
    if(!changed)puts("  No observable differences between the snapshots.");
}
/* Read-only statistics for the retained snapshot timeline. Applied and
 * redoable edits are counted separately; these totals do not represent
 * actions that have already fallen off the bounded history buffer. */
typedef struct HistoryTotals {
    unsigned placed,erased,replaced,notes_added,notes_removed,cells_changed;
} HistoryTotals;
static void history_print_totals(const char *name,const HistoryTotals *totals){
    printf("%s changes: %u placed, %u erased, %u replaced; "
           "%u note marks added, %u removed; %u cells touched.\n",
           name,totals->placed,totals->erased,totals->replaced,
           totals->notes_added,totals->notes_removed,totals->cells_changed);
}
static void history_summary(const SudokuGame *game){
    HistoryTotals applied={0},redoable={0};
    unsigned step,index;
    if(!history_valid(game))return;
    for(step=1u;step<game->history_len;++step){
        const SudokuGameSnapshot *before=&game->history[step-1u];
        const SudokuGameSnapshot *after=&game->history[step];
        HistoryTotals *totals=step<=game->history_cursor?&applied:&redoable;
        for(index=0u;index<SUDOKU_CELL_COUNT;++index){
            unsigned previous=before->board.cells[index];
            unsigned next=after->board.cells[index];
            uint16_t old_notes=before->notes[index];
            uint16_t new_notes=after->notes[index];
            if(previous!=next){
                if(!previous)++totals->placed;
                else if(!next)++totals->erased;
                else ++totals->replaced;
            }
            totals->notes_added+=history_bit_count(
                (uint16_t)(new_notes&(uint16_t)~old_notes));
            totals->notes_removed+=history_bit_count(
                (uint16_t)(old_notes&(uint16_t)~new_notes));
            if(previous!=next||old_notes!=new_notes)
                ++totals->cells_changed;
        }
    }
    printf("History summary: %u applied, %u redoable actions (retained).\n",
           game->history_cursor,game->history_len-1u-game->history_cursor);
    history_print_totals("Applied",&applied);
    history_print_totals("Redoable",&redoable);
}
/* Identify frequently edited cells across retained Undo/Redo snapshots.
 * A step changing both a digit and notes counts as one edited step, but
 * contributes to both detail columns. Redoable steps are included. */
typedef struct HistoryCellActivity {
    unsigned steps,board_edits,note_edits,done,redo;
} HistoryCellActivity;
static void history_hotspots(const SudokuGame *game,unsigned limit){
    HistoryCellActivity activity[SUDOKU_CELL_COUNT]={0};
    unsigned char listed[SUDOKU_CELL_COUNT]={0};
    unsigned step,i,rank,total=0u;
    if(!history_valid(game))return;
    for(step=1u;step<game->history_len;++step){
        const SudokuGameSnapshot *before=&game->history[step-1u];
        const SudokuGameSnapshot *after=&game->history[step];
        for(i=0u;i<SUDOKU_CELL_COUNT;++i){
            unsigned board_changed=before->board.cells[i]!=after->board.cells[i];
            unsigned notes_changed=before->notes[i]!=after->notes[i];
            if(!board_changed&&!notes_changed)continue;
            ++activity[i].steps;
            activity[i].board_edits+=board_changed;
            activity[i].note_edits+=notes_changed;
            if(step<=game->history_cursor)++activity[i].done;
            else ++activity[i].redo;
        }
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        if(activity[i].steps)++total;
    printf("History hotspots: %u edited cells across %u retained actions.\n",
           total,game->history_len-1u);
    if(!total){puts("No edited cells in retained history.");return;}
    for(rank=0u;rank<limit&&rank<total;++rank){
        unsigned best=SUDOKU_CELL_COUNT;
        for(i=0u;i<SUDOKU_CELL_COUNT;++i){
            if(listed[i]||!activity[i].steps)continue;
            if(best==SUDOKU_CELL_COUNT||activity[i].steps>activity[best].steps)
                best=i;
        }
        listed[best]=1u;
        printf("  r%uc%u: %u edited steps (%u board, %u notes; %u DONE, %u REDO).\n",
               best/9u+1u,best%9u+1u,activity[best].steps,
               activity[best].board_edits,activity[best].note_edits,
               activity[best].done,activity[best].redo);
    }
    if(total>rank)
        printf("%u more edited cells hidden (raise hotspots limit).\n",total-rank);
}
/* Read-only map of per-cell edit frequency in retained timeline snapshots.
 * An edit of both a digit and its notes in one action counts only once. */
static void history_heatmap(const SudokuGame *game,const char *scope){
    unsigned counts[SUDOKU_CELL_COUNT]={0};
    unsigned step,index,row,col,touched=0u,total=0u;
    int only_done=strcmp(scope,"done")==0;
    int only_redo=strcmp(scope,"redo")==0;
    if(!history_valid(game))return;
    for(step=1u;step<game->history_len;++step){
        const SudokuGameSnapshot *before=&game->history[step-1u];
        const SudokuGameSnapshot *after=&game->history[step];
        if((only_done&&step>game->history_cursor)||
           (only_redo&&step<=game->history_cursor))continue;
        for(index=0u;index<SUDOKU_CELL_COUNT;++index){
            if(before->board.cells[index]!=after->board.cells[index]||
               before->notes[index]!=after->notes[index])
                ++counts[index];
        }
    }
    printf("History heatmap (%s): %u retained actions, %u DONE, %u REDO.\n",
           scope,game->history_len-1u,game->history_cursor,
           game->history_len-1u-game->history_cursor);
    puts("         c1  c2  c3 |  c4  c5  c6 |  c7  c8  c9");
    for(row=0u;row<9u;++row){
        printf("r%u     ",row+1u);
        for(col=0u;col<9u;++col){
            unsigned n=counts[row*9u+col];
            printf("%3u",n);
            if(col==2u||col==5u)fputs(" | ",stdout);
            else if(col!=8u)putchar(' ');
            if(n){++touched;total+=n;}
        }
        putchar('\n');
    }
    printf("History heatmap totals (%s): %u edited cells, %u cell-edits.\n",
           scope,touched,total);
    puts("Each count is one retained action that changed a cell; evicted history is excluded.");
}
/* Per-cell change timeline across all retained snapshots. It includes
 * REDO steps after the live cursor and never fabricates command names. */
static void history_cell(const SudokuGame *game,unsigned row,unsigned col){
    unsigned step,changed=0u,index=(row-1u)*9u+col-1u;
    if(!history_valid(game))return;
    printf("History cell r%uc%u:\n",row,col);
    for(step=1u;step<game->history_len;++step){
        const SudokuGameSnapshot *before=&game->history[step-1u];
        const SudokuGameSnapshot *after=&game->history[step];
        unsigned prior=before->board.cells[index],next=after->board.cells[index];
        uint16_t old_notes=before->notes[index],new_notes=after->notes[index];
        if(prior==next&&old_notes==new_notes)continue;
        ++changed;
        printf("  Step %u [%s]:",step,
               step<=game->history_cursor?"DONE":"REDO");
        if(prior!=next){
            fputs(" board ",stdout);
            if(prior)printf("%u",prior);else putchar('-');
            fputs(" -> ",stdout);
            if(next)printf("%u",next);else putchar('-');
        }
        if(old_notes!=new_notes){
            fputs(" notes ",stdout);
            history_mask(old_notes);
            fputs(" -> ",stdout);
            history_mask(new_notes);
        }
        putchar('\n');
    }
    printf("History cell summary: %u changed steps.\n",changed);
    if(!changed)puts("  This cell has no recorded changes.");
}
static void commands(void){
    puts("Commands: show [notes|candidates|heatmap|digit N],");
    puts("          set ROW COL DIGIT | set safe|proven ROW COL DIGIT,");
    puts("          set batch r1c3=4,r1c4=6 (comma-separated, atomic),");
    puts("          set batch check|safe r1c3=4,r1c4=6,");
    puts("          erase ROW COL | erase batch r1c3,r1c4,");
    puts("          erase row|column|box N (unit 1..9, one Undo),");
    puts("          note ROW COL DIGIT,");
    puts("          notes ROW COL, notes set|add|remove ROW COL DIGITS,");
    puts("          notes batch r1c3=19,r1c4=- (atomic pencil edits),");
    puts("          notes batch add|remove|toggle r1c3=12,r1c4=9,");
    puts("          notes batch preview [add|remove|toggle] r1c3=12,r1c4=9,");
    puts("          notes audit [N] | notes audit row|column|box N,");
    puts("          notes clear ROW COL, notes fill|prune ROW COL,");
    puts("          notes fill|prune row|column|box N (unit 1..9),");
    puts("          candidates ROW COL, probe ROW COL DIGIT,");
    puts("          probe compare ROW COL, focus [N],");
    puts("          analyze [N], auto-notes,");
    puts("          prune-notes,");
    puts("          clear-notes, hint [all|pairs [N]|hidden-pairs [N]|locked [N]|x-wing [N]|swordfish [N]|trial [N]|trial-forced [N]|triples [N]|hidden-triples [N]|chain [N]],");
    puts("          hint apply [all|pairs [N]|hidden-pairs [N]|locked [N]|x-wing [N]|swordfish [N]|trial [N]|trial-forced [N]|triples [N]|hidden-triples [N]|chain [N]],");
    puts("          undo [N], redo [N], history [N], history summary,");
    puts("          history hotspots [N], history heatmap [all|done|redo],");
    puts("          history inspect STEP,");
    puts("          history goto STEP (0 = initial),");
    puts("          history diff FROM TO | history cell ROW COL,");
    puts("          reset, check [details|clear],");
    puts("          export [givens|current|both], status, save [PATH], help, quit");
    puts("'export' prints copyable 81-digit original clues; 'export current'");
    puts("prints entered digits too; neither is a full save or stored solution.");
    puts("Coordinates and digits are 1..9; original clues are immutable.");
    puts("'show notes' renders pencil marks in a 9x9 mini-grid; '.' is absent.");
    puts("'show candidates' shows live Sudoku candidates, not the solved grid.");
    puts("'show heatmap' shows candidate counts in empty cells (! = none).");
    puts("'show digit N' marks existing N as # and legal vacancies as *, 1..9.");
    puts("'note' toggles a mark; 'notes set ROW COL 135' replaces the full set.");
    puts("'notes set ROW COL -' or 'notes clear ROW COL' clears only that cell.");
    puts("'notes add ROW COL 135' adds marks; 'notes remove ROW COL 135' erases.");
    puts("'notes batch r1c3=19,r1c4=-' sets several note masks in one Undo.");
    puts("A rejected or unchanged notes batch preserves Redo.");
    puts("'notes batch add|remove|toggle' keeps unmentioned pencil marks.");
    puts("Toggle flips each specified mark, also in one Undo step.");
    puts("'notes batch preview' reports exact mask changes without editing.");
    puts("Previews validate the entire list and preserve Undo/Redo.");
    puts("Adding existing or removing absent marks leaves history unchanged.");
    puts("'notes audit [N]' lists stale and unmarked legal digits (default 10).");
    puts("'notes audit row|column|box N' limits the report to one unit.");
    puts("Unmarked legal digits are optional pencil notes, not mistakes.");
    puts("'notes fill ROW COL' sets all locally legal marks for one cell.");
    puts("'notes prune ROW COL' removes illegal marks from that cell only.");
    puts("'notes fill row 1' updates all blank cells in that row in one undo.");
    puts("Use 'column' or 'box' instead of 'row', and 'prune' to remove only.");
    puts("Invalid/duplicate digits are rejected; one replacement = one Undo.");
    puts("'erase batch' clears multiple editable cells and notes in one Undo.");
    puts("Any given/duplicate target rejects the entire erase batch.");
    puts("'erase row|column|box N' clears editable digits and notes only.");
    puts("Boxes are numbered left-to-right, top-to-bottom (1..9).");
    puts("'candidates' lists legal digits without guessing.");
    puts("'focus [N]' ranks empty cells by fewest legal candidates (default 5).");
    puts("'set batch r1c3=4,r1c4=6' places all digits in a single Undo step.");
    puts("'set batch check LIST' previews a whole batch without applying it.");
    puts("'set batch safe LIST' commits only if no immediate contradiction");
    puts("would result; this still does NOT prove digits are correct.");
    puts("All selected cells must be blank/editable and mutually legal.");
    puts("Invalid or duplicate placements reject the entire batch.");
    puts("'set proven ROW COL DIGIT' commits only if every other locally legal");
    puts("digit causes an immediate contradiction; existing mistakes block it.");
    puts("'set safe ROW COL DIGIT' places only after checking immediate");
    puts("candidate contradictions; no such contradiction is NOT proof of correctness.");
    puts("'probe ROW COL DIGIT' previews one locally legal move without applying.");
    puts("'probe compare ROW COL' tests all local digits and reports which");
    puts("produce a provable immediate contradiction; survivors are unproven.");
    puts("It lists newly impossible cells/digits, but does not prove correctness.");
    puts("'analyze [N]' reports candidate counts and contradictions (default 10).");
    puts("It detects zero-candidate cells and digits missing from every possible");
    puts("position in a row/column/box, using no cached solved digits.");
    puts("'history [N]' lists recent state changes and redoable steps (default 10).");
    puts("'history summary' totals applied and redoable snapshot changes.");
    puts("'history hotspots [N]' ranks most frequently edited cells (default 10).");
    puts("'history heatmap [all|done|redo]' shows 9x9 edit counts.");
    puts("History views include redoable edits and never reveal the solution.");
    puts("'history inspect STEP' shows exact digit/note changes at that step.");
    puts("'history diff FROM TO' compares any retained snapshots (0..127).");
    puts("'history cell ROW COL' shows that cell's complete change timeline.");
    puts("Both reports include redoable steps without editing the game.");
    puts("'history goto STEP' restores a retained snapshot; 0 is the initial");
    puts("board. No new Undo entry or loss of Redo. Invalid targets are rejected.");
    puts("History views are read-only and use retained Undo/Redo snapshots.");
    puts("'auto-notes' fills all legal marks; 'prune-notes' removes only illegal marks.");
    puts("'hint' shows one forced single; 'hint all' lists each distinct forced cell.");
    puts("'hint pairs [N]' previews actionable naked pairs (default 5).");
    puts("'hint apply pairs [N]' removes matching pencil marks in one undo.");
    puts("'hint triples [N]' previews actionable naked triples (default 5).");
    puts("'hint apply triples [N]' removes their pencil marks in one undo.");
    puts("'hint hidden-triples [N]' previews three-digit hidden subsets.");
    puts("'hint apply hidden-triples [N]' prunes extra marks in one undo.");
    puts("'hint hidden-pairs [N]' previews pairs hidden among more candidates.");
    puts("'hint apply hidden-pairs [N]' prunes those extra notes in one undo.");
    puts("'hint locked [N]' previews pointing/claiming candidate eliminations.");
    puts("'hint apply locked [N]' prunes those pencil notes in one undo.");
    puts("'hint x-wing [N]' finds row/column rectangle candidate eliminations.");
    puts("'hint apply x-wing [N]' erases matching notes in one undo step.");
    puts("'hint swordfish [N]' previews three-line candidate eliminations.");
    puts("'hint trial-forced [N]' finds forced placements when every");
    puts("other candidate at a cell causes an immediate contradiction.");
    puts("'hint apply trial-forced [N]' places these in one Undo step.");
    puts("'hint trial [N]' excludes locally legal digits causing an immediate");
    puts("candidate contradiction when hypothetically placed (default 5).");
    puts("'hint apply trial [N]' prunes matching handwritten notes in one undo.");
    puts("'hint apply swordfish [N]' removes matching notes in one undo.");
    puts("'hint chain [N]' previews up to N successive forced singles (1..81).");
    puts("'hint apply' places one; 'hint apply all' batches current forced cells.");
    puts("'hint apply chain [N]' commits at most N singles in one undo.");
    puts("'undo [N]' and 'redo [N]' move 1..127 history steps, all or nothing.");
    puts("'check details' locates wrong entries; 'check clear' erases them (undoable).");
    puts("No color, network or special keys required.");
}
/* Share a portable 81-digit puzzle string with a new --puzzle session.
 * This is a read-only view of public givens or the player's current entries,
 * never the cached solved board. Notes, timer, history and saves are omitted. */
static void export_board(const SudokuGame *game,int current){
    const SudokuBoard *board=current?&game->state.board:&game->givens;
    char compact[82];
    /* A public library caller may have corrupted a game structure; do not
     * publish '?'-containing malformed compact data as a usable puzzle. */
    if(sudoku_board_validate(board,NULL)!=SUDOKU_OK){
        puts("Error: cannot export an invalid board.");
        return;
    }
    sudoku_board_compact(board,compact);
    printf("%s: %s\n",current?"Current board":"Puzzle givens",compact);
}
static void display(const SudokuGame *game) {
    unsigned r,c;
    puts("      1 2 3   4 5 6   7 8 9");
    puts("    +-------+-------+-------+");
    for(r=0;r<9u;++r){
        printf("  %u |",r+1u);
        for(c=0;c<9u;++c){
            unsigned i=r*9u+c;
            unsigned d=game->state.board.cells[i];
            printf(" %c",d?(char)('0'+d):'.');
            if(c%3u==2u)fputs(" |",stdout);
        }
        putchar('\n');
        if(r%3u==2u)puts("    +-------+-------+-------+");
    }
    printf("Empty: %u | Mistakes: %u | Time: %" PRIu64 "s\n",
           sudoku_game_empty(game), sudoku_game_mistakes(game), sudoku_game_elapsed(game));
    if(sudoku_game_won(game))puts("SOLVED! Congratulations: all 81 cells match the unique solution.");
}
/* Display a full 9x9 pencil grid without changing the board, notes, or
 * history. A mini-cell holds digits 1-9 in their conventional 3x3 spots;
 * dots are absent marks and [d] is an already-filled Sudoku square.
 * 'show notes' uses handwritten marks, even when they are not locally
 * legal; 'show candidates' computes legal digits from the live board only.
 * No solved-grid lookup, save, timer reset or history edit is performed. */
static void display_note_grid(const SudokuGame *game,int legal){
    unsigned row,col,band,slot;
    if(legal &&
       sudoku_board_validate(&game->state.board,NULL)!=SUDOKU_OK){
        puts("Cannot show candidates: invalid current board.");
        return;
    }
    puts(legal ? "Live candidates grid ('.' = absent; [d] = filled):" :
                 "Handwritten notes grid ('.' = absent; [d] = filled):");
    puts("     1   2   3   4   5   6   7   8   9");
    puts("   +-----------+-----------+-----------+");
    for(row=0u;row<9u;++row){
        uint16_t marks[9]={0};
        for(col=0u;col<9u;++col){
            unsigned index=row*9u+col;
            if(!game->state.board.cells[index]){
                marks[col]=legal ?
                    sudoku_game_candidates(game,row+1u,col+1u) :
                    game->state.notes[index];
            }
        }
        for(band=0u;band<3u;++band){
            printf(" %c ",band==1u?(int)('1'+row):' ');
            for(col=0u;col<9u;++col){
                unsigned index=row*9u+col;
                if(col%3u==0u)putchar('|');
                if(game->state.board.cells[index]){
                    if(band==1u)
                        printf("[%u]",(unsigned)game->state.board.cells[index]);
                    else fputs("   ",stdout);
                }else{
                    for(slot=0u;slot<3u;++slot){
                        unsigned digit=band*3u+slot+1u;
                        putchar((marks[col]&(uint16_t)(1u<<digit)) ?
                                (int)('0'+digit) : '.');
                    }
                }
                if(col%3u!=2u)putchar(' ');
            }
            puts("|");
        }
        if(row%3u==2u)puts("   +-----------+-----------+-----------+");
    }
}
/* POSIX --file is a regular on-disk puzzle, not an interactive pipe.
 * O_NONBLOCK prevents a writer-less FIFO from trapping the CLI at open;
 * fstat validates the already-open descriptor rather than a racy pathname.
 * Keep symlinks to regular files supported. Windows retains fopen. */
static FILE *open_regular_puzzle(const char *path) {
#if defined(_WIN32)
    return fopen(path, "rb");
#else
    int fd = open(path, O_RDONLY | O_NONBLOCK);
    struct stat metadata;
    FILE *input;
    int saved_errno;
    if (fd < 0) return NULL;
    if (fstat(fd, &metadata) != 0) {
        saved_errno = errno;
        (void)close(fd);
        errno = saved_errno;
        return NULL;
    }
    if (!S_ISREG(metadata.st_mode)) {
        (void)close(fd);
        errno = EINVAL;
        return NULL;
    }
    input = fdopen(fd, "rb");
    if (input == NULL) {
        saved_errno = errno;
        (void)close(fd);
        errno = saved_errno;
    }
    return input;
#endif
}

static int puzzle_file(const char *path,SudokuBoard *board){
    /* Never reserve >1 MiB on the call stack (notably Windows' default stack).
     * One extra byte still distinguishes an oversized file from the limit. */
    const size_t capacity = (size_t)SUDOKU_MAX_INPUT_BYTES + 1u;
    unsigned char *bytes;
    SudokuError error;
    size_t n;
    SudokuStatus valid;
    FILE *f=open_regular_puzzle(path);
    if(!f){fprintf(stderr,"Puzzle open failed: %s\n",strerror(errno));return 4;}
    bytes=malloc(capacity);
    if(!bytes){
        (void)fclose(f);
        fputs("Puzzle buffer allocation failed\n",stderr);
        return 4;
    }
    n=fread(bytes,1u,capacity,f);
    if(ferror(f)){
        free(bytes);
        (void)fclose(f);
        fputs("Puzzle read failed\n",stderr);
        return 4;
    }
    if(fclose(f)!=0){
        free(bytes);
        fputs("Puzzle close failed\n",stderr);
        return 4;
    }
    valid=sudoku_board_parse(board,bytes,n,&error);
    free(bytes);
    if(valid!=SUDOKU_OK){fprintf(stderr,"Invalid puzzle: %s\n",sudoku_status_text(valid));return 3;}
    return 0;
}
static int parse(int argc,char **argv,PlayOptions *opt){
    int i,source=0;
    uint64_t n;
    opt->generated.max_attempts=20;
    opt->generated.max_checks=2000;
    opt->generated.max_nodes=UINT64_C(50000);
    opt->generated.max_cpu_ms=5000;
    if(argc<4)return use("missing input source");
    for(i=2;i<argc;++i){
        const char *arg=argv[i],*value;
        if(i+1>=argc)return use("missing option value");
        value=argv[++i];
        if(!*value)return use("empty option value");
        if(strcmp(arg,"--puzzle")==0){opt->puzzle=value;++source;}
        else if(strcmp(arg,"--file")==0){opt->file=value;++source;}
        else if(strcmp(arg,"--resume")==0){opt->resume=value;++source;}
        else if(strcmp(arg,"--save")==0){if(opt->save)return use("repeated --save");opt->save=value;}
        else if(strcmp(arg,"--seed")==0){
            if(opt->has_seed||!decimal(value,UINT32_MAX,&n))return use("invalid seed");
            opt->has_seed=1;opt->generated.seed=(uint32_t)n;
        }else if(strcmp(arg,"--difficulty")==0){
            if(opt->has_difficulty)return use("repeated difficulty");
            opt->has_difficulty=1;
            if(strcmp(value,"easy")==0)opt->generated.difficulty=SUDOKU_DIFFICULTY_EASY;
            else if(strcmp(value,"medium")==0)opt->generated.difficulty=SUDOKU_DIFFICULTY_MEDIUM;
            else if(strcmp(value,"hard")==0)opt->generated.difficulty=SUDOKU_DIFFICULTY_HARD;
            else return use("invalid difficulty");
        }else if(strcmp(arg,"--symmetry")==0){
            if(opt->has_symmetry)return use("repeated symmetry");
            opt->has_symmetry=1;
            if(strcmp(value,"none")==0)opt->generated.rotational=0u;
            else if(strcmp(value,"rotational")==0)opt->generated.rotational=1u;
            else return use("invalid symmetry");
        }else return use("unknown option");
    }
    if(opt->has_seed||opt->has_difficulty){
        if(!opt->has_seed||!opt->has_difficulty)return use("generated games require --seed and --difficulty");
        ++source;
    }else if(opt->has_symmetry)return use("symmetry only valid for generated games");
    if(source!=1)return use("specify exactly one game source");
    return 0;
}
static int start(PlayOptions *opt,SudokuGame *game){
    SudokuBoard givens;
    SudokuGameStatus status;
    int code;
    if(opt->resume){
        status=sudoku_game_load(game,opt->resume);
        if(status!=SUDOKU_GAME_OK){
            fprintf(stderr,"Resume failed: %s\n",sudoku_game_status_text(status));
            return status==SUDOKU_GAME_IO?4:3;
        }
        if(!opt->save)opt->save=opt->resume;
        puts("Resumed saved game (undo/redo history starts fresh).");
        return 0;
    }
    if(opt->has_seed){
        SudokuGenerateResult generated;
        SudokuGenerateStatus g=sudoku_generate(&opt->generated,&generated);
        if(g!=SUDOKU_GENERATE_OK){
            fprintf(stderr,"Generation failed: %s\n",sudoku_generate_status_text(g));
            return g==SUDOKU_GENERATE_BUDGET?6:2;
        }
        givens=generated.puzzle;
        printf("Generated unique %s puzzle with seed %" PRIu32 " (%u clues).\n",
               sudoku_difficulty_text(generated.rated),opt->generated.seed,generated.clues);
    }else if(opt->puzzle){
        SudokuError error;
        SudokuStatus valid=sudoku_board_parse(&givens,(const unsigned char*)opt->puzzle,strlen(opt->puzzle),&error);
        if(valid!=SUDOKU_OK){fprintf(stderr,"Invalid puzzle: %s\n",sudoku_status_text(valid));return 3;}
    }else{
        code=puzzle_file(opt->file,&givens);
        if(code)return code;
    }
    status=sudoku_game_start(game,&givens);
    if(status!=SUDOKU_GAME_OK){
        fprintf(stderr,"Cannot start game: %s\n",sudoku_game_status_text(status));
        return 3;
    }
    puts("Started new game. Type 'help' for commands.");
    return 0;
}
static int position(const char *row,const char *col,unsigned *r,unsigned *c){
    uint64_t a,b;
    if(!row||!col||!decimal(row,9,&a)||!decimal(col,9,&b)||a<1u||b<1u)return 0;
    *r=(unsigned)a;*c=(unsigned)b;return 1;
}
/* Parse a compact user-selected set of distinct digits: "13579" or "-"
 * for no marks. Reject duplicates and all non-1..9 bytes rather than
 * partially applying an invalid request. Order is irrelevant. */
/* Parse one whitespace-free list of player-selected placements:
 * r1c3=4,r1c4=6. Every item is exactly six ASCII bytes; reject partial
 * items, signs, zeroes, trailing commas and oversized lists. The core
 * sudoku_game_set_many API remains responsible for detecting duplicate
 * cells, occupied/given targets and cross-move Sudoku conflicts atomically.
 * No game state is touched during parsing. */
static int parse_batch_moves(const char *spec,
                             SudokuGameMove moves[SUDOKU_CELL_COUNT],
                             unsigned *count){
    size_t len,i=0u;
    unsigned n=0u;
    if(!spec||!moves||!count)return 0;
    len=strlen(spec);
    if(len<6u||len>(size_t)SUDOKU_CELL_COUNT*7u-1u)return 0;
    while(i<len){
        if(n==SUDOKU_CELL_COUNT||len-i<6u)return 0;
        if(spec[i]!='r'||spec[i+1u]<'1'||spec[i+1u]>'9'||
           spec[i+2u]!='c'||spec[i+3u]<'1'||spec[i+3u]>'9'||
           spec[i+4u]!='='||spec[i+5u]<'1'||spec[i+5u]>'9')
            return 0;
        moves[n].row=(unsigned)(spec[i+1u]-'0');
        moves[n].col=(unsigned)(spec[i+3u]-'0');
        moves[n].digit=(unsigned)(spec[i+5u]-'0');
        ++n;
        i+=6u;
        if(i==len)break;
        if(spec[i]!=',')return 0;
        ++i;
        if(i==len)return 0;
    }
    *count=n;
    return n!=0u;
}
/* Collect only non-given cells of a selected row, column or 3x3 box.
 * Box numbering is row-major: 1 = top left, 9 = bottom right.
 * The transactional engine still validates every target and the live state. */
static unsigned erase_unit_targets(const SudokuGame *game,
                                   const char *scope,unsigned number,
                                   SudokuGameCell cells[9]){
    unsigned slot,count=0u;
    for(slot=0u;slot<9u;++slot){
        unsigned row,col,index;
        if(strcmp(scope,"row")==0){row=number;col=slot+1u;}
        else if(strcmp(scope,"column")==0){row=slot+1u;col=number;}
        else {
            row=((number-1u)/3u)*3u+slot/3u+1u;
            col=((number-1u)%3u)*3u+slot%3u+1u;
        }
        index=(row-1u)*9u+col-1u;
        if(game->givens.cells[index])continue;
        cells[count].row=row;
        cells[count].col=col;
        ++count;
    }
    return count;
}
/* A strict comma-separated list of 1..81 rNcM coordinates.
 * No whitespace, optional digits, partial tokens or trailing comma accepted.
 * Duplicate coordinates reach the transactional engine's duplicate guard. */
static int parse_erase_batch(const char *spec,
                             SudokuGameCell cells[SUDOKU_CELL_COUNT],
                             unsigned *count) {
    size_t len,i=0u;
    unsigned n=0u;
    if (!spec || !cells || !count) return 0;
    len=strlen(spec);
    if (len<4u || len>(size_t)SUDOKU_CELL_COUNT*5u-1u) return 0;
    while (i<len) {
        if (n==SUDOKU_CELL_COUNT || len-i<4u) return 0;
        if (spec[i]!='r' || spec[i+1u]<'1' || spec[i+1u]>'9' ||
            spec[i+2u]!='c' || spec[i+3u]<'1' || spec[i+3u]>'9')
            return 0;
        cells[n].row=(unsigned)(spec[i+1u]-'0');
        cells[n].col=(unsigned)(spec[i+3u]-'0');
        ++n;
        i+=4u;
        if (i==len) break;
        if (spec[i]!=',') return 0;
        ++i;
        if (i==len) return 0;
    }
    *count=n;
    return n!=0u;
}
static int parse_note_digits(const char *digits,uint16_t *out){
    uint16_t mask=0u;
    size_t len;
    if(!digits||!out)return 0;
    if(strcmp(digits,"-")==0){*out=0u;return 1;}
    len=strlen(digits);
    if(len<1u||len>9u)return 0;
    while(*digits){
        unsigned digit;
        uint16_t bit;
        if(*digits<'1'||*digits>'9')return 0;
        digit=(unsigned)(*digits++-'0');
        bit=(uint16_t)(1u<<digit);
        if(mask&bit)return 0;
        mask=(uint16_t)(mask|bit);
    }
    *out=mask;
    return 1;
}
/* Strict comma-delimited notes rNcM=DIGITS or rNcM=- transactions.
 * Parse the entire specification before invoking the atomic engine. */
static int parse_notes_batch(const char *spec,
                             SudokuGameNoteEdit edits[SUDOKU_CELL_COUNT],
                             unsigned *count){
    size_t len,i=0u;
    unsigned n=0u;
    if(!spec||!edits||!count)return 0;
    len=strlen(spec);
    if(len<6u||len>(size_t)SUDOKU_CELL_COUNT*15u-1u)return 0;
    while(i<len){
        char digits[10];
        size_t dlen=0u;
        if(n==SUDOKU_CELL_COUNT||len-i<6u)return 0;
        if(spec[i]!='r'||spec[i+1u]<'1'||spec[i+1u]>'9'||
           spec[i+2u]!='c'||spec[i+3u]<'1'||spec[i+3u]>'9'||
           spec[i+4u]!='=')return 0;
        edits[n].row=(unsigned)(spec[i+1u]-'0');
        edits[n].col=(unsigned)(spec[i+3u]-'0');
        i+=5u;
        while(i<len&&spec[i]!=','){
            if(dlen==9u)return 0;
            digits[dlen++]=spec[i++];
        }
        if(!dlen)return 0;
        digits[dlen]='\0';
        if(!parse_note_digits(digits,&edits[n].mask))return 0;
        ++n;
        if(i==len)break;
        ++i;
        if(i==len)return 0;
    }
    *count=n;
    return n!=0u;
}
/* Dispatch a parsed handwritten-note list through the same atomic engine
 * for both an actual edit and its read-only preview. */
static SudokuGameStatus apply_notes_batch(SudokuGame *game,
                                           const SudokuGameNoteEdit *edits,
                                           unsigned count,const char *mode,
                                           unsigned *changed){
    if(strcmp(mode,"add")==0)
        return sudoku_game_add_notes_many(game,edits,count,changed);
    if(strcmp(mode,"remove")==0)
        return sudoku_game_remove_notes_many(game,edits,count,changed);
    if(strcmp(mode,"toggle")==0)
        return sudoku_game_toggle_notes_many(game,edits,count,changed);
    return sudoku_game_set_notes_many(game,edits,count,changed);
}
static void print_notes(const SudokuGame *game,unsigned r,unsigned c){
    unsigned i=(r-1u)*9u+c-1u,d;
    printf("Notes for row %u col %u:",r,c);
    for(d=1u;d<=9u;++d)if(game->state.notes[i]&(1u<<d))printf(" %u",d);
    putchar('\n');
}
/* Calculate only locally legal digits from the *current* board; the
 * stored unique solution is deliberately never consulted. */
static uint16_t candidate_mask(const SudokuGame *game,unsigned i){
    return sudoku_game_candidates(game,i/9u+1u,i%9u+1u);
}
/* Return a digit only when the cell has exactly one legal candidate. */
static unsigned single_candidate(uint16_t mask){
    unsigned d,found=0u;
    for(d=1u;d<=9u;++d){
        if((mask&(uint16_t)(1u<<d))!=0u){
            if(found)return 0u;
            found=d;
        }
    }
    return found;
}
/* Both candidate lookup and hints are read-only, leaving the complete
 * game state (notes, history, timer base and board) unchanged. */
static void print_candidates(const SudokuGame *game,unsigned r,unsigned c){
    unsigned i=(r-1u)*9u+c-1u,d;
    uint16_t mask;
    if(game->state.board.cells[i]){
        printf("Cell row %u col %u already contains %u.\n",r,c,
               (unsigned)game->state.board.cells[i]);
        return;
    }
    mask=candidate_mask(game,i);
    printf("Candidates for row %u col %u:",r,c);
    for(d=1u;d<=9u;++d)
        if((mask&(uint16_t)(1u<<d))!=0u)printf(" %u",d);
    putchar('\n');
}
/* Audit handwritten marks against live legal candidates; this neither
 * reads the solution nor mutates the board, timer or Undo/Redo history.
 * Scope 0 means all cells, 1/2/3 means row/column/box. "Unmarked
 * legal" indicates optional pencil entries, not incorrect placements.
 * Complete totals are kept even when the printed list is limited. */
static void audit_mask_digits(uint16_t mask){
    unsigned digit,shown=0u;
    for(digit=1u;digit<=9u;++digit)
        if(mask&(uint16_t)(1u<<digit))
            printf("%s%u",shown++?",":"",digit);
    if(!shown)putchar('-');
}
/* Preview the exact same validated transaction on a private game clone.
 * No state, history, timer or save destination belonging to the caller is
 * changed, even if an invalid target is detected late in the list. */
static void preview_notes_batch(const SudokuGame *game,
                                const SudokuGameNoteEdit *edits,
                                unsigned count,const char *mode){
    SudokuGame *trial=malloc(sizeof *trial);
    unsigned changed=0u,i;
    SudokuGameStatus status;
    if(!trial){puts("Error: out of memory");return;}
    *trial=*game;
    status=apply_notes_batch(trial,edits,count,mode,&changed);
    if(status!=SUDOKU_GAME_OK){
        printf("Error: %s\n",sudoku_game_status_text(status));
        free(trial);
        return;
    }
    printf("Notes batch preview (%s): %u selected, %u changed; no edits applied.\n",
           mode,count,changed);
    for(i=0u;i<count;++i){
        unsigned index=(edits[i].row-1u)*9u+edits[i].col-1u;
        if(game->state.notes[index]==trial->state.notes[index])continue;
        printf("  r%uc%u: ",edits[i].row,edits[i].col);
        audit_mask_digits(game->state.notes[index]);
        fputs(" -> ",stdout);
        audit_mask_digits(trial->state.notes[index]);
        putchar('\n');
    }
    free(trial);
}
static void audit_notes(const SudokuGame *game,unsigned limit,
                        unsigned scope,unsigned number){
    const char *kind=scope==1u?"row":scope==2u?"column":"box";
    unsigned i,examined=0u,differing=0u,shown=0u,stale_total=0u,
             unmarked_total=0u;
    if(sudoku_board_validate(&game->givens,NULL)!=SUDOKU_OK||
       sudoku_board_validate(&game->state.board,NULL)!=SUDOKU_OK){
        puts("Cannot audit notes: invalid puzzle or current board.");
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i){
        if(game->givens.cells[i]&&
           game->state.board.cells[i]!=game->givens.cells[i]){
            puts("Cannot audit notes: immutable clues were altered.");
            return;
        }
        if((game->state.notes[i]&(uint16_t)~0x3feu)!=0u||
           (game->state.board.cells[i]&&game->state.notes[i])){
            puts("Cannot audit notes: invalid handwritten pencil state.");
            return;
        }
    }
    if(!scope)printf("Pencil audit (all cells; show at most %u):\n",limit);
    else printf("Pencil audit (%s %u):\n",kind,number);
    for(i=0u;i<SUDOKU_CELL_COUNT;++i){
        unsigned row=i/9u+1u,col=i%9u+1u,
                 box=((row-1u)/3u)*3u+(col-1u)/3u+1u;
        uint16_t legal,notes,stale,unmarked;
        unsigned digit;
        if(game->state.board.cells[i])continue;
        if((scope==1u&&row!=number)||
           (scope==2u&&col!=number)||
           (scope==3u&&box!=number))continue;
        ++examined;
        legal=candidate_mask(game,i);
        notes=game->state.notes[i];
        stale=(uint16_t)(notes&(uint16_t)~legal);
        unmarked=(uint16_t)(legal&(uint16_t)~notes);
        if(!stale&&!unmarked)continue;
        ++differing;
        for(digit=1u;digit<=9u;++digit){
            if(stale&(uint16_t)(1u<<digit))++stale_total;
            if(unmarked&(uint16_t)(1u<<digit))++unmarked_total;
        }
        if(shown<limit){
            printf("row %u col %u: stale ",row,col);
            audit_mask_digits(stale);
            fputs("; unmarked legal ",stdout);
            audit_mask_digits(unmarked);
            putchar('\n');
            ++shown;
        }
    }
    printf("Pencil audit summary: %u empty inspected; %u cells differ; "
           "%u stale marks; %u unmarked legal candidates.\n",
           examined,differing,stale_total,unmarked_total);
    if(!differing)
        puts("All inspected pencil marks match the current legal candidates.");
    else if(differing>shown)
        printf("%u additional differing cells not listed (raise limit).\n",
               differing-shown);
}
/* Read-only candidate maps: [d] distinguishes a filled digit from
 * the count of legal candidates in an empty cell. Heatmap shows counts;
 * digit mode shows the selected placed digit as # and legal vacancies
 * as *. Neither reads the solved grid or edits game history. */
static int can_show_candidate_map(const SudokuGame *game){
    unsigned i;
    if(sudoku_board_validate(&game->givens,NULL)!=SUDOKU_OK||
       sudoku_board_validate(&game->state.board,NULL)!=SUDOKU_OK){
        puts("Cannot display candidate map: invalid current board.");
        return 0;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        if(game->givens.cells[i]&&
           game->state.board.cells[i]!=game->givens.cells[i]){
            puts("Cannot display candidate map: immutable clues were altered.");
            return 0;
        }
    return 1;
}
static unsigned count_candidate_digits(uint16_t mask){
    unsigned n=0u;
    while(mask){mask=(uint16_t)(mask&(uint16_t)(mask-1u));++n;}
    return n;
}
static void show_candidate_map(const SudokuGame *game,unsigned digit){
    unsigned row,col,placed=0u,possible=0u,dead=0u;
    uint16_t live[SUDOKU_CELL_COUNT]={0};
    if(!can_show_candidate_map(game))return;
    for(row=0u;row<9u;++row)
        for(col=0u;col<9u;++col){
            unsigned i=row*9u+col;
            if(game->state.board.cells[i]){
                if(game->state.board.cells[i]==digit)++placed;
            }else{
                live[i]=candidate_mask(game,i);
                if(digit&&(live[i]&(uint16_t)(1u<<digit)))++possible;
                if(!live[i])++dead;
            }
        }
    if(digit)
        printf("Digit %u map (* = legal empty; # = placed digit; . = unavailable):\n",
               digit);
    else
        puts("Candidate heatmap ([d] = filled; 1..9 = legal choices; ! = none):");
    puts("       1   2   3   4   5   6   7   8   9");
    puts("    +-----------+-----------+-----------+");
    for(row=0u;row<9u;++row){
        printf("  %u |",row+1u);
        for(col=0u;col<9u;++col){
            unsigned i=row*9u+col,d=game->state.board.cells[i];
            if(d){
                if(digit&&d==digit)fputs(" # ",stdout);
                else printf("[%u]",d);
            }else if(digit)
                fputs((live[i]&(uint16_t)(1u<<digit))?" * ":" . ",stdout);
            else{
                unsigned count=count_candidate_digits(live[i]);
                if(!count)fputs(" ! ",stdout);
                else printf(" %u ",count);
            }
            if(col%3u==2u)putchar('|');
            else putchar(' ');
        }
        putchar('\n');
        if(row%3u==2u)puts("    +-----------+-----------+-----------+");
    }
    if(digit)
        printf("Digit %u summary: %u placed; %u legal empty locations.\n",
               digit,placed,possible);
    else
        printf("Heatmap summary: %u empty cells with no legal candidates.\n",
               dead);
}
/* Read-only candidate pressure report for players who want to choose
 * their next cell without asking the cached solution for an answer.
 * Sort by increasing candidate count, then row/column in reading order.
 * A cell with zero legal candidates is surfaced as a contradiction instead
 * of being silently excluded from the search. */
static void print_focus(const SudokuGame *game,unsigned limit){
    uint16_t masks[SUDOKU_CELL_COUNT]={0};
    unsigned char counts[SUDOKU_CELL_COUNT]={0};
    unsigned i,d,rank,shown=0u,empty=0u,dead=0u;
    if(sudoku_board_validate(&game->state.board,NULL)!=SUDOKU_OK){
        puts("Cannot inspect focus: invalid current board.");
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i){
        if(game->state.board.cells[i])continue;
        ++empty;
        masks[i]=candidate_mask(game,i);
        for(d=1u;d<=9u;++d)
            if(masks[i]&(uint16_t)(1u<<d))++counts[i];
        if(counts[i]==0u)++dead;
    }
    if(!empty){
        puts("Puzzle already filled; no focus needed.");
        return;
    }
    printf("Focus cells (%u of %u empty, fewest candidates first):\n",
           empty<limit?empty:limit,empty);
    for(rank=0u;rank<=9u && shown<limit;++rank){
        for(i=0u;i<SUDOKU_CELL_COUNT && shown<limit;++i){
            if(game->state.board.cells[i] || counts[i]!=rank)continue;
            printf("row %u col %u: %u candidate%s",
                   i/9u+1u,i%9u+1u,rank,rank==1u?"":"s");
            if(rank==0u){
                puts(" (no legal digits)");
            }else{
                fputs(":",stdout);
                for(d=1u;d<=9u;++d)
                    if(masks[i]&(uint16_t)(1u<<d))printf(" %u",d);
                if(rank==1u)fputs(" (forced single)",stdout);
                putchar('\n');
            }
            ++shown;
        }
    }
    if(dead)printf("Warning: %u empty cell%s %s no legal digits; inspect entries.\n",
                   dead,dead==1u?"":"s",dead==1u?"has":"have");
}
/* Enumerate actionable naked pairs from live Sudoku constraints, not from
 * the cached solved grid. Preview is read-only; explicit apply stages all
 * candidate-note removals and commits them through one transactional engine
 * operation. Existing pair cells and digits are never modified. */
static unsigned pair_unit_cell(unsigned unit,unsigned slot){
    if(unit<9u)return unit*9u+slot;
    if(unit<18u)return slot*9u+unit-9u;
    {
        unsigned box=unit-18u;
        return ((box/3u)*3u+slot/3u)*9u+(box%3u)*3u+slot%3u;
    }
}
/* A solution-blind, read-only candidate health report for the entire
 * live Sudoku board. Detect both zero-candidate empty cells and missing
 * digits with no legal position in a row/column/box. These contradictions
 * may occur after a locally legal but globally incorrect player move.
 * Bound detailed findings while always reporting complete totals. */
static unsigned analyze_bits(uint16_t mask){
    unsigned count=0u;
    while(mask){mask=(uint16_t)(mask&(uint16_t)(mask-1u));++count;}
    return count;
}
static void analyze_board(const SudokuGame *game,unsigned limit){
    uint16_t candidates[SUDOKU_CELL_COUNT]={0};
    unsigned distribution[10]={0};
    unsigned empty=0u,dead_cells=0u,blocked=0u,shown=0u;
    unsigned i,unit,digit,slot;
    if(sudoku_board_validate(&game->givens,NULL)!=SUDOKU_OK||
       sudoku_board_validate(&game->state.board,NULL)!=SUDOKU_OK){
        puts("Cannot analyze: invalid puzzle or current board.");
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        if(game->givens.cells[i]&&
           game->state.board.cells[i]!=game->givens.cells[i]){
            puts("Cannot analyze: immutable clues were altered.");
            return;
        }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i){
        unsigned count;
        if(game->state.board.cells[i])continue;
        ++empty;
        candidates[i]=candidate_mask(game,i);
        count=analyze_bits(candidates[i]);
        ++distribution[count];
    }
    printf("Candidate analysis (%u empty, detail limit %u):\n",empty,limit);
    fputs("Candidates per empty cell:",stdout);
    for(i=0u;i<=9u;++i)printf(" %u:%u",i,distribution[i]);
    putchar('\n');
    for(i=0u;i<SUDOKU_CELL_COUNT;++i){
        if(game->state.board.cells[i]||candidates[i])continue;
        ++dead_cells;
        if(shown<limit){
            printf("Contradiction: row %u col %u has no legal candidates.\n",
                   i/9u+1u,i%9u+1u);
            ++shown;
        }
    }
    for(unit=0u;unit<27u;++unit){
        const char *kind=unit<9u?"row":unit<18u?"column":"box";
        for(digit=1u;digit<=9u;++digit){
            unsigned placed=0u,possible=0u;
            uint16_t bit=(uint16_t)(1u<<digit);
            for(slot=0u;slot<9u;++slot){
                unsigned index=pair_unit_cell(unit,slot);
                if(game->state.board.cells[index]==digit)placed=1u;
                if(candidates[index]&bit)possible=1u;
            }
            if(placed||possible)continue;
            ++blocked;
            if(shown<limit){
                printf("Contradiction: digit %u has no legal position in %s %u.\n",
                       digit,kind,unit%9u+1u);
                ++shown;
            }
        }
    }
    printf("Candidate analysis summary: %u zero-candidate cells; "
           "%u missing-digit dead ends; %u contradictions.\n",
           dead_cells,blocked,dead_cells+blocked);
    if(dead_cells+blocked>shown)
        printf("%u additional contradictions not listed (raise limit).\n",
               dead_cells+blocked-shown);
    if(!dead_cells&&!blocked)
        puts("No immediate candidate contradictions found; solvability is not guaranteed.");
}
/* Read-only speculative placement: use the current public board and local
 * row/column/box rules only. A probe is NOT a move or a solution oracle.
 * Compare before/after legal candidates to expose immediate dead ends
 * without consulting the cached solved grid or changing game history. */
static uint16_t probe_candidates(const SudokuBoard *board,unsigned index){
    uint16_t occupied=0u;
    unsigned row=index/9u,col=index%9u,k;
    if(board->cells[index])return 0u;
    for(k=0u;k<9u;++k){
        unsigned row_digit=board->cells[row*9u+k];
        unsigned col_digit=board->cells[k*9u+col];
        unsigned box_digit=board->cells[(row/3u*3u+k/3u)*9u+
                                       (col/3u*3u+k%3u)];
        occupied=(uint16_t)(occupied|
                            (uint16_t)(1u<<row_digit)|
                            (uint16_t)(1u<<col_digit)|
                            (uint16_t)(1u<<box_digit));
    }
    return (uint16_t)(0x3feu&(uint16_t)~occupied);
}
static unsigned probe_count_bits(uint16_t mask){
    unsigned count=0u;
    while(mask){mask=(uint16_t)(mask&(uint16_t)(mask-1u));++count;}
    return count;
}
static void probe_placement(const SudokuGame *game,
                            unsigned row,unsigned col,unsigned digit){
    SudokuBoard trial;
    uint16_t before[SUDOKU_CELL_COUNT]={0};
    uint16_t after[SUDOKU_CELL_COUNT]={0};
    unsigned i,unit,slot,d,removed=0u,new_zero=0u,new_gaps=0u,shown=0u;
    unsigned target=(row-1u)*9u+col-1u;
    uint16_t bit=(uint16_t)(1u<<digit);
    if(sudoku_board_validate(&game->givens,NULL)!=SUDOKU_OK||
       sudoku_board_validate(&game->state.board,NULL)!=SUDOKU_OK){
        puts("Cannot probe: invalid puzzle or current board.");
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        if(game->givens.cells[i]&&
           game->state.board.cells[i]!=game->givens.cells[i]){
            puts("Cannot probe: immutable clues were altered.");
            return;
        }
    if(game->givens.cells[target]){
        printf("Cannot probe row %u col %u: immutable original clue.\n",row,col);
        return;
    }
    if(game->state.board.cells[target]){
        printf("Cannot probe row %u col %u: cell already contains %u.\n",
               row,col,(unsigned)game->state.board.cells[target]);
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        before[i]=probe_candidates(&game->state.board,i);
    if(!(before[target]&bit)){
        printf("Cannot probe row %u col %u = %u: digit is not locally legal.\n",
               row,col,digit);
        return;
    }
    trial=game->state.board;
    trial.cells[target]=(uint8_t)digit;
    if(sudoku_board_validate(&trial,NULL)!=SUDOKU_OK){
        puts("Cannot probe: hypothetical move violates Sudoku rules.");
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        after[i]=probe_candidates(&trial,i);
    printf("Probe row %u col %u = %u: locally legal, NOT applied.\n",
           row,col,digit);
    for(i=0u;i<SUDOKU_CELL_COUNT;++i){
        if(i==target||game->state.board.cells[i])continue;
        removed+=probe_count_bits((uint16_t)(before[i]&(uint16_t)~after[i]));
        if(before[i]&&!after[i]){
            ++new_zero;
            if(new_zero<=4u)
                printf("Probe dead end: row %u col %u would have no legal digits.\n",
                       i/9u+1u,i%9u+1u);
        }
    }
    for(unit=0u;unit<27u;++unit){
        const char *kind=unit<9u?"row":unit<18u?"column":"box";
        for(d=1u;d<=9u;++d){
            unsigned existed=0u,remains=0u;
            uint16_t check=(uint16_t)(1u<<d);
            for(slot=0u;slot<9u;++slot){
                unsigned index=pair_unit_cell(unit,slot);
                if(game->state.board.cells[index]==d||
                   (before[index]&check))existed=1u;
                if(trial.cells[index]==d||(after[index]&check))remains=1u;
            }
            if(existed&&!remains){
                ++new_gaps;
                if(new_gaps<=4u)
                    printf("Probe dead end: digit %u would have no place in %s %u.\n",
                           d,kind,unit%9u+1u);
            }
        }
    }
    printf("Probe summary: %u peer candidates removed; "
           "%u new zero-candidate cells; %u new missing-digit unit gaps.\n",
           removed,new_zero,new_gaps);
    if(new_zero>4u||new_gaps>4u){
        shown=(new_zero>4u?new_zero-4u:0u)+
              (new_gaps>4u?new_gaps-4u:0u);
        printf("%u additional immediate dead ends not listed.\n",shown);
    }
    if(!new_zero&&!new_gaps)
        puts("No immediate contradiction found; this does NOT prove the move is correct.");
    puts("Probe is read-only; use 'set' to make a move.");
}
/* Single-ply contradiction hint: if placing a locally legal candidate
 * makes some other empty square lose its last legal candidate, or leaves
 * a required digit without any position in a row/column/box, that tested
 * candidate can be excluded. All tests use only the present Sudoku rules,
 * never the cached solved grid. Baseline contradictions prevent deductions. */
typedef struct TrialWitness{
    unsigned kind;  /* 0 none, 1 empty cell, 2 missing digit in unit */
    unsigned index; /* cell index or 0..26 unit index */
    unsigned digit;
} TrialWitness;
static TrialWitness trial_witness(const SudokuBoard *board,
                                  const uint16_t before[SUDOKU_CELL_COUNT],
                                  unsigned target,unsigned digit){
    SudokuBoard hypothetical=*board;
    uint16_t after[SUDOKU_CELL_COUNT]={0};
    TrialWitness result={0u,0u,0u};
    unsigned i,unit,slot,d;
    hypothetical.cells[target]=(uint8_t)digit;
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        after[i]=probe_candidates(&hypothetical,i);
    for(i=0u;i<SUDOKU_CELL_COUNT;++i){
        if(i!=target&&before[i]&&!after[i]){
            result.kind=1u;
            result.index=i;
            return result;
        }
    }
    for(unit=0u;unit<27u;++unit)
        for(d=1u;d<=9u;++d){
            uint16_t bit=(uint16_t)(1u<<d);
            unsigned existed=0u,remains=0u;
            for(slot=0u;slot<9u;++slot){
                unsigned index=pair_unit_cell(unit,slot);
                if(board->cells[index]==d||(before[index]&bit))
                    existed=1u;
                if(hypothetical.cells[index]==d||(after[index]&bit))
                    remains=1u;
            }
            if(existed&&!remains){
                result.kind=2u;
                result.index=unit;
                result.digit=d;
                return result;
            }
        }
    return result;
}
static int trial_baseline_consistent(const SudokuBoard *board,
                                     const uint16_t before[SUDOKU_CELL_COUNT]){
    unsigned i,unit,d,slot;
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        if(!board->cells[i]&&!before[i])return 0;
    for(unit=0u;unit<27u;++unit)
        for(d=1u;d<=9u;++d){
            uint16_t bit=(uint16_t)(1u<<d);
            unsigned possible=0u;
            for(slot=0u;slot<9u;++slot){
                unsigned index=pair_unit_cell(unit,slot);
                if(board->cells[index]==d||(before[index]&bit)){
                    possible=1u;
                    break;
                }
            }
            if(!possible)return 0;
        }
    return 1;
}
/* Compare every locally legal digit for one empty cell by performing
 * independent, read-only one-ply hypotheses. A resulting dead-end proves
 * exclusion, whereas absence of an immediate dead-end proves nothing.
 * This never reads the stored solved grid or modifies the live SudokuGame. */
static void probe_compare(const SudokuGame *game,unsigned row,unsigned col){
    uint16_t before[SUDOKU_CELL_COUNT]={0};
    unsigned target=(row-1u)*9u+col-1u;
    unsigned i,d,choices=0u,excluded=0u,undetermined=0u;
    if(sudoku_board_validate(&game->givens,NULL)!=SUDOKU_OK||
       sudoku_board_validate(&game->state.board,NULL)!=SUDOKU_OK){
        puts("Cannot compare: invalid puzzle or current board.");
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        if(game->givens.cells[i]&&
           game->state.board.cells[i]!=game->givens.cells[i]){
            puts("Cannot compare: immutable clues were altered.");
            return;
        }
    if(game->givens.cells[target]){
        printf("Cannot compare row %u col %u: immutable original clue.\n",
               row,col);
        return;
    }
    if(game->state.board.cells[target]){
        printf("Cannot compare row %u col %u: cell already contains %u.\n",
               row,col,(unsigned)game->state.board.cells[target]);
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        before[i]=probe_candidates(&game->state.board,i);
    if(!trial_baseline_consistent(&game->state.board,before)){
        puts("Cannot compare: current candidates already contain a contradiction.");
        return;
    }
    choices=probe_count_bits(before[target]);
    printf("Compare row %u col %u: %u legal candidate%s.\n",
           row,col,choices,choices==1u?"":"s");
    for(d=1u;d<=9u;++d){
        SudokuBoard hypothesis;
        TrialWitness witness;
        unsigned removed=0u;
        if(!(before[target]&(uint16_t)(1u<<d)))continue;
        witness=trial_witness(&game->state.board,before,target,d);
        hypothesis=game->state.board;
        hypothesis.cells[target]=(uint8_t)d;
        for(i=0u;i<SUDOKU_CELL_COUNT;++i){
            if(i==target||game->state.board.cells[i])continue;
            removed+=probe_count_bits(
                (uint16_t)(before[i]&
                (uint16_t)~probe_candidates(&hypothesis,i)));
        }
        if(witness.kind==1u){
            ++excluded;
            printf("Candidate %u: EXCLUDED (r%uc%u would have no legal digits); ",
                   d,witness.index/9u+1u,witness.index%9u+1u);
        }else if(witness.kind==2u){
            const char *kind=witness.index<9u?"row":
                             witness.index<18u?"column":"box";
            ++excluded;
            printf("Candidate %u: EXCLUDED (digit %u would have no place in %s %u); ",
                   d,witness.digit,kind,witness.index%9u+1u);
        }else{
            ++undetermined;
            printf("Candidate %u: UNDETERMINED; ",d);
        }
        printf("%u peer candidate%s removed.\n",
               removed,removed==1u?"":"s");
    }
    printf("Compare summary: %u legal candidate%s; %u provable exclusion%s; "
           "%u undetermined.\n",choices,choices==1u?"":"s",
           excluded,excluded==1u?"":"s",undetermined);
    puts("No immediate contradiction does not prove a candidate correct.");
    puts("Compare is read-only; use 'set' to make a move.");
}
/* A surviving digit is forced when a cell has multiple currently legal
 * candidates and every alternative yields a provable immediate Sudoku
 * contradiction. Use only live row/column/box constraints, never the
 * stored solution to select a digit. Preview is read-only; explicit apply
 * commits all chosen forced cells in one validated Undo transaction. */
/* Guarded user placement: verify that the current board has no immediate
 * candidate contradictions and test the requested digit on a PRIVATE
 * hypothesis before asking the atomic engine to commit. This is a guard
 * against a class of errors, never a solved-grid lookup or proof that a
 * candidate belongs in the final Sudoku solution. */
static SudokuGameStatus set_safe(SudokuGame *game,
                                  unsigned row,unsigned col,unsigned digit){
    uint16_t before[SUDOKU_CELL_COUNT]={0};
    unsigned target,i;
    TrialWitness witness;
    SudokuGameStatus status;
    if(!game)return SUDOKU_GAME_INVALID;
    if(row<1u||row>9u||col<1u||col>9u||digit<1u||digit>9u)
        return SUDOKU_GAME_RANGE;
    target=(row-1u)*9u+col-1u;
    if(sudoku_board_validate(&game->givens,NULL)!=SUDOKU_OK||
       sudoku_board_validate(&game->state.board,NULL)!=SUDOKU_OK){
        puts("Safe set refused: invalid current board.");
        return SUDOKU_GAME_INVALID;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        if(game->givens.cells[i]&&
           game->givens.cells[i]!=game->state.board.cells[i]){
            puts("Safe set refused: an original clue was altered.");
            return SUDOKU_GAME_INVALID;
        }
    if(game->givens.cells[target]){
        printf("Safe set refused: row %u col %u is an original clue.\n",row,col);
        return SUDOKU_GAME_GIVEN;
    }
    if(game->state.board.cells[target]){
        printf("Safe set refused: row %u col %u is already filled.\n",row,col);
        return SUDOKU_GAME_NOT_EMPTY;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        before[i]=probe_candidates(&game->state.board,i);
    if(!trial_baseline_consistent(&game->state.board,before)){
        puts("Safe set refused: current board already has an immediate candidate contradiction.");
        return SUDOKU_GAME_CONFLICT;
    }
    if(!(before[target]&(uint16_t)(1u<<digit))){
        printf("Safe set refused: %u is not locally legal at row %u col %u.\n",
               digit,row,col);
        return SUDOKU_GAME_CONFLICT;
    }
    witness=trial_witness(&game->state.board,before,target,digit);
    if(witness.kind==1u){
        printf("Safe set refused: r%uc%u would have no legal candidates.\n",
               witness.index/9u+1u,witness.index%9u+1u);
        return SUDOKU_GAME_CONFLICT;
    }
    if(witness.kind==2u){
        const char *kind=witness.index<9u?"row":
                         witness.index<18u?"column":"box";
        printf("Safe set refused: digit %u would have no place in %s %u.\n",
               witness.digit,kind,witness.index%9u+1u);
        return SUDOKU_GAME_CONFLICT;
    }
    status=sudoku_game_set(game,row,col,digit);
    if(status==SUDOKU_GAME_OK)
        printf("Safe set row %u col %u = %u: no immediate contradiction; "
               "this does NOT prove correctness.\n",row,col,digit);
    return status;
}
/* Opt-in proof-required user entry, stronger than 'set safe'. A choice
 * is accepted only when it is locally legal and every other locally legal
 * value in the target cell leads to an immediate row/column/box candidate
 * contradiction. This is a logically sound sufficient proof, not a general
 * Sudoku solver or a shortcut via the cached solution.
 *
 * The private trial copies and candidate arrays never mutate the game.
 * The single final update goes through the transactional game engine. */
static SudokuGameStatus set_proven(SudokuGame *game,
                                    unsigned row,unsigned col,unsigned digit){
    uint16_t before[SUDOKU_CELL_COUNT]={0};
    unsigned i,target,choices=0u,excluded=0u,unresolved=0u,d;
    TrialWitness witness;
    SudokuGameStatus status;
    if(!game)return SUDOKU_GAME_INVALID;
    if(row<1u||row>9u||col<1u||col>9u||digit<1u||digit>9u)
        return SUDOKU_GAME_RANGE;
    target=(row-1u)*9u+col-1u;
    if(sudoku_board_validate(&game->givens,NULL)!=SUDOKU_OK||
       sudoku_board_validate(&game->state.board,NULL)!=SUDOKU_OK){
        puts("Proven set refused: invalid current board.");
        return SUDOKU_GAME_INVALID;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        if(game->givens.cells[i]&&
           game->givens.cells[i]!=game->state.board.cells[i]){
            puts("Proven set refused: an original clue was altered.");
            return SUDOKU_GAME_INVALID;
        }
    if(game->givens.cells[target]){
        printf("Proven set refused: row %u col %u is an original clue.\n",
               row,col);
        return SUDOKU_GAME_GIVEN;
    }
    if(game->state.board.cells[target]){
        printf("Proven set refused: row %u col %u is already filled.\n",
               row,col);
        return SUDOKU_GAME_NOT_EMPTY;
    }
    if(sudoku_game_mistakes(game)){
        puts("Proven set refused: correct existing incorrect entries first.");
        return SUDOKU_GAME_CONFLICT;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        before[i]=probe_candidates(&game->state.board,i);
    if(!trial_baseline_consistent(&game->state.board,before)){
        puts("Proven set refused: current board already has an immediate candidate contradiction.");
        return SUDOKU_GAME_CONFLICT;
    }
    if(!(before[target]&(uint16_t)(1u<<digit))){
        printf("Proven set refused: %u is not locally legal at row %u col %u.\n",
               digit,row,col);
        return SUDOKU_GAME_CONFLICT;
    }
    /* Even the requested candidate itself must not imply a contradiction. */
    witness=trial_witness(&game->state.board,before,target,digit);
    if(witness.kind){
        printf("Proven set refused: row %u col %u = %u creates an immediate contradiction.\n",
               row,col,digit);
        return SUDOKU_GAME_CONFLICT;
    }
    for(d=1u;d<=9u;++d){
        if(!(before[target]&(uint16_t)(1u<<d)))continue;
        ++choices;
        if(d==digit)continue;
        witness=trial_witness(&game->state.board,before,target,d);
        if(witness.kind)++excluded;
        else ++unresolved;
    }
    if(unresolved){
        printf("Proven set refused: row %u col %u = %u has %u unresolved "
               "alternative%s; not logically forced.\n",
               row,col,digit,unresolved,unresolved==1u?"":"s");
        return SUDOKU_GAME_CONFLICT;
    }
    status=sudoku_game_set(game,row,col,digit);
    if(status==SUDOKU_GAME_OK)
        printf("Proven set row %u col %u = %u: %u of %u alternatives "
               "refuted; placement committed.\n",
               row,col,digit,excluded,choices-1u);
    return status;
}
/* Batch guard uses only the current board's row/column/box rules, never
 * the solved grid. Validate every input and the simultaneous final board
 * before examining candidate dead ends. No partial edits or history writes.
 * Passing this check is NOT proof that the proposed digits are correct. */
static SudokuGameStatus batch_check(const SudokuGame *game,
                                    const SudokuGameMove *moves,
                                    unsigned count){
    SudokuBoard proposed;
    uint16_t before[SUDOKU_CELL_COUNT]={0};
    uint16_t after[SUDOKU_CELL_COUNT]={0};
    unsigned char seen[SUDOKU_CELL_COUNT]={0};
    unsigned i,unit,digit,slot;
    if(!game||!moves||count==0u||count>SUDOKU_CELL_COUNT)
        return SUDOKU_GAME_INVALID;
    if(game->history_len<1u||
       game->history_len>SUDOKU_GAME_HISTORY||
       game->history_cursor>=game->history_len||
       sudoku_board_validate(&game->givens,NULL)!=SUDOKU_OK||
       sudoku_board_validate(&game->state.board,NULL)!=SUDOKU_OK){
        puts("Batch check refused: invalid current game or board.");
        return SUDOKU_GAME_INVALID;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i){
        if(game->givens.cells[i]&&
           game->state.board.cells[i]!=game->givens.cells[i]){
            puts("Batch check refused: an original clue was altered.");
            return SUDOKU_GAME_INVALID;
        }
        if((game->state.notes[i]&(uint16_t)~0x3feu)!=0u||
           (game->state.board.cells[i]&&game->state.notes[i])){
            puts("Batch check refused: invalid pencil state.");
            return SUDOKU_GAME_INVALID;
        }
        before[i]=probe_candidates(&game->state.board,i);
    }
    if(!trial_baseline_consistent(&game->state.board,before)){
        puts("Batch check refused: current board already has a candidate contradiction.");
        return SUDOKU_GAME_CONFLICT;
    }
    proposed=game->state.board;
    for(i=0u;i<count;++i){
        unsigned index;
        if(moves[i].row<1u||moves[i].row>9u||
           moves[i].col<1u||moves[i].col>9u||
           moves[i].digit<1u||moves[i].digit>9u)return SUDOKU_GAME_RANGE;
        index=(moves[i].row-1u)*9u+moves[i].col-1u;
        if(seen[index]){
            printf("Batch check refused: r%uc%u occurs more than once.\n",
                   moves[i].row,moves[i].col);
            return SUDOKU_GAME_INVALID;
        }
        seen[index]=1u;
        if(game->givens.cells[index]){
            printf("Batch check refused: r%uc%u is an original clue.\n",
                   moves[i].row,moves[i].col);
            return SUDOKU_GAME_GIVEN;
        }
        if(game->state.board.cells[index]){
            printf("Batch check refused: r%uc%u is already filled.\n",
                   moves[i].row,moves[i].col);
            return SUDOKU_GAME_NOT_EMPTY;
        }
        proposed.cells[index]=(uint8_t)moves[i].digit;
    }
    if(sudoku_board_validate(&proposed,NULL)!=SUDOKU_OK){
        puts("Batch check refused: combined placements conflict with Sudoku rules.");
        return SUDOKU_GAME_CONFLICT;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        after[i]=probe_candidates(&proposed,i);
    for(i=0u;i<SUDOKU_CELL_COUNT;++i){
        if(proposed.cells[i]||after[i])continue;
        printf("Batch check refused: r%uc%u would have no legal candidates.\n",
               i/9u+1u,i%9u+1u);
        return SUDOKU_GAME_CONFLICT;
    }
    for(unit=0u;unit<27u;++unit){
        const char *kind=unit<9u?"row":unit<18u?"column":"box";
        for(digit=1u;digit<=9u;++digit){
            unsigned possible=0u;
            uint16_t bit=(uint16_t)(1u<<digit);
            for(slot=0u;slot<9u;++slot){
                unsigned index=pair_unit_cell(unit,slot);
                if(proposed.cells[index]==digit||(after[index]&bit)){
                    possible=1u;
                    break;
                }
            }
            if(!possible){
                printf("Batch check refused: digit %u would have no place in %s %u.\n",
                       digit,kind,unit%9u+1u);
                return SUDOKU_GAME_CONFLICT;
            }
        }
    }
    printf("Batch check passed: %u simultaneous placement%s; "
           "no immediate contradictions (NOT proof of correctness).\n",
           count,count==1u?"":"s");
    return SUDOKU_GAME_OK;
}
static void hint_trial_forced(SudokuGame *game,unsigned limit,int apply){
    uint16_t before[SUDOKU_CELL_COUNT]={0};
    SudokuGameMove moves[SUDOKU_CELL_COUNT];
    unsigned i,d,found=0u;
    if(sudoku_board_validate(&game->givens,NULL)!=SUDOKU_OK||
       sudoku_board_validate(&game->state.board,NULL)!=SUDOKU_OK){
        puts("Cannot inspect trial-forced hints: invalid board.");
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        if(game->givens.cells[i]&&
           game->givens.cells[i]!=game->state.board.cells[i]){
            puts("Cannot inspect trial-forced hints: original clues were changed.");
            return;
        }
    if(sudoku_game_won(game)){
        puts("Puzzle already solved; no trial-forced hints needed.");
        return;
    }
    if(sudoku_game_mistakes(game)){
        puts(apply?"Cannot apply trial-forced hints: correct the existing mistakes first.":
                   "Cannot preview trial-forced hints: correct the existing mistakes first.");
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        before[i]=probe_candidates(&game->state.board,i);
    if(!trial_baseline_consistent(&game->state.board,before)){
        puts("Cannot inspect trial-forced hints: current candidates already contain a contradiction.");
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i){
        unsigned choices=0u,excluded=0u,survivor=0u,survivors=0u;
        if(game->state.board.cells[i])continue;
        for(d=1u;d<=9u;++d){
            TrialWitness witness;
            if(!(before[i]&(uint16_t)(1u<<d)))continue;
            ++choices;
            witness=trial_witness(&game->state.board,before,i,d);
            if(witness.kind)++excluded;
            else{
                ++survivors;
                survivor=d;
            }
        }
        /* Leave ordinary naked singles to the existing simple hint.
         * Never call a digit forced if all candidates contradict. */
        if(choices<2u||survivors!=1u||excluded!=choices-1u)continue;
        printf("Trial forced %u: row %u col %u -> %u "
               "(%u of %u candidates excluded by immediate contradiction).\n",
               found+1u,i/9u+1u,i%9u+1u,survivor,excluded,choices);
        if(apply){
            moves[found].row=i/9u+1u;
            moves[found].col=i%9u+1u;
            moves[found].digit=survivor;
        }
        if(++found==limit)break;
    }
    if(!found){
        puts("No trial-forced placements found.");
        return;
    }
    if(apply){
        unsigned placed=0u;
        SudokuGameStatus result=sudoku_game_set_many(game,moves,found,&placed);
        if(result!=SUDOKU_GAME_OK){
            printf("Error: %s (no trial-forced placements committed).\n",
                   sudoku_game_status_text(result));
            return;
        }
        printf("Applied %u trial-forced placement%s in one undoable edit.\n",
               placed,placed==1u?"":"s");
        if(sudoku_game_won(game))puts("SOLVED! All cells are correct.");
    }
}
static void hint_trial(SudokuGame *game,unsigned limit,int apply){
    uint16_t before[SUDOKU_CELL_COUNT]={0};
    uint16_t eliminations[SUDOKU_CELL_COUNT]={0};
    unsigned i,d,found=0u;
    if(sudoku_board_validate(&game->givens,NULL)!=SUDOKU_OK||
       sudoku_board_validate(&game->state.board,NULL)!=SUDOKU_OK){
        puts("Cannot inspect trial hints: invalid board.");
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        if(game->givens.cells[i]&&
           game->givens.cells[i]!=game->state.board.cells[i]){
            puts("Cannot inspect trial hints: original clues were changed.");
            return;
        }
    if(sudoku_game_won(game)){
        puts("Puzzle already solved; no trial hints needed.");
        return;
    }
    if(sudoku_game_mistakes(game)){
        puts(apply?"Cannot apply trial hints: correct the existing mistakes first.":
                   "Cannot preview trial hints: correct the existing mistakes first.");
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        before[i]=probe_candidates(&game->state.board,i);
    if(!trial_baseline_consistent(&game->state.board,before)){
        puts("Cannot inspect trial hints: current candidates already contain a contradiction.");
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i){
        if(game->state.board.cells[i])continue;
        for(d=1u;d<=9u;++d){
            TrialWitness witness;
            if(!(before[i]&(uint16_t)(1u<<d)))continue;
            witness=trial_witness(&game->state.board,before,i,d);
            if(!witness.kind)continue;
            printf("Trial %u: exclude %u from r%uc%u (",
                   found+1u,d,i/9u+1u,i%9u+1u);
            if(witness.kind==1u)
                printf("r%uc%u would have no legal candidates",
                       witness.index/9u+1u,witness.index%9u+1u);
            else{
                const char *kind=witness.index<9u?"row":
                                 witness.index<18u?"column":"box";
                printf("digit %u would have no place in %s %u",
                       witness.digit,kind,witness.index%9u+1u);
            }
            puts(").");
            if(apply)
                eliminations[i]=(uint16_t)(eliminations[i]|
                                          (uint16_t)(1u<<d));
            if(++found==limit)goto done_trial_hints;
        }
    }
done_trial_hints:
    if(!found){
        puts("No immediate-contradiction trial hints found.");
        return;
    }
    if(apply){
        unsigned removed=0u;
        SudokuGameStatus result=sudoku_game_eliminate_notes(game,eliminations,&removed);
        if(result!=SUDOKU_GAME_OK)
            printf("Error: %s\n",sudoku_game_status_text(result));
        else if(removed)
            printf("Removed %u trial pencil candidate%s in one undoable edit.\n",
                   removed,removed==1u?"":"s");
        else
            puts("No matching trial pencil notes to remove; history unchanged.");
    }
}
static void naked_pairs(SudokuGame *game,unsigned limit,int apply){
    uint16_t masks[SUDOKU_CELL_COUNT]={0};
    uint16_t eliminations[SUDOKU_CELL_COUNT]={0};
    unsigned unit,a,b,k,i,j,d,pair_digits,match,targets,total=0u;
    if(sudoku_board_validate(&game->state.board,NULL)!=SUDOKU_OK){
        puts("Cannot inspect pairs: invalid current board.");
        return;
    }
    if(sudoku_game_won(game)){
        puts("Puzzle already solved; no pair hint needed.");
        return;
    }
    if(sudoku_game_mistakes(game)){
        puts(apply?"Cannot apply pairs: correct the existing mistakes first.":
                   "Cannot preview pairs: correct the existing mistakes first.");
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        masks[i]=candidate_mask(game,i);
    for(unit=0u;unit<27u;++unit){
        const char *kind=unit<9u?"row":unit<18u?"column":"box";
        unsigned number=unit%9u+1u;
        for(a=0u;a<8u;++a){
            i=pair_unit_cell(unit,a);
            if(game->state.board.cells[i])continue;
            pair_digits=0u;
            for(d=1u;d<=9u;++d)
                if(masks[i]&(uint16_t)(1u<<d))++pair_digits;
            if(pair_digits!=2u)continue;
            for(b=a+1u;b<9u;++b){
                uint16_t pair=masks[i];
                j=pair_unit_cell(unit,b);
                if(game->state.board.cells[j]||masks[j]!=pair)continue;
                /* Reject three matching two-digit cells: they do not make
                 * a pair and must not authorize candidate elimination. */
                match=0u;
                targets=0u;
                for(k=0u;k<9u;++k){
                    unsigned index=pair_unit_cell(unit,k);
                    if(!game->state.board.cells[index]&&masks[index]==pair)
                        ++match;
                    if(k!=a&&k!=b&&(masks[index]&pair)!=0u)
                        ++targets;
                }
                if(match!=2u||targets==0u)continue;
                {
                    unsigned first=0u,second=0u;
                    for(d=1u;d<=9u;++d)
                        if(pair&(uint16_t)(1u<<d)){
                            if(!first)first=d;
                            else second=d;
                        }
                    printf("Pair %u in %s %u: r%uc%u + r%uc%u reserve %u,%u; eliminate from",
                           total+1u,kind,number,i/9u+1u,i%9u+1u,
                           j/9u+1u,j%9u+1u,first,second);
                }
                for(k=0u;k<9u;++k){
                    uint16_t eliminated;
                    unsigned index=pair_unit_cell(unit,k),separator=0u;
                    if(k==a||k==b)continue;
                    eliminated=(uint16_t)(masks[index]&pair);
                    if(!eliminated)continue;
                    if(apply)eliminations[index]=(uint16_t)(eliminations[index]|eliminated);
                    printf(" r%uc%u(",index/9u+1u,index%9u+1u);
                    for(d=1u;d<=9u;++d)
                        if(eliminated&(uint16_t)(1u<<d)){
                            if(separator++)putchar(',');
                            printf("%u",d);
                        }
                    putchar(')');
                }
                putchar('\n');
                if(++total==limit)goto done_pairs;
            }
        }
    }
done_pairs:
    if(total==0u){
        puts("No actionable naked pairs found.");
        return;
    }
    if(apply){
        unsigned removed=0u;
        SudokuGameStatus status=sudoku_game_eliminate_notes(game,eliminations,&removed);
        if(status!=SUDOKU_GAME_OK)
            printf("Error: %s\n",sudoku_game_status_text(status));
        else if(removed)
            printf("Removed %u pencil candidate%s in one undoable edit.\n",
                   removed,removed==1u?"":"s");
        else
            puts("No matching pencil notes to remove; history unchanged.");
    }
}
/* A naked triple reserves three candidate digits in exactly three cells
 * of one row, column or box. The three cells each have 2..3 candidates,
 * and their union must have exactly three digits. A fourth cell with a
 * candidate set entirely inside the triple would be contradictory, so it
 * cannot authorize eliminations. This is solution-blind and read-only
 * until the caller explicitly requests an atomic pencil-note reduction. */
static unsigned triple_bit_count(uint16_t mask){
    unsigned n=0u;
    while(mask){mask=(uint16_t)(mask&(uint16_t)(mask-1u));++n;}
    return n;
}
static void naked_triples(SudokuGame *game,unsigned limit,int apply){
    uint16_t candidates[SUDOKU_CELL_COUNT]={0};
    uint16_t eliminations[SUDOKU_CELL_COUNT]={0};
    unsigned unit,a,b,c,slot,i,d,total=0u;
    if(sudoku_board_validate(&game->state.board,NULL)!=SUDOKU_OK){
        puts("Cannot inspect triples: invalid current board.");
        return;
    }
    if(sudoku_game_won(game)){
        puts("Puzzle already solved; no triple hint needed.");
        return;
    }
    if(sudoku_game_mistakes(game)){
        puts(apply?"Cannot apply triples: correct the existing mistakes first.":
                   "Cannot preview triples: correct the existing mistakes first.");
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        candidates[i]=candidate_mask(game,i);
    for(unit=0u;unit<27u;++unit){
        const char *kind=unit<9u?"row":unit<18u?"column":"box";
        unsigned number=unit%9u+1u;
        for(a=0u;a<7u;++a){
            unsigned first=pair_unit_cell(unit,a);
            if(triple_bit_count(candidates[first])<2u||
               triple_bit_count(candidates[first])>3u)continue;
            for(b=a+1u;b<8u;++b){
                unsigned second=pair_unit_cell(unit,b);
                if(triple_bit_count(candidates[second])<2u||
                   triple_bit_count(candidates[second])>3u)continue;
                for(c=b+1u;c<9u;++c){
                    unsigned third=pair_unit_cell(unit,c),subset=0u,targets=0u;
                    uint16_t digits;
                    if(triple_bit_count(candidates[third])<2u||
                       triple_bit_count(candidates[third])>3u)continue;
                    digits=(uint16_t)(candidates[first]|candidates[second]|
                                     candidates[third]);
                    if(triple_bit_count(digits)!=3u)continue;
                    for(slot=0u;slot<9u;++slot){
                        unsigned cell=pair_unit_cell(unit,slot);
                        uint16_t mask=candidates[cell];
                        if(mask && !(mask&(uint16_t)~digits))++subset;
                        if(slot!=a&&slot!=b&&slot!=c&&(mask&digits))++targets;
                    }
                    if(subset!=3u||targets==0u)continue;
                    printf("Triple %u in %s %u: r%uc%u + r%uc%u + r%uc%u reserve ",
                           total+1u,kind,number,first/9u+1u,first%9u+1u,
                           second/9u+1u,second%9u+1u,third/9u+1u,third%9u+1u);
                    {
                        unsigned separator=0u;
                        for(d=1u;d<=9u;++d)
                            if(digits&(uint16_t)(1u<<d))
                                printf("%s%u",separator++?",":"",d);
                    }
                    fputs("; eliminate from",stdout);
                    for(slot=0u;slot<9u;++slot){
                        uint16_t excluded;
                        unsigned cell=pair_unit_cell(unit,slot),separator=0u;
                        if(slot==a||slot==b||slot==c)continue;
                        excluded=(uint16_t)(candidates[cell]&digits);
                        if(!excluded)continue;
                        if(apply)
                            eliminations[cell]=(uint16_t)(eliminations[cell]|excluded);
                        printf(" r%uc%u(",cell/9u+1u,cell%9u+1u);
                        for(d=1u;d<=9u;++d)
                            if(excluded&(uint16_t)(1u<<d))
                                printf("%s%u",separator++?",":"",d);
                        putchar(')');
                    }
                    putchar('\n');
                    if(++total==limit)goto done_triples;
                }
            }
        }
    }
done_triples:
    if(!total){
        puts("No actionable naked triples found.");
        return;
    }
    if(apply){
        unsigned removed=0u;
        SudokuGameStatus status=sudoku_game_eliminate_notes(game,eliminations,&removed);
        if(status!=SUDOKU_GAME_OK)
            printf("Error: %s\n",sudoku_game_status_text(status));
        else if(removed)
            printf("Removed %u triple pencil candidate%s in one undoable edit.\n",
                   removed,removed==1u?"":"s");
        else
            puts("No matching triple pencil notes to remove; history unchanged.");
    }
}
/* Hidden triple: three candidate digits may appear only in the same three
 * cells of one row/column/box, even when those cells have extra candidates.
 * Restrict each digit to 2-3 locations and each source cell to at least
 * two of the three digits; singles and already-resolved pairs are handled
 * by simpler hints. Only the three cells' OTHER candidates are eliminated.
 * No cached solution values are read, and preview never modifies history. */
static void hidden_triples(SudokuGame *game,unsigned limit,int apply){
    uint16_t masks[SUDOKU_CELL_COUNT]={0};
    uint16_t eliminations[SUDOKU_CELL_COUNT]={0};
    unsigned unit,d,e,f,slot,i,k,total=0u;
    if(sudoku_board_validate(&game->state.board,NULL)!=SUDOKU_OK){
        puts("Cannot inspect hidden triples: invalid current board.");
        return;
    }
    if(sudoku_game_won(game)){
        puts("Puzzle already solved; no hidden triple hint needed.");
        return;
    }
    if(sudoku_game_mistakes(game)){
        puts(apply?"Cannot apply hidden triples: correct the existing mistakes first.":
                   "Cannot preview hidden triples: correct the existing mistakes first.");
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        masks[i]=candidate_mask(game,i);
    for(unit=0u;unit<27u;++unit){
        uint16_t places[10]={0};
        const char *kind=unit<9u?"row":unit<18u?"column":"box";
        for(slot=0u;slot<9u;++slot){
            uint16_t possible=masks[pair_unit_cell(unit,slot)];
            for(d=1u;d<=9u;++d)
                if(possible&(uint16_t)(1u<<d))
                    places[d]=(uint16_t)(places[d]|(uint16_t)(1u<<slot));
        }
        for(d=1u;d<=7u;++d){
            if(triple_bit_count(places[d])<2u||
               triple_bit_count(places[d])>3u)continue;
            for(e=d+1u;e<=8u;++e){
                if(triple_bit_count(places[e])<2u||
                   triple_bit_count(places[e])>3u)continue;
                for(f=e+1u;f<=9u;++f){
                    uint16_t cells,chosen;
                    unsigned actionable=0u,valid=1u;
                    if(triple_bit_count(places[f])<2u||
                       triple_bit_count(places[f])>3u)continue;
                    cells=(uint16_t)(places[d]|places[e]|places[f]);
                    if(triple_bit_count(cells)!=3u)continue;
                    chosen=(uint16_t)((1u<<d)|(1u<<e)|(1u<<f));
                    for(slot=0u;slot<9u;++slot){
                        uint16_t source;
                        if(!(cells&(uint16_t)(1u<<slot)))continue;
                        source=masks[pair_unit_cell(unit,slot)];
                        if(triple_bit_count((uint16_t)(source&chosen))<2u){
                            valid=0u;
                            break;
                        }
                        if(source&(uint16_t)~chosen)++actionable;
                    }
                    if(!valid||!actionable)continue;
                    printf("Hidden triple %u in %s %u: ",
                           total+1u,kind,unit%9u+1u);
                    {
                        unsigned sep=0u;
                        for(slot=0u;slot<9u;++slot){
                            i=pair_unit_cell(unit,slot);
                            if(cells&(uint16_t)(1u<<slot)){
                                printf("%sr%uc%u",sep++?" + ":"",i/9u+1u,i%9u+1u);
                            }
                        }
                    }
                    printf(" reserve %u,%u,%u; remove extras",d,e,f);
                    for(slot=0u;slot<9u;++slot){
                        uint16_t excluded;
                        unsigned sep=0u;
                        if(!(cells&(uint16_t)(1u<<slot)))continue;
                        i=pair_unit_cell(unit,slot);
                        excluded=(uint16_t)(masks[i]&(uint16_t)~chosen);
                        if(!excluded)continue;
                        if(apply)
                            eliminations[i]=(uint16_t)(eliminations[i]|excluded);
                        printf(" r%uc%u(",i/9u+1u,i%9u+1u);
                        for(k=1u;k<=9u;++k)
                            if(excluded&(uint16_t)(1u<<k))
                                printf("%s%u",sep++?",":"",k);
                        putchar(')');
                    }
                    putchar('\n');
                    if(++total==limit)goto done_hidden_triples;
                }
            }
        }
    }
done_hidden_triples:
    if(!total){
        puts("No actionable hidden triples found.");
        return;
    }
    if(apply){
        unsigned removed=0u;
        SudokuGameStatus status=sudoku_game_eliminate_notes(game,eliminations,&removed);
        if(status!=SUDOKU_GAME_OK)
            printf("Error: %s\n",sudoku_game_status_text(status));
        else if(removed)
            printf("Removed %u hidden-triple pencil candidate%s in one undoable edit.\n",
                   removed,removed==1u?"":"s");
        else
            puts("No matching hidden-triple pencil notes to remove; history unchanged.");
    }
}
/* A hidden pair is two digits whose only possible locations within a
 * row/column/box are the same two unfilled cells. Thus other candidates
 * can be removed from THOSE cells, unlike a naked pair which removes the
 * paired digits from other cells of the unit. Both modes are solution-blind.
 * Dedupe identical (two cells, two digits) found in overlapping units. */
typedef struct HiddenPairKey {
    unsigned first, second;
    uint16_t digits;
} HiddenPairKey;
static void hidden_pairs(SudokuGame *game,unsigned limit,int apply){
    uint16_t masks[SUDOKU_CELL_COUNT]={0};
    uint16_t eliminations[SUDOKU_CELL_COUNT]={0};
    HiddenPairKey seen[SUDOKU_CELL_COUNT];
    unsigned seen_count=0u,total=0u,unit,i,k,d,e,j;
    if(sudoku_board_validate(&game->state.board,NULL)!=SUDOKU_OK){
        puts("Cannot inspect hidden pairs: invalid current board.");
        return;
    }
    if(sudoku_game_won(game)){
        puts("Puzzle already solved; no hidden pair hint needed.");
        return;
    }
    if(sudoku_game_mistakes(game)){
        puts(apply?"Cannot apply hidden pairs: correct the existing mistakes first.":
                   "Cannot preview hidden pairs: correct the existing mistakes first.");
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        masks[i]=candidate_mask(game,i);
    for(unit=0u;unit<27u;++unit){
        const char *kind=unit<9u?"row":unit<18u?"column":"box";
        for(d=1u;d<=8u;++d){
            unsigned first=0u,second=0u,count=0u;
            for(k=0u;k<9u;++k){
                i=pair_unit_cell(unit,k);
                if(masks[i]&(uint16_t)(1u<<d)){
                    if(count==0u)first=i;
                    else if(count==1u)second=i;
                    ++count;
                }
            }
            if(count!=2u)continue;
            for(e=d+1u;e<=9u;++e){
                unsigned matches=0u,already=0u;
                uint16_t reserved,drop_first,drop_second;
                for(k=0u;k<9u;++k){
                    i=pair_unit_cell(unit,k);
                    if(masks[i]&(uint16_t)(1u<<e)){
                        if(i==first||i==second)++matches;
                        else{matches=3u;break;}
                    }
                }
                if(matches!=2u)continue;
                reserved=(uint16_t)((1u<<d)|(1u<<e));
                drop_first=(uint16_t)(masks[first]&(uint16_t)~reserved);
                drop_second=(uint16_t)(masks[second]&(uint16_t)~reserved);
                if(!(drop_first||drop_second))continue;
                for(j=0u;j<seen_count;++j)
                    if(seen[j].first==first&&seen[j].second==second&&
                       seen[j].digits==reserved){already=1u;break;}
                if(already)continue;
                /* seen_count never exceeds the user-selected 81-pair cap. */
                seen[seen_count].first=first;
                seen[seen_count].second=second;
                seen[seen_count].digits=reserved;
                ++seen_count;
                printf("Hidden pair %u in %s %u: r%uc%u + r%uc%u reserve %u,%u; remove from",
                       total+1u,kind,unit%9u+1u,first/9u+1u,first%9u+1u,
                       second/9u+1u,second%9u+1u,d,e);
                for(j=0u;j<2u;++j){
                    unsigned index=j?second:first,sep=0u;
                    uint16_t drop=j?drop_second:drop_first;
                    if(!drop)continue;
                    if(apply)eliminations[index]=(uint16_t)(eliminations[index]|drop);
                    printf(" r%uc%u(",index/9u+1u,index%9u+1u);
                    for(i=1u;i<=9u;++i)
                        if(drop&(uint16_t)(1u<<i)){
                            if(sep++)putchar(',');
                            printf("%u",i);
                        }
                    putchar(')');
                }
                putchar('\n');
                if(++total==limit)goto done_hidden_pairs;
            }
        }
    }
done_hidden_pairs:
    if(!total){
        puts("No actionable hidden pairs found.");
        return;
    }
    if(apply){
        unsigned removed=0u;
        SudokuGameStatus status=sudoku_game_eliminate_notes(game,eliminations,&removed);
        if(status!=SUDOKU_GAME_OK)
            printf("Error: %s\n",sudoku_game_status_text(status));
        else if(removed)
            printf("Removed %u hidden-pair pencil candidate%s in one undoable edit.\n",
                   removed,removed==1u?"":"s");
        else
            puts("No matching hidden-pair pencil notes to remove; history unchanged.");
    }
}
/* Locked candidates: if every occurrence of digit D in a box lies in
 * one row/column, D can be removed from the rest of that line (pointing).
 * Conversely, if every occurrence in a row/column lies in one box, D can
 * be removed from the other cells in that box (claiming). This scan uses
 * current-board legal candidates only, never the stored solved board. */
static unsigned locked_box(unsigned cell){
    return (cell/27u)*3u+(cell%9u)/3u;
}
static void locked_report(unsigned number,const char *kind,
                          const char *origin,unsigned from,
                          const char *destination,unsigned to,
                          unsigned digit,const unsigned sources[9],
                          unsigned source_count,const unsigned targets[9],
                          unsigned target_count,int apply,
                          uint16_t eliminations[SUDOKU_CELL_COUNT]){
    unsigned k;
    printf("Locked %u (%s %s %u -> %s %u, digit %u): sources",
           number,kind,origin,from+1u,destination,to+1u,digit);
    for(k=0u;k<source_count;++k)
        printf(" r%uc%u",sources[k]/9u+1u,sources[k]%9u+1u);
    fputs("; eliminate",stdout);
    for(k=0u;k<target_count;++k){
        unsigned i=targets[k];
        printf(" r%uc%u",i/9u+1u,i%9u+1u);
        if(apply)eliminations[i]=(uint16_t)(eliminations[i]|(uint16_t)(1u<<digit));
    }
    putchar('\n');
}
static void locked_candidates(SudokuGame *game,unsigned limit,int apply){
    uint16_t masks[SUDOKU_CELL_COUNT]={0};
    uint16_t eliminations[SUDOKU_CELL_COUNT]={0};
    unsigned pass,unit,digit,k,total=0u,i;
    if(sudoku_board_validate(&game->state.board,NULL)!=SUDOKU_OK){
        puts("Cannot inspect locked candidates: invalid current board.");
        return;
    }
    if(sudoku_game_won(game)){
        puts("Puzzle already solved; no locked hint needed.");
        return;
    }
    if(sudoku_game_mistakes(game)){
        puts(apply?"Cannot apply locked candidates: correct the existing mistakes first.":
                   "Cannot preview locked candidates: correct the existing mistakes first.");
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        masks[i]=candidate_mask(game,i);
    /* First scan boxes (pointing); then scan rows/columns (claiming).
     * A source digit needs two or more possible cells to distinguish this
     * from the single-candidate/hidden-single strategies. */
    for(pass=0u;pass<2u;++pass){
        unsigned units=pass==0u?9u:18u;
        for(unit=0u;unit<units;++unit){
            for(digit=1u;digit<=9u;++digit){
                unsigned sources[9],count=0u;
                uint16_t bit=(uint16_t)(1u<<digit);
                for(k=0u;k<9u;++k){
                    i=pair_unit_cell(pass==0u?unit+18u:unit,k);
                    if(masks[i]&bit)sources[count++]=i;
                }
                if(count<2u)continue;
                if(pass==0u){
                    unsigned row=sources[0]/9u,col=sources[0]%9u;
                    unsigned same_row=1u,same_col=1u,axis;
                    for(k=1u;k<count;++k){
                        if(sources[k]/9u!=row)same_row=0u;
                        if(sources[k]%9u!=col)same_col=0u;
                    }
                    for(axis=0u;axis<2u;++axis){
                        unsigned targets[9],target_count=0u;
                        unsigned line=axis?col:row;
                        if((axis&&!same_col)||(!axis&&!same_row))continue;
                        for(k=0u;k<9u;++k){
                            i=pair_unit_cell(axis?line+9u:line,k);
                            if(locked_box(i)!=unit&&(masks[i]&bit))
                                targets[target_count++]=i;
                        }
                        if(!target_count)continue;
                        locked_report(total+1u,"pointing","box",unit,
                                      axis?"column":"row",line,digit,
                                      sources,count,targets,target_count,
                                      apply,eliminations);
                        if(++total==limit)goto done_locked;
                    }
                }else{
                    unsigned box=locked_box(sources[0]),same_box=1u;
                    unsigned targets[9],target_count=0u;
                    for(k=1u;k<count;++k)
                        if(locked_box(sources[k])!=box)same_box=0u;
                    if(!same_box)continue;
                    for(k=0u;k<9u;++k){
                        i=pair_unit_cell(box+18u,k);
                        if((unit<9u?i/9u!=unit:i%9u!=unit-9u)&&
                           (masks[i]&bit))
                            targets[target_count++]=i;
                    }
                    if(!target_count)continue;
                    locked_report(total+1u,"claiming",
                                  unit<9u?"row":"column",unit%9u,
                                  "box",box,digit,sources,count,
                                  targets,target_count,apply,eliminations);
                    if(++total==limit)goto done_locked;
                }
            }
        }
    }
done_locked:
    if(!total){
        puts("No actionable locked candidates found.");
        return;
    }
    if(apply){
        unsigned removed=0u;
        SudokuGameStatus status=sudoku_game_eliminate_notes(game,eliminations,&removed);
        if(status!=SUDOKU_GAME_OK)
            printf("Error: %s\n",sudoku_game_status_text(status));
        else if(removed)
            printf("Removed %u locked pencil candidate%s in one undoable edit.\n",
                   removed,removed==1u?"":"s");
        else
            puts("No matching locked pencil notes to remove; history unchanged.");
    }
}
/* A digit confined to the same two columns in exactly two rows (or the
 * same two rows in exactly two columns) forms an X-Wing. The four corners
 * reserve both positions, so that digit can be removed from other cells of
 * the intersecting columns/rows. Use only locally legal candidates, not the
 * cached solved board; only existing handwritten notes are removed on apply.
 * Requiring exactly two source lines avoids emitting patterns from a
 * contradictory three-line/two-position state. */
static unsigned xwing_index(unsigned axis,unsigned line,unsigned slot){
    return axis ? slot*9u+line : line*9u+slot;
}
static void x_wings(SudokuGame *game,unsigned limit,int apply){
    uint16_t masks[SUDOKU_CELL_COUNT]={0};
    uint16_t eliminations[SUDOKU_CELL_COUNT]={0};
    unsigned axis,digit,a,b,line,slot,first,second,total=0u,i;
    if(sudoku_board_validate(&game->state.board,NULL)!=SUDOKU_OK){
        puts("Cannot inspect X-Wings: invalid current board.");
        return;
    }
    if(sudoku_game_won(game)){
        puts("Puzzle already solved; no X-Wing hint needed.");
        return;
    }
    if(sudoku_game_mistakes(game)){
        puts(apply?"Cannot apply X-Wings: correct the existing mistakes first.":
                   "Cannot preview X-Wings: correct the existing mistakes first.");
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        masks[i]=candidate_mask(game,i);
    for(axis=0u;axis<2u;++axis){
        for(digit=1u;digit<=9u;++digit){
            uint16_t bit=(uint16_t)(1u<<digit);
            for(a=0u;a<8u;++a){
                unsigned pair=0u,count=0u;
                for(slot=0u;slot<9u;++slot){
                    i=xwing_index(axis,a,slot);
                    if(masks[i]&bit){
                        pair|=1u<<slot;
                        ++count;
                    }
                }
                if(count!=2u)continue;
                first=9u;second=9u;
                for(slot=0u;slot<9u;++slot)
                    if(pair&(1u<<slot)){
                        if(first==9u)first=slot;
                        else second=slot;
                    }
                for(b=a+1u;b<9u;++b){
                    unsigned other=0u,other_count=0u,extra=0u;
                    unsigned targets[18],target_count=0u;
                    for(slot=0u;slot<9u;++slot){
                        i=xwing_index(axis,b,slot);
                        if(masks[i]&bit){
                            other|=1u<<slot;
                            ++other_count;
                        }
                    }
                    if(other_count!=2u||other!=pair)continue;
                    /* An impossible 3+ matching-line pattern is not a
                     * sound basis for reporting eliminations. */
                    for(line=0u;line<9u;++line){
                        unsigned position=0u,n=0u;
                        if(line==a||line==b)continue;
                        for(slot=0u;slot<9u;++slot){
                            i=xwing_index(axis,line,slot);
                            if(masks[i]&bit){
                                position|=1u<<slot;
                                ++n;
                            }
                        }
                        if(n==2u&&position==pair)extra=1u;
                    }
                    if(extra)continue;
                    for(line=0u;line<9u;++line){
                        if(line==a||line==b)continue;
                        for(slot=0u;slot<9u;++slot){
                            if(!(pair&(1u<<slot)))continue;
                            i=xwing_index(axis,line,slot);
                            if(masks[i]&bit)targets[target_count++]=i;
                        }
                    }
                    if(!target_count)continue;
                    printf("X-Wing %u (%s %u,%u; %s %u,%u; digit %u): corners",
                           total+1u,axis?"columns":"rows",a+1u,b+1u,
                           axis?"rows":"columns",first+1u,second+1u,digit);
                    /* Print the four corners in deterministic order. */
                    for(line=0u;line<2u;++line)
                        for(slot=0u;slot<2u;++slot){
                            i=xwing_index(axis,line?b:a,slot?second:first);
                            printf(" r%uc%u",i/9u+1u,i%9u+1u);
                        }
                    fputs("; eliminate",stdout);
                    for(i=0u;i<target_count;++i){
                        unsigned target=targets[i];
                        printf(" r%uc%u",target/9u+1u,target%9u+1u);
                        if(apply)
                            eliminations[target]=(uint16_t)(eliminations[target]|bit);
                    }
                    putchar('\n');
                    if(++total==limit)goto done_xwings;
                }
            }
        }
    }
done_xwings:
    if(!total){
        puts("No actionable X-Wings found.");
        return;
    }
    if(apply){
        unsigned removed=0u;
        SudokuGameStatus status=sudoku_game_eliminate_notes(game,eliminations,&removed);
        if(status!=SUDOKU_GAME_OK)
            printf("Error: %s\n",sudoku_game_status_text(status));
        else if(removed)
            printf("Removed %u X-Wing pencil candidate%s in one undoable edit.\n",
                   removed,removed==1u?"":"s");
        else
            puts("No matching X-Wing pencil notes to remove; history unchanged.");
    }
}
/* Swordfish: three rows/columns each have 2..3 candidates for a digit,
 * restricted to exactly three opposite columns/rows. Each opposite line
 * must contain at least two source candidates, excluding degenerate fish.
 * Candidate elimination never consults the cached Sudoku solution. */
static unsigned fish_bits(uint16_t mask){
    unsigned n=0u;
    while(mask){mask=(uint16_t)(mask&(uint16_t)(mask-1u));++n;}
    return n;
}
static void swordfish(SudokuGame *game,unsigned limit,int apply){
    uint16_t masks[SUDOKU_CELL_COUNT]={0};
    uint16_t eliminations[SUDOKU_CELL_COUNT]={0};
    unsigned axis,digit,line,slot,a,b,c,total=0u,i;
    if(sudoku_board_validate(&game->state.board,NULL)!=SUDOKU_OK){
        puts("Cannot inspect Swordfish: invalid current board.");
        return;
    }
    if(sudoku_game_won(game)){
        puts("Puzzle already solved; no Swordfish hint needed.");
        return;
    }
    if(sudoku_game_mistakes(game)){
        puts(apply?"Cannot apply Swordfish: correct the existing mistakes first.":
                   "Cannot preview Swordfish: correct the existing mistakes first.");
        return;
    }
    for(i=0u;i<SUDOKU_CELL_COUNT;++i)
        masks[i]=candidate_mask(game,i);
    for(axis=0u;axis<2u;++axis){
        for(digit=1u;digit<=9u;++digit){
            uint16_t line_masks[9]={0};
            uint16_t bit=(uint16_t)(1u<<digit);
            for(line=0u;line<9u;++line)
                for(slot=0u;slot<9u;++slot)
                    if(masks[xwing_index(axis,line,slot)]&bit)
                        line_masks[line]=(uint16_t)(line_masks[line]|(uint16_t)(1u<<slot));
            for(a=0u;a<7u;++a){
                if(fish_bits(line_masks[a])<2u||fish_bits(line_masks[a])>3u)continue;
                for(b=a+1u;b<8u;++b){
                    if(fish_bits(line_masks[b])<2u||fish_bits(line_masks[b])>3u)continue;
                    for(c=b+1u;c<9u;++c){
                        uint16_t union_mask;
                        unsigned targets[18],target_count=0u,valid=1u;
                        if(fish_bits(line_masks[c])<2u||
                           fish_bits(line_masks[c])>3u)continue;
                        union_mask=(uint16_t)(line_masks[a]|line_masks[b]|line_masks[c]);
                        if(fish_bits(union_mask)!=3u)continue;
                        for(slot=0u;slot<9u;++slot){
                            uint16_t bit_slot=(uint16_t)(1u<<slot);
                            unsigned repeats=0u;
                            if(!(union_mask&bit_slot))continue;
                            if(line_masks[a]&bit_slot)++repeats;
                            if(line_masks[b]&bit_slot)++repeats;
                            if(line_masks[c]&bit_slot)++repeats;
                            if(repeats<2u){valid=0u;break;}
                        }
                        if(!valid)continue;
                        for(line=0u;line<9u;++line){
                            if(line==a||line==b||line==c)continue;
                            for(slot=0u;slot<9u;++slot){
                                if(!(union_mask&(uint16_t)(1u<<slot)))continue;
                                i=xwing_index(axis,line,slot);
                                if(masks[i]&bit)targets[target_count++]=i;
                            }
                        }
                        if(!target_count)continue;
                        printf("Swordfish %u (%s %u,%u,%u; %s",
                               total+1u,axis?"columns":"rows",a+1u,b+1u,c+1u,
                               axis?"rows":"columns");
                        {
                            unsigned shown=0u;
                            for(slot=0u;slot<9u;++slot)
                                if(union_mask&(uint16_t)(1u<<slot))
                                    printf("%s%u",shown++?",":" ",slot+1u);
                        }
                        printf("; digit %u): sources",digit);
                        for(line=0u;line<9u;++line){
                            if(line!=a&&line!=b&&line!=c)continue;
                            for(slot=0u;slot<9u;++slot)
                                if(line_masks[line]&(uint16_t)(1u<<slot)){
                                    i=xwing_index(axis,line,slot);
                                    printf(" r%uc%u",i/9u+1u,i%9u+1u);
                                }
                        }
                        fputs("; eliminate",stdout);
                        for(i=0u;i<target_count;++i){
                            unsigned target=targets[i];
                            printf(" r%uc%u",target/9u+1u,target%9u+1u);
                            if(apply)
                                eliminations[target]=(uint16_t)(eliminations[target]|bit);
                        }
                        putchar('\n');
                        if(++total==limit)goto done_swordfish;
                    }
                }
            }
        }
    }
done_swordfish:
    if(!total){
        puts("No actionable Swordfish found.");
        return;
    }
    if(apply){
        unsigned removed=0u;
        SudokuGameStatus status=sudoku_game_eliminate_notes(game,eliminations,&removed);
        if(status!=SUDOKU_GAME_OK)
            printf("Error: %s\n",sudoku_game_status_text(status));
        else if(removed)
            printf("Removed %u Swordfish pencil candidate%s in one undoable edit.\n",
                   removed,removed==1u?"":"s");
        else
            puts("No matching Swordfish pencil notes to remove; history unchanged.");
    }
}
typedef struct LogicalHint {
    unsigned index, digit, group;
    int hidden;
} LogicalHint;
/* Collect distinct logically forced cells without consulting the solution.
 * Prefer naked singles; then hidden singles in row, column and box order.
 * The seen bitmap prevents double-counting the same cell in several units.
 * A cap of one preserves the original deterministic 'hint' preference. */
static unsigned collect_hints(const SudokuGame *game,LogicalHint *hints,unsigned limit){
    uint16_t masks[SUDOKU_CELL_COUNT]={0};
    unsigned char seen[SUDOKU_CELL_COUNT]={0};
    unsigned i,d,group,slot,count,chosen,total=0u;
    if(!limit)return 0u;
    for(i=0u;i<SUDOKU_CELL_COUNT;++i){
        masks[i]=candidate_mask(game,i);
        d=single_candidate(masks[i]);
        if(d){
            hints[total].index=i;
            hints[total].digit=d;
            hints[total].group=0u;
            hints[total].hidden=0;
            seen[i]=1u;
            if(++total==limit)return total;
        }
    }
    for(group=0u;group<27u;++group){
        for(d=1u;d<=9u;++d){
            count=0u;
            chosen=0u;
            for(slot=0u;slot<9u;++slot){
                if(group<9u)i=group*9u+slot;
                else if(group<18u)i=slot*9u+(group-9u);
                else{
                    unsigned box=group-18u;
                    i=((box/3u)*3u+slot/3u)*9u+(box%3u)*3u+slot%3u;
                }
                if((masks[i]&(uint16_t)(1u<<d))!=0u){
                    ++count;
                    chosen=i;
                }
            }
            if(count==1u && !seen[chosen]){
                hints[total].index=chosen;
                hints[total].digit=d;
                hints[total].group=group;
                hints[total].hidden=1;
                seen[chosen]=1u;
                if(++total==limit)return total;
            }
        }
    }
    return total;
}
static int find_hint(const SudokuGame *game,LogicalHint *hint){
    return collect_hints(game,hint,1u)!=0u;
}
/* 'hint' is observational. 'hint apply' explicitly places exactly one
 * logical single via the normal game setter (and therefore supports undo).
 * Never auto-place when the player's grid already has incorrect entries. */
static void print_hint(SudokuGame *game,int apply){
    LogicalHint hint;
    SudokuGameStatus result;
    const char *action=apply?"Applied hint":"Hint";
    if(sudoku_game_won(game)){
        puts("Puzzle already solved; no hint needed.");
        return;
    }
    if(sudoku_game_mistakes(game)){
        if(apply)
            puts("Cannot apply hint: correct the existing mistakes first.");
        else
            puts("Cannot preview hint: correct the existing mistakes first. Use 'check details'.");
        return;
    }
    if(!find_hint(game,&hint)){
        puts("No simple hint found. Try candidates ROW COL.");
        return;
    }
    if(apply){
        result=sudoku_game_set(game,hint.index/9u+1u,
                              hint.index%9u+1u,hint.digit);
        if(result!=SUDOKU_GAME_OK){
            printf("Error: %s\n",sudoku_game_status_text(result));
            return;
        }
    }
    if(!hint.hidden){
        printf("%s (only candidate): row %u col %u -> %u.\n",
               action,hint.index/9u+1u,hint.index%9u+1u,hint.digit);
    }else{
        const char *unit=hint.group<9u?"row":hint.group<18u?"column":"box";
        printf("%s (only place in %s %u): row %u col %u -> %u.\n",
               action,unit,hint.group%9u+1u,
               hint.index/9u+1u,hint.index%9u+1u,hint.digit);
    }
    if(apply&&sudoku_game_won(game))puts("SOLVED! All cells are correct.");
}
/* Enumerate available logical singles without placing a digit or touching
 * pencil notes, timers or history. Each cell is shown at most once. */
static void print_hint_all(const SudokuGame *game){
    LogicalHint hints[SUDOKU_CELL_COUNT];
    unsigned count,i;
    if(sudoku_game_won(game)){
        puts("Puzzle already solved; no hint needed.");
        return;
    }
    if(sudoku_game_mistakes(game)){
        puts("Cannot list hints: correct the existing mistakes first. Use 'check details'.");
        return;
    }
    count=collect_hints(game,hints,SUDOKU_CELL_COUNT);
    if(!count){
        puts("No simple hint found. Try candidates ROW COL.");
        return;
    }
    printf("Logical hints (%u):\n",count);
    for(i=0u;i<count;++i){
        const LogicalHint *hint=&hints[i];
        if(!hint->hidden){
            printf("Hint (only candidate): row %u col %u -> %u.\n",
                   hint->index/9u+1u,hint->index%9u+1u,hint->digit);
        }else{
            const char *unit=hint->group<9u?"row":hint->group<18u?"column":"box";
            printf("Hint (only place in %s %u): row %u col %u -> %u.\n",
                   unit,hint->group%9u+1u,
                   hint->index/9u+1u,hint->index%9u+1u,hint->digit);
        }
    }
}
/* Apply the current forced deductions as exactly one history operation.
 * Refuse incorrect entries (including legal-but-wrong values) before using
 * current-board candidates; the cached answer never supplies a hint digit. */
static void apply_all_hints(SudokuGame *game){
    LogicalHint hints[SUDOKU_CELL_COUNT];
    SudokuGameMove moves[SUDOKU_CELL_COUNT];
    unsigned count,i,applied=0u;
    SudokuGameStatus result;
    if(sudoku_game_won(game)){
        puts("Puzzle already solved; no hint needed.");
        return;
    }
    if(sudoku_game_mistakes(game)){
        puts("Cannot apply hints: correct the existing mistakes first.");
        return;
    }
    count=collect_hints(game,hints,SUDOKU_CELL_COUNT);
    if(!count){
        puts("No simple hint found. Try candidates ROW COL.");
        return;
    }
    for(i=0u;i<count;++i){
        moves[i].row=hints[i].index/9u+1u;
        moves[i].col=hints[i].index%9u+1u;
        moves[i].digit=hints[i].digit;
    }
    result=sudoku_game_set_many(game,moves,count,&applied);
    if(result!=SUDOKU_GAME_OK){
        printf("Error: %s\n",sudoku_game_status_text(result));
        return;
    }
    printf("Applied %u logical hints in one undoable move.\n",applied);
    if(sudoku_game_won(game))puts("SOLVED! All cells are correct.");
}
/* Build a deterministic sequence of only live-board singles. A private
 * game copy advances after every placement, so later hints can depend on
 * earlier ones. The original game, notes and history are never touched.
 * Each iteration fills one cell; the 81-cell bound guarantees termination. */
static SudokuGameStatus collect_hint_chain(const SudokuGame *game,
                                            LogicalHint hints[SUDOKU_CELL_COUNT],
                                            unsigned limit,unsigned *count){
    SudokuGame *trial;
    SudokuGameStatus result=SUDOKU_GAME_OK;
    *count=0u;
    if(limit==0u||limit>SUDOKU_CELL_COUNT)return SUDOKU_GAME_RANGE;
    trial=malloc(sizeof *trial);
    if(!trial)return SUDOKU_GAME_IO;
    *trial=*game;
    while(*count<limit){
        LogicalHint next;
        if(!find_hint(trial,&next))break;
        result=sudoku_game_set(trial,next.index/9u+1u,
                              next.index%9u+1u,next.digit);
        if(result!=SUDOKU_GAME_OK)break;
        hints[(*count)++]=next;
    }
    free(trial);
    return result;
}
/* Preview successive forced deductions or commit all of them through the
 * transactional set-many API as ONE Undo step. No guess or solution lookup
 * supplies a placement; the verified solution is used only to block a
 * board that already contains wrong user entries. */
static void hint_chain(SudokuGame *game,int apply,unsigned limit){
    LogicalHint hints[SUDOKU_CELL_COUNT];
    SudokuGameMove moves[SUDOKU_CELL_COUNT];
    SudokuGameStatus status;
    unsigned count,i,applied=0u;
    if(sudoku_game_won(game)){
        puts("Puzzle already solved; no hint needed.");
        return;
    }
    if(sudoku_game_mistakes(game)){
        puts(apply?"Cannot apply hints: correct the existing mistakes first.":
                   "Cannot preview hint chain: correct the existing mistakes first.");
        return;
    }
    status=collect_hint_chain(game,hints,limit,&count);
    if(status!=SUDOKU_GAME_OK){
        printf("Error: %s\n",sudoku_game_status_text(status));
        return;
    }
    if(count==0u){
        puts("No simple hint found. Try candidates ROW COL.");
        return;
    }
    if(apply){
        for(i=0u;i<count;++i){
            moves[i].row=hints[i].index/9u+1u;
            moves[i].col=hints[i].index%9u+1u;
            moves[i].digit=hints[i].digit;
        }
        status=sudoku_game_set_many(game,moves,count,&applied);
        if(status!=SUDOKU_GAME_OK){
            printf("Error: %s\n",sudoku_game_status_text(status));
            return;
        }
        printf("Applied %u chained logical hints in one undoable move.\n",applied);
        if(sudoku_game_won(game))puts("SOLVED! All cells are correct.");
        return;
    }
    printf("Logical hint chain (%u steps):\n",count);
    for(i=0u;i<count;++i){
        const LogicalHint *hint=&hints[i];
        if(!hint->hidden){
            printf("Step %u (only candidate): row %u col %u -> %u.\n",
                   i+1u,hint->index/9u+1u,hint->index%9u+1u,hint->digit);
        }else{
            const char *unit=hint->group<9u?"row":hint->group<18u?"column":"box";
            printf("Step %u (only place in %s %u): row %u col %u -> %u.\n",
                   i+1u,unit,hint->group%9u+1u,
                   hint->index/9u+1u,hint->index%9u+1u,hint->digit);
        }
    }
}
/* Identify mistakes against the verified solution without disclosing any
 * answer digit. Read-only: no note, timer, save or undo/redo side effects. */
static void print_check_details(const SudokuGame *game){
    unsigned i,count=0u;
    printf("Check: %u empty, %u incorrect.\n",
           sudoku_game_empty(game),sudoku_game_mistakes(game));
    for(i=0u;i<SUDOKU_CELL_COUNT;++i){
        unsigned placed=game->state.board.cells[i];
        if(placed!=0u && placed!=game->solution.cells[i]){
            printf("Incorrect entry: row %u col %u contains %u.\n",
                   i/9u+1u,i%9u+1u,placed);
            ++count;
        }
    }
    if(count==0u)puts("No incorrect entries.");
}
/* Read a complete command line before interpreting any part of it. fgets
 * plus strlen would silently truncate at an embedded NUL, potentially
 * executing an unintended prefix such as "save path". Discard malformed
 * or overlong lines in full so the next command is aligned correctly.
 * 0 = EOF, 1 = valid line, 2 = rejected line, -1 = input error. */
static int read_command_line(char line[], size_t capacity) {
    size_t used = 0u;
    int ch, seen = 0, too_long = 0, nul = 0, control = 0;
    if (capacity == 0u) return -1;
    while ((ch = fgetc(stdin)) != EOF) {
        seen = 1;
        if (ch == '\n') break;
        if (ch == '\0') nul = 1;
        if ((ch < 32 && ch != '\t' && ch != '\r') || ch == 127)
            control = 1;
        if (used + 1u < capacity) line[used++] = (char)ch;
        else too_long = 1;
    }
    if (ferror(stdin)) return -1;
    if (!seen && ch == EOF) return 0;
    /* Accept Windows CRLF and a trailing CR at EOF, but not a CR
     * embedded in the command (which can rewrite terminal output). */
    if (used && line[used - 1u] == '\r') --used;
    line[used] = '\0';
    if (too_long) {
        puts("Error: command too long");
        return 2;
    }
    if (nul) {
        puts("Error: command contains a NUL byte");
        return 2;
    }
    if (control || memchr(line, '\r', used) != NULL) {
        puts("Error: command contains a control byte");
        return 2;
    }
    return 1;
}
static int event_loop(SudokuGame *game,PlayOptions *opt){
    char line[4096 + 32];
    char last_save_path[4097];
    display(game);
    for (;;) {
        int line_status = read_command_line(line, sizeof line);
        char *command,*a,*b,*c,*extra,*tail;
        unsigned r,d;uint64_t digit;
        SudokuGameStatus status=SUDOKU_GAME_OK;
        if (line_status == 0) break;
        if (line_status < 0) {
            fputs("Game input read failed\n", stderr);
            return 4;
        }
        if (line_status == 2) continue;
        /* Handle save before strtok: the complete remainder of the command is
         * a path, so filenames containing whitespace survive tokenization.
         * An optional surrounding pair of double quotes is accepted. */
        {
            char *first = line;
            while (*first == ' ' || *first == '\t') ++first;
            if (strncmp(first, "save", 4u) == 0 &&
                (first[4] == '\0' || first[4] == ' ' || first[4] == '\t' ||
                 first[4] == '\r' || first[4] == '\n')) {
                char *path = first + 4;
                const char *target;
                size_t path_len;
                SudokuGameStatus saved;
                while (*path == ' ' || *path == '\t') ++path;
                path_len = strlen(path);
                while (path_len &&
                       (path[path_len - 1u] == ' ' || path[path_len - 1u] == '\t' ||
                        path[path_len - 1u] == '\r' || path[path_len - 1u] == '\n'))
                    path[--path_len] = '\0';
                if (path_len && path[0] == '"') {
                    if (path_len < 2u || path[path_len - 1u] != '"') {
                        puts("Error: malformed quoted save path");
                        continue;
                    }
                    path[path_len - 1u] = '\0';
                    ++path;
                    /* Explicit empty quotes must not silently reuse the last
                     * destination and accidentally overwrite an older save. */
                    if (!*path) {
                        puts("Error: empty save path");
                        continue;
                    }
                }
                /* Double quotes delimit an optional *outer* pair; embedded
                 * or stray quote marks are malformed syntax, not literal
                 * filenames. Reject rather than saving to an unexpected
                 * destination (which differs across POSIX and Windows). */
                if (strchr(path, '"') != NULL) {
                    puts("Error: malformed quoted save path");
                    continue;
                }
                target = *path ? path : opt->save;
                if (!target || !*target) {
                    puts("Error: supply a path, e.g. save puzzle.save");
                    continue;
                }
                if (strlen(target) > 4096u) {
                    puts("Error: save path too long");
                    continue;
                }
                saved = sudoku_game_save(game, target);
                if (saved != SUDOKU_GAME_OK &&
                    saved != SUDOKU_GAME_DURABILITY_UNCERTAIN) {
                    printf("Error: %s\n", sudoku_game_status_text(saved));
                    continue;
                }
                /* A post-rename sync warning means the target WAS replaced:
                 * remember the explicit path even when durability is uncertain. */
                if (*path) {
                    (void)strcpy(last_save_path, target);
                    opt->save = last_save_path;
                    target = opt->save;
                }
                if (saved == SUDOKU_GAME_DURABILITY_UNCERTAIN)
                    printf("Warning: %s\n", sudoku_game_status_text(saved));
                else
                    printf("Saved to %s (version 1, checksummed, atomic replace).\n", target);
                continue;
            }
        }
        command=strtok(line," \t\r\n");
        if(!command)continue;
        a=strtok(NULL," \t\r\n");
        b=strtok(NULL," \t\r\n");
        c=strtok(NULL," \t\r\n");
        extra=strtok(NULL," \t\r\n");
        tail=strtok(NULL," \t\r\n");
        /* Never let fifth and later arguments vanish after tokenization. */
        if(tail){
            puts("Error: unknown command or invalid arguments. Type 'help'.");
            continue;
        }
        if(strcmp(command,"quit")==0||strcmp(command,"exit")==0){
            if(a)puts("Error: quit takes no argument");
            else{puts("Goodbye. Use 'save' before quitting to preserve progress.");return 0;}
            continue;
        }
        if(strcmp(command,"help")==0&&!a){commands();continue;}
        if(strcmp(command,"hint")==0){
            uint64_t limit=81u;
            if(!a)print_hint(game,0);
            else if(strcmp(a,"all")==0&&!b)print_hint_all(game);
            else if(strcmp(a,"pairs")==0&&
                    (!b||(!c&&!extra&&decimal(b,81u,&limit)&&limit>=1u)))
                naked_pairs(game,(unsigned)(b?limit:5u),0);
            else if(strcmp(a,"triples")==0&&
                    (!b||(!c&&!extra&&decimal(b,81u,&limit)&&limit>=1u)))
                naked_triples(game,(unsigned)(b?limit:5u),0);
            else if(strcmp(a,"hidden-triples")==0&&
                    (!b||(!c&&!extra&&decimal(b,81u,&limit)&&limit>=1u)))
                hidden_triples(game,(unsigned)(b?limit:5u),0);
            else if(strcmp(a,"hidden-pairs")==0&&
                    (!b||(!c&&!extra&&decimal(b,81u,&limit)&&limit>=1u)))
                hidden_pairs(game,(unsigned)(b?limit:5u),0);
            else if(strcmp(a,"locked")==0&&
                    (!b||(!c&&!extra&&decimal(b,81u,&limit)&&limit>=1u)))
                locked_candidates(game,(unsigned)(b?limit:5u),0);
            else if(strcmp(a,"x-wing")==0&&
                    (!b||(!c&&!extra&&decimal(b,81u,&limit)&&limit>=1u)))
                x_wings(game,(unsigned)(b?limit:5u),0);
            else if(strcmp(a,"swordfish")==0&&
                    (!b||(!c&&!extra&&decimal(b,81u,&limit)&&limit>=1u)))
                swordfish(game,(unsigned)(b?limit:5u),0);
            else if(strcmp(a,"trial")==0&&
                    (!b||(!c&&!extra&&decimal(b,81u,&limit)&&limit>=1u)))
                hint_trial(game,(unsigned)(b?limit:5u),0);
            else if(strcmp(a,"trial-forced")==0&&
                    (!b||(!c&&!extra&&decimal(b,81u,&limit)&&limit>=1u)))
                hint_trial_forced(game,(unsigned)(b?limit:5u),0);
            else if(strcmp(a,"apply")==0&&!b)print_hint(game,1);
            else if(strcmp(a,"chain")==0&&
                    (!b||(!c&&decimal(b,81u,&limit)&&limit>=1u)))
                hint_chain(game,0,(unsigned)limit);
            else if(strcmp(a,"apply")==0&&b&&
                    strcmp(b,"all")==0&&!c)
                apply_all_hints(game);
            else if(strcmp(a,"apply")==0&&b&&
                    strcmp(b,"pairs")==0&&
                    (!c||(!extra&&decimal(c,81u,&limit)&&limit>=1u)))
                naked_pairs(game,(unsigned)(c?limit:5u),1);
            else if(strcmp(a,"apply")==0&&b&&
                    strcmp(b,"triples")==0&&
                    (!c||(!extra&&decimal(c,81u,&limit)&&limit>=1u)))
                naked_triples(game,(unsigned)(c?limit:5u),1);
            else if(strcmp(a,"apply")==0&&b&&
                    strcmp(b,"hidden-triples")==0&&
                    (!c||(!extra&&decimal(c,81u,&limit)&&limit>=1u)))
                hidden_triples(game,(unsigned)(c?limit:5u),1);
            else if(strcmp(a,"apply")==0&&b&&
                    strcmp(b,"hidden-pairs")==0&&
                    (!c||(!extra&&decimal(c,81u,&limit)&&limit>=1u)))
                hidden_pairs(game,(unsigned)(c?limit:5u),1);
            else if(strcmp(a,"apply")==0&&b&&
                    strcmp(b,"locked")==0&&
                    (!c||(!extra&&decimal(c,81u,&limit)&&limit>=1u)))
                locked_candidates(game,(unsigned)(c?limit:5u),1);
            else if(strcmp(a,"apply")==0&&b&&
                    strcmp(b,"x-wing")==0&&
                    (!c||(!extra&&decimal(c,81u,&limit)&&limit>=1u)))
                x_wings(game,(unsigned)(c?limit:5u),1);
            else if(strcmp(a,"apply")==0&&b&&
                    strcmp(b,"swordfish")==0&&
                    (!c||(!extra&&decimal(c,81u,&limit)&&limit>=1u)))
                swordfish(game,(unsigned)(c?limit:5u),1);
            else if(strcmp(a,"apply")==0&&b&&
                    strcmp(b,"trial")==0&&
                    (!c||(!extra&&decimal(c,81u,&limit)&&limit>=1u)))
                hint_trial(game,(unsigned)(c?limit:5u),1);
            else if(strcmp(a,"apply")==0&&b&&
                    strcmp(b,"trial-forced")==0&&
                    (!c||(!extra&&decimal(c,81u,&limit)&&limit>=1u)))
                hint_trial_forced(game,(unsigned)(c?limit:5u),1);
            else if(strcmp(a,"apply")==0&&b&&
                    strcmp(b,"chain")==0&&
                    (!c||(!extra&&decimal(c,81u,&limit)&&limit>=1u)))
                hint_chain(game,1,(unsigned)limit);
            else puts("Error: unknown command or invalid arguments. Type 'help'.");
            continue;
        }
        if(strcmp(command,"export")==0&&
           (!a||((strcmp(a,"givens")==0||strcmp(a,"current")==0||
                   strcmp(a,"both")==0)&&!b))){
            if(!a||strcmp(a,"givens")==0)export_board(game,0);
            else if(strcmp(a,"current")==0)export_board(game,1);
            else{export_board(game,0);export_board(game,1);}
            continue;
        }
        if(strcmp(command,"analyze")==0){
            uint64_t limit=10u;
            if(!a||(!b&&decimal(a,SUDOKU_CELL_COUNT,&limit)&&limit>=1u))
                analyze_board(game,(unsigned)limit);
            else puts("Error: unknown command or invalid arguments. Type 'help'.");
            continue;
        }
        if(strcmp(command,"probe")==0){
            if(a&&strcmp(a,"compare")==0&&
               position(b,c,&r,&d)&&!extra)
                probe_compare(game,r,d);
            else if(position(a,b,&r,&d)&&c&&!extra&&
                    decimal(c,9u,&digit)&&digit>=1u)
                probe_placement(game,r,d,(unsigned)digit);
            else puts("Error: unknown command or invalid arguments. Type 'help'.");
            continue;
        }
        if(strcmp(command,"focus")==0){
            uint64_t limit=5u;
            if(!a||(!b&&decimal(a,SUDOKU_CELL_COUNT,&limit)&&limit>=1u))
                print_focus(game,(unsigned)limit);
            else puts("Error: unknown command or invalid arguments. Type 'help'.");
            continue;
        }
        if(strcmp(command,"show")==0){
            if(!a)display(game);
            else if(!b&&strcmp(a,"notes")==0)display_note_grid(game,0);
            else if(!b&&strcmp(a,"candidates")==0)display_note_grid(game,1);
            else if(!b&&strcmp(a,"heatmap")==0)show_candidate_map(game,0u);
            else if(b&&!c&&!extra&&strcmp(a,"digit")==0&&
                    decimal(b,9u,&digit)&&digit>=1u)
                show_candidate_map(game,(unsigned)digit);
            else puts("Error: unknown command or invalid arguments. Type 'help'.");
            continue;
        }
        if(strcmp(command,"history")==0){
            uint64_t requested=10u;
            if(!a)
                history_list(game,10u);
            else if(strcmp(a,"summary")==0&&!b&&!c&&!extra)
                history_summary(game);
            else if(strcmp(a,"hotspots")==0&&
                    (!b||(!c&&!extra&&decimal(b,SUDOKU_CELL_COUNT,&requested)&&requested>=1u)))
                history_hotspots(game,(unsigned)requested);
            else if(strcmp(a,"heatmap")==0&&!c&&!extra&&
                    (!b||strcmp(b,"all")==0||strcmp(b,"done")==0||strcmp(b,"redo")==0))
                history_heatmap(game,b?b:"all");
            else if(strcmp(a,"inspect")==0&&b&&!c&&!extra&&
                    decimal(b,SUDOKU_GAME_HISTORY-1u,&requested)&&requested>=1u)
                history_inspect(game,(unsigned)requested);
            else if(strcmp(a,"goto")==0&&b&&!c&&!extra&&
                    decimal(b,SUDOKU_GAME_HISTORY-1u,&requested)){
                SudokuGameStatus jumped=sudoku_game_history_goto(game,(unsigned)requested);
                if(jumped!=SUDOKU_GAME_OK)
                    printf("Error: %s\n",sudoku_game_status_text(jumped));
                else{
                    printf("History goto %u: cursor %u; undo %u; redo %u.\n",
                           (unsigned)requested,game->history_cursor,
                           game->history_cursor,
                           game->history_len-1u-game->history_cursor);
                    display(game);
                }
            }
            else if(strcmp(a,"diff")==0&&b&&c&&!extra){
                uint64_t to=0u;
                if(decimal(b,SUDOKU_GAME_HISTORY-1u,&requested)&&
                   decimal(c,SUDOKU_GAME_HISTORY-1u,&to))
                    history_diff(game,(unsigned)requested,(unsigned)to);
                else puts("Error: unknown command or invalid arguments. Type 'help'.");
            }
            else if(strcmp(a,"cell")==0&&b&&c&&!extra&&
                    position(b,c,&r,&d))
                history_cell(game,r,d);
            else if(!b&&!c&&!extra&&
                    decimal(a,SUDOKU_GAME_HISTORY-1u,&requested)&&requested>=1u)
                history_list(game,(unsigned)requested);
            else
                puts("Error: unknown command or invalid arguments. Type 'help'.");
            continue;
        }
        if(strcmp(command,"status")==0&&!a){
            printf("Progress: %u/81 filled, %u mistakes, elapsed %" PRIu64 "s, undo %u, redo %u\n",
                   81u-sudoku_game_empty(game),sudoku_game_mistakes(game),
                   sudoku_game_elapsed(game),game->history_cursor,
                   game->history_len-1u-game->history_cursor);
            if(sudoku_game_won(game))puts("SOLVED!");
            continue;
        }
        if(strcmp(command,"auto-notes")==0&&!a)status=sudoku_game_auto_notes(game);
        else if(strcmp(command,"prune-notes")==0&&!a)status=sudoku_game_prune_notes(game);
        else if(strcmp(command,"clear-notes")==0&&!a)status=sudoku_game_clear_notes(game);
        else if(strcmp(command,"undo")==0&&
                (!a||(!b&&decimal(a,SUDOKU_GAME_HISTORY-1u,&digit)&&digit>=1u)))
            status=sudoku_game_undo_steps(game,a?(unsigned)digit:1u);
        else if(strcmp(command,"redo")==0&&
                (!a||(!b&&decimal(a,SUDOKU_GAME_HISTORY-1u,&digit)&&digit>=1u)))
            status=sudoku_game_redo_steps(game,a?(unsigned)digit:1u);
        else if(strcmp(command,"reset")==0&&!a)status=sudoku_game_reset(game);
        else if(strcmp(command,"check")==0&&a&&
                strcmp(a,"clear")==0&&!b){
            unsigned incorrect=sudoku_game_mistakes(game);
            status=sudoku_game_clear_mistakes(game);
            if(status==SUDOKU_GAME_OK){
                if(incorrect)
                    printf("Cleared %u incorrect entries (undoable).\n",incorrect);
                else
                    puts("No incorrect entries to clear.");
            }
        }
        else if(strcmp(command,"check")==0&&
                (!a||(strcmp(a,"details")==0&&!b))){
            if(a)print_check_details(game);
            else if(sudoku_game_won(game))puts("SOLVED! All cells are correct.");
            else printf("Check: %u empty, %u incorrect.\n",
                        sudoku_game_empty(game),sudoku_game_mistakes(game));
            continue;
        }
        else if(strcmp(command,"notes")==0&&a&&strcmp(a,"audit")==0&&
                ((!b&&!c&&!extra)||
                 (b&&!c&&!extra&&decimal(b,81u,&digit)&&digit>=1u)||
                 (b&&c&&!extra&&
                  (strcmp(b,"row")==0||strcmp(b,"column")==0||
                   strcmp(b,"box")==0)&&decimal(c,9u,&digit)&&digit>=1u))){
            if(!b)audit_notes(game,10u,0u,0u);
            else if(!c)audit_notes(game,(unsigned)digit,0u,0u);
            else{
                unsigned scope=strcmp(b,"row")==0?1u:
                               strcmp(b,"column")==0?2u:3u;
                audit_notes(game,9u,scope,(unsigned)digit);
            }
            continue;
        }
        else if(strcmp(command,"notes")==0&&a&&
                strcmp(a,"batch")==0&&b&&strcmp(b,"preview")==0&&c&&
                (!extra||strcmp(c,"add")==0||strcmp(c,"remove")==0||
                 strcmp(c,"toggle")==0)){
            SudokuGameNoteEdit edits[SUDOKU_CELL_COUNT];
            unsigned count=0u;
            const char *spec=extra?extra:c;
            const char *mode=extra?c:"set";
            if(!parse_notes_batch(spec,edits,&count)){
                puts("Error: malformed notes batch. Use notes batch preview r1c3=19,r1c4=-.");
                continue;
            }
            preview_notes_batch(game,edits,count,mode);
            continue;
        }
        else if(strcmp(command,"notes")==0&&a&&
                strcmp(a,"batch")==0&&b&&!extra&&
                ((!c)||(c&&(strcmp(b,"add")==0||strcmp(b,"remove")==0||
                            strcmp(b,"toggle")==0)))){
            SudokuGameNoteEdit edits[SUDOKU_CELL_COUNT];
            unsigned count=0u,changed=0u;
            const char *spec=c?c:b;
            const char *mode=c?b:"set";
            if(!parse_notes_batch(spec,edits,&count)){
                puts("Error: malformed notes batch. Use notes batch r1c3=19,r1c4=-.");
                continue;
            }
            status=apply_notes_batch(game,edits,count,mode,&changed);
            if(status==SUDOKU_GAME_OK){
                if(changed)
                    printf("Batch %s notes in %u cell%s in one undoable edit.\n",
                           strcmp(mode,"set")==0?"updated":
                           strcmp(mode,"add")==0?"added":
                           strcmp(mode,"toggle")==0?"toggled":"removed",
                           changed,changed==1u?"":"s");
                else
                    puts("No note changes; history unchanged.");
            }
        }
        else if(strcmp(command,"notes")==0&&a&&
                (strcmp(a,"set")==0||strcmp(a,"add")==0||
                 strcmp(a,"remove")==0)&&position(b,c,&r,&d)&&extra){
            uint16_t mask=0u;
            if(!parse_note_digits(extra,&mask)){
                puts("Error: invalid note digits; use 1..9 once each, or '-'.");
                continue;
            }
            if(strcmp(a,"set")==0)status=sudoku_game_set_notes(game,r,d,mask);
            else if(strcmp(a,"add")==0)status=sudoku_game_add_notes(game,r,d,mask);
            else status=sudoku_game_remove_notes(game,r,d,mask);
        }
        else if(strcmp(command,"notes")==0&&a&&strcmp(a,"clear")==0&&
                position(b,c,&r,&d)&&!extra)
            status=sudoku_game_set_notes(game,r,d,0u);
        else if(strcmp(command,"notes")==0&&a&&
                (strcmp(a,"fill")==0||strcmp(a,"prune")==0)&&
                position(b,c,&r,&d)&&!extra)
            status=strcmp(a,"fill")==0 ?
                   sudoku_game_fill_cell_notes(game,r,d) :
                   sudoku_game_prune_cell_notes(game,r,d);
        else if(strcmp(command,"notes")==0&&a&&
                (strcmp(a,"fill")==0||strcmp(a,"prune")==0)&&
                b&&c&&!extra&&
                (strcmp(b,"row")==0||strcmp(b,"column")==0||
                 strcmp(b,"box")==0)&&decimal(c,9u,&digit)&&digit>=1u){
            SudokuGameUnit unit=strcmp(b,"row")==0?SUDOKU_GAME_ROW:
                                strcmp(b,"column")==0?SUDOKU_GAME_COLUMN:
                                SUDOKU_GAME_BOX;
            status=strcmp(a,"fill")==0?
                   sudoku_game_fill_unit_notes(game,unit,(unsigned)digit):
                   sudoku_game_prune_unit_notes(game,unit,(unsigned)digit);
        }
        else if(strcmp(command,"notes")==0&&position(a,b,&r,&d)&&!c&&!extra){
            print_notes(game,r,d);
            continue;
        }
        else if(strcmp(command,"candidates")==0&&position(a,b,&r,&d)&&!c){
            print_candidates(game,r,d);continue;
        }
        else if(strcmp(command,"set")==0&&a&&strcmp(a,"batch")==0&&
                b&&c&&!extra&&
                (strcmp(b,"check")==0||strcmp(b,"safe")==0)){
            SudokuGameMove moves[SUDOKU_CELL_COUNT];
            unsigned count=0u,applied=0u;
            if(!parse_batch_moves(c,moves,&count)){
                puts("Error: malformed batch. Use set batch safe r1c3=4,r1c4=6.");
                continue;
            }
            status=batch_check(game,moves,count);
            if(status==SUDOKU_GAME_OK&&strcmp(b,"safe")==0){
                status=sudoku_game_set_many(game,moves,count,&applied);
                if(status==SUDOKU_GAME_OK)
                    printf("Safe batch placed %u digit%s in one undoable edit.\n",
                           applied,applied==1u?"":"s");
            }
            if(status!=SUDOKU_GAME_OK)
                printf("Error: %s\n",sudoku_game_status_text(status));
            else if(strcmp(b,"safe")==0)
                display(game);
            continue;
        }
        else if(strcmp(command,"set")==0&&a&&strcmp(a,"batch")==0&&
                b&&!c&&!extra){
            SudokuGameMove moves[SUDOKU_CELL_COUNT];
            unsigned count=0u,applied=0u;
            if(!parse_batch_moves(b,moves,&count)){
                puts("Error: malformed batch. Use set batch r1c3=4,r1c4=6.");
                continue;
            }
            status=sudoku_game_set_many(game,moves,count,&applied);
            if(status==SUDOKU_GAME_OK)
                printf("Batch placed %u digit%s in one undoable edit.\n",
                       applied,applied==1u?"":"s");
        }
        else if(strcmp(command,"set")==0&&a&&strcmp(a,"safe")==0&&
                position(b,c,&r,&d)&&extra&&
                decimal(extra,9u,&digit)&&digit>=1u)
            status=set_safe(game,r,d,(unsigned)digit);
        else if(strcmp(command,"set")==0&&a&&strcmp(a,"proven")==0&&
                position(b,c,&r,&d)&&extra&&
                decimal(extra,9u,&digit)&&digit>=1u)
            status=set_proven(game,r,d,(unsigned)digit);
        else if(strcmp(command,"set")==0&&position(a,b,&r,&d)&&c&&!extra&&
                decimal(c,9u,&digit)&&digit>=1u)
            status=sudoku_game_set(game,r,d,(unsigned)digit);
        else if(strcmp(command,"erase")==0&&a&&
                strcmp(a,"batch")==0&&b&&!c&&!extra){
            SudokuGameCell cells[SUDOKU_CELL_COUNT];
            unsigned count=0u,cleared=0u;
            if(!parse_erase_batch(b,cells,&count)){
                puts("Error: malformed erase batch. Use erase batch r1c3,r1c4.");
                continue;
            }
            status=sudoku_game_erase_many(game,cells,count,&cleared);
            if(status==SUDOKU_GAME_OK){
                if(cleared)
                    printf("Batch erased %u cell%s in one undoable edit.\n",
                           cleared,cleared==1u?"":"s");
                else
                    puts("No cells to erase; history unchanged.");
            }
        }
        else if(strcmp(command,"erase")==0&&a&&b&&!c&&!extra&&
                (strcmp(a,"row")==0||strcmp(a,"column")==0||
                 strcmp(a,"box")==0)&&
                decimal(b,9u,&digit)&&digit>=1u){
            SudokuGameCell cells[9];
            unsigned count=erase_unit_targets(game,a,(unsigned)digit,cells);
            unsigned cleared=0u;
            status=sudoku_game_erase_many(game,cells,count,&cleared);
            if(status==SUDOKU_GAME_OK){
                if(cleared)
                    printf("Erased %u cell%s from %s %u in one undoable edit.\n",
                           cleared,cleared==1u?"":"s",a,(unsigned)digit);
                else
                    printf("No editable changes in %s %u; history unchanged.\n",
                           a,(unsigned)digit);
            }
        }
        else if(strcmp(command,"erase")==0&&position(a,b,&r,&d)&&!c)
            status=sudoku_game_erase(game,r,d);
        else if(strcmp(command,"note")==0&&position(a,b,&r,&d)&&c&&!extra&&decimal(c,9,&digit)&&digit>=1u)
            status=sudoku_game_note(game,r,d,(unsigned)digit);
        else{puts("Error: unknown command or invalid arguments. Type 'help'.");continue;}
        if(status!=SUDOKU_GAME_OK){printf("Error: %s\n",sudoku_game_status_text(status));continue;}
        display(game);
    }
    puts("End of input. Progress is only persisted if you used 'save'.");
    return 0;
}
int sudoku_play_main(int argc,char **argv){
    PlayOptions opt={0};
    if(argc==3 && strcmp(argv[2],"--help")==0){
        puts("Usage: sudoku play (--puzzle DIGITS | --file PATH | --resume SAVE | --seed UINT32 --difficulty easy|medium|hard) [--symmetry none|rotational] [--save PATH]");
        commands();
        return 0;
    }
    SudokuGame *game;
    int status=parse(argc,argv,&opt);
    if(status)return status;
    game=malloc(sizeof *game);
    if(!game){fputs("Out of memory\n",stderr);return 4;}
    status=start(&opt,game);
    if(status==0){commands();status=event_loop(game,&opt);}
    free(game);
    return status;
}
