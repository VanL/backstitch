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

[INV-*] is Active. Declared invariants are first-class trace nodes:
deterministic mode resolves declarations and test bindings, semantic mode
reviews bounded binding packets, and semantic verdicts remain advisory.

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
test_roots:
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
test_roots:
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

Test roots classify paths already traversed through code roots. A layer that
explicitly replaces `code_roots` and omits `test_roots` resets test roots to
empty at that precedence. A layer that supplies `test_roots` replaces them and
otherwise retains effective code roots. After all config and CLI layers, every
nonempty test root must be equal to or nested under a final effective code
root. `ProfileConfig.with_overrides` follows this same ordered algorithm. A
lone `test_roots` override retains inherited code roots. Repeatable
`--test-root` is available wherever `--code-root` is available. An empty
effective test-root set does not disable invariant diagnostics: a partial
production-only scan remains a valid invocation but reports required
declarations as untested because their tests were intentionally omitted.

Profile configuration in the first implementation is intentionally limited to
roots and strictness. It must not become a general parser plugin language.

Repository-local defaults for profiles, roots, strictness, scan excludes, and
related CLI options are defined in
`docs/specs/03-backstitch-configuration.md` [CFG-*].

_Implementation mapping_:
- `backstitch/config.py`
- `backstitch/profiles.py`
- `backstitch/settings.py`

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

Backticked mapping tokens are Markdown inline-code tokens (`code_inline`)
inside implementation mapping blocks. Their stored target text is the
`markdown-it-py` inline-code content after Markdown normalization, while
Backstitch still classifies that target as `path`, `path_symbol`, or `symbol`.
Any heading token produced by `markdown-it-py` may define a section if its
heading text ends in a valid section ID after CommonMark heading normalization,
including setext headings and ATX headings with closing hashes.
If the complete normalized heading text ends in one square-bracket marker (or
is only that marker) but the marker has a blank or invalid ID or lacks a
section title, the parser emits `SPEC_SECTION_HEADING_INVALID` and defines no
section. A heading with no terminal square-bracket marker remains ordinary
ID-less prose; brackets followed by later heading prose are not reserved
section syntax.

Markdown block structure is delegated to `markdown-it-py` using its CommonMark
parser. Backstitch must not maintain an independent Markdown fence,
indented-code, or block-boundary parser. Headings, invariant bullets,
implementation mapping markers, and traceability markers are interpreted only
from non-code Markdown tokens produced by `markdown-it-py`. `fence` and
`code_block` tokens are example content, not declarations. Block-level HTML
tokens are also non-declarative except when the token's source text is a
recognized [EXC-4] `<!-- backstitch: ... -->` traceability marker; those marker
tokens follow the same preamble and immediate-section placement rules as
`_Traceability:` marker paragraphs. The enclosing block token's `map` source
lines are the line-number source of truth for diagnostics. Backstitch may
inspect the original source lines covered by a non-code token to interpret
Backstitch-specific marker syntax, but it must not use those lines to override
`markdown-it-py`'s block classification.

Heading anchors must match what GitHub actually generates: computed from the
full heading text including the bracketed section ID (for
`## Alpha Feature [AF-1]`, the anchor is `#alpha-feature-af-1`). A mapping
block that has no preceding ID-bearing heading has no owner; its tokens are
ignored and reported (`MAPPING_BLOCK_OWNERLESS`).

Mapping-block ownership follows the nearest preceding ID-bearing heading. An
ID-less heading at the same depth or shallower than the current owning heading
clears that ownership — a following mapping block has no owner and is reported
(`MAPPING_BLOCK_OWNERLESS`). A deeper ID-less subheading under an ID-bearing
section does not clear ownership: subsection titles between an ID heading and
its `_Implementation mapping_:` block are prose structure, not a new owner.
Example: under `## 6. Schema [CFG-6]`, a `### 6.7 Scan boundaries` subheading
does not detach a mapping block that still documents `[CFG-6]`; an
`## Open Questions` heading at the same depth as `## 6. Schema [CFG-6]` does.

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
- comments from the runtime-independent `tree-sitter-python` parse tree
- file-qualified spec references
- bare section references that resolve only when unique
- same-prefix numeric ranges
- comma-separated reference lists
- Markdown-anchor references

Python structure — owner symbols, doc blocks, statement spans, and comments —
is derived from `tree-sitter-python`, not the running interpreter's `ast` or
`tokenize`. Backstitch keeps a thin traceability layer over parser nodes and
does not maintain its own Python grammar. Backlink extraction tracks the parser
tree and is not limited to the syntax version of the interpreter running
Backstitch.

Bare bracketed tokens use a known-prefix rule: the parser emits every
ID-shaped candidate, and the resolver keeps only candidates whose alphabetic
prefix matches a section-ID prefix that exists somewhere in the corpus.
Unknown-prefix tokens (for example `window[N-1]` or `[JIRA-123]`) are prose
noise and stay silent. A known-prefix candidate that matches no section is a
warning (`CODE_REF_BARE_UNRESOLVED`), never a guessed edge and never a hard
error, because bare references in comments and prose are weak links by
definition.

The exact unbracketed ID regular expression is
`[A-Z][A-Za-z0-9.\-]*[0-9][A-Za-z0-9]*`. It requires an uppercase initial and
at least one digit. Dots and hyphens may occur before the token's last digit;
the suffix after that digit is alphanumeric only. All section references and
invariant IDs use this one grammar.

The resolver must produce stable graph records and issue records. Re-running
on identical inputs must yield byte-identical JSON output. Missing roots,
missing files, missing sections, missing anchors, unsupported explicit ranges,
explicit `path::symbol` references to missing symbols, and unreadable files are
deterministic errors. A Python file the code parser cannot parse is a coverage
warning (`PYTHON_SYNTAX_ERROR`), suppressible by config/exclusion per-file
rules and subject to `check --warnings-as-errors`; inline `# backstitch: noqa`
inside the unparseable file cannot suppress it because no inline directives
were extracted. Ambiguous bare references are context-dependent: in an asserted
backlink (a docstring `Spec:` marker or a spec mapping) the reference claims a
specific trace edge that cannot be established, so ambiguity is an error; in
comments and prose it is a warning. Weak links, missing reciprocal backlinks,
broad
document-only references, planned/exploratory references from shipped code,
ownerless mapping blocks, and unresolved advisory symbols are warnings unless
a later policy explicitly promotes them.

Invariant marker prefixes are reserved before generic bracket-reference
extraction. Their grammar and physical-source-line restriction are [INV-3].
Marker IDs cannot also emit ordinary code references.

A single unreadable or non-UTF-8 file does not abort deterministic `check` or
an obligation read: the input is represented by the ordinary per-file issue
and by [EVC-8.2]'s stable unreadable snapshot-manifest row while other readable
facts remain available. Discovery, packet construction, and current semantic
analysis instead fail closed with `SOURCE_UNREADABLE` and exit `2` when an
included semantic input is unreadable, because they must prove a complete
catalog and packet universe. Whole-run aborts for deterministic `check` remain
reserved for an unusable target repository, not for one bad file inside it.

