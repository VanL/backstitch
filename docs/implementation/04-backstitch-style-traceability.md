# Backstitch Style Traceability — Implementation

Spec: docs/specs/02-backstitch-core.md [SC-1]–[SC-15]
Spec: docs/specs/03-backstitch-configuration.md [CFG-1]–[CFG-10]
Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-1]–[EXC-10]
Spec: docs/specs/05-backstitch-invariants.md [INV-1]–[INV-10]
Plan: docs/plans/2026-07-08-configurable-diagnostics-plan.md
Plan: docs/plans/2026-07-09-backstitch-invariant-traceability-plan.md
Plan: docs/plans/2026-07-02-backstitch-four-way-reconciliation-plan.md
Plan: docs/plans/2026-07-07-tree-sitter-code-parser-plan.md
Plan: docs/plans/2026-07-28-configured-default-command-plan.md
Plan: docs/plans/2026-07-29-architecture-quality-remediation-plan.md
Plan: docs/plans/2026-08-23-gpt-5-6-luna-responses-plan.md

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
  derived from the accepted `RepositorySnapshot` by
  `scan_snapshot_with_artifacts` and passed in, so graph policy is testable
  without IO and reruns are byte-stable.
- **Application seams own workflows, not presentation.**
  `check_application.py` owns capture, report construction, warning collection,
  and the effective check classification. `packet_application.py` owns runtime
  construction, deterministic-failure precedence, packet/report assembly, and
  ordered artifact publication. `coverage_application.py` owns accepted
  repository state, historical projection, ratchet policy, report construction,
  gate classification, and durable publication. `semantic_application.py`
  owns current/historical input validation, repository readiness and
  packetization, semantic-run invocation, currentness recapture, and ordered
  current artifact publication. These seams accept immutable resolved inputs
  and return typed immutable outcomes. `cli.py` retains argument parsing,
  provider-factory construction, suppression display, rendering, output
  messages, and process-exit mapping.
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
- **Packets and results are discriminated unions with two distinct hashes.**
  New section and invariant artifacts carry `kind`; only the exact legacy
  shapes named by the compatibility contract are normalized. Invariant
  `content_hash` keeps its original bounded statement/target/test comparison
  meaning and is not a persistence key. Universal `packet_hash` covers the
  complete kind-specific model-visible projection. It enters the larger
  `analysis_key` with prompt, provider, request, contract, and search-epoch
  identity; that analysis key owns immutable cache addressing ([INV-5],
  [SC-6], [SEM-3]).
- **Binding quality stays at the packet-local evidence boundary.** `analyze`
  validates every cited path and line against shown target/test snippets,
  reconstructs exact excerpts and hashes, injects trusted packet and inference
  metadata, and converts evidence-deficient invariant `ok` results to
  `weak_binding`. `summarize-analysis` has no packet snippets, so it validates
  row identity and shape but deliberately does not re-prove locality. The
  unified runner, not the presentation command, owns cache, policy,
  completeness, and exit authority ([INV-5], [SC-7], [SEM-5], [SEM-7]).
- **The llm quarantine.** `check` and `packets` are structurally incapable
  of importing `llm`: the import lives inside
  `analysis_llm._resolved_model_adapter_parts`, reached only through the
  shipping `default_provider_adapter` factory imported lazily by `analyze`.
  A subprocess test asserts
  `llm ∉ sys.modules` for deterministic commands ([SC-8]).
- **Bare dispatch is config selection with selected-command argument parsing.**
  The packaged
  `default_command = false` keeps an unconfigured bare invocation inert.
  Repository `"check"` or `"analyze"` values are normalized by the sole
  settings resolver, after file merge and before command-scoped environment
  values. Before that one resolution, the CLI parses arguments for the two
  closed candidates and passes their dedicated overrides keyed by owner. The
  resolver applies only the selected command's overrides. A leading path is
  `--repo-root` shorthand; otherwise current-repository input is implicit
  unless the invocation supplies an input. The existing handler receives the
  selected arguments and the same immutable settings snapshot. The CLI does
  not recurse through `main`, start a subprocess, accept arguments in the
  config value, or resolve config twice
  ([SC-5], [CFG-5.1], [INV.PERF.1]).
