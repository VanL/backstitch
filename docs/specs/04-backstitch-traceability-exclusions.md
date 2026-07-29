# Backstitch Traceability Exclusions Specification

Status: Active

This spec defines how `backstitch` suppresses selected deterministic findings
for chosen files, sections, or code locations without removing those files from
`spec_roots` or `code_roots`.

Related specs:

- `docs/specs/02-backstitch-core.md` [SC-4], [SC-9], [SC-11]
- `docs/specs/03-backstitch-configuration.md` [CFG-6]
- `docs/specs/08-intent-coverage.md` [COV-4], [COV-5], [COV-8], [COV-9]

## 1. Purpose And Scope [EXC-1]

Backstitch checks enforce traceability between specs and code. Not every spec
section describes implementable product behavior. Process specs, meta
documentation, transitional plans, and intentional gaps need a controlled way
to say “do not require an implementation mapping here” without faking
mappings or removing files from the corpus.

This spec owns:

- exclusion mechanisms and precedence
- supported inline directives in specs and Python
- configuration tables analogous to `ruff`/`mypy` per-file ignores
- classification globs for meta/process spec files
- validation and observability for unused or invalid suppressions

This spec also owns opt-in, spec-declared rationales for governed
suppressions and the deterministic artifacts supplied to semantic review.
The semantic inference, cache, result, disposition, and authority lifecycle
remains owned by [SEM-*].

This spec does not own:

- scan-path `exclude` / `extend_exclude` ([CFG-6.7]) — those skip discovery
  entirely
- `planned_spec_globs` / `exploratory_spec_globs` ([SC-3]) — those classify
  unshipped product behavior cited from code
- semantic (`llm`) advisory findings
- changing default severities in [SC-11]

_Implementation mapping_:

- `backstitch/diagnostics.py`
- `backstitch/exclusions.py`

## 2. Mental Model [EXC-2]

Think in three layers, mirroring common Python tooling:

| Layer | Ruff/mypy analogue | Backstitch analogue | Effect |
|-------|-------------------|---------------------|--------|
| Scan boundary | exclude paths | `exclude` / `extend_exclude` | File not parsed |
| Classification | rule sets / profiles | `meta_spec_globs`, `process_spec_globs` | Parsed; policy skips mapping requirements |
| Targeted suppression | `# noqa`, `per-file-ignores`, `# type: ignore[code]` | inline directives + `lint` config | Parsed; named issue codes suppressed for a scope |

**Diagnostic code** is the suppression unit. The canonical long code is
preferred. Stable short codes are accepted as aliases and canonicalized.
Examples: `SPEC_SECTION_UNMAPPED`, `BSS007`,
`SPEC_MAPPING_RECIPROCAL_MISSING`, `BSC003`.

Intent-coverage exemptions are a separate accounting mechanism governed by
[COV-4], not ordinary issue suppressions. The exact
`backstitch: no-spec -- <reason>` marker and configured coverage exemption
tables classify a definition as deliberately outside intent coverage. They do
not hide a resolver issue, do not use diagnostic-code scope, and never enter
the ordinary suppression stack.

**Scope** is where a suppression applies:

- repository path glob
- spec file
- spec section ID
- Python module path
- Python line (future v2; not required in first implementation)

A valid suppression names at least one diagnostic code, except for the closed
`meta` mechanism whose code set is [EXC-3]. Blanket ordinary ignores are not
allowed. Every suppression normalizes to one rule with mechanism, origin,
scope, codes, and optional declaration reference. Every match produces one
suppression decision carrying the issue, rule provenance, declaration
reference, and decoded rationale. These canonical objects are used by
matching, audit reporting, obligation inventory, and semantic packet
construction; no consumer reparses source or configuration.

_Implementation mapping_:

- `backstitch/exclusions.py`
- `backstitch/models.py`

## 3. Classification Globs [EXC-3]

### 3.1 `meta_spec_globs`

