# Backstitch Style Spec-Code Traceability Tool Plan
Status: draft
Source specs: docs/specs/01-development-documentation-operating-model.md [DOM-4], [DOM-5], [DOM-10], [DOM-11]; docs/specs/02-backstitch-core.md [SC-1]-[SC-10]
Superseded by: none

## Goal

Build `backstitch` as a standalone spec-code traceability tool with a first
built-in profile named `backstitch-style-v1`. The profile belongs to
`backstitch`, not Weft. This repository's own specs are the primary local
acceptance corpus; Weft is an early external target corpus and eventual
consumer, not the host repository and not a dependency.

The first implementation must make deterministic traceability useful:
parse Markdown specs, parse Python code backlinks, resolve explicit links,
report missing or weak edges, and expose stable JSON/text output. Semantic
analysis is a first-class capability and uses the required `llm` Python API,
but it must sit on top of deterministic packets and results. Do not add a
Weft-backed analysis path in this plan.

This tool is intentionally narrow. It targets repositories that use stable
spec section IDs, implementation mapping notes, code backlinks, and dated
plans. Do not design a universal traceability platform.

## Source Documents

Read these first, in this order:

1. `AGENTS.md`: repository entry point and definition of done.
2. `docs/agent-context/README.md`: shared context read order.
3. `docs/agent-context/decision-hierarchy.md`: source-of-truth order.
4. `docs/agent-context/principles.md`: traceability and verification rules.
5. `docs/agent-context/engineering-principles.md`: DRY, YAGNI, boundary
   validation, and real proof over mock-heavy proof.
6. `docs/agent-context/runbooks/testing-patterns.md`: test strategy and
   anti-mocking guidance.
7. `docs/agent-context/runbooks/writing-plans.md`: plan expectations.
8. `docs/agent-context/runbooks/hardening-plans.md`: required hardening
   checklist for risky or boundary-crossing work.
9. `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`:
   independent review workflow.
10. `docs/specs/00-specs-index.md`: specs entry point.
11. `docs/specs/01-development-documentation-operating-model.md` [DOM-4],
    [DOM-5], [DOM-10], [DOM-11]: governing documentation, traceability,
    planning, verification, and review requirements.
12. `docs/specs/02-backstitch-core.md` [SC-1]-[SC-10]: preliminary product
    behavior for traceability, CLI, reports, packets, and `llm` semantic
    analysis.
13. `docs/implementation/02-repository-map.md`: current repository map.
14. `pyproject.toml`: package metadata, required dependencies, script entry
    point, and static-tool settings.

Read these Weft files as target-corpus examples, not as implementation owners:

- `../weft/docs/specifications/README.md`: current versus planned spec
  taxonomy and reference-code convention.
- `../weft/docs/specifications/03-Manager_Architecture.md`: rich
  implementation mappings and symbol-heavy mapping prose.
- `../weft/docs/specifications/07-System_Invariants.md`: invariant IDs such
  as `[OBS.13.10]`, implementation mappings, and current/planned split.
- `../weft/weft/context.py`: module and function docstrings with
  file-qualified and bare section references.
- `../weft/weft/_constants.py`: comment-level spec references and Markdown
  anchors.
- `../weft/weft/commands/control_convergence.py`: section ranges such as
  `[STATE.1]-[STATE.6]`.

Comprehension checks before implementation:

- Why is this tool in `backstitch` rather than inside `../weft`?
- Which references are deterministic errors, and which should begin as
  warnings to avoid turning first adoption into a documentation cleanup project?
- Why does deterministic mode not invoke `llm`, even though `llm` is a package
  dependency?
- Why should parser tests use fixture files and real subprocess CLI calls
  instead of mocking file reads, `ast.parse()`, tokenization, or the CLI entry
  point?

## Current Structure And Key Files

Current repository setup:

- `pyproject.toml`: package metadata, required dependencies, `backstitch`
  console script, pytest/mypy/ruff settings.
- `backstitch/`: package root. The current CLI is a minimal importable
  skeleton.
