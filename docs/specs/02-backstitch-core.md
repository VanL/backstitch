# Backstitch Core Specification

Status: Preliminary

This spec defines the intended behavior for `backstitch`, a backstitch style
spec-code traceability checker with deterministic graph validation and
`llm`-backed semantic review.

## 1. Purpose And Scope [SC-1]

`backstitch` helps spec-driven projects keep intended behavior, implementation
ownership, tests, and plans traceable. It is built around the backstitch style
v1 grammar and should remain narrow until that workflow is proven against this
repository's specs and the first external target corpus, Weft.

The tool owns:

- deterministic trace graph construction
- deterministic issue classification
- stable text and JSON reports
- bounded semantic-review packet generation
- `llm`-backed semantic review result collection
- summary output that separates structural traceability findings from semantic
  advisory findings

The tool does not own:

- Weft runtime behavior
- project-specific code fixes
- automatic documentation rewrites
- arbitrary documentation systems
- a plugin framework for unrelated traceability styles

## 2. Mental Model [SC-2]

The core model is a typed trace graph:

`spec section <-> implementation owner <-> tests <-> plans`

Important concepts:

- **Target repository**: the repository being checked. It may be `backstitch`,
  Weft, or another backstitch style project.
- **Profile**: a built-in set of conventions for finding specs, code roots,
  planned docs, exploratory docs, section IDs, mappings, and backlinks.
- **Spec section**: a Markdown section or invariant with a stable reference
  code such as `[SC-4]`, `[MF-5]`, or `[OBS.13.10]`.
- **Implementation mapping**: a spec-authored pointer to code ownership,
  usually in an `_Implementation mapping_:` block.
- **Code backlink**: a code docstring or nearby comment that points back to
  a governing spec section.
- **Deterministic finding**: an objective parser or resolver finding. These
  findings are reproducible without model calls.
- **Semantic finding**: an advisory model-generated finding based on a bounded
  packet derived from deterministic results.

Deterministic checks answer whether declared edges exist and resolve. Semantic
analysis asks whether the resolved code appears to satisfy the spec and whether
unmapped code appears to need a spec owner.

## 3. Profiles And Target Roots [SC-3]

`backstitch` must ship with a first built-in profile named
`backstitch-style-v1`.

The `backstitch-style-v1` profile defaults to `backstitch`'s current shape:

```text
spec_roots:
  - docs/specs
plan_roots:
  - docs/plans
code_roots:
  - backstitch
  - tests
planned_spec_globs: []
exploratory_spec_globs: []
```

The same profile must allow root overrides for Weft's current shape:

```text
spec_roots:
  - docs/specifications
plan_roots:
  - docs/plans
code_roots:
  - weft
  - tests
planned_spec_globs:
  - docs/specifications/*A-*.md
exploratory_spec_globs:
  - docs/specifications/13B-*.md
  - docs/specifications/13C-*.md
```

The CLI must allow root overrides because related projects may use the same
traceability grammar with different root names, such as `docs/specs/` and a
project-specific package directory.

Profile configuration in the first implementation is intentionally limited to
roots and strictness. It must not become a general parser plugin language.

## 4. Deterministic Trace Graph [SC-4]

Deterministic mode must construct a report from target-repository files without
calling `llm`, Weft, network services, or project runtime code.

Spec parsing must support:

- Markdown heading IDs, such as `## Manager Behaviour [MA-1]`
- invariant-style bullets, such as `- **OBS.13.10**: ...`
- GitHub-style Markdown heading anchors
- implementation mapping blocks headed by markers such as
  `_Implementation mapping_:`
- backticked mapping tokens for paths, explicit `path::symbol` references, and
  advisory bare symbols

Python parsing must support:

- module, class, function, and method docstrings
- comments parsed with `tokenize`
- file-qualified spec references
- bare section references that resolve only when unique
- same-prefix numeric ranges
- comma-separated reference lists
- Markdown-anchor references

The resolver must produce stable graph records and issue records. Missing files,
missing sections, missing anchors, unsupported explicit ranges, and syntax
errors in requested Python files are deterministic errors. Weak links, missing
reciprocal backlinks, broad document-only references, planned/exploratory
references from shipped code, and unresolved bare mapping symbols are warnings
unless a later policy explicitly promotes them.

## 5. CLI Contract [SC-5]

`backstitch` must expose a console script named `backstitch`.

Required deterministic command:

```bash
backstitch check --repo-root . --profile backstitch-style-v1 --format text
backstitch check --repo-root . --profile backstitch-style-v1 --format json --output spec-trace.json
```

