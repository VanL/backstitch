# Code Parser Migration To `tree-sitter`

Status: **implemented locally, uncommitted** — codex adversarial rounds 1–4,
verdicts "No" → "No" → "No" → **"Yes, implementable"**, P1s narrowing
4→3→1→0. Implementation review found one blocking statement-span parity issue
(`elif` missing, `case` over-emitted); fixed with parser and end-to-end noqa
fixtures. Pre-first-release shaping; implementation ran after the
`markdown-it-py` base landed.
Plan type: implementation with spec revision and a new runtime dependency.
Risk level: boundary-crossing. This replaces the Python parsing engine that
feeds the deterministic trace graph ([SC-4]), adds a native (wheel-shipped)
dependency, and changes the `PYTHON_SYNTAX_ERROR` contract ([SC-4]/[SC-11]).
The `hardening-plans.md` checklist applies.

## Goal

Move Python code parsing from the standard-library `ast` (plus `tokenize`) to
`tree-sitter` with the `tree-sitter-python` grammar. `tree-sitter` should own
Python *structure* — the module/class/function/method tree, documentation
blocks, statement spans, and comments — while Backstitch keeps a thin
traceability layer over that tree: owner-span/qualname derivation, doc-block
and comment backlink extraction, `Spec:`-marker context classification
([SC-11]), and noqa handling ([EXC-5]).

This is the code-parsing twin of the `markdown-it-py` migration
(`docs/plans/2026-07-07-markdown-it-py-parser-plan.md`): both stop Backstitch
hand-rolling or runtime-locking a parser it should not own, and both
deliberately reverse the 2026-06-18 foundational plan's "parse with `ast`" /
"re-plan before taking a parser dependency" instruction now that a real
release shape is being set.

Two problems are solved together:

1. **Runtime-version independence.** `ast.parse` uses the running
   interpreter's grammar, so Backstitch on Python 3.11 cannot parse target
   code that uses 3.12+ syntax (proven: Weft's PEP 695 generics —
   `class Transition[StateT: str, …]`, `def f[T](…)` — parse on 3.14 and raise
   `SyntaxError` on 3.11). `tree-sitter-python` parses a broad grammar
   independent of the running interpreter, so the low install floor (3.11) and
   correct parsing of modern target code stop being in tension.
2. **A multi-language foundation.** `tree-sitter` is the polyglot parsing
   framework Backstitch will extend to other languages. Adopting it while the
   Python analyzer is ~380 lines is the cheapest this migration will ever be,
   and it is done once rather than migrating twice. This plan lays the
   foundation and ships Python on it; it does **not** build multi-language
   dispatch machinery (see Out Of Scope).

## Language Roadmap (scopes the seam)

Committed direction, used here only to shape the seam so the Python
implementation does not bake in Python-only assumptions — **no other language
is built in this plan**:

- **2nd: JavaScript / TypeScript** (`tree-sitter-javascript`,
  `tree-sitter-typescript` — TS/TSX is a separate grammar from JS).
- **3rd: Rust or Java** (`tree-sitter-rust`, `tree-sitter-java`).

The load-bearing consequence: **Python is the only one of these with
docstrings.** JS/TS (JSDoc `/** */`), Rust (`///`, `//!`), and Java (Javadoc)
attach documentation via *structured comments*, not a string-literal node. So
the seam's documentation primitive must be a language-neutral **doc block**
("owner-attached documentation text + line span"), of which a Python docstring
and a JSDoc comment are both instances — never "the first string expression."
Owner *forms* also differ (JS arrow functions / function expressions / object
methods; TS interfaces, type aliases, namespaces), so owner-span shape is
language-defined. This roadmap also forecloses `parso` (Python-only) as an
option: a polyglot roadmap requires a polyglot engine.

## Requested Outcomes

- The existing `python_refs.py` public surface (`parse_python_file`,
  `python_symbol_spans`, `python_symbol_inventory`) behaves identically for
  all files the current `ast` path parses successfully — proven byte-for-byte
  on the self-corpus and Weft via a golden-output diff, except the deliberate
  `PYTHON_SYNTAX_ERROR` contract change below.
- Backstitch running on Python 3.11 parses 3.12+ target syntax without a false
  `PYTHON_SYNTAX_ERROR`, proven with fixtures for **PEP 695 generics**, **PEP
  695 `type` aliases**, and **PEP 701 f-strings** (each parsed on the 3.11
  interpreter). The Weft corpus gate passes on 3.11.
- `tree-sitter` + `tree-sitter-python` are pinned runtime dependencies with
  matrix wheel coverage (3.11–3.14 × {Linux, macOS, Windows} × {arm64, x64})
  **proven by a binary-only install (source builds disabled)** on the target
  matrix, not merely a local `uv lock`.
