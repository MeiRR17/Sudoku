#!/usr/bin/env python3
"""Check actual hosted runner platform; workflow labels alone are not evidence."""
import argparse
import platform
import sys

TARGETS = {
    'ubuntu-latest': ('Linux', {'x86_64', 'amd64'}),
    'windows-latest': ('Windows', {'amd64', 'x86_64'}),
    'macos-latest': ('Darwin', {'arm64', 'aarch64'}),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected', choices=sorted(TARGETS), required=True)
    args = parser.parse_args()
    system = platform.system()
    machine = platform.machine()
    needed_system, needed_arches = TARGETS[args.expected]
    if system != needed_system or machine.lower() not in needed_arches:
        print(f'PLATFORM GATE FAIL: {args.expected} requires {needed_system} '
              f'{sorted(needed_arches)}; actual {system} {machine}', file=sys.stderr)
        return 1
    print(f'PLATFORM GATE PASS: {args.expected} -> {system} {machine}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
