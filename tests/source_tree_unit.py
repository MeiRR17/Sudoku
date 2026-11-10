"""Check canonical source tree hashes without requiring a native compiler."""
import hashlib
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'scripts' / 'platform_acceptance.py'
spec = importlib.util.spec_from_file_location('sudoku_source_tree', SOURCE)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


class SourceTreeDigestTests(unittest.TestCase):
    def test_member_order_independent(self):
        a = {'src/main.c': b'int main(void) { return 0; }\n', 'README.md': b'Hello\n'}
        b = {'README.md': a['README.md'], 'src/main.c': a['src/main.c']}
        self.assertEqual(acceptance.source_tree_digest(a), acceptance.source_tree_digest(b))
        self.assertEqual(len(acceptance.source_tree_digest(a)), 64)

    def test_changed_content_or_filename_changes_digest(self):
        original = acceptance.source_tree_digest({'src/main.c': b'alpha'})
        self.assertNotEqual(original, acceptance.source_tree_digest({'src/main.c': b'beta'}))
        self.assertNotEqual(original, acceptance.source_tree_digest({'src/main2.c': b'alpha'}))

    def test_length_framing_prevents_ambiguous_concatenation(self):
        self.assertNotEqual(acceptance.source_tree_digest({'a': b'bc'}),
                            acceptance.source_tree_digest({'ab': b'c'}))
        self.assertNotEqual(acceptance.source_tree_digest({'a': b'bc'}),
                            acceptance.source_tree_digest({'a': b'b', 'c': b''}))

    def test_digest_is_domain_separated_from_ordinary_payload_sha(self):
        plain = hashlib.sha256(b'alpha').hexdigest()
        self.assertNotEqual(plain, acceptance.source_tree_digest({'file': b'alpha'}))


if __name__ == '__main__':
    unittest.main()
