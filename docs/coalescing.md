# Coalescing State

Status: Active — governed by [DOM-14] in
`docs/specs/01-development-documentation-operating-model.md` (adopted
from agent-guidance @ `2f7eff6` via
`docs/plans/2026-07-14-agent-guidance-propagation-plan.md`).

Owner: any agent that observes a tripped threshold at session start.
Boundary: lessons, plans, and skill/runbook promotion. Specs and
implementation docs are living documents and are never coalesced. The
Golden Rules and the 2026-07-01 four-way bake-off section are
importance-floored and exemplar-class (the ecosystem's
incident-of-record): never fold candidates. Verification: the run log
plus the mandatory zero-warning self-corpus gate. Required action: the
session-start check is **read-only**; all writes happen only inside an
authorized maintenance task (`skills/coalescing/SKILL.md`).

**Local format adaptation:** this ledger uses dated H2 sections, not
dated bullets. Derivation command:
`grep -cE '^## (20[0-9]{2}-|.*\(20[0-9]{2}-[0-9]{2}-[0-9]{2}\)$)' docs/lessons.md` (both dated-H2 shapes: leading-date and trailing-parenthesized-date; repaired 2026-07-28 — the prior leading-date-only command counted 1 of 22 real sections) (sections after the
watermark date).

**Fold unit and progress model (per [DOM-14]):** the lessons ledger is a
single flat chronological ledger, not a domain-grouped one — its fold
unit is the dated H2 section counted repo-wide, and the count includes
only cold, unfolded sections (past the lessons watermark date and outside
the age floor). Because it is folded strictly in date order rather than
by theme-cluster across dates, its progress model is the **date
watermark** in the Watermarks table (a date cursor is correct here: no
unfolded material sits behind the watermark). The plans and promotion
tiers likewise fold repo-wide, tracked by the `Distilled through` /
`Checked through` watermarks below. Should any tier later split into
domain-grouped ledgers, switch that tier to per-section watermarks or a
fold-records index and re-declare it here.

## Thresholds

| Tier | Trigger (derived count) | Threshold | Age floor |
|------|------------------------|-----------|-----------|
| Lessons | dated H2 sections after the lessons watermark | 5 | 30 days, never sections cited by an active plan, never the exemplar sections above |
| Plans | plans with status completed/superseded, not `exemplar`, and no retired-ledger line | 8 | none — harvest gate and two-step retirement are the guards |
| Promotion | distinct citations of the same workflow theme since the promotion watermark | 3 | n/a |

## Watermarks

| Tier | Distilled through | Source SHA |
|------|-------------------|------------|
| Lessons | (none — first sweep below) | — |
| Plans | (none — first sweep pending) | — |
| Promotion | (none) | — |

## Deferral State

| Tier | Checked through (date, SHA) | Counts at check | Reason deferred | Reconsider when |
|------|------------------------------|-----------------|-----------------|-----------------|
| Lessons | 2026-07-14, `9ddb4d6` | 1 dated section past (no) watermark — under threshold 5; also within age floor and exemplar-class | Not tripped; nothing foldable | Count changes or a section ages past 30 days without exemplar status |
| Plans | 2026-07-14, first sweep | not derived | Plan statuses live in `## Related Plans` tags (implementing/implemented), not a status index; first real sweep derives from those | A sweep is authorized with plans in scope |
| Promotion | 2026-07-14, first sweep | not derived | Derive at a future sweep | — |

## Run Log

| Date | Tier(s) | Source SHA | Claim |
|------|---------|------------|-------|
| 2026-07-17 | — (propagation; nothing folded) | source agent-guidance @ `b248e1c`; landed `2a6cc20` | Delta wave per `docs/plans/2026-07-17-agent-guidance-delta-wave-propagation-plan.md`: [DOM-14] fold-unit trigger bullet + this file's fold-unit declaration; six coalescing-skill refinements; interface-review skill; writing-plans and review-loops wave content; call-agent brief standard. Scoped review no blocker, zero findings. Self-corpus gate 0/0/0 pre and post. Reviewer flagged (owner items, pre-existing): the lessons-derivation regex undercounts `## Title (YYYY-MM-DD)` headings; one index row carries a transient-state status. No thresholds, watermarks, or folds touched. |
| 2026-07-14 | all | `9ddb4d6` (checked-deferred; nothing folded) | Layer adopted from agent-guidance `2f7eff6`; first sweep ran in the same unit per the sweep-after-propagation rule. Lessons: 1 dated section (the 2026-07-01 bake-off), under threshold, within age floor, and exemplar-class — nothing foldable. No watermark advanced. Self-corpus gate 0/0/0. |
