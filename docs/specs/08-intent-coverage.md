# Intent Coverage Spec

Status: Proposed

Related specs:

- `docs/specs/02-backstitch-core.md` [SC-3], [SC-4], [SC-11]
- `docs/specs/04-backstitch-traceability-exclusions.md` [EXC-*]
- `docs/specs/06-semantic-gates.md` [SEM-*]
- `docs/specs/07-verification-and-evidence-cases.md` [EVC-7], [EVC-8]

## 1. Purpose And Scope [COV-1]

Every existing Backstitch check is conditional: references that exist must
resolve; invariants that are declared must bind. Intent coverage adds the
universal claim: **every code definition is accounted for by stated intent,
or is deliberately and auditably exempted** — and, in the reverse
direction, every stated requirement is accounted for by implementation.

`coverage.py` asks whether every line is exercised by a test. Intent
coverage asks whether every behavior is reachable from a spec. The
complements are the product:

- **code-without-spec**: definitions with no intent edge — undocumented
  behavior, dead code, or scope creep that entered the repository without
  stated intent;
- **spec-without-code**: requirement sections with no live implementation
  mapping — stated guarantees nothing owns.

Both complements are ranked worklists for the triage loop ([COV-6]), not
merely numbers. The target is never 100% coverage; it is zero
*unaccounted-for* definitions, where "accounted for" includes an explicit
exemption with a reason.

This spec owns coverage computation, exemptions, the ratchet gate, drift
coverage, and the triage loop. It does not own per-annotation resolution
diagnostics (those are [SC-4]/[SC-11], e.g. `SPEC_SECTION_UNMAPPED`),
scan-boundary exclusion ([CFG-6]/[EXC-*]), or semantic judgment mechanics
([SEM-*]). Together with [INV-*] and the semantic lane, these axes form the
contract-coverage matrix stated in [SC-16].

## 2. Mental Model [COV-2]

The four-tool suite, one sentence each: `ruff` — every line well-formed;
`mypy` — every value well-typed; `coverage` — every line exercised by a
test; `backstitch` — every behavior traceable to intent and every intent
traceable to behavior. Intent coverage is the quantifier that makes the
fourth sentence complete.

Like test coverage, intent coverage is a *reach* metric, not a quality
metric: a covered definition has an intent edge; whether the spec text is
informative is a separate, sampled semantic question ([COV-7]). The
deterministic layer never claims more than reach.

## 3. Coverage Computation [COV-3]

Coverage is computed deterministically, without a model, from the trace
graph and the code parse:

- The unit of measurement is the **definition**: module, class, function,
  and method, as produced by the existing code parser. Lines are the wrong
  altitude for intent; definitions are where behavior lives.
- A definition is **directly covered** when it (or its enclosing
  definition) carries a resolving spec reference, is named by a resolving
  implementation mapping (`path::symbol`), or is an invariant target or
  binding test.
- A definition is **inherited-covered** when it is covered only because a
  whole-file mapping or module-level reference blankets it. Inherited
  coverage is reported separately and counts toward a distinct, weaker
  metric — the analogue of the line-versus-branch distinction. A repository
  may set policy on either metric, but the two are never summed silently.
- A definition is **exempt** when a [COV-4] exemption applies.
- Everything else is **uncovered**.

The report states, per module and in total: direct, inherited, exempt, and
uncovered definition counts; the uncovered list with locators; and the
spec-side complement — requirement sections whose implementation mappings
are absent or resolve to nothing live (aggregating the existing [SC-11]
per-section diagnostics into a coverage view rather than re-diagnosing
them). Output follows the [SC-6] determinism rules: stable ordering, stable
JSON, content hashes.

## 4. Exemptions [COV-4]

Not all code deserves a spec. Re-exports, argument plumbing, generated
code, and trivial glue are accounted for by exemption, not by manufactured
spec text. The mechanism mirrors [EXC-*] and the `# pragma: no cover`
idiom:

- inline: `# backstitch: no-spec -- <reason>` on the definition line or
  its docstring block; the reason is mandatory and nonblank;
- configured: per-file and per-glob exemption tables in TOML, each entry
  carrying a reason, for generated trees and vendored code;
- every exemption is auditable: the coverage report lists the exemption
  ledger, and unused or non-matching exemptions are findings (mirroring
  [EXC-*] suppression hygiene), so dead exemptions cannot accumulate
  silently.