- `docs/specs/`: specs for intended behavior.
- `docs/plans/`: dated implementation plans.
- `docs/implementation/`: rationale, repository maps, and ownership notes.
- `tests/`: does not exist yet. Create it with the first implementation slice.

Files and directories to create or extend in deterministic implementation:

- `backstitch/config.py`
- `backstitch/models.py`
- `backstitch/markdown_specs.py`
- `backstitch/python_refs.py`
- `backstitch/resolver.py`
- `backstitch/reporting.py`
- `backstitch/cli.py`
- `backstitch/profiles.py`
- `tests/__init__.py`
- `tests/fixtures/traceability_project/`
- `tests/test_markdown_specs.py`
- `tests/test_python_refs.py`
- `tests/test_resolver.py`
- `tests/test_cli.py`
- `tests/test_backstitch_corpus_traceability.py`
- `tests/test_weft_corpus_traceability.py`

Files and directories to create only after deterministic checks are useful:

- `backstitch/analysis_packets.py`
- `backstitch/analysis_results.py`
- `backstitch/analysis_llm.py`
- `backstitch/prompts/backstitch_style_analysis.md`
- `tests/test_analysis_packets.py`
- `tests/test_analysis_results.py`
- `tests/test_analysis_llm.py`

Do not create these in the first deterministic slice:

- a dependency on Weft
- a plugin framework
- a database or persisted cache
- a generated documentation site
- CI configuration
- automatic code or doc rewriting

## Dependency Boundary

`backstitch` owns trace graph semantics, deterministic issue classification,
packet generation, semantic result schema, and summaries.

`llm` owns model access for semantic analysis. It is a required dependency, not
an optional extra. Deterministic commands should still avoid invoking model
work.

The one execution boundary in this plan:

- deterministic commands: parse, resolve, report, and generate packets without
  model calls;
- semantic commands: call the `llm` Python API over packet JSONL and write
  structured result JSONL.

The CLI should make this boundary visible:

```bash
backstitch check --repo-root .
backstitch packets --repo-root . --output packets.jsonl

backstitch analyze --packets packets.jsonl --model gpt-5.4
```

There is no `--backend` switch and no Weft analysis backend in this plan. If
durable non-`llm` execution becomes useful later, write a separate plan after
the `llm` packet/result schema is stable.

## Target Design

The first built-in profile is `backstitch-style-v1`. Configuration exists only
to point the profile at roots and choose strictness. It must not become a
general language for arbitrary repo doctrine.

Default profile roots for `backstitch`:

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

Weft root overrides for the first external target corpus:

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

The profile should allow root overrides because `backstitch` itself uses
`docs/specs/`, not Weft's `docs/specifications/`. Do not allow arbitrary
parser semantics in v1.

Section ID grammar:

- IDs start with an uppercase letter and may contain uppercase letters,
  lowercase suffixes, digits, `-`, and `.`.
- Valid examples: `MF-5`, `CLI-1.1.1`, `OBS.13.10`, `SB-0.4a`,
  `MANAGER.12a`, `DOM-4`.
- Prefer exact IDs over broad document-only references.

Spec section discovery must support:

- Markdown headings ending in a section ID, for example
  `## Manager Behaviour [MA-1]`.
- Bullet invariant definitions, for example
  `- **OBS.13.10**: durable task-log history ...`.
- Markdown heading anchors, so explicit references such as
  `docs/specifications/00-Quick_Reference.md#queue-names` can be resolved.

Code backlink discovery must support:

- Python module, class, function, and method docstrings parsed with `ast`.
- Python comments parsed with `tokenize`.
- File-qualified references, for example
  `docs/specifications/05-Message_Flow_and_State.md [MF-5]`.
- Bare references, for example `Spec: [DOM-4]`, resolved only when the section
  ID is unique across the spec corpus.
- Same-prefix ranges, for example `[STATE.1]-[STATE.6]`,
  `[MA-0]--[MA-4]`, and `[IMMUT.1-IMMUT.4]`.
