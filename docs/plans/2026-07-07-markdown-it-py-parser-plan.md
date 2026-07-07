# Markdown Parser Migration To `markdown-it-py`

Status: implemented; Claude adversarial diff review findings resolved.
Plan type: implementation with spec clarification.
Risk level: moderate. This changes the Markdown parsing boundary and touches
the deterministic trace graph contract ([SC-4]).

## Goal

Move Markdown block parsing from Backstitch's line-by-line fence and heading
scanner to `markdown-it-py`. `markdown-it-py` should decide Markdown structure,
including fenced/code/html blocks and source line maps. Backstitch should keep a
thin traceability layer over the parser tokens: section ID extraction, mapping
ownership, mapping target classification, traceability marker handling, GitHub
anchor generation, and diagnostics.

The motivating issue is fence handling. Backstitch should not spend code or
review time deciding whether a line is inside a fence. If `markdown-it-py`
parses a block as a fence or code block, Backstitch treats it as non-declarative
content and moves on.

## Source Documents

- `docs/specs/02-backstitch-core.md` [SC-4], [SC-10], [SC-11], [SC-13]
- `docs/specs/04-backstitch-traceability-exclusions.md` [EXC-4]
- `docs/implementation/02-repository-map.md`
- `docs/implementation/04-backstitch-style-traceability.md`
- `docs/plans/2026-06-18-backstitch-style-spec-code-traceability-tool-plan.md`
  - original stop gate: re-plan if parser work starts requiring a Markdown AST
    dependency
  - original implementation note: line-based regex parsing
- `pyproject.toml`, where `markdown-it-py>=4.2.0` is already a runtime
  dependency
- `backstitch/markdown_specs.py`
- `tests/test_markdown_specs.py`

## Spec Baseline

- Code baseline at plan authoring: `df320ab` plus the current dirty worktree.
- Relevant spec file: `docs/specs/02-backstitch-core.md`.
- This plan intentionally supersedes the 2026-06-18 plan's line-based parser
  instruction. That older plan said to stop and re-plan if a Markdown AST
  dependency became necessary; this is that re-plan.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [SC-4] headings | Any `markdown-it-py` heading token may define a section when its normalized inline source ends in a valid section ID. This includes setext headings and ATX headings with closing hashes. | Current implementation recognizes only ATX heading lines matched by `_HEADING_RE` / `_HEADING_ID_RE`; setext headings are prose, and `## Title [T-1] ##` fails the ID regex. | User intent is to accept Markdown structure accepted by `markdown-it-py`, not maintain a local heading parser. | Proposed [SC-4] delta below. |
| [SC-4] code blocks | `fence` and `code_block` tokens are non-declarative; headings, markers, invariant bullets, and mappings inside them are ignored. | Current parser owns fence state and does not treat indented code blocks as code, so indented `_Implementation mapping_:` or `- **ID**:` can currently declare traceability constructs. | Code-block classification is exactly the Markdown decision Backstitch should stop owning. | Proposed [SC-4] delta below. |
| [SC-4] fence closers | Fence open/close rules follow `markdown-it-py` / CommonMark. A would-be closer with an info string remains content, not a closer. | Current line parser closes a fence on any line starting with a long-enough fence run, including invalid closers such as `````python``. | This fixes a known local parser bug and removes fence-specific logic. | Proposed [SC-4] delta below. |
| [SC-4] mapping code spans | Mapping tokens come from `code_inline` children and use parser-normalized code content. | Current `_BACKTICK_TOKEN_RE` captures raw backtick contents, including surrounding spaces that Markdown inline-code parsing would normalize. | Mapping extraction should use Markdown inline-code tokens rather than a backtick regex parser. | Proposed [SC-4] delta below. |
| [SC-10] self-corpus counts | Sections, mappings, errors, and warnings stay stable; code-ref/edge counts may change only when implementation comments or tests change trace citations. | Baseline before implementation: 57 sections, 84 mappings, 258 code refs, 399 edges, 0 errors, 0 warnings, 40 infos. After implementation and mypy-test updates: 57 sections, 84 mappings, 254 code refs, 395 edges, 0 errors, 0 warnings, 39 infos. | The parser migration preserved spec sections and mappings. The code-ref/edge/info drift comes from rewriting local parser comments and test code, not from Markdown section or mapping extraction. | Recorded here per [SC-10]; no spec change needed. |

## Proposed Spec Delta

Promotion strategy: strategy A, active clarification before code. The behavior
is still [SC-4], but the owner of Markdown block structure changes from local
line logic to `markdown-it-py`.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/02-backstitch-core.md` | A | [SC-4], [SC-10] |

