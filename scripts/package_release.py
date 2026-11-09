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
import subprocess
import sys
import tarfile
import tempfile
import zipfile

VERSION = '0.8.1'
ROOT = Path(__file__).resolve().parent.parent
SOURCE_LIST = ROOT / 'scripts' / 'release_files.txt'
EPOCH = 315532800  # 1980-01-01 UTC; valid in both ZIP and TAR.


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


def ensure_safe_archive(path, expected_prefix):
    if path.name.endswith('.tar.gz'):
        with tarfile.open(path, 'r:gz') as archive:
            members = archive.getmembers()
            if any(not m.isfile() for m in members):
                raise ValueError('non-file member found in TAR')
            names = [m.name for m in members]
            values = [archive.extractfile(m).read() for m in members]
    else:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if any(x.is_dir() for x in members):
                raise ValueError('unexpected ZIP directory member')
            names = [x.filename for x in members]
            values = [archive.read(x) for x in members]
    if not names or names != sorted(set(names)):
        raise ValueError('archive entries are empty, duplicated or not sorted')
    for name in names:
        parts = PurePosixPath(name)
        if parts.is_absolute() or '..' in parts.parts or len(parts.parts) < 2 or parts.parts[0] != expected_prefix:
            raise ValueError(f'unsafe archive member {name}')
    return [(name, value) for name, value in zip(names, values)]


def check_archive(path, expected_prefix):
    members = ensure_safe_archive(path, expected_prefix)
    print(f'ARCHIVE PASS {path.name}: {len(members)} files')
    return members


def verify_packages(dest):
    manifest = dest / 'SHA256SUMS'
    if not manifest.is_file():
        raise ValueError('missing SHA256SUMS')
    lines = manifest.read_text(encoding='ascii').splitlines()
    if len(lines) != 4:
        raise ValueError('expected exactly four release archives')
    names = []
    for line in lines:
        if not re.fullmatch(r'[0-9a-f]{64}  [a-zA-Z0-9._-]+', line):
            raise ValueError('invalid SHA256SUMS record')
        digest, name = line.split('  ', 1)
        file = dest / name
        if not file.is_file() or file.is_symlink() or file_hash(file) != digest:
            raise ValueError(f'checksum mismatch: {name}')
        prefix = name.removesuffix('.tar.gz').removesuffix('.zip')
        check_archive(file, prefix)
        names.append(name)
    if sorted(set(names)) != sorted(names):
        raise ValueError('duplicated checksums')
    print('SHA256 PASS: four archives verified')


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
