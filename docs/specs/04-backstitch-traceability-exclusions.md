# Backstitch Traceability Exclusions Specification

Status: Active

This spec defines how `backstitch` suppresses selected deterministic findings
for chosen files, sections, or code locations without removing those files from
`spec_roots` or `code_roots`.

Related specs:

- `docs/specs/02-backstitch-core.md` [SC-4], [SC-9], [SC-11]
- `docs/specs/03-backstitch-configuration.md` [CFG-6]

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

**Scope** is where a suppression applies:

- repository path glob
- spec file
- spec section ID
- Python module path
- Python line (future v2; not required in first implementation)

A valid suppression must name at least one diagnostic code. Blanket “ignore
everything” is not allowed except through explicit `meta` classification on a
file or section.

_Implementation mapping_:

- `backstitch/exclusions.py`

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
| `lint.per-file-ignores` | table path → codes | Suppress issue codes for entire spec or code files |
| `lint.per-section-ignores` | table `path::ID` → codes | Suppress codes for one section; `path::*` for all sections in file |

Path keys are repo-relative globs or exact paths. Section keys use
`relative/spec/path.md::SECTION_ID`.

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

_Implementation mapping_:

- `backstitch/exclusions.py`
- `backstitch/settings.py`
- `backstitch/check_pipeline.py`

## 7. Reporting And CLI [EXC-7]

Add optional reporting flags:

```bash
backstitch check --show-suppressions
```

When set, text/JSON output includes suppressed findings in a separate
`suppressed_issues` collection with reason (`meta`, `config`, `inline`) and
scope.

Default output omits suppressed findings entirely. Findings disabled by
`level = "off"` use the same audit view with reason `diagnostic level off`.

_Implementation mapping_:

- `backstitch/reporting.py`
- `backstitch/check_pipeline.py`
- `backstitch/cli.py`

## 8. Failure Modes [EXC-8]

Exit code `2` when strict loading sees:

- a suppression names an unknown diagnostic code
- malformed `_Traceability:` syntax

Under `allow_unknown_keys = true`, unknown or malformed suppressions that arise
from repository files or repository configuration are downgraded into
structured suppression-hygiene diagnostics.

Suppression-hygiene diagnostics use stable codes:

- `SUPPRESSION_UNUSED`
- `SUPPRESSION_UNKNOWN_CODE`
- `SUPPRESSION_INVALID_SYNTAX`
- `SUPPRESSION_UNSUPPRESSIBLE_CODE`
- future reserved codes listed in [SC-15]

These diagnostics enter the same report stream as other target diagnostics
when they arise from repository files or repository configuration. Invocation
failures while loading a requested config file still follow [SC-5] exit `2`.

Invariant findings follow the same lifecycle. Required untested cannot be
suppressed under packaged defaults; draft untested can. A repository policy
override may change that result only through the ordinary effective-level and
`suppressible_levels` rules, never through an invariant-specific bypass.

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
- DOM fixture: zero `SPEC_SECTION_UNMAPPED` with `meta_spec_globs`, sections
  still parsed

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

_Implementation mapping_:

- `docs/implementation/04-backstitch-style-traceability.md`

## Related Plans

- `docs/plans/2026-07-09-backstitch-invariant-traceability-plan.md`
  (implemented)
- `docs/plans/2026-07-08-configurable-diagnostics-plan.md` (implementing)
- `docs/plans/2026-07-06-backstitch-organization-refactor-plan.md` (implementing)
- `docs/plans/2026-07-02-backstitch-four-way-reconciliation-plan.md` (implementing)
- `docs/plans/2026-07-02-backstitch-traceability-exclusions-plan.md`
