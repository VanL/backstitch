# Agent-Guidance Delta Wave Propagation (2026-07-17)

Status: active

Class: 5+P — lands normative spec text ([DOM-14] trigger denomination)
plus runbook, skill, and state-file changes that govern how every future
change in this repository is planned, reviewed, and coalesced. +P: an
independent scoped adaptation review is owed (dispositions in §7); this
worker operates under a no-subagent fence, so the review is left as an
owner-run task, not waived.

## 1. Goal

Adopt the agent-guidance hub delta between backstitch's last pins (the
2026-07-14 wave, hub `2f7eff6`; and the 2026-07-15 agent-interfaces
adoption, hub `a4b4345`) and hub `b248e1c`. Source is pinned at hub
`b248e1c`; every payload was extracted with
`git -C <agent-guidance> show b248e1c:<path>` and verified against the
hub commit that introduced it.

## 2. Source and Pins

- Source SHA (pin): agent-guidance `b248e1c`.
- Backstitch prior pins: `2f7eff6` (2026-07-14 wave, via
  `2026-07-14-agent-guidance-propagation-plan.md`) and `a4b4345`
  (2026-07-15 designing-agent-facing-interfaces adoption, via
  `2026-07-15-agent-interfaces-runbook-adoption-plan.md`).
- Delta = `a4b4345..b248e1c` (the six payloads below), re-verified
  against the hub commits that authored each.

## 3. Payload Checklist

Each row cites the hub commit it derives from and the grep that confirms
it landed in backstitch (see §6 for the run).

| # | Payload | Hub commit | Target | Grep marker |
|---|---------|-----------|--------|-------------|
| 1 | [DOM-14] trigger bullet — fold-unit denomination | `30c8b04` | `docs/specs/01-development-documentation-operating-model.md` | `denominated in the repository's fold unit` |
| 1b | Fold-unit + progress-model declaration (spec follow-up) | `30c8b04` (F7) | `docs/coalescing.md` | `Fold unit and progress model (per [DOM-14])` |
| 2 | Coalescing skill — six refinements | `cc7ab30` | `skills/coalescing/SKILL.md` | `Denominate the count`, `across three tiers`, `re-verifies the pre-existing code examples`, `upstream framework`, `check theme` / `chronological catch-all`, `beside live concurrent sessions` |
| 3 | New interface-review skill + registration | `763a0e9`/`fc23eae`/`8c504fd` (b248e1c state) | `skills/interface-review/SKILL.md`; `docs/implementation/02-repository-map.md`; `docs/agent-context/runbooks/designing-agent-facing-interfaces.md` | `# Interface Review`; `skills/interface-review/SKILL.md \| Review an agent-facing`; `operationalizes this walk` |
| 4 | writing-plans — approval-attaches bullet | `fafd874` | `docs/agent-context/runbooks/writing-plans.md` | `Approval attaches to the text that was reviewed` |
| 4b | writing-plans — plans-record-evidence bullet | `b248e1c` | `docs/agent-context/runbooks/writing-plans.md` | `never transient repository` |
| 5 | review-loops §4 two-question PASS/BLOCKED + trace | `cd74fcd`/`6052289` | `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md` | `must answer PASS or BLOCKED` |
| 5b | review-loops §4a scoped-change template + round-2 | `ea5314b` | same | `## 4a. Scoped Change Review Prompt` |
| 5c | review-loops §6 verdict vocabulary | `cd74fcd` | same | `Verdict vocabulary, by review type` |
| 6 | call-agent step-2 brief standard + pointer + verdict phrasing | `3ffb807` | `skills/call-agent/SKILL.md` | `required-shape artifact` |

## 4. Adaptations (per-payload)

