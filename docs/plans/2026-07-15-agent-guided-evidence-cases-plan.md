# Aligned Intent To Executable Gate Plan

Status: implemented in report-only form with explicit qualification stops.
Slices 0 through 9 are complete within that narrowed claim. Semantic-policy
qualification, pinned-runner performance qualification, and a current rerun of
bootstrap/discovery product qualification remain unavailable pending the
evidence named below. The worktree is uncommitted and is not ready to land.
Prior PASS records remain historical evidence for the exact bytes and authority
models they reviewed, not approval of later revisions. The governing EVC and
SEM specs move to `Status: Active` only as part of the hashed coordinated
package below.

Plan type: implementation with spec revision.

Class: 5 (normative product and public-interface change), with class-4
hardening because the same core must serve CLI, packet generation, replay, CI
policy, and optional MCP without creating a second source of authority.

Risk level: high and boundary-crossing.

## Goal

Help a repository turn aligned intent into an executable gate.

Backstitch identifies obligations in specs and invariants, shows the evidence
the repository explicitly traces to each obligation, discovers deterministic
candidate evidence that is not yet traced, and advises humans or agents how to
close alignment gaps. Humans remain the final arbiters by editing and reviewing
the repository's specs, mappings, code backlinks, invariant bindings, tests,
and skip annotations. Backstitch then compiles that source-declared alignment
into deterministic evidence packets and runs the existing semantic gate.

The core product is a read-only analyzer of repository source. "Read-only"
means Backstitch never changes spec or code source and never creates a second
evidence-authority manifest. Existing commands may still write requested
reports, packets, and caches to explicit artifact paths. Those artifacts are
derived output and never override current source declarations.

## Product Model

The public nouns have one job each:

| Noun | Meaning | Authority |
|---|---|---|
| obligation | Intent that can be checked: a spec section or invariant | Repository spec/invariant declaration |
| evidence link | A reciprocal mapping, backlink, bind, or binding-test relation that the repository declares relevant | Human-reviewed repository source |
| candidate | A deterministic discovery result that may be relevant but has not been ratified | Advisory only |
| skip | A reasoned source annotation that disposes an obligation without claiming conformance | Human-reviewed repository source |
| evidence packet | Exact source-derived material sent to analysis or replay | Derived, content-addressed artifact |
| gate | Alignment readiness plus semantic evaluation and policy | Backstitch computation over current source |

The product has a repeatable bootstrap phase, a human-owned bridge, and a gate:

```text
bootstrap (repeat against the current tree)
  obligation X -> plausible code/test candidates + trace state + guidance
               -> human disposition
               -> human-reviewed source declarations

gate (derive from current source, never from the candidate report)
  obligation X -> readiness -> deterministic evidence packet
               -> analyze / verify / policy
               -> executable gate result
```

Discovery does not establish alignment. A model suggestion does not establish
alignment. A committed packet does not establish alignment. Human-ratified
source declarations establish alignment; Backstitch checks and compiles them.

## Requested Outcomes

- A new user can run the CLI without MCP, list obligations, understand which
  intent is aligned, inspect exact declared evidence, find likely missing
  evidence, and receive concrete trace guidance.
- `backstitch guide alignment` and a thin repository skill teach the same
  bootstrap loop and supported source annotations without becoming a second
  normative contract.
- If measured benefit justifies Phase D, an agent can use the same read model
  through a local stdio MCP server. MCP is an optional context-efficient
  adapter, not a prerequisite or a more powerful authority surface.
- `backstitch obligation ID --summarize-evidence` points to exact current code
  and test references that participate in the reciprocal trace graph.
- `backstitch obligation ID --find-evidence` returns deterministic candidates,
  each with its trace state, discovery basis, existing relations, exact receipt,
  and suggested source annotations. It never edits the repository.
- Candidate discovery is a refreshable current-tree report. Re-running the same
  command on the same snapshot is byte-stable; running it after source changes
  exposes new, removed, moved, newly traced, partial, and conflicting
  candidates. Saved candidate output is never gate authority.
- A human adds or removes evidence by editing the existing spec mapping and
  code backlink forms, then running Backstitch to see whether reciprocity and
  readiness are satisfied.
- A skip is authored in source, parsed, audited, and reported by Backstitch.
  There is no `skip` or `unskip` source-mutating command in v1.
- Evidence packets are fully derived from the current source snapshot. There
  is no proposal JSON, activation step, active-case manifest, deactivation
  lifecycle, or agent-authored evidence authority.
- CI can distinguish identified intent, aligned intent, source-authored
  disposition, executable current-source gates, artifact currentness when an
  artifact is addressed, and blocked evaluation with stable machine-readable
  states and exit behavior.
- Candidate quality, alignment completion, semantic quality, interaction cost,
  and maintenance cost are measured separately before policy promotion.
- The gate takes the human decisions expressed in current source, not hidden
  candidate labels or an earlier discovery report, and reports whether the
  resulting current packet appears to support the obligation.

## Source Documents

- `docs/specs/07-verification-and-evidence-cases.md` [EVC-1] through [EVC-12]
  (rewritten proposed contract requiring coordinated promotion before
  implementation)
- `docs/specs/06-semantic-gates.md` [SEM-1] through [SEM-10]
- `docs/specs/08-intent-coverage.md` [COV-6], [COV-7], [COV-9]
- `docs/specs/02-backstitch-core.md` [SC-4], [SC-5], [SC-6], [SC-7],
  [SC-8], [SC-10], [SC-13], [SC-15], [SC-16]
- `docs/specs/03-backstitch-configuration.md` [CFG-3], [CFG-5], [CFG-6],
  [CFG-8], [CFG-9]
- `docs/specs/04-backstitch-traceability-exclusions.md` [EXC-4], [EXC-6],
  [EXC-7], [EXC-8]
- `docs/specs/05-backstitch-invariants.md` [INV-3], [INV-5], [INV-7], [INV-9]
- `docs/agent-context/runbooks/designing-agent-facing-interfaces.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/implementation/07-deterministic-semantic-gate.md`
- `docs/plans/2026-07-11-deterministic-semantic-gate-plan.md` dogfood and
  eight-case semantic baseline evidence

## Spec Baseline

- Historical proposed EVC baseline commit:
  `25346a988ad2022237160261aa61d2692d5baaa4`.
- Historical EVC file SHA-256 at that commit:
  `3df5b8eb9391ba98400aa8736f1c99d67082c97278ef371f9b85560ab52b43f1`.
- Independently reviewed rewritten proposed EVC SHA-256:
  `3f4919a6d967b0c4b4758060fbec657a081d38399d98cbf24baa900b497c462f`.
- This product-fit revision starts from that reviewed EVC and reopens review for
  [EVC-10], [EVC-10.1], [EVC-10.2], [EVC-12], and the plan sequencing. The
  pre-review revised EVC SHA-256 is
  `b2fa8888a04347879d01ac8382f5c4673a87df6306e91bc11c450669feb8bfc2`.
- Independently reviewed product-fit EVC SHA-256:
  `2c26c6443aa23bb69e76145056c153cc03089e2f7a153cb4fea46d97992422c9`.
- Independently reviewed product-fit plan pre-record SHA-256:
  `0ad0726923ee075b5bd4955d259ec2188f6f2e75fc40fb864d2cee2b73dc63ad`.
- Independently reviewed verifier-role EVC SHA-256:
  `b4170553afbd2785f5ef8f7e312f368f94a61c057a137901e32dc48ed967ac3a`.
- Independently reviewed verifier-role plan pre-record SHA-256:
  `31fee499989f64a83d5ed803e4836cad48185df40e83a7c2be4301273d672f92`.
- Prior plan SHA-256 before this review:
  `54b870bb43bd29a20d5031135ea0e2415c40d3582d90b816a07d5a5836430860`.
- The historical EVC baseline is tracked at the commit above. The rewritten
  EVC is an uncommitted modification and this plan is untracked. The worktree
  also contains broad user-owned semantic-gate changes. Every implementation
  slice must inspect its target diff and stop if ownership is ambiguous.
- Promotion baseline: pending. No code may cite the revised EVC behavior until
  the spec-revision review and spec-promotion slice complete.

## Superseding Review Pass: Aligned Intent As Authority

Date: 2026-07-15.

Review target: the then-current EVC spec and plan, judged against the product
statement "Backstitch is for helping turn aligned intent into an executable
gate" and the agent-facing interface runbook.

Verdict: `REVISE`. The prior design had useful deterministic machinery, but
its central authority model was wrong. It made a committed active evidence
case the evidence authority and treated the repository trace graph as a weaker
fallback. That creates a second authoring system and lets a repo pass without
the explicit spec-to-code links Backstitch exists to make executable.

| Priority | Finding | Plan disposition |
|---|---|---|
| P1 | The main flow was discovery to agent proposal to activation to active case. That makes a reviewed proposal, not aligned repository intent, the gate input. | Replace it with discovery to source edits to alignment validation to derived packet to gate. |
| P1 | Proposal selections and reasons formed a second evidence-authoring language even when labeled untrusted. | Remove proposal JSON and its validation contract. Source mappings, backlinks, binds, tests, and skips are the only authored alignment records. |
| P1 | `activate`, `deactivate`, immutable case objects, and an active manifest created persistence, conflict, cleanup, and authority machinery not required by the product. | Remove the entire lifecycle. Preserve content addressing only for derived packets, caches, and replay artifacts. |
| P1 | Case mode was stronger than trace mode, so complete source traceability remained second class. | Replace both modes with one aligned packet mode. Incomplete alignment is not a weaker successful packet mode; it is explicit non-executable readiness unless policy permits a report-only bootstrap run. |
| P1 | Backstitch-authored `skip` and `unskip` crossed the source-authoring boundary. | Parse, audit, explain, and validate source-authored skips. Return exact guidance, but perform no source mutation. |
| P1 | The design lacked explicit bootstrap and readiness states. | Add `intent_state`, `alignment_state`, and `gate_state` with closed transitions and machine-readable blocking reasons. |
| P2 | The interface lacked the human's key read: a concise list of the exact evidence currently ratified by repository source. | Add `--summarize-evidence` as the primary evidence read. |
| P2 | Candidate discovery did not make trace failure explicit enough. | Every candidate reports `trace_state`, exact existing relations, and structured trace guidance. An untraced candidate is advisory unless a declaration is broken or a closed readiness rule requires it. |
| P2 | A skipped obligation became too opaque. | Keep summary, declared-evidence, candidate discovery, and trace guidance available while semantic evaluation is skipped. |
| P2 | The old plan duplicated the user's mental model across obligation, proposal, case, manifest, universe, and lifecycle verbs. | Keep `obligation` as the public aggregate. Candidate and packet are drill-down/derived nouns; remove public proposal and lifecycle nouns. |
| P2 | The plan could preserve complex case machinery because it was already specified in detail. | Reject sunk-cost reasoning. Reuse snapshot, receipt, candidate, packet, cache, verify, eval, and policy work only where it still serves source-derived alignment. |

Steelman of the rejected design: a committed active case is reviewable and can
freeze exact evidence for deterministic CI replay. The defect is not lack of
review. The defect is authority duplication. A derived packet can preserve the
same exact bytes and hashes without letting a second manifest decide which
code implements the spec.

## Product-Fit Review Pass: Staged Qualification

Date: 2026-07-15.

Review target: the rewritten aligned-intent EVC and plan, evaluated against the
outside reviews, the shipped semantic-gate dogfood evidence, the agent-interface
runbook, and the product question: can Backstitch become a dependable gate for a
highly conforming repository without making stochastic judgment look
deterministic?

Verdict: `REVISE`. The product direction is sound, but the plan deferred its
largest product uncertainties until after most implementation and made one
performance proof circular.

| Priority | Finding | Disposition |
|---|---|---|
| P1 | [EVC-12.1] requires [COV-6] reconciliation, but the plan omitted COV from source documents, promotion, and final reconciliation. | Add COV to every coordinated-spec list. Reconcile vocabulary and dependency only; implementation of the coverage ratchet remains a separate plan. |
| P1 | The dependency graph had slices but no owner-visible stop/continue gate after the deterministic obligation/discovery wedge. | Add independently stoppable product phases. Qualify obligation/readiness and discovery before packets, MCP, or stronger semantic policy. |
| P1 | Bootstrap economics and candidate usefulness were first measured in the late eval slice. | Dogfood the core CLI and discovery early. Record time/calls/source changes to first executable obligation, candidate dispositions, first-reviewed-diff correctness, and public-help-only completion. |
| P1 | The plan still treated the old literal trace-removal mutation as a semantic critical case after [EVC-12.1] moved it to deterministic readiness. | Require 100% deterministic detection with zero provider calls; replace the semantic control with a syntactically valid but substantively vacuous reciprocal trace. |
| P1 | EVC required the final runner job and hard performance proof before implementation existed. | Keep the scale fixture and ceilings, but treat them as provisional design targets at spec promotion and hard acceptance ceilings once the relevant operation and comparable runner baseline exist. |
| P2 | The existing eight synthetic semantic cases establish a useful baseline but are too small for stronger policy. | Preserve that evidence; require at least 20 reviewed historical misalignment units plus synthetic controls before semantic policy promotion. |
| P2 | MCP could be implemented after the CLI without proving that its maintenance cost buys agent efficiency. | Keep MCP independent of semantic success, but require a stable CLI read model and measured call/byte/context cost showing a concrete adapter benefit. |

Rejected or narrowed review claims:

- The aligned-intent EVC does not need another authority-model rewrite. It
  already removes cases, activation, manifests, and source-mutating commands.
- The existing semantic dogfood is real evidence: 59 packets/results, exact
  cache replay, two trials over four positive and four negative cases, precision
  1.0, false-positive rate 0.0, and recall 0.75. It supports report-only use and
  identifies the missed control; it does not authorize stronger policy.
- The immutable repository snapshot remains shared by readiness, discovery,
  packets, and current analysis. Local agent use does not remove concurrent
  checkout mutation, so localizing capture to `analyze` would reintroduce torn
  source moments.
- MCP does not depend on semantic-model quality. Its gate is stable read-model
  parity and measured context benefit.
- File-size reduction is not a contract goal. Cohesion, explicit ownership, and
  executable boundaries matter; an arbitrary percentage shrink does not.

## Verifier-Role Review Pass: Procedural Independence

Date: 2026-07-15.

Review target: [EVC-3], [EVC-5], and [EVC-10.1], judged against [SC-16]'s
promise that Backstitch makes probabilistic semantic review repeatable,
diffable, auditable, and improvable rather than approximating a proof oracle.

Verdict: `REVISE`. The blinded falsification stage is useful, but two remaining
rules treated model diversity as a source of authority without measuring the
exact pipeline property the product depends on.

| Priority | Finding | Disposition |
|---|---|---|
| P1 | [EVC-3] said qualification must measure correlated failure even though [SC-16] defines a repeatable CI process, not an ensemble oracle. | Delete correlation as a qualification goal. Define independence as reason-free input, adversarial prompt, and separate request/event/cache identity. |
| P1 | [EVC-5] rejected an analyzer/verifier provider-model tuple match. A different tuple is only a diversity heuristic and does not prove independent errors. | Permit equal or distinct tuples. A distinct tuple is optional and grants no evidence-class or policy advantage. |
| P2 | “Repeatable” alone could bless a stable rubber stamp or stable abstainer. | Require the exact composed pipeline to pass committed-corpus precision, recall/sensitivity, all-critical, indeterminate, flip, and replay gates. |
| P2 | Mandatory distinct provider configuration duplicated model and cost identity even when one adversarial pass over the same model was intended. | Add one all-or-nothing `provider_source`: reuse analyze's complete resolved provider/cost descriptor by default or supply one complete override. No field-level fallback. |
| P1 | Reusing each configured verifier epoch across evaluation trials could turn a second stochastic primary into a cache hit and understate uncached flips. | Keep configured epochs in stable composition, derive a distinct content-addressed effective verifier epoch per trial, retain both epochs in events, and require cold primary plus cache-only replay counters. |

Counterarguments retained as explicit boundaries:

- A distinct verifier model may catch a different blind spot. That is a valid
  optional experiment, but its value is established only by qualification of
  the exact composed configuration, not by tuple inequality or correlation.
- Same-model analyze and verify may share blind spots. This lowers measured
  sensitivity rather than changing evidence authority; advisory defaults,
  recall floors, critical cases, and policy selectors contain the risk.
- Temperature zero does not guarantee deterministic hosted inference. Trials,
  uncached flip bounds, immutable cache identity, and zero-call replay remain
  mandatory.

## Proposed Spec Delta

The rewritten proposed EVC is the implementation target only after coordinated
cross-spec promotion. Its revision closes these changes as one contract,
including schemas, ordering, budgets, diagnostics, exits, and acceptance
probes:

| Spec area | Required revision |
|---|---|
| [EVC-1] Purpose | Define Backstitch as an aligned-intent compiler and gate, not an evidence-case authority service. |
| [EVC-2] Flow | Replace proposal and activation with source-declared alignment, readiness, derived packet construction, and gate execution. |
| [EVC-3] Verification | Retain blinded adversarial verifier semantics, make its input a source-derived packet, define independence as procedural rather than statistical, and keep verifier judgment separate from alignment authority. |
| [EVC-4] Artifacts | Remove proposal schema, active manifest, case object, case ID, case hash, and activation conflict contracts. Define a derived evidence-packet artifact and optional replay receipt whose identity is recomputable from source. |
| [EVC-5]/[EVC-6] Evaluation and policy | Permit equal or distinct analyzer/verifier tuples; resolve provider identity through exact analyze reuse or a complete override; retain separate verifier request/event identity and policy projection. Semantic success cannot make an unaligned obligation executable. |
| [EVC-7] Discovery | Retain captured-snapshot candidates, receipts, static relations, fixed ordering, budgets, and conservative relation language. Add `trace_state`, discovery basis, and structured trace guidance. |
| [EVC-8] Interface | Keep the obligation-first CLI. Remove proposal validation, activation, deactivation, skip, and unskip. Add `--summarize-evidence`; make CLI and MCP source-read-only and action-guiding. |
| [EVC-9] CI | Replace case/trace mode selection with current-source alignment readiness, repo-addressed packet derivation, end-of-run snapshot recapture, explicitly historical artifact replay, semantic execution, and policy. |
| [EVC-9.1] Packet | Remove case identities and agent decisions. Bind exact requirement, declared implementation/test evidence, deterministic candidate counterevidence, trace state, and source snapshot identity. Close `current` versus `historical_snapshot` report authority. |
| [EVC-10]/[EVC-10.2] Measurement | Define exact configuration-level analyzer and verifier composition objects and hashes, excluding per-packet/claim/trial/operational data. Keep configured verifier epochs in composition, but derive and record a distinct effective epoch per corpus/trial/base-epoch tuple so every stochastic primary is cold and its replay addresses the same object. Measure obligation discovery, alignment completion, candidate trace-state precision, evidence sufficiency, exact composed-pipeline precision/sensitivity/stability/replay, interaction cost, authoring cost, and maintenance churn separately. Do not measure cross-model correlation or award tuple diversity. Add independently stoppable obligation, discovery, packet/currentness, optional MCP, and semantic qualification stages. |
| [EVC-11] Anti-gaming | Require source-declared reciprocal trace, show untraced candidates, forbid derived artifacts from overriding source, and prevent semantic analysis from laundering incomplete alignment. |
| [EVC-12] Verification | Replace proposal/case/source-edit probes with bootstrap, source-authority, no-mutation, guidance, readiness, derived-packet, conditional CLI/MCP parity, replay, and policy probes. |

Required integration deltas:

- [SC-5]/[SC-8]/[SC-16]: register the final obligation commands and conditional
  MCP command, preserve lazy LLM imports, and state that no obligation
  operation edits repository source. Define verifier independence as procedural
  and replace SC-16's stale calibration sentence with exact corpus- and
  inference-bound counts, rates, confidence bounds, and pass checks; prohibit a
  blended correctness percentage or calibrated model score.
- [SC-6]/[SC-7]/[SC-10]/[SC-13]: adopt the revised packet schema and ensure
  packets are source-derived.
- [SC-15]: allocate only diagnostics still needed after the case lifecycle is
  removed. Do not reserve dead case-manifest codes.
- [CFG-3]/[CFG-6]/[CFG-8]: define discovery, alignment-role, packet-budget,
  verifier `provider_source`, complete provider override, and eval
  configuration. Remove case-root, manifest, proposal, and activation settings.
- [EXC-4]/[EXC-6]/[EXC-7]/[EXC-8]: retain source-authored skip grammar and
  audit behavior, but remove Backstitch source-editing behavior.
- [INV-5]/[INV-9] and [SEM-3] through [SEM-9]: update packet, replay,
  adversarial verification, analyze-provider reuse, optional provider override,
  configuration-level composition identity, and self-acceptance references.
- [COV-6]/[COV-9]: remove broker/proposal/activation/frozen-case vocabulary,
  consume obligation discovery as advice whose accepted outcome is an ordinary
  human-reviewed source diff, and test deterministic worklist/source-diff
  outcomes instead of proposal objects. Leave the COV ratchet implementation
  to its own later plan.

At coordinated promotion, replace [COV-6] with this exact contract text (normal
Markdown, not the blockquote markers used here for review):

> The uncovered-definition report is a worklist owned by intent coverage. It
> does not create an evidence broker, proposal store, activation state, or
> evidence case. A human or agent may use [EVC-8]'s read-only obligation list,
> evidence summary, and candidate discovery to inspect related intent and
> source, but those reads cannot ratify a classification or source relation.
>
> For each deterministically ranked uncovered definition, the reviewer chooses
> one outcome: `needs-spec`, `glue`, `dead`, or `contradicts-spec`.
> `needs-spec` proposes ordinary spec text plus reciprocal source declarations;
> `glue` proposes a reasoned [COV-4] exemption; `dead` proposes source removal;
> and `contradicts-spec` identifies the existing obligation and proposes a
> corrective source diff whose semantic effect can be evaluated through the
> ordinary current-repository gate. Backstitch may show exact supported
> annotation forms, but it does not apply any proposal.
>
> Only a human-reviewed source diff changes coverage or alignment. After that
> diff lands, the resolver and coverage computation recompute from repository
> source. Rejected advice creates no durable product state. The loop continues
> until the worklist is empty or the owner records a bounded stop decision.
> The coverage runner owns ranking; the human reviewer owns disposition;
> [EVC-8] owns obligation reads and guidance. Verification reruns coverage and
> the reciprocal trace gate from current source. The required action is to land
> or reject an ordinary source diff, never to activate tool-owned state.

At the same promotion, replace [COV-9]'s existing `` `uncovered_next` ranking
is deterministic for a fixed repository state`` bullet and its immediately
following `loop proposals carry their served evidence` bullet with these exact
bullets. Preserve the later drift and diagnostic bullets unchanged:

> - the uncovered-definition worklist ranking is deterministic for a fixed
>   repository state; repeated runs return the same definition identities and
>   ranking facts; and
> - for each `needs-spec`, `glue`, `dead`, or `contradicts-spec` disposition,
>   only an ordinary landed source diff changes coverage or alignment;
>   rejected or no-diff advice leaves both unchanged, and no proposal or
>   activation object exists.

Promotion strategy: C for the new EVC file while it remains a dedicated
planned spec; A for active integration specs. Independently review the full EVC
draft, then update every active integration spec named by [EVC-12.1] in one
coordinated promotion. Change EVC prose status only with those reconciliations,
record the exact promotion baseline, and keep its planned scanner rung until
mappings and code land together. Do not implement against this plan's summary
as a substitute for the proposed spec.

## Public Interface

The CLI is sufficient for humans, scripts, and CI:

```text
backstitch obligation list
backstitch obligation ID
backstitch obligation ID --summarize-evidence
backstitch obligation ID --find-evidence
backstitch obligation ID --candidate CANDIDATE_ID
backstitch guide alignment
backstitch check
backstitch analyze --repo-root PATH
backstitch analyze --packets PATH --packet-report PATH
backstitch mcp --repo-root PATH  # only when Phase D is implemented
```

`obligation list` is also the bootstrap report. Its one paginated `entries`
array is ordered by `(path, start_line, entry_type, identity)` and contains
either an addressable `obligation` row or an `unaddressable_intent` row. The
latter carries the existing canonical diagnostic identity, source location,
bounded excerpt, and repair action for text that has no unique supported
obligation ID. A repository with no discoverable spec intent succeeds with an
empty array, `bootstrap_state = "no_intent"`, and a guidance action. Valid but
untraced obligations are ordinary obligation rows with
`alignment_state = "untraced"`; they are never hidden as bootstrap issues.

The default `obligation ID` response is a compact current-source orientation
record. It names the obligation, source location, kind, alignment state,
independent skip disposition, gate readiness, counts by evidence role and
candidate trace state, blocking reasons, source snapshot identity, and next
actions. It does not inline snippets and makes no artifact-currentness claim.

`--summarize-evidence` returns exact source-declared evidence rows. Each row
includes role, canonical path, owner, start/end lines, relation kinds,
reciprocity state, receipt hash, and a short excerpt. It returns broken or
one-sided declarations as explicit evidence-state failures rather than hiding
them.

`--find-evidence` returns a bounded, ordered candidate list. Each candidate
includes:

- `candidate_id` and exact receipt
- kind, path, owner, and span
- deterministic discovery basis and static relation claims
- `trace_state`: `declared`, `partially_declared`, `untraced`, or `conflicted`
- existing spec mappings, code backlinks, binds, and test relations
- `suggested_trace_edits`: structured advice naming the exact supported
  annotation forms and target IDs, never an applied patch
- one mandatory guidance action

`--candidate` returns full snippet and neighbor detail for one discovery-minted
candidate. It never accepts an arbitrary path as a substitute identity.

The default obligation detail already computes per-obligation readiness, so v1
adds no second `obligation ... check` grammar. Existing `backstitch check`
remains the deterministic repository-wide alignment gate. The current semantic
gate is `backstitch analyze --repo-root PATH`: it captures the current source,
derives readiness and packets internally, runs analysis/verification/policy,
then recaptures and compares source identity before publishing a
current-conformance result. A changed checkout aborts the current result as a
tool failure with no current policy claim.

Existing artifact-addressed `backstitch analyze --packets PATH` remains a
snapshot replay surface for compatibility. It validates the packet report and
exact packet bytes, labels its report `scope = "historical_snapshot"`, and may
judge only that frozen snapshot. It cannot claim a current repository gate or
project current-source policy. `packets` remains the explicit derived-artifact
surface and records the source snapshot needed to validate replay. Packet-only
`summarize-analysis` remains historical for the same reason. The spec revision
closes CLI compatibility, mutually exclusive arguments, reports, exits, and
migration guidance for these two analyze modes.

`backstitch guide alignment` returns the installed, versioned quick start for
the human/agent bootstrap loop, supported mapping/backlink/invariant-target/
binding-test/skip forms,
and public commands. `skills/backstitch-alignment/SKILL.md` is a thin workflow
adapter that tells an agent when to call those reads and when to hand source
changes back for review. It points to the installed guide and current command
help; it does not duplicate schemas or normative rules.

No public v1 commands named `proposal`, `validate`, `activate`, `deactivate`,
`skip`, or `unskip` are added.

If Phase D is implemented, MCP exposes the same read core with
self-explanatory tools:

```text
list_obligations
get_obligation
summarize_obligation_evidence
find_obligation_evidence
get_obligation_candidate
```

That adapter also exposes the installed guide as the static
`backstitch://guides/alignment` resource. Tool and resource descriptors carry
their installed version and content hash so stale agent guidance is visible.

`backstitch mcp --repo-root PATH` then starts a local stdio server pinned to one
allowed root. Every MCP repository call also carries `repo_root`; it must
resolve to that allowed root. No hidden session setup is required. MCP may
cache immutable indexes by snapshot hash inside the server process, but every
response identifies the snapshot and no caller relies on a prior call. MCP
performs no network/provider call and no repository-source write. A deferred
Phase D ships none of this surface.

## Readiness Model

The revised spec closes the exact states and transitions. Its model is:

| Fact | Values | Meaning |
|---|---|---|
| `intent_state` | `identified` | An addressable obligation has one unique supported declaration and canonical ID. Parser or identity defects remain `unaddressable_intent` list entries instead of synthetic obligation states. |
| `alignment_state` | `untraced`, `partial`, `complete`, `invalid` | Required reciprocal implementation/test/bind roles are absent, incomplete, complete, or malformed. This fact is computed even when skipped. |
| `disposition` | `evaluate`, `skipped` | Source policy requests evaluation or carries one valid reasoned skip. It never replaces alignment facts. |
| `obligation_rung` | `active`, `planned`, `exploratory`, `meta` | Existing profile and traceability classification decides whether the obligation participates in the current gate. |
| `gate_state` | `not_executable`, `executable` | Current source cannot run or can run. Capture, config, and tool failures remain top-level operation problems instead of synthetic obligation states. This is readiness, not an analysis verdict. |

Artifact-addressed operations add a separate `artifact_currentness` fact with
`current`, `stale`, or `unverifiable`, plus independent `artifact_integrity`
with `valid` or `corrupt`. They may report `current` only after an explicit
repository address is captured and compared with the artifact's source
snapshot. Packet-only replay has
`artifact_currentness = "unverifiable"` relative to any present checkout and
uses `scope = "historical_snapshot"`. Semantic classifications, verifier
results, policy diagnostics, and exit status remain the execution result; they
are not folded into readiness state.

Role requirements must be explicit and kind-specific. Minimum v1 rules:

- a section obligation requires at least one valid reciprocal implementation
  relation; whether it requires a direct test relation is a closed configured
  policy surfaced in the response, never an ambient assumption
- an invariant requires its declaration, bound target, and binding-test
  relation according to [INV-5]
- malformed, missing, duplicate, one-sided, or stale source declarations make
  alignment `partial` or `invalid` with exact repair guidance
- a valid source-authored skip sets `disposition = "skipped"` while preserving
  `alignment_state`, remains in totals, never counts as covered or verified,
  and suppresses only semantic evaluation
- evidence summary and candidate discovery remain available for skipped
  obligations
- an untraced discovery candidate is an advisory fact, not automatically a
  gate error; it becomes blocking only through a closed readiness rule or when
  it exposes a broken declaration
- semantic model output cannot upgrade `untraced`, `partial`, or `invalid`
  alignment, or a skipped disposition, to an executable current-source gate

## Current Structure And Reuse

| Existing seam | Reuse |
|---|---|
| `backstitch/check_pipeline.py`, `backstitch/target_roots.py`, `backstitch/config.py` | Keep repository discovery/config ownership, but make the pipeline capture one immutable byte view before parsing or resolving. The public wrapper constructs the snapshot, then delegates to the pure snapshot consumer. |
| `backstitch/markdown_specs.py`, `backstitch/models.py`, `backstitch/resolver.py` | Keep canonical obligation IDs, mappings, backlinks, binds, and reciprocal graph semantics as the authority model. Refactor file access so these owners consume only bytes from the captured view during one operation. |
| `backstitch/code_parser.py`, `backstitch/python_refs.py` | Extend the existing tree-sitter boundary for conservative candidate discovery. Static relation never claims runtime reach. |
| `backstitch/reporting.py` | Reuse deterministic issue and policy framing; do not build a second readiness reporter. |
| `backstitch/analysis_packets.py` | Replace the sole packet producer with source-aligned packets. Do not keep case and trace selection algorithms. |
| `backstitch/semantic_packets.py`, `backstitch/semantic_identity.py` | Preserve canonical byte projection and hash ownership while changing the packet fields. |
| `backstitch/semantic_cache.py`, `backstitch/artifact_contracts.py` | Reuse immutable cache/replay contracts. Current source-derived packet identity controls reuse. |
| `backstitch/semantic_analysis.py`, `backstitch/semantic_evidence.py`, `backstitch/semantic_policy.py` | Preserve the provider boundary, evidence reconstruction, and policy separation. Alignment readiness is an earlier deterministic gate. |
| `backstitch/semantic_eval.py`, `backstitch/semantic_eval_reports.py` | Own only the schema-3 semantic corpus, cold-primary/cache-only replay, measured semantic precision/sensitivity, and exact-code policy authority. Bootstrap, discovery, Phase C, and performance retain separate artifacts. |
| `backstitch/cli.py` | Add thin argparse adapters over the transport-neutral obligation core and preserve exit 0/1/2 and traceback-free behavior. |
| `backstitch/settings.py`, `backstitch/defaults.toml` | Add only final closed discovery/alignment/packet settings. Remove all obsolete proposal/case lifecycle settings from the spec before code. |

Proposed module boundary:

```text
backstitch/repository_snapshot.py
  capture/index source bytes once + snapshot identity + byte-only reads

backstitch/check_pipeline.py + resolver.py
  construct snapshot once, then parse/resolve without filesystem rereads

backstitch/obligations.py
  inventory + readiness + declared-evidence summary

backstitch/evidence_discovery.py
  captured snapshot + candidates + receipts + trace-state + guidance

backstitch/obligation_api.py
  canonical transport-neutral result/problem envelopes

backstitch/mcp_server.py
  optional stdio adapter only
```

`repository_snapshot.py` is the sole new source-capture owner. It resolves the
already-configured included paths, opens each source file once under the
existing containment/symlink rules, stores canonical path plus exact bytes and
file metadata, and computes one snapshot identity. Parsers, resolver,
obligation readiness, discovery, and packet construction receive this object
and are structurally unable to reopen repository source. An intentional final
recapture for current `analyze --repo-root` is a second whole snapshot, not a
resolver reread; only the snapshot owner performs it.

Do not introduce separate contract, broker, case, edit, and reference modules
unless implementation proves distinct ownership. Prefer the snapshot owner,
three feature-core modules, and one transport adapter. The installed guide may
be a packaged Markdown resource loaded by the CLI/MCP; it must not duplicate
normative behavior.

## Agent-Interface Review Against The Runbook

| Principle | Revised judgment |
|---|---|
| Context economy | List and default detail orient; summaries, discovery, and candidate detail are explicit. There are no write payloads or lifecycle receipts. |
| Progressive disclosure | Help/reference, list, obligation detail, evidence summary, candidate list, candidate detail. CLI alone teaches the whole path. |
| Self-explanatory names | `obligation`, `--summarize-evidence`, `--find-evidence`, and `--candidate` match the user's task. Internal receipt and relation nouns remain subordinate. |
| One identity per thing | Canonical obligation ID addresses intent; candidate ID addresses one structural discovery; receipt hash addresses exact bytes; packet hash addresses derived model input. No case-series identity exists. |
| Derive what is derivable | Backstitch derives state, candidates, relations, guidance, packets, and hashes. The caller supplies no proposal or trusted locator. |
| No hidden session | Every CLI call uses inspectable cwd/`--repo-root`; every MCP call carries `repo_root`. Snapshot-keyed server caching is transparent. |
| Teach, do not reject | Near misses normalize where safe. Invalid declarations return exact supported source forms and next actions. Advice is not an auto-fix. |
| Every message has an action | Every success, warning, and problem includes one closed guidance action with a firing test. |
| Atomic writes | Not applicable to source. Backstitch performs no source writes. Existing explicit report/cache writers retain their own atomic contracts. |
| Trust boundary | Humans and repository review own alignment. Agents may discover and advise. Backstitch compiles and evaluates. Derived artifacts and model output never confer alignment. |
| Agent-shaped wire format | Responses follow obligation tasks, not parser or storage internals. No generic query language is exposed. |

