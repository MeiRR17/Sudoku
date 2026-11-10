"""Fast, dependency-free guards for exact-SHA platform acceptance.

Never creates a receipt or requires a native toolchain. The full acceptance
script still must run on each real target host before any release claim.
"""
import importlib.util
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


if __name__ == '__main__':
    unittest.main()
