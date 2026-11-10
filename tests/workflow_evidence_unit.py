"""No-network checks that acceptance evidence is retained without publishing binaries.

This is a workflow-configuration guard, not evidence that Actions ran.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'manual-quality.yml'


def workflow():
    return WORKFLOW.read_text(encoding='utf-8')


class EvidenceWorkflowTests(unittest.TestCase):
    def test_manual_only_no_implicit_ci_cost(self):
        source = workflow()
        self.assertRegex(source, r'(?m)^on:\n  workflow_dispatch:\n')
        self.assertNotRegex(source, r'(?m)^  (?:push|pull_request|schedule):')
        self.assertIn('permissions:\n  contents: read', source)

    def test_successful_exact_sha_acceptance_precedes_upload(self):
        source = workflow()
        self.assertIn('--require-sha "${{ github.sha }}"', source)
        gate = source.index('run: python scripts/platform_acceptance.py ')
        upload = source.index('uses: actions/upload-artifact@')
        self.assertLess(gate, upload)
        self.assertRegex(source, r'(?m)^        uses: actions/upload-artifact@[0-9a-f]{40} # v[0-9.]+$')

    def test_only_receipt_and_hash_manifest_retained(self):
        source = workflow()
        self.assertIn('if-no-files-found: error', source)
        self.assertIn('retention-days: 7', source)
        self.assertIn('compression-level: 0', source)
        paths = re.search(r'(?m)^          path: \|\n((?:            [^\n]+\n)+)', source)
        self.assertIsNotNone(paths)
        self.assertEqual(paths.group(1).splitlines(),
                         ['            dist/platform-receipt.json',
                          '            dist/SHA256SUMS'])
        self.assertNotIn('dist/**', paths.group(1))
        self.assertNotIn('dist/*.zip', paths.group(1))
        self.assertNotIn('dist/*.tar.gz', paths.group(1))

    def test_evidence_artifact_name_distinguishes_platform_sha_and_attempt(self):
        source = workflow()
        self.assertIn('name: sudoku-evidence-${{ inputs.runner_os }}-'
                      '${{ github.sha }}-attempt-${{ github.run_attempt }}', source)
        self.assertIn('runs-on: ${{ inputs.runner_os }}', source)


if __name__ == '__main__':
    unittest.main()