_Implementation mapping_:
- `backstitch/grammar.py`
- `backstitch/markdown_specs.py`
- `backstitch/code_parser.py`
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

Required obligation, packet, and result commands:

```bash
backstitch packets --repo-root . --profile backstitch-style-v1 --output packets.jsonl
backstitch packets --repo-root . --kind section --output packets.jsonl
backstitch packets --repo-root . --kind invariant --output invariants.jsonl
backstitch packets --repo-root . --kind all --output all-packets.jsonl
backstitch packets --repo-root . --kind all --output packets.jsonl --report packet-report.json
backstitch obligation list --repo-root . --format json
backstitch obligation OBLIGATION_ID --repo-root . --format json
backstitch obligation OBLIGATION_ID --summarize-evidence
backstitch obligation OBLIGATION_ID --find-evidence
backstitch obligation OBLIGATION_ID --candidate CANDIDATE_ID
backstitch guide alignment --format text
backstitch analyze --repo-root . --output analysis.jsonl --report analysis-report.json
backstitch analyze --packets packets.jsonl --packet-report packet-report.json --output analysis.jsonl --report analysis-report.json
backstitch eval --corpus tests/semantic_eval/v3/manifest.json --output semantic-eval-report.json
backstitch cache cleanup-lock --cache-path PATH (--analysis-key HASH | --verify-key HASH) --lock-stale-seconds SECONDS --reason TEXT
```

The exact option grammar, selector exclusivity, pagination, source-snapshot
rules, and current-versus-historical analyze modes are [EVC-5.1] and [EVC-8.3].
Current analysis derives packet schema 3 from `--repo-root`; packet input is a
historical replay. `backstitch mcp` is registered only if the optional Phase D
adapter ships and then follows [EVC-8.6]. CLI is the complete required
interface. No obligation, guide, packet, or implemented MCP operation writes
repository source.

`cache cleanup-lock` requires exactly one key flag. `--analysis-key` addresses
the analyzer lock/guard/audit contract; `--verify-key` addresses the disjoint
verifier contract in [SEM-4]. Both require the explicit stale interval because
the cleanup command performs no configuration discovery.

Every requested semantic output is distinct from every other input and output
as [EVC-5.1] requires. Equality or semantic-root overlap is invalid before
snapshot capture, temporary creation, cache work, adapter construction,
provider work, or publication.

`--kind` defaults to `section`. Filtering affects packet output only, not the
deterministic report, policy, or exit status.
For one corpus and policy, `section`, `invariant`, and `all` therefore have the
same exit code: `1` when any rendered issue has a severity in effective
`diagnostics.fail_on`, otherwise `0` after successful output.
The schema-2 `--report` sidecar is accepted only with `--kind all`; filtered
packet output is an inspection artifact and cannot be replayed by `analyze`.
Current `analyze --repo-root` always uses the complete selected corpus.

Model selection may come from `--model`, config (`[analyze].model`), `LLM_MODEL`,
or the `llm` default ([CFG-5], [SC-7]).

```bash
backstitch analyze --packets packets.jsonl --packet-report packet-report.json --model MODEL --output analysis.jsonl
```

All analyze output flags are optional. The unified semantic-analysis interface
owns staged publication and stdout always renders the final text summary or
complete canonical report selected by `--format` ([EVC-5.1]).

```bash
backstitch summarize-analysis --deterministic-report spec-trace.json --analysis-results analysis.jsonl
```

`summarize-analysis` is presentation-only. It validates every input row, exits
`2` for any malformed report or result, never applies semantic policy or
dispositions, never asserts verification state, and never exits `1`.

Required environment-diagnosis command:

```bash
backstitch doctor
backstitch doctor --probe --format json
```

`doctor` diagnoses the semantic-analysis environment (the `llm`
installation, model resolution, credentials, constrained-decoding
capability, and — with `--probe` — endpoint reachability) per [SC-14]. It
accepts `--model`, `--config`, and `--no-config` with `analyze`'s
semantics, anchoring config discovery at the current working directory.
`doctor` exits `0` when no check reports `fail` (skipped checks never
affect the exit code) and `2` when any check fails or doctor itself cannot
run; it never exits `1`, which is reserved for statements about the target
repository.

Exit codes:

- `0`: command completed without deterministic errors
- `1`: target-repository findings selected by effective policy exist. For
  `analyze`, the semantic finding must also satisfy [SEM-5] and [SEM-6].
- `2`: invalid CLI arguments, unreadable target repository, malformed input
  file, or internal failure that prevents a report

Diagnostic policy controls which deterministic target-repository findings are
rendered as `error`, `warning`, `info`, or `off`, and which rendered levels
cause `check` and `packets` to exit `1`. This policy never changes exit `2`:
invalid CLI arguments, malformed configuration, malformed input artifacts,
output write failures, and internal failures remain invocation or tool failures
and are not configurable as target diagnostics.

`--warnings-as-errors` and `[check].warnings_as_errors` are compatibility
shorthands for adding `warning` to the command's effective `fail_on` levels.
They do not mutate diagnostic identity or the configured level written in JSON
reports.

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

The CLI must keep deterministic checks and source reads usable without semantic
analysis. The presence of `llm` as a dependency does not permit importing or
calling it during `check`, `packets`, `obligation`, or `guide`.

_Implementation mapping_:
- `backstitch/cli.py`
- `backstitch/analysis_llm.py`
- `backstitch/analysis_results.py`
- `backstitch/artifact_contracts.py`
- `backstitch/check_pipeline.py`
- `backstitch/doctor.py`
- `backstitch/profiles.py`
- `backstitch/reporting.py`
- `backstitch/resolver.py`
- `backstitch/semantic_analysis.py`
- `backstitch/semantic_reports.py`

### 5.1 Configuration Inputs [SC-5.1]

Every command that consumes Backstitch settings accepts the configuration
selection and repeatable generic override grammar defined in [CFG-5.1]:

```bash
backstitch --config PATH --option KEY VALUE <command> ...
backstitch --no-config --option KEY VALUE <command> ...
```

`--config PATH` may name any TOML filename. It is explicit selection, not an
additional discovery convention. `--config`, `--no-config`, and `--option`
must all be rejected rather than silently ignored by commands that do not
consume configuration. Invalid option syntax or an invalid effective
configuration is exit `2` before command side effects.

_Implementation mapping_:

- `backstitch/settings.py`
- `backstitch/cli.py`
- `tests/test_cli_config.py`
- `tests/test_settings.py`

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

Issue records must include stable diagnostic identity and locator fields:
canonical `code`, stable `short_code`, optional `context`, effective
`severity` (`error`, `warning`, or `info`), `default_severity` from
Backstitch's packaged default policy before repository policy overrides, path,
line where available, message, and enough target metadata for a human or agent
to locate the problem. `message` is presentation, not API. Automation and tests
must key on structured fields.

