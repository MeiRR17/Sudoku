#!/usr/bin/env python3
"""Build deterministic *development* ZIP/TGZ archives and SHA-256 manifest.

This script deliberately does NOT create GitHub releases, apply a software
license, or claim portability. Run this on each real target platform.
"""
import argparse
import gzip
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile

VERSION = '0.8.2'
ROOT = Path(__file__).resolve().parent.parent
SOURCE_LIST = ROOT / 'scripts' / 'release_files.txt'
EPOCH = 315532800  # 1980-01-01 UTC; valid in both ZIP and TAR.
MAX_ARCHIVE_FILES = 1024
MAX_UNPACKED_BYTES = 64 * 1024 * 1024  # Bound untrusted archive verification memory.


def file_hash(path):
    h = hashlib.sha256()
    with path.open('rb') as src:
        for chunk in iter(lambda: src.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def target_platform():
    systems = {'Linux': 'linux', 'Darwin': 'macos', 'Windows': 'windows'}
    machines = {'x86_64': 'x86_64', 'AMD64': 'x86_64', 'aarch64': 'arm64', 'arm64': 'arm64'}
    system = systems.get(platform.system())
    arch = machines.get(platform.machine())
    if not system or not arch:
        raise ValueError('unsupported packaging host; no platform label inferred')
    return f'{system}-{arch}'


def source_paths():
    raw = SOURCE_LIST.read_text(encoding='utf-8').splitlines()
    files = []
    for line in raw:
        if not line or line.startswith('#'):
            continue
        name = PurePosixPath(line)
        if name.is_absolute() or '..' in name.parts or str(name) != line or line.startswith('.') and line == '.':
            raise ValueError(f'unsafe source path: {line}')
        path = ROOT.joinpath(*name.parts)
        if not path.is_file() or path.is_symlink():
            raise ValueError(f'not a regular source file: {line}')
        files.append((str(name), path.read_bytes(), 0o644))
    if len(files) != len(set(x[0] for x in files)):
        raise ValueError('duplicate source manifest path')
    if not files:
        raise ValueError('empty source manifest')
    return sorted(files)


def installed_paths(prefix):
    files = []
    for file in sorted(prefix.rglob('*')):
        if file.is_symlink():
            raise ValueError('symlink in installation tree, refusing to package')
        if not file.is_file():
            continue
        rel = file.relative_to(prefix).as_posix()
        mode = 0o755 if rel.startswith('bin/') else 0o644
        files.append((rel, file.read_bytes(), mode))
    if not any(p.startswith('bin/sudoku') for p, _, _ in files):
        raise ValueError('sudoku executable missing from staged installation')
    return files


def create_tar(dest, prefix, files):
    with dest.open('wb') as output:
        with gzip.GzipFile(fileobj=output, filename='', mode='wb', mtime=0, compresslevel=9) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
                for rel, data, mode in sorted(files):
                    item = tarfile.TarInfo(f'{prefix}/{rel}')
                    item.size = len(data)
                    item.mode = mode
                    item.mtime = EPOCH
                    item.uid = item.gid = 0
                    item.uname = item.gname = ''
                    archive.addfile(item, io.BytesIO(data))


def create_zip(dest, prefix, files):
    with zipfile.ZipFile(dest, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for rel, data, mode in sorted(files):
            info = zipfile.ZipInfo(f'{prefix}/{rel}', date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o100000 | mode) << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _safe_member_name(name, expected_prefix):
    """Reject mixed/ambiguous paths; never use zipfile's lossy path sanitizer."""
    if not name or "\\" in name or "\x00" in name or name.endswith('/'):
        raise ValueError(f'unsafe archive member {name!r}')
    parsed = PurePosixPath(name)
    if (parsed.is_absolute() or parsed.as_posix() != name
            or len(parsed.parts) < 2 or parsed.parts[0] != expected_prefix
            or any(part in ('.', '..') for part in name.split('/'))):
        raise ValueError(f'unsafe archive member {name!r}')
    return '/'.join(parsed.parts[1:])


def ensure_safe_archive(path, expected_prefix):
    """Read only bounded, regular files beneath one expected top-level dir."""
    members = {}
    names = []
    unpacked = 0
    if path.name.endswith('.tar.gz'):
        with tarfile.open(path, 'r:gz') as archive:
            infos = archive.getmembers()
            if not 1 <= len(infos) <= MAX_ARCHIVE_FILES:
                raise ValueError('invalid number of TAR members')
            for item in infos:
                if not item.isfile() or item.size < 0:
                    raise ValueError('non-regular TAR member')
                rel = _safe_member_name(item.name, expected_prefix)
                unpacked += item.size
                if unpacked > MAX_UNPACKED_BYTES:
                    raise ValueError('TAR unpacked content exceeds size budget')
                stream = archive.extractfile(item)
                if stream is None:
                    raise ValueError('unreadable TAR member')
                with stream:
                    payload = stream.read(item.size + 1)
                if len(payload) != item.size:
                    raise ValueError('TAR member length mismatch')
                members[rel] = payload
                names.append(item.name)
    else:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if not 1 <= len(infos) <= MAX_ARCHIVE_FILES:
                raise ValueError('invalid number of ZIP members')
            for item in infos:
                # The canonical packager sets Unix regular-file attributes on
                # every host. Reject symlinks, device files, and missing types.
                mode = item.external_attr >> 16
                if item.is_dir() or item.create_system != 3 or not stat.S_ISREG(mode):
                    raise ValueError('non-regular ZIP member')
                rel = _safe_member_name(item.filename, expected_prefix)
                unpacked += item.file_size
                if unpacked > MAX_UNPACKED_BYTES:
                    raise ValueError('ZIP unpacked content exceeds size budget')
                with archive.open(item, 'r') as stream:
                    payload = stream.read(item.file_size + 1)
                if len(payload) != item.file_size:
                    raise ValueError('ZIP member length mismatch')
                members[rel] = payload
                names.append(item.filename)
    if names != sorted(set(names)) or len(names) != len(members):
        raise ValueError('archive entries empty, duplicated or not sorted')
    return members


def check_archive(path, expected_prefix):
    members = ensure_safe_archive(path, expected_prefix)
    print(f'ARCHIVE PASS {path.name}: {len(members)} regular files')
    return members


def verify_packages(dest):
    manifest = dest / 'SHA256SUMS'
    if not manifest.is_file() or manifest.is_symlink():
        raise ValueError('missing or unsafe SHA256SUMS')
    lines = manifest.read_text(encoding='ascii').splitlines()
    if len(lines) != 4 or len(lines) != len(set(lines)):
        raise ValueError('expected four distinct archive checksums')
    parsed = {}
    for line in lines:
        if not re.fullmatch(r'[0-9a-f]{64}  [a-zA-Z0-9._-]+', line):
            raise ValueError('invalid SHA256SUMS record')
        digest, name = line.split('  ', 1)
        file = dest / name
        if not file.is_file() or file.is_symlink() or file_hash(file) != digest:
            raise ValueError(f'checksum mismatch: {name}')
        ext = '.tar.gz' if name.endswith('.tar.gz') else '.zip' if name.endswith('.zip') else ''
        if not ext:
            raise ValueError(f'unexpected release extension: {name}')
        prefix = name[:-len(ext)]
        if not re.fullmatch(r'sudoku-v' + re.escape(VERSION) +
                            r'-(?:source|(?:linux|windows|macos)-(?:x86_64|arm64))', prefix):
            raise ValueError(f'unexpected release filename: {name}')
        if (prefix, ext) in parsed:
            raise ValueError(f'duplicate release variant: {name}')
        parsed[(prefix, ext)] = check_archive(file, prefix)
    variants = {prefix for prefix, _ in parsed}
    if len(variants) != 2 or f'sudoku-v{VERSION}-source' not in variants:
        raise ValueError('must contain one binary platform and one source release')
    if any((prefix, ext) not in parsed for prefix in variants for ext in ('.zip', '.tar.gz')):
        raise ValueError('missing one release archive format')
    for prefix in variants:
        tar_entries = parsed[(prefix, '.tar.gz')]
        if tar_entries != parsed[(prefix, '.zip')]:
            raise ValueError(f'ZIP and TAR.GZ content disagree: {prefix}')
        if prefix.endswith('-source'):
            required = {'README.md', 'CMakeLists.txt',
                        'src/core/solver.c', 'src/core/game.c',
                        'scripts/package_release.py', 'scripts/release_files.txt'}
        else:
            executable = 'bin/sudoku.exe' if '-windows-' in prefix else 'bin/sudoku'
            required = {executable, 'include/sudoku/board.h',
                        'include/sudoku/game.h'}
        if not required.issubset(tar_entries):
            raise ValueError(f'missing mandatory release content: {prefix}')
    print('SHA256 AND CROSS-FORMAT PASS: 4 archives, matched files byte-for-byte')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--config', default='Release')
    ap.add_argument('--verify-only', action='store_true')
    args = ap.parse_args()
    out = args.output.resolve()
    if args.verify_only:
        verify_packages(out)
        return
    if args.build is None or not (args.build / 'CMakeCache.txt').is_file():
        ap.error('a configured CMake --build directory is required')
    if not shutil.which('cmake'):
        ap.error('cmake is required')
    target = target_platform()
    with tempfile.TemporaryDirectory(prefix='sudoku-stage-') as folder:
        stage = Path(folder) / 'install'
        subprocess.run(['cmake', '--install', str(args.build.resolve()), '--config', args.config,
                        '--prefix', str(stage)], check=True, stdout=subprocess.PIPE)
        files = installed_paths(stage)
        binary = stage / 'bin' / ('sudoku.exe' if platform.system() == 'Windows' else 'sudoku')
        result = subprocess.run([str(binary), '--version'], capture_output=True, text=True, check=True)
        if result.stdout.strip() != 'Sudoku ' + VERSION + ' (experimental)':
            raise ValueError('installed executable version mismatch: ' + result.stdout)
        out.mkdir(parents=True, exist_ok=True)
        prefixes = [(f'sudoku-v{VERSION}-{target}', files),
                    (f'sudoku-v{VERSION}-source', source_paths())]
        records = []
        for prefix, entries in prefixes:
            for ext, fn in [('.tar.gz', create_tar), ('.zip', create_zip)]:
                archive = out / (prefix + ext)
                fn(archive, prefix, entries)
                check_archive(archive, prefix)
                records.append((archive.name, file_hash(archive)))
        (out / 'SHA256SUMS').write_text(''.join(f'{digest}  {name}\n' for name, digest in sorted(records)), encoding='ascii')
    verify_packages(out)
    print('DEVELOPMENT PACKAGE PASS — no official GitHub release or license approved')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'Package failure: {exc}', file=sys.stderr)
        sys.exit(1)
