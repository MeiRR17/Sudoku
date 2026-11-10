"""Test streaming TAR archive bounds without building the Sudoku executable."""
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sudoku_package_release',
                                              ROOT / 'scripts' / 'package_release.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)
PREFIX = 'sudoku-v' + package.VERSION + '-source'


class StreamedTarVerificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='sudoku-tar-check-')
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'source.tar.gz'

    def archive(self, names, *, symlink=False, payload=b''):
        with tarfile.open(self.path, 'w:gz') as output:
            for index, name in enumerate(names):
                entry = tarfile.TarInfo(PREFIX + '/' + name)
                if symlink and index == 0:
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = '/etc/passwd'
                else:
                    entry.size = len(payload)
                output.addfile(entry, io.BytesIO(payload) if entry.isfile() else None)

    def test_valid_tar_content_is_preserved(self):
        self.archive(['a.txt', 'b.txt'], payload=b'hello')
        self.assertEqual(package.ensure_safe_archive(self.path, PREFIX),
                         {'a.txt': b'hello', 'b.txt': b'hello'})

    def test_exact_member_limit_is_accepted(self):
        self.archive([f'part{i:04d}.txt' for i in range(package.MAX_ARCHIVE_FILES)])
        self.assertEqual(len(package.ensure_safe_archive(self.path, PREFIX)),
                         package.MAX_ARCHIVE_FILES)

    def test_first_member_over_limit_is_rejected(self):
        self.archive([f'part{i:04d}.txt'
                      for i in range(package.MAX_ARCHIVE_FILES + 1)])
        with self.assertRaisesRegex(ValueError, 'invalid number of TAR members'):
            package.ensure_safe_archive(self.path, PREFIX)

    def test_empty_tar_is_rejected(self):
        self.archive([])
        with self.assertRaisesRegex(ValueError, 'invalid number of TAR members'):
            package.ensure_safe_archive(self.path, PREFIX)

    def test_duplicate_tar_name_is_rejected(self):
        self.archive(['a.txt', 'a.txt'])
        with self.assertRaisesRegex(ValueError, 'duplicated'):
            package.ensure_safe_archive(self.path, PREFIX)

    def test_unsorted_tar_is_rejected(self):
        self.archive(['b.txt', 'a.txt'])
        with self.assertRaisesRegex(ValueError, 'not sorted'):
            package.ensure_safe_archive(self.path, PREFIX)

    def test_tar_symlink_is_rejected(self):
        self.archive(['link'], symlink=True)
        with self.assertRaisesRegex(ValueError, 'non-regular TAR member'):
            package.ensure_safe_archive(self.path, PREFIX)

    def test_windows_unsafe_tar_names_rejected(self):
        for name in ('con.txt', 'COM1.txt', 'NUL', 'a:stream', 'bad?.txt',
                     'trailing.', 'trailing ', 'COM².txt'):
            with self.subTest(name=name):
                self.archive([name])
                with self.assertRaisesRegex(ValueError, 'unsafe archive member'):
                    package.ensure_safe_archive(self.path, PREFIX)

    def test_portable_normal_tar_names_accepted(self):
        self.archive(['.github/workflows/build.yml', 'src/main.c'], payload=b'abc')
        self.assertEqual(package.ensure_safe_archive(self.path, PREFIX),
                         {'.github/workflows/build.yml': b'abc', 'src/main.c': b'abc'})

    def test_tar_traversal_is_rejected(self):
        self.archive(['../escape'])
        with self.assertRaisesRegex(ValueError, 'unsafe archive member'):
            package.ensure_safe_archive(self.path, PREFIX)


if __name__ == '__main__':
    unittest.main()