`off` is a diagnostic policy result, not a report severity. A diagnostic whose
effective level is `off` is omitted from `issues`, excluded from report summary
counts, and recoverable only through the suppression/audit view with reason
`diagnostic level off`. `fail_on` and `suppressible_levels` may contain only
`error`, `warning`, and `info`; `off` is invalid in those lists.

New deterministic reports require `summary.invariants`, `invariants`, and
`binds`. Invariant records contain `invariant_id`, `statement`, `tier`,
`declaration_kind` (`code` or `spec`), `path`, `line`, nullable `owner_symbol`,
and nullable `section_id`. Exactly one owner locator is non-null. Code owner
symbols use the parser's source-qualified name; module declarations use the
reserved `<module>` sentinel, which cannot collide with a Python identifier.
`summary.invariants` equals the invariant-record count, including duplicates.
Bind records contain `invariant_id`, `test_path`, `test_symbol`, `marker_line`,
`start_line`, and `end_line`. Test symbols use the same source-qualified parser
name for sync and async definitions; binds are unique by invariant ID, path,
and symbol, retaining the smallest marker line. Existing `edges` remain mapping
and backlink relations. Invariant issue records use `invariant_id` with null
`section_id`. Marker-invalid issues with no parseable ID leave both ID fields
null and use path and physical line plus an available syntactic owner; all
other issues use null `invariant_id`. A duplicate root issue uses the smallest
`(path, line)` across its colliding declarations and sections, using canonical
repository-relative POSIX paths and normal Python string and tuple order.

The report loader accepts the legacy shape only when all three invariant
additions are absent and normalizes to zero and empty collections. Partial
shapes are malformed. Producers always emit the new shape.

Current packet producers emit only the closed packet schema 3 and packet-report
schema 2 contracts in [EVC-9.1]. The source-derived model projection excludes
snapshot, readiness, skip reason, policy, cache, and provenance. Packet and
report byte ceilings are fatal rather than truncating required evidence or the
closed counterevidence universe. Canonical analyzer results remain schema 2;
the current/historical analysis report is schema 3 and contains the exact
alignment, currentness, verification, finding, debt, cache, and problem
projections in [EVC-9.1] and [SEM-7].

Packet schema 2 and unversioned legacy artifacts are bounded historical or
migration input only. They may be validated and rendered by legacy
presentation paths, but cannot produce a schema-3 current or qualification
report, satisfy current completeness, enter a current cache identity, or gain
gate authority. They are never silently rewritten. Partial version markers,
mixed legacy/new fields, and unversioned cache objects are malformed.

Human-facing text output should render both short and canonical codes, for
example `[BSS001 SPEC_FILE_MISSING]`. Machine-readable JSON keeps the canonical
long code as the primary key and includes `short_code` as a display alias.

Section and invariant packet rows share the exact obligation, requirement,
declared-evidence, counterevidence, trace-summary, evidence-region, issue,
warning, readiness, and snapshot shapes in [EVC-9.1]. The model-visible issue
projection excludes repository-effective deterministic severity so policy
changes cannot alter packet or analysis identity.

_Implementation mapping_:
- `backstitch/diagnostics.py`
- `backstitch/models.py`
- `backstitch/artifact_contracts.py`
- `backstitch/check_pipeline.py`
- `backstitch/reporting.py`
- `backstitch/analysis_packets.py`
- `backstitch/analysis_results.py`
- `backstitch/resolver.py`

## 7. Semantic Analysis [SC-7]

Semantic analysis uses the `llm` Python API directly. Deterministic commands
never import it or construct a model. Analysis operates only on validated
source-derived packets. The packet projection is the model boundary; the model
never roams the repository. Verification is a blinded adversarial procedure;
it does not require a distinct provider or model ([EVC-3], [EVC-5]).

All gate authority, evidence validation, caching, diagnostics, reports, output
publication, and exit selection are owned by one production interface:

```python
run_semantic_analysis(request: SemanticAnalysisRequest) -> SemanticAnalysisRun
```

The packet-level semantic runner remains the single analyzer/cache/policy
implementation seam. Current-repository orchestration wraps it with
[EVC-5.1]'s one-snapshot derivation, readiness gate, verifier, recapture, and
staged publication. Historical mode validates exact packet/report bytes but
cannot acquire current authority. Settings own inference identities, request
controls, caches, completeness, budgets, verification, and dispositions.
Policy owns effective levels, winning-rule identity, qualification selectors,
and `fail_on`.

The production interface owns deterministic packet iteration, lazy adapter
construction, single flight, blinded verification, policy, serialization, and
publication. Current mode stages all requested artifacts, captures the same
repository again, and publishes in [EVC-5.1]'s dependency order only when the
snapshot identities match. A changed snapshot or publication failure is exit
2 and emits no current success claim. CLI code invokes this one path and does
not write or re-evaluate semantic artifacts. `summarize-analysis` never calls
the gate entry point.

Model output is the closed untrusted shape in [SEM-3]. Packet identity, kind,
hashes, verification state, code, and provenance come from trusted input and
normalization, never model fields. Evidence is validated and reconstructed
exactly once against [SEM-5]. A malformed response or provider failure emits no
canonical analyzer result row or verifier event, records one
[SEM-7]/[EVC-8.4] problem, and forces exit 2. Concurrency may change worker
completion order but never packet, event, result, or report order.

Default tests never call external models. They use controlled adapters at the
external boundary while exercising real packet, evidence, cache, policy,
serialization, and CLI assembly.

Live analysis remains an explicit pytest-policy lane. Disabled live tests are
collected and skipped. Once enabled, missing credentials, transport failure,
invalid rows, report problems, or incomplete output fail. A cloud live test
requires report status `complete`, no problems, and one valid canonical result
per packet. A local-endpoint test also proves analyze's own requests reached the
endpoint and uses at least two curated invariant packets, each unique, warning
free, and containing qualifying target and binding-test snippets. It applies
the same complete/no-problem assertion.

A test-owned local proxy may observe and record exact requests but may not
inject controls, replace response format, retry a packet, or repair content.
Provider-neutral temperature, seed, JSON mode, and token controls are production
request settings under [SEM-3], not proxy patches. Local-endpoint automation on
forked pull requests remains disabled until a separate threat-model review.
This optional live lane is distinct from [SEM-9]'s required cache replay, which
cannot be disabled by an Actions variable.

Classification vocabularies, legacy normalization, evidence spans,
`ok`-to-`weak_binding` behavior, diagnostic projection, dispositions, and
exit precedence are [SC-6], [INV-5], and [SEM-3] through [SEM-7].
`summarize-analysis` validates row identity and shape only; it cannot re-prove
evidence locality without the packet and has no gate authority.