- Multiple IDs in one bracket, for example `[TS-0, TS-1]`.

Implementation mapping discovery must support:

- `_Implementation mapping_:` and `_Implementation mapping per layer_:` blocks
  in specs.
- Backticked path tokens such as `weft/core/manager.py`.
- Backticked explicit symbol tokens such as
  `weft/core/manager.py::Manager._handle_work_message`.
- Existing bare symbol tokens such as `Manager._handle_work_message` as
  advisory mappings only. Do not infer their file in v1.

Issue severities:

- `error`: deterministic explicit reference does not resolve, or the CLI
  cannot scan a requested root.
- `warning`: weak or incomplete trace edge, missing reciprocal backlink,
  unsupported symbol resolution, planned/exploratory spec cited by shipped
  code, broad document-only code reference.
- `info`: inventory output, such as unmapped sections or code owners that cite
  specs outside a current spec mapping.

Initial issue codes:

- `SPEC_FILE_MISSING`
- `SPEC_SECTION_MISSING`
- `SPEC_SECTION_AMBIGUOUS`
- `SPEC_ANCHOR_MISSING`
- `REF_RANGE_UNSUPPORTED`
- `MAPPING_PATH_MISSING`
- `MAPPING_SYMBOL_UNRESOLVED`
- `CODE_BACKLINK_MISSING`
- `CODE_REF_BROAD`
- `CODE_REF_PLANNED_SPEC`
- `CODE_REF_EXPLORATORY_SPEC`
- `SPEC_SECTION_UNMAPPED`
- `CODE_REF_UNMAPPED_FROM_SPEC`

CLI shape:

```bash
backstitch check --repo-root . --profile backstitch-style-v1 --format text
backstitch check --repo-root . --profile backstitch-style-v1 --format json --output /tmp/spec-trace.json
```

Exit codes:

- `0`: no `error` findings.
- `1`: at least one deterministic `error` finding.
- `2`: invalid CLI arguments, unreadable repo root, or internal tool error
  that prevents a report.

JSON report shape:

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

The JSON schema does not need a separate schema file in the first slice. Keep
dataclasses stable and test emitted keys exactly.

## Invariants And Constraints

These constraints are part of the implementation contract:

- Core deterministic mode must not call `llm`.
- Weft must not become a dependency or semantic-analysis backend in this plan.
- Deterministic and analysis modes remain separate. Deterministic mode
  validates graph structure. Analysis mode produces advisory semantic findings.
- Deterministic `error` findings must be objective and reproducible.
- Analysis findings must not fail CI in this plan.
- Do not infer implementation symbols from prose in v1. Resolve paths and
  explicit `path::symbol`; warn on bare symbols.
- Do not auto-edit specs or code.
- Do not fix broad Weft traceability debt while implementing the parser unless
  a deterministic error blocks the target-corpus smoke test.
- Avoid broad config. The default profile is the product.
- Keep output stable. Tests should assert issue codes, severities, paths, and
  line numbers where practical.
- Keep report paths repo-relative where possible.
- Treat planned and exploratory spec citations from shipped code as warnings
  at first, not errors.

Stop and re-plan if:

- implementation wants to add a Weft dependency or backend;
- parser work starts requiring a Markdown AST dependency;
- resolver starts guessing symbol ownership from prose;
- first Weft scan turns the slice into a documentation cleanup project;
- analysis execution starts before deterministic JSON is stable;
- tests mainly mock file IO, AST parsing, tokenization, or CLI behavior.

## Tasks

### 1. Finish package bootstrap and repository map

Outcome: make the repository package shape explicit and remove generated-stub
ambiguity.

Files to touch:

- `pyproject.toml`
- `backstitch/__init__.py`
- `backstitch/__main__.py`
- `backstitch/cli.py`
- `backstitch/py.typed`
- `README.md`
- `docs/implementation/02-repository-map.md`

Implementation notes:

- Keep core `dependencies = []`.
- Put `llm` under required project dependencies.
- Do not add a Weft dependency or extra.
- Keep `backstitch = "backstitch.cli:main"` as the console entry point.
- Add only a minimal CLI parser until the real commands are implemented.
- Delete generated `main.py` if it exists.
- Update the repository map so future agents know `backstitch/` owns the
  package and `pyproject.toml` owns package/tooling metadata.

Red-green TDD:

- Not useful for metadata bootstrap. Replace with import and CLI smoke checks.

Verification:

```bash
uv lock
uv run backstitch --help
uv run python -m backstitch --help
uv run ruff check backstitch
```

Done when:

- package imports through `uv run`;
- console script help works;
- no stale `main.py` entry point remains.

### 2. Add fixture corpus and convention documentation

Outcome: document the backstitch style grammar and create small fixture projects
for parser and resolver tests.

Files to touch:

- `docs/implementation/04-backstitch-style-traceability.md`
- `tests/__init__.py`
- `tests/fixtures/traceability_project/docs/specifications/01-Core.md`
- `tests/fixtures/traceability_project/docs/specifications/01A-Core_Planned.md`
- `tests/fixtures/traceability_project/src/runtime.py`
- `tests/fixtures/traceability_project/tests/test_runtime.py`

Implementation notes:

- The implementation doc should define strict, warning, and advisory edges.
- Fixture project should include:
  - two current spec sections;
  - one planned spec section;
  - one implementation mapping to a real file path;
  - one `path::symbol` mapping;
  - one missing mapping path for failure tests;
  - module, function, and comment backlinks;
  - one planned-spec backlink for warning tests.
- Keep fixtures tiny. They are parser contracts, not a sample application.

Red-green TDD:

- Add fixture files first.
- Parser tests in later tasks should fail until modules exist.

Done when:

- fixture corpus is present;
- implementation doc explains the grammar enough for a zero-context engineer.

### 3. Add core models and profile config

Outcome: create typed dataclasses for parsed specs, code refs, mappings,
issues, and reports, plus the `backstitch-style-v1` profile.

Files to touch:

- `backstitch/models.py`
- `backstitch/config.py`
- `backstitch/profiles.py`
- `tests/test_models.py`

Implementation notes:

- Use `@dataclass(frozen=True, slots=True)` for immutable values.
- Use `Literal` only where it improves severity clarity.
- Do not use Pydantic unless validation complexity forces it. It should not in
  this slice.
- Include diagnostic fields: path, line, section ID, symbol, code, severity,
  message.
- Keep profile defaults in code. Do not add YAML parsing in v1.

Red-green TDD:

- Write tests that instantiate a report, serialize it to JSON-compatible data,
  and assert exact keys.
- Tests should fail before `models.py` exists.

Done when:

- models import without invoking `llm`;
- `uv run pytest tests/test_models.py -q` passes.

### 4. Implement Markdown spec parsing

Outcome: parse section IDs, anchors, and implementation mapping tokens from
Markdown files under configured spec roots.

Files to touch:

- `backstitch/markdown_specs.py`
- `backstitch/models.py` if fields need adjustment
- `tests/test_markdown_specs.py`
- fixture Markdown files if tests need more cases

Implementation notes:

- Use line-based parsing with compiled regexes.
- Parse heading IDs such as `## Manager Behaviour [MA-1]`.
- Parse invariant bullets such as `- **OBS.13.10**: ...`.
- Generate GitHub-style heading anchors.
- Extract implementation mappings from `_Implementation mapping_:` blocks and
  continuation lines until the next clear section boundary.
- Extract only backticked mapping tokens.
- Classify mapping targets as `path`, `path_symbol`, or `symbol`.
- Do not resolve bare symbols here.

Red-green TDD:

- Write fixture-based tests for headings, bullets, anchors, path mappings,
  `path::symbol` mappings, and advisory bare symbols.
- Include a malformed line containing `[NOT-A-SECTION]` in prose and prove it
  is not a section definition.

Do not mock:

- `Path.read_text()`.

Done when:

