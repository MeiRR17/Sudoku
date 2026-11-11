"""Test streaming TAR archive bounds without building the Sudoku executable."""
import importlib.util
import gzip
from unittest.mock import patch
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

    def test_valid_gzip_with_non_tar_payload_is_rejected_cleanly(self):
        # Real gzip stream, invalid TAR header: tarfile raises ReadError.
        with gzip.open(self.path, 'wb') as stream:
            stream.write(b'not a tar header' * 70)
        with self.assertRaisesRegex(ValueError, 'malformed archive container'):
            package.ensure_safe_archive(self.path, PREFIX)

    def test_truncated_gzip_tar_is_rejected_cleanly(self):
        self.archive(['a.txt'], payload=b'file-data')
        self.path.write_bytes(self.path.read_bytes()[:18])
        with self.assertRaisesRegex(ValueError, 'malformed archive container'):
            package.ensure_safe_archive(self.path, PREFIX)

    def test_missing_gzip_trailer_rejected_even_with_intact_tar_members(self):
        self.archive(['a.txt'], payload=b'hello')
        # Removing just CRC32+ISIZE leaves all TAR records readable. The
        # decoder must be drained past the TAR end marker to notice this.
        original = self.path.read_bytes()
        self.path.write_bytes(original[:-8])
        with self.assertRaisesRegex(ValueError, 'malformed archive container'):
            package.ensure_safe_archive(self.path, PREFIX)

    def test_corrupt_gzip_trailer_rejected_even_with_intact_tar_members(self):
        self.archive(['a.txt'], payload=b'hello')
        corrupt = bytearray(self.path.read_bytes())
        corrupt[-8] ^= 1  # GZIP CRC32 bit, not member/TAR bytes.
        self.path.write_bytes(corrupt)
        with self.assertRaisesRegex(ValueError, 'malformed archive container'):
            package.ensure_safe_archive(self.path, PREFIX)

    def test_concatenated_gzip_with_nonzero_extra_tar_data_rejected(self):
        self.archive(['a.txt'], payload=b'hello')
        self.path.write_bytes(self.path.read_bytes() + gzip.compress(b'hidden-data'))
        with self.assertRaisesRegex(ValueError, 'non-zero trailing TAR data'):
            package.ensure_safe_archive(self.path, PREFIX)

    def test_zero_only_concatenated_gzip_member_rejected(self):
        self.archive(['a.txt'], payload=b'hello')
        self.path.write_bytes(self.path.read_bytes() + gzip.compress(b'\0' * 10240))
        with self.assertRaisesRegex(ValueError, 'non-canonical TAR padding length'):
            package.ensure_safe_archive(self.path, PREFIX)

    def test_empty_concatenated_gzip_member_rejected(self):
        self.archive(['a.txt'], payload=b'hello')
        self.path.write_bytes(self.path.read_bytes() + gzip.compress(b''))
        with self.assertRaisesRegex(ValueError, 'non-canonical GZIP trailer or extra member'):
            package.ensure_safe_archive(self.path, PREFIX)

    def test_raw_zero_bytes_after_gzip_trailer_rejected(self):
        self.archive(['a.txt'], payload=b'hello')
        self.path.write_bytes(self.path.read_bytes() + b'\0' * 64)
        with self.assertRaisesRegex(ValueError, 'non-canonical GZIP trailer or extra member'):
            package.ensure_safe_archive(self.path, PREFIX)

    def test_valid_gzip_with_extra_zero_tar_records_rejected(self):
        self.archive(['a.txt'], payload=b'hello')
        uncompressed = gzip.decompress(self.path.read_bytes())
        # Valid recomputed CRC/ISIZE, but too many TAR padding records.
        with gzip.open(self.path, 'wb') as stream:
            stream.write(uncompressed + b'\0' * 10240)
        with self.assertRaisesRegex(ValueError, 'non-canonical TAR padding length'):
            package.ensure_safe_archive(self.path, PREFIX)

    def test_long_pax_tar_member_still_accepted(self):
        filename = 'nested/' + 'longfile' * 18 + '.txt'
        self.archive([filename], payload=b'hello')
        self.assertEqual(package.ensure_safe_archive(self.path, PREFIX),
                         {filename: b'hello'})

    def test_decoded_tar_padding_budget_is_enforced(self):
        self.archive(['a.txt'], payload=b'hello')
        # Standard TAR has at least 10 KiB of data and zero padding; a
        # smaller synthetic budget must fail during the actual decoder read.
        with patch.object(package, 'MAX_TAR_DECODED_BYTES', 1024):
            with self.assertRaisesRegex(ValueError, 'TAR decoded stream exceeds size budget'):
                package.ensure_safe_archive(self.path, PREFIX)

    def test_tar_source_file_mode_must_be_portable(self):
        with tarfile.open(self.path, 'w:gz') as output:
            entry = tarfile.TarInfo(PREFIX + '/README.md')
            entry.mode = 0o777
            entry.size = 4
            output.addfile(entry, io.BytesIO(b'text'))
        with self.assertRaisesRegex(ValueError, 'non-canonical TAR file mode'):
            package.ensure_safe_archive(self.path, PREFIX)

    def test_tar_binary_executable_bit_cannot_be_removed(self):
        binary_prefix = f'sudoku-v{package.VERSION}-linux-x86_64'
        with tarfile.open(self.path, 'w:gz') as output:
            entry = tarfile.TarInfo(binary_prefix + '/bin/sudoku')
            entry.mode = 0o644  # Same binary bytes, no Unix execute permission.
            entry.size = 4
            output.addfile(entry, io.BytesIO(b'game'))
        with self.assertRaisesRegex(ValueError, 'non-canonical TAR file mode'):
            package.ensure_safe_archive(self.path, binary_prefix)

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