- A **specified** language-analyzer seam (`ParsedModule` contract, below) so a
  second language is a new implementation of one interface — without
  speculative multi-language machinery.
- The spec is updated: the Python-structure boundary and the
  syntax-error-as-error sentence ([SC-4]), the `PYTHON_SYNTAX_ERROR`
  severity/suppressibility ([SC-11]), and the required test surfaces ([SC-10]).

## Source Documents

- `docs/specs/02-backstitch-core.md` [SC-4] (deterministic trace graph, code
  backlinks, and the "syntax errors … are deterministic errors" sentence
  ~line 234), [SC-10] (required proof surfaces), [SC-11] (issue codes /
  `PYTHON_SYNTAX_ERROR` severity), [SC-13] (input validation)
- `docs/specs/04-backstitch-traceability-exclusions.md` [EXC-5] (noqa forms;
  comment form attaches to the next statement only), [EXC-9] (comment-directive
  containment regression class)
- `docs/specs/05-backstitch-invariants.md` (Proposed) — code-declared
  invariants live in docstrings of the owning module/class/function/method;
  the analyzer must keep exposing doc-block owners and scopes
- `docs/plans/2026-07-07-markdown-it-py-parser-plan.md` — structural precedent
- `docs/plans/2026-06-18-backstitch-style-spec-code-traceability-tool-plan.md`
  — the foundational plan this supersedes for Python parsing (lines 219, 506,
  524 prescribe `ast`; the line-329 stop gate guards against a parser AST
  dependency). This plan is that re-plan.
- `backstitch/python_refs.py` (read first), `backstitch/models.py`
  (`ERROR_SEVERITY_CODES`, the `PYTHON_SYNTAX_ERROR` row), `backstitch/cli.py`
  (`_cmd_check`/`_cmd_packets` exit codes ~lines 321–346;
  `--warnings-as-errors` at ~line 106), `backstitch/exclusions.py`
  (suppression gates on `issue.severity == "error"`, ~line 225)
- `tests/test_python_refs.py`, the self-corpus and Weft corpus traceability
  tests, `tests/acceptance/`
- `pyproject.toml`; `docs/agent-context/runbooks/hardening-plans.md`,
  `testing-patterns.md`
- `tree-sitter` (PyPI 0.26.0, per-version wheels incl. cp314, requires-python
  >=3.10) and `tree-sitter-python` (PyPI 0.25.0, `cp310-abi3` wheels for
  macOS/Linux/Windows × x64/arm64). API for 0.26: `Language(tspython.language())`,
  `Parser(LANGUAGE)`, `Node`, `Query` + `QueryCursor(query)`. **Re-verify the
  binding API against the exact pins at implementation** — it moved across
  0.21→0.23→0.25.

## Spec Baseline

- Code baseline: `7d85601` with a clean worktree. The `markdown-it-py`
  migration has landed; the 3.11-floor and CI matrix finalization remain part
  of this plan's later slices.
- Governing spec: `docs/specs/02-backstitch-core.md` ([SC-4], [SC-10], [SC-11]).
- Promotion baseline identifier: uncommitted worktree diff from `7d85601`
  after applying the [SC-4]/[SC-10]/[SC-11] spec delta and dependency pins in
  `docs/specs/02-backstitch-core.md`, `pyproject.toml`, and `uv.lock`.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior (pre-migration) | Rationale | Spec proposal |
|----------|------------------|--------------------------------|-----------|---------------|
| [SC-4]/[SC-11] `PYTHON_SYNTAX_ERROR` severity | A file the parser cannot parse yields a **warning** ("could not analyze this file"), not an error. Suppressible via **config/exclusion per-file rules** — but **not** via inline `# backstitch: noqa` inside the unparseable file (all-or-nothing recovery means its inline directives were never read). Strict escalation is **`check`-only** via the existing `--warnings-as-errors` / `[check].warnings_as_errors`; `packets` has no such flag, so on `packets` a parse failure simply no longer forces exit 1. No new knob. | `PYTHON_SYNTAX_ERROR` is always error-severity ([SC-11], in `ERROR_SEVERITY_CODES`), non-suppressible, and forces `check`/`packets` exit 1; it fires whenever the running interpreter's `ast` cannot parse the file, including on valid-but-newer target syntax. | A traceability checker reports *coverage* ("couldn't read this file"), not code correctness; version-independent parsing means a parse failure now signals only that the pinned parser could not build a valid tree. It does **not** prove that every malformed Python file will be rejected; tree-sitter can accept some legacy-or-invalid forms that `ast` rejects, and static gates remain the code-validity check. | [SC-4] + [SC-11] delta below. |
| [SC-4] Python structure source | Python structure (owners, doc blocks, statement spans, comments) comes from `tree-sitter-python`, runtime-independent; not bounded by the interpreter Backstitch runs on. | Docstrings via `ast`, comments via `tokenize` — both bound to the running interpreter's grammar. | Backstitch should not own Python grammar nor be limited to the runtime's syntax version — the `markdown-it-py` boundary argument for code. | [SC-4] delta below. |
| [SC-10] proof surfaces | Fixture-backed `tree-sitter` analyzer tests are a required proof surface; anti-mocking forbids mocking the parser. | Required proof surfaces name `ast`-based tests. | The proof surface must track the real parser. | [SC-10] delta below. |