## Invariants And Constraints

1. Repository source is the only evidence-alignment authority.
2. The existing reciprocal trace contract is reused. No parallel mapping or
   evidence-selection language is introduced.
3. One source-capture owner reads each included repository source file once per
   snapshot. Parsers, resolver, readiness, discovery, and packet construction
   consume that immutable byte image and cannot reread the live filesystem.
4. CLI, packet generation, CI, and implemented MCP call one core and return the
   same canonical result for the same operation and snapshot.
5. Backstitch never edits spec or code source in v1. Suggested annotations are
   advice with exact target IDs and supported forms, not patches.
6. Candidate discovery is deterministic, bounded, conservatively named, and
   source-snapshot consistent. Static relation does not imply runtime reach,
   execution, assertion, or conformance.
7. Every exact snippet and source claim has a receipt over current raw bytes.
8. A derived packet contains all required declared evidence and the closed
   deterministic counterevidence universe. It cannot silently omit a candidate
   because an agent did not select it.
9. Candidate over-approximation cannot make every untraced candidate a gate
   failure. Blocking rules are closed and source-based.
10. Skip disposition is independent of alignment state. Skips remain visible,
   reasoned, auditable, and in denominators; they grant no coverage or semantic
   success and do not hide whether evidence is complete.
11. Alignment readiness precedes semantic analysis. Semantic output cannot
    launder incomplete traceability.
12. Exact packet bytes, prompt identity, provider/model identity, and epochs
    own cache/replay identity. Historical replay is snapshot-scoped. Only a
    repository-addressed derivation plus end-of-run source recapture may claim
    current conformance; stale cache is never current evidence.
13. Verifier independence is procedural: reason-free input, adversarial prompt,
    and separate request/event/cache identity. Equal and distinct
    analyzer/verifier model tuples are both valid and receive no authority
    merely from equality or difference.
14. Stronger semantic policy qualifies the exact composed inference contracts.
    Stability and replay are necessary but insufficient without measured
    precision, recall/sensitivity, and all-critical capture.
15. Each evaluation trial derives distinct verifier event epochs from the
    qualification corpus, trial index, and configured base epochs. Primary
    verification is cold; replay uses those exact trial epochs cache-only.
16. Deterministic commands and implemented MCP cannot import the LLM provider
    or perform a network call. Only existing analyze/eval/doctor provider paths
    may do so.
17. Public enumerable contracts have closed registries and firing tests:
    commands, flags, states, candidate kinds, relation kinds, trace states,
    guidance codes, diagnostics, schema versions, config keys, and exit paths.
18. Every error is traceback-free and carries an actionable repair.
19. No runtime tracing, arbitrary filesystem query, HTTP MCP, or automatic
    source fix enters v1 as an implementation convenience.

## Hidden Couplings And Risk Register

| Risk | Required control |
|---|---|
| Existing packet v2 implementation is already changed in the dirty worktree | Inspect per-file diffs before editing; rebase the plan on actual current ownership and stop on overlap ambiguity. |
| Mappings and backlinks have different parser owners | Build readiness from the existing resolved report, not a new text scan. |
| Multi-file capture can tear while the checkout changes | Compare pre/post file metadata and a repeated inventory for every attempt; discard and retry the whole image up to three attempts; never mix bytes across attempts. |
| Resolver and discovery can read different source moments | `repository_snapshot.py` captures once; `check_pipeline` passes that same object through resolver, readiness, discovery, and packet construction. A test-only post-capture hook mutates the real fixture and proves no consumer rereads it. |
| Candidate discovery can overfit Python syntax | Label relation basis; add negative fixtures; never turn an untraced heuristic candidate into an unconditional error. |
| Full-repo discovery can be slow | Capture/index once per operation; cache only by visible snapshot hash in MCP; enforce deterministic item, byte, and work-unit budgets. A wall-clock deadline may abort the whole operation only. |
| Packet counterevidence can exceed model budgets | Specify deterministic priority, closure, and fail-closed budget behavior in EVC. Never let a model or agent silently trim it. |
| CLI and MCP may drift | Golden canonical core-result parity tests; thin adapters only. |
| Source-authored skips can hide debt | Preserve denominator, audit, effective policy, reason, and evidence inspection. |
| Derived packet files may be mistaken for authority | Include source snapshot and derivation metadata. Packet-only analysis is historical. Current analysis owns repo capture, packet derivation, final recapture, and stale rejection. Deleting derived output loses no alignment decision. |
| A distinct verifier model may be mistaken for stronger evidence | Equal and distinct tuples use the same evidence class and qualification gate; reports bind exact resolved inference contracts and make no correlation claim. |
| Analyze-provider reuse may become hidden field-level inheritance | One closed `provider_source` selects the complete resolved analyze descriptor or one complete override; partial fallback is invalid and firing-tested. |
| Evaluation trials may reuse verifier cache entries and look falsely stable | Derive the effective verifier epoch from the validated corpus digest, configured base epoch, and trial index; store both epochs; require zero primary hits and zero replay calls. |
| A repeated evaluation may inherit verifier objects from an earlier execution | Use a fresh operation-scoped verifier cache staging directory, prove it empty before calls, allow only the immediate replay to read it, and discard it after atomic report publication or failure. |
| Agent guidance can become a second spec | One normative EVC contract; CLI/MCP load one installed guide, the repository skill points to it, and tests bind current command/schema identity. |
| Readiness and existing gate commands can fork | `obligation` detail, `check`, packets, and `analyze` must call the same readiness core; no obligation-specific gate command is added. |

Fatal failures: invalid source declarations, ambiguous obligation identity,
snapshot inconsistency, unreadable required evidence, packet budget overflow,
whole-operation wall-clock deadline, stale replay presented as current,
invalid config, provider/tool failure, and artifact corruption. Deadline
failure emits no partial packet, candidate page, cache entry, or policy result.

Advisory results: untraced heuristic candidates, safe path/ID normalization,
candidate budget nearing its limit, and nonblocking bootstrap guidance. Policy
may promote only diagnostics the spec explicitly makes promotable.

## Rollback And One-Way-Door Posture

This revision deliberately removes the new persistence and source-editing
one-way doors. The remaining public CLI/MCP and packet schema changes are still
compatibility surfaces.

Rollback is by slice:

- obligation inventory and discovery can ship report-only and be removed
  without changing existing trace authority
- MCP is an optional adapter and can be disabled without affecting CLI/CI
- packet schema migration retains bounded read-only diagnostics for old packet
  artifacts; no old cache result satisfies the new packet identity
- verifier and stronger policy remain off until qualification passes; switching
  the resolved analyzer/verifier composition invalidates the prior selector.
  With no requested failure-authority selector it remains report-only; with an
  exact requested selector it exits 2 before provider work and tells the owner
  to requalify or remove that selector
- derived packets and caches can be deleted and rebuilt from source

Stop and re-plan if implementation needs source mutation, a committed
selection manifest, agent-supplied trusted paths, a second gate pipeline, an
unbounded scan, or an exception that lets semantic success override alignment.

## Required Reading And Comprehension Gates

Before editing, read the source documents above plus the target modules for the
slice. The implementer must answer:

1. Which current structures distinguish a spec mapping from a code backlink,
   and where is reciprocity decided?
2. How do invariant declarations and binds establish target and binding-test
   relations?
3. Which exact packet projection is model-visible, and which raw bytes own its
   hash?
4. Which CLI paths may import the provider today, and how do subprocess tests
   prove prohibited imports stay absent?
5. How will one core result be byte-compared across CLI JSON and MCP without
   transport metadata contaminating identity?
6. What makes a candidate advisory versus readiness-blocking?
7. How does [COV-6]'s reverse-direction uncovered-definition worklist consume
   obligation discovery without granting Backstitch or an agent authority to
   ratify a source change?
8. Why is verifier independence procedural rather than model-statistical, and
   how do `provider_source`, exact inference identity, corpus sensitivity, and
   replay prevent either same-model or distinct-model composition from gaining
   unmeasured authority?

If any answer is uncertain, stop before changing code.

## Spec-Revision And Promotion Gate

This gate precedes every implementation slice:

1. Rewrite the EVC spec to the product model and interface above.
2. Remove all proposal, activation, deactivation, active manifest, immutable
   case object, and source-editing contracts, config, diagnostics, and probes.
3. Close all replacement schemas, states, ordering, budgets, guidance, exits,
   and acceptance behavior. Do not leave them only in this plan.
4. Reconcile exact deltas to SC, CFG, EXC, INV, SEM, and COV specs. COV scope in
   this plan is [COV-6]/[COV-9] vocabulary, interface, and acceptance-contract
   reconciliation, not ratchet implementation.
5. Run an independent review against the eleven agent-interface principles,
   hardening checklist, current implementation seams, and enumerable-contract
   rule. P1/P2 findings block promotion.
6. Change EVC prose status to Active, add the related-plan backlink, and record
   the promotion baseline commit plus exact worktree hashes.
7. Run default self-corpus and suppression audit. Keep EVC in its planned
   scanner rung until mappings, code, and reciprocal backlinks land together.

Done signal: revised spec PASS, promotion baseline recorded, default check exit
0 with zero errors/warnings, suppressions auditable, no code yet cites missing
or unpromoted EVC behavior.

### Coordinated promotion record

- Date: 2026-07-15
- Baseline commit: `25346a988ad2022237160261aa61d2692d5baaa4`
- Reviewed EVC input before promotion: SHA-256
  `b4170553afbd2785f5ef8f7e312f368f94a61c057a137901e32dc48ed967ac3a`
  (the checklist's `2c26c644…` baseline is superseded by the later
  verifier-role PASS)
- Plan pre-record SHA-256:
  `2be1de33a1de185d925f38889c733822b0dfc868c67aa64e741364e48ce2e4ae`
- Independently reviewed promotion spec SHA-256:
  - `00-specs-index.md`:
    `81ee3af50b77bbd5f62b3d73e12a4fb8d3785c3af4fffeb2bfae0fa03b1ff438`
  - `02-backstitch-core.md`:
    `c9991a583a83d9e47fdca173be4579e64678fe320651e5cbe01ab0a0f6cdd49e`
  - `03-backstitch-configuration.md`:
    `c202cf0de4866b3d9a5dba06dc85b2bc60908d2b2631ec54e0a2a4a7a8b0f253`
  - `04-backstitch-traceability-exclusions.md`:
    `703a747574ec14d83be40de21b3e368440d5de7f5648332e3e7b0a274bef0f4a`
  - `05-backstitch-invariants.md`:
    `c6bb038b98297cb6d79c80b594a20c1af6345555b39f4495c1b30e6727ed0d24`
  - `06-semantic-gates.md`:
    `8b47c028b14d3764f25eb40d856b748b4aeb18f3593e35a411cb4b9733a64805`
  - `07-verification-and-evidence-cases.md`:
    `6a70fc1280965354228b0d3077e4bec055ed4cd404a4c4735642cb7dd5333ca3`
  - `08-intent-coverage.md`:
    `4b0e787eb0f870cf9da08c47c759df0fc873228ba354e466c8bb34c6a645410a`
- Plan pre-closure-record SHA-256:
  `8a4a9fa724e2b794d54de9760b6181639c109f8ccbcf3bf33d79cdd494734f4a`
- Plans index SHA-256:
  `3968139cde8ecfc555936459c17911f8e4e0259deb45642231629a96a8c1fa24`
- `git diff --check`: exit 0
- `backstitch check`: exit 0; 113 sections, 182 mappings, 288 code refs,
  557 edges, 3 invariants, 3 binds, zero errors/warnings/infos
- `--show-suppressions`: exit 0; 202 auditable suppressions, including the
  exact planned-rung EVC entries
- `bin/check-dom15-fixtures`: exit 0
- EVC/SEM status in the coordinated worktree: Active
- Independent review: PASS with no open P1/P2; Slice 0 may start
- Sequencing deviations: no intermediate commit is created without user
  authorization; HEAD plus exact worktree hashes form the checkpoint. The
  checklist's promotion-only PR limit is treated as a phase boundary because
  the user explicitly requested implementation after promotion. `BSX010` and
  `BSE001` remain reserved until their emitters and firing tests land
  atomically. MCP remains optional and is deferred unless Phase D proves
  measured benefit and receives dependency approval.

## Staged Product Phases And Owner Gates

Each phase is a coherent product result with an owner-visible stop/continue
decision. Later failure does not erase earlier value. It does block dependent
claims and work.

Before implementation dogfood, Slice 0 freezes the exact [EVC-10.2]
content-addressed Phase A/B qualification manifest, fixture-tree manifests, and
phase-specific reviewer protocols. The manifest also freezes the exact canonical tested-
distribution inventory plus installed guide and repository-skill hashes; plan
and result validation rederive all three from authoritative regular no-follow
inputs. Each result binds its phase-owned qualification projection, so valid
Phase-B-only evolution does not invalidate accepted Phase A evidence. Phase A
has no-intent, untraced, partial, complete, and
skipped fixtures and at least two public-help-only sessions. Phase B has every
candidate kind and trace state, accepted/rejected/irrelevant/disconfirming gold
labels, an explicit critical-candidate set, and at least two sessions. The
initial pass rules are fixed before output is seen: bootstrap completion 1.0,
authority comprehension 1.0 across all four propositions, candidate capture at
least 0.9, trace-state precision 1.0, irrelevant-candidate rate at most 0.2,
first-reviewed-diff correctness 1.0, and all critical candidates captured. An
independent reviewer signs the hashes and rubric before a participant runs the
workflow. A phase-owned change creates a new phase identity and result; a
common distribution, guide, or skill change invalidates both. It never rewrites
the old denominator. Phase A and Phase B each use [EVC-10.2]'s separate closed
dogfood-result shape and can pass independently; Phase B binds the passing Phase
A result hash. Later product review may cite both exact artifacts, but Slice 8
does not embed them in or infer semantic authority from them. Bootstrap and
comprehension use task/session denominators; candidate capture uses distinct
eligible (`accepted` or `rejected`) gold candidates; trace precision covers
every surfaced matched candidate, including tolerated irrelevant output;
irrelevant rows are negative controls measured when surfaced; irrelevant rate
uses surfaced candidates; and first-diff correctness uses required-diff session
tasks. Critical rows must be eligible, never irrelevant. Null
zero-denominator values never pass. Stored outcomes, counts, rates, checks, and
pass state must recompute from ordered canonical CLI outputs, tree-verified
source revisions, unified diffs, fixture gold, and session observations.
Gold is independently reviewed and source-bound, not copied from discovery.
It labels every surfaced production candidate exactly once and may include
eligible source candidates discovery missed; those rows count as uncaptured.
Expected trace state is independent from the artifact state. A complete section
relation is the mapping/backlink pair, while the required diff contains only
declarations missing from the original tree for surfaced human-accepted
candidates; invariant declarations use
`spec_mapping` for a spec-invariant implementation target and `binding_test`
for its binding-test target. A correct first diff must also make the target
obligation executable. Each Phase B task records the exact sorted human-
accepted candidate IDs handed to the participant. An omitted accepted candidate
is a capture miss, not an impossible diff task; one cumulative original-based
diff covers every missing declaration across surfaced accepted nondeclared
candidates.

| Phase | Slices | Product result | Continue gate |
|---|---|---|---|
| A: obligation core | 0, 1, 2, 4A | CLI list/detail/evidence summary, readiness, guide, no source mutation | Every preregistered fixture has exact state/coordinates; every preregistered public-help-only session completes or correctly diagnoses the bootstrap task; each participant's four raw boolean authority answers match the frozen rubric when validator-derived; the deterministic state/receipt floor is exact. Release fixtures one at a time in frozen order and record handoff-to-submission elapsed time, reviewed diff attempts, changed files/lines, calls, and review rounds to first executable obligation. Stop on any threshold miss. |
| B: discovery and guidance | 3, 4B | Answers "Given obligation X, what current code or tests are plausible candidates for fulfilling X?" with deterministic candidates, trace states, receipts, and source-edit advice | Preregistered gold labels yield candidate capture >= 0.9, trace-state precision 1.0, irrelevant rate <= 0.2, and all critical/disconfirming candidates captured. After exact human-accepted IDs are supplied as input, first cumulative reviewed-diff correctness is 1.0. This measures search-set quality and post-selection authoring guidance, not the correctness or ease of human disposition. Stop and redesign discovery before packets on any threshold miss. |
| C: packets and currentness | 6, 7 | Source-derived packet v3, explicitly historical replay, repo-addressed current analysis, report-only semantic output | Packet evidence sufficiency is exact on the frozen Phase C fixture set; relevant edits invalidate packet/cache identity, unrelated captured edits preserve packet/cache identity but make an in-flight currentness comparison stale, and stale current claims are impossible. Analyzer result JSONL plus canonical verifier result/event projections replay with zero calls and byte-identically; operational reports are excluded because elapsed time and cache counters vary. Keep verifier authority advisory. |
| D: optional MCP | 5, after B | Context-efficient read adapter over the qualified CLI core | The CLI read model is stable; same-task dogfood shows a concrete reduction in calls, response bytes, or agent context cost; installed-wheel stdio parity is exact. If benefit is absent, record `deferred`, ship no advertised MCP surface, and create no MCP semantic cohort or qualification dependency without blocking A-C or E. |
| E: semantic qualification | 8 | Blinded adversarial verifier evidence and policy qualification | Deterministic literal trace removal is caught with zero model calls; the semantic corpus contains at least 20 reviewed historical misalignments plus synthetic controls, including valid-but-vacuous trace; [EVC-10.1] precision, sensitivity, critical-case, indeterminate, flip, and replay thresholds pass for the exact composed analyzer/verifier inference identities. Equal and distinct model tuples face the same gate; correlation is not measured. Otherwise remain report-only. |