### [SC-4] replace the paragraph beginning "Markdown parsing must track fenced code blocks"

> Markdown block structure is delegated to `markdown-it-py` using its
> CommonMark parser. Backstitch must not maintain an independent Markdown
> fence, indented-code, or block-boundary parser. Headings, invariant bullets,
> implementation mapping markers, and traceability markers are interpreted only
> from non-code Markdown tokens produced by `markdown-it-py`. `fence` and
> `code_block` tokens are example content, not declarations. Block-level HTML
> tokens are also non-declarative except when the token's source text is a
> recognized [EXC-4] `<!-- backstitch: ... -->` traceability marker; those
> marker tokens follow the same preamble and immediate-section placement rules
> as `_Traceability:` marker paragraphs. The enclosing block token's `map`
> source lines are the line-number source of truth for diagnostics. Backstitch
> may inspect the original source lines covered by a non-code token to
> interpret Backstitch-specific marker syntax, but it must not use those lines
> to override `markdown-it-py`'s block classification.

### [SC-4] insert after "backticked mapping tokens for paths, explicit `path::symbol` references, and advisory bare symbols"

> Backticked mapping tokens are Markdown inline-code tokens (`code_inline`)
> inside implementation mapping blocks. Their stored target text is the
> `markdown-it-py` inline-code content after Markdown normalization, while
> Backstitch still classifies that target as `path`, `path_symbol`, or `symbol`.
> Any heading token produced by `markdown-it-py` may define a section if its
> heading text ends in a valid section ID after CommonMark heading
> normalization, including setext headings and ATX headings with closing hashes.

### [SC-10] add to required proof surfaces after "fixture-backed Markdown parser tests"

> - Markdown parser tests that prove declarations inside `markdown-it-py`
>   `fence` and `code_block` tokens are ignored without a Backstitch-owned fence
>   state machine
> - Markdown parser tests that pin known parser-boundary divergences from the
>   legacy line parser: setext headings, ATX closing hashes, indented code
>   blocks, CommonMark fence closers, standalone HTML-comment traceability
>   markers, and inline-code normalization for mapping tokens

## Current Context And Key Files

Read these first, in order:

1. `backstitch/markdown_specs.py`
   - Current `parse_markdown_spec()` reads source lines and owns fence state
     with `fence_state`.
   - It owns heading detection, invariant bullet detection, mapping marker
     detection, mapping block continuation, bracket-bullet subsections,
     traceability markers, and GitHub-style anchor generation.
   - It uses `_BACKTICK_TOKEN_RE` to extract mapping tokens from source text.
2. `tests/test_markdown_specs.py`
   - Existing tests pin heading sections, invariant bullets, mapping blocks,
     bracket bullets, anchors, tildes, ownerless mapping blocks, and ID-less
     heading ownership.
3. `docs/specs/02-backstitch-core.md` [SC-4]
   - Current spec describes Markdown behavior, including fence semantics and
     mapping-block ownership.
4. `docs/specs/04-backstitch-traceability-exclusions.md` [EXC-4]
   - Traceability markers can appear as marker lines, section markers, and
     trailing HTML comments on headings.
5. `markdown-it-py` local API
   - `MarkdownIt("commonmark").parse(text)` returns tokens.
   - `heading_open`, `paragraph_open`, `bullet_list_open`, `list_item_open`,
     `inline`, `fence`, and `code_block` tokens carry enough structure for the
     migration.
   - Token `map` values are zero-based `[start, end]` source line ranges.
   - `inline.children` includes `code_inline` children for backticked mapping
     tokens.

Comprehension checks before editing:

1. What does Backstitch still own after this migration? Answer: only the
   Backstitch traceability grammar over Markdown tokens, not Markdown block
   classification.
2. What is forbidden? Answer: a local fence opener/closer state machine or a
   second Markdown block parser that can disagree with `markdown-it-py`.
3. Why keep `github_anchor()`? Answer: `markdown-it-py` does not own GitHub
   heading-anchor generation; [SC-4] still requires GitHub-style anchors.

## Invariants And Constraints

- `markdown-it-py` is the only owner of Markdown block structure. No local
  fence state, indented-code parser, or regex-based block classifier should
  remain in `parse_markdown_spec()`.
