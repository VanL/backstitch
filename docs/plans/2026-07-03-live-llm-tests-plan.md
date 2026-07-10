# Live LLM Tests

Status: implemented; local/CI gate policy revised by
`docs/plans/2026-07-10-local-default-live-llm-tests-plan.md`.
Plan type: implementation with spec revision
Risk level: boundary-crossing; external provider, network, CI secret handling

## Goal

Add an optional live LLM test path that exercises Backstitch's real packet,
`analyze`, result-validation, and summary flow against this repository's own
specs and code. The default test suite remains hermetic and requires no network
or provider credentials. Local developers can opt in with an existing `llm`
key store or provider environment variable; GitHub Actions can opt in by
setting a repository secret.

## Requested Outcomes

- Full testing: prove the real `llm` adapter and provider path works, not only
  the injected fake adapter.
- Dogfooding: run live semantic analysis over packets generated from this
  repository's own specs and implementation files.
- CI enablement: create a path where adding the appropriate repository secret
  makes GitHub Actions run live LLM tests without changing code.
- Preserve the current no-network default test contract.
- Follow the repository's spec-changing workflow: plan, review, spec-promotion
  slice, then implementation against the promoted spec.

## Source Documents

- `docs/specs/02-backstitch-core.md` [SC-5], [SC-6], [SC-7], [SC-10]
- `docs/specs/03-backstitch-configuration.md` [CFG-5], [CFG-9]
- `docs/implementation/04-backstitch-style-traceability.md`
- `docs/implementation/02-repository-map.md`
- `docs/agent-context/runbooks/writing-plans.md` §4b-§4d
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- GitHub Actions docs:
  - <https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets>
  - <https://docs.github.com/en/actions/reference/workflows-and-actions/contexts>
- OpenAI model docs. Re-check during implementation because model availability
  and canonical docs URLs change faster than repository code:
  - <https://platform.openai.com/docs/models>
  - <https://platform.openai.com/docs/models/gpt-5.4-mini>

## Spec Baseline

- `5672102` (repo HEAD at plan authoring) for
  `docs/specs/02-backstitch-core.md` and
  `docs/specs/03-backstitch-configuration.md`.
- Worktree note: the repository already had unrelated modified files under
  `docs/agent-context/` and an untracked
  `docs/plans/2026-07-03-input-validation-invariants-plan.md`. The governing
  spec files were clean at plan authoring.
- Promotion baseline identifier: `2ed88ea` (spec-promotion slice: [SC-7] and
  [CFG-9] in-file edits + Related Plans). Model re-check at promotion:
  `uv run llm models list` confirms `gpt-5.4-mini` is registered and is the
  most recent GPT-5-series mini (5.4 > 5.2 > 5.1 > 5-mini).

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [SC-7], [SC-10] | Default local and CI suites stay hermetic; environment opt-in only | Repository pytest config enables local live tests; current CI explicitly disables them, with future CI opt-in behind a repository variable | User correction on 2026-07-10: local completion must exercise the live lane; current CI disablement is not permanent | Promoted by `2026-07-10-local-default-live-llm-tests-plan.md` |

## Context and Key Files

- `backstitch/analysis_llm.py`: owns `default_adapter`, the only production
  path that imports `llm` and calls a real model. Existing unit tests inject a
  fake adapter around `analyze_packets`.
- `backstitch/cli.py`: `_cmd_analyze` loads packets, resolves model selection,
  builds the real adapter, writes JSONL, and returns the [SC-5] exit code.
- `backstitch/analysis_packets.py`: generates the bounded packets that form
  the semantic boundary. The live test must use this production path.
- `backstitch/analysis_results.py`: validates analysis rows and powers
  `summarize-analysis`. The live path should prove model output reaches this
  consumer.
- `tests/test_analysis_llm.py`: current hermetic semantic tests. Do not turn
  these into live tests.
- `tests/acceptance/test_probe_analysis.py`: current [SC-10] probes using the
  model boundary fake. These remain mandatory and hermetic.
- `pyproject.toml`: pytest markers live here under strict marker checking.
  Add a `live_llm` marker.
- `tests/live/test_live_llm.py`: new live test module. Create this directory
  rather than mixing optional network tests into the existing hermetic files.
