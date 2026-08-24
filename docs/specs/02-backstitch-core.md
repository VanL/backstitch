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
committed configuration must make the advertised hermetic self-check,
`backstitch check --repo-root .`, clean ([SC-10]). A self-check that fails on
the tool's own repository is a shipped defect, not an accepted quirk.

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
- `tests/test_traceability_reducer.py`

## 5. CLI Contract [SC-5]

`backstitch` must expose a console script named `backstitch`.

A repository may configure one bare-invocation default through [CFG-6]
`default_command`. After argparse handles `--help` and `--version`, an
invocation with no explicit subcommand resolves configuration exactly once
with the current working directory as its discovery anchor. Effective
`"check"` dispatches the existing `check` command with that directory as
`--repo-root`; effective `"analyze"` dispatches current-repository `analyze`
with that directory as `--repo-root`. Effective `false` is the packaged
default and returns exit `2` with a line-safe missing-command error.

An explicit subcommand always wins selection and never redirects through
`default_command`; ordinary strict config validation still rejects an invalid
known `default_command` value. Bare dispatch delegates stdout, stderr, exit
codes, configuration, snapshot,
cache, budget, and provider behavior to the selected existing handler.
In particular, current-repository `analyze` retains its deterministic
preflight and performs no provider work when effective deterministic policy
fails.

`default_command` is a closed command name, not command-line syntax. V1
accepts only `"check"` and `"analyze"`; the configuration value itself accepts
no arguments, separators, external executables, multiple steps, or recursive
dispatch. Arguments supplied in the invocation are parsed against the selected
existing command. A leading path is shorthand for that command's
`--repo-root`; otherwise current-repository input is implicit unless the
invocation already supplies `--repo-root` or analyze `--packets`. Thus
`backstitch .` delegates to the selected command over `.`, and bare analyze
accepts ordinary arguments such as `--model`. An argument invalid for the
selected default remains a CLI usage error. Other commands require an explicit
invocation.

For local use, invoking bare `backstitch` explicitly delegates command
selection and the selected command's documented side effects to the effective
repository configuration. A configured check output may write its report;
configured analyze may read credentials, write cache state, make bounded
provider calls, and incur bounded cost under its existing contract. Bare
dispatch is forbidden in secret-bearing hostile-target automation: those
workflows continue to name the semantic command, select trusted tool
configuration explicitly, and use only workflow-owned static overrides under
[SEM-9] and [EVC-11].
The CLI does not infer whether an invocation is local or automated; the
hostile-target prohibition is a workflow contract enforced by trusted
workflow source and its firing tests.

Required deterministic command:

```bash
backstitch check --repo-root . --profile backstitch-style-v1 --format text
backstitch check --repo-root . --profile backstitch-style-v1 --format json --output spec-trace.json
backstitch coverage [PATH] [--repo-root PATH] [--format text|json] [--output PATH] [--profile NAME] [--config PATH|--no-config] [--option KEY VALUE]... [--require-ratchet REF]
```

