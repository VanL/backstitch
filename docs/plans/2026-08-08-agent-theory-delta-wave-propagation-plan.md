# Agent-Theory Delta Wave Propagation Plan (2026-08-08)

Status: completed — landed `bd4a8cd`, pinned `32b87ce`; sweep ran
checked-deferred; hub back-port committed (agent-theory `d52e12a`).
Class: 3+P (effective 5) — spec text and durable guidance land.
Owner: propagating agent under the hub's `skills/propagate-guidance/SKILL.md`;
adaptation decisions recorded here; owner authorized the wave 2026-08-08
("Please do", following theory ratification).

## Scope and Pin

- Source: agent-theory (formerly agent-guidance) @ **`ec716e8`**
  (committed HEAD; the hub's dirty worktree files — its own README/
  principles/repository-map edits and untracked `docs/lore/` — are NOT
  in this wave).
- Consumer's last pin: `e42762c` (recorded in `docs/coalescing.md` run
  log, 2026-07-28 wave).
- Delta: `e42762c..ec716e8`, 17 hub commits, including the repository
  rename agent-guidance → agent-theory, the program/module-theory
  machinery, the [DOM-14] archive rule, [DOM-15] classification
  amendments, the register-conditioning and ascension-boundary theory
  revisions (hub-local theory; only their guidance consequences land
  here), and gate improvements.
- Receiving tree state at plan time: **clean** (`git status` empty;
  HEAD `b453132`). No dirty-tree invariant rows needed; any WIP
  appearing mid-wave belongs to concurrent sessions and must not be
  staged.

## Standing decisions for this wave

1. **Theory files do not transplant.** Backstitch's
   `docs/program-theory.md` is its own ratified account (Active,
   2026-08-08). The hub's theory file, changelog, README, and plans are
   hub-native. The definitional primer transplants as a reference spec.
2. **Primer slot collision:** hub `docs/specs/02-agent-theory-and-
   program-theory.md` lands as `docs/specs/09-agent-theory-and-program-
   theory.md` (02 is `[SC-*]` core). All transplanted references to the
   primer's path are retargeted to `09-`.
3. **Rename policy (amended at survey — demotion-in-place):** the
   wave's default was annotate-provenance; backstitch's own 2026-07-28
   run-log row already governs the rename locally — existing provenance
   lines naming agent-guidance "are left as written." The local policy
   wins. New text written by this wave says **agent-theory**;
   provenance lines edited anyway for other payload reasons gain the
   "(now agent-theory)" clarifier; all other pre-existing provenance
   lines, run-log rows, plan filenames, and lessons entries stay
   untouched.
4. **Term-collision policy:** in backstitch, *traceability*, *evidence*,
   *coverage*, and *check* have exact product senses. Transplanted
   process text that says "traceability gate" gets the disambiguating
   form "doc-traceability gate (`bin/check-doc-paths`)" on first use
   per file; hub process senses must not read as product contract
   language. The theory file's terminology note is the reference.
5. **Gate-wiring decision:** backstitch CI ruff-lints the three doc
   gates but never executes them — the exact "unstated execution path"
   defect the wave's own rule names. A `doc-gates` job is added to
   `.github/workflows/ci.yml` running `check-doc-paths`,
   `check-dom15-fixtures --self-test` + the real check, and
   `coalesce-check` on full history (`fetch-depth: 0`).
