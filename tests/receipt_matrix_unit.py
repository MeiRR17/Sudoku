"""Pure-Python negative/positive tests for unsigned cross-host receipt consistency."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
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
        for label, (system, arches, compilers, suffix) in MATRIX.PLATFORMS.items():
            folder = Path(self.temp.name) / label
            folder.mkdir()
            archives = {}
            for kind in ('source', suffix):
                for ext in ('.tar.gz', '.zip'):
                    name = f'sudoku-v{VERSION}-{kind}{ext}'
                    # The matrix checks SHA bytes. Native package acceptance
                    # is separately responsible for ZIP/TAR structure checks.
                    payload = f'{label}:{kind}:{ext}'.encode('ascii')
                    (folder / name).write_bytes(payload)
                    archives[name] = hashlib.sha256(payload).hexdigest()
            receipt = {
                'schema_version': 2, 'status': 'passed', 'scope': 'unsigned development evidence',
                'git_commit_sha': SHA, 'project_version': VERSION,
                'runner_expected': label, 'observed_system': system,
                'observed_arch': sorted(arches)[0], 'c_compiler_id': sorted(compilers)[0],
                'quality_gate_mode': 'full' if label == 'ubuntu-latest' else 'fast',
                'checks': ['quality_gate', 'package_release', 'package_verify'],
                'archive_sha256': archives,
                'source_tree_sha256': 'c' * 64,
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
        # Native archive bytes may differ while the source digest agrees.
        for label, ext in (('macos-latest', '.zip'), ('windows-latest', '.tar.gz')):
            name = f'sudoku-v{VERSION}-source{ext}'
            payload = f'different compression from {label}'.encode('ascii')
            (self.folders[label] / name).write_bytes(payload)
            self.receipts[label]['archive_sha256'][name] = hashlib.sha256(payload).hexdigest()
            self.write(label)
        self.assertEqual(len(self.check()), 3)

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

    def test_source_tree_digest_disagreement_rejected(self):
        self.receipts['macos-latest']['source_tree_sha256'] = 'd' * 64
        self.write('macos-latest')
        with self.assertRaisesRegex(ValueError, 'source content differs'):
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
        with self.assertRaisesRegex(ValueError, 'duplicate SHA256SUMS filename'):
            self.check()

    def test_unsorted_manifest_rejected(self):
        file = self.folders['ubuntu-latest'] / 'SHA256SUMS'
        rows = file.read_text().splitlines()
        rows.reverse()
        file.write_text('\n'.join(rows) + '\n')
        with self.assertRaisesRegex(ValueError, 'must be sorted'):
            self.check()

    def test_missing_required_checks_rejected(self):
        self.receipts['ubuntu-latest']['checks'] = ['quality_gate']
        self.write('ubuntu-latest')
        with self.assertRaisesRegex(ValueError, 'required checks missing'):
            self.check()

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