## Proposed Spec Delta

Promotion strategy **A — in-file edits**. Exact anchor text confirmed in the
spec-promotion slice (Task 1); intent fixed here.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/02-backstitch-core.md` | A | [SC-4] (two edits), [SC-10], [SC-11] |

### [SC-4] — two edits

1. In the determinism paragraph (~line 234), **remove** "and syntax errors in
   requested Python files" from the list of deterministic **errors**, and add:
   a Python file the code parser cannot parse is a coverage **warning**
   (`PYTHON_SYNTAX_ERROR`), suppressible and subject to `--warnings-as-errors`,
   not a deterministic error. The remaining deterministic-error list (missing
   roots/files/sections/anchors, unsupported ranges, `path::symbol` misses,
   unreadable files) is unchanged.
2. In the code-backlink paragraph, add that Python structure (owner symbols,
   doc blocks, statement spans, comments) is derived from a runtime-independent
   code parser (`tree-sitter`); backlink extraction tracks the parser's tree,
   not the running interpreter's `ast`, and is not limited to the interpreter's
   syntax version. Mirror the `markdown-it-py` wording: Backstitch keeps a thin
   traceability layer over parser nodes and maintains no Python grammar.

### [SC-11]

Change the issue-code row from
`| PYTHON_SYNTAX_ERROR | error | Python file could not be parsed |`
to **warning**, and **remove `PYTHON_SYNTAX_ERROR` from `ERROR_SEVERITY_CODES`**
in `backstitch/models.py`. Add: an unparseable code file is a coverage warning,
suppressible by config/exclusion per-file rules but **not** by inline noqa in
the file itself (it did not parse); strict enforcement on `check` is via the
existing `--warnings-as-errors` / `[check].warnings_as_errors`, while `packets`
(which has no such flag) simply no longer exits 1 on a parse failure. No new
knob.

### [SC-10]

Add fixture-backed `tree-sitter` analyzer tests (owner spans, doc-block
extraction with exact line numbers, statement spans, comment extraction, error
recovery on malformed input, and the three version-independence fixtures) to
the required proof surfaces, and extend the anti-mocking clause: the parser
boundary is not mocked — tests parse real source.

Spec-promotion also adds this plan to each touched spec's `## Related Plans`.

## The `ParsedModule` seam contract (specified, not "directional")

The seam is one interface the traceability layer consumes; the `tree-sitter`
Python analyzer is its first implementation. Fields and semantics are fixed
here so no local choices leak in:

- **Input:** `parse(source: bytes) -> ParsedModule`. **UTF-8 is validated
  before `tree-sitter` ever sees the file, on every read path — not just
  `parse_python_file`.** `parse_python_file` is guarded by the scan loop's
  `UnicodeDecodeError` → `FILE_UNREADABLE` handling (`resolver.py` ~line 831).
  But the two symbol entry points, `python_symbol_inventory` and
  `python_symbol_spans`, are called **separately** (e.g. inventory for
  `path::symbol` mappings, `resolver.py` ~line 873) and today read UTF-8 while
  catching only `SyntaxError`, **not** `UnicodeDecodeError`
  (`python_refs.py:236`) — a latent crash on a non-UTF-8 `path::symbol` target
  that this migration must **fix, not reproduce**. Contract for all three
  entry points: a non-UTF-8 read yields `FILE_UNREADABLE` (via `parse_python_file`
  / the scan loop) or `None` (`python_symbol_inventory` / `python_symbol_spans`
  catch `UnicodeDecodeError`/`OSError` and return `None`), so a non-UTF-8 `.py`
  stays `FILE_UNREADABLE`/unresolved and **never** becomes `PYTHON_SYNTAX_ERROR`.
  Only validated UTF-8 source, re-encoded to bytes, reaches the parser
  (`tree-sitter` parses bytes). Fixture: a non-UTF-8 `.py` that is also the
  target of a `path::symbol` mapping.
