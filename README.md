# Backstitch

  [![CI](https://github.com/VanL/backstitch/actions/workflows/ci.yml/badge.svg)](https://github.com/VanL/backstitch/actions/workflows/ci.yml)
  [![codecov](https://codecov.io/gh/VanL/backstitch/branch/main/graph/badge.svg)](https://codecov.io/gh/VanL/backstitch)
  [![PyPI version](https://badge.fury.io/py/backstitch.svg)](https://badge.fury.io/py/backstitch)
  [![Python versions](https://img.shields.io/pypi/pyversions/backstitch.svg)](https://pypi.org/project/backstitch/)

*Spec-to-code traceability and invariant checks for Python repositories.*

```bash
$ uv tool install backstitch
$ cd your-project
$ mkdir -p docs/specs docs/plans src
$ backstitch check --spec-root docs/specs --code-root src
```

Backstitch verifies that spec requirements point to real implementation owners,
code points back to the requirements it implements, and declared invariants are
bound to real tests. It runs as two lanes under one policy layer:

- **Trace lane** — deterministic facts about declared relationships. No model,
  byte-stable reports, hard-gate by default.
- **Semantic lane** — bounded model review of finite, reproducible packets
  through the `llm` ecosystem, without open-ended repository access. Advisory
  by default; every verdict is evidence-bound and cached as a frozen,
  replayable artifact.
- **Policy layer** — repository configuration decides which findings, at which
  evidence class, become blocking. The decision to block is always a
  reviewable config diff, never a model output.

Backstitch does not promise that models prove correctness. It promises that
semantic review becomes repeatable enough to run in CI, diffable enough to
audit, and structured enough to improve. The workflow stays deterministic even
where one lane uses probabilistic judgment, because everything around the
judgment is contract: what evidence the model sees, which requirement it
judges, which prompt and model produced the verdict, what shape must come
back, how uncertainty is represented, and how severities map to exit codes.

Backstitch is a standalone tool. Weft is a reference target and eventual
consumer, not a package dependency.

## Recommended For

- **Spec-driven Python projects.** Stable requirement IDs and reciprocal links
  make intended behavior navigable from docs to code and back.
- **Repositories maintained by coding agents.** Deterministic ownership,
  diagnostics, and acceptance gates replace prose-only compliance claims.
- **Critical behavior that needs explicit test bindings.** Required and draft
  invariants make missing, malformed, duplicate, or misplaced bindings visible.
- **Teams that want bounded semantic review.** Backstitch generates finite,
  reproducible packets before any model call and validates returned evidence.

## Table of Contents

- [Backstitch](#backstitch)
  - [Recommended For](#recommended-for)
  - [Table of Contents](#table-of-contents)
  - [Features](#features)
  - [Installation](#installation)
  - [Quick Start](#quick-start)
  - [Command Reference](#command-reference)
    - [Global Options](#global-options)
    - [Commands](#commands)
    - [Exit Codes](#exit-codes)
  - [Core Concepts](#core-concepts)
    - [Spec and Code Traceability](#spec-and-code-traceability)
    - [Invariant Bindings](#invariant-bindings)
    - [Diagnostic Policy](#diagnostic-policy)
    - [Configuration Discovery](#configuration-discovery)
  - [Semantic Review](#semantic-review)
  - [Development and Contributing](#development-and-contributing)
    - [Runtime](#runtime)
    - [Testing](#testing)
    - [Live LLM Tests](#live-llm-tests)
    - [Releases](#releases)
  - [License](#license)

## Features

- **Bidirectional traceability** - Resolves spec mappings and Python backlinks
- **Invariant checking** - Connects required or draft guarantees to real tests
- **Stable diagnostics** - Canonical names, short aliases, contexts, and levels
- **Configurable policy** - Ordered selectors, `fail_on`, and suppressibility
- **Auditable suppression** - Hidden findings remain available with reasons
- **Deterministic reports** - Stable JSON, ordering, locators, and content hashes
- **Bounded semantic review** - Section and invariant packets with evidence limits
- **Runtime-independent parsing** - CommonMark and modern Python syntax support
- **Self-application** - Backstitch's own repository is a strict acceptance corpus

## Installation

```bash
# Install the CLI globally with uv (recommended)
uv tool install backstitch

# Or with pipx
pipx install backstitch

# Or add it to a project environment
uv add --dev backstitch
pip install backstitch
```

For a source checkout:

```bash
$ uv sync --extra dev
$ uv run backstitch --version
backstitch 0.3.0
```

**Requirements:**

- Python 3.11+
- `llm`, `markdown-it-py`, `tree-sitter`, and `tree-sitter-python` (installed
  automatically)

## Quick Start

For a project with application code under `src`, create the scan roots and add
the repository profile:

```bash
$ mkdir -p docs/specs docs/plans src tests
```

```toml
# pyproject.toml
[tool.backstitch.profile]
name = "backstitch-style-v1"
spec_roots = ["docs/specs"]
plan_roots = ["docs/plans"]
code_roots = ["src", "tests"]
test_roots = ["tests"]
```

Give a requirement a stable ID and map it to an exact repository-relative
implementation path:

```markdown
## Authentication boundary [AUTH-1]

The request path must reject unauthenticated callers.

_Implementation mapping_:
- `src/auth.py`
```

Add the reciprocal backlink in the owning Python docstring or a nearby comment:

```python
def authenticate(request: Request) -> User:
    """Authenticate one request.

    Spec: docs/specs/auth.md [AUTH-1]
    """
```

Run the deterministic checker from the repository root:

```bash
$ backstitch obligation list
$ backstitch obligation docs/specs/01-example.md#EXAMPLE-1 --summarize-evidence
$ backstitch obligation docs/specs/01-example.md#EXAMPLE-1 --find-evidence
$ backstitch guide alignment
$ backstitch check
$ backstitch check --format json --output spec-trace.json
$ backstitch check --show-suppressions
```

The obligation reads help bootstrap alignment before it is complete. Declared
evidence comes only from source mappings, backlinks, invariant binds, and
binding tests. Discovered candidates are deterministic review advice; a human
or agent must still author an ordinary source diff, and Backstitch never applies
that diff itself.

The built-in `backstitch-style-v1` profile defaults to `docs/specs` for specs
and `backstitch` plus `tests` for code. Override roots in configuration or with
repeatable `--spec-root`, `--code-root`, and `--test-root` options.

## Command Reference

### Global Options

Global configuration options may appear before a command. Command-specific
forms are also available where relevant.

- `--config PATH` - Use exactly one configuration file; skip discovery
- `--no-config` - Skip repository configuration; packaged defaults still load
- `--version` - Show the installed Backstitch version
- `--help` - Show help

### Commands

| Command | Description |
|---------|-------------|
| `obligation` | List obligations or inspect readiness, declared evidence, and deterministic candidates |
| `guide alignment` | Print the installed, versioned alignment quick start |
| `check` | Build the deterministic trace graph and report findings |
| `packets` | Generate bounded section or invariant review packets; no model calls |
| `analyze` | Resolve immutable semantic results and apply repository policy |
| `eval` | Measure one semantic identity against a closed mutation/control corpus |
| `summarize-analysis` | Combine a deterministic report with semantic results |
| `doctor` | Diagnose model, credential, decoding, and endpoint readiness |
| `config show` | Print effective settings, layers, and diagnostic policy as JSON |
| `config path` | Print the discovered repository configuration path |
| `cache cleanup-lock` | Audit and remove one unchanged abandoned semantic lock |

Common deterministic examples:

```bash
$ backstitch obligation list --repo-root .
$ backstitch obligation docs/specs/01-example.md#EXAMPLE-1 --find-evidence
$ backstitch check --repo-root . --warnings-as-errors
$ backstitch check --repo-root . --format json --output spec-trace.json
$ backstitch packets --repo-root . --kind invariant --output invariants.jsonl
$ backstitch packets --repo-root . --kind all --output packets.jsonl
```

Run `backstitch <command> --help` for the full option set.

### Exit Codes

- `0` - Command completed and no effective `fail_on` level was present
- `1` - The target repository has a finding at an effective failing level
- `2` - Arguments, configuration, input artifacts, output, or the tool failed

Exit `1` describes the target repository. Exit `2` describes the invocation or
tool. Backstitch contains per-file failures where possible and never exposes a
Python traceback as normal CLI output.

## Core Concepts

### Spec and Code Traceability

Backstitch parses Markdown sections with IDs such as `[AUTH-1]`, implementation
mapping blocks, and Python references in module, class, function, and method
docstrings or comments. Mappings use exact repository-relative paths. Bare IDs
resolve only when unique; Backstitch reports ambiguity instead of guessing.

The deterministic report contains normalized sections, code references,
mappings, resolved edges, invariants, binds, issues, and summary counts.
Identical inputs produce stable JSON ordering.

### Invariant Bindings

Declare behavior in an owning Python docstring or inside an ID-bearing spec
section:

```python
def resolve() -> Report:
    """Build the deterministic report.

    Invariant: [INV.RES.1] Identical inputs produce byte-identical JSON.
    """
```

Bind the invariant inside a real test definition:

```python
def test_report_is_stable() -> None:
    """Tests-invariant: [INV.RES.1]"""
```

Use `Invariant (draft):` for an advisory declaration. Under packaged defaults,
an untested required invariant is an error and an untested draft invariant is a
warning. `packets --kind invariant` includes bounded target and binding-test
snippets for advisory semantic review.

### Diagnostic Policy

Diagnostics have canonical names such as `CODE_REF_UNMAPPED_FROM_SPEC` and
stable short aliases such as `BSC008`. Rules are ordered and the last matching
rule wins:

```toml
[tool.backstitch.diagnostics]
fail_on = ["error", "warning"]
suppressible_levels = ["warning", "info"]

[[tool.backstitch.diagnostics.levels]]
select = ["BSC*", "INVARIANT_UNTESTED:draft"]
level = "warning"
```

Selectors accept canonical codes, short codes, `*`, family prefixes, and
supported contexts. A diagnostic set to `off` is omitted from normal findings
but remains available in `suppressed_issues` under `--show-suppressions`.

### Configuration Discovery

Backstitch always starts with packaged defaults, then applies repository
configuration, supported environment values, and explicit CLI options. It
searches upward for the nearest `.backstitch.toml` or `pyproject.toml` with a
`[tool.backstitch]` table. A standalone file uses the same key layout without
the `tool.backstitch` prefix. Explicit `--config PATH` and `extend` may name
any TOML filename; those names never become implicit discovery conventions.

```toml
[tool.backstitch.profile]
name = "backstitch-style-v1"
spec_roots = ["docs/specs"]
code_roots = ["src", "tests"]
test_roots = ["tests"]

[tool.backstitch.check]
format = "text"
warnings_as_errors = false
```

One invocation-scoped resolver applies the cascade `CLI > defined environment
> selected config > extended config > packaged defaults`, then passes an
immutable settings object into command code. Repeat a generic override before
or after a config-consuming command:

```bash
backstitch --option analyze.cache_mode read-write analyze ...
backstitch config show --option check.warnings_as_errors true
```

`KEY` is a known runtime-consulted dotted leaf. `VALUE` is parsed as one TOML
value when possible, otherwise as a bare string. Quote ambiguous strings.
`summarize-analysis`, `guide`, and `cache cleanup-lock` reject configuration
controls because they do not consume settings.

Test roots classify paths within code roots. Replacing `code_roots` without
also supplying `test_roots` resets test roots for that configuration layer;
every nonempty final test root must be contained by a final code root.

## Semantic Review

Deterministic checks never call a model. Generate packets explicitly, then
analyze and summarize them:

```bash
$ backstitch check --format json --output spec-trace.json
$ backstitch packets --kind all \
    --output packets.jsonl \
    --report packet-report.json
$ backstitch analyze \
    --packets packets.jsonl \
    --packet-report packet-report.json \
    --output analysis.jsonl \
    --report analysis-report.json
$ backstitch summarize-analysis \
    --deterministic-report spec-trace.json \
    --analysis-results analysis.jsonl
```

Packets bound the spec text, code snippets, tests, deterministic findings, and
exact evidence regions shown to the model. The provider receives a
packet-derived response schema, but model output remains untrusted: Backstitch
owns packet identity, validates structured rows and evidence locality, and
contains malformed output per packet.

Semantic verdicts can be stored in an immutable, content-addressed cache.
`cache_mode = "read-write"` calls the provider only for misses; `"require"`
forbids provider calls and fails on a miss. Cache identity includes the packet,
prompt, provider, request controls, contract version, and explicit search
epoch. Policy is deliberately excluded, so a policy-only change reprojects the
same frozen result with zero calls.

The repository ignores `.backstitch/`. Treat its semantic cache as disposable
acceleration state and its reports as fresh run outputs, not as source or
reviewed evidence to commit. The usual local flows are:

- update findings with bounded provider calls by explicitly selecting the
  trusted `pyproject.toml` and applying the reviewed static `read-write`
  options; valid hits are reused and only misses call the provider;
- replay with zero provider calls by using the default `require` profile; a
  missing object fails with exit `2`;
- diagnose without reading or writing cache objects by using a trusted config
  whose `[analyze] cache_mode` is `"off"`; and
- retain a deliberate new sample by changing the trusted `search_epoch` (and
  verifier `search_epochs`, when verification is enabled) before a
  `read-write` run.

When no Backstitch process is using it, the whole `.backstitch/` directory can
be removed. The next `read-write` run rebuilds needed objects; the next
`require` run reports misses. Backstitch does not currently provide
fine-grained pruning or concurrent whole-root deletion. A durable reviewed
snapshot for indefinite provider-free replay would be a separate future
feature, not a use of this cache.

The analysis report records completeness, cache hits and misses, provider
calls, budgets, evidence-bound diagnostics, candidate debt, applied policy,
problems, and the result digest. Exit `0` means the required review completed
and policy allowed it. Exit `1` is reserved for policy-failing human or
mechanically verified target findings. Exit `2` means the invocation, cache,
provider, normalization, completeness, budget, or publication failed.

Measure one exact semantic identity against the committed mutation and
negative-control corpus with:

```bash
$ backstitch eval \
    --corpus tests/semantic_eval/v3/manifest.json \
    --config pyproject.toml \
    --option analyze.cache_mode read-write \
    --option verify.enabled true \
    --option verify.cache_mode read-write \
    --output semantic-eval-report.json
```

The committed schema-3 smoke corpus exercises the current evaluator in report
mode only. The eval report separates evidence sufficiency from conditional and
end-to-end recall. It also records precision, false-positive and indeterminate
rates, uncached flip rate, required-cache replay stability, cost, and latency.
Report mode is observational. Enforce mode can grant stronger policy authority
only after a reviewed historical corpus, a passing report for the exact
analyzer/verifier composition, and an explicit human-pinned report digest.

Use `backstitch doctor --probe` before semantic analysis to check model
registration, credentials, constrained decoding, and endpoint reachability.
See [the semantic gate implementation guide](docs/implementation/07-deterministic-semantic-gate.md)
for cache trust, refresh, replay, evidence-authority, and rollout details.

## Development and Contributing

### Runtime

Backstitch uses `markdown-it-py` for CommonMark block structure and
`tree-sitter-python` for Python ownership, comments, and docstrings. Running on
Python 3.11 can therefore analyze newer target syntax such as PEP 695 generics
and PEP 701 f-strings without relying on the host interpreter's `ast` grammar.

### Testing

The repository pytest configuration runs the live cloud-provider contract test
in the default local suite. A normal local run needs a working `llm` model and
credential:

```bash
$ uv run pytest -q
```

For an intentionally hermetic run:

```bash
$ uv run pytest -q -m "not live_llm and not benchmark"
$ uv run pytest tests -q -n 0 -m benchmark
$ uv run pytest tests/live/test_live_llm.py -q -o run_live_llm=false
```

To reproduce the CI coverage report locally:

```bash
$ uv run pytest tests -q -n auto --dist loadgroup -m "not live_llm and not benchmark" --cov=backstitch --cov-report=term-missing
```

The completion gate also includes:

```bash
$ uv run pytest tests/acceptance -q
$ uv run ruff check backstitch tests bin
$ uv run ruff format --check backstitch bin .github/scripts tests
$ uv run mypy backstitch bin/release.py tests
$ uv run backstitch check --repo-root . --show-suppressions
```

### Live LLM Tests

`tests/live/test_live_llm.py` drives the real `packets` to `analyze` to `check`
to `summarize-analysis` path. It asserts structured contracts, transport, and
model success for cloud runs, not exact wording or classification.

```bash
# Store a provider key once, then run the local-default live test
$ uv run llm keys set openai
$ LLM_MODEL=gpt-4.1-mini uv run pytest tests/live/test_live_llm.py -q

# Or use a provider environment variable
$ OPENAI_API_KEY=... LLM_MODEL=gpt-4.1-mini uv run pytest -m live_llm -q
```

The same test supports a loopback OpenAI-compatible endpoint such as Ollama:

```bash
$ docker run -d --name backstitch-llm \
    -p 127.0.0.1:11434:11434 \
    -v "$PWD/.ollama-cache:/root/.ollama" \
    ollama/ollama
$ docker exec backstitch-llm ollama pull llama3.2:3b
$ BACKSTITCH_LOCAL_LLM_UPSTREAM=http://127.0.0.1:11434/v1 \
    BACKSTITCH_LOCAL_LLM_SERVED_MODEL=llama3.2:3b \
    BACKSTITCH_LIVE_LLM_KIND=local \
    uv run pytest -m live_llm -q
```

Cloud tests cost money and can fail because of provider outages, rate limits,
or model retirement. Local endpoints avoid provider credentials but add model
startup and output-quality variance. See
`docs/implementation/06-choosing-a-local-model.md` for measured local-model
guidance.

The hermetic CI matrix always deselects live tests and receives no provider
secret. The manual `semantic-refresh` workflow binds its trusted tool checkout
to the dispatch run's exact default-branch revision, requires the
`OPENAI_API_KEY` repository secret, restores only validated immutable cache
object trees, runs the bounded dogfood and eval refresh, and uploads fresh
review reports. Cache service state is optional and untrusted. Missing
credentials, incomplete analysis, or corrupt restored objects fail; cache
eviction causes a bounded cold refresh. The workflow never commits or pushes
cache or report content. It uses `repository_dispatch`, whose run ref is the
default branch, instead of branch-selectable `workflow_dispatch`. Trigger it
with write access:

```bash
$ gh api --method POST repos/{owner}/{repo}/dispatches \
    -f event_type=semantic-refresh
```

Repository collaborators with permission to create a repository dispatch can
request a report-only analysis of an open pull request. Supply the PR number
and the exact lowercase 40-hex head SHA shown by the GitHub API:

```bash
$ gh api --method POST repos/{owner}/{repo}/dispatches \
    -f event_type=semantic-pr-report \
    -F 'client_payload[pull_request_number]=123' \
    -f 'client_payload[head_sha]=0123456789abcdef0123456789abcdef01234567'
```

That workflow runs trusted Backstitch code, dependencies, prompts, provider
controls, and configuration from the exact default-branch workflow revision.
It treats the API-confirmed PR checkout as read-only data and never installs
or executes its workflows, hooks, plugins, build configuration, or commands.
The provider receives only the bounded packet projection selected by trusted
Backstitch: relevant specification text, code and test evidence, deterministic
findings, and exact evidence regions. Provider credentials exist only during
the credential check and analysis step. The resulting artifact is
observational; it does not comment on the PR, create a status, or gain merge
authority.

The separate `local-llm` workflow owns the Ollama canary.

### Releases

The local release helper runs regular, cloud-live, and local-live checks before
creating and pushing a version tag. The tag-triggered workflow publishes to
PyPI through Trusted Publishing and creates the GitHub Release.

```bash
$ bin/release.py --version X.Y.Z --dry-run
$ bin/release.py --version X.Y.Z

# When version files and CHANGELOG.md are already prepared
$ bin/release.py all --dry-run
$ bin/release.py all
```

See `docs/implementation/05-release-publishing.md` for release setup, rollback,
and verification.

## License

Backstitch is released under the MIT License. See [LICENSE](LICENSE).