Phase records live in this plan and the reviewed evaluation evidence. They are
not product manifests and cannot change alignment. Phase A and B dogfood happens
when those phases exist; Slice 8 does not substitute semantic evaluation for
their user measurement. Current product qualification requires their complete
artifacts to match the final distribution, while historical hashes remain audit
records only.

## Tasks And Dependency Gates

### Slice 0: Add Adversarial Acceptance Probes

Files:

- `tests/acceptance/` fixtures and public subprocess probes
- `tests/product_eval/alignment-bootstrap/manifest.json`
- `tests/product_eval/alignment-bootstrap/phase-a-reviewer-protocol.md`
- `tests/product_eval/alignment-bootstrap/phase-b-reviewer-protocol.md`
- content-addressed Phase A/B fixture-tree manifests and gold labels

Write failing probes first for:

- CLI help teaches the obligation-first bootstrap path
- empty/no-spec repo, malformed IDs, duplicate IDs, missing mappings,
  one-sided mappings, missing implementation, missing required test, invariant
  bind failures, and valid complete alignment
- literal removal of each mapping, backlink, internal invariant-target, or
  binding-test relation becomes a
  deterministic readiness failure with zero provider calls; a separate fixture
  preserves valid reciprocal syntax while making the behavioral relation
  substantively vacuous for semantic evaluation
- mixed paginated list entries for addressable obligations and unaddressable
  intent, including deterministic cursors and repair actions
- source-authored valid/malformed/duplicate/ownerless skips and skip visibility
- evidence summary exact coordinates and broken reciprocity
- candidate trace states and suggested annotation guidance
- the preregistered Phase A/B manifest has exact fixture hashes, sample sizes,
  initial thresholds, critical candidate IDs, phase-specific public-help-only protocols, and
  four-part authority rubric before any dogfood; it also binds and rederives the
  tested distribution, installed guide, and repository skill; changing any
  judged or authoritative input creates a new digest instead of rewriting the
  result
- the closed dogfood result rejects unmatched candidate output and recomputes
  every count, rate, null denominator, critical-capture flag, threshold check,
  failure reason, and pass value from content-addressed CLI output, parsed
  first-review diffs, fixture gold, and independent session tasks
- task authoring cost records every read-only Backstitch call separately from
  the byte-bound CLI observations that prove outcomes; count/log mismatch or a
  proof observation absent from the call log is invalid
- mutation probes independently make candidate capture, trace-state precision,
  and critical capture fail their own checks without laundering the miss into
  `INVALID_OBSERVATION`; one-sided required declarations fail preregistration
- Phase A can pass before a Phase B run or result exists; every Phase A outcome
  recomputes from ordered CLI JSON over an exact original or revised source
  tree, Phase B binds the passing Phase A hash, and candidate rows reconstruct
  from bound CLI JSON
- Phase A/B dogfood records keep authoring cost, candidate dispositions,
  first-reviewed-diff correctness, and authority-boundary comprehension out of
  runtime alignment state
- deterministic repeated output and unrelated-file stability
- skipped obligations still allow summary and discovery
- no obligation command changes repository source bytes
- provider import/network prohibition on list/detail/summary/discovery and
  deterministic `check`
- derived packet recomputation, stale replay rejection, and no alternate
  manifest authority
- current `analyze --repo-root` start/end snapshot equality, mid-run source
  mutation failure, and historical `analyze --packets` non-authority
- post-capture replacement/deletion/permission changes prove resolver, parsers,
  readiness, discovery, and packet construction perform no second source read
- mid-capture add/remove/replace mutations discard the entire attempt, retry at
  most three total capture attempts, and exhaust as snapshot inconsistency exit
  2 with no partial report, cursor, packet, cache entry, or policy result
- POSIX descriptor-walk rejection for symlink and non-regular final inputs,
  intermediate-directory replacement, and the exact pre-traversal
  `UNSUPPORTED_PLATFORM` result when required primitives are absent
- rejection of output, staging, cache, lock, guard, audit, and provider-local
  mutable paths that overlap any captured semantic input
- every row of the combined current-analyze exit matrix, including all-skipped
  corpora with failing BSE001 or another trace issue, and every legacy semantic
  completeness key against selected versus all-skipped corpora
- verification report shapes for disabled, enabled-with-findings, and enabled
  with zero eligible findings; all counters, contexts, and call counts must
  reconstruct exactly
- verifier `provider_source = "analyze"` reuses the complete resolved
  provider/model/cost descriptor and accepts tuple equality; `override`
  requires every provider field with no fallback; same-model and distinct-model
  compositions bind their exact contracts and face the same qualification gate
- reuse rejects a different `--model` or `LLM_MODEL` before calls instead of
  retaining stale revision/cost metadata; a complete config descriptor change
  changes both inference identities
- an exact failure-authority selector plus missing, corrupt, failing, or
  identity-mismatched qualification exits 2 with the requalification action;
  the same unavailable qualification stays advisory only when no such selector
  is requested
- analyzer and verifier composition objects/hashes recompute from exact
  contract-version, provider, request, installed prompt, base/ordered epoch,
  aggregation-threshold, and indeterminate fields; changing any one invalidates
  qualification while packet, claim, trial, path, budget, policy, and response
  changes do not
- identical analyzer claims across two trials derive distinct verifier epochs
  from the validated corpus digest, configured base epoch, and trial index;
  controlled epoch-dependent verifier responses cause one cold primary call
  per distinct epoch-specific key, zero replay calls, and a nonzero composed
  flip metric while both base and effective epochs recompute from stored events
- evaluation refuses a nonempty verifier staging cache before calls, never
  reads ordinary or prior-evaluation verifier cache entries, replays only the
  current execution's primary objects, and discards staging on success or
  failure
- selected and all-skipped report audit rows reproduce readiness counts and
  retain every non-failing deterministic issue, including distinct untraced
  versus completely aligned skipped obligations
- audit-only mutation fails packet-report content identity, and packet-report
  input/output over the exact byte ceiling fails before any partial packet,
  audit, cache, analysis, or policy publication
- eval primary-only, replay-only, equal, and divergent findings with stored
  claim evidence, nullable side state, exact hashes, and flip counts
- fixture-tree manifest rejection for missing, extra, changed, symlink, or
  non-regular objects, plus exact pinned-runner mismatch refusal before scale
  ceilings are applied

Use real temporary repositories, parser, resolver, filesystem, and subprocess
CLI. Phase D owns MCP fixtures and probes only if the owner opens that optional
slice. Done: probes fail for missing behavior, not harness mistakes, and an
independent reviewer has approved the Phase A/B manifest and protocol hashes
before dogfood starts.

### Slice 1: Capture One Immutable Repository Source View

Files:

- new `backstitch/repository_snapshot.py`
- `backstitch/check_pipeline.py`
- `backstitch/resolver.py`
- `backstitch/markdown_specs.py`
- `backstitch/code_parser.py`
- `backstitch/python_refs.py`
- snapshot, resolver, parser, and acceptance tests

Work:

- resolve configured source paths through the existing target-root,
  containment, symlink, and exclusion rules
- support only the EVC v1 POSIX descriptor walk: open the repository and every
  intermediate directory by descriptor with no-follow flags, reject alternate
  path-based fallbacks, and return the exact unsupported-platform problem
  before traversal when a required primitive is absent
- read each included spec/code/test source file once into an immutable record
  with canonical path, exact bytes, required file metadata, raw receipt, and
  one ordered repository snapshot identity
- capture one bounded path/kind catalog across every configured source root;
  bind its canonical hash into snapshot identity so missing versus empty roots,
  non-source mapping targets, and directory ownership cannot collide while
  clone-local stat tuples remain capture checks rather than identity fields
- converge exact declared mapping targets within the same three-attempt whole-
  capture ceiling; capture out-of-root regular targets as byte inputs and
  directories as catalog rows so [SC-4]'s exact-path ladder never rereads live
  source or silently narrows its repository-wide contract
- normalize catalog/target identities to NFC repository-relative POSIX form,
  use `.` only for the repository-root row, strip only a trailing directory
  slash for lookup, and reject normalized collisions
- record inventory and file identity/metadata before and after each bounded
  read, then repeat the ordered inventory/metadata pass; any membership or
  identity change discards every byte from that attempt
- retain the current proposed `snapshot_capture_attempts = 3` operational
  contract: retry the whole capture from an empty buffer, never mix attempts,
  and return snapshot inconsistency/exit 2 with no partial output after the
  third failed attempt
- split `check_pipeline` into the existing public filesystem wrapper plus one
  core that accepts the snapshot; make resolver and parsers consume only that
  byte source during the operation
- return the snapshot with the resolved report so readiness, discovery, and
  packet construction cannot recapture or rescan independently
- use the same owner for the intentional final whole-snapshot recapture in
  current analyze mode

Use test-only mid-capture and post-capture hooks with a real temporary
repository. Add, replace, delete, and chmod source files during capture to
prove torn attempts are discarded and bounded retry/exhaustion is exact. Make
the same changes after a successful capture; resolver/parsers must finish from
captured bytes without a second source read, while current analyze's
intentional final recapture detects the changed snapshot and withholds a
current result.

Stop if a parser/resolver accepts a live `Path` where captured bytes suffice,
or if a second source-discovery path appears. Done: exact-byte, ordering,
containment, read-once, mutation, and TOCTOU probes pass.

### Slice 2: Build Obligation Inventory And Readiness

Files:

- `backstitch/models.py`
- `backstitch/check_pipeline.py`
- `backstitch/resolver.py` snapshot-backed report
- new `backstitch/obligations.py`
- focused unit tests

Work:

- derive one canonical obligation record per supported spec section and
  invariant from the existing report
- compute declared evidence roles and reciprocity without rescanning source
- implement closed intent/alignment/gate states plus independent disposition,
  with ordered blockers and no artifact claim in default detail
- return one bounded, paginated bootstrap entry stream covering no intent,
  unaddressable intent, and addressable obligations
- parse source-authored skips through the existing exclusion/parser owner
- keep skipped evidence reads available and denominators honest
- define canonical JSON rows, stable ordering, and budgets

Stop if the slice invents a second trace graph or duplicates issue policy.
Done: all readiness transitions and malformed branches have firing tests.

### Slice 3: Build Deterministic Discovery And Trace Guidance

Files:

- `backstitch/code_parser.py`
- `backstitch/python_refs.py`
- `backstitch/repository_snapshot.py`
- new `backstitch/evidence_discovery.py`
- discovery fixtures and tests

Work:

- consume the same immutable snapshot and resolved report from Slice 1; do not
  reopen repository source
- mint stable candidate IDs and exact raw-byte receipts
- derive conservative Python structural candidates, existing relations, and
  closed trace states
- generate structured guidance for supported mapping/backlink/invariant-target/
  binding-test forms
  without generating or applying a patch
- define fixed ordering, pagination/cursors, closure, deterministic item/byte/
  work-unit budgets, and unrelated-file stability
- permit an operational wall-clock deadline only as a whole-operation abort
  with exit 2 and no partial response or artifact
- include unresolved/static candidates as labeled counterevidence; never claim
  runtime execution or assertion

Stop if an arbitrary path query, runtime tracing, model call, or heuristic
hard failure appears. Done: positive and negative fixtures prove every
candidate/relation/trace-state branch.

### Slice 4A: Add The Transport-Neutral Obligation Core And CLI

Files:

- new `backstitch/obligation_api.py`
- `backstitch/cli.py`
- packaged reference/guide resource
- `skills/backstitch-alignment/SKILL.md`
- `tests/test_cli.py` and obligation API tests

Work:

- implement list, default detail, evidence summary, guide, and their exact
  public addresses from `## Public Interface`
- reuse one core result/problem envelope with closed guidance codes
- keep default output compact; make detail explicit and bounded
- preserve exit 0 success, exit 1 applied gate failure, and exit 2 invalid
  input/config/tool failure, with no tracebacks
- prove repository discovery anchors and no provider import
- route existing `check`, packets, and analyze through the same readiness core;
  do not add an obligation-specific gate pipeline
- make the installed guide the one teaching payload for CLI, MCP, and the thin
  repository skill; test its version/hash and command/schema references

Done: Phase A's wheel-installed public help, bootstrap, JSON/text/exit, and
fresh-eyes dogfood gates pass with the authoring-cost record captured.

### Slice 4B: Expose Discovery And Candidate Detail Through The Same CLI

Files:

- `backstitch/obligation_api.py`
- `backstitch/cli.py`
- `backstitch/evidence_discovery.py`
- packaged guide and repository skill
- `tests/test_cli.py`, obligation API tests, and discovery dogfood fixtures

Work:

- add `--find-evidence` and `--candidate` to the same obligation aggregate and
  canonical envelope; do not introduce a discovery service or query language
- make default detail candidate counts, candidate ordering, pagination, receipt
  detail, and trace guidance agree with the deterministic discovery owner
- make refresh ordinary: repeat discovery on the same snapshot for byte-stable
  core output and after relevant source edits for a newly snapshot-bound report;
  never load an older report as current candidate or gate authority
- expose the exact human-reviewed `accepted`/`rejected`/`irrelevant` evaluation
  labels only in dogfood evidence, never as runtime alignment state
- run Phase B dogfood before any packet or MCP qualification claim and record
  candidate quality; then hand participants the exact sorted human-accepted IDs
  and measure one cumulative original-based reciprocal diff for all accepted
  candidates the product surfaced as incomplete

Done: all candidate JSON/text/exit probes pass and Phase B receives an explicit
owner stop/continue disposition.

### Slice 5: Add The Optional Read-Only MCP Adapter

Entry gate: Phase B read-model qualification, a recorded same-task CLI call/
byte/context-cost baseline plus an owner decision that the observed cost
justifies an MCP implementation trial, exact pinned SDK/API approval, and a real
stdio client fixture. Semantic-policy qualification is not required.

Files:

- new `backstitch/mcp_server.py`
- `pyproject.toml` optional extra and wheel manifest
- test-only installed-wheel stdio client fixture
- MCP parity, framing, source-byte, and import-boundary tests

Work:

- expose the five named obligation read tools and the installed alignment guide
  resource over local stdio
- pin server startup to `backstitch mcp --repo-root PATH`; require `repo_root`
  on repository-bound calls and reject any root that does not resolve to that
  allowed root; no hidden handles
- translate transport framing only; core payload bytes remain identical to CLI
- allow snapshot-keyed in-process index reuse while returning snapshot identity
- prohibit source writes, provider/model calls, approval, arbitrary filesystem
  reads, and remote transports
- byte-compare CLI and real stdio canonical core results for every success and
  problem family; verify every tool leaves repository source bytes unchanged
  and imports no provider or credential path

Stop if SDK framing cannot preserve canonical core results or the dependency is
not distributable in the wheel. Done: real installed-wheel stdio parity passes
and same-task dogfood shows a concrete call, byte, or context-cost reduction
against the entry baseline. If it does not, record Phase D as `deferred`, ship
no MCP command, tools, resource, optional dependency, or semantic-evaluation
cohort, and continue without blocking the other phases.

### Slice 6: Compile Source Alignment Into The Packet Schema

Files:

- `backstitch/analysis_packets.py`
- `backstitch/semantic_packets.py`
- `backstitch/semantic_identity.py`
- `backstitch/semantic_evidence.py`
- `backstitch/semantic_reports.py`
- packet, identity, result, report, and acceptance tests
- `tests/product_eval/phase_c/` packet/currentness fixture manifest and trees

Work:

- replace the sole producer with the promoted source-aligned packet schema
- treat packet compilation as the start of the gate phase: consume only the
  human decisions encoded in current reciprocal source declarations, never a
  candidate report or evaluation disposition
- include exact current obligation text, declared implementation/test evidence,
  deterministic bounded counterevidence, trace state, and receipt identity
  hashes derived from the complete raw receipts; full receipt objects remain
  compiler inputs and do not extend [EVC-9.1]'s closed packet shape
- reject semantic execution for non-executable alignment while permitting a
  clearly report-only bootstrap artifact if the spec retains one
- stamp packet reports with the captured source snapshot and derivation
  identity required for historical replay and currentness comparison; bind
  the complete non-provenance report, including audit arrays, under one
  recomputed packet-report content hash
- deduplicate overlapping model-visible regions and keep citation coordinates
  unambiguous
- bind packet identity only to [EVC-9.1]'s exact model-visible current bytes;
  bind derivation config in `source_snapshot.derivation_config_hash` and bind
  prompt/provider/request later in the analysis identity; exclude advisory
  prose from semantic identity unless model-visible
- retain old packet readers only for migration diagnostics
- enforce the exact packet-report byte ceiling before parsing input and after
  complete output assembly; never truncate or publish a partial audit
- keep packet-only consumers explicitly historical unless a repository address
  is captured and compared through the currentness owner
- prove the bootstrap refresh boundary separately: re-running discovery on an
  unchanged snapshot is byte-stable, while a relevant source change yields a
  newly bound candidate report without altering gate authority
- freeze the small provider-free Phase C packet/currentness fixture set and
  manifest used by the Slice 6/7 stop gate; this is not the Slice 8 semantic
  qualification corpus and grants no policy authority

