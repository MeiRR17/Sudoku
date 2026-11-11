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
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile
import zlib
import unicodedata

VERSION = '0.8.4'
ROOT = Path(__file__).resolve().parent.parent
SOURCE_LIST = ROOT / 'scripts' / 'release_files.txt'
EPOCH = 315532800  # 1980-01-01 UTC; valid in both ZIP and TAR.
MAX_ARCHIVE_FILES = 1024
MAX_UNPACKED_BYTES = 64 * 1024 * 1024  # Bound untrusted archive verification memory.
MAX_SOURCE_MANIFEST_BYTES = 256 * 1024  # Refuse oversized manifest before decoding.
MAX_ZIP_ARCHIVE_BYTES = MAX_UNPACKED_BYTES + 16 * 1024 * 1024
MAX_ZIP_DIRECTORY_BYTES = 8 * 1024 * 1024
MAX_TAR_ARCHIVE_BYTES = MAX_UNPACKED_BYTES + 16 * 1024 * 1024
# Include TAR headers, per-entry PAX metadata and zero padding in decoded budget.
MAX_TAR_DECODED_BYTES = MAX_UNPACKED_BYTES + MAX_ARCHIVE_FILES * 8192 + 16384
MAX_CHECKSUM_MANIFEST_BYTES = 4096
MAX_PORTABLE_PATH_BYTES = 4096  # Avoid pathological component-prefix expansion.
MAX_PORTABLE_PATH_PARTS = 64

# Windows rejects device names, ADS colons, restricted punctuation, control
# characters and trailing dots/spaces. Enforce the same canonical names on
# source entries, staged install files and untrusted archive members.
_WINDOWS_DEVICES = frozenset(
    ('CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$') +
    tuple(f'{prefix}{digit}' for prefix in ('COM', 'LPT')
          for digit in ('1', '2', '3', '4', '5', '6', '7', '8', '9', '¹', '²', '³'))
)


def portable_relative_name(name):
    """True only for canonical POSIX components safe on Windows as well."""
    if not name or not isinstance(name, str):
        return False
    # Casefold collision tracking indexes every path prefix. Bound both
    # pathname length and nesting before creating those intermediate keys.
    if (len(name) > MAX_PORTABLE_PATH_BYTES
            or name.count('/') >= MAX_PORTABLE_PATH_PARTS
            or len(name.encode('utf-8')) > MAX_PORTABLE_PATH_BYTES):
        return False
    for component in name.split('/'):
        if (component in ('', '.', '..') or component.endswith((' ', '.'))
                or any(ord(ch) < 32 or ord(ch) == 127 or ch in '<>:"\\|?*'
                       for ch in component)
                or component.split('.', 1)[0].rstrip(' ').upper() in _WINDOWS_DEVICES):
            return False
    return True


def claim_portable_path(name, known):
    """Reject case/Unicode aliases and file-versus-directory collisions.

    On case-insensitive extraction, different POSIX spellings can resolve to
    the same file or directory. Track every normalized path prefix so even
    distinct child names under "Assets/" and "assets/" cannot be packaged.
    The bounded archive file-count limit bounds this dictionary too.
    """
    parts = name.split('/')
    for i in range(1, len(parts) + 1):
        prefix = '/'.join(parts[:i])
        key = unicodedata.normalize('NFC', prefix).casefold()
        old = known.get(key)
        is_file = i == len(parts)
        if old is not None:
            old_prefix, old_is_file = old
            if old_prefix != prefix or old_is_file or is_file:
                raise ValueError(f'nonportable path collision: {name!r} versus {old_prefix!r}')
        else:
            known[key] = (prefix, is_file)


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