- Backstitch may read original source lines only within token `map` ranges, and
  only to interpret Backstitch-specific constructs in tokens already classified
  as non-code Markdown.
- Declarations inside `fence`, `code_block`, and block-level HTML tokens must
  not create sections, mappings, anchors, or traceability markers, except that
  standalone `html_block` tokens whose source text is a recognized [EXC-4]
  `<!-- backstitch: ... -->` marker must be routed through the existing
  traceability-marker logic.
- Existing Backstitch traceability behavior should stay stable unless the
  current behavior contradicts `markdown-it-py` tokenization. Any such drift
  must be recorded in the Deviation Log and pinned by tests.
- GitHub anchor generation stays in Backstitch. Do not switch to an unrelated
  anchor plugin unless the spec changes again.
- Mapping target classification stays in Backstitch. `markdown-it-py` should
  provide `code_inline` token content; Backstitch still decides path,
  `path::symbol`, or symbol.
- Mapping line numbers must remain precise. `code_inline` child tokens do not
  carry their own source maps, so implementation may scan only the enclosing
  non-code token's mapped source lines to locate each inline-code token's
  source line. That bounded scan is allowed for diagnostics; it must not decide
  Markdown block structure.
- Keep issue codes and severities unchanged.
- Do not introduce a parser plugin framework or user-configurable Markdown
  parser profile in this plan.
- No new runtime dependency. `markdown-it-py` is already present.
- Tests must use the real parser, not token mocks.

## Design Direction

Introduce a small internal token adapter inside `backstitch/markdown_specs.py`.
The adapter should make token-stream processing explicit without exposing
`markdown-it-py` token objects outside the module.

Expected ownership split:

- `MarkdownIt("commonmark")`: Markdown block structure and token line maps.
- Adapter helpers: token traversal, source line lookup, heading inline content,
  `code_inline` extraction, and list item boundaries.
- Existing Backstitch helpers: section-ID regex, `github_anchor()`,
  `classify_mapping_token()`, `parse_traceability_marker_line()`, and issue
  construction.

Implementation should bias toward a readable token walker rather than a large
abstraction. A small local dataclass for normalized block records is acceptable
if it simplifies tests and keeps `parse_markdown_spec()` from knowing
`markdown-it-py` token quirks.

## Tasks

1. **Spec-promotion slice.**
   - Apply the proposed [SC-4] and [SC-10] text.
   - Update `docs/implementation/04-backstitch-style-traceability.md` to remove
     "line-based parsing" / "no Markdown AST dependency" claims and document the
     new boundary.
   - Update `docs/implementation/02-repository-map.md` if needed so
     `markdown_specs.py` is described as the traceability layer over
     `markdown-it-py`.

2. **Parser behavior tests first.**
   - Keep all existing `tests/test_markdown_specs.py` tests.
   - Add tests proving headings, invariant bullets, mapping markers, and
     traceability markers inside `fence` and `code_block` tokens are ignored.
   - Add a standalone `<!-- backstitch: ignore ... -->` marker test for both
     file preamble and immediate section placement. This protects [EXC-4.3]
     from being broken by blanket `html_block` skipping.
   - Add setext-heading and ATX-closing-hash fixtures and assert they define
     sections when `markdown-it-py` emits heading tokens with valid section IDs.
   - Add indented-code fixtures and assert indented heading, mapping marker, and
     invariant-looking lines do not declare anything when parsed as
     `code_block`.
   - Add two fence fixtures that a naive line parser gets wrong:
     - a closing-fence-looking line with an info string, followed by a
       heading-shaped line that must remain inside the fence
     - a 4-space-indented fence opener that CommonMark treats as indented code,
       not a real fence
   - Add or update tests for mapping tokens extracted from `code_inline`
     children rather than regex backtick scanning, including normalized inline
     code such as `` ` a.py ` ``.
   - Add tests that pin `SpecMapping.line` for a multi-line mapping paragraph
     and for the Weft inline-bullet form.
   - Add a marker-placement test for a trailing HTML marker on a heading, so
     the token migration does not regress [EXC-4].
   - Add parser-level anchor tests for headings with trailing HTML-comment
     markers and headings with inline code or emphasis. Anchor input must be
     the raw heading inline source with recognized trailing marker comments
     stripped, not a concatenation of child text tokens.
   - Add loose-list and tight-list mapping-block fixtures so list-item inline
     extraction is tested in both token shapes.

