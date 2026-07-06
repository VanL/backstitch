# Local LLM Evaluation Lane

Status: implementation complete. The local live gate now passes on local
hardware with the bounded `llama3.2:3b` default: on a 16 vCPU / 16.8 GB
Docker Desktop VM (2026-07-06), `num_ctx 4096` / `num_predict 1024` /
`temperature 0` passed 7 of 8 gate runs at ~25-40 s each. The earlier
2 CPU / 8 GB timeouts were an artifact of that simulated floor, not of the
models. The workflow stays manual `workflow_dispatch` until a dispatch on
the actual GitHub target runner (public repo, 4 vCPU / 16 GB) passes. The
~1-in-8 borderline-output flake originally named here was subsequently
eliminated by adapter-level constrained decoding
(`docs/plans/2026-07-06-analyze-json-mode-plan.md`): post-change, 8/8 gate
runs with zero contained error rows on the same hardware.
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

- Exercise the real (non-fake) `default_adapter` → HTTP → parse → validation
  path against a genuine model with **no provider credential** — proving at least
  one healthy end-to-end generation plus valid-row handling. It does **not** claim
  every per-packet call is healthy: small models blip, and the lenient contract
  tolerates individual per-packet errors (see the success contract).
- Later — via a **separate, threat-model-gated graduation plan** (not designed
  here) — give fork/internal PRs a real-model lane the secret-gated cloud lane
  structurally cannot provide.
- Keep the local model provisioned in a manual GitHub Actions lane with **cached
  model weights** (image caching is optional — GitHub runners do not persist
  Docker layers between jobs), spun up locally on non-GPU hardware. Weights are
  **tag-trusted** (record the resolved Ollama manifest digest for traceability);
  byte-level reproducibility across upstream tag moves is not claimed.
- Preserve the current no-network default test contract; add no Python package.
- Follow the repo's spec-changing workflow: plan → independent review →
  spec-promotion slice → implementation against the promoted spec.

## Relationship To The Cloud Live Lane (already landed)

The cloud/OpenAI live lane and its plan landed during this plan's authoring
(`c2aad73` module + marker, `503a93e` workflow, `605cf8d` the sibling plan,
`09c9f9c` release machinery). This plan **extends** those existing files; it
does not create them. Read the current landed module before editing — its shape
is load-bearing and changed during authoring:

1. Skip is **function-level** via `pytestmark = [live_llm, skipif(BACKSTITCH_LIVE_LLM != "1")]`,
   deliberately **not** a module-level skip, so the test is still *collected* and
   reported skipped (a module-level skip makes `pytest tests/live/…` collect
   nothing and exit 5, failing the hermetic skip-proof step). `import llm` lives
   **inside** the test body (`_resolve_live_model`), keeping collection
   hermetic. The local kind must keep all endpoint imports/HTTP/`llm` use inside
   the test body — never at module import.
2. `_resolve_live_model()` resolves the model **in-process** via
   `llm.get_model(model_name)` and drives its credential preflight off
   `model.needs_key`; a keyless model (`needs_key` falsy) is explicitly allowed
   with no credential — exactly the local case. It is the **first statement** of
   the test, so `LLM_USER_PATH`/`LLM_MODEL` for the local kind must be set
   *before* it runs (see Hidden Couplings).
3. `_run_cli(...)` runs `sys.executable -m backstitch ...` **without** an `env=`
   override, so subprocesses inherit the test process's `os.environ`. Setting
   `os.environ["LLM_USER_PATH"]`/`LLM_MODEL` once makes the in-process transport
   preflight and the `analyze` subprocess resolve the **same** `backstitch-local`
   registration.
4. `DEFAULT_LIVE_PACKETS = 1`. At one packet the local lenient contract is
   **vacuous** (see Hidden Couplings): the local kind must use ≥2 packets.

The local kind is added **inside** the existing single test
`test_live_llm_analysis_contract` (keyed on a new `BACKSTITCH_LIVE_LLM_KIND`
env), not as a parallel module or a second test, so collection and the
hermetic skip-proof step are unaffected.

## Source Documents

- `docs/specs/02-backstitch-core.md` [SC-5], [SC-6], [SC-7]
- `docs/specs/03-backstitch-configuration.md` [CFG-5], [CFG-9]
- `docs/plans/2026-07-03-live-llm-tests-plan.md` (sibling cloud lane, landed)
- `tests/live/test_live_llm.py` (the module this plan extends — read first)
- `.github/workflows/ci.yml` (read first; the release-gated `CI` workflow — this
  plan does **not** edit it) and the **new** `.github/workflows/local-llm.yml`
  this plan adds
- `.github/workflows/release-gate.yml` + `.github/scripts/require_green_workflows.py`
  (why the local lane must be a separate workflow — read first)
- `tests/test_release_workflow.py` (guards the workflow shape — see Hidden
  Couplings; must stay green — `ci.yml` is untouched by this plan)
- `backstitch/analysis_llm.py` (`default_adapter`, `_error_record`,
  `analyze_exit_code`: exit 2 on total failure — every produced row errored, or
  a pre-analysis invocation/model/output error; exit 0 on partial) and
  `backstitch/cli.py` (`_cmd_analyze` returns that exit code) — the real
  boundary; unchanged by this plan
- `docs/implementation/04-backstitch-style-traceability.md`,
  `docs/implementation/02-repository-map.md`
- `docs/agent-context/runbooks/writing-plans.md` §4b–§4d, `hardening-plans.md`,
  `testing-patterns.md`
- `llm` OpenAI-compatible config (re-check; URLs drift):
  <https://llm.datasette.io/en/stable/other-models.html>. Verified against
  installed `llm` 0.31: an `extra-openai-models.yaml` entry reads only
  `model_id`, `model_name`, `api_base`, capability flags, and `api_key_name`;
  `SharedOptions` exposes `max_tokens`, **not** `num_ctx` (so context/KV-cache
  bounds are an Ollama-server concern, not an `llm` yaml option). `api_base`
  sets `needs_key = None` and `llm` sends a placeholder `api_key="DUMMY_KEY"`
  the server ignores — no provider credential required. `llm.user_dir()` reads
  `LLM_USER_PATH` live and model registration is uncached, so in-process
  resolution after setting the env var works.
- Ollama OpenAI compatibility: <https://docs.ollama.com/api/openai-compatibility>;
  image `ollama/ollama` (pin by digest in CI); context bound via `OLLAMA_CONTEXT_LENGTH`
  / a Modelfile `PARAMETER num_ctx`, not `llm`. Documented alternatives (not the
  default): llama.cpp server `ghcr.io/ggml-org/llama.cpp:server`, LocalAI.
- GitHub Actions: caching <https://github.com/actions/cache>; fork-PR / secret
  behavior and first-time-contributor approval
  <https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows>

## Spec Baseline

- `09c9f9c` (repo HEAD at plan revision) for `docs/specs/02-backstitch-core.md`
  and `docs/specs/03-backstitch-configuration.md`. `2ed88ea` promoted the
  optional-live-test wording into [SC-7]/[CFG-9]; this plan **rewrites** the
  [SC-7] failure sentence into cloud-vs-local contracts and adds a local
  paragraph (see Proposed Spec Delta). The landed module, workflow, and sibling
  plan are all at or before HEAD; the repo was committed to actively during
  authoring, so re-confirm HEAD and the module shape at implementation start.
- Worktree note at revision: modified files under `docs/agent-context/`;
  untracked plan files under `docs/plans/`. The governing spec files, the live
  module, and the workflow were committed/clean.
- Promotion baseline identifier: worktree after spec-promotion slice, diff base
  `09c9f9ca21cbcbb8558d03da98568270ed32fdab`; promoted spec files
  `docs/specs/02-backstitch-core.md` and
  `docs/specs/03-backstitch-configuration.md`; verified with
  `uv run backstitch check --repo-root .` (exit 0, zero errors, zero warnings).

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [SC-7] | Task 3: measure K (prompt bytes/token) during the bake-off and derive the byte ceiling from the recorded value | `LOCAL_ASSUMED_BYTES_PER_TOKEN = 4` assumed (top of the plan's ~3–4 range); the ceiling's context term now reads `OLLAMA_CONTEXT_LENGTH` at runtime so it cannot desync from the workflow | the local bake-off ran under a CPU/memory simulation without token accounting, so no measured K exists yet | none — measure K during the target-runner bake-off and replace the assumption |

## Context and Key Files

See Source Documents for the landed files. Key current behavior:

- `analysis_llm.py`: `default_adapter` calls `llm.get_model(...).prompt(prompt).text()`
  (non-streaming). `_error_record` turns any per-packet failure into a
  **schema-valid** `ambiguous` row carrying an `error` field. `analyze_exit_code`
  returns **exit 2 on total failure** (every produced row errored — or a
  pre-analysis invocation/model/output error), exit 0 on partial. Unchanged.
- `tests/live/test_live_llm.py`: see Relationship. The cloud load-bearing
  assertion is `assert not errored`; this plan makes it conditional on
  kind/strictness and adds the `local` branch with ≥2 packets.
- `.github/workflows/ci.yml`: the release-gated `CI` workflow (`hermetic` job +
  secret-gated `live-llm` job). This plan does **not** edit it; the local lane is
  a **separate** `.github/workflows/local-llm.yml` so a flaky Ollama job cannot
  gate the `CI` workflow that `release-gate.yml` requires green (see Hidden
  Couplings).

Comprehension checks before editing:

1. `_resolve_live_model()` is the first line of the test and `DEFAULT_LIVE_PACKETS = 1`.
   What must be true about *where* the local env setup runs and *how many*
   packets the local kind uses, and why does one packet make "tolerate
   individual error rows" meaningless (1 error of 1 = total failure = `analyze`
   exit 2)?
2. `SharedOptions` has no `num_ctx`. Where must a context/memory bound for the
   local model actually be set, and why is putting `num_ctx` in
   `extra-openai-models.yaml` a no-op?
3. `release-gate.yml` requires the whole `CI` workflow green
   (`require_green_workflows.py --workflow "CI"`) and `ci.yml`'s `on: push` is
   unconstrained. Why must the local lane be a **separate** workflow file (not a
   job in `ci.yml`), and what would a flaky Ollama job in `ci.yml` do to releases
   and to release-tag pushes?

## Invariants and Constraints

Inherited (must still hold): default suite stays no-network; live path gated by
`BACKSTITCH_LIVE_LLM=1` (function-level `skipif`; test collected, reported
skipped, never fails when unset); real CLI path only (`packets` → `analyze` →
`summarize-analysis`); model sees only Backstitch packets; subset small and
deterministic (≤5); assertions structural, never model wording; semantic
findings advisory, never CI-failing by classification ([SC-7]).

New to the local lane:

- **No new Python dependency.** Reached through `llm`'s built-in
  OpenAI-compatible support via `extra-openai-models.yaml`. Do **not** install
  `llm-ollama` or any plugin, and do not add an HTTP client dependency —
  analysis goes through `default_adapter`; the reachability/transport preflight
  uses the standard library (`urllib`), and its `import llm`/`urllib` stays
  inside the test body (collection must remain hermetic).
