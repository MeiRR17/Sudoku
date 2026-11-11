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
    puts("          notes ROW COL, candidates ROW COL, auto-notes, prune-notes,");
    puts("          clear-notes, hint [apply], undo, redo, reset, check [details|clear],");
    puts("          status, save [PATH], help, quit");
    puts("Coordinates and digits are 1..9; original clues are immutable.");
    puts("'note' toggles pencil marks; 'candidates' lists legal digits without guessing.");
    puts("'auto-notes' fills all legal marks; 'prune-notes' removes only illegal marks.");
    puts("'hint' finds a forced single; 'hint apply' places it as an undoable move.");
    puts("'check details' locates wrong entries; 'check clear' erases them (undoable).");
    puts("No color, network or special keys required.");
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
static int puzzle_file(const char *path,SudokuBoard *board){
    /* Never reserve >1 MiB on the call stack (notably Windows' default stack).
     * One extra byte still distinguishes an oversized file from the limit. */
    const size_t capacity = (size_t)SUDOKU_MAX_INPUT_BYTES + 1u;
    unsigned char *bytes;
    SudokuError error;
    size_t n;
    SudokuStatus valid;
    FILE *f=fopen(path,"rb");
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
typedef struct LogicalHint {
    unsigned index, digit, group;
    int hidden;
} LogicalHint;
/* Naked singles first; if none exist, scan for a hidden single in a
 * row, column or 3x3 box. Never look up the completed solution. */
static int find_hint(const SudokuGame *game,LogicalHint *hint){
    uint16_t masks[SUDOKU_CELL_COUNT]={0};
    unsigned i,d,group,slot,count,chosen;
    for(i=0u;i<SUDOKU_CELL_COUNT;++i){
        masks[i]=candidate_mask(game,i);
        d=single_candidate(masks[i]);
        if(d){
            hint->index=i;
            hint->digit=d;
            hint->group=0u;
            hint->hidden=0;
            return 1;
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
            if(count==1u){
                hint->index=chosen;
                hint->digit=d;
                hint->group=group;
                hint->hidden=1;
                return 1;
            }
        }
    }
    return 0;
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
static int event_loop(SudokuGame *game,PlayOptions *opt){
    char line[4096 + 32];
    char last_save_path[4097];
    display(game);
    while(fgets(line,sizeof line,stdin)){
        char *command,*a,*b,*c,*extra;
        unsigned r,d;uint64_t digit;
        SudokuGameStatus status=SUDOKU_GAME_OK;
        size_t len=strlen(line);
        if(len==sizeof line-1u && line[len-1u]!='\n' && !feof(stdin)){
            int ch;
            while((ch=fgetc(stdin))!='\n'&&ch!=EOF){}
            puts("Error: command too long");continue;
        }
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
        if(strcmp(command,"hint")==0&&
           (!a||(strcmp(a,"apply")==0&&!b))){
            print_hint(game,a!=NULL);continue;
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
        else if(strcmp(command,"undo")==0&&!a)status=sudoku_game_undo(game);
        else if(strcmp(command,"redo")==0&&!a)status=sudoku_game_redo(game);
        else if(strcmp(command,"reset")==0&&!a)status=sudoku_game_reset(game);
        else if(strcmp(command,"check")==0&&a&&
                strcmp(a,"clear")==0&&!b)
            status=sudoku_game_clear_mistakes(game);
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
    if(ferror(stdin)){fputs("Game input read failed\n",stderr);return 4;}
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