3. **Introduce the `markdown-it-py` token adapter.**
   - Import `MarkdownIt` in `backstitch/markdown_specs.py`.
   - Create the parser with `MarkdownIt("commonmark")`.
   - Convert zero-based token `map` starts to one-based diagnostic line numbers.
   - Use `heading_open` plus following `inline` token to detect headings and
     anchor text.
   - Use list-item paragraph `inline` tokens to detect invariant bullets and
     bracket-bullet subsections.
   - Use paragraph/list inline tokens to detect `_Implementation mapping_`
     markers and extract `code_inline` mapping targets.
   - Route standalone `html_block` tokens through
     `parse_traceability_marker_line()` only when their source text is a
     recognized [EXC-4] marker; ignore other block HTML as declarations.
   - Ignore `fence` and `code_block` tokens as declarations.

4. **Rewrite `parse_markdown_spec()` around tokens.**
   - Remove `fence_state` entirely.
   - Remove `_BACKTICK_TOKEN_RE` as the owner of mapping extraction. If a regex
     remains, it may be used only inside a mapped non-code token to locate the
     source line for already-identified `code_inline` children.
   - Define mapping-block continuation in token terms:
     - a `bullet_list` is part of the mapping block iff the immediately
       preceding non-marker sibling block is the mapping-marker paragraph or a
       continuing mapping-list item
     - standalone recognized traceability-marker tokens may appear between a
       section definition and body content, but they do not extend mapping-block
       continuation
     - tight and loose list items must be normalized so their first `inline`
       child is processed the same way
     - any other non-marker block ends the mapping block
   - Preserve mapping-block ownership rules:
     - nearest preceding ID-bearing heading owns mapping blocks
     - same-or-shallower ID-less heading clears ownership
     - deeper ID-less subheading does not clear ownership
     - bracket bullets inside mapping blocks define sections and own their own
       tokens
     - ownerless mapping blocks emit `MAPPING_BLOCK_OWNERLESS`
   - Preserve traceability marker behavior:
     - file preamble markers before the first section
     - immediate section markers after section definitions
     - trailing heading HTML comments apply to the new heading
     - misplaced markers warn rather than silently applying

5. **Run targeted and full verification.**
   - `uv run pytest tests/test_markdown_specs.py -q`
   - `uv run pytest tests/test_resolver.py tests/test_resolver_ladder.py -q`
   - `uv run pytest tests/test_exclusions.py tests/test_python_noqa.py -q`
   - `uv run pytest tests -q -m "not live_llm"`
   - `uv run pytest tests/acceptance -q`
   - `uv run ruff check .`
   - `uv run ruff format --check .`
   - `uv run mypy backstitch bin/release.py tests --config-file pyproject.toml`
   - `uv run backstitch check --repo-root .`
   - `uv run backstitch check --repo-root . --show-suppressions`
   - Compare `uv run backstitch check --repo-root . --format json` before and
     after implementation. If emitted sections, mappings, edges, or issue
     counts change, record the change in the Deviation Log and update or add
     golden/self-corpus fixtures as required by [SC-10].

6. **Independent review.**
   - Run an independent plan review before implementation.
   - Run an independent diff review after implementation.
   - Specifically ask reviewers whether any local code still decides fence or
     block boundaries outside `markdown-it-py`.
   - If the migration exposes a reusable parser correction, add a durable note
     to `docs/lessons.md`.

## Testing Guidance

Do not mock `MarkdownIt` or hand-create token streams for contract tests. The
point of the change is to prove Backstitch follows the real parser.

Use small fixture Markdown files for parser behavior. Pin structured outputs:
section IDs, section kind, line numbers, anchors, mapping targets, issue codes,
and marker warnings. Message text should be asserted by substring only.

Add tests that would fail if a future maintainer reintroduced a line-level
fence parser and got Markdown fence rules wrong. The minimum cases are:
invalid closing fence with an info string, and an indented fence opener that
CommonMark treats as code.

## Rollout And Rollback

Rollout is a normal code/spec/docs/test change. No CLI shape, JSON schema, or
configuration key changes are planned.

Rollback is a revert of the spec/docs/parser/test changes. Because the public
output schema is unchanged, rollback does not require a compatibility shim.

## Stop Gates

- Stop if the implementation starts maintaining local fence state again.
- Stop if the implementation needs a user-configurable Markdown parser profile.
- Stop if `markdown-it-py` token maps are insufficient to preserve diagnostics;
  record the exact missing line-number case and re-plan.
