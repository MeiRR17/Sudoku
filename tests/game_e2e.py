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

    # A verified unique-solution puzzle has a column Swordfish for digit 2:
    # columns 4,6,7 restrict candidate positions to rows 3,7,9.
    swordfish_puzzle = (
        '500600902000105308000000500800001020000003000'
        '010920800060500004280000000305000070'
    )
    swordfish_transpose = ''.join(
        swordfish_puzzle[row * 9 + col]
        for col in range(9) for row in range(9)
    )
    assert len(swordfish_puzzle) == len(swordfish_transpose) == 81
    stdout, stderr = run(['--puzzle', swordfish_puzzle],
                         'hint swordfish\nhint swordfish 1\nstatus\nquit\n')
    column_fish = (
        'Swordfish 1 (columns 4,6,7; rows 3,7,9; digit 2): '
        'sources r3c4 r9c4 r3c6 r7c6 r9c6 r7c7 r9c7; '
        'eliminate r3c2 r3c3'
    )
    assert stdout.count(column_fish) == 2, stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--puzzle', swordfish_transpose],
                         'hint swordfish 1\nstatus\nquit\n')
    row_fish = (
        'Swordfish 1 (rows 4,6,7; columns 3,7,9; digit 2): '
        'sources r4c3 r4c9 r6c3 r6c7 r6c9 r7c7 r7c9; '
        'eliminate r2c3 r3c3'
    )
    assert row_fish in stdout and 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--puzzle', swordfish_puzzle],
                         'note 3 2 2\nnote 3 3 2\nnote 3 2 7\n'
                         'status\nhint apply swordfish 1\nnotes 3 2\n'
                         'notes 3 3\nstatus\nundo\nnotes 3 2\n'
                         'status\nredo\nhint apply swordfish 1\n'
                         'status\nquit\n')
    assert 'Removed 2 Swordfish pencil candidates in one undoable edit.' in stdout
    assert 'Notes for row 3 col 2: 7\n' in stdout
    assert 'Notes for row 3 col 3:\n' in stdout
    assert 'Notes for row 3 col 2: 2 7\n' in stdout
    assert stdout.count('undo 4, redo 0') == 2, stdout
    assert 'undo 3, redo 1' in stdout
    assert 'No matching Swordfish pencil notes to remove; history unchanged.' in stdout
    assert not stderr
    checks += 1

    stdout, stderr = run(['--puzzle', swordfish_puzzle],
                         'hint apply swordfish\nstatus\nundo\nquit\n')
    assert 'No matching Swordfish pencil notes to remove; history unchanged.' in stdout
    assert 'undo 0, redo 0' in stdout
    assert 'Error: no action to undo or redo' in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--puzzle', solution],
                         'hint swordfish\nhint apply swordfish\nstatus\nquit\n')
    assert stdout.count('Puzzle already solved; no Swordfish hint needed.') == 2
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 9 4\nhint swordfish\nhint apply swordfish\nstatus\nquit\n')
    assert 'Cannot preview Swordfish: correct the existing mistakes first.' in stdout
    assert 'Cannot apply Swordfish: correct the existing mistakes first.' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    invalid_swordfish = [
        'hint swordfish 0', 'hint swordfish 82', 'hint swordfish -1',
        'hint swordfish nope', 'hint swordfish 1 extra',
        'hint apply swordfish 0', 'hint apply swordfish 82',
        'hint apply swordfish -1', 'hint apply swordfish nope',
        'hint apply swordfish 1 extra',
    ]
    stdout, stderr = run(['--puzzle', swordfish_puzzle],
                         'status\n' + '\n'.join(invalid_swordfish) +
                         '\nstatus\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(invalid_swordfish)
    assert stdout.count('undo 0, redo 0') == 2
    assert 'Swordfish 1 ' not in stdout and not stderr
    checks += 1

    # Hidden triple: column 9 contains digit 2/7/8 only in rows 1,2,3;
    # unlike a naked triple these cells have additional candidates (digit 4).
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'hint hidden-triples\nhint hidden-triples 1\nstatus\nquit\n')
    first_hidden_triple = (
        'Hidden triple 1 in column 9: r1c9 + r2c9 + r3c9 '
        'reserve 2,7,8; remove extras r1c9(4) r2c9(4) r3c9(4)'
    )
    assert stdout.count(first_hidden_triple) == 2, stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'note 1 9 4\nnote 2 9 4\nnote 3 9 4\n'
                         'note 1 9 1\nstatus\nhint apply hidden-triples 1\n'
                         'notes 1 9\nnotes 2 9\nnotes 3 9\nstatus\n'
                         'undo\nnotes 1 9\nstatus\nredo\n'
                         'hint apply hidden-triples 1\nstatus\nquit\n')
    assert 'Removed 3 hidden-triple pencil candidates in one undoable edit.' in stdout
    assert 'Notes for row 1 col 9: 1\n' in stdout
    assert 'Notes for row 2 col 9:\n' in stdout
    assert 'Notes for row 3 col 9:\n' in stdout
    assert 'Notes for row 1 col 9: 1 4\n' in stdout
    assert stdout.count('undo 5, redo 0') == 2, stdout
    assert 'undo 4, redo 1' in stdout
    assert 'No matching hidden-triple pencil notes to remove; history unchanged.' in stdout
    assert not stderr
    checks += 1

    # No matching marks means no new snapshot, and no solution insertion.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'hint apply hidden-triples\nstatus\nundo\nquit\n')
    assert 'No matching hidden-triple pencil notes to remove; history unchanged.' in stdout
    assert 'undo 0, redo 0' in stdout
    assert 'Error: no action to undo or redo' in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--puzzle', solution],
                         'hint hidden-triples\nhint apply hidden-triples\nstatus\nquit\n')
    assert stdout.count('Puzzle already solved; no hidden triple hint needed.') == 2
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 9 4\nhint hidden-triples\n'
                         'hint apply hidden-triples\nstatus\nquit\n')
    assert 'Cannot preview hidden triples: correct the existing mistakes first.' in stdout
    assert 'Cannot apply hidden triples: correct the existing mistakes first.' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    invalid_hidden_triples = [
        'hint hidden-triples 0', 'hint hidden-triples 82',
        'hint hidden-triples -1', 'hint hidden-triples nope',
        'hint hidden-triples 1 extra',
        'hint apply hidden-triples 0', 'hint apply hidden-triples 82',
        'hint apply hidden-triples -1', 'hint apply hidden-triples nope',
        'hint apply hidden-triples 1 extra',
    ]
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'status\n' + '\n'.join(invalid_hidden_triples) +
                         '\nstatus\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(invalid_hidden_triples)
    assert stdout.count('undo 0, redo 0') == 2
    assert 'Hidden triple 1 ' not in stdout and not stderr
    checks += 1

    # Naked triple in the classic unique puzzle: r3c4, r3c5 and r3c6
    # reserve digits 2,3,4. The preview is deterministic and read-only.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'hint triples\nhint triples 1\nstatus\nquit\n')
    first_triple = ('Triple 1 in row 3: r3c4 + r3c5 + r3c6 '
                    'reserve 2,3,4; eliminate from '
                    'r3c1(2) r3c7(3,4) r3c9(2,4)')
    assert stdout.count(first_triple) == 2, stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # User notes may be arbitrary legal choices; only the matching bits are
    # removed. One grouped Undo restores them and Redo repeats the removal.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'note 3 1 2\nnote 3 7 3\nnote 3 9 2\n'
                         'note 3 1 7\nstatus\nhint apply triples 1\n'
                         'notes 3 1\nnotes 3 7\nnotes 3 9\nstatus\n'
                         'undo\nnotes 3 1\nstatus\nredo\n'
                         'hint apply triples 1\nstatus\nquit\n')
    assert 'Removed 3 triple pencil candidates in one undoable edit.' in stdout
    assert 'Notes for row 3 col 1: 7\n' in stdout
    assert 'Notes for row 3 col 7:\n' in stdout
    assert 'Notes for row 3 col 9:\n' in stdout
    assert 'Notes for row 3 col 1: 2 7\n' in stdout
    assert stdout.count('undo 5, redo 0') == 2, stdout
    assert 'undo 4, redo 1' in stdout
    assert 'No matching triple pencil notes to remove; history unchanged.' in stdout
    assert not stderr
    checks += 1

    # A preview never inserts digits or changes the saved state; applying
    # without handwritten notes is a true history-neutral no-op.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'hint apply triples\nstatus\nundo\nquit\n')
    assert 'No matching triple pencil notes to remove; history unchanged.' in stdout
    assert 'undo 0, redo 0' in stdout
    assert 'Error: no action to undo or redo' in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--puzzle', solution],
                         'hint triples\nhint apply triples\nstatus\nquit\n')
    assert stdout.count('Puzzle already solved; no triple hint needed.') == 2
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 9 4\nhint triples\nhint apply triples\nstatus\nquit\n')
    assert 'Cannot preview triples: correct the existing mistakes first.' in stdout
    assert 'Cannot apply triples: correct the existing mistakes first.' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    invalid_triples = [
        'hint triples 0', 'hint triples 82', 'hint triples -1',
        'hint triples nope', 'hint triples 1 extra',
        'hint apply triples 0', 'hint apply triples 82',
        'hint apply triples -1', 'hint apply triples nope',
        'hint apply triples 1 extra',
    ]
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'status\n' + '\n'.join(invalid_triples) +
                         '\nstatus\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(invalid_triples)
    assert stdout.count('undo 0, redo 0') == 2
    assert 'Triple 1 ' not in stdout and not stderr
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

    # Verify the column-oriented transpose, not only row-based X-Wings.
    # The classic fixture has two actionable column patterns, including a
    # digit-6 rectangle with sources in columns 4,6 and rows 1,9.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'hint x-wing 1\nhint x-wing 2\nstatus\nquit\n')
    col_xwing = (
        'X-Wing 1 (columns 4,6; rows 1,9; digit 6): '
        'corners r1c4 r9c4 r1c6 r9c6; eliminate r9c7'
    )
    second_col_xwing = (
        'X-Wing 2 (columns 4,6; rows 4,7; digit 7): '
        'corners r4c4 r7c4 r4c6 r7c6; eliminate r7c3 r4c7'
    )
    assert stdout.count(col_xwing) == 2, stdout
    assert stdout.count(second_col_xwing) == 1, stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # A board with only one blank has no X-Wing elimination.
    stdout, stderr = run(['--puzzle', near_win],
                         'hint x-wing\nhint apply x-wing\nstatus\nquit\n')
    assert stdout.count('No actionable X-Wings found.') == 2
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

    # One CLI command replaces all notes on a cell and consumes one Undo.
    stdout, stderr = run(['--puzzle', near_win],
                         'notes set 1 1 135\nnotes 1 1\nstatus\n'
                         'notes set 1 1 135\nstatus\n'
                         'notes set 1 1 79\nnotes 1 1\nstatus\n'
                         'undo\nnotes 1 1\nstatus\nredo\nnotes 1 1\n'
                         'notes clear 1 1\nnotes 1 1\nstatus\n'
                         'undo\nnotes 1 1\nquit\n')
    assert 'Notes for row 1 col 1: 1 3 5\n' in stdout
    assert 'Notes for row 1 col 1: 7 9\n' in stdout
    assert 'Notes for row 1 col 1:\n' in stdout
    assert stdout.count('undo 1, redo 0') == 2, stdout
    assert 'undo 2, redo 0' in stdout and 'undo 1, redo 1' in stdout
    assert 'undo 3, redo 0' in stdout and 'undo 2, redo 1' in stdout
    assert not stderr
    checks += 1

    # '-' clears exactly one cell; same mask remains history-neutral.
    stdout, stderr = run(['--puzzle', near_win],
                         'notes set 1 1 913\nnotes set 1 1 139\n'
                         'status\nnotes set 1 1 -\nnotes 1 1\n'
                         'status\nnotes clear 1 1\nstatus\nquit\n')
    assert stdout.count('undo 1, redo 0') == 1, stdout
    assert stdout.count('undo 2, redo 0') == 2, stdout
    assert 'Notes for row 1 col 1:\n' in stdout and not stderr
    checks += 1

    # Fail closed on duplicate, oversized or illegal pencil sequences,
    # missing arguments, clue cells, and extra trailing tokens.
    bad_notes = [
        'notes set 1 1 113', 'notes set 1 1 0', 'notes set 1 1 112345678',
        'notes set 1 1 12a', 'notes set 1 1 1,2',
        'notes set 1 1', 'notes set 1 1 - trailing',
        'notes clear 1 1 trailing', 'notes set 1 1 12 trailing',
        'notes set 1 1 12345 trailing extra',
    ]
    stdout, stderr = run(['--puzzle', near_win],
                         'status\n' + '\n'.join(bad_notes) +
                         '\nnotes 1 1\nstatus\nnotes set 1 2 135\n'
                         'notes set 1 1 135\nset 1 1 5\n'
                         'notes set 1 1 1\nstatus\nquit\n')
    assert stdout.count('Error:') >= len(bad_notes) + 2, stdout
    assert 'Notes for row 1 col 1:\n' in stdout
    assert stdout.count('undo 0, redo 0') == 2
    assert 'Error: cannot modify an original clue' in stdout
    assert 'Error: pencil notes only allowed in empty cells' in stdout
    assert 'undo 2, redo 0' in stdout and not stderr
    checks += 1

    # Add/remove multiple pencil marks in one Undo without replacing the
    # entire set. Redundant add/remove calls must be history neutral.
    stdout, stderr = run(['--puzzle', near_win],
                         'notes set 1 1 1\nnotes add 1 1 35\nnotes 1 1\n'
                         'status\nnotes add 1 1 53\nstatus\n'
                         'notes remove 1 1 13\nnotes 1 1\nstatus\n'
                         'notes remove 1 1 31\nstatus\n'
                         'undo\nnotes 1 1\nstatus\nredo\nnotes 1 1\n'
                         'status\nquit\n')
    assert 'Notes for row 1 col 1: 1 3 5\n' in stdout
    assert 'Notes for row 1 col 1: 5\n' in stdout
    assert stdout.count('undo 2, redo 0') == 2, stdout
    assert stdout.count('undo 3, redo 0') == 3, stdout
    assert 'undo 2, redo 1' in stdout and not stderr
    checks += 1

    # Mask 0 is a no-op in add/remove; bad digits and surplus tokens do
    # not mutate state. Marks cannot be added to a given or filled cell.
    bad_note_modifiers = [
        'notes add 1 1 11', 'notes remove 1 1 11',
        'notes add 1 1 0', 'notes remove 1 1 x',
        'notes add 1 1 1234567890',
        'notes add 1 1 12 extra', 'notes remove 1 1 12 extra',
        'notes remove 1 1', 'notes add 0 1 12'
    ]
    stdout, stderr = run(['--puzzle', near_win],
                         'status\n' + '\n'.join(bad_note_modifiers) +
                         '\nnotes 1 1\nstatus\n'
                         'notes add 1 1 -\nnotes remove 1 1 -\nstatus\n'
                         'notes add 1 2 1\nnotes set 1 1 15\nset 1 1 5\n'
                         'notes remove 1 1 1\nstatus\nquit\n')
    assert stdout.count('Error:') >= len(bad_note_modifiers)+2, stdout
    assert 'Notes for row 1 col 1:\n' in stdout
    assert stdout.count('undo 0, redo 0') == 3
    assert 'Error: cannot modify an original clue' in stdout
    assert 'Error: pencil notes only allowed in empty cells' in stdout
    assert 'undo 2, redo 0' in stdout and not stderr
    checks += 1

    # A single-cell candidate refresh is one Undo; repeating 'fill' is a
    # no-op, unlike global auto-notes which changes all remaining cells.
    stdout, stderr = run(['--puzzle', near_win],
                         'notes fill 1 1\nnotes 1 1\nstatus\n'
                         'notes fill 1 1\nstatus\nundo\nnotes 1 1\n'
                         'status\nredo\nnotes 1 1\nstatus\nquit\n')
    assert stdout.count('Notes for row 1 col 1: 5\n') == 2, stdout
    assert 'Notes for row 1 col 1:\n' in stdout
    assert stdout.count('undo 1, redo 0') == 3
    assert 'undo 0, redo 1' in stdout and not stderr
    checks += 1

    # Cell prune retains manually selected marks that are still legal,
    # drops stale notes, and does not insert any missing candidate.
    stdout, stderr = run(['--puzzle', near_win],
                         'notes set 1 1 159\nnotes prune 1 1\n'
                         'notes 1 1\nstatus\nundo\nnotes 1 1\n'
                         'status\nredo\nnotes 1 1\nstatus\n'
                         'notes prune 1 1\nstatus\nquit\n')
    assert 'Notes for row 1 col 1: 5\n' in stdout
    assert 'Notes for row 1 col 1: 1 5 9\n' in stdout
    assert stdout.count('undo 2, redo 0') == 3
    assert 'undo 1, redo 1' in stdout and not stderr
    checks += 1

    # Fill after manual notes replaces just one cell with its legal
    # candidates, not every other cell's handwritten notes.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'notes set 1 3 9\nnotes set 1 4 8\n'
                         'notes fill 1 3\nnotes 1 3\nnotes 1 4\n'
                         'status\nundo\nnotes 1 3\nnotes 1 4\nquit\n')
    assert 'Notes for row 1 col 3: 1 2 4\n' in stdout
    assert 'Notes for row 1 col 3: 9\n' in stdout
    assert stdout.count('Notes for row 1 col 4: 8\n') == 2
    assert 'undo 3, redo 0' in stdout and not stderr
    checks += 1

    # Invalid coordinates, filled or immutable cells, and surplus tokens
    # fail without history changes. Accept no candidates only as a legal
    # empty-cell note set; never write digits to the board.
    bad_cell_note_commands = [
        'notes fill 0 1', 'notes prune 1 0', 'notes fill 10 1',
        'notes fill 1 1 extra', 'notes prune 1 1 extra',
        'notes fill 1', 'notes prune 1',
    ]
    stdout, stderr = run(['--puzzle', near_win],
                         'status\n' + '\n'.join(bad_cell_note_commands) +
                         '\nstatus\nnotes fill 1 2\nnotes prune 1 2\n'
                         'status\nnotes fill 1 1\nset 1 1 5\n'
                         'notes prune 1 1\nstatus\nquit\n')
    assert stdout.count('Error:') >= len(bad_cell_note_commands)+3
    assert stdout.count('undo 0, redo 0') == 3
    assert 'Error: cannot modify an original clue' in stdout
    assert 'Error: pencil notes only allowed in empty cells' in stdout
    assert 'undo 2, redo 0' in stdout and not stderr
    checks += 1

    # Fill exactly one row. Notes in a different row are preserved;
    # repeated fill is history neutral and Undo reverses all row changes.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'notes set 2 2 9\nnotes fill row 1\n'
                         'notes 1 3\nnotes 2 2\nstatus\n'
                         'notes fill row 1\nstatus\nundo\nnotes 1 3\n'
                         'notes 2 2\nstatus\nredo\nnotes 1 3\nstatus\nquit\n')
    assert 'Notes for row 1 col 3: 1 2 4\n' in stdout
    assert stdout.count('Notes for row 2 col 2: 9\n') == 2
    assert 'Notes for row 1 col 3:\n' in stdout
    assert stdout.count('undo 2, redo 0') == 3
    assert 'undo 1, redo 1' in stdout and not stderr
    checks += 1

    # Prune marks only in row 1, adding no candidate digits or history
    # for unchanged cells. Undo restores both dropped handwritten marks.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'notes set 1 3 19\nnotes set 1 4 8\n'
                         'notes set 2 2 9\nnotes prune row 1\n'
                         'notes 1 3\nnotes 1 4\nnotes 2 2\nstatus\n'
                         'undo\nnotes 1 3\nnotes 1 4\nstatus\nquit\n')
    assert 'Notes for row 1 col 3: 1\n' in stdout
    assert 'Notes for row 1 col 3: 1 9\n' in stdout
    assert 'Notes for row 1 col 4:\n' in stdout
    assert 'Notes for row 1 col 4: 8\n' in stdout
    assert 'Notes for row 2 col 2: 9\n' in stdout
    assert 'undo 4, redo 0' in stdout and 'undo 3, redo 1' in stdout
    assert not stderr
    checks += 1

    # Both a column and a box can be refreshed independently; outside
    # their selected nine cells existing pencil marks must be unchanged.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'notes fill column 3\nnotes 1 3\nnotes 1 4\n'
                         'notes fill box 1\nnotes 1 4\nnotes 1 3\n'
                         'status\nundo\nstatus\nquit\n')
    assert stdout.count('Notes for row 1 col 3: 1 2 4\n') == 2
    assert stdout.count('Notes for row 1 col 4:\n') == 2
    assert 'undo 2, redo 0' in stdout and 'undo 1, redo 1' in stdout
    assert not stderr
    checks += 1

    # Reject invalid units, bounds and surplus tokens with no mutations.
    bad_unit_notes = [
        'notes fill row 0', 'notes fill row 10',
        'notes prune column 0', 'notes prune box 10',
        'notes fill block 1', 'notes prune boxes 1',
        'notes fill row -1', 'notes fill box nope',
        'notes fill row', 'notes prune column',
        'notes fill row 1 extra', 'notes prune box 1 extra',
    ]
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'status\n' + '\n'.join(bad_unit_notes) +
                         '\nstatus\nnotes fill box 1\nstatus\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(bad_unit_notes)
    assert stdout.count('undo 0, redo 0') == 2
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Dedicated pencil grid: 3x3 mini-cells show manually selected notes,
    # while candidates mode reflects only legal digits in the live board.
    # Neither read-only view can mutate notes, placed digits or history.
    stdout, stderr = run(['--puzzle', near_win],
                         'notes set 1 1 19\nshow notes\nshow candidates\n'
                         'notes 1 1\nstatus\nquit\n')
    handwritten = stdout.split(
        "Handwritten notes grid ('.' = absent; [d] = filled):", 1)[1].split(
        "Live candidates grid ('.' = absent; [d] = filled):", 1)[0]
    legal_grid = stdout.split(
        "Live candidates grid ('.' = absent; [d] = filled):", 1)[1].split(
        'Notes for row 1 col 1:', 1)[0]
    assert '|1..        |' in handwritten and '|..9        |' in handwritten
    assert ' 1 |... [3] [4]|' in handwritten
    assert ' 1 |.5. [3] [4]|' in legal_grid
    assert '|1..        |' not in legal_grid
    assert 'Notes for row 1 col 1: 1 9\n' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Classic puzzle: r1c3 currently permits 1,2,4; show notes stays
    # empty but legal-grid candidates appear in the correct mini-cell.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'show notes\nshow candidates\nstatus\nquit\n')
    handwritten = stdout.split(
        "Handwritten notes grid ('.' = absent; [d] = filled):", 1)[1].split(
        "Live candidates grid ('.' = absent; [d] = filled):", 1)[0]
    legal_grid = stdout.split(
        "Live candidates grid ('.' = absent; [d] = filled):", 1)[1].split(
        'Progress:', 1)[0]
    assert ' 1 |[5] [3] ...|' in handwritten
    assert ' 1 |[5] [3] 4..|' in legal_grid
    assert '|        12.|' in legal_grid
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # Viewing grids across Undo/Redo adds no phantom history entries.
    stdout, stderr = run(['--puzzle', near_win],
                         'notes set 1 1 5\nshow notes\nundo\nshow notes\n'
                         'redo\nshow candidates\nstatus\nquit\n')
    assert stdout.count("Handwritten notes grid ('.' = absent; [d] = filled):") == 2
    assert stdout.count("Live candidates grid ('.' = absent; [d] = filled):") == 1
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Invalid modifiers and surplus tokens must not be treated as 'show'.
    invalid_shows = [
        'show note', 'show all', 'show notes extra',
        'show candidates extra', 'show 1', 'show candidates 3',
        'show notes x y', 'show pencil', 'show 0'
    ]
    stdout, stderr = run(['--puzzle', near_win],
                         'status\n' + '\n'.join(invalid_shows) +
                         '\nstatus\nshow notes\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(invalid_shows)
    assert stdout.count("Handwritten notes grid ('.' = absent; [d] = filled):") == 1
    assert stdout.count('undo 0, redo 0') == 2 and not stderr
    checks += 1

    # Pencil display survives existing save/resume and still distinguishes
    # player notes from legal candidates after loading a session.
    pencil_view_save = folder / 'pencil view.save'
    stdout, stderr = run(['--puzzle', near_win, '--save', pencil_view_save],
                         'notes set 1 1 19\nsave\nquit\n')
    assert 'Saved to ' in stdout and pencil_view_save.exists() and not stderr
    stdout, stderr = run(['--resume', pencil_view_save],
                         'show notes\nshow candidates\nnotes 1 1\n'
                         'status\nquit\n')
    assert '|1..        |' in stdout and '|..9        |' in stdout
    assert ' 1 |.5. [3] [4]|' in stdout
    assert 'Notes for row 1 col 1: 1 9\n' in stdout and not stderr
    checks += 1

    # Stale manual marks differ from locally legal but unmarked options;
    # audit is read-only and supports whole-board or unit selection.
    stdout, stderr = run(['--puzzle', near_win],
                         'notes set 1 1 19\nnotes audit 1\n'
                         'notes audit row 1\nnotes audit column 1\n'
                         'notes audit box 1\nnotes 1 1\nstatus\nquit\n')
    assert stdout.count('row 1 col 1: stale 1,9; unmarked legal 5') == 4
    assert stdout.count('Pencil audit summary: 1 empty inspected; '
                        '1 cells differ; 2 stale marks; '
                        '1 unmarked legal candidates.') == 4
    assert 'Notes for row 1 col 1: 1 9\n' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Complete candidate set => clean audit, and Undo after audits still
    # returns directly to the original blank pencil state.
    stdout, stderr = run(['--puzzle', near_win],
                         'notes set 1 1 5\nnotes audit\nnotes audit 81\n'
                         'notes audit row 1\nstatus\nundo\nnotes 1 1\n'
                         'status\nquit\n')
    assert stdout.count('0 cells differ; 0 stale marks; '
                        '0 unmarked legal candidates.') == 3
    assert stdout.count('All inspected pencil marks match the current '
                        'legal candidates.') == 3
    assert 'Notes for row 1 col 1:\n' in stdout
    assert 'undo 0, redo 1' in stdout and not stderr
    checks += 1

    # Report limit bounds detail, but never the totals across inspected
    # empty cells. Unmarked legal digits are not actual solution values.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'notes audit 1\nstatus\nquit\n')
    assert 'Pencil audit (all cells; show at most 1):' in stdout
    assert 'row 1 col 3: stale -; unmarked legal 1,2,4' in stdout
    assert 'additional differing cells not listed (raise limit)' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # Unit filters restrict the scan while preserving every handwritten
    # mark and the complete Undo/Redo history.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'notes set 1 3 9\n'
                         'notes audit row 1\nnotes audit column 3\n'
                         'notes audit box 1\nnotes 1 3\nstatus\nquit\n')
    assert stdout.count('row 1 col 3: stale 9; unmarked legal 1,2,4') == 3
    assert 'Pencil audit (row 1):' in stdout
    assert 'Pencil audit (column 3):' in stdout
    assert 'Pencil audit (box 1):' in stdout
    assert 'Notes for row 1 col 3: 9\n' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Invalid scopes, counts and trailing tokens fail without listing or
    # modifying notes.
    invalid_audits = [
        'notes audit 0', 'notes audit 82', 'notes audit -1',
        'notes audit nope', 'notes audit row 0',
        'notes audit row 10', 'notes audit box x',
        'notes audit blocks 1', 'notes audit rows 1',
        'notes audit 1 extra', 'notes audit column 1 extra',
        'notes audit row', 'notes audit column'
    ]
    stdout, stderr = run(['--puzzle', near_win],
                         'status\n' + '\n'.join(invalid_audits) +
                         '\nstatus\nnotes audit 1\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(invalid_audits)
    assert stdout.count('Pencil audit (') == 1
    assert stdout.count('undo 0, redo 0') == 2 and not stderr
    checks += 1

    stdout, stderr = run(['--puzzle', solution],
                         'notes audit\nstatus\nquit\n')
    assert 'Pencil audit summary: 0 empty inspected; 0 cells differ;' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # Candidate analysis is independent of the solved grid, pencil marks,
    # and Undo history. The standard classic puzzle has 51 blanks and a
    # known candidate-count histogram, but no immediate contradictions.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'analyze 2\nstatus\nquit\n')
    assert 'Candidate analysis (51 empty, detail limit 2):' in stdout
    assert ('Candidates per empty cell: 0:0 1:4 2:13 3:17 '
            '4:14 5:2 6:1 7:0 8:0 9:0') in stdout
    assert ('Candidate analysis summary: 0 zero-candidate cells; '
            '0 missing-digit dead ends; 0 contradictions.') in stdout
    assert 'No immediate candidate contradictions found;' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # A locally valid but wrong move may leave an empty cell with no
    # candidates; report it without inserting any solution digits.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 9 4\nanalyze 1\nstatus\n'
                         'undo\nanalyze 1\nstatus\nquit\n')
    assert 'Contradiction: row 7 col 9 has no legal candidates.' in stdout
    assert 'Candidate analysis summary: 1 zero-candidate cells;' in stdout
    assert 'undo 1, redo 0' in stdout
    assert 'undo 0, redo 1' in stdout and not stderr
    checks += 1

    # A different locally valid wrong move leaves no zero-candidate
    # cells, but makes a required digit impossible in column 8.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 1\nanalyze 3\nstatus\nquit\n')
    assert 'Contradiction: digit 1 has no legal position in column 8.' in stdout
    assert 'Candidate analysis summary: 0 zero-candidate cells; ' in stdout
    assert '1 missing-digit dead ends; 1 contradictions.' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Never truncate aggregate counts even when only one contradiction
    # can be shown. A legal wrong move creates multiple dead-end units.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 7 8\nanalyze 1\nstatus\nquit\n')
    assert 'Candidate analysis (50 empty, detail limit 1):' in stdout
    assert 'additional contradictions not listed (raise limit)' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Solved boards have no open candidate slots or impossible digits.
    stdout, stderr = run(['--puzzle', solution],
                         'analyze\nstatus\nquit\n')
    assert 'Candidate analysis (0 empty, detail limit 10):' in stdout
    assert ('Candidate analysis summary: 0 zero-candidate cells; '
            '0 missing-digit dead ends; 0 contradictions.') in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # Reject invalid limits, extra arguments and misleading aliases.
    bad_analyze = ['analyze 0', 'analyze 82', 'analyze -1',
                   'analyze nope', 'analyze 2 extra',
                   'analyze 1 2', 'analyze all']
    stdout, stderr = run(['--puzzle', near_win],
                         'status\n'+'\n'.join(bad_analyze)+
                         '\nstatus\nanalyze 1\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(bad_analyze)
    assert stdout.count('Candidate analysis (') == 1
    assert stdout.count('undo 0, redo 0') == 2 and not stderr
    checks += 1

    # Heatmap labels immutable/player-filled digits with [d] and shows
    # the number of locally legal candidates in each remaining cell.
    stdout, stderr = run(['--puzzle', near_win],
                         'show heatmap\nshow digit 5\nstatus\nquit\n')
    assert 'Candidate heatmap ([d] = filled; 1..9 = legal choices; ! = none):' in stdout
    assert '  1 | 1  [3] [4]|[6] [7] [8]|[9] [1] [2]|' in stdout
    assert 'Heatmap summary: 0 empty cells with no legal candidates.' in stdout
    assert 'Digit 5 map (* = legal empty; # = placed digit; . = unavailable):' in stdout
    assert '  1 | *  [3] [4]|[6] [7] [8]|[9] [1] [2]|' in stdout
    assert 'Digit 5 summary: 8 placed; 1 legal empty locations.' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # Classic puzzle has three candidates for r1c3: 1,2,4. The digit map
    # highlights that legal location without guessing its solved value.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'show heatmap\nshow digit 4\nstatus\nquit\n')
    assert '  1 |[5] [3]  3 |' in stdout
    assert '  1 |[5] [3]  * |' in stdout
    assert 'Digit 4 summary:' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # Both views are read-only even after incorrect manual notes and
    # across undo/redo. Notes must survive every visualization.
    stdout, stderr = run(['--puzzle', near_win],
                         'notes set 1 1 19\nshow heatmap\nshow digit 5\n'
                         'notes 1 1\nstatus\nundo\nshow heatmap\n'
                         'redo\nshow digit 5\nnotes 1 1\nstatus\nquit\n')
    assert stdout.count('Heatmap summary: 0 empty cells with no legal candidates.') == 2
    assert stdout.count('Digit 5 summary: 8 placed; 1 legal empty locations.') == 2
    assert stdout.count('Notes for row 1 col 1: 1 9\n') == 2
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # A legal-looking wrong move can leave another empty square without
    # candidates; display ! while leaving board and history unchanged.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 9 4\nshow heatmap\nstatus\nquit\n')
    assert 'Heatmap summary: 1 empty cells with no legal candidates.' in stdout
    assert ' ! |' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Invalid digit selectors and redundant parameters fail closed.
    invalid_candidate_maps = [
        'show digit', 'show digit 0', 'show digit 10',
        'show digit -1', 'show digit x', 'show digit 5 extra',
        'show digit 5 6', 'show heatmap 5', 'show heatmap extra',
        'show heatmap 1 2', 'show digits 5'
    ]
    stdout, stderr = run(['--puzzle', near_win],
                         'status\n' + '\n'.join(invalid_candidate_maps) +
                         '\nstatus\nshow digit 5\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(invalid_candidate_maps)
    assert stdout.count('Digit 5 map (') == 1
    assert stdout.count('undo 0, redo 0') == 2 and not stderr
    checks += 1

    # Both views are also available after resuming a saved game, and
    # neither changes the selected save destination or handwritten marks.
    map_save = folder / 'candidate visual map.save'
    stdout, stderr = run(['--puzzle', near_win, '--save', map_save],
                         'notes set 1 1 19\nsave\nquit\n')
    assert 'Saved to ' in stdout and map_save.exists() and not stderr
    stdout, stderr = run(['--resume', map_save],
                         'show heatmap\nshow digit 5\nnotes 1 1\n'
                         'status\nquit\n')
    assert 'Digit 5 summary: 8 placed; 1 legal empty locations.' in stdout
    assert 'Heatmap summary: 0 empty cells with no legal candidates.' in stdout
    assert 'Notes for row 1 col 1: 1 9\n' in stdout and not stderr
    checks += 1

    # Probe a locally legal but globally wrong digit without placing it:
    # the tentative 4 at r1c9 makes r7c9 lose its final candidate.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'probe 1 9 4\nstatus\nnotes 1 9\nquit\n')
    assert 'Probe row 1 col 9 = 4: locally legal, NOT applied.' in stdout
    assert 'Probe dead end: row 7 col 9 would have no legal digits.' in stdout
    assert ('Probe summary: 10 peer candidates removed; '
            '1 new zero-candidate cells; 0 new missing-digit unit gaps.') in stdout
    assert 'Progress: 30/81 filled' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # Unit-level dead-end distinct from a cell with no candidates.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'probe 1 3 1\nstatus\nquit\n')
    assert 'Probe row 1 col 3 = 1: locally legal, NOT applied.' in stdout
    assert 'Probe dead end: digit 1 would have no place in column 8.' in stdout
    assert ('Probe summary: 7 peer candidates removed; '
            '0 new zero-candidate cells; 1 new missing-digit unit gaps.') in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # A locally allowed hypothesis without immediate contradictions cannot
    # be certified correct; the report must say so explicitly.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'probe 1 3 4\nstatus\nquit\n')
    assert 'Probe row 1 col 3 = 4: locally legal, NOT applied.' in stdout
    assert ('Probe summary: 8 peer candidates removed; '
            '0 new zero-candidate cells; 0 new missing-digit unit gaps.') in stdout
    assert 'does NOT prove the move is correct.' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # Immediate local violations, immutable clues and filled entries fail
    # without modifying the board, handwritten marks or Undo history.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'notes set 1 3 19\n'
                         'probe 1 3 5\nprobe 1 1 5\nnotes 1 3\n'
                         'status\nset 1 3 4\nprobe 1 3 1\n'
                         'status\nquit\n')
    assert 'Cannot probe row 1 col 3 = 5: digit is not locally legal.' in stdout
    assert 'Cannot probe row 1 col 1: immutable original clue.' in stdout
    assert 'Cannot probe row 1 col 3: cell already contains 4.' in stdout
    assert 'Notes for row 1 col 3: 1 9\n' in stdout
    assert 'undo 1, redo 0' in stdout and 'undo 2, redo 0' in stdout
    assert not stderr
    checks += 1

    # Probe of the final open cell in a near-solved puzzle is preview only
    # and must not automatically declare victory or create a history step.
    stdout, stderr = run(['--puzzle', near_win],
                         'probe 1 1 5\nstatus\nquit\n')
    assert 'Probe row 1 col 1 = 5: locally legal, NOT applied.' in stdout
    assert ('Probe summary: 0 peer candidates removed; '
            '0 new zero-candidate cells; 0 new missing-digit unit gaps.') in stdout
    assert 'Progress: 80/81 filled' in stdout
    assert 'SOLVED!' not in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # Strict command argument parsing: invalid digits, coordinates, extra
    # tokens and unsupported aliases never evaluate or apply a hypothesis.
    invalid_probes = [
        'probe', 'probe 1', 'probe 1 3',
        'probe 0 3 1', 'probe 10 3 1',
        'probe 1 0 1', 'probe 1 3 0', 'probe 1 3 10',
        'probe 1 3 -1', 'probe 1 3 x',
        'probe 1 3 1 extra', 'probe 1 3 1 extra extra',
    ]
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'status\n' + '\n'.join(invalid_probes) +
                         '\nstatus\nprobe 1 3 4\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(invalid_probes)
    assert stdout.count('Probe row 1 col 3 = 4: locally legal, NOT applied.') == 1
    assert stdout.count('undo 0, redo 0') == 2 and not stderr
    checks += 1

    # One-ply trial hints: the classic unique puzzle has r1c3=1 as its
    # first locally legal but immediately contradictory hypothesis.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'hint trial 1\nhint trial 2\nstatus\nquit\n')
    first_trial = ('Trial 1: exclude 1 from r1c3 '
                   '(digit 1 would have no place in column 8).')
    second_trial = ('Trial 2: exclude 2 from r1c6 '
                    '(digit 8 would have no place in column 6).')
    assert stdout.count(first_trial) == 2, stdout
    assert second_trial in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # The 10th row-major trial identifies the previously tested
    # candidate r1c9=4 as excluding the last legal digit of r7c9.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'hint trial 10\nstatus\nquit\n')
    assert ('Trial 10: exclude 4 from r1c9 '
            '(r7c9 would have no legal candidates).') in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # Apply only removes matching handwritten pencil marks, in one
    # history entry. It never fills the answer and preserves other marks.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'notes set 1 3 14\nstatus\nhint apply trial 1\n'
                         'notes 1 3\nstatus\nundo\nnotes 1 3\n'
                         'status\nredo\nnotes 1 3\n'
                         'hint apply trial 1\nstatus\nquit\n')
    assert 'Removed 1 trial pencil candidate in one undoable edit.' in stdout
    assert stdout.count('Notes for row 1 col 3: 4\n') == 2, stdout
    assert 'Notes for row 1 col 3: 1 4\n' in stdout
    assert 'undo 2, redo 0' in stdout
    assert 'undo 1, redo 1' in stdout
    assert 'No matching trial pencil notes to remove; history unchanged.' in stdout
    assert not stderr
    checks += 1

    # An application without handwritten matches must preserve Redo.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'hint apply trial 1\nstatus\nundo\nquit\n')
    assert 'No matching trial pencil notes to remove; history unchanged.' in stdout
    assert 'undo 0, redo 0' in stdout
    assert 'Error: no action to undo or redo' in stdout and not stderr
    checks += 1

    # Solved games and mistakes must be gated. A single open cell with a
    # forced value does not itself imply any contradiction-based deduction.
    stdout, stderr = run(['--puzzle', near_win],
                         'hint trial\nhint apply trial\nstatus\nquit\n')
    assert stdout.count('No immediate-contradiction trial hints found.') == 2
    assert 'undo 0, redo 0' in stdout and not stderr
    stdout, stderr = run(['--puzzle', solution],
                         'hint trial\nhint apply trial\nstatus\nquit\n')
    assert stdout.count('Puzzle already solved; no trial hints needed.') == 2
    assert 'undo 0, redo 0' in stdout and not stderr
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 9 4\nhint trial\nhint apply trial\n'
                         'status\nquit\n')
    assert 'Cannot preview trial hints: correct the existing mistakes first.' in stdout
    assert 'Cannot apply trial hints: correct the existing mistakes first.' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Reject zero/out-of-range limits, malformed integers and extra
    # arguments without changing the board or history.
    bad_trial_args = [
        'hint trial 0', 'hint trial 82', 'hint trial -1',
        'hint trial nope', 'hint trial 2 extra',
        'hint apply trial 0', 'hint apply trial 82',
        'hint apply trial -1', 'hint apply trial nope',
        'hint apply trial 2 extra'
    ]
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'status\n' + '\n'.join(bad_trial_args) +
                         '\nstatus\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(bad_trial_args)
    assert stdout.count('undo 0, redo 0') == 2
    assert 'Trial 1:' not in stdout and not stderr
    checks += 1

    # Compare all three live candidates in r1c3 without trying any real
    # move. Candidate 1 is immediately contradictory, but 2 and 4 remain
    # undetermined; none are pulled from the saved Sudoku solution.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'probe compare 1 3\nstatus\nquit\n')
    assert 'Compare row 1 col 3: 3 legal candidates.' in stdout
    assert ('Candidate 1: EXCLUDED (digit 1 would have no place in column 8); '
            '7 peer candidates removed.') in stdout
    assert 'Candidate 2: UNDETERMINED; 11 peer candidates removed.' in stdout
    assert 'Candidate 4: UNDETERMINED; 8 peer candidates removed.' in stdout
    assert ('Compare summary: 3 legal candidates; 1 provable exclusion; '
            '2 undetermined.') in stdout
    assert 'No immediate contradiction does not prove a candidate correct.' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # A different cell exercises a zero-candidate witness and a separate
    # missing-digit witness alongside an undetermined hypothetical move.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'probe compare 1 9\nstatus\nquit\n')
    assert 'Compare row 1 col 9: 3 legal candidates.' in stdout
    assert 'Candidate 2: UNDETERMINED; 7 peer candidates removed.' in stdout
    assert ('Candidate 4: EXCLUDED (r7c9 would have no legal digits); '
            '10 peer candidates removed.') in stdout
    assert ('Candidate 8: EXCLUDED (digit 8 would have no place in row 2); '
            '4 peer candidates removed.') in stdout
    assert ('Compare summary: 3 legal candidates; 2 provable exclusions; '
            '1 undetermined.') in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # One open square has exactly one legal candidate, but comparison
    # must remain a preview and never automatically win the game.
    stdout, stderr = run(['--puzzle', near_win],
                         'probe compare 1 1\nstatus\nquit\n')
    assert 'Compare row 1 col 1: 1 legal candidate.' in stdout
    assert 'Candidate 5: UNDETERMINED; 0 peer candidates removed.' in stdout
    assert ('Compare summary: 1 legal candidate; 0 provable exclusions; '
            '1 undetermined.') in stdout
    assert 'Progress: 80/81 filled' in stdout and 'SOLVED!' not in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # Comparison neither edits handwritten pencil notes nor inserts
    # history snapshots; existing Undo and Redo still work afterward.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'notes set 1 3 19\nprobe compare 1 3\n'
                         'notes 1 3\nstatus\nundo\nnotes 1 3\n'
                         'status\nredo\nnotes 1 3\nstatus\nquit\n')
    assert 'Candidate 1: EXCLUDED' in stdout
    assert stdout.count('Notes for row 1 col 3: 1 9\n') == 2
    assert 'Notes for row 1 col 3:\n' in stdout
    assert stdout.count('undo 1, redo 0') == 2
    assert 'undo 0, redo 1' in stdout and not stderr
    checks += 1

    # Do not make new deductions if the current puzzle already contains
    # an immediate contradiction. Refuse clues and occupied squares too.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'probe compare 1 1\nset 1 9 4\n'
                         'probe compare 1 3\nprobe compare 1 9\n'
                         'status\nquit\n')
    assert 'Cannot compare row 1 col 1: immutable original clue.' in stdout
    assert 'Cannot compare: current candidates already contain a contradiction.' in stdout
    assert 'Cannot compare row 1 col 9: cell already contains 4.' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Coordinate parser must reject malformed/partial commands and
    # trailing tokens without accidentally launching a normal probe.
    invalid_comparisons = [
        'probe compare', 'probe compare 1', 'probe compare 0 3',
        'probe compare 1 0', 'probe compare 10 3', 'probe compare 1 10',
        'probe compare nope 3', 'probe compare 1 -1',
        'probe compare 1 3 extra', 'probe compare 1 3 extra extra'
    ]
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'status\n' + '\n'.join(invalid_comparisons) +
                         '\nstatus\nprobe compare 1 3\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(invalid_comparisons)
    assert stdout.count('Compare row 1 col 3: 3 legal candidates.') == 1
    assert stdout.count('undo 0, redo 0') == 2 and not stderr
    checks += 1

    # Trial-forced preview: no hint is selected from the cached solution.
    # In the classic puzzle, every alternative for r1c6, r1c8 and r1c9
    # causes an immediate cell/row/column/box contradiction.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'hint trial-forced 1\nhint trial-forced 3\n'
                         'status\nquit\n')
    assert stdout.count(
        'Trial forced 1: row 1 col 6 -> 8 '
        '(3 of 4 candidates excluded by immediate contradiction).') == 2
    assert 'Trial forced 2: row 1 col 8 -> 1 ' in stdout
    assert 'Trial forced 3: row 1 col 9 -> 2 ' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # Batch placement of several logically forced values is a single
    # validated Undo snapshot. Unrelated manual pencil notes are kept;
    # notes in a newly filled cell are cleared and Undo restores them.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'notes set 1 6 26\nnotes set 1 3 19\n'
                         'hint apply trial-forced 3\n'
                         'notes 1 3\nnotes 1 6\nstatus\n'
                         'undo\nnotes 1 6\nstatus\nredo\n'
                         'notes 1 3\nstatus\nquit\n')
    assert 'Applied 3 trial-forced placements in one undoable edit.' in stdout
    assert 'Progress: 33/81 filled' in stdout
    assert 'Progress: 30/81 filled' in stdout
    assert stdout.count('Notes for row 1 col 3: 1 9\n') == 2
    assert 'Notes for row 1 col 6: 2 6\n' in stdout
    assert 'Notes for row 1 col 6:\n' in stdout
    assert 'undo 3, redo 0' in stdout
    assert 'undo 2, redo 1' in stdout and not stderr
    checks += 1

    # Ordinary naked singles are handled by 'hint' and are not duplicated
    # as a trial-forced finding. A solved puzzle also has no trial hints.
    stdout, stderr = run(['--puzzle', near_win],
                         'hint trial-forced\nhint apply trial-forced\n'
                         'status\nquit\n')
    assert stdout.count('No trial-forced placements found.') == 2
    assert 'undo 0, redo 0' in stdout and not stderr
    stdout, stderr = run(['--puzzle', solution],
                         'hint trial-forced\nhint apply trial-forced\n'
                         'status\nquit\n')
    assert stdout.count('Puzzle already solved; no trial-forced hints needed.') == 2
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # A locally legal but wrong placed digit must block preview and
    # application; no fresh state should be committed.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 9 4\nhint trial-forced\n'
                         'hint apply trial-forced\nstatus\nquit\n')
    assert 'Cannot preview trial-forced hints: correct the existing mistakes first.' in stdout
    assert 'Cannot apply trial-forced hints: correct the existing mistakes first.' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Strict decimal bound 1..81 and argument count, without changing
    # the board or making a spurious Undo entry for rejected commands.
    bad_forced_args = [
        'hint trial-forced 0', 'hint trial-forced 82',
        'hint trial-forced -1', 'hint trial-forced nope',
        'hint trial-forced 1 extra',
        'hint apply trial-forced 0', 'hint apply trial-forced 82',
        'hint apply trial-forced nope', 'hint apply trial-forced -1',
        'hint apply trial-forced 1 extra',
    ]
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'status\n' + '\n'.join(bad_forced_args) +
                         '\nstatus\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(bad_forced_args)
    assert stdout.count('undo 0, redo 0') == 2
    assert 'Trial forced 1:' not in stdout and not stderr
    checks += 1

    # Guarded placement rejects a locally legal move that would empty
    # another cell's candidate set; no notes or history are modified.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set safe 1 9 4\nstatus\nquit\n')
    assert 'Safe set refused: r7c9 would have no legal candidates.' in stdout
    assert 'Progress: 30/81 filled' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # A different locally legal hypothesis is rejected because it leaves
    # a required digit without any position in another column.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set safe 1 3 1\nstatus\nquit\n')
    assert 'Safe set refused: digit 1 would have no place in column 8.' in stdout
    assert 'Progress: 30/81 filled' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # A noncontradictory placement is actually committed as one Undo,
    # can be undone/redone, and explicitly is not certified correct.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set safe 1 3 4\nstatus\nundo\nstatus\n'
                         'redo\nstatus\nquit\n')
    assert ('Safe set row 1 col 3 = 4: no immediate contradiction; '
            'this does NOT prove correctness.') in stdout
    assert stdout.count('Progress: 31/81 filled') == 2
    assert 'Progress: 30/81 filled' in stdout
    assert 'undo 1, redo 0' in stdout and 'undo 0, redo 1' in stdout
    assert not stderr
    checks += 1

    # Noncontradictory is NOT the same as correct: this locally legal
    # but globally wrong digit is allowed with the explicit disclaimer.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set safe 1 3 2\nstatus\nquit\n')
    assert ('Safe set row 1 col 3 = 2: no immediate contradiction; '
            'this does NOT prove correctness.') in stdout
    assert 'Progress: 31/81 filled, 1 mistakes' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Guarded set preserves unrelated notes and clears pencil marks
    # in exactly the newly filled cell, consistent with regular set.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'notes set 1 3 19\nnotes set 2 2 9\n'
                         'set safe 1 3 4\nnotes 1 3\nnotes 2 2\n'
                         'status\nundo\nnotes 1 3\nnotes 2 2\n'
                         'status\nquit\n')
    assert 'Notes for row 1 col 3:\n' in stdout
    assert 'Notes for row 1 col 3: 1 9\n' in stdout
    assert stdout.count('Notes for row 2 col 2: 9\n') == 2
    assert 'undo 3, redo 0' in stdout and 'undo 2, redo 1' in stdout
    assert not stderr
    checks += 1

    # Refuse immutable/filled targets, locally illegal moves and a
    # baseline board which already has a local contradiction.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set safe 1 1 5\nset safe 1 3 5\n'
                         'set 1 9 4\nset safe 1 9 4\n'
                         'set safe 1 3 4\nstatus\nquit\n')
    assert 'Safe set refused: row 1 col 1 is an original clue.' in stdout
    assert 'Safe set refused: 5 is not locally legal at row 1 col 3.' in stdout
    assert 'Safe set refused: row 1 col 9 is already filled.' in stdout
    assert ('Safe set refused: current board already has an immediate '
            'candidate contradiction.') in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Final cell can still win the game, but the guard's correctness
    # disclaimer does not depend on the cached solved grid.
    stdout, stderr = run(['--puzzle', near_win],
                         'set safe 1 1 5\nstatus\nquit\n')
    assert 'Safe set row 1 col 1 = 5: no immediate contradiction;' in stdout
    assert 'SOLVED!' in stdout and 'undo 1, redo 0' in stdout
    assert not stderr
    checks += 1

    # Strict parser: missing arguments, zero/out-of-range coordinates,
    # malformed digits and any surplus tokens fail before evaluation.
    bad_safe = [
        'set safe', 'set safe 1', 'set safe 1 3',
        'set safe 0 3 4', 'set safe 10 3 4',
        'set safe 1 0 4', 'set safe 1 10 4',
        'set safe 1 3 0', 'set safe 1 3 10',
        'set safe 1 3 -1', 'set safe 1 3 nope',
        'set safe 1 3 4 extra', 'set safe 1 3 4 extra more'
    ]
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'status\n' + '\n'.join(bad_safe) +
                         '\nstatus\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(bad_safe)
    assert stdout.count('undo 0, redo 0') == 2
    assert 'Safe set row 1 col 3 = ' not in stdout and not stderr
    checks += 1

    # Targeted proof-required placement: r1c6=8 is forced because the
    # other three locally legal digits immediately contradict Sudoku.
    # This is a real placement, unlike 'probe compare' and 'hint' preview.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set proven 1 6 8\nstatus\nundo\nstatus\n'
                         'redo\nstatus\nquit\n')
    assert ('Proven set row 1 col 6 = 8: 3 of 3 alternatives '
            'refuted; placement committed.') in stdout
    assert stdout.count('Progress: 31/81 filled') == 2
    assert 'Progress: 30/81 filled' in stdout
    assert 'undo 1, redo 0' in stdout and 'undo 0, redo 1' in stdout
    assert not stderr
    checks += 1

    # A locally legal choice is not automatically proven. r1c3=4 has
    # another unrefuted candidate (2), so the board remains unchanged.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set proven 1 3 4\nstatus\nquit\n')
    assert ('Proven set refused: row 1 col 3 = 4 has 1 unresolved '
            'alternative; not logically forced.') in stdout
    assert 'Progress: 30/81 filled' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # An otherwise locally legal but contradictory target itself must
    # fail, regardless of whether any alternatives can be refuted.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set proven 1 3 1\nstatus\nquit\n')
    assert ('Proven set refused: row 1 col 3 = 1 creates an immediate '
            'contradiction.') in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # An incorrect value that has no immediate contradiction must NOT
    # pass a proof-required placement just because it passes 'set safe'.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set proven 1 3 2\nstatus\nquit\n')
    assert ('Proven set refused: row 1 col 3 = 2 has 1 unresolved '
            'alternative; not logically forced.') in stdout
    assert 'Progress: 30/81 filled' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # A simple single is a legitimate proof with zero alternatives.
    # This may complete the puzzle but must not depend on solution lookup.
    stdout, stderr = run(['--puzzle', near_win],
                         'set proven 1 1 5\nstatus\nquit\n')
    assert ('Proven set row 1 col 1 = 5: 0 of 0 alternatives '
            'refuted; placement committed.') in stdout
    assert 'SOLVED!' in stdout and 'undo 1, redo 0' in stdout
    assert not stderr
    checks += 1

    # Applying the proven digit clears notes in only the selected cell,
    # preserves notes elsewhere, and a single Undo restores the old marks.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'notes set 1 6 26\nnotes set 1 3 19\n'
                         'set proven 1 6 8\nnotes 1 6\nnotes 1 3\n'
                         'status\nundo\nnotes 1 6\nnotes 1 3\n'
                         'status\nquit\n')
    assert 'Proven set row 1 col 6 = 8:' in stdout
    assert 'Notes for row 1 col 6:\n' in stdout
    assert 'Notes for row 1 col 6: 2 6\n' in stdout
    assert stdout.count('Notes for row 1 col 3: 1 9\n') == 2
    assert 'undo 3, redo 0' in stdout
    assert 'undo 2, redo 1' in stdout and not stderr
    checks += 1

    # Original clues, occupied cells, locally illegal choices, existing
    # incorrect digits, and immediate baseline contradictions fail closed.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set proven 1 1 5\nset proven 1 6 5\n'
                         'set proven 1 6 8\nset proven 1 6 8\n'
                         'set 1 3 2\nset proven 1 8 1\n'
                         'status\nquit\n')
    assert 'Proven set refused: row 1 col 1 is an original clue.' in stdout
    assert 'Proven set refused: 5 is not locally legal at row 1 col 6.' in stdout
    assert 'Proven set refused: row 1 col 6 is already filled.' in stdout
    assert 'Proven set refused: correct existing incorrect entries first.' in stdout
    assert 'undo 2, redo 0' in stdout and not stderr
    checks += 1

    # Another puzzle state with no locally legal candidates must be
    # rejected before relying on the hypothetical proof.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 9 4\nset proven 1 3 4\nstatus\nquit\n')
    assert 'Proven set refused: correct existing incorrect entries first.' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Strict four-token form after 'set proven': extra tokens, invalid
    # or partial coordinates/digits never modify the board or history.
    bad_proven = [
        'set proven', 'set proven 1', 'set proven 1 6',
        'set proven 0 6 8', 'set proven 10 6 8',
        'set proven 1 0 8', 'set proven 1 10 8',
        'set proven 1 6 0', 'set proven 1 6 10',
        'set proven 1 6 -1', 'set proven 1 6 nope',
        'set proven 1 6 8 extra', 'set proven 1 6 8 extra more',
    ]
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'status\n' + '\n'.join(bad_proven) +
                         '\nstatus\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(bad_proven)
    assert stdout.count('undo 0, redo 0') == 2
    assert 'Proven set row ' not in stdout and not stderr
    checks += 1

    # Read-only timeline lists committed versus undoable/redoable edits and
    # exposes the true digit/note differences for each snapshot.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'history\nset 1 3 4\nnotes set 1 4 19\n'
                         'undo\nhistory 2\nhistory inspect 1\n'
                         'history inspect 2\nstatus\nquit\n')
    assert 'History: 0 recorded actions; cursor 0; undo 0; redo 0.' in stdout
    assert 'No history entries yet.' in stdout
    assert 'History: 2 recorded actions; cursor 1; undo 1; redo 1.' in stdout
    assert ('History step 1 [DONE]: 1 placed, 0 erased, 0 replaced; '
            '0 note marks added, 0 removed; r1c3') in stdout
    assert ('History step 2 [REDO]: 0 placed, 0 erased, 0 replaced; '
            '2 note marks added, 0 removed; r1c4') in stdout
    assert 'History inspect step 1 [DONE]:\n  Board r1c3: - -> 4' in stdout
    assert 'History inspect step 2 [REDO]:\n  Notes r1c4: - -> 1,9' in stdout
    assert 'undo 1, redo 1' in stdout and not stderr
    checks += 1

    # Summary aggregates actual retained snapshot differences separately
    # for applied and redoable actions, without touching the Undo cursor.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'history summary\nset 1 3 4\nnotes set 1 4 19\n'
                         'undo\nhistory summary\nredo\nhistory summary\n'
                         'status\nquit\n')
    assert 'History summary: 0 applied, 0 redoable actions (retained).' in stdout
    assert 'History summary: 1 applied, 1 redoable actions (retained).' in stdout
    assert 'History summary: 2 applied, 0 redoable actions (retained).' in stdout
    assert ('Applied changes: 1 placed, 0 erased, 0 replaced; '
            '0 note marks added, 0 removed; 1 cells touched.') in stdout
    assert ('Redoable changes: 0 placed, 0 erased, 0 replaced; '
            '2 note marks added, 0 removed; 1 cells touched.') in stdout
    assert ('Applied changes: 1 placed, 0 erased, 0 replaced; '
            '2 note marks added, 0 removed; 2 cells touched.') in stdout
    assert 'undo 2, redo 0' in stdout and not stderr
    checks += 1

    # A multi-cell hint is a single action but counts every changed cell.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'hint apply trial-forced 3\nhistory summary\n'
                         'status\nquit\n')
    assert 'History summary: 1 applied, 0 redoable actions (retained).' in stdout
    assert ('Applied changes: 3 placed, 0 erased, 0 replaced; '
            '0 note marks added, 0 removed; 3 cells touched.') in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # A strict no-argument summary parser must not accept surplus tokens.
    bad_summary = ['history summary extra', 'history summary 0',
                   'history summary 1 2']
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'status\n' + '\n'.join(bad_summary) +
                         '\nstatus\nhistory summary\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(bad_summary)
    assert 'History summary: 0 applied, 0 redoable actions (retained).' in stdout
    assert stdout.count('undo 0, redo 0') == 2 and not stderr
    checks += 1

    # A new move after Undo cuts the old Redo branch. The timeline must
    # describe the replacement state, never the abandoned pencil notes.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 4\nnotes set 1 4 19\nundo\n'
                         'set 1 4 6\nhistory\nhistory inspect 2\n'
                         'status\nquit\n')
    assert 'History: 2 recorded actions; cursor 2; undo 2; redo 0.' in stdout
    assert 'History step 2 [DONE]: 1 placed, 0 erased, 0 replaced;' in stdout
    assert 'History inspect step 2 [DONE]:\n  Board r1c4: - -> 6' in stdout
    assert 'Notes r1c4: - -> 1,9' not in stdout
    assert 'undo 2, redo 0' in stdout and not stderr
    checks += 1

    # An atomic three-cell placement appears as one history step with
    # three board changes in the detailed inspection.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'hint apply trial-forced 3\nhistory 1\n'
                         'history inspect 1\nstatus\nquit\n')
    assert 'Applied 3 trial-forced placements in one undoable edit.' in stdout
    assert ('History step 1 [DONE]: 3 placed, 0 erased, 0 replaced; '
            '0 note marks added, 0 removed; 3 changed cells') in stdout
    assert 'History inspect step 1 [DONE]:' in stdout
    for board_line in ['Board r1c6: - -> 8',
                       'Board r1c8: - -> 1', 'Board r1c9: - -> 2']:
        assert board_line in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Reset is accurately represented as one combined erasure of digits
    # and notes, with correct counts rather than struct-padding memcmp.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 4\nnotes set 1 4 19\nreset\n'
                         'history 1\nhistory inspect 3\nstatus\nquit\n')
    assert ('History step 3 [DONE]: 0 placed, 1 erased, 0 replaced; '
            '0 note marks added, 2 removed; 2 changed cells') in stdout
    assert 'History inspect step 3 [DONE]:' in stdout
    assert 'Board r1c3: 4 -> -' in stdout
    assert 'Notes r1c4: 1,9 -> -' in stdout
    assert 'undo 3, redo 0' in stdout and not stderr
    checks += 1

    # Limit affects listing, not the full count. Inspecting an absent
    # record is nonfatal and does not create an Undo snapshot.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 4\nnotes set 1 4 19\n'
                         'history 1\nhistory inspect 3\n'
                         'status\nquit\n')
    assert 'History: 2 recorded actions; cursor 2; undo 2; redo 0.' in stdout
    assert 'History step 2 [DONE]:' in stdout
    assert 'History step 1 [DONE]:' not in stdout
    assert '1 earlier actions hidden (raise history limit).' in stdout
    assert 'History step 3 is not recorded.' in stdout
    assert 'undo 2, redo 0' in stdout and not stderr
    checks += 1

    # Reader must reject malformed limits, nonexistent step zero and
    # surplus tokens rather than running a different command.
    bad_history = [
        'history 0', 'history 128', 'history -1', 'history abc',
        'history inspect', 'history inspect 0', 'history inspect 128',
        'history inspect -1', 'history inspect nope',
        'history 2 extra', 'history inspect 1 extra',
        'history inspect 1 2', 'history foo bar'
    ]
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'status\n'+'\n'.join(bad_history)+
                         '\nstatus\nhistory\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(bad_history)
    assert stdout.count('History: 0 recorded actions; cursor 0; undo 0; redo 0.') == 1
    assert stdout.count('undo 0, redo 0') == 3 and not stderr
    checks += 1

    # Absolute history navigation restores already-recorded states
    # without adding an action or deleting the redo branch.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 4\nnotes set 1 4 19\n'
                         'history goto 0\nnotes 1 4\nstatus\n'
                         'history goto 2\nnotes 1 4\nstatus\n'
                         'history goto 1\nnotes 1 4\n'
                         'history\nstatus\nquit\n')
    assert 'History goto 0: cursor 0; undo 0; redo 2.' in stdout
    assert 'History goto 2: cursor 2; undo 2; redo 0.' in stdout
    assert 'History goto 1: cursor 1; undo 1; redo 1.' in stdout
    assert 'Notes for row 1 col 4: 1 9\n' in stdout
    assert stdout.count('Notes for row 1 col 4:\n') == 2
    assert 'History: 2 recorded actions; cursor 1; undo 1; redo 1.' in stdout
    assert 'History step 2 [REDO]:' in stdout
    assert 'undo 1, redo 1' in stdout and not stderr
    checks += 1

    # Seeking to the current step is a no-op; the next normal Undo/Redo
    # action must still traverse existing snapshots as before.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 4\nhistory goto 1\nhistory goto 1\n'
                         'history\nundo\nhistory\nredo\n'
                         'history\nstatus\nquit\n')
    assert stdout.count('History goto 1: cursor 1; undo 1; redo 0.') == 2
    assert stdout.count('History: 1 recorded actions; cursor 1; undo 1; redo 0.') == 2
    assert 'History: 1 recorded actions; cursor 0; undo 0; redo 1.' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # A normal edit after seeking backwards discards the old Redo branch,
    # exactly as when editing after a conventional Undo.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 4\nnotes set 1 4 19\n'
                         'history goto 1\nset 1 4 6\n'
                         'history inspect 2\nhistory\n'
                         'history goto 2\nstatus\nquit\n')
    assert 'History goto 1: cursor 1; undo 1; redo 1.' in stdout
    assert 'History inspect step 2 [DONE]:\n  Board r1c4: - -> 6' in stdout
    assert 'Notes r1c4: - -> 1,9' not in stdout
    assert 'History: 2 recorded actions; cursor 2; undo 2; redo 0.' in stdout
    assert 'History goto 2: cursor 2; undo 2; redo 0.' in stdout
    assert 'undo 2, redo 0' in stdout and not stderr
    checks += 1

    # Missing snapshot index is not an editing command and cannot move
    # the cursor or implicitly create a new history record.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 4\nhistory goto 2\n'
                         'history\nstatus\nquit\n')
    assert 'Error: ' in stdout
    assert 'History: 1 recorded actions; cursor 1; undo 1; redo 0.' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Bulk trial-forced placement is a single snapshot. Absolute seek
    # restores the entire group atomically with no extra Undo entry.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'hint apply trial-forced 3\n'
                         'history goto 0\nstatus\n'
                         'history goto 1\nstatus\nquit\n')
    assert 'Applied 3 trial-forced placements in one undoable edit.' in stdout
    assert 'History goto 0: cursor 0; undo 0; redo 1.' in stdout
    assert 'History goto 1: cursor 1; undo 1; redo 0.' in stdout
    assert 'Progress: 30/81 filled' in stdout
    assert 'Progress: 33/81 filled' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Strict CLI parser: missing, negative, too-large and excess
    # arguments are rejected before history navigation.
    bad_history_goto = [
        'history goto', 'history goto -1', 'history goto 128',
        'history goto 4294967295', 'history goto nope',
        'history goto 0 extra', 'history goto 0 extra more',
        'history goto 1.0'
    ]
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'status\n' + '\n'.join(bad_history_goto) +
                         '\nstatus\nhistory goto 0\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(bad_history_goto)
    assert 'History goto 0: cursor 0; undo 0; redo 0.' in stdout
    assert stdout.count('undo 0, redo 0') == 2 and not stderr
    checks += 1

    # Direct comparison of distant checkpoints includes real board and
    # pencil changes, without adding an Undo entry.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 4\nnotes set 1 4 19\n'
                         'history diff 0 2\nhistory diff 2 0\n'
                         'status\nquit\n')
    assert 'History diff 0 -> 2:\n  Board r1c3: - -> 4' in stdout
    assert '  Notes r1c4: - -> 1,9' in stdout
    assert ('History diff summary: 2 cells changed; 1 placed, 0 erased, '
            '0 replaced; 2 marks added, 0 removed.') in stdout
    assert 'History diff 2 -> 0:\n  Board r1c3: 4 -> -' in stdout
    assert '  Notes r1c4: 1,9 -> -' in stdout
    assert ('History diff summary: 2 cells changed; 0 placed, 1 erased, '
            '0 replaced; 0 marks added, 2 removed.') in stdout
    assert 'undo 2, redo 0' in stdout and not stderr
    checks += 1

    # Equal snapshots and a pristine history have no changes.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'history diff 0 0\nhistory cell 1 3\n'
                         'status\nquit\n')
    assert 'History diff 0 -> 0:' in stdout
    assert ('History diff summary: 0 cells changed; 0 placed, 0 erased, '
            '0 replaced; 0 marks added, 0 removed.') in stdout
    assert 'No observable differences between the snapshots.' in stdout
    assert 'History cell r1c3:' in stdout
    assert 'History cell summary: 0 changed steps.' in stdout
    assert 'This cell has no recorded changes.' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # Per-cell timeline includes both board and pencil changes, including
    # redoable steps above the current cursor.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'notes set 1 3 19\nnotes add 1 3 2\n'
                         'set 1 3 4\nundo\n'
                         'history cell 1 3\nhistory cell 1 4\n'
                         'status\nquit\n')
    assert 'History cell r1c3:' in stdout
    assert 'Step 1 [DONE]: notes - -> 1,9' in stdout
    assert 'Step 2 [DONE]: notes 1,9 -> 1,2,9' in stdout
    assert 'Step 3 [REDO]: board - -> 4 notes 1,2,9 -> -' in stdout
    assert 'History cell summary: 3 changed steps.' in stdout
    assert 'History cell r1c4:' in stdout
    assert 'This cell has no recorded changes.' in stdout
    assert 'undo 2, redo 1' in stdout and not stderr
    checks += 1

    # Comparing two redoable snapshots is observational and keeps them
    # available for an eventual history goto.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 4\nnotes set 1 4 19\n'
                         'history goto 0\nhistory diff 1 2\n'
                         'history cell 1 4\nhistory goto 2\n'
                         'status\nquit\n')
    assert 'History diff 1 -> 2:' in stdout
    assert 'Notes r1c4: - -> 1,9' in stdout
    assert 'Step 2 [REDO]: notes - -> 1,9' in stdout
    assert 'History goto 2: cursor 2; undo 2; redo 0.' in stdout
    assert 'undo 2, redo 0' in stdout and not stderr
    checks += 1

    # Group placement and reset are accurately compared as aggregate
    # changes between distant checkpoints.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'hint apply trial-forced 3\n'
                         'history diff 0 1\nhistory cell 1 6\n'
                         'status\nquit\n')
    assert 'History diff 0 -> 1:' in stdout
    for placement in ['Board r1c6: - -> 8',
                      'Board r1c8: - -> 1', 'Board r1c9: - -> 2']:
        assert placement in stdout
    assert ('History diff summary: 3 cells changed; 3 placed, 0 erased, '
            '0 replaced; 0 marks added, 0 removed.') in stdout
    assert 'Step 1 [DONE]: board - -> 8' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Both commands reject malformed arguments; a syntactically valid
    # nonexistent snapshot gets a clear read-only unavailable report.
    invalid_history_queries = [
        'history diff', 'history diff 0', 'history diff -1 0',
        'history diff 128 0', 'history diff 0 128',
        'history diff x 0', 'history diff 0 x',
        'history diff 0 0 extra', 'history cell',
        'history cell 1', 'history cell 0 1',
        'history cell 10 1', 'history cell 1 0',
        'history cell 1 10', 'history cell x 2',
        'history cell 1 2 extra'
    ]
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'status\n'+'\n'.join(invalid_history_queries)+
                         '\nhistory diff 0 1\nstatus\nquit\n')
    assert stdout.count('Error: unknown command or invalid arguments') == len(invalid_history_queries)
    assert 'History diff unavailable: recorded steps are 0..0.' in stdout
    assert stdout.count('undo 0, redo 0') == 2 and not stderr
    checks += 1

    # CLI batch delegates to the validated core batch API: both digits
    # become visible at once and can be undone/redone as ONE snapshot.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set batch r1c3=4,r1c4=6\nstatus\n'
                         'history 1\nundo\nstatus\nredo\nstatus\nquit\n')
    assert 'Batch placed 2 digits in one undoable edit.' in stdout
    assert stdout.count('Progress: 32/81 filled') == 2
    assert 'Progress: 30/81 filled' in stdout
    assert 'History step 1 [DONE]: 2 placed, 0 erased, 0 replaced;' in stdout
    assert 'undo 1, redo 0' in stdout and 'undo 0, redo 1' in stdout
    assert not stderr
    checks += 1

    # Notes at each filled cell are cleared; notes outside the batch
    # are retained, and Undo restores all previous marks together.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'notes set 1 3 19\nnotes set 1 4 28\n'
                         'notes set 2 2 9\n'
                         'set batch r1c3=4,r1c4=6\n'
                         'notes 1 3\nnotes 1 4\nnotes 2 2\n'
                         'status\nundo\nnotes 1 3\nnotes 1 4\n'
                         'notes 2 2\nstatus\nquit\n')
    assert 'Batch placed 2 digits in one undoable edit.' in stdout
    assert 'Notes for row 1 col 3:\n' in stdout
    assert 'Notes for row 1 col 4:\n' in stdout
    assert 'Notes for row 1 col 3: 1 9\n' in stdout
    assert 'Notes for row 1 col 4: 2 8\n' in stdout
    assert stdout.count('Notes for row 2 col 2: 9\n') == 2
    assert 'undo 4, redo 0' in stdout and 'undo 3, redo 1' in stdout
    assert not stderr
    checks += 1

    # Duplicate destinations and conflicting simultaneous values are
    # rejected atomically: neither the first nor second placement commits.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set batch r1c3=4,r1c3=4\n'
                         'set batch r1c3=4,r1c9=4\n'
                         'set batch r1c3=4,r2c2=4\n'
                         'status\nhistory\nquit\n')
    assert stdout.count('Error: ') >= 3
    assert 'Batch placed' not in stdout
    assert 'Progress: 30/81 filled' in stdout
    assert 'History: 0 recorded actions; cursor 0; undo 0; redo 0.' in stdout
    assert not stderr
    checks += 1

    # Given cells and occupied editable cells cannot be replaced in a
    # batch. Earlier successful moves and their history remain intact.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set batch r1c1=5,r1c4=6\n'
                         'set 1 3 4\nset batch r1c3=4,r1c4=6\n'
                         'status\nquit\n')
    assert 'Batch placed' not in stdout
    assert 'Progress: 31/81 filled' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # A rejected batch after Undo must not discard redoable history.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 4\nundo\n'
                         'set batch r1c1=5,r1c4=6\n'
                         'status\nredo\nstatus\nquit\n')
    assert 'Batch placed' not in stdout
    assert 'undo 0, redo 1' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # A one-entry batch is still a standard single Undo step and can
    # solve the last cell of a nearly completed Sudoku.
    stdout, stderr = run(['--puzzle', near_win],
                         'set batch r1c1=5\nstatus\nquit\n')
    assert 'Batch placed 1 digit in one undoable edit.' in stdout
    assert 'SOLVED!' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Reject partial entries, zeroes, signs, repeated separators and
    # surplus tokens before calling the core. No malformed prefix is applied.
    bad_batches = [
        'set batch', 'set batch ', 'set batch 134',
        'set batch r1c3=', 'set batch r1c3=0',
        'set batch r0c3=4', 'set batch r1c0=4',
        'set batch r10c3=4', 'set batch R1C3=4',
        'set batch r1c3=4,', 'set batch ,r1c3=4',
        'set batch r1c3=4,,r1c4=6',
        'set batch r1c3=4;r1c4=6', 'set batch r1c3=4,r1c4=x',
        'set batch r1c3=4,r1c4=6extra',
        'set batch r1c3=4 r1c4=6',
    ]
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'status\n' + '\n'.join(bad_batches) +
                         '\nstatus\nquit\n')
    assert stdout.count('Error: ') == len(bad_batches)
    assert 'Batch placed' not in stdout
    assert stdout.count('undo 0, redo 0') == 2 and not stderr
    checks += 1

    # Read-only check of a complete batch: no board, notes, or Undo/Redo
    # changes; safe application then commits the same batch in one action.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set batch check r1c3=4,r1c4=6\n'
                         'status\nset batch safe r1c3=4,r1c4=6\n'
                         'status\nundo\nstatus\nredo\nstatus\nquit\n')
    assert stdout.count(
        'Batch check passed: 2 simultaneous placements; '
        'no immediate contradictions (NOT proof of correctness).') == 2
    assert 'Safe batch placed 2 digits in one undoable edit.' in stdout
    assert stdout.count('Progress: 30/81 filled') == 2
    assert stdout.count('Progress: 32/81 filled') == 2
    assert 'undo 1, redo 0' in stdout and 'undo 0, redo 1' in stdout
    assert not stderr
    checks += 1

    # One locally legal but globally wrong candidate in the batch creates
    # a zero-candidate cell, and the complete batch is refused atomically.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set batch check r1c9=4\n'
                         'set batch safe r1c3=4,r1c9=4\n'
                         'status\nhistory\nquit\n')
    assert 'Batch check refused: r7c9 would have no legal candidates.' in stdout
    assert 'Batch check refused: combined placements conflict with Sudoku rules.' in stdout
    assert 'Progress: 30/81 filled' in stdout
    assert 'History: 0 recorded actions; cursor 0; undo 0; redo 0.' in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # Another locally legal hypothesis makes a required digit impossible
    # in its unit. It must fail before any commit.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set batch safe r1c3=1\nstatus\nquit\n')
    assert 'Batch check refused: digit 1 would have no place in column 8.' in stdout
    assert 'Batch check passed:' not in stdout
    assert 'Safe batch placed' not in stdout
    assert 'undo 0, redo 0' in stdout and not stderr
    checks += 1

    # No immediate contradiction does not prove a correct value: the
    # safe batch can accept a deliberately globally incorrect but locally
    # consistent player guess, with explicit disclaimer.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set batch safe r1c3=2\nstatus\nquit\n')
    assert ('Batch check passed: 1 simultaneous placement; '
            'no immediate contradictions (NOT proof of correctness).') in stdout
    assert 'Safe batch placed 1 digit in one undoable edit.' in stdout
    assert 'Progress: 31/81 filled, 1 mistakes' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Failed guarded batch after an Undo cannot discard the redo history;
    # inspection is read-only, then conventional Redo succeeds.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set 1 3 4\nundo\n'
                         'set batch check r1c9=4\n'
                         'set batch safe r1c9=4\nstatus\n'
                         'redo\nstatus\nquit\n')
    assert stdout.count('Batch check refused: r7c9 would have no legal candidates.') == 2
    assert 'undo 0, redo 1' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Duplicate targets, givens, filled cells, and contradictory combined
    # placements are rejected before the atomic core operation.
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'set batch check r1c3=4,r1c3=4\n'
                         'set batch safe r1c1=5,r1c4=6\n'
                         'set batch safe r1c3=4,r1c9=4\n'
                         'set 1 3 4\n'
                         'set batch check r1c3=4\nstatus\nquit\n')
    assert 'Batch check refused: r1c3 occurs more than once.' in stdout
    assert 'Batch check refused: r1c1 is an original clue.' in stdout
    assert 'Batch check refused: combined placements conflict with Sudoku rules.' in stdout
    assert 'Batch check refused: r1c3 is already filled.' in stdout
    assert 'Progress: 31/81 filled' in stdout
    assert 'undo 1, redo 0' in stdout and not stderr
    checks += 1

    # Check mode on a near-complete puzzle leaves the game unsolved,
    # and safe mode may then commit the final digit.
    stdout, stderr = run(['--puzzle', near_win],
                         'set batch check r1c1=5\nstatus\n'
                         'set batch safe r1c1=5\nstatus\nquit\n')
    assert ('Batch check passed: 1 simultaneous placement; '
            'no immediate contradictions (NOT proof of correctness).') in stdout
    assert 'Progress: 80/81 filled' in stdout
    assert 'Safe batch placed 1 digit in one undoable edit.' in stdout
    assert 'SOLVED!' in stdout and 'undo 1, redo 0' in stdout
    assert not stderr
    checks += 1

    # Malformed four-token forms cannot accidentally fall through to the
    # original unguarded batch command or mutate any part of the game.
    invalid_safe_batches = [
        'set batch safe', 'set batch check',
        'set batch safe r1c3=0', 'set batch check r0c3=4',
        'set batch check r1c3=4,', 'set batch safe r1c3=4,',
        'set batch safe r1c3=4 extra', 'set batch check r1c3=4 extra',
        'set batch unsafe r1c3=4', 'set batch preview r1c3=4',
    ]
    stdout, stderr = run(['--file', fixtures / 'unique.txt'],
                         'status\n' + '\n'.join(invalid_safe_batches) +
                         '\nstatus\nquit\n')
    assert stdout.count('Error: ') == len(invalid_safe_batches)
    assert 'Safe batch placed' not in stdout
    assert stdout.count('undo 0, redo 0') == 2 and not stderr
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