- **Line numbers:** every line in `ParsedModule` is **1-indexed** and derived
  from parser byte offsets through a Backstitch-owned line index, not from the
  binding `Point` accessors. End lines are **inclusive**, matching
  `ast.end_lineno`; map `end_byte - 1` to the last content line so
  `python_symbol_spans` end lines are byte-identical to `ast` — verified by
  fixtures. The implementation must avoid making `Node.start_point` /
  `Node.end_point` load-bearing; the 0.26 binding crashed under repeated
  traversal during the implementation smoke tests.
- **`parse_ok: bool` + `error_line: int | None`:** `parse_ok` is False iff the
  tree has any `ERROR` or `MISSING` node (`root.has_error`). `error_line` is
  the 1-indexed start line of the first such node (used for the
  `PYTHON_SYNTAX_ERROR` warning; when `ast` gave `SyntaxError.lineno`, the
  nearest equivalent is the first error node's line — fixture-pin the chosen
  line so it is stable).
- **`owner_spans`:** ordered `(qualname, start_line, end_line)` for every
  class/function/method, **nested with dotted qualnames**, in source order.
  `owner_symbol` sentinel for module scope is the literal `"module"` (matches
  today).
- **`doc_blocks`:** ordered `(owner_qualname, start_line, text)` — the
  documentation attached to the module and each owner. For Python this is the
  first-statement string literal (below); the field is language-neutral so
  JS/TS/Rust/Java map their doc-comments onto it without reshaping the seam.
- **`comments`:** ordered `(start_line, text)` where `text` is the comment
  body normalized exactly as today (`lstrip("#").strip()`), for every comment
  node.
- **`statement_spans`:** ordered `(start_line, end_line)` for every node that
  is the `ast.stmt` equivalent (mapping in Invariants), for [EXC-5]
  next-statement attachment.
- **On `parse_ok is False`:** `owner_spans`, `doc_blocks`, `comments`,
  `statement_spans` are all empty (all-or-nothing — see Invariants), so
  `parse_python_file` emits only the warning, and `python_symbol_spans` /
  `python_symbol_inventory` return `None` exactly as today.

The traceability layer (`_extract_line_refs`, bracket grammar, noqa, `Spec:`
context classification) consumes `ParsedModule` and is otherwise unchanged.
Building any language dispatch/registry now is out of scope.

## Invariants And Constraints

- **Error recovery is all-or-nothing (decided, not deferred).** `tree-sitter`
  always returns a tree with `ERROR`/`MISSING` nodes on malformed input. To
  stay behavior-preserving, **any `root.has_error` → emit the
  `PYTHON_SYNTAX_ERROR` warning at `error_line` and extract nothing** (no refs,
  no owner spans, no comments); `python_symbol_spans`/`inventory` return
  `None`. Partial extraction from a broken file is explicitly **not** done in
  this migration — it would create refs/edges/symbols `ast` never produced and
  break the golden diff. (Partial recovery is a possible later enhancement,
  its own plan.)
- **Docstring recognition matches `ast` exactly.** A doc block exists only when
  the first statement of a module/class/function body is a **plain string
  literal** — `tree-sitter` node type `string`, a `concatenated_string` of
  plain strings, **or either of those wrapped in one or more
  `parenthesized_expression` nodes** (`ast` normalizes `("doc")` and
  `(("doc"))` to `Constant[str]`, so the analyzer unwraps parentheses to reach
  the inner string) — **excluding** f-strings/interpolated strings and bytes
  literals (matches `ast.Constant`-with-`str`-value at `python_refs.py:205`).
  A leading f-string or `b"…"` is **not** a doc block. Fixture the
  parenthesized-string case.
- **Doc-block value decoding matches `ast`'s string value.** The current code
  uses `str(ast.Constant.value)` (prefix/quotes removed, escapes processed,
  implicit concatenation joined), then `splitlines()` with per-line offset
  `docstring.lineno + offset`. The analyzer must produce the **same logical
  text and the same per-line absolute line numbers**, including the existing
  quirk that an escaped `\n` inside a single-physical-line literal yields
  multiple logical lines at the same base line number. Decoding a *string
  literal* is version-stable (string syntax did not change in 3.12+), so a
  focused literal decoder — or `ast.literal_eval` on the **isolated string
  token text only** (not the file) — is acceptable; the contract is
  byte-identical logical value to `ast`. Fixtures cover raw strings, unicode/
  hex escapes, triple-quoted content, implicit concatenation, and the
  escaped-`\n`-in-one-line case.
