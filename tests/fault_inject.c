/* Test-only Linux LD_PRELOAD interposer. It is NEVER linked into Sudoku.
 * Inject file-fsync, directory-fsync and rename failures deterministically.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

int fsync(int fd) {
    const char *fault = getenv("SUDOKU_TEST_FAULT");
    struct stat st;
    if (fault != NULL && fstat(fd, &st) == 0 &&
        ((strcmp(fault, "file-sync") == 0 && S_ISREG(st.st_mode)) ||
         (strcmp(fault, "dir-sync") == 0 && S_ISDIR(st.st_mode)))) {
        errno = EIO;
        return -1;
    }
    return (int)syscall(SYS_fsync, fd);
}

int rename(const char *source, const char *target) {
    const char *fault = getenv("SUDOKU_TEST_FAULT");
    if (fault != NULL && strcmp(fault, "rename") == 0) {
        errno = EIO;
        return -1;
    }
    return renameat(AT_FDCWD, source, AT_FDCWD, target);
}
