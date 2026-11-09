"""Portable local quality gate: python scripts/quality_gate.py [--mode fast|full].

fast: build with system CMake generator and run CTest.
full: Linux/macOS GCC+Clang builds where available, GCC sanitizer, GCC coverage
      (minimum 90% core line), and deterministic CLI latency baseline.
No network or package installation; all artifacts stay in --build-root.
"""
import argparse
import pathlib
import platform
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def run(*args):
    print('+', ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True, cwd=ROOT)


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
