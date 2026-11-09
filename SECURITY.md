# Security Policy — experimental Sudoku CLI

## Supported versions

There is **no production-supported release** yet. The latest development branch is `master`; older experimental versions receive no guaranteed security fixes. Do not deploy this program in a security-sensitive workflow or expose it directly to untrusted network requests.

## Scope and limits

The software works offline. Its main adversarial inputs are puzzle text from `--file`, stdin or `--puzzle`, destination file paths supplied to `--output`, and unsupported flags. Parsing rejects invalid bytes and >1 MiB input. `--output` uses an exclusive-create operation to refuse overwriting existing paths; it is **not** an atomic crash-safe commit. There is no built-in network service, authentication or account data.

The exact solver can consume CPU on pathological valid puzzles. The number of recursive placements is bounded by the 81 cells, but the search tree can still be exponential. A strict CPU-time or node budget has not yet been implemented. Do not process untrusted requests in an unbounded shared service.

## Report a vulnerability

Avoid publishing an exploit, secrets, or a sensitive crashing input in a public issue. Use [GitHub private vulnerability reporting](https://github.com/MeiRR17/Sudoku/security/advisories/new) when available; if the private reporting interface is unavailable, request a secure contact channel through the repository owner without sharing technical exploit details publicly. Include minimal steps, affected commit, platform/compiler, any sanitizer stack trace and impact. No response SLA is offered for this experimental project.

Do not interpret the public repository as a license grant. See [ROADMAP.md](ROADMAP.md).