def read_regular_source(path, maximum, kind):
    """Bound bytes on the opened regular-file inode, not a pathname precheck.

    O_NONBLOCK prevents a swapped-in FIFO from hanging during open, while
    O_NOFOLLOW rejects leaf symlinks on POSIX. Earlier path-component checks
    remain necessary for source containment. Windows uses available flags.
    """
    flags = (os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) |
             getattr(os, 'O_NOFOLLOW', 0) |
             getattr(os, 'O_CLOEXEC', 0) |
             getattr(os, 'O_BINARY', 0))
    fd = os.open(path, flags)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(kind + ' must be a regular file')
        size = metadata.st_size
        if size < 0 or size > maximum:
            raise ValueError(kind + ' exceeds size budget')
        with os.fdopen(fd, 'rb') as stream:
            fd = -1
            payload = stream.read(size + 1)
        if len(payload) != size:
            raise ValueError(kind + ' changed during read')
        return payload
    finally:
        if fd >= 0:
            os.close(fd)


def bounded_file_bytes(path, remaining):
    """Reject nonregular or concurrently growing source files before packing."""
    return read_regular_source(path, remaining, 'package content')


def source_paths():
    # A source manifest is itself part of the release trust boundary.
    if SOURCE_LIST.is_symlink():
        raise ValueError('symlinked source manifest refused')
    manifest = read_regular_source(
        SOURCE_LIST, MAX_SOURCE_MANIFEST_BYTES, 'source manifest')
    raw = manifest.decode('utf-8').splitlines()
    files = []
    seen = set()
    seen_portable = {}
    total = 0
    for line in raw:
        if not line or line.startswith('#'):
            continue
        # Check size, depth and forbidden names before normalizing the path.
        if not portable_relative_name(line):
            raise ValueError(f'unsafe source path: {line}')
        name = PurePosixPath(line)
        # A POSIX-only name check is insufficient on Windows: backslashes
        # become path separators and colons can select a drive or NTFS
        # alternate data stream. Forbid both on every host.
        if (name.is_absolute() or str(name) != line):
            raise ValueError(f'unsafe source path: {line}')
        if line in seen:
            raise ValueError('duplicate source manifest path')
        if len(files) >= MAX_ARCHIVE_FILES:
            raise ValueError('source manifest exceeds file count budget')
        claim_portable_path(line, seen_portable)
        seen.add(line)
        # Refuse *every* symlink component, not just a symlink at the leaf.
        # Otherwise a tracked directory symlink could package external data.
        path = ROOT
        for part in name.parts:
            path = path / part
            if path.is_symlink():
                raise ValueError(f'symlink in source manifest path: {line}')
        if not path.is_file():
            raise ValueError(f'not a regular source file: {line}')
        payload = bounded_file_bytes(path, MAX_UNPACKED_BYTES - total)
        total += len(payload)
        files.append((str(name), payload, 0o644))
    if not files:
        raise ValueError('empty source manifest')
    return sorted(files)


def installed_paths(prefix):
    files = []
    total = 0
    seen = 0
    seen_portable = {}
    # Walk lazily: sorting rglob() before applying count budgets allocates
    # an unbounded path list, even when the eventual archive has few files.
    for file in prefix.rglob('*'):
        seen += 1
        if seen > MAX_ARCHIVE_FILES * 4:
            raise ValueError('installation exceeds entry count budget')
        if file.is_symlink():
            raise ValueError('symlink in installation tree, refusing to package')
        if not file.is_file():
            continue
        if len(files) >= MAX_ARCHIVE_FILES:
            raise ValueError('installation exceeds file count budget')
        rel = file.relative_to(prefix).as_posix()
        if not portable_relative_name(rel):
            raise ValueError(f'unsafe installed path: {rel}')
        claim_portable_path(rel, seen_portable)
        mode = 0o755 if rel.startswith('bin/') else 0o644
        payload = bounded_file_bytes(file, MAX_UNPACKED_BYTES - total)
        total += len(payload)
        files.append((rel, payload, mode))
    if not any(p.startswith('bin/sudoku') for p, _, _ in files):
        raise ValueError('sudoku executable missing from staged installation')
    return sorted(files)


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
    relative_name = '/'.join(parsed.parts[1:])
    if not portable_relative_name(relative_name):
        raise ValueError(f'unsafe archive member {name!r}')
    return relative_name


