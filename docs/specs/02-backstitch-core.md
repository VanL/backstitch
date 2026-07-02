# Backstitch Core Specification

Status: Active

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

_Implementation mapping_:
- `backstitch/__init__.py`
- `backstitch/cli.py`
- `backstitch/resolver.py`

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

Declared invariants as first-class trace nodes — including semantic review of
whether a citing test actually binds its invariant — are **proposed** (not
yet adopted) in `docs/specs/05-backstitch-invariants.md` [INV-*]. Core
implementation work must not implement [INV-*] until that spec's status
changes.

_Implementation mapping_:
- `backstitch/models.py`

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

`plan_roots` are reserved in v1: plan files are not scanned for sections or
mappings unless they also fall under `spec_roots`. Mapping tokens pointing
into plan roots keep the `.md` warning semantics in [SC-11]. A later spec
revision may activate plan scanning with its own reference codes.

The default profile deliberately keeps `tests` in `code_roots`: test-to-spec
edges are part of the trace graph. Repositories whose test roots contain
fixture corpora (intentionally broken projects used by the test suite) must
exclude them through configuration ([CFG-6] `exclude`), and the repository's
committed configuration must make the advertised default invocation clean
([SC-10]). A default invocation that fails on the tool's own repository is a
shipped defect, not an accepted quirk.

Profile configuration in the first implementation is intentionally limited to
roots and strictness. It must not become a general parser plugin language.

Repository-local defaults for profiles, roots, strictness, scan excludes, and
related CLI options are defined in
`docs/specs/03-backstitch-configuration.md` [CFG-*].

_Implementation mapping_:
- `backstitch/config.py`
- `backstitch/profiles.py`

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

