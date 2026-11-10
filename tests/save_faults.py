"""Linux-only save persistence fault-injection E2E.

LD_PRELOAD interposes fchmod/fsync/rename/link. Tests document the distinction between
pre-commit failures (old save preserved) and post-rename dir-sync failure
(target replaced, durability unconfirmed). Does not simulate real power loss.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

EXE = Path(sys.argv[1]).resolve()
INTERPOSER = Path(sys.argv[2]).resolve()
CC = sys.argv[3]
SOLUTION = '534678912672195348198342567859761423426853791713924856961537284287419635345286179'
PUZZLE = '0' + SOLUTION[1:]
checks = 0


def play(target, commands, fault=None, library=None):
    global checks
    env = os.environ.copy()
    if fault is not None:
        env['LD_PRELOAD'] = str(library)
        env['SUDOKU_TEST_FAULT'] = fault
    else:
        env.pop('SUDOKU_TEST_FAULT', None)
    result = subprocess.run([str(EXE), 'play', '--puzzle', PUZZLE, '--save', str(target)],
                            input=commands, text=True, capture_output=True, env=env,
                            timeout=15)
    assert result.returncode == 0, (fault, result.returncode, result.stderr)
    assert not result.stderr, result.stderr
    checks += 1
    return result.stdout


with tempfile.TemporaryDirectory(prefix='sudoku-fault-') as directory:
    root = Path(directory)
    library = root / 'libsave_fault.so'
    subprocess.run([CC, '-std=c11', '-shared', '-fPIC', '-O0', str(INTERPOSER),
                    '-o', str(library)], check=True, capture_output=True, text=True)
    save = root / 'game with spaces.save'
    assert 'Saved to' in play(save, 'save\nquit\n')
    before = save.read_bytes()
    assert before.startswith(b'SUDOKU_SAVE_V1\n')
    checks += 1

    for fault in ('file-mode', 'file-sync', 'rename'):
        output = play(save, 'set 1 1 5\nsave\nquit\n', fault, library)
        assert 'Error: file operation failed' in output, (fault, output)
        assert save.read_bytes() == before, 'previous valid game was modified on pre-rename failure'
        assert not list(root.glob(save.name + '.tmp.*')), 'temporary file leaked'
        checks += 1

    # The target is replaced before the parent-directory fsync; if fsync fails,
    # distinguish this from a failed rename rather than promising old data.
    output = play(save, 'set 1 1 5\nsave\nquit\n', 'dir-sync', library)
    assert 'Warning: save replaced target, but parent directory sync failed' in output
    assert 'Error: file operation failed' not in output
    assert save.read_bytes() != before
    assert not list(root.glob(save.name + '.tmp.*'))
    checks += 1

    # When explicit save replaces a target but directory sync fails, it must
    # still become the default so the next bare 'save' never fails for no path.
    manual = root / 'manual save with spaces.save'
    env = os.environ.copy()
    env['LD_PRELOAD'] = str(library)
    env['SUDOKU_TEST_FAULT'] = 'dir-sync'
    manual_run = subprocess.run([str(EXE), 'play', '--puzzle', PUZZLE],
                                input=f'save {manual}\nsave\nquit\n',
                                text=True, capture_output=True, env=env, timeout=15)
    assert manual_run.returncode == 0 and not manual_run.stderr
    assert manual_run.stdout.count('Warning: save replaced target') == 2
    assert manual.is_file() and not list(root.glob(manual.name + '.tmp.*'))
    checks += 1

    # Verify the staging inode is already 0600 *before* its fchmod call,
    # including under umask(000). This catches the old fopen("wbx") race.
    born_private = root / 'private from birth.save'
    previous_umask = os.umask(0)
    try:
        output = play(born_private, 'save\nquit\n', 'check-created-mode', library)
    finally:
        os.umask(previous_umask)
    assert 'Saved to' in output and born_private.exists()
    assert (born_private.stat().st_mode & 0o777) == 0o600
    assert not list(root.glob(born_private.name + '.tmp.*'))
    checks += 1

    # CLI results must not publish a partial *final* output on staged
    # permission, file fsync or link-publication failure. No stale temp leaks.
    for fault in ('file-mode', 'file-sync', 'publish-link'):
        result_path = root / ('cli-' + fault + '.txt')
        env = os.environ.copy()
        env['LD_PRELOAD'] = str(library)
        env['SUDOKU_TEST_FAULT'] = fault
        result = subprocess.run([str(EXE), 'solve', '--puzzle', PUZZLE,
                                 '--format', 'compact', '--output', str(result_path)],
                                capture_output=True, text=True, env=env, timeout=15)
        assert result.returncode == 4, (fault, result.returncode, result.stderr)
        assert result.stdout == '' and 'Output ' in result.stderr
        assert not result_path.exists(), 'failed CLI output published incomplete result'
        assert not list(root.glob(result_path.name + '.tmp.*')), 'CLI staging file leaked'
        checks += 1

    resume = subprocess.run([str(EXE), 'play', '--resume', str(save)], input='status\nquit\n',
                            text=True, capture_output=True, timeout=15)
    assert resume.returncode == 0 and 'SOLVED!' in resume.stdout
    checks += 1
    # Successful re-save performs a clean metadata sync and retains a valid game.
    assert 'Saved to' in play(save, 'set 1 1 5\nsave\nquit\n')
    assert not list(root.glob(save.name + '.tmp.*'))
    checks += 1

print(f'SAVE FAULT E2E PASS: {checks} checks (pre-rename preservation, post-rename uncertainty, atomic CLI output failure, clean resume)')
