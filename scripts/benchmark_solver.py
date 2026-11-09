"""Collect reproducible subprocess performance baselines for a small fixed dataset.

Single process start overhead is included; this benchmark measures end-user
CLI latency, not isolated engine timings. No hard speed thresholds in v0.5.
"""
import argparse
import json
import os
import pathlib
import platform
import statistics
import subprocess
import time


def percentile(sorted_numbers, p):
    return sorted_numbers[min(len(sorted_numbers) - 1, max(0, (len(sorted_numbers) * p + 99) // 100 - 1))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('executable', type=pathlib.Path)
    ap.add_argument('--iterations', type=int, default=25)
    ap.add_argument('--output', type=pathlib.Path)
    args = ap.parse_args()
    if not 5 <= args.iterations <= 10000:
        ap.error('iterations must be between 5 and 10000')
    binary = args.executable.resolve()
    cases = {
        'classic_unique': ('solve', '530070000600195000098000060800060003400803001700020006060000280000419005000080079'),
        'ai_escargot': ('solve', '100007090030020008009600500005300900010080002600004000300000010040000007007000300'),
        'diabolical': ('solve', '800000000003600000070090200050007000000045700000100030001000068008500010090000400'),
        'empty_two_or_more': ('count', '0' * 81),
        'unsolvable_zero': ('count', '531070000600195000098000060800060003400803001700020006060000280000419005000080079'),
    }
    compiler = subprocess.run([str(binary), '--version'], capture_output=True, text=True, check=True).stdout.strip()
    report = {'platform': platform.platform(), 'machine': platform.machine(),
              'python': platform.python_version(), 'program': compiler,
              'iterations': args.iterations, 'measure': 'CLI subprocess elapsed time in milliseconds',
              'cases': {}}
    for name, (cmd, puzzle) in cases.items():
        samples = []
        for i in range(args.iterations + 2):
            begin = time.perf_counter_ns()
            p = subprocess.run([str(binary), cmd, '--puzzle', puzzle, '--format', 'compact'],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            elapsed = (time.perf_counter_ns() - begin) / 1_000_000
            if p.returncode:
                raise RuntimeError(f'{name} failed: {p.returncode}: {p.stderr!r}')
            if i >= 2:  # warm-up samples omitted
                samples.append(elapsed)
        samples.sort()
        report['cases'][name] = {'p50_ms': round(statistics.median(samples), 3),
                                 'p95_ms': round(percentile(samples, 95), 3),
                                 'max_ms': round(samples[-1], 3)}
        print(f'BENCH {name}: p50={statistics.median(samples):.3f}ms '
              f'p95={percentile(samples, 95):.3f}ms')
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    main()