def preflight_zip_directory(path):
    """Bound ZIP central-directory metadata before ZipFile builds filelist.

    The canonical Sudoku packager produces one single-disk ZIP, with an
    ordinary 22-byte EOCD record, zero archive comment and no ZIP64 records.
    Checking the tail *before* constructing ZipFile prevents an attacker from
    forcing its eager central-directory parser to allocate many member objects.
    This is an input-format check, not authentication.
    """
    length = path.stat().st_size
    if length < 22 or length > MAX_ZIP_ARCHIVE_BYTES:
        raise ValueError('ZIP container exceeds size budget or is truncated')
    with path.open('rb') as source:
        source.seek(-22, 2)
        tail = source.read(22)
    if len(tail) != 22:
        raise ValueError('ZIP directory trailer is truncated')
    signature, disk, start_disk, disk_entries, entries, cd_size, cd_start, comment = (
        struct.unpack('<4s4H2IH', tail)
    )
    if signature != b'PK' + bytes((5, 6)) or comment != 0:
        raise ValueError('ZIP canonical directory trailer missing')
    if disk or start_disk or disk_entries != entries:
        raise ValueError('multi-disk ZIP archive not supported')
    if entries < 1 or entries > MAX_ARCHIVE_FILES:
        raise ValueError('invalid number of ZIP members')
    if cd_size > MAX_ZIP_DIRECTORY_BYTES or cd_start + cd_size != length - 22:
        raise ValueError('ZIP central directory exceeds budget or offset is invalid')
    # EOCD counts are attacker-controlled too. Walk the actual central
    # records without decoding names or instantiating ZipInfo objects.
    # Require exactly 'entries' records occupying exactly 'cd_size' bytes.
    with path.open('rb') as source:
        source.seek(cd_start)
        end = cd_start + cd_size
        for _ in range(entries):
            if source.tell() + 46 > end:
                raise ValueError('ZIP central directory entry count mismatch')
            header = source.read(46)
            if (len(header) != 46 or
                    header[:4] != b'PK' + bytes((1, 2))):
                raise ValueError('ZIP central directory entry count mismatch')
            if (header[20:24] == bytes((255,)) * 4 or
                    header[24:28] == bytes((255,)) * 4 or
                    header[42:46] == bytes((255,)) * 4):
                raise ValueError('ZIP64 entries are not canonical development archives')
            name_len, extra_len, comment_len = struct.unpack_from('<3H', header, 28)
            source.seek(name_len + extra_len + comment_len, 1)
            if source.tell() > end:
                raise ValueError('ZIP central directory entry length exceeds budget')
        if source.tell() != end:
            raise ValueError('ZIP central directory entry count mismatch')


class _BoundedTarGzipReader:
    """Count *all* decoded GZIP bytes, including TAR headers and padding."""

    def __init__(self, stream):
        self.stream = stream
        self.total = 0
        self.crc = 0

    def read(self, size=-1):
        # Streaming TAR normally requests fixed-size blocks. Never permit an
        # unbounded read even when a caller supplies -1.
        if size is None or size < 0:
            size = 65536
        remaining = MAX_TAR_DECODED_BYTES - self.total
        chunk = self.stream.read(min(size, remaining + 1))
        self.total += len(chunk)
        if self.total > MAX_TAR_DECODED_BYTES:
            raise ValueError('TAR decoded stream exceeds size budget')
        self.crc = zlib.crc32(chunk, self.crc)
        return chunk


def canonical_archive_mode(relative_name, expected_prefix):
    """Require the exact portable permission bits emitted by the packager.

    Development source archives contain read-only text/source files (0644).
    Installed binaries in bin/ use 0755, while libraries and headers use 0644.
    Checking modes prevents a byte-identical but non-executable Unix binary
    from passing ZIP/TAR parity and checksum verification.
    """
    if relative_name.startswith('bin/') and not expected_prefix.endswith('-source'):
        return 0o755
    return 0o644