6. **Red check-doc-paths scope** (owner-assigned to wave mechanics in
   the crystallization plan): the 4 hub-founding-plan citations in the
   DOM spec's Related Plans convert to quoted-name + hub attribution
   (the wave's own foreign-plans rule); the 5 `tests/performance/*.json`
   claims are **declared future artifacts** (the specs themselves say
   qualification reports `unavailable` until they are reviewed and
   committed) — they get an auditable declared-future-artifact
   allowlist in `bin/check-doc-paths` with rationale citing the owning
   clauses, in this repository's governed-suppression idiom. Creating
   placeholder files to green the gate is rejected (the product must
   not define its own expected result).
7. **Plan-index backfill is out of scope.** 41 plan files, 20 index
   rows → 21 unindexed. The wave lands the unindexed-plans reporting
   rule; backfill is bulk-session work (hub skill step 4). Recorded in
   the sweep section as a reportable condition with the deferral shape.
8. **Hub lessons do not transplant wholesale.** Their distilled
   doctrine arrives via the runbook/spec payloads below; backstitch's
   ledger records this wave's own lessons only.

## Payload checklist (grep-verifiable; one line each)

Wholesale end-state copies (local file identical to consumer pin):
- [x] `docs/agent-context/runbooks/hardening-plans.md` — §15 declared
      deviation-capacity additions
- [x] `docs/agent-context/runbooks/testing-patterns.md` — enumerable-
      contract firing-test patterns
- [x] `docs/agent-context/runbooks/writing-implementation-docs.md` —
      2-line delta
- [x] `skills/README.md` — crystallize-program-theory row
- [x] `docs/README.md` — program-theory tier in the docs map

Splice payloads (hub delta hunks into locally adapted files):
- [x] `AGENTS.md`: read-order item 1 upgraded to hub end-state wording
      (crystallize pointer, Class-5-needs-Draft rule); module-theory
      block; session-start coalescing check section; classification
      bullet gains index-row + close-out sentence; DoD gains class ≥3
      index-row close bullet
- [x] `docs/agent-context/README.md`: read order gains program theory
      at 1 + self-reference at 2; machine-readable-order pointer;
      declared-claim floor paragraph
- [x] `docs/agent-context/context.index.yaml`: program-theory in
      read_order + documents role
- [x] `docs/agent-context/decision-hierarchy.md`: Trusted Base section;
      product-scope governing-account bullet; negative-direction
      staleness sentence
- [x] `docs/agent-context/engineering-principles.md`: read-list gains
      program theory at 1 + rationale at 3; §5 theory bullets; §12
      "gates do not gate gates" paragraph
- [x] `docs/agent-context/runbooks/maintaining-traceability.md`:
      closure-review executable-evidence bullet; chain terminus
      `code/test evidence`
- [x] `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`:
      bounded-attempts paragraph; existence-check-first paragraph;
      guidance-surfaces-reviewable paragraph; §5a audit-response
      protocol
- [x] `docs/agent-context/runbooks/writing-plans.md`: existence-check
      rule; comprehension-questions-with-teeth; demotion-in-place rule;
      class ≥3 index-row completion rule; superseded-flip rule;
      two-step retirement rewrite (second-agent optional, owner decision
      2026-08-07); retained-ref reachability rule; mm fold-up wording fix
- [x] `docs/agent-context/runbooks/writing-specs.md`: theory-boundary
      lede + section; enumerated-list same-change gate rule;
      gate-wiring rule (2026-08-07 wording — declared execution path,
      not CI-for-every-tool); anti-pattern rows
- [x] `docs/specs/01-development-documentation-operating-model.md`:
      [DOM-2] program-theory + module-theory taxonomy; [DOM-3] startup
      order + theory-vs-contract paragraph; [DOM-4] identity-work
      theory-alignment + REV bullet; [DOM-5] git-backed-coalescing
      carve-out; [DOM-14] archive-rule rewrite + optional second-agent
      + deferral-state rows; [DOM-15] ordinary-maintenance Class 2 +
      owner-gated promotions + two new fixture rows; Related Plans
      repair (decision 6)
- [x] `skills/coalescing/SKILL.md`: archive-rule alignment (repair
      boundary, archive phase, optional second-agent, unindexed
      reporting, ascension-boundary "generalizes the discipline"
      wording, coalesce-check evidence-trail note)
- [x] `skills/brainstorming-to-plan/SKILL.md`: admission-test wording
      (cites hub [AT-THEORY-7] — marked as hub theory, see decision 4)
- [x] `skills/interface-review/SKILL.md`: retired hub plan cite →
      quoted-name retired form
- [x] `bin/coalesce-check`: shallow-clone loud skip; foreign-attribution
      reporting replaces sibling probing; `COALESCE_SIBLING_ROOT`
      opt-in; known-limitation comment — all re-based onto backstitch's
      H2 lessons derivation and local header
- [x] `bin/check-dom15-fixtures`: rigorous fence parser + six fence
      probes routed through `full_check`; marker-comment rename
- [x] `docs/implementation/01-documentation-system.md`: program-theory
      tier delta if the consumer copy's structure carries the taxonomy
      section (verify at transplant; skip with a note if the local doc
      diverged)

New files:
- [x] `docs/specs/09-agent-theory-and-program-theory.md` — the primer
      (hub end-state), Status line adapted with this plan + pin; specs
      index row added (reference, not session-start)
- [x] `skills/crystallize-program-theory/SKILL.md` — copied, Status
      line adapted (this plan + pin); hub-local path references
      retargeted (primer → `09-`, hub theory examples marked hub-side)

Repairs and wiring in this wave:
- [x] DOM Related Plans foreign-cite repair (decision 6)
- [x] `bin/check-doc-paths` declared-future-artifact allowlist
      (decision 6)
- [x] `.github/workflows/ci.yml` `doc-gates` job (decision 5)
- [x] rename pass on live guidance surfaces (decision 3)
- [x] term-collision pass over every transplanted surface (decision 4)

## Verification

- Completeness gate: one grep per checklist line after transplant.
- Backstitch gates: `bin/check-doc-paths` (expect green after decision
  6), `bin/check-dom15-fixtures --self-test` + real run,
  `bin/coalesce-check`, ruff over `bin/`, and the product suite is NOT
  run here (no product surface is touched; CI runs it on push).
- Scoped independent review (different family, codex): adaptation only
  — placement, retargets, term-collision safety, no-clobber; source
  content is hub-reviewed.
- Landing: file-list staging equality against this checklist; nothing
  runs after a failed gate; wave commit then pin follow-up commit
  updating `docs/coalescing.md` provenance to `ec716e8`.

## Expected staged-file list (landing gate: staged list == this list)

`.github/workflows/ci.yml`, `AGENTS.md`, `bin/check-doc-paths`,
`bin/check-dom15-fixtures`, `bin/coalesce-check`, `docs/README.md`,
`docs/agent-context/README.md`,
`docs/agent-context/context.index.yaml`,
`docs/agent-context/decision-hierarchy.md`,
`docs/agent-context/engineering-principles.md`,
`docs/agent-context/runbooks/hardening-plans.md`,
`docs/agent-context/runbooks/maintaining-traceability.md`,
`docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`,
`docs/agent-context/runbooks/testing-patterns.md`,
`docs/agent-context/runbooks/writing-implementation-docs.md`,
`docs/agent-context/runbooks/writing-plans.md`,
`docs/agent-context/runbooks/writing-specs.md`,
`docs/implementation/01-documentation-system.md`,
`docs/plans/2026-08-08-agent-theory-delta-wave-propagation-plan.md`,
`docs/program-theory.md` (review finding A-03: the primer-path
sentence updated to the landed `09-` file),
`docs/specs/00-specs-index.md`,
`docs/specs/01-development-documentation-operating-model.md`,
`docs/specs/04-backstitch-traceability-exclusions.md`,
`docs/specs/09-agent-theory-and-program-theory.md` (new),
`pyproject.toml`, `skills/README.md`,
`skills/brainstorming-to-plan/SKILL.md`, `skills/coalescing/SKILL.md`,
`skills/crystallize-program-theory/SKILL.md` (new),
`skills/interface-review/SKILL.md`.

The pin follow-up commit then updates `docs/coalescing.md` alone
(run-log row + provenance pin to `ec716e8` — the pin cannot live in
the commit it names).

## Sweep (standing rule: first sweep after propagation)

Run `bin/coalesce-check` + the state file's declared derivations;
expected outcome is an honest report: 21 unindexed plans (reportable,
backfill deferred as bulk-session work — reconsideration: an authorized
index-reconciliation session), harvest candidates vs threshold from the
index's closed-vocabulary rows only (free-prose rows counted as not
derivable), lessons tier per the H2 derivation. Deferrals recorded in
`docs/coalescing.md` with checked-through state; no folds forced under
wave time pressure.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Execution Log

