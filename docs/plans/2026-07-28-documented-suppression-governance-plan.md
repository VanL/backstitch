# Documented Suppression Governance Plan

Plan type: implementation with spec revision.

Status: implementation in progress.

Class: 5+P. The work changes the public suppression configuration, source
directive grammar, semantic packet/result/report contracts, and this
repository's future verification rule. It also crosses the immutable semantic
cache boundary. The Class-4 hardening checklist therefore applies, and the
process modifier requires a different-family review before implementation and
again before landing.

## Goal

Make suppression rationale a first-class, auditable repository artifact.
Repositories may continue to use Backstitch's current lightweight suppression
forms by default. Repositories that opt in require every active traceability
suppression to reference a nonblank rationale declared in a scanned spec.
Backstitch validates that relation mechanically and reviews the same
declaration, rule, matched findings, and bounded source evidence through the
existing obligation, packet, immutable-cache, semantic-policy, and disposition
lifecycle.

Backstitch opts in. Its current broad EVC rule must be narrowed to the exact
current sections or split by rationale rather than being copied forward
unchanged.

## Requested Outcomes

- [ ] Add a spec-owned suppression-declaration grammar with stable identities
  and strict reasons.
- [ ] Add one opt-in deterministic requirement. Packaged defaults remain
  backward-compatible and less strict.
- [ ] Preserve the canonical configuration resolver and immutable
  `BackstitchSettings`; generic `--option` overrides the new scalar setting
  through the existing CLI > env > config > packaged-default cascade.
- [ ] Normalize every suppression source into one canonical rule and decision
  model. Do not add a second suppression pipeline.
- [ ] Keep existing precedence, suppressibility, exit semantics, and
  `--show-suppressions` recovery.
- [ ] Extend the existing obligation and semantic lifecycle with a
  `suppression` kind. Do not add a separate LLM command, cache, report,
  disposition store, or policy engine.
- [ ] Keep section and invariant packet schemas, builders, prompts, and result
  contracts unchanged. Merely adding suppression-kind support must not change
  their bytes or keys; later source/policy migration may honestly re-key an
  existing packet when its model-visible issues/evidence change; eligibility
  changes may add or remove packets.
- [ ] Dogfood the strict deterministic and semantic modes in this repository,
  with reasons for every retained suppression and removal of stale ones.
- [ ] Add firing tests for every new config key, grammar form, diagnostic,
  packet kind, classification, report field, and compatibility path.

## Source Documents

- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10], [DOM-11], [DOM-15]
- `docs/specs/02-backstitch-core.md` [SC-6], [SC-7], [SC-8], [SC-10],
  [SC-13], [SC-15]
- `docs/specs/03-backstitch-configuration.md` [CFG-5.1], [CFG-6], [CFG-8],
  [CFG-9]
- `docs/specs/04-backstitch-traceability-exclusions.md` [EXC-1] through
  [EXC-10]
- `docs/specs/06-semantic-gates.md` [SEM-2] through [SEM-7], [SEM-9],
  [SEM-10]
- `docs/specs/07-verification-and-evidence-cases.md` [EVC-1], [EVC-2],
  [EVC-2.1], [EVC-3.1], [EVC-6], [EVC-8], [EVC-8.3.2], [EVC-8.7],
  [EVC-9.1], [EVC-10.1], [EVC-12]
- `docs/implementation/04-backstitch-style-traceability.md`
- `docs/implementation/07-deterministic-semantic-gate.md`
- `docs/plans/2026-07-27-canonical-config-resolution-plan.md`
- `docs/plans/2026-07-27-semantic-analysis-lifecycle-plan.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`

## Spec Baseline

- Diff and commit base:
  `225bc539da35fa1970061aa6a2c53de4a9f4fb78`.
- Plan-authoring file hashes:
  - `docs/specs/03-backstitch-configuration.md`:
    `469f212a3fb73760775a30de472100d22a672bc2aaad58da15734790aa915fed`
  - `docs/specs/04-backstitch-traceability-exclusions.md`:
    `703a747574ec14d83be40de21b3e368440d5de7f5648332e3e7b0a274bef0f4a`
  - `docs/specs/06-semantic-gates.md`:
    `c96b0f3a0a3c66527cce48fe2d903c4693f209befd2780d4b4001de4a92a150a`
  - `docs/specs/07-verification-and-evidence-cases.md`:
    `ed27a74a8a8f91fccfbccd01ee8ac376410d64a22f4a667741dd0e123b48d2a2`
- This plan revises all four specs. Record the promotion baseline after the
  reviewed delta is applied. Implementation compliance is against that
  promotion baseline.
- Promotion baseline applied against `225bc539da35fa1970061aa6a2c53de4a9f4fb78`
  on 2026-07-28:
  - `docs/specs/03-backstitch-configuration.md`:
    `02d81a8456b405c977b24c689013789176a40ca3e795c9fc3e42f728507c1fe6`
  - `docs/specs/04-backstitch-traceability-exclusions.md`:
    `c8d98f095a242fc1b654c8681938864f35d7625ca244a0fc2914c2ef55fba66f`
  - `docs/specs/06-semantic-gates.md`:
    `950052ff69186cc7ca6dc794c2553c69ba26762518d8474122fc839324665e0e`
  - `docs/specs/07-verification-and-evidence-cases.md`:
    `0ad09b045d1ea15b60b385d053864db6b4dc4d8ec7349eaf3878c2e8ec69ae58`
- Promotion reconciliation after the independent fresh-eyes corrections and
  Slice 1 mapping/backlink additions:
  - `docs/specs/03-backstitch-configuration.md`:
    `2b6c7ccbdb32bd4b9283ef16f00b0de8c0b02f716c7972cc2b25d5e1d5e7f65a`
  - `docs/specs/04-backstitch-traceability-exclusions.md`:
    `69a60f1f8d83ad4a5202c3b1358b9914dff4613c58dc1e344a776512ded9a8e2`
  - `docs/specs/06-semantic-gates.md`:
    `b02fb192ae0e9bf266b993a814090e416468a05622458f515634ba9892045a82`
  - `docs/specs/07-verification-and-evidence-cases.md`:
    `36c99233674900a1ffa9bae7475ac89c2a706741a1256325bdcd3dd306f6d89c`
  The corrections closed the surrounding EVC role/inventory wording, the
  CFG/EXC key tables and reason vocabulary, BSA006-BSA008 registry wording,
  schema-2/schema-3 packet-kind wording, and required reciprocal mapping
  references. They did not change the reviewed product boundary.

## Current Structure And Required Reading

Read these files before implementation:

- `backstitch/settings.py`
  - `resolve_config(...)` is the only public configuration assembly boundary.
    `LintSettings` currently carries `warn_unused_ignores`,
    `per_file_ignores`, and `per_section_ignores`.
  - Strict table parsing, `extend`, source anchoring, generic `--option`, and
    config provenance already exist. Extend them; do not parse suppression
    TOML elsewhere.
- `backstitch/exclusions.py`
  - `SuppressionIndex`, the inline parsers, config canonicalization,
    `should_suppress(...)`, and unused-rule diagnostics own current
    suppression behavior.
  - `SuppressionReason` currently means provenance (`meta`, `config_file`,
    and so on), not human rationale.
- `backstitch/check_pipeline.py` and `backstitch/reporting.py`
  - Policy is applied before suppression.
  - A suppressed record is currently the weak tuple `(Issue, str)`.
  - `--show-suppressions` is the only recovery view; JSON's existing `reason`
    field contains provenance.
- `backstitch/markdown_specs.py`, `backstitch/python_refs.py`, and
  `backstitch/resolver.py`
  - CommonMark and tree-sitter remain the source-structure owners.
  - [EVC-8.3.2]'s strict JSON reason parser is the pattern to extract and
    generalize. Do not introduce a regex-only Markdown parser or a second JSON
    string grammar.
- `backstitch/obligation_runtime.py`, `backstitch/obligations.py`,
  `backstitch/analysis_packets.py`, and `backstitch/semantic_packets.py`
  - One accepted repository snapshot feeds the deterministic report,
    obligation inventory, evidence discovery, and packet population.
  - Section and invariant are the only current obligation/packet kinds.
  - Schema-3 packets use a shared model-visible projection and immutable
    packet hash.