`coverage` is the deterministic [COV-*] command. Positional `PATH` and
`--repo-root` are mutually exclusive aliases; absent either, the current
working directory is the root anchor. Report mode accepts the common
configuration controls. Ratchet mode rejects explicit config/profile/option
selection and accepts only repository discovery plus format/output, the root
alias, and the exact `--require-ratchet REF` assertion defined by [COV-9].
The command returns `0` when no issue meets `fail_on`, `1` for selected target
findings, and `2` for invocation, configuration, Git, budget, validation, or
publication failure. It never changes `check` behavior or report bytes.

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
backstitch analyze --repo-root . --preflight --format text
backstitch analyze --repo-root . --preflight --format json
backstitch analyze --repo-root . --output analysis.jsonl --report analysis-report.json
backstitch analyze --packets packets.jsonl --packet-report packet-report.json --output analysis.jsonl --report analysis-report.json
backstitch eval --corpus tests/semantic_eval/v3/manifest.json --output semantic-eval-report.json
backstitch cache cleanup-lock --cache-path PATH (--analysis-key HASH | --review-key HASH | --verify-key HASH) --lock-stale-seconds SECONDS --reason TEXT
```

The exact option grammar, selector exclusivity, pagination, source-snapshot
rules, and current-versus-historical analyze modes are [EVC-5.1] and [EVC-8.3].
Current analysis derives packet schema 3 from `--repo-root`; packet input is a
historical replay. `backstitch mcp` is registered only if the optional Phase D
adapter ships and then follows [EVC-8.6]. CLI is the complete required
interface. No obligation, guide, packet, or implemented MCP operation writes
repository source.

`analyze --preflight` accepts the ordinary current-repository input,
configuration, model-selection, and `--format text|json` grammar. It requires
current `--repo-root` input and rejects historical `--packets` or
`--packet-report` input and every semantic packet, result, or report output
path. Preflight executes the same provider-free preparation later consumed by
ordinary current analysis. It performs no model invocation, credential read,
network access, semantic-cache read or mutation, output temporary creation, or
artifact publication. Provider-local model construction is allowed only when
the selected adapter must be constructed to validate the exact request; that
construction performs none of the forbidden effects.

Preflight exits `0` when the prepared analysis is executable or has a valid
all-skipped state. An effective deterministic target finding selected by
`fail_on` exits `1`. Repository readiness, packet, prompt,
request-capability, cost, output-overlap, or other preparation blockers exit
`2`. Invalid CLI syntax or malformed configuration is also exit `2`, but
remains an invocation error rather than a preparation report.

JSON preflight writes exactly one closed schema-2 object to stdout for both
ready and provider-free blocked outcomes, with empty stderr. Schema 2
supersedes the ephemeral schema-1 output shape; Backstitch has no persisted
preflight artifact or compatibility loader, and consumers must reject rather
than reinterpret an unknown schema:

```text
{
  "schema_version": 2,
  "operation": "analysis.preflight",
  "ready": boolean,
  "selected_command": "analyze",
  "config": {"selected_path": string|null, "settings_sha256": "sha256:..."},
  "snapshot": {"snapshot_hash": "sha256:...", "file_count": integer,
               "byte_count": integer}|null,
  "readiness": {
    "total": integer, "executable": integer, "blocked": integer,
    "reason_groups": [
      {"code": string, "count": integer,
       "example_obligation_ids": [string]}
    ],
    "next_command": string
  }|null,
  "packet_plan":
    {
      "status": "complete", "complete": true,
      "packet_count": integer, "packet_bytes": integer,
      "aggregate_prompt_bytes": integer,
      "maximum_request_bytes": integer
    }
    | {
      "status": "over_budget", "complete": false,
      "crossed_ceiling": string,
      "measured_packet_count": integer,
      "unmeasured_packet_count": integer,
      "measured_packet_bytes": integer,
      "measured_prompt_bytes": integer,
      "first_crossing_packet_id": string,
      "top_measured_contributors": [{
        "packet_id": string, "kind": string,
        "packet_byte_count": integer, "request_byte_count": integer
      }]
    }
    | null,
  "inference": {
    "analyzer": {
      "stable_model_id": string,
      "adapter_model_id": string,
      "capability_revision": string,
      "effective_request": object,
      "request_identity": object
    },
    "verifier": {
      "stable_model_id": string,
      "adapter_model_id": string,
      "capability_revision": string,
      "effective_request": object,
      "request_identity": object
    }|null
  }|null,
  "budgets": {
    "projection": "conservative_cold",
    "limits": {
      "maximum_packets": integer|null,
      "maximum_prompt_bytes": integer|null,
      "maximum_input_bytes": integer|null,
      "maximum_provider_calls": integer,
      "maximum_estimated_cost_microusd": integer|null,
      "maximum_runtime_seconds": integer
    },
    "analyzer": {
      "provider_calls": integer|null,
      "estimated_cost_microusd": integer|null,
      "provider_call_status":
        "within_limit"|"requires_cache_hits"|"exceeds"|"unavailable",
      "estimated_cost_status":
        "within_limit"|"requires_cache_hits"|"exceeds"|"disabled"|"unavailable",
      "cost_rate_source": string|null
    },
    "verifier": {
      "status": "disabled"|"deferred_until_analyzer_results",
      "maximum_input_bytes": integer|null,
      "maximum_prompt_bytes": integer|null,
      "maximum_provider_calls": integer|null,
      "maximum_estimated_cost_microusd": integer|null,
      "maximum_runtime_seconds": integer|null
    },
    "call_cost_status":
      "within_limits"|"requires_cache_hits"|"exceeds"|"unknown"|"unavailable"
  },
  "outputs": {"current_artifacts_would_publish": boolean},
  "problems": [
    {"stage": string, "code": string, "details": object,
     "action": string}
  ]
}
```

The two `packet_plan` variants are the closed preflight projection of
[EVC-9.1]'s complete and overflow `PacketPlan`: they omit retained byte
payloads but rename no status, count, byte, crossing, or contributor field.
`maximum_request_bytes` is the largest complete `model_request_bytes` length,
not the largest code-owned instruction block. Nested inference,
request-identity, and problem values use their closed [SEM-*]/[EVC-*]
contracts; `object` above does not grant open extension.
Fields remain present with `null`, zero, or empty values when their phase is
not authoritative. A blocked phase never fabricates later facts.
`effective_request` contains no credential or secret. Each reason group
contains at most three example obligation IDs in canonical obligation order.

`budgets` is a presentation projection over the authoritative retained
`PacketPlan`, resolved inference, and configured limits. It never owns or
rebuilds packet or model-request bytes. Zero disables `maximum_packets`,
`maximum_prompt_bytes`, and `maximum_estimated_cost_microusd`; their rendered
limits are then null. The trusted capability always supplies
`maximum_input_bytes` when inference is resolved. A complete plan projects one
analyzer call per packet for `read-write` and `off`; `require` projects zero
provider calls because that mode forbids them. The conservative cold analyzer
cost applies [SEM-7]'s existing per-request ceiling formula to every projected
call and uses the exact retained model-request byte length. It is null with
`estimated_cost_status = "disabled"` when the configured cost ceiling is zero.

For `read-write`, a cold projection over a configured call or cost ceiling is
`requires_cache_hits`, not a provider-free blocker: ordinary analysis still
performs the authoritative cache-aware planned-miss gate after its first
currentness recapture. For `off`, the same exceedance is exact and blocks
preflight with exit 2. For `require`, call and cost projections are zero but
`call_cost_status = "requires_cache_hits"` because preflight does not inspect
cache availability. When verification is enabled, verifier work and request
bytes depend on analyzer findings; preflight reports
`deferred_until_analyzer_results` and `call_cost_status = "unknown"` unless an
already-authoritative analyzer exceedance takes precedence. It never
fabricates verifier calls, request bytes, or cost. It does report the resolved
verifier input, aggregate prompt, call, cost, and runtime ceilings so the
deferred boundary is visible. An incomplete or absent packet plan leaves analyzer
projections null and unavailable. An exact packet-plan budget crossing remains
authoritative in `packet_plan`, while the later call/cost projection and its
combined status remain unavailable.

The conservative cost validator and arithmetic have one lower-layer owner
shared by preflight and execution. A positive cost ceiling with no reviewed
backend/plugin framing contract, insufficient input overhead, or missing
authoritative rate source is a structured provider-free preflight blocker.
Preflight does not read analyzer or verifier cache state. An exact warm-cache
preview would be a different cache-reading/currentness contract and is not
part of this command.

Text preflight writes a concise status to stdout. A ready result includes the
packet count plus the analyzer projected/maximum call and, when enabled,
projected/maximum cost values with their cold or cache-dependent status. A
blocker may occupy
multiple bounded lines: one summary, canonical reason groups with no more than
three obligation IDs each, and one exact next command. Invalid CLI syntax or
malformed configuration instead writes the ordinary one-line
`backstitch: error: ...` message to stderr with empty stdout. Ordinary current
`analyze --format json` uses the same structured preparation-failure object on
stdout, with empty stderr, when preparation blocks before provider work.
Ordinary text analyze renders the same bounded facts on stderr.

Candidate discovery and packet materialization may publish progress only
through an optional event sink. Its phase vocabulary is closed and ordered:
`snapshot`, `catalog`, `relations`, `closure`, `candidate_detail`,
`packet_materialization`, `packet_accounting`, `complete`. Each event contains
the phase, completed work units, optional
total work units, and a line-safe current identity. The CLI may attach a
TTY-only stderr renderer; otherwise it uses a no-op sink. Progress never
appears on stdout, non-TTY stderr, JSON, reports, artifacts, cache identities,
or hashes. JSON preflight keeps stderr empty even when stderr is a TTY.
Renderer failure disables progress and does not change the domain result,
public bytes, or exit code.

`cache cleanup-lock` requires exactly one key flag. `--analysis-key` addresses
the analyzer lock/guard/audit contract; `--review-key` addresses the disjoint
evidence-stable baseline-election contract; `--verify-key` addresses the
disjoint verifier contract in [SEM-4]. All require the explicit stale interval
because the cleanup command performs no configuration discovery.

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
dispositions, never asserts verification state, and never exits `1`. Its
known packet identities are the deterministic report's edge-bearing sections,
bound invariants, and valid unique suppression declarations in
`suppressed_issues`. Summarizing suppression results therefore requires the
audited deterministic report produced with `--show-suppressions`; a report
that omits that audit cannot validate a suppression result identity.

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
- `backstitch/check_application.py`
- `backstitch/check_pipeline.py`
- `backstitch/coverage_application.py`
- `backstitch/doctor.py`
- `backstitch/obligation_api.py`
- `backstitch/operation_progress.py`
- `backstitch/packet_application.py`
- `backstitch/profiles.py`
- `backstitch/reporting.py`
- `backstitch/resolver.py`
- `backstitch/semantic_analysis.py`
- `backstitch/semantic_application.py`
- `backstitch/semantic_budget.py`
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

`coverage --format json` emits the separate closed
`backstitch-intent-coverage-report` schema 1 artifact in [COV-3]. It reuses the
accepted immutable snapshot and raw trace graph but does not extend, replace,
or conditionally alter this section's deterministic check-report schema.

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
Provider-neutral temperature, seed, reasoning effort, JSON mode, and token
controls are production request settings under [SEM-3], not proxy patches. Local-endpoint automation on
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
- `backstitch/packet_application.py`
- `backstitch/semantic_analysis.py`
- `backstitch/semantic_application.py`
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
`check`, `coverage`, `packets`, `obligation`, and `guide` must be structurally
incapable of importing it. The boundary is enforced by import placement, not
convention, and [SC-10]/[EVC-12] prove it with subprocess tests.

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

<!-- backstitch: meta because docs/specs/04-backstitch-traceability-exclusions.md#SUP-VERIFICATION-META -->

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
- black-box bare-invocation tests proving configured `check` and `analyze`
  use the current repository, preserve their explicit-command exit/output
  contracts, and dispatch through one configuration resolution
- a no-default probe proving bare invocation exits `2` without importing
  `llm`, scanning source, touching cache state, or reaching a provider
- help/version and explicit-command probes proving they do not execute or
  redirect through the configured default
- one firing test for each `default_command` value, the disabling `false`
  value, every invalid type/value family, and `extend` override/disable
  behavior
- configured Ruff policy tests proving the exact manifest/lock/runtime pin,
  the reviewed lint discovery surface including intended extensionless Python
  entry points, configured `C901` at 10, active-rule raw inventory, and the
  checked [SC-17.1] suppression registry through the same canonical lint
  vector used by CI and release prechecks
- explicit-versus-bare environment tests proving `LLM_MODEL` applies to bare
  analyze but remains irrelevant to bare check, with one file/config
  resolution and one immutable settings snapshot
- a subprocess proof that deterministic commands (`check`, `packets`) never
  import `llm`
- default diagnostic registry validation: every implemented diagnostic code in
  the packaged defaults TOML has a unique short code, valid default level,
  valid status, and at least one firing test; every emitted diagnostic code is
  present in that registry
- diagnostic-policy tests proving all-error, all-info, mixed-level, `off`, and
  `fail_on` behavior through the real CLI and JSON report path
- an enumerated runtime-import graph test proving [SC-17]'s DAG and ranked
  dependency direction without hiding function-local imports
- configured C901 verification over the same production paths as CI
- registry consistency tests named and documented as consistency tests, plus
  separate firing fixtures that reach each diagnostic through its real
  producer; constructing the producer's output type is not firing proof
- application-interface tests proving CLI adapters preserve public bytes and
  exits while deterministic commands remain provider-free
- a table-driven transition matrix for Backstitch's traceability reducer over
  `markdown-it-py` tokens; `markdown-it-py` remains the sole Markdown syntax
  parser
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
  17. coverage hostile-input probes prove marker-like strings in comments,
      literals, examples, wrong syntax-tree locations, and near-miss spellings
      do not become exemptions; exact malformed markers produce BSN004
  18. coverage config/Git probes prove unknown keys and missing ratchet bases
      exit `2`, untracked Python definitions participate in patch coverage,
      and two serial runs over one accepted state produce byte-identical output
- invariant probes cover marker isolation, paired root overrides, every BSI
  firing case, report, packet, and result self-acceptance and legacy
  normalization, `--kind` filtering and mixed-order byte stability, targetless
  spec invariants remaining non-executable, laundering normalization, hash
  stability, and three dogfood invariants
- [EVC-12]'s obligation bootstrap, source-authority, no-mutation, readiness,
  skip, evidence-summary, discovery, snapshot, currentness, verify, and
  qualification probes run through installed public interfaces
- a normal-suite hermetic dogfood journey runs from installed CLI entry points
  and one real settings snapshot. It exercises `check`, filtered obligation
  views, preflight, packets, current analyze through a deterministic
  test-owned local `llm` model, result/report loading, summarize, eval,
  historical replay, exact cache replay, cache miss, cleanup-lock, currentness
  races, and atomic publication. A second identical analyze produces
  byte-identical artifacts and zero local-model calls. Only remote model
  computation and isolated clock/barrier seams may be replaced; settings,
  snapshot, readiness, packet planning, application, adapter, cache, and
  artifact-loading owners stay real
- a second hermetic dogfood journey introduces controlled readiness debt in an
  isolated self-corpus copy while deterministic `check` stays clean. Bare
  analyze, explicit analyze, and preflight must report the same preparation
  identity, debt count, canonical reason groups, bounded IDs, exact recovery
  command, and zero model calls
- every release candidate runs protected live qualification for the complete
  committed GPT-5.6 Luna default descriptor and the protected GPT-5.5
  override through their production stable/raw selections. A change to a
  selected model, model revision, effective request, capability descriptor,
  adapter, provider dependency, or qualification logic requires the same
  bounded qualification before the changed contract is treated as release-
  ready. One qualification event makes at most two generation calls total and
  at most one per descriptor, with a hard $0.10 USD estimated-cost ceiling.
  The provider client disables automatic transport retries for these requests,
  so the limit bounds wire attempts rather than only logical adapter calls.
  Each accepted call is immediately replayed from immutable cache with zero
  provider calls. Provider unavailability is reported as `unavailable`, not
  `incompatible`. Exact-request serialization/rejection or a provider-accepted
  response that fails Backstitch's closed normalizer is `incompatible`;
  missing/rejected credentials, absent authorization, rate limiting,
  transport failure, timeout, and provider 5xx are `unavailable`. Both block
  release, as do local qualification setup and preflight errors. Neither
  outcome edits a descriptor. Elapsed time and repository inactivity do not
  invalidate a prior semantic evaluation and do not create a process
  violation. Qualification is execution evidence for the current release
  event; Backstitch does not define or persist a dated capability-receipt
  artifact
- one hermetic test using the real installed `llm` Responses adapter and a
  test-owned HTTP transport proves the Luna request wire shape, exactly one
  call, the independent closed response normalizer, and exactly one wire
  attempt when the transport returns a retryable provider error
- qualification tests fire for compatible, incompatible, and unavailable
  outcomes, the two-call and $0.10 ceilings, zero-call replay, and the release
  precheck's unconditional invocation; selected descriptor/request fixtures
  prove that a changed current contract is the contract exercised, and no
  wall-clock-age case exists
- every implemented diagnostic code in the default registry has at least one
  test that proves it fires. Reserved codes may appear in the registry only
  with `status = "reserved"` and must not be accepted as emitted issue codes or
  ordinary suppressions until promoted to `implemented`.
- self-corpus smoke check against this repository's specs, plans, docs, and
  `backstitch`, using the repository's committed configuration and the
  explicit `backstitch check --repo-root .` invocation. Success criteria: exit `0`, zero
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
  serial lane runs every `benchmark` test without xdist. Each command receives
  one unmeasured warm-up and five measured runs. The result reports every
  sample and the median. A latency qualification is available only when the
  current runtime exactly matches the wall-clock runner contract, which uses
  the closed [EVC-10] identity schema, and a content-bound baseline exists; the
  median must not exceed 120% of that baseline. A missing baseline, a baseline
  bound to another contract, or a missing, invalid, unobserved, or mismatched
  runner identity reports `unavailable` without failing CI or release. Command
  failure, timeout, malformed committed baseline, or breach of the code-owned
  catastrophic median ceiling remains fatal. Unavailable qualification is a
  measured passing outcome, not a pytest skip; no benchmark failure may be
  converted into a skip. An ordinary serial local pytest run may include both
  normal and benchmark tests.
  The wall-clock runner contract path is
  `tests/performance/wall-clock-runner-contract.json`; an observed identity is
  read from the test-harness-only
  `BACKSTITCH_BENCHMARK_RUNNER_IDENTITY_PATH`. The baseline path is
  `tests/performance/wall-clock-baseline.json`, with exactly
  `schema_version = 1`, the lowercase SHA-256 of the runner contract,
  `measured_runs = 5`, `allowed_regression_fraction = 0.2`, and positive
  finite medians for exactly `default-check` and `obligation-list`. Extra
  fields or command IDs are invalid. A baseline bound to another runner
  contract reports `unavailable`
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
| `SPEC_MAPPING_TEST_ONLY` | `BSC009` | warning | none | Active implementation mapping resolves only to test roots |
| `INVARIANT_UNTESTED` | `BSI001` | error/warning | `required`, `draft` | Unique invariant declaration has no valid binding test |
| `INVARIANT_UNKNOWN` | `BSI002` | error | none | Valid test binding names no declaration |
| `INVARIANT_DUPLICATE` | `BSI003` | error | none | Invariant ID is duplicate or collides with a section ID |
| `INVARIANT_BINDING_NOT_TEST` | `BSI004` | warning | none | Well-formed binding marker is outside valid test-definition scope |
| `INVARIANT_MARKER_INVALID` | `BSI005` | error | none | Reserved invariant marker syntax or owner is invalid |
| `INTENT_UNCOVERED_DEFINITION` | `BSN001` | info/error | `repository`, `patch` | Definition has no intent edge and no exemption |
| `INTENT_INHERITED_ONLY` | `BSN002` | info/error | `repository`, `patch` | Definition is covered only by a file-level blanket |
| `INTENT_EXEMPTION_UNUSED` | `BSN003` | warning | none | Intent exemption matches no definition |
| `INTENT_EXEMPTION_UNREASONED` | `BSN004` | error | none | Intent exemption has no valid nonblank reason |
| `INTENT_REQUIREMENT_UNIMPLEMENTED` | `BSN005` | info | none | Declared requirement mappings resolve to no live owner |
| `INTENT_DRIFT_SUSPECT` | `BSN006` | info | none | Mapped implementation changed without governing contract or connected test movement |
| `INTENT_COVERAGE_FLOOR_REGRESSION` | `BSN007` | error | none | Intent coverage is below a configured floor |
| `INTENT_COVERAGE_INCOMPLETE` | `BSN008` | info/error | `repository`, `patch` | A definition could not be classified for intent coverage |
| `INTENT_COVERAGE_POLICY_REGRESSION` | `BSN009` | error | none | Gate policy weakened without an exact acknowledgment |

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

`SPEC_MAPPING_TEST_ONLY` fires once for an active, non-meta requirement when
at least one implementation-mapping target resolves under an effective
`test_root` and no implementation-mapping target resolves outside all
effective test roots. Test targets remain valid test evidence and retain their
graph edges; they are not reclassified as production evidence. Invalid or
unresolved production tokens keep their ordinary mapping diagnostics and do
not suppress BSC009. One resolved production target clears BSC009. Planned,
exploratory, and meta sections do not fire it.

Every issue record carries at least one non-empty locator (`path`,
`section_id`, or `symbol`), and issues arising from a code reference carry the
citing file and line, so a human or agent can always navigate to the problem.

Invariant-traceability diagnostics follow [INV-8].

Intent-coverage diagnostics are the closed [COV-9] registry. `BSN001`,
`BSN002`, and `BSN008` each have exact `repository` and `patch` contexts;
their `info/error` row is an enumerable aggregate for this section's code
inventory, not a third severity value. [COV-9] is the sole context-row
authority: repository is info and patch is error. `BSN003` through `BSN007`
and `BSN009` have no context.

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
- `backstitch/obligations.py`
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

Doctor owns environment diagnosis only. It does not capture a repository
snapshot, compute semantic readiness or packet budgets, validate the trusted
Backstitch capability descriptor against the exact effective request, or
claim that analysis is executable. Exact stable/raw identity resolution,
request-capability validation, request identity, and repository preparation
belong to `analyze --preflight`, which consumes the same resolved-inference
owner as execution. `doctor --probe` remains a reachability check and never
performs a generation. A green doctor is therefore necessary environment
evidence, not a successful request or analysis-readiness receipt.

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
| `INTENT_UNCOVERED_DEFINITION` | `BSN001` | implemented | Intent coverage (`repository`, `patch` contexts; [COV-9]) |
| `INTENT_INHERITED_ONLY` | `BSN002` | implemented | Intent coverage (`repository`, `patch` contexts; [COV-9]) |
| `INTENT_EXEMPTION_UNUSED` | `BSN003` | implemented | Intent-coverage exemption audit ([COV-9]) |
| `INTENT_EXEMPTION_UNREASONED` | `BSN004` | implemented | Intent-coverage exemption audit ([COV-9]) |
| `INTENT_REQUIREMENT_UNIMPLEMENTED` | `BSN005` | implemented | Intent reverse complement ([COV-9]) |
| `INTENT_DRIFT_SUSPECT` | `BSN006` | implemented | Intent drift coverage ([COV-9]) |
| `INTENT_COVERAGE_FLOOR_REGRESSION` | `BSN007` | implemented | Intent-coverage ratchet ([COV-9]) |
| `INTENT_COVERAGE_INCOMPLETE` | `BSN008` | implemented | Intent coverage (`repository`, `patch` contexts; [COV-9]) |
| `INTENT_COVERAGE_POLICY_REGRESSION` | `BSN009` | implemented | Intent-coverage policy ratchet ([COV-9]) |
| `SPEC_MAPPING_TEST_ONLY` | `BSC009` | implemented | Active section maps implementation only to test roots ([SC-11]) |

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

## 17. Internal Architecture And Dependency Direction [SC-17]

The static runtime import graph among `backstitch.*` modules is a directed
acyclic graph. A function-local import remains an edge and does not excuse an
internal cycle. Lazy imports are permitted at the external provider
quarantine, but no lazy import may create an internal strongly connected
component.

Dependency direction is leaf primitives and closed contracts, then source and
configuration adapters, then domain owners, then application workflows, then
CLI adapters. The CLI owns argument parsing, translation to typed application
requests, rendering, and public exit mapping. It does not own domain
computation, snapshot or cache lifecycle, or artifact-set publication.

Each supported behavior has one shipping orchestration path, and behavioral
tests exercise that path. A test-only duplicate orchestration path is not a
supported interface. Cohesion, shared state, and lifecycle determine module
boundaries; file length alone does not. Generic no-follow I/O, identity, and
artifact-publication primitives have one leaf owner when they are genuinely
independent of a domain lifecycle.

Names changed by architecture work read as short declarative statements at
their call sites. Architecture work does not require a standalone rename wave.

Executable gates enumerate the internal import graph and enforce zero strongly
connected components larger than one. Ruff enforces McCabe complexity `C901`
at a ceiling of 10 over every lint-eligible tracked Python source and intended
extensionless Python entry point. The score is a review trigger, not a design
verdict. A function above the ceiling is permitted only through the reviewed,
source-linked suppression process in [SC-17.1]. File length alone remains
insufficient reason to split an owner.

_Implementation mapping_:
- `backstitch/cli.py`
- `backstitch/config.py`
- `backstitch/settings.py`
- `backstitch/filesystem_io.py`
- `backstitch/scan_exclusions.py`
- `backstitch/semantic_eval_identity.py`
- `backstitch/semantic_verification_contract.py`
- `backstitch/artifact_publication.py`
- `backstitch/check_application.py`
- `backstitch/coverage_application.py`
- `backstitch/packet_application.py`
- `backstitch/semantic_application.py`
- `backstitch/obligation_api.py`
- `backstitch/semantic_cache.py`
- `backstitch/markdown_specs.py`
- `tests/test_architecture.py`
- `tests/test_traceability_reducer.py`
- `pyproject.toml`
- `.github/workflows/ci.yml`

### 17.1 Repository Complexity And Suppression Gate [SC-17.1]

<!-- backstitch: skip-obligation [SC-17.1] "The generated suppression registry is exhaustively checked by Ruff policy and index gates; model evaluation would duplicate deterministic proof and exceed the reviewed provider request capability." -->

Ruff's version is exact-pinned in the development manifest and lock. The
repository proves that the executing binary, manifest pin, and lock resolve
to the same version before deriving rule or suppression inventories.

The normal configured Ruff check includes `C901` with
`lint.mccabe.max-complexity = 10`. Lint discovery covers every tracked Python
source that is not inside an explicit, test-owned fixture-input exclusion and
every intended extensionless Python entry point. Formatter scope is
independent and does not expand merely because lint discovery expands.

A governed source suppression has the form
`# noqa: <RULES> approved [SC-17.1] RUFF-SUP-NNN exception`. Its group ID must
exist exactly once in the registry below. The generated index identifies a
suppression by `repo-relative path::qualified symbol`; line numbers are
presentation data, not identity. Each source pointer must map to exactly one
active Ruff diagnostic for the declared rule, except when the registry
explicitly declares and tests a reviewed cardinality greater than one.

