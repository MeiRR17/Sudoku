"""Portable local quality gate: python scripts/quality_gate.py [--mode fast|full].

fast: build with system CMake generator and run CTest.
full: Linux/macOS GCC+Clang builds where available, GCC sanitizer, GCC coverage
      (minimum 90% core line), and deterministic CLI latency baseline.
No network or package installation; all artifacts stay in --build-root.
"""
import argparse
import json
import pathlib
import platform
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def require_assertions_enabled(optimization=None):
    """Fail closed: our CLI/package E2E scripts use required Python asserts.

    An optimized interpreter may report PASS without executing those checks.
    This protects the full quality gate before any build/test subprocess.
    Individual E2E scripts also reject optimization when invoked via CTest.
    """
    if optimization is None:
        optimization = sys.flags.optimize
    if optimization != 0:
        raise ValueError('Python optimization disables required Sudoku E2E assertions')


def run(*args):
    print('+', ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True, cwd=ROOT)


# A passing CTest exit code is insufficient when optional Python discovery
# silently omits the E2E regressions. Require the actual named test suite.
BASE_TESTS = frozenset('''
sudoku_board_unit sudoku_properties sudoku_game_unit sudoku_generator_unit
sudoku_generator_clock
sudoku_solver_unit sudoku_count_unique sudoku_solve_unique sudoku_help
sudoku_version sudoku_demo_smoke sudoku_validate_compact sudoku_validate_file
sudoku_invalid_row sudoku_stdin sudoku_count_unsolvable sudoku_solve_unsolvable
sudoku_game_e2e sudoku_generator_golden sudoku_cli_golden
'''.split())
PACKAGE_TESTS = frozenset(('sudoku_package_e2e', 'sudoku_package_integrity'))
WINDOWS_TESTS = frozenset(('sudoku_windows_save_concurrency',))

# CTest inventories can retain all expected names while accidentally running
# the wrong binary, a substitute Python script, or even a no-op echo command.
# Match expected executables and the exact source test-script paths before
# accepting an inventory as evidence that the real suite was registered.
C_TEST_PROGRAMS = {
    'sudoku_board_unit': 'sudoku_board_tests',
    'sudoku_properties': 'sudoku_property_tests',
    'sudoku_game_unit': 'sudoku_game_tests',
    'sudoku_generator_unit': 'sudoku_generator_tests',
    'sudoku_generator_clock': 'sudoku_generator_clock_tests',
    'sudoku_solver_unit': 'sudoku_solver_tests',
    'sudoku_windows_save_concurrency': 'sudoku_windows_save_concurrency_tests',
}
# Preserve the actual subcommand and fixture for each required CTest,
# not only the executable name. A sudoku --help stand-in for sudoku solve
# can otherwise produce a false-positive mandatory test listing.
CLI_TEST_ARGUMENTS = {
    'sudoku_count_unique': ('count', '--file', 'unique.txt', '--format', 'compact'),
    'sudoku_solve_unique': ('solve', '--file', 'unique.txt', '--format', 'compact'),
    'sudoku_help': ('--help',),
    'sudoku_version': ('--version',),
    'sudoku_demo_smoke': ('--demo',),
    'sudoku_validate_compact': ('validate', '--puzzle', '0' * 81,
                                '--format', 'compact'),
    'sudoku_validate_file': ('validate', '--file', 'valid.txt'),
    'sudoku_invalid_row': ('validate', '--file', 'invalid_row.txt'),
    'sudoku_count_unsolvable': ('count', '--file', 'unsolvable.txt',
                                '--format', 'compact'),
    'sudoku_solve_unsolvable': ('solve', '--file', 'unsolvable.txt',
                                '--format', 'compact'),
}

PYTHON_TEST_SCRIPTS = {
    'sudoku_game_e2e': 'game_e2e.py',
    'sudoku_generator_golden': 'generator_golden.py',
    'sudoku_cli_golden': 'cli_golden.py',
    'sudoku_package_e2e': 'package_smoke.py',
    'sudoku_package_integrity': 'package_integrity.py',
    'sudoku_save_fault_injection': 'save_faults.py',
}


# The Python CTest wrapper must run the actual checked-in script with the
# complete expected argument contract, not merely its filename. Substituting
# fixtures/build roots or appending switches can make a CTest pass meaningless.
PYTHON_TEST_ARG_COUNTS = {
    'sudoku_game_e2e': 4,
    'sudoku_generator_golden': 3,
    'sudoku_cli_golden': 4,
    'sudoku_package_e2e': 4,
    'sudoku_package_integrity': 4,
    'sudoku_save_fault_injection': 5,
}

