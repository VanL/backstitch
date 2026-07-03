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

`tests/live/test_live_llm.py` drives the real CLI (`packets` → `analyze` →
`check` → `summarize-analysis`) over this repository's own specs, calling a real
provider through the production adapter. It is **skipped unless you opt in** with
`BACKSTITCH_LIVE_LLM=1`, so it never runs in the default suite. It asserts
structured contracts (one result row per packet, no error rows, schema-valid
JSONL) — not model wording or classification, which are not API.

Model choice is intentionally explicit: the test does not fall back to your
global `llm` default, so CI and local runs are reproducible. Use a current
GPT-5-series mini model; verify availability with `uv run llm models list`.

```bash
# Using a key stored by `llm` (run once):
uv run llm keys set openai
BACKSTITCH_LIVE_LLM=1 LLM_MODEL=<configured-model> \
  uv run pytest tests/live/test_live_llm.py -q

# Using a provider environment variable instead of a stored key:
OPENAI_API_KEY=... BACKSTITCH_LIVE_LLM=1 LLM_MODEL=gpt-5.4-mini \
  uv run pytest -m live_llm -q
```

These tests **cost money** (real provider calls) and can be **flaky** for
reasons unrelated to Backstitch — provider outages, rate limits, model
retirement, and nondeterministic output. Keep the packet set small; the live
test is a smoke and contract check, not an exhaustive semantic review. In CI the
live job is part of the normal `CI` workflow: it runs when the repository
`OPENAI_API_KEY` secret is available and skips without failure when secrets are
unavailable, such as forked pull requests. See
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