- `.github/workflows/ci.yml`: currently absent in this checkout. The
  implementation should create a workflow with a normal no-secret job and a
  live-LLM job gated by event and secret availability.
- `README.md` or a short implementation doc section: document the local opt-in
  command and the GitHub Actions secret path.

Comprehension checks before editing:

1. Why is `default_adapter` the only acceptable place to touch `llm`, and why
   must `check` and `packets` remain unable to import or call it?
2. Which validation does `analyze` perform that `summarize-analysis` cannot
   perform because it no longer has the original packet?
3. In GitHub Actions, where are `secrets` available, and why should the
   workflow not try to decide live-job execution from a job-level
   `secrets.*` conditional?

## Invariants and Constraints

- Default local and CI tests must stay no-network. `uv run pytest tests -q`
  must pass without provider credentials and without contacting a model.
- The live LLM test requires explicit opt-in: `BACKSTITCH_LIVE_LLM=1`.
  Without that variable, the live test module must skip, not fail.
- When opt-in is set, the model resolves as `LLM_MODEL` if set, otherwise the
  named live default `DEFAULT_BACKSTITCH_LIVE_LLM_MODEL`. That default must be
  the most recent available GPT-5-series mini model. At this plan revision,
  the intended default is `gpt-5.4-mini`. Implementation may duplicate that
  literal in the test module and workflow because they run in different
  contexts; the two copies must be treated as one canonical value and checked
  together during the model-doc re-check. If the chosen model is not registered
  with `llm`, fail with a clear diagnostic. Silent fallback to a fake adapter
  is not allowed.
- Missing provider credentials after live opt-in is a failure in the local live
  test and a job-level skip only in CI when the repository secret is absent.
- Live tests must use the real CLI path: `backstitch packets`, then
  `backstitch analyze`, then `backstitch summarize-analysis`. Do not call
  `analyze_packets` directly in the live proof.
- The model may only see packets generated by Backstitch. Do not give it
  independent repository access.
- Keep the packet count small and deterministic. The live test is a smoke and
  contract test, not an exhaustive semantic review of the whole repository.
  The default live subset is one packet; increasing to at most five packets is
  a deliberate future hardening step after the one-packet path has stable run
  history.
- The test should assert structured contracts and command behavior, not exact
  wording or exact classification. Model rationale text is not API.
- A row with an `error` field is a live-test failure. A valid `ambiguous`
  classification without an error field may be legitimate model judgment.
- The live test intentionally fails on malformed provider output. Treat those
  failures as useful signal while the job is non-required; do not make the live
  job a required branch-protection check until the selected packet and model
  have enough run history to distinguish product breakage from provider/model
  variability.
- Semantic findings remain advisory. Adding live CI must not make
  `confirmed_mismatch` or `probable_mismatch` fail the job unless a separate
  future policy explicitly changes [SC-7].
- No new Python package dependencies. `llm` is already required.
- No provider-specific code in Backstitch runtime modules. Provider setup
  belongs in environment, `llm`, docs, tests, or CI.
- Secrets must never be printed. Do not pass API keys as command-line
  arguments. Prefer provider environment variables in CI; for OpenAI models,
  `llm` supports `OPENAI_API_KEY` and the `openai` key alias.
- Do not upload live analysis artifacts by default. They may contain source
  snippets and model output, even if they should not contain secrets.
- The CI live job must not run on untrusted pull requests from forks. GitHub
  does not pass normal repository secrets to forked PR runs, and attempting to
  force this creates the wrong security posture.

## Hidden Couplings

- `analyze` discovers config relative to the packets file. A live test that
  writes packets to a temp directory should pass `--no-config` and an explicit
  `--model`, or deliberately place config where discovery is expected. Prefer
  `--no-config` plus explicit model for this test.
- `LLM_MODEL` is already product configuration for model selection. The live
  harness can use it, but it should not change `resolve_model_name`.
- Local `llm` may use a stored key in the user's `LLM_USER_PATH`. CI starts
  clean and must use the provider's secret-backed env var.
- Current [SC-7] wording forbids external-model tests. The spec must be
  promoted before code cites or implements the new optional live-test path.
- Existing test files intentionally prove fake-adapter behavior. Moving live
  tests into those files would weaken the reader's ability to tell hermetic
  and live proof apart.