def validate_ctest_command(name, command, build_dir=None):
    """Require a real, expected test executable/script, not merely its name."""
    if (not isinstance(command, list) or not command or
            any(not isinstance(x, str) or not x for x in command)):
        raise ValueError('Required CTest command missing or malformed: ' + name)

    def executable_name(path):
        # The inventory is inspected on its native host (including Windows).
        return pathlib.Path(path).name.lower()

    def require_build_binary(path, expected):
        program = executable_name(path)
        if program not in (expected, expected + '.exe'):
            raise ValueError('Required CTest executable mismatch: ' + name)
        if build_dir is not None:
            resolved = pathlib.Path(path).resolve()
            root = pathlib.Path(build_dir).resolve()
            if root not in resolved.parents:
                raise ValueError('Required CTest executable outside build: ' + name)

    if name in C_TEST_PROGRAMS:
        require_build_binary(command[0], C_TEST_PROGRAMS[name])
    elif name in PYTHON_TEST_SCRIPTS:
        if len(command) < 2 or 'python' not in executable_name(command[0]):
            raise ValueError('Required CTest Python runner mismatch: ' + name)
        expected = ROOT / 'tests' / PYTHON_TEST_SCRIPTS[name]
        if pathlib.Path(command[1]).resolve() != expected.resolve():
            raise ValueError('Required CTest Python script mismatch: ' + name)
        if len(command) != PYTHON_TEST_ARG_COUNTS[name]:
            raise ValueError('Required CTest Python arguments mismatch: ' + name)
        if name in ('sudoku_game_e2e', 'sudoku_generator_golden',
                    'sudoku_cli_golden', 'sudoku_save_fault_injection'):
            require_build_binary(command[2], 'sudoku')
        if name in ('sudoku_game_e2e', 'sudoku_cli_golden'):
            if pathlib.Path(command[3]).resolve() != (
                    ROOT / 'tests' / 'fixtures').resolve():
                raise ValueError('Required CTest Python fixture directory mismatch: ' + name)
        elif name in ('sudoku_package_e2e', 'sudoku_package_integrity'):
            if pathlib.Path(command[2]).resolve() != ROOT.resolve():
                raise ValueError('Required CTest Python checkout directory mismatch: ' + name)
            if build_dir is not None and pathlib.Path(command[3]).resolve() != (
                    pathlib.Path(build_dir).resolve()):
                raise ValueError('Required CTest Python build directory mismatch: ' + name)
        elif name == 'sudoku_save_fault_injection':
            if pathlib.Path(command[3]).resolve() != (
                    ROOT / 'tests' / 'fault_inject.c').resolve():
                raise ValueError('Required CTest Python fault source mismatch: ' + name)
            if build_dir is not None:
                cache = pathlib.Path(build_dir) / 'CMakeCache.txt'
                try:
                    cache_text = cache.read_text(encoding='utf-8')
                except OSError as exc:
                    raise ValueError('Required CTest configured C compiler missing: ' + name) from exc
                matches = re.findall(
                    r'^CMAKE_C_COMPILER:(?:FILEPATH|STRING)=(.+)$', cache_text, re.M)
                if len(matches) != 1 or pathlib.Path(command[4]).resolve() != (
                        pathlib.Path(matches[0]).resolve()):
                    raise ValueError('Required CTest Python compiler mismatch: ' + name)
    elif name == 'sudoku_stdin':
        if (executable_name(command[0]) not in ('cmake', 'cmake.exe') or
                '-P' not in command or
                not any(pathlib.Path(x).resolve() ==
                        (ROOT / 'tests' / 'run_stdin.cmake').resolve()
                        for x in command[1:] if x.endswith('.cmake'))):
            raise ValueError('Required CTest stdin driver mismatch: ' + name)
        # The real CMake stdin driver is only useful when it invokes the
        # built sudoku executable against the checked-in input fixture.
        binary = next((x.split('=', 1)[1] for x in command
                       if x.startswith('-DSUDOKU_BIN=')), None)
        fixture = next((x.split('=', 1)[1] for x in command
                        if x.startswith('-DFIXTURE=')), None)
        if not binary or not fixture or pathlib.Path(fixture).resolve() != (
                ROOT / 'tests' / 'fixtures' / 'valid.txt').resolve():
            raise ValueError('Required CTest stdin arguments mismatch: ' + name)
        require_build_binary(binary, 'sudoku')
    else:
        require_build_binary(command[0], 'sudoku')
        if name in CLI_TEST_ARGUMENTS:
            expected = CLI_TEST_ARGUMENTS[name]
            actual = command[1:]
            if len(actual) != len(expected):
                raise ValueError('Required CTest CLI arguments mismatch: ' + name)
            for provided, wanted in zip(actual, expected):
                # File fixtures must be the checked-in fixture paths, but CTest
                # may normalize the spelling of paths on its native host.
                if wanted in ('unique.txt', 'valid.txt',
                              'invalid_row.txt', 'unsolvable.txt'):
                    fixture = (ROOT / 'tests' / 'fixtures' / wanted).resolve()
                    if pathlib.Path(provided).resolve() != fixture:
                        raise ValueError('Required CTest CLI fixture mismatch: ' + name)
                elif provided != wanted:
                    raise ValueError('Required CTest CLI arguments mismatch: ' + name)


