# Backstitch Style Traceability — Implementation

Spec: docs/specs/02-backstitch-core.md [SC-1]–[SC-15]
Spec: docs/specs/03-backstitch-configuration.md [CFG-1]–[CFG-10]
Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-1]–[EXC-10]
Spec: docs/specs/05-backstitch-invariants.md [INV-1]–[INV-10]
Plan: docs/plans/2026-07-08-configurable-diagnostics-plan.md
Plan: docs/plans/2026-07-09-backstitch-invariant-traceability-plan.md
Plan: docs/plans/2026-07-02-backstitch-four-way-reconciliation-plan.md
Plan: docs/plans/2026-07-07-tree-sitter-code-parser-plan.md

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
- **Markdown structure belongs to `markdown-it-py`.** `markdown_specs.py`
  interprets Backstitch traceability constructs over CommonMark tokens; it
  does not maintain an independent fence, indented-code, or block-boundary
  parser. `fence` and `code_block` tokens are non-declarative content, while
  recognized [EXC-4] HTML-comment marker tokens still feed the suppression
  marker path.
- **Python structure belongs to `tree-sitter-python`.** `code_parser.py`
  owns the runtime-independent parser seam for owner spans, doc blocks,
  comments, and statement spans; `python_refs.py` only interprets Backstitch
  traceability syntax over that structure. No `ast` or `tokenize` path parses
  target files. A malformed Python tree is all-or-nothing coverage loss:
  `PYTHON_SYNTAX_ERROR` is emitted as a suppressible warning and inline noqa
  inside that unparseable file cannot suppress it because no directives were
  extracted. Line numbers are derived from byte offsets through Backstitch's
  own line index rather than the binding `Point` accessors; the 0.26 binding
  crashed under repeated traversal during migration testing, and byte offsets
  are the stable source of truth. This boundary is a traceability parser, not
  a Python validity checker: some invalid legacy forms can still produce a
  tree, so ruff, mypy, and import/runtime tests remain responsible for code
  validity.
- **Test roots are role labels inside code roots.** The scanner walks
  `code_roots` once; `test_roots` only decides where `Tests-invariant:` may
  create binds. Code-root and test-root overrides are therefore paired. An
  explicit code-root override without a test-root override resets test roots,
  while a lone test-root override retains inherited code roots. This avoids
  scanning a second filesystem universe and makes omitted tests surface as
  BSI001 instead of silently inheriting stale role roots ([INV-3], [CFG-6]).
- **Invariant markers are consumed before ordinary refs.** `markdown_specs.py`
  and `python_refs.py` produce declaration and binding records from physical
  marker lines, then prevent those IDs from leaking into ordinary section
  references. `resolve()` owns shared-namespace uniqueness, valid binds,
  unknown references, no-cascade duplicates, and untested findings. It does
  not inspect snippets or semantic state ([INV-3], [INV-4]).
- **Packets and results are discriminated unions.** New section and invariant
  artifacts carry `kind`; only the three exact pre-invariant legacy shapes are
  normalized. Invariant packets bound targets and test definitions to eight
  records and 120 lines each, then hash only the final statement/target/test
  projection. The hash is comparison metadata, not a cache key or persistence
  feature ([INV-5], [SC-6]).
- **Binding quality stays at the model boundary.** `analyze` validates every
  cited path and line against shown target/test snippets, injects trusted
  packet kind/hash metadata, and converts evidence-deficient invariant `ok`
  results to `weak_binding`. `summarize-analysis` has no packet snippets, so it
  validates row identity and shape but deliberately does not re-prove locality
  ([INV-5], [SC-7]).
- **The llm quarantine.** `check` and `packets` are structurally incapable
  of importing `llm`: the import lives inside `analysis_llm.default_adapter`
  and the `analyze` CLI handler, and a subprocess test asserts
  `llm ∉ sys.modules` for deterministic commands ([SC-8]).
- **Constrained decoding when available.** `default_adapter` requests
  provider-enforced JSON output (`json_object=True`) whenever the resolved
  model's `Options` declares that field — a capability check, never a
  provider name — so servers with constrained decoding cannot emit
  syntactically invalid rows; models without the option get the unchanged
  call (`docs/plans/2026-07-06-analyze-json-mode-plan.md`).
- **The doctor shares the quarantine, not the pipeline.** `backstitch
  doctor` ([SC-14], `doctor.py`) diagnoses the same environment `analyze`
  depends on — model resolution via `resolve_model_name`, credentials,
  `json_object` capability, endpoint reachability behind `--probe` — but
  never generates, never mutates backstitch state, and imports `llm` only
  inside check functions. Its remedies stay provider-neutral; provider
  names live in `06-choosing-a-local-model.md`, which the memory check
  points at.
- **Diagnostic identity is not severity.** `diagnostics.py` owns the packaged
  registry, short-code aliases, context-aware default policy, and effective
  policy evaluation. Resolver/parser emission sites provide canonical code and
  context. `check_pipeline.py` applies packaged-default policy for
  `default_severity`, then layered repository policy for effective `severity`.
  This keeps resolver behavior independent of CLI/config state while making
  all-error, all-info, mixed, and `off` policies use the same path.
