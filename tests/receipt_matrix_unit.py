"""Pure-Python negative/positive tests for unsigned cross-host receipt consistency."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
import zipfile
import contextlib
import io
import sys
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('sudoku_receipt_matrix',
                                              ROOT / 'scripts' / 'verify_receipt_matrix.py')
MATRIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MATRIX)
SHA = 'a' * 40
VERSION = '0.8.4'


class ReceiptMatrixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sudoku-matrix-test-')
        self.addCleanup(self.temp.cleanup)
        self.folders = {}
        self.receipts = {}
        self.source_entries = {
            'README.md': b'Canonical Sudoku source fixture\n',
            'CMakeLists.txt': b'project(Sudoku VERSION 0.8.4 LANGUAGES C)\n',
            'src/core/solver.c': b'solver unit source placeholder\n',
            'src/core/game.c': b'game unit source placeholder\n',
            'scripts/package_release.py': b'packager source placeholder\n',
            'scripts/release_files.txt': b'',
        }
        self.source_entries['scripts/release_files.txt'] = (
            '\n'.join(sorted(self.source_entries)) + '\n').encode('ascii')
        self.source_digest = MATRIX.ACCEPTANCE.source_tree_digest(self.source_entries)
        for label, (system, arches, compilers, suffix) in MATRIX.PLATFORMS.items():
            folder = Path(self.temp.name) / label
            folder.mkdir()
            archives = {}
            for kind in ('source', suffix):
                exe = 'bin/sudoku.exe' if label == 'windows-latest' else 'bin/sudoku'
                entries = (self.source_entries if kind == 'source' else
                           {exe: f'binary fixture from {label}'.encode('ascii'),
                            'include/sudoku/board.h': b'board header fixture',
                            'include/sudoku/game.h': b'game header fixture'})
                prefix = f'sudoku-v{VERSION}-{kind}'
                records = [(name, content, 0o755 if name.startswith('bin/') else 0o644)
                           for name, content in sorted(entries.items())]
                for ext, writer in (('.tar.gz', MATRIX.PACKAGE.create_tar),
                                    ('.zip', MATRIX.PACKAGE.create_zip)):
                    name = prefix + ext
                    writer(folder / name, prefix, records)
                    archives[name] = hashlib.sha256((folder / name).read_bytes()).hexdigest()
            receipt = {
                'schema_version': 2, 'status': 'passed', 'scope': 'unsigned development evidence',
                'git_commit_sha': SHA, 'project_version': VERSION,
                'runner_expected': label, 'observed_system': system,
                'observed_arch': sorted(arches)[0], 'c_compiler_id': sorted(compilers)[0],
                'quality_gate_mode': 'full' if label == 'ubuntu-latest' else 'fast',
                'checks': ['quality_gate', 'package_release', 'package_verify',
                           'packaged_game_save_resume'],
                'archive_sha256': archives,
                'source_tree_sha256': self.source_digest,
                'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            }
            self.folders[label] = folder
            self.receipts[label] = receipt
            self.write(label)

    def write(self, label):
        folder = self.folders[label]
        receipt = self.receipts[label]
        (folder / 'platform-receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
        (folder / 'SHA256SUMS').write_text(''.join(
            f'{digest}  {name}\n' for name, digest in sorted(receipt['archive_sha256'].items())),
            encoding='ascii')

    def check(self):
        return MATRIX.verify_matrix(self.folders, SHA, VERSION)


    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO support required')
    def test_fifo_receipt_file_is_rejected_without_writer(self):
        folder = self.folders['ubuntu-latest']
        path = folder / 'platform-receipt.json'
        path.unlink()
        os.mkfifo(path)
        with self.assertRaisesRegex(ValueError, 'missing or unsafe evidence file'):
            MATRIX.bounded_text(path, MATRIX.MAX_RECEIPT_BYTES, 'utf-8')

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO support required')
    def test_fifo_archive_is_rejected_without_writer(self):
        folder = self.folders['ubuntu-latest']
        name = 'sudoku-v0.8.4-source.zip'
        path = folder / name
        path.unlink()
        os.mkfifo(path)
        with self.assertRaisesRegex(ValueError, 'missing or unsafe archive'):
            MATRIX.verify_archive_hash(path, '0' * 64)

    def test_metadata_matrix_requires_exact_run_id_and_attempt(self):
        for label in self.receipts:
            self.receipts[label]['github_run_id'] = '123456789012'
            self.receipts[label]['github_run_attempt'] = 2
            self.write(label)
        self.assertEqual(
            len(MATRIX.verify_matrix(self.folders, SHA, VERSION,
                                     metadata_only=True,
                                     require_run_id='123456789012',
                                     require_run_attempt=2)), 3)

    def test_metadata_matrix_rejects_mixed_run_attempts(self):
        for label in self.receipts:
            self.receipts[label]['github_run_id'] = '123456789012'
            self.receipts[label]['github_run_attempt'] = 2
            self.write(label)
        self.receipts['macos-latest']['github_run_attempt'] = 3
        self.write('macos-latest')
        with self.assertRaisesRegex(ValueError, 'run ID or attempt mismatch'):
            MATRIX.verify_matrix(self.folders, SHA, VERSION,
                                 metadata_only=True,
                                 require_run_id='123456789012',
                                 require_run_attempt=2)

    def test_metadata_matrix_rejects_mixed_run_ids(self):
        for label in self.receipts:
            self.receipts[label]['github_run_id'] = '123456789012'
            self.receipts[label]['github_run_attempt'] = 2
            self.write(label)
        self.receipts['windows-latest']['github_run_id'] = '123456789013'
        self.write('windows-latest')
        with self.assertRaisesRegex(ValueError, 'run ID or attempt mismatch'):
            MATRIX.verify_matrix(self.folders, SHA, VERSION,
                                 metadata_only=True,
                                 require_run_id='123456789012',
                                 require_run_attempt=2)

    def test_metadata_matrix_rejects_missing_run_identity(self):
        with self.assertRaisesRegex(ValueError, 'run ID or attempt mismatch'):
            MATRIX.verify_matrix(self.folders, SHA, VERSION,
                                 metadata_only=True,
                                 require_run_id='123456789012',
                                 require_run_attempt=2)

    def test_incomplete_receipt_run_identity_is_rejected(self):
        self.receipts['ubuntu-latest']['github_run_id'] = '123456789012'
        self.write('ubuntu-latest')
        with self.assertRaisesRegex(ValueError, 'invalid Actions run identity'):
            MATRIX.verify_matrix(self.folders, SHA, VERSION,
                                 metadata_only=True)

    def test_explicit_null_identity_fields_are_not_absent(self):
        self.receipts['ubuntu-latest']['github_run_id'] = None
        self.receipts['ubuntu-latest']['github_run_attempt'] = None
        self.write('ubuntu-latest')
        with self.assertRaisesRegex(ValueError, 'invalid Actions run identity'):
            MATRIX.verify_matrix(self.folders, SHA, VERSION,
                                 metadata_only=True)

    def test_boolean_attempt_cannot_masquerade_as_integer(self):
        self.receipts['ubuntu-latest'].update(
            github_run_id='123456789012', github_run_attempt=True)
        self.write('ubuntu-latest')
        with self.assertRaisesRegex(ValueError, 'invalid Actions run identity'):
            MATRIX.verify_matrix(self.folders, SHA, VERSION,
                                 metadata_only=True)

    def test_required_run_identity_must_be_valid_pair(self):
        for run_id, attempt in (('123456789012', None), (None, 2),
                                ('00012', 2), ('12345', 0)):
            with self.subTest(run_id=run_id, attempt=attempt):
                with self.assertRaisesRegex(ValueError, 'valid paired Actions'):
                    MATRIX.verify_matrix(self.folders, SHA, VERSION,
                                         metadata_only=True,
                                         require_run_id=run_id,
                                         require_run_attempt=attempt)

    def test_metadata_only_accepts_exact_three_unsigned_receipt_bundles(self):
        # Actions uploads only receipt JSON + SHA256SUMS, not unlicensed
        # binaries. This mode compares claims, NOT downloaded file bytes.
        for folder in self.folders.values():
            for archive in folder.glob('*.zip'):
                archive.unlink()
            for archive in folder.glob('*.tar.gz'):
                archive.unlink()
        matched = MATRIX.verify_matrix(self.folders, SHA, VERSION,
                                       metadata_only=True)
        self.assertEqual(set(matched), set(MATRIX.PLATFORMS))
        with self.assertRaisesRegex(ValueError, 'missing or unsafe archive'):
            self.check()

    def test_metadata_only_rejects_different_git_shas(self):
        self.receipts['windows-latest']['git_commit_sha'] = 'b' * 40
        self.write('windows-latest')
        with self.assertRaisesRegex(ValueError, 'git_commit_sha'):
            MATRIX.verify_matrix(self.folders, SHA, VERSION,
                                 metadata_only=True)

    def test_metadata_only_rejects_source_digest_disagreement(self):
        self.receipts['macos-latest']['source_tree_sha256'] = 'f' * 64
        self.write('macos-latest')
        with self.assertRaisesRegex(ValueError, 'source content differs'):
            MATRIX.verify_matrix(self.folders, SHA, VERSION,
                                 metadata_only=True)

    def test_metadata_only_rejects_manifest_receipt_disagreement(self):
        label = 'ubuntu-latest'
        first = sorted(self.receipts[label]['archive_sha256'])[0]
        self.receipts[label]['archive_sha256'][first] = '0' * 64
        # Deliberately do not rewrite SHA256SUMS.
        (self.folders[label] / 'platform-receipt.json').write_text(
            json.dumps(self.receipts[label]), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'receipt and SHA256SUMS differ'):
            MATRIX.verify_matrix(self.folders, SHA, VERSION,
                                 metadata_only=True)

    def test_metadata_only_cannot_detect_forged_archive_bytes(self):
        # An intentionally corrupted binary cannot be certified by metadata.
        source = self.folders['ubuntu-latest'] / f'sudoku-v{VERSION}-source.zip'
        source.write_bytes(b'altered after receipt issuance')
        MATRIX.verify_matrix(self.folders, SHA, VERSION, metadata_only=True)
        with self.assertRaisesRegex(ValueError, 'archive hash mismatch'):
            self.check()

    def test_metadata_only_refuses_local_platform_mode(self):
        with patch.object(sys, 'argv',
                          ['verify_receipt_matrix.py', '--require-sha', SHA,
                           '--metadata-only', '--local',
                           str(self.folders['ubuntu-latest']),
                           '--expected', 'ubuntu-latest']):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    MATRIX.main()
        self.assertEqual(error.exception.code, 2)

    def test_local_cli_validates_real_single_platform_archives(self):
        stdout = io.StringIO()
        with patch.object(sys, 'argv',
                          ['verify_receipt_matrix.py', '--require-sha', SHA,
                           '--local', str(self.folders['ubuntu-latest']),
                           '--expected', 'ubuntu-latest']):
            with contextlib.redirect_stdout(stdout):
                MATRIX.main()
        self.assertIn('LOCAL EVIDENCE CONSISTENT: ubuntu-latest', stdout.getvalue())
        self.assertIn('no cross-host claim', stdout.getvalue())

    def test_local_cli_rejects_missing_platform_label(self):
        with patch.object(sys, 'argv',
                          ['verify_receipt_matrix.py', '--require-sha', SHA,
                           '--local', str(self.folders['ubuntu-latest'])]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    MATRIX.main()
        self.assertEqual(error.exception.code, 2)

    def test_local_cli_rejects_mixed_matrix_arguments(self):
        with patch.object(sys, 'argv',
                          ['verify_receipt_matrix.py', '--require-sha', SHA,
                           '--local', str(self.folders['ubuntu-latest']),
                           '--expected', 'ubuntu-latest',
                           '--linux', str(self.folders['ubuntu-latest'])]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    MATRIX.main()
        self.assertEqual(error.exception.code, 2)

    def test_matrix_cli_requires_all_three_platforms(self):
        with patch.object(sys, 'argv',
                          ['verify_receipt_matrix.py', '--require-sha', SHA,
                           '--linux', str(self.folders['ubuntu-latest'])]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    MATRIX.main()
        self.assertEqual(error.exception.code, 2)

    def test_local_cli_rejects_wrong_sha(self):
        with patch.object(sys, 'argv',
                          ['verify_receipt_matrix.py', '--require-sha', 'not-a-sha',
                           '--local', str(self.folders['ubuntu-latest']),
                           '--expected', 'ubuntu-latest']):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    MATRIX.main()
        self.assertEqual(error.exception.code, 2)

    def test_matching_three_platform_receipts_are_consistent(self):
        self.assertEqual(set(self.check()), set(MATRIX.PLATFORMS))

    def test_missing_platform_rejected(self):
        self.folders.pop('macos-latest')
        with self.assertRaisesRegex(ValueError, 'precisely Linux'):
            self.check()

    def test_wrong_sha_rejected(self):
        self.receipts['windows-latest']['git_commit_sha'] = 'c' * 40
        self.write('windows-latest')
        with self.assertRaisesRegex(ValueError, 'git_commit_sha'):
            self.check()

    def test_wrong_machine_and_compiler_rejected(self):
        for field, value in (('observed_arch', 'arm64'), ('c_compiler_id', 'GNU')):
            self.receipts['windows-latest'][field] = value
            self.write('windows-latest')
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, 'CPU architecture|C compiler'):
                    self.check()
            if field == 'observed_arch':
                self.receipts['windows-latest'][field] = 'amd64'

    def test_modified_receipt_checksum_rejected(self):
        self.receipts['macos-latest']['archive_sha256'][f'sudoku-v{VERSION}-macos-arm64.zip'] = 'c' * 64
        (self.folders['macos-latest'] / 'platform-receipt.json').write_text(
            json.dumps(self.receipts['macos-latest']), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'receipt and SHA256SUMS differ'):
            self.check()

    def test_different_compressed_source_archives_are_allowed(self):
        # Different compressor settings can produce other archive bytes,
        # without changing extracted file names, bytes or source hash.
        label = 'macos-latest'
        name = f'sudoku-v{VERSION}-source.zip'
        target = self.folders[label] / name
        with zipfile.ZipFile(target, 'w') as archive:
            for rel, content in sorted(self.source_entries.items()):
                entry = zipfile.ZipInfo(f'sudoku-v{VERSION}-source/{rel}',
                                        date_time=(1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = (0o100644 << 16)
                archive.writestr(entry, content, compress_type=zipfile.ZIP_STORED)
        self.receipts[label]['archive_sha256'][name] = hashlib.sha256(target.read_bytes()).hexdigest()
        self.write(label)
        self.assertEqual(len(self.check()), 3)

    def test_local_matrix_source_parser_binds_to_receipt_archive_hashes(self):
        """Full matrix must hash-bind both source formats before extraction."""
        label = 'ubuntu-latest'
        folder = self.folders[label]
        prefix = f'sudoku-v{VERSION}-source'
        digests = self.receipts[label]['archive_sha256']
        with patch.object(MATRIX.PACKAGE, 'verified_archive_members',
                          wraps=MATRIX.PACKAGE.verified_archive_members) as verify:
            MATRIX.verify_one(folder, label, SHA, VERSION)
        observed = [tuple(c.args) for c in verify.call_args_list]
        self.assertIn((folder / (prefix + '.zip'),
                       digests[prefix + '.zip'], prefix), observed)
        self.assertIn((folder / (prefix + '.tar.gz'),
                       digests[prefix + '.tar.gz'], prefix), observed)

    def test_source_zip_replaced_after_preflight_cannot_change_matrix_contents(self):
        """Source bytes may change after the first standalone checksum pass."""
        label = 'ubuntu-latest'
        folder = self.folders[label]
        name = f'sudoku-v{VERSION}-source.zip'
        original_check = MATRIX.verify_archive_hash
        replaced = False

        def replace_after_checksum(path, sha):
            nonlocal replaced
            original_check(path, sha)
            if Path(path) == folder / name and not replaced:
                replaced = True
                # A different regular file at the same pathname should be
                # rejected by the snapshot's second hash BEFORE ZIP decoding.
                competitor = folder / 'competitor-source.zip'
                competitor.write_bytes(b'replaced after receipt hash\n')
                os.replace(competitor, folder / name)

        with patch.object(MATRIX, 'verify_archive_hash',
                          side_effect=replace_after_checksum):
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                MATRIX.verify_one(folder, label, SHA, VERSION)
        self.assertTrue(replaced)

    def test_archive_tampering_after_receipt_rejected(self):
        name = f'sudoku-v{VERSION}-linux-x86_64.zip'
        (self.folders['ubuntu-latest'] / name).write_bytes(b'altered archive')
        with self.assertRaisesRegex(ValueError, 'archive hash mismatch'):
            self.check()

    def test_missing_claimed_archive_rejected(self):
        name = f'sudoku-v{VERSION}-linux-x86_64.zip'
        (self.folders['ubuntu-latest'] / name).unlink()
        with self.assertRaisesRegex(ValueError, 'missing or unsafe archive'):
            self.check()

    def test_symlinked_archive_rejected(self):
        folder = self.folders['ubuntu-latest']
        name = f'sudoku-v{VERSION}-linux-x86_64.zip'
        target = folder / 'original-package.zip'
        (folder / name).rename(target)
        try:
            (folder / name).symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'file symlinks unavailable: {exc}')
        with self.assertRaisesRegex(ValueError, 'missing or unsafe archive'):
            self.check()

    def test_oversized_archive_rejected_before_hashing(self):
        name = f'sudoku-v{VERSION}-linux-x86_64.zip'
        with (self.folders['ubuntu-latest'] / name).open('wb') as stream:
            stream.truncate(MATRIX.MAX_ARCHIVE_BYTES + 1)
        with self.assertRaisesRegex(ValueError, 'archive exceeds size budget'):
            self.check()

    def test_oversized_receipt_rejected_before_json_parse(self):
        (self.folders['ubuntu-latest'] / 'platform-receipt.json').write_bytes(
            b' ' * (MATRIX.MAX_RECEIPT_BYTES + 1))
        with self.assertRaisesRegex(ValueError, 'evidence file exceeds size budget'):
            self.check()

    def test_oversized_checksum_manifest_rejected_before_parse(self):
        (self.folders['ubuntu-latest'] / 'SHA256SUMS').write_bytes(
            b' ' * (MATRIX.MAX_MANIFEST_BYTES + 1))
        with self.assertRaisesRegex(ValueError, 'evidence file exceeds size budget'):
            self.check()

    def test_all_receipts_can_share_a_forged_source_digest(self):
        # Unchanged matching receipt strings no longer pass without matching
        # the canonical digest of actual archive contents.
        for label in MATRIX.PLATFORMS:
            self.receipts[label]['source_tree_sha256'] = 'd' * 64
            self.write(label)
        with self.assertRaisesRegex(ValueError, 'receipt source content digest mismatch'):
            self.check()

    def test_modified_source_with_recomputed_unsigned_hashes_rejected(self):
        # Both ZIP/TAR and SHA256SUMS may be regenerated by an adversary.
        label = 'ubuntu-latest'
        modified = dict(self.source_entries)
        modified['README.md'] = b'Modified code hidden behind forged receipts\n'
        prefix = f'sudoku-v{VERSION}-source'
        records = [(name, content, 0o644) for name, content in sorted(modified.items())]
        for ext, writer in (('.tar.gz', MATRIX.PACKAGE.create_tar),
                            ('.zip', MATRIX.PACKAGE.create_zip)):
            name = prefix + ext
            dest = self.folders[label] / name
            writer(dest, prefix, records)
            self.receipts[label]['archive_sha256'][name] = hashlib.sha256(dest.read_bytes()).hexdigest()
        self.write(label)
        with self.assertRaisesRegex(ValueError, 'receipt source content digest mismatch'):
            self.check()

    def test_zip_tar_source_member_disagreement_rejected(self):
        label = 'ubuntu-latest'
        prefix = f'sudoku-v{VERSION}-source'
        name = prefix + '.tar.gz'
        dest = self.folders[label] / name
        changed = dict(self.source_entries)
        changed['README.md'] = b'Changed only in source tar\n'
        MATRIX.PACKAGE.create_tar(dest, prefix,
            [(name, content, 0o644) for name, content in sorted(changed.items())])
        self.receipts[label]['archive_sha256'][name] = hashlib.sha256(dest.read_bytes()).hexdigest()
        self.write(label)
        with self.assertRaisesRegex(ValueError, 'source ZIP and TAR.GZ contents differ'):
            self.check()

    def test_source_manifest_mismatch_rejected(self):
        label = 'ubuntu-latest'
        prefix = f'sudoku-v{VERSION}-source'
        # Archive members and unsigned digests are internally consistent,
        # but the embedded manifest deliberately omits a shipped source.
        changed = dict(self.source_entries)
        changed['scripts/release_files.txt'] = b'scripts/release_files.txt\n'
        for ext, writer in (('.tar.gz', MATRIX.PACKAGE.create_tar),
                            ('.zip', MATRIX.PACKAGE.create_zip)):
            name = prefix + ext
            dest = self.folders[label] / name
            writer(dest, prefix, [(n, v, 0o644) for n, v in sorted(changed.items())])
            self.receipts[label]['archive_sha256'][name] = hashlib.sha256(dest.read_bytes()).hexdigest()
        self.write(label)
        with self.assertRaisesRegex(ValueError, 'source archive manifest mismatch'):
            self.check()

    def test_binary_zip_tar_content_disagreement_rejected(self):
        label = 'ubuntu-latest'
        name = f'sudoku-v{VERSION}-linux-x86_64.zip'
        dest = self.folders[label] / name
        MATRIX.PACKAGE.create_zip(dest, f'sudoku-v{VERSION}-linux-x86_64', [
            ('bin/sudoku', b'changed binary bytes', 0o755),
            ('include/sudoku/board.h', b'board header fixture', 0o644),
            ('include/sudoku/game.h', b'game header fixture', 0o644),
        ])
        self.receipts[label]['archive_sha256'][name] = hashlib.sha256(dest.read_bytes()).hexdigest()
        self.write(label)
        with self.assertRaisesRegex(ValueError, 'ZIP and TAR.GZ content disagree'):
            self.check()

    def test_binary_missing_header_rejected_after_regenerated_hashes(self):
        label = 'ubuntu-latest'
        prefix = f'sudoku-v{VERSION}-linux-x86_64'
        entries = [('bin/sudoku', b'same synthetic executable', 0o755),
                   ('include/sudoku/board.h', b'board header fixture', 0o644)]
        for ext, writer in (('.zip', MATRIX.PACKAGE.create_zip),
                            ('.tar.gz', MATRIX.PACKAGE.create_tar)):
            name = prefix + ext
            dest = self.folders[label] / name
            writer(dest, prefix, entries)
            self.receipts[label]['archive_sha256'][name] = hashlib.sha256(dest.read_bytes()).hexdigest()
        self.write(label)
        with self.assertRaisesRegex(ValueError, 'missing mandatory release content'):
            self.check()

    def test_binary_zip_symlink_rejected_after_regenerated_hash(self):
        label = 'ubuntu-latest'
        name = f'sudoku-v{VERSION}-linux-x86_64.zip'
        dest = self.folders[label] / name
        prefix = f'sudoku-v{VERSION}-linux-x86_64'
        with zipfile.ZipFile(dest, 'w') as archive:
            for rel, contents, mode in (
                    ('bin/sudoku', b'linked binary', 0o120777),
                    ('include/sudoku/board.h', b'board header fixture', 0o100644),
                    ('include/sudoku/game.h', b'game header fixture', 0o100644)):
                item = zipfile.ZipInfo(prefix + '/' + rel, date_time=(1980, 1, 1, 0, 0, 0))
                item.create_system = 3
                item.external_attr = mode << 16
                archive.writestr(item, contents)
        self.receipts[label]['archive_sha256'][name] = hashlib.sha256(dest.read_bytes()).hexdigest()
        self.write(label)
        with self.assertRaisesRegex(ValueError, 'non-regular ZIP member'):
            self.check()

    def test_source_tree_digest_disagreement_rejected(self):
        self.receipts['macos-latest']['source_tree_sha256'] = 'd' * 64
        self.write('macos-latest')
        with self.assertRaisesRegex(ValueError, 'receipt source content digest mismatch'):
            self.check()

    def test_missing_source_tree_digest_rejected(self):
        self.receipts['ubuntu-latest'].pop('source_tree_sha256')
        self.write('ubuntu-latest')
        with self.assertRaisesRegex(ValueError, 'invalid canonical source content'):
            self.check()

    def test_malformed_source_tree_digest_rejected(self):
        self.receipts['ubuntu-latest']['source_tree_sha256'] = 'not-a-sha'
        self.write('ubuntu-latest')
        with self.assertRaisesRegex(ValueError, 'invalid canonical source content'):
            self.check()

    def test_old_receipt_schema_rejected(self):
        self.receipts['ubuntu-latest']['schema_version'] = 1
        self.write('ubuntu-latest')
        with self.assertRaisesRegex(ValueError, 'schema_version'):
            self.check()

    def test_receipt_duplicate_json_key_rejected(self):
        file = self.folders['ubuntu-latest'] / 'platform-receipt.json'
        file.write_text(file.read_text()[:-1] + ',"status":"passed"}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'duplicate receipt JSON key'):
            self.check()

    def test_manifest_duplicate_filename_rejected(self):
        file = self.folders['ubuntu-latest'] / 'SHA256SUMS'
        rows = file.read_text().splitlines()
        rows[-1] = rows[0]
        file.write_text('\n'.join(rows) + '\n')
        with self.assertRaisesRegex(ValueError, 'expected four distinct archive checksums'):
            self.check()

    def test_unsorted_manifest_rejected(self):
        file = self.folders['ubuntu-latest'] / 'SHA256SUMS'
        rows = file.read_text().splitlines()
        rows.reverse()
        file.write_text('\n'.join(rows) + '\n')
        with self.assertRaisesRegex(ValueError, 'non-canonical SHA256SUMS filename ordering'):
            self.check()

    def test_metadata_only_rejects_noncanonical_checksum_line_endings(self):
        label = 'ubuntu-latest'
        manifest = self.folders[label] / 'SHA256SUMS'
        canonical = manifest.read_bytes()
        for blob in (canonical[:-1], canonical.replace(b'\n', b'\r\n'),
                     canonical.replace(b'\n', b'\r')):
            with self.subTest(ending=repr(blob[-5:])):
                manifest.write_bytes(blob)
                with self.assertRaisesRegex(
                        ValueError, 'non-canonical SHA256SUMS line endings'):
                    MATRIX.verify_matrix(self.folders, SHA, VERSION,
                                         metadata_only=True)
        manifest.write_bytes(canonical)
        self.assertEqual(len(MATRIX.verify_matrix(self.folders, SHA, VERSION,
                                                 metadata_only=True)), 3)

    def test_local_and_metadata_readers_share_canonical_parser(self):
        label = 'ubuntu-latest'
        manifest = self.folders[label] / 'SHA256SUMS'
        expected = self.receipts[label]['archive_sha256']
        self.assertEqual(MATRIX.read_manifest(manifest), expected)
        parsed = MATRIX.PACKAGE.canonical_checksum_records(manifest.read_bytes())
        self.assertEqual({name: digest for digest, name in parsed}, expected)

    def test_missing_required_checks_rejected(self):
        self.receipts['ubuntu-latest']['checks'] = ['quality_gate']
        self.write('ubuntu-latest')
        with self.assertRaisesRegex(ValueError, 'required checks missing'):
            self.check()

    def test_packaged_save_resume_is_a_required_native_receipt_check(self):
        # Every accepted host must attest that its extracted binary and
        # shipped-source rebuild survived save/resume/corruption smoke.
        for label in MATRIX.PLATFORMS:
            self.assertIn('packaged_game_save_resume', self.receipts[label]['checks'])
            self.receipts[label]['checks'].remove('packaged_game_save_resume')
            self.write(label)
            with self.subTest(runner=label):
                with self.assertRaisesRegex(ValueError, 'required checks missing'):
                    MATRIX.verify_matrix(self.folders, SHA, VERSION,
                                         metadata_only=True)
            self.receipts[label]['checks'].append('packaged_game_save_resume')
            self.write(label)
        self.assertEqual(len(MATRIX.verify_matrix(self.folders, SHA, VERSION,
                                                 metadata_only=True)), 3)

    def test_naive_timestamp_rejected(self):
        self.receipts['ubuntu-latest']['created_utc'] = '2026-11-10T11:00:00'
        self.write('ubuntu-latest')
        with self.assertRaisesRegex(ValueError, 'missing timezone'):
            self.check()

    def test_extra_archive_rejected(self):
        self.receipts['ubuntu-latest']['archive_sha256']['malicious.zip'] = 'b' * 64
        self.write('ubuntu-latest')
        with self.assertRaisesRegex(ValueError, 'unexpected archive set'):
            self.check()


if __name__ == '__main__':
    unittest.main()