def _ensure_safe_archive(path, expected_prefix):
    """Read only bounded, regular files beneath one expected top-level dir."""
    members = {}
    names = []
    seen_portable = {}
    unpacked = 0
    if path.name.endswith('.tar.gz'):
        # A huge sparse/compressed container should not be streamed for
        # hashing or parsing merely because its unpacked members are small.
        if path.stat().st_size > MAX_TAR_ARCHIVE_BYTES:
            raise ValueError('TAR container exceeds compressed size budget')
        # r|gz reads one member at a time. getmembers() would eagerly
        # materialize attacker-controlled metadata before applying the
        # MAX_ARCHIVE_FILES limit, defeating bounded-memory verification.
        # The tarfile iterator stops at the TAR end marker without necessarily
        # reading the GZIP trailer. Drain the decompressor so CRC32 and ISIZE
        # are checked even when all file members looked valid.
        with path.open('rb') as compressed:
            with gzip.GzipFile(fileobj=compressed, mode='rb') as decoder:
                bounded = _BoundedTarGzipReader(decoder)
                with tarfile.open(fileobj=bounded, mode='r|') as archive:
                    for item in archive:
                        if len(names) >= MAX_ARCHIVE_FILES:
                            raise ValueError('invalid number of TAR members')
                        if not item.isfile() or item.size < 0:
                            raise ValueError('non-regular TAR member')
                        rel = _safe_member_name(item.name, expected_prefix)
                        if item.mode != canonical_archive_mode(rel, expected_prefix):
                            raise ValueError('non-canonical TAR file mode')
                        if rel in members:
                            raise ValueError('archive entries empty, duplicated or not sorted')
                        claim_portable_path(rel, seen_portable)
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
                    if not names:
                        raise ValueError('invalid number of TAR members')
                    # The writer uses standard 10 KiB TAR records. Reject
                    # extra zero-only records hidden after the end marker.
                    canonical_size = (
                        (archive.offset + 2 * tarfile.BLOCKSIZE +
                         tarfile.RECORDSIZE - 1) // tarfile.RECORDSIZE
                    ) * tarfile.RECORDSIZE
                while True:
                    padding = bounded.read(65536)
                    if not padding:
                        break
                    if any(padding):
                        raise ValueError('non-zero trailing TAR data')
                if bounded.total != canonical_size:
                    raise ValueError('non-canonical TAR padding length')
                # gzip transparently accepts concatenated members and raw
                # zero bytes after the footer. Our package writer emits one
                # gzip member only: its final CRC32/ISIZE must describe the
                # entire decoded TAR stream, not a later appended member.
                with path.open('rb') as encoded:
                    encoded.seek(-8, 2)
                    crc, isize = struct.unpack('<II', encoded.read(8))
                if crc != bounded.crc or isize != (bounded.total & 0xffffffff):
                    raise ValueError('non-canonical GZIP trailer or extra member')
    else:
        preflight_zip_directory(path)
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
                # Forged metadata can request encryption or compressors our
                # development writer never emits. Reject before ZipExtFile
                # raises RuntimeError or NotImplementedError on open().
                if item.flag_bits & 0x41:
                    raise ValueError('encrypted ZIP member is not supported')
                if item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ValueError('unsupported ZIP compression method')
                rel = _safe_member_name(item.filename, expected_prefix)
                if mode != (stat.S_IFREG | canonical_archive_mode(rel, expected_prefix)):
                    raise ValueError('non-canonical ZIP file mode')
                if rel in members:
                    raise ValueError('archive entries empty, duplicated or not sorted')
                claim_portable_path(rel, seen_portable)
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