_Implementation mapping_:
- `backstitch/analysis_llm.py`
- `backstitch/analysis_packets.py`
- `backstitch/analysis_results.py`
- `backstitch/artifact_contracts.py`
- `backstitch/cli.py`
- `backstitch/semantic_analysis.py`
- `backstitch/semantic_cache.py`
- `backstitch/semantic_evidence.py`
- `backstitch/semantic_identity.py`
- `backstitch/semantic_packets.py`
- `backstitch/semantic_policy.py`
- `backstitch/semantic_reports.py`
- `tests/conftest.py`
- `tests/live/test_live_llm.py`

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
- semantic failure authority outside [SEM-5] through [SEM-9]
- source-mutating obligation, skip, unskip, proposal, activation, or
  documentation-rewrite commands
- a proposal/case manifest as alignment authority
- model-selected packet membership or evidence-universe membership
- remote MCP transport; the optional [EVC-8.6] adapter, if implemented, is
  local stdio and read-only

`llm` must be imported lazily and only inside the `analyze` and `doctor`
execution paths.
`check`, `packets`, `obligation`, and `guide` must be structurally incapable of
importing it. The boundary is enforced by import placement, not convention,
and [SC-10]/[EVC-12] prove it with subprocess tests.

If durable Weft-backed analysis becomes desirable later, it requires a separate
spec or spec revision because it changes the dependency and execution boundary.

_Implementation mapping_:
- `backstitch/cli.py`
- `backstitch/doctor.py`
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
- `backstitch/defaults.toml`
- `backstitch/diagnostics.py`
- `backstitch/artifact_contracts.py`
- `backstitch/models.py`
- `backstitch/resolver.py`

## 10. Verification Expectations [SC-10]

Verification must use real files and real subprocesses where practical.

Required proof surfaces:

- fixture-backed Markdown parser tests
- Markdown parser tests that prove declarations inside `markdown-it-py`
  `fence` and `code_block` tokens are ignored without a Backstitch-owned fence
  state machine
- Markdown parser tests that pin known parser-boundary divergences from the
  legacy line parser: setext headings, ATX closing hashes, indented code
  blocks, CommonMark fence closers, standalone HTML-comment traceability
  markers, and inline-code normalization for mapping tokens
- fixture-backed Python parser tests
- fixture-backed `tree-sitter` analyzer tests proving owner spans, doc-block
  extraction with exact line numbers, statement spans, comment extraction,
  all-or-nothing error recovery on malformed input, and runtime-version
  independence for PEP 695 generics, PEP 695 `type` aliases, and PEP 701
  f-strings
- resolver tests for clean and broken graphs
- CLI subprocess tests for text, JSON, output file, and exit-code behavior
- a subprocess proof that deterministic commands (`check`, `packets`) never
  import `llm`
- default diagnostic registry validation: every implemented diagnostic code in
  the packaged defaults TOML has a unique short code, valid default level,
  valid status, and at least one firing test; every emitted diagnostic code is
  present in that registry
- diagnostic-policy tests proving all-error, all-info, mixed-level, `off`, and
  `fail_on` behavior through the real CLI and JSON report path
- suppression-hygiene tests proving unused, unknown, malformed,
  unsuppressible, duplicate, broad, deprecated, and redirected suppressions
  produce structured diagnostics with stable codes where implemented
- compatibility tests proving `--warnings-as-errors` and
  `[check].warnings_as_errors` still affect exit behavior but do not rewrite
  diagnostic identity
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
  8. malformed v2 model output emits no result for that packet, records one
     `normalization/malformed_result` problem, continues later packets, and
     exits `2`
  9. concurrent `analyze` output order is byte-identical to serial order
  10. sibling target discovery works from a linked worktree ([SC-12])
  11. key-incomplete report JSON, malformed packet JSONL, and an unwritable
      `--output` path each exit `2` with a one-line error and no traceback
  12. a mapping token with multiple suffix/basename candidates fires
      `TARGET_PATH_AMBIGUOUS` with no edge, and the same token with exactly
      one candidate resolves with `MAPPING_PATH_INEXACT` ([SC-4] ladder)
  13. self-acceptance round-trip: a `check --format json` report of this
      repository passes `summarize-analysis` validation unchanged (paired
      with an empty analysis-results file); generated packet-schema-3 rows and
      packet-report-schema-2 pass current and historical loading; valid
      analyzer result rows and analysis-report-schema-3 pass validation; and a
      controlled malformed response produces the closed failed analysis report
      and problem record from probe 8. Every machine-readable artifact the tool
      writes survives the tool's own reading.
  14. packaged semantic defaults and Backstitch's applied TOML policy produce
      different levels for the same cached finding without a provider call
  15. complete semantic replay exits `0`, an applied verified target finding
      exits `1`, and cache/provider/completeness failure exits `2`
  16. a second required-cache replay makes zero provider calls and emits
      byte-identical canonical result JSONL
- invariant probes cover marker isolation, paired root overrides, every BSI
  firing case, report, packet, and result self-acceptance and legacy
  normalization, `--kind` filtering and mixed-order byte stability, targetless
  spec invariants remaining non-executable, laundering normalization, hash
  stability, and three dogfood invariants
- [EVC-12]'s obligation bootstrap, source-authority, no-mutation, readiness,
  skip, evidence-summary, discovery, snapshot, currentness, verify, and
  qualification probes run through installed public interfaces
- every implemented diagnostic code in the default registry has at least one
  test that proves it fires. Reserved codes may appear in the registry only
  with `status = "reserved"` and must not be accepted as emitted issue codes or
  ordinary suppressions until promoted to `implemented`.
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
- packet-generation tests that prove complete evidence membership, exact byte
  ceilings, and fail-closed overflow without truncated required evidence
- analysis-result tests with valid and malformed JSONL
- semantic-analysis tests using fake model adapters, not external model calls
- live-policy tests proving the repository pytest config enables the real live
  test for an ordinary local invocation without the legacy environment opt-in,
  while the current hermetic CI command explicitly overrides the policy off
  and direct collection reports exactly one skip. This is the legacy bounded
  live-test lane. The semantic gate and refresh lanes use [SEM-9], have no
  repository-variable activation switch, and use least-privilege permissions
- wall-clock benchmark tests carry the registered `benchmark` marker. Normal
  xdist and coverage lanes explicitly select `not benchmark`; a dedicated
  serial lane runs every `benchmark` test without xdist. The serial lane may
  not convert failures into skips. An ordinary serial local pytest run may
  include both normal and benchmark tests
- `ruff` over the CI-listed source/test files, and `mypy` over `backstitch`,
  `bin/release.py`, and tests (excluding fixture target repositories)

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
- `tests/test_code_parser.py`
- `tests/test_python_refs.py`
- `tests/test_resolver.py`
- `tests/test_cli.py`
- `tests/test_backstitch_corpus_traceability.py`
- `tests/conftest.py`
- `tests/live/test_live_llm.py`
- `tests/test_pytest_policy.py`
- `tests/performance/test_evidence_spike_wall_clock.py`
- `tests/test_release_script.py`
- `tests/test_release_workflow.py`