Array of globs matching spec file paths relative to the repo root.

Files classified as **meta** are parsed normally, remain in `spec_roots`, and
may be cited from code. Default policy for sections in meta files:

| Issue code | Default when meta |
|------------|-------------------|
| `SPEC_SECTION_UNMAPPED` | suppressed |
| `CODE_BACKLINK_RECIPROCAL_MISSING` for mappings to non-`.py` paths | suppressed |
| `SPEC_MAPPING_RECIPROCAL_MISSING` | not suppressed |
| non-suppressible effective levels ([SC-11], [SC-15]) | never suppressed |

Meta classification does not exempt a section from broken references,
duplicate IDs, or malformed mappings.

### 3.2 `process_spec_globs`

Alias of `meta_spec_globs` in v1. Both keys merge. Prefer `meta_spec_globs` in
new configuration.

### 3.3 Relationship to planned/exploratory

| Glob | Meaning |
|------|---------|
| `planned_spec_globs` | Product behavior not yet shipped; code citation warns |
| `exploratory_spec_globs` | Experimental product behavior; code citation warns |
| `meta_spec_globs` | Non-product/process documentation; mapping not required |

A file may match multiple globs. Precedence: explicit inline suppression >
config suppression > `meta` > `exploratory` > `planned` > default.

This precedence and the [EXC-6.2] stack answer different questions and must
not be conflated: this section (§3) governs how a *file* is classified when
globs overlap; [EXC-6.2] governs whether an *emitted issue* is suppressed.
When a file is both a `meta_spec_glob` match and carries an inline ignore,
classify the file by §3, then run each emitted issue through §6.2.

_Implementation mapping_:

- `backstitch/exclusions.py`
- `backstitch/config.py`
- `backstitch/settings.py`

## 4. Inline Directives In Specs [EXC-4]

### 4.1 File-level preamble

Before the first section heading, an optional block:

```markdown
_Traceability: meta_
```

or

```markdown
_Traceability: ignore SPEC_SECTION_UNMAPPED, CODE_BACKLINK_RECIPROCAL_MISSING_
```

Applies to all sections in the file unless a section overrides it.

### 4.2 Section-level marker

Immediately after a section heading or invariant bullet, before body text:

```markdown
## 5. Planning Standard [DOM-5]

_Traceability: meta_

Non-trivial changes should begin with a dated plan...
```

or

```markdown
_Traceability: ignore SPEC_SECTION_UNMAPPED_
```

Section markers override file-level markers for that section only.

### 4.3 HTML comment form (optional alternative)

```markdown
## 5. Planning Standard [DOM-5] <!-- backstitch: meta -->
```

and

```markdown
<!-- backstitch: ignore SPEC_SECTION_UNMAPPED -->
```

HTML comments are equivalent to `_Traceability:` markers. Parsers must accept
both.

### 4.4 Syntax rules

- Marker line is case-insensitive on the `Traceability` label.
- `meta` applies the **full** meta classification policy of [EXC-3] to its
  scope — the same suppression table as a `meta_spec_globs` match, not a
  shorthand for ignoring `SPEC_SECTION_UNMAPPED` alone. One word, one
  meaning, wherever it appears.
- `ignore` accepts a comma-separated list of diagnostic codes.
- Unknown diagnostic codes — in config tables or inline markers — are validation
  errors: exit `2` naming the code and its location, by default. A
  suppression naming a code that does not exist is the same fake affordance
  as a typo'd config key ([CFG-8]): it looks like protection and does
  nothing. `allow_unknown_keys = true` downgrades unknown codes to structured
  suppression-hygiene diagnostics, the same forward-compatibility hatch with
  the same scope.
  `warn_unused_ignores` is a different check entirely: it governs **stale**
  ignores — codes that are real but currently match no finding — and stays a
  warning-level diagnostic.
- Markers must not suppress diagnostics whose effective level is outside
  `diagnostics.suppressible_levels`.