- Markdown parser tests pass;
- parser can scan `../weft/docs/specifications/` without crashing.

### 5. Implement Python backlink parsing

Outcome: parse spec backlinks from Python module, class, function, and method
docstrings, plus comments.

Files to touch:

- `backstitch/python_refs.py`
- `backstitch/models.py` if fields need adjustment
- `tests/test_python_refs.py`
- fixture Python files if tests need more cases

Implementation notes:

- Use `ast.parse()` and `ast.get_docstring()` for docstrings.
- Walk modules, classes, functions, and async functions.
- Record owner symbols as `module`, `ClassName`, `function_name`, or
  `ClassName.method_name`.
- Use `tokenize` for comments so line numbers are real.
- Parse file-qualified refs, bare refs, ranges, comma lists, and Markdown
  anchors.
- If a Python file has a syntax error, emit a deterministic parser issue
  rather than crashing the scan.

Red-green TDD:

- Add tests for every supported reference form before implementation.
- Include one ambiguous bare section fixture and assert resolver, not parser,
  classifies ambiguity.

Do not mock:

- `ast.parse()`
- `tokenize`

Done when:

- Python parser tests pass;
- parser output includes owner path, owner symbol, line number, raw text, and
  parsed targets.

### 6. Implement deterministic resolver and trace graph

Outcome: combine parsed spec sections, implementation mappings, anchors, and
code backlinks into a trace graph with deterministic issues.

Files to touch:

- `backstitch/resolver.py`
- `backstitch/models.py`
- `tests/test_resolver.py`

Implementation notes:

- Keep resolution pure: parsed records in, report out.
- Resolve file-qualified spec references by repo-relative path and section ID
  or anchor.
- Resolve bare section IDs only when unique across the spec corpus.
- Expand supported same-prefix numeric ranges only when every intermediate
  section exists.
- Emit `REF_RANGE_UNSUPPORTED` instead of guessing.
- Resolve mapping paths against repo root.
- Resolve `path::symbol` only for Python files with AST symbol inventory.
- Treat missing files, sections, anchors, unparseable requested files, and
  unsupported explicit ranges as errors.
- Treat missing reciprocal backlinks, planned/exploratory code refs, broad
  document-only refs, and unresolved bare mapping symbols as warnings.
- Include `SPEC_SECTION_UNMAPPED` as info by default.

Red-green TDD:

- Build one clean fixture graph and one deliberately broken fixture graph.
- Assert exact issue codes and severities.
- Test reciprocal warnings separately from hard resolution errors.

Done when:

- resolver tests pass;
- fixture project produces stable JSON-compatible output.

### 7. Add reporting and CLI commands

Outcome: expose deterministic checks through `backstitch check` with text and
JSON output.

Files to touch:

- `backstitch/reporting.py`
- `backstitch/cli.py`
- `backstitch/__main__.py` only if entrypoint behavior changes
- `tests/test_cli.py`

Implementation notes:

- Use `argparse`; no Typer dependency.
- Support:
  - `check`;
  - `--repo-root`;
  - `--profile backstitch-style-v1`;
  - `--spec-root`, repeatable override;
  - `--code-root`, repeatable override;
  - `--format text|json`;
  - `--output PATH`;
  - `--warnings-as-errors`.
- Text output should have a summary and grouped issues.
- JSON output should match the report model keys.
- Exit `1` on errors, or warnings when `--warnings-as-errors` is set.
- Exit `2` for invalid args or scan failures that prevent a report.

Red-green TDD:

- Use subprocess tests against the fixture project.
- Test clean, broken, JSON, text, output file, invalid repo root, and
  `--warnings-as-errors`.
- Direct function tests can supplement subprocess tests, but they are not the
  only proof.

Done when:

- `uv run pytest tests/test_cli.py -q` passes;
- `uv run backstitch check --repo-root tests/fixtures/traceability_project`
  returns expected exit codes.

### 8. Add backstitch self-corpus check

