"""Fast, dependency-free guards for exact-SHA platform acceptance.

Never creates a receipt or requires a native toolchain. The full acceptance
script still must run on each real target host before any release claim.
"""
import importlib.util
import hashlib
import json
import os
import stat
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'scripts' / 'platform_acceptance.py'
spec = importlib.util.spec_from_file_location('sudoku_platform_acceptance', SOURCE)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)

SHA = 'a' * 40
OTHER_SHA = 'b' * 40


class CheckoutGuardTests(unittest.TestCase):
    def fake_git(self, status='', head=SHA):
        def call(*args, capture=False):
            self.assertTrue(capture)
            if args[:3] == ('git', 'rev-parse', '--verify'):
                self.assertEqual(args[3], 'HEAD')
                return head
            self.assertEqual(args, ('git', 'status', '--porcelain', '--untracked-files=all'))
            return status
        return call

    def test_clean_exact_sha_passes(self):
        with patch.object(acceptance, 'call', self.fake_git()):
            self.assertEqual(acceptance.verify_checkout(SHA), SHA)

    def test_clean_checkout_without_constraint_passes_locally(self):
        with patch.object(acceptance, 'call', self.fake_git()):
            self.assertEqual(acceptance.verify_checkout(), SHA)

    def test_mismatched_required_sha_fails(self):
        with patch.object(acceptance, 'call', self.fake_git()):
            with self.assertRaisesRegex(ValueError, 'does not match required SHA'):
                acceptance.verify_checkout(OTHER_SHA)

    def test_malformed_required_sha_fails(self):
        with patch.object(acceptance, 'call', self.fake_git()):
            with self.assertRaisesRegex(ValueError, '40 lowercase hex'):
                acceptance.verify_checkout('main')

    def test_invalid_actual_sha_fails(self):
        with patch.object(acceptance, 'call', self.fake_git(head='not-a-commit')):
            with self.assertRaisesRegex(ValueError, 'exact Git commit'):
                acceptance.verify_checkout()

    def test_untracked_file_blocks_receipt(self):
        with patch.object(acceptance, 'call', self.fake_git(status='?? injected.c')):
            with self.assertRaisesRegex(ValueError, 'tracked or untracked'):
                acceptance.verify_checkout(SHA)

    def test_tracked_change_blocks_receipt(self):
        with patch.object(acceptance, 'call', self.fake_git(status=' M src/core/game.c')):
            with self.assertRaisesRegex(ValueError, 'tracked or untracked'):
                acceptance.verify_checkout(SHA)


class CompilerIdentityTests(unittest.TestCase):
    def test_supported_compiler_id_parsing(self):
        for name in ('MSVC', 'AppleClang', 'GNU', 'Clang'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                build = Path(folder)
                compiler_file = build / 'CMakeFiles/3.31.0/CMakeCCompiler.cmake'
                compiler_file.parent.mkdir(parents=True)
                compiler_file.write_text(f'set(CMAKE_C_COMPILER_ID "{name}")\n',
                                         encoding='utf-8')
                self.assertEqual(acceptance.compiler_identity(build), name)

    def test_missing_compiler_identity_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'exactly one'):
                acceptance.compiler_identity(Path(folder))