- **Constrained decoding is part of the resolved request.**
  `default_provider_adapter` requires the configured request options, verifies
  schema support before dispatch, and sends the packet-specific closed result
  schema. Unsupported request modes fail before a provider call; a rejected
  request is never retried with weaker controls
  (`docs/plans/2026-07-06-analyze-json-mode-plan.md`).
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
  Structured rules and declaration-bearing inline rules resolve through the
  same canonical decision path. When required-declaration mode is enabled, a
  missing, malformed, duplicate, unresolved, or unused declaration fails
  closed and cannot hide the original finding. Audit rows carry the exact
  declaration and decoded nonblank rationale.
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
  result and model-output validation stay with `analysis_results.py`,
  `semantic_evidence.py`, and the immutable cache execution path.
  `analysis_llm.py` owns only provider request construction and wire
  adaptation. The counterweight is [SC-13.5]: everything the tool emits must
  pass its own validation (acceptance probe 13), so tightening can never
  orphan real output.
- **Evidence locality is enforced where the packets are.** `analyze` holds
  the packets, so it is the boundary that rejects model evidence outside
  the packet's shown paths and line ranges ([SC-7]).
  `summarize-analysis` never sees packets: it validates result-row schema
  (classification, confidence in [0, 1], non-blank evidence paths) and
  rejects packet IDs no audited report packet could have produced
  (edge-bearing sections, bound invariants, or used suppression declarations),
  and trusts that the rows came from `analyze`. Suppression-result summaries
  therefore require a deterministic report produced with
  `--show-suppressions`.
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

- Filesystem discovery and Git-blob history are source adapters into
  `settings._assemble_settings`. The common finalizer owns model selection,
  typed parsing, provenance projection, and final profile-root containment.
  `config.normalize_profile_root` compares roots after pure lexical
  normalization, so historical validation never follows the current
  checkout's symlinks. Blob-side operational output, cache, qualification, and
  target paths are also normalized lexically because they are not historical
  gate authority; the current filesystem adapter retains physical
  canonicalization for those addresses. `tests/test_config_parity.py` pins the
  non-operational parity and rejection matrix.
- `default_command = "analyze"` makes the repository's bare invocation enter
  current-repository semantic analysis. That is an intentional local
  credential, cache, provider, and bounded-cost choice. The hermetic
  self-corpus gate therefore remains explicit `backstitch check`; config tests
  inspect the committed selection without triggering provider work. The
  packaged `false` remains the rollback and inheritance-disable value, and
  secret-bearing workflows still invoke `analyze` and trusted config
  explicitly.
- The analyzer identity is the Model Monster service PURL
  `pkg:service/openai.com/gpt-5.6-luna`; `adapter_model_id = "gpt-5.6-luna"`
  is only the raw `llm` transport name. The committed request uses the OpenAI
  Responses path with logical `max_tokens = 16384` and
  `reasoning_effort = "max"`; `llm` owns their wire translation to
  `max_output_tokens` and `reasoning.effort`. Temperature and seed are absent.
  Optional request-field absence is frozen before adapter construction, enters
  neither the request projection nor the wire body, and means accepting the
  provider default. The repository uses `read-write` with evidence-stable
  reuse: unchanged evidence keeps the immutable first-writer result even when
  model selection or time changes, while changed evidence calls the currently
  selected model. Review locks are acquired for the complete run in lexical
  order and remain held through qualification and budget preflight.
- Release qualification runs the exact current Luna and protected GPT-5.5
  selections as a bounded release-candidate event. It writes no dated
  capability receipt. Compatible, incompatible, unavailable, and local
  preflight outcomes are process evidence only; time and repository inactivity
  do not alter semantic cache identity or invalidate an evidence-stable result.