- There is no packet-filtering CLI. The live test owns a tiny in-Python JSONL
  filter between `packets` and `analyze`: generate all packets through the CLI,
  read those records, sort/filter deterministically, write the deterministic
  subset to `live-packets.jsonl`, then pass that subset file to `analyze`.
- The deterministic self-corpus report in the live test deliberately uses the
  committed default configuration, not `--no-config`, so it exercises the same
  dogfood surface as the normal self-corpus gate. `analyze` uses `--no-config`
  because model selection is explicit and the packets file lives in a temp
  directory.

## Proposed Spec Delta

Promotion strategy: A - in-file edits to existing active sections. No new spec
section is introduced. Because [SC-7] and [CFG-9] already have implementation
mapping blocks, this is a wording change to existing requirements rather than
a new unmapped section. The spec-promotion slice must also add this plan to
each touched spec's `## Related Plans`.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/02-backstitch-core.md` | A - in-file active edit | [SC-7], Related Plans |
| `docs/specs/03-backstitch-configuration.md` | A - in-file active edit | [CFG-9], Related Plans |

### `docs/specs/02-backstitch-core.md` [SC-7]

Replace the final paragraph of [SC-7]:

> Tests for semantic analysis must not call external models. They should use fake
> model adapters or equivalent local fakes to prove prompt construction, model
> selection, output parsing, malformed model-output handling, and result
> aggregation.

with:

> Default semantic-analysis tests must not call external models. They must use
> fake model adapters or equivalent local fakes to prove prompt construction,
> model selection, output parsing, malformed model-output handling, and result
> aggregation.
>
> Optional live semantic-analysis tests are permitted only under an explicit
> opt-in gate. A live test must use packets produced by deterministic mode,
> call the real `llm` adapter through the public `analyze` command, keep the
> packet set bounded, and validate structured result JSONL rather than exact
> model wording. Missing credentials must skip only when the live gate is not
> enabled; once the live gate is enabled, missing credentials, provider
> failures, malformed model output, and invalid result rows must fail the live
> test by assertion on per-row errors and analysis-load errors. This is stricter
> than `analyze`'s exit-code contract: per this section, `analyze` still exits
> `0` on partial failure and records one `ambiguous`/error row per failed packet.
> Automation may exit successfully without invoking the live test when provider
> credentials are not configured for that environment; once credentials are
> present and the live test is invoked, these failure assertions apply.
> Live semantic findings remain advisory and must not create CI failure based on
> classification unless a separate policy explicitly changes this section.

### `docs/specs/03-backstitch-configuration.md` [CFG-9]

Replace:

> Do not call external LLMs in config tests. Use fake adapters for `analyze`
> integration tests.

with:

> Do not call external LLMs in config tests. Use fake adapters for `analyze`
> configuration integration tests. Optional live LLM tests belong to [SC-7]'s
> semantic-analysis verification path and must not be used as no-op-prevention
> proof for configuration keys.

## Rollout And Rollback

Rollout sequence:

1. Review this plan and proposed spec delta.
2. Promote the spec delta before implementing tests or CI.
3. Add the local live test with skip-by-default behavior.
4. Add GitHub Actions normal CI and live LLM CI. Keep the live job separate
   from the ordinary test job.
5. Set repository secret `OPENAI_API_KEY` for the first provider path and,
   optionally, repository variable `BACKSTITCH_LIVE_LLM_MODEL` for the model.
   If the variable is omitted, the workflow should use
   `DEFAULT_BACKSTITCH_LIVE_LLM_MODEL`, defined once in the workflow as the most
   recent available GPT-5-series mini model. At plan update time, OpenAI's
   model docs identify that model as `gpt-5.4-mini`.
6. Observe at least three successful live workflow runs before making the live
   job a required branch-protection check.
   The first CI design is intentionally post-merge/manual: live LLM runs on
   `push` to `main` and `workflow_dispatch`, not on pull requests, including
   same-repository pull requests. This avoids paid/provider flake on every PR
   while the job is being characterized. If pre-merge live coverage becomes
   necessary later, add that as an explicit policy change after run history
   exists.

Rollback:

- Immediate rollback is to unset `OPENAI_API_KEY` or disable the workflow job;
  the default no-network suite remains intact.
