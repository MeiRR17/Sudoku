/* Test-only Linux LD_PRELOAD interposer. It is NEVER linked into Sudoku.
 * Inject mode/fsync/rename/link faults and check private mode at birth.
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

/* A successfully written CLI --output stage must never be installed if the
 * no-overwrite publication fails. Game saves use rename, not link. */
int link(const char *source, const char *target) {
    const char *fault = getenv("SUDOKU_TEST_FAULT");
    if (fault != NULL && strcmp(fault, "publish-link") == 0) {
        errno = EIO;
        return -1;
    }
    return (int)syscall(SYS_linkat, AT_FDCWD, source, AT_FDCWD, target, 0);
}

/* Mode-setting must happen before the save is written or renamed. Test-only
 * syscall delegation avoids recursion through the interposed libc symbol. */
int fchmod(int fd, mode_t mode) {
    const char *fault = getenv("SUDOKU_TEST_FAULT");
    struct stat st;
    if (fault != NULL && fstat(fd, &st) == 0 && S_ISREG(st.st_mode)) {
        if (strcmp(fault, "file-mode") == 0 ||
            (strcmp(fault, "check-created-mode") == 0 &&
             (st.st_mode & 0777u) != 0600u)) {
            errno = EPERM;
            return -1;
        }
    }
    return (int)syscall(SYS_fchmod, fd, mode);
}