Outcome: prove the tool can scan `backstitch`'s own specs, plans, implementation
docs, and package code. This is the primary local acceptance corpus for
`backstitch-style-v1`.

Files to touch:

- `tests/test_backstitch_corpus_traceability.py`

Implementation notes:

- Use this repository root as the target.
- Assert:
  - scan completes;
  - no deterministic `error` findings exist for explicit file, section,
    anchor, or mapping path references.
- Allow warnings while the initial code surface is still small.
- If dead references are found, fix the exact broken reference or stop and
  report that the backstitch docs need a separate cleanup slice.

Red-green TDD:

- Add this test before broad cleanup.
- It should fail only on objective dead references, not advisory warnings.

Done when:

- `uv run pytest tests/test_backstitch_corpus_traceability.py -q` passes.

### 9. Add first Weft target-corpus check

Outcome: prove the same profile can scan Weft with root overrides and gate only
objective deterministic errors at first.

Files to touch:

- `tests/test_weft_corpus_traceability.py`

Implementation notes:

- Locate Weft as `../weft` relative to this repo.
- Skip with a clear pytest message if `../weft` is absent. Do not make the
  package depend on Weft's source tree for ordinary users.
- Use `backstitch-style-v1` with Weft root overrides.
- Assert:
  - scan completes;
  - no deterministic `error` findings exist for explicit file, section,
    anchor, or mapping path references.
- Allow warnings. The first Weft adoption should reveal migration work without
  failing on weak reciprocal links.
- If dead references are found, fix only the exact broken reference or stop and
  report that Weft needs a separate cleanup slice.

Red-green TDD:

- Add this test after the self-corpus test is passing.
- It should fail only on objective dead references, not advisory warnings.

Done when:

- `uv run pytest tests/test_weft_corpus_traceability.py -q` passes or skips
  cleanly when Weft is absent.

### 10. Generate analysis packets

Outcome: create bounded semantic-review packets from deterministic results.

Files to touch:

- `backstitch/analysis_packets.py`
- `backstitch/prompts/backstitch_style_analysis.md`
- `backstitch/cli.py`
- `tests/test_analysis_packets.py`

Implementation notes:

- Add:

  ```bash
  backstitch packets --repo-root . --profile backstitch-style-v1 --output packets.jsonl
  ```

- Each packet should include:
  - packet ID;
  - spec file, section ID, title, and section text;
  - resolved implementation files and optional symbols;
  - bounded code snippets;
  - directly linked tests if present;
  - deterministic issues touching that section;
  - prompt instructions requiring structured output.
- Default snippet limits: no more than 120 lines per code owner and no more
  than 8 code owners per packet. If broader, emit a packet warning instead of
  dumping huge files.
- Do not call an LLM in this task.

Red-green TDD:

- Fixture packet tests first.
- Assert bounded snippets and stable JSONL fields.

Done when:

- packet tests pass;
- packet JSONL is small enough for code review.

### 11. Accept and summarize semantic analysis results

Outcome: validate structured semantic findings and aggregate them with
deterministic findings.

Files to touch:

- `backstitch/analysis_results.py`
- `backstitch/cli.py`
- `tests/test_analysis_results.py`

Implementation notes:

- Add:

  ```bash
  backstitch summarize-analysis \
    --deterministic-report spec-trace.json \
    --analysis-results trace-analysis.jsonl \
    --format text
  ```

- Classifications:
  - `ok`
  - `confirmed_mismatch`
  - `probable_mismatch`
  - `missing_trace`
  - `ambiguous`
- Invalid analysis rows are analysis-summary errors, not repo trace errors.
- Semantic findings must not change deterministic issue severity.
- Text output must separate deterministic structure issues from semantic
  advisory findings.

Red-green TDD:

- Test valid rows, invalid JSON, unknown packet IDs, and unsupported
  classifications.

Done when:

- analysis result tests pass;
- summaries are stable and reviewable.

### 12. Add `llm` semantic analysis

Outcome: make semantic analysis usable through the required `llm` Python API.

Files to touch:

- `backstitch/analysis_llm.py`
- `backstitch/cli.py`
- `tests/test_analysis_llm.py`

Implementation notes:

- Use the `llm` Python API directly.
- Accept model name, packet input, output path, and concurrency limit.
- Tests should not call external models. Use a fake adapter boundary injected
  into the analysis function.
- Keep the result schema identical to Task 10.
- Do not add a Weft-backed command runner.

Red-green TDD:

- Test prompt construction, packet iteration, model selection, result parsing,
  and malformed model-output handling with a fake model adapter.

Done when:

- `llm` analysis tests pass without network access.

## Testing Plan

Use real files and real subprocesses for core behavior. This tool is mostly
pure parsing and resolution, so there is no reason to mock its main inputs.

Test locations:

- `tests/test_markdown_specs.py`
- `tests/test_python_refs.py`
- `tests/test_resolver.py`
- `tests/test_cli.py`
- `tests/test_backstitch_corpus_traceability.py`
- `tests/test_weft_corpus_traceability.py`
- `tests/test_analysis_packets.py`
- `tests/test_analysis_results.py`
- `tests/test_analysis_llm.py`

What to test:

- Markdown parsing: heading IDs, bullet invariant IDs, anchors, mapping path
  tokens, `path::symbol`, advisory bare symbols, planned/exploratory spec
  classification.
- Python parsing: module/class/function/method docstrings, comments,
  file-qualified refs, bare refs, ranges, comma lists, anchors, syntax errors.
- Resolver: missing file, missing section, ambiguous bare section, missing
  anchor, unsupported range, missing mapping path, unresolved bare symbol,
  planned/exploratory refs, reciprocal warnings, clean fixture graph.
- CLI: text, JSON, output file, exit codes, root overrides,
  `--warnings-as-errors`, invalid repo root.
- Backstitch self corpus: scan this repository's real specs, plans,
  implementation docs, and `backstitch`, and fail only on deterministic
  errors.
- Weft target corpus: scan real `../weft` when present and fail only on
  deterministic errors.
- Analysis packets: bounded snippets, packet warning for broad sections,
  stable JSONL.
- Analysis results: valid rows, invalid JSON rows, unknown packet IDs,
  unsupported classifications.
- Analysis: fake `llm` adapter, malformed model output, and stable result
  JSONL.

What not to mock:

- filesystem reads for fixture projects;
- Python AST parsing;
- tokenization;
- subprocess CLI invocation;
- backstitch's real docs and source in the self-corpus test;
- Weft's real corpus in the target-corpus test when present.

Acceptable mocks or fakes:

- fake `llm` model adapter for backend result formatting;

Red-green discipline:

- Every parser or resolver behavior starts with a failing fixture-based test.
- Do not implement parser behavior because it "seems useful" unless a test
  names the contract.
- If the Weft corpus check fails on documentation debt, stop and classify the
  debt. Do not silently loosen deterministic errors until it passes.

## Verification And Gates

Per-task commands:

```bash
uv run pytest tests/test_models.py -q
uv run pytest tests/test_markdown_specs.py -q
uv run pytest tests/test_python_refs.py -q
uv run pytest tests/test_resolver.py -q
uv run pytest tests/test_cli.py -q
uv run pytest tests/test_backstitch_corpus_traceability.py -q
uv run pytest tests/test_weft_corpus_traceability.py -q
```

Analysis-phase commands:

```bash
uv run pytest tests/test_analysis_packets.py -q
uv run pytest tests/test_analysis_results.py -q
uv run pytest tests/test_analysis_llm.py -q
```

Final gates:

```bash
uv run pytest
uv run mypy backstitch
uv run ruff check backstitch tests
uv run backstitch --help
```

Manual smoke checks after deterministic implementation:

```bash
uv run backstitch check --repo-root . --spec-root docs/specs --code-root backstitch --format text
uv run backstitch check --repo-root ../weft --format json --output /tmp/weft-spec-trace.json
uv run backstitch packets --repo-root ../weft --output /tmp/weft-spec-trace-packets.jsonl
```

