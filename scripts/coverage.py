"""Measure core/parser/solver/generator line coverage with GCC gcov's compressed JSON output.

Usage: python3 scripts/coverage.py build-coverage --min-percent 90
No third-party dependencies. Run after ctest on a GCC --coverage build.
"""
import argparse
import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('build', type=Path)
    parser.add_argument('--min-percent', type=float, default=90)
    args = parser.parse_args()
    build = args.build.resolve()
    src = Path(__file__).resolve().parent.parent
    totals = []
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        for name in ('board', 'solver', 'generator', 'game'):
            file = src / 'src' / 'core' / (name + '.c')
            obj = build / 'CMakeFiles' / 'sudoku_core.dir' / 'src' / 'core' / (name + '.c.o')
            cmd = ['gcov', '--json-format', '--branch-counts', '-o', str(obj), str(file)]
            proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
            if proc.returncode:
                print('gcov failed:', proc.stdout, proc.stderr, file=sys.stderr)
                return 2
            paths = sorted(cwd.glob('*.gcov.json.gz'))
            if not paths:
                print('gcov produced no JSON coverage:', name, file=sys.stderr)
                return 2
            coverage = json.loads(gzip.decompress(paths[-1].read_bytes()))
            for p in paths:
                p.unlink()
            matches = [x for x in coverage['files'] if Path(x['file']).name == file.name]
            if len(matches) != 1:
                print('coverage source not found:', file, file=sys.stderr)
                return 2
            lines = [line for line in matches[0]['lines'] if line.get('function_name') is not None
                     or line.get('count') is not None]
            # gcov JSON only includes executable code lines, never blanks/comments.
            executable = [line for line in lines if 'count' in line]
            covered = sum(line['count'] > 0 for line in executable)
            total = len(executable)
            if not total:
                print('empty coverage:', name, file=sys.stderr)
                return 2
            rate = covered * 100 / total
            totals.append((covered, total))
            print(f'CORE COVERAGE {name}.c: {covered}/{total} lines ({rate:.2f}%)')
    used = sum(x for x, _ in totals)
    total = sum(y for _, y in totals)
    rate = used * 100 / total
    print(f'CORE COVERAGE TOTAL: {used}/{total} lines ({rate:.2f}%), threshold {args.min_percent:.1f}%')
    return 0 if rate >= args.min_percent else 1


if __name__ == '__main__':
    sys.exit(main())