- Stop if accepting `markdown-it-py` tokenization changes current self-corpus
  output without a test and Deviation Log row.
- Stop if standalone [EXC-4] HTML-comment markers become silent no-ops.
- Stop if mapping tokens lose precise source lines and the implementation cannot
  recover them from the enclosing token's mapped source range.
- Stop if `github_anchor()` behavior would change.
- Stop if the work expands into Python parser or resolver redesign.

## Out Of Scope

- Enabling Markdown plugins or GitHub-flavored Markdown extensions.
- Changing GitHub anchor generation.
- Changing mapping target classification.
- Changing issue codes, severities, or output schemas.
- Reworking the Python reference parser.
- Removing any dependency. `markdown-it-py` is already the dependency this plan
  puts to use.

## Completion Gate

Completion requires:

- [SC-4]/[SC-10] spec clarification applied and reconciled
- parser implementation uses `markdown-it-py` for block structure
- no local fence state remains in `backstitch/markdown_specs.py`
- firing tests prove fenced/code-block declarations are ignored through the real
  parser
- firing tests prove standalone HTML-comment traceability markers still work
- known divergences from the legacy parser are recorded in the Deviation Log
  and pinned by tests
- self-corpus JSON output drift is recorded, or explicitly reported as unchanged
- all verification commands pass
- independent diff review has no unresolved findings
- plan status, verification results, and residual risks are recorded here

## Adversarial Review Results

Claude adversarial plan review ran 2026-07-07. It found blockers in the first
draft:

- standalone [EXC-4.3] HTML-comment markers would have been broken by blanket
  `html_block` skipping
- setext headings and ATX closing hashes were unacknowledged parser-behavior
  changes
- the Deviation Log was empty despite known divergences from the legacy parser
- mapping token line numbers, token-based mapping continuation, and fence
  regression fixtures were underspecified

This draft incorporates those findings into the spec delta, Deviation Log,
invariants, tasks, tests, and completion gate.

## Implementation Results

Implemented 2026-07-07.

Changed files in the implementation slice:

- `backstitch/markdown_specs.py`
- `tests/test_markdown_specs.py`
- `.github/workflows/ci.yml`
- `pyproject.toml`
- `tests/test_analysis_llm.py`
- `tests/test_analysis_results.py`
- `tests/test_doctor.py`
- `tests/test_python_noqa.py`
- `tests/test_release_workflow.py`
- `tests/acceptance/conftest.py`
- `docs/specs/02-backstitch-core.md`
- `docs/implementation/02-repository-map.md`
- `docs/implementation/04-backstitch-style-traceability.md`
- `docs/lessons.md`
- this plan

Implementation notes:

- `parse_markdown_spec()` now walks `MarkdownIt("commonmark").parse(text)`
  tokens. `fence` and `code_block` tokens are non-declarative.
- No local fence state remains.
- Mapping targets come from `code_inline` children. A bounded source-line scan
  over the enclosing token `map` locates diagnostic lines; it does not decide
  Markdown block structure.
- Standalone `html_block` Backstitch markers still route through [EXC-4].
  Inline HTML markers are accepted only as heading trailers, not as prose
  mentions.
- Mapping-list continuation now rejects invariant bullet lists after a mapping
  marker. This was required by the Weft corpus: an implementation mapping
  paragraph may introduce a section's owner set, followed by invariant bullets
  that define sections rather than mapping targets.
- Mapping-list continuation and bracket-bullet section definition use the first
  inline source line from the parser token. Wrapped bracket bullets therefore
  still define their subsection, and code spans on continuation lines are owned
  by that subsection.
- CI mypy now includes tests. `pyproject.toml` excludes only
  `tests/fixtures/`, because those are synthetic target repositories, not
  Backstitch test modules.

Verification run after implementation and Claude re-review closeout:

- `uv run pytest tests/test_markdown_specs.py -q -p no:cacheprovider`: 34
  passed
- `uv run pytest`: 453 passed, 1 skipped (`tests/live/test_live_llm.py` opt-in)
- `uv run pytest tests/acceptance`: 14 passed
- `uv run ruff format --check backstitch bin .github/scripts tests/test_release_script.py tests/test_release_workflow.py tests/test_release_workflow_gate.py tests/test_python_noqa.py tests/acceptance/conftest.py tests/test_analysis_results.py tests/test_analysis_llm.py tests/test_doctor.py tests/test_markdown_specs.py`: 31 files already formatted
- `uv run ruff check`: all checks passed
- `uv run mypy backstitch bin/release.py tests --config-file pyproject.toml`:
  success, 62 source files checked