class ReceiptWriteTests(unittest.TestCase):
    def test_private_atomic_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'dist' / 'platform-receipt.json'
            receipt = {'status': 'passed', 'git_commit_sha': SHA}
            acceptance.write_receipt(dest, receipt)
            self.assertEqual(json.loads(dest.read_text()), receipt)
            self.assertFalse(dest.with_name(dest.name + '.tmp').exists())
            if os.name == 'posix':
                self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o600)

    def test_existing_receipt_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'evidence.json'
            dest.write_text('previous')
            with self.assertRaises(FileExistsError):
                acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertEqual(dest.read_text(), 'previous')
            self.assertFalse(dest.with_name(dest.name + '.tmp').exists())

    def test_existing_temporary_symlink_cannot_be_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            victim = root / 'victim.txt'
            victim.write_text('unchanged')
            dest = root / 'evidence.json'
            stage = root / 'evidence.json.tmp'
            try:
                stage.symlink_to(victim)
            except (OSError, NotImplementedError):
                self.skipTest('host cannot create a symlink')
            with self.assertRaises(FileExistsError):
                acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertEqual(victim.read_text(), 'unchanged')
            self.assertTrue(stage.is_symlink())
            self.assertFalse(dest.exists())

    def test_unsupported_hardlink_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'evidence.json'
            with patch.object(acceptance.os, 'link', side_effect=OSError('unsupported')):
                with self.assertRaises(OSError):
                    acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertFalse(dest.exists())
            self.assertFalse(dest.with_name(dest.name + '.tmp').exists())

    def test_serialization_failure_cleans_up_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'evidence.json'
            with self.assertRaises(TypeError):
                acceptance.write_receipt(dest, {'value': object()})
            self.assertFalse(dest.exists())
            self.assertFalse(dest.with_name(dest.name + '.tmp').exists())

class ArchiveReceiptHashTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='sudoku-archive-receipt-')
        self.addCleanup(self.directory.cleanup)
        self.dist = Path(self.directory.name)
        self.version = '0.8.4'
        self.names = sorted('sudoku-v0.8.4-' + kind + ext
                            for kind in ('source', 'linux-x86_64')
                            for ext in ('.zip', '.tar.gz'))
        for name in self.names:
            (self.dist / name).write_bytes(name.encode('ascii'))
        self.rehash()

    def rehash(self):
        (self.dist / 'SHA256SUMS').write_text(''.join(
            hashlib.sha256((self.dist / name).read_bytes()).hexdigest() +
            '  ' + name + '\n' for name in self.names), encoding='ascii')

    def check(self):
        return acceptance.verified_archive_hashes(self.dist, self.version,
                                                   'ubuntu-latest')

    def test_four_exact_archive_hashes_pass(self):
        self.assertEqual(sorted(self.check()), self.names)

    def test_modified_archive_fails(self):
        (self.dist / self.names[0]).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'archive changed'):
            self.check()

    def test_sparse_oversized_archive_is_rejected_before_hash(self):
        with (self.dist / self.names[0]).open('wb') as stream:
            stream.truncate(acceptance.MAX_ARCHIVE_BYTES + 1)
        with self.assertRaisesRegex(ValueError, 'archive exceeds size budget'):
            self.check()

    def test_symlinked_archive_is_rejected(self):
        source = self.dist / self.names[0]
        backup = self.dist / 'backup.archive'
        source.rename(backup)
        try:
            source.symlink_to(backup)
        except (OSError, NotImplementedError):
            self.skipTest('symlink creation unavailable')
        with self.assertRaisesRegex(ValueError, 'missing or unsafe archive'):
            self.check()

    def test_oversized_checksum_manifest_is_rejected(self):
        (self.dist / 'SHA256SUMS').write_bytes(b'x' *
                                               (acceptance.MAX_CHECKSUM_BYTES + 1))
        with self.assertRaisesRegex(ValueError, 'SHA256SUMS exceeds size budget'):
            self.check()

    def test_duplicate_or_unsorted_manifest_rejected(self):
        path = self.dist / 'SHA256SUMS'
        lines = path.read_text().splitlines()
        path.write_text('\n'.join(lines[::-1]) + '\n', encoding='ascii')
        with self.assertRaisesRegex(ValueError, 'wrong or unsorted'):
            self.check()
        path.write_text('\n'.join([lines[0]] * 4) + '\n', encoding='ascii')
        with self.assertRaisesRegex(ValueError, 'duplicate SHA256SUMS'):
            self.check()

    def test_unexpected_platform_archive_rejected(self):
        filename = self.names[0].replace('linux-x86_64', 'macos-arm64')
        (self.dist / filename).write_bytes(b'wrong platform')
        self.names[0] = filename
        self.rehash()
        with self.assertRaisesRegex(ValueError, 'wrong or unsorted'):
            self.check()


if __name__ == '__main__':
    unittest.main()