- `backstitch/analysis_results.py`, `backstitch/semantic_evidence.py`,
  `backstitch/semantic_policy.py`, `backstitch/semantic_analysis.py`, and
  `backstitch/semantic_reports.py`
  - Result normalization, evidence locality, diagnostic projection,
    dispositions, completeness, budgets, immutable cache, and report
    publication are already separate owners. Extend these exact owners.
- `backstitch/artifact_contracts.py`
  - Current packet and report schemas are closed. Compatibility changes need
    exact reader and producer tests, not permissive dictionary handling.
- `pyproject.toml`
  - The current audit has 206 suppressed findings from four policy families:
    DOM meta classification (15), EVC file ignore (14), COV file ignore (9),
    and the test-tree citation rule (168).
  - `analyze.cache_mode = "require"`, `require_complete = true`,
    `required_kinds = ["section", "invariant"]`, and
    `finding_handling = "require_disposition"`.

Comprehension gate before editing:

1. Why must declaration existence be checked after repository snapshot capture
   even though the declaration reference's type is checked by
   `resolve_config(...)`?
2. How can a structured `meta` rule affect both ordinary suppression and the
   obligation rung without creating two rule evaluators?
3. Which exact bytes must change a suppression packet hash, and which policy or
   rendering changes must still replay with zero provider calls?
4. Why may an evidence-bound model result create disposition debt but not
   decide whether the deterministic suppression applies?

Stop and revise the plan if the implementation cannot answer all four with one
configuration snapshot, one repository snapshot, one suppression decision
model, and the existing semantic lifecycle.

## Scope And Terminology

A **governed suppression** is an [EXC-3] meta classification, an [EXC-4] or
[EXC-5] inline ignore/meta directive, or an [EXC-6] configured ignore/meta
rule that causes a deterministic issue to enter `suppressed_issues`.

The following are deliberately not governed suppressions in this revision:

- `exclude` / `extend_exclude`: no finding is produced because the path is not
  scanned.
- `planned_spec_globs` / `exploratory_spec_globs`: these classify adoption
  state and do not suppress a finding.
- [EVC-8.3.2] obligation skips: they already require a strict source-authored
  reason and remain visible as `OBLIGATION_SKIPPED`.
- `diagnostics.level = "off"`: this is visibility policy. It remains
  recoverable in the shared audit view but is not an exception declaration.

This boundary is normative. Do not broaden the implementation to redesign scan
boundaries, skip disposition, or diagnostic policy.

A **suppression declaration** is a parsed source artifact with a stable
`SUP-*` identity and a strict nonblank rationale. A **declaration reference**
is the exact repo-relative spec path plus `#` plus that identity. A
**suppression decision** is one canonical record containing the issue,
mechanism, origin, operational scope, declaration reference, and decoded
rationale.

## Invariants And Constraints

1. **Opt-in compatibility.** Packaged
   `lint.require_suppression_declarations = false`. Existing
   `meta_spec_globs`, per-file/per-section tables, and inline directives retain
   behavior when the option is false. The new structured rules always require
   declarations because their purpose is the governed path.
2. **One resolver.** Only `resolve_config(...)` parses and validates config
   shape. The new bool participates in ordinary config/env/CLI precedence and
   works through `--option lint.require_suppression_declarations true|false`.
   Downstream code receives `BackstitchSettings`.
3. **One rule model.** Legacy config, structured config, meta classification,
   Markdown directives, and Python directives normalize to a single immutable
   `SuppressionRule`. Matching produces a single immutable
   `SuppressionDecision`. Check, audit, obligations, packets, and tests consume
   those objects.
4. **No second source parser.** Markdown structure stays with
   `markdown-it-py`; Python structure stays with tree-sitter. Strict JSON
   reason decoding and limits are shared with the existing skip-reason helper.
5. **Fail closed when opted in.** A missing, malformed, duplicate, unresolved,
   blank, or misplaced declaration does not suppress the original finding.
   It emits the exact hygiene diagnostic. `allow_unknown_keys` does not weaken
   this opt-in source-integrity rule.
6. **No model authority over deterministic truth.** A valid deterministic
   declaration authorizes suppression before any provider work. Semantic
   review can emit evidence-bound findings and disposition debt through
   [SEM-6]; it cannot apply, revoke, or silently widen the suppression.
7. **Audit compatibility.** JSON `suppressed_issues[].reason` retains its
   existing provenance value. New `declaration` and `rationale` fields are
   additive and always present (`null` for legacy records). Text output shows
   the same data. No finding disappears from both normal and audit output.
8. **Existing precedence.** Effective diagnostic policy and suppressibility
   still run first; meta, configured ignore, and inline precedence remain
   [EXC-6.2]. Declaration validity gates whether a winning rule may apply; it
   is not another precedence tier.
9. **One accepted snapshot.** Declaration parsing, rule resolution, matched
   findings, source excerpts, obligations, and packets come from the same
   accepted snapshot/config identities. No packet builder reopens current
   source.
10. **Bounded completeness.** A suppression packet contains the complete
    matched decision set for its declaration in canonical order. It never
    samples or silently truncates. Existing packet and prompt-byte ceilings
    fail the operation before provider work.
11. **Cache isolation without false hits.** Adding support for the new kind
    does not change existing section/invariant packet bytes, prompts, result
    schemas, or cache keys. A change confined to model-visible suppression
    rationale, normalized rule projection, or suppression-only evidence
    changes that suppression packet. A scope, code, source, mapping, or
    matched-issue change that alters an existing packet's post-suppression
    `issues` or declared/counterevidence must honestly re-key every affected
    packet. A meta or adoption-rung change may remove or create eligible
    packets; readiness fields excluded from the model projection do not re-key
    an otherwise unchanged packet. Do not feed pre-suppression issues into old
    packets to manufacture cache hits.
12. **Policy replay.** Changes only to diagnostic policy, dispositions,
    concurrency, rendering, output paths, or `--show-suppressions` do not
    change raw inference identity and replay with zero provider calls.
13. **No unbounded dogfood migration.** Implementation may remove or narrow
    existing suppressions. It may not add a new suppressed code, path, or
    section merely to make the self-corpus pass.
14. **Public contract discipline.** Closed artifact readers accept the exact
    prior section/invariant forms and the exact new suppression form. No
    `dict.get(...)` forward-compatibility hatch is added to closed artifacts.
15. **Quarantine.** `check`, `packets`, and obligation commands remain
    structurally unable to import or call `llm`. Packet generation remains
    deterministic.

Fatal failures:

- malformed structured config or declaration-reference syntax is config exit
  `2`;
- source declaration integrity problems are target diagnostics and leave the
  original issue unsuppressed;
- incomplete packet populations, artifact mismatch, budget exhaustion,
  malformed model output, cache integrity failure, and undisposed semantic
  findings under this repository's `require_disposition` policy are exit `2`;
- ordinary effective findings retain existing `fail_on` exit `1`.

## Rollout, Rollback, And One-Way Doors

Roll out in compatibility-first order:

1. add readers, canonical rule/decision types, and optional declarations while
   packaged strictness remains false;
2. add semantic suppression artifacts while preserving prior
   section/invariant artifacts and readers;
3. migrate this repository's rules and turn deterministic strictness on;
4. run a trusted `read-write` semantic refresh to populate new suppression
   objects and every section/invariant object honestly invalidated by the
   dogfood rule/mapping/source migration;
5. restore `require` mode and run the zero-call and disposition gates.

Rollback before step 3 is a normal code/spec revert. After step 3, roll back
the repository opt-in and structured rules together with runtime support; do
not leave a config that an older Backstitch rejects. Cache objects require no
cleanup and remain disposable. Reports are regenerated and are never rollback
inputs.

The source directive and artifact formats are compatibility surfaces, but
there is no destructive data migration and no persistent authoritative state.
Older Backstitch versions reject `suppression-declaration` and `because`
syntax as malformed; downstream repositories must upgrade the tool before
committing those opt-in forms. Clause-free legacy forms remain the mixed-version
compatibility path.
The only one-way-door-like cost is externally consumed new artifacts. Hold
their exact schema and prior-reader tests to the pre-landing review gate.

