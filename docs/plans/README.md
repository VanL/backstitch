# Plans

This directory contains dated implementation plans.

## Rules

- Use plans for non-trivial changes, architectural work, or any change where a
  zero-context engineer would otherwise need to rediscover the approach.
- Prefer filenames like `YYYY-MM-DD-short-name-plan.md`.
- Plans should cite exact spec sections when they exist.
- Plans should stay current enough to reflect what is being implemented.
- Completed plans should retain their verification and review notes as history.
- Prefer over-prescriptive plans on risky work: invariants, hidden couplings,
  rollback, rollout, and anti-mocking guidance should be explicit.
- Do not start risky implementation work until the hardening checklist is
  satisfied and the rollback or sequencing story is written clearly enough to
  survive review.

## Standard

Every plan should include:

- goal
- source documents
- context and key files
- invariants and constraints
- dependency-ordered tasks
- testing plan
- verification and gates
- independent review loop
- out of scope
- fresh-eyes review

For risky changes, also include the plan-hardening material documented in:

- `docs/agent-context/runbooks/hardening-plans.md`

Risky plans are blocked if they do not make explicit:

- what must not change
- enough current-structure context to find the right edit point
- what must stay real in tests
- rollback or rollout sequencing when compatibility depends on it

## Status Index

| Plan | Status |
|------|--------|
| 2026-08-08-agent-theory-delta-wave-propagation-plan.md | active — landing the hub delta `e42762c..ec716e8` (source `ec716e8`) |
| 2026-08-08-program-theory-crystallization-plan.md | completed |
| 2026-07-11-deterministic-semantic-gate-plan.md | active |
| 2026-07-14-agent-guidance-propagation-plan.md | active |
| 2026-07-15-agent-interfaces-runbook-adoption-plan.md | completed — runbook adopted from agent-guidance @ a4b4345 |
| 2026-07-15-agent-guided-evidence-cases-plan.md | implemented, uncommitted — report-only; current bootstrap/discovery, semantic-policy, and performance qualification remain explicitly unavailable |
| 2026-07-16-evidence-spike-hardening-plan.md | slices 0-6 implemented, review-confirmed; Slice 7 (post-review residuals) added 2026-07-17, scoped outside review PASS — cleared for implementation |
| 2026-07-17-agent-guidance-delta-wave-propagation-plan.md | active — landing the hub delta `a4b4345..b248e1c` (source `b248e1c`) |
| 2026-07-27-semantic-analysis-lifecycle-plan.md | same-model and Claude plan reviews PASS; Slices 1-4 implemented and final review PASS; landing gate pending an owner-authorized commit |
| 2026-07-27-canonical-config-resolution-plan.md | implemented and verified; Claude implementation findings addressed; uncommitted pending landing authorization |
| 2026-07-27-serial-benchmark-lane-plan.md | completed — normal xdist and serial benchmark lanes split; independent completed-work review PASS |
| 2026-07-28-stable-wall-clock-benchmark-plan.md | completed — sampled median reporting, qualified relative limits, and always-on catastrophic ceilings; independent rereview PASS |
| 2026-07-28-documented-suppression-governance-plan.md | implemented and independently reviewed |
| 2026-07-28-configured-default-command-plan.md | implemented and verified; final independent review PASS; included in the owner-authorized landing commit |
| 2026-07-28-evidence-stable-semantic-result-reuse-plan.md | implemented and verified; final independent review PASS; included in the owner-authorized landing commit |
| 2026-07-28-intent-coverage-implementation-plan.md | deterministic report, Git ratchet, stale-history, and closed-report slices implemented and reviewed; semantic mapping-quality qualification and rollout gates remain open |
| 2026-07-28-agent-guidance-delta-wave-propagation-plan.md | active — landing the hub delta `b248e1c..e42762c` (source `e42762c`) |
| 2026-07-29-architecture-quality-remediation-plan.md | completed — implementation, verification, independent review, and owner-authorized landing |
| 2026-07-29-usability-remediation-plan.md | completed — implementation, exact-state dogfood, independent review, and owner-authorized landing |
| 2026-08-04-semantic-preparation-performance-plan.md | completed — implementation, verification, and final independent review PASS |
| 2026-08-05-ruff-complexity-and-suppression-registry-plan.md | completed — C901/10 active; 43 temporary groups retired; verification and independent review PASS |

(Existing plans carry status via each spec's `## Related Plans` tags;
rows are added here as plans open or the coalescing sweep needs them.)

## Retired Plans

One line per retired plan; the body lives in git at the source SHA.

| Plan | Dates | Outcome | Absorbed into | Source SHA |
|------|-------|---------|---------------|------------|