- **No provider-specific runtime code in `backstitch/`.** Endpoint/model wiring
  lives only in `extra-openai-models.yaml`, the test, CI, and docs.
- **No provider credential required; a placeholder key is sent.** `api_base` ⇒
  `needs_key = None` in `llm` 0.31, and `llm` sends `api_key="DUMMY_KEY"` (which
  Ollama ignores). Do **not** add or rely on `OPENAI_API_KEY`. A future server
  that *requires* a bearer token gets an `api_key_name:` in its yaml entry and
  its own env var — never reuse `OPENAI_API_KEY` or the cloud secret.
- **Do not mutate the developer's global `llm` config.** The test writes its
  `extra-openai-models.yaml` into a per-test temp dir (created **before** any
  resolution — a missing `extra_path` is a silent no-op in `llm`) and points
  `LLM_USER_PATH` at it via `monkeypatch`; env is restored after the test.
- **Local env is set before `_resolve_live_model()`.** `LLM_USER_PATH` and
  `LLM_MODEL="backstitch-local"` must be set before the test's first statement,
  or resolution silently falls back to the cloud/default model. Preflight and
  `analyze` therefore share resolution via `_run_cli`'s env inheritance; the
  transport preflight asserts the resolved model's `api_base` equals the
  configured endpoint.
- **Transport proven separately from analysis-JSON quality.** Before the analyze
  run, a subprocess (the same resolution path `analyze` inherits) generates one
  real completion through `backstitch-local` and must return non-empty text.
  Hard assertion. This preflight plus the total-failure guard is the transport
  proof; a transient per-packet call failure mid-run (recorded as an error row)
  is tolerated in non-strict, since ≥1 successful row already shows transport
  works. The fixed `"Reply with … OK"` probe is a **transport health check, not
  semantic analysis** — it feeds the model no repository content, so it does not
  breach the [SC-7] packet boundary (which forbids the model roaming the repo
  outside packets). The spec delta carves this out explicitly.
- **Local kind uses ≥2 packets.** With one packet a single malformed row is
  *total* failure (`analyze` exit 2) and the lenient contract has no effect. Use
  a small local subset of at least two (`DEFAULT_LOCAL_LIVE_PACKETS`, initial
  value 3, ≤ `MAX_LIVE_PACKETS`) so tolerating an individual error row is
  distinguishable from total failure.
- **Total analysis failure still fails, even lenient.** Keep the landed
  `assert analyze returncode == 0` (exit 2 = all errored). Only the per-row
  `assert not errored` is relaxed for the local kind.
- **Lenient about model quality.** Individual per-packet model-quality error
  rows are **not** failures for `kind == "local"` unless
  `BACKSTITCH_LIVE_LLM_STRICT=1`. Load-bearing proof: transport + parse +
  validation + containment health + non-total-failure — not clean
  classifications.
- **Reachability means "the OpenAI surface serves this model."** Preflight hits
  `GET <endpoint>/models` (the `/v1` surface `analyze` uses) and asserts the
  target model id is listed — not merely that a socket answered.