## Proposed Spec Delta

Promotion strategy: **A, active text first in already-mapped sections.** The
spec-promotion slice edits [CFG-6], [CFG-8], [CFG-9], [EXC-1], [EXC-2],
[EXC-4] through [EXC-10], [SEM-2] through [SEM-7], [SEM-9], [SEM-10],
[EVC-1], [EVC-2], [EVC-2.1], [EVC-3.1], [EVC-8], [EVC-8.7], [EVC-9.1],
and [EVC-12]. It adds no new ID-bearing section and no mapping block.
No implementation may cite the revised requirements until the later slice
that adds code, tests, any mapping additions, and reciprocal backlinks
together.

### `docs/specs/04-backstitch-traceability-exclusions.md`

Add to [EXC-1] ownership:

> This spec also owns opt-in, spec-declared rationales for governed
> suppressions and the deterministic artifacts supplied to semantic review.
> The semantic inference, cache, result, disposition, and authority lifecycle
> remains owned by [SEM-*].

Replace [EXC-2]'s “valid suppression” paragraph with:

> A valid suppression names at least one diagnostic code, except for the
> closed `meta` mechanism whose code set is [EXC-3]. Blanket ordinary ignores
> are not allowed. Every suppression normalizes to one rule with mechanism,
> origin, scope, codes, and optional declaration reference. Every match
> produces one suppression decision carrying the issue, rule provenance,
> declaration reference, and decoded rationale. These canonical objects are
> used by matching, audit reporting, obligation inventory, and semantic packet
> construction; no consumer reparses source or configuration.

Add to [EXC-4.4]:

> An inline `meta` or `ignore` may append exactly
> ` because PATH#SUP-ID`, where `PATH` is a repo-relative POSIX spec path and
> `SUP-ID` follows the suppression-declaration grammar in [EXC-6]. The
> delimiter is the lowercase token `because` surrounded by ASCII spaces.
> Codes precede the delimiter. HTML-comment forms use the same token order
> before `-->`; underscore forms have one closing `_` after the declaration
> reference:
> `_Traceability: ignore CODE because PATH#SUP-ID_`. When
> `lint.require_suppression_declarations = true`, omission of this clause
> emits `SUPPRESSION_REASON_MISSING` and the directive does not suppress.
> Under the packaged `false` default, the existing clause-free forms retain
> their behavior.

Add to [EXC-5.1]:

> Python `noqa` and `ignore` directives accept the same terminal
> ` because PATH#SUP-ID` clause. It does not change docstring-module or
> next-statement scope. Under required-declaration mode a clause-free
> directive emits `SUPPRESSION_REASON_MISSING` and does not suppress.

Add a subsection under [EXC-6], “Documented suppression rules,” with this
exact configuration:

```toml
[tool.backstitch.lint]
warn_unused_ignores = true
require_suppression_declarations = false

[[tool.backstitch.lint.suppressions]]
mechanism = "ignore"
path = "tests/*"
sections = []
codes = ["CODE_REF_UNMAPPED_FROM_SPEC"]
declaration = "docs/specs/04-backstitch-traceability-exclusions.md#SUP-TEST-CITATIONS"

[[tool.backstitch.lint.suppressions]]
mechanism = "meta"
path = "docs/specs/01-development-documentation-operating-model.md"
sections = []
codes = []
declaration = "docs/specs/04-backstitch-traceability-exclusions.md#SUP-DOM-META"
```

Add this exact contract below the example:

> `lint.require_suppression_declarations` is boolean and defaults to `false`.
> It governs legacy meta globs, legacy per-file/per-section ignores, and inline
> meta/ignore directives. When true, a legacy or inline rule without a valid
> declaration reference does not suppress and emits
> `SUPPRESSION_REASON_MISSING`. It does not govern scan exclusion, adoption
> rungs, obligation skips, or diagnostic `off` policy.
>
> `lint.suppressions` is an ordered array of closed tables. Each table contains
> exactly `mechanism`, `path`, `sections`, `codes`, and `declaration`.
> `mechanism` is `ignore` or `meta`. `path` is one nonblank repo-relative glob
> with the existing [EXC-6] anchoring and match semantics. `sections` is an
> array of unique valid section IDs; an empty array means file scope. `ignore`
> requires one or more unique ordinary diagnostic codes. Canonical long and
> short-code aliases follow the existing [EXC-2] rules. Input order is not
> significant; Backstitch canonicalizes section IDs lexically and codes by
> registry identity before matching, display, or hashing. `meta` requires
> `codes = []`, applies the exact [EXC-3] policy, and requires
> `sections = []`, preserving config-meta's existing file scope. Section-level
> meta remains an [EXC-4] inline capability. Every structured rule requires one
> declaration
> regardless of the global bool. Unknown fields, invalid combinations,
> duplicates, and malformed references follow [CFG-8].
> Structured `ignore` rules occupy the existing configured-ignore precedence
> tier. Structured `meta` rules occupy the existing meta-classification tier
> and feed the same effective meta set used by deterministic checks and
> obligation-rung projection.
>
> `lint.suppressions` follows ordinary array replacement across `extend`
> layers; it does not gain the special append behavior of
> `diagnostics.levels`. A child that replaces the array restates every
> structured rule it intends to retain. Rule origin records the exact
> contributing config layer and zero-based array position.
>
> A suppression declaration is a CommonMark paragraph token in a scanned spec:
>
> `_Traceability: suppression-declaration [SUP-ID] "strict JSON string"_`
>
> `SUP-ID` is `SUP-` followed by one or more uppercase ASCII letters, digits,
> dots, or hyphens, with an uppercase letter or digit at each end. It is unique
> across the accepted spec corpus. The marker must be ordinary paragraph
> content under an owning ID-bearing section, not a fence, code block, HTML
> comment, heading suffix, preamble, or Python source. The final value uses the
> exact [EVC-8.3.2] JSON-string decoding, nonblank, line-safety, and 4096-byte
> limits. A reference is exactly `repo/relative/spec.md#SUP-ID`; bare IDs,
> absolute paths, backslashes, globs, fragments naming ordinary section IDs,
> and paths outside effective `spec_roots` are invalid.
>
> Declaration parsing produces source artifacts but does not itself suppress
> any finding. One declaration may authorize more than one operational rule
> only when each rule references it explicitly. Under
> `warn_unused_ignores = true`, an unreferenced declaration or a referenced
> rule that matches no issue emits `SUPPRESSION_UNUSED`.

Add to [EXC-7]:

> Each governed suppressed issue retains the existing `reason` provenance
> field and adds `declaration` and `rationale`. These fields are always present
> in JSON; each is `null` only for a legacy suppression accepted while
> required-declaration mode is false. Text output shows provenance,
> declaration, and rationale, rendering rationale with canonical JSON-string
> escaping rather than writing source bytes as terminal control text. The
> source rationale is data, not trusted terminal markup. Diagnostic `off`
> audit records retain
> `reason = "diagnostic level off"` and null declaration/rationale.
> Structured meta rules reuse `reason = "meta"`. Structured ignore rules reuse
> `reason = "config_file"` when `sections = []` and
> `reason = "config_section"` otherwise. Inline forms retain
> `inline_spec`/`inline_code`; the additive fields do not mint a second
> provenance vocabulary.

Add to [EXC-8]:

> `SUPPRESSION_REASON_MISSING` also fires when required-declaration mode sees
> no reference, an unresolved declaration, or a declaration with no valid
> decoded rationale. `SUPPRESSION_INVALID_SYNTAX` fires for malformed source
> declaration syntax, placement, reference syntax, duplicate markers in one
> owning section, or a duplicate `SUP-*` identity anywhere in the accepted
> corpus. Every duplicate declaration is invalid and no affected rule
> suppresses. Existing duplicate-section diagnostics remain authoritative for
> ordinary spec sections. In every case the affected rule
> is ineligible to suppress. `allow_unknown_keys` does not downgrade these
> source-integrity findings when required-declaration mode is enabled.
> Structured rules and inline directives that voluntarily include a `because`
> clause always use this strict declaration-integrity path regardless of the
> global bool: the named hygiene code fires, the rule does not suppress, and
> `allow_unknown_keys` does not downgrade it. The bool governs only whether a
> clause-free legacy rule remains eligible.