- **Suppression is not filtering.** `reporting.py` renders; it never drops
  findings. Suppression happens once, in `check_pipeline.py`, after effective
  policy application and before exit-code/render, through `exclusions.py`.
  Every suppressed finding is recoverable with `--show-suppressions` ([EXC-7]).
  Findings hidden by `level = "off"` use the same audit view with reason
  `diagnostic level off`. Fable's audit-free `filter_report` was deliberately
  not ported.
- **Suppressibility gates on effective level.** [SC-11] has
  context-dependent codes and [SC-15] makes level configurable. The
  suppression gate checks the issue's effective `severity` against
  `diagnostics.suppressible_levels`, never bare code membership. A warning
  context remains suppressible unless policy promotes it; a promoted error
  becomes non-suppressible by policy.
- **Validation is total, bounded by self-acceptance.** Input validators
  mirror the *producer's* full record contract ([SC-13]), never the
  consuming code path's projection — that asymmetry is how nineteen review
  rounds found the same rule broken one field at a time. Packet JSONL and
  deterministic-report validators live in `artifact_contracts.py`; semantic
  result and model-output validation stay with `analysis_results.py` and
  `analysis_llm.py`. The counterweight is [SC-13.5]: everything the tool
  emits must pass its own validation (acceptance probe 13), so tightening can
  never orphan real output.
- **Evidence locality is enforced where the packets are.** `analyze` holds
  the packets, so it is the boundary that rejects model evidence outside
  the packet's shown paths and line ranges ([SC-7]).
  `summarize-analysis` never sees packets: it validates result-row schema
  (classification, confidence in [0, 1], non-blank evidence paths) and
  rejects packet IDs no report packet could have produced (edge-bearing
  sections or bound invariants), and trusts that the rows came from `analyze`.
  Its `--help` says so; verifying a
  hand-edited results file requires rerunning `analyze`.

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
- Heading and code-span recognition follows `markdown-it-py` CommonMark
  tokenization: setext headings and ATX headings with closing hashes can
  define sections, and mapping tokens come from `code_inline` content rather
  than Backstitch's own backtick scanner.
- Mapping tokens resolve by the [SC-4] ladder: exact silently; unique
  suffix with `MAPPING_PATH_INEXACT` (edge kept); multiple candidates
  `TARGET_PATH_AMBIGUOUS` (no edge); none `MAPPING_PATH_MISSING` with the
  plan-`.md` warning predicate.
- Comment-form `backstitch: noqa` attaches to the next tree-sitter statement span
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

`backstitch/defaults.toml` is the lowest-precedence configuration layer and the
behavioral source of truth for built-in profile defaults, default excludes, the
diagnostic registry, and diagnostic policy. `pyproject.toml` carries the
committed repository overlay. Choices and their reasons:

- `extend_exclude` (never bare `exclude`): the packaged defaults already exclude
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
- `tests` is also explicit in `test_roots`. The pairing is intentional:
  production-only `--code-root backstitch` remains a valid partial scan and
  reports the three dogfood declarations as BSI001, while `--test-root tests`
  retains the committed code roots and restores their binds.
- The repository declares exactly three initial required invariants:
  byte-stable resolver JSON, ambiguity never guessed into an edge, and no
  `llm` import from deterministic commands. Each binds to the existing test
  that directly enforces it; the default self-scan requires three binds and
  zero invariant findings.
- `meta_spec_globs` classifies the DOM operating-model spec as process
  documentation: parsed, citable, mapping not required.
- The only lint suppressions are on `tests/*` for citation-inventory codes
  (`CODE_REF_UNMAPPED_FROM_SPEC`, `SPEC_MAPPING_RECIPROCAL_MISSING`): test
  files cite the sections they exercise without being implementation
  owners. Both are recoverable via `--show-suppressions` and asserted
  auditable by `tests/test_backstitch_corpus_traceability.py`.
- `diagnostics.levels` appends across config layers. Repository rules can
  override defaults with a later `select = ["*"]` rule, and
  `config show` exposes both the config layer list and the resolved
  per-diagnostic policy so this behavior is inspectable.

The self-corpus gate requires exit 0 with zero errors AND zero warnings on
the default invocation; the dogfood-delta test proves the config is live by
diffing against `--no-config`.

## Verification Map

- Unit/contract: `tests/test_*.py` (parsers, resolver, ladder, diagnostics,
  settings, exclusions, target roots, analysis pipeline)
- Diagnostic registry/policy: `tests/test_diagnostics.py` — registry shape,
  short-code uniqueness, selector matching, ordered policy, `off`, and
  reserved-code rejection
- Contract coverage: `tests/test_issue_code_coverage.py` and suppression
  hygiene tests — every implemented [SC-11]/[SC-15] diagnostic has a firing
  proof, and context-dependent severities fire both ways
