# Local LLM Evaluation Lane

Status: draft (two independent reviews incorporated; awaiting spec-promotion)
Plan type: implementation with spec revision
Risk level: boundary-crossing — new CI execution context, Docker service
lifecycle, network transport to a locally hosted model, `llm` provider
configuration outside backstitch runtime, and (on graduation) fork-PR exposure

## Goal

Add a second, credential-free live-analysis path that exercises Backstitch's
real `llm` adapter against a **local, CPU-only, OpenAI-compatible model server**
(default: an Ollama Docker image serving a small model) instead of a paid cloud
provider. It reuses the already-landed live module and CLI proof; it differs
only in how the model is provisioned/selected and in a deliberately lenient
success contract. Because it needs no secret it can eventually run on forked
pull requests. The default hermetic suite stays no-network and **no new Python
dependency is added**: the local endpoint is reached through `llm`'s existing
OpenAI-compatible support (`api_base` in `extra-openai-models.yaml`), verified
against `llm` 0.31 to route through the unchanged `default_adapter`.

## Requested Outcomes

- Prove the real (non-fake) `default_adapter` → HTTP → parse → validation path
  works against a genuine model with **no provider credential**.
- Eventually give fork/internal PRs a real-model lane the secret-gated cloud
  lane structurally cannot provide.
- Keep the local model provisioned as a cached Docker image + cached model
  weights, spun up in CI and reproducible locally, on non-GPU hardware.
- Preserve the current no-network default test contract; add no Python package.
- Follow the repo's spec-changing workflow: plan → independent review →
  spec-promotion slice → implementation against the promoted spec.

## Relationship To The Cloud Live Lane (already landed)

The cloud/OpenAI live lane landed during this plan's authoring:

- `c2aad73` added `tests/live/test_live_llm.py` and the `live_llm` marker.
- `503a93e` added `.github/workflows/ci.yml` (a `hermetic` job and a
  post-merge/manual `live-llm` job).

This plan **extends those existing files**; it does not create them. The shared
module is already provider-general in two load-bearing ways this plan depends
on (verified by reading the landed code):

1. `_resolve_live_model()` resolves the model **in-process** via
   `llm.get_model(model_name)` and drives its credential preflight off
   `model.needs_key`. A keyless model (`needs_key` falsy) is explicitly allowed
   with no credential — exactly the local case.
2. `_run_cli(...)` runs `sys.executable -m backstitch ...` **without** an `env=`
   override, so subprocesses inherit the test process's `os.environ`. Setting
   `os.environ["LLM_USER_PATH"]` and `os.environ["LLM_MODEL"]` once therefore
   makes the in-process transport preflight and the `analyze` subprocess resolve
   the **same** `backstitch-local` registration — no env-drift between them.

The local kind is added **inside** the existing single test
`test_live_llm_analysis_contract` (keyed on a new `BACKSTITCH_LIVE_LLM_KIND`
env), not as a parallel module or a second test function, so the module still
skips as a unit when the gate is off and the hermetic job's skip-proof step is
unaffected.

## Source Documents

- `docs/specs/02-backstitch-core.md` [SC-5], [SC-6], [SC-7]
- `docs/specs/03-backstitch-configuration.md` [CFG-5], [CFG-9]
- `docs/plans/2026-07-03-live-llm-tests-plan.md` (sibling cloud lane, landed)
- `tests/live/test_live_llm.py` (the module this plan extends — read first)
- `.github/workflows/ci.yml` (the workflow this plan extends — read first)
- `backstitch/analysis_llm.py` (`default_adapter`, `_error_record`,
  `analyze_exit_code` — the real boundary; unchanged by this plan)
- `docs/implementation/04-backstitch-style-traceability.md`,
  `docs/implementation/02-repository-map.md`
- `docs/agent-context/runbooks/writing-plans.md` §4b–§4d, `hardening-plans.md`,
  `testing-patterns.md`