The Phase C manifest is
`tests/product_eval/phase_c/manifest.json` with exactly
`{schema_version: 1, fixtures, scenarios}`. Each fixture row has exactly
`fixture_id`, `tree_path`, `tree_sha256`, `expected_obligation_ids`,
`expected_packet_atoms`, and `expected_current_generation`.
`expected_current_generation` has exactly `outcome`, `exit_code`, and
`blocking_codes`. `outcome` is `evaluated`, `not_run_all_skipped`,
`alignment_debt`, or `deterministic_failure`; its exit code is respectively
`0`, `0`, `2`, or `1`. `blocking_codes` is an ordered unique array: empty for
the two successful outcomes, exactly `["ALIGNMENT_DEBT"]` for alignment debt,
and the canonical ordinary deterministic fail-on issue codes in ordinary
report order, deduplicated at first occurrence, for a deterministic failure.
Negative generation fixtures do not receive artifact
scenarios because they publish no current packet/report artifact. A packet atom has exactly
`obligation_id`, `requirement_sha256`, `declared_receipt_hashes`, and
`counter_candidate_ids`; arrays are ordered unique and hashes are lowercase
SHA-256. `requirement_sha256` is SHA-256 of the exact UTF-8 bytes of
`requirement.text`. Atoms sort by canonical obligation ID.

Each scenario row has exactly `scenario_id`, `kind`, `source_fixture_id`,
nullable `compare_fixture_id`, nullable `artifact_transform`,
`expected_currentness`, and `expected_packet_identity`. `kind` is one of
`current_generation`, `historical_replay`, `stale_comparison`,
`relevant_mutation`, `unrelated_mutation`, or `corrupt_artifact`.
`expected_currentness` is `current`, `stale`, `unverifiable`, or `corrupt`;
`expected_packet_identity` is `equal`, `different`, or `not_applicable`.
Packet identity compares the ordered `(packet_id, packet_hash)` vector, not
packet JSONL or report bytes: an unrelated captured edit changes snapshot
metadata while preserving semantic/cache identity.
The source fixture is always the artifact producer. Current generation and
historical replay require null compare/transform; they expect respectively
`current` and `unverifiable`. Stale comparison requires a distinct comparison
fixture, null transform, and `stale`. Relevant and unrelated mutation require
a distinct comparison fixture and null transform; both expect `stale`, while
packet identity is respectively `different` and `equal`. Corrupt artifact
requires null comparison and one transform with exactly `artifact`
(`packet_jsonl` or `packet_report`), zero-based `byte_offset`, and `xor_mask`
(integer 1 through 255). The runner XORs exactly that byte in the source
fixture's canonical emitted artifact before loading it and expects `corrupt`;
packet identity is `not_applicable`. Scenario IDs are ordered unique and every
fixture reference must resolve in the same manifest.
Fixture IDs and paths are ordered unique; paths are contained relative POSIX
directories; tree hashes use the existing qualification tree-hash algorithm;
`tree_sha256` is lowercase `sha256:` plus 64 hexadecimal characters, while
packet-atom hashes are bare 64-character lowercase hexadecimal strings;
obligation IDs are ordered unique. Expected atoms and currentness outcomes are
derived by independent source inspection, frozen, and content-addressed before
the first Slice 7 result; they must not be copied from packet/currentness
output. The manifest,
trees, and gold receive an independent preregistration review before any Phase
C run. The frozen set contains at least one aligned
section, aligned invariant, all-skipped corpus, active alignment-debt corpus,
deterministic-failure corpus, relevant mutation, unrelated captured mutation,
valid historical replay, stale comparison, and corrupt artifact case. Slice 6
owns packet/audit expectations; Slice 7 adds analyzer/verifier/currentness
expectations without changing these source trees or manifest identity.

The accepted preregistration checkpoint is manifest raw SHA-256
`2244a9ba5a7b5e09e376ffaa9d053bf6c073a1d8349b1d7525f27928267072ad`
and canonical-object SHA-256
`a4ab149407d9d4443c35c55a29a39eb2a35dee4f8320feb2b057287f6ab3e2e6`.
Fixture tree hashes are: aligned-base
`sha256:0eca9fcb9f62372fb49343ab6cf9a953c1fa04667fa55e0e394f14fbbbe82447`,
aligned-relevant
`sha256:aadd0ab9956c93ca16845bfa9d3af91e68a371c8e1296fad22a3d6eb9ac9c5c2`,
aligned-unrelated
`sha256:f5d511359ccb2ad082bb1eb7b08833ad303478d76a48407c8232220f9e20de86`,
alignment-debt
`sha256:ba7517f3a4b8387cfc5d103f8b5fb4d59862cb811936041471c57efe97ba96ce`,
all-skipped
`sha256:8a5033e429c8a94fff7b0ad0b7f27fe5053d9916ded44b822046d14f15d1398f`,
and deterministic-failure
`sha256:a8258f0d342eb04d10294670469252796f1c1febf483f460fd88a5c85db4afb7`.
An independent actual-byte review passed before execution. The later result
review passed after the tests consumed every manifest field and scenario.

Stop if a committed packet can override source or if evidence is selected by a
model/agent. Done: deterministic packet bytes, mutation sensitivity, unrelated
stability, and stale replay probes pass.

### Slice 7: Reuse Analyze, Verify, Cache, And Policy

Files:

- `backstitch/semantic_analysis.py`
- `backstitch/semantic_cache.py`
- `backstitch/semantic_policy.py`
- verifier modules introduced by the promoted EVC spec
- deterministic semantic tests

Work:

- place deterministic readiness before any provider call
- make `analyze --repo-root` own one current run: capture source, derive packets,
  analyze/verify/project policy, recapture source, then publish a current result
  only when the snapshot still matches
- keep `analyze --packets` and packet-only summarization snapshot-scoped and
  structurally unable to claim current repository conformance
- reuse current analysis/cache/policy seams with the new packet identity
- add blinded adversarial verification only over the closed packet projection;
  keep its prompt, request, event, and cache identity separate even when it
  reuses analyze's provider/model tuple
- implement `provider_source = "analyze"` as complete resolved-descriptor reuse
  and `override` as one complete provider table; reject partial inheritance,
  duplicate provider fields, unknown shapes, and different CLI/environment
  model values that would retain stale revision/cost metadata before adapter
  construction
- resolve requested exact `CODE:independently_verified` failure authority before
  cache/provider construction; until Slice 8 owns the current qualification
  loader, any request for that authority is exit 2 with the exact
  requalification action, while absent failure authority remains advisory;
  Slice 8 adds successful loading and the missing/corrupt/failing/identity-
  mismatch artifact cases
- build the exact configuration-level analyzer and verifier composition objects
  before cache/provider construction, store/recompute their individual hashes
  and combined hash in eval identity, and never substitute packet/claim event
  keys for the report-level composition selector
- keep alignment authority, analyzer judgment, verifier judgment, and policy
  as distinct records
- fail closed on stale/corrupt/missing required artifacts and tool failures
- implement the first-match current-analyze exit matrix, including deterministic
  policy before semantic calls and the exact all-skipped publication behavior
- emit the closed tagged verification report for disabled, enabled, and
  enabled-with-zero-finding runs without inventing a second representation
- keep report-only defaults until qualification authorizes stronger policy
- reject `[analyze.eval]` as producer configuration; retain only its bounded
  historical artifact reader until Slice 8 removes that migration vocabulary

Done: call counts, outbound bytes, cache hits/misses, failures, aggregation,
same-model reuse, full override, config rejection, and policy projection have
firing tests with no live provider dependency. Identity-drift tests cover CLI,
environment, complete analyze config, complete verifier override, and equal-to-
distinct composition changes. Golden tests change every composition field and
every explicitly excluded per-packet/claim/trial/operational field.

### Slice 8: Consolidate Product Evidence And Qualify Semantic Policy

Files:

- `backstitch/semantic_eval.py`
- `backstitch/semantic_eval_reports.py`
- `backstitch/settings.py`
- `backstitch/semantic_policy.py`
- `backstitch/cli.py`
- `tests/semantic_eval/` corpus and negative controls
- `tests/performance/runner-contract.json` and the `semantic-scale` CI job
- reviewed reports under `docs/evidence/`

Keep four evidence products separate. Phase A/B records measure bootstrap and
the bridge from obligations to plausible candidates. Phase C measures packet,
currentness, and cache behavior without granting semantic authority. The
schema-3 semantic report alone qualifies an exact analyzer/verifier composition
for stronger policy. The pinned-runner performance result measures operational
fitness and never changes a semantic verdict. There is no aggregate artifact
whose pass can hide a failed or stale component.

The accepted Phase A result `a92964db...` and Phase B result `6b8f1bdc...` are
historical audit evidence. Their complete result artifacts are not committed,
and Slice 6/7 changed the tested distribution after they ran. Hashes in this
plan do not recreate absent bytes and must not be presented as provider-free
replay. A fresh A/B run against the final distribution is required before
claiming current bootstrap/discovery product qualification, but it is not a
surrogate prerequisite for semantic-policy authority. The frozen Phase C
manifest and its passing manifest-driven verification record remain a separate
prerequisite for running the semantic corpus through the source-derived current
pipeline.

Implement Slice 8 in these independently reviewable steps:

1. **8.0 contract closure and legacy quarantine.** Finish [EVC-10.1]'s exact
   corpus, report, metric, trial-collapse, analyzer/verifier replay, and
   exact-code authority rules. Replace the current producer path rather than
   porting analyzer-only schema-1 corpus/schema-2 report logic. Remove
   `AnalyzeEvalSettings` and every `[analyze.eval]` producer seam. A bounded
   legacy report loader may remain only behind an explicit historical
   validation path and can never return a current qualification object.
2. **8.1 closed loaders and identity.** Implement schema-3 corpus/tree loading,
   `VerifyEvalSettings`, canonical analyzer/verifier/composed identities, exact
   effective analyzer and verifier trial epochs, and schema-3 report
   internal/authoritative validators. Reject unknown keys, non-regular or
   escaping inputs, NFC collisions, hash drift, source/gold contradictions,
   and output/input aliasing before adapter construction.
3. **8.2 production source pipeline and fresh caches.** For each isolated
   fixture variant, use real capture, readiness, packet compilation, analyze,
   evidence normalization, adversarial verification, and policy projection.
   Give each evaluation execution fresh empty analyzer and verifier roots.
   Primary is read-write; immediate replay is require. Record every analyzer
   attempt, including `ok` results, plus every verifier event. Distinct keys
   cause exactly one primary call; replay causes zero calls. Gold never enters
   source trees, packets, prompts, or provider requests.
4. **8.3 metrics and report publication.** Recompute evidence sufficiency,
   conditional precision/recall, end-to-end recall, Wilson bounds,
   false-positive and indeterminate rates, uncached flips, and critical status
   from labelled corpus units rather than trial-expanded denominators. Emit
   aggregate and exact long `SEMANTIC_*` code cohorts with closed check names.
   Atomically publish only after authoritative self-validation. Provider-free
   validation replays the committed corpus/report math and identities; report
   generation is one cold provider-backed primary plus zero-call cache replay.
5. **8.4 strong-policy loader.** Resolve exact
   `CODE:independently_verified` failure authority before ordinary cache or
   provider construction. Require a committed enforce report whose configured
   digest, aggregate cohort, exact-code cohort, source-derivation identity,
   qualification identity (corpus, mode, trials, floors, thresholds, confidence,
   and critical requirement), and composed inference identity all pass.
   Missing, corrupt, report-mode, failing, empty-code, or identity-mismatched
   evidence is exit 2 with raw report digest plus expected/current derivation,
   qualification, and composition details and the exact requalification action.
   Generate an enforce candidate to an explicit output path first;
   gate authority begins only after human review pins that path and digest in
   config. Advisory policy remains available without qualification.
6. **8.5 qualifying corpus and measured run.** Expand the historical synthetic
   baseline to at least 20 independently reviewed historical misalignment
   units plus positive, negative, indeterminate, flip, out-of-packet decoy,
   prompt-injection, and valid-but-vacuous reciprocal-trace controls. Literal
   trace removal stays in deterministic readiness and makes zero model calls.
   Run same-model analyze-provider reuse first. Record resolved identities and
   cost. A distinct-model run is optional and grants no extra authority.
7. **8.6 independent performance result.** Add the exact scale fixture,
   `tests/performance/runner-contract.json`, and `semantic-scale` job. Verify the
   pinned runtime before applying latency/RSS ceilings. A missing or mismatched
   runner makes performance qualification unavailable. It does not mutate or
   weaken the semantic report.
8. **8.7 refresh and final review.** Re-run Phase A/B only after the final
   distribution, guide, and skill bytes are frozen if current bootstrap claims
   are in scope. Independently review Phase C, the semantic corpus before live
   output, the generated report after output, the performance result, and the
   integrated strong-selector path. Hard-fail false positives, a missed
   critical valid-but-vacuous trace, nonzero replay calls, silent source
   mutation, or any open P1 blocks promotion.

### Slice 9: Reconcile Documentation And Traceability

Files:

- all promoted SC/CFG/EXC/INV/SEM/EVC specs and reconciled
  [COV-6]/[COV-9]
- new implementation note under `docs/implementation/`
- `docs/implementation/00-implementation-index.md`
- `docs/implementation/02-repository-map.md`
- `docs/implementation/03-agent-inventory.md`
- CLI/MCP guide, mappings, backlinks, and plan record

Work:

- align final public grammar, states, schemas, diagnostics, config, and exits
- document the human bootstrap loop and why Backstitch never edits traces
- document CLI sufficiency, MCP optionality, replay, rollback, and policy gates
- record why MCP was implemented or deferred using the Phase D context-cost
  evidence
- add reciprocal mappings/backlinks and remove planned-rung suppressions only
  in the same green slice
- record verification, dogfood, residual risk, deviation disposition, and any
  durable lesson

Done: full definition of done passes. Do not call the work ready to land while
it remains uncommitted.

## Dependency And Parallelization Strategy

```text
spec revision + independent PASS + promotion
  -> Slice 0 acceptance probes
  -> Slice 1 immutable source capture
       -> Slice 2 obligation/readiness
            -> Slice 4A core API/CLI -> Phase A stop/continue
            -> Slice 3 discovery/guidance
                 -> Slice 4B candidate CLI -> Phase B stop/continue
                      -> Slice 6 packets
                           -> Slice 7 current analyze/verify/cache/policy
                                -> Phase C stop/continue
                                     -> Slice 8 semantic qualification
                                          -> Phase E stop/continue
                      -> measured MCP-benefit gate
                           -> Slice 5 MCP -> Phase D stop/continue
  -> Slice 9 docs/traceability after every in-scope phase
```

Implementation is mostly sequential because slices share core models and
contracts. After Phase B, packet work may proceed without MCP. MCP transport
work begins only if its measured-benefit gate passes, then may run in parallel
with packet integration if separate worktrees avoid `pyproject.toml` and shared
test fixture conflicts. Merge the core/CLI branch first; rebase MCP; then
continue integrated verification. Do not parallelize spec promotion with code.

## Testing Plan And Anti-Mocking Rules

Keep real:

- temporary repositories and exact source bytes
- Markdown and Python parsers
- resolver, mappings, backlinks, binds, exclusion/skip parser, and issue policy
- candidate index, receipts, budgets, ordering, and cursor validation
- CLI subprocesses and, only when Phase D is implemented, a real
  installed-wheel MCP stdio client/server
- packet, cache, report, replay, and policy objects across their public seams

Allowed controlled seams:

- provider adapters may return fixed structured responses, but exact outbound
  bytes, call count, identity, normalization, cache writes, and failures stay real
- time may be injected only for operational deadlines/timestamps
- filesystem failure injection may wrap atomic artifact writers, but final and
  staging paths remain real
- a test-only post-capture hook may mutate a real temporary repository to prove
  snapshot isolation; it may not replace the snapshot, parser, or resolver

Never mock the resolver when testing readiness, the parser when testing trace
guidance, the candidate index when testing CLI or implemented MCP, or the cache
when testing packet identity.

Provider-resolution tests keep config layering and the production resolver
real. They prove analyze reuse after CLI/config precedence, one credential
configuration path for reuse, complete override isolation, cost-source
validation, equal-tuple acceptance, atomic model/revision/cost pairing, and
identity/qualification invalidation when either resolved inference contract
changes. Strong-selector probes prove mismatch is exit 2 before calls; advisory
probes prove report-only behavior without that selector. No test substitutes a
boolean “different model” seam for the resolved descriptors.

Composition-identity tests use the real installed prompt descriptors and
provider-distribution metadata. They independently recompute the closed
analyzer, verifier, and combined canonical JSON hashes. Packet/claim and trial
event keys remain real but must not contaminate the qualification selector.

Coverage map:

```text
SOURCE INTENT                ALIGNMENT CORE              USER/GATE FLOW
spec section/invariant  ->  obligation inventory   ->  list/detail
mapping + backlink      ->  evidence summary       ->  human review
bind + binding test     ->  readiness states       ->  check
untraced code           ->  candidate discovery    ->  trace guidance
source-authored skip    ->  skipped disposition    ->  audit + inspect
complete alignment      ->  derived packet         ->  analyze/verify/policy
changed source bytes    ->  stale identity         ->  rebuild or fail closed
```

Every branch above needs success, malformed, boundary, and stale-state tests.
LLM prompt/projection changes require semantic eval cases and replay baselines.

