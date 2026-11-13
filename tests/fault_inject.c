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

/* Linux-only test shim: inject an atomic stage-create failure.
 * mkostemp implements the same six-X filename substitution and mode 0600,
 * without calling our interposed mkstemp again. Production uses mkstemp. */
int mkstemp(char *pattern) {
    const char *fault = getenv("SUDOKU_TEST_FAULT");
    if (fault != NULL && strcmp(fault, "stage-create") == 0) {
        errno = EACCES;
        return -1;
    }
    return mkostemp(pattern, 0);
}

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
    int result;
    if (fault != NULL && strcmp(fault, "rename") == 0) {
        errno = EIO;
        return -1;
    }
    result = renameat(AT_FDCWD, source, AT_FDCWD, target);
    if (result == 0 && fault != NULL &&
        (strcmp(fault, "parent-fifo-after-rename") == 0 ||
         strcmp(fault, "parent-directory-after-rename") == 0)) {
        /* Simulate a concurrent path replacement after the save was installed
         * but before the game opens its parent for metadata fsync. This
         * intentionally leaves the old directory under .displaced so the
         * Python test can verify it and restore the path after the child. */
        char parent[4160], displaced[4192];
        const char *slash = strrchr(target, '/');
        size_t count;
        int written;
        if (!slash || slash == target) { errno = EINVAL; return -1; }
        count = (size_t)(slash - target);
        if (count >= sizeof parent) { errno = ENAMETOOLONG; return -1; }
        memcpy(parent, target, count);
        parent[count] = '\0';
        written = snprintf(displaced, sizeof displaced, "%s.displaced", parent);
        if (written < 0 || (size_t)written >= sizeof displaced) {
            errno = ENAMETOOLONG;
            return -1;
        }
        if (renameat(AT_FDCWD, parent, AT_FDCWD, displaced) != 0)
            return -1;
        if (strcmp(fault, "parent-directory-after-rename") == 0) {
            if (mkdir(parent, 0700) != 0) return -1;
        } else if (mkfifo(parent, 0600) != 0) {
            return -1;
        }
    }
    return result;
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
