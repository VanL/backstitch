# Backstitch Program Theory

Status: Active — owner-ratified 2026-08-08. Assembled from the
ratified crystallization decisions D1–D6 (plan
"2026-08-08-program-theory-crystallization-plan"); independent
semantic review 2026-08-08 (ADOPT-WITH-EDITS, PT-01–PT-09, all
applied). Revisions gate on the human owner.
Owner: Backstitch product owner
Boundary: Conceptual identity and design judgment above the contract
tier. Exact behavior belongs to the specs; the contract-tier identity
clause is [SC-16] in `docs/specs/02-backstitch-core.md`, which this
file cites and never restates. When theory and a spec diverge, the
spec governs current behavior — call out the mismatch and revise one
explicitly.
Verification: Owner and independent semantic review; consistency with
[SC-16] and the crystallization plan's decision log.
Required action: Read before product-scope judgment (audits, reviews,
feature-fit and design opinions) and before changing a core concept,
durable principle, or non-goal. Feature and spec-revision debates are
tested against [SC-16] first (its own rule); this file frames the
judgment above that test. Conform, or propose a revision here.

"Program theory" follows Peter Naur's "Programming as Theory
Building" (1985): this file is the current externalized account of
what kind of system Backstitch is, not a substitute for possessing
that model in practice. The definitional primer is
`docs/specs/09-agent-theory-and-program-theory.md`, adopted from the
agent-theory hub.