- **Statement-span node set for [EXC-5] is grammar-shaped, not a hand list.**
  The intended `ast.stmt` equivalent is every complete Python statement node
  that occupies a body/module child position. The 0.26 binding does not expose
  `_simple_statement` / `_compound_statement` as queryable node kinds, so the
  implementation must derive statements from the real parse tree shape
  (module/block/statement-list children, unwrapping decorated definitions to
  the inner `def`/`class` line) and fixture-pin the statement-kind checklist
  below. Do not replace this with a brittle catch-all over every named node.
  The enumeration is a *checklist* the fixtures must all cover, and it must
  include the two round-2 gaps: **`future_import_statement`** (a `from
  __future__` import) and **`type_alias_statement`** (PEP 695 `type X = …`,
  which this plan's own fixtures exercise) — alongside `expression_statement`,
  `import_statement`/`import_from_statement`, `return`/`assert`/`raise`/`pass`/
  `break`/`continue`/`global`/`nonlocal`/`delete` statements, `assignment`/
  `augmented_assignment`, and the compound statements (`if`/`for`/`while`/
  `with`/`try`/`match`/`function_definition`/`class_definition`/`async`
  variants). **Decorators:** a `decorated_definition` node's statement line is
  the inner `function_definition`/`class_definition` `def`/`class` line,
  **not** the decorator line — matching `ast.FunctionDef.lineno`.
  `_next_statement_span` keeps its semantics (first statement whose start line
  > the comment line); fixtures cover decorated defs, a `__future__` import,
  and a `type` alias, so [EXC-5]/[EXC-9] next-statement noqa containment is
  byte-identical.
- **`tokenize` retires with `ast`.** Comments come from `tree-sitter` comment
  nodes, not `tokenize` (also runtime-locked). No `tokenize` path survives.
- **1-indexed line fidelity is absolute** across owners, doc-block lines,
  comments, statement spans, and the warning line; a single off-by-one
  corrupts the trace graph and every evidence range. Highest-risk invariant;
  dedicated fixtures.
- **Determinism, purity, self-corpus gate, and the llm quarantine hold.**
  Parsing stays pure and byte-stable; `resolve()` purity ([SC-4]) untouched;
  `uv run backstitch check` on Backstitch's own code stays exit 0 / 0 errors /
  0 warnings; the [SC-8]/[SC-10] `llm ∉ sys.modules` quarantine stays green.
- **Pinned, wheel-covered dependency**, matrix-proven with source builds
  disabled (Task 2). A pin without matrix wheel coverage is a blocker.
- **Grammar-lag and validity gaps are bounded, not eliminated.** A construct
  the pinned `tree-sitter-python` predates parses as an `ERROR` node → the
  `PYTHON_SYNTAX_ERROR` **warning**, never a crash. The reverse class also
  exists: tree-sitter may accept a form that Python 3's `ast` rejects (for
  example legacy `except X, Y` syntax). Backstitch is not a syntax validator;
  ruff/mypy/import-time tests remain the gates for code validity.

## Hidden Couplings

- **Severity demotion blast radius (verified).** `PYTHON_SYNTAX_ERROR` is in
  `ERROR_SEVERITY_CODES` (`models.py:60`); demoting it (a) makes it
  **config-suppressible** — suppression gates on `issue.severity == "error"`
  (`exclusions.py:225`) — which is intended, though inline noqa in the
  unparseable file cannot suppress it (all-or-nothing means the file's inline
  directives were never parsed; inline code suppressions come only from a
  parsed module docstring/comments, `resolver.py` ~line 910); (b) drops the
  **`check`** exit 1 it used to force unless `--warnings-as-errors`
  (**check-only**, `cli.py:106`), while **`packets`** has no such flag
  (`cli.py:117`) and simply stops exiting 1 on a parse failure
  (`cli.py:346`) — a coverage gap is not a packet-generation failure; (c) moves
  the self-corpus and **Weft debt** baselines (the Weft test pins an exact
  error set) — both change deliberately and their tests update in the same
  slice; (d) may shift acceptance-probe expectations — audit `tests/acceptance/`
  for any probe asserting `PYTHON_SYNTAX_ERROR` severity or a parse-failure
  exit code.
- **Docstring line offsets vs raw tokens** and **`end_lineno` inclusivity** —
  see Invariants; both are golden-diff-load-bearing.
- **Concurrent `markdown-it-py` migration** edits `models.py`, the
  scan/resolve pipeline, and tests on the same uncommitted tree — see
  Sequencing.

## Design Direction

- **Thin seam, not a framework** — the `ParsedModule` contract above is the
  whole interface. No language detection, registry, or dispatch now (Out Of
  Scope); the seam's only job today is to isolate `tree-sitter` so the
  traceability layer is parser-agnostic, and to be shaped (doc blocks, not
  docstrings) so JS/TS drop in later without reshaping it.