Performance qualification uses one deterministic generated fixture with 1,000
obligations, 5,000 Python modules, 20,000 discovery candidates, and at least 50
MiB of source. On the pinned Linux CI runner, record cold list, full discovery,
packet generation, current analyze replay-from-cache, warm MCP list/detail,
deterministic work counts, and peak RSS. Initial hard ceilings are 30 seconds
for full discovery or packet generation, 5 seconds for cache-only current
analyze, 2 seconds for warm list/detail, and 1 GiB peak RSS. The pre-promotion
contract adopts those numbers as provisional design targets; warm MCP is
measured only when Phase D is implemented. The contract does not claim
an impossible pre-implementation measurement. As each operation exists, add the
committed runner contract and job, capture the first comparable baseline, and
apply the target as that phase's hard acceptance ceiling. A miss stops the
phase for diagnosis and independent review of an explicit spec revision; it is
never silently relaxed during implementation. Ordinary wall-clock deadlines
never choose candidates or truncate a packet.

## Verification Commands And Gates

Per slice: focused unit tests plus affected acceptance probes. Before any
integration-ready or completion claim:

```text
uv run pytest --ignore=tests/live -q
uv run pytest tests/acceptance -q
uv run ruff check backstitch tests
uv run ruff format --check backstitch tests
uv run mypy backstitch
uv run backstitch check --repo-root .
uv run backstitch check --repo-root . --show-suppressions
git diff --check
```

The default Backstitch invocation must exit 0 with zero errors and warnings.
Every enumerable contract touched by the change must have a firing test.
Suppressions remain exact, reasoned, and auditable. Live model runs supplement
but never replace deterministic proof.

## Rollout And Post-Deploy Signals

Rollout order:

1. source-derived obligation inventory, readiness, and evidence summary in
   report-only mode, CLI guide, public-help-only dogfood, and the Phase A owner
   decision
2. deterministic discovery and trace guidance, candidate-label dogfood, and the
   Phase B owner decision
3. source-aligned packet producer, stale replay checks, repo-addressed current
   analyze, explicitly historical packet replay, and the Phase C owner decision
4. optional read-only MCP only when Phase D's measured context-benefit gate and
   installed-wheel parity pass; otherwise defer it
5. same-model blinded adversarial verifier through analyze-provider reuse and
   expanded evaluation, still report-only; distinct-model override remains an
   optional separately qualified experiment
6. CI cache replay for reviewed executable obligations
7. stronger warning/error policy only after measured qualification and a
   separate policy review

Signals:

- obligation state distribution and time from untraced/partial to complete
- reviewed diff attempts, changed files/lines, Backstitch calls, and review
  rounds to first executable obligation
- broken reciprocity and stale receipt counts
- candidate recall and trace-state precision by kind
- accepted/rejected/irrelevant candidate disposition rates and first-reviewed-
  diff reciprocal-pair correctness
- guidance follow-through rate measured from later source changes, without
  claiming Backstitch authored them
- CLI/MCP parity failures and interaction/response-byte cost
- guide/skill identity drift and bootstrap completion from public help only
- packet rebuilds per relevant versus unrelated changed line
- stale replay rejection and cache hit/miss rates
- analyzer/verifier false positives, false negatives, indeterminate rate, and
  flip rate per exact composed identity; no cross-model correlation metric
- skipped share of total obligations and effective-policy failures
- provider calls and spend; deterministic replay target is zero calls

## Independent Review Loop

The rewritten EVC spec and this plan require a fresh independent review. The
reviewer reads the agent-interface runbook, hardening runbook, promoted spec
deltas, current implementation seams, and this plan. The stance is:

> Could a new engineer implement this without inventing a second authority,
> source-editing behavior, a second gate path, or heuristic failure semantics?
> Are all public states, schemas, budgets, guidance, errors, and tests closed?

P1 findings block. P2 findings are incorporated or receive an explicit
owner-visible rejection. Review again after each meaningful slice and once
over the integrated diff from public help only.

### Historical Review Records

- The initial broker/case design was independently blocked and hardened across
  snapshot identity, candidate closure, immutable publication, packet v3,
  verifier identity, budgets, error contracts, eval math, and rollout.
- A rereview passed the broker-centered contract at EVC hash
  `d3aa00fca03d18706c1d79411c23c5d08225b2afbb25b1dac223a28f30a48389`.
- The obligation-centered lifecycle revision passed at EVC hash
  `3df5b8eb9391ba98400aa8736f1c99d67082c97278ef371f9b85560ab52b43f1`
  and plan pre-record hash
  `0f166f454a0a0dc0beadd85e8f21402824c1dd73c3deb2aecd271c83c4e02801`.
- Those PASS verdicts remain valid only for their reviewed bytes. The aligned
  intent review above supersedes their product-authority assumption and
  reopens spec and plan review.

### Current Review Record

| Date | Reviewer | Target | Verdict | Findings |
|---|---|---|---|---|
| 2026-07-15 | discussion review | EVC `3df5b8e…`, plan `54b870b…` | REVISE | Source alignment must be authority; remove proposal/case/source-edit lifecycle; add readiness, summary, trace-state guidance, and derived packets. |
| 2026-07-15 | independent plan reviewer | plan `f733358ddf3ba44e3894a7b17b3c2738b49459651454cb98f621ca4b1807629f` | PASS | All findings incorporated: orthogonal alignment/disposition, explicit current versus historical gate authority, bootstrap issue rows, deterministic work budgets, one snapshot owner, bounded torn-capture retry, and scale gates. |
| 2026-07-15 | independent spec/plan readiness check | pre-rewrite EVC plus aligned-intent plan | BLOCKED | The plan direction was reviewable, but the EVC still described the superseded case/activation model. |
| 2026-07-15 | independent spec/plan reviewer | EVC `18c30fe5186162c19fd055a5d40074a3ab11a8c5d872855b94e93b0ba8b13dfa` plus pre-refresh plan | REVISE | Close all-skipped exit precedence, disabled/zero-finding verification report shapes, eval claim evidence, and refresh the plan's baseline and newly required boundary probes. |
| 2026-07-15 | independent spec/plan reviewer | EVC `cb98165a1a644bded872f2af2ad6c666f4fc62e87111169b8faef20896d24d71`, plan `3356e54295096526c09cc4a6af2ccb17dec48fbf1c9ccfbfe23081901dcba846` | REVISE | Preserve per-obligation skipped alignment state and retained non-failing deterministic issues in zero-packet analysis reports. |
| 2026-07-15 | independent spec/plan reviewer | EVC `564567f9a1ea634c297ea5e5ce54225afefedf09dfb450025b130b4906a11471`, plan `6e96e637c86e7078edcc27c804bdacc5cd28ff395831b0ebd311ddd093c76dcc` | REVISE | Bind complete audit projections under packet-report content identity and add an exact fail-closed report-byte ceiling. |
| 2026-07-15 | independent spec/plan reviewer | EVC `3f4919a6d967b0c4b4758060fbec657a081d38399d98cbf24baa900b497c462f`, plan pre-record `e7089e96ff0af87226488d9dec0aa3f0c9982d7e8c7a38da7cac1f27faf65e5c` | PASS | No open P1/P2. Packet-report content identity, audit preservation, report-byte bounds, all-skipped exits, verifier shapes, eval replay, filesystem boundaries, and plan probes are closed. |
| 2026-07-15 | independent product-fit rereviewer | EVC `b2fa8888a04347879d01ac8382f5c4673a87df6306e91bc11c450669feb8bfc2`, plan `ca8784604bdc27bf9223d42fcf2a4b462721e6b853826a0f9ec1b6c3b28df009` | REVISE | Reconcile [COV-9]'s proposal-object probes, make Phase D truly optional in global completion and semantic cohorts, and preregister Phase A/B fixtures, sample sizes, critical cases, thresholds, and comprehension rubric. |
| 2026-07-15 | independent product-fit rereviewer | EVC `389aed5f90d54183502df3769c0c4282bb7e8fe0c72b215f292ed1dcb7f670c1`, plan `53c95c2f8dcf1ac65fac851ca0a2002ef480d70ecf46f917b295d1472d187d10` | REVISE | Name the exact superseded [COV-9] bullets and close Phase A/B fixture/result shapes, metric equations, denominators, zero-denominator behavior, and recomputation. MCP optionality is closed. |
| 2026-07-15 | independent product-fit rereviewer | EVC `e9ec63bf2ed9d75ed5bf3b8f60b229abe5ee54dd0a99612740836c2d21d9fb8d`, plan `a54c35611b970b422c7459a9145aad34989a7e54a5882f17c879df8888836998` | REVISE | Split the combined dogfood result so Phase A can stop independently, bind Phase A outcomes to exact CLI/source evidence, bind Phase B to the passing Phase A hash, match session counts, and reconstruct candidate rows from bound output. |
| 2026-07-15 | independent product-fit rereviewer | EVC `2c26c6443aa23bb69e76145056c153cc03089e2f7a153cb4fea46d97992422c9`, plan pre-record `0ad0726923ee075b5bd4955d259ec2188f6f2e75fc40fb864d2cee2b73dc63ad` | PASS | No open P1/P2. COV-9 targets the exact obsolete bullets; Phase A/B are preregistered, separately stoppable, content-bound, and mathematically reproducible; MCP is optional across interface, probes, performance, and semantic cohorts. |
| 2026-07-15 | independent verifier-role reviewer | EVC `6efa638acf341323e6ce0d1aa38606d5756355669b2512d8117a80254aebbd34`, plan `2ba01058a435410bf136dc16756d5ad5deacd52f13ad8a280a6e7ab8559795b2` | REVISE | Fail setup instead of silently degrading an explicitly requested strong gate after identity drift; make reused model/revision/cost selection atomic across CLI/environment/config; remove SC-16's stale blended-score/calibration permission during promotion. |
| 2026-07-15 | independent verifier-role reviewer | EVC `6bade30302ce4c0745d029ef6cc33bc2c9fe3a45c920f221c8b900e6bb37cfe4`, plan `5a91178ed4b40315b16ade48348a7e9a606fe33a7f9c21f327474186b6d3a6b1` | REVISE | Close the report-level analyzer/verifier composition projections and canonical hashes; per-packet, claim, and trial event contracts cannot serve as a multi-unit qualification selector. Prior selector, atomic descriptor, and SC-16 findings are closed. |
| 2026-07-15 | independent verifier-role reviewer | EVC `889d081fd15780267f942f3ef334080685137c5eb7c67de1901fae99ee25c955`, plan `4aa8c44f0d39d4199ab4e2e2cd3fe6fbbd830d11cea7801e4ca0c67165121ec9` | REVISE | Derive distinct effective verifier epochs per corpus/base-epoch/trial so stochastic primary trials cannot share verifier cache entries; retain stable base composition, replay each trial against its own exact epoch, and fire a differing-response flip probe. Prior composition-closure findings are closed. |
| 2026-07-15 | independent verifier-role reviewer | EVC `b4170553afbd2785f5ef8f7e312f368f94a61c057a137901e32dc48ed967ac3a`, plan pre-record `31fee499989f64a83d5ed803e4836cad48185df40e83a7c2be4301273d672f92` | PASS | No open P1/P2. Cross-model correlation and tuple inequality are removed without weakening corpus precision/sensitivity; same-model verify is valid; strong selectors fail closed; provider reuse is atomic; stable composition and trial-specific cold verifier epochs are closed and replayable. |
| 2026-07-15 | independent coordinated-promotion reviewer | coordinated hashes in the promotion record; plan pre-closure `8a4a9fa7…` | PASS | No open P1/P2. Current/historical packet rules, mandatory paired report grammar, sole verify-eval authority, diagnostic staging, config exactness, aligned vocabulary, verifier framing, fail-closed bounds, and source authority are consistent. Slice 0 cleared. |
| 2026-07-15 | independent Slice 1 contract reviewer | EVC `d2363360…`, plan `b8c4b005…` | REVISE | A root-only catalog missed exact out-of-root [SC-4] targets, and path normalization/root/trailing-slash behavior was underdefined. |
| 2026-07-15 | independent Slice 1 contract rereviewer | EVC `328b3a6063defea0e96e9408541845a77f1b861fa25402015eff58921d3a88ea`, plan pre-record `c7edcd5d8d2b4d9560e4a4c818acf36c8ddba317857d311feb18dc43ba23bfbf` | PASS | No open P1/P2. Staged target convergence preserves repo-wide exact mappings; NFC collision, root, trailing-slash, missing-root, catalog budget, torn-capture, clone identity, and replay rules are closed. |
| 2026-07-16 | independent integrated implementation reviewer | report-only Slice 8/9 implementation | REVISE, then PASS | Initial review found three P2 qualification-boundary defects: structured error detail loss, unbounded/prefixed report hashing, and output/report aliasing. The first correction rereview found one residual report-to-corpus/config alias. Final rereview found no open P1/P2 and confirmed every check precedes adapter construction. |

### Prior Verification Record

Recorded 2026-07-15 for the proposed spec-revision slice:

- historical EVC proposal preserved by commit
  `25346a988ad2022237160261aa61d2692d5baaa4`; the committed file SHA-256
  recomputes to
  `3df5b8eb9391ba98400aa8736f1c99d67082c97278ef371f9b85560ab52b43f1`
- rewritten EVC SHA-256
  `3f4919a6d967b0c4b4758060fbec657a081d38399d98cbf24baa900b497c462f`
  received independent PASS with no open P1/P2
- `git diff --check`: exit 0 for the current worktree
- `uv run backstitch check --repo-root .`: exit 0; 112 spec sections, 182
  mappings, 288 code refs, 557 edges, 3 invariants, 3 binds, zero errors,
  warnings, or infos
- `uv run backstitch check --repo-root . --show-suppressions`: exit 0 with the
  same zero-issue summary and 201 auditable suppressions; the 32 EVC section
  suppressions are planned-spec `config_file` entries
- the rewritten EVC, this plan record, and plan index remain uncommitted; the
  repository also retains unrelated user-owned worktree changes

### Current Product-Fit Verification Record

Recorded 2026-07-15 for the staged-qualification review:

- product-fit EVC SHA-256
  `2c26c6443aa23bb69e76145056c153cc03089e2f7a153cb4fea46d97992422c9`
  and plan pre-record SHA-256
  `0ad0726923ee075b5bd4955d259ec2188f6f2e75fc40fb864d2cee2b73dc63ad`
  received independent PASS with no open P1/P2
- tracked-file `git diff --check` plus untracked-plan
  `git diff --no-index --check`: exit 0 under the expected no-index diff status
- `uv run backstitch check --repo-root .`: exit 0; 113 spec sections, 182
  mappings, 288 code refs, 557 edges, 3 invariants, 3 binds, zero errors,
  warnings, or infos
- `uv run backstitch check --repo-root . --show-suppressions`: exit 0 with the
  same zero-issue summary and 202 auditable suppressions
- `bin/check-dom15-fixtures`: exit 0; the [DOM-15] fixture contract is OK
- the EVC, plan, and plan-index changes remain uncommitted; coordinated
  [EVC-12.1] promotion remains the explicit implementation blocker

### Current Verifier-Role Verification Record

Recorded 2026-07-15 for the verifier-role revision:

- EVC SHA-256
  `b4170553afbd2785f5ef8f7e312f368f94a61c057a137901e32dc48ed967ac3a`
  and plan pre-record SHA-256
  `31fee499989f64a83d5ed803e4836cad48185df40e83a7c2be4301273d672f92`
  received independent PASS with no open P1/P2
- tracked-file `git diff --check`: exit 0; untracked-plan
  `git diff --no-index --check`: expected exit 1 because the whole file is new,
  with no whitespace-error output
- `uv run backstitch check --repo-root .`: exit 0; 113 spec sections, 182
  mappings, 288 code refs, 557 edges, 3 invariants, 3 binds, zero errors,
  warnings, or infos
- `uv run backstitch check --repo-root . --show-suppressions`: exit 0 with the
  same zero-issue summary and 202 auditable suppressions
- `bin/check-dom15-fixtures`: exit 0; the [DOM-15] fixture contract is OK
- the EVC remains proposed; the EVC, plan, and plan-index changes remain
  uncommitted; coordinated [EVC-12.1] promotion remains the explicit
  implementation blocker

### Current Implementation Closure Verification Record

Recorded 2026-07-16 for the report-only implementation claim:

- `uv run pytest -q -m 'not live_llm'`: exit 0 across the final 1,616-test
  non-live collection
- `uv run ruff check .`: exit 0; `uv run ruff format --check backstitch bin
  .github/scripts tests`: exit 0 across 117 checked source files
- `uv run mypy backstitch bin/release.py tests --config-file pyproject.toml`:
  exit 0 across 116 source files
- `bin/check-dom15-fixtures`: exit 0; the [DOM-15] fixture contract is OK
- `uv run backstitch check --repo-root .`: exit 0; 115 spec sections, 230
  mappings, 331 code refs, 668 edges, 3 invariants, 3 binds, and zero errors,
  warnings, or infos
- `uv run backstitch check --repo-root . --show-suppressions`: exit 0 with the
  same zero-issue summary and 200 auditable suppressions
- `git diff --check`: exit 0
- the hosted `gpt-5.4-mini` live transport contract passed; local
  `llama3.2:3b` accepted transport/schema but returned malformed non-JSON and
  exited 2 without weakening normalization
- the integrated implementation rereview passed with no open P1/P2 after four
  qualification-boundary defects were corrected
- the worktree remains uncommitted and is not ready to land; the historical
  Phase A/B results were not rerun against the final distribution, the
  semantic candidate has zero reviewed historical units, no reviewed Linux
  runner identity exists, and the current 23,170,539-byte self packet report
  exceeds the normal 10 MiB ceiling

## Fresh-Eyes Review

Run the first fresh-eyes review at Phase A/B, not only at completion. Give the
reviewer only public help, the installed guide, a clean fixture with no
traceability, a partial fixture, a complete fixture, a skipped fixture, and the
promoted specs. They must bootstrap from list to summary to discovery to
source-edit guidance, make source edits themselves, observe readiness change,
and explain why Backstitch did not ratify the change. Record the authoring-cost,
candidate-disposition, and first-reviewed-diff measures before packet work.

