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
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def run(*args):
    print('+', ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True, cwd=ROOT)


# A passing CTest exit code is insufficient when optional Python discovery
# silently omits the E2E regressions. Require the actual named test suite.
BASE_TESTS = frozenset('''
sudoku_board_unit sudoku_properties sudoku_game_unit sudoku_generator_unit
sudoku_solver_unit sudoku_count_unique sudoku_solve_unique sudoku_help
sudoku_version sudoku_demo_smoke sudoku_validate_compact sudoku_validate_file
sudoku_invalid_row sudoku_stdin sudoku_count_unsolvable sudoku_solve_unsolvable
sudoku_game_e2e sudoku_generator_golden sudoku_cli_golden
'''.split())
PACKAGE_TESTS = frozenset(('sudoku_package_e2e', 'sudoku_package_integrity'))


def validate_test_manifest(raw, sanitizer=False, coverage=False, system=None):
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
    if not sanitizer and not coverage:
        required.update(PACKAGE_TESTS)
        if (system or platform.system()) == 'Linux':
            required.add('sudoku_save_fault_injection')
    missing = sorted(required.difference(names))
    if missing:
        raise ValueError('Required CTest checks missing: ' + ', '.join(missing))
    # CTest returns success when required tests are DISABLED or skipped.
    # A listed-but-skipped test must never count as release gate evidence.
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
                    'SKIP_RETURN_CODE', 'SKIP_REGULAR_EXPRESSION'):
                raise ValueError('Required CTest check disabled or skippable: ' + test['name'])
    print(f'CTEST INVENTORY PASS: {len(required)} mandatory / {len(names)} listed', flush=True)
    return len(required)


def verify_ctest_inventory(path, sanitizer=False, coverage=False):
    command = ['ctest', '--test-dir', str(path), '-C', 'Release', '--show-only=json-v1']
    print('+', ' '.join(command), flush=True)
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
    validate_test_manifest(result.stdout, sanitizer=sanitizer, coverage=coverage)


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
