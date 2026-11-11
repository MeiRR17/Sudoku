"""Offline, dependency-free guardrails for the manual multi-host evidence gate.

These text-level tests do not execute GitHub Actions or certify a native build.
They make accidental automatic triggering, runner mismatches and binary artifact
uploads visible before scheduling any paid native runner minutes.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'manual-quality.yml'


class ManualQualityWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text(encoding='utf-8')
        cls.quality, cls.review = cls.source.split('\n  compare-unsigned-receipts:\n', 1)

    def test_workflow_remains_manual_only(self):
        self.assertRegex(self.source, r'(?m)^on:\n  workflow_dispatch:\n')
        self.assertNotRegex(self.source, r'(?m)^  (?:push|pull_request|pull_request_target|schedule|workflow_run):')
        self.assertIn('default: ubuntu-latest', self.quality)

    def test_all_choice_has_three_correct_native_runners(self):
        choices = self.quality.split('        options:\n', 1)[1].split('      full_linux_gate:', 1)[0]
        for runner in ('ubuntu-latest', 'windows-latest', 'macos-latest', 'all'):
            self.assertIn('          - ' + runner + '\n', choices)
        self.assertIn("inputs.runner_os == 'all'", self.quality)
        self.assertIn('fromJSON(', self.quality)
        self.assertIn("format('[\"{0}\"]', inputs.runner_os)", self.quality)
        self.assertIn('runs-on: ${{ matrix.runner }}', self.quality)
        self.assertIn('fail-fast: false', self.quality)

    def test_actual_host_and_exact_sha_required_in_every_native_job(self):
        required = ('verify_runner_platform.py --expected "${{ matrix.runner }}"',
                    'python -B -m unittest discover -s tests -p',
                    'python scripts/platform_acceptance.py --expected "${{ matrix.runner }}"',
                    '--require-sha "${{ github.sha }}"',
                    'verify_receipt_matrix.py --require-sha "${{ github.sha }}" --local dist',
                    "matrix.runner == 'ubuntu-latest'")
        for fragment in required:
            self.assertIn(fragment, self.quality)

    def test_one_host_skips_metadata_aggregation(self):
        self.assertRegex(self.review, r"(?m)^    if: \$\{\{ inputs.runner_os == 'all' \}\}$")
        self.assertIn('    needs: quality\n', self.review)
        self.assertIn('    runs-on: ubuntu-latest\n', self.review)

    def test_only_unsigned_metadata_is_uploaded(self):
        uploaded = self.quality.split('      - name: Preserve unsigned acceptance evidence', 1)[1]
        self.assertEqual(uploaded.count('dist/platform-receipt.json'), 1)
        self.assertEqual(uploaded.count('dist/SHA256SUMS'), 1)
        self.assertNotIn('dist/*.zip', uploaded)
        self.assertNotIn('dist/*.tar.gz', uploaded)
        self.assertIn('if-no-files-found: error', uploaded)
        self.assertIn('sudoku-evidence-${{ matrix.runner }}-${{ github.sha }}-attempt-${{ github.run_attempt }}', uploaded)

    def test_review_is_scoped_to_this_exact_run_and_attempt(self):
        self.assertIn('  actions: read', self.source)
        self.assertIn('  contents: read', self.source)
        self.assertIn('GH_TOKEN: ${{ github.token }}', self.review)
        self.assertIn('EVIDENCE_SHA: ${{ github.sha }}', self.review)
        self.assertIn('EVIDENCE_ATTEMPT: ${{ github.run_attempt }}', self.review)
        self.assertIn('gh run download "$GITHUB_RUN_ID" --repo "$GITHUB_REPOSITORY"', self.review)
        self.assertIn('"sudoku-evidence-${runner}-${EVIDENCE_SHA}-attempt-${EVIDENCE_ATTEMPT}"', self.review)

    def test_review_cannot_claim_artifact_acceptance(self):
        self.assertIn('--metadata-only', self.review)
        self.assertIn('--linux evidence/ubuntu-latest', self.review)
        self.assertIn('--windows evidence/windows-latest', self.review)
        self.assertIn('--macos evidence/macos-latest', self.review)
        self.assertIn('NOT release certification', self.review)
        for command in ('gh release create', 'gh pr merge', 'dist/*.zip', 'dist/*.tar.gz'):
            self.assertNotIn(command, self.review)


if __name__ == '__main__':
    unittest.main()
