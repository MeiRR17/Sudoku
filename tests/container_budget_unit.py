"""Byte budgets for release manifests and compressed containers.

Real canonical ZIP/TAR.GZ four-archive smoke fixture; malformed inputs must
fail before expensive checksums, member allocation or streamed extraction.
"""
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sudoku_container_budget',
                                              ROOT / 'scripts' / 'package_release.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)
PREFIX = 'sudoku-v' + package.VERSION + '-source'


class ContainerBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='sudoku-container-budget-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_oversized_checksum_manifest_rejected_before_hash(self):
        (self.root / 'SHA256SUMS').write_bytes(b'x' * (package.MAX_CHECKSUM_MANIFEST_BYTES + 1))
        with patch.object(package, 'file_hash', side_effect=AssertionError('hash must not run')):
            with self.assertRaisesRegex(ValueError, 'SHA256SUMS exceeds size budget'):
                package.verify_packages(self.root)

    def test_nonascii_checksum_manifest_rejected(self):
        (self.root / 'SHA256SUMS').write_bytes(b'\xff\n')
        with self.assertRaisesRegex(ValueError, 'SHA256SUMS must be ASCII'):
            package.verify_packages(self.root)

    def test_missing_checksum_manifest_rejected(self):
        with self.assertRaisesRegex(ValueError, 'missing or unsafe SHA256SUMS'):
            package.verify_packages(self.root)

    def test_too_few_checksum_records_rejected(self):
        (self.root / 'SHA256SUMS').write_bytes(b'\n')
        with self.assertRaisesRegex(ValueError, 'expected four distinct archive checksums'):
            package.verify_packages(self.root)

    def test_oversized_tar_rejected_before_tar_parser(self):
        archive = self.root / 'large.tar.gz'
        with archive.open('wb') as output:
            output.truncate(package.MAX_TAR_ARCHIVE_BYTES + 1)
        with patch.object(package.tarfile, 'open',
                          side_effect=AssertionError('tar parser must not open')):
            with self.assertRaisesRegex(ValueError, 'TAR container exceeds compressed size budget'):
                package.ensure_safe_archive(archive, PREFIX)

    def test_tar_at_limit_reaches_parser(self):
        archive = self.root / 'limit.tar.gz'
        with archive.open('wb') as output:
            output.truncate(package.MAX_TAR_ARCHIVE_BYTES)
        with patch.object(package.tarfile, 'open',
                          side_effect=RuntimeError('tar parser reached')):
            with self.assertRaisesRegex(RuntimeError, 'tar parser reached'):
                package.ensure_safe_archive(archive, PREFIX)

    def test_archive_checked_before_checksum_hash(self):
        prefix = 'sudoku-v' + package.VERSION + '-linux-x86_64'
        names = [prefix + '.tar.gz', prefix + '.zip',
                 PREFIX + '.tar.gz', PREFIX + '.zip']
        (self.root / 'SHA256SUMS').write_text(
            ''.join('0' * 64 + '  ' + name + '\n' for name in names),
            encoding='ascii')
        # The first archive exceeds the budget. None of the 80 MiB contents
        # must be streamed through file_hash, regardless of digest validity.
        with (self.root / names[0]).open('wb') as output:
            output.truncate(package.MAX_TAR_ARCHIVE_BYTES + 1)
        with patch.object(package, 'file_hash',
                          side_effect=AssertionError('hash must not run')):
            with self.assertRaisesRegex(ValueError, 'archive exceeds compressed size budget'):
                package.verify_packages(self.root)

    def test_small_valid_tar_stream_remains_readable(self):
        archive = self.root / 'small.tar.gz'
        with tarfile.open(archive, 'w:gz') as writer:
            entry = tarfile.TarInfo(PREFIX + '/a.txt')
            payload = b'ok'
            entry.size = len(payload)
            writer.addfile(entry, io.BytesIO(payload))
        self.assertEqual(package.ensure_safe_archive(archive, PREFIX),
                         {'a.txt': b'ok'})

    def test_real_four_archive_distribution_passes(self):
        required_source = ('README.md', 'CMakeLists.txt',
                           'src/core/solver.c', 'src/core/game.c',
                           'scripts/package_release.py',
                           'scripts/release_files.txt')
        source = [(p, b'placeholder', 0o644) for p in required_source]
        source[-1] = (source[-1][0], ('\n'.join(required_source) + '\n').encode(), 0o644)
        binary = [(p, b'placeholder', mode) for p, mode in (
            ('bin/sudoku', 0o755), ('include/sudoku/board.h', 0o644),
            ('include/sudoku/game.h', 0o644))]
        manifest = []
        for prefix, files in ((PREFIX, source),
                              ('sudoku-v' + package.VERSION + '-linux-x86_64', binary)):
            for extension, writer in (('.zip', package.create_zip),
                                      ('.tar.gz', package.create_tar)):
                path = self.root / (prefix + extension)
                writer(path, prefix, files)
                manifest.append((path.name, package.file_hash(path)))
        (self.root / 'SHA256SUMS').write_text(
            ''.join(digest + '  ' + name + '\n'
                    for name, digest in sorted(manifest)), encoding='ascii')
        package.verify_packages(self.root)


if __name__ == '__main__':
    unittest.main()