## 11. Diagnostic Codes And Default Policy [SC-11]

Deterministic target-repository diagnostics use stable canonical codes. The
default reporting level is policy, supplied by Backstitch's packaged default
TOML, not by hard-coded Python inventories. The table below records implemented
deterministic diagnostics and allocated BSI defaults; the packaged registry is
the machine-readable source of truth, and registry status controls whether a
row is emittable.

| Code | Short | Default level | Context | Meaning |
|------|-------|---------------|---------|---------|
| `SCAN_ROOT_MISSING` | `BST001` | error | none | Configured spec, plan, or code root not found |
| `FILE_UNREADABLE` | `BST002` | error | none | File could not be read; scan continues |
| `SPEC_FILE_MISSING` | `BSS001` | error | none | Referenced spec file does not exist |
| `SPEC_SECTION_MISSING` | `BSS002` | error | none | File-qualified section reference not found in that file |
| `SPEC_SECTION_AMBIGUOUS` | `BSS003` | error/warning | `asserted`, `weak` | Bare ID matches multiple sections |
| `SPEC_SECTION_DUPLICATE` | `BSS004` | warning | none | Section ID defined more than once |
| `SPEC_ANCHOR_MISSING` | `BSS005` | error | none | File#anchor reference not found |
| `REF_RANGE_UNSUPPORTED` | `BSS006` | error | none | Section range could not be expanded |
| `SPEC_SECTION_UNMAPPED` | `BSS007` | info | none | Spec section has no implementation mapping |
| `SPEC_SECTION_HEADING_INVALID` | `BSS008` | error | none | Reserved ID-bearing Markdown heading is malformed |
| `MAPPING_PATH_MISSING` | `BSM001` | error/warning | `required`, `plan-artifact` | Mapping path missing |
| `MAPPING_PATH_INEXACT` | `BSM002` | warning | none | Mapping token resolved via unique suffix/basename match |
| `TARGET_PATH_AMBIGUOUS` | `BSM003` | error | none | Mapping token matches multiple paths; no edge emitted |
| `MAPPING_SYMBOL_MISSING` | `BSM004` | error | none | Explicit `path::symbol` names a symbol absent from that file |
| `MAPPING_SYMBOL_UNRESOLVED` | `BSM005` | warning | none | Advisory bare symbol in mapping could not be resolved |
| `MAPPING_BLOCK_OWNERLESS` | `BSM006` | warning | none | Mapping block has no preceding ID-bearing heading |
| `PYTHON_SYNTAX_ERROR` | `BSC001` | warning | none | Python file could not be parsed |
| `CODE_REF_BARE_UNRESOLVED` | `BSC002` | warning | none | Known-prefix bare reference matches no section |
| `SPEC_MAPPING_RECIPROCAL_MISSING` | `BSC003` | warning | none | Code backlink without spec mapping |
| `CODE_BACKLINK_RECIPROCAL_MISSING` | `BSC004` | warning | none | Spec mapping without code backlink |
| `CODE_REF_BROAD` | `BSC005` | warning | none | Document-only code reference |
| `CODE_REF_PLANNED_SPEC` | `BSC006` | warning | none | Shipped code cites planned spec |
| `CODE_REF_EXPLORATORY_SPEC` | `BSC007` | warning | none | Shipped code cites exploratory spec |
| `CODE_REF_UNMAPPED_FROM_SPEC` | `BSC008` | info | none | Code cites spec without spec mapping to file |
| `INVARIANT_UNTESTED` | `BSI001` | error/warning | `required`, `draft` | Unique invariant declaration has no valid binding test |
| `INVARIANT_UNKNOWN` | `BSI002` | error | none | Valid test binding names no declaration |
| `INVARIANT_DUPLICATE` | `BSI003` | error | none | Invariant ID is duplicate or collides with a section ID |
| `INVARIANT_BINDING_NOT_TEST` | `BSI004` | warning | none | Well-formed binding marker is outside valid test-definition scope |
| `INVARIANT_MARKER_INVALID` | `BSI005` | error | none | Reserved invariant marker syntax or owner is invalid |

The BSI rows are the normative implemented defaults for [INV-*]. The
deterministic invariant slice promoted each code together with its first
emission and firing test ([SC-15]).

Short codes are stable aliases. They may be accepted in configuration and
suppression syntax, but reports and `config show` canonicalize to the long
code. Short codes are never reused.

For context-dependent diagnostics, `default_severity` records the default level
for that exact emitted context. Repository policy may override the effective
`severity`, but must not erase `context` or `default_severity`.

Severity rationale: errors mean the author asserted something false or unusable
as asserted (a named file, section, anchor, or symbol that does not exist, or
an asserted trace edge that cannot be established), or the tool could not read
what it was told to read. Warnings mean the link is weak or one-directional but
nothing asserted is broken. `SPEC_SECTION_AMBIGUOUS` straddles the line by
context: an ambiguous ID in an asserted backlink or mapping means the claimed
edge cannot be built (error), while the same ID in a comment or prose is a weak
link (warning). In every case, report precisely and never guess an edge.

Every issue record carries at least one non-empty locator (`path`,
`section_id`, or `symbol`), and issues arising from a code reference carry the
citing file and line, so a human or agent can always navigate to the problem.

Invariant-traceability diagnostics follow [INV-8].

An unparseable code file is a coverage warning. It is suppressible by
config/exclusion per-file rules, but not by inline noqa inside that same
unparseable file because the parser did not extract its inline directives.
Strict enforcement on `check` uses the existing `--warnings-as-errors` flag or
`[check].warnings_as_errors` as compatibility shorthands for `fail_on`.

_Implementation mapping_:
- `backstitch/defaults.toml`
- `backstitch/diagnostics.py`
- `backstitch/artifact_contracts.py`
- `backstitch/models.py`
- `backstitch/python_refs.py`
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

## 13. Input Validation Invariants [SC-13]

Every record backstitch accepts across a trust boundary — packet JSONL
read by `analyze`, analysis-result JSONL and deterministic reports read by
`summarize-analysis`, model output, configuration files — is validated
against the rules below. These are stated as rules, not examples: a
validator that checks only the fields its own code path consumes does not
satisfy this section.

- **[SC-13.1] Validation is total over required shape.** An input record
  is validated against the full record contract of its producer — every
  required field present, every type exact, every enumerated vocabulary
  closed (issue codes, severities, classifications, edge kinds, section
  kinds, mapping kinds, reference contexts) — not against the projection
  the consumer happens to read. Unknown top-level packet input extensions are
  tolerated but excluded from the semantic projection only on the bounded
  historical compatibility path. Current packet-schema-3 rows, canonical
  analyzer results, verifier events, packet-report-schema-2,
  analysis-report-schema-3, eval artifacts, and versioned cache objects are
  closed and reject unknown keys. For
  configuration, key and value-type strictness is
  [CFG-8]'s rule; suppression-code vocabularies are validated in the CLI
  and exclusions layer ([EXC-8]).