- `llm` OpenAI-compatible config (re-check; URLs drift):
  <https://llm.datasette.io/en/stable/other-models.html>. Verified against the
  installed `llm` 0.31: `openai_models.register_models` sets
  `chat_model.needs_key = None` when an entry has `api_base`, and passes
  `api_key="DUMMY_KEY"` at client build, so **no key is required or sent**;
  `llm.user_dir()` reads `LLM_USER_PATH` live on every call and model
  registration is uncached, so in-process resolution after setting the env var
  works.
- Ollama OpenAI compatibility: <https://docs.ollama.com/api/openai-compatibility>;
  image `ollama/ollama` (pin by digest in CI); model tag, e.g.
  <https://ollama.com/library/qwen2.5-coder>. Documented alternatives (not the
  default): llama.cpp server `ghcr.io/ggml-org/llama.cpp:server`, LocalAI.
- GitHub Actions: caching <https://github.com/actions/cache>; fork-PR / secret
  behavior and approval-for-first-time-contributors
  <https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows>

## Spec Baseline

- `503a93e` (repo HEAD at plan revision) for `docs/specs/02-backstitch-core.md`
  and `docs/specs/03-backstitch-configuration.md`. `2ed88ea` already promoted
  the optional-live-test wording into [SC-7]/[CFG-9]; this plan **extends** that
  wording to cover a local OpenAI-compatible endpoint. HEAD also already carries
  the landed module and workflow (`c2aad73`, `503a93e`).
- Worktree note at revision: modified files under `docs/agent-context/`;
  untracked plan files under `docs/plans/`. The governing spec files (`02`,
  `03`), `tests/live/test_live_llm.py`, and `.github/workflows/ci.yml` were
  committed/clean.
- Promotion baseline identifier: _record after this plan's spec-promotion slice
  lands (Task 2)._

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Context and Key Files

