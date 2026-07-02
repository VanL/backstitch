# Backstitch Traceability Exclusions Plan

Status: archival — written against the `implement-backstitch` branch during
the four-way bake-off. The go-forward base is `impl-fable-5`; a new
reconciliation plan will supersede this one. Where this plan and
`docs/specs/04-backstitch-traceability-exclusions.md` disagree, the spec is
authoritative (notably: comment-form `noqa` scope).

Source specs:

- `docs/specs/04-backstitch-traceability-exclusions.md` [EXC-1]–[EXC-10]
- `docs/specs/02-backstitch-core.md` [SC-3], [SC-9], [SC-11]
- `docs/specs/03-backstitch-configuration.md` [CFG-6]

Depends on: `implement-backstitch` branch (settings loader, resolver, config)

## Goal

Add ruff/mypy-style exclusions so backstitch can require full traceability on
product specs while allowing controlled partial ignores for process/meta
sections — without `extend_exclude` (whole-file scan skip) and without fake
`_Implementation mapping_` blocks.

Immediate consumer: `docs/specs/01-development-documentation-operating-model.md`
stays in `spec_roots`; its `[DOM-*]` sections stop emitting
`SPEC_SECTION_UNMAPPED` via `meta_spec_globs`.

## Source Documents

Read in this order:

1. `docs/specs/04-backstitch-traceability-exclusions.md`
2. `docs/specs/03-backstitch-configuration.md` [CFG-6], [CFG-6.7]
3. `docs/specs/02-backstitch-core.md` [SC-3], [SC-11]
4. `backstitch/resolver.py` — `SPEC_SECTION_UNMAPPED` emission (~L414)
5. `backstitch/markdown_specs.py` — section parsing
6. `backstitch/settings.py` — config schema extension point
7. Ruff docs: `per-file-ignores`, `extend-exclude`
8. mypy docs: `warn_unused_configs`, per-module sections

Comprehension checks:

- Why is `meta_spec_globs` better than `extend_exclude` for DOM?
- Why must error-severity codes stay non-suppressible by default?
- Where does precedence differ from ruff (inline beats config)?

## Context and Key Files

| Path | Role today |
|------|------------|
| `backstitch/resolver.py` | Emits all issue codes; no suppression |
| `backstitch/markdown_specs.py` | Parses sections; has `is_planned` / `is_exploratory` only |
| `backstitch/python_refs.py` | Parses code refs; no noqa |
| `backstitch/settings.py` | Config loader; has `exclude` only |
| `backstitch/models.py` | `SpecSection` dataclass |
| `backstitch/cli.py` | Applies settings to checks |
| `docs/specs/01-development-documentation-operating-model.md` | 12× `SPEC_SECTION_UNMAPPED` today |

### Files to create

| Path | Purpose |
|------|---------|
| `backstitch/exclusions.py` | Suppression index, precedence, `should_suppress()` |
| `tests/test_exclusions.py` | Unit tests |
| `tests/fixtures/meta_spec_project/` | DOM-like meta spec fixture |

### Files to modify

| Path | Change |
|------|--------|
| `backstitch/models.py` | `SpecSection.is_meta`, optional `suppressions` metadata |
| `backstitch/markdown_specs.py` | Parse `_Traceability:` and HTML markers |
| `backstitch/python_refs.py` | Parse `backstitch: noqa` in docstrings/comments |
| `backstitch/settings.py` | `lint` tables, `meta_spec_globs` |
| `backstitch/resolver.py` | Filter issues through `should_suppress()` |
| `backstitch/cli.py` | Optional `--show-suppressions` |
| `pyproject.toml` | `meta_spec_globs` for DOM spec |
| `docs/specs/03-backstitch-configuration.md` | Document new keys |
| `docs/specs/00-specs-index.md` | Add spec 04 |
| `docs/implementation/04-backstitch-style-traceability.md` | Exclusion boundary |

## Invariants and Constraints

- `exclude` / `extend_exclude` behavior unchanged ([CFG-6.7]).
- `planned_spec_globs` / `exploratory_spec_globs` semantics unchanged ([SC-3]).
- Error-severity codes in [SC-11] are not suppressible unless a future spec
  explicitly adds an escape hatch.
- Suppressed issues must not affect exit codes ([SC-5]).
- Product specs (`02-*`, `03-*`) keep current mapping requirements unless
  explicitly suppressed.
- Parser must not call `llm`.
- Rollback: remove `exclusions.py` and config keys; DOM infos return.

## Design Summary

### Three mechanisms (use the right one)

```text
extend_exclude          → file not scanned (already shipped)
meta_spec_globs         → process/meta file; no mapping required
per-file-ignores      → file scanned; named codes suppressed
per-section-ignores   → partial file ignore (DOM section mixed with product — future)
_Traceability: meta_   → section-level, in-spec, reviewable in PR
backstitch: noqa        → Python-side suppressions
```

### DOM recommendation (this repo)

```toml
[tool.backstitch.profile]
meta_spec_globs = ["docs/specs/01-development-documentation-operating-model.md"]
```

Not `extend_exclude` — DOM stays parsed and `[DOM-*]` remains resolvable if
code ever cites it.

### Partial ignore example

If `02-backstitch-core.md` section [SC-8] (non-goals) should not require a
mapping:

```markdown
## 8. Boundaries And Non-Goals [SC-8]

_Traceability: meta_
```

or config:

```toml
[tool.backstitch.lint.per-section-ignores]
"docs/specs/02-backstitch-core.md::SC-8" = ["SPEC_SECTION_UNMAPPED"]
```

## Tasks

### 1. Spec and index (done with this plan)

- Publish `docs/specs/04-backstitch-traceability-exclusions.md`
- Update `docs/specs/00-specs-index.md`

### 2. Exclusion engine

- File: `backstitch/exclusions.py`
- Implement:
  - `SuppressionIndex` built from settings + parsed inline markers
  - `should_suppress(issue, *, spec_file, section_id, code_file, line) -> bool`
  - `SuppressionReason` enum: `meta`, `config_file`, `config_section`, `inline_spec`, `inline_code`
  - `ERROR_CODES` frozenset from [SC-11]
- Stop gate: precedence unit tests before resolver wiring

### 3. Parse spec markers

- File: `backstitch/markdown_specs.py`
- Parse file preamble and per-section `_Traceability: meta_` / `ignore CODE,...`
- Parse `<!-- backstitch: meta -->` on heading lines and ignore comments
- Set `SpecSection.is_meta` from classification + markers
- Extend `_classify_spec_file()` with `meta_spec_globs` from effective profile

### 4. Extend settings and profile

- Files: `backstitch/settings.py`, `backstitch/config.py`, `backstitch/profiles.py`
- Add `meta_spec_globs`, `process_spec_globs` to profile overlay
- Add `[lint]` tables: `warn_unused_ignores`, `per-file-ignores`,
  `per-section-ignores`
- Wire CLI profile merge for new keys

### 5. Parse Python noqa

- File: `backstitch/python_refs.py`
- Recognize `backstitch: noqa CODE` in module docstrings (module scope) and
  comments (next-statement scope, required per [EXC-5]; file-wide bleed of a
  comment-form directive is the regression [EXC-9] tests against)
- Store on `CodeRef` metadata or parallel structure for resolver

### 6. Resolver integration

- File: `backstitch/resolver.py`
- Before appending each `Issue`, call `should_suppress()`
- Skip `SPEC_SECTION_UNMAPPED` when `section.is_meta`
- Collect suppressed issues when `--show-suppressions` set
- Implement `warn_unused_ignores` pass after check completes

### 7. CLI and reporting

- File: `backstitch/cli.py`, `backstitch/reporting.py`
- Add `--show-suppressions` to `check`
- JSON report: optional `suppressed_issues` array with `reason` and `scope`

### 8. Dogfood DOM + tests

- `pyproject.toml`: `meta_spec_globs` for DOM spec
- Fixtures:
  - meta spec file with mixed sections (one with `_Traceability: meta_`)
  - per-section-ignores config
  - stale ignore triggers `warn_unused_ignores`
- Assert DOM corpus: 0 warnings, 0 infos from DOM unmapped
- Assert product spec unmapped still fires without suppression

### 9. Documentation

- Update `03-backstitch-configuration.md`, `02-backstitch-core.md` [SC-9],
  implementation doc 04

## Testing Plan

| Test | Proves |
|------|--------|
| `test_meta_glob_suppresses_unmapped_only` | Meta file sections not unmapped |
| `test_meta_does_not_suppress_missing_section` | Errors still fire |
| `test_section_traceability_marker` | Partial section ignore |
| `test_per_file_ignores_config` | Config path works |
| `test_per_section_ignores_wildcard` | `path::*` works |
| `test_inline_noqa_module_docstring` | Python suppression |
| `test_precedence_inline_over_config` | Precedence [EXC-6.2] |
| `test_warn_unused_ignores` | Stale config warns |
| `test_dom_corpus_no_unmapped_infos` | Real DOM spec clean |
| `test_extend_exclude_unchanged` | Regression [CFG-6.7] |

Commands:

```bash
uv run pytest tests/test_exclusions.py -q
uv run pytest -q
uv run mypy backstitch
uv run ruff check backstitch tests
uv run backstitch check --repo-root .
```

## Verification and Gates

- DOM: 12 `SPEC_SECTION_UNMAPPED` infos → 0
- Product specs: still 0 errors, 0 warnings
- `backstitch check --show-suppressions` lists suppressed DOM issues with
  reason `meta`
- No regression in Weft corpus test

## Independent Review Loop

- Reviewer: different agent family than author
- Read: spec 04, plan, `exclusions.py`, resolver diff
- Prompt: “Could you implement precedence without double-suppression bugs? Are
  error codes adequately protected?”

## Out of Scope

- Line-level Python `# backstitch: noqa` on arbitrary statements (v2)
- Suppressing semantic/`llm` findings
- `extend_exclude` changes
- Moving DOM out of `docs/specs/`
- CI promotion of infos to errors
- UI/editor integration

## Fresh-Eyes Review

- [x] Three layers distinguished (scan vs classification vs targeted)
- [x] DOM uses `meta_spec_globs`, not `extend_exclude`
- [x] Partial ignore via section marker + per-section config
- [x] ruff/mypy analogues named
- [x] Precedence documented
- [x] Error codes protected
- [x] Tasks ordered with stop gates