A registry row records the group ID, rule set, approved source-directive
count, approved raw-diagnostic counts per rule, temporary or permanent
lifetime, protected invariant, real proof, rejected alternatives, and
approval. Blank, placeholder, circular, or score-only rationales are invalid.
Temporary rows name a deterministic removal or re-evaluation task. Permanent
rows explain why splitting the owner would weaken locality or correctness and
cite the real test or acceptance proof.

The checked generator derives the active source inventory, validates every
registry/source relationship, and rewrites only the generated region below.
It fails closed on a missing or duplicated registry heading, malformed
markers, unknown groups or rules, stale symbols, duplicate pointers,
cardinality drift, unregistered raw diagnostics, or source/spec disagreement.
The generator must prove that the exact registry heading exists once in this
active spec; agreement between a fixture and a ported constant is not proof.

The global raw inventory covers diagnostics emitted by the active configured
Ruff rule families when `noqa` is ignored. It does not claim to inventory
textual `noqa` comments for disabled rule families. Per-file ignores, global
baseline allowlists, silent threshold inflation, and unregistered `noqa`
directives are not valid substitutes for a registry row.

CI and release prechecks run the normal Ruff check and the suppression-index
check. A change to the Ruff pin, discovery surface, active rules, threshold,
source markers, registry, or generator requires recomputing the raw inventory
and reviewing every changed disposition.

