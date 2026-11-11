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
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
MAX_ARCHIVE_BYTES = 80 * 1024 * 1024  # Same ZIP/TAR compressed cap as package_release.
MAX_CHECKSUM_BYTES = 4096
RUNNER_ARCHIVE_SUFFIX = {
    'ubuntu-latest': 'linux-x86_64',
    'windows-latest': 'windows-x86_64',
    'macos-latest': 'macos-arm64',
}


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


def source_tree_digest(members):
    """Hash verified source member paths and bytes, independent of compression.

    Length-prefixed framing prevents ambiguous concatenations. The caller
    MUST pass entries from the strict, bounded release archive verifier.
    """
    digest = hashlib.sha256(b'Sudoku-source-content-v1\0')
    for name, content in sorted(members.items()):
        encoded = name.encode('utf-8')
        digest.update(len(encoded).to_bytes(4, 'big'))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, 'big'))
        digest.update(content)
    return digest.hexdigest()


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



def write_receipt(output, receipt):
    """Write one private, fully flushed receipt without clobbering any file.

    The exclusive temporary file prevents symlink following; linking the
    completed inode to a not-yet-existing destination is atomic and refuses
    to replace a receipt created concurrently. Both paths share a directory.
    Unsupported hardlinks fail closed; no release evidence is fabricated.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = output.with_name(output.name + '.tmp')
    fd = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as file:
            json.dump(receipt, file, indent=2, sort_keys=True)
            file.write('\n')
            file.flush()
            os.fsync(file.fileno())
        os.link(stage, output)
    finally:
        stage.unlink()

def open_regular_input(path, kind):
    """Open untrusted evidence without following a final POSIX symlink.

    A path.is_file()/is_symlink() preflight alone races with replacement by a
    named pipe or symlink. O_NONBLOCK prevents waiting for a FIFO writer and
    fstat checks the *opened descriptor*. O_NOFOLLOW prevents final-component
    symlink swaps where supported; Windows retains the preflight check.
    The caller owns and closes the returned binary stream.
    """
    if path.is_symlink():
        raise ValueError('missing or unsafe ' + kind)
    flags = (os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) |
             getattr(os, 'O_NOFOLLOW', 0) |
             getattr(os, 'O_CLOEXEC', 0) |
             getattr(os, 'O_NOINHERIT', 0) |
             getattr(os, 'O_BINARY', 0))
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError('missing or unsafe ' + kind) from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('missing or unsafe ' + kind)
        return os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise


def verified_archive_hashes(dist, version, expected):
    """Recheck exact on-disk development artifacts without unbounded reads.

    A prior package verification is necessary but not sufficient: files could
    be changed before the acceptance receipt is emitted. Treat the checksum
    manifest and all four claimed files as untrusted at this boundary.
    """
    if expected not in RUNNER_ARCHIVE_SUFFIX:
        raise ValueError('unsupported acceptance runner')
    prefix = f'sudoku-v{version}-'
    names = {prefix + kind + ext
             for kind in ('source', RUNNER_ARCHIVE_SUFFIX[expected])
             for ext in ('.zip', '.tar.gz')}
    manifest = dist / 'SHA256SUMS'
    with open_regular_input(manifest, 'SHA256SUMS') as stream:
        raw = stream.read(MAX_CHECKSUM_BYTES + 1)
    if len(raw) > MAX_CHECKSUM_BYTES:
        raise ValueError('SHA256SUMS exceeds size budget')
    lines = raw.decode('ascii').splitlines()
    parsed = {}
    for line in lines:
        if not re.fullmatch(r'[0-9a-f]{64}  [A-Za-z0-9._-]+', line):
            raise ValueError('invalid SHA256SUMS record')
        digest, name = line.split('  ', 1)
        if name in parsed:
            raise ValueError('duplicate SHA256SUMS filename')
        parsed[name] = digest
    if len(lines) != 4 or set(parsed) != names or list(parsed) != sorted(parsed):
        raise ValueError('wrong or unsorted four-archive manifest')
    for name, expected_digest in parsed.items():
        archive = dist / name
        digest = hashlib.sha256()
        total = 0
        with open_regular_input(archive, 'archive: ' + name) as stream:
            # Enforce the bound on the actual opened inode, not a stale path.
            metadata = os.fstat(stream.fileno())
            if metadata.st_size > MAX_ARCHIVE_BYTES:
                raise ValueError('archive exceeds size budget: ' + name)
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise ValueError('archive exceeds size budget: ' + name)
                digest.update(chunk)
        if digest.hexdigest() != expected_digest:
            raise ValueError('archive changed after verification: ' + name)
    return dict(sorted(parsed.items()))


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
    version_text = (ROOT / 'CMakeLists.txt').read_text(encoding='utf-8')
    match = re.search(r'project\(Sudoku VERSION ([0-9]+\.[0-9]+\.[0-9]+) LANGUAGES C\)', version_text)
    if not match:
        raise ValueError('CMake project version missing')
    checksums = verified_archive_hashes(dist, match.group(1), args.expected)
    # Detect source changes made during the build/test/package operations.
    verify_checkout(sha)
    # The ZIP/TAR parity verifier already checked every member's canonical
    # path, file type and size. Hash their extracted content rather than the
    # compressed bytes, which may differ across hosts/zlib implementations.
    from package_release import ensure_safe_archive
    source_prefix = f'sudoku-v{match.group(1)}-source'
    source_members = ensure_safe_archive(dist / (source_prefix + '.zip'),
                                         source_prefix)
    source_sha = source_tree_digest(source_members)
    receipt = {
        'schema_version': 2,
        'source_tree_sha256': source_sha,
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
    write_receipt(output, receipt)
    print('PLATFORM ACCEPTANCE RECEIPT PASS:', output, flush=True)
    print(json.dumps(receipt, sort_keys=True), flush=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f'PLATFORM ACCEPTANCE FAIL: {exc}', file=sys.stderr)
        sys.exit(1)
