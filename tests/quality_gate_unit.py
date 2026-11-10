"""Fast tests for the mandatory CTest inventory guard (no compiler needed)."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[1] / 'scripts' / 'quality_gate.py'
spec = importlib.util.spec_from_file_location('sudoku_quality_gate', SOURCE)
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)


def inventory(names):
    return json.dumps({'kind': 'ctestInfo', 'version': {'major': 1, 'minor': 0},
                       'tests': [{'name': name} for name in names]})


class InventoryTests(unittest.TestCase):
    def test_full_linux_release_requires_22(self):
        names = set(quality.BASE_TESTS) | set(quality.PACKAGE_TESTS)
        names.add('sudoku_save_fault_injection')
        self.assertEqual(quality.validate_test_manifest(inventory(sorted(names)),
                                                         system='Linux'), 22)

    def test_windows_and_macos_release_require_21(self):
        names = set(quality.BASE_TESTS) | set(quality.PACKAGE_TESTS)
        for system in ('Windows', 'Darwin'):
            with self.subTest(system=system):
                self.assertEqual(quality.validate_test_manifest(inventory(sorted(names)),
                                                                 system=system), 21)

    def test_sanitizer_build_requires_19_not_packaging(self):
        self.assertEqual(quality.validate_test_manifest(
            inventory(sorted(quality.BASE_TESTS)), sanitizer=True, system='Linux'), 19)

    def test_coverage_build_requires_19_not_packaging(self):
        self.assertEqual(quality.validate_test_manifest(
            inventory(sorted(quality.BASE_TESTS)), coverage=True, system='Linux'), 19)

    def test_omitted_python_tests_are_fatal(self):
        names = set(quality.BASE_TESTS) | set(quality.PACKAGE_TESTS)
        names.discard('sudoku_game_e2e')
        with self.assertRaisesRegex(ValueError, 'sudoku_game_e2e'):
            quality.validate_test_manifest(inventory(sorted(names)), system='Darwin')

    def test_omitted_linux_fault_injection_is_fatal(self):
        names = set(quality.BASE_TESTS) | set(quality.PACKAGE_TESTS)
        with self.assertRaisesRegex(ValueError, 'sudoku_save_fault_injection'):
            quality.validate_test_manifest(inventory(sorted(names)), system='Linux')

    def test_missing_packaging_test_fails_release(self):
        with self.assertRaisesRegex(ValueError, 'sudoku_package_e2e'):
            quality.validate_test_manifest(inventory(sorted(quality.BASE_TESTS)),
                                           system='Windows')

    def test_bad_or_missing_json_is_fatal(self):
        for document in ('', 'not json', '{}', '{"tests": null}', '[]'):
            with self.subTest(document=document):
                with self.assertRaises(ValueError):
                    quality.validate_test_manifest(document, system='Linux')

    def test_duplicate_ctest_name_is_fatal(self):
        names = sorted(quality.BASE_TESTS)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            quality.validate_test_manifest(inventory(names + [names[0]]),
                                           sanitizer=True, system='Linux')

    def test_unnamed_ctest_item_is_fatal(self):
        data = json.dumps({'tests': [{'name': name} for name in quality.BASE_TESTS]
                           + [{'command': ['missing-name']}]})
        with self.assertRaisesRegex(ValueError, 'unnamed'):
            quality.validate_test_manifest(data, sanitizer=True, system='Linux')

    def test_ctest_query_is_scoped_to_actual_build(self):
        result = SimpleNamespace(stdout=inventory(sorted(quality.BASE_TESTS)))
        build = Path('my-build')
        with patch.object(quality.subprocess, 'run', return_value=result) as mocked:
            quality.verify_ctest_inventory(build, sanitizer=True)
        args, kwargs = mocked.call_args
        self.assertEqual(args[0], ['ctest', '--test-dir', str(build), '-C', 'Release',
                                   '--show-only=json-v1'])
        self.assertTrue(kwargs['check'])


if __name__ == '__main__':
    unittest.main()