- **CPU-only, memory-bounded.** Prefer a **3B-class 4-bit model** only if it fits
  the smaller floor; otherwise use the named low-memory fallback. Name the target
  runner class in the workflow and cite current specs: `ubuntu-latest` is
  **4 vCPU / 16 GB** for public repos and **2 vCPU / 8 GB** for private
  (re-check GitHub's runner docs at implementation — specs drift). Design to the
  private **2 vCPU / 8 GB** floor unless the workflow explicitly targets a larger
  class. Bound context/KV-cache on
  the **Ollama server** via a concrete `OLLAMA_CONTEXT_LENGTH` (a named constant,
  initial value **4096**, set once as a workflow env and mirrored in docs),
  **not** via the `llm` yaml (`num_ctx` is not an `llm` option). The Task 3
  bake-off validates 4096 against the actual selected packet sizes and the 8 GB
  floor and adjusts it there if needed. The initial implementation uses
  `qwen2.5:0.5b` only as a lower-cost manual default after `llama3.2:3b`,
  `llama3.2:1b`, and `qwen2.5-coder:0.5b` failed the local 2 CPU / 8 GB
  approximation; it is not a proven passing default. A 7B model is only for
  confirmed 16 GB runners.
- **Fatal vs best-effort.** Fatal: model unresolved, endpoint unreachable or
  model absent from `/models`, transport preflight empty or wrong `api_base`,
  any CLI subprocess unexpected exit (including `analyze` exit 2), row
  schema/packet-id invalid, `load_analysis_results` load errors. Best-effort
  (not fatal for local non-strict): individual packet rows carrying an `error`
  field. The lenient assertion keys only on the `error` field — a plain
  `ambiguous` classification without an `error` field is legitimate model
  judgment, never a failure.

## Hidden Couplings

- **One-packet leniency contradiction.** The local kind must default to ≥2
  packets or the lenient contract is dead (see Invariants). Gate the packet
  count on kind: `DEFAULT_LOCAL_LIVE_PACKETS` for local, `DEFAULT_LIVE_PACKETS`
  (1) for cloud.
- **Env-before-first-statement.** `_resolve_live_model()` runs first. Set the
  local `LLM_USER_PATH`/`LLM_MODEL` in a step that executes before it (e.g. a
  small setup at the very top of the test, guarded on `kind == "local"`, or a
  fixture that runs first) — not in a branch appended after the existing first
  line.
- **`num_ctx` is not an `llm` option.** Bounding memory belongs on the Ollama
  server side; the `extra-openai-models.yaml` entry has exactly three keys
  (`model_id: backstitch-local`, `model_name: <tag>`, `api_base: <endpoint>`)
  plus optional capability flags. A `num_ctx` there is silently ignored.
- **Separate workflow, outside the release gate.** Do **not** add `local-llm` to
  `ci.yml`. `ci.yml` is `name: CI`, and `release-gate.yml` requires the whole
  `CI` workflow green (`.github/scripts/require_green_workflows.py --workflow
  "CI"`), so a flaky local Ollama job in `ci.yml` would block releases even when
  it is "non-required" in branch protection. Also `ci.yml`'s `on: push` is
  unconstrained and fires on release **tag** pushes. Put the lane in a **new**
  workflow file `.github/workflows/local-llm.yml` with `name: local-llm` (not
  `CI`). Because the current model/default did not pass locally, land it as
  manual `workflow_dispatch` only; add `push: main` later only after a
  target-runner pass. This also leaves the existing
  `tests/test_release_workflow.py` guard (which slices `ci.yml`) untouched, and
  the guard-placement problem (`local-llm` before `live-llm`) disappears.
- **`_run_cli` inherits `os.environ`.** Do not add an `env=` override that drops
  `LLM_USER_PATH`/`LLM_MODEL`; that would re-route `analyze` to the global config
  while the preflight passed.
- **Release-helper env coupling.** `bin/release.py` runs
  `tests/live/test_live_llm.py` with `BACKSTITCH_LIVE_LLM=1` but does not pin
  `BACKSTITCH_LIVE_LLM_KIND`. A maintainer shell exporting
  `BACKSTITCH_LIVE_LLM_KIND=local` would flip the release precheck into the
  Docker/Ollama path by accident. The release precheck must **pin
  `BACKSTITCH_LIVE_LLM_KIND=openai`** (or explicitly clear it) so the local kind
  never runs there; update `tests/test_release_script.py` to assert the pinned
  env shape.
- **`analyze` uses `--no-config` + explicit `--model backstitch-local`.** The
  endpoint binding comes from `LLM_USER_PATH`'s yaml, not backstitch config.
- **`check` exit-0 coupling.** The landed flow asserts `check` exit 0 (dogfood
  against a clean corpus). On the initial push/dispatch rollout the corpus is
  clean. **Before graduating to fork PRs**, a fork's WIP doc debt would make
  `check` exit 1 and fail the local test for unrelated reasons — graduation must
  relax this for the local kind or keep the job off fork PRs.
- **Model name identity (base vs served).** The yaml `model_name` is forwarded
  verbatim as the OpenAI `model` param and must equal the name Ollama actually
  serves: in CI the **served** model (`backstitch-local-model:latest`, created by
  the Modelfile and listed by Ollama with the explicit tag), in dev the pulled
  base tag. Keep `BACKSTITCH_LOCAL_LLM_SERVED_MODEL` = yaml `model_name` = the
  `/models`-listed name as one canonical value, and the **base** tag
  (`BACKSTITCH_LOCAL_LLM_BASE_MODEL`) as the separate pulled/cache-key value. The
  reachability preflight (`/models` lists the served name) catches a mismatch
  that would otherwise hide as a tolerated error row.
- **Docker model cache vs image cache.** The slow path is the ~2 GB model
  download, not the image. Cache the mounted weights dir keyed by model tag.
  Ownership/path trap: `ollama/ollama` writes root-owned files; `actions/cache`
  runs as the runner user. Use one **absolute** cache path (not `~`) mounted at
  the same path across steps, run the container as root (not `--user`, which
  breaks the entrypoint), and `sudo chown -R "$USER"` the cache dir before the
  save step, or the save silently skips and every run re-downloads.

## Proposed Spec Delta

Promotion strategy: **A — in-file edits to existing active sections.** [SC-7]
and [CFG-9] are active and mapped. This **replaces** one sentence in [SC-7]'s
optional-live-test paragraph (so cloud and local contracts do not contradict)
and **adds** a local paragraph; [CFG-9] gets an additive clarification. No
mapping-block change is required (no new `backstitch/` code path). The
spec-promotion slice also adds this plan to each spec's `## Related Plans`.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/02-backstitch-core.md` | A — in-file active edit (replace + add) | [SC-7], Related Plans |
| `docs/specs/03-backstitch-configuration.md` | A — in-file active edit | [CFG-9], Related Plans |

### `docs/specs/02-backstitch-core.md` [SC-7]

**Replace** this sentence in the "Optional live semantic-analysis tests…"
paragraph:

> Missing credentials must skip only when the live gate is not enabled; once the
> live gate is enabled, missing credentials, provider failures, malformed model
> output, and invalid result rows must fail the live test by assertion on
> per-row errors and analysis-load errors.

**with:**

> Missing credentials must skip only when the live gate is not enabled. Once the
> live gate is enabled, missing credentials, invalid result rows (schema or
> packet id), and analysis-load errors must fail the live test by assertion. The
> two targets have distinct, non-overlapping contracts:
>
> - A **cloud-provider** live test asserts model success: no result row carries
>   an `error` field (unchanged from prior wording). This per-row assertion is
>   not relaxed for cloud targets.
> - A **local-endpoint** live test (below) instead asserts a reachability and
>   transport proof plus a total-failure guard, and tolerates *individual*
>   per-packet error records — malformed model output or a transient per-packet
>   call failure, which the adapter records identically — unless a stricter
>   opt-in demands model success.

**Insert** this paragraph after that paragraph and before "Live semantic
findings remain advisory…":

> An optional live test may target a local, self-hosted, OpenAI-compatible model
> endpoint instead of a paid cloud provider, reached through `llm`'s standard
> OpenAI-compatible model configuration (`api_base`) with no additional package
> dependency and no change to the runtime adapter. It needs no provider
> credential (`llm` sends only a placeholder key the server ignores). It must use
> packets produced by deterministic mode, call the real adapter through the
> public `analyze` command over a bounded set of **at least two** packets (so
> tolerating an individual error record is distinguishable from total failure),
> and validate structured result JSONL. It must prove the endpoint served a
> generation **through the same adapter registration and environment that
> `analyze` inherits** (a subprocess exercising the same adapter and
> `LLM_USER_PATH` registration, using a fixed transport-health-probe prompt that
> feeds the model no repository content and so does not breach the packet
> boundary), and must fail if the analyze run reports total failure (every packet
> produced an error record). It must additionally prove that the `analyze`
> command's own calls reached the local endpoint (e.g. a request-count check), so
> the proof is that `analyze`'s real adapter→HTTP path ran — not merely that a
> separate preflight generation succeeded and some non-error row exists. It does
> not assert that every per-packet call had healthy transport, since an
> individual transient call failure is recorded like malformed output and is
> tolerated in non-strict mode. Because small local models legitimately emit malformed output
> and per-packet calls can blip, a local-endpoint test must not treat individual
> per-packet error records as failures unless a stricter opt-in explicitly
> demands model success. An unreachable endpoint, a model absent from the
> endpoint, or a failed transport proof is a failure once the live gate is
> enabled, and a skip when it is not. Because it needs no repository secret, a
> local-endpoint test is eligible to run in credential-free automation contexts,
> including forked pull requests, **only after an explicit threat-model-gated
> workflow change**; it is not enabled on forked pull requests by default. This
> does not change `analyze`'s exit-code contract or the advisory status of
> semantic findings.

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
> runtime modules. A local-endpoint live test uses an ephemeral per-test `llm`
> configuration directory (for example via `LLM_USER_PATH`) and does not read
> the global `llm` config; this wiring is outside Backstitch config and must not
> be treated as proof for any Backstitch config key.

(The final sentence was added during implementation review — opencode's
[CFG-9] isolation finding — and is part of the applied spec text.)

## Rollout And Rollback

Rollout sequence:

1. Independent review of this plan and the delta (done: three reviews below).
2. Spec-promotion slice: apply the delta; update `## Related Plans`; record the
   promotion baseline identifier. The default local model is decided by the
   Task 3 bake-off (see Decisions); candidates stay supported via
   `BACKSTITCH_LOCAL_LLM_BASE_MODEL`, so this does not block promotion.
3. Add the `local` kind to `tests/live/test_live_llm.py` (skip-by-default via the
   existing `skipif`) with the committed `extra-openai-models.yaml` template and
   the ≥2-packet local subset.
4. Add a **separate** `.github/workflows/local-llm.yml` (not in `ci.yml`, so it
   stays outside the release-gated `CI` workflow). **Initial scope:
   `workflow_dispatch` only, not `push` or `pull_request`** because the local
   live gate did not pass under the simulated floor. Add its firing guard test.
5. Document local provisioning and the manual workflow.
6. Graduate to fork PRs only after: pinned image digest + workflow-controlled
   model tag, cache path proven stable, `check` exit-0 relaxed for the local
   kind, and the Threat Model prerequisites. Record graduation as an explicit
   change, not a silent trigger edit.

Rollback: remove/disable the `local-llm` job; hermetic and cloud lanes untouched.
Code rollback isolated to `tests/live/`, the committed yaml template, the new
`.github/workflows/local-llm.yml` + its guard test, and docs (`ci.yml` is never
touched). Runtime modules do not change. If the spec wording proves too broad,
add a Deviation Log row and run a spec-revision slice.

One-way doors: none in the initial (non-PR) rollout. Graduating to fork PRs is
the higher-bar step, gated on the Threat Model prerequisites.

## Threat Model (fork-PR graduation)

"No secret" mitigates secret exfiltration only. A fork PR runs fork-authored
checked-out repo code (tests, scripts) while the workflow *definition* comes from
the base branch, so before the `local-llm` job runs on `pull_request`:

- Pin the Docker image by **digest**, not the floating `ollama/ollama` tag.
- Take the model tag, endpoint, image, and server context bound from
  **workflow-controlled constants**, never from fork-editable env or files.
- Rely on GitHub's "require approval for first-time contributors"; keep the job
  non-required.
- Treat per-PR cost as an abuse vector: a ~2 GB pull + CPU inference on every
  fork push is a resource-DoS surface. Bound with a `paths` filter and the hard
  `timeout-minutes`, and start from `workflow_dispatch` only so exposure is
  opt-in until the cache path and model choice are proven.
- Set `permissions: contents: read` (least-privilege `GITHUB_TOKEN`) on the job;
  use `pull_request`, never `pull_request_target` (which would run fork code with
  the base repo's token/secrets).
- Cache isolation: fork PRs must not write the trusted weights cache (cache
  poisoning). Use `actions/cache/restore` on untrusted events and
  `actions/cache/save` **only** on trusted events (`push`/`dispatch`); do not let
  a fork populate a cache key a trusted run later trusts.
- Base-controlled vs fork-controlled (resolve the apparent contradiction): for a
  `pull_request` event GitHub runs the **workflow definition from the base
  branch**, so the triggers, pinned image digest, model tag, endpoint, and
  context constants are base-controlled and not fork-editable. What *is*
  fork-authored is the **checked-out code** the job runs (`tests/live/…`, any
  invoked scripts). So the constants are safe, but the test code executes
  arbitrary CPU/network work in the job.
- `actions/checkout` with `persist-credentials: false`; treat the checked-out
  test code as untrusted regardless of the base-controlled constants.
- **Verify the base-vs-fork semantics before graduation.** The claim above (that
  `pull_request` runs the base-branch workflow definition, so the pinned image /
  model / env constants are not fork-editable) must be re-verified against
  current GitHub behavior at graduation time. If it is wrong, those "constants"
  are fork-editable and the whole threat model changes materially.
- **Explicit residual risk for fork graduation:** fork-authored `pytest` runs
  arbitrary code — outbound network, CPU burn within the timeout, env mutation,
  and edits to `tests/live/…` itself. A changed-files gate on
  `pyproject.toml`/`uv.lock` does **not** contain arbitrary test code. So fork-PR
  graduation must be a deliberate decision that either accepts this residual risk
  explicitly or restricts fork runs to **manual approval only** (not automatic on
  every fork push). This is a one-way-door-ish call and is out of scope for the
  initial `workflow_dispatch` rollout.
- Dependency policy: `uv sync` runs fork-controlled lockfiles. Run with locked,
  hash-pinned deps (no implicit resolution/build of fork-authored packages). This
  must be an **executable** gate before graduation — a workflow step that
  skips/fails the job when a fork PR changes `pyproject.toml`/`uv.lock` (e.g. a
  changed-files check), not prose policy.

## Tasks

1. **Independent plan review.** _(done — see Independent Review Incorporation.)_

2. **Spec-promotion slice.**
   - Files: `docs/specs/02-backstitch-core.md`,
     `docs/specs/03-backstitch-configuration.md`.
   - Apply the exact `## Proposed Spec Delta` (a **replace** plus an insert in
     [SC-7]; a replace in [CFG-9]); add this plan to each `## Related Plans` as
     `(implementing)`.
   - Record the promotion baseline identifier here.
   - Re-confirm HEAD and the live-module shape (the repo moved during authoring).
   - Verify: `uv run backstitch check --repo-root .` → exit 0, zero warnings.
   - Stop and re-plan if a reviewer wants a new spec section instead of the
     in-file [SC-7] edit.

3. **Add the `local` kind to the shared live test.**
   - Files: `tests/live/test_live_llm.py`. Render `extra-openai-models.yaml` at
     runtime from a Python dict via `json.dumps` (see below); do **not** commit a
     `.tmpl` and string-substitute into it — a committed template invites the
     unsafe substitution this plan forbids. Any committed YAML example is
     documentation-only and must not render the runtime file.
   - **Bake-off (do first):** run the local subset through both
     `qwen2.5-coder:3b` and `llama3.2:3b` on a 2 vCPU / 8 GB-class box; pick the
     one with fewer contained-error rows and lower latency as
     `DEFAULT_BACKSTITCH_LOCAL_LLM_BASE_MODEL`, **and tune `DEFAULT_LOCAL_LIVE_PACKETS`
     (2 or 3) and `OLLAMA_CONTEXT_LENGTH` jointly to fit the runner budget —
     start at 2 packets.** Record all three here. Candidate models stay
     first-class via `BACKSTITCH_LOCAL_LLM_BASE_MODEL`.
     Acceptance rule: if **both** 3B candidates exceed the 8 GB floor or the
     15-min budget for the ≥2-packet subset, choose a smaller default only if it
     actually passes the non-total-failure contract; otherwise keep the workflow
     manual-only and record the blocker. Do not raise the CI timeout to force a
     too-large model, and do not ship an automatic default that cannot pass on
     the standard runner. For reproducibility, run
     the bake-off **on the target GitHub runner (or under equivalent 2 vCPU / 8 GB
     cgroup limits)**, not just any laptop, and record: image digest, model tag,
     `OLLAMA_CONTEXT_LENGTH`, packet count, cold/warm latency, and peak memory.
     Implementation record: local Docker run against the pinned Ollama image
     `sha256:f1a705f2bd113fb8d15f85f7c217f0dc5f6bebda6b0cc42b82c3ad165ffcb9dc`,
     `llama3.2:3b`, `OLLAMA_CONTEXT_LENGTH=4096`, `num_predict=512`,
     `DEFAULT_LOCAL_LIVE_PACKETS=2`, and `--cpus 2 --memory 8g` timed out in
     `analyze` at 300 seconds before producing the two-packet result. After the
     selector was narrowed to the two smallest real packets and `num_predict` was
     reduced to 256, `llama3.2:1b` still timed out at 300 seconds,
     `qwen2.5-coder:0.5b` timed out at 300 seconds, and `qwen2.5:0.5b` completed
     but exited 2 because both rows were invalid (one non-JSON output, one
     invented evidence path). The workflow therefore lands as manual-only with
     `qwen2.5:0.5b` as a low-cost experimental default, not as a proven green
     canary. Add `push: main` only after target-runner evidence shows a model
     passes the non-total-failure contract.
     Follow-up record (2026-07-06): re-ran the bake-off on Apple-silicon
     Docker Desktop without the cgroup limits (16 vCPU / 16.8 GB VM), same
     pinned image digest (the floating tag equaled the pin that day),
     2-packet subset, ~25-40 s wall per full gate run. Unmodified
     `llama3.2:3b` with default sampling produced the first-ever green run
     of the local live gate; a repeat run hit the total-failure guard on an
     invented evidence line — roughly 50/50. Unmodified `qwen2.5:0.5b` again
     failed totally (evidence line outside the packet's shown content),
     consistent with the earlier 2 CPU / 8 GB record. Bounded `llama3.2:3b`
     via Modelfile (`num_ctx 4096`, `temperature 0`): `num_predict 256`
     passed 2/5 with "model output is not valid JSON" truncation failures;
     `num_predict 512` passed 4/5; `num_predict 1024` passed 7/8. The
     residual ~1-in-8 failure is borderline model-output validity —
     llama.cpp inference is not bit-deterministic even at temperature 0 —
     not timeouts and not transport. Winner adopted as the committed
     workflow default: `llama3.2:3b` at `num_ctx 4096` / `num_predict 1024`
     / `temperature 0` (temperature verified server-side). The 300 s
     per-call timeouts above were an artifact of the constrained simulated
     environment.
   - Constants (name base vs served distinctly to avoid the trap):
     `DEFAULT_BACKSTITCH_LOCAL_LLM_BASE_MODEL` (bake-off winner, the pulled tag)
     and `DEFAULT_BACKSTITCH_LOCAL_LLM_SERVED_MODEL` (`backstitch-local-model:latest`
     in CI, because Ollama lists created models with an explicit tag),
     `DEFAULT_LOCAL_ENDPOINT = "http://127.0.0.1:11434/v1"`,
     `DEFAULT_LOCAL_LIVE_PACKETS` (≥2, ≤ `MAX_LIVE_PACKETS`; the exact value is a
     **bake-off output** — start at 2 and only raise if the runner budget allows,
     since the selector's smallest-first sort still can't guarantee the 3 smallest
     eligible packets fit 4096 context and the 15-min budget on CPU).
   - `kind = os.environ.get("BACKSTITCH_LIVE_LLM_KIND", "openai")`. Keep `openai`
     behavior byte-identical (default) so the cloud lane is unchanged. **Hard-fail
     (`pytest.fail`) if `kind` is anything other than `openai` or `local`** — a
     typo must not silently fall through to cloud behavior or skip local setup.
   - Change the test signature to
     `test_live_llm_analysis_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch)`.
     The `local` setup block below is the **first thing** in the test body, before
     `live_model = _resolve_live_model()` — do not append it after that line.
   - When `kind == "local"`: create `tmp_path/"llm-home"` (must exist first);
     write `extra-openai-models.yaml` there with exactly this shape (no
     `num_ctx`, no key field), substituting the two values:

     ```yaml
     - model_id: backstitch-local
       model_name: "<server_model>"      # e.g. qwen2.5-coder:3b — the exact Ollama tag
       api_base: "<endpoint>"            # e.g. http://127.0.0.1:11434/v1
     ```

     then `monkeypatch.setenv("LLM_USER_PATH", str(llm_home))` and
     `monkeypatch.setenv("LLM_MODEL", "backstitch-local")`.
     **Generate the file safely:** build the entry as a Python dict and emit it
     with `json.dumps([record])` (JSON is valid YAML) — do **not** string-
     substitute into a hand-quoted template, since a `model_name`/`endpoint`
     containing quotes, `#`, `:`, or newlines (the local env contract lets users
     set these) would corrupt the YAML and mis-resolve the model.
   - Exact env contract read by the local kind (document these in Task 4). Split
     **base** from **served** model to avoid testing the unbounded pulled tag
     instead of the context-bounded created model:
     - `BACKSTITCH_LIVE_LLM` (gate), `BACKSTITCH_LIVE_LLM_KIND=local`.
     - `BACKSTITCH_LOCAL_LLM_BASE_MODEL`: the Ollama tag to **pull** (e.g.
       `qwen2.5:0.5b`); the manual workflow creates the served model from it via
       a Modelfile.
     - `BACKSTITCH_LOCAL_LLM_SERVED_MODEL`: the model name `analyze`/the yaml
       `model_name`/reachability/cache-key/bake-off record all use. In dev it may
       equal the base tag (default context); in the manual workflow it is
       `backstitch-local-model:latest` (the Modelfile-bounded model Ollama lists
       on `/v1/models`). Default `DEFAULT_BACKSTITCH_LOCAL_LLM_SERVED_MODEL`.
     - `BACKSTITCH_LOCAL_LLM_ENDPOINT` (default `DEFAULT_LOCAL_ENDPOINT`),
       `BACKSTITCH_LIVE_LLM_STRICT` (optional).
     Note: in the `analyze` subprocess the explicit `--model backstitch-local`
     wins; `LLM_MODEL` only feeds `_resolve_live_model` before the subprocess,
     and `LLM_USER_PATH` is what the subprocess actually needs to resolve the
     local registration.
   - Update the module docstring and the `assert not errored` comment, which
     currently state the load-bearing assertion is "no result row carries an
     `error` field" — that is the *cloud* contract; note the local kind's lenient
     contract so the extended file does not carry false guidance.
   - **Pin the release precheck (explicit files).** `bin/release.py` runs the live
     test with `BACKSTITCH_LIVE_LLM=1`; set `BACKSTITCH_LIVE_LLM_KIND=openai`
     (or clear it) there so a maintainer shell can't flip the precheck into the
     Docker path, and update `tests/test_release_script.py` to assert the pinned
     env shape. (Named as a task here, not only in Hidden Couplings.)
   - Select `DEFAULT_LOCAL_LIVE_PACKETS` packets for the local kind (the cloud
     kind keeps 1). Parameterize `_select_live_packets` on the count, and add a
     hard `assert len(subset) >= 2` for `kind == "local"` so a shrunken corpus
     cannot silently make leniency vacuous (one packet = total-failure semantics).
   - **Prompt-size budget:** the selector sorts by JSON *bytes*, not tokens, so
     future spec growth could push the "smallest N" past the context/timeout
     budget. Context is token-based; bytes are a crude proxy, so pick a
     **deliberately conservative** byte ceiling and record its derivation from the
     bake-off — e.g. `ceiling = OLLAMA_CONTEXT_LENGTH * K` where `K` (bytes/token,
     ~3–4 for English/code) is measured during the bake-off with margin for the
     model's output tokens. Assert each selected packet's built-prompt byte length
     is under that recorded ceiling, failing with a message that tells maintainers
     exactly how to shrink or retune the subset. Do not invent `K` at
     implementation time — take it from the recorded bake-off.
   - **Enforce "local".** The spec says *local, self-hosted*. Assert the endpoint
     host is loopback (`localhost`/`127.0.0.1`/`::1`) unless a deliberately named
     `BACKSTITCH_LOCAL_LLM_ALLOW_NONLOCAL=1` is set — otherwise a stray env or
     workflow edit could point the "local" proof at a remote unauthenticated
     endpoint, violating the spec boundary.
   - Preflights (`import llm`/`urllib` inside the test body):
     - Reachability: `GET` the joined URL `<endpoint>/models` (handle a trailing
       slash on `<endpoint>`) with an explicit `urllib` timeout; parse the OpenAI
       shape `{"data": [{"id": …}]}` and assert `<server_model>` appears in the
       ids. On connection error / non-200 / absent model, `pytest.fail` with the
       endpoint, the model, and the ids seen.
     - Transport (as a **subprocess** so it proves the same resolution + adapter
       `analyze` uses). The `sys.executable -c` body: (a) `m =
       llm.get_model("backstitch-local")`, assert keyless
       (`getattr(m, "needs_key", None) is None`) and `m.api_base == <endpoint>`
       — the contract is pinned to the `uv.lock` `llm` (0.31), which exposes
       `model.api_base`, so assert it equals the configured endpoint **after
       normalizing both sides** (strip a trailing `/`), since `llm` may normalize
       the value and an exact compare would false-fail a correctly-bound model.
       If the
       attribute is absent (`getattr(m, "api_base", _SENTINEL) is _SENTINEL`),
       **`pytest.fail` loudly** with an `llm`-version-drift message rather than
       silently degrading to "reachability + some text" — a bump that hides the
       binding must re-establish this check; (b)
       `adapter = default_adapter("backstitch-local")`
       — the exact function `_cmd_analyze` calls (`cli.py:589`), which returns
       only a callable, not the model — then `out = adapter("Reply with the
       single word OK")` and print `out`. The test asserts the subprocess exited
       0 and printed non-empty text. The keyless assertion doubles as the
       `llm`-version-drift guard (the repo pins only `llm>=0.31`), so a future
       `llm` that stops auto-nulling the key for `api_base` fails loudly here
       instead of silently requiring a credential.
   - `_resolve_live_model()` needs no change for local (`needs_key` is `None`).
   - **Prove `analyze` itself reached the local server** (the reason the lane
     exists — otherwise a regression that emits a canned valid row or routes to
     another model still passes the lenient floor). This needs **two named
     endpoints**: the **upstream** (`BACKSTITCH_LOCAL_LLM_UPSTREAM`, the real
     Ollama, e.g. `http://127.0.0.1:11434/v1`) and the **adapter `api_base`**,
     which points at a **stdlib counting proxy** on a separate `127.0.0.1` port
     that forwards to the upstream and counts requests. The yaml `api_base` and
     the reachability preflight both use the **proxy**; the proxy forwards to the
     upstream. Reset/record the count around the `analyze` phase specifically
     (excluding the transport preflight) and assert the proxy saw **≥
     number-of-packets** analyze requests (count any `POST` to a `/v1/*`
     completion path, not only `chat/completions`, so a future `llm` transport
     variant does not false-fail). This is the load-bearing "the real
     `default_adapter → HTTP` path ran through `analyze`" proof, distinct from the
     preflight's "a generation is possible." Strengthen it against a
     constant-prompt/canned-row defect: the proxy records analyze-phase request
     **bodies** and asserts (a) each selected packet id (or another packet-unique
     marker) appears in at least one analyze request body, and (b) the JSON
     `model` field equals the **served** alias. Register the model with streaming
     disabled (`can_stream: false` if supported) so the proxy is a dumb
     non-streaming forwarder for the exact `llm` 0.31 request shape and cannot
     deadlock/alter behavior; test the proxy itself.
   - Shared flow runs unchanged (`_run_cli` inherits the env). Keep
     `assert analyze returncode == 0` (total-failure guard).
   - Conditional row-error assertion:
     `if kind == "openai" or os.environ.get("BACKSTITCH_LIVE_LLM_STRICT") == "1": assert not errored`.
     For `kind == "local"` (non-strict), add an **explicit** floor rather than
     leaning on the exit-0/`errors`-list lockstep:
     `assert any("error" not in row for row in raw_rows)` and
     `assert len(errored) < len(raw_rows)` — so a regression that emits all-error
     rows but drops the `errors` list still fails. When
     `DEFAULT_LOCAL_LIVE_PACKETS >= 3`, require **≥2** non-error rows, so a
     systematic "first packet always works, later always fail" defect is caught
     rather than passing on one lucky row. Keep `validate_analysis_row`
     and `load_analysis_results().errors == ()` for all kinds.
   - **Subprocess timeouts.** `_run_cli` currently passes no `timeout=`, so a hung
     local model would hang pytest indefinitely. For the local kind, give the
     transport-preflight subprocess and the `analyze` call explicit `timeout=`
     values (e.g. 300 s), and fail with a clear message on `TimeoutExpired`, so a
     stuck server surfaces as a test failure rather than a silent hang that only
     the CI step timeout eventually kills.
   - Nothing mocked; only skip is the opt-in gate off.
   - Done: with a local server up,
     `BACKSTITCH_LIVE_LLM=1 BACKSTITCH_LIVE_LLM_KIND=local uv run pytest -m
     live_llm -q` passes (≥2 packets, lenient); the hermetic skip-proof step
     still passes (test collected, skipped).

4. **Document local usage and provisioning.**
   - Files: `README.md`,
     `docs/implementation/04-backstitch-style-traceability.md`.
   - Default Ollama provisioning, absolute cache dir:
     - `docker run -d --name backstitch-llm -p 127.0.0.1:11434:11434 -v "$PWD/.ollama-cache:/root/.ollama" ollama/ollama`
     - `docker exec backstitch-llm ollama pull <model>` (dev convenience; the
       manual workflow additionally bounds context via a Modelfile and pins the
       image by digest)
     - `BACKSTITCH_LIVE_LLM=1 BACKSTITCH_LIVE_LLM_KIND=local uv run pytest -m live_llm -q`
   - State the CPU/memory expectation (small CPU model, non-GPU), the
     slow-inference tradeoff, the documented alternative servers, and that a
     small model's classifications are advisory — the lane proves plumbing.
   - Note explicitly that the floating `ollama/ollama` tag in the local example
     is developer convenience; the **manual workflow pins the image by digest**
     as a security requirement (Threat Model), and the two must not be conflated.

5. **Add a separate `local-llm` GitHub Actions workflow.**
   - File: **new** `.github/workflows/local-llm.yml`, `name: local-llm` (NOT
     `CI` — see Hidden Couplings; it must stay outside the release-gated `CI`
     workflow). Do not edit `ci.yml`.
   - Trigger: `workflow_dispatch` only. The originally planned `push: main`
     post-merge canary is deferred because the implemented defaults did not pass
     the local live gate under the 2 CPU / 8 GB simulation. Broadening to
     `push`, all branches, or `pull_request` is a later cost-and-Threat-Model
     gated expansion after target-runner evidence exists.
   - Single job. Set `permissions: contents: read` (least-privilege
     `GITHUB_TOKEN`) **now** on the initial workflow (not deferred to graduation),
     and have the guard test assert it. Define `OLLAMA_CONTEXT_LENGTH` **once** as
     a workflow env (the bake-off value) and reference it everywhere rather than
     re-hardcoding the number.
   - Add a workflow-level `concurrency:` so two trusted runs don't race the save.
     `concurrency` expressions accept only `github`/`inputs` contexts (not `env`),
     so key it on a literal + `github.workflow`/`github.ref`, e.g.
     `concurrency: { group: 'local-llm-${{ github.ref }}', cancel-in-progress: false }`
     (do not try to interpolate the cache key from `env`). Regardless, make
     `actions/cache/save` **non-fatal** (`continue-on-error: true`) so a
     concurrent "key already exists" warns rather than fails; the "assert a
     trusted cold run saved" check (step 12) must distinguish "key already
     exists" (fine — a concurrent run won the race) from "save failed on
     permissions/unreadable files" (a real problem).
   - **Disk, not just memory.** `ubuntu-latest` has ~14 GB SSD. Docker layers +
     Ollama blobs + the created model + uv env + cache staging can exhaust it.
     Emit `df -h` before and after pull/save and treat disk exhaustion as a named
     failure mode.
   - **Forbid the non-local escape hatch in CI.** The guard test must assert the
     workflow does **not** set `BACKSTITCH_LOCAL_LLM_ALLOW_NONLOCAL`, so the
     credential-free "local" lane can never silently become a remote-endpoint
     lane in CI.
   - **Branch protection:** state that `local-llm` must **not** be a required
     status check until it has a stable run history — otherwise repo settings
     (not `release-gate.yml`) could let a flaky canary block merges.
   - Steps, in order (load-bearing for the cache):
     1. `actions/checkout@v4` with `persist-credentials: false`.
     2. **`astral-sh/setup-uv@v5` with `python-version: "3.14"`** (do not omit —
        the project requires `>=3.14`, there is no `.python-version` file, and
        `ci.yml` pins it the same way; the guard test asserts this).
     3. `actions/cache/restore` on an **absolute** dir (e.g.
        `/home/runner/.ollama-cache`); key includes the **base model tag**
        (`BACKSTITCH_LOCAL_LLM_BASE_MODEL` — **not** the stable served alias,
        which would never invalidate when the base changes), the context length,
        the pinned image digest, and a manual **cache-epoch** suffix. Note honestly: Ollama
        tags are **mutable** but GitHub caches are **immutable** — a moved tag
        keeps the same key, and on a cache hit the per-run `ollama pull` only
        refreshes the *ephemeral* local copy (it is not re-saved). So bumping the
        **cache-epoch** is the only persistent refresh lever; `ollama pull` alone
        does not update an existing cache key. Use the restore/save split (not the
        one-shot `actions/cache`) so the save happens after the final chown.
     4. `docker run -d` the **digest-pinned** `ollama/ollama` as **root** (do not
        use `--user` — it breaks the image entrypoint/`/root/.ollama` perms),
        binding **loopback only** (`-p 127.0.0.1:11434:11434`), mounting the cache
        dir at `/root/.ollama`.
     5. **Readiness poll before pull:** bounded loop until the server root
        answers, so `pull` does not race server start.
     6. Pull and bound context **via a Modelfile** (Ollama's OpenAI surface has no
        per-request context setting; `OLLAMA_CONTEXT_LENGTH` env behavior varies
        by version, so it is a fallback only if verified against the pinned
        image): `docker exec ... ollama pull <tag>` (no-op on cache hit), then
        `ollama create backstitch-local-model:latest` from a Modelfile
        (`FROM <tag>` + `PARAMETER num_ctx <ctx>` **and `PARAMETER num_predict <n>`**
        to cap output — `analyze` exposes no `max_tokens`, so a rambling CPU model
        can otherwise burn the whole timeout even with healthy transport; verify
        `num_predict` like `num_ctx`). The yaml `model_name` is
        `backstitch-local-model:latest`.
     7. **Model poll after pull:** bounded loop on `GET <endpoint>/models` until
        the served model is listed. Then **log both digests** as per-run
        evidence: the pulled **base tag** manifest digest and the **created served
        model** digest (read from `~/.ollama/models/manifests/…` or `ollama show`
        output — name the exact field/path in the workflow). The cache key is
        tag+image+epoch, not model digest, so a moved base tag changes weights and
        these recorded digests are the only per-run trace of what actually ran.
     7b. **Prove the context bound applied:** `ollama show backstitch-local-model:latest`
         and confirm the reported `num_ctx` equals `<ctx>`; fail the job if not —
         otherwise a silently-ignored bound lets the job OOM/timeout while every
         gate looks "implemented".
     8. `astral-sh/setup-uv@v5` is already step 2; `uv sync --extra dev --locked`
        (fail on lockfile drift — the local contract depends on `llm` 0.31
        internals). Log the resolved version
        (`uv run python -c 'import llm; print(llm.__version__)'`) as evidence the
        pinned contract held.
     9. Run with `BACKSTITCH_LIVE_LLM=1 BACKSTITCH_LIVE_LLM_KIND=local` and the
        endpoint/model as **workflow constants**. Set a **job-level**
        `timeout-minutes` (e.g. 20) *and* a smaller pytest-step
        `timeout-minutes: 15`, so a hung Docker pull cannot burn the whole job.
     10. `if: always()` emit `free -m` and **health-filtered**
         `docker logs backstitch-llm` (grep server/health lines only — verify the
         pinned image does not log request bodies, which would put packet content
         in CI logs; filter if it does) (no
         secrets) so a timeout is distinguishable from a memory/model problem.
     11. `if: always()` stop the container, then `sudo chown -R "$USER"
         <cache-dir>` — **after** inference, since the root container keeps
         writing weights/logs during the run; an early chown leaves post-run
         root-owned files the save cannot read.
     12. `actions/cache/save` gated on **successful provisioning** — reference
         the pull + model-poll steps' `outcome == 'success'` explicitly (so it
         saves after provisioning succeeded **even if the pytest step later
         failed**, but never after a failed/partial pull), **and** only on trusted
         refs (`github.ref == 'refs/heads/main'`). Do not use bare `success()` (a failed test
         would wrongly skip the save) or bare `always()` (would save a broken
         weights dir). This prevents both fork cache poisoning and trusted-run
         self-poisoning. Cleanup/logging/chown stay `if: always()`. Also skip the
         save when the restore was an **exact cache hit**. A bare `if:` is
         implicitly `success()`, so name the exact expression, e.g.:
         `if: ${{ !cancelled() && steps.pull.outcome == 'success' &&
         steps.model-poll.outcome == 'success' && steps.restore.outputs.cache-hit
         != 'true' && github.ref == 'refs/heads/main' }}`. Note the trusted clause
         is `github.ref == 'refs/heads/main'` — **not** "any `workflow_dispatch`":
         a manual run can target any ref, and allowing save on a non-main dispatch
         lets an experimental branch write the shared cache key. Either restrict
         save to the main ref (shown) or include the ref in the cache key. Do **not** set `restore-keys` (a partial-prefix
         match can carry stale weights into a fresh primary key). Make the save
         `continue-on-error: true` (a concurrent "key exists" should warn, not
         fail) **but** emit a `::notice::` and, on a trusted cold run
         (`cache-hit != 'true'`), assert a save actually occurred — otherwise a
         permissions mistake silently re-downloads gigabytes on every trusted manual run
         forever.
   - **Add a firing guard test** for the new workflow (enumerable-contract rule,
     [SC-10] / DoD): assert `.github/workflows/local-llm.yml` exists with
     `name: local-llm`; `on` has `workflow_dispatch`; there is **no** `push` or
     `pull_request` trigger (until a green target-runner default is proven);
     the job uses `setup-uv` with `python-version: "3.14"`, a **digest-pinned**
     image (`ollama/ollama@sha256:`), both job-level and step-level
     `timeout-minutes`, `OLLAMA_CONTEXT_LENGTH`, `num_predict`, the base/served
     model constants (`BACKSTITCH_LOCAL_LLM_BASE_MODEL`, `…_SERVED_MODEL` =
     `backstitch-local-model:latest`), and sets `BACKSTITCH_LIVE_LLM_KIND: local`,
     `permissions: contents: read`, and a `concurrency` key. Use a **pure-Python
     active-line parser** (no new tool dependency — do not add `actionlint` just
     for this): strip comments/blank lines, then assert on active lines, since
     PyYAML mis-parses the workflow `on:` key as boolean `True` and naive
     substring matching passes on a commented-out `pull_request`, a dead duplicate
     string, or changed indentation. Beyond existence, assert the
     **security/ordering** contract with targeted (ordered) text checks: the
     loopback port bind (`127.0.0.1:11434`), the `chown`/cache-save steps appear
     **after** the test step, the exact cache-save `if:` expression, **no**
     `restore-keys`, the restore and save `path:` are byte-identical, and the save
     references real step ids (`steps.pull`/`steps.model-poll`/`steps.restore`).
     Put it in `tests/test_release_workflow.py` (already covered
     by `ci.yml`'s `ruff format --check .` and its pytest run); this plan does not
     edit `ci.yml`.
   - Confirm `uv run pytest tests/test_release_workflow.py -q` still passes
     (unaffected — `ci.yml` is untouched). Model tag/endpoint/image digest/context
     are workflow-controlled. If per-run cost is high once graduated to PRs, a
     workflow-level `paths:` on `local-llm.yml` is now safe (it gates only this
     workflow, not `CI`) — a named tradeoff, not a silent cap.
   - **Implementation-time pins** (depend on artifacts not in front of us now, so
     they are resolved in this slice against the *exact* pinned image/action and
     recorded): the reliable `actions/cache/save` "saved" signal (if none exists,
     drop that assertion rather than claim it) and the exact `ollama show`/manifest
     field names for `num_ctx`/`num_predict`/digests.

6. **Traceability reconciliation.**
   - Files as needed: `docs/implementation/02-repository-map.md`,
     `04-backstitch-style-traceability.md`, `README.md`, this plan's log.
   - Ensure specs, plan, module, workflow, docs form a closed chain; run the
     final gates with zero errors and zero warnings.

## Testing Plan

Hermetic proof primary and unchanged: `uv run pytest tests -q` passes with no
server and no credentials; the test is collected and skipped when
`BACKSTITCH_LIVE_LLM` is unset; unexpected endpoint activity in the hermetic job
is a failure. The new `local-llm.yml` guard test must pass, and
`uv run pytest tests/test_release_workflow.py -q` must stay green (`ci.yml` is
untouched).

Local live proof (server running, ≥2 packets):

- `BACKSTITCH_LIVE_LLM=1 BACKSTITCH_LIVE_LLM_KIND=local uv run pytest -m live_llm -q`
- Strict variant (known-good model): add `BACKSTITCH_LIVE_LLM_STRICT=1` to also
  require no error rows.

Observed implementation result: the gate now passes locally with the bounded
`llama3.2:3b` default — 7 of 8 runs green at ~25-40 s per run on a 16 vCPU
Docker environment (2026-07-06). A dispatch on the actual GitHub target
runner remains the acceptance gate for enabling automatic triggers.

Anti-mocking: the local test must not fake the model boundary, subprocesses,
packet generation, HTTP transport, or validation. Only the opt-in gate skips.

Invariants protected: no-network default; real adapter + transport + parse +
validation + containment health on genuine output; non-total-failure; no
classification-based CI failure.

## Verification And Gates

Per-task gates above. Final:

```bash
uv run pytest tests -q
uv run pytest tests/acceptance -q          # [SC-10] probe suite — required by AGENTS.md DoD
uv run pytest tests/test_release_workflow.py -q
uv run ruff check .
uv run ruff format --check .
uv run mypy backstitch
uv run backstitch check --repo-root .
```

Local live gate (server available):

```bash
BACKSTITCH_LIVE_LLM=1 BACKSTITCH_LIVE_LLM_KIND=local uv run pytest -m live_llm -q
```

Observed-success signals: transport preflight returns non-empty text and the
resolved `api_base` matches the endpoint; **the counting proxy saw ≥ N analyze
requests** (the load-bearing "`analyze` hit the local endpoint" proof — do not
"complete" the lane without it); `analyze` exits 0 (not 2); one schema-valid row
per packet with **≥1 non-error row**; clean `load_analysis_results`; hermetic CI
passes with the test skipping. Separate **pre-merge static validation** (guard
test on `local-llm.yml`) from **manual live canary evidence** (the job actually
passing via `workflow_dispatch` on the target runner). No *provider* secret
values in logs (the model lane has no provider secret — the job still carries a
read-scoped `GITHUB_TOKEN`, which is why checkout uses `persist-credentials: false`).

Residual risk to name at completion:

- CPU inference is slow; ≥2 small packets still bound the run, but cold model
  load + small-model swap against a 8 GB ceiling can trip the 15-min timeout —
  the `free -m`/docker-logs step distinguishes memory-floor from model flake.
- `analyze` exposes no `max_tokens`; output length is bounded only by the Ollama
  server context and the model.
- Small models produce malformed output often; the lenient contract accepts
  individual error rows but still fails on total failure.
  `BACKSTITCH_LIVE_LLM_STRICT=1` must not be a required gate without a strong
  model.
- Model tags/images drift; the default needs periodic re-check.
- Fork-PR graduation is a distinct, higher-bar step with the Threat Model
  prerequisites; until then the lane does not run on PRs.
- The lane proves plumbing, not judgment quality.
- The live lane proves the real **transport**; response **parsing correctness**
  (raw model output → validated rows) is proven by the hermetic suite with a fake
  adapter and known output. A hypothetical `analyze` defect that calls the model,
  ignores the response, and emits a canned valid row is not distinguishable by
  any live smoke test (it needs a controllable model, which contradicts "real
  model") — it is caught by the hermetic parsing tests, not here. This division
  of labor is deliberate; do not try to make the live lane assert parse content.
- It is a smoke/plumbing proof, **not a reliability test**: a systematic
  "first request works, subsequent fail" adapter, connection-reuse, or
  model-unload bug can pass once a single packet succeeds. The ≥1-non-error
  floor and the transport preflight bound this but do not fully catch it;
  `BACKSTITCH_LIVE_LLM_STRICT=1` (no error rows) or a future dedicated
  reliability probe would.

## Independent Review Incorporation

Three independent reviewers read the plan, the delta, the landed module/workflow,
and the installed `llm` 0.31 source. Adversarial and feasibility ran first;
codex (a different agent family) ran on the revised plan and caught issues both
missed — most from the module/workflow changing under the plan during authoring.

Codex review (round 1) — all confirmed against code and fixed:

- **P0 `num_ctx` is not an `llm` option** (`SharedOptions` has `max_tokens`).
  Fixed: memory/context bound moved to the Ollama server
  (`OLLAMA_CONTEXT_LENGTH`/Modelfile); the yaml entry is three keys only.
- **P0 one-packet leniency contradiction** (`DEFAULT_LIVE_PACKETS = 1`; 1 error =
  total failure = exit 2). Fixed: local kind uses `DEFAULT_LOCAL_LIVE_PACKETS`
  (≥2); Invariants, Hidden Couplings, spec delta, and Testing Plan updated.
- **P0 spec delta conflicted with current [SC-7]** ("malformed model output must
  fail"). Fixed: the delta now **replaces** that sentence with cloud-vs-local
  contracts instead of inserting a contradictory paragraph.
- **P1 ordering:** `_resolve_live_model()` is the first line; local env must be
  set before it. Fixed: Invariants + Hidden Couplings + Task 3 make this explicit.
- **P1 "no key sent" is false** (`DUMMY_KEY` is sent). Fixed wording.
- **P1 CI job omitted `setup-uv`.** Fixed: Task 5 includes it.
- **P1 workflow guard test** (`test_release_workflow.py` asserts no job-level `if`
  after `live-llm:`). ~~Fixed: place `local-llm` **before** `live-llm`~~
  **SUPERSEDED by round 4:** the lane became a **separate** `local-llm.yml`
  workflow, so it never touches `ci.yml` and the placement problem is moot.
- **P2 skip mechanism** is function-level `skipif`, not module-level. Fixed:
  Relationship/Invariants corrected; `import llm`/`urllib` stay in the test body.
- **P2 fork-PR spec wording too permissive.** Fixed: the delta says local tests
  are eligible on fork PRs **only after an explicit threat-model-gated change**.

Codex review (round 2) — on the revised plan; round-1 P0s confirmed resolved:

- **P0 per-packet transport-failure contradiction.** `_error_record` covers both
  malformed output and adapter/HTTP exceptions (`analysis_llm.py:152`), so a
  transient per-packet transport blip would be tolerated, contradicting
  "transport failures must fail." Fixed: the spec delta now scopes transport
  fatality to the preflight + total-failure guard (not per-packet); individual
  per-packet error records (malformed output *or* transient call failure) are
  tolerated in non-strict. Invariants/Hidden Couplings state the same.
- **P1 "same resolution" claim stronger than the proof.** Fixed: the transport
  preflight is now a **subprocess** that resolves and generates via the same
  registration `analyze` inherits, and the spec wording is qualified accordingly.
- **P1 ordering trap.** Fixed: Task 3 pins the signature to
  `(tmp_path, monkeypatch)` and puts the local setup first, before
  `_resolve_live_model()`.
- **P1 fork-PR threat model incomplete.** Fixed: Threat Model adds
  `permissions: contents: read`, no `pull_request_target`, cache-poisoning
  isolation, and a fork lockfile/dependency policy.
- **P2 cache lifecycle wording.** Fixed: outcome softened (weights cached; image
  caching optional — runners don't persist layers); cache key includes tag +
  image digest.
- **P2 reachability preflight underspecified.** Fixed: Task 3 pins URL join,
  `urllib` timeout, the `data[].id` shape, and failure diagnostics.
- **P2 unknown `BACKSTITCH_LIVE_LLM_KIND`.** Fixed: Task 3 hard-fails on any kind
  other than `openai`/`local`.
- **P2 bake-off is a moving gate.** Fixed: Task 3 adds an acceptance rule
  (fall back to `llama3.2:1b` if both 3B models bust the floor/budget; do not
  raise the timeout to force a too-large default).
- Codex re-confirmed against code: `needs_key`-driven keyless preflight works
  when env is set first; `_run_cli` inherits `os.environ`; `analyze` exits 2 only
  when every packet errored (a valid total-failure guard at ≥2 packets), and note
  model-resolution/invocation errors also exit 2.

Codex review (round 3) — no P0s; precision gaps for a zero-context implementer:

- **Transport preflight strengthened** to call `default_adapter("backstitch-local")`
  (the exact function `_cmd_analyze` uses at `cli.py:589`), plus a keyless
  assertion that doubles as the `llm>=0.31` version-drift guard.
- **Literal `extra-openai-models.yaml` template + exact env contract** added to
  Task 3; clarified that `--model` wins in the subprocess while `LLM_USER_PATH`
  is what it needs to resolve.
- **Docker sequence pinned:** readiness poll *before* `pull`, model poll on
  `/v1/models` *after*; run the container as root (not `--user`) and
  `sudo chown` before cache save; job-level timeout in addition to the step
  timeout.
- **Fork-PR cache safety concretized:** `actions/cache/restore` on untrusted
  events, `save` only on trusted; `checkout` with `persist-credentials: false`;
  explicit note that fork code runs arbitrary work regardless of env placement.
- **Docstring/comment update required** so the extended module does not keep the
  cloud-only "no error row" guidance.
- **`paths` mitigation clarified** as a job-level changed-files gate or a
  separate workflow, not a workflow-level `paths:`.

Codex review (round 4) — no correctness P0s in the test path; one CI-integration
P0 no prior reviewer caught (it required reading the release machinery):

- **P0 release-gate coupling.** `release-gate.yml` requires the whole `CI`
  workflow green and `ci.yml`'s `on: push` is unconstrained, so a `local-llm`
  job *inside* `ci.yml` would block releases on a flaky Ollama job and fire on
  release tags. Fixed: the lane is now a **separate** `.github/workflows/local-llm.yml`
  (`name: local-llm`, push constrained to branches with `tags-ignore`), and the
  guard-placement coupling disappears.
- **P1 new workflow needs a firing guard test.** Fixed: Task 5 adds one
  (existence, triggers, no PR trigger, `setup-uv`, pinned digest, timeouts,
  `BACKSTITCH_LIVE_LLM_KIND`), satisfying the enumerable-contract/DoD rule.
- **P1 `len(subset) >= 2` must be a hard assertion for local.** Fixed: added to
  Task 3.
- **P1 `api_base` inspection path** for the preflight specified (`model.api_base`
  with a `/models`-binding fallback, no private-attribute guessing).
- **P2 spec "same model resolution" overclaim.** Fixed: reworded to "same
  adapter registration and environment that `analyze` inherits."
- **P2 cache action mode** noted for trusted-vs-fork (restore/save split).

Codex review (round 5) — verdict "yes, I could implement this correctly";
remaining caveats cleaned up, no correctness blockers:

- **Cache-save ownership timing.** Fixed: the `chown` moved to an `if: always()`
  step **after** inference, with an explicit `actions/cache/save` (trusted events
  only) after it — the early chown left post-run root-owned files.
- **Threat-model base-vs-fork contradiction.** Fixed: clarified that a
  `pull_request` runs the base-branch workflow definition (constants safe) while
  the checked-out test code is fork-authored and untrusted.
- **Stale `ci.yml` references** in Source Documents, rollback, and testing plan.
  Fixed to `local-llm.yml`.
- **Transport preflight precision:** `default_adapter` returns only a callable;
  the subprocess also calls `llm.get_model` for the keyless/`api_base` asserts.
  Fixed.
- **Best-effort wording:** keyed only on the `error` field (a plain `ambiguous`
  row is legitimate). Fixed.

Codex review (round 6) — CI-hardening precision; no test-path correctness issues:

- **Context bound was a `<n>` placeholder.** Fixed: `OLLAMA_CONTEXT_LENGTH=4096`
  as a named constant, validated by the bake-off against the 8 GB floor.
- **Cache save could self-poison on failed provisioning.** Fixed: save gated on
  `success()` (pull + model poll), not `always()`; cleanup/chown stay `always()`.
- **New workflow omitted Python 3.14.** Fixed: `setup-uv` pins `python-version:
  "3.14"`; the guard test asserts it.
- **Fork dependency policy was prose.** Fixed: named as an **executable**
  changed-files gate required before graduation (out of scope for first landing).
- **`ruff format --check`** added to the final gates (CI runs it).
- **Exit-2 "iff" wording** softened (also fires on pre-analysis
  invocation/model/output errors); stale `ci.yml` reference cleaned.

Codex review (round 7) — verdict "yes, I could implement the initial lane
correctly"; all three core correctness checks pass. Refinements folded in:

- **Subprocess timeouts** added (`_run_cli` has none; a hung local model would
  hang pytest) — explicit `timeout=` on the preflight and `analyze` calls.
- **Spec transport-proof wording** sharpened: proves one successful generation
  via the shared registration plus ≥1 non-error row, not healthy transport on
  every per-packet call.
- **Fork arbitrary-code residual risk** made explicit: fork `pytest` runs
  arbitrary network/CPU/env code that a changed-files gate can't contain;
  graduation must accept that risk explicitly or require manual approval only.
- **Cache-save gating clarified** to key on the pull/model-poll step `outcome`
  (save after successful provisioning even if pytest failed; never on a partial
  pull), not bare `success()`/`always()`.
- **Trigger narrowed** to `workflow_dispatch` + `push` on `main` (post-merge
  canary) to avoid inference on every branch push.
- **Bake-off reproducibility + local-vs-CI image pinning** documented.

Codex review (round 8) — verdict **"yes, I could implement the initial
`workflow_dispatch` + `push: main` lane confidently and correctly"**; the only
"no" is fork-PR graduation, which this plan deliberately scopes out and gates.
Final polish folded in:

- **Cache-key reproducibility overclaim corrected:** Ollama tags are mutable, so
  a moved tag keeps the same key — documented `ollama pull` as the freshness
  mechanism and a cache-epoch suffix as the refresh lever.
- **Guard-test location fixed** to `tests/test_release_workflow.py` (a sibling
  file would fall outside `ci.yml`'s format/mypy list, which this plan avoids
  editing).
- **Cache save skips on exact cache-hit** (restore `cache-hit` output).
- **Base-vs-fork GitHub semantics** flagged for re-verification at graduation.

Codex review (round 9) — core path re-confirmed sound; precision found by
simulating the packet selector:

- **Packet-count/context budget fragility.** Fixed: `DEFAULT_LOCAL_LIVE_PACKETS`
  is now a bake-off output starting at **2**, tuned jointly with
  `OLLAMA_CONTEXT_LENGTH` on the target runner (smallest-first selection alone
  can't guarantee 3 packets fit 4096 ctx / 15 min on CPU).
- **Packet-boundary vs health-probe contradiction.** Fixed: the fixed
  `"Reply … OK"` probe is carved out in Invariants and the spec delta as a
  transport health check that feeds no repository content.
- **Fork graduation is aspirational.** Fixed: Requested Outcomes and Out of Scope
  now say fork-PR graduation is a **separate future plan**, not implementable
  from this one.
- **Cache freshness overstated** (GitHub caches immutable). Fixed: cache-epoch
  bump is the only persistent refresh; per-run `ollama pull` only refreshes the
  ephemeral local copy.

Codex review (round 10) — verdict "yes, I could implement the initial lane
confidently and correctly as written"; last-mile precision applied:

- **Exact cache-save `if:` expression** pinned (a bare `if:` is implicitly
  `success()`, so the condition names `!cancelled()` + step outcomes +
  `cache-hit` + trusted event).
- **`OLLAMA_CONTEXT_LENGTH` single-sourced** as a workflow env (was re-hardcoded).
- **`permissions: contents: read` moved to the initial workflow** (not deferred),
  asserted by the guard test.
- **Guard-test rationale** corrected (`ruff format` coverage, not mypy) and fork
  wording tightened (base-branch workflow definition vs untrusted checkout).

Convergence: across ten codex rounds the correctness of the core path
(`_resolve_live_model` / `_run_cli` env inheritance / `default_adapter` /
`analyze` exit-2 total-failure guard at ≥2 packets) was re-verified against the
landed code every round; the initial `workflow_dispatch` + `push: main` lane is
implementable confidently and correctly. Fork-PR graduation is intentionally a
separate, later, threat-model-gated plan.

Codex **Challenge (adversarial) mode** via the `/codex` skill (Step 2B) — a
deeper pass than the consult rounds: it read the repo guidance, opened the
installed `llm` 0.31 source, and ran **live experiments** (confirming
`api_base` → `needs_key=None` → `DUMMY_KEY`, and that `LLM_USER_PATH` re-resolves
on each `get_model`). Verdict yes-with-caveats; new findings, all folded in:

- **Lenient contract could pass with most packet transport broken** (2 of 3
  packets transport-fail + 1 valid). Fixed: the Requested-Outcome wording no
  longer claims a lane-level "whole path healthy" proof — only ≥1 healthy
  generation + valid-row handling.
- **Context bound was asserted, not proven.** Fixed: Task 5 adds a server-side
  `ollama show` verification that `OLLAMA_CONTEXT_LENGTH` was applied.
- **Cache-save cold-miss race** between two concurrent trusted runs. Fixed:
  workflow `concurrency:` + non-fatal `actions/cache/save`.
- **"spun up reproducibly" overclaimed** given mutable tags. Fixed: weights are
  tag-trusted; record the manifest digest; byte-reproducibility not claimed.
- **YAML template string-substitution could corrupt the file.** Fixed: generate
  via `json.dumps([record])` (valid YAML), not hand-quoted substitution.
- **`llm>=0.31` vs attribute-level `api_base` assert.** Fixed: written
  version-adaptively now (`getattr` + conditional assert), verified against the
  `uv.lock`-pinned 0.31.
- **[SC-7] delta could be read to weaken cloud.** Fixed: cloud and local
  contracts split into explicit non-overlapping bullets.
- **Guard test would break under PyYAML** (`on:` → `True`). Fixed: text/substring
  assertions required.
- **"No secrets" overclaim.** Fixed: narrowed to "no provider secret"; the job
  still carries a read-scoped `GITHUB_TOKEN`; checkout uses
  `persist-credentials: false`.

Codex Challenge mode (pass 2) — the harder reviewer kept finding real issues
(reading `AGENTS.md` DoD, Ollama docs, GitHub runner specs). All folded in:

- **Missing explicit non-error assertion** (exit-0/`errors`-list lockstep could
  be gamed). Fixed: `assert any("error" not in row …)` + `len(errored) < len(rows)`.
- **Acceptance suite omitted from final gates** (`AGENTS.md` DoD). Fixed: added
  `uv run pytest tests/acceptance -q`.
- **Ollama context bound uncertain via env** (OpenAI surface has no context
  setting). Fixed: default to a **Modelfile `PARAMETER num_ctx` + `ollama create`**,
  verified via `ollama show`.
- **Template/`json.dumps` contradiction** I introduced. Fixed: no committed
  `.tmpl`; render at runtime via `json.dumps` (valid YAML).
- **"local" not forced local.** Fixed: assert a loopback endpoint unless
  `BACKSTITCH_LOCAL_LLM_ALLOW_NONLOCAL=1`; Docker binds `127.0.0.1:11434`.
- **Model-weight traceability.** Fixed: log the resolved manifest digest per run.
- **Cache `restore-keys` / partial-match staleness.** Fixed: forbid `restore-keys`.
- **`continue-on-error` hides a broken cache lane forever.** Fixed: notice +
  assert a trusted cold run actually saved.
- **`llm>=0.31` binding.** Fixed: assert `api_base` directly against the pinned
  0.31 and **fail loudly** on attribute drift (no silent degrade).
- **Guard test too shallow** for cache/security sequencing. Fixed: ordered text
  assertions (loopback bind, cache-after-chown, `if:` expr, no `restore-keys`).
- **Stale runner floor** (2/7). Fixed: cite current specs (4/16 public, 2/8
  private); design to 2 vCPU / 8 GB.
- **Reliability blind spot** (first-works-then-fails) named as residual risk.
- **Stale round-1 review bullet** (place before `live-llm`) marked superseded.

Codex Challenge mode (pass 3) — deeper still; key gaps closed:

- **`analyze` never proven to hit the local server** (the lane's whole point).
  Fixed: Task 3 adds a stdlib counting-proxy assertion that the `analyze` phase
  produced ≥ N requests to the endpoint; the spec delta now requires it.
- **Base-vs-served model ambiguity** (introduced by the Modelfile fix). Fixed:
  split `BACKSTITCH_LOCAL_LLM_BASE_MODEL` (pulled) from `…_SERVED_MODEL`
  (Modelfile-bounded; what yaml/reachability/cache/bake-off use).
- **`workflow_dispatch` could poison the trusted cache** from any ref. Fixed:
  cache save requires `github.ref == 'refs/heads/main'`, not "any dispatch".
- **`llm>=0.31` vs pinned.** Fixed: CI `uv sync --locked` + record resolved
  version.
- **Exact `concurrency:` block** given (github/inputs contexts only, not env).
- **Disk (14 GB) pressure** named with `df -h` before/after.
- **Both model digests** (base + served) logged per run.
- **Prompt budget** given a recorded byte-ceiling derivation (not invented).
- **Guard test** strengthened (step-ids, identical cache path, forbid
  `ALLOW_NONLOCAL` in CI).
- **Branch protection** note: `local-llm` must not be required until stable.

Codex Challenge mode (pass 4) — several items were adjacent surface created by
pass-3 fixes (a signal of diminishing prose-precision returns); substance closed:

- **Two named endpoints** for the counting proxy (upstream Ollama vs adapter
  `api_base` proxy), so `analyze` provably routes through the counter.
- **Cache key uses the base tag**, not the stable served alias (the split had
  broken the invalidation contract).
- **Release-helper coupling** (`bin/release.py` runs the live test without pinning
  the kind): pin `BACKSTITCH_LIVE_LLM_KIND=openai` in the release precheck +
  guard it in `test_release_script.py`.
- **`127.0.0.1` used consistently** (endpoint + Docker bind) to avoid IPv6
  `localhost` false-fails.
- **`api_base` compared after normalization**; request count matches any `/v1/*`
  completion path (transport-variant tolerant).
- **Parsing-correctness division of labor** named (hermetic suite proves parse;
  live lane proves transport) — a canned-row defect is a hermetic-test concern.
- **Observed-success aligned with the spec** (request-count + ≥1 non-error);
  pre-merge static validation separated from post-merge canary evidence.
- **Guard test prefers `actionlint`/active-line parsing** over naive substrings.

Codex Challenge mode (pass 5) — substantive items closed; the rest is the
asymptote (escalating precision on test-harness internals + task-placement):

- **Output cap:** Modelfile `PARAMETER num_predict` (analyze has no `max_tokens`).
- **Proxy strengthened:** records analyze-phase request **bodies**, asserts each
  packet id appears and `model` == served alias; streaming disabled; proxy tested.
- **Release precheck named as a task** (`bin/release.py` + `test_release_script.py`),
  not only Hidden Couplings.
- **≥2 non-error rows required when packets ≥ 3** (catches "only first works").
- **Base/served constants renamed** distinctly; guard test pins both + the
  served alias.
- **Docker logs health-filtered** (avoid packet content in CI logs).
- **Guard test = pure-Python active-line parser** (no new `actionlint` dependency).
- **Two signals explicitly deferred to the implementation slice** (exact
  `cache/save` "saved" signal; exact `ollama show` fields) — pinned against the
  real image/action, or the assertion dropped rather than faked.

Convergence note: across 5 Challenge passes the correctness spine
(`_resolve_live_model` / `_run_cli` env inheritance / `default_adapter` /
`analyze` exit-2 total-failure guard, verified live against `llm` 0.31) held every
pass; remaining Challenge findings are implementation-time precision (exact YAML
expressions, parser choice, digest fields) best resolved with the real workflow +
tests in front of us, not more plan prose.

Adversarial + feasibility (round 0) — folded in earlier: verified the core
mechanism (real adapter → local Ollama via `api_base`, no plugin, no credential,
no runtime change) against `llm` 0.31; fixed the three-key yaml entry, the
`LLM_USER_PATH` env-inheritance mechanism (in-process resolution works; the
"binds at import" claim was false), the transport-preflight/same-resolution
guarantee, the Docker cache path/ownership trap, the fork-PR threat model beyond
secret theft, and the `check` exit-0 coupling on fork PRs.

Implementation independent review (opencode, read-only) — findings incorporated:

- **CFG-9 local endpoint isolation missing.** Fixed: [CFG-9] now states that
  local-endpoint live tests use an ephemeral per-test `llm` config directory and
  do not read global `llm` config or prove Backstitch config keys.
- **Workflow runner floor undocumented.** Fixed: `local-llm.yml` now names the
  observed GitHub-hosted runner classes (4 vCPU / 16 GB public, 2 vCPU / 8 GB
  private as of 2026-07-03), and the guard test asserts the comment remains.
- **Proxy background failure could be opaque.** Fixed: unexpected proxy
  forwarding exceptions are returned as HTTP 502 diagnostics instead of relying
  on daemon-thread tracebacks.
- **`num_predict` concern answered.** It is intentional and documented in this
  plan as the Modelfile output cap because `analyze` exposes no `max_tokens`.

Post-implementation adversarial review (fable, 2026-07-06) — eight verified
finder angles over the implementation plus a premise-level review of this
plan. Confirmed findings, all fixed in the same slice:

- **[SC-7] over-deletion.** The applied spec edit deleted two sentences the
  delta never authorized removing — the exit-code-contract comparison and the
  "automation may exit successfully without invoking the live test" allowance
  that `ci.yml`'s secret-gated skip relies on. Both restored.
- **[CFG-9] delta drift.** The applied spec text and this plan's delta had
  diverged in both directions; the spec now carries both the delta's
  loader-isolation clause and the opencode ephemeral-config clause, and the
  delta above matches the applied text.
- **Streaming premise false.** `can_stream: false` in
  `extra-openai-models.yaml` is honored only by `llm`'s CLI; the Python API
  path `analyze` uses streams SSE regardless (verified by live probe against
  the registered model). The proxy relays streams correctly, but the "dumb
  non-streaming forwarder" rationale above is wrong, and the hermetic proxy
  test covered only the non-streamed shape. An SSE relay test now covers the
  shape production actually uses.
- **Proxy mid-stream error handling.** A failure after the status line was
  written (upstream stall, client disconnect) injected a 502 into the running
  body or escaped the handler thread; the proxy now drops the connection once
  a response has started and sends 502 only before.
- **Proxy upstream path prefix.** `forward_url` rebuilt URLs from the origin
  only, silently dropping any upstream path prefix; `/v1/*` suffixes now map
  onto the configured upstream path (covered by a unit test).
- **Prompt budget desync.** `LOCAL_PROMPT_BYTE_CEILING` hardcoded 4096×4 while
  its failure message pointed at `OLLAMA_CONTEXT_LENGTH`; the ceiling now
  reads that env var, and K=4 is recorded as an assumption in the Deviation
  Log (this plan forbade inventing K; the bake-off recorded none).
- **Dead lenient-floor branch.** The ≥2-non-error-rows arm was gated on the
  compile-time `DEFAULT_LOCAL_LIVE_PACKETS` (statically dead at 2, and
  silently fully strict if bumped against a 2-packet corpus); now gated on the
  actual row count.
- **Workflow verification gaps.** The `num_ctx`/`num_predict` greps were
  unanchored (40960 passed as 4096); the required trusted-cold-run save
  assertion had decayed to a notice without the escape hatch being recorded
  (now a failing check on `steps.save.outcome == 'failure'`, which
  distinguishes real save failures from benign "key already exists" in
  `actions/cache/save@v4`); digest evidence was best-effort `|| true` (now a
  required manifest `sha256sum` listing). The guard test pins all three.
- **`ci.yml` kind pin.** The cloud live job now pins
  `BACKSTITCH_LIVE_LLM_KIND: openai` like `bin/release.py`, so an
  environment-leaked `local` cannot reroute it; guard test added.
- **Duplicate upstream resolution.** The env fallback chain was resolved
  independently in the test body and `_configure_local_llm`; it is now
  resolved once (`_resolve_local_upstream`) and carried by the proxy.

Premise-level findings (open decisions, not code fixes):

- **The bake-off ran at the wrong floor.** This repository is public, so
  `ubuntu-latest` is 4 vCPU / 16 GB; every recorded model failure was produced
  under a 2 vCPU / 8 GB simulation — half the actual target in both
  dimensions — and the 300 s per-call timeout was the binding constraint in
  every recorded failure. The "no model passes" conclusion is unproven on the
  real runner. Next action: one `workflow_dispatch` run with `llama3.2:3b` on
  the target runner before any further tuning, then record the floor decision
  ("design to public 4/16" or "insure against going private") explicitly.
  Resolution (2026-07-06): the local re-run on 16 vCPU / 16 GB Docker
  confirmed the artifact — `llama3.2:3b` passes the gate in ~25-40 s — and
  the workflow defaults were updated accordingly; the target-runner
  dispatch is the remaining step.
- **Known-failing default.** `qwen2.5:0.5b` cannot pass the contract the
  workflow dispatches it against; when the target-runner evidence lands,
  either default to a model that passes, add a dispatch input with no
  default, or label the job experimental in its name.
  Resolution (2026-07-06): the default switched to bounded `llama3.2:3b`
  per the local bake-off evidence.
- **No owner, clock, or kill rule** for the paused state; add them to
  Decisions alongside the target-runner evidence.

Independent review round (codex, 2026-07-06) over the hardening diff: no P1
findings; three P2s, all applied — the workflow parameter greps are now
anchored at line start and value end, the manifest sha256 evidence check
requires non-empty output, and the proxy 502 hermetic test uses an
accept-and-close listener instead of assuming a closed host port.

## Out Of Scope

- Changing `backstitch/` runtime modules to know about providers/endpoints.
- Adding `llm-ollama` or any Python package / `llm` plugin.
- Making semantic classification fail CI.
- Making `BACKSTITCH_LIVE_LLM_STRICT` a required gate on first landing.
- Running fork-PR local CI: graduation is a **separate future plan** with its own
  verified threat model (workflow mutability, cache trust, arbitrary fork test
  code), not implementable from this plan.
- Running a full-repository local semantic review per CI run.
- Replacing the cloud live lane; the lanes coexist.
- GPU inference or larger-than-runner models as the committed default.

## Decisions

- **Default local model — bounded `llama3.2:3b`.** Both reviewers recommended
  `llama3.2:3b` over `qwen2.5-coder:3b` for cleaner JSON on a format-shaped,
  plumbing-only lane, and the 2026-07-06 local bake-off (16 vCPU / 16.8 GB
  Docker) confirmed it: bounded `llama3.2:3b` (`num_ctx 4096`,
  `num_predict 1024`, `temperature 0`) passed 7 of 8 gate runs and is now the
  committed workflow default. `qwen2.5:0.5b` was abandoned after producing
  total invalid rows in every environment tested. The trigger stays
  manual-first pending target-runner evidence.
- **Trigger — manual first.** Initial scope is `workflow_dispatch` only.
  Graduating to `push: main`, broader push triggers, or fork PRs requires a
  target-runner pass and, for fork PRs, the Threat-Model-gated step.