#### Approved Ruff Suppression Registry

| Group | Rules | Approved directives | Approved raw diagnostics by rule | Lifetime | Protected invariant | Real proof | Rejected alternatives | Approval |
|---|---|---:|---|---|---|---|---|---|
| `RUFF-SUP-001` | `C901` | `1` | `C901=1` | permanent | One product-identity traversal owns cache exclusion, nonregular rejection, no-follow reads, executable bits, hashes, and canonical order. | test_authoritative_product_identities_* in tests/test_alignment_eval.py. | Separating traversal from opened-file identity would create a TOCTOU seam. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-004` | `C901` | `1` | `C901=1` | permanent | One strict filesystem-to-JSON boundary preserves regular-file, no-symlink, duplicate-key, finite-number, and object-only validation. | tests/test_alignment_eval.py duplicate-key, noncanonical-byte, and symlink cases. | Generic JSON helpers would detach filesystem identity and first-error precedence. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-005` | `C901` | `1` | `C901=1` | temporary: T8 alignment, CLI, evidence, and coverage | Create a named per-fixture manifest validator returning one fixture definition and coverage facts while phase-wide hashes, uniqueness, and coverage stay local. | Full phase manifest, fixture, coverage, declaration, and candidate-artifact matrix in tests/test_alignment_eval.py. | Reclassify P3 if the helper must shuttle mutable aggregate sets or phase-wide decisions. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-006` | `C901` | `1` | `C901=1` | permanent | One untrusted-artifact boundary owns canonical bytes, closed envelope shape, operation and snapshot identity, digest, and counts. | CLI-output mutation, malformed artifact, snapshot, and Phase A and B recomputation tests in tests/test_alignment_eval_result.py. | Field-at-a-time helpers would obscure first-failure order. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-007` | `C901` | `1` | `C901=1` | permanent | One explicit readiness and guidance-code decision table recomputes bootstrap outcome. | Bootstrap readiness, call and proof binding, raw authority, and stored-metric drift tests in tests/test_alignment_eval_result.py. | A rule engine or predicate-per-branch split would hide decision precedence. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-008` | `C901` | `1` | `C901=1` | permanent | One graph-contract audit preserves ID and coordinate uniqueness, closed relation kinds, endpoint resolution, locator direction, and obligation ownership. | Candidate reconstruction, obligation identity, duplicate-coordinate, and canonical run tests in tests/test_alignment_eval_result.py. | Separate static and declared validators could diverge on shared endpoint rules. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-011` | `C901` | `1` | `C901=1` | permanent | One explicit read-only command grammar owns option uniqueness, selector conflicts, pagination constraints, and fixture-root binding. | Noncanonical recorded argv, malformed call-log, and canonical run-binding tests in tests/test_alignment_eval_result.py. | Argparse reuse or generic option tables could accept more than the recorded proof grammar. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-012` | `C901` | `1` | `C901=1` | permanent | One fixture-tree boundary owns contained paths, manifest identity, exact inventory, hashes, normalized collisions, and frozen config. | Missing, extra, changed, symlink, collision, and config cases in tests/test_alignment_eval.py. | Independent manifest and filesystem validators could disagree about the accepted tree. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-013` | `C901` | `1` | `C901=1` | permanent | One content-addressed plan loader preserves Phase A and B identity isolation, path and hash validation, sessions, thresholds, and product identities. | Closed-plan, phase-isolation, session-count, product-identity, and threshold-drift tests in tests/test_alignment_eval.py. | Splitting field groups would obscure which inputs contribute to each phase identity. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-014` | `C901` | `1` | `C901=1` | permanent | One provider boundary owns resolved model identity, request options, schema mode, transport, usage, and closed provenance. | Exact-wire, raw-transport, schema, identity-mismatch, omission, no-retry, and absence tests in tests/test_analysis_llm.py. | Provider subclasses or duplicated request assembly would create parallel transport contracts. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-015` | `C901` | `1` | `C901=1` | permanent | One packet planner owns active selection, materialization, cumulative ceilings, first crossing, progress, and measured-prefix accounting. | Budget crossing, retained bytes, deadline phases, progress, clean corpus, and mixed-kind tests in tests/test_analysis_packets.py. | A second accounting pass or divergent dry-run planner would break measured-byte authority. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-016` | `C901` | `1` | `C901=1` | permanent | One current-row boundary owns schema, kind and identity coupling, hashes, classification, evidence coordinates and order, and role completeness. | Current suppression, invariant, role-set, vocabulary, malformed field, confidence, and evidence tests in tests/test_analysis_results.py. | Generic schema machinery or reordered checks would weaken audited first-error behavior. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-017` | `C901` | `1` | `C901=1` | permanent | One compatibility owner distinguishes current, partial-current, and legacy result rows and enforces packet-local evidence. | Legacy and partial union, suppression reinterpretation, kind mismatch, packet evidence, malformed JSON, and classification tests. | Independent legacy dispatch could reinterpret partial current rows. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-018` | `C901` | `1` | `C901=1` | permanent | One invariant-packet boundary owns identity, content hash, locator, snippets, and issue shape. | Legacy invariant acceptance, malformed invariant, discriminator leakage, and content-bound tests. | Merging section and invariant branches would make discriminator-specific precedence implicit. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-019` | `C901` | `1` | `C901=1` | permanent | One loader owns line framing, JSON parsing, schema discrimination, legacy normalization, and row-context errors. | Full load, normalization, and malformed matrix in tests/test_artifact_contracts.py. | Separate loaders could classify the same row differently. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-020` | `C901` | `1` | `C901=1` | permanent | One relational shape check owns declared-region containment, relation lists, locators, and canonical order. | v3 source-aligned, nested declaration, and malformed packet tests. | Separating containment from relation ordering could admit internally inconsistent packets. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-021` | `C901` | `1` | `C901=1` | permanent | One v3 header audit owns identity, locator, span, hashes, and closed header vocabulary. | v3 producer and loader round trips through analysis packet and artifact contract suites. | One helper per field would add indirection without a new owner. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-022` | `C901` | `1` | `C901=1` | permanent | One summary validator owns counts and cross-field total consistency. | Packet compilation, load, and summary-disagreement tests. | Generic count validation would lose packet-kind semantics. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-023` | `C901` | `1` | `C901=1` | permanent | One schema-4 audit owns suppression versus source discriminator rules, relations, issue order, hashes, spans, and identity. | Schema-4 suppression, hash sensitivity, issue order, malformed packet, and load tests. | Handler maps or reflection would obscure the closed discriminator contract. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-024` | `C901` | `1` | `C901=1` | permanent | One explicit legacy section-packet shape preserves discriminator-specific fields and error order. | Legacy normalization and malformed section packet cases in tests/test_artifact_contracts.py. | Reflection or a generic packet validator would hide the compatibility table. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-025` | `C901` | `1` | `C901=1` | permanent | One v2 invariant migration contract owns declaration, span, content, hash, and semantic issue validation. | v2 invariant bounds, declaration-before-marker, multiline declaration, and malformed invariant tests. | Shared v2 machinery is rejected unless it preserves every discriminator-specific first error. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-026` | `C901` | `1` | `C901=1` | permanent | One v2 section migration contract owns snippets, source bounds, semantic issues, and packet-hash recomputation. | v2 acceptance, producer-bound, and multiline-declaration tests in tests/test_artifact_contracts.py. | Field-loop abstraction would hide section-only constraints. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-029` | `C901` | `1` | `C901=1` | permanent | One CLI adapter owns path conflict validation and closed blocked, failure, publication, and success rendering. | Packet exit, debt, path collision, budget, publication, and clean-corpus tests. | Generic outcome rendering could change public messages or exits. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-030` | `C901` | `1` | `C901=1` | permanent | One explicit command-to-config-key allowlist preserves CLI override scope. | CLI and settings no-op prevention and command-scoping tests. | Reflection over argparse fields or broad pass-through would widen configuration authority. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-032` | `C901` | `1` | `C901=1` | permanent | One tree-sitter node dispatcher preserves definitions, bindings, patterns, calls, attributes, and fallback traversal order. | Static syntax, branch binding, PEP 695, scope, comprehension, and parser-ownership tests. | Visitor registries or runtime-AST fallback would hide or duplicate parser semantics. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-033` | `C901` | `1` | `C901=1` | permanent | One recursive walk owns statement and block traversal plus special case and elif spans. | Statement-body, elif and match, and noqa attachment tests in tests/test_code_parser.py and tests/test_python_refs.py. | Parallel span derivation or generic tree walking would break parser-owned coordinates. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-035` | `C901` | `1` | `C901=1` | permanent | One registry parser owns row validation, short-code uniqueness, replacement existence, and cycle proof. | Registry uniqueness, family, status, replacement, cycle, and canonicalization tests in tests/test_diagnostics.py. | Schema libraries or post-construction repair would obscure fail-closed registry authority. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-036` | `C901` | `1` | `C901=1` | permanent | One endpoint decision table owns URL sanitation, redirects, HTTP states, bounds, payload parsing, and model membership. | Status, redirect, oversized, truncated, slow, credential, malformed payload, membership, and connection tests in tests/test_doctor.py. | Generic HTTP clients or response helpers could follow redirects or leak credentials. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-037` | `C901` | `1` | `C901=1` | permanent | One mutable resolver owner builds module, plausible-name, definition, scope, and function-scope indexes in order. | Module-root, ambiguity, lexical scope, ordinals, PEP 695, and source-order tests in tests/test_evidence_discovery.py. | Helpers that partially mutate resolver tables would split initialization ownership. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-038` | `C901` | `1` | `C901=1` | permanent | One graph-search state machine owns seeds, budget charges, lexical cap, bridges, ambiguity expansion, depth frontier, and ceiling. | Budget-unit, collapsed-bridge, ambiguity, frontier, depth, and candidate-ceiling tests. | Generic graph libraries or split queues would change charging and selection order. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-039` | `C901` | `1` | `C901=1` | permanent | One pass owns issue, conflict, section, invariant, reciprocal flags, and candidate relation rows. | Section and invariant reciprocal, conflict, module invariant, frontier, and projection tests. | Independent relation and trace-flag passes could disagree. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-042` | `C901` | `1` | `C901=1` | permanent | One parser owns reserved-skip exclusion, underscore and HTML grammar, declaration delimiters, mechanisms, references, strict unknowns, and malformed affordances. | Inline, meta, declaration, unknown, reserved, and malformed cases in exclusions and Markdown suites. | Regex decomposition could change precedence or accept near misses. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-043` | `C901` | `1` | `C901=1` | permanent | One canonical ordered path owns rule scopes, meta semantics, usage accounting, unsuppressible diagnostics, and declaration lookup. | Meta, inline-over-config, section, context severity, unsuppressible, unused, and short-code tests. | Separate match and audit passes could disagree about the effective suppression. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-044` | `C901` | `1` | `C901=1` | permanent | One bounded subprocess protocol owns stdin, output threads, deadline, aggregate charging, close and join, and primary failure. | Unsafe-ref, output-budget, byte-budget, large-batch, and timeout-history tests in tests/test_git_baseline.py. | Generic subprocess wrappers or unbounded communicate would weaken resource limits. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-045` | `C901` | `1` | `C901=1` | permanent | One Git record parser owns framing, path arity, renames, OIDs, canonical paths, blob batching, and deterministic transitions. | Multiple-path, merge-base, 200-transition, unsafe-path, and blob-dedup tests. | Line parsing or per-record Git calls would break framing and scale. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-046` | `C901` | `1` | `C901=1` | permanent | One classifier owns mapping, backlink, whole-file inheritance, smallest owner, invariant declarations, binds, and precedence. | Direct, inherited, module, backlink, invariant, binding, exemption, and ambiguity tests in tests/test_intent_coverage.py. | Separate edge classifiers could apply different ownership ambiguity rules. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-048` | `C901` | `1` | `C901=1` | permanent | One reducer transition owns reserved-skip block parsing, ordinary-marker coexistence, interleave invalidation, and state mutation. | Skip order, duplicate, interleave, malformed, and marker coexistence tests. | Preprocessing outside the token reducer would split parser state. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-049` | `C901` | `1` | `C901=1` | permanent | One complete-file resolver owns duplicate invalidation, section and invariant ownership, unused versus invalid classification, and order. | Standalone and inline skip, duplicate, ownership, unknown target, reason, interleave, and coexistence tests. | Eager resolution during token parsing would act on an incomplete file. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-050` | `C901` | `1` | `C901=1` | permanent | One requirement projector owns exact line masking for mappings, traceability markers, skips, HTML directives, and preserved layout. | Wrapped requirement, directive masking, invariant skip, mapping span, and CommonMark tests. | A second Markdown parser would duplicate the structure boundary. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-051` | `C901` | `1` | `C901=1` | permanent | One public problem audit owns the closed code-to-detail-shape contract and canonical envelope validation. | Every closed detail shape, deadline phase, malformed shape, and not-found tests in tests/test_obligation_api.py. | Generic object validation or open detail dictionaries would weaken enumerable API proof. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-052` | `C901` | `1` | `C901=1` | permanent | One text adapter owns explicit operation, result, problem, null, success, and error rendering. | List, get, evidence, candidate pagination, and exact adapter-budget tests. | Reflection or parsing values back from presentation text would make wording load-bearing. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-053` | `C901` | `1` | `C901=1` | permanent | One additional-path derivation boundary owns snapshot roots, captured Markdown, canonical collisions, ownership, and bare-symbol advisory handling. | Target convergence, missing targets, config identity, symlink replacement, and collision tests in tests/test_obligation_runtime.py. | Source reopening or treating bare symbols as paths would violate snapshot authority. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-054` | `C901` | `1` | `C901=1` | permanent | One section state transition owns evidence completeness, conflict precedence, blockers, guidance, rung, skip, gate state, and counts. | Reciprocal and one-sided relations, role independence, test roots, rungs, skip, conflict, and candidate-count tests. | Separate blocker and guidance passes could disagree about the same state. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-056` | `C901` | `1` | `C901=1` | permanent | One application lifecycle owns runtime, deterministic blocking, packet plan, report, progress completion, atomic publication, and failure precedence. | CLI parity, deadline-no-publication, progress isolation, partial publication, and deterministic-block tests. | Moving publication before accounting or using parallel writes would break artifact-set authority. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-057` | `C901` | `1` | `C901=1` | permanent | One line parser owns precedence among file-qualified refs, adjacent groups, ranges, bare IDs, and consumed spans. | File-qualified, compact, comma, cross-bracket, dash, anchor, prose-noqa, and noise tests. | Independent regex passes without shared consumption state could double-project references. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-058` | `C901` | `1` | `C901=1` | permanent | One physical-line pass owns interpolation and escape rejection, bindings, declaration continuations, consumed lines, and invariant construction. | Physical marker, malformed, concatenated, interpolated, escaped, continuation, binding, and owner tests. | Evaluated-string parsing or a parallel marker parser would lose source coordinates. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-059` | `C901` | `1` | `C901=1` | permanent | One stable-read attempt owns expected lstat, no-follow open, fstat identity, bounded chunks, deadline, and close. | Stable bounded failure, per-read deadline, symlink, nonregular, and boundary-pin tests. | Ordinary Path.read_bytes or detached checks would weaken no-follow identity. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-060` | `C901` | `1` | `C901=1` | permanent | One torn-read transaction owns initial inventory, ordered reads, mutation hooks, hashes, and whole-attempt discard. | Torn retry and exhaustion, membership, inode, catalog mutation, and deadline tests. | Retaining partial bytes across attempts would mix repository moments. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-061` | `C901` | `1` | `C901=1` | permanent | One attempt inventory owns normalized targets, source and catalog roles, direct files, directories, missing targets, collisions, and identity. | Additional and missing targets, catalog mutation, collision, unsafe components, budget, and identity tests. | Separate code, spec, and additional inventories could disagree about one repository view. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-062` | `C901` | `1` | `C901=1` | permanent | One descriptor-relative directory lease owns recursion, exclusions, names, catalog and source classification, no-follow opens, and nonregular rejection. | Catalog, exclusion, symlink, Unicode, collision, mutation, and canonical-owner tests in tests/test_repository_snapshot.py. | Path-based reopening or recursion outside the descriptor would create TOCTOU risk. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-063` | `C901` | `1` | `C901=1` | permanent | One public capture owner preserves platform and root validation, config sources, path convergence, retry, catalog hash, and final identity. | Full repository snapshot suite plus no-reopen and shared-projection snapshot resolver tests. | Separate semantic and config snapshots or fallback readers would violate one-view capture. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-064` | `C901` | `1` | `C901=1` | permanent | One projection phase owns report parts, suppression diagnostics and decisions, issue order, parsed artifacts, and immutable output. | Snapshot and check shared projection, suppressions, parser diagnostics, and CLI format consistency tests. | Independent report and artifact passes could diverge. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-065` | `C901` | `1` | `C901=1` | permanent | One completed-edge audit owns mapping and backlink reciprocity, path and symbol coverage, duplicate accounting, and inventory diagnostics. | One-sided mapping and backlink, directory mapping, test-only mapping, and reciprocal tests. | Emitting reciprocity during partial resolution would report transient graph state. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-066` | `C901` | `1` | `C901=1` | permanent | One code-reference phase owns qualified, bare, and range dispatch, prefix filtering, rung classification, deduplication, and backlinks. | Bare, qualified, range, rung, reciprocal, and snapshot resolver tests. | A second parser or separate bare-reference engine would duplicate resolution policy. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-067` | `C901` | `1` | `C901=1` | permanent | One qualified-reference boundary owns containment, existence, classification, section and range expansion, issues, and backlinks. | Missing spec and section, range, outside-root, rung, and reciprocal tests. | Resolving sections without file policy context could accept invalid targets. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-068` | `C901` | `1` | `C901=1` | permanent | One invariant phase owns declaration ownership, target and bind resolution, ambiguity, containment, edges, and issues. | Code and spec invariant, binding, missing and ambiguous target, duplicate, and outside-root tests. | Separate code and spec invariant engines could apply different identity rules. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-069` | `C901` | `1` | `C901=1` | permanent | One resolver phase owns mapping normalization, ladder resolution, ambiguity, missing severity, edges, and diagnostics. | Mapping, ambiguity, missing target, rung, and reciprocal tests in resolver and snapshot resolver suites. | Separate path and symbol lookup paths could diverge. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-070` | `C901` | `1` | `C901=1` | permanent | One captured-byte scan path owns roots, Markdown and Python parsing, module identities, path facts, resolution phases, and final projection. | Shared projection, no-reopen, external target, missing and unreadable row, and CLI check tests. | Any source reopening or parallel scan API would violate snapshot authority. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-076` | `C901` | `1` | `C901=1` | permanent | One prepared-plan byte-integrity validator preserves packet order, contribution equality, prompt prefix, digest, and aggregate measurements. | tests/test_semantic_analysis.py retained-request-byte, misaligned-plan, and prompt-mutation cases | Field-by-field helpers or a second request-byte validation path | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-077` | `C901` | `1` | `C901=1` | temporary: T6 cache and semantic execution | One run owner preserves preflight, cache/verification execution, exit choice, result-before-report publication, report rebuild, and output-error precedence. | Full tests/test_semantic_analysis.py, especially publication failure, partial output, cost, currentness, and verification cases | Phase helpers that pass the full local state or move publication/report validation order | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-079` | `C901` | `1` | `C901=1` | permanent | One ordered analyzer preflight owns the closed cache, identity, timing, packet, and adapter constraints. | tests/test_semantic_cache.py invalid epoch, duplicate ID, cache eligibility, blank provider, and require-mode cases | One helper per check or a generic configuration framework | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-080` | `C901` | `1` | `C901=1` | permanent | Lock-kind selection, unchanged-owner authority, best-effort cleanup, and primary-failure protection remain one guarded transaction. | tests/test_semantic_cache.py cleanup critical-section, ownership-loss, unchanged-token, and primary-failure cases | Per-lock-kind cleanup owners or cleanup errors displacing the primary failure | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-081` | `C901` | `1` | `C901=1` | permanent | One closed inference-contract validator binds prompt, provider, request, cached identity completeness, and canonical form. | tests/test_semantic_cache.py unknown-field, malformed-identity, and corruption matrices | Generic schema validation or separate provider/request acceptance paths | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-082` | `C901` | `1` | `C901=1` | temporary: T6 cache and semantic execution | Ordered cache-mode resolution stays in one owner while a named call owner contains adapter, deadline, reservation, accounting, and external errors. | Full tests/test_semantic_cache.py off/read-write/require, race, deadline, budget, corrupt-hit, and continuation cases | Splitting cache mutation/normalization order or trusting the earlier inspection pass | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-084` | `C901` | `1` | `C901=1` | temporary: T6 cache and semantic execution | Inspection shares only pure preflight and identity freezing, then remains strictly read-only and independently revalidates untrusted hits. | tests/test_semantic_cache.py cache-inspection, off-mode no-stat, corrupt-hit, and require-miss cases | Sharing execution state, creating cache paths/guards, or treating inspection as authoritative for execution | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-085` | `C901` | `1` | `C901=1` | temporary: T6 cache and semantic execution | Verifier work and identity preflight can be shared while hit inspection remains read-only and side-effect free. | tests/test_semantic_verification.py read-only inspection and malformed-work cases | A shared path that constructs adapters, writes cache state, or translates errors differently from execution | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-086` | `C901` | `1` | `C901=1` | permanent | Immutable baseline, result object, inference contract, review identity, and envelope validation remain one no-fallback chain. | tests/test_semantic_cache.py absent-target, stale identity, corrupt target, and race cases | Partial loaders, fallback reads, or reordered artifact validation | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-087` | `C901` | `1` | `C901=1` | permanent | One context-manager owns lexical lease acquisition, second-read arbitration, exact fallback, yield lifetime, and reverse cleanup. | tests/test_semantic_cache.py lock-order, publication-race, carry-forward, deadline, and cleanup cases | Helpers that move lease arrays, selections, or active state across owners | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-088` | `C901` | `1` | `C901=1` | temporary: T6 cache and semantic execution | Ordered verifier cache modes remain one owner while a named call owner preserves deadline, reservation, prompt bytes, adapter, counters, and error translation. | Full tests/test_semantic_verification.py cache, single-flight, deadline, malformed-adapter, and work-preflight suites | Moving hit/miss correction, normalization, or item containment into a generic cache executor | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-091` | `C901` | `1` | `C901=1` | permanent | One filesystem trust boundary observes walk order, symlink status, regular bytes, modes, manifest equality, and digest from one tree. | tests/test_semantic_eval_reports_v3.py fixture load/materialization and validation-priority cases | Separate walker and manifest readers that can observe different filesystem states | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-092` | `C901` | `1` | `C901=1` | permanent | One metric owner shares exact slot populations across expected findings, predictions, stability, false positives, flips, critical cases, and confidence bounds. | tests/test_semantic_eval_reports_v3.py aggregate/by-code recomputation and authoritative observation cases | Generic metrics framework or helpers that duplicate finding-slot definitions | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-093` | `C901` | `1` | `C901=1` | permanent | Attempt identity, primary/replay bytes, provenance, and cache-object hashes remain one artifact chain. | tests/test_semantic_eval_reports_v3.py local identity/cache and replay recomputation cases | Partial result or provenance loaders and reordered hash validation | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-094` | `C901` | `1` | `C901=1` | permanent | One closed deterministic-config contract preserves root containment and ordered unique policy fields. | tests/test_semantic_eval_reports_v3.py corpus manifest/config mutation cases | Generic config schema machinery or reordered first-error precedence | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-095` | `C901` | `1` | `C901=1` | permanent | Claim reconstruction, primary/replay verifier results, aggregate context, and comparison signature remain one event contract. | tests/test_semantic_eval_reports_v3.py event/by-code and effective-epoch recomputation cases | Per-side validators that weaken cross-side byte identity or event ordering | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-096` | `C901` | `1` | `C901=1` | permanent | Analysis, verification, derivation, evaluation, and composition hashes form one paired report identity. | tests/test_semantic_eval_reports_v3.py identity/composition recomputation mutations | Independent analysis and verification validators that can accept a mismatched pair | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-097` | `C901` | `1` | `C901=1` | permanent | Authoritative source facts own eligibility, gold membership, packet validation, and analyzer/verifier evidence rebinding. | tests/test_semantic_eval_reports_v3.py authoritative source-fact and metric cases | Report-derived gold, synthetic packet facts, or splitting evidence validation from eligibility | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-098` | `C901` | `1` | `C901=1` | permanent | Cold/replay lane counters and costs reconcile from one distinct-key population oracle. | tests/test_semantic_eval.py cold-primary/zero-call replay; tests/test_semantic_eval_reports_v3.py local recomputation | Per-counter helpers or report-claimed call populations | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-099` | `C901` | `1` | `C901=1` | permanent | One report-local validator owns closed shape, attempt/event coverage and order, metrics, operational counts, and qualification. | Full tests/test_semantic_eval_reports_v3.py | Moving coverage/order checks into loaders that lack the complete report | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-101` | `C901` | `1` | `C901=1` | permanent | Closed response validation, vocabulary, confidence/rationale rules, evidence normalization, and invariant downgrade precedence remain one boundary. | Full tests/test_semantic_evidence.py, especially downgrade and forged-evidence cases | Separating downgrade from role validation or accepting partial responses | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-102` | `C901` | `1` | `C901=1` | permanent | The explicit kind/classification decision table is the audit surface for minimum evidence roles. | tests/test_semantic_evidence.py every-kind/classification role matrix | Opaque lookup indirection without an enumerable firing matrix | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-103` | `C901` | `1` | `C901=1` | permanent | One matrix owner resolves every code/state cell with later-rule precedence, exact provenance, and failure-authority checks. | tests/test_semantic_policy.py exact-cell, selector precedence, and authority matrices | Generic rule engine or precomputed policy that obscures winning-rule provenance | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-104` | `C901` | `1` | `C901=1` | permanent | Finding-keyed verification composition, disposition use, diagnostic order, and debt projection remain one audit pass. | tests/test_semantic_policy.py transition, precedence, unknown-observation, debt, and unused-disposition cases | Separate diagnostic/debt loops or positional verifier composition | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-105` | `C901` | `1` | `C901=1` | permanent | Top-level schema, scope, currentness, source, alignment, and counts validate before derived source state exists. | tests/test_semantic_reports.py source-shape first-error and current/historical scope matrices | Separate schema-version readers or constructing state before validation completes | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-106` | `C901` | `1` | `C901=1` | permanent | Registry vocabulary, context/severity, occurrence ordinal, and deterministic issue identity recompute in one ordered pass. | tests/test_semantic_reports.py issue identity/order cases; tests/test_canonical_owners.py registry ownership | Trusting rendered issue fields or moving ordinal ownership outside the pass | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-107` | `C901` | `1` | `C901=1` | permanent | Audit, deterministic issues, packet identity, kind counts, timestamp, and content digest reconcile in one source-report validator. | tests/test_semantic_reports.py derived-mismatch, issue-contract, canonical-output, and first-error cases | Digest validation before constituent contracts or a second content projection | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-108` | `C901` | `1` | `C901=1` | permanent | Schema, snapshot, derivation, readiness counts, and selection status validate before normalized packet-report state exists. | tests/test_semantic_reports.py packet source-shape first-error and derived-mismatch cases | Schema-specific parallel loaders or returning state before counts balance | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-109` | `C901` | `1` | `C901=1` | permanent | Exact LF, JSON, canonical bytes, packet binding, semantic evidence, uniqueness, and packet order remain one JSONL boundary. | tests/test_semantic_reports.py exact result-JSONL mutations; tests/test_canonical_owners.py | Separating line parsing from packet-bound canonical revalidation | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-111` | `C901` | `1` | `C901=1` | permanent | One bounded legacy reader preserves its exact count, debt, diagnostic, problem, and status relationships. | tests/test_semantic_reports.py legacy round-trip and current-argument rejection cases | Routing legacy reports through current-schema normalization | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-112` | `C901` | `1` | `C901=1` | permanent | Selected inference, prompts, result sources/providers, reuse mode, and operational count shape remain one schema-5 contract. | tests/test_semantic_reports.py schema-5 operational oracle and authoritative-fact mutations | Normalization that obscures carried versus exact result selection | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-113` | `C901` | `1` | `C901=1` | permanent | Semantic identity, kind/classification, evidence, finding hash, policy provenance, and authority remain one diagnostic contract. | tests/test_semantic_reports.py cross-contract forgery, evidence span, finding hash, and policy cases | Independent hash/evidence/policy validators that can accept different rows | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-114` | `C901` | `1` | `C901=1` | permanent | Alignment vocabulary, identity grammar, skip/gate consistency, canonical order, and readiness counts share one audit population. | tests/test_semantic_reports.py audit-bucket and source-shape cases; suppression lifecycle probes | One handler per obligation kind or partial-row acceptance | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-115` | `C901` | `1` | `C901=1` | permanent | One bounded legacy packet-report reader preserves exact identity, kind, count, warning, prompt, and packet relationships. | tests/test_semantic_reports.py schema-1 round-trip and closed/range/count cases | Current-schema normalization or relaxed legacy acceptance | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-116` | `C901` | `1` | `C901=1` | permanent | The explicit stage/code/details decision table is the closed problem contract. | tests/test_semantic_reports.py _PROBLEM_CASES firing matrix and closed-details mutations | Loose details schemas, generic dispatch, or untested stage/code pairs | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-118` | `C901` | `1` | `C901=1` | permanent | Result objects, events, selected inference, review keys, provenance, selection mode, and provider grouping remain one authoritative chain. | tests/test_semantic_reports.py schema-5 authoritative-fact mutation matrix | Partial provenance loaders or provider grouping derived from report claims | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-119` | `C901` | `1` | `C901=1` | permanent | Enabled/disabled shape, counters, event order, aggregate counts, and report status share one subsection population. | tests/test_semantic_reports.py enabled/disabled, failed-run, cache-off, and aggregate cases | Separate counter and event passes that can accept different populations | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-120` | `C901` | `1` | `C901=1` | permanent | Provider, request, prompt, epoch, and cost fields form one closed verifier identity contract. | tests/test_semantic_reports.py verification-contract relationship mutations | Independent field validators that do not recompute the paired contract | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-121` | `C901` | `1` | `C901=1` | permanent | Claim hash, verifier packet hash, results, evidence, aggregate, and context remain one event contract. | tests/test_semantic_reports.py verification aggregate and evidence-rebinding cases | Per-result validation that loses claim or aggregate linkage | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-125` | `C901` | `1` | `C901=1` | permanent | Packet, claim, request, prompt identity, epochs, hashes, and verify key recompute as one complete provider-independent graph. | tests/test_semantic_verification.py claim/request/identity mutation and normalization cases | Partial validators, self-attesting hashes, or parallel claim/request identity paths | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-128` | `C901` | `1` | `C901=1` | permanent | One closed inventory owns every gate-affecting profile, coverage, diagnostics, and lint key while excluding presentation-only keys and canonicalizing floor scopes. | tests/test_settings.py::test_flatten_ratchet_policy_layer_has_exact_included_and_excluded_gate_keys enumerates every included and excluded gate key, floor-scope canonicalization, and exclude/extend behavior; tests/test_config_parity.py::test_equal_layers_produce_equal_nonoperational_settings proves source parity. | Reflection over all settings fields would silently admit presentation-only inputs. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-129` | `C901` | `1` | `C901=1` | permanent | The explicit closed analyze descriptor, cache, budget, alias, cost, and cross-field contract remains beside final construction. | tests/test_semantic_settings.py every field/type/range, cache identity, cost input, packet bound, and alias cases. | Reflection or dataclass auto-loading would hide field and cross-field firing obligations. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-134` | `C901` | `1` | `C901=1` | permanent | One effective-origin mirror preserves replacement, append, floor reset, and packaged empty-default semantics. | tests/test_settings.py coverage-policy provenance and ratchet trust plus tests/test_config_parity.py equality. | A generic provenance-event framework or a second merge implementation. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-139` | `C901` | `1` | `C901=1` | permanent | One enumerable fixture-table audit owns class grammar, cumulative coverage, negative facts, and subsume-cue validation. | bin/check-dom15-fixtures --self-test and the live DOM-15 gate with one mutation probe per declared rule. | A general Markdown policy engine or removal of a mutation probe. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-142` | `C901` | `1` | `C901=1` | permanent | The explicit fail-closed publication, local-tag, remote-tag, version-change, and retag decision table remains one audit surface. | tests/test_release_script.py plan-tag, published-version, refreshed-state, and conflict cases. | A generic rule engine or one helper per branch. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-145` | `C901` | `1` | `C901=1` | permanent | One end-to-end packets, analyze, cache replay, check, and summary story preserves same-corpus causal assertions and row-level validation. | The live analysis contract plus helper-driven hermetic preflight and real transport tests. | Stage splitting that loses same-corpus causality or mocks the CLI, provider, or cache. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-147` | `C901` | `1` | `C901=1` | permanent | One static AST edge collector includes direct, relative, function-local, and TYPE_CHECKING imports so the conservative graph remains authoritative. | Focused local-edge and TYPE_CHECKING tests plus live DAG and ranked-layer gates. | Runtime import probing or a visitor abstraction that can hide local edges. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-148` | `C901` | `1` | `C901=1` | permanent | One cross-rank private-import audit covers direct imports and module-attribute aliases using the same rank and alias state. | Module-attribute discovery test plus the live layer gate in tests/test_architecture.py. | Runtime reflection or separating alias collection from attribute scanning. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-149` | `C901` | `1` | `C901=1` | permanent | The deterministic two-pass SCC algorithm retains its traversal order and local visited, finish, reverse, and assignment state. | Settings/snapshot separation and zero-live-SCC tests in tests/test_architecture.py. | A graph dependency or fragmented traversal helpers without a new graph contract. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-151` | `C901` | `1` | `C901=1` | permanent | Each matrix case installs two invalid facts and proves the source validator reports the first contractual error. | The parametrized first-error test plus canonical source-shape neighbors in tests/test_semantic_reports.py. | Single-error tests or dynamic mutation that no longer proves precedence. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-152` | `C901` | `1` | `C901=1` | permanent | Every provider dataclass field and request field mutates one composition side while the other side remains byte-identical. | The exhaustive field test plus epoch, threshold, and aggregation composition neighbors. | Reflection that silently accepts a new field or separate tests that lose exact-side causality. | owner task reply Approve 2026-08-05 |
| `RUFF-SUP-153` | `F401` | `1` | `F401=1` | permanent | The doctor intentionally imports llm to prove importability, then obtains the installed version through the package metadata owner. | tests/test_doctor.py import success, import failure containment, version reporting, and no-traceback cases. | Removing the probe import or adding a fake use would stop testing the dependency boundary. | owner task reply Approve 2026-08-05 |

