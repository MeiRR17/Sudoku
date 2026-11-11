"""Byte budgets for release manifests and compressed containers.

Real canonical ZIP/TAR.GZ four-archive smoke fixture; malformed inputs must
fail before expensive checksums, member allocation or streamed extraction.
"""
import hashlib
import importlib.util
import io
import os
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

    def test_file_hash_matches_sha256_for_regular_zip_bytes(self):
        archive = self.root / 'normal.zip'
        payload = b'canonical archive test' * 9
        archive.write_bytes(payload)
        self.assertEqual(package.file_hash(archive), hashlib.sha256(payload).hexdigest())

    def test_file_hash_oversized_sparse_archive_rejected(self):
        archive = self.root / 'oversized.zip'
        with archive.open('wb') as stream:
            stream.truncate(package.MAX_ZIP_ARCHIVE_BYTES + 1)
        with self.assertRaisesRegex(ValueError, 'archive exceeds compressed size budget'):
            package.file_hash(archive)

    def test_file_hash_rejects_nonregular_device(self):
        if os.name != 'posix' or not Path('/dev/null').exists():
            self.skipTest('POSIX character device unavailable')
        with self.assertRaisesRegex(ValueError, 'release archive must be a regular file'):
            package.file_hash(Path('/dev/null'))

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'mkfifo'),
                         'POSIX FIFO support required')
    def test_replaced_checksum_manifest_fifo_never_blocks(self):
        import subprocess
        import sys
        pipe = self.root / 'SHA256SUMS'
        os.mkfifo(pipe)
        # Simulate a positive path preflight before replacement by a pipe.
        # Timeouts prevent a regression to blocking open() from hanging CTest.
        code = (
            'import importlib.util, pathlib, unittest.mock, sys; '
            'spec=importlib.util.spec_from_file_location("pack",sys.argv[1]); '
            'pkg=importlib.util.module_from_spec(spec); spec.loader.exec_module(pkg); '
            'p=pathlib.Path(sys.argv[2]); '
            'mock=unittest.mock; '
            'ctx=mock.patch.object(pathlib.Path,"is_file",return_value=True); '
            'ctx2=mock.patch.object(pathlib.Path,"is_symlink",return_value=False); '
            'ctx.__enter__(); ctx2.__enter__(); '
            'pkg.verify_packages(p)'
        )
        process = subprocess.run(
            [sys.executable, '-B', '-c', code, str(ROOT / 'scripts' / 'package_release.py'),
             str(self.root)],
            capture_output=True, text=True, timeout=3)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('SHA256SUMS must be a regular file', process.stderr)

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'mkfifo'),
                         'POSIX FIFO support required')
    def test_swapped_archive_fifo_rejected_before_hash_or_parser(self):
        import subprocess
        import sys
        pipe = self.root / 'replaced.zip'
        os.mkfifo(pipe)
        code = (
            'import importlib.util, pathlib, sys; '
            'spec=importlib.util.spec_from_file_location("pack",sys.argv[1]); '
            'pkg=importlib.util.module_from_spec(spec); spec.loader.exec_module(pkg); '
            'pkg.file_hash(pathlib.Path(sys.argv[2]))'
        )
        process = subprocess.run(
            [sys.executable, '-B', '-c', code, str(ROOT / 'scripts' / 'package_release.py'),
             str(pipe)],
            capture_output=True, text=True, timeout=3)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('release archive must be a regular file', process.stderr)

    def test_final_archive_symlink_rejected_during_hash(self):
        if not hasattr(os, 'O_NOFOLLOW'):
            self.skipTest('O_NOFOLLOW unavailable')
        ordinary = self.root / 'real.zip'
        ordinary.write_bytes(b'ordinary')
        link = self.root / 'link.zip'
        try:
            link.symlink_to(ordinary)
        except (OSError, NotImplementedError):
            self.skipTest('symlink creation unavailable')
        with self.assertRaises(OSError):
            package.file_hash(link)

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
