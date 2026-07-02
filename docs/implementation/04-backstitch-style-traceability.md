# Backstitch Style Traceability — Implementation

Spec: docs/specs/02-backstitch-core.md [SC-1]–[SC-12]
Spec: docs/specs/03-backstitch-configuration.md [CFG-1]–[CFG-10]
Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-1]–[EXC-10]
Plan: docs/plans/2026-07-02-backstitch-four-way-reconciliation-plan.md

This document explains why the reconciled implementation is shaped the way
it is — boundaries, tradeoffs, and provenance — not a narration of the code.

## Provenance And Boundaries

The implementation is a harvest, not a rewrite: the deterministic core
(parsers, resolver, fixtures, test depth) comes from the fable-5 bake-off
branch; `settings.py`, `exclusions.py`, and `target_roots.py` come from the
implement branch adapted to the canonical spec schema; `grammar.py` and the
injectable-adapter llm boundary follow the opus branch; the path-resolution
ladder generalizes a codex hardening idea. Every port carried named
adaptations recorded in the plan; nothing was adopted wholesale.

Load-bearing boundaries:

- **Purity.** `resolve()` is pure: parsed records in, `Report` out. All
  filesystem truth (path existence, symbol inventories, scan file lists) is
  gathered by `scan_repository` and passed in, so graph policy is testable
  without IO and reruns are byte-stable.
- **The llm quarantine.** `check` and `packets` are structurally incapable
  of importing `llm`: the import lives inside `analysis_llm.default_adapter`
  and the `analyze` CLI handler, and a subprocess test asserts
  `llm ∉ sys.modules` for deterministic commands ([SC-8]).
- **Suppression is not filtering.** `reporting.py` renders; it never drops
  findings. Suppression happens once, in the CLI pipeline, after emission
  and before exit-code and render, through `exclusions.py` — and every
  suppressed finding is recoverable with `--show-suppressions` ([EXC-7]).
  Fable's audit-free `filter_report` was deliberately not ported.
- **Severity gates on the instance.** [SC-11] has context-dependent codes;
  non-suppressibility checks `issue.severity == "error"`, never bare code
  membership, so a warning-context finding stays suppressible.

## Grammar Decisions Worth Knowing

- Section IDs require a digit (`grammar.py`) — excludes glossary bullets
  like `**Manager**:` without losing any documented ID form.
- Bare bracketed refs resolve by the known-prefix rule: unknown prefixes
  (`window[N-1]`, `[JIRA-123]`) are silent; known prefixes that match
  nothing warn (`CODE_REF_BARE_UNRESOLVED`).
- Ambiguity severity follows reference context ([SC-11]):
  `CodeRef.ref_context` is set by the parser and never re-inferred from
  text downstream. The context is three-way: `asserted` (a docstring line
  starting with the `Spec:` marker — a claimed trace edge, ambiguity is an
  error), `docstring` (docstring prose citing an ID — a weak link, warning),
  and `comment` (warning). Only the marker line asserts; prose in the same
  docstring does not.
- ID-less subheadings deeper than the owning section (`### 6.7` inside
  `## 6 [CFG-6]`) do not clear mapping-block ownership; same-or-shallower
  ID-less headings do. Real specs put subsections between an ID heading and
  its mapping block.
- Mapping tokens resolve by the [SC-4] ladder: exact silently; unique
  suffix with `MAPPING_PATH_INEXACT` (edge kept); multiple candidates
  `TARGET_PATH_AMBIGUOUS` (no edge); none `MAPPING_PATH_MISSING` with the
  plan-`.md` warning predicate.
- Comment-form `backstitch: noqa` attaches to the next statement's AST span
  only ([EXC-5]); the docstring form is module-scoped. File-wide bleed of a
  comment directive is the [EXC-9] regression class and has a dedicated
  containment fixture.
- The noqa directive is anchored at line start ([EXC-5] grammar): prose
  merely mentioning `backstitch: noqa` never parses, and on a directive
  line everything after the marker must be issue codes — a bare directive
  or an unparseable tail always warns, and an unknown code follows [EXC-4]
  strictness (error by default, warning under the hatch). Silently dropped
  tails are the fake-protection class the exclusions spec exists to
  prevent.

## Dogfood Configuration And Suppression Audit

`pyproject.toml` carries the committed configuration. Choices and their
reasons:

- `extend_exclude` (never bare `exclude`): the defaults already exclude
  `.worktrees`; replacing them would scan four archived bake-off
  implementations into the corpus.
- Exclusion has exactly one authority: `settings.is_excluded`
  (component-aware, so a bare `venv` skips the subtree at any depth). The
  resolver takes `None` to mean the built-in defaults and an explicit
  empty tuple to mean scan everything — no hard-coded dot-directory skip
  sits underneath the config ([CFG-6.7]).
- `tests` stays in `code_roots` because test-to-spec edges are part of the
  graph; the fixture corpora inside `tests/` are intentionally broken
  mini-projects and are excluded as scan boundaries, not suppressed.
- `meta_spec_globs` classifies the DOM operating-model spec as process
  documentation: parsed, citable, mapping not required.
- The only lint suppressions are on `tests/*` for citation-inventory codes
  (`CODE_REF_UNMAPPED_FROM_SPEC`, `SPEC_MAPPING_RECIPROCAL_MISSING`): test
  files cite the sections they exercise without being implementation
  owners. Both are recoverable via `--show-suppressions` and asserted
  auditable by `tests/test_backstitch_corpus_traceability.py`.

The self-corpus gate requires exit 0 with zero errors AND zero warnings on
the default invocation; the dogfood-delta test proves the config is live by
diffing against `--no-config`.

## Verification Map

- Unit/contract: `tests/test_*.py` (parsers, resolver, ladder, settings,
  exclusions, target roots, analysis pipeline)
- Contract coverage: `tests/test_issue_code_coverage.py` — every [SC-11]
  code fires, context-dependent severities fire both ways
- Review remediation regressions: `tests/test_review_remediation.py` — one
  test per reproduced independent-review finding (heading markers, live
  config keys, noqa hygiene, marker override, fence length)
- Acceptance: `tests/acceptance/` — the twelve [SC-10] probes, black-box
- Self-corpus: `tests/test_backstitch_corpus_traceability.py`

## Golden Report Ledger

`tests/fixtures/traceability_project.expected.json` freezes the full broken-
fixture report; `tests/test_behavior_freeze.py` regenerates it only under
`BACKSTITCH_UPDATE_GOLDEN=1`. Intentional regenerations so far:

- Reconciliation Task 19 (initial freeze): baseline capture of the reconciled
  behavior over the four-way fixture corpus.
- Review remediation (2026-07-02): `ref_context` gained the asserted/prose
  split. The diff was ten hunks, all relabeling `"docstring"` refs on `Spec:`
  marker lines to `"asserted"`; the issue histogram was unchanged (the
  fixture's one ambiguity is comment-context and stays a warning). The Weft
  external gate moved 32 -> 24 errors for the same reason: eight
  docstring-prose ambiguity instances became warnings; the nine pinned error
  signatures are unchanged.
