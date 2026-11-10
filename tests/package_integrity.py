"""Negative tests for canonical archive verifier; Python stdlib only.

Intentionally rewrites test archives and their SHA256SUMS to verify that the
format parity/regular-file/path controls cannot be bypassed by a new checksum.
"""
import hashlib
import importlib.util
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(sys.argv[1]).resolve()
BUILD = Path(sys.argv[2]).resolve()
SPEC = importlib.util.spec_from_file_location('sudoku_packager', ROOT / 'scripts' / 'package_release.py')
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)
checks = 0


def tested_fail(folder, term):
    global checks
    try:
        PACKAGE.verify_packages(folder)
    except ValueError as error:
        assert term in str(error), (term, error)
    else:
        raise AssertionError(f'Package unexpectedly accepted ({term})')
    checks += 1


def update_checksum(folder, name):
    manifest = folder / 'SHA256SUMS'
    rows = manifest.read_text().splitlines()
    rows = [hashlib.sha256((folder / name).read_bytes()).hexdigest() + '  ' + name
            if row.endswith('  ' + name) else row for row in rows]
    manifest.write_text('\n'.join(rows) + '\n')


def modify_zip(zip_path, change):
    with zipfile.ZipFile(zip_path) as source:
        members = [(item, source.read(item)) for item in source.infolist()]
    tmp = zip_path.with_suffix('.newzip')
    with zipfile.ZipFile(tmp, 'w') as dest:
        for index, (item, data) in enumerate(members):
            item, data = change(index, item, data)
            dest.writestr(item, data)
    tmp.replace(zip_path)


with tempfile.TemporaryDirectory(prefix='sudoku-integrity-') as td:
    base = Path(td)
    good = base / 'good'
    subprocess.run([sys.executable, str(ROOT / 'scripts' / 'package_release.py'),
                    '--build', str(BUILD), '--output', str(good)],
                   stdout=subprocess.DEVNULL, check=True)
    PACKAGE.verify_packages(good)
    checks += 1
    archive_name = next(x.name for x in good.glob('*-source.zip'))

    def scenario(name):
        dest = base / name
        shutil.copytree(good, dest)
        return dest

    altered = scenario('checksum')
    with (altered / archive_name).open('ab') as file:
        file.write(b'bad')
    tested_fail(altered, 'checksum mismatch')

    mismatch = scenario('cross-format')
    modify_zip(mismatch / archive_name,
               lambda index, item, data: (item, data + b'altered\n') if index == 0 else (item, data))
    update_checksum(mismatch, archive_name)
    tested_fail(mismatch, 'ZIP and TAR.GZ content disagree')

    # Regression: tamper BOTH source formats, then recompute BOTH checksums.
    # Zip/TAR parity and SHA256SUMS still pass, but the archived manifest
    # must detect a missing non-mandatory test file.
    incomplete = scenario('incomplete-source')
    source_prefix = archive_name[:-len('.zip')]
    complete_source = PACKAGE.ensure_safe_archive(good / archive_name, source_prefix)
    omitted = 'tests/source_membership_unit.py'
    assert omitted in complete_source
    source_without_test = [(name, data, 0o644)
                           for name, data in complete_source.items() if name != omitted]
    for ext, writer in (('.zip', PACKAGE.create_zip),
                        ('.tar.gz', PACKAGE.create_tar)):
        filename = source_prefix + ext
        writer(incomplete / filename, source_prefix, source_without_test)
        update_checksum(incomplete, filename)
    tested_fail(incomplete, 'source archive manifest mismatch')

    symlink = scenario('symlink')
    def set_symlink(index, item, data):
        if index == 0:
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
        return item, data
    modify_zip(symlink / archive_name, set_symlink)
    update_checksum(symlink, archive_name)
    tested_fail(symlink, 'non-regular ZIP member')

    traversal = scenario('traversal')
    def set_traversal(index, item, data):
        if index == 0:
            item.filename = item.filename.split('/')[0] + '/../escape'
        return item, data
    modify_zip(traversal / archive_name, set_traversal)
    update_checksum(traversal, archive_name)
    tested_fail(traversal, 'unsafe archive member')

    duplicate = scenario('duplicate')
    with zipfile.ZipFile(duplicate / archive_name, 'a') as output:
        entry = zipfile.ZipInfo('sudoku-v' + PACKAGE.VERSION + '-source/README.md')
        entry.create_system = 3
        entry.external_attr = (stat.S_IFREG | 0o644) << 16
        output.writestr(entry, b'duplicate')
    update_checksum(duplicate, archive_name)
    tested_fail(duplicate, 'archive entries empty, duplicated or not sorted')

    missing = scenario('missing-archive')
    one = next(missing.glob('*-source.tar.gz'))
    one.unlink()
    tested_fail(missing, 'checksum mismatch')

    forged_name = scenario('forged-name')
    manifest = forged_name / 'SHA256SUMS'
    manifest.write_text(manifest.read_text().replace('-source.zip', '-source.exe'))
    tested_fail(forged_name, 'checksum mismatch')

print(f'PACKAGE INTEGRITY PASS: {checks} independent normal/adversarial checks')
