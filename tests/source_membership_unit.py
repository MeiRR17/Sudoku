"""Source-package self-consistency, including real ZIP and TAR.GZ manifests.

No full Sudoku build is needed: create minimal valid synthetic source and
binary development archives, then verify/reject using the real packager.
"""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'scripts' / 'package_release.py'
spec = importlib.util.spec_from_file_location('sudoku_source_membership', SOURCE)
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def source_fixture():
    paths = ('README.md', 'CMakeLists.txt', 'src/core/solver.c',
             'src/core/game.c', 'scripts/package_release.py',
             'scripts/release_files.txt', 'tests/regression.txt')
    entries = {name: (name + '\n').encode('utf-8') for name in paths}
    entries['scripts/release_files.txt'] = (
        '# All development source files\n' + '\n'.join(sorted(paths)) + '\n'
    ).encode('utf-8')
    return entries


def package_files(entries):
    return [(name, content, 0o644) for name, content in sorted(entries.items())]


class SourceMembershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='sudoku-source-membership-')
        self.addCleanup(self.tmp.cleanup)
        self.dist = Path(self.tmp.name)
        self.entries = source_fixture()

    def build_packages(self):
        binary = {
            'bin/sudoku': b'placeholder binary for archive-structure tests',
            'include/sudoku/board.h': b'board header',
            'include/sudoku/game.h': b'game header',
        }
        names = [('sudoku-v' + package.VERSION + '-source', self.entries),
                 ('sudoku-v' + package.VERSION + '-linux-x86_64', binary)]
        records = []
        for prefix, entries in names:
            for ext, writer in (('.tar.gz', package.create_tar),
                                ('.zip', package.create_zip)):
                target = self.dist / (prefix + ext)
                writer(target, prefix, package_files(entries))
                records.append((target.name, package.file_hash(target)))
        (self.dist / 'SHA256SUMS').write_text(
            ''.join(f'{digest}  {name}\n' for name, digest in sorted(records)),
            encoding='ascii')
        # All digests and ZIP/TAR contents match even in rejection scenarios.
        self.assertEqual(len(records), 4)

    def test_complete_real_archives_accepted(self):
        self.build_packages()
        package.verify_packages(self.dist)

    def test_missing_optional_source_rejected_despite_matching_checksums(self):
        del self.entries['tests/regression.txt']
        self.build_packages()
        with self.assertRaisesRegex(ValueError, 'source archive manifest mismatch'):
            package.verify_packages(self.dist)

    def test_extra_source_rejected_despite_matching_checksums(self):
        self.entries['tests/extra.txt'] = b'unlisted'
        self.build_packages()
        with self.assertRaisesRegex(ValueError, 'source archive manifest mismatch'):
            package.verify_packages(self.dist)

    def test_modified_embedded_manifest_with_omitted_entry_rejected(self):
        data = self.entries['scripts/release_files.txt']
        self.entries['scripts/release_files.txt'] = data.replace(b'tests/regression.txt\n', b'')
        self.build_packages()
        with self.assertRaisesRegex(ValueError, 'source archive manifest mismatch'):
            package.verify_packages(self.dist)

    def test_duplicate_declaration_rejected(self):
        self.entries['scripts/release_files.txt'] += b'README.md\n'
        self.build_packages()
        with self.assertRaisesRegex(ValueError, 'duplicate source archive manifest path'):
            package.verify_packages(self.dist)

    def test_invalid_utf8_declaration_rejected(self):
        self.entries['scripts/release_files.txt'] += b'\xff\n'
        self.build_packages()
        with self.assertRaisesRegex(ValueError, 'must be UTF-8'):
            package.verify_packages(self.dist)

    def test_unsafe_declaration_rejected(self):
        self.entries['scripts/release_files.txt'] += b'../escape.txt\n'
        self.build_packages()
        with self.assertRaisesRegex(ValueError, 'unsafe source archive manifest path'):
            package.verify_packages(self.dist)

    def test_oversized_embedded_manifest_rejected(self):
        self.entries['scripts/release_files.txt'] += b'#' * (package.MAX_SOURCE_MANIFEST_BYTES + 1)
        self.build_packages()
        with self.assertRaisesRegex(ValueError, 'oversized release_files manifest'):
            package.verify_packages(self.dist)

    def test_missing_manifest_rejected_even_if_other_files_exist(self):
        entries = dict(self.entries)
        del entries['scripts/release_files.txt']
        with self.assertRaisesRegex(ValueError, 'missing or oversized release_files'):
            package.verify_source_membership(entries)

    def test_empty_declaration_rejected(self):
        entries = dict(self.entries)
        entries['scripts/release_files.txt'] = b'# no entries\n'
        with self.assertRaisesRegex(ValueError, 'empty source archive manifest'):
            package.verify_source_membership(entries)

    def test_normalized_alias_declaration_rejected(self):
        entries = dict(self.entries)
        entries['scripts/release_files.txt'] += b'TESTS/regression.txt\n'
        with self.assertRaisesRegex(ValueError, 'nonportable path collision'):
            package.verify_source_membership(entries)


if __name__ == '__main__':
    unittest.main()
