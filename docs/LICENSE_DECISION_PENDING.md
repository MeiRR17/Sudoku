# License decision — awaiting repository owner approval

**Decision state: OPEN / NOT APPROVED (2026-11-09).** No `LICENSE` file should be added based on an assistant assumption. Public GitHub visibility **does not** automatically grant a right to use, modify or redistribute the code.

The owner must confirm that all code, tests, sample fixtures and other content can be licensed, identify any third-party components or borrowed datasets that require notices, and explicitly select the intended terms. Choices worth considering include a permissive license (MIT / Apache-2.0), a copyleft license (GPL-3.0-or-later) or keeping the code all-rights-reserved. **These are options, not recommendations adopted on the owner's behalf.**

Until the decision is recorded:

- Do not publish an official release or attach downloadable binary artifacts to a public GitHub Release.
- Do not declare an SPDX license ID in package metadata or package manifests.
- Keep technical development and private local testing separate from public distribution.
- Issue #10 (`v0.8.0`) stays OPEN; subsequent release candidate/production authorization cannot treat packaging as complete.

Once approved, add the exact chosen `LICENSE`, a notices/dependency review if needed, and an auditable decision record in the next approved commit before public release.