| Payload | Divergence | Adaptation |
|---------|-----------|------------|
| 1 | Backstitch's [DOM-14] pre-image matched canonical verbatim | Bullet replacement lands verbatim; §-anchor re-verified (line-start `- coalescing triggers are event-derived`). |
| 1b | Backstitch's lessons ledger is a flat chronological dated-H2 ledger, not domain-grouped; the new spec text requires the fold unit + progress model be *declared* in `docs/coalescing.md` | Added an explicit declaration: fold unit = repo-wide dated H2 section, progress model = date watermark (a date cursor is correct for a strictly date-ordered ledger). Not a hub-verbatim transplant — a local declaration the spec text now requires. |
| 2 | Backstitch's coalescing skill is a localized copy (`# Coalescing Sweep`, local step numbering, local adaptation notes) | Six refinements integrated at their heading/paragraph anchors, not clobbered; local adaptation notes preserved. Refinement 1 gained a one-line local note pointing at this repo's flat ledger. |
| 3 | Backstitch has no central skill-index table (`skills/README.md` is a how-to, not a registry); the hub registers interface-review in repository-map §Skills + a runbook back-pointer | Registered the same two surfaces: repository-map §Skills row (that file is dirty — additive single-row insert, region in §6) and the `designing-agent-facing-interfaces.md` back-pointer (clean). Status/provenance localized to this plan + `b248e1c`; hub plans quoted by name. |
| 4/4b | Backstitch writing-plans pre-image matched canonical at both anchors | Both bullets land verbatim at their anchors (top executable-documents list; Plan Lifecycle mutability boundary). The mm plan is cited by name only, as a quoted foreign reference. |
| 5 | Backstitch §4 had a local `delta as if promoted` tweak on the old prompt | Whole §4 blockquote replaced with the two-question PASS/BLOCKED prompt; §4a and §6 verdict appendix added. The standing-invariants-registry clause is conditional ("where this repository keeps…"), so it lands without asserting backstitch has one. |
| 6 | Backstitch call-agent step-2 pre-image matched canonical | Parenthetical + brief-standard block land verbatim; the block's §4a pointer resolves to the section added in payload 5. |

## 5. Invariants and Fences

- No git writes: this worker edits the working tree only; staging and
  commit are the owner's, expressed here as instructions, not as claims
  about the tree.
- Touch nothing foreign: the concurrent evidence-spike WIP (semantic
  gate, obligations, product-eval fixtures) is out of scope. The two
  dirty files this wave must touch — `docs/plans/README.md` and
  `docs/implementation/02-repository-map.md` — receive localized additive
  inserts only, no reflow, exact regions reported in §6.
- Mandatory gate: `uv run backstitch check --repo-root .` must be no
  worse than the pre-change baseline (§6 records both runs).
- To land: stage by explicit path list (the payload targets plus this
  plan and its index row), never `git add -A`; then pin this plan's
  source SHA note if a state-file watermark advances (no watermark
  advances in this wave — no material was folded).

## 6. Verification and Gates

- Baseline `backstitch check` (pre-change): 0 errors, 0 warnings, 0 infos.
- Post-change `backstitch check`: recorded in the handoff report; the
  gate requirement is no-worse-than baseline.
- Completeness: one grep per §3 marker over the target files.
- Localized-insert regions (dirty files):
  - `docs/plans/README.md` §Status Index — one additive row for this plan.
  - `docs/implementation/02-repository-map.md` §Skills — one additive row
    for `skills/interface-review/SKILL.md` (the two existing rows and the
    surrounding WIP hunks are untouched).

## 7. Independent Review Loop (dispositions)

Scope fence for the reviewer: the source content is already hub-reviewed;
review ONLY the adaptation — placement/anchors, the payload-1b local
declaration, the interface-review provenance localization and
registration surfaces, the localized additive inserts into the two dirty
files, and any performative additions. Use the §4a scoped-change prompt.

| ID | Finding | Disposition |
|----|---------|-------------|
| — | Review run 2026-07-17 (grok, read-only, §4a-form brief): **no blocker**, zero findings. Fidelity to the hub `b248e1c` end-state confirmed (no intermediate-commit residue); the [DOM-14] splice structure-preserving; the payload-1b declaration verified locally TRUE (the ledger is strictly chronological, so the date-watermark progress model is correct); localized additive rows on the two shared-dirty files held single-row | Accepted as run |
| obs | Reviewer observations, recorded: the lessons-derivation regex undercounts (21 later lessons use `## Title (YYYY-MM-DD)` headings — pre-existing, not this wave); the flagged `implemented, uncommitted` index row stands for owner decision; the skills-registry gap stays owner backfill | No change this wave |

## 8. Out of Scope

- Backfilling repository-map §Skills with the already-present
  `call-agent`, `coalescing`, `brainstorming-to-plan`, and `debugging`
  skills (pre-existing registry gap — owner call, not this wave).
- The flagged `docs/plans/README.md` row
  `2026-07-15-agent-guided-evidence-cases-plan.md`
  ("implemented, uncommitted — report-only"): the new
  plans-record-evidence rule's first local catch — owner decides whether
  to reword; this worker does not edit a foreign WIP row.
- A coalescing sweep: deferred. The lessons ledger is unchanged by this
  wave and its concurrent-session guidance (refinement 6) says to
  coalesce defensively beside live WIP.