An inline `meta` or `ignore` may append exactly
` because PATH#SUP-ID`, where `PATH` is a repo-relative POSIX spec path and
`SUP-ID` follows the suppression-declaration grammar in [EXC-6]. The
delimiter is the lowercase token `because` surrounded by ASCII spaces.
Codes precede the delimiter. HTML-comment forms use the same token order
before `-->`; underscore forms have one closing `_` after the declaration
reference:
`_Traceability: ignore CODE because PATH#SUP-ID_`. When
`lint.require_suppression_declarations = true`, omission of this clause
emits `SUPPRESSION_REASON_MISSING` and the directive does not suppress.
Under the packaged `false` default, the existing clause-free forms retain
their behavior.

### 4.5 Obligation skip marker

The only source-authored obligation skip grammar is [EVC-8.3.2], including its
inline-heading, HTML-comment, and directive-block forms; strict JSON reason;
placement, ownership, coexistence order, byte/character limits; and code-only
invariant exclusion. This spec does not define a second spelling. One ordinary
`meta` or `ignore` directive may coexist in the exact EVC order. Ordinary
traceability policy and skip disposition are parsed independently.

A valid marker changes only the obligation disposition to `skipped`, excludes
semantic execution, and emits auditable `OBLIGATION_SKIPPED`/`BSE001`. It does
not change alignment or suppress trace, invariant, identity, syntax,
containment, currentness, or artifact-integrity findings. Backstitch never
writes or removes skip markers. A code-only invariant has no valid v1 skip
location.

_Implementation mapping_:

- `backstitch/cli.py`
- `backstitch/diagnostics.py`
- `backstitch/exclusions.py`
- `backstitch/markdown_specs.py`
- `backstitch/resolver.py`

## 5. Inline Directives In Python [EXC-5]

### 5.1 Module docstring and comments

```python
"""Resolver.

Spec: docs/specs/02-backstitch-core.md [SC-4]
backstitch: noqa SPEC_MAPPING_RECIPROCAL_MISSING
"""
```

and line comments:

```python
# backstitch: noqa CODE_REF_UNMAPPED_FROM_SPEC
```

Rules:

- Token sequence is `backstitch:` then `noqa` then one or more issue codes.
- Applies to the module (docstring form) or the containing logical block
  (comment form applies to next statement only in v1; module scope for
  docstring).
- `# backstitch: ignore` is an alias for `# backstitch: noqa`.

Python `noqa` and `ignore` directives accept the same terminal
` because PATH#SUP-ID` clause. It does not change docstring-module or
next-statement scope. Under required-declaration mode a clause-free
directive emits `SUPPRESSION_REASON_MISSING` and does not suppress.

`backstitch: no-spec` is not a `noqa`/`ignore` alias. Its exact comment and
docstring placement, token grammar, mandatory reason, ownership, and inert
near-miss behavior are [COV-4]. The coverage parser owns that marker and its
separate exemption ledger; this section does not widen ordinary inline
suppression syntax.

_Implementation mapping_:

- `backstitch/python_refs.py`
- `backstitch/exclusions.py`
- `backstitch/resolver.py`

## 6. Configuration [EXC-6]

Extend `[tool.backstitch]` / `.backstitch.toml`:

```toml
[tool.backstitch.profile]
meta_spec_globs = ["docs/specs/01-development-documentation-operating-model.md"]

[tool.backstitch.lint]
warn_unused_ignores = true

[tool.backstitch.lint.per-file-ignores]
"docs/specs/01-development-documentation-operating-model.md" = ["SPEC_SECTION_UNMAPPED"]

[tool.backstitch.lint.per-section-ignores]
"docs/specs/02-backstitch-core.md::SC-8" = ["SPEC_SECTION_UNMAPPED"]
"docs/specs/01-development-documentation-operating-model.md::*" = ["SPEC_SECTION_UNMAPPED"]
```