Repeat the review before completion with packet/currentness behavior added. The
reviewer must build a packet, replay it, provoke staleness, and explain why
static relation and model judgment do not establish alignment.

## What Already Exists

- The trace graph already models mappings, backlinks, invariant declarations,
  binds, issues, and reciprocal failures. The plan reuses it as authority.
- The semantic gate already owns deterministic packets, hashes, cache, model
  normalization, policy projection, reports, and eval seams in the dirty
  worktree. The plan changes their input, not their trust split.
- The exclusion system already owns source annotations and suppression audit.
  The plan extends parsing/reporting only and adds no writer.
- The CLI already owns repository discovery, config, exit behavior, and lazy
  provider imports. New adapters stay thin.

## Out Of Scope

- automatic edits or a v1 `--fix` mode
- proposal JSON, active evidence manifests, case activation/deactivation, and
  garbage collection
- runtime instrumentation or claims of actual execution coverage
- HTTP, SSE, or remote MCP transports
- arbitrary filesystem/query tools or agent-defined relation kinds
- non-Python static call graphs in v1
- model-selected trusted evidence or automatic human approval
- automatic error promotion based only on model support scores
- cross-model correlation benchmarking or any evidence-class advantage for a
  distinct analyzer/verifier tuple
- a skill installer or duplicated normative rules in the thin repository skill
- implementation of [COV-3] through [COV-9]'s intent-coverage computation,
  ratchet, anti-Goodhart sampling, or drift coverage; this plan reconciles only
  [COV-6]/[COV-9]'s superseded interface vocabulary and acceptance dependency

## Deviation Log

Append-only. The superseding product-model review is recorded because it
changes the earlier planned contract before implementation.

| Date | Slice | Spec ref | Deviation and reason | Risk/invariant effect | Verification | Review disposition | Promoted baseline |
|---|---|---|---|---|---|---|---|
| 2026-07-15 | planning | [EVC-2], [EVC-4], [EVC-8], [EVC-9] | Replace active evidence-case authority with source-declared alignment and derived packets. | Removes second authority, source mutation, and persistence lifecycle; requires a full EVC rewrite. | This review pass plus fresh independent review after rewrite. | Accepted by owner discussion; independent review pending. | pending |
| 2026-07-15 | planning review closure | [EVC-1] through [EVC-12.1] | Close the aligned-intent rewrite without promoting it ahead of active integration specs. | Preserves source authority and leaves implementation blocked on coordinated promotion. | Independent PASS at EVC `3f4919a6…` and plan pre-record `e7089e96…`; default self-corpus and suppression audit recorded below. | Accepted with no open P1/P2. | pending coordinated promotion |
| 2026-07-15 | product-fit staging review | [EVC-8.6], [EVC-10], [EVC-10.1], [EVC-10.2], [EVC-12], [COV-6], [COV-9] | Qualify obligation core, discovery, packets, optional MCP, and semantics as separate product stages; preregister Phase A/B inputs, exact result math, and independent stop gates; make MCP truly optional; replace COV proposal probes. | Prevents late discovery of a weak deterministic wedge, post-hoc dogfood thresholds, combined-stage pass laundering, and optional-adapter coupling. | Independent PASS at EVC `2c26c644…` and plan pre-record `0ad072692…`; current self-corpus, suppression, DOM-15, and diff gates recorded below. | Accepted with no open P1/P2. | pending coordinated promotion |
| 2026-07-15 | verifier-role review | [EVC-3], [EVC-5], [EVC-10.1], [EVC-12] | Remove cross-model correlation and tuple inequality as qualification surrogates; define procedural adversarial independence; default to complete analyze-provider reuse with optional all-or-nothing override. | Reduces provider/config burden without weakening the exact composed-pipeline precision, sensitivity, critical-case, stability, or replay gate. | Fresh independent rereview plus self-corpus, suppression, DOM-15, and diff gates. | Owner-directed revision; independent review pending. | pending coordinated promotion |
| 2026-07-15 | verifier-role review closure | [EVC-3.1], [EVC-5], [EVC-6], [EVC-10.1], [EVC-12], [EVC-12.1] | Close the verifier as a blinded, adversarial, replayable function rather than a cross-model oracle; bind qualification to exact composed identities and measured repo-corpus quality. | Removes unearned tuple-diversity authority while preventing stable rubber stamps, stale qualification selectors, partial provider inheritance, and cached trials from understating flips. | Independent PASS at EVC `b4170553…` and plan pre-record `31fee499…`; current self-corpus, suppression, DOM-15, and diff gates recorded below. | Accepted with no open P1/P2. | pending coordinated promotion |
| 2026-07-15 | coordinated promotion closure | [EVC-12.1], [SC-*], [CFG-*], [EXC-*], [INV-*], [SEM-*], [COV-6], [COV-9] | Promote EVC and SEM only with the reconciled active contracts; keep COV proposed and MCP conditional. | Establishes one source-authority and one current gate path before code cites EVC. | Independent PASS over the exact promotion hashes; default check 0/zero issues, 202 auditable suppressions, DOM-15 and diff gates pass. | Accepted with no open P1/P2; Slice 0 cleared. | HEAD `25346a9…` plus reviewed worktree hashes |
| 2026-07-15 | Slice 1 implementation correction | [EVC-8.2], [SC-4] | Bind the frozen path/kind catalog into snapshot identity and converge captured exact mapping targets. The promoted file-only identity could collide across missing versus empty roots or out-of-root mapping-target changes that alter deterministic readiness. | Restores the invariant that every resolver-affecting captured fact changes snapshot identity without narrowing [SC-4]; adds bounded catalog identity, target-set convergence, and NFC path closure without clone-local stat data. | Focused catalog/target/canonicalization identity and mutation tests plus independent spec/code review before Slice 1 closure. | First review found one P1 out-of-root target gap and one P2 canonicalization gap; both closed. Rereview PASS at EVC `328b3a60…`, plan pre-record `c7edcd5d…`. | supersedes promoted [EVC-8.2] snapshot object |
| 2026-07-15 | Slice 1 configuration-input correction | [CFG-3], [CFG-6], [EVC-8.2] | Preserve legal parent and user-level config discovery while keeping clone-local absolute config paths out of snapshot identity. The promoted repository-relative-only file table could not represent an applied config outside `--repo-root`. | Adds one ordered path-free config-input identity lane, retains exact loader bytes, and revalidates them before and after every whole capture attempt. Repository-contained configs remain file rows and physical counts are deduplicated. | Parent-config capture, exact-byte identity, mutation/retry, clone-root exclusion, check routing, focused snapshot/runtime/settings/CLI/acceptance tests, self-corpus, Ruff, and mypy; fresh independent review required. | Initial review found a P1 leaf re-resolution/symlink bypass and P2 catalog-kind mismatch. Both were corrected; rereview PASS with 121 focused tests, Ruff, mypy, equal-clone identity, dedup, and exact symlink/identity-change probes. | supersedes the promoted [EVC-8.2] snapshot object shape before release |
| 2026-07-15 | Slice 0 preregistration correction | [EVC-10.2] | Make candidate capture count only eligible `accepted`/`rejected` gold and treat `irrelevant` gold solely as negative controls. The first frozen corpus made correct omission of irrelevant rows lower capture, so the two metrics contradicted each other. | Restores disjoint positive-recall and false-surfacing measures; requires regenerated manifests/results and a fresh independent review before dogfood. | Closed result recomputation tests, isolated installed-CLI fixture probes, exact-threshold/path mutation tests, and independent preregistration rereview. | First review FAIL: metric contradiction plus result-validator, fixture-root, Phase A task, threshold, label, and Unicode-path gaps. Correction in progress; dogfood blocked. | supersedes preregistration digest `e7e53a87…` |
| 2026-07-16 | Slice 0 preregistration hardening | [EVC-10.2] | Fresh preregistration review found that Phase B copied its expected trace state and complete gold set from production output, result product hashes were self-asserted, section declaration sets could be one-sided, Phase A used repo-wide issue heuristics, and session observations did not bind candidate-run paths. | Separates reviewed gold from discovery so misses and trace errors can fail measured checks; binds plan/results to authoritative distribution, guide, and skill bytes; derives exact declarations/readiness; preserves source authority. Candidate and product artifacts must be regenerated after the final static-discovery closure fix. | Failing-then-passing identity, independent-gold, one-sided-declaration, path-binding, capture/precision/critical mutation, production-artifact rederivation, Ruff, mypy, diff, and fresh independent review. | Correction implemented; final artifact freeze and independent rereview pending. Dogfood and dependent packet work remain blocked. | supersedes the in-progress 2026-07-15 Slice 0 corpus before any participant session |
| 2026-07-16 | Slice 0 preregistration freeze closure | [EVC-10.2] | Freeze the final reviewed obligation/discovery product after path-stable receipt and readiness corrections. Add two independently judged module-owner negative controls as `rejected`/`untraced`/noncritical; regenerate every fixture tree, candidate artifact, phase manifest, protocol hash, and authoritative product identity. | Produces 62 gold rows: 61 eligible, 60 captured eligible, one deliberately uncaptured noncritical row, 61/61 correct surfaced trace states, one surfaced irrelevant control, and all 29 critical rows captured. No participant has seen output and no dogfood result exists. | Strict loader and hash rederivation; 77 alignment-eval tests; 76 adjacent obligation/discovery/acceptance tests; independent metric-failure mutations; Ruff, format, mypy, self-corpus at zero issues, suppression audit, and diff gates. | Fresh-eyes preregistration audit PASS with no open P1/P2. Dogfood remains a separate owner stop/continue action and was not run. | manifest `88a136bed561dd2b9a2fe6b23b13796cf4d8744999bb02521349a0133b115ec4`; distribution `2e1bcfdca49832d13eef127a26079914557fd85e6cb6e549284b10751530900f`; guide `45e678f3eca717d65313b7bea6617a2b2a532e7b1ca20376cf249c7234acc04b`; skill `f7929a9424eb6818b7a90b7231c4ce97d830fe116ffbab328dc3ee420aff512a`; Phase B `0b1a472b2cde21d7bdef8120358530aa728fb439e4a0b98af8f82b1a2c7d14d0`; protocol `eef9afb4502656c710351b893aba3149daec6f214613ee1c76235b4e729cab97` |
| 2026-07-16 | Slice 0 Phase A measurement correction | [EVC-10.2] | A Phase A run showed that byte-bound proof observations were being used as the product-call count even when participants made additional summary, discovery, detail, or check calls. Add an ordered `backstitch_calls` ledger for every allowlisted task-scoped read-only call; keep `cli_observations` as its byte-bound proof subset. | Prevents interaction-cost undercount without turning unproved auxiliary output into qualification evidence. Count/log mismatch, malformed call grammar, unresolved revision binding, or a proof call absent from the ledger becomes `INVALID_OBSERVATION`. No run under the superseded digest is accepted for qualification. | Strict hash rederivation; 84 alignment-eval tests including default-format, auxiliary-check, count, proof-subset, ordinal, revision, command, root, and format cases; 76 adjacent tests; Ruff, format, mypy, self-corpus at zero issues, suppression audit, and diff gates. | Independent correction review PASS with no open P1/P2. No further dogfood was run under the corrected manifest. | manifest `94d9553b02765df2f4ddb41e7d5ae609051b48ad74f992b1adc8d18c5adbb06d`; distribution `f096daeaaf27604083a37dc836c7b77d583d412f40c888d71005bf3df50afbcc`; guide `45e678f3eca717d65313b7bea6617a2b2a532e7b1ca20376cf249c7234acc04b`; skill `f7929a9424eb6818b7a90b7231c4ce97d830fe116ffbab328dc3ee420aff512a`; Phase A `1317a3178047e29944a14ae4c938f5b67bc5527b089696ee9e5ece15e506d2a9`; Phase B `0b1a472b2cde21d7bdef8120358530aa728fb439e4a0b98af8f82b1a2c7d14d0`; protocol `5f6326b8ce0949b5b7357d6a676793b3971a88085f1b8f4b0358c1e665efa95b` |
| 2026-07-16 | Slice 0 Phase A authority/timing correction | [EVC-10.2] | Independent review of result `dc338206…` found that it stored recorder-asserted `{proposition, correct}` rows instead of raw participant answers and measured only first-to-last product-call time even though all fixtures were visible at session start. Replace the result field with `{proposition, answer}`, derive correctness from the frozen rubric, and release fixtures one at a time with runner-observed handoff-to-submission timing. | Prevents a recorder from self-asserting comprehension and prevents orientation or reasoning time from disappearing from authoring-cost evidence. The old result is retained as a failed, superseded run; it cannot qualify the new distribution or manifest. | Firing tests make one valid false answer lower the derived comprehension rate and fail its check; old keys, wrong propositions/order, and non-boolean answers are invalid. Run fixtures sequentially under a fresh independently approved digest and audit task timing against participant records. Manifest bytes must be canonical JSON with an optional final LF; result identity always uses the canonical object digest. Referenced phase manifests require exact canonical bytes and bind their raw-byte hashes. | Final independent rereview PASS after closing the earlier P1/P2 result defects, canonical-versus-raw identity ambiguity, and appended-byte fixture-manifest gap. No open P1/P2; fresh sequential Phase A dogfood is cleared. | qualification manifest `e623b164717ff164b8c5024f5dd11f2fed2003f6983cbd875253be9f3fa02693`; raw file `40e818166f2b2cf225b5753930e984dba0fe448611bcb8c3051f29964015f28d`; distribution `126143f89f0440644a442453d993435a184cb01f7775c7624e204aaefd7c1cef`; protocol `013274ac9fd2102046f35046428af06c88777d82674c8f1567ea99dc7120ce28` |
| 2026-07-16 | Phase A stop/continue | [EVC-10.2] | Run two fresh public-help-only sessions with one-at-a-time fixture release, raw authority answers, actual complete JSON proof calls, participant-owned diffs, and monotonic handoff timing. Retain an earlier text-output run as nonqualifying exploratory evidence rather than inventing absent JSON calls. | Measures the real bootstrap loop without recorder-created evidence. The accepted result is valid only for its exact qualification and distribution identities. | Production result loading, transcript-to-call/output/diff/tree/timing audit, source-boundary audit, 10/10 bootstrap outcomes, and 2/2 raw authority sessions. | Independent PASS with no open P1/P2. This stage record is historical after the subsequent Phase B proof correction changes the tested distribution. | result `ee55e65cc9e2badd686f5237335ff77c48dea8be02e1124af340cde2b3925b4a`; timing ledger `0d524114c040078ccaf09eb3c7e9e8e2d02de8c1094e021b5f6287744a65cf88`; qualification `e623b164717ff164b8c5024f5dd11f2fed2003f6983cbd875253be9f3fa02693` |
| 2026-07-16 | Slice 0 Phase B public-proof correction | [EVC-10.2] | A pre-Phase-B public probe showed that the result helper synthesized one all-candidate envelope while the exact public command returned a five-row page with a cursor, and Phase B outputs were not rerun. Make the canonical proof an actual `--find-evidence --limit 100 --format json` call with `next_cursor = null`; rerun it byte-for-byte for Phase B; keep default pages and cursor review calls in the interaction ledger. | Prevents synthetic evaluation output from qualifying discovery and preserves actual public-command provenance without expanding the result schema. Any distribution change invalidates the prior Phase A identity, so fresh Phase A must run again after preregistration review. | Actual full public-output construction in tests; synthetic-guidance/hash mutation rejection; complete output/candidate/snapshot equality; focused result suite, Ruff, format, mypy, diff, self-corpus, and independent rereview before dogfood. | Independent preregistration rereview PASS with no open P1/P2. All 92 alignment/result tests and quality/self-corpus gates pass; fresh Phase A is cleared under the new identity. | qualification `857cd0b3317e568d359573803d321dd2776cd1b7872c1a465970ac4b1f21ebc3`; raw manifest `b1055b2e70ac6ed5a5bc25ffb7e45721693b3031f390c69ae701b601c8b26ebc`; distribution `3d728f764d623452d7dbeb8719619fb4e28826903ddba0798c0c1df234b616aa`; protocol `ce1b3f8b000b4530f2549a357986b75fdab49042e1526247f656feb5cadcff92` |
| 2026-07-16 | Phase A stop/continue after public-proof correction | [EVC-10.2] | Re-run the full one-at-a-time Phase A workflow under qualification `857cd0b3…` using two clean public-help-only identities. Discard a coached replacement session and replace it rather than laundering the interaction into qualification evidence. | Preserves independent participant behavior and proves 10/10 bootstrap outcomes plus 2/2 authority sessions for the exact corrected distribution. This record becomes historical when the evaluation distribution changes below; its participant evidence remains an audit input, not a current qualification. | Production loader recomputation, raw transcript/call ordering audit, exact proof-output reruns, tree/diff/timing ledgers, and independent final review. | PASS with no open P1/P2. | result `dd7eabb8cf65c7e26abd25342f6f8e9ae24c935e6f1aa4b8cf28730b3193ba2a`; timing `2ae998c60ccf916fc53eca452b25bfecd55dd685bca08570bf9363cbc8e056a7`; qualification `857cd0b3317e568d359573803d321dd2776cd1b7872c1a465970ac4b1f21ebc3` |
| 2026-07-16 | Slice 0 Phase B human-disposition and lifecycle correction | [EVC-2.3], [EVC-10.2] | Exploratory Phase B showed two agents independently selected several behaviorally plausible candidates that frozen human gold rejected. Stop treating hidden human disposition as a participant answer. Define Phase B's core question as "Given obligation X, what current code or tests are plausible candidates?" Bind exact human-accepted IDs as task input only for post-selection trace authoring. Split phase protocols and phase qualification identities. Make bootstrap refreshable and keep the later current packet/semantic operation as the gate. | Preserves independent discovery gold, including accepted misses; first-diff declarations derive from accepted intersect surfaced candidates and subtract declarations already present in the original tree; one cumulative original-based diff covers the complete missing set. A valid Phase-B-only change no longer invalidates Phase A, while common product drift still does. Phase B remains valuable for search-set quality and bridge usability but confers no gate authority. | Absent-accepted, partial-versus-untraced missing declarations, exact human-input, multi-accepted cumulative set, refresh, phase identity isolation, prior Phase A survival, schema/hash, full alignment-eval/result, guide/skill, quality, self-corpus, and fresh independent review gates. | Final independent rereview PASS after closing the partial-candidate missing-declaration defect and adding the public refresh probe. Fresh phase results remain pending. | top `7711088361f11a7f27fe853532485cef827eb1d9106b92601dba91e5c1ffe0ef`; Phase A `4cf7c5d2750cf4821b9c69c8658d581c94b62aa9bcb510e91761deee6ea40d4d`; Phase B `bad5690e4853c4db8d612bd0fdda953b89b67b84baa55abd94d2f3d746c99cc9`; distribution `e43d58a0fb0e293643d5d6ab927abba59c9909a6f78c12944c6858b99c44c240`; guide `195587dac2541df9a367c6f65347eefccde06236ef16a1fb0e07861774ae3dcb`; skill `9b2db4508689bd8eaca9ad50bcb128f9656d5b0e4be7131df615b8465526a403`; A protocol `64b10dd459ce5bdd44aa27f85ec366ce731f768739563e8dc9d8074dec0c436c`; B protocol `4824651ca1a2ffe00213fcda7f88a77bc1eeed26ea5cb321e24d7a5e18f7b8b6` |
| 2026-07-16 | Phase A stop/continue after human-disposition correction | [EVC-10.2] | Re-run the full one-at-a-time Phase A workflow under qualification `4cf7c5d2…` using two oriented public-help-only identities. Discard sessions 8 and 9 because the runner exposed fixture bytes before orientation; neither session appears in the accepted result. | Preserves the preregistered release boundary and measures the exact corrected common distribution before Phase B. The accepted result contains participant-owned call ledgers and diffs, raw authority answers, and runner-owned handoff-to-submission timing. | Production loader recomputation, byte-for-byte proof reruns, transcript/call/diff/tree/timing audit, 10/10 bootstrap outcomes, 2/2 authority sessions, and an independent focused-test audit. | Independent PASS with no open P1/P2. Phase B may proceed against this exact prior result. | result `a92964db5f7d7006b35b23eb5501cc2939ed7784f399c3e5a384e43e49897090`; timing `fa6fff697955b6c55f63a202853032741936cd7f5cdd1db371ba6e7247b32be7`; Phase A qualification `4cf7c5d2750cf4821b9c69c8658d581c94b62aa9bcb510e91761deee6ea40d4d`; distribution `e43d58a0fb0e293643d5d6ab927abba59c9909a6f78c12944c6858b99c44c240` |
| 2026-07-16 | Phase B stop/continue after human-disposition correction | [EVC-10.2] | Run all seven frozen discovery fixtures in two one-at-a-time public-help-only sessions. Supply the exact human-accepted projection as task input only after discovery; preserve rejected/irrelevant gold as hidden product measurement. | Separates search-set quality from human authority while measuring the practical bridge from a selected candidate to reciprocal source declarations. The one accepted untraced candidate requires a first diff; the accepted declared candidate requires no edit; empty accepted projections require no edit. | Production result loading against the bound passing Phase A result; exact full-page public-output reruns; all candidate/gold/tree/hash projections; participant call and no-edit ledgers; original-based first diffs; deterministic executability; and monotonic timing. | Independent PASS with no open P1/P2. Capture is 60/61 eligible (`0.9836065574`), trace-state precision 61/61, irrelevant surfacing 1/61, critical capture 29/29, and first-diff correctness 2/2. Future runners should preserve distinct pre-edit and post-edit proof files; this run remains valid because participant ledgers attest the original calls and preserved-tree reruns are byte-identical. | result `6b8f1bdc6e2bf078977388d8e10ea8bdbefb65c8c6c9fd78cab66bf180eed5aa`; timing `cd8b8ebcee2e04a6a3349e640749b36ca96a9df7115bb58d8426ac5e30b4bb0b`; Phase B qualification `bad5690e4853c4db8d612bd0fdda953b89b67b84baa55abd94d2f3d746c99cc9`; prior Phase A `a92964db5f7d7006b35b23eb5501cc2939ed7784f399c3e5a384e43e49897090` |
| 2026-07-16 | Phase D MCP benefit gate | [EVC-8.6], [EVC-10.2] | Defer the optional MCP adapter. The canonical Phase B discovery task already completes in one CLI call. Its seven complete response bodies are 5,186 through 33,749 bytes (132,846 bytes total), and required MCP parity would return the same core payload bytes. | A stdio adapter cannot reduce the measured one-call baseline or response-byte/context payload under the parity contract. Adding an SDK, command, resource, tools, credential/import boundary, and installed-wheel client would create surface without demonstrated product leverage. CLI remains the sufficient public interface; MCP can be reconsidered only with a new measured task where transport changes call, byte, or context cost. | Phase B call ledgers and exact output byte counts; absence of a qualifying pinned SDK/API and real-client benefit decision. | Deferred by the preregistered entry gate. No MCP command, dependency, resource, tool, eval surface, or qualification cohort will ship in this change. | CLI full-page outputs: `5186`, `5297`, `10480`, `14467`, `30341`, `33326`, `33749` bytes; canonical direct task call count `1` |
| 2026-07-16 | Slice 6 source-aligned packet compiler | [EVC-9.1], [SEM-3], [SEM-5], [SEM-7] | Replace current packet production with one immutable-runtime compiler and schema-2 source report while retaining old readers only for migration diagnostics. Harden every reader-owned cross-field relationship found by review rather than trusting self-hashes. | Current packets consume only source-declared evidence, include deterministic counterevidence, and cannot be minted for non-executable obligations. Packet/report identity, exact citation coordinates, readiness, issue/audit recomputation, current-runtime bytes, report ceilings, and staged publication fail closed. | 199 focused packet/result/report/analysis/CLI tests; Ruff, format, focused mypy, `git diff --check`; production v3-to-report-v2 analyzer preflight; exact source-mutation and forgery probes. | Independent review initially found four P1 classes and one P2, then three residual P1s, then one role P1 plus excerpt-span P2. Final rereview PASS with no open P1/P2. | uncommitted worktree checkpoint; Slice 7 may start after its spec rereview passes |
| 2026-07-16 | Slice 7 pre-implementation contract closure | [SC-5], [CFG-6.5], [EVC-3.1], [EVC-5], [EVC-10.1], [SEM-4], [SEM-9] | Close verifier work cardinality, outbound bytes/schema, result evidence, lock/cleanup namespaces, runtime ownership, qualification-authority sequencing, producer-config migration, and the independently frozen Phase C fixture/currentness manifest before code. | Prevents per-packet verifier undercount, dead stale-age config, hidden currentness orchestration, unsupported refutation, implicit qualification defaults, and premature independently-verified failure authority. | Exact contract rereview across EVC/SEM/SC/CFG/plan, including closed Phase C fixture/scenario/hash/transform/gold rules. | Independent review required four revision passes; final PASS with no open P1/P2. | Slice 7 implementation cleared |
| 2026-07-16 | Phase C stop/continue | [EVC-5.1], [EVC-9.1] | Execute every preregistered packet/currentness scenario through production packet and analysis paths, with controlled adapters only at the provider boundary. | Proves current versus historical scope, relevant/unrelated packet identity, corrupt-artifact rejection, in-flight publication withholding, per-fixture zero-call readiness, and cold analyzer/verifier primary followed by exact require-mode replay. This is a plan-owned verification record, not a semantic qualification artifact. | Manifest raw `2244a9ba5a7b5e09e376ffaa9d053bf6c073a1d8349b1d7525f27928267072ad`; canonical object `a4ab149407d9d4443c35c55a29a39eb2a35dee4f8320feb2b057287f6ab3e2e6`; six recorded fixture-tree hashes; 12 manifest-driven tests; Ruff, format, mypy, and diff checks. | Final independent rereview PASS with no open P1/P2 after current-generation identity and artifact-specific corruption diagnostics were added. | Continue to Slice 8 contract closure; manifest and fixture gold were frozen and independently reviewed before the first run. |
| 2026-07-16 | Slice 8 pre-implementation contract closure | [CFG-6.7], [EVC-6], [EVC-8.4], [EVC-10.1], [EVC-12] | Replace the obsolete analyzer-only eval contract with one variant-scoped schema-3 semantic corpus/report and exact strong-policy authority boundary. Keep A/B, Phase C, semantic measurement, and performance as separate evidence products. | Closes trial-collapsed metric equations, cold analyzer/verifier primary and cache-only replay, complete cache-object provenance, canonical long-code cohorts, reviewed historical/critical controls, source-derivation and qualification-config invalidation, candidate generation before human digest pinning, and noncircular output publication. | EVC `192f92b0df394733d743a64bebe191bbe5938829acf9e037e6b130e963c762ad`; CFG `63df011ffa497776b87d57068bf65453fda04c0daf451d8c2fd72c6968f11286`; plan pre-record `aaa2b1442081aa0e8430b8007e0b24abb609320b0d15bbb7ac1c3b5a2253cf1d`; self-corpus 0 errors/warnings/suppressions. | Independent review required two revision rounds and finished PASS with no open P1/P2. | Slice 8.1 implementation cleared. |
| 2026-07-16 | Slice 8.1 through 8.4 implementation | [EVC-3.1], [EVC-5], [EVC-6], [EVC-9.1], [EVC-10.1] | Implement the schema-3 corpus/report runner, source-derived observed-fact validator, cold-primary plus cache-only replay, trial-collapsed metrics, exact composition/source-derivation identities, and fail-closed strong-selector loader. | Keeps report mode observational and requires an exact reviewed enforce corpus/report before independently-verified selectors gain failure authority. The CLI now preserves the complete qualification problem row, bounded report bytes, bare raw-byte digest, and configured output/report non-aliasing; the shared runner receives the same eval settings as CLI preflight. | Focused semantic eval/report/policy/analysis matrices, schema-3 smoke corpus, hosted transport contract, and independent integration review plus correction rereview. | Initial integration review found three P2 qualification-boundary gaps. The first correction rereview found one residual configured-report/input alias. All four were corrected; final focused rereview PASS with no open P1/P2. | implemented, report-only |
| 2026-07-16 | Slice 8 discovery and self-scale correction | [EVC-7], [EVC-8.3], [EVC-9.1] | Make path-only trace authority name only the exact module candidate, bound lexical seeds to class/function/method definitions with a default of ten, and prepare the snapshot-bound parse/static catalog once per multi-obligation operation. Mechanically refresh only Phase B candidate artifacts after discovery semantics changed; do not rerun Phase A. | Prevents whole-file declaration inflation and cross-obligation mutable-state leakage while preserving deterministic work accounting. The self semantic packet remains fail-closed rather than silently truncating imprecise broad traces. | Path-only and catalog-isolation firing tests; full Phase B artifact rederivation; self measurement of 51 packets, 23,170,539 JSONL bytes, 23,263,716 prompt bytes, 1,013,964 largest prompt; development timing improved from roughly 2m48s to 45.5s. | Independent review accepted the product boundary; packet-size debt remains explicit. | implemented; self semantic packet unavailable under 10 MiB ceiling |
| 2026-07-16 | Slice 8.5 corpus stop | [EVC-10.1] | Freeze an enforce-shaped 20-case schema-3 candidate with all closed controls before any model output, but do not call generated synthetic cases historical evidence. | The corpus proves structural loadability and source-derived gold consistency only. Its substantive reviewed-historical count is zero, so no provider run or report may grant strong policy authority. | Generator drift check, 40 source-derived variants, all control tags, critical valid-but-vacuous trace, independent source review, and corpus acceptance tests. | FAIL for policy authority; PASS for structural/internal source integrity. | semantic enforce qualification unavailable pending 20 stable historical misalignment sources and human approval |
| 2026-07-16 | Slice 8.6 performance stop | [EVC-10] | Commit the exact scale shape and runner-availability contract, but do not invent `runner-contract.json`, a `semantic-scale` job, or a Linux baseline from the arm64 development machine. | Performance status is explicitly unavailable for missing, invalid, unobserved, or mismatched runtime identity and cannot alter semantic authority. | Exact generator/tests for 1,000 obligations, 5,000 modules, 20,000 candidates, and 50 MiB; firing tests for every runner-availability state. | Missing reviewed Linux runner identity and same-environment baseline are explicit blockers. | performance qualification unavailable |
| 2026-07-16 | Slice 8 live transport and refresh posture | [SEM-7], [SEM-9], [EVC-3.1], [EVC-10.1] | Keep provider-backed work authorized but evidence-scoped. The hosted `gpt-5.4-mini` contract passed; local `llama3.2:3b` accepted transport/schema but returned malformed non-JSON after roughly six minutes. Update trusted refresh to current-source analysis plus the schema-3 smoke evaluator in report mode under an exact reviewed config allowlist. | A weak local model cannot weaken normalization. Trusted refresh produces review artifacts only and cannot select the synthetic qualification candidate or grant policy authority. | Hosted live test PASS; local live test honest exit 2; exact refresh-config mutation tests; release-workflow tests. | Local model not gate-qualified; hosted transport success is not semantic qualification. | report-only refresh path implemented |
| 2026-07-16 | Slices 8.7 and 9 implementation closure | [EVC-6], [EVC-8.6], [EVC-10], [EVC-10.1], [EVC-10.2], [EVC-12] | Close the CLI-first aligned-intent implementation and documentation without laundering historical Phase A/B results, synthetic semantic fixtures, hosted transport success, or an unobserved runner into product authority. Keep MCP deferred because the measured task is already one CLI call. | Public bootstrap, human-owned source alignment, current-source packet compilation, adversarial verification, replay, evaluation, and fail-closed policy machinery are implemented. Strong semantic policy, current bootstrap/discovery qualification, self-dogfood analysis under the normal packet ceiling, and pinned-runner performance remain explicitly unavailable. | Full 1,616-test non-live collection and test run; Ruff check and format; mypy over 116 source files; DOM-15 fixture contract; default self-corpus with zero issues; 200-item suppression audit; `git diff --check`; hosted/local live outcomes recorded separately. | Integrated review found four P2 qualification-boundary defects across two passes; final rereview PASS with no open P1/P2. | uncommitted report-only implementation; not ready to land |
| 2026-07-17 | Slice 6 hardening closure | [EVC-7], [EVC-8], [EVC-10.2] | Retain the accepted eight-module aligned-intent split: `alignment_eval`, `alignment_guide`, `evidence_discovery`, `evidence_summary`, `obligation_api`, `obligation_runtime`, `obligations`, and `repository_snapshot`. The implementation proved distinct ownership boundaries beyond the earlier compact module sketch. | Keeps capture, orchestration, source projection, public envelopes, guidance, and qualification separate while preserving repository source as the sole alignment authority. No public contract or feature is added. | Hardening boundary pins, focused owner tests, full non-live suite, self-corpus, Ruff, mypy, and repository-map inspection. | Accepted by the reviewed evidence-spike hardening plan; final implementation verification recorded there. | uncommitted hardening checkpoint |

