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
    puts("          notes ROW COL, undo, redo, reset, check, status,");
    puts("          save [PATH], help, quit");
    puts("Coordinates and digits are 1..9; original clues are immutable.");
    puts("'note' toggles pencil candidates. No color, network or special keys required.");
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
    unsigned char bytes[SUDOKU_MAX_INPUT_BYTES+1u];
    SudokuError error;
    size_t n;
    SudokuStatus valid;
    FILE *f=fopen(path,"rb");
    if(!f){fprintf(stderr,"Puzzle open failed: %s\n",strerror(errno));return 4;}
    n=fread(bytes,1u,sizeof bytes,f);
    if(ferror(f)){fclose(f);fputs("Puzzle read failed\n",stderr);return 4;}
    if(fclose(f)!=0){fputs("Puzzle close failed\n",stderr);return 4;}
    valid=sudoku_board_parse(board,bytes,n,&error);
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
static int event_loop(SudokuGame *game,PlayOptions *opt){
    char line[256];
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
        if(strcmp(command,"show")==0&&!a){display(game);continue;}
        if(strcmp(command,"status")==0&&!a){
            printf("Progress: %u/81 filled, %u mistakes, elapsed %" PRIu64 "s, undo %u, redo %u\n",
                   81u-sudoku_game_empty(game),sudoku_game_mistakes(game),
                   sudoku_game_elapsed(game),game->history_cursor,
                   game->history_len-1u-game->history_cursor);
            if(sudoku_game_won(game))puts("SOLVED!");
            continue;
        }
        if(strcmp(command,"save")==0&&!b){
            const char *path=a?a:opt->save;
            if(!path){puts("Error: supply a path, e.g. save puzzle.save");continue;}
            if(strlen(path)>4096u){puts("Error: save path too long");continue;}
            status=sudoku_game_save(game,path);
            if(status!=SUDOKU_GAME_OK)printf("Error: %s\n",sudoku_game_status_text(status));
            else{
                /* Paths extracted by strtok point into reused input line. */
                if(a){
                    if(strlen(path)>4096u){puts("Error: save path too long");continue;}
                    (void)strcpy(last_save_path,path);
                    opt->save=last_save_path;
                }
                printf("Saved to %s (version 1, checksummed, atomic replace).\n",path);
            }
            continue;
        }
        if(strcmp(command,"undo")==0&&!a)status=sudoku_game_undo(game);
        else if(strcmp(command,"redo")==0&&!a)status=sudoku_game_redo(game);
        else if(strcmp(command,"reset")==0&&!a)status=sudoku_game_reset(game);
        else if(strcmp(command,"check")==0&&!a){
            if(sudoku_game_won(game))puts("SOLVED! All cells are correct.");
            else printf("Check: %u empty, %u incorrect.\n",sudoku_game_empty(game),sudoku_game_mistakes(game));
            continue;
        }
        else if(strcmp(command,"notes")==0&&position(a,b,&r,&d)&&!c){print_notes(game,r,d);continue;}
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