- Code rollback is isolated to `tests/live/`, `.github/workflows/`, marker docs,
  and documentation. Runtime Backstitch behavior should not need rollback
  because `backstitch/analysis_llm.py` and `backstitch/cli.py` should not
  change for provider support.
- If the spec wording proves too broad, add a Deviation Log row and run a spec
  revision slice before adjusting tests.

One-way doors: none intended. Do not add schema changes, new exit-code
semantics, or provider-specific runtime abstractions in this plan.

## Tasks

1. Independent plan review.
   - Files to read: this plan, `docs/specs/02-backstitch-core.md` [SC-7],
     `docs/specs/03-backstitch-configuration.md` [CFG-9],
     `docs/implementation/04-backstitch-style-traceability.md`.
   - Review stance: challenge whether the spec delta preserves the hermetic
     default suite, whether CI secret handling is safe, and whether the live
     proof is meaningful rather than a shallow provider ping.
   - Done signal: review findings are incorporated or answered in this plan.

2. Spec-promotion slice.
   - Files to touch: `docs/specs/02-backstitch-core.md`,
     `docs/specs/03-backstitch-configuration.md`.
   - Apply the exact text in `## Proposed Spec Delta`.
   - Add this plan to each touched spec's `## Related Plans`.
   - Record the promotion baseline identifier in this plan.
   - Re-check the official OpenAI model docs and `uv run llm models list`
     before implementation starts. If the most recent GPT-5-series mini model
     is no longer `gpt-5.4-mini`, update this plan before adding workflow or
     test code.
   - Verify: `uv run backstitch check --repo-root .` exits 0 with zero errors
     and zero warnings.
   - Stop and re-plan if the promoted spec creates warning-class traceability
     debt or if a reviewer asks for a new section rather than editing [SC-7].

3. Add live pytest marker and local test module.
   - Files to touch: `pyproject.toml`, `tests/live/test_live_llm.py`.
   - Add marker: `live_llm: tests that call a real LLM provider when explicitly enabled`.
   - Test behavior:
     - `pytestmark = [pytest.mark.live_llm, pytest.mark.skipif(...)]`.
     - If `BACKSTITCH_LIVE_LLM != "1"`, skip via a function-level
       `pytest.mark.skipif` on `pytestmark`, NOT a module-level
       `pytest.skip(..., allow_module_level=True)`. A module-level skip makes
       `pytest tests/live/test_live_llm.py` collect zero tests and exit 5 (no
       tests ran), which fails the hermetic CI skip-proof step. The skipif keeps
       the test collected and reported as skipped; keep `import llm` inside the
       test body so collection stays hermetic.
     - If opt-in is set, resolve `live_model = os.environ.get("LLM_MODEL") or
       DEFAULT_BACKSTITCH_LIVE_LLM_MODEL`, where
       `DEFAULT_BACKSTITCH_LIVE_LLM_MODEL` is `gpt-5.4-mini` unless the
       spec-promotion slice refreshed it. Fail clearly if `llm.get_model`
       cannot resolve `live_model`.
     - Before the provider call, run a credential preflight that reports a
       clear failure when neither `OPENAI_API_KEY` nor an `llm` stored
       `openai` key is available for an OpenAI model. The preflight may use
       `llm.get_key(key_alias="openai", env_var="OPENAI_API_KEY")`; do not
       print the key. For non-OpenAI providers added later, extend this
       preflight explicitly instead of guessing.
     - Generate packets from this repository with
       `[sys.executable, "-m", "backstitch", "packets", "--repo-root", ".",
       "--output", "<tmp>/all-packets.jsonl"]`.
     - Assert `packets` exits 0 and wrote non-empty JSONL.
     - Read `<tmp>/all-packets.jsonl` in Python, select a small deterministic
       subset, default 1 packet, max 5, and write that subset to
       `<tmp>/live-packets.jsonl`. Candidate packets are those whose
       `spec_path == "docs/specs/02-backstitch-core.md"` and whose
       `owners[].path` satisfies either `path == "backstitch/cli.py"` or
       `fnmatch.fnmatch(path, "backstitch/analysis_*.py")`. Sort candidates by
       serialized JSON byte length, then `packet_id`, then original packet
       order; select the first N. This prefers the smallest matching packets,
       preserves reproducibility, and reduces model-format flake. If that
       candidate set is empty, fail because the dogfood corpus stopped
       exercising the semantic path meaningfully.
     - Run
       `[sys.executable, "-m", "backstitch", "analyze", "--packets",
       "<tmp>/live-packets.jsonl", "--model", live_model, "--concurrency",
       "1", "--no-config", "--output", "<tmp>/analysis.jsonl"]`.
     - Run
       `[sys.executable, "-m", "backstitch", "check", "--repo-root", ".",
       "--format", "json", "--output", "<tmp>/report.json"]`.
     - Assert `check` exits 0. This is intentional: the live test is a
       dogfood proof against the committed clean corpus. Local WIP doc debt may
       break the live test, which is acceptable because the normal hermetic
       suite remains the development-time gate.
     - Run
       `[sys.executable, "-m", "backstitch", "summarize-analysis",
       "--deterministic-report", "<tmp>/report.json", "--analysis-results",
       "<tmp>/analysis.jsonl"]`.
     - Generate `report.json` from the full repository, not the subset, so
       `summarize-analysis` can resolve the subset packet IDs against the same
       report surface normal users would produce.
   - Assertions:
     - no command prints a traceback
     - `analyze` exits 0
     - `packets`, `check`, and `summarize-analysis` exit 0
     - one result row exists per live packet
     - parse `<tmp>/analysis.jsonl` in-process and make the load-bearing model
       assertion first: no raw row has an `error` field. This is the only
       assertion that distinguishes successful model analysis from a contained
       provider/model failure, because `_error_record` intentionally produces a
       schema-valid row.
     - every row validates through `validate_analysis_row(row,
       expected_packet_ids)` for the subset packet IDs. Do not claim this call
       re-checks packet-local evidence bounds; `analyze` enforces that because
       it has the packet data.
     - `load_analysis_results(analysis_text, expected_packet_ids).errors == ()`.
       This catches JSONL/schema/packet-ID load problems. It is a separate
       assertion from `summarize-analysis` exit 0, because `summarize-analysis`
       renders analysis input problems and still exits 0 when the deterministic
       report is valid.
     - treat exit-code assertions as command-path and artifact-health checks,
       not as proof of model success. `analyze` exit 0 allows partial failure,
       and `summarize-analysis` exit 0 does not imply the analysis JSONL was
       problem-free.
   - What must stay real: CLI subprocesses, packet generation, real
     `default_adapter`, provider call, result validation.
   - What may be mocked: nothing inside the live test. The only allowed skip
     is the explicit opt-in gate not being set.

