/* Windows-only save staging concurrency regression.
 * Threads race to save one complete game to the same destination. The
 * stage filename counter must be atomic, per-process and fail-closed; the
 * final file must remain valid and no stage files may survive. */
#include "sudoku/game.h"
#include "sudoku/board.h"
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define THREADS 12u
#define SAVES_PER_THREAD 8u
#define CHECK(expr) do { if (!(expr)) { \
    fprintf(stderr, "Windows save concurrency failed at line %d: %s\n", \
            __LINE__, #expr); return 1; \
} } while (0)

static const char solution[] =
    "534678912672195348198342567859761423426853791713924856"
    "961537284287419635345286179";
static const char save_path[] = "sudoku-windows-concurrent.save";

typedef struct Shared {
    const SudokuGame *game;
    HANDLE start;
    volatile LONG ok;
    volatile LONG io;
    volatile LONG bad;
} Shared;

static DWORD WINAPI run_save(LPVOID opaque) {
    Shared *shared = (Shared *)opaque;
    unsigned attempt;
    if (WaitForSingleObject(shared->start, 30000u) != WAIT_OBJECT_0) {
        (void)InterlockedIncrement(&shared->bad);
        return 1u;
    }
    for (attempt = 0u; attempt < SAVES_PER_THREAD; ++attempt) {
        SudokuGameStatus status = sudoku_game_save(shared->game, save_path);
        if (status == SUDOKU_GAME_OK)
            (void)InterlockedIncrement(&shared->ok);
        else if (status == SUDOKU_GAME_IO)
            (void)InterlockedIncrement(&shared->io);
        else
            (void)InterlockedIncrement(&shared->bad);
    }
    return 0u;
}

int main(void) {
    char puzzle[82];
    SudokuBoard board;
    SudokuGame *game = malloc(sizeof *game);
    SudokuGame *loaded = malloc(sizeof *loaded);
    Shared shared = {0};
    HANDLE threads[THREADS] = {0};
    WIN32_FIND_DATAA found;
    HANDLE search;
    unsigned i;
    CHECK(game && loaded);
    (void)remove(save_path);
    (void)memcpy(puzzle, solution, sizeof solution);
    puzzle[0] = '0';
    CHECK(sudoku_board_parse(&board, (const unsigned char *)puzzle, 81u, NULL)
          == SUDOKU_OK);
    CHECK(sudoku_game_start(game, &board) == SUDOKU_GAME_OK);
    CHECK(sudoku_game_set(game, 1u, 1u, 5u) == SUDOKU_GAME_OK);
    CHECK(sudoku_game_won(game));

    shared.game = game;
    shared.start = CreateEventA(NULL, TRUE, FALSE, NULL);
    CHECK(shared.start != NULL);
    for (i = 0u; i < THREADS; ++i) {
        threads[i] = CreateThread(NULL, 0u, run_save, &shared, 0u, NULL);
        CHECK(threads[i] != NULL);
    }
    CHECK(SetEvent(shared.start) != 0);
    CHECK(WaitForMultipleObjects(THREADS, threads, TRUE, 30000u) == WAIT_OBJECT_0);
    for (i = 0u; i < THREADS; ++i) CHECK(CloseHandle(threads[i]) != 0);
    CHECK(CloseHandle(shared.start) != 0);
    CHECK(shared.bad == 0);
    CHECK(shared.ok + shared.io == (LONG)(THREADS * SAVES_PER_THREAD));
    CHECK(shared.ok > 0);
    CHECK(sudoku_game_load(loaded, save_path) == SUDOKU_GAME_OK);
    CHECK(sudoku_game_won(loaded));
    search = FindFirstFileA("sudoku-windows-concurrent.save.tmp.*", &found);
    if (search != INVALID_HANDLE_VALUE) {
        (void)FindClose(search);
        fprintf(stderr, "Temporary staging file leaked\n");
        return 1;
    }
    CHECK(GetLastError() == ERROR_FILE_NOT_FOUND);
    CHECK(remove(save_path) == 0);
    free(loaded);
    free(game);
    puts("WINDOWS SAVE CONCURRENCY PASS: atomic staging, valid replacement, no leaked files");
    return 0;
}