Add to [EXC-9]:

> Verification covers both strictness modes; every Markdown, HTML, docstring,
> comment, legacy-config, structured-ignore, and structured-meta form; missing,
> blank, malformed, duplicate, misplaced, unresolved, outside-root, unused,
> valid declarations; exact section containment; precedence;
> canonical ordering; additive audit fields; and the invariant that an invalid
> required declaration leaves the original finding active. A firing
> configuration test proves the new bool changes behavior and a no-op test
> fails if its runtime consultation is removed.

Add under [EXC-10] for Backstitch's own repository:

> Backstitch enables required-declaration mode. Its suppression declarations
> live in this spec. The dogfood migration must audit each existing policy
> family, remove stale rules, narrow the EVC file-wide rule to exact current
> sections or split it by rationale, and add no new suppressed scope. Every
> retained rule appears in `--show-suppressions` with its declaration and
> decoded rationale.

The implementation slice inserts the final reviewed `SUP-*` markers under
[EXC-10]. The marker text is operational repository data and must describe the
post-audit rules, so the plan does not preregister a rationale for a rule that
may be removed. The required minimum decisions are:

- DOM meta classification: retain with a process-document rationale;
- COV: retain only while the whole file remains on the planned rung, with a
  removal condition tied to activation and reciprocal mappings;
- tests: retain for non-owner test citations, limited to the two current
  codes;
- EVC: do not retain file-wide. First test whether direct mappings and
  reciprocal backlinks are now the correct answer. Suppress only the exact
  residual sections that have a defensible shared rationale, and split
  declarations when one reason does not truthfully cover all of them.

### `docs/specs/03-backstitch-configuration.md`

Add to [CFG-6.11]:

> [EXC-6] also defines `lint.require_suppression_declarations` and the closed
> `[[lint.suppressions]]` array. Both standalone and `pyproject.toml` spellings
> use the normal table prefix. They are parsed only by the canonical [CFG-5.1]
> resolver and are present in the immutable settings snapshot.

Add to [CFG-8]:

> A malformed structured suppression table or declaration-reference value is
> a config error and exits `2` before snapshot capture or provider work.
> Config-time reference validation is syntax-only: nonblank repo-relative
> POSIX path, one valid `#SUP-ID`, no absolute path, backslash, glob, control
> character, or extra fragment. Whether that path is inside an effective
> `spec_root`, exists in the accepted snapshot, and owns a valid declaration is
> snapshot-derived target truth governed by [EXC-8], not a second config read.

Add to [CFG-9]:

> `lint.require_suppression_declarations` and every field of
> `lint.suppressions` have firing, wrong-type, closed-shape, precedence,
> `extend`, `config show`, and generic `--option` coverage where the value is a
> scalar option leaf. `lint.suppressions` itself is not settable through
> `--option`; [CFG-5.1]'s existing unknown/non-leaf rejection applies.

### `docs/specs/06-semantic-gates.md`

Add to [SEM-2]:

> A valid governed suppression may create a `suppression` obligation and
> packet. The declaration rationale, normalized operational rules, complete
> matched suppression decisions, and bounded issue-source excerpts are
> model-visible evidence and therefore affect that suppression packet's hash.
> Adding the suppression packet kind or replaying an unchanged deterministic
> decision does not by itself alter a section or invariant packet. A rule,
> scope, code, source, mapping, matched-finding, or meta-classification change
> that changes an existing packet's model-visible issues or evidence honestly
> changes that packet's identity. A meta/rung change may add or remove an
> eligible packet without changing an otherwise identical projection. Policy,
> dispositions, rendering,
> and audit display remain outside every raw-verdict cache key.

In [SEM-3], revise “Current packet rows carry `schema_version = 3`” to:

> Current section and invariant packet rows retain schema 3 exactly.
> Opted-in suppression packet rows use schema 4. A current packet artifact may
> contain both versions; version is determined per row, never inferred from
> position or kind.

Add this exact suppression schema and projection to [SEM-3]:

```text
{
  schema_version: 4,
  packet_id, packet_hash,
  kind: "suppression",
  obligation_id,
  source_snapshot: {
    snapshot_hash, obligation_state_hash, derivation_config_hash
  },
  readiness: {
    intent_state, alignment_state, disposition, obligation_rung, gate_state,
    required_roles
  },
  requirement,
  suppression_rules,
  counterevidence,
  evidence_regions,
  issues,
  packet_warnings
}
```

> One executable schema-4 packet is emitted per referenced declaration,
> grouping every matched decision that names it in canonical rule/issue order.
> `packet_id` and `obligation_id` are both
> `suppression::PATH#SUP-ID`. Readiness is exactly `identified`, `complete`,
> `evaluate`, `active`, `executable`, with `required_roles = []`.
> `requirement` uses the schema-3 requirement shape: role `requirement`, the
> declaration's spec path, identity `SUP-ID`, owning section title, exact
> marker start/end coordinates, and decoded rationale as text.
>
> `suppression_rules` is a nonempty canonical array with exactly:

```text
{
  mechanism: "ignore" | "meta",
  provenance:
    "meta" | "config_file" | "config_section" |
    "inline_spec" | "inline_code",
  path,
  sections,
  codes,
  declaration,
  origin: {
    source, position, line
  }
}
```

> `sections` and `codes` are the normalized arrays from [EXC-6].
> `declaration` equals the packet declaration reference. `origin.source` is
> the exact config-layer or repository-relative source path;
> `origin.position` is the zero-based structured-config array position or null;
> `origin.line` is the positive inline source line or null. Exactly one of
> position/line is non-null. Legacy rules cannot produce suppression packets
> because they have no declaration.
>
> `issues` is the complete nonempty canonical [SC-6] projection of matched
> suppressed issues. For each issue with a source path and positive line,
> `counterevidence` contains the exact single LF-delimited logical source line
> from the accepted snapshot in this closed shape:

```text
{
  role: "counterevidence",
  path, start_line, end_line, snippet,
  issue_indexes
}
```

> `issue_indexes` is the sorted, unique, nonempty array of zero-based indexes
> into `issues` whose locators share that exact path and line. Equal source
> lines merge; disjoint lines remain separate.
> Issues without such a locator remain in `issues` and produce no invented
> region. `evidence_regions` contains the requirement and those
> counterevidence regions in [SEM-5] order. `packet_warnings` is exactly `[]`.
> Empty, sampled, or truncated rule/issue populations are invalid and overflow
> is fatal under existing packet byte ceilings.
>
> The schema-4 model-visible projection is exactly:

```text
{
  packet_contract_version: 4,
  packet_id, kind, obligation_id,
  requirement,
  suppression_rules,
  counterevidence,
  evidence_regions,
  issues,
  packet_warnings
}
```

> `packet_hash` is SHA-256 of canonical JSON for that projection. Source
> snapshot, readiness, policy, audit rendering, and provenance outside
> `suppression_rules.origin` are excluded.
>
> Suppression packets use packet schema 4 and a code-owned suppression prompt.
> Section and invariant schema, projection, prompt descriptor, packet hash,
> result schema, and analysis-key construction remain byte-for-byte unchanged.
> New readers accept the exact mixed population and the prior
> section/invariant-only population.
>
> Standalone `packets --kind` accepts `suppression`; `all` includes it.
> `check`, `packets`, and obligation commands remain deterministic and do not
> import `llm`.

In [SEM-4], replace the packet-object and canonical-result paragraphs with:

> A packet object contains exactly `schema_version = 1`,
> `object_type = "semantic-packet"`, one current [EVC-9.1] model projection,
> and `packet_hash`. The nested projection is contract 3 for section/invariant
> or contract 4 for suppression. It never contains instructions. A prompt-only
> change therefore reuses the packet object and creates a different result key
> without colliding at the packet path.
>
> A result object contains exactly `schema_version = 1`,
> `object_type = "semantic-result"`, `inference_contract`, `analysis_key`,
> `result`, `provenance`, and `raw_response_sha256`. Its nested canonical
> analyzer row is result schema 2 for section and invariant and result schema 3
> for suppression. The kind, packet
> projection contract, prompt response contract, and nested result schema must
> agree exactly; mismatch is corruption, not a cache miss.
>
> A canonical result row contains exactly `schema_version`, `packet_id`,
> `kind`, `packet_hash`, `analysis_key`, `classification`, `confidence`,
> `rationale`, `summary`, `evidence`, and `verification_state`. Schema 2
> retains the exact section/invariant kinds and classifications. Schema 3
> requires `kind = "suppression"` and the [SEM-6] suppression classification
> vocabulary. Confidence is always present and may be null. Every inference
> row remains `evidence_bound`; trusted verification and dispositions project
> separately. Evidence uses the exact [SEM-5] packet-local contract for its
> kind.

Revise [SEM-4]'s cache-mode miss statement to:

> An inference-relevant change creates a miss for every work identity whose
> model-visible packet, prompt, provider, request, contract, or epoch changed.
> Adding support for a new packet kind does not alter old-kind identities.
> Changes to suppression scope, mappings, or matched issues may legitimately
> alter existing packet projections and therefore their keys. Meta/rung changes
> may alter packet eligibility. A policy-only change remains a zero-call
> replay.

Add to [SEM-5]:

> Suppression result rows use result schema 3 and the same closed packet-local
> evidence representation. Section and invariant result rows remain schema 2.
> Suppression `ok` and `rationale_insufficient` require `requirement`;
> `scope_overbroad` and `risk_unaddressed` require `requirement` and
> `counterevidence`; `ambiguous` requires `requirement`. Missing or
> out-of-range evidence is malformed. Model normalization produces only
> `evidence_bound`; the existing verification and human-disposition authority
> rules do not change.

Add to [SEM-6]'s classification table:

| Suppression classification | Canonical code | Short code |
|---|---|---|
| `rationale_insufficient` | `SEMANTIC_SUPPRESSION_RATIONALE_INSUFFICIENT` | `BSA006` |
| `scope_overbroad` | `SEMANTIC_SUPPRESSION_SCOPE_OVERBROAD` | `BSA007` |
| `risk_unaddressed` | `SEMANTIC_SUPPRESSION_RISK_UNADDRESSED` | `BSA008` |

Add below the table:

> Suppression classifications are `ok`, `rationale_insufficient`,
> `scope_overbroad`, `risk_unaddressed`, and `ambiguous`; `ambiguous` retains
> `SEMANTIC_AMBIGUOUS`/`BSA005`. The three new codes use the existing
> `confirmed_mismatch` packaged level row across verification states. Their
> finding hashes use `packet_kind = "suppression"` and otherwise retain the
> exact finding contract. Evidence-bound findings never decide whether the
> deterministic suppression applies. Ordinary `finding_handling` and exact
> dispositions govern their debt and human disposition.

In [SEM-7], replace “Current generation emits the closed packet-report schema
2 in [EVC-9.1]” and add:

> Current packet and analysis reports include closed suppression eligible,
> emitted, result, cache-hit, provider-call, classification, diagnostic, and
> debt counts. `require_complete` covers every emitted suppression packet. A
> required `suppression` kind is satisfied when all eligible suppression
> packets were emitted; zero eligible suppressions is vacuously complete so
> deleting the last suppression does not break CI. Missing one of a nonzero
> eligible population is incomplete and exits `2`.
>
> Packet-report schema 3 and analysis-report schema 4 are the current producer
> contracts when suppression packets are supported. Readers retain exact
> packet-report schema 2 and analysis-report schema 3 support for the
> immediately prior section/invariant-only historical contract. Compatibility
> readers never reinterpret an old row as a suppression row.
> Analysis-report schema 4 adds `packet_schema_versions` from packet-report
> schema 3 and `kind_counts`. `kind_counts` contains exactly `eligible`,
> `emitted`, `results`, `cache_hits`, `cache_misses`, and `provider_calls`;
> each contains exactly nonnegative `section`, `invariant`, and `suppression`
> integers. Eligible/emitted copy the packet report. Results and work counts
> recompute from canonical rows and operational events; each nested total
> equals the corresponding existing aggregate count. Every other
> analysis-report schema-3 field and semantic rule is unchanged.

Revise [SEM-9]'s `required_kinds` contract to admit `suppression` in canonical
order after `invariant`, with the zero-eligible rule above. Add:

> Backstitch sets
> `lint.require_suppression_declarations = true` and includes `suppression` in
> `analyze.required_kinds`. Trusted refresh builds missing suppression cache
> objects in `read-write` mode. The committed `require` mode then proves
> zero-call replay. A rationale or suppression-only projection change misses
> its suppression object. A rule, matched-finding, meta, mapping, or source
> change also misses any section/invariant object whose visible issue or
> evidence changed and may add/remove packets whose eligibility changed. A
> non-`ok`
> evidence-bound review creates ordinary finding debt; Backstitch's existing
> `finding_handling = "require_disposition"` requires a current human
> disposition without granting the model deterministic suppression authority.

Add to [SEM-10]:

> Tests prove prior section/invariant packet, prompt, result, report-reader, and
> cache fixtures remain valid; each suppression classification and evidence
> role fires; rationale/rule-projection-only changes miss the suppression
> packet; changes to deterministic issues or evidence re-key every truthfully
> affected packet; meta/rung changes alter eligibility without being treated
> as a hidden hash input; policy/disposition/rendering changes make zero calls;
> empty,
> incomplete, oversized, malformed, stale-snapshot, cache-corrupt, and
> undisposed paths fail at their existing owners; and live local analysis
> exercises at least one real suppression packet.

### `docs/specs/07-verification-and-evidence-cases.md`

In [EVC-1], replace “compilation of aligned source into evidence packet schema
version 3” with:

> compilation of aligned source into section/invariant packet schema 3 and
> suppression packet schema 4, with exact mixed-artifact rules in [EVC-9.1]

Revise [EVC-2]'s obligation glossary row to:

| Noun | Meaning | Authority |
|---|---|---|
| **obligation** | One addressable spec section, first-class invariant, or valid used suppression declaration | Its repository source declaration |

Add to [EVC-2.1]:

> A valid suppression declaration referenced by at least one matched governed
> rule enters the inventory as one active suppression obligation. Its identity
> is `suppression::PATH#SUP-ID`; intent is identified, alignment is complete,
> disposition is evaluate, gate state is executable, and required source roles
> are empty. Invalid, unreferenced, or unmatched declarations do not become
> executable semantic obligations; their deterministic hygiene remains
> [EXC-8]. Suppression obligations cannot carry an [EVC-8.3.2] skip because
> their declaration already exists to explain a suppression. Section and
> invariant readiness rules do not change.

Add to [EVC-3.1]:

> Verifier claim/result contracts admit `kind = "suppression"`, result schema
> 3, and the [SEM-6] suppression classifications/codes. The reason-free claim
> still excludes analyzer rationale, confidence, policy, dispositions, and
> source skip reasons. A suppression declaration's rationale is the packet's
> source-authored requirement and remains visible; it is not analyzer
> rationale. The verifier may challenge a suppression finding through the
> same support/refute/indeterminate result and evidence binding, but BSA006
> through BSA008 have no independent failure authority without a future exact
> [EVC-10.1] qualification. This revision does not add them to the measured
> promotion corpus.

Add to [EVC-8]:

> `obligation list` includes executable suppression obligations in canonical
> identity order. `obligation get` returns their declaration, normalized rules,
> matched issue count, and current readiness. Existing evidence discovery and
> mutation guidance do not run for this kind: suppression packet evidence is
> deterministically derived from the declaration, normalized rules, matched
> issues, and accepted snapshot. Unsupported summarize/find/get-candidate
> selectors return the existing closed invalid-operation envelope; no parallel
> suppression API is added.

In [EVC-8.7], replace “`required_kinds` requires each named packet kind among
selected rows” with:

> `required_kinds` requires `section` and `invariant` among selected rows
> exactly as before. For `suppression`, a nonzero eligible population requires
> every eligible suppression packet among selected rows; zero eligible
> suppressions is vacuously complete. [EVC-12] fires both the zero-eligible and
> nonzero-incomplete cases. This asymmetry lets removal of the last exception
> remain a passing end state without weakening ordinary intent completeness.

Rename [EVC-9.1] to “Source-Aligned Evidence Packets [EVC-9.1]”. Replace “One
executable obligation produces one packet artifact row” and the following kind
sentence with:

> One executable section or invariant obligation produces the exact schema-3
> row defined below. One executable suppression obligation produces the exact
> schema-4 row and projection in [SEM-3]. A current JSONL artifact may contain
> both versions. `kind` is `section`, `invariant`, or `suppression` and must
> agree with row schema and canonical identity. Schema-3 semantics and bytes
> do not change.

Add after [EVC-9.1]'s schema-3 model-visible projection:

> Schema-4 suppression rows use [SEM-3]'s exact closed top-level, nested-rule,
> requirement, counterevidence, evidence-region, issue, readiness, and
> model-visible projection contracts. Their packet hash uses contract version
> 4. Schema-3 and schema-4 rows share source-snapshot currentness, complete
> population, byte-ceiling, canonical JSONL ordering, publication, and
> self-validation rules. There is no compatibility normalization from one row
> version or kind into another.

Replace [EVC-9.1]'s packet-report opening with:

> Current generation emits packet-report schema 3. It is packet-report schema
> 2 with exactly these closed changes:
>
> - `schema_version` is `3`;
> - scalar `packet_schema_version` becomes
>   `packet_schema_versions`, an ascending duplicate-free array containing
>   exactly the row versions present: `[3]` or `[3, 4]`;
> - `derivation_contract.packet_contract_version` becomes
>   `packet_contract_versions` with the same exact array;
> - `alignment_audit.kind` admits `suppression`;
> - `kind_counts` is added with exactly `eligible` and `emitted`; each contains
>   exactly nonnegative `section`, `invariant`, and `suppression` counts that
>   recompute from the inventory/audit and emitted JSONL rows;
> - `readiness_counts` uses the same disjoint buckets across all three kinds;
> - `packet_count` and `readiness_counts.selected` equal section + invariant +
>   suppression emitted rows.
>
> Every other field and semantic rule is unchanged. The
> `packet_report_content_sha256` preimage contains exactly every packet-report
> schema-3 field except itself, `tool_version`, and `created_at`, including
> both plural version fields and `kind_counts`. Canonical JSON owns key order.
> The hash therefore continues to cover every non-provenance report field.
> Readers retain exact packet-report schema 2 support for historical
> section/invariant-only replay and never reinterpret a schema-2 artifact as
> containing suppression.

Add to [EVC-12]:

> Acceptance probes cover mixed schema-3/schema-4 packet JSONL,
> packet-report schema 2 compatibility and schema 3 production,
> suppression obligation/API behavior, analyzer and optional verifier
> evidence binding, empty and nonempty required-kind completeness, and the
> invariant that schema-3 section/invariant bytes and identities do not change
> merely because suppression support is installed.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [SEM-7], [EVC-8.7], [EVC-12] | Analyze separately rejects a nonzero eligible suppression population with fewer emitted packets. | Current packet-report schema 3 rejects that artifact first: eligible and emitted both recompute from the selected executable/evaluate audit rows and selected rows must exactly match packets. Analyze treats a validated report as complete; zero eligible remains vacuously complete. | The planned post-validation state is unrepresentable without weakening the closed report contract or adding another population field. The existing validator is the correct failure owner and exits `2` before adapter construction. | Revise [SEM-7], [EVC-8.7], and [EVC-12] to name intrinsic schema-3 completeness and require an invalid-artifact boundary probe instead of a dead analyzer branch. |

## Dependency-Ordered Implementation Slices

### Spec-promotion slice: promote the reviewed contract

- Files:
  `docs/specs/03-backstitch-configuration.md`,
  `docs/specs/04-backstitch-traceability-exclusions.md`,
  `docs/specs/06-semantic-gates.md`,
  `docs/specs/07-verification-and-evidence-cases.md`, and this plan.
- Apply the exact delta above to existing mapped sections without adding new
  ID-bearing headings or mapping blocks.
- Add this plan to each touched spec's `## Related Plans`.
- Record the promotion baseline identifier and rerun `git diff --check`.
- Do not add code backlinks yet.
- Done signal: promoted spec diff matches the reviewed proposal, and a
  fresh-eyes comparison finds no plan/spec divergence.

### Slice 1: canonical deterministic declaration and rule model

- Files:
  `backstitch/settings.py`, `backstitch/config.py`,
  `backstitch/markdown_specs.py`, `backstitch/python_refs.py`,
  `backstitch/exclusions.py`, `backstitch/resolver.py`,
  `backstitch/check_pipeline.py`, `backstitch/reporting.py`,
  `backstitch/defaults.toml`, and focused tests.
- Start with failing tests for the bool, structured table, declaration parser,
  every strict failure, legacy compatibility, invalid-rule fail-closed
  behavior, and additive audit fields.
- Generalize the existing strict JSON reason helper. Add immutable declaration,
  rule, decision, and audit record types. Preserve source/config provenance.
- Make effective profile construction consume canonical structured-meta rules
  so checks and obligations share one meta set.
- Replace tuple suppressed records. Do not add a second reporting filter or
  settings loader.
- Add reciprocal backlinks and any mapping additions for the revised [CFG-*]
  and [EXC-*] sections in the same slice.
- Stop if the implementation needs to reread config/source, weakens
  `allow_unknown_keys`, changes legacy behavior with strictness false, or
  gives check and obligation code separate meta-rule evaluators.
- Done signal: targeted settings, exclusions, parser, pipeline, reporting, and
  dogfood fixture tests pass; prior compatibility fixtures are unchanged.

Independent review after Slice 1 must inspect the real source/config parsers,
fail-closed behavior, precedence, provenance, and audit JSON before Slice 2.

### Slice 2: suppression obligation and packet kind

- Files:
  `backstitch/obligations.py`, `backstitch/obligation_runtime.py`,
  `backstitch/obligation_api.py`, `backstitch/analysis_packets.py`,
  `backstitch/semantic_packets.py`, `backstitch/artifact_contracts.py`,
  `backstitch/semantic_reports.py`, packaged prompt resources, and focused
  tests/acceptance probes.
- Add `suppression` to the canonical obligation inventory. Construct it from
  `CheckPipelineResult` decisions and parsed declarations from the same
  runtime; do not create a parallel repository capture or packet command.
- Emit one complete, bounded schema-4 packet per used declaration. Preserve
  schema-3 section/invariant rows byte for byte.
- Add exact mixed-population and immediately-prior report readers. Update
  `--kind`, obligation API vocabulary, counts, ordering, and byte budgets.
- Add a prompt whose sole question is whether the stated rationale is
  specific, the scope is no broader than the matched findings support, and
  material masking/removal risk is addressed. It must not ask the model to
  activate or revoke the suppression.
- Stop if an existing section/invariant fixture hash changes, if source is
  reopened, if issue sets are sampled, or if a separate artifact/cache path
  appears.
- Done signal: exact golden packet/report tests and acceptance probes prove
  mixed-kind compatibility, completeness, bounded failure, and no-LLM
  deterministic operation.

Independent review after Slice 2 must compare old fixture bytes/hashes and
inspect the full model-visible suppression projection.

### Slice 3: semantic result, policy, cache, and disposition lifecycle

- Files:
  `backstitch/analysis_results.py`, `backstitch/semantic_evidence.py`,
  `backstitch/semantic_identity.py`, `backstitch/analysis_llm.py`,
  `backstitch/semantic_policy.py`, `backstitch/semantic_analysis.py`,
  `backstitch/semantic_verification.py`, `backstitch/semantic_reports.py`,
  `backstitch/settings.py`, `backstitch/defaults.toml`, and focused tests.
- Add the exact suppression result schema, classifications, BSA006-BSA008
  registry/policy cells, evidence-role rules, counts, and required-kind
  behavior.