- `uv run backstitch check --repo-root .`: exit 0; 57 sections, 84 mappings,
  254 code refs, 395 edges, 0 errors, 0 warnings, 39 infos
- `uv run backstitch check --repo-root . --show-suppressions --format json`:
  exit 0; 57 sections, 84 mappings, 254 code refs, 0 errors, 0 warnings, 39
  infos; 152 suppressed issues

## Independent Diff Review Closeout

The first attempt to run Claude was blocked by missing local auth. After auth
was restored, Claude adversarial review ran with session
`b9e57235-59ee-4f67-9764-320d270ef639`. An earlier fallback independent
subagent review and the later Claude review found these issues:

- P1 mixed mapping/invariant lists: a mapping list whose later item was an
  invariant could drop the invariant section and emit its code spans as
  mappings. Fixed by defining invariant items inside mapping lists and skipping
  mapping emission for those items. Added
  `test_invariant_item_inside_mapping_list_is_not_mapping_content`.
- P2 duplicate mapping targets on later source lines: the bounded line lookup
  reused the same line for duplicate code spans. Fixed by tracking both source
  line and span index while matching `code_inline` values. Added
  `test_duplicate_mapping_targets_on_later_lines_keep_source_lines`.
- P2 SC-10 mypy contract stale: spec still said mypy over `backstitch` only.
  Fixed [SC-10] to require mypy over `backstitch`, `bin/release.py`, and tests,
  excluding fixture target repositories.
- P2 stale plan count: corrected parser and aggregate verification counts after
  the new regression tests.
- P1 nested container leakage: blockquoted and ordered-list example content
  could be processed as real headings, invariants, or mapping markers because
  the token loop skipped only `bullet_list_open` containers. Fixed by skipping
  `blockquote_open` and `ordered_list_open` containers as non-declarative
  content. Added
  `test_blockquotes_and_ordered_lists_do_not_declare_traceability`.
- P2 standalone marker casing: standalone uppercase `<!-- BACKSTITCH: ... -->`
  markers were skipped before reaching the case-insensitive marker parser.
  Fixed by routing standalone HTML comments through
  `parse_traceability_marker_line()`. Added
  `test_standalone_html_traceability_markers_are_case_insensitive`.
- P2 `_Traceability:` paragraph casing: paragraph marker dispatch was narrowed
  to a literal uppercase prefix. Fixed by case-insensitive dispatch. Added
  `test_traceability_paragraph_markers_are_case_insensitive`.
- P2 mapping-list continuation: if the first list item after an implementation
  mapping marker was prose and a later item had code, mappings could be
  dropped. Fixed by scanning list items for any mapping-shaped item while still
  treating invariant items as invariant sections. Added
  `test_mapping_list_can_start_with_plain_item_then_mapping_item`.
- P1 wrapped bracket-bullet mappings: Claude re-review session
  `c37d6c23-6152-4463-88cd-50cb4fd07dff` found that wrapped bracket bullets
  matched continuation detection but failed section definition, so their code
  spans could be dropped or misattributed to the parent mapping owner. Fixed by
  matching bracket bullets against the first inline source line and by trimming
  the trailing wrapped-line em dash from bullet titles. Added
  `test_wrapped_bracket_bullet_mapping_defines_subsection`.
- P2 acceptance count wording: answered without code change. There are thirteen
  numbered [SC-10] probes plus one committed-config demonstration test, so
  `tests/acceptance` reports 14 passed while the docs still correctly say
  thirteen probes.
- P2 multi-line code-span line lookup: accepted as residual risk under the
  plan's bounded best-effort source-line lookup. Existing behavior now handles
  duplicate same-target spans on later lines; true multi-line code spans remain
  rare and fall back to the enclosing token start line.
- P2 mypy scope and Python-version changes: full mypy over `backstitch`,
  `bin/release.py`, and `tests` passes. The Python-version changes shown in
  the focused diff predated this parser slice and were not changed here.
- Final focused Claude retry after the wrapped-bullet fix produced no review
  text and returned a Claude error record after manual interruption; session
  `5efea0a6-a752-43fe-858c-7446ff491b69` is recorded for audit but is not
  counted as an independent review.

All actionable independent review findings are resolved.
