#!/usr/bin/env python3
"""Check that three unsigned platform receipts describe one exact source SHA.

Consistency checks are NOT artifact authenticity, native-run verification,
license approval, or a production release. No network or package install.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
PLATFORMS = {
    'ubuntu-latest': ('Linux', {'x86_64', 'amd64'}, {'GNU', 'Clang'}, 'linux-x86_64'),
    'windows-latest': ('Windows', {'amd64', 'x86_64'}, {'MSVC'}, 'windows-x86_64'),
    'macos-latest': ('Darwin', {'arm64', 'aarch64'}, {'AppleClang', 'Clang'}, 'macos-arm64'),
}
SHA_RE = re.compile(r'[0-9a-f]{40}\Z')
DIGEST_RE = re.compile(r'[0-9a-f]{64}\Z')


def unique_dict(items):
    """Disallow ambiguous duplicate keys in both receipts and nested maps."""
    result = {}
    for name, value in items:
        if name in result:
            raise ValueError('duplicate receipt JSON key: ' + name)
        result[name] = value
    return result


def read_manifest(path):
    lines = path.read_text(encoding='ascii').splitlines()
    records = {}
    for line in lines:
        if not re.fullmatch(r'[0-9a-f]{64}  [a-zA-Z0-9._-]+', line):
            raise ValueError('invalid SHA256SUMS record')
        digest, filename = line.split('  ', 1)
        if filename in records:
            raise ValueError('duplicate SHA256SUMS filename')
        records[filename] = digest
    if len(lines) != 4:
        raise ValueError('expected four SHA256SUMS entries')
    if list(records) != sorted(records):
        raise ValueError('SHA256SUMS filenames must be sorted')
    return records


def verify_one(folder, platform_name, sha, version):
    system, arches, compilers, platform_suffix = PLATFORMS[platform_name]
    receipt = json.loads((folder / 'platform-receipt.json').read_text(encoding='utf-8'),
                         object_pairs_hook=unique_dict)
    if not isinstance(receipt, dict):
        raise ValueError('receipt must be a JSON object')
    required = {'schema_version': 2, 'status': 'passed', 'git_commit_sha': sha,
                'project_version': version, 'runner_expected': platform_name,
                'observed_system': system}
    for field, wanted in required.items():
        if type(receipt.get(field)) is not type(wanted) or receipt[field] != wanted:
            raise ValueError(f'{platform_name}: wrong receipt {field}')
    if str(receipt.get('observed_arch', '')).lower() not in arches:
        raise ValueError(f'{platform_name}: wrong observed CPU architecture')
    if receipt.get('c_compiler_id') not in compilers:
        raise ValueError(f'{platform_name}: wrong C compiler')
    if receipt.get('quality_gate_mode') not in ('full', 'fast'):
        raise ValueError(f'{platform_name}: unsupported quality gate mode')
    checks = receipt.get('checks')
    if not isinstance(checks, list) or not {'quality_gate', 'package_release',
                                           'package_verify'}.issubset(checks):
        raise ValueError(f'{platform_name}: required checks missing')
    if not isinstance(receipt.get('scope'), str) or 'unsigned' not in receipt['scope']:
        raise ValueError(f'{platform_name}: unsigned scope marker missing')
    try:
        created = datetime.fromisoformat(receipt['created_utc'])
    except (TypeError, ValueError, KeyError) as error:
        raise ValueError(f'{platform_name}: invalid creation time') from error
    if created.tzinfo is None or created.utcoffset() is None:
        raise ValueError(f'{platform_name}: receipt time missing timezone')

    prefix = f'sudoku-v{version}-'
    expected_files = {prefix + kind + ext
                      for kind in ('source', platform_suffix)
                      for ext in ('.zip', '.tar.gz')}
    digests = receipt.get('archive_sha256')
    if not isinstance(digests, dict) or set(digests) != expected_files:
        raise ValueError(f'{platform_name}: unexpected archive set')
    if any(not isinstance(value, str) or DIGEST_RE.fullmatch(value) is None
           for value in digests.values()):
        raise ValueError(f'{platform_name}: invalid archive SHA-256')
    if read_manifest(folder / 'SHA256SUMS') != digests:
        raise ValueError(f'{platform_name}: receipt and SHA256SUMS differ')
    source_tree = receipt.get('source_tree_sha256')
    if not isinstance(source_tree, str) or DIGEST_RE.fullmatch(source_tree) is None:
        raise ValueError(f'{platform_name}: invalid canonical source content SHA-256')
    return receipt


def verify_matrix(folders, sha, version):
    if not isinstance(sha, str) or SHA_RE.fullmatch(sha) is None:
        raise ValueError('require one exact 40-character lowercase Git SHA')
    if set(folders) != set(PLATFORMS):
        raise ValueError('require precisely Linux, Windows and macOS evidence')
    receipts = {name: verify_one(Path(folders[name]), name, sha, version)
                for name in PLATFORMS}
    # ZIP and GZip compressors can emit different bytes across operating
    # systems even when their extracted, validated source trees are identical.
    # The acceptance runner records a domain-separated canonical content hash
    # over sorted path/length/content tuples from its verified source ZIP.
    source_hashes = {r['source_tree_sha256'] for r in receipts.values()}
    if len(source_hashes) != 1:
        raise ValueError('source content differs across target platforms')
    return receipts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-sha', required=True)
    parser.add_argument('--linux', type=Path, required=True)
    parser.add_argument('--windows', type=Path, required=True)
    parser.add_argument('--macos', type=Path, required=True)
    args = parser.parse_args()
    cmake = (ROOT / 'CMakeLists.txt').read_text(encoding='utf-8')
    match = re.search(r'project\(Sudoku VERSION ([0-9]+\.[0-9]+\.[0-9]+) LANGUAGES C\)', cmake)
    if match is None:
        raise ValueError('CMake project version missing')
    receipts = verify_matrix({'ubuntu-latest': args.linux,
                              'windows-latest': args.windows,
                              'macos-latest': args.macos}, args.require_sha,
                             match.group(1))
    for name, receipt in receipts.items():
        print(name, receipt['observed_arch'], receipt['c_compiler_id'],
              receipt['quality_gate_mode'])
    print('EVIDENCE MATRIX CONSISTENT: exact SHA and matching source archives')
    print('NOT RELEASE APPROVAL: receipts unsigned; license and actual artifact inspection remain required')


if __name__ == '__main__':
    try:
        main()
    except (OSError, UnicodeError, ValueError) as exc:
        print('EVIDENCE MATRIX FAIL:', exc, file=sys.stderr)
        sys.exit(1)