def ensure_safe_archive(path, expected_prefix):
    """Reject damaged ZIP/TAR.GZ payloads with the verifier's ValueError API.

    zipfile, gzip and tarfile raise several decoder-specific exceptions for
    untrusted compressed bytes. A malformed distribution is a verification
    failure, not an uncaught traceback or a successful partial extraction.
    Preserve the bounded, regular-file and canonical-path checks above.
    """
    try:
        return _ensure_safe_archive(path, expected_prefix)
    except (tarfile.TarError, zipfile.BadZipFile, gzip.BadGzipFile,
            zlib.error, EOFError, struct.error) as exc:
        raise ValueError('malformed archive container') from exc


def check_archive(path, expected_prefix):
    members = ensure_safe_archive(path, expected_prefix)
    print(f'ARCHIVE PASS {path.name}: {len(members)} regular files')
    return members


def verify_source_membership(entries):
    """Require a self-consistent, buildable-source membership declaration.

    A recomputed unsigned SHA256SUMS and matching ZIP/TAR bytes do not prove
    that a source package contains the files claimed by its own manifest.
    Verify exact equality of the archived path set and archived manifest.
    This validates completeness relative to that manifest, not authenticity.
    """
    payload = entries.get('scripts/release_files.txt')
    if payload is None or len(payload) > MAX_SOURCE_MANIFEST_BYTES:
        raise ValueError('source archive missing or oversized release_files manifest')
    try:
        lines = payload.decode('utf-8').splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError('source archive manifest must be UTF-8') from exc
    declared = set()
    seen_portable = {}
    for line in lines:
        if not line or line.startswith('#'):
            continue
        path = PurePosixPath(line)
        if (not portable_relative_name(line) or path.is_absolute()
                or str(path) != line):
            raise ValueError(f'unsafe source archive manifest path: {line!r}')
        if line in declared:
            raise ValueError(f'duplicate source archive manifest path: {line!r}')
        if len(declared) >= MAX_ARCHIVE_FILES:
            raise ValueError('source archive manifest exceeds file count budget')
        claim_portable_path(line, seen_portable)
        declared.add(line)
    if not declared:
        raise ValueError('empty source archive manifest')
    actual = set(entries)
    if actual != declared:
        missing = sorted(declared - actual)
        extra = sorted(actual - declared)
        raise ValueError(f'source archive manifest mismatch: missing={missing!r} extra={extra!r}')


def verify_packages(dest):
    manifest = dest / 'SHA256SUMS'
    if not manifest.is_file() or manifest.is_symlink():
        raise ValueError('missing or unsafe SHA256SUMS')
    # Never decode an untrusted checksum manifest without a byte ceiling.
    # Four canonical records are far below 4 KiB on supported platforms.
    with manifest.open('rb') as stream:
        raw = stream.read(MAX_CHECKSUM_MANIFEST_BYTES + 1)
    if len(raw) > MAX_CHECKSUM_MANIFEST_BYTES:
        raise ValueError('SHA256SUMS exceeds size budget')
    try:
        lines = raw.decode('ascii').splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError('SHA256SUMS must be ASCII') from exc
    if len(lines) != 4 or len(lines) != len(set(lines)):
        raise ValueError('expected four distinct archive checksums')
    parsed = {}
    for line in lines:
        if not re.fullmatch(r'[0-9a-f]{64}  [a-zA-Z0-9._-]+', line):
            raise ValueError('invalid SHA256SUMS record')
        digest, name = line.split('  ', 1)
        file = dest / name
        if not file.is_file() or file.is_symlink():
            raise ValueError(f'checksum mismatch: {name}')
        # Bounds must precede even the streaming SHA-256 pass: a single
        # sparse archive could otherwise consume unbounded I/O and time.
        limit = (MAX_TAR_ARCHIVE_BYTES if name.endswith('.tar.gz')
                 else MAX_ZIP_ARCHIVE_BYTES)
        if file.stat().st_size > limit:
            raise ValueError(f'archive exceeds compressed size budget: {name}')
        if file_hash(file) != digest:
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
            verify_source_membership(tar_entries)
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