## Definition Of Done

- The EVC and integration specs express source-declared alignment as authority
  and have a fresh independent PASS.
- Every in-scope slice is implemented or an explicit blocker narrows the claim.
- CLI alone exposes the complete obligation core. If Phase D is implemented,
  MCP exposes that same core with exact parity; if deferred, its owner record
  exists and the distribution advertises no MCP surface.
- Backstitch performs no repository-source mutation and no derived artifact can
  override current source alignment.
- Every enumerable state, command, flag, config key, relation, candidate kind,
  trace state, guidance code, diagnostic, schema, and exit path has a firing
  test.
- Full non-live tests, acceptance probes, Ruff, format, mypy, self-corpus,
  suppression audit, and diff check pass with observed results recorded here.
- Independent slice reviews and final fresh-eyes review pass.
- Dogfood reports separate bootstrap/alignment quality from semantic/verifier
  quality and policy authority does not exceed measured evidence. Same-model
  and distinct-model compositions use the same exact qualification contract;
  no correlation or tuple-diversity claim enters promotion.
- Specs, implementation docs, guide, repository map, mappings, backlinks, and
  code agree; durable lessons are recorded.
- If the owner asks to land the work, completed slices are committed and
  verified with `git log`. Otherwise the handoff says uncommitted and does not
  call the work ready to land.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|---|---|---|---|---|---|
| CEO Review | `/plan-ceo-review` | Scope and strategy | 0 | not run | Product direction was resolved in the user discussion. |
| Codex Review | `/codex review` | Independent second opinion | 0 | historical only | Prior PASS records reviewed a superseded authority model. |
| Eng Review | `/plan-eng-review` | Architecture and tests | 13 | PASS; Slice 0 cleared | Product/interface and independent technical findings are folded into the active coordinated specs and plan. |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | not applicable | No visual UI. |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | not run | CLI/MCP bootstrap acceptance is included in the plan. |

**VERDICT:** CLEARED FOR IMPLEMENTATION AT SLICE 0. The exact promoted spec
package, self-corpus result, suppression audit, DOM-15 result, hashes, and
independent PASS are recorded above.

**CLOSED PROMOTION GATE:**

- The coordinated [EVC-12.1] package passed with no open P1/P2. Later
  substantive spec changes require a fresh review and hashes.
