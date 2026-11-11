"""End-to-end deterministic development package acceptance on current host.

Never claims other OS support. Requires Python stdlib, CMake and C11 compiler.
"""
import hashlib
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(sys.argv[1]).resolve()
BUILD = Path(sys.argv[2]).resolve()
PACKAGER = ROOT / 'scripts' / 'package_release.py'
EXPECTED = '534678912672195348198342567859761423426853791713924856961537284287419635345286179'


def call(*cmd):
    return subprocess.run([str(x) for x in cmd], capture_output=True, text=True, check=True)


def verify_packaged_game_save_resume(binary, temp, label):
    """Test real shipped CLI save and resume, not only the checkout binary.

    Run the binary extracted from a release ZIP (and separately rebuild from
    the release source ZIP) in an isolated temporary directory. No privileges,
    network access, production save paths or third-party dependencies.
    """
    puzzle = '0' + EXPECTED[1:]
    save = temp / (label + ' game with spaces.save')
    damaged = temp / (label + ' corrupted.save')
    unsaved = temp / (label + ' unsaved.save')

    def play(args, commands=''):
        return subprocess.run([str(binary), 'play', *map(str, args)],
                              input=commands, capture_output=True, text=True,
                              encoding='utf-8', timeout=25)

    initial = play(['--puzzle', puzzle, '--save', save],
                   'note 1 1 5\nsave\nquit\n')
    assert initial.returncode == 0, (initial.stdout, initial.stderr)
    assert 'Saved to ' + str(save) in initial.stdout, initial.stdout
    assert save.is_file() and save.stat().st_size > 64
    assert 'Resumed saved game' not in initial.stdout

    restored = play(['--resume', save], 'notes 1 1\nstatus\nquit\n')
    assert restored.returncode == 0, (restored.stdout, restored.stderr)
    assert 'Resumed saved game' in restored.stdout
    assert 'Notes for row 1 col 1: 5' in restored.stdout
    assert 'undo 0, redo 0' in restored.stdout
    assert 'Progress: 80/81 filled' in restored.stdout

    # Tamper with the stored state, not its checksum; a real checksum
    # verifier must refuse the modified bytes before entering gameplay.
    corrupted = bytearray(save.read_bytes())
    corrupted[50] = ord('0') if corrupted[50] != ord('0') else ord('1')
    damaged.write_bytes(corrupted)
    rejected = play(['--resume', damaged])
    assert rejected.returncode == 3, (rejected.stdout, rejected.stderr)
    assert 'corrupted save file' in rejected.stderr and not rejected.stdout

    no_implicit = play(['--puzzle', puzzle, '--save', unsaved], 'quit\n')
    assert no_implicit.returncode == 0, (no_implicit.stdout, no_implicit.stderr)
    assert not unsaved.exists(), 'quitting a shipped binary must not autosave'




with tempfile.TemporaryDirectory(prefix='sudoku-package-e2e-') as tmp:
    temp = Path(tmp)
    left, right = temp / 'build-one', temp / 'build-two'
    for dest in (left, right):
        call(sys.executable, PACKAGER, '--build', BUILD, '--output', dest)
        call(sys.executable, PACKAGER, '--verify-only', '--output', dest)
    names = sorted(x.name for x in left.iterdir())
    assert len(names) == 5, names  # two binary, two source archives, SHA256SUMS
    for name in names:
        a, b = left / name, right / name
        assert hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest(), name
    binary = next(x for x in left.glob('*-linux-*.zip')) if platform.system() == 'Linux' else None
    if binary is None:
        binary = next(x for x in left.glob('*-macos-*.zip')) if platform.system() == 'Darwin' else next(x for x in left.glob('*-windows-*.zip'))
    package_name = binary.stem
    with zipfile.ZipFile(binary) as archive:
        archive.extractall(temp / 'extracted')
    root = temp / 'extracted' / package_name
    exe = root / 'bin' / ('sudoku.exe' if platform.system() == 'Windows' else 'sudoku')
    if platform.system() != 'Windows':
        exe.chmod(0o755)  # zip extraction permissions vary by host
    assert call(exe, '--version').stdout.strip() == 'Sudoku 0.8.4 (experimental)'
    result = call(exe, 'solve', '--file', ROOT / 'tests/fixtures/unique.txt', '--format', 'compact')
    assert result.stdout.strip() == EXPECTED
    assert 'Usage' in call(exe, '--help').stdout
    verify_packaged_game_save_resume(exe, temp, 'installed')
    with tarfile.open(next(left.glob('*-source.tar.gz')), 'r:gz') as tar:
        names = tar.getnames()
        assert any(x.endswith('/CMakeLists.txt') for x in names)
        assert any(x.endswith('/src/core/game.c') for x in names)
        assert all('/build-' not in x and '/.git/' not in x and '/dist/' not in x for x in names)
    # Extract and build the *shipped source archive*, not the checkout. This
    # catches a missing CMake/module/source file in release_files.txt.
    source_zip = next(left.glob('*-source.zip'))
    with zipfile.ZipFile(source_zip) as source_archive:
        source_archive.extractall(temp / 'source-extracted')
    source_root = temp / 'source-extracted' / source_zip.stem
    independent_build = temp / 'source-build'
    call('cmake', '-S', source_root, '-B', independent_build,
         '-DBUILD_TESTING=OFF', '-DCMAKE_BUILD_TYPE=Release')
    call('cmake', '--build', independent_build, '--config', 'Release')
    from_source = independent_build / ('sudoku.exe' if platform.system() == 'Windows' else 'sudoku')
    if not from_source.is_file():
        from_source = independent_build / 'Release' / from_source.name
    assert call(from_source, 'solve', '--puzzle',
                '530070000600195000098000060800060003400803001700020006060000280000419005000080079',
                '--format', 'compact').stdout.strip() == EXPECTED
    verify_packaged_game_save_resume(from_source, temp, 'rebuilt-source')
    # Consume the exported static core as an independently configured CMake project.
    consumer = temp / 'consumer'
    consumer.mkdir()
    (consumer / 'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.16)
project(SudokuConsumer LANGUAGES C)
find_package(Sudoku 0.8 CONFIG REQUIRED)
add_executable(consumer consumer.c)
target_link_libraries(consumer PRIVATE Sudoku::sudoku_core)
''')
    (consumer / 'consumer.c').write_text('''#include <sudoku/board.h>
int main(void) {
    SudokuBoard b = {{0}};
    return sudoku_board_validate(&b, 0) == SUDOKU_OK ? 0 : 1;
}
''')
    call('cmake', '-S', consumer, '-B', temp / 'consumer-build', '-DCMAKE_PREFIX_PATH=' + str(root))
    call('cmake', '--build', temp / 'consumer-build', '--config', 'Release')
    executable = temp / 'consumer-build' / ('consumer.exe' if platform.system() == 'Windows' else 'consumer')
    if not executable.is_file():
        executable = temp / 'consumer-build' / 'Release' / executable.name
    call(executable)
    # Simulated uninstall of isolated prefix: no privileged files touched.
    import shutil
    shutil.rmtree(root)
    assert not root.exists()
    print('PACKAGE E2E PASS: reproducible ZIP/TGZ, source rebuild, exact native play/save/resume/corruption checks, hashes, install, CMake consumer and uninstall')