<!-- BEGIN GENERATED RUFF SUPPRESSION INDEX -->
Global active-rule raw inventory: `C901=109`, `F401=1`

| Group | Source symbols | Directives | Raw diagnostics by rule |
| --- | --- | ---: | --- |
| `RUFF-SUP-001` | `backstitch/alignment_eval.py::_authoritative_distribution_inventory` | `1` | `C901=1` |
| `RUFF-SUP-004` | `backstitch/alignment_eval.py::_json_file` | `1` | `C901=1` |
| `RUFF-SUP-005` | `backstitch/alignment_eval.py::_phase_ids` | `1` | `C901=1` |
| `RUFF-SUP-006` | `backstitch/alignment_eval.py::_public_envelope` | `1` | `C901=1` |
| `RUFF-SUP-007` | `backstitch/alignment_eval.py::_recompute_bootstrap_outcome` | `1` | `C901=1` |
| `RUFF-SUP-008` | `backstitch/alignment_eval.py::_validate_candidate_relationships` | `1` | `C901=1` |
| `RUFF-SUP-011` | `backstitch/alignment_eval.py::_validate_recorded_backstitch_argv` | `1` | `C901=1` |
| `RUFF-SUP-012` | `backstitch/alignment_eval.py::_validate_tree` | `1` | `C901=1` |
| `RUFF-SUP-013` | `backstitch/alignment_eval.py::load_alignment_eval_plan` | `1` | `C901=1` |
| `RUFF-SUP-014` | `backstitch/analysis_llm.py::default_provider_adapter` | `1` | `C901=1` |
| `RUFF-SUP-015` | `backstitch/analysis_packets.py::plan_source_aligned_packets` | `1` | `C901=1` |
| `RUFF-SUP-016` | `backstitch/analysis_results.py::_validate_current_analysis_row` | `1` | `C901=1` |
| `RUFF-SUP-017` | `backstitch/analysis_results.py::validate_analysis_row` | `1` | `C901=1` |
| `RUFF-SUP-018` | `backstitch/artifact_contracts.py::_invariant_packet_shape_error` | `1` | `C901=1` |
| `RUFF-SUP-019` | `backstitch/artifact_contracts.py::_load_packets_text` | `1` | `C901=1` |
| `RUFF-SUP-020` | `backstitch/artifact_contracts.py::_packet_v3_declared_error` | `1` | `C901=1` |
| `RUFF-SUP-021` | `backstitch/artifact_contracts.py::_packet_v3_header_error` | `1` | `C901=1` |
| `RUFF-SUP-022` | `backstitch/artifact_contracts.py::_packet_v3_summary_error` | `1` | `C901=1` |
| `RUFF-SUP-023` | `backstitch/artifact_contracts.py::_packet_v4_shape_error` | `1` | `C901=1` |
| `RUFF-SUP-024` | `backstitch/artifact_contracts.py::_section_packet_shape_error` | `1` | `C901=1` |
| `RUFF-SUP-025` | `backstitch/artifact_contracts.py::_v2_invariant_packet_shape_error` | `1` | `C901=1` |
| `RUFF-SUP-026` | `backstitch/artifact_contracts.py::_v2_section_packet_shape_error` | `1` | `C901=1` |
| `RUFF-SUP-029` | `backstitch/cli.py::_cmd_packets` | `1` | `C901=1` |
| `RUFF-SUP-030` | `backstitch/cli.py::_dedicated_cli_overrides` | `1` | `C901=1` |
| `RUFF-SUP-032` | `backstitch/code_parser.py::_StaticSyntaxCollector.visit_reference` | `1` | `C901=1` |
| `RUFF-SUP-033` | `backstitch/code_parser.py::_statement_spans` | `1` | `C901=1` |
| `RUFF-SUP-035` | `backstitch/diagnostics.py::parse_registry` | `1` | `C901=1` |
| `RUFF-SUP-036` | `backstitch/doctor.py::_check_endpoint` | `1` | `C901=1` |
| `RUFF-SUP-037` | `backstitch/evidence_discovery.py::_ReferenceResolver.build_symbol_tables` | `1` | `C901=1` |
| `RUFF-SUP-038` | `backstitch/evidence_discovery.py::_closure` | `1` | `C901=1` |
| `RUFF-SUP-039` | `backstitch/evidence_discovery.py::_project_declared_relations` | `1` | `C901=1` |
| `RUFF-SUP-042` | `backstitch/exclusions.py::parse_traceability_directive_line` | `1` | `C901=1` |
| `RUFF-SUP-043` | `backstitch/exclusions.py::suppression_decision` | `1` | `C901=1` |
| `RUFF-SUP-044` | `backstitch/git_baseline.py::_GitRunner._communicate_bounded` | `1` | `C901=1` |
| `RUFF-SUP-045` | `backstitch/git_baseline.py::_read_transition_changes` | `1` | `C901=1` |
| `RUFF-SUP-046` | `backstitch/intent_coverage.py::_classify_definitions` | `1` | `C901=1` |
| `RUFF-SUP-048` | `backstitch/markdown_specs.py::_TraceabilityReducer.process_reserved_skip_lines` | `1` | `C901=1` |
| `RUFF-SUP-049` | `backstitch/markdown_specs.py::_resolve_skip_candidates` | `1` | `C901=1` |
| `RUFF-SUP-050` | `backstitch/markdown_specs.py::project_section_packet_requirement` | `1` | `C901=1` |
| `RUFF-SUP-051` | `backstitch/obligation_api.py::problem_envelope` | `1` | `C901=1` |
| `RUFF-SUP-052` | `backstitch/obligation_api.py::render_envelope_text` | `1` | `C901=1` |
| `RUFF-SUP-053` | `backstitch/obligation_runtime.py::_declared_mapping_targets` | `1` | `C901=1` |
| `RUFF-SUP-054` | `backstitch/obligations.py::_section_record` | `1` | `C901=1` |
| `RUFF-SUP-056` | `backstitch/packet_application.py::publish_packets` | `1` | `C901=1` |
| `RUFF-SUP-057` | `backstitch/python_refs.py::_extract_line_refs` | `1` | `C901=1` |
| `RUFF-SUP-058` | `backstitch/python_refs.py::_project_python_doc_markers` | `1` | `C901=1` |
| `RUFF-SUP-059` | `backstitch/repository_snapshot.py::_bounded_read_attempt` | `1` | `C901=1` |
| `RUFF-SUP-060` | `backstitch/repository_snapshot.py::_capture_attempt` | `1` | `C901=1` |
| `RUFF-SUP-061` | `backstitch/repository_snapshot.py::_inventory` | `1` | `C901=1` |
| `RUFF-SUP-062` | `backstitch/repository_snapshot.py::_inventory_open_directory` | `1` | `C901=1` |
| `RUFF-SUP-063` | `backstitch/repository_snapshot.py::capture_repository_snapshot` | `1` | `C901=1` |
| `RUFF-SUP-064` | `backstitch/resolver.py::_project_scan_artifacts` | `1` | `C901=1` |
| `RUFF-SUP-065` | `backstitch/resolver.py::_reciprocal_and_inventory_issues` | `1` | `C901=1` |
| `RUFF-SUP-066` | `backstitch/resolver.py::_resolve_code_refs` | `1` | `C901=1` |
| `RUFF-SUP-067` | `backstitch/resolver.py::_resolve_file_qualified_ref` | `1` | `C901=1` |
| `RUFF-SUP-068` | `backstitch/resolver.py::_resolve_invariants` | `1` | `C901=1` |
| `RUFF-SUP-069` | `backstitch/resolver.py::_resolve_mappings` | `1` | `C901=1` |
| `RUFF-SUP-070` | `backstitch/resolver.py::scan_snapshot_with_artifacts` | `1` | `C901=1` |
| `RUFF-SUP-076` | `backstitch/semantic_analysis.py::_resolve_request_bytes` | `1` | `C901=1` |
| `RUFF-SUP-077` | `backstitch/semantic_analysis.py::_run_semantic_analysis` | `1` | `C901=1` |
| `RUFF-SUP-079` | `backstitch/semantic_cache.py::_analyze_config_problems` | `1` | `C901=1` |
| `RUFF-SUP-080` | `backstitch/semantic_cache.py::_drain_owned_cleanup_under_guard` | `1` | `C901=1` |
| `RUFF-SUP-081` | `backstitch/semantic_cache.py::_validate_inference_contract_shape` | `1` | `C901=1` |
| `RUFF-SUP-082` | `backstitch/semantic_cache.py::analyze_with_cache` | `1` | `C901=1` |
| `RUFF-SUP-084` | `backstitch/semantic_cache.py::inspect_semantic_cache` | `1` | `C901=1` |
| `RUFF-SUP-085` | `backstitch/semantic_cache.py::inspect_verification_cache` | `1` | `C901=1` |
| `RUFF-SUP-086` | `backstitch/semantic_cache.py::load_semantic_baseline` | `1` | `C901=1` |
| `RUFF-SUP-087` | `backstitch/semantic_cache.py::prepare_evidence_stable_cache` | `1` | `C901=1` |
| `RUFF-SUP-088` | `backstitch/semantic_cache.py::verify_with_cache` | `1` | `C901=1` |
| `RUFF-SUP-091` | `backstitch/semantic_eval_reports.py::_load_fixture_tree` | `1` | `C901=1` |
| `RUFF-SUP-092` | `backstitch/semantic_eval_reports.py::_metric_row_from_observed` | `1` | `C901=1` |
| `RUFF-SUP-093` | `backstitch/semantic_eval_reports.py::_validate_analysis_attempt` | `1` | `C901=1` |
| `RUFF-SUP-094` | `backstitch/semantic_eval_reports.py::_validate_deterministic_config` | `1` | `C901=1` |
| `RUFF-SUP-095` | `backstitch/semantic_eval_reports.py::_validate_event` | `1` | `C901=1` |
| `RUFF-SUP-096` | `backstitch/semantic_eval_reports.py::_validate_identity` | `1` | `C901=1` |
| `RUFF-SUP-097` | `backstitch/semantic_eval_reports.py::_validate_observed_facts` | `1` | `C901=1` |
| `RUFF-SUP-098` | `backstitch/semantic_eval_reports.py::_validate_operational` | `1` | `C901=1` |
| `RUFF-SUP-099` | `backstitch/semantic_eval_reports.py::validate_semantic_eval_report_consistency` | `1` | `C901=1` |
| `RUFF-SUP-101` | `backstitch/semantic_evidence.py::normalize_model_result` | `1` | `C901=1` |
| `RUFF-SUP-102` | `backstitch/semantic_evidence.py::required_evidence_roles` | `1` | `C901=1` |
| `RUFF-SUP-103` | `backstitch/semantic_policy.py::materialize_semantic_policy` | `1` | `C901=1` |
| `RUFF-SUP-104` | `backstitch/semantic_policy.py::project_semantic_results` | `1` | `C901=1` |
| `RUFF-SUP-105` | `backstitch/semantic_reports.py::_analysis_report_source_state` | `1` | `C901=1` |
| `RUFF-SUP-106` | `backstitch/semantic_reports.py::_packet_report_issue_error` | `1` | `C901=1` |
| `RUFF-SUP-107` | `backstitch/semantic_reports.py::_packet_report_source_shape` | `1` | `C901=1` |
| `RUFF-SUP-108` | `backstitch/semantic_reports.py::_packet_report_source_state` | `1` | `C901=1` |
| `RUFF-SUP-109` | `backstitch/semantic_reports.py::_revalidate_result_jsonl` | `1` | `C901=1` |
| `RUFF-SUP-111` | `backstitch/semantic_reports.py::_validate_analysis_report_v1_shape` | `1` | `C901=1` |
| `RUFF-SUP-112` | `backstitch/semantic_reports.py::_validate_analysis_report_v5_shape` | `1` | `C901=1` |
| `RUFF-SUP-113` | `backstitch/semantic_reports.py::_validate_diagnostic` | `1` | `C901=1` |
| `RUFF-SUP-114` | `backstitch/semantic_reports.py::_validate_packet_report_audit` | `1` | `C901=1` |
| `RUFF-SUP-115` | `backstitch/semantic_reports.py::_validate_packet_report_v1_shape` | `1` | `C901=1` |
| `RUFF-SUP-116` | `backstitch/semantic_reports.py::_validate_problem_v3` | `1` | `C901=1` |
| `RUFF-SUP-118` | `backstitch/semantic_reports.py::_validate_v5_authoritative_facts` | `1` | `C901=1` |
| `RUFF-SUP-119` | `backstitch/semantic_reports.py::_validate_verification` | `1` | `C901=1` |
| `RUFF-SUP-120` | `backstitch/semantic_reports.py::_validate_verification_contract` | `1` | `C901=1` |
| `RUFF-SUP-121` | `backstitch/semantic_reports.py::_validate_verification_event` | `1` | `C901=1` |
| `RUFF-SUP-125` | `backstitch/semantic_verification.py::validate_verification_links` | `1` | `C901=1` |
| `RUFF-SUP-128` | `backstitch/settings.py::_flatten_ratchet_policy_layer` | `1` | `C901=1` |
| `RUFF-SUP-129` | `backstitch/settings.py::_parse_analyze_settings` | `1` | `C901=1` |
| `RUFF-SUP-134` | `backstitch/settings.py::_ratchet_policy_provenance` | `1` | `C901=1` |
| `RUFF-SUP-139` | `bin/check-dom15-fixtures::check` | `1` | `C901=1` |
| `RUFF-SUP-142` | `bin/release.py::plan_tag_action` | `1` | `C901=1` |
| `RUFF-SUP-145` | `tests/live/test_live_llm.py::_exercise_live_llm_analysis_contract` | `1` | `C901=1` |
| `RUFF-SUP-147` | `tests/test_architecture.py::_internal_imports` | `1` | `C901=1` |
| `RUFF-SUP-148` | `tests/test_architecture.py::_private_imports` | `1` | `C901=1` |
| `RUFF-SUP-149` | `tests/test_architecture.py::_strongly_connected_components` | `1` | `C901=1` |
| `RUFF-SUP-151` | `tests/test_semantic_reports.py::test_analysis_report_source_shape_preserves_first_error_priority` | `1` | `C901=1` |
| `RUFF-SUP-152` | `tests/test_semantic_verification.py::test_every_provider_and_request_composition_field_invalidates_its_side` | `1` | `C901=1` |
| `RUFF-SUP-153` | `backstitch/doctor.py::_check_llm_import` | `1` | `F401=1` |
<!-- END GENERATED RUFF SUPPRESSION INDEX -->

