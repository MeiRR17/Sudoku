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

PACKAGE_SOURCE = SOURCE.with_name('package_release.py')
package_spec = importlib.util.spec_from_file_location('sudoku_package_for_acceptance_tests',
                                                       PACKAGE_SOURCE)
packager = importlib.util.module_from_spec(package_spec)
package_spec.loader.exec_module(packager)

SHA = 'a' * 40
OTHER_SHA = 'b' * 40


class FreshBuildWorkspaceTests(unittest.TestCase):
    def test_two_attempts_same_sha_use_private_empty_directories(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            first = acceptance.fresh_acceptance_build_root(SHA, base)
            second = acceptance.fresh_acceptance_build_root(SHA, base)
            self.assertNotEqual(first, second)
            for path in (first, second):
                self.assertEqual(path.parent, base)
                self.assertTrue(path.name.startswith('acceptance-' + SHA[:12] + '-'))
                self.assertTrue(path.is_dir())
                self.assertEqual(list(path.iterdir()), [])

    def test_stale_same_sha_cmake_cache_not_reused_or_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            old_build = base / ('acceptance-' + SHA[:12])
            old_build.mkdir()
            (old_build / 'CMakeCache.txt').write_text('stale', encoding='utf-8')
            fresh = acceptance.fresh_acceptance_build_root(SHA, base)
            self.assertNotEqual(fresh, old_build)
            self.assertEqual(list(fresh.iterdir()), [])
            self.assertEqual((old_build / 'CMakeCache.txt').read_text(encoding='utf-8'), 'stale')

    def test_invalid_commit_sha_rejected_before_creating_build(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            for bad in ('', 'master', 'F' * 40, '0' * 39, 'z' * 40):
                with self.subTest(bad=bad):
                    with self.assertRaisesRegex(ValueError, 'invalid acceptance commit SHA'):
                        acceptance.fresh_acceptance_build_root(bad, base)
            self.assertEqual(list(base.iterdir()), [])

    def test_missing_build_parent_created(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / 'nested' / 'builds'
            fresh = acceptance.fresh_acceptance_build_root(SHA, base)
            self.assertTrue(base.is_dir())
            self.assertEqual(fresh.parent, base)

    @unittest.skipUnless(hasattr(os, 'symlink'), 'symlinks unavailable')
    def test_symlinked_build_parent_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            real = base / 'target'
            real.mkdir()
            alias = base / 'alias'
            try:
                alias.symlink_to(real, target_is_directory=True)
            except OSError:
                self.skipTest('creating symlinks is not permitted on this host')
            with self.assertRaisesRegex(ValueError, 'unsafe acceptance build parent'):
                acceptance.fresh_acceptance_build_root(SHA, alias)
            self.assertEqual(list(real.iterdir()), [])


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


class WorkflowIdentityTests(unittest.TestCase):
    def test_offline_receipt_does_not_claim_an_actions_run(self):
        self.assertEqual(acceptance.workflow_identity_from_env({}), {})

    def test_accepts_exact_actions_identity(self):
        self.assertEqual(
            acceptance.workflow_identity_from_env(
                {'GITHUB_RUN_ID': '123456789012', 'GITHUB_RUN_ATTEMPT': '2'}),
            {'github_run_id': '123456789012', 'github_run_attempt': 2})

    def test_missing_id_or_attempt_fails_closed(self):
        for env in ({'GITHUB_RUN_ID': '42'},
                    {'GITHUB_RUN_ATTEMPT': '1'}):
            with self.subTest(env=env):
                with self.assertRaisesRegex(ValueError, 'run identity'):
                    acceptance.workflow_identity_from_env(env)

    def test_malformed_actions_identifiers_fail_closed(self):
        for key, value in (('GITHUB_RUN_ID', '0'),
                           ('GITHUB_RUN_ID', '00012'),
                           ('GITHUB_RUN_ID', 'abc'),
                           ('GITHUB_RUN_ID', '1' * 21),
                           ('GITHUB_RUN_ATTEMPT', '0'),
                           ('GITHUB_RUN_ATTEMPT', '02'),
                           ('GITHUB_RUN_ATTEMPT', 'nan'),
                           ('GITHUB_RUN_ATTEMPT', '1' * 11)):
            with self.subTest(key=key, value=value):
                env = {'GITHUB_RUN_ID': '42', 'GITHUB_RUN_ATTEMPT': '1'}
                env[key] = value
                with self.assertRaisesRegex(ValueError, 'run identity'):
                    acceptance.workflow_identity_from_env(env)


class ReceiptOutputPathTests(unittest.TestCase):
    def test_relative_destination_stays_under_repository_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = acceptance.acceptance_receipt_path(
                root, Path('dist') / 'platform-receipt.json')
            self.assertEqual(result, root / 'dist' / 'platform-receipt.json')
            self.assertFalse(result.parent.exists())

    def test_absolute_destination_is_preserved_without_resolving(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = acceptance.acceptance_receipt_path(root, root / 'receipt.json')
            self.assertEqual(result, root / 'receipt.json')

    @unittest.skipUnless(hasattr(os, 'symlink'), 'symlinks unavailable')
    def test_dangling_receipt_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'missing-target'
            output = root / 'receipt.json'
            try:
                output.symlink_to(target)
            except OSError:
                self.skipTest('creating symlinks is not permitted')
            with self.assertRaisesRegex(ValueError, 'symlinked acceptance receipt'):
                acceptance.acceptance_receipt_path(root, Path('receipt.json'))
            self.assertTrue(output.is_symlink())
            self.assertFalse(target.exists())

    @unittest.skipUnless(hasattr(os, 'symlink'), 'symlinks unavailable')
    def test_symlinked_receipt_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / 'real'
            real.mkdir()
            alias = root / 'alias'
            try:
                alias.symlink_to(real, target_is_directory=True)
            except OSError:
                self.skipTest('creating symlinks is not permitted')
            with self.assertRaisesRegex(ValueError, 'symlinked acceptance receipt directory'):
                acceptance.acceptance_receipt_path(root, Path('alias') / 'receipt.json')
            self.assertEqual(list(real.iterdir()), [])

    @unittest.skipUnless(hasattr(os, 'symlink'), 'symlinks unavailable')
    def test_symlinked_grandparent_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / 'real'
            (real / 'nested').mkdir(parents=True)
            alias = root / 'alias'
            try:
                alias.symlink_to(real, target_is_directory=True)
            except OSError:
                self.skipTest('creating symlinks is not permitted')
            with self.assertRaisesRegex(ValueError, 'symlinked acceptance receipt directory'):
                acceptance.acceptance_receipt_path(
                    root, Path('alias') / 'nested' / 'receipt.json')
            self.assertEqual(list((real / 'nested').iterdir()), [])

    def test_regular_file_in_parent_chain_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocker = root / 'not-a-directory'
            blocker.write_text('keep', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'parent is not a directory'):
                acceptance.acceptance_receipt_path(
                    root, Path('not-a-directory') / 'nested' / 'receipt.json')
            self.assertEqual(blocker.read_text(encoding='utf-8'), 'keep')

    def test_parent_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, 'parent traversal'):
                acceptance.acceptance_receipt_path(
                    root, Path('..') / 'outside' / 'receipt.json')


    def test_existing_receipt_file_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'receipt.json'
            output.write_text('keep', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'overwrite'):
                acceptance.acceptance_receipt_path(root, Path('receipt.json'))
            self.assertEqual(output.read_text(encoding='utf-8'), 'keep')


class ReceiptWriteTests(unittest.TestCase):
    def test_private_atomic_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'dist' / 'platform-receipt.json'
            receipt = {'status': 'passed', 'git_commit_sha': SHA}
            acceptance.write_receipt(dest, receipt)
            self.assertEqual(json.loads(dest.read_text()), receipt)
            self.assertFalse(list(dest.parent.glob(dest.name + '.tmp.*')))
            if os.name == 'posix':
                self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o600)

    @unittest.skipUnless(os.name == 'posix', 'directory fsync is POSIX-only')
    def test_published_receipt_syncs_parent_after_file(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'receipt.json'
            real_fsync = os.fsync
            synced_directory = []
            def observe(fd):
                synced_directory.append(stat.S_ISDIR(os.fstat(fd).st_mode))
                return real_fsync(fd)
            with patch.object(acceptance.os, 'fsync', side_effect=observe):
                acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertEqual(synced_directory, [False, True])
            self.assertEqual(json.loads(dest.read_text()), {'status': 'passed'})

    @unittest.skipUnless(os.name == 'posix', 'post-fsync identity check is POSIX-only')
    def test_final_name_replacement_after_directory_fsync_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dest = root / 'receipt.json'
            victim = root / 'unrelated.json'
            victim.write_text('do not follow', encoding='utf-8')
            real_fsync = os.fsync
            changed = False
            def replace_after_directory_sync(fd):
                nonlocal changed
                result = real_fsync(fd)
                if stat.S_ISDIR(os.fstat(fd).st_mode) and not changed:
                    changed = True
                    dest.unlink()
                    dest.symlink_to(victim)
                return result
            with patch.object(acceptance.os, 'fsync',
                              side_effect=replace_after_directory_sync):
                with self.assertRaisesRegex(
                        OSError, 'published receipt changed after directory synchronization'):
                    acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertTrue(changed)
            self.assertTrue(dest.is_symlink())
            self.assertEqual(victim.read_text(encoding='utf-8'), 'do not follow')

    @unittest.skipUnless(os.name == 'posix', 'post-fsync private mode check is POSIX-only')
    def test_final_mode_broadening_after_directory_fsync_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'receipt.json'
            real_fsync = os.fsync
            changed = False
            def broaden_after_directory_sync(fd):
                nonlocal changed
                result = real_fsync(fd)
                if stat.S_ISDIR(os.fstat(fd).st_mode) and not changed:
                    changed = True
                    os.chmod(dest, 0o644)
                return result
            with patch.object(acceptance.os, 'fsync',
                              side_effect=broaden_after_directory_sync):
                with self.assertRaisesRegex(OSError,
                                            'permissions or link count changed'):
                    acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertTrue(changed)
            self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o644)

    @unittest.skipUnless(os.name == 'posix', 'post-fsync hardlink check is POSIX-only')
    def test_extra_hardlink_after_directory_fsync_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dest = root / 'receipt.json'
            alias = root / 'unexpected-alias'
            real_fsync = os.fsync
            changed = False
            def add_link_after_directory_sync(fd):
                nonlocal changed
                result = real_fsync(fd)
                if stat.S_ISDIR(os.fstat(fd).st_mode) and not changed:
                    changed = True
                    os.link(dest, alias)
                return result
            with patch.object(acceptance.os, 'fsync',
                              side_effect=add_link_after_directory_sync):
                with self.assertRaisesRegex(OSError,
                                            'permissions or link count changed'):
                    acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertTrue(changed)
            self.assertTrue(alias.exists())
            self.assertEqual(dest.stat().st_ino, alias.stat().st_ino)

    @unittest.skipUnless(os.name == 'posix', 'post-fsync identity check is POSIX-only')
    def test_final_name_removal_after_directory_fsync_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dest = root / 'receipt.json'
            real_fsync = os.fsync
            changed = False
            def remove_after_directory_sync(fd):
                nonlocal changed
                result = real_fsync(fd)
                if stat.S_ISDIR(os.fstat(fd).st_mode) and not changed:
                    changed = True
                    dest.unlink()
                return result
            with patch.object(acceptance.os, 'fsync',
                              side_effect=remove_after_directory_sync):
                with self.assertRaisesRegex(OSError, 'No such file'):
                    acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertTrue(changed)
            self.assertFalse(dest.exists())

    @unittest.skipUnless(os.name == 'posix', 'directory fsync is POSIX-only')
    def test_parent_sync_failure_reports_uncertain_published_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'receipt.json'
            real_fsync = os.fsync
            def fail_directory(fd):
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    raise OSError('injected directory sync failure')
                return real_fsync(fd)
            with patch.object(acceptance.os, 'fsync', side_effect=fail_directory):
                with self.assertRaisesRegex(OSError, 'directory sync failure'):
                    acceptance.write_receipt(dest, {'status': 'passed'})
            # The link already exists; never report that publication did not occur.
            self.assertEqual(json.loads(dest.read_text()), {'status': 'passed'})
            self.assertFalse(list(dest.parent.glob('receipt.json.tmp.*')))

    @unittest.skipUnless(os.name == 'posix', 'directory handles are POSIX-only')
    def test_directory_swap_after_link_is_not_certified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / 'evidence'
            parent.mkdir()
            moved = root / 'moved-evidence'
            dest = parent / 'receipt.json'
            real_link = os.link
            def replace_parent(*args, **kwargs):
                real_link(*args, **kwargs)
                parent.rename(moved)
                parent.mkdir()
            with patch.object(acceptance.os, 'link', side_effect=replace_parent):
                with self.assertRaisesRegex(OSError, 'changed after publication'):
                    acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertFalse(dest.exists())
            self.assertEqual(json.loads((moved / 'receipt.json').read_text()),
                             {'status': 'passed'})
            self.assertFalse(list(moved.glob('receipt.json.tmp.*')))

    @unittest.skipUnless(os.name == 'posix', 'O_NOFOLLOW is POSIX-only')
    def test_symlinked_receipt_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            genuine = root / 'real'
            genuine.mkdir()
            alias = root / 'alias'
            try:
                alias.symlink_to(genuine, target_is_directory=True)
            except OSError:
                self.skipTest('symlinks unavailable on this host')
            with self.assertRaises(OSError):
                acceptance.write_receipt(alias / 'receipt.json', {'status': 'passed'})
            self.assertEqual(list(genuine.iterdir()), [])

    @unittest.skipUnless(os.name == 'posix', 'POSIX dir_fd stage only')
    def test_posix_stage_collision_retries_without_touching_orphan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dest = root / 'receipt.json'
            orphan = root / ('receipt.json.tmp.' + 'a' * 24)
            orphan.write_text('previous incomplete stage', encoding='utf-8')
            with patch.object(acceptance.secrets, 'token_hex',
                              side_effect=['a' * 24, 'b' * 24]):
                acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertEqual(orphan.read_text(encoding='utf-8'),
                             'previous incomplete stage')
            self.assertEqual(json.loads(dest.read_text()), {'status': 'passed'})
            self.assertEqual(list(root.glob('receipt.json.tmp.*')), [orphan])

    @unittest.skipUnless(os.name == 'posix', 'POSIX dir_fd stage only')
    def test_parent_swap_during_stage_creation_cleans_pinned_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'original'
            original.mkdir()
            displaced = root / 'displaced'
            destination = original / 'receipt.json'
            def swap_parent(_):
                original.rename(displaced)
                original.mkdir()
                return 'a' * 24
            with patch.object(acceptance.secrets, 'token_hex',
                              side_effect=swap_parent):
                with self.assertRaisesRegex(OSError,
                                            'changed before publication'):
                    acceptance.write_receipt(destination, {'status': 'passed'})
            self.assertEqual(list(displaced.iterdir()), [])
            self.assertEqual(list(original.iterdir()), [])

    @unittest.skipUnless(os.name == 'posix', 'POSIX dir_fd stage only')
    def test_published_inode_replacement_cannot_be_certified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / 'receipt.json'
            real_link = os.link
            def tamper(*args, **kwargs):
                real_link(*args, **kwargs)
                destination.unlink()
                destination.write_text('replacement', encoding='utf-8')
            with patch.object(acceptance.os, 'link', side_effect=tamper):
                with self.assertRaisesRegex(OSError, 'published inode differs'):
                    acceptance.write_receipt(destination, {'status': 'passed'})
            self.assertEqual(destination.read_text(encoding='utf-8'),
                             'replacement')
            self.assertEqual(list(root.glob('receipt.json.tmp.*')), [])

    @unittest.skipUnless(os.name == 'posix', 'POSIX private stage only')
    def test_stage_is_private_before_receipt_bytes_written(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'receipt.json'
            real_fdopen = os.fdopen
            seen_modes = []
            def observe(fd, *args, **kwargs):
                seen_modes.append(stat.S_IMODE(os.fstat(fd).st_mode))
                return real_fdopen(fd, *args, **kwargs)
            old_umask = os.umask(0)
            try:
                with patch.object(acceptance.os, 'fdopen', side_effect=observe):
                    acceptance.write_receipt(dest, {'status': 'passed'})
            finally:
                os.umask(old_umask)
            self.assertEqual(seen_modes, [0o600])
            self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o600)

    @unittest.skipUnless(os.name == 'posix', 'POSIX receipt mode check only')
    def test_restrictive_umask_still_produces_owner_readable_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'receipt.json'
            previous = os.umask(0o777)
            try:
                acceptance.write_receipt(dest, {'status': 'passed'})
            finally:
                os.umask(previous)
            self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o600)
            self.assertEqual(json.loads(dest.read_text()), {'status': 'passed'})

    @unittest.skipUnless(os.name == 'posix', 'POSIX receipt descriptor check only')
    def test_initial_fstat_failure_retries_identity_and_cleans_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'receipt.json'
            real_fstat = os.fstat
            failed = False
            def fail_once(fd):
                nonlocal failed
                if not stat.S_ISDIR(real_fstat(fd).st_mode) and not failed:
                    failed = True
                    raise OSError('injected initial fstat failure')
                return real_fstat(fd)
            with patch.object(acceptance.os, 'fstat', side_effect=fail_once):
                with self.assertRaisesRegex(OSError, 'initial fstat failure'):
                    acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertTrue(failed)
            self.assertFalse(dest.exists())
            self.assertEqual(list(dest.parent.iterdir()), [])

    @unittest.skipUnless(os.name == 'posix', 'POSIX receipt descriptor check only')
    def test_persistent_fstat_failure_leaves_only_unidentified_orphan(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'receipt.json'
            real_fstat = os.fstat
            def fail_file_fstat(fd):
                if not stat.S_ISDIR(real_fstat(fd).st_mode):
                    raise OSError('persistent fstat failure')
                return real_fstat(fd)
            with patch.object(acceptance.os, 'fstat', side_effect=fail_file_fstat):
                with self.assertRaisesRegex(OSError, 'persistent fstat failure'):
                    acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertFalse(dest.exists())
            stages = list(dest.parent.glob('receipt.json.tmp.*'))
            # Without a trustworthy inode identity, fail closed and do not
            # unlink by pathname. The open descriptor is closed on the error path.
            self.assertEqual(len(stages), 1)
            self.assertTrue(stages[0].is_file())

    @unittest.skipUnless(os.name == 'posix', 'POSIX receipt mode check only')
    def test_fchmod_failure_aborts_and_cleans_private_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'receipt.json'
            with patch.object(acceptance.os, 'fchmod',
                              side_effect=OSError('injected mode failure')):
                with self.assertRaisesRegex(OSError, 'mode failure'):
                    acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertFalse(dest.exists())
            self.assertEqual(list(dest.parent.iterdir()), [])

    @unittest.skipUnless(os.name == 'posix', 'POSIX receipt mode check only')
    def test_ineffective_fchmod_fails_closed_under_restrictive_umask(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'receipt.json'
            previous = os.umask(0o777)
            try:
                with patch.object(acceptance.os, 'fchmod', return_value=None):
                    with self.assertRaisesRegex(OSError, 'permissions not private'):
                        acceptance.write_receipt(dest, {'status': 'passed'})
            finally:
                os.umask(previous)
            self.assertFalse(dest.exists())
            self.assertEqual(list(dest.parent.iterdir()), [])

    @unittest.skipUnless(os.name == 'posix', 'POSIX inode-guarded cleanup only')
    def test_replaced_stage_regular_file_is_not_unlinked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dest = root / 'receipt.json'
            real_link = os.link
            def replace_stage(*args, **kwargs):
                real_link(*args, **kwargs)
                stage = next(root.glob('receipt.json.tmp.*'))
                stage.unlink()
                stage.write_text('another writer', encoding='utf-8')
            with patch.object(acceptance.os, 'link',
                              side_effect=replace_stage):
                with self.assertRaisesRegex(OSError,
                                            'staging file replaced before cleanup'):
                    acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertEqual(next(root.glob('receipt.json.tmp.*')).read_text(),
                             'another writer')
            self.assertEqual(json.loads(dest.read_text()), {'status': 'passed'})

    @unittest.skipUnless(os.name == 'posix', 'POSIX inode-guarded cleanup only')
    def test_replaced_stage_symlink_does_not_delete_unrelated_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dest = root / 'receipt.json'
            victim = root / 'unrelated'
            victim.write_text('keep', encoding='utf-8')
            real_link = os.link
            def replace_stage(*args, **kwargs):
                real_link(*args, **kwargs)
                stage = next(root.glob('receipt.json.tmp.*'))
                stage.unlink()
                stage.symlink_to(victim)
            with patch.object(acceptance.os, 'link',
                              side_effect=replace_stage):
                with self.assertRaisesRegex(OSError,
                                            'staging file replaced before cleanup'):
                    acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertEqual(victim.read_text(), 'keep')
            self.assertTrue(next(root.glob('receipt.json.tmp.*')).is_symlink())

    def test_existing_receipt_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'evidence.json'
            dest.write_text('previous')
            with self.assertRaises(FileExistsError):
                acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertEqual(dest.read_text(), 'previous')
            self.assertFalse(list(dest.parent.glob(dest.name + '.tmp.*')))

    def test_existing_temporary_symlink_is_ignored_without_following(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            victim = root / 'victim.txt'
            victim.write_text('unchanged')
            dest = root / 'evidence.json'
            stale = root / 'evidence.json.tmp'
            try:
                stale.symlink_to(victim)
            except (OSError, NotImplementedError):
                self.skipTest('host cannot create a symlink')
            acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertEqual(json.loads(dest.read_text()), {'status': 'passed'})
            self.assertEqual(victim.read_text(), 'unchanged')
            self.assertTrue(stale.is_symlink())
            self.assertFalse(list(root.glob(dest.name + '.tmp.*')))

    def test_stale_stage_from_crash_does_not_block_new_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dest = root / 'evidence.json'
            orphan = root / 'evidence.json.tmp.previous-crash'
            orphan.write_text('incomplete')
            acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertEqual(json.loads(dest.read_text()), {'status': 'passed'})
            self.assertEqual(orphan.read_text(), 'incomplete')
            self.assertEqual(list(root.glob('evidence.json.tmp.*')), [orphan])

    def test_concurrent_existing_target_stays_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'evidence.json'
            def publish_concurrent(*args, **kwargs):
                dest.write_text('another process won')
                raise FileExistsError('existing receipt')
            with patch.object(acceptance.os, 'link', side_effect=publish_concurrent):
                with self.assertRaises(FileExistsError):
                    acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertEqual(dest.read_text(), 'another process won')
            self.assertFalse(list(dest.parent.glob('evidence.json.tmp.*')))

    def test_unsupported_hardlink_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'evidence.json'
            with patch.object(acceptance.os, 'link', side_effect=OSError('unsupported')):
                with self.assertRaises(OSError):
                    acceptance.write_receipt(dest, {'status': 'passed'})
            self.assertFalse(dest.exists())
            self.assertFalse(list(dest.parent.glob(dest.name + '.tmp.*')))

    def test_serialization_failure_cleans_up_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'evidence.json'
            with self.assertRaises(TypeError):
                acceptance.write_receipt(dest, {'value': object()})
            self.assertFalse(dest.exists())
            self.assertFalse(list(dest.parent.glob(dest.name + '.tmp.*')))

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

    def test_noncanonical_manifest_line_endings_cannot_create_receipt(self):
        manifest = self.dist / 'SHA256SUMS'
        canonical = manifest.read_bytes()
        for blob in (canonical[:-1], canonical.replace(b'\n', b'\r\n'),
                     canonical.replace(b'\n', b'\r')):
            with self.subTest(trailer=repr(blob[-5:])):
                manifest.write_bytes(blob)
                with self.assertRaisesRegex(
                        ValueError, 'non-canonical SHA256SUMS line endings'):
                    self.check()
        manifest.write_bytes(canonical)
        self.assertEqual(sorted(self.check()), self.names)

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

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO support required')
    def test_fifo_archive_is_rejected_without_a_writer(self):
        path = self.dist / self.names[0]
        path.unlink()
        os.mkfifo(path)
        with self.assertRaisesRegex(ValueError, 'missing or unsafe archive'):
            self.check()

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO support required')
    def test_fifo_checksum_manifest_is_rejected_without_a_writer(self):
        path = self.dist / 'SHA256SUMS'
        path.unlink()
        os.mkfifo(path)
        with self.assertRaisesRegex(ValueError, 'missing or unsafe SHA256SUMS'):
            self.check()

    @unittest.skipUnless(hasattr(os, 'O_NOFOLLOW'), 'POSIX O_NOFOLLOW required')
    def test_archive_symlink_swap_after_preflight_is_rejected(self):
        archive = self.dist / self.names[0]
        backup = self.dist / 'source-backup.bin'
        real_open = os.open
        swapped = False

        def swapping_open(path, flags, *args, **kwargs):
            nonlocal swapped
            if Path(path) == archive and not swapped:
                archive.rename(backup)
                archive.symlink_to(backup)
                swapped = True
            return real_open(path, flags, *args, **kwargs)

        with patch.object(acceptance.os, 'open', side_effect=swapping_open):
            with self.assertRaisesRegex(ValueError, 'missing or unsafe archive'):
                self.check()
        self.assertTrue(swapped)



class SourceArchiveReceiptSnapshotTests(unittest.TestCase):
    """Source tree receipt must match the same ZIP bytes as the SHA-256."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sudoku-source-receipt-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.version = '0.8.4'
        self.prefix = 'sudoku-v0.8.4-source'
        self.name = self.prefix + '.zip'
        self.archive = self.folder / self.name
        self.source = {'README.md': b'verified original source data\n',
                       'src/core/solver.c': b'/* no embedded solution */\n'}

    def make_archive(self, path, source):
        packager.create_zip(path, self.prefix,
                            [(name, content, 0o644)
                             for name, content in source.items()])
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def digest(self, checksum):
        # The native script imports the packager at call time. Route that
        # import to the actual file loaded above, not a simplified stub.
        with patch.dict('sys.modules', {'package_release': packager}):
            return acceptance.verified_source_tree_digest(
                self.folder, self.version, checksum)

    def test_source_digest_matches_actual_verified_zip_content(self):
        sha = self.make_archive(self.archive, self.source)
        self.assertEqual(self.digest({self.name: sha}),
                         acceptance.source_tree_digest(self.source))

    def test_source_archive_mutation_rejected_against_claimed_hash(self):
        sha = self.make_archive(self.archive, self.source)
        self.make_archive(self.archive, {'README.md': b'tampered code\n'})
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            self.digest({self.name: sha})

    def test_missing_or_invalid_expected_archive_digest_rejected(self):
        self.make_archive(self.archive, self.source)
        for record in ({}, {self.name: 1}, {self.name: 'g' * 64},
                       {self.name: 'A' * 64}):
            with self.subTest(record=record):
                with self.assertRaisesRegex(ValueError, 'missing or invalid verified'):
                    self.digest(record)

    @unittest.skipUnless(os.name == 'posix', 'rename of opened inode tested on POSIX')
    def test_source_path_swap_after_open_cannot_change_receipt_digest(self):
        original_sha = self.make_archive(self.archive, self.source)
        competitor = self.folder / 'competing.zip'
        self.make_archive(competitor, {'README.md': b'competing ZIP data\n'})
        actual_open = packager.open_checked_binary
        swaps = 0

        def replace_after_open(path, kind):
            nonlocal swaps
            stream = actual_open(path, kind)
            if Path(path) == self.archive:
                swaps += 1
                os.replace(competitor, self.archive)
            return stream

        with patch.object(packager, 'open_checked_binary',
                          side_effect=replace_after_open):
            # Digest must describe the original opened descriptor, not the
            # new archive that replaced the path after preflight.
            digest = self.digest({self.name: original_sha})
        self.assertEqual(swaps, 1)
        self.assertEqual(digest, acceptance.source_tree_digest(self.source))
        self.assertNotEqual(hashlib.sha256(self.archive.read_bytes()).hexdigest(),
                            original_sha)

    def test_wrong_member_prefix_fails_despite_matching_archive_hash(self):
        packager.create_zip(self.archive, 'sudoku-v0.8.4-wrong',
                            [('README.md', b'different root', 0o644)])
        sha = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'unsafe archive member'):
            self.digest({self.name: sha})



if __name__ == '__main__':
    unittest.main()