Exemption is deliberately **cheaper than specification**: one line with a
reason versus authored spec text plus mappings. This asymmetry is a design
requirement, not an accident — if faking a spec is easier than exempting,
the gate manufactures vacuous specs ([COV-7]).

Diagnostics:

| Code | Short | Packaged level | Meaning |
|---|---|---|---|
| `INTENT_UNCOVERED_DEFINITION` | `BSN001` | info | Definition has no intent edge and no exemption |
| `INTENT_INHERITED_ONLY` | `BSN002` | info | Definition covered only by a file-level blanket |
| `INTENT_EXEMPTION_UNUSED` | `BSN003` | warning | Exemption matches nothing |
| `INTENT_EXEMPTION_UNREASONED` | `BSN004` | error | Exemption without a nonblank reason |
| `INTENT_REQUIREMENT_UNIMPLEMENTED` | `BSN005` | info | Requirement section with no live implementation mapping |

The `BSN` short-code family is allocated to intent coverage; `BSI` remains
the invariant family per [SC-11]/[SC-15] and is never reused here.

Packaged levels are conservative and advisory, per the [SC-11]/[SEM-6]
philosophy; repositories promote through ordinary policy.

## 5. The Ratchet Gate [COV-5]

Absolute coverage on an existing repository invites either despair or
boiling the ocean. The gate that works is the diff ratchet:

- **Patch coverage:** in gated mode, every definition *added or changed*
  in the diff under review must be directly covered, inherited-covered
  where policy allows, or exempted. Pre-existing uncovered definitions are
  the backlog, not the gate.
- **Monotonicity:** a repository may record ratchet floors (per-metric,
  per-tree minimums). A change that lowers a floored metric is a finding.
  Floors only move up, by deliberate configuration edits.
- The diff boundary is computed from repository state (base ref), not
  trusted from the invoker.

```toml
[tool.backstitch.coverage]
mode = "report"                 # report | ratchet
granularity = "definition"
inherited_counts = false        # inherited coverage satisfies the ratchet?
ratchet_base = "origin/main"

[tool.backstitch.coverage.floors]
"backstitch/" = { direct = 0.0 }   # raised only by deliberate edits
```

This is the mechanization of the operating-model rule that changes trace
to specs ([DOM-4]): prose agents follow unevenly becomes a gate they
cannot.

## 6. The Triage Loop [COV-6]

The uncovered-definition report is a worklist owned by intent coverage. It
does not create an evidence broker, proposal store, activation state, or
evidence case. A human or agent may use [EVC-8]'s read-only obligation list,
evidence summary, and candidate discovery to inspect related intent and
source, but those reads cannot ratify a classification or source relation.

For each deterministically ranked uncovered definition, the reviewer chooses
one outcome: `needs-spec`, `glue`, `dead`, or `contradicts-spec`.
`needs-spec` proposes ordinary spec text plus reciprocal source declarations;
`glue` proposes a reasoned [COV-4] exemption; `dead` proposes source removal;
and `contradicts-spec` identifies the existing obligation and proposes a
corrective source diff whose semantic effect can be evaluated through the
ordinary current-repository gate. Backstitch may show exact supported
annotation forms, but it does not apply any proposal.

Only a human-reviewed source diff changes coverage or alignment. After that
diff lands, the resolver and coverage computation recompute from repository
source. Rejected advice creates no durable product state. The loop continues
until the worklist is empty or the owner records a bounded stop decision.
The coverage runner owns ranking; the human reviewer owns disposition;
[EVC-8] owns obligation reads and guidance. Verification reruns coverage and
the reciprocal trace gate from current source. The required action is to land
or reject an ordinary source diff, never to activate tool-owned state.

## 7. Anti-Goodhart Requirements [COV-7]

Two failure modes are anticipated and must be countered by design:

- **Vacuous specs.** A coverage gate incentivizes spraying uninformative
  text ("this module manages state") over uncovered code — the analogue of
  tests that execute lines without asserting. Countermeasure: sampled
  semantic informativeness review — a spec's text should distinguish the
  current implementation from a mutated one; the [SEM-8] corpus gains
  spec-side mutations for this. Loop-generated spec text is always flagged
  for this sampling. Exemption being cheaper than fake specification
  ([COV-4]) removes the incentive at the source.