- Reuse immutable cache lookup, single-flight, provider budgets, normalization,
  finding identity, policy projection, dispositions, blinded optional
  verification, verification-state authority, publication, and exit truth.
  The verifier accepts the new kind and classifications but gains no
  independent failure authority without the existing exact qualification
  contract.
- Keep the measured semantic-eval corpus and qualification schemas scoped to
  section/invariant and BSA001-BSA005. BSA006-BSA008 remain explicitly
  unqualified until a separate measured-promotion plan.
- Add metamorphic tests that distinguish:
  rationale/normalized-projection-only changes re-key the suppression packet;
  effective issue/evidence changes re-key every truthfully affected packet;
  meta/rung changes alter eligibility; policy, disposition, concurrency,
  output, and audit-only changes preserve keys and make zero calls.
- Add reciprocal backlinks and mapping additions for revised [SEM-*] sections
  in this slice.
- Stop if a model result can suppress/unsuppress deterministic output, if a
  new cache or report store appears, or if section/invariant cache keys move.
- Done signal: semantic unit and acceptance tests cover every new enumerable
  element and both live-miss and zero-call replay paths.

Independent review after Slice 3 must inspect authority, cache identity,
closed schemas, and compatibility before dogfood activation.

### Slice 4: dogfood migration and opt-in activation

- Files:
  `pyproject.toml`,
  `docs/specs/04-backstitch-traceability-exclusions.md`,
  `tests/test_backstitch_corpus_traceability.py`, relevant workflow tests, and
  no unrelated source.
- Inventory the four current rule families from a fresh
  `--show-suppressions --format json` result.
- Remove stale suppressions. Prefer adding truthful direct mappings and
  reciprocal backlinks over preserving EVC exceptions. Convert only retained
  rules to structured form and add
  final `SUP-*` declarations under [EXC-10].
- Remove `profile.meta_spec_globs` after its DOM behavior is represented by the
  structured meta rule.
- Narrow EVC from a file glob to exact justified sections. If one rationale
  cannot truthfully cover every section, split it. Do not add scope.
- Set `lint.require_suppression_declarations = true` and append
  `suppression` to `analyze.required_kinds`.
- Extend self-corpus tests to compare every audit decision to its declaration,
  require nonblank rationales, reject legacy null fields, and prove the
  deterministic opt-in key fires.
- Remove a declaration in the same change that removes its last rule.
  Backstitch's all-error dogfood policy intentionally makes an unreferenced
  `SUP-*` marker's `SUPPRESSION_UNUSED` finding fail the gate.
- Update trusted workflow contract tests only as needed to preserve config
  ownership and normal read-write/require lifecycle. Do not add another
  config file.
- Stop for owner review if any retained suppression has no defensible bounded
  rationale or if strict activation requires suppressing a new diagnostic.
- Done signal: default check exits 0 with zero issues; audit scope is no broader
  than the pre-migration inventory; every retained record has a valid
  declaration/rationale.

### Slice 5: semantic refresh, documentation, and traceability reconciliation

- Run the trusted local live `read-write` invocation with ordinary static
  `--option` overlays to create missing suppression cache objects. Then restore
  committed `require` posture and prove zero provider calls.
- Disposition any non-`ok` suppression finding only through the existing
  reviewed `[[analyze.dispositions]]` contract. Do not weaken
  `finding_handling` or BSA policy to make the run pass. A finding that exposes
  an unjustified rule is resolved by narrowing/removing the rule first.
- Update:
  `docs/implementation/02-repository-map.md`,
  `docs/implementation/04-backstitch-style-traceability.md`,
  `docs/implementation/07-deterministic-semantic-gate.md`, `README.md`,
  `CHANGELOG.md`, `AGENTS.md`, and `docs/plans/README.md`.
- In `AGENTS.md`'s Backstitch implementation definition of done, replace
  “suppressions auditable via `--show-suppressions`” with:
  “every governed suppression has a valid spec declaration and nonblank
  rationale in `--show-suppressions`, and every eligible suppression packet
  has a current semantic result or reviewed disposition under the applied
  configuration.” This is repository guidance, not a packaged default imposed
  on downstream repositories.
- Reconcile mappings and reciprocal backlinks, update the deviation log and
  promotion baseline, and run the full gates.
- Done signal: final different-family review PASS, all evidence recorded, and
  the completed slice is committed per repository guidance.

## Testing Plan

Use failing-test-first for each observable contract. The named exit from red to
green is the smallest applicable focused test file.

Required deterministic coverage:

- config type/shape/default/extend/CLI precedence and `config show`;
- every declaration and reference grammar form at real CommonMark and
  tree-sitter boundaries;
- strict false compatibility and strict true fail-closed behavior;
- structured ignore/meta matching, section containment, ordering, precedence,
  unknown/unused/invalid/unsuppressible behavior;
- canonical decisions and additive text/JSON audit;
- dogfood delta and exact no-broadening inventory.

Required semantic coverage:

- suppression obligation identity and grouping;
- schema-4 packet projection and mixed schema-3/schema-4 artifact;
- immediately prior packet/report/result reader compatibility;
- all result classifications, evidence roles, BSA codes, policy cells, finding
  hashes, dispositions, optional verifier composition, counts, and
  required-kind zero/nonzero behavior;
- cache hit/miss metamorphic matrix;
- current snapshot recapture, budgets, malformed provider rows, publication
  atomicity, and zero-call require mode;
- a live local provider call for a suppression packet, followed by a require
  replay with zero calls.

Do not mock:

- config discovery/merge/parsing for public resolver tests;
- CommonMark or tree-sitter source structure;
- repository snapshot capture and recapture;
- packet/result/report validators;
- immutable cache read/write/lock behavior;
- self-corpus subprocesses;
- the final live LLM test.

Pure unit tests may use literal settings, issues, normalized rules/decisions,
packet rows, a counting provider adapter, temporary cache roots, and the
existing deterministic fake provider. Do not mock away the owner being tested.

## Verification And Gates

Per-slice commands are the smallest focused tests named by the changed owner.
Final gates:

```bash
uv run pytest -q tests/test_settings.py tests/test_cli_config.py
uv run pytest -q tests/test_exclusions.py tests/test_python_noqa.py \
  tests/test_markdown_specs.py tests/test_check_pipeline.py tests/test_reporting.py
uv run pytest -q tests/test_obligations.py tests/test_obligation_runtime.py \
  tests/test_obligation_api.py tests/test_analysis_packets.py \
  tests/test_artifact_contracts.py tests/test_semantic_reports.py
uv run pytest -q tests/test_analysis_results.py tests/test_semantic_evidence.py \
  tests/test_analysis_llm.py tests/test_semantic_policy.py \
  tests/test_semantic_analysis.py tests/test_semantic_settings.py
uv run pytest -q tests/acceptance
uv run pytest -q -m "not live_llm and not benchmark"
uv run pytest -q -m live_llm
uv run pytest tests -q -n 0 -m benchmark
uv run ruff check .
uv run ruff format --check .
uv run mypy backstitch bin/release.py tests --config-file pyproject.toml
uv run backstitch check --repo-root .
uv run backstitch check --repo-root . --show-suppressions --format json
git diff --check
```

The default self-corpus result must be exit 0 with zero errors, warnings, and
infos. The audit result must contain no null declaration/rationale for governed
suppressions, no broader path/code/section scope than the recorded pre-migration
inventory, and no undocumented suppression. Acceptance probes must prove
declaration failure leaves the original finding active.

Operational success after landing:

- the first trusted refresh reports new suppression objects plus only those
  old-kind misses explained by changed visible issues/evidence, plus any
  packet-population change explained by eligibility;
- after that migration state is fixed, the following require-mode run reports
  zero provider calls;
- a rationale-only declaration edit invalidates its suppression packet; a
  rule/source edit invalidates every truthfully affected packet;
- removing the final suppression leaves required-kind completeness passing;
- installing suppression support alone leaves section/invariant fixture bytes
  and cache identities unchanged.

## Independent Review Loop

Before any spec promotion:

1. perform two author fresh-eyes passes:
   - architecture/scope: look for a second resolver, rule engine, snapshot,
     parser, LLM command, cache, report, or authority path;
   - contract/implementation: verify exact types, failure owners,
     compatibility, firing tests, rollback, and no-broadening dogfood gate.
