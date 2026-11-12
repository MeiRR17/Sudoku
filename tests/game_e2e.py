"""End-to-end terminal gameplay, atomic save, resume and corrupted-save checks.

Portable stdlib, no tty/color dependency. The child receives commands on stdin.
"""
# These executable E2E scripts intentionally use Python 'assert' for
# required release checks. -O/-OO and PYTHONOPTIMIZE remove all assertions;
# refusing optimization prevents a silent false-positive acceptance.
if not __debug__:
    raise SystemExit('SUDOKU TEST FAIL: Python optimization disables required assertions')


import os
import pathlib
import re
import stat
import subprocess
import sys
import tempfile

exe = pathlib.Path(sys.argv[1]).resolve()
fixtures = pathlib.Path(sys.argv[2]).resolve()
solution = '534678912672195348198342567859761423426853791713924856961537284287419635345286179'
near_win = '0' + solution[1:]
checks = 0


def run(args, commands='', exit_code=0, timeout=25):
    global checks
    p = subprocess.run([str(exe), 'play', *map(str, args)], input=commands,
                       text=True, encoding='utf-8', capture_output=True, timeout=timeout)
    assert p.returncode == exit_code, (args, p.returncode, p.stderr, p.stdout)
    assert '\x1b[' not in p.stdout, 'Unexpected ANSI escape/color codes'
    checks += 1
    return p.stdout, p.stderr


def run_raw(args, commands, exit_code=0):
    """Feed byte-exact commands, including NUL, through the real game CLI."""
    global checks
    p = subprocess.run([str(exe), 'play', *map(str, args)], input=commands,
                       capture_output=True, timeout=25)
    assert p.returncode == exit_code, (args, p.returncode, p.stderr, p.stdout)
    checks += 1
    return p.stdout.decode('utf-8'), p.stderr.decode('utf-8')


