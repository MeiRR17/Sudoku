"""End-to-end terminal gameplay, atomic save, resume and corrupted-save checks.

Portable stdlib, no tty/color dependency. The child receives commands on stdin.
"""
import os
import pathlib
import stat
import subprocess
import sys
import tempfile

exe = pathlib.Path(sys.argv[1]).resolve()
fixtures = pathlib.Path(sys.argv[2]).resolve()
solution = '534678912672195348198342567859761423426853791713924856961537284287419635345286179'
near_win = '0' + solution[1:]
checks = 0


def run(args, commands='', exit_code=0):
    global checks
    p = subprocess.run([str(exe), 'play', *map(str, args)], input=commands,
                       text=True, encoding='utf-8', capture_output=True, timeout=25)
    assert p.returncode == exit_code, (args, p.returncode, p.stderr, p.stdout)
    assert '\x1b[' not in p.stdout, 'Unexpected ANSI escape/color codes'
    checks += 1
    return p.stdout, p.stderr


with tempfile.TemporaryDirectory() as directory:
    folder = pathlib.Path(directory)
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

    # A logical hint uses current board candidates only, with no move,
    # note edits, history change or accidental undo/redo branch reset.
    stdout, stderr = run(['--puzzle', near_win],
                         'hint\nstatus\nhint unexpected\nstatus\nquit\n')
    assert 'Hint (only candidate): row 1 col 1 -> 5.' in stdout
    assert stdout.count('undo 0, redo 0') == 2
    assert stdout.count('Error: unknown command or invalid arguments') == 1
    assert not stderr
    checks += 1

    # This 25-clue puzzle has a unique solution and no naked singles; only
    # the hidden-single column search can report the first forced step.
    hidden_single_puzzle = '500600902000105308000000500800001020000003000010920800060500004280000000305000070'
    stdout, stderr = run(['--puzzle', hidden_single_puzzle],
                         'hint\nstatus\nhint\nstatus\nquit\n')
    assert stdout.count('Hint (only place in column 8): row 7 col 8 -> 8.') == 2, stdout
    assert stdout.count('undo 0, redo 0') == 2 and not stderr
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