2. run `claude -p` directly from the repository root, with up to 15 minutes,
   against this plan, its exact proposed spec delta, the baseline specs,
   relevant implementation docs, and current code. Do not use a Claude skill
   or wrapper.
3. require `PASS` or `BLOCKED` using the repository review prompt. Record every
   finding and its accepted/rejected/out-of-scope disposition in this plan.
4. rerun a focused direct `claude -p` review after corrections if any blocker
   or ambiguity was found.

Run independent completed-work review after each meaningful slice and a final
different-family review before landing. Reviewers must look for unnecessary
machinery as well as missing safeguards. A review suggestion does not expand
scope automatically; scope additions require an explicit plan revision.

## Plan Review Record

### Author fresh-eyes review 1: architecture and scope

PASS after corrections:

- Removed performative canonical-input ordering. Arrays accept ordinary input
  order and normalize internally.
- Made `extend` replacement and per-rule origin explicit so the implementer
  does not invent an append merge or lose provenance.
- Corrected the EVC migration from “replace the file-wide rule” to “prefer
  direct mappings; suppress only defensible residual sections.”
- Added canonical JSON-string escaping for terminal audit output.
- Named result schema 3, packet-report schema 3, and analysis-report schema 4,
  with exact immediately-prior readers.
- Added the existing optional verifier to the reuse path. No separate
  suppression verifier or authority path is authorized.
- Rechecked the excluded boundaries: scan exclusion, adoption rungs, skips,
  and diagnostic `off` remain outside this revision.

### Author fresh-eyes review 2: contracts and execution

PASS after corrections:

- Resolved the failure-owner contradiction: malformed or duplicate source
  declarations are target diagnostics, not config exit `2`; their rules do not
  suppress.
- Prevented a scope expansion by requiring structured config `meta` rules to
  remain file-scoped. Existing inline section meta remains unchanged.
- Defined mixed packet-version reporting exactly:
  `packet_schema_versions = [3] | [3, 4]` in packet-report schema 3 and
  analysis-report schema 4, while prior readers retain their scalar.
- Checked every new enumerable contract: one config bool, five structured-rule
  fields, one source marker and reference grammar, one packet kind, one packet
  schema, one result schema, three classifications/codes, two report schemas,
  and two added audit fields all have named firing coverage.
- Checked rollout against the current lifecycle: repository activation follows
  compatibility readers; live refresh precedes require-mode replay; cache
  rollback needs no mutation.
- Checked the no-broadening gate against the observed four rule families and
  206 audit records. The plan permits removal/mapping and exact narrowing, not
  a new code/path/section suppression.

### Direct Claude review

Round 1: `VERDICT: BLOCKED`.

| ID | Severity | Disposition |
|---|---|---|
| F1 | P1 | Accepted. Added the spec-07 baseline and exact [SEM-4], [EVC-3.1], [EVC-9.1], and related obligation/API/report deltas; changed contradictory “add” instructions to explicit replacements. |
| F2 | P1 | Accepted. Qualified cache isolation everywhere. Effective issue/evidence changes truthfully re-key affected old-kind packets; meta/rung changes alter eligibility; no pre-suppression packet input workaround is allowed. |
| F3 | P2 | Accepted. Clause-bearing inline and structured rules use strict declaration integrity regardless of the global bool; the bool governs clause-free legacy forms. |
| F4 | P3 | Accepted. Structured provenance reuses `meta`, `config_file`, and `config_section`. |
| F5 | P3 | Accepted. Replaced the nonexistent array-of-table restriction citation with [CFG-5.1]'s unknown/non-leaf rule. |
| F6 | P3 | Accepted. Config owns reference syntax; snapshot-derived target truth owns spec-root containment and declaration resolution. |
| F7 | P3 | Accepted. The underscore closes after the declaration reference. |

The author also followed F1's ownership implication through [EVC-1],
[EVC-2.1], [EVC-8], and [EVC-12], because the plan intentionally makes
suppression a real obligation kind. Measured BSA006-BSA008 qualification
remains explicitly out of scope.

Focused Round 2: `VERDICT: FAIL`. F1-F7 were verified fixed. The fixes exposed
five new exactness defects, all accepted:

| ID | Severity | Disposition |
|---|---|---|
| R2-1 | P2 | Added the [EVC-8.7] suppression-specific zero-eligible rule and retained section/invariant semantics. |
| R2-2 | P3 | Added `kind_counts` to the packet-report content-hash preimage; every non-provenance field remains covered. |
| R2-3 | P3 | Moved the obligation glossary delta to [EVC-2] and revised [EVC-1]'s stale schema-3-only scope bullet. |
| R2-4 | P3 | Restated the complete cache result envelope and canonical result-row fields in [SEM-4]. |
| R2-5 | Minor | Distinguished packet eligibility changes from model-projection re-keying throughout. |

Focused Round 3: `VERDICT: PASS`. R2-1 through R2-5 were verified fixed; no
new defect caused by those fixes was confirmed. Claude also verified the four
spec hashes against `225bc53`, every replacement anchor against the baseline
text, and every corrected owner against the promotion edit list.

## Implementation Review Record

- Slice 1 independent review: `PASS`. The review checked source/config
  parsing, strict fail-closed behavior, precedence, provenance, shared meta
  resolution, and additive audit output.
- Slice 2 independent review: `PASS` after one correction. Packet issue order
  now uses one policy-independent canonical key in both producer and validator;
  a severity-swap test proves stable bytes and identity.
- Slice 3 independent review: `PASS` after authority, compatibility,
  completeness, and race-accounting corrections. BSA006-BSA008 have no
  mechanical or human authority under an independently verified policy cell;
  historical schema-less results cannot be suppression results; current
  packet-report validation owns intrinsic suppression completeness; and an
  ownership-loss race may truthfully report a provider call followed by a
  cache hit at aggregate and per-kind levels.
- Slice 4 migration evidence: the fresh pre-migration audit contained 206
  records in the four planned families (DOM 15, EVC 14, COV 9, tests 168).
  Truthful reciprocal mappings removed 11 EVC section exceptions and two
  related test reciprocal findings. The governed post-migration audit contains
  192 records (DOM 15, exact residual EVC 3, COV 9, tests 165), zero active
  errors/warnings/infos, and zero null declarations or rationales. The
  self-corpus test pins each declaration population and the exact allowed
  path/code/section boundaries.
- Slice 4 independent review: `PASS` after removing a test path that was not a
  runtime owner and then removing its overly broad [EVC-8] module citation.
  Re-review confirmed zero added `(path, section_id, code)` suppression
  identities against the 206-record baseline.

## Out Of Scope

- scan-exclude rationale or an ignore-file feature;
- changing planned/exploratory rung semantics;
- changing the existing obligation-skip reason contract;
- requiring reasons for diagnostic `off` policy;
- automatic model-authored reasons, dispositions, config edits, or source
  mutation;
- a new suppression-only CLI, provider, cache, report, workflow, config file,
  or persistence store;
- model failure authority without the existing human/mechanical/qualified
  verification path;
- redesigning semantic evaluation or qualifying BSA006-BSA008 for direct
  failure authority;
- cleaning unrelated traceability debt or refactoring nearby parsers beyond
  the canonicalization required by this plan.

## Fresh-Eyes Completion Checklist

- [ ] A zero-context implementer can identify every owner and reuse path.
- [ ] The opt-in compatibility and strict fail-closed behavior do not conflict.
- [ ] Every suppressed audit record has one provenance and, when governed, one
  declaration/rationale.
- [ ] The LLM reviews evidence but cannot decide deterministic truth.
- [ ] Installing support leaves section/invariant fixture bytes and identities
  unchanged; later source/rule changes re-key only truthfully affected packets.
- [ ] The EVC migration cannot preserve future file-wide suppression.
- [ ] Empty suppression inventory is a valid end state.
- [ ] Rollout and rollback do not depend on committed cache state.
- [ ] Each enumerable contract element has a firing test.
- [ ] No task authorizes adjacent cleanup or a second implementation path.