Expected result after deterministic phase:

- no deterministic `error` findings for the backstitch self corpus;
- no deterministic `error` findings for the Weft corpus when present, or a
  narrow list of exact dead references that must be fixed separately;
- reciprocal and specificity issues may remain warnings;
- JSON output is stable enough for analysis packets.

## Rollout And Rollback

Rollout:

1. Land package bootstrap.
2. Land deterministic parser, resolver, CLI, and fixture tests.
3. Add backstitch self-corpus check as the primary local acceptance proof.
4. Add Weft corpus check as warning-tolerant external target-corpus proof.
5. Add packet/result schema.
6. Add `llm` semantic analysis.

Rollback:

- Remove `backstitch/` additions for the failed slice.
- Remove matching `tests/` additions.
- Revert `pyproject.toml` only if package bootstrap itself is wrong.
- Keep this plan or supersede it with a corrected plan rather than silently
  deleting execution history.

One-way doors:

- None in deterministic mode.
- Promoting reciprocal warnings to CI errors is a policy one-way door. Do not
  do it in this plan.
- Publishing a package release creates external expectations. Do not release
  until deterministic CLI and packet/result schemas are stable.

## Independent Review Loop

Self-review is required before reporting the plan ready. This plan includes a
fresh-eyes review section below.

External review is recommended before implementation because the plan creates a
new reusable development workflow and a zero-context implementer could build a
too-generic or too-LLM-driven tool. Prefer a different agent family when
available.

Suggested review prompt:

```text
Read docs/plans/2026-06-18-backstitch-style-spec-code-traceability-tool-plan.md.
Review the plan, pyproject.toml, and repository docs. Look for errors, bad
ideas, missing files, over-broad scope, weak tests, and latent ambiguities. Do
not implement anything. Answer whether a zero-context engineer could implement
this confidently and correctly, and list required fixes first.
```

Reviewer should read:

- `AGENTS.md`
- `docs/specs/01-development-documentation-operating-model.md`
- `docs/agent-context/principles.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `pyproject.toml`
- this plan

## Out Of Scope

- Supporting arbitrary documentation systems.
- Supporting every programming language.
- Building a plugin system.
- Adding a Weft dependency or backend.
- Auto-fixing docs or code.
- Running an LLM in CI.
- Failing CI on semantic analysis findings.
- Failing CI on reciprocal warnings before a migration plan exists.
- Rewriting Weft's existing spec mappings in this slice.

## Fresh-Eyes Review

Review pass 1 findings:

- Finding: The original Weft-hosted plan put the tool in the wrong ownership
  boundary.
  Fix: implementation now lives in `backstitch`; Weft is only a target corpus
  and eventual consumer.
- Finding: Semantic analysis could create a circular Weft dependency.
  Fix: semantic analysis uses the required `llm` Python API directly, and this
  plan excludes a Weft backend.
- Finding: Existing Weft mappings include bare symbols that cannot be resolved
  safely.
  Fix: v1 treats bare symbols as advisory and resolves only paths plus
  explicit `path::symbol`.
- Finding: Parser tests could become mock-heavy.
  Fix: the testing plan requires fixture files, real AST/tokenization, real CLI
  subprocess tests, and a real Weft corpus smoke test when present.

Review pass 2 findings:

- Finding: `backstitch` itself uses `docs/specs/`, while the Weft profile
  defaults to `docs/specifications/`.
  Fix: the plan requires root overrides without allowing arbitrary parser
  semantics.
- Finding: `llm` tests could accidentally require network access.
  Fix: tests use fake model adapters; live model calls are out of scope for
  initial backend tests.
- Finding: Promoting warning findings too early would turn adoption into a docs
  migration project.
  Fix: reciprocal and specificity issues remain warnings until a separate
  migration plan.

Residual risk:

- The first Weft corpus scan may be noisy. That is acceptable if deterministic
  errors stay objective, warnings are non-gating, and `llm` analysis waits for
  stable packet/result schemas.