- **[SC-13.2] Blank means absent.** An empty or whitespace-only string is
  never a valid identifier — packet ID, path locator, section ID, symbol,
  anchor — nor a valid summary or title. Where such a field is required,
  blank is malformed input; where it is optional, the only way to omit it
  is `null`, never `""` or `"   "`. A `rationale` discharges the
  confidence-or-rationale requirement ([SC-7]) only when non-blank;
  free-text fields (messages, raw reference text, snippets, section text)
  are type-checked only.
- **[SC-13.3] Numbers are exact.** `bool` is never accepted where an
  integer is required. Line numbers are 1-based (`line >= 1`, or `null`
  where the contract allows no line). Counts are non-negative integers.
  Confidence is a number in `[0, 1]`.
- **[SC-13.4] Composite documents are self-consistent.** A current packet's
  `packet_id` equals its canonical `obligation_id`; its snapshot, readiness,
  packet hash, report content hash, analysis composition, verifier-event, and
  currentness relations satisfy [EVC-3.1], [EVC-4.1], and [EVC-9.1]. A
  deterministic report's summary counts equal what its own contents
  tally (issue severities; section, ref, mapping, and invariant list lengths).
  A report's edges reference only sections the report itself contains; binds
  reference only invariants in the same report and concrete test definitions.
  Inconsistency is malformed input, not a value judgment left to the consumer.
- **[SC-13.5] Self-acceptance.** Every machine-readable artifact
  backstitch emits — deterministic JSON reports, packet JSONL,
  analysis-result JSONL — passes backstitch's own validation of that
  artifact type. This bounds [SC-13.1]–[SC-13.4] from both sides:
  validators must reject forgeries and must accept everything the tool
  actually produces (probe 13, [SC-10]). Human-facing text output has no
  validating consumer and is out of scope.
- **[SC-13.6] Malformed directives are diagnostics.** A suppression or
  marker directive that does not parse ([EXC-4], [EXC-5]) is an error or
  warning naming the directive — never a silent no-op, and never silent
  deletion of the section or content it is attached to.
- **[SC-13.7] Rejection happens at the input boundary.** Malformed input
  is rejected before adapter construction, cache mutation, provider traffic,
  or output publication where the required facts are available. Output-write
  failures are discovered when the write happens and are exit `2` ([SC-5]);
  they are not required to be pre-checked. Per-packet containment follows
  [SC-7]'s problem-only contract; malformed/provider failures never become
  result rows or verifier events.

Total validation covers invariant, packet, report, analyzer-result, verifier,
and qualification relations. Accept legacy packet/result forms only through
[SC-6]'s bounded historical validation/presentation path; they cannot produce
a current or qualification report. Reject every partial or mixed legacy and
new shape.

Severity of a validation failure is [SC-5] exit `2` for invocation inputs
(packet files, report files, configuration) and a structured analysis problem
for untrusted model rows, consistent with [SC-7].

_Implementation mapping_:
- `backstitch/artifact_contracts.py`
- `backstitch/cli.py`
- `backstitch/semantic_eval_reports.py`
- `backstitch/analysis_results.py`
- `backstitch/analysis_llm.py`
- `backstitch/settings.py`
- `backstitch/exclusions.py`

## 14. Environment Doctor [SC-14]

`backstitch doctor` reports the health of the semantic-analysis
environment as an ordered list of named checks, emitted in exactly the
order they are defined below (output order is part of the contract for
both text and JSON formats). Each check yields `pass`, `fail`, or `skip`
with a one-line detail and, on failure, a one-line remedy naming the
required action. Checks are provider-neutral: they consult only the `llm`
library's public surface and generic HTTP, never provider identities.

Required checks:

- `llm-import`: the `llm` package imports; its installed version is
  reported. Failure to import is a failure; the version itself is
  informational (the declared constraint is open-ended, so API drift is
  guarded by the hermetic dependency-contract test, not by a version
  comparison here).
- `model`: the model resolves via the [CFG-5] precedence (`--model`,
  then `LLM_MODEL`, then config, then the `llm` default — environment
  overrides config), reporting which source won. An unresolvable model
  is a failure naming the attempted name.
- `credential`: when the resolved model declares a key requirement, a
  credential is discoverable the same way `analyze` would find it; a
  keyless model (local `api_base`) passes with that fact in the detail.
- `json-mode`: reports whether the resolved model's options declare
  `json_object` (constrained decoding available to `analyze`). Absence
  is a reported fact, not a failure.
- `memory` (informational, never a failure): best-effort detected
  physical memory plus a pointer to the local-model catalog in the
  implementation docs.
- `endpoint` (only with `--probe`; skipped without it and skipped for
  models with no `api_base`): the model's `api_base` answers an
  unauthenticated `GET <api_base>/models` within a bounded timeout. A
  connection failure, timeout, or HTTP status other than `200`, `401`,
  or `403` is a failure. On `200`, the served model name — the model's
  `model_name` attribute when present, otherwise its `model_id` (the
  identifier `llm`'s OpenAI wrapper actually sends to the server; an
  `api_base` registration resolves an alias while the server lists the
  served upstream name) — must appear in the returned OpenAI-style
  `data[].id` list, else the check fails with the ids seen. On `401` or
  `403` the endpoint counts as reachable and the check passes with a
  detail stating that the model list is authentication-gated and
  membership was not verified. No credential is ever sent; no generation
  is performed.

Allowed statuses per check (an implementation must not emit others):
`llm-import` — `pass`/`fail`; `model` — `pass`/`fail`, `skip` when
`llm-import` failed; `credential` — `pass`/`fail`, `skip` when the model
is unresolved; `json-mode` — `pass` (the detail states whether
constrained decoding is available), `skip` when the model is unresolved;
`memory` — `pass` only (undetectable memory is a `pass` with an
"unknown" detail); `endpoint` — `pass`/`fail`, `skip` without `--probe`,
when the model is unresolved, or when the model has no `api_base`.

`--format json` emits `{"checks": [{"name": ..., "status":
"pass"|"fail"|"skip", "detail": ..., "remedy": ...}], "ok": <bool>}`;
`remedy` is empty for non-failures. `ok` is `true` and the exit code is
`0` if and only if no check has status `fail`; otherwise the exit code is
`2` — never `1` ([SC-5]). Skipped checks never affect the exit code.
Doctor performs no model generation and no network I/O without
`--probe`, mutates no backstitch state and writes nothing itself
(consulting `llm` may create `llm`'s own user directory — that is
`llm.user_dir()` behavior doctor inherits, not a doctor write), and
must not import `llm` at module import time ([SC-8]).

_Implementation mapping_:
- `backstitch/doctor.py`
- `backstitch/cli.py`
- `tests/test_doctor.py`

## 15. Diagnostic Registry And Policy [SC-15]

Backstitch ships a packaged default TOML file that is always loaded as the
lowest-precedence configuration layer. The default TOML owns:

- built-in profile defaults formerly held only in Python
- default scan excludes
- diagnostic registry entries
- default diagnostic policy (`default_level`, ordered level rules, `fail_on`,
  and suppressible levels)

Repository config and explicit `--config` files layer on top of packaged
defaults. `--no-config` skips repository discovery but still loads packaged
defaults.

Diagnostic registry entries have:

- canonical long code
- unique short code
- status: `implemented`, `reserved`, `deprecated`, or `redirected`
- default summary
- optional replacement code for redirected/deprecated entries
- optional allowed contexts

Only `implemented` diagnostics may be emitted by the current version. Reserved
diagnostics document the allocation list but are not valid emitted issue codes
or ordinary suppressions until promoted. Deprecated and redirected codes are
accepted as aliases only when the registry names their replacement; using them
produces a suppression-hygiene diagnostic unless the relevant hygiene code is
disabled by policy.

Diagnostic policy is an ordered rule list. Each rule names selectors and a
target level (`error`, `warning`, `info`, or `off`). Later configuration layers
are applied after earlier layers; later matching rules win. Selectors support
canonical long codes, short codes, `*`, code-family prefixes ending in `*`, and
context selectors of the form `CODE:context` or `SHORT:context`. This lets a
repository append one rule selecting `*` to make all target diagnostics errors
or infos.

`off` is a reporting policy result, not a report severity and not silent
deletion. Off-level diagnostics are omitted from `issues`, excluded from
summary counts, and must be recoverable through the suppression audit view with
reason `diagnostic level off`. `off` is invalid in `fail_on` and
`suppressible_levels`.

The initial suppression-hygiene and reserved diagnostic allocation is:

| Code | Short | Status | Intended surface |
|------|-------|--------|------------------|
| `CONFIG_TOML_INVALID` | `BST003` | reserved | Config loading |
| `CONFIG_FILE_MISSING` | `BST004` | reserved | Config loading |
| `CONFIG_EXTEND_MISSING` | `BST005` | reserved | Config loading |
| `CONFIG_EXTEND_CYCLE` | `BST006` | reserved | Config loading |
| `CONFIG_UNKNOWN_KEY` | `BST007` | reserved | Config validation |
| `CONFIG_TYPE_INVALID` | `BST008` | reserved | Config validation |
| `CONFIG_VALUE_INVALID` | `BST009` | reserved | Config validation |
| `CONFIG_PROFILE_UNKNOWN` | `BST010` | reserved | Config validation |
| `REPORT_JSON_INVALID` | `BST011` | reserved | Artifact loading |
| `REPORT_SHAPE_INVALID` | `BST012` | reserved | Artifact loading |
| `REPORT_SUMMARY_MISMATCH` | `BST013` | reserved | Artifact loading |
| `OUTPUT_WRITE_FAILED` | `BST014` | reserved | Invocation failure |
| `REPO_ROOT_INVALID` | `BST015` | reserved | Invocation failure |
| `INTERNAL_ERROR` | `BST016` | reserved | Tool failure |
| `SUPPRESSION_UNUSED` | `BSX001` | implemented | Suppression hygiene |
| `SUPPRESSION_WITHOUT_CODE` | `BSX002` | reserved | Suppression hygiene |
| `SUPPRESSION_UNKNOWN_CODE` | `BSX003` | implemented | Suppression hygiene |
| `SUPPRESSION_INVALID_SYNTAX` | `BSX004` | implemented | Suppression hygiene |
| `SUPPRESSION_UNSUPPRESSIBLE_CODE` | `BSX005` | implemented | Suppression hygiene |
| `SUPPRESSION_REDIRECTED_CODE` | `BSX006` | reserved | Suppression hygiene |
| `SUPPRESSION_DEPRECATED_CODE` | `BSX007` | reserved | Suppression hygiene |
| `SUPPRESSION_DUPLICATE_CODE` | `BSX008` | reserved | Suppression hygiene |
| `SUPPRESSION_BROAD_CODE` | `BSX009` | reserved | Suppression hygiene |
| `SUPPRESSION_REASON_MISSING` | `BSX010` | implemented | Suppression hygiene |
| `INVARIANT_UNTESTED` | `BSI001` | implemented | Invariant resolution (`required`, `draft` contexts) |
| `INVARIANT_UNKNOWN` | `BSI002` | implemented | Invariant resolution |
| `INVARIANT_DUPLICATE` | `BSI003` | implemented | Invariant resolution |
| `INVARIANT_BINDING_NOT_TEST` | `BSI004` | implemented | Invariant parsing and resolution |
| `INVARIANT_MARKER_INVALID` | `BSI005` | implemented | Invariant parsing |
| `PACKET_JSON_INVALID` | `BSP001` | reserved | Packet loading |
| `PACKET_SHAPE_INVALID` | `BSP002` | reserved | Packet loading |
| `PACKET_SECTION_TRUNCATED` | `BSP003` | reserved | Packet generation |
| `PACKET_OWNER_TRUNCATED` | `BSP004` | reserved | Packet generation |
| `PACKET_OWNER_OMITTED` | `BSP005` | reserved | Packet generation |
| `PACKET_OWNER_NOT_FILE` | `BSP006` | reserved | Packet generation |
| `PACKET_OWNER_UNREADABLE` | `BSP007` | reserved | Packet generation |
| `PACKET_SYMBOL_NOT_FOUND` | `BSP008` | reserved | Packet generation |
| `ANALYSIS_ROW_INVALID` | `BSP009` | reserved | Analysis loading |
| `ANALYSIS_PACKET_UNKNOWN` | `BSP010` | reserved | Analysis loading |
| `MODEL_OUTPUT_INVALID` | `BSP011` | reserved | Analysis model boundary |
| `MODEL_PACKET_ID_MISMATCH` | `BSP012` | reserved | Analysis model boundary |
| `MODEL_CALL_FAILED` | `BSP013` | reserved | Analysis model boundary |
| `SEMANTIC_CONFIRMED_MISMATCH` | `BSA001` | implemented | Semantic projection (all [SEM-5]/[EVC-6] contexts) |
| `SEMANTIC_PROBABLE_MISMATCH` | `BSA002` | implemented | Semantic projection (all [SEM-5]/[EVC-6] contexts) |
| `SEMANTIC_MISSING_TRACE` | `BSA003` | implemented | Syntactically complete but substantively missing behavioral trace |
| `SEMANTIC_WEAK_BINDING` | `BSA004` | implemented | Semantic projection (all [SEM-5]/[EVC-6] contexts) |
| `SEMANTIC_AMBIGUOUS` | `BSA005` | implemented | Semantic projection (all [SEM-5]/[EVC-6] contexts) |
| `OBLIGATION_SKIPPED` | `BSE001` | implemented | Auditable valid obligation skip ([EVC-6]) |

