# Agent-Guidance Delta Wave Propagation (2026-07-28)

Status: active

Class: 3+P — runbook, skill, entry-point, and tooling adoption that
governs how future changes here are planned and how the coalescing layer
derives its counts. No spec text lands, so this is 3, not 5. +P: an
independent scoped adaptation review is owed (dispositions in §7); this
worker operates under a no-subagent fence, so the review is left as an
owner-run task, not waived.

## 1. Goal

Adopt the agent-guidance hub delta between backstitch's last pin (hub
`b248e1c`, the 2026-07-17 wave) and hub `e42762c`. Four payloads: the
coalescing skill's four amendments, the closed status-vocabulary bullet
in `writing-plans.md`, the harness-scoping sentence in `AGENTS.md`, and
two new executable gates in `bin/`.

## 2. Source and Pins

- Source SHA (pin): agent-guidance `e42762c`.
- Backstitch prior pin: `b248e1c` (2026-07-17 wave, via
  `docs/plans/2026-07-17-agent-guidance-delta-wave-propagation-plan.md`).
- Delta = `b248e1c..e42762c` (four hub commits: `38e3868`, `976bd35`
  (relicense — not propagable), `51626db`, `e42762c`).
- Every payload was extracted from the pinned END-STATE
  (`git -C <agent-guidance> show e42762c:<path>`), never from an
  intermediate commit's diff. The hub commit that authored each payload
  is recorded below as provenance only.

## 3. Payload Checklist

| # | Payload | Hub commit | Target | Grep marker |
|---|---------|-----------|--------|-------------|
| 1a | Coalescing skill — Purpose line gains surface repair | `e42762c` | `skills/coalescing/SKILL.md` | `repair defects in the` |
| 1b | Coalescing skill — repair-in-sweep block, step 1 | `e42762c` (fold-up from taut `3706d73`) | same | `Inspect and repair the coalescing surfaces first` |
| 1c | Coalescing skill — structured-index derivation clause | `e42762c` | same | `structured and gated` |
| 1d | Coalescing skill — cue-portability paragraph, step 2 | `51626db` | same | `Cue portability` |
| 2 | writing-plans — closed status vocabulary bullet | `e42762c` | `docs/agent-context/runbooks/writing-plans.md` | `The status vocabulary is closed` |
| 3 | AGENTS.md — harness scoping sentence after the two overrides | `38e3868` | `AGENTS.md` | `Harness-enforced controls are outside the hierarchy` |
| 4a | New gate `bin/check-doc-paths` (adapted) | `51626db` | `bin/check-doc-paths` | `check-doc-paths: OK` |
| 4b | New gate `bin/coalesce-check` (adapted) | `51626db` | `bin/coalesce-check` | `lessons dated H2 sections` |
| 4c | Registration of both gates | — (local) | `docs/implementation/02-repository-map.md` | `bin/coalesce-check` |

## 4. Adaptations (per-payload)