(append-only)

- 2026-08-08: Plan opened after survey (three-way classification of
  every payload file against consumer pin `e42762c` and source
  `ec716e8`; per-file hub diffs exported to the session scratchpad).
- 2026-08-08: Decision 3 amended in place (demotion-in-place): the
  receiving repo's recorded rename policy (run-log row 2026-07-28)
  supersedes the wave's default annotate-provenance rule.
- 2026-08-08: Transplant complete; completeness gate green (one grep
  per checklist row — all 28 rows verified and checked off). Three
  receiving-repo gates fired during landing, each
  resolved in the repo's own idiom:
  (a) ruff C901 on the extended fixture self-test — resolved by
  locality-preserving decomposition (`_fence_probe_failures`), never
  suppression (the repo's A4 doctrine);
  (b) the self-corpus scanner flagged the primer's five [AT-REF-*]
  sections `SPEC_SECTION_UNMAPPED`, and a bare `meta_spec_globs` entry
  then tripped `SUPPRESSION_REASON_MISSING` — resolved with the
  governed structured suppression: `[[tool.backstitch.lint.suppressions]]`
  meta rule + `[SUP-AT-PRIMER-META]` declaration in the exclusions
  spec, audited via `--show-suppressions`.
  (c) `bin/check-doc-paths` itself: red at HEAD on nine danglers —
  four hub-founding-plan cites in the DOM spec's Related Plans
  (converted to quoted-name + hub attribution) and five
  `tests/performance/*.json` declared-future-artifact claims (the
  governed allowlist per standing decision 6) — and it then caught a
  phantom hub-plan cite in the transplanted primer's Related Plans,
  converted to quoted-name + hub attribution.
- 2026-08-08: Scoped independent review (codex, read-only, high
  effort; full output captured to the session scratchpad before
  filtering). Verdict: **LAND-WITH-EDITS**, findings A-01..A-07.
  Verified clean: primer-path retargets, no-clobber (H2 derivation,
  hermetic DoD, local runbook material, backstitch DOM rows), splice
  integrity, [SUP-AT-PRIMER-META] conformance to [EXC-6.4], doc-gates
  CI job isolation. Dispositions, all applied unless noted:
  - A-01 (P2, applied): hub-relative labels in the primer's tables
    ("This repository" / "This hub repository") renamed to name the
    agent-theory hub explicitly.
  - A-02 (P2, applied): allowlist contract completed — unused-entry
    detection (an allowlisted path no scanned surface claims fails),
    symlink parity on the stale-entry check, and a `--self-test` mode
    with five firing probes (unlisted-missing, allowlisted-missing,
    stale entry, unused entry, symlink-present), wired into the CI
    doc-gates job. C901 trips resolved by decomposition
    (`_stale_allowlist_failures` / `_scan_claims` / probe table), the
    repo's A4 idiom.
  - A-03 (P3, applied): theory file's "arrives locally with the
    pending propagation wave" updated to the landed `09-` path.
  - A-04 (P3, applied with one recorded deviation): process-prose
    "evidence" disambiguated — primer posture line now "observed
    results"; AGENTS.md and the coalescing skill call
    `bin/coalesce-check` a "provenance trail (process sense, not
    [EVC-*] product evidence)"; ci.yml step renamed; the
    maintaining-traceability closure bullet now says "executable
    verification result". **Deviation:** the crystallize skill's
    ALT/REV template field `Evidence:` is NOT renamed to
    `Provenance:` as suggested — it is the hub's shared record
    grammar and renaming it here would fork the cross-repo template;
    a terminology note in the skill's status block marks the sense
    instead.
  - A-05 (P3, applied): the two provenance lines renamed against the
    local leave-as-written policy (agent-context README
    interfaces-runbook bullet; implementation/01 scaffold line)
    restored to their HEAD wording.
  - A-06 (P3, applied): checklist rows checked (28/28), gate count
    corrected to three with the check-doc-paths red-gate work
    itemized, completeness-gate wording aligned to one-grep-per-row.
  - A-07 (nit, applied): allowlist rationale now cites [SC-10],
    [EVC-10], and implementation/05's Verification section.
  Reviewer also confirmed the session-start cues fire (8 harvest
  candidates at threshold 8, 21 unindexed, lessons derivation change
  1 → 22) — carried into the sweep section.
- 2026-08-08: Landed. Wave commit `bd4a8cd` (staged-list equality
  gate passed; 30 files, two new). Pin commit `32b87ce`
  (`docs/coalescing.md` run-log row + deferral refresh; provenance
  source agent-theory @ `ec716e8`). First-sweep-after-propagation ran
  checked-deferred (counts and reconsideration conditions in the
  state file). Back-port: the primer hub-label adaptation rule added
  to the hub's propagate-guidance step-4 table (agent-theory
  `d52e12a`) — observed at taut (adapted) and here (missed, caught by
  review A-01); simplebroker has no primer copy, no sibling repair
  needed. Plan closed; index row flipped in the same change.
- 2026-08-08: Gate results at transplant end: `check-doc-paths` OK
  (allowlist live, stale-entry self-check included);
  `check-dom15-fixtures --self-test` + real run OK; `coalesce-check`
  exit 0 (6 SHA claims, 3 foreign, 22 lessons H2 sections); ruff
  check + format clean; `ruff_suppression_index.py --check` OK;
  self-corpus `backstitch check` 0 errors / 0 warnings / 0 infos.