- `tests/live/test_live_llm.py` (landed): one module-level skip gate
  (`BACKSTITCH_LIVE_LLM != "1"` → `allow_module_level=True`), `_resolve_live_model()`
  (in-process, `needs_key`-driven), `_select_live_packets()` (deterministic
  smallest-first subset from `[SC-7]`'s spec path), and one test
  `test_live_llm_analysis_contract(tmp_path)`. The load-bearing cloud assertion
  is `assert not errored` (no row carries an `error` field). This plan makes
  that assertion conditional on kind/strictness and adds the `local` branch.
- `.github/workflows/ci.yml` (landed): `hermetic` job (runs on push/PR/dispatch,
  no secrets, includes the skip-proof step and the self-corpus gate) and
  `live-llm` job (`workflow_dispatch` or `push` to `main`, secret-gated). This
  plan adds a `local-llm` job.
- `backstitch/analysis_llm.py`: `default_adapter` calls `llm.get_model(...)` then
  `.prompt(prompt).text()` (non-streaming). `_error_record` turns any per-packet
  failure into a **schema-valid** `ambiguous` row with an `error` field.
  `analyze_exit_code`/`_cmd_analyze` return exit 2 iff **every** packet errored,
  exit 0 on partial failure. Unchanged by this plan.
- `pyproject.toml`: the `live_llm` marker (shared).

Comprehension checks before editing:

1. Given `_run_cli` inherits `os.environ` and `llm.user_dir()` reads
   `LLM_USER_PATH` live, what single mutation makes both the in-process
   transport preflight and the `analyze` subprocess resolve the same
   `backstitch-local` registration — and why is a subprocess-only resolution
   *not* required (the earlier assumption that config "binds at import" is
   false for `llm` 0.31)?
2. Every failure funnels through `_error_record` into a schema-valid row, so
   "one row per packet + all rows validate + no load errors" can be satisfied
   with **every** packet errored. Which existing assertion already prevents a
   total-failure pass, and why is it `assert analyze exits 0` (exit 2 == all
   errored), not the row checks?
3. On a fork PR the runner executes fork-authored workflow/test code. Beyond
   "no secret to steal," what can a fork do with a job that pulls and runs a
   Docker image and model — and which values must therefore come from
   workflow-controlled constants, not fork-editable env?

## Invariants and Constraints

Inherited (must still hold): default suite stays no-network; live path gated by
`BACKSTITCH_LIVE_LLM=1` (module skips, never fails, when unset); real CLI path
only (`packets` → `analyze` → `summarize-analysis`); model sees only
Backstitch packets; subset small/deterministic (default 1, max 5); assertions
are structural, never model wording; semantic findings advisory, never CI-failing
by classification ([SC-7]).

New to the local lane:

- **No new Python dependency.** Reached through `llm`'s built-in
  OpenAI-compatible support via `extra-openai-models.yaml`. Do **not** install
  `llm-ollama` or any plugin, and do not add an HTTP client dependency —
  analysis goes through `default_adapter`; the reachability/transport preflight
  uses the standard library (`urllib`).
- **No provider-specific runtime code in `backstitch/`.** Endpoint/model wiring
  lives only in `extra-openai-models.yaml`, the test, CI, and docs.
- **No key required or sent for the default Ollama path.** `api_base` ⇒
  `needs_key = None` in `llm` 0.31; the landed `_resolve_live_model` already
  skips the credential preflight when `needs_key` is falsy. Do **not** add a
  dummy `OPENAI_API_KEY`. A future server that *requires* a bearer token gets an
  `api_key_name:` in its yaml entry and its own env var — never reuse
  `OPENAI_API_KEY` or the cloud secret.
- **Do not mutate the developer's global `llm` config.** The test writes its
  `extra-openai-models.yaml` into a per-test temp dir and points
  `LLM_USER_PATH` at it via `monkeypatch`; the user's
  `~/.config/io.datasette.llm/` is untouched and env is restored after the test.
  The temp dir must exist **before** any resolution (a missing `extra_path` is a
  silent no-op in `llm`, surfacing only as "Unknown model").
- **Preflight and `analyze` must provably share resolution.** Set
  `os.environ["LLM_USER_PATH"]` and `os.environ["LLM_MODEL"]="backstitch-local"`
  before both; rely on `_run_cli`'s env inheritance (no `env=` override). The
  transport preflight asserts the resolved model's `api_base` equals the
  configured endpoint, so "reached the right server" is proven, not assumed.
- **Transport proven separately from analysis-JSON quality.** Before the analyze
  run, one real generation through `backstitch-local` must return non-empty
  text. This is a hard assertion; a wall of contained error rows cannot pass as
  "server reached."
- **Total analysis failure still fails, even in lenient mode.** Keep the landed
  `assert analyze returncode == 0`; exit 2 (all packets errored) is a failure.
  Only the per-row `assert not errored` is relaxed for the local kind.
- **Success contract is deliberately lenient about model quality.** A small CPU
  model legitimately emits malformed JSON; per-packet model-quality error rows
  are **not** failures for `kind == "local"` unless `BACKSTITCH_LIVE_LLM_STRICT=1`.
  The load-bearing proof is transport + parse + validation + containment health
  plus non-total-failure — not clean classifications.
- **Reachability means "the OpenAI surface serves this model."** The preflight
  hits `GET <endpoint>/models` (the `/v1` surface `analyze` uses) and asserts
  the target model id is listed — not merely that a socket answered.
- **CPU-only, memory-bounded.** Default a **3B-class 4-bit model** and design to
  the smaller floor (**2 vCPU / 7 GB** standard runner). Bound KV-cache memory
  with a small `num_ctx` in the yaml entry. Name a concrete smaller fallback
  (`llama3.2:1b`) if the 3B model does not fit; do not leave "must fit" as an
  unbacked assertion. A 7B model is only for confirmed 16 GB runners and must
  not be the committed default.
- **Fatal vs best-effort.** Fatal: model unresolved, endpoint unreachable or
  model absent from `/models`, transport preflight empty or wrong `api_base`,
  any CLI subprocess unexpected exit (including `analyze` exit 2), row
  schema/packet-id invalid, `load_analysis_results` load errors. Best-effort
  (not fatal for local non-strict): individual packet `error`/`ambiguous` rows.

## Hidden Couplings

- **Shared module, two contracts.** Cloud kind asserts `not errored`; local kind
  asserts transport + pipeline health + non-total-failure and tolerates error
  rows. Gate only the `assert not errored` line on
  `kind == "openai" or BACKSTITCH_LIVE_LLM_STRICT`. Keep every other assertion
  shared. One test function, one skip gate.
- **`LLM_USER_PATH` is read live and uncached** (`llm.user_dir()` per call;
  `register_models` re-reads `extra-openai-models.yaml` each `get_model`). So
  in-process resolution after `monkeypatch.setenv` works, and the analyze
  subprocess (inheriting `os.environ`) sees the same registration. The earlier
  "config binds at import → must use subprocess" reasoning is **false** and must
  not appear in the implementation.
- **`_run_cli` inherits `os.environ`.** Do not add an `env=` override that drops
  `LLM_USER_PATH`/`LLM_MODEL`; that would silently re-route `analyze` to the
  global config while the preflight passed.
- **`analyze` discovers config relative to the packets file.** Keep `--no-config`
  and explicit `--model backstitch-local`; the endpoint binding comes from
  `LLM_USER_PATH`'s yaml, not backstitch config discovery.
- **`check` exit-0 coupling.** The landed flow asserts `check` exit 0 (dogfood
  against a clean committed corpus). On the initial push/dispatch rollout the
  corpus is clean, so this holds. **Before graduating the job to fork PRs**, a
  fork's WIP doc debt would make `check` exit 1 and fail the local test for
  unrelated reasons — graduation must relax this for the local kind (assert
  `check` runs and produces a valid report; do not assert exit 0) or keep the
  job off fork PRs.
- **Model tag identity.** `model_name` in the yaml is forwarded verbatim as the
  OpenAI `model` param; it must equal the exact pulled Ollama tag. Keep
  `BACKSTITCH_LOCAL_LLM_MODEL`, the workflow pull tag, and the yaml `model_name`
  as one canonical value (same discipline the cloud lane applied to its model
  literal). A mismatch 404s and would otherwise hide as a tolerated error row —
  the reachability preflight (`/models` lists the tag) catches it.
- **Docker model cache vs image cache.** The slow path is the ~2 GB model
  download, not the image. Cache the mounted weights dir keyed by model tag.
  Ownership/path trap: `ollama/ollama` writes root-owned files; `actions/cache`
  runs as the runner user. Use one **absolute** cache path (not `~`) mounted at
  the same path across steps, and either `--user $(id -u)` or `sudo chown` before
  cache save, or the save silently skips and every run re-downloads (blowing the
  timeout on a supposed cache hit).

## Proposed Spec Delta

Promotion strategy: **A — in-file edits to existing active sections.** [SC-7]
and [CFG-9] are active and already carry `_Implementation mapping_` blocks and
the optional-live-test wording (promoted in `2ed88ea`). This is an additive
clarification of existing active requirements, not a new section. No mapping-block
change is required: no new `backstitch/` code path is added (the runtime adapter
is unchanged); new behavior lives in tests, CI, and `llm` environment config.
The spec-promotion slice also adds this plan to each spec's `## Related Plans`.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/02-backstitch-core.md` | A — in-file active edit | [SC-7], Related Plans |
| `docs/specs/03-backstitch-configuration.md` | A — in-file active edit | [CFG-9], Related Plans |

### `docs/specs/02-backstitch-core.md` [SC-7]

Insert the following paragraph **after** the paragraph beginning "Optional live
semantic-analysis tests are permitted only under an explicit opt-in gate…" and
**before** the "Live semantic findings remain advisory…" paragraph:

> An optional live test may target a local, self-hosted, OpenAI-compatible model
> endpoint instead of a paid cloud provider, reached through `llm`'s standard
> OpenAI-compatible model configuration (`api_base`) with no additional package
> dependency and no change to the runtime adapter. Because a local-endpoint test
> needs no provider credential, it may run in automation contexts that do not
> receive repository secrets, including forked pull requests. A local-endpoint
> live test must use packets produced by deterministic mode, call the real
> adapter through the public `analyze` command, keep the packet set bounded, and
> validate structured result JSONL. It must prove the endpoint served a
> generation **through the same model resolution the `analyze` command uses**,
> and must fail if the analyze run reports total failure (every packet in the
> bounded set produced an error record), so contained per-packet errors cannot
> masquerade as a working call. Its load-bearing assertion is the health of the
> real transport, parsing, validation, and malformed-output-containment path
> plus non-total-failure; because small local models legitimately emit malformed
> output, a local-endpoint live test must not treat individual per-packet
> model-quality error records as failures unless a stricter opt-in explicitly
> demands model success. An unreachable endpoint, a model absent from the
> endpoint, or a failed transport proof is a failure once the live gate is
> enabled, and a skip when it is not. This does not change `analyze`'s exit-code
> contract or the advisory status of semantic findings.

### `docs/specs/03-backstitch-configuration.md` [CFG-9]

Replace the final paragraph of [CFG-9]:

> Do not call external LLMs in config tests. Use fake adapters for `analyze`
> configuration integration tests. Optional live LLM tests belong to [SC-7]'s
> semantic-analysis verification path and must not be used as no-op-prevention
> proof for configuration keys.

with:

> Do not call external LLMs in config tests. Use fake adapters for `analyze`
> configuration integration tests. Optional live LLM tests — whether against a
> cloud provider or a local OpenAI-compatible endpoint — belong to [SC-7]'s
> semantic-analysis verification path and must not be used as no-op-prevention
> proof for configuration keys. Local-endpoint model wiring (`api_base` and
> model registration via `llm`'s `extra-openai-models.yaml`) is `llm`/provider
> environment configuration, not a backstitch configuration key, and must not
> introduce provider-specific handling into backstitch's configuration loader or
> runtime modules.

## Rollout And Rollback

Rollout sequence:

1. Independent review of this plan and the delta (done: two reviews below).
2. Spec-promotion slice: apply the delta; update `## Related Plans`; record the
   promotion baseline identifier. **Resolve the default-model question first**
   (both reviewers flagged format stability) — the default is a committed module
   constant + workflow literal.
3. Add the `local` kind to `tests/live/test_live_llm.py` with skip-by-default
   behavior and the committed `extra-openai-models.yaml` template.
4. Add the `local-llm` CI job. **Initial scope: `workflow_dispatch` + `push`
   only, not `pull_request`** (mirrors the cloud lane's conservative rollout and
   both reviewers' recommendation). Non-required in branch protection.
5. Document local provisioning and the CI job.
6. Graduate to fork PRs only after: pinned image digest + workflow-controlled
   model tag, cache path proven stable, `check` exit-0 relaxed for the local
   kind, and resource-abuse mitigations in place (see Threat Model). Record the
   graduation as an explicit change, not a silent trigger edit.

Rollback: remove/disable the `local-llm` job; the hermetic and cloud lanes are
untouched. Code rollback isolated to `tests/live/`, the committed yaml template,
`.github/workflows/ci.yml`, and docs. Runtime modules do not change. If the spec
wording proves too broad, add a Deviation Log row and run a spec-revision slice.

One-way doors: none intended in the initial (non-PR) rollout. Graduating to fork
PRs is the higher-bar step and is gated on the Threat Model prerequisites.

## Threat Model (fork-PR graduation)

"No secret" mitigates secret exfiltration only. A fork PR runs fork-authored
test/workflow code, so before the `local-llm` job runs on `pull_request`:

- Pin the Docker image by **digest**, not the floating `ollama/ollama` tag.
- Take the model tag, endpoint, image, and `num_ctx` from **workflow-controlled
  constants**, never from fork-editable env or files.
- Rely on GitHub's "require approval for first-time contributors" for fork
  workflow runs; keep the job non-required.
- Treat per-PR cost as an abuse vector, not just a bill: a ~2 GB pull + CPU
  inference on every fork push is a resource-DoS surface. Bound with a `paths`
  filter and the hard `timeout-minutes`, and start from `workflow_dispatch` +
  `push` so the exposure is opt-in until the cache path is proven.

## Tasks

1. **Independent plan review.** _(done — see Independent Review Incorporation.)_

2. **Spec-promotion slice.**
   - Files: `docs/specs/02-backstitch-core.md`,
     `docs/specs/03-backstitch-configuration.md`.
   - Apply the exact `## Proposed Spec Delta`; add this plan to each
     `## Related Plans` as `(implementing)`.
   - Record the promotion baseline identifier here.
   - **Resolve the default local model** (`qwen2.5-coder:3b` vs `llama3.2:3b`;
     fallback `llama3.2:1b`) and re-check its Ollama tag before writing code.
   - Verify: `uv run backstitch check --repo-root .` → exit 0, zero warnings.
   - Stop and re-plan if a reviewer wants a new spec section instead of the
     in-file [SC-7] edit.

3. **Add the `local` kind to the shared live test.**
   - Files: `tests/live/test_live_llm.py`, plus a committed template
     `tests/live/fixtures/extra-openai-models.yaml.tmpl` (single source of the
     entry shape).
   - Add constants: `DEFAULT_BACKSTITCH_LOCAL_LLM_MODEL` (the resolved default),
     `DEFAULT_LOCAL_ENDPOINT = "http://localhost:11434/v1"`.
   - Read kind: `kind = os.environ.get("BACKSTITCH_LIVE_LLM_KIND", "openai")`.
     Keep `openai` behavior identical (default) so the cloud lane is unchanged.
   - For `kind == "local"` (use the `monkeypatch` fixture; add it to the test
     signature):
     - Create `tmp_path/"llm-home"` (must exist first). Write
       `extra-openai-models.yaml` there with the full **three-key** entry:
       `model_id: backstitch-local`, `model_name: <server_model>`,
       `api_base: <endpoint>`, plus an `options` block setting a small
       `num_ctx` to bound KV-cache memory. Omit any key field (keyless).
     - `monkeypatch.setenv("LLM_USER_PATH", str(llm_home))` and
       `monkeypatch.setenv("LLM_MODEL", "backstitch-local")`.
     - Reachability preflight: `GET <endpoint>/models` via `urllib`; assert the
       response lists `<server_model>` (or the id `analyze` will send). Fail
       clearly if unreachable or the model is absent.
     - Transport preflight (in-process, env already set): resolve
       `llm.get_model("backstitch-local")`, assert its `api_base` equals
       `<endpoint>`, then `.prompt("Reply with the single word OK").text()` and
       assert non-empty. Hard assertion.
   - `_resolve_live_model()` needs no change for local: `needs_key` is `None`,
     so its credential preflight is skipped. It returns `"backstitch-local"` via
     `LLM_MODEL`.
   - Shared flow runs unchanged (`_run_cli` inherits the env). Keep
     `assert analyze returncode == 0` (total-failure guard).
   - Make the row-error assertion conditional:
     `if kind == "openai" or os.environ.get("BACKSTITCH_LIVE_LLM_STRICT") == "1": assert not errored`.
     Keep row `validate_analysis_row` checks and `load_analysis_results().errors == ()`
     for all kinds.
   - What stays real: CLI subprocesses, packet generation, `default_adapter`,
     the real local HTTP call, result validation. Nothing mocked; only skip is
     the opt-in gate off.
   - Done: with a local server up,
     `BACKSTITCH_LIVE_LLM=1 BACKSTITCH_LIVE_LLM_KIND=local uv run pytest -m
     live_llm -q` passes; the hermetic job's skip-proof step still passes
     (module skips as a unit when the gate is off). Update the ci.yml comment
     that says "exactly one skipped test" if the collection count changes (it
     should not: still one test).

4. **Document local usage and provisioning.**
   - Files: `README.md`,
     `docs/implementation/04-backstitch-style-traceability.md`.
   - Default Ollama provisioning, with an absolute cache dir:
     - `docker run -d --name backstitch-llm -p 11434:11434 -v "$PWD/.ollama-cache:/root/.ollama" ollama/ollama`
     - `docker exec backstitch-llm ollama pull <model>`
     - `BACKSTITCH_LIVE_LLM=1 BACKSTITCH_LIVE_LLM_KIND=local uv run pytest -m live_llm -q`
   - State the CPU/memory expectation (3B-class, ~2 GB weights, non-GPU), the
     slow-inference/one-packet tradeoff, the documented alternative servers, and
     that a small model's classifications are advisory — the lane proves
     plumbing, not judgment.

5. **Add the GitHub Actions `local-llm` job.**
   - File: `.github/workflows/ci.yml` (the `on:` block already has `push`,
     `pull_request`, `workflow_dispatch`).
   - `needs: test`. Initial `if:`
     `${{ github.event_name == 'workflow_dispatch' || github.event_name == 'push' }}`
     (not `pull_request` yet — see Rollout/Threat Model). Non-required.
   - Steps, in order (the ordering is load-bearing for the cache):
     1. `actions/checkout@v4`.
     2. `actions/cache` restore/save on an **absolute** dir
        (e.g. `/home/runner/.ollama-cache`), key includes the model tag.
     3. `docker run -d` the **digest-pinned** `ollama/ollama` mounting that exact
        dir at `/root/.ollama`; handle root-owned files (`--user $(id -u)` or
        `sudo chown` before save).
     4. `docker exec ... ollama pull <tag>` (fast/no-op on cache hit).
     5. Health poll `GET <endpoint>/models` (and/or native `/api/tags`) in a
        bounded loop until the tag is present — this closes the serve/pull race.
     6. `uv sync --extra dev`.
     7. Run with `BACKSTITCH_LIVE_LLM=1 BACKSTITCH_LIVE_LLM_KIND=local` and the
        endpoint/model as **workflow constants**; `timeout-minutes: 15`.
     8. Always (`if: always()`) emit `free -m` and `docker logs backstitch-llm`
        (no secrets) so a timeout can be told apart from a memory or model
        problem.
   - Model tag, endpoint, image digest, and `num_ctx` are workflow-controlled,
     never fork-supplied. If per-run cost is high, add a `paths` filter — a named
     tradeoff, not a silent cap.

6. **Traceability reconciliation.**
   - Files as needed: `docs/implementation/02-repository-map.md`,
     `04-backstitch-style-traceability.md`, `README.md`, this plan's log.
   - Ensure specs, plan, module, workflow, docs form a closed chain; run the
     final gates with zero errors and zero warnings.

## Testing Plan

Hermetic proof primary and unchanged: `uv run pytest tests -q` passes with no
server and no credentials; the module skips when `BACKSTITCH_LIVE_LLM` is unset;
unexpected endpoint/provider activity in the hermetic job is a failure.

Local live proof (server running):

- `BACKSTITCH_LIVE_LLM=1 BACKSTITCH_LIVE_LLM_KIND=local uv run pytest -m live_llm -q`
- Strict variant (known-good model):
  add `BACKSTITCH_LIVE_LLM_STRICT=1` to also require no error rows.

Anti-mocking: the local test must not fake the model boundary, subprocesses,
packet generation, HTTP transport, or validation. Only the opt-in gate skips.

Invariants protected: no-network default; real adapter + real transport + parse
+ validation + containment health on genuine output; non-total-failure; no
classification-based CI failure.

## Verification And Gates

Per-task gates above. Final:

```bash
uv run pytest tests -q
uv run ruff check .
uv run mypy backstitch
uv run backstitch check --repo-root .
```

Local live gate (server available):

```bash
BACKSTITCH_LIVE_LLM=1 BACKSTITCH_LIVE_LLM_KIND=local uv run pytest -m live_llm -q
```

Observed-success signals: transport preflight returns non-empty text and the
resolved `api_base` matches the endpoint; `analyze` exits 0 (not 2); one
schema-valid row per packet; clean `load_analysis_results`; hermetic CI passes
with the module skipping; `local-llm` job passes on `push`/`dispatch`; no secret
values in logs (the lane has none).

Residual risk to name at completion:

- CPU inference is slow; one packet is intentional. Cold model load + small-model
  swap against a 7 GB ceiling can trip the 15-min timeout — the `free -m`/docker
  logs step is what distinguishes memory-floor from model flake.
- `analyze` exposes no `max_tokens`; output length is bounded only by the yaml
  `num_ctx` and the model. A verbose model on a larger packet can approach the
  timeout.
- Small models produce malformed output often; the lenient contract accepts it.
  `BACKSTITCH_LIVE_LLM_STRICT=1` must not be a required gate without a strong
  model.
- Model tags/images drift; the default needs periodic re-check.
- Fork-PR graduation is a distinct, higher-bar step with the Threat Model
  prerequisites; until then the lane does not run on PRs.
- The lane proves plumbing, not judgment quality.

## Independent Review Incorporation

Two independent reviewers (adversarial + feasibility) read the plan, the delta,
the landed module/workflow, and the installed `llm` 0.31 source.

Feasibility review:

- **Missing `model_id` yaml key would hard-crash** (`KeyError`). Fixed: Task 3
  and the committed template specify the full three-key entry.
- **`needs_key=None` is automatic with `api_base`** — no dummy key. Fixed:
  removed dummy-key advice; documented `api_key_name:` for future token servers.
- **`LLM_USER_PATH` honored live; subprocess-only claim unnecessary.** Fixed:
  Hidden Couplings now states in-process resolution works and the analyze
  subprocess inherits the env.
- **Cache path/ownership trap** (root-owned volume vs runner user; `~` vs
  absolute path). Fixed: Task 5 requires one absolute path and `--user`/`chown`.
- **Timeout is the top failure; no output budget.** Fixed: `num_ctx` in the yaml,
  `free -m`/docker-logs diagnostics, named `llama3.2:1b` fallback.
- **`check` exit-0 couples the live run to a clean corpus** — bites on fork PRs.
  Fixed: Hidden Couplings + Rollout make relaxing it a graduation prerequisite.
- **Model_name vs Ollama tag** must be one canonical value. Fixed: Hidden
  Couplings; reachability preflight catches a mismatch.
- **Health-check `/api/tags` confirms the pull finished.** Folded into Task 5.

Adversarial review:

- **"Config binds at import" was false** and load-bearing for a wrong design.
  Fixed: removed; corrected mechanism recorded with the reason to still prefer
  env-parity.
- **Dummy-key branch is dead advice.** Fixed (see above).
- **Transport preflight didn't guarantee `analyze` uses the same resolution.**
  Fixed: single `os.environ` mutation + `_run_cli` inheritance; preflight
  asserts resolved `api_base == endpoint`.
- **Fork-PR threat model is more than secret theft** (runner abuse, SSRF pivot,
  resource DoS). Fixed: new Threat Model section; workflow-controlled
  image/model; start off-PR.
- **Lenient contract satisfiable entirely by `_error_record`.** Fixed: keep
  `assert analyze exit 0` (exit 2 == all errored) as the total-failure guard;
  the delta now requires failing on total failure.
- **Shared module + ci.yml already exist at `503a93e`.** Fixed: Baseline,
  Relationship, and Tasks now extend the landed files, not create them.
- **Reachability endpoint math ambiguous.** Fixed: pinned to `GET
  <endpoint>/models` and assert the model is listed.
- **Memory-floor timeout confound.** Fixed: diagnostics + `num_ctx` + fallback.
- **Spec-delta wording could diverge from intent.** Fixed: the [SC-7] insert now
  binds the proof to the analyze-path resolution and requires total-failure to
  fail.

Both reviewers verified the central claim — real adapter reaches a local Ollama
server via `extra-openai-models.yaml`/`api_base`, no plugin, no key, no runtime
change — holds against `llm` 0.31.

## Out Of Scope

- Changing `backstitch/` runtime modules to know about providers/endpoints.
- Adding `llm-ollama` or any Python package / `llm` plugin.
- Making semantic classification fail CI.
- Making `BACKSTITCH_LIVE_LLM_STRICT` a required gate on first landing.
- Running fork-PR local CI before the Threat Model prerequisites are met.
- Running a full-repository local semantic review per CI run.
- Replacing the cloud live lane; the lanes coexist.
- GPU inference or larger-than-runner models as the committed default.

## Open Questions For The User

- **Default local model.** Both reviewers independently recommended reconsidering
  `qwen2.5-coder:3b` in favor of `llama3.2:3b` for cleaner JSON on a
  format-shaped, plumbing-only lane (code reasoning matters less here than output
  stability). Current choice: `qwen2.5-coder:3b` per your selection, with
  `llama3.2:3b`/`llama3.2:1b` documented as drop-ins. Resolve before Task 2.
- **PR trigger.** Initial scope is `workflow_dispatch` + `push` (conservative,
  reviewer-endorsed). Graduating to fork PRs is the Threat-Model-gated step.
