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
| Lessons | 2026-08-08, `bd4a8cd` | 22 dated H2 sections (repaired derivation, both shapes; the prior 2026-07-14 row's count of 1 was the broken leading-date-only command). Cold subset past the 30-day age floor: 5 (dated ≤ 2026-07-09), of which 1 is the exemplar bake-off — 4 eligible, under threshold 5 | Not tripped: eligible cold count 4 < 5 | A section dated 2026-07-10..07-16 crosses the 30-day floor (from 2026-08-09 onward the eligible count rises fast — recount at next session start) |
| Plans | 2026-08-08, `bd4a8cd` | 21 index rows / 42 plan files → **21 unindexed** (reportable); harvest candidates (completed/superseded, not exemplar, no retired-ledger line): **8 = threshold 8, tripped** | Deferred: tripped at exactly threshold inside a propagation-wave unit; several completed rows carry free-prose status suffixes that need normalization to the closed vocabulary before a harvest gate can run cleanly; folding under wave pressure destroys evidence. Index backfill (21 rows) is bulk-session work, never propagation work (hub propagate-guidance step 4) | An authorized dedicated sweep/index-reconciliation session; or the candidate count rises above 8 |
| Promotion | 2026-08-08, `bd4a8cd` | not derived | Same wave-unit reason; no fold-up rows exist yet in this file | An authorized dedicated sweep |

## Run Log

| Date | Tier(s) | Source SHA | Claim |
|------|---------|------------|-------|
| 2026-08-08 | — (propagation + checked-deferred sweep; nothing folded) | source agent-theory @ `ec716e8`; landed `bd4a8cd` | Delta wave per `docs/plans/2026-08-08-agent-theory-delta-wave-propagation-plan.md` (28-payload checklist): program/module-theory startup machinery, [DOM-5] carve-out, [DOM-14] archive rule, [DOM-15] amendments, runbook wave, primer as `docs/specs/09-agent-theory-and-program-theory.md` (meta via `[SUP-AT-PRIMER-META]`), crystallize skill, gate improvements (shallow skip, rigorous fence parser, declared-future-artifact allowlist + self-test — closes the pre-existing red `check-doc-paths`), doc-gates CI job. Scoped review LAND-WITH-EDITS, A-01..A-07 applied (one recorded deviation, plan §review round). First-sweep-after-propagation ran checked-deferred: lessons 22 sections (4 eligible < 5), plans 8 harvest candidates = threshold (deferred, wave unit + free-prose status rows), 21 unindexed reported, promotion not derived — deferral rows above. All gates green incl. self-corpus 0/0/0. No thresholds, watermarks, or folds touched. |
| 2026-07-28 | — (gate correction; nothing folded) | — | **`coalesce-check` no longer probes the filesystem for sibling repositories** (corrected upstream in agent-theory and propagated). The old `SIBLING_ROOT = REPO_ROOT.parent` hardcoded a checkout layout no document declared, and reported SHAs resolvable only in a neighbouring working copy as *verified* — laundering a local-only claim into a green check, defeating the cue-portability rule the tool enforces. Now: own SHAs verified locally and against this repo's published remote; unresolvable SHAs reported as **foreign claims** naming the repository they cite (informational, never a verdict); an unresolvable SHA naming no repository is a genuine failure. `COALESCE_SIBLING_ROOT` is opt-in local convenience, off by default. |
| 2026-07-28 | — (upstream rename; nothing folded) | — | The guidance hub was renamed `agent-guidance` → `agent-theory` (it names a discipline — theory-building for agent-assisted development — not an artifact of instructions). `bin/coalesce-check`'s sibling list was repointed so hub SHA claims resolve again. Existing provenance lines, run-log rows, and plan filenames naming `agent-guidance` refer to that same upstream repository under its former name and are left as written; git commit messages likewise retain it. |
| 2026-07-28 | — (propagation + repair; nothing folded) | source agent-guidance @ `e42762c`; landed `78a6e83` | Delta wave per `docs/plans/2026-07-28-agent-guidance-delta-wave-propagation-plan.md`: coalescing-skill amendments, status-vocabulary bullet, harness scoping sentence, both executable gates adapted. Repair-in-sweep applied at landing: declared lessons-derivation command repaired (counted 1 of 22 dated sections; now both H2 shapes) — closing the 2026-07-17 reviewer's owner item — with state-file authority restored in the tool docstring. First coalesce-check run: 22 sections; local-only pins `9ddb4d6`, `2a6cc20`. Scoped review no blocker. No thresholds, watermarks, or folds touched. |
| 2026-07-17 | — (propagation; nothing folded) | source agent-guidance @ `b248e1c`; landed `2a6cc20` | Delta wave per `docs/plans/2026-07-17-agent-guidance-delta-wave-propagation-plan.md`: [DOM-14] fold-unit trigger bullet + this file's fold-unit declaration; six coalescing-skill refinements; interface-review skill; writing-plans and review-loops wave content; call-agent brief standard. Scoped review no blocker, zero findings. Self-corpus gate 0/0/0 pre and post. Reviewer flagged (owner items, pre-existing): the lessons-derivation regex undercounts `## Title (YYYY-MM-DD)` headings; one index row carries a transient-state status. No thresholds, watermarks, or folds touched. |
| 2026-07-14 | all | `9ddb4d6` (checked-deferred; nothing folded) | Layer adopted from agent-guidance `2f7eff6`; first sweep ran in the same unit per the sweep-after-propagation rule. Lessons: 1 dated section (the 2026-07-01 bake-off), under threshold, within age floor, and exemplar-class — nothing foldable. No watermark advanced. Self-corpus gate 0/0/0. |