4. Document local usage.
   - Files to touch: `README.md` and
     `docs/implementation/04-backstitch-style-traceability.md`.
   - Document local examples:
     - stored-key path:
       `uv run llm keys set openai`
     - env-key path:
       `OPENAI_API_KEY=... BACKSTITCH_LIVE_LLM=1 LLM_MODEL=gpt-5.4-mini uv run pytest -m live_llm -q`
     - existing default-key-store path:
       `BACKSTITCH_LIVE_LLM=1 LLM_MODEL=<configured-model> uv run pytest tests/live/test_live_llm.py -q`
   - State that model choice is intentionally explicit; do not rely on the
     user's global `llm` default for reproducible CI.
   - State the cost and flake tradeoff plainly.

5. Add GitHub Actions workflow.
   - Superseded on 2026-07-03 by
     `docs/plans/2026-07-03-backstitch-release-publishing-plan.md` after user
     correction: live LLM is now part of the normal `CI` workflow and skips
     only when repository secrets are unavailable.
   - Files to touch: `.github/workflows/ci.yml`.
   - Workflow triggers:
     - `pull_request` for normal no-secret CI only.
     - `push` for branch CI, but the paid live job must run only when
       `github.ref == 'refs/heads/main'`.
     - `workflow_dispatch` for explicit manual live runs on demand.
   - Explicit tradeoff: same-repository pull requests do not run live LLM
     tests before merge. The live job is a post-merge canary plus a manual
     pre-merge tool via `workflow_dispatch`, not a default PR gate.
   - Create a normal CI job that runs without secrets:
     - install dependencies with `uv`
     - `uv run pytest tests -q -m "not live_llm"`
     - `uv run pytest tests/live/test_live_llm.py -q` with no live env, proving
       the default skip gate works. Expect one skipped live test; unexpected
       live-provider activity in this step is a failure.
     - `uv run ruff check .`
     - `uv run mypy backstitch`
     - `uv run backstitch check --repo-root .`
   - Create a separate `live-llm` job:
     - `needs: test`
     - `if: ${{ github.event_name == 'workflow_dispatch' || (github.event_name == 'push' && github.ref == 'refs/heads/main') }}`
     - inject `OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}` as step or job
       env, not as a command argument
     - set `BACKSTITCH_LIVE_LLM: "1"`
     - set `DEFAULT_BACKSTITCH_LIVE_LLM_MODEL: "gpt-5.4-mini"` in one workflow
       env block, updated only after re-checking the model docs and
       `uv run llm models list`. This literal must match the test module's
       `DEFAULT_BACKSTITCH_LIVE_LLM_MODEL`; treat the two copies as one
       canonical value, not as independent defaults.
     - set `BACKSTITCH_LIVE_LLM_MODEL: ${{ vars.BACKSTITCH_LIVE_LLM_MODEL }}`
       as env; in shell compute
       `LLM_MODEL="${BACKSTITCH_LIVE_LLM_MODEL:-$DEFAULT_BACKSTITCH_LIVE_LLM_MODEL}"`
     - in the shell, if `OPENAI_API_KEY` is empty, print a GitHub notice and
       exit 0 before running live tests
     - before running pytest, verify the model is registered without making a
       network call:
       `uv run python -c 'import llm, os; llm.get_model(os.environ["LLM_MODEL"])'`
     - if the secret is present, run `uv run pytest tests/live/test_live_llm.py -q`
   - Do not use `secrets.*` in a job-level `if`. GitHub's context table does
     not make `secrets` available in `jobs.<job_id>.if`; check secret presence
     inside a runner step.
   - Do not run the live job on `pull_request`; forked PRs do not receive
     ordinary repository secrets.