The BSI allocations remained reserved through contract alignment, then all
five became `implemented` together with their first emissions and firing
tests. Packaged default policy sets BSI001 required to error and draft to
warning, BSI004 to warning, and BSI002, BSI003, and BSI005 to error.

The five BSA allocations became implemented with their production projection
and firing tests. Their allowed contexts are exactly `evidence_bound`,
`verification_indeterminate`, `independently_verified`,
`mechanically_verified`, `human_verified`, `disputed_by_verifier`, and
`human_rejected`. They never enter deterministic `Issue` inventories or
ordinary source suppressions; semantic diagnostics reuse the registry's
selector and level resolver through their separate [SEM-6] record family.

`BSE001` is the only aligned-evidence diagnostic allocation. It remains
reserved until the skip parser, emitter, and firing test land atomically;
operation problems use [EVC-8.4]'s non-suppressible problem vocabulary and do
not allocate case-lifecycle diagnostics. Ordinary trace and invariant
diagnostics remain authoritative for graph defects. `BSX010` likewise remains
reserved until its first skip-reason emission and firing test.

_Implementation mapping_:
- `backstitch/defaults.toml`
- `backstitch/diagnostics.py`
- `backstitch/models.py`
- `backstitch/settings.py`
- `backstitch/check_pipeline.py`

## 16. Product Identity And Lanes [SC-16]

This section states the identity every other section applies. When a proposed
feature or spec revision is debated, it is tested against this section first.

**Boundary rule.** Backstitch observes, classifies, and gates. It never
authors content, never repairs the repository, never guesses an edge, and
never lets a model roam. Backstitch is a reader of repositories; the one
narrow exception any future write feature must satisfy is that it may
transcribe what the resolver already deterministically proved, and nothing
else.

**Evidence-class rule.** No claim ever exceeds its evidence class. Every
finding carries what kind of knowledge it is — asserted versus weak in the
deterministic lane ([SC-11] severity rationale); `evidence_bound` through
`human_verified` in the semantic lane ([SEM-5], [EVC-6]) — and policy may
promote a finding's consequence, never its evidence class.

**The promise.** Backstitch does not promise that models prove correctness.
It promises that semantic review becomes repeatable enough to run in CI,
diffable enough to audit, and structured enough to improve. The workflow is
deterministic even where one lane uses probabilistic judgment, because the
judgment is surrounded by deterministic contract — what evidence the model
may see, which contract it judges, which prompt/model/config produced the
verdict, what shape must come back, how uncertainty is represented, how
severities map to exit codes, and how suppressions and dispositions are
audited — and because the judgment itself happens exactly once per cache
identity and is then a content-addressed, replayable fact
([SEM-3], [SEM-4]). Backstitch converts probabilistic judgment into
deterministic evidence.

**Two lanes and one authority.**

- **Trace lane** — deterministic facts about declared relationships:
  sections, mappings, backlinks, invariant bindings, coverage, and drift
  ([SC-4], [INV-*], [COV-*]). Hard-gate by default.
- **Semantic lane** — bounded model judgment over source-derived packets;
  `analyze` and blinded adversarial `verify` are stages within this one lane
  ([SC-7], [SEM-*], [EVC-*]). Independence is procedural, not a requirement
  for distinct models, providers, or statistically independent errors.
  Advisory by default.
- **Policy layer** — not a lane; the projection both lanes' findings flow
  through ([SC-15], [SEM-6]). It is the repository's authority mapping:
  which findings, at which evidence class, become blocking. The decision to
  block is always a reviewable configuration diff, never a model output.

**Metric identity rule.** Trendable signals (coverage counts, ambiguous
sections, drift suspects, regressions since base, flip rate, promotion
readiness) are computed only from committed artifacts, such as reports,
caches, and derived packet receipts, so every trend is replayable. Signal definitions carry the
same stable-identity discipline as diagnostics: a metric's definition is
versioned, a changed definition is a new metric version with the old one
deprecated, and no metric is ever silently redefined. Aggregated semantic
results are rendered as counts by classification and evidence class, never
as a blended correctness percentage. Semantic qualification reports exact
counts, rates, confidence bounds, and pass checks bound to one committed corpus
and exact composed inference identities; Backstitch emits no blended
correctness percentage or calibrated model score.

**Contract coverage.** The measurement surface asks five questions, four
deterministic and one semantic:

| Axis | Question | Lane | Governed by |
|---|---|---|---|
| Spec coverage | which promised behaviors have mapped implementation? | trace | [COV-3], [COV-6] |
| Test evidence coverage | which promised behaviors have binding tests or probes? | trace | [INV-*], [SC-10] |
| Orphan code | which definitions have no declared purpose? | trace | [COV-3], [COV-7] |
| Drift coverage | which changed code touches contract-bearing areas without corresponding spec/test movement? | trace | [COV-8] |
| Semantic agreement | which promises did bounded review judge implemented, contradicted, under-tested, or ambiguous? | semantic | [SEM-6], [EVC-6] |

The lane split, defaults, and policy authority stated here are current
contract. The semantic-lane internals and the coverage/drift axes are
governed by their own specs, whose Status lines control what is implemented
versus proposed; this section states identity, which does not change with
implementation status.

_Implementation mapping_:
- `backstitch/cli.py`

## Related Plans

- `docs/plans/2026-07-11-deterministic-semantic-gate-plan.md`
  (implementing)
- `docs/plans/2026-07-15-agent-guided-evidence-cases-plan.md`
  (implementing)
- `docs/plans/2026-07-27-canonical-config-resolution-plan.md`
  (implementation and verification recorded)
- `docs/plans/2026-07-10-local-default-live-llm-tests-plan.md`
  (implemented)
- `docs/plans/2026-07-09-backstitch-invariant-traceability-plan.md`
  (implemented)
- `docs/plans/2026-07-08-configurable-diagnostics-plan.md` (implementing)
- `docs/plans/2026-07-07-tree-sitter-code-parser-plan.md` (implementing)
- `docs/plans/2026-07-06-local-model-catalog-and-doctor-plan.md` (implementing)
- `docs/plans/2026-07-06-backstitch-organization-refactor-plan.md` (implementing)
- `docs/plans/2026-07-03-local-llm-eval-lane-plan.md` (implementing)
- `docs/plans/2026-07-10-local-llm-release-gate-stabilization-plan.md`
  (implementing)
- `docs/plans/2026-07-03-live-llm-tests-plan.md` (implementing)
- `docs/plans/2026-07-03-input-validation-invariants-plan.md` (implementing)
- `docs/plans/2026-07-27-serial-benchmark-lane-plan.md` (implementing)
- `docs/plans/2026-07-02-backstitch-four-way-reconciliation-plan.md` (implementing)
- `docs/plans/2026-06-18-backstitch-style-spec-code-traceability-tool-plan.md` (superseded)
- `docs/plans/2026-07-01-backstitch-toml-configuration-plan.md` (archival)
- `docs/plans/2026-07-02-backstitch-traceability-exclusions-plan.md` (archival)