- Review remediation regressions: `tests/test_review_remediation.py` — one
  test per reproduced independent-review finding (heading markers, live
  config keys, noqa hygiene, marker override, fence length)
- Acceptance: `tests/acceptance/` — the [SC-10] black-box probes, including
  invariant diagnostics, role roots, packet unions, hashes, dogfood, and
  new/legacy artifact self-acceptance
- Self-corpus: `tests/test_backstitch_corpus_traceability.py`
- Live LLM: `tests/live/test_live_llm.py` — enabled by repository pytest config
  for local runs; real provider or local OpenAI-compatible endpoint (see below)

## Live LLM Verification

The hermetic suite fakes the model boundary; it proves prompt construction,
parsing, and aggregation, but never that the real `llm` adapter and a real
provider or OpenAI-compatible endpoint actually work. `tests/live/test_live_llm.py`
closes that gap under the [SC-7] pytest policy gate. `pyproject.toml` enables
the gate for ordinary local runs; `tests/conftest.py` applies a collection-time
skip when automation overrides `run_live_llm=false`. The environment opt-in
remains available for dedicated lanes whose ini policy is off.

Boundary and rationale:

- **Real path only.** It drives the CLI (`packets` → `analyze` → `check` →
  `summarize-analysis`) as subprocesses through the production `default_adapter`.
  Nothing inside the live test is mocked; the only allowed skip is the explicit
  pytest policy being disabled.
- **Bounded dogfood corpus.** The cloud lane keeps the smallest matching
  section packet from `docs/specs/02-backstitch-core.md` owned by a semantic-
  analysis module. The local lane instead generates `--kind invariant` and
  requires the ordered IDs `invariant::INV.RES.1` and `invariant::INV.RES.2`.
  Each must occur once, have no packet warnings, and contain bounded target and
  binding-test snippets. There is no smallest-packet fallback: corpus drift
  fails before model listing or completion traffic.
- **Structure, not wording.** Assertions are on the result contract: one row per
  packet, every row passes `validate_analysis_row`, and
  `load_analysis_results` reports zero errors. Cloud-provider runs also assert
  no row carries an `error` field. `analysis_llm._error_record` deliberately
  emits a schema-valid `ambiguous` row for a contained failure, and both
  `analyze` (partial failure) and `summarize-analysis` (bad rows rendered as
  advisory text) exit `0`, so exit codes prove command path and artifact health,
  not model success.
- **Local endpoint proof.** With `BACKSTITCH_LIVE_LLM_KIND=local`, the test writes
  a temporary `llm` `extra-openai-models.yaml` entry pointing
  `backstitch-local` at a loopback counting proxy. The proxy forwards to the
  configured upstream Ollama endpoint. For every completion it replaces
  endpoint defaults with request-level `temperature = 0` and seed `42`; it
  records the exact forwarded bodies only during `analyze`. The test validates
  the curated corpus before provider activity, verifies `/v1/models`, requires
  a subprocess transport probe through `default_adapter`, at least one non-
  error row, and analyze bodies showing the packet IDs, served model,
  temperature, and seed. Invalid completion JSON is rejected locally with HTTP
  400 and is never forwarded unseeded. The CI
  workflow uses `backstitch-local-model:latest` because Ollama exposes created
  models with an explicit tag on `/v1/models`. The committed manual-workflow
  base model is `llama3.2:3b`, bounded by the workflow Modelfile (`num_ctx
  4096`, `num_predict 1024`, stored `temperature 0`). The 2026-07-06 8/8
  constrained-decoding result remains a historical observation, but not valid
  evidence of effective temperature zero: the request omitted temperature and
  pinned Ollama 0.31.1 applied `1.0`. The stabilized request-level controls and
  curated invariant corpus passed the real local gate on 2026-07-10. The
  earlier 2 CPU / 8 GB timeouts were an artifact of that simulation, and
  `qwen2.5:0.5b` was abandoned after producing total invalid rows. Individual
  per-packet `error` rows are tolerated only for
  non-strict local runs because content-level rejects (invalid evidence
  paths or fields) remain possible from small models even when syntax is
  decoder-enforced; `BACKSTITCH_LIVE_LLM_STRICT=1` restores the cloud-style
  no-error-row assertion.
- **Advisory findings stay advisory.** Semantic classification never fails the
  deterministic checker. Current hermetic CI explicitly disables the local
  pytest default. `.github/workflows/ci.yml` retains a cloud provider job behind
  `BACKSTITCH_CI_LIVE_LLM=1`, restricted to main-branch push or manual-main
  events with read-only repository permissions, then injects `OPENAI_API_KEY`
  from repository secrets. `.github/workflows/local-llm.yml` is a separate
  Ollama workflow on `workflow_dispatch` and pushes to `main`; the release gate
  requires it green by commit SHA. It remains outside the `CI` workflow and
  outside fork pull requests.

Local usage and the cost/flake tradeoff are documented in `README.md`.

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
