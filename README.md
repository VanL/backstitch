# backstitch

Backstitch style spec-code traceability checks and semantic review tooling.

`backstitch` is a standalone developer tool. It owns the backstitch style v1
traceability grammar, deterministic trace graph construction, and semantic
analysis result schemas. This repository's own specs are a primary acceptance
corpus. Weft is an external target corpus and eventual consumer, not a package
dependency.

Current implementation status: the deterministic checker (`backstitch check`),
review-packet generation (`backstitch packets`), `llm` semantic analysis
(`backstitch analyze`, `backstitch summarize-analysis`), and TOML
configuration (`backstitch config show|path`) are implemented per
`docs/specs/02-backstitch-core.md`, `03-backstitch-configuration.md`, and
`04-backstitch-traceability-exclusions.md`. The invariant traceability spec
(`05-backstitch-invariants.md`) is Proposed and not implemented. This
repository dogfoods itself: `uv run backstitch check` must pass with zero
errors and zero warnings.

## Testing

The default suite is hermetic — no network, no provider credentials:

```bash
uv run pytest tests -q
```

### Optional live LLM tests

`tests/live/test_live_llm.py` drives the real CLI (`packets` -> `analyze` ->
`check` -> `summarize-analysis`) over this repository's own specs through the
production adapter. It is **skipped unless you opt in** with
`BACKSTITCH_LIVE_LLM=1`, so it never runs in the default suite. It asserts
structured contracts (one result row per packet, schema-valid JSONL, clean
analysis loading), not model wording or classification, which are not API.

Cloud-provider runs additionally assert model success: no result row may carry
an `error` field. Model choice is intentionally explicit: the test does not fall
back to your global `llm` default, so CI and local runs are reproducible. Use a
current GPT-5-series mini model; verify availability with
`uv run llm models list`.

```bash
# Using a key stored by `llm` (run once):
uv run llm keys set openai
BACKSTITCH_LIVE_LLM=1 LLM_MODEL=<configured-model> \
  uv run pytest tests/live/test_live_llm.py -q

# Using a provider environment variable instead of a stored key:
OPENAI_API_KEY=... BACKSTITCH_LIVE_LLM=1 LLM_MODEL=gpt-5.4-mini \
  uv run pytest -m live_llm -q
```

The same test also has a credential-free local lane for a loopback
OpenAI-compatible endpoint, normally Ollama. It proves local transport and
result handling, not judgment quality. Small CPU models often emit malformed
JSON, so non-strict local runs tolerate individual per-packet `error` rows as
long as `analyze` does not report total failure and at least one selected packet
produces a non-error row.

```bash
docker run -d --name backstitch-llm \
  -p 127.0.0.1:11434:11434 \
  -v "$PWD/.ollama-cache:/root/.ollama" \
  ollama/ollama
docker exec backstitch-llm ollama pull llama3.2:3b
BACKSTITCH_LIVE_LLM=1 BACKSTITCH_LIVE_LLM_KIND=local \
  uv run pytest -m live_llm -q
```

The floating `ollama/ollama` tag above is for developer convenience. The
separate manual `local-llm` workflow pins the image by digest, bounds
context/output through an Ollama Modelfile, serves the bounded alias as
`backstitch-local-model:latest`, binds only `127.0.0.1`, and caches model
weights in an absolute runner path. On unconstrained local hardware (a 16 vCPU
Docker VM) the gate passes with `llama3.2:3b` in under a minute; with the
workflow's Modelfile bounds (`num_ctx 4096`, `num_predict 1024`,
`temperature 0`) and the adapter's provider-enforced JSON output it passed
8 of 8 local runs with no contained error rows
(`docs/plans/2026-07-06-analyze-json-mode-plan.md`). Occasional content-level
error rows remain possible — a failed run is a rerun, not an alarm — and the
lane stays a manual workflow until a passing run on the actual GitHub runner
is recorded.

Cloud-provider tests **cost money** and can be **flaky** for reasons unrelated
to Backstitch: provider outages, rate limits, model retirement, and
nondeterministic output. The local lane is also flaky in a different way: cold
model pulls, CPU inference, and small-model output quality can dominate runtime.
Keep the packet set small; live tests are smoke and contract checks, not
exhaustive semantic review. In CI the cloud live job is part of the normal `CI`
workflow: it runs when the repository `OPENAI_API_KEY` secret is available and
skips without failure when secrets are unavailable, such as on forked pull
requests. The local Ollama lane is a separate manual workflow and must not be a
required status check until it has stable passing run history. See
`docs/implementation/04-backstitch-style-traceability.md` for the boundary
rationale.

## Release

Backstitch releases use `bin/release.py` locally and a tag-triggered GitHub
release gate. The helper updates `pyproject.toml` and `backstitch/__init__.py`
together, runs local checks including the live LLM test, creates the release
commit when needed, and pushes the `vX.Y.Z` tag. The GitHub workflow publishes
to PyPI through Trusted Publishing and creates the GitHub Release.

```bash
bin/release.py --version X.Y.Z --dry-run
bin/release.py --version X.Y.Z
```

See `docs/implementation/05-release-publishing.md` for setup, rollback, and
verification details.