6. CI repository setup.
   - Repository secret: `OPENAI_API_KEY`.
   - Optional repository variable: `BACKSTITCH_LIVE_LLM_MODEL`. When set it
     overrides the baked default for that environment without a code change;
     when unset the workflow falls back to `DEFAULT_BACKSTITCH_LIVE_LLM_MODEL`
     (Task 5).
   - Canonical default model: `DEFAULT_BACKSTITCH_LIVE_LLM_MODEL`, defined once
     in the workflow env block and mirrored by the test module's constant of
     the same name. Keep the two literals byte-identical. At plan update time
     both are `gpt-5.4-mini`; re-check OpenAI's model docs and
     `uv run llm models list` during the spec-promotion slice (Task 2) and
     update both copies together — model availability changes faster than
     repository code. Note the preflight (`llm.get_model`) only proves the ID is
     registered in `llm`, not that the provider still serves it; a retired-but-
     registered ID passes preflight and fails at call time.
   - Branch protection: do not make `live-llm` required until it has a stable
     run history. When made required, provider outages will block merges.

7. Traceability reconciliation.
   - Files to touch as needed:
     - `docs/implementation/02-repository-map.md`
     - `docs/implementation/04-backstitch-style-traceability.md`
     - `README.md`
     - this plan's verification log
   - Ensure specs, plan, implementation docs, tests, and workflow form a
     closed chain.
   - Run the final gates listed below.

## Testing Plan

Hermetic proof remains primary:

- `uv run pytest tests/test_analysis_llm.py tests/acceptance/test_probe_analysis.py -q`
- `uv run pytest tests -q`

Live local proof, only with a configured key:

- `BACKSTITCH_LIVE_LLM=1 LLM_MODEL=<model> uv run pytest tests/live/test_live_llm.py -q`
- If using OpenAI via env:
  `OPENAI_API_KEY=... BACKSTITCH_LIVE_LLM=1 LLM_MODEL=<model> uv run pytest -m live_llm -q`

CI proof:

- Without `OPENAI_API_KEY`: normal CI passes; live job records a notice and
  exits successfully without calling a model.
- With `OPENAI_API_KEY`: live job runs only on `push` to `main` or
  `workflow_dispatch`, calls the provider, and fails on unknown model,
  model-call failure, malformed model output, invalid rows, or
  summary-load failure.

Anti-mocking posture:

- Unit and acceptance tests continue to fake only the model boundary.
- The live test must not fake the model boundary, subprocesses, packet
  generation, or result validation.

## Verification And Gates

Per-task gates are listed in `## Tasks`. Final implementation gates:

```bash
uv run pytest tests/test_analysis_llm.py tests/acceptance/test_probe_analysis.py -q
uv run pytest tests -q
uv run ruff check .
uv run mypy backstitch
uv run backstitch check --repo-root .
```

Live gate when credentials are available:

```bash
BACKSTITCH_LIVE_LLM=1 LLM_MODEL=<model> uv run pytest tests/live/test_live_llm.py -q
```

Observed-success signals:

- local opt-in command produces valid `analysis.jsonl` and
  `summarize-analysis` accepts it
- Actions normal CI passes without secrets
- Actions live job skips by notice without `OPENAI_API_KEY`
- Actions live job calls a model and passes when `OPENAI_API_KEY` is set
- no secret values appear in workflow logs

Residual risk to name at completion:

- provider outage, model retirement, account quota, and rate limits can fail
  the live job without indicating a Backstitch regression
- model output quality is nondeterministic; the test gates structure and
  command contract, not semantic correctness
- no retry is planned for the first implementation. If run history shows
  provider transport failures dominate, add a narrow retry policy later for
  transport/rate-limit/5xx failures only. Do not retry malformed model output
  or packet-local evidence failures, because those are the behavior the live
  test is meant to reveal.
- `analyze` deliberately collapses transient provider failures and real
  model-output contract violations into the same per-packet error-record shape.
  The live test's strict no-row-error assertion cannot distinguish those
  causes. This is accepted for the initial non-required post-merge/manual job;
  do not treat a red live job as a proven Backstitch regression until the row
  error message and provider status have been inspected.

## Independent Review Loop

Review prompt:

> Review `docs/plans/2026-07-03-live-llm-tests-plan.md` as a risky
> boundary-crossing plan. Read the proposed [SC-7] and [CFG-9] deltas, the
> current `analysis_llm.py` adapter boundary, and GitHub Actions secret/context
> constraints. Prioritize findings where the plan weakens the default hermetic
> suite, mishandles secrets, makes semantic findings CI-failing by accident, or
> creates a live test that does not meaningfully dogfood Backstitch.

The plan author must answer every finding by editing this plan or recording
why the current path is still correct.

## Out Of Scope

- New provider integrations or model-provider abstraction in Backstitch.
- Running a full-repository live semantic review on every CI run.
- Failing CI based on semantic classification.
- Changing `analyze` exit-code semantics.
- Storing model outputs as artifacts by default.
- Supporting secrets in forked pull-request workflows.
- Adding new package dependencies.

## Fresh-Eyes Review

Review pass 1: attached implementation-readiness review,
`/Users/van/.codex/attachments/d398deaa-a4b8-43b3-b7e8-d744fa43ab41/pasted-text.txt`.

- Finding: Task 3 named `packets.jsonl` and `live-packets.jsonl` but never
  specified how the subset file is produced. Fix: Task 3 now generates
  `<tmp>/all-packets.jsonl`, filters JSONL in Python, and writes
  `<tmp>/live-packets.jsonl` before invoking `analyze`.
- Finding: subprocess examples used bare `python -m backstitch`, which can
  resolve outside the pytest environment. Fix: Task 3 now requires
  `sys.executable -m backstitch`.
- Finding: workflow triggers were unspecified, and the paid live job would run
  on every branch push. Fix: Task 5 now names `pull_request`, `push`, and
  `workflow_dispatch`, with the live job limited to `workflow_dispatch` or
  `push` to `main`.
- Finding: model fallback was hardcoded in several places without a resolution
  preflight. Fix: the plan now defines one
  `DEFAULT_BACKSTITCH_LIVE_LLM_MODEL`, currently `gpt-5.4-mini`, requires a
  docs/`llm models list` re-check before implementation, and adds a
  no-network `llm.get_model` preflight.
- Finding: row validation wording overclaimed packet-local evidence checks.
  Fix: Task 3 now says `validate_analysis_row(row, expected_packet_ids)`
  checks schema and packet IDs, while `analyze` owns packet-local evidence
  enforcement because it has packet data.