### 6.1 Keys

| Key | Type | Meaning |
|-----|------|---------|
| `meta_spec_globs` | string array | File-level meta classification ([EXC-3]) |
| `process_spec_globs` | string array | Alias of `meta_spec_globs` in v1 |
| `lint.warn_unused_ignores` | bool | Warn when a suppression matches nothing (default `true`) |
| `lint.require_suppression_declarations` | bool | Require governed rules to resolve a spec declaration (default `false`) |
| `lint.suppressions` | ordered array of closed tables | Structured declared `ignore` and file-scoped `meta` rules |
| `lint.per-file-ignores` | table path → codes | Suppress issue codes for entire spec or code files |
| `lint.per-section-ignores` | table `path::ID` → codes | Suppress codes for one section; `path::*` for all sections in file |

Path keys are repo-relative globs or exact paths. Section keys use
`relative/spec/path.md::SECTION_ID`.

Skip has no configuration key and no `allow_skips` switch. Repositories that
prohibit valid skips promote `BSE001` through ordinary diagnostic policy.

### 6.2 Precedence

Later steps override earlier steps for the same diagnostic code and location:

1. effective diagnostic policy decides suppressible levels
2. `meta_spec_globs` / section `meta` marker
3. `lint.per-file-ignores` and `lint.per-section-ignores`
4. inline `_Traceability:` / `backstitch: noqa` markers
5. CLI flag `--show-suppressions` only affects reporting, not precedence

Inline markers win over config so local intent beats central config, matching
`# noqa` behavior in Ruff.

Suppressibility is based on the effective diagnostic level after policy
application and the configured `diagnostics.suppressible_levels`. By default,
`warning` and `info` diagnostics are suppressible and `error` diagnostics are
not. Attempts to suppress a non-suppressible effective level emit
`SUPPRESSION_UNSUPPRESSIBLE_CODE`.

Invariant diagnostics use normal canonical and short-code policy and the audit
stream. Under packaged defaults, required untested is error-level and not
suppressible; draft untested is warning-level and suppressible. Repository
effective policy controls suppressibility, and `off` remains auditable.

### 6.3 `extend_exclude` vs exclusions

| Mechanism | DOM operating-model example |
|-----------|----------------------------|
| `extend_exclude` | File not scanned at all; no sections; code cannot resolve `[DOM-*]` |
| `meta_spec_globs` | File scanned; `[DOM-*]` resolvable; mapping not required |
| `per-file-ignores` | File scanned; only named issue codes suppressed |

For `01-development-documentation-operating-model.md`, prefer `meta_spec_globs`
or `per-file-ignores`, not `extend_exclude`, so the file stays in the corpus.

### 6.4 Documented suppression rules

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

`lint.require_suppression_declarations` is boolean and defaults to `false`.
It governs legacy meta globs, legacy per-file/per-section ignores, and inline
meta/ignore directives. When true, a legacy or inline rule without a valid
declaration reference does not suppress and emits
`SUPPRESSION_REASON_MISSING`. It does not govern scan exclusion, adoption
rungs, obligation skips, or diagnostic `off` policy.

`lint.suppressions` is an ordered array of closed tables. Each table contains
exactly `mechanism`, `path`, `sections`, `codes`, and `declaration`.
`mechanism` is `ignore` or `meta`. `path` is one nonblank repo-relative glob
with the existing [EXC-6] anchoring and match semantics. `sections` is an
array of unique valid section IDs; an empty array means file scope. `ignore`
requires one or more unique ordinary diagnostic codes. Canonical long and
short-code aliases follow the existing [EXC-2] rules. Input order is not
significant; Backstitch canonicalizes section IDs lexically and codes by
registry identity before matching, display, or hashing. `meta` requires
`codes = []`, applies the exact [EXC-3] policy, and requires
`sections = []`, preserving config-meta's existing file scope. Section-level
meta remains an [EXC-4] inline capability. Every structured rule requires one
declaration
regardless of the global bool. Unknown fields, invalid combinations,
duplicates, and malformed references follow [CFG-8].
Structured `ignore` rules occupy the existing configured-ignore precedence
tier. Structured `meta` rules occupy the existing meta-classification tier
and feed the same effective meta set used by deterministic checks and
obligation-rung projection.

