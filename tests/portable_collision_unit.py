"""Reject portable-path collisions before source, install or archive publication.

Uses real ZIP/TAR members plus a bounded case-sensitive temporary file tree.
Pure path-component checks run on all platforms without filesystem assumptions.
"""
import importlib.util
import io
import os
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sudoku_collision_packager',
                                               ROOT / 'scripts' / 'package_release.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)
PREFIX = 'sudoku-v' + package.VERSION + '-source'


class PortableCollisionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='sudoku-name-collision-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def tar(self, names):
        path = self.base / 'sample.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            for name in names:
                data = b'content'
                member = tarfile.TarInfo(PREFIX + '/' + name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        return path

    def zip(self, names):
        path = self.base / 'sample.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            for name in names:
                member = zipfile.ZipInfo(PREFIX + '/' + name)
                member.create_system = 3
                member.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(member, b'content')
        return path

    def test_file_name_case_collision(self):
        for archive in (self.tar, self.zip):
            with self.subTest(format=archive.__name__):
                with self.assertRaisesRegex(ValueError, 'nonportable path collision'):
                    package.ensure_safe_archive(archive(['README.md', 'readme.md']), PREFIX)

    def test_parent_directory_case_collision(self):
        for archive in (self.tar, self.zip):
            with self.subTest(format=archive.__name__):
                with self.assertRaisesRegex(ValueError, 'nonportable path collision'):
                    package.ensure_safe_archive(archive(['Docs/a.txt', 'docs/b.txt']), PREFIX)

    def test_unicode_casefold_collision(self):
        for archive in (self.tar, self.zip):
            with self.subTest(format=archive.__name__):
                with self.assertRaisesRegex(ValueError, 'nonportable path collision'):
                    package.ensure_safe_archive(archive(['STRASSE.txt', 'straße.txt']), PREFIX)

    def test_unicode_normalization_collision(self):
        for archive in (self.tar, self.zip):
            with self.subTest(format=archive.__name__):
                with self.assertRaisesRegex(ValueError, 'nonportable path collision'):
                    package.ensure_safe_archive(archive(['e\u0301.txt', 'é.txt']), PREFIX)

    def test_file_directory_collision_both_orders(self):
        for names in (('folder', 'folder/item'), ('folder/item', 'folder')):
            with self.subTest(names=names):
                with self.assertRaisesRegex(ValueError, 'nonportable path collision'):
                    package.ensure_safe_archive(self.tar(names), PREFIX)

    def test_reused_identical_directory_prefix_is_valid(self):
        names = ['src/board.c', 'src/game.c']
        for archive in (self.tar, self.zip):
            with self.subTest(format=archive.__name__):
                self.assertEqual(list(package.ensure_safe_archive(archive(names), PREFIX)), names)

    def test_explicit_exact_duplicate_keeps_original_error(self):
        for archive in (self.tar, self.zip):
            with self.subTest(format=archive.__name__):
                with self.assertRaisesRegex(ValueError, 'duplicated'):
                    package.ensure_safe_archive(archive(['src/a.c', 'src/a.c']), PREFIX)

    def test_source_manifest_rejects_case_alias(self):
        if os.name == 'nt' or sys.platform == 'darwin':
            self.skipTest('requires a case-sensitive source filesystem')
        root = self.base / 'source'
        (root / 'scripts').mkdir(parents=True)
        (root / 'README.md').write_bytes(b'one')
        (root / 'readme.md').write_bytes(b'two')
        manifest = root / 'scripts' / 'release_files.txt'
        manifest.write_text('README.md\nreadme.md\n', encoding='utf-8')
        with patch.object(package, 'ROOT', root), patch.object(package, 'SOURCE_LIST', manifest):
            with self.assertRaisesRegex(ValueError, 'nonportable path collision'):
                package.source_paths()

    def test_installed_paths_reject_case_alias(self):
        if os.name == 'nt' or sys.platform == 'darwin':
            self.skipTest('requires a case-sensitive installation filesystem')
        root = self.base / 'install'
        (root / 'bin').mkdir(parents=True)
        (root / 'bin' / 'sudoku').write_bytes(b'bin')
        (root / 'Foo.txt').write_bytes(b'one')
        (root / 'foo.txt').write_bytes(b'two')
        with self.assertRaisesRegex(ValueError, 'nonportable path collision'):
            package.installed_paths(root)

    def test_only_a_bounded_number_of_prefixes_is_retained(self):
        seen = {}
        package.claim_portable_path('a/b/c', seen)
        package.claim_portable_path('a/b/d', seen)
        self.assertEqual(len(seen), 4)
        with self.assertRaisesRegex(ValueError, 'nonportable path collision'):
            package.claim_portable_path('A/x', seen)


if __name__ == '__main__':
    unittest.main()