Terminology note (this repository's homonyms): in this file,
`evidence class` and `intent coverage` are Backstitch product terms.
Broader support for a claim is called an `observation` or
`provenance`; traditional test coverage is called `line coverage`.

---

## Purpose and desired feel [THEORY-1]

Backstitch is **spec-to-code traceability and invariant checking for
Python repositories** — in the owner's category claim, a
next-generation coverage/mypy/ruff-class tool. Its own ladder
statement ([COV-2]): ruff proves every line well-formed; mypy every
value well-typed; coverage every line exercised by a test; backstitch
every behavior traceable to intent and every intent traceable to
behavior.

It should feel like:

- **a reader of repositories** — [SC-16] owns the exact boundary and
  any permitted exception,
- **findings you can argue with** — every issue navigable to a
  locator, reproducible byte-for-byte, its severity rationale
  stated,
- **governed exceptions that remain auditable** — [EXC-*] owns when
  a declaration and rationale are required,
- **human-owned consequences** — [SC-16] owns the exact
  policy-authority rule,
- **honest at its own expense** — the tool refuses to rubber-stamp
  itself; a clean report produced by unauditable hiding is a
  failure, not a pass ([SC-10]).

"Simple" for Backstitch is a small *concept* count against a large
capability: the graph nouns stay few while the machinery defending
their evidence classes may be large. The recorded imbalance — most
of the code exists to keep a model's judgment inside a deterministic
envelope — is the identity working as intended, not bloat.

## The thesis [THEORY-2]

Ratified by the owner 2026-08-08 (crystallization D1), superseding
the earlier "do what Naur said was impossible" framing (a
demotion-in-place; see [THEORY-9]):

> Naur was right — theory lives in minds and, now, in ephemeral
> agent contexts. What automated intelligence adds is not a new home
> for theory but a new instrument: repeatable evaluation that
> articulated portions of a theory are exposed through particular
> code — existence checked deterministically, fidelity judged
> semantically under evidence classes, and unevaluable articulation
> reported rather than guessed. Backstitch measures the transfer
> surface; possession stays where Naur put it.

Consequences:

- **Agent contexts are ephemeral theory substrates.** The corpus is
  how theory is re-instantiated into each new substrate, session
  after session — so a drifted corpus poisons every rebirth, and a
  false articulation is worse than an absent one: the next session
  will trust it.
- **Intent coverage is the thesis's native measure**, not a bolt-on:
  which portions are exposed, which exposures are evaluable, which
  code is exposure of nothing, and how exposure is distributed.
- **Evaluation is never possession.** Passing every gate proves the
  transfer surface is sound — never that anyone understands
  anything. [SC-16]'s evidence-class rule is this boundary's
  contract-tier enforcement.
- **Division of labor with the discipline**: the agent-theory hub
  wagers that theory can be iteratively developed and maintained
  across human and ephemeral-agent substrates; Backstitch makes one
  part of that wager measurable — whether the articulated portions
  still correspond to the code. Neither claim carries the other's
  burden of proof.

## Whole-system mental model [THEORY-3]

Backstitch's product shape is the two lanes and one authority named
in [SC-16]. At theory altitude, the distinction is epistemic:
**existence** of an exposure and **fidelity** of an exposure are
different questions; **consequence** is a later human-owned
judgment. [SC-16] owns lane contents, defaults, evidence classes,
replay requirements, and authority rules.

- **Exposure geometry.** The resolved graph supports three
  projections of one relation: *reach* (is this definition
  attributable to stated intent — landed as [COV-*]), *scatter* (how
  many places does one constraint route to — the locality signal;
  computed once, not yet landed, and requiring the
  declared-cross-cutting refinement so universals are not
  false-flagged), and *concentration* (how many constraints does one
  place answer for). Concentration's support is one ad hoc
  self-corpus observation with no prospective or external
  validation: its single run flagged the same two modules an
  eight-review architecture audit had flagged by judgment. Zero new
  concepts; one graph.
- **The instrument must see motion, not just state.** Alignment
  measurement does not prove liveness: code, tests, and theory can
  all verify true while a decision point in a caller routes
  production around the aligned code — every tool in the ladder
  green, the code dead in practice. The stated resolution direction
  is recurrent, human-validated discovery extended to surface
  decision points as deterministic candidates ([THEORY-7], drift
  falsifier); recorded as direction, not capability.
- **Adoption has two phases and an ecological footprint.** Phase
  one, corpus-shaping (specs with stable IDs, contracts out of
  prose), has one owner-reported observation: at SimpleBroker,
  about 1.5 agent-assisted days; bugs were found; the owner judged
  the phase net positive. This is one sympathetic adopter's report,
  not an efficacy test. Phase two, tool-wiring, remains unexercised
  outside the self-corpus. And the tool assumes — where absent,
  induces — a documentation architecture in which the
  machine-checkable contract lives in specs rather than the human
  entry surface: the fleet's layered-docs architecture co-evolved
  with this adoption pressure. An adopter should know they are
  buying that architecture. A non-inline mapping carrier (a mapping
  table) is an honestly *unexplored* alternative and the named first
  mitigation if phase-one cost bites externally.
- **The bootstrap loop is a standing rhythm, not a one-shot.**
  Deterministic candidates, human dispositions carrying the
  authority, nothing model-selected — run recurrently, because a
  one-time bootstrap cannot catch drift that postdates it.

## Core concepts and ownership [THEORY-4]

| Concept | Meaning at theory altitude | Relevant contract owner(s) |
|---------|---------------------------|----------------------------|
| Spec section | An articulated portion of the theory, stably addressable | [SC-*] |
| Implementation mapping / code backlink | The two directions of an exposure claim | [SC-*] |
| Invariant binding | An exposure claim whose evidence is a test | [INV-*] |
| Deterministic finding | Evidence about exposure existence | [SC-2], [SC-4], [SC-11], [SC-15] |
| Semantic verdict | Evidence about exposure fidelity, evidence-classed, replayable | [SEM-*] |
| `ambiguous` | The bounded packet cannot support a stronger judgment; for section analysis this includes articulation too vague to judge | [SEM-*] |
| Obligation / candidate / disposition | The bootstrap loop's authority chain — candidates advise, humans align | [EVC-*] |
| Suppression | An auditable exception; governed forms bind a declaration and rationale | [EXC-*] |
| Intent coverage | The reach projection with auditable exemption | [COV-*] |
| Policy | The only path from finding to consequence | [SC-15], [SEM-6], [CFG-*], [SC-16] |

## Non-goals [THEORY-5]

The contract tier owns the enumerated refusals in [SC-1], [SC-8],
[INV-6], and [EVC-1]; this file does not duplicate them. Theory-tier
non-goals above those:

- **Not the discipline's organ.** Backstitch operationalizes
  traceability that agent-theory (among other disciplines) demands;
  its market includes repositories maintained by coding agents. It
  is a standalone reader of repositories whose readers may run that
  discipline — the relationship is market and provenance, not
  identity.
- **Not a claim of exercised generality.** Zero-to-one honesty: the
  self-corpus is the only wired deployment; the falsifiers below
  are predeclared, not survived. The account stays narrow until
  first real contact (venue: mm) supplies external-contact
  observations.

## Adopted durable alternatives [THEORY-6]

Six records, owner-ratified 2026-08-08 (crystallization D5); the
litigated register's other seven remain owned by their specs, golden
rules, and lessons. Format stays prose-with-fields pending a formal
record grammar.

**A1 — The zero-warning self-corpus gate is the definition of done,
not a target.** The self-corpus smoke check existed in the first
spec commit; commit `1e9c0d9` ratified the zero-warning
shipped-defect rule ("a self-check that fails on the tool's own
repository is a shipped defect, not an accepted quirk") before
functional reconciliation began. Non-waivable, no residual-risk
budget ([SC-10]; the promotion-strategy machinery exists downstream
of this gate). Reconsider when: a warning class appears that a clean
repository genuinely cannot clear — observable as a suppression
whose honest rationale is "unclearable" rather than "not
applicable."

**A2 — Never guess an edge.** Ambiguity is reported, never resolved
by ranking candidates; [SC-4] owns the resolution ladder and its
severities. The position: errors mean something asserted is false or
unusable as asserted; warnings mean weak but unbroken; no rung emits
a guessed edge. Reconsider when: hand-fixing of inexact-path
warnings at volume shows the exactness requirement itself is the
friction, or an auto-resolution proposal arrives — which contradicts
this record and reopens review, never silently adopts.

**A3 — Gate authority is never overridable by invocation.** A
gating command accepts no caller-supplied laxer policy — three
consecutive adversarial rounds each found and closed an escape hatch
(`--profile`, then `--config`, then pass). [COV-5] owns the accepted
and rejected authority inputs. Reconsider when: any new operational
flag is proposed on a command whose exit code is a gate.

**A4 — A governance tool may not suppress itself.** When the
suppression-registry generator tripped the complexity rule it
governs, the resolution was locality-preserving decomposition, never
self-suppression. Reconsider when: a new generator or governance
tool appears under a rule it enforces — the record is read before
the exception is contemplated.

**A5 — The product must not define its own expected result.** Frozen
gold sets are never regenerated from product output; absent rows
stay in the denominator as capture misses. A migration that deleted
gold rows was rejected and reversed by independent audit as
tautological. Reconsider when: any fixture refresh is proposed as a
"hash refresh" — the proposal reopens review with this record
loaded.

**A6 — Anti-Goodhart coverage.** The target is never 100% coverage;
it is zero *unaccounted-for* definitions. [COV-7] owns the current
anti-Goodhart mechanics. Reconsider when: the external-corpus
falsifier in [THEORY-7] fires — vacuous sections appearing to clear
the ratchet.

## Tensions and falsifiers [THEORY-7]

Six falsifiers and one live tension are recorded below. Only
falsifier 1 has an adoption observation; item 6 records a
self-corpus condition but is not yet a completed falsification test.
Venue for external-contact tests: **mm** — every fleet repository is
owner-authored, and mm holds the most non-owner code, making it the
closest available approximation of external contact. Weft remains
the design-time reference target.

1. **First-contact adoption cost** (one phase-one observation,
   favorable, sympathetic adopter). Falsified if adoption demands a
   full corpus restructuring before value lands. Observable on mm:
   no bounded corpus slice yields a reviewable result until the full
   applicable contract corpus is restructured. First mitigation
   before declaring falsification: the unexplored mapping-table
   carrier.
2. **The two-lane boundary under real use.** Falsified from either
   side: pressure to let model verdicts gate directly, or semantic
   findings never promoted into policy at all.
3. **Repeatability under provider drift.** Falsified if verdicts
   flip on re-evaluation with unchanged packets, or epoch churn
   degrades "repeatable" to "repeatable until the provider ships."
4. **Articulation convergence.** `ambiguous` rates must decline as a
   corpus matures. The mm adoption plan must predeclare the
   eligible-section denominator, maturity checkpoints, and decline
   threshold; otherwise this falsifier is not scored.
5. **Anti-Goodhart on a non-self-authored corpus.** [COV-7]'s
   economics assumed a good-faith author; falsified if ratchet
   pressure produces spec text that restates code signatures.
6. **The self-corpus paradox** — a historical live tension, not yet
   a falsifier. A 2026-07-16 build exceeded the then-normal 10 MiB
   aggregate packet ceiling. The applied ceiling is now 40 MB, and
   the 2026-08-05 record shows a complete 111-packet,
   33,373,837-byte preflight. The surviving test is whether the
   tool's own corpus can complete its semantic lane under the
   applied packet contract after mapping refinement.
7. **The gut falsifier: undetected drift** (owner, 2026-08-08). D1
   is falsified by the silent false negative — code or theory
   changed meaningfully and Backstitch didn't flag it. Observable: a
   human audit, production incident, or independent detector
   establishes in-scope drift for which the applied Backstitch run
   emitted no finding. The instrument held to its own severity
   philosophy: claims rot silently, contracts fail loudly, and the
   thesis dies the day the instrument rots silently. Canonical blind
   spot: routed-around alignment (all four ladder tools green, a
   decision point bypassing the aligned code in production).
   Corollary: discovery runs recurrently with human validation;
   decision-point discovery is the named direction.

## Founding continuity [THEORY-8]

Three facts, with the narrative primary sources in the agent-theory
hub's lore tier (entry
"2026-07-29-backstitch-readme-dialogue-founding-text", cited by
name):

1. **Docs led substantive implementation**: the first spec commit
   also added a minimal CLI/package skeleton; the founding plan and
   specs preceded the functional four-way reconciliation.
2. **The implementation was born from the 2026-07-01 four-way
   bake-off through its 2026-07-02 reconciliation**, and that event
   seeded the discipline's verification doctrine — the hub's
   2026-07-02 lessons fold distills the observed failures (four
   agents, same baseline, all passing automated gates while
   diverging on everything unchecked, each violating its own
   declared contract somewhere) into its Golden Rule 13, engineering
   principles §12/§13, testing patterns, and the
   adversarial-acceptance-probes runbook. The full incident record
   is this repository's own lessons ledger.
3. **The identity was articulated in dialogue, twice, and revised
   once.** The founding plan's wager (2026-06-18 — deterministic
   first, model strictly downstream, deliberately narrow) survived
   intact into [SC-16]. The 2026-07-29 founding message was
   composite: the owner supplied the practice description and risk
   diagnosis; pasted text from an external naming exchange supplied
   the thesis sentence, nine possession questions, and iterative
   loop, coined there by another agent in reply to the owner and
   then adopted by the owner. Naming followed practice and did not
   come from the practitioner. That session's README vision draft
   never landed; crystallization D6 retains it only as source
   material for a separate later README unit, and D1 supersedes its
   corpus-substrate spine. The 2026-08-08 revision (D1) superseded
   the "falsify Naur" framing in place.

## Revisions [THEORY-9]

(None yet — this is the initial account, drafted from
crystallization decisions D1–D6. Revisions append here as
[REV-THEORY-NNN] records and gate on the human owner.)