`lint.suppressions` follows ordinary array replacement across `extend`
layers; it does not gain the special append behavior of
`diagnostics.levels`. A child that replaces the array restates every
structured rule it intends to retain. Rule origin records the exact
contributing config layer and zero-based array position.

A suppression declaration is a CommonMark paragraph token in a scanned spec:

`_Traceability: suppression-declaration [SUP-ID] "strict JSON string"_`

`SUP-ID` is `SUP-` followed by one or more uppercase ASCII letters, digits,
dots, or hyphens, with an uppercase letter or digit at each end. It is unique
across the accepted spec corpus. The marker must be ordinary paragraph
content under an owning ID-bearing section, not a fence, code block, HTML
comment, heading suffix, preamble, or Python source. The final value uses the
exact [EVC-8.3.2] JSON-string decoding, nonblank, line-safety, and 4096-byte
limits. A reference is exactly `repo/relative/spec.md#SUP-ID`; bare IDs,
absolute paths, backslashes, globs, fragments naming ordinary section IDs,
and paths outside effective `spec_roots` are invalid.

Declaration parsing produces source artifacts but does not itself suppress
any finding. One declaration may authorize more than one operational rule
only when each rule references it explicitly. Under
`warn_unused_ignores = true`, an unreferenced declaration or a referenced
rule that matches no issue emits `SUPPRESSION_UNUSED`.

_Implementation mapping_:

- `backstitch/exclusions.py`
- `backstitch/grammar.py`
- `backstitch/models.py`
- `backstitch/settings.py`
- `backstitch/check_pipeline.py`

## 7. Reporting And CLI [EXC-7]

Add optional reporting flags:

```bash
backstitch check --show-suppressions
```

When set, text/JSON output includes suppressed findings in a separate
`suppressed_issues` collection with the canonical provenance reason (`meta`,
`config_file`, `config_section`, `inline_spec`, or `inline_code`) and scope.

Default output omits suppressed findings entirely. Findings disabled by
`level = "off"` use the same audit view with reason `diagnostic level off`.

`--show-suppressions` also lists every valid obligation skip with obligation
ID, decoded reason, source path and line, and effective `BSE001` policy. The
skip remains visible even when BSE001 is off; it is an audit record, not proof
that ordinary trace findings were suppressed.

Coverage exemptions and drift/policy acknowledgments use the separate closed
audit ledgers in [COV-3], [COV-5], and [COV-8]. They are not projected into
`suppressed_issues` and cannot gain ordinary suppression authority. Coverage
reports must preserve every used, overlap-only, unused, malformed, and
acknowledged record required by [COV-4]/[COV-9].

Each governed suppressed issue retains the existing `reason` provenance
field and adds `declaration` and `rationale`. These fields are always present
in JSON; each is `null` only for a legacy suppression accepted while
required-declaration mode is false. Text output shows provenance,
declaration, and rationale, rendering rationale with canonical JSON-string
escaping rather than writing source bytes as terminal control text. The
source rationale is data, not trusted terminal markup. Diagnostic `off`
audit records retain
`reason = "diagnostic level off"` and null declaration/rationale.
Structured meta rules reuse `reason = "meta"`. Structured ignore rules reuse
`reason = "config_file"` when `sections = []` and
`reason = "config_section"` otherwise. Inline forms retain
`inline_spec`/`inline_code`; the additive fields do not mint a second
provenance vocabulary.

_Implementation mapping_:

- `backstitch/reporting.py`
- `backstitch/check_pipeline.py`
- `backstitch/cli.py`
- `backstitch/models.py`