- **Extraction via bounded node walks over the real parse tree shape.** The
  0.26 binding API was smoke-tested, but the implementation avoids query and
  `Point` convenience paths for load-bearing extraction. Node-type coupling is
  concentrated in `code_parser.py`, and fixtures pin the grammar shapes that
  matter to Backstitch.
- **`ParsedPython` and the public function signatures are unchanged;** the seam
  sits below them; callers are untouched.

## Tasks

1. **Spec-promotion slice.** Apply the [SC-4] (two edits) + [SC-10] + [SC-11]
   delta and the `ERROR_SEVERITY_CODES` removal; add this plan to
   `## Related Plans`; record the promotion baseline; verify
   `uv run backstitch check` exit 0. Stop and re-plan if a reviewer wants
   `PYTHON_SYNTAX_ERROR` kept at error severity (that reverses the floor-tension
   resolution).
2. **Add and pin the dependency.** `tree-sitter==<pin>`,
   `tree-sitter-python==<pin>` in `pyproject.toml`; `uv lock`. **Prove
   binary-only install (no source build) across the matrix** — e.g. a CI
   matrix step installing with source builds disabled
   (`UV_NO_BUILD`/`--only-binary`), on 3.11–3.14 × {Linux, macOS, Windows}.
   Record resolved versions and re-verify the query API against the pins.
3. **Implement the analyzer behind the `ParsedModule` seam** (new module, e.g.
   `backstitch/code_parser.py`). TDD against fixtures: owner spans (nested,
   async, methods, **decorated class/function — `python_symbol_spans`
   start/end lines match `ast` with decorators present**), doc-block
   recognition (plain-string only; f-string/bytes excluded; parenthesized
   `("doc")`) and **value decoding** (raw/escaped/concatenated/triple-quoted +
   escaped-`\n`-one-line, byte-identical to `ast`), statement spans (incl.
   decorated defs → `def` line, `__future__` import, `type` alias), comments,
   error recovery (`has_error` → warning + empty), a **non-UTF-8 `.py` that is
   a `path::symbol` target** — if the target is inside `code_roots`, assert
   both scan-side `FILE_UNREADABLE` and `MAPPING_SYMBOL_UNRESOLVED`; if outside,
   assert no crash and `MAPPING_SYMBOL_UNRESOLVED` — never
   `PYTHON_SYNTAX_ERROR`, and line-number fidelity vs a golden set. Version-
   independence fixtures on the **3.11** interpreter: PEP 695 generics, PEP 695
   `type` alias, PEP 701 f-string.
4. **Cut `python_refs.py` to the seam; delete the `ast`/`tokenize` paths.** No
   signature changes. Prove a **byte-identical golden diff** of every
   `CodeRef` / `python_symbol_spans` / `python_symbol_inventory` over the whole
   self-corpus + Weft, pre- vs post-migration, empty except the intended
   `PYTHON_SYNTAX_ERROR` severity change.
5. **Reconcile corpus gates + finalize the 3.11 floor.** Update the
   self-corpus and Weft debt tests and any acceptance probe for the severity
   change; the Weft gate must now **pass on 3.11**. Then finalize
   `requires-python`, classifiers, ruff `target-version`, and the CI matrix on
   top (the `ast`-interim warn/classify machinery is unnecessary — the code
   now parses).
6. **Docs + traceability.** Add a "code structure belongs to `tree-sitter`"
   boundary bullet to `04-backstitch-style-traceability.md` (mirroring the
   `markdown-it-py` one), update the repo map and README dependency notes;
   close the spec/plan/impl/test chain at 0 errors / 0 warnings.

## Testing Guidance

- **Golden-output diff** over self-corpus + Weft (Task 4) is the load-bearing
  behavior-preservation proof; empty except the intended severity change.
- Docstring-decode fixtures: raw strings, unicode/hex escapes, triple-quoted,
  implicit concatenation, escaped-`\n`-in-one-line — all byte-identical to
  `ast`'s value and line offsets.
- Statement-span/decorator fixtures proving [EXC-5] next-statement noqa
  containment is unchanged (the [EXC-9] regression class stays contained).
- Version-independence on 3.11: PEP 695 generics, PEP 695 `type`, PEP 701
  f-string fixtures all parse and yield expected owners/doc blocks.
- Error recovery: malformed fixtures yield the `PYTHON_SYNTAX_ERROR` **warning**
  (never a crash/traceback), and empty extraction.
- Anti-mocking: parser never mocked. Full gates on **3.11 and 3.14**:
  `uv run pytest tests`, `tests/acceptance`, `ruff check/format`, `mypy`,
  `uv run backstitch check` (exit 0 / 0 / 0), self-corpus and Weft gates.

## Rollout And Rollback

