# Native Windows Support Exploration (2026-09-14)

**Status:** deferred exploration; no implementation scheduled

**Class:** 3 for exploration. Any implementation that changes the POSIX-only
contract is Class 5 and requires its own reviewed spec delta.

**Plan type:** exploration. This document does not change the active specs or
select a native filesystem design.

## Goal and Scope

Determine the smallest correct way to support the Backstitch workflows the
owner needs on Windows. The owner values Windows testing for the portability
defects it can reveal, but has no local Windows runner. All real Windows
execution must therefore occur in CI.

This is separate from
`docs/plans/2026-09-14-review-findings-remediation-plan.md`, whose slice 5
corrects the current platform claim. Nothing in that remediation waits for
this exploration. Revisit when the owner prioritizes native Windows use or
testing; there is no time-based deadline or assumed external-adopter threshold.

## Sources and Baseline

- `docs/program-theory.md`: a repository reader whose evidence must be sound.
- `docs/agent-context/README.md`, `docs/agent-context/decision-hierarchy.md`,
  `docs/agent-context/principles.md`,
  `docs/agent-context/engineering-principles.md`,
  `docs/agent-context/lessons.md`, and `docs/lessons.md`.
- `docs/agent-context/runbooks/writing-plans.md` and
  `docs/agent-context/runbooks/hardening-plans.md`.
- `docs/specs/02-backstitch-core.md` [SC-5], [SC-10], [SC-17].
- `docs/specs/03-backstitch-configuration.md` [CFG-5.1].
- `docs/specs/06-semantic-gates.md` [SEM-4], [SEM-7].
- `docs/specs/07-verification-and-evidence-cases.md` [EVC-8.2].
- Baseline at authoring: `7d1bb154665e7fca1d8cf2c16d5fd62a0e9cd2db`.
  Refresh it when exploration resumes; the seven-slice remediation may have
  changed the relevant publication and support text.

## Context and Open Questions

The prior remediation draft called this a snapshot backend change. The actual
boundary includes configuration reads, inventory, publication, and cache I/O:

| Owner | Question to resolve with code and real Windows evidence |
|---|---|
| `backstitch/filesystem_io.py`, `backstitch/settings.py` | How can bootstrap/config reads prove stable regular-file identity without traversing a symlink, junction, or other reparse point? |
| `backstitch/repository_snapshot.py` | What native observations prove directory membership, containment, file identity, and metadata change across a whole capture? Define file attributes, case aliases, Unicode normalization collisions, and native absolute paths before choosing an API. |
| `backstitch/artifact_publication.py` | Which atomic replacement and durability guarantees hold, including directory syncing and open destinations? |
| `backstitch/semantic_cache.py` | Do actual hard-link publication, process locking, cleanup, and no-replace races satisfy [SEM-4]? A Windows branch in the code is not end-to-end proof. |
| `tests/`, `.github/workflows/ci.yml` | Which fixtures rely on POSIX permissions or symlinks? Which hash differences reflect checkout line endings? Existing dependency-only jobs do not exercise Backstitch. |

Also settle the intended workflows before promising support for every command.
A native handle layer could preserve strong containment, but it has real
maintenance and CI debugging costs. A simpler algorithm is acceptable only
with an explicit, reviewed account of the guarantees it provides. Do not
silently weaken the existing immutable-capture boundary to make a prototype
pass.

## Exploration Tasks

- [ ] Identify the Windows workflows that provide current value and compare
  that value with the cost of adding and maintaining support.
- [ ] Inspect the owners above and map the actual platform assumptions. Reuse
  existing contracts and test fixtures wherever they apply.
- [ ] Prototype only the uncertain native operations in isolation. Use a real
  hosted Windows runner; keep experiment code out of the shipping path.
- [ ] Exercise root/intermediate/final link or reparse behavior, directory and
  file replacement during capture, stable unreadable inputs, and publication
  and cache operations. Record the observed limits of the candidate approach.
- [ ] Decide whether to implement, narrow the feature, or defer. If proceeding,
  produce a separate implementation plan with exact proposed spec changes,
  code ownership, necessary tests, CI scope, and rollout/rollback behavior.

## Invariants and Testing

Keep one repository snapshot model and one whole-capture/retry lifecycle.
Reuse stable-read and publication owners instead of introducing parallel
orchestration. Preserve POSIX behavior. No new dependency is assumed.

Windows evidence must run on Windows. A mocked platform selector does not
prove native filesystem behavior. Tests should cover observable correctness,
not ctypes declarations or specific API call sequences. Choose Python and
architecture coverage based on the implementation's actual compatibility
boundaries; no new matrix is prescribed by this exploration plan.

Consider line-ending conversion and case-insensitive filesystems explicitly.
Do not normalize away byte differences when exact source bytes are the
contract, or refresh expected hashes merely to accept a different checkout.

## Review, Verification, and Handoff

Review the exploration outcome for both correctness and simplification. An
implementable result names the native guarantees and their real CI evidence;
a deferred result names the unresolved question or product tradeoff.

No production behavior or spec text changes in this exploration, so rollback
is removal of isolated experiment files and any experiment-only CI wiring.
This document adds no release gate. Closing exploration updates its index row;
any eventual implementation is tracked separately and does not reopen the
completed remediation plan.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|

## Review Record

Independent correctness/YAGNI review passed on 2026-09-14. The reviewer
confirmed that the exploration preserves the active contract, captures the
cross-owner Windows questions, and prescribes no backend, deadline, or matrix.
Documentation and self-corpus checks passed with the companion remediation
plan. No Windows experiment has run.
