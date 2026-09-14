# Semantic Response And CLI Portability Plan (2026-09-14)

**Status:** active; independently reviewed, implementation not started

**Class:** 5, spec-changing. Two production contracts change: analyzer
generation and cross-runtime Wilson serialization. One test-only slice removes
accidental machinery while retaining coverage of existing CLI paths.

**Plan type:** minimal implementation with atomic spec revision and three
targeted commits.

## Goal

Restore the release candidate with three bounded changes:

1. delete or relax test machinery that asserts more than the CLI contract;
2. make semantic-evaluation reports portable across supported Python runtimes;
3. stop the analyzer's provider schema from inviting responses that its own
   normalizer must reject.

Everything else stays with its existing owner. Release qualification remains
in the 0.4.0 release plan. The zero-job semantic workflows remain diagnosis
work until their validation error is known.

## Source Documents And Evidence

- `docs/program-theory.md`
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-11], [DOM-15]
- `docs/specs/02-backstitch-core.md` [SC-7], [SC-10]
- `docs/specs/05-backstitch-invariants.md` [INV-5]
- `docs/specs/06-semantic-gates.md` [SEM-3], [SEM-5], [SEM-8]
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/implementation/07-deterministic-semantic-gate.md`
- `docs/plans/2026-08-23-gpt-5-6-luna-responses-plan.md`
- `docs/plans/2026-09-14-v0-4-0-release-readiness-plan.md`

Baseline: `53e9809b6d91095431ac0d5a2f6dc15340ccda98`.

Observed evidence:

- Hosted `local-llm` run `34889596724` reached the real `backstitch analyze`
  path. The schema admitted invariant `weak_binding` without `requirement`
  evidence; [SEM-5] normalization correctly rejected it.
- CI run `34889596754` exposed three test assumptions rather than production
  failures: Linux PTY closure returned `EIO`; two separately timed historical
  runs differed only in `elapsed_milliseconds`; and Python 3.14 selected a
  different fail-closed symlink diagnostic.
- The same run exposed a production portability defect. Python 3.11 computes
  one Wilson lower bound as `0.2065493143772375`, while the committed artifact
  contains `0.20654931437723753`. Exact canonical comparison means one
  supported runtime can reject another runtime's report.
- `semantic-refresh` and `semantic-pr-report` still produce zero-job workflow
  failures. Their precise GitHub validation error has not been obtained. No
  YAML change is authorized by this plan.

## CLI Reachability

Every retained change protects an existing command path:

| Change | Existing CLI path | Stable contract |
|---|---|---|
| Delete PTY probe | `backstitch analyze --repo-root ...` | deterministic pre-provider recapture rejects changed source with zero provider calls |
| Historical replay assertion | `backstitch analyze --packets ... --packet-report ...` | exit and semantic status are stable; operational elapsed time is not |
| Symlink assertion | `backstitch analyze` and `backstitch cache cleanup-lock` | corrupt cache fails closed before provider work; internal prose is not an interface |
| Wilson canonicalization | `backstitch eval`, then `backstitch analyze` consuming the qualification report | any supported runtime accepts the same valid report and applies the same threshold decision |
| Analyzer schema | `backstitch analyze` and `backstitch eval` through the shared provider adapter | generation schema and local normalization agree on classification-required evidence |

No retained change creates a new interface. The CLI and its typed application
modules remain the test surface.

## Current Owners

- `semantic_application.py` performs the pre-provider recapture and is already
  covered deterministically, including zero provider work after mutation.
- `analysis_llm.py::_semantic_response_schema()` owns the packet-specific
  generation schema. `semantic_evidence.py::required_evidence_roles()` owns
  the classification-to-role matrix. `normalize_model_result()` remains the
  trust boundary.
- `semantic_eval_reports.py` is the single producer and authoritative
  recomputation owner for Wilson bounds.
- Canonical semantic result, cache, report, policy, and verifier formats are
  downstream interfaces and do not need to change.

## Invariants And Constraints

- Correctness comes from the local normalizer and authoritative report
  validator. Provider schema enforcement remains untrusted.
- One current analyzer schema and one normalization path. No old/new schema,
  compatibility reader, provider-specific projection, model capability
  registry, or model-name table.
- Derive schema role requirements from `required_evidence_roles()`; do not
  duplicate the matrix in another production owner.
- Preserve the existing six-field model wire shape if supported schema
  vocabulary can express the role invariant. Change the wire shape only when
  a focused adapter probe proves that necessary.
- Do not require every available region as evidence. Availability is not a
  claim that the model relied on it.
- Unknown fields, invalid classifications, forged or duplicate coordinates,
  and missing required roles still fail locally. Do not weaken [SEM-5], retry
  with a looser schema, or repair model JSON.
- Wilson portability gets one explicit canonical operation, not a general
  numeric-normalization module or a second inverse-normal implementation.
- Tests assert exit class, structured code, stable fields, and durable output.
  They do not pin TTY mechanics, timing, private prose, Python's last float
  bit, workflow choreography, or review freshness.
- No new dependency or abstraction used by one call site.
- Weft remains decoupled. No Weft content or tests enter this repository.

## Rollback

The three commits are independent. The test simplification can be reverted
without product effect. Wilson canonicalization and the analyzer contract each
land atomically with their spec and tests and can be reverted before release.
There is no persistent-data migration or compatibility period. No release tag
or publication occurs under this plan.

## Slice Plan

### Slice 1: Remove assertions that are not CLI contracts

Make only these test changes:

1. Delete
   `test_installed_analysis_rejects_mutation_after_preparation` from
   `tests/acceptance/test_probe_full_dogfood.py` and remove it from the
   acceptance manifest. Do not add a PTY helper or replacement synchronization
   seam. Existing deterministic application tests already prove pre-provider
   recapture and zero provider calls. Keep the installed CLI
   mutation-during-provider test, which proves no stale publication through
   the external command.
2. In the historical replay test, remove cross-run byte equality. Keep the
   CLI exit-code assertion and parsed
   `semantic_status == "historical_replay"`. Add no comparison helper.
3. In the symlink-loop cache test, require `CacheProtocolError` from cleanup
   without matching its private message. Keep the analysis-side
   `corrupt_cache` code and zero-provider-call assertions. Add no list of
   accepted prose variants.

This slice changes no production code or spec. Its purpose is subtraction:
the suite still covers the CLI behavior while ceasing to preserve its test
mechanism and implementation wording.

**Proof:** the focused tests pass; the remaining mutation tests still fail if
pre-provider recapture or post-provider currentness is removed; the symlink
test still fails if provider work begins or cleanup stops failing closed.

**Commit:** `test: remove accidental semantic CLI constraints`

### Slice 2: Canonicalize Wilson bounds at their single owner

Promote [SEM-8] atomically. Keep its existing Wilson formula, then apply
`round(value, 15)` to lower and upper bounds before serialization,
authoritative recomputation comparison, and qualification threshold
comparison. Fifteen decimal places are chosen narrowly because they collapse
the observed one-last-bit difference while retaining substantially more
precision than any configured qualification threshold. Ordinary exact
proportions remain unchanged.

Implement the rule only in `backstitch/semantic_eval_reports.py`; callers use
that owner. In `tests/test_semantic_eval_reports_v3.py`, keep fixed expected
vectors independent of production code. Pin the canonical lower bound
`0.206549314377238` and upper bound `0.793450685622762`; prove the neighboring
pre-canonical lower values map to the same result. Retain tamper tests so the
next distinct canonical value and changed source counts are rejected.

Do not add a general float wrapper, decimal type, tolerance, second metric
implementation, or cross-version fixture generator.

**Proof:** the fixed vectors pass in the supported Python 3.11 through 3.14
matrix. A report produced through `backstitch eval` is accepted through the
qualification-report path used by `backstitch analyze`, and threshold
decisions use the serialized canonical value.

**Commit:** `fix(eval): canonicalize Wilson bounds`

### Slice 3: Align analyzer generation with required evidence

Promote [INV-5], [SEM-3], and [SEM-5] atomically. Start with a focused,
non-landing probe against the actual OpenAI Responses and hosted Ollama
adapters to answer one question: what is the least schema vocabulary both
accept that can make each classification's required roles mandatory?

Selection rule:

1. Prefer the current six top-level fields if one closed object can express
   the classification/evidence relation with vocabulary both adapters accept.
2. If it cannot, use one closed nested discriminated value that binds a
   classification branch to role-keyed evidence arrays. Require only what is
   needed to make [SEM-5]'s required role set structural. Do not add
   `uniqueItems` or mandatory empty arrays merely because JSON Schema can;
   duplicate rejection remains local-normalizer work.
3. If neither shape is accepted, stop and revise this plan from observed
   adapter errors. Do not add per-provider schemas, runtime introspection, or
   a fallback to the weaker schema.

Whichever single shape wins, build its branches from the packet's exact
regions and `required_evidence_roles()`. Omit classifications whose required
roles do not exist in that packet. The local normalizer still reconstructs
canonical evidence from packet bytes and repeats every trust check.

Update only the selected wire description in [SEM-3]/[SEM-5], [INV-5] where
it states analyzer output, the three analyzer prompts, and the implementation
mapping:

- `backstitch/prompts/backstitch_style_analysis.md`
- `backstitch/prompts/invariant_binding_analysis.md`
- `backstitch/prompts/suppression_analysis.md`
- `backstitch/analysis_llm.py`
- `backstitch/semantic_evidence.py`

If the wire shape changes, advance the section/invariant prompt versions from
3 to 4, the suppression prompt from 1 to 2, and the provider adapter identity
from 4 to 5. If the six-field shape is preserved, prompt bytes and identity
change only if their model-visible contract actually changes.

Tests in `tests/test_analysis_llm.py` and
`tests/test_semantic_evidence.py` carry one explicit, spec-derived [SEM-5]
expected-role table as their independent oracle. They check both
`required_evidence_roles()` and the generated schema against it, then prove:
feasible branches admit required roles; impossible branches are absent;
schema-accepted representative output normalizes; and missing roles, forged
coordinates, duplicates, and unknown keys remain rejected.
`tests/live/test_live_llm.py` captures the exact schema actually sent. Tests
must not encode provider model names or a capability table.

**Proof:** focused unit tests, protected OpenAI qualification, and the hosted
local-model test all exercise the same schema through `backstitch analyze` or
`backstitch eval`. Canonical stored result bytes and historical replay remain
unchanged.

**Commit:** `fix(semantic): align generation with evidence requirements`

## Verification And Existing Owners

After each slice, run its focused tests. At plan completion run:

```bash
uv run pytest tests -q -n auto --dist loadgroup -m "not live_llm and not benchmark"
uv run pytest tests -q -n 0 -m benchmark
uv run ruff format --check backstitch bin .github/scripts tests
uv run --frozen --no-sync ruff check . bin/check-doc-paths bin/check-dom15-fixtures bin/coalesce-check
uv run mypy backstitch bin/release.py tests --config-file pyproject.toml
python bin/check-doc-paths
python bin/check-dom15-fixtures
uv run backstitch check --repo-root .
```

The protected OpenAI and hosted local-model checks are Slice 3 acceptance
evidence. Exact-SHA full CI and release continuation remain recorded only in
`docs/plans/2026-09-14-v0-4-0-release-readiness-plan.md`; do not create a
second qualification ledger or a qualification-only commit here.

## Explicitly Deferred Or Out Of Scope

- The zero-job `semantic-refresh` and `semantic-pr-report` workflows: obtain a
  concrete GitHub/actionlint validation error first, then plan the proven fix
  separately. The present `runner.temp` theory is not implementation authority.
- release tagging, PyPI publication, immutable release creation, or timeout
  changes
- native Windows runtime support; the existing CI matrix supplies only the
  supported Python portability evidence available here
- verifier response redesign or canonical result/cache/report migration
- model capability discovery, version-aware projection, compatibility paths,
  retry policy, model changes, or token-cap changes
- new test hooks, PTY wrappers, workflow-lint infrastructure, numeric
  frameworks, or cleanup of unrelated test style

## Failure Modes And Stop Rules

| Failure | Required action |
|---|---|
| Removing the PTY test leaves the pre-provider mutation rule without deterministic zero-call coverage | Restore contract coverage at the existing application interface, not with process-control machinery |
| Wilson values or threshold results still differ across supported Python jobs | Stop; do not add tolerance until the exact remaining computation is identified |
| The schema still admits a classification without its required roles | Block Slice 3 even if a sampled model happens to comply |
| A provider rejects the proposed schema | Keep one schema; revise from the exact rejection instead of branching by provider |
| Canonical stored result or verifier shape changes | Stop unless a demonstrated necessity first revises this plan and spec |
| Any full gate or exact-SHA release gate fails | Keep release readiness blocked; diagnose under the owning plan |

## Independent Review

Two independent read-only reviews challenged every slice for CLI reachability
and YAGNI. Their findings caused this rewrite: delete the PTY probe instead of
supporting it; treat Wilson as a real `eval`/`analyze` portability bug; remove
the unproven workflow fix and duplicate release slice; avoid preselecting a
larger model wire shape; and reduce replay/symlink work to direct assertions.

Plan review result after incorporation: PASS. Before landing Slice 3 and again
before release, review the exact implementation diff for schema duplication,
new interfaces, and tests that preserve mechanisms rather than contracts.

## Deviation And Execution Log

| Slice | Planned behavior | Observed behavior | Rationale or follow-up |
|---|---|---|---|

Do not mark this plan complete until all three commits exist, local gates pass,
the provider-backed Slice 3 evidence is recorded, and independent
implementation review has no unanswered blocker.
