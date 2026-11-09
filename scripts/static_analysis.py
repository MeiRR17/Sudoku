#!/usr/bin/env python3
"""Fail on any Clang static-analyzer diagnostic in Sudoku production C sources.

This is an opt-in/local quality gate, not proof of program correctness.
Run: python3 scripts/static_analysis.py [--compiler clang]
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
SOURCES = (
    'src/cli/main.c', 'src/cli/play.c',
    'src/core/board.c', 'src/core/solver.c',
    'src/core/generator.c', 'src/core/game.c',
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', default='clang')
    args = parser.parse_args()
    compiler = shutil.which(args.compiler)
    if not compiler:
        parser.error(f'Clang compiler not found: {args.compiler}')
    problems = []
    for path in SOURCES:
        cmd = [compiler, '--analyze', '-std=c11', '-I' + str(ROOT / 'include'),
               '-Wall', '-Wextra', '-Wpedantic', str(ROOT / path)]
        p = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True, check=False)
        output = (p.stdout + p.stderr).strip()
        if p.returncode or output:
            problems.append(path)
            print(f'STATIC ANALYSIS FAIL: {path} (exit={p.returncode})\n{output}',
                  file=sys.stderr)
        else:
            print(f'STATIC ANALYSIS PASS: {path}')
    if problems:
        print(f'STATIC ANALYSIS FAILED: {len(problems)}/{len(SOURCES)} translation units',
              file=sys.stderr)
        return 1
    print(f'STATIC ANALYSIS PASS: {len(SOURCES)}/{len(SOURCES)} translation units; no Clang diagnostics')
    return 0


if __name__ == '__main__':
    sys.exit(main())
