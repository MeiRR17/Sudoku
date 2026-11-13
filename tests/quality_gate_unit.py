"""Fast tests for the mandatory CTest inventory guard (no compiler needed)."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[1] / 'scripts' / 'quality_gate.py'
spec = importlib.util.spec_from_file_location('sudoku_quality_gate', SOURCE)
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)


def test_command(name, build_dir=None):
    """Synthetic native-looking CTest command matching CMake registration."""
    build = Path(build_dir) if build_dir is not None else SOURCE.parent.parent / 'build'
    binary = str(build / 'sudoku')
    if name in quality.C_TEST_PROGRAMS:
        return [str(build / quality.C_TEST_PROGRAMS[name])]
    if name in quality.PYTHON_TEST_SCRIPTS:
        command = [sys.executable,
                   str(SOURCE.parent.parent / 'tests' / quality.PYTHON_TEST_SCRIPTS[name])]
        if name in ('sudoku_game_e2e', 'sudoku_cli_golden'):
            return command + [binary, str(SOURCE.parent.parent / 'tests' / 'fixtures')]
        if name == 'sudoku_generator_golden':
            return command + [binary]
        if name in ('sudoku_package_e2e', 'sudoku_package_integrity'):
            return command + [str(SOURCE.parent.parent), str(build)]
        if name == 'sudoku_save_fault_injection':
            return command + [binary, str(SOURCE.parent.parent / 'tests' /
                                          'fault_inject.c'), '/usr/bin/cc']
        raise AssertionError('unhandled Python CTest name: ' + name)
    if name == 'sudoku_stdin':
        return ['cmake', '-DSUDOKU_BIN=' + binary,
                '-DFIXTURE=' + str(SOURCE.parent.parent / 'tests' / 'fixtures'
                                  / 'valid.txt'), '-P',
                str(SOURCE.parent.parent / 'tests' / 'run_stdin.cmake')]
    if name in quality.CLI_TEST_ARGUMENTS:
        args = [str(SOURCE.parent.parent / 'tests' / 'fixtures' / part)
                if part in ('unique.txt', 'valid.txt', 'invalid_row.txt',
                            'unsolvable.txt') else part
                for part in quality.CLI_TEST_ARGUMENTS[name]]
        return [binary, *args]
    return [binary]


def inventory(names, build_dir=None):
    return json.dumps({'kind': 'ctestInfo', 'version': {'major': 1, 'minor': 0},
                       'tests': [{'name': name,
                                  'command': test_command(name, build_dir)}
                                 for name in names]})


class InventoryTests(unittest.TestCase):
    def test_full_linux_release_requires_23(self):
        names = set(quality.BASE_TESTS) | set(quality.PACKAGE_TESTS)
        names.add('sudoku_save_fault_injection')
        self.assertEqual(quality.validate_test_manifest(inventory(sorted(names)),
                                                         system='Linux'), 23)

    def test_windows_release_requires_23(self):
        names = set(quality.BASE_TESTS) | set(quality.PACKAGE_TESTS) | set(quality.WINDOWS_TESTS)
        self.assertEqual(quality.validate_test_manifest(inventory(sorted(names)),
                                                         system='Windows'), 23)

    def test_macos_release_requires_22(self):
        names = set(quality.BASE_TESTS) | set(quality.PACKAGE_TESTS)
        self.assertEqual(quality.validate_test_manifest(inventory(sorted(names)),
                                                         system='Darwin'), 22)

    def test_omitted_windows_concurrency_gate_is_fatal(self):
        names = set(quality.BASE_TESTS) | set(quality.PACKAGE_TESTS)
        with self.assertRaisesRegex(ValueError, 'sudoku_windows_save_concurrency'):
            quality.validate_test_manifest(inventory(sorted(names)), system='Windows')

    def test_sanitizer_build_requires_20_not_packaging(self):
        self.assertEqual(quality.validate_test_manifest(
            inventory(sorted(quality.BASE_TESTS)), sanitizer=True, system='Linux'), 20)

    def test_coverage_build_requires_20_not_packaging(self):
        self.assertEqual(quality.validate_test_manifest(
            inventory(sorted(quality.BASE_TESTS)), coverage=True, system='Linux'), 20)

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
        names = set(quality.BASE_TESTS) | set(quality.WINDOWS_TESTS)
        with self.assertRaisesRegex(ValueError, 'sudoku_package_e2e'):
            quality.validate_test_manifest(inventory(sorted(names)),
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

    def test_required_disabled_test_fails_closed(self):
        tests = [{'name': name} for name in quality.BASE_TESTS]
        tests[0]['properties'] = [{'name': 'DISABLED', 'value': True}]
        with self.assertRaisesRegex(ValueError, 'disabled or skippable'):
            quality.validate_test_manifest(json.dumps({'tests': tests}),
                                           sanitizer=True, system='Linux')

    def test_required_skip_policy_fails_closed(self):
        for prop in ('SKIP_RETURN_CODE', 'SKIP_REGULAR_EXPRESSION'):
            with self.subTest(prop=prop):
                tests = [{'name': name} for name in quality.BASE_TESTS]
                tests[0]['properties'] = [{'name': prop, 'value': 77}]
                with self.assertRaisesRegex(ValueError, 'disabled or skippable'):
                    quality.validate_test_manifest(json.dumps({'tests': tests}),
                                                   sanitizer=True, system='Linux')

    def test_registered_test_cannot_be_replaced_with_noop(self):
        tests = json.loads(inventory(sorted(quality.BASE_TESTS)))['tests']
        cases = (
            ('sudoku_game_unit', ['echo', 'PASSED']),
            ('sudoku_help', ['cmake', '-E', 'true']),
            ('sudoku_game_e2e', ['python3', 'other_script.py']),
            ('sudoku_stdin', ['echo', 'OK']),
        )
        for name, command in cases:
            with self.subTest(name=name):
                changed = [dict(item) for item in tests]
                next(item for item in changed if item['name'] == name)['command'] = command
                with self.assertRaisesRegex(ValueError, 'Required CTest'):
                    quality.validate_test_manifest(
                        json.dumps({'tests': changed}), sanitizer=True, system='Linux')

    def test_cli_subcommands_cannot_be_substituted(self):
        # An installed sudoku --help or a valid Sudoku executable running the
        # wrong subcommand must not count as the required solve/count check.
        names = sorted(quality.BASE_TESTS)
        original = json.loads(inventory(names))
        for name, replacement in (
                ('sudoku_count_unique', ['--help']),
                ('sudoku_solve_unique', ['--version']),
                ('sudoku_demo_smoke', ['--help']),
                ('sudoku_validate_compact', ['validate', '--file', 'valid.txt']),
                ('sudoku_solve_unsolvable', ['count', '--file',
                                             str(SOURCE.parent.parent / 'tests'
                                                 / 'fixtures' / 'unsolvable.txt'),
                                             '--format', 'compact'])):
            with self.subTest(name=name):
                data = json.loads(json.dumps(original))
                target = next(item for item in data['tests']
                              if item['name'] == name)
                target['command'] = target['command'][:1] + replacement
                with self.assertRaisesRegex(ValueError, 'CLI arguments mismatch'):
                    quality.validate_test_manifest(
                        json.dumps(data), sanitizer=True, system='Linux')

    def test_cli_fixture_swap_and_extra_argument_fail_closed(self):
        names = sorted(quality.BASE_TESTS)
        for name in ('sudoku_count_unique', 'sudoku_validate_file',
                     'sudoku_invalid_row', 'sudoku_count_unsolvable'):
            with self.subTest(name=name):
                data = json.loads(inventory(names))
                target = next(t for t in data['tests'] if t['name'] == name)
                target['command'] = [
                    'invalid_row.txt' if value.endswith('unique.txt')
                    else 'unique.txt' if value.endswith('invalid_row.txt')
                    else 'unique.txt' if value.endswith('valid.txt')
                    else 'valid.txt' if value.endswith('unsolvable.txt')
                    else value for value in target['command']]
                with self.assertRaisesRegex(ValueError, 'CLI fixture mismatch'):
                    quality.validate_test_manifest(
                        json.dumps(data), sanitizer=True, system='Linux')

        data = json.loads(inventory(names))
        target = next(t for t in data['tests'] if t['name'] == 'sudoku_help')
        target['command'].append('ignored-extra-argument')
        with self.assertRaisesRegex(ValueError, 'CLI arguments mismatch'):
            quality.validate_test_manifest(
                json.dumps(data), sanitizer=True, system='Linux')

    def test_all_ctest_cli_entries_have_explicit_argument_contracts(self):
        for name, args in quality.CLI_TEST_ARGUMENTS.items():
            command = test_command(name)
            self.assertEqual(command[0], str(SOURCE.parent.parent / 'build'
                                             / 'sudoku'))
            self.assertGreater(len(command), 1)
            self.assertIn(name, quality.BASE_TESTS)
            # Every known CLI test is explicitly bound to its command form.
            self.assertEqual(len(args), len(command) - 1)

    def test_stdin_requires_the_built_game_and_real_fixture(self):
        root = SOURCE.parent.parent
        data = json.loads(inventory(sorted(quality.BASE_TESTS)))
        entry = next(t for t in data['tests'] if t['name'] == 'sudoku_stdin')
        correct = list(entry['command'])
        cases = (
            [p for p in correct if not p.startswith('-DSUDOKU_BIN=')],
            [p for p in correct if not p.startswith('-DFIXTURE=')],
            [p.replace('valid.txt', 'invalid_row.txt') for p in correct],
            [p.replace('-DSUDOKU_BIN=' + str(root / 'build' / 'sudoku'),
                       '-DSUDOKU_BIN=' + str(root / 'build' / 'echo'))
             for p in correct],
        )
        for command in cases:
            with self.subTest(command=command):
                entry['command'] = command
                with self.assertRaisesRegex(ValueError, 'Required CTest'):
                    quality.validate_test_manifest(
                        json.dumps(data), sanitizer=True, system='Linux')

    def test_missing_and_malformed_required_commands_fail_closed(self):
        for command in (None, [], '', [''], [4], ['sudoku', None]):
            with self.subTest(command=command):
                data = json.loads(inventory(sorted(quality.BASE_TESTS)))
                target = next(t for t in data['tests'] if t['name'] == 'sudoku_game_unit')
                if command is None:
                    del target['command']
                else:
                    target['command'] = command
                with self.assertRaisesRegex(ValueError, 'Required CTest command'):
                    quality.validate_test_manifest(
                        json.dumps(data), sanitizer=True, system='Linux')

    def test_all_python_ctest_arguments_have_exact_arity(self):
        names = set(quality.BASE_TESTS) | set(quality.PACKAGE_TESTS)
        names.add('sudoku_save_fault_injection')
        for name in sorted(quality.PYTHON_TEST_SCRIPTS):
            for variant in ('missing', 'surplus'):
                data = json.loads(inventory(sorted(names)))
                target = next(test for test in data['tests'] if test['name'] == name)
                if variant == 'missing':
                    target['command'].pop()
                else:
                    target['command'].append('--skip')
                with self.subTest(name=name, variant=variant):
                    with self.assertRaisesRegex(ValueError, 'Python arguments mismatch'):
                        quality.validate_test_manifest(
                            json.dumps(data), system='Linux')

    def test_python_e2e_fixture_directory_cannot_be_substituted(self):
        for name in ('sudoku_game_e2e', 'sudoku_cli_golden'):
            data = json.loads(inventory(sorted(quality.BASE_TESTS)))
            target = next(test for test in data['tests'] if test['name'] == name)
            target['command'][-1] = str(SOURCE.parent.parent / 'fixtures-wrong')
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, 'fixture directory mismatch'):
                    quality.validate_test_manifest(json.dumps(data),
                                                   sanitizer=True, system='Linux')

    def test_python_package_source_and_build_dirs_must_match(self):
        build = SOURCE.parent.parent / 'test-native-build'
        names = set(quality.BASE_TESTS) | set(quality.PACKAGE_TESTS)
        for name in sorted(quality.PACKAGE_TESTS):
            for arg_index, expected_error in ((2, 'checkout directory mismatch'),
                                               (3, 'build directory mismatch')):
                data = json.loads(inventory(sorted(names), build_dir=build))
                target = next(test for test in data['tests'] if test['name'] == name)
                target['command'][arg_index] = str(build / 'substituted')
                with self.subTest(name=name, argument=arg_index):
                    with self.assertRaisesRegex(ValueError, expected_error):
                        quality.validate_test_manifest(json.dumps(data),
                                                       system='Darwin', build_dir=build)

    def test_fault_injection_driver_and_compiler_must_match(self):
        build = SOURCE.parent.parent / 'test-fault-build'
        names = set(quality.BASE_TESTS) | set(quality.PACKAGE_TESTS)
        names.add('sudoku_save_fault_injection')
        with tempfile.TemporaryDirectory() as tmpdir:
            build = Path(tmpdir)
            (build / 'CMakeCache.txt').write_text(
                'CMAKE_C_COMPILER:FILEPATH=/usr/bin/cc\n', encoding='utf-8')
            good = json.loads(inventory(sorted(names), build_dir=build))
            self.assertEqual(quality.validate_test_manifest(
                json.dumps(good), system='Linux', build_dir=build), len(names))
            for index, bad, error in (
                    (3, '/tmp/wrong-fault.c', 'fault source mismatch'),
                    (4, '/bin/echo', 'compiler mismatch')):
                data = json.loads(inventory(sorted(names), build_dir=build))
                target = next(test for test in data['tests']
                              if test['name'] == 'sudoku_save_fault_injection')
                target['command'][index] = bad
                with self.subTest(argument=index):
                    with self.assertRaisesRegex(ValueError, error):
                        quality.validate_test_manifest(json.dumps(data),
                                                       system='Linux', build_dir=build)
            (build / 'CMakeCache.txt').unlink()
            with self.assertRaisesRegex(ValueError, 'configured C compiler missing'):
                quality.validate_test_manifest(json.dumps(good),
                                               system='Linux', build_dir=build)

    def test_real_python_script_must_match_repository_test_path(self):
        data = json.loads(inventory(sorted(quality.BASE_TESTS)))
        target = next(t for t in data['tests'] if t['name'] == 'sudoku_game_e2e')
        correct = list(target['command'])
        for bad in ('fake_game_e2e.py',
                    str(SOURCE.parent.parent / 'elsewhere' / 'game_e2e.py')):
            with self.subTest(bad=bad):
                target['command'] = [correct[0], bad, correct[2]]
                with self.assertRaisesRegex(ValueError, 'Python script mismatch'):
                    quality.validate_test_manifest(
                        json.dumps(data), sanitizer=True, system='Linux')

    def test_python_e2e_must_use_built_sudoku_binary(self):
        data = json.loads(inventory(sorted(quality.BASE_TESTS)))
        target = next(t for t in data['tests'] if t['name'] == 'sudoku_game_e2e')
        target['command'] = [sys.executable, str(SOURCE.parent.parent / 'tests'
                                               / 'game_e2e.py'), 'echo',
                             str(SOURCE.parent.parent / 'tests' / 'fixtures')]
        with self.assertRaisesRegex(ValueError, 'executable mismatch'):
            quality.validate_test_manifest(json.dumps(data),
                                           sanitizer=True, system='Linux')

    def test_required_binary_outside_configured_build_fails(self):
        build = SOURCE.parent.parent / 'expected-build'
        data = json.loads(inventory(sorted(quality.BASE_TESTS),
                                    build_dir=build))
        target = next(t for t in data['tests'] if t['name'] == 'sudoku_game_unit')
        target['command'] = [str(SOURCE.parent.parent / 'outside' /
                                 'sudoku_game_tests')]
        with self.assertRaisesRegex(ValueError, 'outside build'):
            quality.validate_test_manifest(json.dumps(data),
                                           sanitizer=True, system='Linux',
                                           build_dir=build)

    def test_valid_release_legacy_cli_python_and_cmake_drivers(self):
        for host in ('Linux', 'Darwin', 'Windows'):
            with self.subTest(system=host):
                names = set(quality.BASE_TESTS) | set(quality.PACKAGE_TESTS)
                if host == 'Linux':
                    names.add('sudoku_save_fault_injection')
                elif host == 'Windows':
                    names.update(quality.WINDOWS_TESTS)
                result = quality.validate_test_manifest(
                    inventory(sorted(names)), system=host)
                self.assertEqual(result, len(names))

    def test_ctest_query_is_scoped_to_actual_build(self):
        build = SOURCE.parent.parent / 'my-build'
        result = SimpleNamespace(stdout=inventory(sorted(quality.BASE_TESTS),
                                                  build_dir=build))
        with patch.object(quality.subprocess, 'run', return_value=result) as mocked:
            quality.verify_ctest_inventory(build, sanitizer=True)
        args, kwargs = mocked.call_args
        self.assertEqual(args[0], ['ctest', '--test-dir', str(build), '-C', 'Release',
                                   '--show-only=json-v1'])
        self.assertTrue(kwargs['check'])


class PythonAssertionIntegrityTests(unittest.TestCase):
    def test_nonoptimized_mode_is_accepted(self):
        self.assertIsNone(quality.require_assertions_enabled(0))

    def test_optimized_modes_cannot_start_quality_gate(self):
        for mode in (1, 2):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(ValueError, 'disables required Sudoku E2E'):
                    quality.require_assertions_enabled(mode)

    def test_each_assert_based_e2e_refuses_python_dash_o(self):
        # Launch the REAL checked-in executable scripts without any binary
        # arguments. The early guard must fail before opening a build path
        # or invoking subprocesses, under both -O and -OO.
        root = SOURCE.parent.parent
        checks = ('package_smoke.py', 'game_e2e.py', 'cli_golden.py',
                  'generator_golden.py', 'package_integrity.py', 'save_faults.py')
        for script in checks:
            for mode in ('-O', '-OO'):
                with self.subTest(script=script, mode=mode):
                    result = subprocess.run(
                        [sys.executable, mode, str(root / 'tests' / script)],
                        text=True, capture_output=True, timeout=8)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Python optimization disables required assertions',
                                  result.stderr)

    def test_pythonoptimize_environment_cannot_skip_tests(self):
        env = dict(os.environ, PYTHONOPTIMIZE='1')
        for script in (SOURCE, SOURCE.parent.parent / 'tests' / 'package_smoke.py'):
            with self.subTest(script=script.name):
                result = subprocess.run(
                    [sys.executable, str(script)], env=env,
                    text=True, capture_output=True, timeout=8)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Python optimization disables required',
                              result.stderr)

    def test_optimized_quality_gate_fails_before_build(self):
        for mode in ('-O', '-OO'):
            with self.subTest(mode=mode):
                result = subprocess.run(
                    [sys.executable, mode, str(SOURCE), '--mode', 'fast'],
                    text=True, capture_output=True, timeout=8)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Python optimization disables required Sudoku E2E',
                              result.stderr)


if __name__ == '__main__':
    unittest.main()