with tempfile.TemporaryDirectory() as directory:
    folder = pathlib.Path(directory)
    # Do not let embedded NUL truncate a save command into an executable
    # prefix. The following status/quit commands must still be processed.
    nul_save = folder / 'nul-injected.save'
    stdout, stderr = run_raw(
        ['--puzzle', near_win],
        f'save {nul_save}'.encode('utf-8') + b'\x00ignored\nstatus\nquit\n')
    assert stdout.count('Error: command contains a NUL byte') == 1, stdout
    assert 'Progress: 80/81 filled' in stdout and not nul_save.exists()
    assert not stderr
    checks += 1

    # A valid move followed by a hidden NUL suffix must not solve the board.
    stdout, stderr = run_raw(
        ['--puzzle', near_win], b'set 1 1 5\x00ignored\nstatus\nquit\n')
    assert 'Error: command contains a NUL byte' in stdout
    assert 'Progress: 80/81 filled' in stdout and 'SOLVED!' not in stdout
    assert not stderr
    checks += 1

    # Drain an overlong line, even if it also contains NUL, and run the
    # next complete command once (not a surviving tail fragment).
    stdout, stderr = run_raw(
        ['--puzzle', near_win],
        b'ignored' + b'x' * 5000 + b'\x00suffix\nstatus\nquit\n')
    assert stdout.count('Error: command too long') == 1, stdout
    assert 'Error: command contains a NUL byte' not in stdout
    assert stdout.count('Progress: 80/81 filled') == 1 and not stderr
    checks += 1

    # Reject quit with an embedded NUL; a final unterminated status line
    # is still processed before reaching normal EOF.
    stdout, stderr = run_raw(
        ['--puzzle', near_win], b'quit\x00ignored\nstatus')
    assert stdout.count('Error: command contains a NUL byte') == 1
    assert 'Progress: 80/81 filled' in stdout
    assert 'End of input. Progress is only persisted' in stdout
    assert 'Goodbye.' not in stdout and not stderr
    checks += 1
    # Other ASCII control bytes must never reach command parsing, file paths
    # or echoed terminal output. Keep the following command aligned.
    terminal_save = folder / 'terminal-injected.save'
    control_inputs = [
        f'save {terminal_save}'.encode('utf-8') + b'\x1b[31m\n',
        f'save {terminal_save}'.encode('utf-8') + b'\rmalicious\n',
        b'set 1 1 5\x08\n',
        b'quit\x7f\n',
        b'show\x0c\n',
    ]
    for bad_line in control_inputs:
        stdout, stderr = run_raw(
            ['--puzzle', near_win], bad_line + b'status\nquit\n')
        assert stdout.count('Error: command contains a control byte') == 1, stdout
        assert stdout.count('Progress: 80/81 filled') == 1, stdout
        assert 'SOLVED!' not in stdout and '\x1b' not in stdout
        assert 'Goodbye.' in stdout and not stderr
        assert not list(folder.glob('terminal-injected.save*'))
        checks += 1

    # The rejection logic must not break CRLF scripts or a trailing CR at
    # EOF: only CR within a command is malformed.
    stdout, stderr = run_raw(['--puzzle', near_win], b'status\r\nquit\r\n')
    assert stdout.count('Progress: 80/81 filled') == 1
    assert 'Goodbye.' in stdout and 'Error:' not in stdout and not stderr
    checks += 1
    stdout, stderr = run_raw(['--puzzle', near_win], b'status\r')
    assert stdout.count('Progress: 80/81 filled') == 1
    assert 'End of input. Progress is only persisted' in stdout
    assert not stderr
    checks += 1

    # Locked candidates (pointing box -> row/column and claiming line ->
    # box) use current-board legality, not the stored solution. Preview must
    # not touch the player's board or game history.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'hint locked\nhint locked 1\nhint locked 2\n'
                         'hint locked 12\nstatus\nquit\n')
    pointing1 = ('Locked 1 (pointing box 1 -> row 2, digit 7): '
                 'sources r2c2 r2c3; eliminate r2c7 r2c9')
    pointing2 = ('Locked 2 (pointing box 2 -> row 3, digit 3): '
                 'sources r3c4 r3c5; eliminate r3c7')
    claiming = ('Locked 12 (claiming row 2 -> box 3, digit 8): '
                'sources r2c7 r2c9; eliminate r1c7 r1c9')
    assert stdout.count(pointing1) == 4, stdout
    assert stdout.count(pointing2) == 3, stdout
    assert claiming in stdout, stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # Applying the first two pointing patterns erases only existing manual
    # candidate marks in one undoable edit. A further preview never alters
    # history; repeating application with nothing left is a true no-op.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'note 2 7 7\nnote 2 9 7\nnote 3 7 3\n'
                         'note 2 7 8\nstatus\nhint apply locked 1\n'
                         'notes 2 7\nnotes 2 9\nnotes 3 7\nstatus\n'
                         'undo\nnotes 2 7\nstatus\nredo\n'
                         'hint apply locked 1\nstatus\nquit\n')
    assert 'Removed 2 locked pencil candidates in one undoable edit.' in stdout
    assert 'Notes for row 2 col 7: 8\n' in stdout
    assert 'Notes for row 2 col 9:\n' in stdout
    assert 'Notes for row 3 col 7: 3\n' in stdout
    assert 'Notes for row 2 col 7: 7 8\n' in stdout
    assert 'No matching locked pencil notes to remove; history unchanged.' in stdout
    assert stdout.count('undo 5, redo 0') == 2, stdout
    assert 'undo 4, redo 1' in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'note 2 7 7\nnote 2 9 7\nnote 3 7 3\n'
                         'note 2 7 8\nstatus\nhint apply locked 2\n'
                         'notes 2 7\nnotes 3 7\nstatus\nundo\n'
                         'notes 2 7\nstatus\nredo\nstatus\nquit\n')
    assert 'Removed 3 locked pencil candidates in one undoable edit.' in stdout
    assert 'Notes for row 2 col 7: 8\n' in stdout
    assert 'Notes for row 3 col 7:\n' in stdout
    assert 'Notes for row 2 col 7: 7 8\n' in stdout
    assert stdout.count('undo 5, redo 0') == 2
    assert 'undo 4, redo 1' in stdout and not stderr
    checks += 1

    # Claiming works even when the first few pointing patterns have no
    # corresponding handwritten notes: it can eliminate the candidate 8
    # from other box-3 cells using only row-2 constraints.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'note 1 7 8\nnote 1 9 8\n'
                         'hint apply locked 12\nnotes 1 7\nnotes 1 9\n'
                         'status\nundo\nnotes 1 7\nstatus\nquit\n')
    assert 'Removed 2 locked pencil candidates in one undoable edit.' in stdout
    assert 'Notes for row 1 col 7:\n' in stdout
    assert 'Notes for row 1 col 9:\n' in stdout
    assert 'Notes for row 1 col 7: 8\n' in stdout
    assert 'undo 3, redo 0' in stdout and 'undo 2, redo 1' in stdout
    assert not stderr
    checks += 1

    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'hint apply locked\nstatus\nundo\nquit\n')
    assert 'No matching locked pencil notes to remove; history unchanged.' in stdout
    assert 'undo 0, redo 0' in stdout
    assert 'Error: no action to undo or redo' in stdout and not stderr
    checks += 1

    # A locally rule-legal but wrong digit blocks both forms of strategy,
    # so inferred eliminations cannot be based on a corrupted player board.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 9 4\nhint locked\nhint apply locked\n'
                         'status\nquit\n')
    assert 'Cannot preview locked candidates: correct the existing mistakes first.' in stdout
    assert 'Cannot apply locked candidates: correct the existing mistakes first.' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--puzzle', solution],
                         'hint locked\nhint apply locked\nstatus\nquit\n')
    assert stdout.count('Puzzle already solved; no locked hint needed.') == 2
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    invalid_locked = [
        'hint locked 0', 'hint locked 82', 'hint locked -1',
        'hint locked nope', 'hint locked 1 extra',
        'hint apply locked 0', 'hint apply locked 82',
        'hint apply locked -1', 'hint apply locked nope',
        'hint apply locked 1 extra',
    ]
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'status\n' + '\n'.join(invalid_locked) +
                         '\nstatus\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(invalid_locked)
    assert stdout.count('undo 0, redo 0') == 2
    assert 'Locked 1 ' not in stdout and not stderr
    checks += 1

    # Genuine 24-given unique puzzle with two actionable naked pairs. A
    # pair reserves two digits in exactly two unit cells; elimination reports
    # which candidate marks other cells in that unit could remove.
    pair_puzzle = (
        '000670000600105008008002000000001020400850091'
        '000000006001000284000009030040006000'
    )
    assert len(pair_puzzle) == 81
    # X-Wing: in this unique puzzle, digit 2 is restricted to columns
    # 2,3 in rows 2,5. Therefore 2 can be excluded from the same
    # columns in other rows. Preview must not change game history.
    stdout, stderr = run(['--puzzle', pair_puzzle],
                         'hint x-wing\nhint x-wing 1\nstatus\nquit\n')
    first_xwing = (
        'X-Wing 1 (rows 2,5; columns 2,3; digit 2): '
        'corners r2c2 r2c3 r5c2 r5c3; '
        'eliminate r1c2 r1c3 r6c2 r6c3 r8c2 r8c3 r9c3'
    )
    assert stdout.count(first_xwing) == 2, stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # Only existing handwritten marks are removed. Multiple eliminations
    # form one Undo transaction and preserve unrelated notes/digits.
    stdout, stderr = run(['--puzzle', pair_puzzle],
                         'note 1 2 2\nnote 1 3 2\nnote 6 2 2\n'
                         'note 1 2 7\nstatus\nhint apply x-wing 1\n'
                         'notes 1 2\nnotes 1 3\nnotes 6 2\nstatus\n'
                         'undo\nnotes 1 2\nstatus\nredo\n'
                         'hint apply x-wing 1\nstatus\nquit\n')
    assert 'Removed 3 X-Wing pencil candidates in one undoable edit.' in stdout
    assert 'Notes for row 1 col 2: 7\n' in stdout
    assert 'Notes for row 1 col 3:\n' in stdout
    assert 'Notes for row 6 col 2:\n' in stdout
    assert 'Notes for row 1 col 2: 2 7\n' in stdout
    assert stdout.count('undo 5, redo 0') == 2, stdout
    assert 'undo 4, redo 1' in stdout
    assert 'No matching X-Wing pencil notes to remove; history unchanged.' in stdout
    assert not stderr
    checks += 1

    # No handwritten candidates: applying a logical X-Wing is a history-neutral
    # no-op; don't fill solution digits or guess.
    stdout, stderr = run(['--puzzle', pair_puzzle],
                         'hint apply x-wing\nstatus\nundo\nquit\n')
    assert 'No matching X-Wing pencil notes to remove; history unchanged.' in stdout
    assert 'undo 0, redo 0' in stdout
    assert 'Error: no action to undo or redo' in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--puzzle', solution],
                         'hint x-wing\nhint apply x-wing\nstatus\nquit\n')
    assert stdout.count('Puzzle already solved; no X-Wing hint needed.') == 2
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 9 4\nhint x-wing\nhint apply x-wing\nstatus\nquit\n')
    assert 'Cannot preview X-Wings: correct the existing mistakes first.' in stdout
    assert 'Cannot apply X-Wings: correct the existing mistakes first.' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    invalid_xwing = [
        'hint x-wing 0', 'hint x-wing 82', 'hint x-wing -1',
        'hint x-wing nope', 'hint x-wing 1 extra',
        'hint apply x-wing 0', 'hint apply x-wing 82',
        'hint apply x-wing -1', 'hint apply x-wing nope',
        'hint apply x-wing 1 extra',
    ]
    stdout, stderr = run(['--puzzle', pair_puzzle],
                         'status\n' + '\n'.join(invalid_xwing) +
                         '\nstatus\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(invalid_xwing)
    assert stdout.count('undo 0, redo 0') == 2
    assert 'X-Wing 1 ' not in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--puzzle', pair_puzzle],
                         'hint pairs\nstatus\nnote 1 1 2\n'
                         'hint pairs 1\nnotes 1 1\nstatus\nundo\n'
                         'hint pairs 2\nnotes 1 1\nstatus\nquit\n')
    first_pair = ('Pair 1 in row 5: r5c6 + r5c7 reserve 3,7; '
                  'eliminate from r5c2(3,7) r5c3(3,7)')
    second_pair = ('Pair 2 in column 6: r5c6 + r7c6 reserve 3,7; '
                   'eliminate from r1c6(3) r6c6(3,7)')
    assert stdout.count(first_pair) == 3, stdout
    assert stdout.count(second_pair) == 2, stdout
    assert 'Progress: 24/81 filled' in stdout
    assert 'undo 1, redo 0' in stdout and 'undo 0, redo 1' in stdout
    assert 'Notes for row 1 col 1: 2' in stdout
    assert 'Notes for row 1 col 1:\n' in stdout
    assert not stderr
    checks += 1

    # Pairs are not fabricated on a single-candidate puzzle, and a game
    # with known wrong entries blocks strategy recommendations.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'hint pairs\nset 1 9 4\nhint pairs\nstatus\nquit\n')
    assert 'No actionable naked pairs found.' in stdout
    assert 'Cannot preview pairs: correct the existing mistakes first.' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--puzzle', solution], 'hint pairs\nstatus\nquit\n')
    assert 'Puzzle already solved; no pair hint needed.' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    invalid_pairs = ['hint pairs 0', 'hint pairs 82', 'hint pairs -1',
                     'hint pairs nonsense', 'hint pairs 2 extra',
                     'hint pairs 1.5']
    stdout, stderr = run(['--puzzle', pair_puzzle],
                         'status\n' + '\n'.join(invalid_pairs) +
                         '\nstatus\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(invalid_pairs)
    assert stdout.count('undo 0, redo 0') == 2
    assert 'Pair 1 ' not in stdout and not stderr
    checks += 1

    # Pair application is opt-in: it removes ONLY matching existing pencil
    # notes, preserving other manual notes, filled digits and immutable givens.
    # The first pair affects r5c2/r5c3; two pairs add r1c6/r6c6.
    stdout, stderr = run(['--puzzle', pair_puzzle],
                         'note 5 2 3\nnote 5 2 7\nnote 5 2 2\n'
                         'note 5 3 3\nnote 5 3 7\nnote 1 6 3\n'
                         'note 6 6 3\nnote 6 6 7\nstatus\n'
                         'hint apply pairs 1\nnotes 5 2\nnotes 1 6\nstatus\n'
                         'undo\nnotes 5 2\nstatus\n'
                         'hint apply pairs 2\nnotes 5 2\nnotes 5 3\n'
                         'notes 1 6\nnotes 6 6\nstatus\n'
                         'hint apply pairs 2\nstatus\n'
                         'undo\nnotes 6 6\nstatus\nredo\nstatus\nquit\n')
    assert 'Removed 4 pencil candidates in one undoable edit.' in stdout
    assert 'Removed 7 pencil candidates in one undoable edit.' in stdout
    assert 'No matching pencil notes to remove; history unchanged.' in stdout
    assert stdout.count('Notes for row 5 col 2: 2\n') == 2, stdout
    assert 'Notes for row 5 col 2: 2 3 7\n' in stdout
    assert 'Notes for row 1 col 6: 3\n' in stdout
    assert 'Notes for row 1 col 6:\n' in stdout
    assert 'Notes for row 5 col 3:\n' in stdout
    assert 'Notes for row 6 col 6: 3 7\n' in stdout
    assert 'Notes for row 6 col 6:\n' in stdout
    assert stdout.count('undo 9, redo 0') == 4, stdout
    assert stdout.count('undo 8, redo 1') == 2, stdout
    assert 'Progress: 24/81 filled' in stdout and not stderr
    checks += 1

    # No matching pencil notes is a true no-op, not a phantom Undo entry.
    stdout, stderr = run(['--puzzle', pair_puzzle],
                         'hint apply pairs\nstatus\nundo\nquit\n')
    assert 'No matching pencil notes to remove; history unchanged.' in stdout
    assert 'undo 0, redo 0' in stdout
    assert 'Error: no action to undo or redo' in stdout
    assert not stderr
    checks += 1

    # Existing incorrect digits block automatic pencil elimination.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 9 4\nhint apply pairs\nstatus\nquit\n')
    assert 'Cannot apply pairs: correct the existing mistakes first.' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    invalid_pair_apply = ['hint apply pairs 0', 'hint apply pairs 82',
                          'hint apply pairs -1', 'hint apply pairs nope',
                          'hint apply pairs 2 extra', 'hint apply pairs 1.5']
    stdout, stderr = run(['--puzzle', pair_puzzle],
                         'status\n' + '\n'.join(invalid_pair_apply) +
                         '\nstatus\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(invalid_pair_apply)
    assert stdout.count('undo 0, redo 0') == 2
    assert 'Pair 1 in ' not in stdout and not stderr
    checks += 1

    # Hidden pairs are different from naked pairs: exactly two numbers can
    # occupy only the same two cells of a unit, even if each cell currently
    # permits more than two candidates. Extra candidates in those two cells
    # may be removed, but unrelated pencil digits must remain untouched.
    stdout, stderr = run(['--puzzle', pair_puzzle],
                         'hint hidden-pairs\nhint hidden-pairs 1\n'
                         'hint hidden-pairs 3\nstatus\nquit\n')
    row_hidden = ('Hidden pair 1 in row 5: r5c2 + r5c3 reserve 2,6; '
                  'remove from r5c2(3,7) r5c3(3,7)')
    column_hidden = ('Hidden pair 2 in column 5: r8c5 + r9c5 reserve 1,8; '
                     'remove from r8c5(2,4) r9c5(2,3)')
    assert stdout.count(row_hidden) == 3, stdout
    assert stdout.count(column_hidden) == 2, stdout
    assert 'Hidden pair 3 ' not in stdout  # duplicate box-8 pair suppressed
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--puzzle', pair_puzzle],
                         'note 5 2 2\nnote 5 2 3\nnote 5 2 7\n'
                         'note 5 3 3\nnote 5 3 7\n'
                         'note 8 5 2\nnote 8 5 4\n'
                         'note 9 5 2\nnote 9 5 3\n'
                         'hint apply hidden-pairs 1\n'
                         'notes 5 2\nnotes 5 3\nnotes 8 5\nstatus\n'
                         'undo\nnotes 5 2\nstatus\n'
                         'redo\nnotes 5 2\nstatus\nquit\n')
    assert 'Removed 4 hidden-pair pencil candidates in one undoable edit.' in stdout
    assert 'Notes for row 5 col 2: 2\n' in stdout
    assert 'Notes for row 5 col 3:\n' in stdout
    assert 'Notes for row 8 col 5: 2 4\n' in stdout  # second pair not applied
    assert 'Notes for row 5 col 2: 2 3 7\n' in stdout  # Undo restores notes
    assert stdout.count('undo 10, redo 0') == 2, stdout
    assert 'undo 9, redo 1' in stdout
    assert 'Progress: 24/81 filled' in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--puzzle', pair_puzzle],
                         'note 5 2 2\nnote 5 2 3\nnote 5 2 7\n'
                         'note 5 3 3\nnote 5 3 7\n'
                         'note 8 5 2\nnote 8 5 4\n'
                         'note 9 5 2\nnote 9 5 3\n'
                         'hint apply hidden-pairs 2\n'
                         'notes 5 2\nnotes 8 5\nnotes 9 5\nstatus\n'
                         'hint apply hidden-pairs 2\nstatus\n'
                         'undo\nnotes 8 5\nstatus\nquit\n')
    assert 'Removed 8 hidden-pair pencil candidates in one undoable edit.' in stdout
    assert 'No matching hidden-pair pencil notes to remove; history unchanged.' in stdout
    assert 'Notes for row 5 col 2: 2\n' in stdout
    assert 'Notes for row 8 col 5:\n' in stdout
    assert 'Notes for row 9 col 5:\n' in stdout
    assert 'Notes for row 8 col 5: 2 4\n' in stdout
    assert stdout.count('undo 10, redo 0') == 2
    assert 'undo 9, redo 1' in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--puzzle', pair_puzzle],
                         'hint apply hidden-pairs\nstatus\nundo\nquit\n')
    assert 'No matching hidden-pair pencil notes to remove; history unchanged.' in stdout
    assert 'undo 0, redo 0' in stdout
    assert 'Error: no action to undo or redo' in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 9 4\nhint hidden-pairs\n'
                         'hint apply hidden-pairs\nstatus\nquit\n')
    assert 'Cannot preview hidden pairs: correct the existing mistakes first.' in stdout
    assert 'Cannot apply hidden pairs: correct the existing mistakes first.' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--puzzle', solution],
                         'hint hidden-pairs\nhint apply hidden-pairs\nstatus\nquit\n')
    assert stdout.count('Puzzle already solved; no hidden pair hint needed.') == 2
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    invalid_hidden = [
        'hint hidden-pairs 0', 'hint hidden-pairs 82',
        'hint hidden-pairs -1', 'hint hidden-pairs nope',
        'hint hidden-pairs 2 extra',
        'hint apply hidden-pairs 0', 'hint apply hidden-pairs 82',
        'hint apply hidden-pairs -1', 'hint apply hidden-pairs nope',
        'hint apply hidden-pairs 2 extra',
    ]
    stdout, stderr = run(['--puzzle', pair_puzzle],
                         'status\n' + '\n'.join(invalid_hidden) +
                         '\nstatus\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(invalid_hidden)
    assert stdout.count('undo 0, redo 0') == 2
    assert 'Hidden pair 1 ' not in stdout and not stderr
    checks += 1

    # Candidate-pressure explorer is read-only, deterministic, and sorted
    # first by fewest legal candidates, then by row/column reading order.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'status\nfocus\nfocus 6\nnote 1 3 4\n'
                         'focus 1\nstatus\nundo\nfocus 1\nstatus\nquit\n')
    assert 'Focus cells (5 of 51 empty, fewest candidates first):' in stdout
    assert 'Focus cells (6 of 51 empty, fewest candidates first):' in stdout
    assert stdout.count('row 5 col 5: 1 candidate: 5 (forced single)') == 4
    for expected in (
        'row 7 col 6: 1 candidate: 7 (forced single)',
        'row 7 col 9: 1 candidate: 4 (forced single)',
        'row 8 col 8: 1 candidate: 3 (forced single)',
        'row 1 col 4: 2 candidates: 2 6',
        'row 3 col 1: 2 candidates: 1 2',
    ):
        assert expected in stdout, (expected, stdout)
    assert stdout.count('Progress: 30/81 filled') == 3
    assert 'undo 1, redo 0' in stdout and 'undo 0, redo 1' in stdout
    assert not stderr
    checks += 1

    # A full 81-slot request is capped by the number of remaining cells.
    # On a solved game it does not disclose hidden solution data or edit it.
    stdout, stderr = run(['--puzzle', near_win],
                         'focus 1\nfocus 81\nstatus\nset 1 1 5\n'
                         'focus\nstatus\nquit\n')
    assert stdout.count('Focus cells (1 of 1 empty, fewest candidates first):') == 2
    assert stdout.count('row 1 col 1: 1 candidate: 5 (forced single)') == 2
    assert 'Puzzle already filled; no focus needed.' in stdout
    assert 'undo 0, redo 0' in stdout and 'undo 1, redo 0' in stdout
    assert not stderr
    checks += 1

    # A locally legal but wrong entry may leave another cell with no legal
    # candidate. Focus must surface that dead end rather than silently hide it.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 9 4\nfocus 3\nstatus\nquit\n')
    assert 'row 7 col 9: 0 candidates (no legal digits)' in stdout
    assert 'Warning: ' in stdout and 'no legal digits; inspect entries.' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    invalid_focus = ['focus 0', 'focus 82', 'focus -1', 'focus nope',
                     'focus 1 extra', 'focus 2.5']
    stdout, stderr = run(['--puzzle', near_win],
                         'status\n' + '\n'.join(invalid_focus) +
                         '\nstatus\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(invalid_focus)
    assert stdout.count('undo 0, redo 0') == 2
    assert 'Focus cells (' not in stdout and not stderr
    checks += 1

    # Portable puzzle exchange uses the already-supported --puzzle 81-digit
    # format. Givens stay immutable across edits; current reflects only
    # player entries, never the cached solution or private pencil notes.
    stdout, stderr = run(['--puzzle', near_win],
                         'export\nexport givens\nexport current\nstatus\n'
                         'note 1 1 5\nexport both\nstatus\nset 1 1 5\n'
                         'export current\nexport\nstatus\nundo\n'
                         'export current\nnotes 1 1\nstatus\nquit\n')
    assert stdout.count('Puzzle givens: ' + near_win) == 4, stdout
    assert stdout.count('Current board: ' + near_win) == 3, stdout
    assert stdout.count('Current board: ' + solution) == 1, stdout
    assert 'Notes for row 1 col 1: 5' in stdout, stdout
    assert 'undo 0, redo 0' in stdout
    assert 'undo 2, redo 0' in stdout and 'undo 1, redo 1' in stdout
    assert not stderr
    checks += 1

    # Export may display a rule-legal but incorrect player's entry. It must
    # not silently substitute the stored answer (or promise solvability).
    original = ''.join((fixtures / 'unique.txt').read_text().split())
    modified = original[:2] + '1' + original[3:]
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 1\nexport\nexport current\nstatus\nquit\n')
    assert 'Puzzle givens: ' + original in stdout
    assert 'Current board: ' + modified in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Invalid export modes and extra arguments must be rejected without
    # touching the board, save path, pencil marks or Undo/Redo.
    invalid_exports = [
        'export currently', 'export givens extra', 'export current extra',
        'export both extra', 'export current many more', 'export --help',
    ]
    stdout, stderr = run(['--puzzle', near_win],
                         'status\n' + '\n'.join(invalid_exports) +
                         '\nstatus\nexport\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(invalid_exports)
    assert stdout.count('undo 0, redo 0') == 2
    assert stdout.count('Puzzle givens: ' + near_win) == 1
    assert 'Current board:' not in stdout and not stderr
    checks += 1

    # Navigate multiple undo states atomically: excessive requests must
    # leave notes, cursor and redo history untouched.
    stdout, stderr = run(['--puzzle', near_win],
                         'note 1 1 1\nnote 1 1 2\nnote 1 1 3\n'
                         'status\nundo 2\nnotes 1 1\nstatus\nredo 2\n'
                         'notes 1 1\nstatus\nundo 4\nstatus\nredo 1\n'
                         'status\nundo 3\nnotes 1 1\nstatus\nredo 4\n'
                         'status\nredo 3\nstatus\nquit\n')
    assert 'Notes for row 1 col 1: 1\n' in stdout
    assert 'Notes for row 1 col 1: 1 2 3\n' in stdout
    assert 'Notes for row 1 col 1:\n' in stdout
    assert stdout.count('undo 3, redo 0') >= 3, stdout
    assert stdout.count('undo 1, redo 2') >= 1, stdout
    assert stdout.count('undo 0, redo 3') >= 2, stdout
    assert stdout.count('Error: no action to undo or redo') == 3, stdout
    assert not stderr
    checks += 1

    # Invalid counts and extra tokens are rejected before history mutation.
    invalid_history = ['undo 0', 'redo 0', 'undo 128', 'redo 128',
                       'undo -1', 'redo nope', 'undo 2 extra',
                       'redo 1 extra', 'undo 3.5']
    stdout, stderr = run(['--puzzle', near_win],
                         'note 1 1 4\nstatus\n' +
                         '\n'.join(invalid_history) +
                         '\nstatus\nundo\nstatus\nredo\nstatus\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(invalid_history)
    assert stdout.count('undo 1, redo 0') == 3, stdout
    assert 'undo 0, redo 1' in stdout
    assert not stderr
    checks += 1

    saved = folder / 'game with spaces.save'
    stdout, stderr = run(['--puzzle', near_win, '--save', saved], '\n'.join([
        'notes 1 1', 'note 1 1 5', 'notes 1 1', 'set 1 1 5', 'check',
        'undo', 'redo', 'status', 'save', 'quit', '']))
    assert 'Notes for row 1 col 1: 5' in stdout
    assert 'SOLVED!' in stdout and 'Check: ' not in stdout
    assert 'Saved to' in stdout and saved.exists() and not stderr
    checks += 1
    assert not list(folder.glob(saved.name + '.tmp.*'))
    checks += 1
    # POSIX save mode must never become world/group readable, even under
    # a permissive process umask or when replacing an older permissive save.
    if os.name == 'posix':
        private_save = folder / 'private game.save'
        old_umask = os.umask(0)
        try:
            stdout, stderr = run(['--puzzle', near_win, '--save', private_save],
                                 'save\nquit\n')
        finally:
            os.umask(old_umask)
        assert 'Saved to' in stdout and not stderr
        assert stat.S_IMODE(private_save.stat().st_mode) == 0o600
        checks += 1
        private_save.chmod(0o666)
        stdout, stderr = run(['--resume', private_save], 'save\nquit\n')
        assert 'Saved to' in stdout and not stderr
        assert stat.S_IMODE(private_save.stat().st_mode) == 0o600
        checks += 1
    # Interactive save accepts paths with spaces and makes them the default.
    explicit = folder / 'manual save with spaces.save'
    stdout, stderr = run(['--puzzle', near_win],
                         f'set 1 1 5\nsave {explicit}\nsave\nquit\n')
    assert stdout.count(f'Saved to {explicit}') == 2 and explicit.is_file() and not stderr
    checks += 1
    stdout, stderr = run(['--resume', explicit], 'status\nquit\n')
    assert 'SOLVED!' in stdout and not stderr
    checks += 1
    # A failed explicit save does not replace the last working default path.
    stdout, stderr = run(['--puzzle', near_win, '--save', explicit],
                         f'save {folder}\nsave\nquit\n')
    assert 'Error: file operation failed' in stdout
    assert f'Saved to {explicit}' in stdout and not stderr
    checks += 1
    # Discard an overlong input command as one unit (no stray partial command).
    stdout, stderr = run(['--puzzle', near_win], 'save ' + 'x' * 4200 + '\nquit\n')
    assert 'Error: command too long' in stdout and 'Goodbye.' in stdout and not stderr
    checks += 1
    quoted = folder / 'quoted game path.save'
    stdout, stderr = run(['--puzzle', near_win], f'save "{quoted}"\nquit\n')
    assert f'Saved to {quoted}' in stdout and quoted.is_file() and not stderr
    checks += 1
    # Invalid explicit quotes must not fall back to --save and clobber an
    # earlier completed session. A bare 'save' remains the only fallback.
    preserved = explicit.read_bytes()
    stdout, stderr = run(['--puzzle', near_win, '--save', explicit],
                         'save ""\nquit\n')
    assert 'Error: empty save path' in stdout and 'Saved to' not in stdout and not stderr
    assert explicit.read_bytes() == preserved
    checks += 1
    incomplete = folder / 'incomplete quoted path.save'
    stdout, stderr = run(['--puzzle', near_win],
                         f'save "{incomplete}\nquit\n')
    assert 'Error: malformed quoted save path' in stdout and not incomplete.exists() and not stderr
    checks += 1
    # Quoting has one optional pair only. Stray or nested quote characters
    # must not become literal filenames or redirect a previous default save.
    known_files = {p.name for p in folder.iterdir()}
    malformed_inputs = [
        f'save "{folder / "bad nested quote.save"}"'.replace('nested', 'nes"ted'),
        f'save {folder / "dangling quote.save"}"',
        f'save {folder / "embedded quote.save"}'.replace('embedded', 'em"bedded'),
    ]
    for command in malformed_inputs:
        stdout, stderr = run(['--puzzle', near_win, '--save', explicit],
                             command + '\nquit\n')
        assert stdout.count('Error: malformed quoted save path') == 1
        assert 'Saved to' not in stdout and not stderr
        assert explicit.read_bytes() == preserved
        assert {p.name for p in folder.iterdir()} == known_files
        checks += 1
    # Gameplay file loading must use bounded heap storage instead of a >1 MiB
    # stack frame (especially relevant for the default Windows/MSVC stack).
    # Gameplay --file reserves stdin for player commands; a FIFO with no
    # writer must be rejected immediately, rather than hanging at fopen.
    if os.name == 'posix' and hasattr(os, 'mkfifo'):
        fifo = folder / 'writerless-game-puzzle.fifo'
        os.mkfifo(fifo)
        stdout, stderr = run(['--file', fifo], exit_code=4, timeout=3)
        assert not stdout and 'Puzzle open failed:' in stderr
        checks += 1
    copied = folder / 'unique puzzle from file with spaces.txt'
    copied.write_text(near_win + '\n', encoding='ascii')
    stdout, stderr = run(['--file', copied], 'status\nquit\n')
    assert 'Started new game' in stdout and 'Progress:' in stdout and not stderr
    checks += 1
    empty_file = folder / 'empty puzzle.txt'
    empty_file.write_bytes(b'')
    stdout, stderr = run(['--file', empty_file], exit_code=3)
    assert not stdout and 'Invalid puzzle:' in stderr
    checks += 1
    bad_file = folder / 'binary puzzle.txt'
    bad_file.write_bytes(bytes([0]) + near_win.encode('ascii'))
    stdout, stderr = run(['--file', bad_file], exit_code=3)
    assert not stdout and 'Invalid puzzle:' in stderr
    checks += 1
    oversized = folder / 'oversized puzzle.txt'
    oversized.write_bytes(b'0' * (1024 * 1024 + 1))
    stdout, stderr = run(['--file', oversized], exit_code=3)
    assert not stdout and 'Invalid puzzle:' in stderr
    checks += 1
    stdout, stderr = run(['--file', folder / 'missing puzzle.txt'], exit_code=4)
    assert not stdout and 'Puzzle open failed:' in stderr
    checks += 1
    first = saved.read_bytes()
    assert first.startswith(b'SUDOKU_SAVE_V1\n') and b'\nC=' in first
    checks += 1
    stdout, stderr = run(['--resume', saved], 'status\nreset\nundo\nsave\nquit\n')
    assert 'Resumed saved game' in stdout and 'SOLVED!' in stdout
    assert saved.exists() and not stderr
    checks += 1
    before = saved.read_bytes()
    # Fake interrupted-writing staging file never replaces an existing valid save.
    temp_orphan = folder / (saved.name + '.tmp.INTERRUPTED')
    temp_orphan.write_bytes(b'SUDOKU_SAVE_V1\nG=truncated')
    stdout, stderr = run(['--resume', saved], 'status\nquit\n')
    assert 'SOLVED!' in stdout and saved.read_bytes() == before
    checks += 1
    # Check checksum validation and no implicit fallback/repair.
    damaged = folder / 'corrupt.save'
    corrupt = bytearray(first)
    corrupt[50] = ord('0') if corrupt[50] != ord('0') else ord('1')
    damaged.write_bytes(corrupt)
    stdout, stderr = run(['--resume', damaged], exit_code=3)
    assert 'corrupted save file' in stderr and not stdout
    checks += 1
    damaged.write_bytes(b'X' * 2000)
    stdout, stderr = run(['--resume', damaged], exit_code=3)
    assert 'corrupted save file' in stderr and not stdout
    checks += 1
    # A deliberately recalculated checksum must not permit a noncanonical
    # timestamp such as E=00. Corruption rejection must be structural, not
    # merely a mismatch with the original FNV-1a checksum.
    prefix, old_checksum = first.rsplit(b'\nC=', 1)
    assert len(old_checksum) == 17 and old_checksum.endswith(b'\n')
    # The split at '\nC=' consumes the line break following E=...
    head, saved_elapsed = prefix.rsplit(b'\nE=', 1)
    assert saved_elapsed.isdigit()
    padded_body = head + b'\nE=0' + saved_elapsed + b'\n'
    value = 0xcbf29ce484222325
    for byte in padded_body:
        value ^= byte
        value = (value * 0x100000001b3) & ((1 << 64) - 1)
    damaged.write_bytes(padded_body + f'C={value:016X}\n'.encode('ascii'))
    stdout, stderr = run(['--resume', damaged], exit_code=3)
    assert 'corrupted save file' in stderr and not stdout
    checks += 1
    # A failed attempted save cannot overwrite the existing game.
    stdout, stderr = run(['--puzzle', near_win], f'save {folder}\nquit\n')
    assert 'file operation failed' in stdout and not stderr
    checks += 1
    # Erase also removes pencil notes on an empty editable cell. Undo must
    # restore the notes, and redo must erase them again.
    stdout, stderr = run(['--puzzle', near_win],
                         'note 1 1 5\nnotes 1 1\nerase 1 1\nnotes 1 1\n'
                         'undo\nnotes 1 1\nredo\nnotes 1 1\nquit\n')
    assert stdout.count('Notes for row 1 col 1: 5') == 2, stdout
    assert stdout.count('Notes for row 1 col 1:\n') == 2, stdout
    assert not stderr
    checks += 1

    # Clear marks in multiple cells with one undoable action, and reject
    # unexpected arguments without changing notes or history.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'note 1 3 4\nnote 1 4 9\nclear-notes\nstatus\n'
                         'clear-notes\nstatus\nundo\nnotes 1 3\nnotes 1 4\n'
                         'redo\nnotes 1 3\nnotes 1 4\nclear-notes unexpected\nquit\n')
    assert stdout.count('undo 3, redo 0') == 2, stdout
    assert 'Notes for row 1 col 3: 4' in stdout
    assert 'Notes for row 1 col 4: 9' in stdout
    assert 'Notes for row 1 col 3:\n' in stdout
    assert 'Notes for row 1 col 4:\n' in stdout
    assert 'Error: unknown command or invalid arguments' in stdout
    assert not stderr
    checks += 1

    # Candidates reveal only currently legal Sudoku digits. The command
    # leaves notes, board and undo/redo history unchanged, and invalid input
    # cannot silently mutate state or reveal the verified unique solution.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'candidates 1 3\nstatus\nnote 1 3 4\n'
                         'candidates 1 3\nnotes 1 3\nset 1 3 4\n'
                         'candidates 1 3\nundo\ncandidates 1 3\n'
                         'candidates 1 3 extra\ncandidates 0 3\n'
                         'candidates 1 3 5\nstatus\nquit\n')
    assert stdout.count('Candidates for row 1 col 3: 1 2 4') == 3, stdout
    assert 'Cell row 1 col 3 already contains 4.' in stdout
    assert 'Notes for row 1 col 3: 4' in stdout
    assert 'undo 0, redo 0' in stdout  # First candidates call is a no-op.
    assert 'undo 1, redo 1' in stdout  # After undo, candidates leaves redo.
    assert stdout.count('Error: unknown command or invalid arguments') == 3
    assert not stderr
    checks += 1

    # A filled original clue is reported, never replaced, when candidates
    # is requested; a near-complete puzzle must expose only its last digit.
    stdout, stderr = run(['--puzzle', near_win],
                         'candidates 1 1\ncandidates 1 2\n'
                         'status\nquit\n')
    assert 'Candidates for row 1 col 1: 5' in stdout
    assert 'Cell row 1 col 2 already contains 3.' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # Incorrect digits are reported by their *locations* only, never the
    # solution values. Both hint preview and apply fail closed when the
    # current board contains a rule-legal but incorrect user entry.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 1\nset 1 4 6\ncheck\ncheck details\n'
                         'hint\nhint apply\nstatus\ncheck details extra\n'
                         'check verbose\nstatus\nerase 1 3\ncheck details\n'
                         'status\nquit\n')
    assert 'Incorrect entry: row 1 col 3 contains 1.' in stdout, stdout
    assert stdout.count('Incorrect entry:') == 1, stdout
    assert 'Cannot preview hint: correct the existing mistakes first.' in stdout
    assert 'Cannot apply hint: correct the existing mistakes first.' in stdout
    assert 'No incorrect entries.' in stdout
    assert stdout.count('undo 2, redo 0') == 2
    assert 'undo 3, redo 0' in stdout
    assert stdout.count('Error: unknown command or invalid arguments') == 2
    assert not stderr
    checks += 1

    # A partially solved valid puzzle is not mislabeled as incorrect, and
    # check details must remain read-only with no automated placements.
    stdout, stderr = run(['--puzzle', near_win],
                         'check details\nstatus\nquit\n')
    assert 'Check: 1 empty, 0 incorrect.' in stdout
    assert 'No incorrect entries.' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # Explicit bulk correction clears only wrong player-entered digits,
    # preserving correctly placed digits, givens and handwritten notes.
    # The whole correction is undoable; repeating it is history-neutral.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 1\nset 1 4 2\nnote 2 2 5\n'
                         'check details\ncheck clear\nstatus\n'
                         'check details\nnotes 2 2\nundo\n'
                         'check details\nredo\ncheck details\n'
                         'check clear\nstatus\nquit\n')
    assert stdout.count('Incorrect entry: row 1 col 3 contains 1.') == 2, stdout
    assert stdout.count('Incorrect entry: row 1 col 4 contains 2.') == 2, stdout
    assert stdout.count('No incorrect entries.') == 2, stdout
    assert 'Cleared 2 incorrect entries (undoable).' in stdout
    assert 'No incorrect entries to clear.' in stdout
    assert 'Notes for row 2 col 2: 5' in stdout
    assert stdout.count('undo 4, redo 0') == 2, stdout
    assert not stderr
    checks += 1

    # check clear is a true no-op on a clean snapshot. It must not discard a
    # previously available redo branch or insert a phantom undo history step.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 1\nundo\ncheck clear\n'
                         'status\nredo\ncheck details\n'
                         'check clear extra\ncheck clear wrong\nquit\n')
    assert 'undo 0, redo 1' in stdout
    assert 'No incorrect entries to clear.' in stdout
    assert 'Incorrect entry: row 1 col 3 contains 1.' in stdout
    assert stdout.count('Error: unknown command or invalid arguments') == 2
    assert not stderr
    checks += 1

    # A logical hint uses current board candidates only, with no move,
    # note edits, history change or accidental undo/redo branch reset.
    stdout, stderr = run(['--puzzle', near_win],
                         'hint\nstatus\nhint unexpected\nstatus\nquit\n')
    assert 'Hint (only candidate): row 1 col 1 -> 5.' in stdout
    assert stdout.count('undo 0, redo 0') == 2
    assert stdout.count('Error: unknown command or invalid arguments') == 1
    assert not stderr
    checks += 1

    # 'hint all' enumerates distinct forced cells without placing digits,
    # modifying notes, revealing the solved grid or touching history.
    stdout, stderr = run(['--puzzle', near_win],
                         'hint all\nstatus\nhint all\nstatus\n'
                         'hint all unexpected\nstatus\nquit\n')
    assert stdout.count('Logical hints (1):') == 2, stdout
    assert stdout.count('Hint (only candidate): row 1 col 1 -> 5.') == 2
    assert stdout.count('undo 0, redo 0') == 3
    assert stdout.count('Error: unknown command or invalid arguments') == 1
    assert 'Applied hint' not in stdout and not stderr
    checks += 1

    # A listed hint does not erase handwritten notes or consume a history
    # slot; a later explicit apply is still exactly one undoable placement.
    stdout, stderr = run(['--puzzle', near_win],
                         'note 1 1 5\nstatus\nhint all\nstatus\nnotes 1 1\n'
                         'hint apply\nstatus\nundo\nstatus\nnotes 1 1\nquit\n')
    assert stdout.count('Notes for row 1 col 1: 5') == 2, stdout
    assert stdout.count('undo 1, redo 0') == 2, stdout
    assert 'undo 2, redo 0' in stdout and 'undo 1, redo 1' in stdout, stdout
    assert stdout.count('Hint (only candidate): row 1 col 1 -> 5.') >= 1
    assert 'Applied hint (only candidate): row 1 col 1 -> 5.' in stdout
    assert not stderr
    checks += 1

    # A solved board has no hints; wrong moves block listing just as they
    # block preview/apply, without clearing or undoing the player's entries.
    stdout, stderr = run(['--puzzle', solution], 'hint all\nquit\n')
    assert 'Puzzle already solved; no hint needed.' in stdout and not stderr
    checks += 1
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 1\nstatus\nhint all\nstatus\nquit\n')
    assert 'Cannot list hints: correct the existing mistakes first.' in stdout
    assert 'Logical hints (' not in stdout
    assert stdout.count('undo 1, redo 0') == 2 and not stderr
    checks += 1

    # Apply every immediately forced hint as a single undoable action, unlike
    # sequential setters that would consume one history entry per cell.
    two_gaps = '0' + solution[1:80] + '0'
    stdout, stderr = run(['--puzzle', two_gaps],
                         'note 1 1 5\nhint all\nstatus\nhint apply all\n'
                         'status\nundo\nstatus\nnotes 1 1\nredo\nstatus\n'
                         'hint apply all\nhint apply all extra\nquit\n')
    assert 'Logical hints (2):' in stdout, stdout
    assert 'Applied 2 logical hints in one undoable move.' in stdout, stdout
    assert stdout.count('SOLVED!') >= 1, stdout
    assert 'undo 2, redo 0' in stdout and 'undo 1, redo 1' in stdout, stdout
    assert 'Notes for row 1 col 1: 5' in stdout, stdout
    assert 'Puzzle already solved; no hint needed.' in stdout, stdout
    assert stdout.count('Error: unknown command or invalid arguments') == 1
    assert not stderr
    checks += 1

    # Incorrect entries block group application. No partial placements, no
    # new undo entry and no stored-solution digits are revealed.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 1\nstatus\nhint apply all\nstatus\n'
                         'hint apply all extra\nquit\n')
    assert 'Cannot apply hints: correct the existing mistakes first.' in stdout
    assert 'Applied ' not in stdout
    assert stdout.count('undo 1, redo 0') == 2
    assert stdout.count('Error: unknown command or invalid arguments') == 1
    assert not stderr
    checks += 1

    # Iterative forced-single chain reaches deductions that were NOT present
    # in the initial hint-all snapshot. Preview is repeatable and read-only.
    # The standard 30-given sample has 16 immediate singles but 51 reachable
    # successive forced placements, solving it without guessing.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'hint all\nhint chain\nstatus\nhint chain\nstatus\n'
                         'hint apply chain\nstatus\nundo\nstatus\n'
                         'redo\nstatus\nhint apply chain extra\nquit\n')
    assert 'Logical hints (16):' in stdout, stdout
    assert stdout.count('Logical hint chain (51 steps):') == 2, stdout
    assert stdout.count('Step 1 (only candidate): row 5 col 5 -> 5.') == 2, stdout
    assert stdout.count('Step 51 ') == 2, stdout
    assert 'Applied 51 chained logical hints in one undoable move.' in stdout
    assert 'Progress: 30/81 filled' in stdout and 'Progress: 81/81 filled' in stdout
    assert stdout.count('undo 0, redo 0') == 2
    assert 'undo 1, redo 0' in stdout and 'undo 0, redo 1' in stdout
    assert stdout.count('Error: unknown command or invalid arguments') == 1
    assert not stderr
    checks += 1

    # Users can request a short teaching sequence rather than applying all
    # 51 deductions at once. Preview is read-only; apply 3 records one Undo.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'hint chain 3\nstatus\nhint chain 1\nstatus\n'
                         'hint apply chain 3\nstatus\nundo\nstatus\n'
                         'redo\nstatus\nquit\n')
    assert 'Logical hint chain (3 steps):' in stdout, stdout
    assert 'Logical hint chain (1 steps):' in stdout, stdout
    assert 'Step 3 ' in stdout and 'Step 4 ' not in stdout, stdout
    assert 'Applied 3 chained logical hints in one undoable move.' in stdout
    assert stdout.count('Progress: 30/81 filled') == 3, stdout
    assert stdout.count('Progress: 33/81 filled') == 2, stdout
    assert stdout.count('undo 0, redo 0') == 2
    assert 'undo 1, redo 0' in stdout and 'undo 0, redo 1' in stdout
    assert not stderr
    checks += 1

    # Reject zero, >81, nondecimal and extra arguments before looking at
    # candidate digits. Invalid requests are history/board neutral.
    invalid_chains = [
        'hint chain 0', 'hint chain 82', 'hint chain -1',
        'hint chain 3 extra', 'hint chain 3.0',
        'hint apply chain 0', 'hint apply chain 82',
        'hint apply chain nope', 'hint apply chain 3 extra',
    ]
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'status\n' + '\n'.join(invalid_chains) +
                         '\nstatus\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(invalid_chains)
    assert stdout.count('Progress: 30/81 filled') == 2
    assert stdout.count('undo 0, redo 0') == 2
    assert 'Applied ' not in stdout and 'Logical hint chain (' not in stdout
    assert not stderr
    checks += 1

    # Existing incorrect digits block both preview and group application;
    # neither command adds an undo entry or leaks the cached solution.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 1\nstatus\nhint chain\n'
                         'hint apply chain\nstatus\nquit\n')
    assert 'Cannot preview hint chain: correct the existing mistakes first.' in stdout
    assert 'Cannot apply hints: correct the existing mistakes first.' in stdout
    assert 'Logical hint chain (' not in stdout
    assert stdout.count('undo 1, redo 0') == 2 and not stderr
    checks += 1

    # This 25-clue puzzle has a unique solution and no naked singles; only
    # the hidden-single column search can report the first forced step.
    hidden_single_puzzle = '500600902000105308000000500800001020000003000010920800060500004280000000305000070'
    stdout, stderr = run(['--puzzle', hidden_single_puzzle],
                         'hint\nstatus\nhint\nstatus\nquit\n')
    assert stdout.count('Hint (only place in column 8): row 7 col 8 -> 8.') == 2, stdout
    assert stdout.count('undo 0, redo 0') == 2 and not stderr
    checks += 1
    # This 25-clue puzzle cannot be completed by singles alone. The chain
    # stops when deductions are exhausted rather than guessing from the
    # stored unique answer, and all 8 steps form one reversible batch.
    stdout, stderr = run(['--puzzle', hidden_single_puzzle],
                         'hint chain\nstatus\nhint apply chain\n'
                         'status\nhint apply chain\nstatus\nundo\nstatus\nquit\n')
    assert 'Logical hint chain (8 steps):' in stdout, stdout
    assert 'Step 1 (only place in column 8): row 7 col 8 -> 8.' in stdout
    assert stdout.count('Applied 8 chained logical hints in one undoable move.') == 1
    assert 'No simple hint found. Try candidates ROW COL.' in stdout
    assert 'SOLVED!' not in stdout
    assert stdout.count('undo 1, redo 0') == 2 and 'undo 0, redo 1' in stdout
    assert not stderr
    checks += 1

    # Listing all hidden singles must be deterministic, deduplicate cells
    # forced by multiple units, and leave the live board and history alone.
    stdout, stderr = run(['--puzzle', hidden_single_puzzle],
                         'hint all\nstatus\nhint all\nstatus\nquit\n')
    lines = [line for line in stdout.splitlines() if line.startswith('Hint (')]
    assert lines and len(lines) % 2 == 0, stdout
    midpoint = len(lines) // 2
    assert lines[:midpoint] == lines[midpoint:], stdout
    places = [tuple(map(int, re.search(r'row (\d+) col (\d+) ->', line).groups()))
              for line in lines[:midpoint]]
    assert len(places) == len(set(places)), stdout
    assert lines[0] == 'Hint (only place in column 8): row 7 col 8 -> 8.', stdout
    assert 'Logical hints (' in stdout and stdout.count('undo 0, redo 0') == 2
    assert all('only place' in line or 'only candidate' in line for line in lines)
    assert not stderr
    checks += 1

    # Transposition preserves unique solutions and turns the above hidden
    # column single into a hidden row single. No answer lookup is permitted.
    hidden_row_puzzle = '500800023000001680000000005610009500000002000050130000935008000000200007280000400'
    stdout, stderr = run(['--puzzle', hidden_row_puzzle],
                         'hint\nstatus\nquit\n')
    assert 'Hint (only place in row 8): row 8 col 7 -> 8.' in stdout, stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # A completed valid grid is not offered any irrelevant candidate hint.
    stdout, stderr = run(['--puzzle', solution], 'hint\nquit\n')
    assert 'Puzzle already solved; no hint needed.' in stdout and not stderr
    checks += 1

    # Applying a logical single is explicitly opt-in and undoable;
    # previewing hints must remain observational. A solved board cannot
    # receive a second automatic move.
    stdout, stderr = run(['--puzzle', near_win],
                         'hint\nstatus\nhint apply\nstatus\nundo\nstatus\n'
                         'redo\nstatus\nhint apply\nquit\n')
    assert 'Hint (only candidate): row 1 col 1 -> 5.' in stdout
    assert 'Applied hint (only candidate): row 1 col 1 -> 5.' in stdout
    assert 'SOLVED! All cells are correct.' in stdout
    assert 'Puzzle already solved; no hint needed.' in stdout
    assert stdout.count('undo 0, redo 0') == 1
    assert 'undo 1, redo 0' in stdout and 'undo 0, redo 1' in stdout
    assert not stderr
    checks += 1

    # Hidden singles take the same normal setter/undo route as manually
    # entered numbers, without choosing from the stored solution.
    stdout, stderr = run(['--puzzle', hidden_single_puzzle],
                         'hint apply\nstatus\nundo\nstatus\nquit\n')
    assert 'Applied hint (only place in column 8): row 7 col 8 -> 8.' in stdout
    assert 'undo 1, redo 0' in stdout and 'undo 0, redo 1' in stdout
    assert not stderr
    checks += 1

    # If the board already contains a rule-legal but incorrect entry, a
    # hint may no longer be sound. Refuse automatic placement without
    # changing any additional cell or recording an undo step.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 1\nstatus\nhint apply\nstatus\n'
                         'hint apply extra\nhint preview\nquit\n')
    assert stdout.count('Cannot apply hint: correct the existing mistakes first.') == 1
    assert stdout.count('undo 1, redo 0') == 2
    assert stdout.count('Error: unknown command or invalid arguments') == 2
    assert not stderr
    checks += 1

    # Auto-notes fills all live-rule candidates with one undoable edit;
    # repeating it is history-neutral and resume persists the generated notes.
    auto_save = folder / 'generated pencil notes.save'
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         f'notes 1 3\nauto-notes\nnotes 1 3\nstatus\n'
                         f'auto-notes\nstatus\nundo\nnotes 1 3\n'
                         f'redo\nnotes 1 3\nsave {auto_save}\nquit\n')
    assert stdout.count('Notes for row 1 col 3: 1 2 4') == 2, stdout
    assert stdout.count('Notes for row 1 col 3:\n') == 2, stdout
    assert stdout.count('undo 1, redo 0') == 2, stdout
    assert auto_save.is_file() and not stderr
    checks += 1
    stdout, stderr = run(['--resume', auto_save],
                         'notes 1 3\nauto-notes wrong\n'
                         'status\nquit\n')
    assert 'Notes for row 1 col 3: 1 2 4' in stdout
    assert 'Error: unknown command or invalid arguments' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # Pruning removes only marks made illegal by a subsequent placement,
    # never fills missing candidates, and is one undoable/idempotent edit.
    prune_save = folder / 'pruned personal notes.save'
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         f'note 1 3 1\nnote 1 3 4\nnote 1 3 8\n'
                         f'set 1 6 4\nprune-notes\nnotes 1 3\nstatus\n'
                         f'prune-notes\nstatus\nundo\nnotes 1 3\n'
                         f'redo\nnotes 1 3\nsave {prune_save}\nquit\n')
    assert stdout.count('Notes for row 1 col 3: 1\n') == 2, stdout
    assert 'Notes for row 1 col 3: 1 4 8' in stdout
    assert stdout.count('undo 5, redo 0') == 2, stdout
    assert prune_save.is_file() and not stderr
    checks += 1
    stdout, stderr = run(['--resume', prune_save],
                         'notes 1 3\nprune-notes extra\nstatus\nquit\n')
    assert 'Notes for row 1 col 3: 1' in stdout
    assert 'Error: unknown command or invalid arguments' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # A reset on an untouched board must not create phantom undo history.
    stdout, stderr = run(['--puzzle', near_win], 'reset\nstatus\nundo\nquit\n')
    assert 'undo 0, redo 0' in stdout and 'no action to undo or redo' in stdout
    assert not stderr
    checks += 1
    # Repeating reset after clearing notes must remain a no-op: a single undo
    # restores the pre-reset notes instead of undoing a phantom reset.
    stdout, stderr = run(['--puzzle', near_win],
                         'note 1 1 5\nreset\nreset\nundo\nnotes 1 1\nquit\n')
    assert 'Notes for row 1 col 1: 5' in stdout and not stderr
    checks += 1
    # Verify immutable givens, syntax error resilience and strict conflicts.
    stdout, stderr = run(['--puzzle', near_win], 'set 1 1 4\nset 1\nset 1 2 3\ncheck\nquit\n')
    assert 'placement conflicts with Sudoku rules' in stdout
    assert 'unknown command or invalid arguments' in stdout
    assert 'cannot modify an original clue' in stdout
    checks += 1
    stdout, stderr = run(['--puzzle', '0' * 81], exit_code=3)
    assert 'unique solution' in stderr and stdout == ''
    checks += 1
    stdout, stderr = run(['--file', fixtures / 'unique.txt'], 'check\nquit\n')
    assert 'Started new game' in stdout and 'Check:' in stdout
    checks += 1
    stdout, stderr = run(['--seed', '42', '--difficulty', 'easy'], 'status\nquit\n')
    assert 'Generated unique easy puzzle' in stdout and 'Empty:' in stdout
    checks += 1
    stdout, stderr = run(['--seed', 'invalid', '--difficulty', 'easy'], exit_code=2)
    assert 'invalid seed' in stderr
    checks += 1
    # Quit without save does not create a file; explicit save only.
    unsaved = folder / 'unsaved.save'
    stdout, stderr = run(['--puzzle', near_win, '--save', unsaved], 'quit\n')
    assert not unsaved.exists()
    checks += 1

print(f'GAME E2E PASS: {checks} checks (win, undo/redo, notes, atomic save/resume, corruption, generated game, CLI)')