Rollout: spec slice → dependency (matrix binary-install proof) → analyzer
behind the seam (tests) → cutover with the golden-diff proof → corpus-gate +
3.11-floor finalization → docs. Each slice independently reviewable.

Rollback: the seam makes rollback surgical — restore an `ast`/`tokenize`
`ParsedModule` implementation (or revert `python_refs.py`) and drop the
dependency; traceability layer and callers untouched. Pre-first-release, no
external consumers.

## Stop Gates

Stop and re-plan if: the golden diff cannot reach empty (and the divergence is
not a documented intended deviation); line-number or docstring-value fidelity
cannot be made exact; the pinned grammar cannot parse Backstitch's own source
or lacks matrix binary wheels; the seam starts growing multi-language
dispatch/registry before a second language is real; or the change requires
editing the same `models.py`/pipeline regions the in-flight `markdown-it-py`
migration is mid-change on (serialize instead — Sequencing).

## Sequencing (pre-release, concurrent migrations)

First-release-shaping, not a change to a released product — getting the
parsing foundation right now is the point. But two foundational parser
migrations are in flight on one uncommitted tree (`markdown-it-py`, another
agent; and this). They overlap in `models.py`, the scan/resolve pipeline, and
tests. **Serialize:** let `markdown-it-py` reach a committed base first, carve
the doctor / json-mode / catalog / release-process / 3.11-floor work into
commits, then start this migration on the clean base, then finalize the CI
matrix. Drafting and reviewing this plan is collision-free and proceeds now.

## Out Of Scope

- Multi-language *dispatch* (detection, per-language registry, a second
  grammar) — deferred until a concrete second language is built; the seam
  accepts one, nothing more is built now.
- Partial extraction from files with parse errors (all-or-nothing here).
- Rewriting the traceability layer (bracket grammar, noqa) — unchanged.
- Semantic/type analysis beyond owner/doc-block/comment/statement extraction.
- Touching Markdown parsing or `markdown-it-py`.
- Incremental/streaming parsing (Backstitch is batch).

## Completion Gate

- Golden-output diff empty over self-corpus + Weft except the intended
  severity change; `ast` and `tokenize` gone from `python_refs.py`; parser
  behind the seam; callers unchanged.
- Backstitch on 3.11 parses PEP 695 + PEP 701 fixtures; Weft gate green on 3.11.
- Dependencies pinned, matrix binary-install proven; `uv sync --locked` clean.
- All gates green on 3.11 and 3.14; self-corpus 0 / 0 / 0.
- Spec/plan/impl/test chain closed; docs updated.
- Independent (codex) adversarial re-review returns "Yes" (below).

## Implementation Verification (2026-07-07)

- Independent Claude review (read-only) found one blocking issue: `elif`
  statement spans were missing and `case_clause` spans were over-emitted,
  which could misattach comment-form noqa. Fixed in `backstitch/code_parser.py`
  and covered by `tests/test_code_parser.py` plus an end-to-end
  `tests/test_python_refs.py` fixture.
- Local AST-parity sweep over `backstitch/*.py` and `tests/test_*.py` reports
  zero statement-span divergences after the fix.
- Python 3.11: `uv run pytest tests -q -m "not live_llm"`, `uv run pytest
  tests/acceptance -q`, `uv run pytest tests/test_weft_corpus_traceability.py
  -q`, `uv run ruff check .`, configured `ruff format --check`, `uv run mypy
  backstitch bin/release.py tests --config-file pyproject.toml`, and `uv run
  backstitch check --repo-root . --format json` all passed. Self-corpus
  summary: 57 sections, 86 mappings, 256 refs, 0 errors, 0 warnings, 39 infos.
- Python 3.14: `uv run --python 3.14 --extra dev pytest tests -q -m "not
  live_llm"` and `uv run --python 3.14 --extra dev backstitch check --repo-root
  . --format json` passed with the same 0-error/0-warning self-corpus summary.
- Binary-only local install proof passed: `uv sync --python 3.11 --locked
  --extra dev --no-build --no-install-project`; editable dev mode was restored
  with `uv sync --python 3.11 --locked --extra dev`.
- CI binary-wheel proof is configured for Python 3.11-3.14 across Linux,
  macOS, and Windows x64/arm64 runner labels. Local execution proves only the
  current macOS arm64 leg; the remaining legs require GitHub Actions.

## Independent Review Incorporation

Codex adversarial round 1 (read the real `python_refs.py`/`models.py`/specs;
verdict **"No"**) — all incorporated:

- **[P1] Error recovery was deferred to implementation.** Fixed: decided in the
  plan — `root.has_error` → warning at `error_line` + extract nothing;
  spans/inventory return `None` (all-or-nothing, behavior-preserving).
