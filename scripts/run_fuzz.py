"""Opt-in bounded libFuzzer smoke campaign, in a copied corpus directory.

Requirements: clang with libFuzzer, sanitizer runtimes and Python 3.
Only a short deterministic campaign, NOT a coverage-complete security audit.
Usage: python3 scripts/run_fuzz.py --runs 8000
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--runs', type=int, default=3000)
    p.add_argument('--seed', type=int, default=1770)
    args = p.parse_args()
    if not 1 <= args.runs <= 1000000:
        p.error('runs must be between 1 and 1000000')
    if not shutil.which('clang'):
        p.error('clang with libFuzzer is required')
    with tempfile.TemporaryDirectory(prefix='sudoku-fuzz-') as tmp:
        workspace = Path(tmp)
        for name in ('parser', 'solver'):
            binary = workspace / ('fuzz_' + name)
            command = ['clang', '-std=c11', '-O1', '-g', '-fsanitize=fuzzer,address,undefined',
                       '-I' + str(ROOT / 'include'), str(ROOT / 'tests' / ('fuzz_' + name + '.c')),
                       str(ROOT / 'src/core/board.c')]
            if name == 'solver':
                command.append(str(ROOT / 'src/core/solver.c'))
            command += ['-o', str(binary)]
            print('FUZZ BUILD', name, flush=True)
            subprocess.run(command, check=True)
            source = ROOT / 'tests' / 'corpus' / name
            corpus = workspace / ('corpus-' + name)
            shutil.copytree(source, corpus)
            print('FUZZ RUN', name, args.runs, 'seed=', args.seed, flush=True)
            subprocess.run([str(binary), str(corpus), '-runs=' + str(args.runs),
                            '-max_len=192' if name == 'parser' else '-max_len=81',
                            '-seed=' + str(args.seed), '-timeout=5',
                            '-artifact_prefix=' + str(workspace) + '/'], check=True)
        print('FUZZ SMOKE PASS (no crash; not exhaustive)', flush=True)


if __name__ == '__main__':
    main()
