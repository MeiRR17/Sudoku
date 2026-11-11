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
static void commands(void){
    puts("Commands: show, set ROW COL DIGIT, erase ROW COL, note ROW COL DIGIT,");
    puts("          notes ROW COL, candidates ROW COL, focus [N], auto-notes, prune-notes,");
    puts("          clear-notes, hint [all|pairs [N]|hidden-pairs [N]|locked [N]|chain [N]],");
    puts("          hint apply [all|pairs [N]|hidden-pairs [N]|locked [N]|chain [N]],");
    puts("          undo [N], redo [N], reset, check [details|clear],");
    puts("          export [givens|current|both], status, save [PATH], help, quit");
    puts("'export' prints copyable 81-digit original clues; 'export current'");
    puts("prints entered digits too; neither is a full save or stored solution.");
    puts("Coordinates and digits are 1..9; original clues are immutable.");
    puts("'note' toggles pencil marks; 'candidates' lists legal digits without guessing.");
    puts("'focus [N]' ranks empty cells by fewest legal candidates (default 5).");
    puts("'auto-notes' fills all legal marks; 'prune-notes' removes only illegal marks.");
    puts("'hint' shows one forced single; 'hint all' lists each distinct forced cell.");
    puts("'hint pairs [N]' previews actionable naked pairs (default 5).");
    puts("'hint apply pairs [N]' removes matching pencil marks in one undo.");
    puts("'hint hidden-pairs [N]' previews pairs hidden among more candidates.");
    puts("'hint apply hidden-pairs [N]' prunes those extra notes in one undo.");
    puts("'hint locked [N]' previews pointing/claiming candidate eliminations.");
    puts("'hint apply locked [N]' prunes those pencil notes in one undo.");
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
    int ch, seen = 0, too_long = 0, nul = 0;
    if (capacity == 0u) return -1;
    while ((ch = fgetc(stdin)) != EOF) {
        seen = 1;
        if (ch == '\n') break;
        if (ch == '\0') nul = 1;
        if (used + 1u < capacity) line[used++] = (char)ch;
        else too_long = 1;
    }
    if (ferror(stdin)) return -1;
    if (!seen && ch == EOF) return 0;
    line[used] = '\0';
    if (too_long) {
        puts("Error: command too long");
        return 2;
    }
    if (nul) {
        puts("Error: command contains a NUL byte");
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
        char *command,*a,*b,*c,*extra;
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
            else if(strcmp(a,"hidden-pairs")==0&&
                    (!b||(!c&&!extra&&decimal(b,81u,&limit)&&limit>=1u)))
                hidden_pairs(game,(unsigned)(b?limit:5u),0);
            else if(strcmp(a,"locked")==0&&
                    (!b||(!c&&!extra&&decimal(b,81u,&limit)&&limit>=1u)))
                locked_candidates(game,(unsigned)(b?limit:5u),0);
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
                    strcmp(b,"hidden-pairs")==0&&
                    (!c||(!extra&&decimal(c,81u,&limit)&&limit>=1u)))
                hidden_pairs(game,(unsigned)(c?limit:5u),1);
            else if(strcmp(a,"apply")==0&&b&&
                    strcmp(b,"locked")==0&&
                    (!c||(!extra&&decimal(c,81u,&limit)&&limit>=1u)))
                locked_candidates(game,(unsigned)(c?limit:5u),1);
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
        if(strcmp(command,"focus")==0){
            uint64_t limit=5u;
            if(!a||(!b&&decimal(a,SUDOKU_CELL_COUNT,&limit)&&limit>=1u))
                print_focus(game,(unsigned)limit);
            else puts("Error: unknown command or invalid arguments. Type 'help'.");
            continue;
        }
        if(strcmp(command,"show")==0&&!a){display(game);continue;}
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
        else if(strcmp(command,"notes")==0&&position(a,b,&r,&d)&&!c){print_notes(game,r,d);continue;}
        else if(strcmp(command,"candidates")==0&&position(a,b,&r,&d)&&!c){
            print_candidates(game,r,d);continue;
        }
        else if(strcmp(command,"set")==0&&position(a,b,&r,&d)&&c&&!extra&&decimal(c,9,&digit)&&digit>=1u)
            status=sudoku_game_set(game,r,d,(unsigned)digit);
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
