#!/usr/bin/env python3
"""Fail-closed local platform acceptance and exact-commit evidence receipt.

Runs the fast/full build gate once, then builds/verifies development archives.
Emits an unsigned local JSON receipt only after all commands succeed. It is
not release approval, artifact signing, or proof for any other host platform.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def call(*args, capture=False):
    result = subprocess.run([str(x) for x in args], cwd=ROOT, check=True,
                            text=True, capture_output=capture)
    return result.stdout.strip() if capture else None


def compiler_identity(build):
    files = sorted((build / 'CMakeFiles').glob('*/CMakeCCompiler.cmake'))
    if len(files) != 1:
        raise ValueError('expected exactly one configured C compiler identity')
    data = files[0].read_text(encoding='utf-8')
    found = re.search(r'^set\(CMAKE_C_COMPILER_ID "([^"]+)"\)', data, re.M)
    if not found:
        raise ValueError('configured C compiler identity missing')
    return found.group(1)


def verify_checkout(required_sha=None):
    """Bind evidence to the exact clean checkout, including untracked files."""
    sha = call('git', 'rev-parse', '--verify', 'HEAD', capture=True)
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('not on an exact Git commit')
    if required_sha is not None:
        if not re.fullmatch(r'[0-9a-f]{40}', required_sha):
            raise ValueError('required SHA must be exactly 40 lowercase hex characters')
        if sha != required_sha:
            raise ValueError(f'Git HEAD does not match required SHA: {required_sha}')
    if call('git', 'status', '--porcelain', '--untracked-files=all', capture=True):
        raise ValueError('tracked or untracked worktree changes prevent exact-commit evidence')
    return sha


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--expected', required=True,
                    choices=('ubuntu-latest', 'windows-latest', 'macos-latest'))
    ap.add_argument('--mode', choices=('fast', 'full'), default='fast')
    ap.add_argument('--require-sha', help='Require exact Git HEAD (automatically uses GITHUB_SHA in Actions)')
    ap.add_argument('--output', type=Path, default=Path('dist/platform-receipt.json'))
    args = ap.parse_args()
    if args.mode == 'full' and args.expected != 'ubuntu-latest':
        ap.error('full mode is only supported for the Linux x64 runner')
    output = (ROOT / args.output).resolve()
    if output.exists():
        raise ValueError('refusing to overwrite an existing acceptance receipt')

    call(sys.executable, ROOT / 'scripts/verify_runner_platform.py',
         '--expected', args.expected)
    sha = verify_checkout(args.require_sha or os.environ.get('GITHUB_SHA'))

    build_root = ROOT / '.quality-build' / ('acceptance-' + sha[:12])
    call(sys.executable, ROOT / 'scripts/quality_gate.py', '--mode', args.mode,
         '--build-root', build_root)
    build = build_root / ('clang' if args.mode == 'full' else 'native')
    compiler = compiler_identity(build)
    if args.expected == 'windows-latest' and compiler != 'MSVC':
        raise ValueError('Windows x64 acceptance requires actual MSVC compiler')
    if args.expected == 'macos-latest' and compiler not in ('AppleClang', 'Clang'):
        raise ValueError('macOS arm64 requires an Apple/Clang compiler')
    if args.expected == 'ubuntu-latest' and compiler not in ('GNU', 'Clang'):
        raise ValueError('Linux x64 requires GCC or Clang')

    dist = output.parent
    call(sys.executable, ROOT / 'scripts/package_release.py', '--build', build,
         '--output', dist)
    call(sys.executable, ROOT / 'scripts/package_release.py', '--verify-only',
         '--output', dist)
    manifest = dist / 'SHA256SUMS'
    checksums = {}
    for line in manifest.read_text(encoding='ascii').splitlines():
        digest, name = line.split('  ', 1)
        if not re.fullmatch(r'[0-9a-f]{64}', digest) or '/' in name or '\\' in name:
            raise ValueError('unsafe archive manifest record')
        actual = hashlib.sha256((dist / name).read_bytes()).hexdigest()
        if digest != actual:
            raise ValueError(f'archive changed after verification: {name}')
        checksums[name] = digest
    if len(checksums) != 4:
        raise ValueError('expected four checked development archives')
    # Detect source changes made during the build/test/package operations.
    verify_checkout(sha)

    version_text = (ROOT / 'CMakeLists.txt').read_text(encoding='utf-8')
    match = re.search(r'project\(Sudoku VERSION ([0-9]+\.[0-9]+\.[0-9]+) LANGUAGES C\)', version_text)
    if not match:
        raise ValueError('CMake project version missing')
    receipt = {
        'schema_version': 1,
        'status': 'passed',
        'scope': 'this host only; unsigned development evidence, not release approval',
        'git_commit_sha': sha,
        'project_version': match.group(1),
        'runner_expected': args.expected,
        'observed_system': platform.system(),
        'observed_arch': platform.machine(),
        'c_compiler_id': compiler,
        'quality_gate_mode': args.mode,
        'checks': ['quality_gate', 'package_release', 'package_verify'],
        'archive_sha256': dict(sorted(checksums.items())),
        'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = output.with_name(output.name + '.tmp')
    stage.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    stage.replace(output)
    print('PLATFORM ACCEPTANCE RECEIPT PASS:', output, flush=True)
    print(json.dumps(receipt, sort_keys=True), flush=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f'PLATFORM ACCEPTANCE FAIL: {exc}', file=sys.stderr)
        sys.exit(1)