Required packet/result commands:

```bash
backstitch packets --repo-root . --profile backstitch-style-v1 --output packets.jsonl
backstitch analyze --packets packets.jsonl --model MODEL --output analysis.jsonl
backstitch summarize-analysis --deterministic-report spec-trace.json --analysis-results analysis.jsonl
```

Exit codes:

- `0`: command completed without deterministic errors
- `1`: deterministic trace errors exist, or warnings were promoted by an
  explicit CLI option
- `2`: invalid CLI arguments, unreadable target repository, malformed input
  file, or internal failure that prevents a report

The CLI must keep deterministic checks usable without semantic analysis. The
presence of `llm` as a dependency does not permit model calls during
`backstitch check`.

## 6. Report And Data Contracts [SC-6]

The deterministic JSON report must contain at least:

```json
{
  "profile": "backstitch-style-v1",
  "repo_root": "/absolute/path",
  "summary": {
    "spec_sections": 0,
    "code_refs": 0,
    "spec_mappings": 0,
    "errors": 0,
    "warnings": 0,
    "infos": 0
  },
  "spec_sections": [],
  "code_refs": [],
  "spec_mappings": [],
  "edges": [],
  "issues": []
}
```

Issue records must include stable issue code, severity, path, line where
available, message, and enough target metadata for a human or agent to locate
the problem.

Packet JSONL records must include:

- packet ID
- spec file and section ID
- section title and bounded section text
- resolved implementation owners
- bounded code snippets
- directly linked tests when available
- deterministic issues relevant to the packet
- prompt instructions for structured semantic review

Analysis-result JSONL records must include:

- packet ID
- classification
- confidence or rationale field
- evidence references against packet-local file/line data
- concise summary

Supported semantic classifications are:

- `ok`
- `confirmed_mismatch`
- `probable_mismatch`
- `missing_trace`
- `ambiguous`

## 7. Semantic Analysis [SC-7]

Semantic analysis must use the `llm` Python API directly. `llm` is a required
package dependency for `backstitch`.

Semantic analysis must operate on packets produced by deterministic mode. It
must not let the model roam the repository independently. The packet boundary
is the semantic review boundary.

Semantic findings are advisory. They must not change deterministic issue
severity and must not be treated as CI-failing findings unless a separate
policy explicitly chooses that later.

Tests for semantic analysis must not call external models. They should use fake
model adapters or equivalent local fakes to prove prompt construction, model
selection, output parsing, malformed model-output handling, and result
aggregation.

## 8. Boundaries And Non-Goals [SC-8]

`backstitch` must not depend on Weft. Weft may be a target repository for
checks, but `backstitch` must not import Weft or require a Weft manager,
TaskSpec, queue, or runtime.

The first implementation must not include:

- a Weft-backed analysis runner
- automatic code or documentation fixes
- a parser plugin framework
- support for arbitrary documentation styles
- support for every programming language
- LLM calls in deterministic checks
- CI failures based on semantic findings

If durable Weft-backed analysis becomes desirable later, it requires a separate
spec or spec revision because it changes the dependency and execution boundary.

## 9. Failure Modes And Edge Cases [SC-9]

The tool must handle these cases explicitly:

- missing spec roots or code roots
- unreadable files
- Python syntax errors in scanned files
- duplicate section IDs
- bare section references that are ambiguous
- section ranges that cannot be expanded without guessing
- references to planned or exploratory docs
- implementation mappings to missing paths
- explicit `path::symbol` references to missing symbols
- broad document-only references
- malformed deterministic report input
- malformed packet JSONL
- malformed model output

The default behavior should prefer precise warnings over guessed success. If a
reference cannot be resolved without inference, report it.

## 10. Verification Expectations [SC-10]

Verification must use real files and real subprocesses where practical.

Required proof surfaces:

- fixture-backed Markdown parser tests
- fixture-backed Python parser tests
- resolver tests for clean and broken graphs
- CLI subprocess tests for text, JSON, output file, and exit-code behavior
- self-corpus smoke check against this repository's specs, plans, docs, and
  `backstitch`
- target-corpus smoke check against `../weft` when present
- packet-generation tests that prove snippet bounds
- analysis-result tests with valid and malformed JSONL
- semantic-analysis tests using fake model adapters, not external model calls
- `ruff` and `mypy` over `backstitch`

Mocks must not replace the parser or resolver core path. Fakes are acceptable
only for external model calls and intentionally absent target repositories.

## Related Plans

- `docs/plans/2026-06-18-backstitch-style-spec-code-traceability-tool-plan.md`
