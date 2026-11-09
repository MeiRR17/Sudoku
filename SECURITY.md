# Security Policy — experimental Sudoku CLI

## Supported versions

There is **no production-supported release** yet. The latest development branch is `master`; older experimental versions receive no guaranteed security fixes. Do not deploy this program in a security-sensitive workflow or expose it directly to untrusted network requests.

## Scope and limits

The software works offline. Its main adversarial inputs are puzzle text from `--file`, stdin or `--puzzle`, destination file paths supplied to `--output`, and unsupported flags. Parsing rejects invalid bytes and >1 MiB input. `--output` uses an exclusive-create operation to refuse overwriting existing paths; it is **not** an atomic crash-safe commit. There is no built-in network service, authentication or account data.

### Local gameplay save files (v0.7.0)

`SUDOKU_SAVE_V1` is a strictly bounded (1 KiB), checksummed, plain ASCII format. It is **not encrypted or authenticated**, and a deliberately modified save with a recomputed checksum is not protected against tampering. Use trusted storage paths. Saved state is written to an exclusively created temporary file in the same directory and atomically replaced after a successful write/flush/fsync; this does not guarantee persistence over power loss without a parent-directory fsync. Orphaned temporary files may remain after abrupt termination. Importing a corrupt save does not mutate a running game; no automatic recovery from arbitrary temp files occurs. Windows/macOS native save behavior remains unverified and is tracked for the packaging release.

The exact solver can consume CPU on pathological valid puzzles. The number of recursive placements is bounded by the 81 cells, but the search tree can still be exponential. A strict CPU-time or node budget has not yet been implemented. Do not process untrusted requests in an unbounded shared service.

## Report a vulnerability

Avoid publishing an exploit, secrets, or a sensitive crashing input in a public issue. Use [GitHub private vulnerability reporting](https://github.com/MeiRR17/Sudoku/security/advisories/new) when available; if the private reporting interface is unavailable, request a secure contact channel through the repository owner without sharing technical exploit details publicly. Include minimal steps, affected commit, platform/compiler, any sanitizer stack trace and impact. No response SLA is offered for this experimental project.

Do not interpret the public repository as a license grant. See [ROADMAP.md](ROADMAP.md).


## v0.8.3 save durability boundary

On POSIX the game now requests an `fsync` of the parent directory after replacing a save. If that operation fails, it reports a distinct **durability uncertainty warning**: a new target may be present, but survival across power loss is unverified. The checksum is for accidental corruption only, **not authenticity**. Native Windows/macOS save behavior and hardware-level crash recovery remain unverified and are release blockers. Never treat a warning as a guarantee that the prior save was preserved.
