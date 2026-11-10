"""Package source/install memory-budget regressions; stdlib and temp files only."""
import importlib.util
import itertools
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sudoku_packager', ROOT / 'scripts' / 'package_release.py')
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class PackageBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sudoku-package-budget-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        (self.root / 'scripts').mkdir(parents=True)
        (self.root / 'src').mkdir()
        self.manifest = self.root / 'scripts' / 'release_files.txt'
        self.root_patch = patch.object(packager, 'ROOT', self.root)
        self.list_patch = patch.object(packager, 'SOURCE_LIST', self.manifest)
        self.root_patch.start()
        self.list_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.list_patch.stop)

    def source(self, entries):
        lines = []
        for name, data in entries:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            lines.append(name)
        self.manifest.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    def install(self, payload=b'ok'):
        stage = Path(self.temp.name) / 'stage'
        (stage / 'bin').mkdir(parents=True)
        (stage / 'bin' / 'sudoku').write_bytes(payload)
        return stage

    def test_source_exact_content_budget_passes(self):
        self.source([('src/code.c', b'abcd'), ('src/other.c', b'efgh')])
        with patch.object(packager, 'MAX_UNPACKED_BYTES', 8):
            files = packager.source_paths()
        self.assertEqual([(name, data) for name, data, _ in files],
                         [('src/code.c', b'abcd'), ('src/other.c', b'efgh')])

    def test_source_single_file_over_budget_rejected_before_read(self):
        self.source([('src/huge.c', b'')])
        # Sparse 64MiB+1 file: no allocation or full content read is required.
        with (self.root / 'src' / 'huge.c').open('wb') as file:
            file.truncate(packager.MAX_UNPACKED_BYTES + 1)
        with self.assertRaisesRegex(ValueError, 'package content exceeds size budget'):
            packager.source_paths()

    def test_source_cumulative_budget_rejected(self):
        self.source([('src/a.c', b'123456'), ('src/b.c', b'123456')])
        with patch.object(packager, 'MAX_UNPACKED_BYTES', 10):
            with self.assertRaisesRegex(ValueError, 'package content exceeds size budget'):
                packager.source_paths()

    def test_source_manifest_size_budget_rejected(self):
        self.source([('src/a.c', b'abc')])
        with patch.object(packager, 'MAX_SOURCE_MANIFEST_BYTES', 6):
            with self.assertRaisesRegex(ValueError, 'source manifest exceeds size budget'):
                packager.source_paths()

    def test_source_file_count_budget_rejected(self):
        self.source([('src/a.c', b'a'), ('src/b.c', b'b')])
        with patch.object(packager, 'MAX_ARCHIVE_FILES', 1):
            with self.assertRaisesRegex(ValueError, 'source manifest exceeds file count budget'):
                packager.source_paths()

    def test_installed_exact_budget_passes(self):
        stage = self.install(b'12345678')
        with patch.object(packager, 'MAX_UNPACKED_BYTES', 8):
            self.assertEqual(packager.installed_paths(stage),
                             [('bin/sudoku', b'12345678', 0o755)])

    def test_installed_oversized_sparse_binary_rejected(self):
        stage = self.install(b'')
        with (stage / 'bin' / 'sudoku').open('wb') as file:
            file.truncate(packager.MAX_UNPACKED_BYTES + 1)
        with self.assertRaisesRegex(ValueError, 'package content exceeds size budget'):
            packager.installed_paths(stage)

    def test_installed_cumulative_budget_rejected(self):
        stage = self.install(b'123456')
        (stage / 'doc.txt').write_bytes(b'abcdef')
        with patch.object(packager, 'MAX_UNPACKED_BYTES', 10):
            with self.assertRaisesRegex(ValueError, 'package content exceeds size budget'):
                packager.installed_paths(stage)

    def test_installed_file_count_budget_rejected(self):
        stage = self.install(b'a')
        (stage / 'doc.txt').write_bytes(b'b')
        with patch.object(packager, 'MAX_ARCHIVE_FILES', 1):
            with self.assertRaisesRegex(ValueError, 'installation exceeds file count budget'):
                packager.installed_paths(stage)

    def test_installed_tree_is_sorted_after_streaming(self):
        stage = self.install(b'sudoku')
        (stage / 'z.txt').write_bytes(b'z')
        (stage / 'a.txt').write_bytes(b'a')
        self.assertEqual([name for name, _, _ in packager.installed_paths(stage)],
                         ['a.txt', 'bin/sudoku', 'z.txt'])

    def test_install_file_enumeration_stops_on_unbounded_iterator(self):
        stage = self.install()
        # A sorted(rglob(...)) implementation would attempt to exhaust this
        # infinite iterator before validating the archive size.
        with patch.object(Path, 'rglob', return_value=itertools.repeat(stage / 'bin' / 'sudoku')):
            # The portable-path registry now rejects the second identical
            # file immediately; both errors prevent any unbounded walk.
            with self.assertRaisesRegex(ValueError, 'nonportable path collision|installation exceeds file count budget'):
                packager.installed_paths(stage)

    def test_install_directory_enumeration_stops_on_unbounded_iterator(self):
        stage = self.install()
        with patch.object(Path, 'rglob', return_value=itertools.repeat(stage / 'bin')):
            with self.assertRaisesRegex(ValueError, 'installation exceeds entry count budget'):
                packager.installed_paths(stage)

    def test_install_symlinks_still_fail_closed(self):
        stage = self.install()
        link = stage / 'linked-sudoku'
        try:
            link.symlink_to(stage / 'bin' / 'sudoku')
        except (OSError, NotImplementedError):
            self.skipTest('symbolic links unavailable')
        with self.assertRaisesRegex(ValueError, 'symlink in installation tree'):
            packager.installed_paths(stage)

    def test_windows_device_path_in_staged_install_rejected(self):
        if os.name == 'nt':
            self.skipTest('Windows cannot create a reserved DOS device filename')
        stage = self.install()
        (stage / 'CON.txt').write_bytes(b'device-name')
        with self.assertRaisesRegex(ValueError, 'unsafe installed path'):
            packager.installed_paths(stage)

    def test_windows_punctuation_in_staged_install_rejected(self):
        if os.name == 'nt':
            self.skipTest('Windows cannot create an NTFS alternate stream as a file')
        stage = self.install()
        (stage / 'bad:stream').write_bytes(b'adstream')
        with self.assertRaisesRegex(ValueError, 'unsafe installed path'):
            packager.installed_paths(stage)

    def test_portable_names_rejected_on_all_hosts(self):
        invalid = ('CON', 'CON.txt', 'nul.log', 'COM9.bin', 'LPT².txt',
                   'CONIN$', 'bad:name', 'bad?.txt', 'bad|name',
                   'trailing.', 'trailing ', 'a//b', 'a/../b',
                   'bad\\name', 'tab\tname')
        for value in invalid:
            with self.subTest(value=value):
                self.assertFalse(packager.portable_relative_name(value))
        for value in ('README.md', '.github/workflows/manual-quality.yml',
                      'src/core/game.c', 'bin/sudoku.exe'):
            self.assertTrue(packager.portable_relative_name(value), value)

    def test_changed_file_length_rejected_after_metadata_preflight(self):
        class ChangingFile:
            def stat(self):
                class Status:
                    st_size = 3
                return Status()

            def open(self, mode):
                import io
                return io.BytesIO(b'four')

        with self.assertRaisesRegex(ValueError, 'package source changed during read'):
            packager.bounded_file_bytes(ChangingFile(), 8)


if __name__ == '__main__':
    unittest.main()