_Implementation mapping_:
- `.github/workflows/ci.yml`
- `pyproject.toml`
- `uv.lock`
- `bin/ruff_suppression_index.py`
- `bin/release.py`
- `tests/test_ruff_policy.py`
- `tests/test_ruff_suppression_index.py`
- `backstitch/alignment_eval.py`
- `backstitch/analysis_llm.py`
- `backstitch/analysis_packets.py`
- `backstitch/analysis_results.py`
- `backstitch/artifact_contracts.py`
- `backstitch/cli.py`
- `backstitch/code_parser.py`
- `backstitch/coverage_application.py`
- `backstitch/diagnostics.py`
- `backstitch/doctor.py`
- `backstitch/evidence_discovery.py`
- `backstitch/evidence_summary.py`
- `backstitch/exclusions.py`
- `backstitch/git_baseline.py`
- `backstitch/intent_coverage.py`
- `backstitch/intent_history.py`
- `backstitch/markdown_specs.py`
- `backstitch/obligation_api.py`
- `backstitch/obligation_runtime.py`
- `backstitch/obligations.py`
- `backstitch/packet_application.py`
- `backstitch/python_refs.py`
- `backstitch/repository_snapshot.py`
- `backstitch/resolver.py`
- `backstitch/semantic_analysis.py`
- `backstitch/semantic_application.py`
- `backstitch/semantic_cache.py`
- `backstitch/semantic_eval.py`
- `backstitch/semantic_eval_reports.py`
- `backstitch/semantic_evidence.py`
- `backstitch/semantic_policy.py`
- `backstitch/semantic_reports.py`
- `backstitch/semantic_verification.py`
- `backstitch/settings.py`
- `bin/check-dom15-fixtures`
- `bin/coalesce-check`
- `tests/live/test_live_llm.py`
- `tests/semantic_eval/v3/generate_qualification_candidate.py`
- `tests/test_architecture.py`
- `tests/test_canonical_owners.py`
- `tests/test_semantic_reports.py`
- `tests/test_semantic_verification.py`

## Related Plans

- `docs/plans/2026-08-23-gpt-5-6-luna-responses-plan.md`
  (active implementation plan; request capabilities, Responses migration,
  and release qualification)
- `docs/plans/2026-08-05-ruff-complexity-and-suppression-registry-plan.md`
  (active implementation plan; [SC-17], [SC-17.1])
- `docs/plans/2026-08-04-semantic-preparation-performance-plan.md`
  (implementation plan; [SC-5] and [SC-7])
- `docs/plans/2026-07-29-usability-remediation-plan.md`
  (active usability implementation plan; [SC-5], [SC-10], [SC-11], [SC-14],
  and [SC-15])
- `docs/plans/2026-07-29-architecture-quality-remediation-plan.md`
  (active architecture-quality implementation plan)
- `docs/plans/2026-07-28-intent-coverage-implementation-plan.md`
  (active implementation plan; [SC-5], [SC-6], [SC-8], [SC-10], [SC-11],
  and [SC-15] coverage registrations)
- `docs/plans/2026-07-28-configured-default-command-plan.md`
  (implemented and independently reviewed; uncommitted)
- `docs/plans/2026-07-28-documented-suppression-governance-plan.md`
  (implemented and independently reviewed)
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
