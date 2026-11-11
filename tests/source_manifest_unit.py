"""Guard release-source manifest portability and symlink containment.

Uses real temporary files; no CMake toolchain or network required.
"""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'scripts' / 'package_release.py'
spec = importlib.util.spec_from_file_location('sudoku_source_packager', SOURCE)
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class SourceManifestSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='sudoku-source-paths-')
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / 'repo'
        (self.root / 'scripts').mkdir(parents=True)
        (self.root / 'src').mkdir()
        self.manifest = self.root / 'scripts' / 'release_files.txt'
        (self.root / 'src' / 'board.c').write_bytes(b'board-source\n')
        (self.root / 'src' / 'solver.c').write_bytes(b'solver-source\n')
        self.root_patch = patch.object(package, 'ROOT', self.root)
        self.manifest_patch = patch.object(package, 'SOURCE_LIST', self.manifest)
        self.root_patch.start()
        self.manifest_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.manifest_patch.stop)

    def lines(self, *lines):
        self.manifest.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    def test_valid_manifest_sorted_and_byte_exact(self):
        self.lines('# source manifest', 'src/solver.c', 'src/board.c')
        files = package.source_paths()
        self.assertEqual(files, [('src/board.c', b'board-source\n', 0o644),
                                 ('src/solver.c', b'solver-source\n', 0o644)])

    def test_unsafe_windows_separators_drive_and_ads_rejected(self):
        for name in ('src\\..\\secrets.txt', 'src\\board.c',
                     'C:/sensitive/file.txt', 'src/board.c:private'):
            with self.subTest(name=name):
                self.lines(name)
                with self.assertRaisesRegex(ValueError, 'unsafe source path'):
                    package.source_paths()

    def test_windows_device_names_and_punctuation_rejected(self):
        invalid = ('src/CON.txt', 'src/prn.c', 'src/aux',
                   'src/NUL.log', 'src/com1.c', 'src/Lpt9.txt',
                   'src/COM¹.txt', 'src/CONIN$', 'src/a?.c',
                   'src/a*.c', 'src/a|b.c', 'src/space .',
                   'src/bad\x07name.c', 'src/name. ')
        for name in invalid:
            with self.subTest(name=name):
                self.lines(name)
                with self.assertRaisesRegex(ValueError, 'unsafe source path'):
                    package.source_paths()

    def test_windows_safe_filenames_are_still_allowed(self):
        self.lines('src/board.c', 'src/solver.c')
        self.assertEqual(len(package.source_paths()), 2)

    def test_absolute_and_parent_paths_rejected(self):
        for name in ('/etc/passwd', '../secrets.txt',
                     'src/../src/board.c', 'src/./board.c'):
            with self.subTest(name=name):
                self.lines(name)
                with self.assertRaisesRegex(ValueError, 'unsafe source path'):
                    package.source_paths()

    def test_parent_directory_symlink_rejected(self):
        external = Path(self.tmp.name) / 'outside'
        external.mkdir()
        (external / 'secret.txt').write_text('not in repository')
        link = self.root / 'alias'
        try:
            link.symlink_to(external, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('directory symlinks unavailable')
        self.lines('alias/secret.txt')
        with self.assertRaisesRegex(ValueError, 'symlink in source manifest path'):
            package.source_paths()

    def test_leaf_symlink_rejected(self):
        link = self.root / 'src' / 'alias.c'
        try:
            link.symlink_to(self.root / 'src' / 'board.c')
        except (OSError, NotImplementedError):
            self.skipTest('file symlinks unavailable')
        self.lines('src/alias.c')
        with self.assertRaisesRegex(ValueError, 'symlink in source manifest path'):
            package.source_paths()

    def test_source_manifest_symlink_rejected(self):
        alternate = self.root / 'alternate.txt'
        alternate.write_text('src/board.c\n')
        self.manifest.unlink()
        try:
            self.manifest.symlink_to(alternate)
        except (OSError, NotImplementedError):
            self.skipTest('manifest symlinks unavailable')
        with self.assertRaisesRegex(ValueError, 'symlinked source manifest refused'):
            package.source_paths()

    def test_missing_regular_file_rejected(self):
        self.lines('src/not-found.c')
        with self.assertRaisesRegex(ValueError, 'not a regular source file'):
            package.source_paths()

    def test_duplicate_manifest_entries_rejected(self):
        self.lines('src/board.c', 'src/board.c')
        with self.assertRaisesRegex(ValueError, 'duplicate source manifest path'):
            package.source_paths()

    def test_empty_manifest_rejected(self):
        self.lines('# comment only')
        with self.assertRaisesRegex(ValueError, 'empty source manifest'):
            package.source_paths()

    def test_bounded_regular_source_reads_actual_open_inode(self):
        regular = self.root / 'src' / 'board.c'
        self.assertEqual(package.bounded_file_bytes(regular, 14), b'board-source\n')
        with self.assertRaisesRegex(ValueError, 'package content exceeds size budget'):
            package.bounded_file_bytes(regular, 12)
        self.assertEqual(package.read_regular_source(
            regular, 14, 'source manifest'), b'board-source\n')

    def test_symlinked_leaf_is_refused_by_opened_descriptor(self):
        if not hasattr(os, 'O_NOFOLLOW'):
            self.skipTest('O_NOFOLLOW unavailable on this host')
        linked = self.root / 'src' / 'alias-source.c'
        try:
            linked.symlink_to(self.root / 'src' / 'board.c')
        except (OSError, NotImplementedError):
            self.skipTest('symlink creation unavailable')
        with self.assertRaises(OSError):
            package.bounded_file_bytes(linked, 64)

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'mkfifo'),
                         'POSIX FIFO required')
    def test_writerless_fifo_never_blocks_manifest_or_source_read(self):
        fifo = self.root / 'scripts' / 'writerless-manifest.fifo'
        os.mkfifo(fifo)
        # A subprocess timeout is deliberate: a regression to fopen() must
        # fail the test promptly instead of hanging the entire test suite.
        script = (
            'import importlib.util, pathlib, sys; '
            'spec=importlib.util.spec_from_file_location("packager",sys.argv[1]); '
            'mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); '
            'mod.read_regular_source(pathlib.Path(sys.argv[2]),128,sys.argv[3])'
        )
        for kind in ('source manifest', 'package content'):
            with self.subTest(kind=kind):
                result = subprocess.run(
                    [sys.executable, '-B', '-c', script, str(SOURCE),
                     str(fifo), kind],
                    capture_output=True, text=True, timeout=3)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(kind + ' must be a regular file', result.stderr)

    def test_nested_source_member_reads_pinned_directory(self):
        nested = self.root / 'src' / 'nested'
        nested.mkdir()
        (nested / 'good.c').write_bytes(b'actual source bytes')
        self.lines('src/nested/good.c')
        self.assertEqual(package.source_paths(),
                         [('src/nested/good.c', b'actual source bytes', 0o644)])

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NOFOLLOW') and
                         hasattr(os, 'O_DIRECTORY') and os.open in os.supports_dir_fd,
                         'POSIX openat/O_NOFOLLOW required')
    def test_parent_symlink_rejected_even_if_preflight_is_bypassed(self):
        outside = Path(self.tmp.name) / 'outside-source'
        outside.mkdir()
        (outside / 'secret.c').write_bytes(b'secret source bytes')
        shortcut = self.root / 'alias'
        shortcut.symlink_to(outside, target_is_directory=True)
        self.lines('alias/secret.c')
        # This simulates a symlink swap after the old Path.is_symlink
        # preflight but before the actual source file is opened.
        with patch.object(Path, 'is_symlink', return_value=False):
            with self.assertRaises(OSError):
                package.source_paths()

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NOFOLLOW') and
                         hasattr(os, 'O_DIRECTORY') and os.open in os.supports_dir_fd,
                         'POSIX openat/O_NOFOLLOW required')
    def test_leaf_symlink_rejected_by_pinned_directory_open(self):
        linked = self.root / 'src' / 'swapped.c'
        linked.symlink_to(self.root / 'src' / 'board.c')
        with self.assertRaises(OSError):
            package.read_source_member('src/swapped.c', 128)

    def test_source_member_rejects_parent_escape(self):
        for unsafe in ('../secrets.c', '/etc/passwd', 'src/../secret.c'):
            with self.subTest(name=unsafe):
                with self.assertRaisesRegex(ValueError, 'unsafe source member'):
                    package.read_source_member(unsafe, 4096)

    def test_manifest_file_must_be_regular_and_bounded(self):
        self.lines('src/board.c')
        self.assertEqual(len(package.source_paths()), 1)
        # The manifest itself is bounded before decoding or parsing.
        self.manifest.write_bytes(b'#' + b'a' *
                                  package.MAX_SOURCE_MANIFEST_BYTES)
        with self.assertRaisesRegex(ValueError, 'source manifest exceeds size budget'):
            package.source_paths()


if __name__ == '__main__':
    unittest.main()