| Payload | Divergence | Adaptation |
|---------|-----------|------------|
| 1a–1d | This repo's coalescing skill is a localized copy: local `Status:` provenance line (adopted @ `2f7eff6`), a local flat-ledger note under the fold-unit paragraph, and locally reflowed decay text | All four amendments integrated at their heading/paragraph anchors; every local adaptation preserved byte-for-byte. No clobber, no reflow of untouched text. |
| 1c | This repo's plan index is free text, not a closed-vocabulary gated index | The clause is conditional ("Where the repo's index is structured and gated"), so it lands verbatim without asserting a gate this repo does not have. It reads forward: the preference is stated, the migration is owed at next touch (§8). |
| 2 | This repo's Plan Lifecycle list has no blank lines between bullets; the hub paragraph carries a ragged line break mid-sentence | Bullet lands first in the list (matching hub order, before the mutability-boundary bullet), reflowed to this file's wrap width with no wording change. Foreign lineage (taut `3706d73`, mm's backfill campaign) quoted by name and commit, as the hub states it. |
| 3 | This repo's AGENTS.md keeps the two overrides under `## Shared Agent Context`, not a separate permissions heading | Sentence inserted immediately after the attribution override, so "the two overrides above" resolves correctly in this layout. `AGENTS.md` is shared-dirty: localized additive insert only, region in §6. |
| 4a | Hub scan surfaces do not match this layout, and this repo has no bootstrap script | `SCAN_DIRS` gains `docs/implementation` (the repository map lives there and is nearly all path claims); the claim pattern gains this repo's `backstitch/` and `tests/` trees; the hub's `--scaffold` mode is dropped (backstitch is a consumer, not the hub — there is nothing to bootstrap). |
| 4b | **Lessons derivation.** This repo's ledger uses dated H2 sections in two shapes — `## 2026-07-01: …` (1 section) and `## Title (2026-07-03)` (21 sections). The command declared in `docs/coalescing.md` matches only the first and reports 1 where the true count is 22; the 2026-07-17 wave review flagged this as a pre-existing owner item | The tool counts both shapes and reports the split (`22 (1 leading-date, 21 trailing-date)`). Its docstring names the discrepancy and states that where tool and declared command disagree the tool is the authority, per the skill's Maintenance Notes (an executable `coalesce-check` replaces step 1's manual derivation). This closes the reviewer-noted undercount mechanically. Rewriting the declared command in `docs/coalescing.md` is an owner item, deliberately not done here (§8). |

Scoped review (grok, read-only, 2026-07-28, §4a-form): **no blocker**.
O1 confirmed the declared-derivation undercount (1 of 22); the landing
applied the repair-in-sweep reconciliation — declared command repaired
to both dated-H2 shapes in `docs/coalescing.md`, and the tool docstring
restored to state-file authority ("the file wins and the script is the
defect"), resolving the cross-consumer authority inconsistency vs
weft's adaptation. O3: SIBLINGS matches the hub back-port `cec5666`.
O4 (uv cache sandbox quirk) is environmental, not a wave defect.
| 4b | This repo's cues cite the guidance hub, not only consumer siblings | `SIBLINGS` leads with `agent-guidance`; cue-path resolution now runs `git cat-file` in the repo where the SHA actually resolved, instead of assuming local. Without this, every hub pin in `docs/coalescing.md` would read as broken. |
| 4c | Root Entry Points is the right home, and it is inside a dirty hunk | Two additive rows appended after the `bin/release.py` row; nothing reflowed. Region and landing recipe in §6. |

## 5. Invariants and Fences

- **No git writes.** This worker edits the working tree only. Staging,
  commit, and any state-file pin are the owner's; they appear here as
  instructions, never as claims about the tree.
- **Touch nothing foreign.** Heavy concurrent WIP is live (semantic
  analysis lifecycle, configured default command, evidence-stable result
  reuse: 39 modified tracked files). Three dirty files this wave must
  touch — `AGENTS.md`, `docs/implementation/02-repository-map.md`,
  `docs/plans/README.md` — receive localized additive inserts only, with
  exact regions reported in §6. All other dirty files are foreign and
  untouched.
- **Mandatory gate:** `uv run backstitch check --repo-root .` no worse
  than the pre-change baseline; §6 records both runs.
- Pre-existing defects found by the new gates are reported, not fixed: a
  propagation never repairs a receiving repo's baselined failures.
- To land: stage by explicit path list (the eight payload targets plus
  this plan and its index row), never `git add -A`; for the three
  shared-dirty files build synthetic HEAD+mine blobs so foreign WIP stays
  uncommitted.

## 6. Verification and Gates

- Baseline `uv run backstitch check --repo-root .` (pre-change):
  121 spec sections, 296 mappings, 376 code refs, 794 edges, 8
  invariants, 16 binds; **0 errors, 0 warnings, 0 infos**.
- Post-change `uv run backstitch check --repo-root .`: recorded in the
  handoff report; the gate requirement is no-worse-than baseline.
- New gates, first run in this repo:
  - `bin/coalesce-check` — exit 0. 4 SHA claims (2 verified in
    siblings), 0 retrieval cues, lessons dated H2 sections: 22 (1
    leading-date, 21 trailing-date). Two **local-only pins** reported
    (`9ddb4d6`, `2a6cc20`): real, informational, owner's call.
  - `bin/check-doc-paths` — exit 1 on 9 pre-existing dangling path
    claims (§8). Not fixed here.
- Completeness: one grep per §3 marker over the target files.
- Localized-insert regions (shared-dirty files):
  - `AGENTS.md` — `## Shared Agent Context`, one 5-line bullet inserted
    after the attribution override (approx. line 28). Their WIP is in
    Definition of Done (approx. line 96): no hunk overlap.
  - `docs/implementation/02-repository-map.md` — `## Root Entry Points`,
    two rows after the `bin/release.py` row (approx. line 13). Their WIP
    modifies the `pyproject.toml` row two lines above, so at default
    context these rows share one hunk: build a synthetic blob for this
    file rather than relying on `git add -p` to split it.
  - `docs/plans/README.md` — `## Status Index`, one row appended at the
    table end (approx. line 62). Their WIP appends three rows immediately
    above: same hunk, same synthetic-blob recipe.

## 7. Independent Review Loop (dispositions)

Scope fence for the reviewer: the source content is already hub-reviewed;
review ONLY the adaptation — anchor placement, the two tool adaptations
(scan surfaces, claim pattern, lessons derivation, sibling resolution),
the conditional structured-index clause landing in a repo with a
free-text index, the localized additive inserts into the three dirty
files, and any performative additions. Use the §4a scoped-change prompt
in `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`.

| ID | Finding | Disposition |
|----|---------|-------------|
| — | (No review run this wave — no-subagent fence; owner-run task) | Open |

## 8. Out of Scope

- **The `docs/coalescing.md` declared derivation command.** It still
  reads `grep -cE '^## 20[0-9]{2}-'` and still undercounts (1 vs 22).
  `bin/coalesce-check` now derives the true count and its docstring
  records the discrepancy; rewriting the state file's command is an owner
  item, flagged since the 2026-07-17 wave.
- **The flagged `implemented, uncommitted` index row**
  (`2026-07-15-agent-guided-evidence-cases-plan.md`) and the other
  free-text ambiguity phrases in the Status Index. Payload 2's rule is
  forward-looking: they migrate to `status-review` at next touch, by
  whoever next touches them. This worker does not edit foreign WIP rows.
- **The nine dangling path claims** `bin/check-doc-paths` found, all
  pre-existing:
  - four dead `## Related Plans` backlinks in
    `docs/specs/01-development-documentation-operating-model.md`
    (lines 460–463) to deleted 2026-04-07 plans — these are exactly the
    harvest gate's backlink-conversion item, owed by a coalescing sweep,
    not by a propagation;
  - `tests/performance/wall-clock-runner-contract.json` and
    `tests/performance/wall-clock-baseline.json`, claimed as present in
    `docs/specs/02-backstitch-core.md` and
    `docs/implementation/05-release-publishing.md` but not in the tree
    (operator-generated); and
    `tests/performance/runner-contract.json` in
    `docs/specs/07-verification-and-evidence-cases.md`, which looks like
    the superseded name of the first. Owner decides whether these become
    real files or non-claim prose.
- **Registering `bin/check-dom15-fixtures`** in the repository map — a
  pre-existing registry gap, noticed while adding the two new rows.
- **A coalescing sweep.** Deferred: heavy concurrent WIP is live, and the
  skill's own concurrent-session guidance says to coalesce defensively
  beside it. Nothing was folded and no watermark moves in this wave.