Markdown parsing must track fenced code blocks in both CommonMark forms: an
opening fence is at least three backticks (```` ``` ````) or at least three
tildes (`~~~`); the closing fence uses the same character and is at least as
long as the opening fence. Headings, invariant bullets, and mapping markers
inside either fence form are example content, not declarations: they must not
create sections, must not receive mapping attribution, and must not shift
attribution of the following mapping block. Both fence forms require
fixtures ([SC-10]) — tilde fences are exactly the kind of ambiguity that gets
mishandled when the spec only says "fenced code blocks".

Heading anchors must match what GitHub actually generates: computed from the
full heading text including the bracketed section ID (for
`## Alpha Feature [AF-1]`, the anchor is `#alpha-feature-af-1`). A mapping
block that has no preceding ID-bearing heading has no owner; its tokens are
ignored and reported (`MAPPING_BLOCK_OWNERLESS`).

Mapping path tokens are repo-relative, and resolution is a fixed ladder with
no discretion:

1. the token names an existing repo-relative path exactly — it resolves
   silently; this is the only spelling that resolves without a finding
2. no exact match, but exactly one file under the scan roots matches the
   token as a path suffix or basename — it resolves with a
   `MAPPING_PATH_INEXACT` warning naming the resolved path, so the edge is
   kept but the token is flagged for correction
3. no exact match and multiple suffix/basename candidates —
   `TARGET_PATH_AMBIGUOUS` error, no edge; ambiguity is reported, never
   resolved by picking one candidate
4. no candidates at all — `MAPPING_PATH_MISSING`, with an exact severity
   predicate: **warning** iff the token ends in `.md` and its path falls
   under a configured plan root (plan documents are execution artifacts that
   go archival, so a dangling plan pointer is advisory); **error** in every
   other case, including missing `.md` files under spec roots — spec files
   are load-bearing

Python parsing must support:

- module, class, function, and method docstrings
- comments parsed with `tokenize`
- file-qualified spec references
- bare section references that resolve only when unique
- same-prefix numeric ranges
- comma-separated reference lists
- Markdown-anchor references

Bare bracketed tokens use a known-prefix rule: the parser emits every
ID-shaped candidate, and the resolver keeps only candidates whose alphabetic
prefix matches a section-ID prefix that exists somewhere in the corpus.
Unknown-prefix tokens (for example `window[N-1]` or `[JIRA-123]`) are prose
noise and stay silent. A known-prefix candidate that matches no section is a
warning (`CODE_REF_BARE_UNRESOLVED`), never a guessed edge and never a hard
error, because bare references in comments and prose are weak links by
definition.

The resolver must produce stable graph records and issue records. Re-running
on identical inputs must yield byte-identical JSON output. Missing roots,
missing files, missing sections, missing anchors, unsupported explicit ranges,
explicit `path::symbol` references to missing symbols, unreadable files, and
syntax errors in requested Python files are deterministic errors. Ambiguous
bare references are context-dependent: in an asserted backlink (a docstring
`Spec:` marker or a spec mapping) the reference claims a specific trace edge
that cannot be established, so ambiguity is an error; in comments and prose
it is a warning. Weak links, missing reciprocal backlinks, broad
document-only references, planned/exploratory references from shipped code,
ownerless mapping blocks, and unresolved advisory symbols are warnings unless
a later policy explicitly promotes them.

A single unreadable or non-UTF-8 file must never abort the scan: the file gets
a per-file `FILE_UNREADABLE` error naming the path, and the rest of the report
is still produced. Whole-run aborts are reserved for an unusable target
repository, not for one bad file inside it.

_Implementation mapping_:
- `backstitch/markdown_specs.py`
- `backstitch/python_refs.py`
- `backstitch/resolver.py`
- `backstitch/models.py`

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
backstitch analyze --packets packets.jsonl --output analysis.jsonl
```

Model selection may come from `--model`, config (`[analyze].model`), `LLM_MODEL`,
or the `llm` default ([CFG-5], [SC-7]).

```bash
backstitch analyze --packets packets.jsonl --model MODEL --output analysis.jsonl
```

```bash
backstitch summarize-analysis --deterministic-report spec-trace.json --analysis-results analysis.jsonl
```

Exit codes:

- `0`: command completed without deterministic errors
- `1`: deterministic trace errors exist, or warnings were promoted by an
  explicit CLI option
- `2`: invalid CLI arguments, unreadable target repository, malformed input
  file, or internal failure that prevents a report

Exit code `1` is a statement about the target repository; exit code `2` is a
statement about the invocation or the tool. The two must never blur: an
unwritable `--output` path, a deterministic report missing required keys, a
malformed packets file, or an unknown model name are all exit `2`, even though
the scan itself may have succeeded.

The missing-roots boundary is pinned to that rule: a missing or unreadable
`--repo-root` is an invocation problem — no report, exit `2`. A repo root
that exists but is missing a configured scan root (`--spec-root docs/specz`)
is a statement about the target repository: the scan proceeds, the report is
produced with a `SCAN_ROOT_MISSING` error record, and the command exits `1`.
Implementations must not collapse the second case into the first.

No invocation may surface a Python traceback. Every failure path prints a
one-line `backstitch: error: ...` diagnostic naming the offending input where
known, and exits `2`. A traceback reaching the user is a bug by definition.

The CLI must keep deterministic checks usable without semantic analysis. The
presence of `llm` as a dependency does not permit model calls during
`backstitch check`.

_Implementation mapping_:
- `backstitch/cli.py`

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
- truncation warnings (`packet_warnings`) whenever a snippet, owner, or
  section bound trimmed content, so a model never mistakes a partial packet
  for a complete one; repository-level deterministic problems (missing roots,
  syntax errors) surface here as advisory context rather than polluting every
  packet's issue list

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

_Implementation mapping_:
- `backstitch/models.py`
- `backstitch/reporting.py`
- `backstitch/analysis_packets.py`
- `backstitch/analysis_results.py`

## 7. Semantic Analysis [SC-7]

Semantic analysis must use the `llm` Python API directly. `llm` is a required
package dependency for `backstitch`.

Semantic analysis must operate on packets produced by deterministic mode. It
must not let the model roam the repository independently. The packet boundary
is the semantic review boundary.

Model output is untrusted input. The `packet_id` in a result record is always
taken from the packet being analyzed, never from the model response, so a
hallucinated ID cannot corrupt aggregation. Malformed model output (including
markdown-fenced JSON) is handled per packet: one bad response yields one
`ambiguous`/error record, not an aborted run.

`analyze` may process packets concurrently, but output must remain
deterministic: results are emitted in packet order regardless of worker
completion order.

Semantic findings are advisory. They must not change deterministic issue
severity and must not be treated as CI-failing findings unless a separate
policy explicitly chooses that later.

Tests for semantic analysis must not call external models. They should use fake
model adapters or equivalent local fakes to prove prompt construction, model
selection, output parsing, malformed model-output handling, and result
aggregation.

_Implementation mapping_:
- `backstitch/analysis_llm.py`
- `backstitch/analysis_packets.py`
- `backstitch/analysis_results.py`

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

`llm` must be imported lazily and only inside the `analyze` execution path.
`check` and `packets` must be structurally incapable of importing it — the
boundary is enforced by import placement, not by convention, and [SC-10]
proves it with a subprocess test.

If durable Weft-backed analysis becomes desirable later, it requires a separate
spec or spec revision because it changes the dependency and execution boundary.

_Implementation mapping_:
- `backstitch/cli.py`
- `backstitch/resolver.py`

## 9. Failure Modes And Edge Cases [SC-9]

The tool must handle these cases explicitly:

- missing spec roots or code roots
- unreadable files, including non-UTF-8 content (per-file error, scan
  continues; see [SC-4])
- Python syntax errors in scanned files
- duplicate section IDs
- bare section references that are ambiguous
- section ranges that cannot be expanded without guessing
- references to planned or exploratory docs
- implementation mappings to missing paths
- mapping tokens with multiple suffix/basename candidates (ambiguous; no
  edge — [SC-4] ladder)
- mapping tokens resolved via a unique suffix/basename match (inexact
  warning, edge kept — [SC-4] ladder)
- explicit `path::symbol` references to missing symbols
- mapping blocks with no owning ID-bearing heading
- headings and mapping markers inside fenced code blocks (ignored; see [SC-4])
- broad document-only references
- malformed deterministic report input, including structurally valid JSON that
  is missing required report keys
- malformed packet JSONL
- malformed model output
- unwritable `--output` destinations

The default behavior should prefer precise warnings over guessed success. If a
reference cannot be resolved without inference, report it.

Controlled suppression of selected traceability findings (meta specs,
per-section ignores, inline `noqa`) is defined in
`docs/specs/04-backstitch-traceability-exclusions.md` [EXC-*].

_Implementation mapping_:
- `backstitch/resolver.py`

## 10. Verification Expectations [SC-10]

Verification must use real files and real subprocesses where practical.

Required proof surfaces:

- fixture-backed Markdown parser tests
- fixture-backed Python parser tests
- resolver tests for clean and broken graphs
- CLI subprocess tests for text, JSON, output file, and exit-code behavior
- a subprocess proof that deterministic commands (`check`, `packets`) never
  import `llm`
- the **acceptance probe suite** — small, surgical probes covering the exact
  cases known to separate serious implementations from deficient ones. These
  are acceptance criteria, not ordinary tests: an implementation that fails
  any probe is not a candidate for integration regardless of its own suite
  passing. House them in one recognizable place (suggested:
  `tests/acceptance/`) so a reviewer can run the whole suite as a unit.
  Required probes:
  1. a GitHub anchor to an ID-bearing heading resolves
     (`#alpha-feature-af-1` form)
  2. heading-shaped lines inside backtick fences AND tilde fences create no
     sections and hijack no mapping attribution
  3. a non-UTF-8 file yields `FILE_UNREADABLE` and the scan continues to a
     full report
  4. a document-only reference fires `CODE_REF_BROAD`
  5. a twice-defined section ID fires `SPEC_SECTION_DUPLICATE` even when
     unreferenced
  6. the committed config demonstrably applies (compare against
     `--no-config`)
  7. an unknown config key exits `2` naming the key and file (under the
     default `allow_unknown_keys = false`; the escape hatch downgrading to a
     warning is its own [CFG-9] test, not a probe failure)
  8. malformed model output is contained per packet, never aborting the run
  9. concurrent `analyze` output order is byte-identical to serial order
  10. sibling target discovery works from a linked worktree ([SC-12])
  11. key-incomplete report JSON, malformed packet JSONL, and an unwritable
      `--output` path each exit `2` with a one-line error and no traceback
  12. a mapping token with multiple suffix/basename candidates fires
      `TARGET_PATH_AMBIGUOUS` with no edge, and the same token with exactly
      one candidate resolves with `MAPPING_PATH_INEXACT` ([SC-4] ladder)
- every issue code in the [SC-11] table has at least one test that proves it
  fires; a declared code with no firing test is an untested contract and a
  verification failure
- self-corpus smoke check against this repository's specs, plans, docs, and
  `backstitch`, using the repository's committed configuration and the
  advertised default invocation. Success criteria: exit `0`, zero
  error-severity and zero warning-severity findings in the default output,
  and every suppression recoverable via `--show-suppressions` and documented
  in implementation notes — a clean report produced by unauditable hiding is
  a failure, not a pass. Note the [SC-4] ladder consequence: committed
  mappings in this repository must use exact repo-relative paths, since a
  basename shortcut fires `MAPPING_PATH_INEXACT` and fails the
  zero-warnings gate — fix the token, never suppress the warning
- target-corpus smoke check against `../weft` when present
- packet-generation tests that prove snippet bounds and truncation warnings
- analysis-result tests with valid and malformed JSONL
- semantic-analysis tests using fake model adapters, not external model calls
- `ruff` and `mypy` over `backstitch`

Mocks must not replace the parser or resolver core path. Fakes are acceptable
only for external model calls and intentionally absent target repositories.

Assertion style: tests pin structured issue fields (code, severity, path,
line, section ID, symbol) exactly, and assert message text by substring, not
verbatim equality. No test or tool may parse structure back out of a rendered
message; the structured fields are the contract, the message is presentation.
External-corpus regression tests pin known debt as structured
`(code, path, section_id)` signatures — ideally count-pinned so both new
errors and silently disappearing debt fail the gate. Warning-class debt on
an external corpus (for example `MAPPING_PATH_INEXACT` from shorthand
mapping tokens) may be baselined the same way; the gate exists to catch
change, not to force another project's cleanup. A committed golden
full-report fixture is required for changes that alter resolver
classification behavior (issue codes, severities, edge emission) so the
delta is reviewed rather than discovered, and optional otherwise; it must be
paired with a documented regeneration command so updating it is deliberate
but not painful.

_Implementation mapping_:
- `tests/test_markdown_specs.py`
- `tests/test_python_refs.py`
- `tests/test_resolver.py`
- `tests/test_cli.py`
- `tests/test_backstitch_corpus_traceability.py`

## 11. Issue Codes [SC-11]

Deterministic issue codes and default severities:

| Code | Severity | Meaning |
|------|----------|---------|
| `SCAN_ROOT_MISSING` | error | Configured spec, plan, or code root not found |
| `SPEC_FILE_MISSING` | error | Referenced spec file does not exist |
| `SPEC_SECTION_MISSING` | error | File-qualified section reference not found in that file |
| `SPEC_SECTION_AMBIGUOUS` | error/warning | Bare ID matches multiple sections (asserted backlinks and mappings: error; comments/prose: warning) |
| `SPEC_SECTION_DUPLICATE` | warning | Section ID defined more than once |
| `SPEC_ANCHOR_MISSING` | error | File#anchor reference not found |
| `REF_RANGE_UNSUPPORTED` | error | Section range could not be expanded |
| `MAPPING_PATH_MISSING` | error/warning | Mapping path missing (warning iff `.md` under a plan root — exact predicate in [SC-4]; otherwise error) |
| `MAPPING_PATH_INEXACT` | warning | Mapping token resolved via unique suffix/basename match, not an exact repo-relative path |
| `TARGET_PATH_AMBIGUOUS` | error | Mapping token matches multiple paths after exact-match precedence; no edge emitted |
| `MAPPING_SYMBOL_MISSING` | error | Explicit `path::symbol` names a symbol absent from that file |
| `MAPPING_SYMBOL_UNRESOLVED` | warning | Advisory bare symbol in mapping could not be resolved |
| `MAPPING_BLOCK_OWNERLESS` | warning | Mapping block has no preceding ID-bearing heading; tokens ignored |
| `PYTHON_SYNTAX_ERROR` | error | Python file could not be parsed |
| `FILE_UNREADABLE` | error | File could not be read (missing permissions, non-UTF-8); scan continues |
| `CODE_REF_BARE_UNRESOLVED` | warning | Known-prefix bare reference matches no section |
| `SPEC_MAPPING_RECIPROCAL_MISSING` | warning | Code backlink without spec mapping |
| `CODE_BACKLINK_RECIPROCAL_MISSING` | warning | Spec mapping without code backlink |
| `CODE_REF_BROAD` | warning | Document-only code reference |
| `CODE_REF_PLANNED_SPEC` | warning | Shipped code cites planned spec |
| `CODE_REF_EXPLORATORY_SPEC` | warning | Shipped code cites exploratory spec |
| `SPEC_SECTION_UNMAPPED` | info | Spec section has no implementation mapping |
| `CODE_REF_UNMAPPED_FROM_SPEC` | info | Code cites spec without spec mapping to file |

Severity rationale: errors mean the author asserted something false or
unusable as asserted (a named file, section, anchor, or symbol that does not
exist, or an asserted trace edge that cannot be established), or the tool
could not read what it was told to read. Warnings mean the link is weak or
one-directional but nothing asserted is broken. `SPEC_SECTION_AMBIGUOUS`
straddles the line by context: an ambiguous ID in an asserted backlink or
mapping means the claimed edge cannot be built (error), while the same ID in
a comment or prose is a weak link (warning). In every case, report
precisely and never guess an edge.

Every issue record carries at least one non-empty locator (`path`,
`section_id`, or `symbol`), and issues arising from a code reference carry the
citing file and line, so a human or agent can always navigate to the problem.

Invariant-traceability issue codes (`INVARIANT_*`) are proposed in
`docs/specs/05-backstitch-invariants.md` [INV-8] and follow this table's
severity rationale.

_Implementation mapping_:
- `backstitch/resolver.py`

## 12. Sibling Target Discovery [SC-12]

External target corpora (for example Weft) are discovered via
`backstitch/target_roots.py`:

1. `BACKSTITCH_WEFT_ROOT` environment override
2. `[target_roots].weft` from discovered config ([CFG-5], [CFG-6])
3. `<git-main-repo-parent>/weft` (sibling of the backstitch repository)

Discovery must work from the main repository checkout and from
`.worktrees/*` linked checkouts. The worktree case is the one that breaks in
practice: naive `<checkout-parent>/weft` resolves to `.worktrees/weft` from a
linked worktree, silently skipping the corpus. Verification must include a
fixture that runs discovery from a linked-worktree path with no
`BACKSTITCH_WEFT_ROOT` set and asserts the target resolves to the sibling of
the **main** checkout's parent, plus assertions that the environment override
and the config override each beat sibling discovery.

_Implementation mapping_:
- `backstitch/target_roots.py`

## Related Plans

- `docs/plans/2026-07-02-backstitch-four-way-reconciliation-plan.md` (implementing)
- `docs/plans/2026-06-18-backstitch-style-spec-code-traceability-tool-plan.md` (superseded)
- `docs/plans/2026-07-01-backstitch-toml-configuration-plan.md` (archival)
- `docs/plans/2026-07-02-backstitch-traceability-exclusions-plan.md` (archival)
