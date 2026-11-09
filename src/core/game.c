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
SudokuGameStatus sudoku_game_erase(SudokuGame *game, unsigned row, unsigned col) {
    int idx = cell_index(row, col);
    if (!valid_game(game)) return SUDOKU_GAME_INVALID;
    if (idx < 0) return SUDOKU_GAME_RANGE;
    if (game->givens.cells[idx]) return SUDOKU_GAME_GIVEN;
    if (game->state.board.cells[idx] == 0u) return SUDOKU_GAME_OK;
    game->state.board.cells[idx] = 0;
    remember(game);
    return SUDOKU_GAME_OK;
}
SudokuGameStatus sudoku_game_note(SudokuGame *game, unsigned row, unsigned col, unsigned digit) {
    int idx = cell_index(row, col);
    if (!valid_game(game)) return SUDOKU_GAME_INVALID;
    if (idx < 0 || digit < 1u || digit > 9u) return SUDOKU_GAME_RANGE;
    if (game->givens.cells[idx]) return SUDOKU_GAME_GIVEN;
    if (game->state.board.cells[idx]) return SUDOKU_GAME_NOT_EMPTY;
    game->state.notes[idx] ^= (uint16_t)(1u << digit);
    remember(game);
    return SUDOKU_GAME_OK;
}
SudokuGameStatus sudoku_game_undo(SudokuGame *game) {
    if (!valid_game(game)) return SUDOKU_GAME_INVALID;
    if (game->history_cursor == 0u) return SUDOKU_GAME_NO_HISTORY;
    game->state = game->history[--game->history_cursor];
    return SUDOKU_GAME_OK;
}
SudokuGameStatus sudoku_game_redo(SudokuGame *game) {
    if (!valid_game(game)) return SUDOKU_GAME_INVALID;
    if (game->history_cursor + 1u == game->history_len) return SUDOKU_GAME_NO_HISTORY;
    game->state = game->history[++game->history_cursor];
    return SUDOKU_GAME_OK;
}
SudokuGameStatus sudoku_game_reset(SudokuGame *game) {
    SudokuGameSnapshot cleared = {0};
    if (!valid_game(game)) return SUDOKU_GAME_INVALID;
    cleared.board = game->givens;
    if (memcmp(&cleared, &game->state, sizeof cleared) == 0) return SUDOKU_GAME_OK;
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
    secs = game->elapsed_base;
    if (now != (time_t)-1 && game->session_start != (time_t)-1 && now > game->session_start) {
        uint64_t delta = (uint64_t)(now - game->session_start);
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
    uint64_t elapsed;
    int n, tail;
    unsigned i;
    if (!valid_game(game)) return 0;
    sudoku_board_compact(&game->givens, givens);
    sudoku_board_compact(&game->state.board, current);
    for (i=0;i<81u;++i) {
        unsigned note = game->state.notes[i];
        if(note > 0x3feu || (note & 1u)) return 0;
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
SudokuGameStatus sudoku_game_save(const SudokuGame *game, const char *path) {
    static unsigned serial=0;
    char bytes[SUDOKU_SAVE_MAX_BYTES];
    char *temp;
    size_t n,len;
    FILE *file=NULL;
    unsigned attempt;
    int ok;
    if(!valid_game(game)||!path||!*path)return SUDOKU_GAME_INVALID;
    if(!render_save(game,bytes,&n))return SUDOKU_GAME_INVALID;
    len=strlen(path);
    if(len>4096u)return SUDOKU_GAME_IO;
    temp=malloc(len+64u);
    if(!temp)return SUDOKU_GAME_IO;
    for(attempt=0;attempt<64u;++attempt){
        unsigned id=++serial;
        (void)snprintf(temp,len+64u,"%s.tmp.%08lX.%08X",path,
                       (unsigned long)time(NULL),id);
        file=fopen(temp,"wbx");
        if(file)break;
        if(errno!=EEXIST){ free(temp);return SUDOKU_GAME_IO; }
    }
    if(!file){free(temp);return SUDOKU_GAME_IO;}
    ok=fwrite(bytes,1u,n,file)==n;
    if(ok)ok=fflush(file)==0;
#if defined(_WIN32)
    if(ok)ok=_commit(_fileno(file))==0;
#else
    if(ok)ok=fsync(fileno(file))==0;
#endif
    if(fclose(file)!=0)ok=0;
    if(ok){
#if defined(_WIN32)
        ok=MoveFileExA(temp,path,MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)!=0;
#else
        ok=rename(temp,path)==0;
#endif
    }
    if(!ok)(void)remove(temp);
    free(temp);
    return ok?SUDOKU_GAME_OK:SUDOKU_GAME_IO;
}
SudokuGameStatus sudoku_game_load(SudokuGame *game, const char *path) {
    char bytes[SUDOKU_SAVE_MAX_BYTES+1u];
    size_t n;
    FILE *file;
    SudokuGame *candidate;
    if(!game||!path||!*path)return SUDOKU_GAME_INVALID;
    file=fopen(path,"rb");
    if(!file)return SUDOKU_GAME_IO;
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