- **Over-specification.** Every spec the loop generates is prose that must
  be maintained and re-read; unbounded spec growth is a real cost, and a
  coverage gate must not become the mechanism by which the corpus grows
  without bound. The `needs-spec` classification bar is behavioral: a
  definition needs spec text only when it embodies a decision a maintainer
  would want stated. Everything else is glue, and glue is exempted. The
  coverage report separately tracks spec-corpus growth attributable to the
  loop so the trend is visible and governable.

## 8. Drift Coverage [COV-8]

The fifth deterministic question is asked at change time: **which changed
code touches contract-bearing areas without corresponding spec or test
movement?** Spec, test-evidence, and orphan coverage measure a repository
state; drift coverage measures a *diff* against the trace graph.

- A **drift suspect** is a contract edge whose implementation side changed
  in the diff under review while its governing section text, its
  implementation-mapping block, and its binding tests all remained
  unchanged. Computation is fully deterministic: the diff boundary is
  repository-derived from a base ref (the [COV-5] ratchet rules), and edge
  membership comes from the existing trace graph.
- Drift is often legitimate — a refactor moves code without moving
  promises. The finding is therefore packaged advisory, and the
  acknowledgment idiom is a diff-scoped suppression with a nonblank reason
  ("refactor, contract unchanged"), auditable like every other suppression.
  Acknowledgment must be *cheaper* than a cosmetic spec edit, or the gate
  manufactures meaningless contract churn — the same asymmetry rule as
  [COV-4].
- The **stale-doc suspect** signal is derived, not separate: a contract
  edge accumulating unacknowledged drift suspects across changes since its
  section text last moved. It is reported as a trend per the [SC-16] metric
  identity rule, never as a blocking finding by packaged policy.

| Code | Short | Packaged level | Meaning |
|---|---|---|---|
| `INTENT_DRIFT_SUSPECT` | `BSN006` | info | Mapped implementation changed; governing section, mapping, and binding tests did not |

Drift coverage does not judge whether the change *should* have moved the
contract — that is a semantic question, answerable through the ordinary
[SEM-*] lane over a packet containing the diff context. The deterministic
finding only makes the silence visible.

## 9. Verification Expectations [COV-9]

Executable gates cover, at minimum:

- a definition with a resolving docstring reference, a `path::symbol`
  mapping, and an invariant binding is directly covered under each edge
  kind independently
- file-level blanket mapping yields inherited, never direct, coverage
- `INTENT_UNCOVERED_DEFINITION` fires for a fresh unreferenced definition
  and stops firing when a reference, mapping, or exemption is added
- an exemption without a reason fails; an unused exemption fires its
  finding; removing the exempted code makes the exemption unused
- ratchet mode passes a diff whose new definitions are covered or
  exempted, fails one that adds an uncovered definition, and ignores
  pre-existing backlog; base-ref computation is repository-derived
- floors: lowering a floored metric fires; raising a floor is config-only
- the spec-side complement lists a requirement section whose mapping was
  deleted, and clears when a live mapping returns
- coverage output is deterministic and byte-stable across repeated runs
- the uncovered-definition worklist ranking is deterministic for a fixed
  repository state; repeated runs return the same definition identities and
  ranking facts; and
- for each `needs-spec`, `glue`, `dead`, or `contradicts-spec` disposition,
  only an ordinary landed source diff changes coverage or alignment;
  rejected or no-diff advice leaves both unchanged, and no proposal or
  activation object exists.
- a diff that changes a mapped implementation without touching its section
  text, mapping block, or binding tests fires `INTENT_DRIFT_SUSPECT`; the
  same diff with a binding-test change does not; an acknowledged suspect is
  recoverable through the suppression audit view with its reason
- drift computation is deterministic for a fixed base ref and repository
  state, and the base ref is repository-derived, never trusted from the
  invoker
- every `BSN*` diagnostic fires and respects packaged-versus-applied
  policy layering

## Related Plans

- `docs/plans/2026-07-15-agent-guided-evidence-cases-plan.md`
  (vocabulary reconciliation only; [COV-3] through [COV-5], [COV-7], and
  [COV-8] remain unimplemented and require their own promoted plan)
