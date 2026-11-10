"""ZIP central-directory preflight regression tests (stdlib only).

These tests use real ZIP files, then forge only the 22-byte directory trailer.
Malformed archives must fail *before* Python zipfile builds an eager filelist.
"""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sudoku_zip_preflight',
                                              ROOT / 'scripts' / 'package_release.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class ZipPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sudoku-zip-preflight-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'sample.zip'
        self.prefix = 'sudoku-v' + package.VERSION + '-source'

    def archive(self, names=('a.txt',)):
        package.create_zip(self.path, self.prefix,
                           [(name, name.encode('ascii'), 0o644) for name in names])
        return self.path

    def change_trailer(self, offset, fmt, value):
        data = bytearray(self.path.read_bytes())
        struct.pack_into(fmt, data, len(data) - 22 + offset, value)
        self.path.write_bytes(data)

    def test_standard_archive_with_one_and_multiple_files(self):
        for names in (('a.txt',), ('a.txt', 'b.txt', 'nested/c.txt')):
            with self.subTest(names=names):
                self.archive(names)
                package.preflight_zip_directory(self.path)
                contents = package.ensure_safe_archive(self.path, self.prefix)
                self.assertEqual(set(contents), set(names))

    def test_corrupt_zip_payload_crc_is_reported_as_verification_failure(self):
        # Canonical central directory and regular member, but damaged data.
        # zipfile raises BadZipFile on CRC mismatch while extracting bytes.
        with zipfile.ZipFile(self.path, 'w', compression=zipfile.ZIP_STORED) as archive:
            info = zipfile.ZipInfo(self.prefix + '/crc.txt',
                                   date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, b'unique-crc-test-payload')
        data = bytearray(self.path.read_bytes())
        at = data.index(b'unique-crc-test-payload')
        data[at] ^= 1
        self.path.write_bytes(data)
        # The structural preflight still succeeds: failure must come from
        # reading the changed member, and be normalized to ValueError.
        package.preflight_zip_directory(self.path)
        with self.assertRaisesRegex(ValueError, 'malformed archive container'):
            package.ensure_safe_archive(self.path, self.prefix)

    def test_encrypted_member_rejected_before_decryption(self):
        self.archive()
        data = bytearray(self.path.read_bytes())
        local = data.index(b'PK' + bytes((3, 4)))
        central = data.index(b'PK' + bytes((1, 2)))
        # Set encryption bit in both headers; ZipExtFile would otherwise
        # raise RuntimeError because no password was supplied.
        for at in (local + 6, central + 8):
            flags = struct.unpack_from('<H', data, at)[0]
            struct.pack_into('<H', data, at, flags | 1)
        self.path.write_bytes(data)
        package.preflight_zip_directory(self.path)
        with self.assertRaisesRegex(ValueError, 'encrypted ZIP member'):
            package.ensure_safe_archive(self.path, self.prefix)

    def test_strong_encryption_marker_rejected(self):
        self.archive()
        data = bytearray(self.path.read_bytes())
        local = data.index(b'PK' + bytes((3, 4)))
        central = data.index(b'PK' + bytes((1, 2)))
        for at in (local + 6, central + 8):
            flags = struct.unpack_from('<H', data, at)[0]
            struct.pack_into('<H', data, at, flags | 0x40)
        self.path.write_bytes(data)
        package.preflight_zip_directory(self.path)
        with self.assertRaisesRegex(ValueError, 'encrypted ZIP member'):
            package.ensure_safe_archive(self.path, self.prefix)

    def test_unsupported_zip_compression_method_rejected(self):
        self.archive()
        data = bytearray(self.path.read_bytes())
        local = data.index(b'PK' + bytes((3, 4)))
        central = data.index(b'PK' + bytes((1, 2)))
        for at in (local + 8, central + 10):
            struct.pack_into('<H', data, at, 99)
        self.path.write_bytes(data)
        package.preflight_zip_directory(self.path)
        with self.assertRaisesRegex(ValueError, 'unsupported ZIP compression method'):
            package.ensure_safe_archive(self.path, self.prefix)

    def test_too_many_members_rejected_before_zipfile(self):
        self.archive()
        self.change_trailer(8, '<H', package.MAX_ARCHIVE_FILES + 1)
        self.change_trailer(10, '<H', package.MAX_ARCHIVE_FILES + 1)
        with patch.object(package.zipfile, 'ZipFile',
                          side_effect=AssertionError('ZipFile must not open')):
            with self.assertRaisesRegex(ValueError, 'invalid number of ZIP members'):
                package.ensure_safe_archive(self.path, self.prefix)

    def test_forged_small_count_does_not_hide_extra_central_records(self):
        self.archive(('a.txt', 'b.txt'))
        self.change_trailer(8, '<H', 1)
        self.change_trailer(10, '<H', 1)
        with patch.object(package.zipfile, 'ZipFile',
                          side_effect=AssertionError('ZipFile must not open')):
            with self.assertRaisesRegex(ValueError, 'central directory entry count mismatch'):
                package.ensure_safe_archive(self.path, self.prefix)

    def test_corrupt_central_record_header_rejected(self):
        self.archive()
        data = bytearray(self.path.read_bytes())
        directory_start = struct.unpack_from('<I', data, len(data) - 22 + 16)[0]
        data[directory_start:directory_start + 4] = b'XXXX'
        self.path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'central directory entry count mismatch'):
            package.preflight_zip_directory(self.path)

    def test_central_directory_zip64_sentinel_rejected(self):
        self.archive()
        data = bytearray(self.path.read_bytes())
        directory_start = struct.unpack_from('<I', data, len(data) - 22 + 16)[0]
        struct.pack_into('<I', data, directory_start + 20, 0xffffffff)
        self.path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'ZIP64 entries are not canonical'):
            package.preflight_zip_directory(self.path)

    def test_zero_members_rejected(self):
        self.archive()
        self.change_trailer(8, '<H', 0)
        self.change_trailer(10, '<H', 0)
        with self.assertRaisesRegex(ValueError, 'invalid number of ZIP members'):
            package.preflight_zip_directory(self.path)

    def test_zip64_count_sentinel_rejected(self):
        self.archive()
        self.change_trailer(8, '<H', 65535)
        self.change_trailer(10, '<H', 65535)
        with self.assertRaisesRegex(ValueError, 'invalid number of ZIP members'):
            package.preflight_zip_directory(self.path)

    def test_split_disk_rejected(self):
        self.archive()
        self.change_trailer(4, '<H', 1)
        with self.assertRaisesRegex(ValueError, 'multi-disk'):
            package.preflight_zip_directory(self.path)

    def test_disk_entry_count_mismatch_rejected(self):
        self.archive()
        self.change_trailer(8, '<H', 2)
        with self.assertRaisesRegex(ValueError, 'multi-disk'):
            package.preflight_zip_directory(self.path)

    def test_oversized_central_directory_rejected(self):
        self.archive()
        self.change_trailer(12, '<I', package.MAX_ZIP_DIRECTORY_BYTES + 1)
        with self.assertRaisesRegex(ValueError, 'central directory exceeds budget'):
            package.preflight_zip_directory(self.path)

    def test_forged_directory_offset_rejected(self):
        self.archive()
        self.change_trailer(16, '<I', 0xffffffff)
        with self.assertRaisesRegex(ValueError, 'central directory exceeds budget'):
            package.preflight_zip_directory(self.path)

    def test_noncanonical_comment_rejected(self):
        self.archive()
        self.change_trailer(20, '<H', 1)
        with self.assertRaisesRegex(ValueError, 'canonical directory trailer'):
            package.preflight_zip_directory(self.path)

    def test_missing_eocd_signature_rejected(self):
        self.archive()
        self.change_trailer(0, '<I', 0)
        with self.assertRaisesRegex(ValueError, 'canonical directory trailer'):
            package.preflight_zip_directory(self.path)

    def test_short_file_rejected(self):
        self.path.write_bytes(b'PK')
        with self.assertRaisesRegex(ValueError, 'size budget or is truncated'):
            package.preflight_zip_directory(self.path)

    def test_sparse_oversized_zip_rejected_without_reading_it(self):
        with self.path.open('wb') as file:
            file.truncate(package.MAX_ZIP_ARCHIVE_BYTES + 1)
        with self.assertRaisesRegex(ValueError, 'size budget or is truncated'):
            package.preflight_zip_directory(self.path)


if __name__ == '__main__':
    unittest.main()