## 8. Failure Modes [EXC-8]

Exit code `2` when strict loading sees:

- a suppression names an unknown diagnostic code
- malformed `_Traceability:` syntax

Recognized `skip-obligation` source syntax is the exception defined by
[EVC-8.3.2]. Malformed syntax, placement, ownership, coexistence, or duplicate
markers emit warning-level `SUPPRESSION_INVALID_SYNTAX`/`BSX004` and leave the
disposition `evaluate`; missing/blank reasons emit
`SUPPRESSION_REASON_MISSING`/`BSX010`; and a well-formed target without a
parsed owner emits `SUPPRESSION_UNUSED`/`BSX001`. These repository-source
diagnostics do not become strict-loader exit `2`, and
`allow_unknown_keys` does not alter this reserved grammar. Invalid config or
invocation syntax still exits `2`.

Under `allow_unknown_keys = true`, unknown codes and malformed clause-free
legacy suppressions that arise from repository files or repository
configuration are downgraded into structured suppression-hygiene diagnostics.
The strict declaration-integrity exceptions below are never downgraded.

Suppression-hygiene diagnostics use stable codes:

- `SUPPRESSION_UNUSED`
- `SUPPRESSION_UNKNOWN_CODE`
- `SUPPRESSION_INVALID_SYNTAX`
- `SUPPRESSION_UNSUPPRESSIBLE_CODE`
- `SUPPRESSION_REASON_MISSING`
- future reserved codes listed in [SC-15]

These diagnostics enter the same report stream as other target diagnostics
when they arise from repository files or repository configuration. Invocation
failures while loading a requested config file still follow [SC-5] exit `2`.

Invariant findings follow the same lifecycle. Required untested cannot be
suppressed under packaged defaults; draft untested can. A repository policy
override may change that result only through the ordinary effective-level and
`suppressible_levels` rules, never through an invariant-specific bypass.

`SUPPRESSION_REASON_MISSING` also fires when required-declaration mode sees
no reference, an unresolved declaration, or a declaration with no valid
decoded rationale. `SUPPRESSION_INVALID_SYNTAX` fires for malformed source
declaration syntax, placement, reference syntax, duplicate markers in one
owning section, or a duplicate `SUP-*` identity anywhere in the accepted
corpus. Every duplicate declaration is invalid and no affected rule
suppresses. Existing duplicate-section diagnostics remain authoritative for
ordinary spec sections. In every case the affected rule
is ineligible to suppress. `allow_unknown_keys` does not downgrade these
source-integrity findings when required-declaration mode is enabled.
Structured rules and inline directives that voluntarily include a `because`
clause always use this strict declaration-integrity path regardless of the
global bool: the named hygiene code fires, the rule does not suppress, and
`allow_unknown_keys` does not downgrade it. The bool governs only whether a
clause-free legacy rule remains eligible.

_Implementation mapping_:

- `backstitch/diagnostics.py`
- `backstitch/exclusions.py`

## 9. Verification Expectations [EXC-9]

Required proof:

- meta file suppresses `SPEC_SECTION_UNMAPPED` but not `SPEC_SECTION_MISSING`
- section-level `ignore` suppresses only that section
- `per-file-ignores` and `per-section-ignores` work from config
- inline Python `backstitch: noqa` suppresses configured code-side warnings
- scope containment for comment-form `noqa`: a fixture with two findings of
  the same code in one file, where the `noqa` comment sits on only one of
  them, must suppress exactly that one — the [EXC-5] next-statement rule is
  the contract, and file-wide bleed of a comment-form directive is the
  specific regression this test exists to catch (docstring-form remains
  module-scoped)
- every suppressed finding is recoverable: with `--show-suppressions`, each
  suppression appears in `suppressed_issues` with its reason; suppression
  must never silently delete a finding from every view
- `warn_unused_ignores` warns on stale config entries
- an unknown issue code in a suppression (config or inline) exits `2` by
  default and downgrades to a warning under `allow_unknown_keys = true`