- **[P1] Docstring fidelity under-specified.** Fixed: recognition pinned to
  plain string / `concatenated_string` only (f-strings and bytes excluded to
  match `ast.Constant`-str), and a decode contract (byte-identical logical
  value + line offsets to `ast`, incl. the escaped-`\n`-one-line quirk) with
  named fixtures.
- **[P1] Statement-span equivalence imprecise.** Fixed: explicit
  `tree-sitter-python` node set for `ast.stmt`, and decorators resolved to the
  `def`/`class` line (not the decorator), preserving [EXC-5]/[EXC-9].
- **[P1] Severity delta incomplete.** Fixed: the delta now also amends the
  [SC-4] "syntax errors … are deterministic errors" sentence (~line 234),
  states suppressibility explicitly, and uses the **existing**
  `--warnings-as-errors` as strict escalation (no vague future knob); exit-code
  and Weft/acceptance blast radius enumerated in Hidden Couplings.
- **[P2] Seam not a contract.** Fixed: the `ParsedModule` contract section
  fixes input (bytes), ordering, `"module"` sentinel, comment normalization,
  inclusive end rows, warning shape, and parse-error behavior.
- **[P2] PEP 701 unproven.** Fixed: PEP 701 f-string is now an explicit
  version-independence fixture (Task 3 / Testing).
- **[P2] Install proof weak.** Fixed: Task 2 requires a matrix **binary-only**
  install (source builds disabled), not just local `uv lock`.

Plus the JavaScript/TypeScript (2nd) and Rust/Java (3rd) roadmap folded in: the
seam's documentation primitive is a language-neutral **doc block**, not a
docstring, so the Python implementation does not bake in a Python-only model.

Codex adversarial round 2 (read the code again; verdict **"No"**) — deeper,
all incorporated:

- **[P1] `--warnings-as-errors` is `check`-only, not `packets`.** Fixed: the
  severity story no longer claims strict escalation on `packets`; a demoted
  parse failure just stops forcing `packets` exit 1 (stated as intended).
- **[P1] Statement-span set omitted `future_import_statement` /
  `type_alias_statement`** (the latter exercised by this plan's own fixtures).
  Fixed: the set is now defined by body/module child position in
  `tree-sitter-python`'s parse tree (not a drift-prone arbitrary walk), with
  both nodes named and fixtured.
- **[P1] Docstring recognition missed parenthesized strings** (`ast` normalizes
  `("doc")` to `Constant[str]`). Fixed: unwrap `parenthesized_expression` to
  the inner string; fixtured.
- **[P2] Bytes input vs non-UTF-8.** Fixed: UTF-8 is validated before
  `tree-sitter`, so a non-UTF-8 `.py` stays `FILE_UNREADABLE`, never
  `PYTHON_SYNTAX_ERROR`.
- **[P2] Inline-suppressibility overstated.** Fixed: a parse-failure warning is
  suppressible by config/exclusion per-file rules but not by inline noqa in the
  unparseable file (all-or-nothing means its directives were never read).

Codex adversarial round 3 (verdict **"No"** — four of five round-2 fixes
confirmed resolved; one P1 remained). Incorporated:

- **[P1] UTF-8 boundary only covered `parse_python_file`.** The scan calls
  `python_symbol_inventory`/`python_symbol_spans` separately (for `path::symbol`
  mappings), and today they catch only `SyntaxError`, not `UnicodeDecodeError`
  — a latent crash on a non-UTF-8 `path::symbol` target. Fixed: the input
  contract now covers all three read paths (inventory/spans catch
  `UnicodeDecodeError`/`OSError` → `None`), with a fixture; the migration fixes
  the latent bug rather than reproducing it.
- **[P2] decorated-owner fixture for `python_symbol_spans`** (not just statement
  spans) added to Task 3.

Codex adversarial round 4 (verdict **"Yes — the plan is implementable"**). It
verified the round-3 UTF-8 fix against the real code, confirmed the third call
site (`analysis_packets.py:78`, `python_symbol_spans`) is compatible with the
`None` contract (packet generation already falls back to the file head with a
warning), and confirmed `resolver.py:284` already treats a `None` symbol
inventory as `MAPPING_SYMBOL_UNRESOLVED`. The only remaining item was P2
fixture-clarity polish (assert `code_roots`-inside vs -outside behavior for the
non-UTF-8 `path::symbol` target), now folded into Task 3.

Convergence: across four rounds the P1 count fell 4 → 3 → 1 → 0, each round
narrowing from deferred-decisions to specific node types to a single latent
non-UTF-8 read path. The plan is implementable as written; implementation is
gated only on the Sequencing section.