def validate_test_manifest(raw, sanitizer=False, coverage=False, system=None,
                           build_dir=None):
    """Fail closed on absent/duplicate named CTest checks before executing any."""
    try:
        manifest = json.loads(raw)
    except (ValueError, TypeError) as error:
        raise ValueError('CTest JSON inventory unreadable') from error
    tests = manifest.get('tests') if isinstance(manifest, dict) else None
    if not isinstance(tests, list):
        raise ValueError('CTest JSON inventory has no tests array')
    names = [test.get('name') for test in tests if isinstance(test, dict)]
    if len(names) != len(tests) or any(not isinstance(n, str) for n in names):
        raise ValueError('CTest JSON inventory contains unnamed tests')
    if len(set(names)) != len(names):
        raise ValueError('CTest JSON inventory contains duplicate test names')
    required = set(BASE_TESTS)
    if (system or platform.system()) == 'Windows':
        required.update(WINDOWS_TESTS)
    if not sanitizer and not coverage:
        required.update(PACKAGE_TESTS)
        if (system or platform.system()) == 'Linux':
            required.add('sudoku_save_fault_injection')
    missing = sorted(required.difference(names))
    if missing:
        raise ValueError('Required CTest checks missing: ' + ', '.join(missing))
    # CTest also marks some failing executables successful if WILL_FAIL
    # inverts the exit code or PASS_REGULAR_EXPRESSION matches stdout.
    # Mandatory release checks must retain their actual failure semantics.
    for test in tests:
        if test['name'] not in required:
            continue
        properties = test.get('properties', [])
        if not isinstance(properties, list):
            raise ValueError('Required CTest properties malformed: ' + test['name'])
        for prop in properties:
            if not isinstance(prop, dict) or not isinstance(prop.get('name'), str):
                raise ValueError('Required CTest properties malformed: ' + test['name'])
            label = prop['name']
            if (label == 'DISABLED' and prop.get('value')) or label in (
                    'SKIP_RETURN_CODE', 'SKIP_REGULAR_EXPRESSION',
                    'WILL_FAIL', 'PASS_REGULAR_EXPRESSION'):
                raise ValueError('Required CTest check disabled or skippable or outcome-overridden: ' + test['name'])
        validate_ctest_command(test['name'], test.get('command'), build_dir)
    print(f'CTEST INVENTORY PASS: {len(required)} mandatory / {len(names)} listed', flush=True)
    return len(required)


def verify_ctest_inventory(path, sanitizer=False, coverage=False):
    command = ['ctest', '--test-dir', str(path), '-C', 'Release', '--show-only=json-v1']
    print('+', ' '.join(command), flush=True)
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
    validate_test_manifest(result.stdout, sanitizer=sanitizer, coverage=coverage,
                           build_dir=path)


def build(path, compiler=None, sanitizer=False, coverage=False):
    command = ['cmake', '-S', ROOT, '-B', path, '-DCMAKE_BUILD_TYPE=Debug' if (sanitizer or coverage) else '-DCMAKE_BUILD_TYPE=Release']
    if compiler:
        command.append(f'-DCMAKE_C_COMPILER={compiler}')
    if sanitizer:
        command.append('-DSUDOKU_ENABLE_SANITIZERS=ON')
    if coverage:
        command.append('-DSUDOKU_ENABLE_COVERAGE=ON')
    run(*command)
    run('cmake', '--build', path, '--config', 'Release', '--parallel', '2')
    verify_ctest_inventory(path, sanitizer=sanitizer, coverage=coverage)
    run('ctest', '--test-dir', path, '-C', 'Release', '--output-on-failure')


def main():
    require_assertions_enabled()
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['fast', 'full'], default='fast')
    ap.add_argument('--build-root', type=pathlib.Path, default=ROOT / '.quality-build')
    args = ap.parse_args()
    if not shutil.which('cmake') or not shutil.which('ctest'):
        ap.error('CMake and CTest must be installed')
    dest = args.build_root.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    if args.mode == 'fast':
        build(dest / 'native')
        print('QUALITY GATE fast PASS', flush=True)
        return
    if platform.system() == 'Windows':
        ap.error('full mode requires local GCC/gcov and Clang; use fast with MSVC on Windows')
    if not shutil.which('gcc') or not shutil.which('clang') or not shutil.which('gcov'):
        ap.error('full mode requires gcc, clang and gcov')
    build(dest / 'clang', compiler='clang')
    run(sys.executable, ROOT / 'scripts' / 'static_analysis.py')
    build(dest / 'gcc-sanitized', compiler='gcc', sanitizer=True)
    build(dest / 'gcc-coverage', compiler='gcc', coverage=True)
    run(sys.executable, ROOT / 'scripts' / 'coverage.py', dest / 'gcc-coverage', '--min-percent', '90')
    bin_name = 'sudoku.exe' if platform.system() == 'Windows' else 'sudoku'
    run(sys.executable, ROOT / 'scripts' / 'benchmark_solver.py', dest / 'clang' / bin_name,
        '--iterations', '25', '--output', dest / 'benchmark.json')
    print('QUALITY GATE full PASS', flush=True)


if __name__ == '__main__':
    main()