- `extend_exclude` (never bare `exclude`): the packaged defaults already exclude
  `.worktrees`; replacing them would scan four archived bake-off
  implementations into the corpus.
- Exclusion has exactly one authority: `scan_exclusions.is_excluded`
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
- The repository opts into `lint.require_suppression_declarations = true`.
  Three config rules govern DOM process metadata, the exact deferred
  `EVC-8.6` section, and test citation-inventory noise. Inline `meta` markers
  govern the exact EVC process, verification-policy, and documentation-policy
  sections. All six declarations live under [EXC-10]. The deferred EVC rule
  is section-bounded, and the test rule retains only
  `CODE_REF_UNMAPPED_FROM_SPEC` and `SPEC_MAPPING_RECIPROCAL_MISSING`.
- `tests/test_backstitch_corpus_traceability.py` pins each declaration
  population and allowed path/code/section boundary. The current audit has
  263 records: 235 test-citation, 15 DOM-meta, 7 verification-meta,
  2 documentation-meta, 2 EVC-process, and 2 deferred-MCP findings. The
  deferred pair includes the one explicit `EVC-8.6` obligation skip. Every
  record has a valid declaration and nonblank rationale.
- `diagnostics.levels` appends across config layers. Repository rules can
  override defaults with a later `select = ["*"]` rule, and
  `config show` exposes both the config layer list and the resolved
  per-diagnostic policy so this behavior is inspectable.

The hermetic self-corpus gate is explicit `backstitch check --repo-root .` and
requires exit 0 with zero errors and zero warnings. The dogfood-delta test
separately proves the committed config is live by diffing against
`--no-config`; provider-capable bare analyze is not a hermetic gate.

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
  `summarize-analysis`) as subprocesses through the production
  `default_provider_adapter`. Nothing inside the live test is mocked; the only
  allowed skip is the explicit pytest policy being disabled.
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
  no row carries an `error` field. Provider or normalization failures remain
  typed semantic problems and never become trusted result rows. Exit codes
  therefore prove the command path and artifact health, not model wording.
- **Local endpoint proof.** With `BACKSTITCH_LIVE_LLM_KIND=local`, the test writes
  a temporary `llm` `extra-openai-models.yaml` entry pointing
  `backstitch-local` at a loopback counting proxy. The proxy forwards to the
  configured upstream Ollama endpoint without changing the request or response.
  Production configuration supplies `temperature = 0`, seed `42`, required
  schema output, and the 1024-token output bound. The proxy records exact
  forwarded bodies only during `analyze`, validates the packet-bound production
  schema, and rejects SDK retries or adapter compatibility fallback before a
  second upstream request. The ordinary result normalizer remains the sole
  validator; the proxy never injects controls, replaces response format, or
  repairs model output.
  The test validates the curated corpus before provider activity, verifies
  `/v1/models`, requires a subprocess transport probe through
  `default_provider_adapter`, at least one non-error row, and exact analyze bodies
  showing the packet IDs, served model, temperature, seed, nonstream mode, and
  packet-bounded schema. Invalid completion JSON, malformed packet prompts,
  malformed upstream envelopes, and duplicate packet attempts fail locally
  without additional upstream traffic. The CI
  workflow uses `backstitch-local-model:latest` because Ollama exposes created
  models with an explicit tag on `/v1/models`. The committed manual-workflow
  base model is `llama3.2:3b`, bounded by the workflow Modelfile (`num_ctx
  4096`, `num_predict 1024`, stored `temperature 0`). The 2026-07-06 8/8
  constrained-decoding result remains a historical observation, but not valid
  evidence of effective temperature zero: the request omitted temperature and
  pinned Ollama 0.31.1 applied `1.0`. The stabilized request-level controls,
  curated invariant corpus, and schema bridge passed the real local gate on
  2026-07-10. The
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