- precedence tests: inline beats config; meta does not suppress errors
- invariant tests prove required and draft untested under packaged defaults,
  plus an explicit policy override and `off` audit recovery
- every valid and invalid [EVC-8.3.2] form fires its exact disposition,
  BSE001/hygiene code, policy, and audit result; valid skip leaves ordinary
  trace findings intact, malformed skip remains `evaluate`, code-only
  invariants reject skip, and no command mutates source
- DOM fixture: zero `SPEC_SECTION_UNMAPPED` with `meta_spec_globs`, sections
  still parsed

Verification covers both strictness modes; every Markdown, HTML, docstring,
comment, legacy-config, structured-ignore, and structured-meta form; missing,
blank, malformed, duplicate, misplaced, unresolved, outside-root, unused,
valid declarations; exact section containment; precedence;
canonical ordering; additive audit fields; and the invariant that an invalid
required declaration leaves the original finding active. A firing
configuration test proves the new bool changes behavior and a no-op test
fails if its runtime consultation is removed.

_Implementation mapping_:

- `tests/test_exclusions.py`
- `tests/test_python_noqa.py`

## 10. Documentation [EXC-10]

Update on implementation:

- `docs/specs/03-backstitch-configuration.md` — cross-link `lint` tables
- `docs/specs/02-backstitch-core.md` — note exclusions in [SC-9]
- `docs/implementation/04-backstitch-style-traceability.md`
- invariant documentation must show draft-tier suppressibility,
  required-tier non-suppressibility, policy override behavior, and audit output

Backstitch enables required-declaration mode. Its suppression declarations
live in this spec. The dogfood migration must audit each existing policy
family, remove stale rules, narrow the EVC file-wide rule to exact current
sections or split it by rationale, and add no new suppressed scope. Every
retained rule appears in `--show-suppressions` with its declaration and
decoded rationale.

_Traceability: suppression-declaration [SUP-DOM-META] "The development-documentation operating model defines repository process rather than runtime behavior, so its sections remain addressable but do not require implementation mappings."_

_Traceability: suppression-declaration [SUP-EVC-PROCESS] "The EVC purpose and coordinated promotion record define scope and documentation process; neither claims a direct runtime implementation owner."_

_Traceability: suppression-declaration [SUP-EVC-DEFERRED-MCP] "The optional local MCP adapter is explicitly deferred and has no implementation mapping until that product phase is promoted."_

_Traceability: suppression-declaration [SUP-COV-INFLIGHT] "Intent coverage is active while its implementation lands section by section; exact unmapped sections remain visible and temporarily non-failing until each production owner, mapping, and reciprocal backlink lands together."_

_Traceability: suppression-declaration [SUP-TEST-CITATIONS] "Tests cite contracts as verification evidence but are not general implementation owners; test-only unmapped backlinks and reciprocal-mapping findings are retained as audited noise."_

_Implementation mapping_:

- `docs/implementation/04-backstitch-style-traceability.md`

## Related Plans

- `docs/plans/2026-07-28-intent-coverage-implementation-plan.md`
  (active implementation plan; [COV-*] promotion and temporary inflight debt)
- `docs/plans/2026-07-28-documented-suppression-governance-plan.md`
  (implemented and independently reviewed)

- `docs/plans/2026-07-15-agent-guided-evidence-cases-plan.md`
  (implementing)
- `docs/plans/2026-07-09-backstitch-invariant-traceability-plan.md`
  (implemented)
- `docs/plans/2026-07-08-configurable-diagnostics-plan.md` (implementing)
- `docs/plans/2026-07-06-backstitch-organization-refactor-plan.md` (implementing)
- `docs/plans/2026-07-02-backstitch-four-way-reconciliation-plan.md` (implementing)
- `docs/plans/2026-07-02-backstitch-traceability-exclusions-plan.md`
