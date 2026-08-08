# Agent-Theory Delta Wave Propagation Plan (2026-08-08)

Status: active
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
3. **Rename policy:** live guidance surfaces say **agent-theory**;
   provenance notes citing pre-rename pins keep the historical name in
   the form "agent-guidance (now agent-theory) @ `SHA`". Historical
   plans and lessons entries are not edited for the rename.
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
- [ ] `docs/agent-context/runbooks/hardening-plans.md` — §15 declared
      deviation-capacity additions
- [ ] `docs/agent-context/runbooks/testing-patterns.md` — enumerable-
      contract firing-test patterns
- [ ] `docs/agent-context/runbooks/writing-implementation-docs.md` —
      2-line delta
- [ ] `skills/README.md` — crystallize-program-theory row
- [ ] `docs/README.md` — program-theory tier in the docs map

Splice payloads (hub delta hunks into locally adapted files):
- [ ] `AGENTS.md`: read-order item 1 upgraded to hub end-state wording
      (crystallize pointer, Class-5-needs-Draft rule); module-theory
      block; session-start coalescing check section; classification
      bullet gains index-row + close-out sentence; DoD gains class ≥3
      index-row close bullet
- [ ] `docs/agent-context/README.md`: read order gains program theory
      at 1 + self-reference at 2; machine-readable-order pointer;
      declared-claim floor paragraph
- [ ] `docs/agent-context/context.index.yaml`: program-theory in
      read_order + documents role
- [ ] `docs/agent-context/decision-hierarchy.md`: Trusted Base section;
      product-scope governing-account bullet; negative-direction
      staleness sentence
- [ ] `docs/agent-context/engineering-principles.md`: read-list gains
      program theory at 1 + rationale at 3; §5 theory bullets; §12
      "gates do not gate gates" paragraph
- [ ] `docs/agent-context/runbooks/maintaining-traceability.md`:
      closure-review executable-evidence bullet; chain terminus
      `code/test evidence`
- [ ] `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`:
      bounded-attempts paragraph; existence-check-first paragraph;
      guidance-surfaces-reviewable paragraph; §5a audit-response
      protocol
- [ ] `docs/agent-context/runbooks/writing-plans.md`: existence-check
      rule; comprehension-questions-with-teeth; demotion-in-place rule;
      class ≥3 index-row completion rule; superseded-flip rule;
      two-step retirement rewrite (second-agent optional, owner decision
      2026-08-07); retained-ref reachability rule; mm fold-up wording fix
- [ ] `docs/agent-context/runbooks/writing-specs.md`: theory-boundary
      lede + section; enumerated-list same-change gate rule;
      gate-wiring rule (2026-08-07 wording — declared execution path,
      not CI-for-every-tool); anti-pattern rows
- [ ] `docs/specs/01-development-documentation-operating-model.md`:
      [DOM-2] program-theory + module-theory taxonomy; [DOM-3] startup
      order + theory-vs-contract paragraph; [DOM-4] identity-work
      theory-alignment + REV bullet; [DOM-5] git-backed-coalescing
      carve-out; [DOM-14] archive-rule rewrite + optional second-agent
      + deferral-state rows; [DOM-15] ordinary-maintenance Class 2 +
      owner-gated promotions + two new fixture rows; Related Plans
      repair (decision 6)
- [ ] `skills/coalescing/SKILL.md`: archive-rule alignment (repair
      boundary, archive phase, optional second-agent, unindexed
      reporting, ascension-boundary "generalizes the discipline"
      wording, coalesce-check evidence-trail note)
- [ ] `skills/brainstorming-to-plan/SKILL.md`: admission-test wording
      (cites hub [AT-THEORY-7] — marked as hub theory, see decision 4)
- [ ] `skills/interface-review/SKILL.md`: retired hub plan cite →
      quoted-name retired form
- [ ] `bin/coalesce-check`: shallow-clone loud skip; foreign-attribution
      reporting replaces sibling probing; `COALESCE_SIBLING_ROOT`
      opt-in; known-limitation comment — all re-based onto backstitch's
      H2 lessons derivation and local header
- [ ] `bin/check-dom15-fixtures`: rigorous fence parser + six fence
      probes routed through `full_check`; marker-comment rename
- [ ] `docs/implementation/01-documentation-system.md`: program-theory
      tier delta if the consumer copy's structure carries the taxonomy
      section (verify at transplant; skip with a note if the local doc
      diverged)

New files:
- [ ] `docs/specs/09-agent-theory-and-program-theory.md` — the primer
      (hub end-state), Status line adapted with this plan + pin; specs
      index row added (reference, not session-start)
- [ ] `skills/crystallize-program-theory/SKILL.md` — copied, Status
      line adapted (this plan + pin); hub-local path references
      retargeted (primer → `09-`, hub theory examples marked hub-side)

Repairs and wiring in this wave:
- [ ] DOM Related Plans foreign-cite repair (decision 6)
- [ ] `bin/check-doc-paths` declared-future-artifact allowlist
      (decision 6)
- [ ] `.github/workflows/ci.yml` `doc-gates` job (decision 5)
- [ ] rename pass on live guidance surfaces (decision 3)
- [ ] term-collision pass over every transplanted surface (decision 4)

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