- Finding: `summarize-analysis` needs packet IDs to exist in the deterministic
  report. Fix: Task 3 now explicitly keeps `report.json` full-repository while
  `analysis.jsonl` is the bounded live subset.

Review pass 2: attached implementation-readiness review,
`/Users/van/.codex/attachments/89721289-bcd7-40da-ab60-60e8f81542c3/pasted-text.txt`.

- Finding: a multi-packet live test with `no error` rows is likely flaky
  because real models can violate packet-local evidence or output-shape rules.
  Fix: the default subset is now one packet, selected as the smallest matching
  packet by deterministic sort order, and branch protection remains blocked
  until run history exists.
- Finding: packet selection needed a stable algorithm. Fix: Task 3 now filters
  candidates by `spec_path` and owner path, then sorts by serialized JSON byte
  length, `packet_id`, and original order before selecting N.
- Finding: exit-code assertions were incomplete. Fix: Task 3 now asserts
  `packets`, `analyze`, `check`, and `summarize-analysis` all exit 0.
- Finding: credential diagnostics were too implicit. Fix: Task 3 now requires
  a local OpenAI credential preflight using `llm.get_key` without printing the
  key, while CI still skips by notice when the repository secret is absent.
- Finding: same-repository pull requests also skip live proof. Fix: rollout
  and workflow sections now state the tradeoff explicitly: live LLM CI is
  post-merge/manual until run history justifies a pre-merge policy change.
- Finding: full-repo `check` inside the live test couples local runs to
  self-corpus cleanliness. Fix: Hidden Couplings and Task 3 now state this is
  intentional dogfood behavior, with the hermetic suite remaining the normal
  development-time gate.
- Finding: default skipped live tests may show in normal pytest output. Fix:
  the normal CI job now expects one skipped live test and treats unexpected
  provider activity as failure.

Review pass 3: attached deeper proof-strength review,
`/Users/van/.codex/attachments/f2614ff2-9918-4c02-96d6-0bf7a079f544/pasted-text.txt`.

- Finding: the assertion list overstated rigor because `analyze` exit 0,
  `validate_analysis_row`, and `summarize-analysis` exit 0 can all pass while
  a model/provider failure was contained as an `ambiguous` row with an `error`
  field. Fix: Task 3 now states that no raw row may have an `error` field as
  the first load-bearing model-success assertion, and labels exit-code checks
  as command-path/artifact-health checks.
- Finding: `summarize-analysis` exit 0 does not prove analysis rows were clean;
  it can render analysis input problems while exiting 0 if the deterministic
  report is valid. Fix: Task 3 now requires
  `load_analysis_results(analysis_text, expected_packet_ids).errors == ()`.
- Finding: [SC-7] proposed wording implied provider failures become failures
  through the tool pipeline. Fix: the proposed spec delta now says live tests
  must fail by assertion on per-row errors and analysis-load errors while
  preserving `analyze`'s partial-failure exit-0 contract.
- Finding: transient provider failures and real contract violations are
  indistinguishable under `analyze`'s error-record abstraction. Fix: Residual
  risk now names this accepted limitation and says a red live job is not a
  proven Backstitch regression until the row message and provider status are
  inspected.

Review pass 4: attached final readiness review,
`/Users/van/.codex/attachments/bd6ef92e-a594-4adf-b55b-5396f09f3120/pasted-text.txt`.

- Finding: the proposed [SC-7] text said missing credentials must fail after
  live opt-in, while the CI wrapper intentionally exits successfully without
  invoking pytest when no repository secret is configured. Fix: the [SC-7]
  delta now permits automation to exit successfully without invoking the live
  test when provider credentials are absent; once credentials exist and the
  live test runs, row-error assertions apply.
- Finding: `DEFAULT_BACKSTITCH_LIVE_LLM_MODEL` is unavoidably duplicated in
  the test module and workflow despite the plan saying "one place." Fix:
  invariants and Task 5 now say these two literals are one canonical value
  copied into two execution contexts and must be checked together during the
  model-doc re-check.
- Finding: `backstitch/analysis_*.py` was descriptive but not an implementation
  rule. Fix: Task 3 now names the exact owner-path predicate:
  `path == "backstitch/cli.py"` or
  `fnmatch.fnmatch(path, "backstitch/analysis_*.py")`.
