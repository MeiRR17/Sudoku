"""Guard release-source manifest portability and symlink containment.

Uses real temporary files; no CMake toolchain or network required.
"""
import importlib.util
from pathlib import Path
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


if __name__ == '__main__':
    unittest.main()
