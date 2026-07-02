# Backstitch Four-Way Reconciliation Plan

Status: implemented (pending independent review)  
Supersedes (for implementation):  
`docs/plans/2026-06-18-backstitch-style-spec-code-traceability-tool-plan.md` (deterministic + semantic body),  
`docs/plans/2026-07-01-backstitch-toml-configuration-plan.md` (archival),  
`docs/plans/2026-07-02-backstitch-traceability-exclusions-plan.md` (archival)

**Spec baseline (record in every commit message until complete):**  
`1e9c0d9d185c1a2c244f70db8af8c39139fc245c` — `docs/specs/02-backstitch-core.md`, `03`, `04` at Status: Active; `05` at Status: Proposed (**do not implement [INV-*]**).

## Goal

Bring `main` from a stub CLI to a single reconciled implementation that satisfies
the active specs, by **harvesting proven pieces** from four parallel worktrees
without adopting any branch wholesale.

**Spine (deterministic core):** `.worktrees/fable-5/` — `markdown_specs.py`,
`python_refs.py`, `resolver.py` architecture (`scan_repository` + pure
`resolve()`), fixture corpora, and parser/resolver test depth.

**Subsystems to graft (do not re-invent):** `.worktrees/implement-backstitch/` —
`settings.py`, `exclusions.py`, `target_roots.py` (adapt to spec schema; fix
unknown-key strictness).

**Patterns to graft:** `.worktrees/opus-backstitch/` — `grammar.py`,
lazy-`llm` import boundary in `analysis_llm.py` / `cli.py`, subprocess
import-guard tests, fake-`run_prompt` adapter tests.

**Do not use:** `.worktrees/codex-backstitch/` (weakest base). **Do not port**
fable's `toml_config.py`, fable's `filter_report()` suppression keys
(`select` / `ignore` / top-level `per-file-ignores`), fable's **`.md` mapping
token skip** in `markdown_specs.py` (`emit_tokens` drops backticked `.md` —
conflicts with [SC-4] plan-root `MAPPING_PATH_MISSING` semantics), or
implement's `markdown_specs.py` / `resolver.py` cores (anchor bug, thin tests).

Spec **requirements** are read-only during this plan ([decision-hierarchy]):
do not change [SC-*], [CFG-*], or [EXC-*] semantics while implementing. Task 20
may add `## Related Plans` backlinks and archive headers on superseded plans —
that is documentation traceability, not a spec edit. Record behavioral deviations
in `## Deviation Log` below.

## Source Documents

Read in this order before Task 1:

1. `AGENTS.md` — definition of done ([SC-10], commits required)
2. `docs/agent-context/decision-hierarchy.md` — spec SHA, completion gate
3. `docs/agent-context/engineering-principles.md` — §12 enumerable gates, §13 variation vs deficiency
4. `docs/agent-context/runbooks/hardening-plans.md` — **mandatory** (public CLI + config contract)
5. `docs/agent-context/runbooks/writing-plans.md` — task shape
6. `docs/agent-context/runbooks/testing-patterns.md` — Patterns 5–6 (no verbatim message pins)
7. `docs/agent-context/runbooks/adversarial-acceptance-probes.md` — invariant floors
8. `docs/specs/02-backstitch-core.md` — [SC-1]–[SC-12]
9. `docs/specs/03-backstitch-configuration.md` — [CFG-1]–[CFG-10]
10. `docs/specs/04-backstitch-traceability-exclusions.md` — [EXC-1]–[EXC-10]
11. `docs/lessons.md` — Golden Rule 13, 2026-07-01 bake-off section
12. `pyproject.toml` — hatchling, `llm>=0.31`, ruff/mypy/pytest settings

**Worktree reference copies (read-only sources; do not commit worktree paths):**

| Worktree | Path | Use for |
|----------|------|---------|
| fable-5 | `.worktrees/fable-5/` | Parser/resolver/fixtures/tests |
| implement-backstitch | `.worktrees/implement-backstitch/` | settings, exclusions, target_roots |
| opus-backstitch | `.worktrees/opus-backstitch/` | grammar, analysis_llm lazy import, test guards |

**Prerequisite:** `.worktrees/` must exist locally through **Task 21 and
independent review** (not shipped to PyPI). If missing, stop and ask the
maintainer — do not improvise from memory. When copying, use `cp`/`rsync`; never
add `.worktrees/` paths to committed docstrings or comments. Maintainer may
delete worktrees only after closeout.

Comprehension checks (answer in your own words before coding):

1. Why is fable the resolver spine but **not** the config layer?
2. Why must `check` never import `llm`, and how is that proven?
3. Why does self-corpus require **zero warnings**, not only zero errors?
4. What is the difference between `exclude` (skip scan) and
   `lint.per-file-ignores` (suppress findings)?
5. Why must mapping tokens in committed specs use **exact** repo-relative paths?

## Context and Key Files

### Current `main` (starting point)

| Path | Today |
|------|-------|
| `backstitch/cli.py` | Stub: `--version` only, always exit 0 |
| `backstitch/__init__.py` | Version string |
| `tests/` | **Does not exist** |
| `tests/acceptance/` | **Does not exist** |
| `pyproject.toml` | Package metadata; **no** `[tool.backstitch]` yet |

### Target package layout (end state)

| Path | Owner / role |
|------|----------------|
| `backstitch/grammar.py` | Single `SECTION_ID` regex ([SC-4]) — from opus |
| `backstitch/models.py` | Frozen datatypes; `ISSUE_CODES` frozenset = [SC-11] table exactly |
| `backstitch/config.py` | `ProfileConfig` with `meta_spec_globs` — from **implement** (not fable) |
| `backstitch/profiles.py` | Built-in `backstitch-style-v1`; optional `weft_profile()` helper |
| `backstitch/markdown_specs.py` | Spec parser — from fable + traceability markers from implement |
| `backstitch/python_refs.py` | Code parser — from fable, imports `grammar` |
| `backstitch/resolver.py` | `scan_repository()` + `resolve()` — from fable + path ladder + suppression hook |
| `backstitch/reporting.py` | `render_text`, `render_json` only — **no** fable `filter_report` |
| `backstitch/settings.py` | TOML discovery/load — from implement, **fixed** for [CFG-8] |
| `backstitch/exclusions.py` | Suppression engine — from implement |
| `backstitch/target_roots.py` | Weft sibling discovery — from implement |
| `backstitch/cli.py` | All subcommands + config wiring |
| `backstitch/analysis_packets.py` | Packet generation (no llm) |
| `backstitch/analysis_results.py` | JSONL load/summarize |
| `backstitch/analysis_llm.py` | Lazy `llm`; injectable `run_prompt` — from opus |
| `backstitch/prompts/backstitch_style_analysis.md` | Prompt template |

### Code style (non-negotiable)

- Python **3.14+**; stdlib `tomllib` only for config (no new dependencies).
- `from __future__ import annotations` in every module.
- Module docstring cites governing spec section codes.
- **Typed** public functions; `mypy` strict settings in `pyproject.toml`.
- Format with `ruff format`; lint with `ruff check` — do not hand-format.
- **DRY:** one regex in `grammar.py`; one issue-code inventory in `models.ISSUE_CODES`.
- **YAGNI:** no plugin framework, no per-module config tables, no [INV-*] from spec 05.
- Immutable dataclasses (`frozen=True`, `slots=True`) for graph records.

### Testing rules (implementer tends to over-mock — override that)

| Layer | Harness | Mock policy |
|-------|---------|-------------|
| Parsers | Unit tests on **fixture files** on disk | **Never** mock `open`, `ast.parse`, or `tokenize` |
| Resolver | Unit tests calling `resolve()` on parsed records | **Never** mock parsers inside resolver tests |
| CLI | **`subprocess.run([sys.executable, "-m", "backstitch", ...])`** | **Never** mock `argparse` or `main()` |
| `llm` | Inject `run_prompt` callable; subprocess `sys.modules` guard | **Only** fake the model boundary |
| Acceptance | `tests/acceptance/` subprocess probes | Black-box only |

Assert **structured fields** exactly (`code`, `severity`, `path`, `line`,
`section_id`); message text by **substring only** (testing-patterns Pattern 5).

## Invariants and Constraints

These must remain true throughout:

- [SC-4] Deterministic commands (`check`, `packets`) **never** import `llm`.
- [SC-11] Issue codes and default severities match the spec table exactly
  (use `SPEC_MAPPING_RECIPROCAL_MISSING` / `CODE_BACKLINK_RECIPROCAL_MISSING`,
  **not** fable's `CODE_BACKLINK_MISSING`).
- [CFG-8] Unknown config keys → exit `2` by default; `allow_unknown_keys = true`
  is the only escape hatch.
- [CFG-6] Config keys are **snake_case** (`spec_roots`, not `spec-roots`).
- [EXC-*] Suppressions via `exclusions.py`; config keys under `[tool.backstitch.lint]`.
- [EXC-4] Unknown suppression issue codes (config or inline) → exit `2` by
  default; `allow_unknown_keys = true` downgrades to stderr warnings (same hatch
  as [CFG-8]).
- [EXC-3] `process_spec_globs` is a v1 **alias** of `meta_spec_globs` (merged at
  load time); both keys must work in settings and profile overlay.
- [SC-4] Path ladder: exact → `MAPPING_PATH_INEXACT` → `TARGET_PATH_AMBIGUOUS`
  → `MAPPING_PATH_MISSING` (severity predicate for plan `.md`).
- [SC-10] Every [SC-11] code has a firing test; acceptance probes pass;
  self-corpus: exit `0`, **zero errors and zero warnings**, suppressions auditable.
- One bad file → `FILE_UNREADABLE`, scan continues; no traceback to user ever.
- Exit `1` = target findings; exit `2` = invocation/tool failure ([SC-5]).
- Backward compatible: no config file ⇒ same behavior as built-in profile defaults.
- No new dependencies beyond `llm` (already declared).

### Hidden couplings

- `exclude` / `extend_exclude` must apply to **both** spec discovery and code scan.
- `extend` paths resolve relative to the **containing config file's directory**.
- Suppression runs **after** issue emission; suppressed issues must not affect exit codes.
- `meta_spec_globs` must suppress DOM `[DOM-*]` infos without removing DOM from corpus.
- Self-corpus `tests/` in `code_roots` requires **`extend_exclude`** for fixture
  trees — never `exclude = ["tests/fixtures/**"]` alone, because `exclude`
  **replaces** default excludes ([CFG-6.7]) and would stop excluding `.worktrees`.
  Use `extend_exclude = ["tests/fixtures/**", "tests/acceptance/fixtures/**"]`
  under **`[tool.backstitch]`** (top-level config keys per implement's loader —
  **not** under `[tool.backstitch.profile]`; TOML table scope would make it an
  invalid profile key and exit `2` under strict unknown-key handling).
- Git worktree paths (`.worktrees/*`) must not break Weft discovery ([SC-12]).

### Rollback / rollout

- **Rollback:** revert reconciliation commits; `main` returns to stub CLI.
  No migrations (config is opt-in).
- **Rollout:** land in numbered commits per task group; each commit passes
  `ruff`, `mypy`, and `pytest` for completed slices.
- **Post-deploy signal:** `uv run backstitch check --repo-root .` exit `0`
  with zero warnings on CI.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [EXC-*] mapping blocks | Spec 04 shipped without `_Implementation mapping_` blocks | Blocks added to [EXC-1]..[EXC-10] during the Task 17 dogfood burn-down | Documentation traceability (same class as Task 20 backlinks), not a requirements change; without them every module backlink to [EXC-*] warned | none needed |
| [SC-4] ID-less subheadings | Unstated | Deeper ID-less subheadings (`### 6.7` inside `## 6 [CFG-6]`) retain mapping-block ownership; same-or-shallower ones clear it | Real specs put subsections between an ID heading and its mapping block; the dogfood run surfaced the case | done: clarifying paragraph added to [SC-4] in the review remediation (2026-07-02) |
| [SC-5] analyze `--output` | Usage examples always pass `--output` | `--output` optional; results JSONL to stdout by default | Fable's CLI contract and its ported tests; the spec text is an example, not a prohibition | none needed |
| [SC-11] `ref_context` | Initial implementation used a two-way docstring/comment split; every docstring ref (marker or prose) was error-context for ambiguity | Post-review remediation: three-way `asserted`/`docstring`/`comment`; only `Spec:` marker lines assert, so only they take the ambiguity error branch | Independent review caught the spec text (asserted vs prose) being coarser in code than written; Weft gate baseline moved 32 -> 24 errors (eight prose instances downgraded to warnings, same nine pinned signatures) | none needed — implementation now matches the spec as written |
| [SC-4] fence closer length | Initial implementation closed a fence on any run of the same character | Post-review remediation: closer must be the same character AND at least the opener's length (CommonMark) | Independent review caught the gap; the spec already required it | none needed — implementation fix |
| [SC-4] plan-root ladder search | Reviewer asked whether the [SC-4] suffix-search ladder should also search `plan_roots` for bare `.md` tokens | Declined: the ladder searches scan roots only; `plan_roots` stays reserved for classification per [SC-3], and plan-file mapping tokens keep the [SC-11] `.md`-under-plan-root warning semantics | Expanding the search set is a contract change, not a bug; nothing in the corpus needs it. Revisit only if bare plan filenames must resolve | none — separate decision if ever wanted |
| [CFG-3] config discovery above `$HOME` | Reviewer noted walk-to-root can pass `$HOME` | Intentional: [CFG-3] as written allows discovery to the filesystem root | Matches ruff/git behavior; the spec text is deliberate | none needed |

## Tasks

Dependency order is strict. Do not start a task until its prerequisites pass
verification. **Red-green TDD:** write the failing test named in each task
before implementation unless the task says otherwise.

---

### Task 0 — Bootstrap workspace

**Outcome:** Empty test harness and acceptance directory exist; tooling runs.

**Files to create:**

- `tests/__init__.py`
- `tests/conftest.py` — `REPO_ROOT` fixture pointing at repo root
- `tests/acceptance/__init__.py`
- `tests/acceptance/README.md` — pointer: probes implement [SC-10] list
- `tests/test_bootstrap.py` — one trivial test so pytest has a collectable item
  (empty `tests/` makes `pytest --collect-only` exit `5`, which is not success)

**Files to read:** `pyproject.toml`, `docs/agent-context/runbooks/testing-patterns.md`

**Verify:**

```bash
uv sync --extra dev
uv run pytest tests/test_bootstrap.py -q
uv run pytest tests/ --collect-only -q
uv run ruff check backstitch tests
uv run mypy backstitch
```

**Done when:** bootstrap test passes; collect-only exits `0`; ruff/mypy clean on stub package.

---

### Task 1 — Foundation types and grammar

**Outcome:** Shared models and section-ID grammar exist with drift-guard test.

**Files to create:**

- `backstitch/grammar.py` — copy from `.worktrees/opus-backstitch/backstitch/grammar.py`
- `backstitch/models.py` — start from `.worktrees/fable-5/backstitch/models.py`
- `backstitch/config.py` — copy from `.worktrees/implement-backstitch/backstitch/config.py`
  (**not** fable — implement has `meta_spec_globs`; fable lacks it and uses
  `exclude_globs` on the profile, which belongs in `settings` per [CFG-6.7])
- `backstitch/profiles.py` — copy from `.worktrees/fable-5/backstitch/profiles.py`
  but **remove** `exclude_globs` from `BACKSTITCH_STYLE_V1` (defaults + dogfood
  `extend_exclude` handle fixture trees)
- `tests/test_models.py`
- `tests/test_grammar.py`
- `tests/test_config.py` — **create**: `ProfileConfig` exposes `meta_spec_globs`;
  default built-in profile has empty `meta_spec_globs`

**Adapt `models.py`:**

1. Set `ISSUE_CODES` to **exactly** the codes in [SC-11] (add
   `MAPPING_PATH_INEXACT`, `TARGET_PATH_AMBIGUOUS`; rename fable's
   `CODE_BACKLINK_MISSING` → `CODE_BACKLINK_RECIPROCAL_MISSING`; add
   `SPEC_MAPPING_RECIPROCAL_MISSING`; remove codes not in [SC-11]).
2. Add to `CodeRef`: `ref_context: Literal["asserted_backlink", "docstring_prose", "comment"]`.
   `docstring` alone is too coarse — [SC-11] treats only **asserted** backlinks
   (docstring `Spec:` marker) as error context for ambiguity; docstring prose is
   weak like comments. Task 4 populates this in `python_refs.py`; Task 5 uses it
   for severity. **Do not** infer context from raw text in the resolver.
3. Add `ERROR_SEVERITY_CODES: frozenset[str]` containing only codes that are
   **always** error-severity in [SC-11]. **Exclude** context-dependent codes
   (`SPEC_SECTION_AMBIGUOUS`, `MAPPING_PATH_MISSING`): their severity varies per
   instance; `exclusions.py` must gate non-suppressibility via
   `issue.severity == "error"` (and per-code rules), not mere membership in this
   set. `exclusions.py` imports `ISSUE_CODES` and `ERROR_SEVERITY_CODES` from
   `models` only — no second hand-maintained list.

**Tests first (red):**

- `test_issue_codes_match_sc11_table` — parse [SC-11] markdown table or
  maintain explicit expected set; assert `ISSUE_CODES` equals spec set.
- `test_grammar_rejects_task_manager_prose` — `Task`, `Manager` invalid;
  `DOM-4`, `OBS.13.10` valid.

**Verify:** `uv run pytest tests/test_models.py tests/test_grammar.py tests/test_config.py -q`

**Stop gate:** If you add a second regex outside `grammar.py`, stop and merge.

---

### Task 2 — Copy fixture corpora

**Outcome:** Broken and clean mini-repos exist for resolver/CLI proofs.

**Copy tree (preserve structure):**

- `.worktrees/fable-5/tests/fixtures/traceability_project/` → `tests/fixtures/traceability_project/`
- `.worktrees/fable-5/tests/fixtures/clean_project/` → `tests/fixtures/clean_project/`
- `.worktrees/fable-5/tests/fixtures/traceability_project.expected.json` → same path
  (**reference only until Task 19 regenerates it** — it encodes fable's issue
  codes and severities and will **not** pass against the reconciled resolver; do
  not wire it into Task 5 tests)

**Files to read:** fixture `docs/specifications/01-Core.md`, `src/runtime.py` — note
`broad_reader()` for `CODE_REF_BROAD` probe.

**Verify:** fixtures exist on disk; no tests yet.

**Done when:** `find tests/fixtures -type f | wc -l` equals **9** (six files under
`traceability_project/`, two under `clean_project/`, one
`traceability_project.expected.json`).

---

### Task 3 — Markdown spec parser

**Outcome:** `parse_markdown_spec()` passes fable's parser tests + tilde fences.

**Files:**

- Create `backstitch/markdown_specs.py` from `.worktrees/fable-5/backstitch/markdown_specs.py`
- Create `tests/test_markdown_specs.py` from `.worktrees/fable-5/tests/test_markdown_specs.py`

**Adapt:**

1. Replace inline section-ID regex with `from backstitch.grammar import SECTION_ID, ...`.
2. **Defer** implement traceability marker parsing to Task 12 — do not half-port.
3. **Remove fable's `.md` mapping skip** ([SC-4], [P1]): delete the
   `if token.endswith(".md"): continue` branch in `emit_tokens` (~fable
   `markdown_specs.py:117-120`). Classify backticked `.md` tokens as normal
   `path` mappings; the resolver (Task 6) applies `MAPPING_PATH_MISSING`
   warning vs error using the plan-root predicate — do not drop them at parse time.
4. **Replace** fable's `test_directory_callable_and_doc_tokens` assertion that
   `"docs/specifications/01-Core.md" not in dirmap` with tests proving `.md`
   tokens in mapping blocks **are** emitted:
   - `test_md_mapping_token_with_path_is_emitted` — e.g. `docs/specifications/01-Core.md`
   - `test_bare_md_filename_classifies_as_path` — e.g. `2026-05-10-backstitch-plan.md`
     must classify as `kind="path"`, **not** `symbol` (fable's extension allowlist
     omits `.md`, so bare plan filenames wrongly become symbols today)
5. **Fix `classify_mapping_token`:** any token ending in `.md` is a **path**,
   with or without `/` (covers Weft-style bare plan filenames). Do not rely on
   the generic extension regex alone — `.md` must be explicit.
6. **Fence length rule ([SC-4]):** fable stores only the first three fence
   characters, so a ` ````` ` opener can be wrongly closed by ` ``` `. Track
   **fence character** (`\`` vs `~`) **and opener length**; close only when the
   closing line uses the same character and length ≥ opener. **Red test:**
   `test_longer_fence_opener_requires_matching_close_length` (4-backtick opener
   must not close on a 3-backtick line).

**Red-green:** Copy tests first; run → fail (module missing) → port module → pass.

**Must-pass cases:** backtick fences, **tilde fences**, mismatched fence lengths,
Weft inline mapping form, repo-relative and **bare** `.md` mapping tokens emitted
as paths, `MAPPING_BLOCK_OWNERLESS`,
`github_anchor` for `## Alpha Feature [AF-1]` → `#alpha-feature-af-1`.

**Verify:** `uv run pytest tests/test_markdown_specs.py -q`

**Anti-mock:** tests read real `.md` files under `tests/fixtures/`.

---

### Task 4 — Python reference parser

**Outcome:** `parse_python_file()` passes fable parser tests.

**Files:**

- `backstitch/python_refs.py` from fable worktree
- `tests/test_python_refs.py` from fable worktree

**Adapt:**

1. Import `SECTION_ID` from `grammar.py`.
2. Populate `CodeRef.ref_context` ([Task 1]):
   - `"asserted_backlink"` — docstring contains an explicit `Spec:` backlink marker
   - `"docstring_prose"` — docstring bracketed IDs or prose without `Spec:` marker
   - `"comment"` — `#` / tokenize comment refs
   Add parser tests before Task 5 severity tests, including
   `test_docstring_without_spec_marker_is_prose_not_asserted`.

**Defer:** `backstitch: noqa` parsing ([EXC-5]) — fable has none; implement's
collection is in its `python_refs.py` (do-not-port core). Land statement-scoped
noqa in **Task 12** on fable's parser skeleton.

**Verify:** `uv run pytest tests/test_python_refs.py -q`

---

### Task 5 — Resolver core (without config/suppressions)

**Outcome:** Pure `resolve()` + `scan_repository()` emit correct issues on fixtures.

**Files:**

- `backstitch/resolver.py` from `.worktrees/fable-5/backstitch/resolver.py`
- `tests/test_resolver.py` from fable (port tests incrementally)

**Adapt reciprocal issue codes:**

- Rename `CODE_BACKLINK_MISSING` emissions → `CODE_BACKLINK_RECIPROCAL_MISSING`
- Add `SPEC_MAPPING_RECIPROCAL_MISSING` where fable emitted reciprocal mapping issues

**Adapt `SPEC_SECTION_AMBIGUOUS` context-dependent severity ([SC-11]):**

Fable's `_resolve_bare` always emits **warning**. The merged spec requires
**error** when the bare ID appears in an **asserted** backlink (docstring
`Spec:` marker), **spec mapping**, or other asserted context, and **warning** in
comments/prose only.

1. Use `CodeRef.ref_context` from Task 4 — do not infer from raw text.
2. Emit `severity="error"` for `asserted_backlink` and spec-mapping asserted
   contexts; `severity="warning"` for `docstring_prose` and `comment`.
3. **Red tests (one per context)** before changing emission logic:
   - `test_ambiguous_bare_id_in_asserted_backlink_is_error`
   - `test_ambiguous_bare_id_in_docstring_prose_is_warning`
   - `test_ambiguous_bare_id_in_comment_is_warning`
   - `test_ambiguous_bare_id_in_mapping_is_error`

**Adapt `scan_repository` excludes (fable/implement seam):**

Fable's resolver reads `profile.exclude_globs` (~line 656); implement's
`ProfileConfig` has no such field. Replace with an explicit parameter on
`scan_repository(..., exclude_globs: tuple[str, ...] = ())`. Task 8 passes `()`;
Task 12 supplies merged excludes from `settings.exclude`.

**Red-green order:**

1. Port `test_clean_fixture_has_no_errors`
2. Port `test_broad_document_only_ref_warns`
3. Port `test_anchor_ref_resolves_to_id_section_edge` (GitHub anchor probe)
4. Port remaining fable resolver tests

**Verify:** `uv run pytest tests/test_resolver.py -q`

**Stop gate:** If resolver imports `settings` or `exclusions`, remove — wiring is Task 13.

---

### Task 6 — Path resolution ladder [SC-4]

**Outcome:** `MAPPING_PATH_INEXACT` and `TARGET_PATH_AMBIGUOUS` implemented.

**Files to touch:**

- `backstitch/resolver.py` — replace fable's exact-path-only `_resolve_mappings` target resolution
- `backstitch/markdown_specs.py` — only if Task 3 `.md` token work needs fixture
  adjustments; parser must emit `.md` mappings (Task 3), resolver classifies them
- `tests/test_resolver.py` — add tests
- `tests/test_markdown_specs.py` — update `.md` mapping expectations (Task 3)
- `tests/fixtures/path_ladder_project/` — **create** minimal fixture:
  - `docs/specs/Ladder.md` with mappings using shorthand tokens
  - two files sharing a basename in different dirs (ambiguous case)
  - one unique suffix match (inexact warning case)

**Algorithm (no discretion):**

1. Exact repo-relative path exists → resolve silently.
2. Else collect candidate files where path **ends with** token or **basename**
   matches. Search roots: `spec_roots`, `code_roots`, and — for tokens ending in
   `.md` — **`plan_roots`** as well, so bare plan filenames (e.g.
   `2026-05-10-backstitch-plan.md`) can resolve via suffix/basename under
   `docs/plans/`. Document this rule in a code comment; **red test:**
   `test_bare_plan_filename_resolves_under_plan_roots`.
3. 0 candidates → `MAPPING_PATH_MISSING` with severity predicate ([SC-4]):
   **warning** iff token ends in `.md` and path falls under a configured
   `plan_root`; **error** otherwise (including missing `.md` under `spec_roots`).
4. 1 candidate → edge + `MAPPING_PATH_INEXACT` warning naming resolved path.
5. 2+ candidates → `TARGET_PATH_AMBIGUOUS` error, **no edge**.

**Red-green:** Write ladder tests first; they must fail on Task 5 code. Include:

- `test_mapping_path_missing_under_plan_root_is_warning` (requires `.md` mapping
  token emitted by parser — depends on Task 3 `.md` fix)
- `test_mapping_path_missing_under_spec_root_is_error`

**Verify:** `uv run pytest tests/test_resolver.py -k ladder -q`

---

### Task 7 — Reporting layer

**Outcome:** Stable text/JSON rendering.

**Files:**

- `backstitch/reporting.py` from fable **but strip** `filter_report()` entirely
- `tests/test_reporting.py` — create minimal render contract test

**Verify:** render tests pass; `filter_report` does not exist in package.

---

### Task 8 — Minimal CLI `check` (no config file yet)

**Outcome:** Subprocess `backstitch check` runs deterministic scan.

**Files:**

- `backstitch/cli.py` — port command structure from fable `cli.py` (check only first)
- `backstitch/__main__.py` — `from backstitch.cli import main`
- `tests/test_cli.py` — port subprocess tests: clean exit 0, broken exit 1, bad repo exit 2

**Wire:** `check` → `scan_repository` → `render_text`/`render_json`; map severities to exit codes.

**Known fable defects — fix at port time (do not wait for Task 16 probe 11):**

- `check --output` to an unwritable path currently leaks a traceback and exits
  `1`. Wrap file writes; emit `backstitch: error: …` on stderr and exit `2`
  ([SC-5]).
- Add subprocess test `test_check_unwritable_output_exits_two` in this task.

**Verify:**

```bash
uv run pytest tests/test_cli.py -q
uv run backstitch check --repo-root tests/fixtures/clean_project --profile backstitch-style-v1
```

**Anti-mock:** CLI tests use subprocess only.

---

### Task 9 — Settings loader [CFG-*]

**Outcome:** Spec-compliant TOML discovery and strict unknown keys.

**Files:**

- `backstitch/settings.py` from `.worktrees/implement-backstitch/backstitch/settings.py`
- `tests/test_settings.py` from implement worktree
- `tests/fixtures/config_project/` from implement worktree

**Required adaptations (implement diverges from spec):**

1. **Remove** implement's `warn_unused_keys` top-level behavior that downgrades
   unknown keys to stderr warnings. That is **not** the same as
   `lint.warn_unused_ignores` ([EXC-6], Task 10) — do not delete the latter.
2. Implement [CFG-8] `allow_unknown_keys` (default `false`): unknown key in the
   backstitch namespace → raise `ConfigLoadError` (or equivalent) → CLI exit `2`
   naming key and file; when `allow_unknown_keys = true`, warn on stderr and still load.
3. Ensure schema uses **snake_case** keys per [CFG-6] (`spec_roots`, `lint`, etc.).
4. Parse `[packets].output` into settings or remove from `_TABLE_KEYS` — no silent dead schema.
5. Do **not** port fable `toml_config.py`.
6. Reject top-level `profile = "…"` string keys ([CFG-6.1]): the only profile
   name spelling is `[profile].name`. Top-level `profile` is an unknown key.
7. Merge `process_spec_globs` into `meta_spec_globs` at load time ([EXC-3.2] /
   [EXC-6] alias); expose both keys in settings schema.
8. **[CFG-4.3] path expansion order:** expand `~` and `$VAR` / `${VAR}` **first**;
   only then, if still relative, resolve against the config file's directory.
   Implement's `expand_path_value` may already be correct — add an explicit red
   test (`test_expand_tilde_before_relative_base`, `test_expand_absolute_env_without_double_prefix`)
   and fix if the port fails it.
9. **`analyze` discovery anchor ([CFG-3]):** verify `load_settings` uses the
   parent directory of `--packets` (not cwd) when `analyze` runs. Add
   `test_analyze_discovers_config_from_packets_parent`.
10. **`exclude` / `extend_exclude` placement ([CFG-6.7]):** implement's loader
    treats these as **top-level** `[tool.backstitch]` keys (sibling to `[profile]`,
    not inside `[profile]`). Spec §6.7 defines semantics but not table placement —
    follow implement here and record the de-facto placement in
    `docs/implementation/04-backstitch-style-traceability.md` (Task 20). **Do not**
    edit active spec text during this plan; any §6.7 table-placement clarification
    is a separate spec-revision PR after implementation.

**Red-green (write these before the loader passes):**

- `test_unknown_key_exits_two` — unknown top-level key → exit `2`
- `test_top_level_profile_string_exits_two` — `profile = "backstitch-style-v1"`
  at document root → exit `2` naming `profile`
- `test_profile_table_name_loads` — `[profile] name = "backstitch-style-v1"` loads
- `test_process_spec_globs_merged_into_meta` — both globs active after merge

**Verify:** `uv run pytest tests/test_settings.py -q`

**Stop gate:** If unknown keys only warn, stop — that fails acceptance probe 7.

---

### Task 10 — Exclusions engine [EXC-*]

**Outcome:** `should_suppress()` gates issues per spec precedence; unknown
suppression codes fail load like unknown config keys.

**Files:**

- `backstitch/exclusions.py` from implement worktree
- `tests/test_exclusions.py` from implement worktree
- `tests/fixtures/meta_spec_project/` from implement worktree

**Adapt (implement diverges from spec):**

1. **Delete** implement's hand-maintained `KNOWN_ISSUE_CODES` and
   `ERROR_SEVERITY_CODES` lists. Import `ISSUE_CODES` and
   `ERROR_SEVERITY_CODES` from `backstitch.models` only ([DRY]).
2. Replace implement's "unknown issue code → stderr warning" behavior with
   [EXC-4]: unknown suppression code in **config** (`lint.per-file-ignores`,
   `lint.per-section-ignores`) or **inline** markers (`_Traceability: ignore …`,
   `backstitch: noqa …`) → validation error → CLI/config load exit `2`, naming
   code and location.
3. When `allow_unknown_keys = true` ([CFG-8]), unknown suppression codes
   downgrade to stderr warnings and load continues — mirror the config-key hatch.
4. Keep `lint.warn_unused_ignores` as a **separate** stale-ignore warning
   ([EXC-4]) — real codes that match no finding; not the same as unknown codes.
5. Non-suppressibility for context-dependent codes: rely on `issue.severity == "error"`
   at suppression time, not membership in `ERROR_SEVERITY_CODES` alone (see Task 1).

**Red-green (before resolver wiring):**

- precedence tests (`inline` beats `config`)
- `test_unknown_suppression_code_in_config_exits_two`
- `test_unknown_suppression_code_in_inline_marker_exits_two`
- `test_allow_unknown_keys_downgrades_unknown_suppression_code`

**Verify:** `uv run pytest tests/test_exclusions.py -q`

---

### Task 11 — Target roots [SC-12]

**Outcome:** Weft discovery works from `.worktrees/*` checkouts.

**Files:**

- `backstitch/target_roots.py` from implement worktree
- `tests/test_target_roots.py` from implement worktree

**Red-green:** worktree fixture test must fail if naive `parent/weft` used.

**Verify:** `uv run pytest tests/test_target_roots.py -q`

---

### Task 12 — Integrate settings + exclusions into scan pipeline

**Outcome:** `check` uses discovered config; suppressions applied; excludes honored.

**Intra-task order (commit or verify after each slice — avoid one big-bang diff):**

1. **12a — Excludes:** wire `settings.exclude` into `scan_repository(exclude_globs=…)`
2. **12b — Markers:** Markdown `_Traceability:` / HTML comment parsing
3. **12c — Noqa:** Python statement-scoped `noqa` + `tests/test_python_noqa.py`
4. **12d — Suppression:** `build_suppression_index` + `should_suppress` in CLI
5. **12e — Reporting:** `suppressed_issues` on `Report` / JSON render path

**Files to touch:**

- `backstitch/resolver.py` — `scan_repository()` accepts `ProfileConfig` + exclude globs from settings
- `backstitch/markdown_specs.py` — discovery helpers honor excludes
- `backstitch/python_refs.py` — code walk honors excludes
- `backstitch/cli.py` — `_load_settings()` → profile overlay → `scan_repository()` →
  `build_suppression_index()` → `should_suppress()` on each issue **before** exit-code
  and render (match implement's post-scan filter; do not resurrect fable `filter_report`)

**Add traceability marker parsing (from implement):**

- `parse_traceability_marker_line`, `_Traceability: meta`, HTML comments
- Wire into `markdown_specs.py` scan (Task 3 deferred item)

**Python inline `noqa` pipeline ([EXC-5], [EXC-9]) — implement on fable's
`python_refs.py` (not implement's parser):**

Implement's noqa *collection* lives in its `python_refs.py` and bleeds
comment-form directives file-wide ([EXC-9] regression). Do **not** copy that
logic wholesale. Instead:

1. In `python_refs.py`, parse `backstitch: noqa` / `backstitch: ignore`:
   - **Module docstring form** → module-scoped suppression codes
   - **Comment form** → **next statement only** ([EXC-5] v1 rule)
2. Return per-file/module codes **and** per-line `(line → codes)` map for
   statement-scoped comment directives.
3. Feed into `build_suppression_index(inline_code_ignores=…)` in `exclusions.py`.
4. **Red test first** ([EXC-9] scope containment): fixture with **two** findings
   of the same suppressible code in one file, `noqa` on only one statement —
   exactly one finding suppressed. Implement's `test_exclusions.py` does **not**
   cover this; create `tests/fixtures/noqa_scope_project/` + `tests/test_python_noqa.py`.
5. Wire scan path: `scan_repository` passes inline maps from python + spec parsers
   into the suppression index.

**Suppressed findings reporting ([EXC-7]):**

- Extend `Report` / JSON output with optional `suppressed_issues` collection
  (reason: `meta` | `config` | `inline`, plus scope fields).
- Default render omits suppressed findings; `--show-suppressions` includes them
  in text and JSON ([EXC-7]). Task 13 exposes the flag; this task builds the data.

**Profile / meta classification wiring:**

- Overlay `meta_spec_globs` from settings onto `ProfileConfig` (Task 1 field)
- Merge `process_spec_globs` alias the same way implement `cli.py` does
- Pass merged globs into `build_suppression_index()` and section classification

**Red-green:**

- `test_dogfood_config_delta_is_live` pattern from fable self-corpus test
- Config-applied exclude prevents scanning `tests/fixtures/**`

**Verify:** `uv run pytest tests/test_resolver.py tests/test_cli.py -q`

---

### Task 13 — Full CLI surface [SC-5], [CFG-7]

**Outcome:** All commands and config subcommands work.

**Port from fable `cli.py` + implement wiring:**

| Command | Notes |
|---------|-------|
| `check` | `--no-config`, `--config`, `--show-suppressions`, `--warnings-as-errors` / `--no-warnings-as-errors` |
| `packets` | requires `--output`; no llm |
| `analyze` | lazy-import `analysis_llm` in handler only; model precedence via `resolve_model_name` ([SC-5]/[CFG-5]: `--model` → `[analyze].model` → `LLM_MODEL` → llm default) |
| `summarize-analysis` | malformed / key-incomplete JSON → exit 2 (no traceback) |
| `config show` | JSON effective settings; strict unknown-key behavior |
| `config path` | prints discovered path or empty + exit 0 |

**Tests to add/port:**

- `tests/test_cli_config.py` from fable (adapt key names to snake_case tables)
- Exit-2 probes: unwritable `--output`, `--config` + `--no-config` together
- `test_cli_import_and_check_and_packets_do_not_import_llm` from opus pattern

**Verify:** `uv run pytest tests/test_cli.py tests/test_cli_config.py -q`

---

### Task 14 — Analysis pipeline (packets, results, llm)

**Outcome:** Semantic path complete with lazy `llm` boundary.

**Files (port order):**

1. `backstitch/prompts/backstitch_style_analysis.md` — fable or opus
2. `backstitch/analysis_packets.py` — fable
3. `backstitch/analysis_results.py` — fable/opus
4. `backstitch/analysis_llm.py` — **opus pattern** (`make_llm_run_prompt` imports
   `llm` inside function; injectable `run_prompt`) plus **`resolve_model_name`**
   from implement (`analysis_llm.py`) with its five precedence unit tests

**Known fable defects — fix at port time:**

- `summarize-analysis` on structurally valid JSON missing required keys (e.g.
  `{"summary": {}}`) currently raises `KeyError` → traceback, exit `1`. Validate
  required report keys; exit `2` with one-line error ([SC-5], acceptance probe 11).
- Add `test_summarize_analysis_incomplete_json_exits_two` before declaring Task 14 done.

**Tests:**

- `tests/test_analysis_packets.py`
- `tests/test_analysis_results.py`
- `tests/test_analysis_llm.py` — port implement's `resolve_model_name` precedence
  tests + fake adapter + malformed JSON containment + concurrency order

**Red-green:** subprocess llm guard tests before wiring `analyze` command.

**Verify:** `uv run pytest tests/test_analysis_packets.py tests/test_analysis_results.py tests/test_analysis_llm.py -q`

---

### Task 15 — Issue-code contract coverage gate [SC-10]

**Outcome:** Every [SC-11] code has a firing test.

**Files:**

- `tests/test_issue_code_coverage.py` — **create**

**Pattern:**

```python
# For each code in ISSUE_CODES, parametrized test referencing
# the one fixture/test that proves it fires.
```

Harvest mapping from fable `test_resolver.py` + new ladder tests + settings/cli tests.

**Severity gate (not just firing):** context-dependent codes must have tests
proving **both** severity branches where applicable:

- `SPEC_SECTION_AMBIGUOUS` — error (asserted `Spec:` backlink + mapping) and
  warning (docstring prose + comment); Task 5 tests
- `MAPPING_PATH_MISSING` — warning (missing `.md` under `plan_roots`) and error
  (missing path elsewhere); Task 6 tests

A code that fires with the wrong severity fails this task.

**Verify:** `uv run pytest tests/test_issue_code_coverage.py -q` — 100% coverage of `ISSUE_CODES`.

**Stop gate:** Any code with no test fails the task.

---

### Task 16 — Acceptance probe suite [SC-10]

**Outcome:** Twelve probes in `tests/acceptance/` pass via subprocess.

**Files:** create one module per probe group (keep cheap):

| Probe # | File | Assert |
|---------|------|--------|
| 1 | `test_probe_anchors.py` | `#alpha-feature-af-1` resolves |
| 2 | `test_probe_fences.py` | backtick + tilde fences |
| 3 | `test_probe_encoding.py` | non-UTF-8 → `FILE_UNREADABLE`, full report |
| 4 | `test_probe_broad_ref.py` | `CODE_REF_BROAD` fires |
| 5 | `test_probe_duplicate_id.py` | `SPEC_SECTION_DUPLICATE` unreferenced |
| 6 | `test_probe_config_applies.py` | isolated fixture: `.backstitch.toml` changes behavior vs `--no-config`. [SC-10]'s "committed config" wording is additionally covered on this repo in Task 17 (`test_probe_committed_config.py`) |
| 7 | `test_probe_unknown_config_key.py` | unknown key → exit 2 names key |
| 8 | `test_probe_malformed_llm.py` | bad model output contained per packet |
| 9 | `test_probe_concurrency.py` | parallel analyze byte-identical to serial |
| 10 | `test_probe_weft_discovery.py` | worktree-safe sibling discovery |
| 11 | `test_probe_cli_exit_two.py` | bad report JSON, bad packet JSONL, unwritable output |
| 12 | `test_probe_path_ladder.py` | ambiguous + inexact mapping tokens |

Use dedicated tiny fixtures under `tests/acceptance/fixtures/` where possible.

**Verify:** `uv run pytest tests/acceptance/ -q`

---

### Task 17 — Dogfood configuration + self-corpus zero-warning gate

**Outcome:** Default `backstitch check` on this repo exits 0 with no errors **or warnings**.

**Files:**

- `pyproject.toml` — add:

```toml
[tool.backstitch]
# Top-level keys ([CFG-6.7]); NOT under [profile] — TOML table scope would
# make extend_exclude a profile key and fail strict load.
extend_exclude = ["tests/fixtures/**", "tests/acceptance/fixtures/**"]

[tool.backstitch.profile]
name = "backstitch-style-v1"
spec_roots = ["docs/specs"]
plan_roots = ["docs/plans"]
code_roots = ["backstitch", "tests"]
meta_spec_globs = ["docs/specs/01-development-documentation-operating-model.md"]

[tool.backstitch.lint.per-file-ignores]
"tests/*" = ["CODE_REF_UNMAPPED_FROM_SPEC"]
```

**Self-corpus test** must assert `extend_exclude` is live (fixture tree not scanned).

- `tests/test_backstitch_corpus_traceability.py` — port from fable/implement
- `tests/acceptance/test_probe_committed_config.py` — [SC-10] probe 6 on **this
  repo**: `backstitch check --repo-root .` vs `--no-config` must differ
  (dogfood `extend_exclude` / `meta_spec_globs` / lint ignores are live)

**If warnings appear:**

1. Prefer **fixing mapping tokens** to exact repo-relative paths ([SC-10] — do not suppress `MAPPING_PATH_INEXACT`).
2. Use `meta_spec_globs` / `per-section-ignores` only for true process sections.
3. Document every suppression in `docs/implementation/04-backstitch-style-traceability.md`.

**Red-green:** `test_self_corpus_zero_errors_and_warnings` fails until clean.

**Verify:**

```bash
uv run backstitch check --repo-root .
# exit 0; summary shows 0 errors, 0 warnings
uv run backstitch check --repo-root . --show-suppressions  # auditable
uv run pytest tests/test_backstitch_corpus_traceability.py -q
uv run pytest tests/acceptance/test_probe_committed_config.py -q
```

---

### Task 18 — External Weft corpus smoke (optional skip)

**Outcome:** Weft integration test passes when sibling exists.

**Files:** `tests/test_weft_corpus_traceability.py` — **create fresh**; do **not**
port implement's error-count ceiling (`weft_error_count.txt`) or fable's version
that parses values out of message text with ``split("`")`` (Pattern 5 violation).

**Required shape ([SC-10] external-corpus guidance):**

- Pin known debt as structured `(code, path, section_id)` **signatures**
- Pin **exact count** of signatures so new errors *and* silently disappearing
  debt both fail
- Assert on structured JSON fields from `--format json`, never parse rendered messages
- Use `target_roots.discover_weft()` (Task 11), not `REPO_ROOT.parent / "weft"`

Mark `@pytest.mark.integration` or `skipif` when Weft absent.

**Verify:** run when Weft present; otherwise skip documented in test.

---

### Task 19 — Behavior freeze golden (resolver classification changes)

**Outcome:** Full-report golden guards resolver output drift **after reconciliation**.

**Prerequisite:** Tasks 5–6 adaptations are complete. Fable's copied
`traceability_project.expected.json` (Task 2) is **not** the pass target — it
pins fable vocabulary (`CODE_BACKLINK_MISSING`, warning-only ambiguity, no ladder
codes) that this plan intentionally changes.

**Files:**

- `tests/test_behavior_freeze.py` from fable — **adapt** message assertions to
  substring style only (Pattern 5); keep histogram + full JSON golden machinery
- Document regeneration command in the test module (e.g.
  `uv run pytest tests/test_behavior_freeze.py --update-golden` or env var)

**First act (before expecting green):**

1. Run the reconciled resolver on `traceability_project` and **regenerate**
   `traceability_project.expected.json` under the new classification behavior.
2. **Hand-review the diff** between fable's original golden and the regenerated
   file — this diff is the **intentional-changes ledger** for reconciliation.
   Every hunk must trace to a named adaptation (reciprocal code renames, ambiguity
   context severity, path-ladder codes, etc.) or it is an unintended regression.
3. Commit the regenerated golden only after that review.

**Verify:** golden test passes against the **regenerated** file; regeneration
command documented; intentional-changes ledger noted in the Task 21 commit
message or implementation doc.

---

### Task 20 — Documentation and traceability

**Outcome:** Implementation docs and spec backlinks updated.

**Files to create/update:**

- `docs/implementation/04-backstitch-style-traceability.md` — architecture, boundaries, dogfood config, suppression audit
- `docs/implementation/02-repository-map.md` — add new modules
- `docs/specs/02-backstitch-core.md` — `## Related Plans` backlink to this plan
- `docs/specs/03-backstitch-configuration.md` — backlink
- `docs/specs/04-backstitch-traceability-exclusions.md` — backlink
- Archive headers on superseded plans (status: superseded by this plan)
- In `docs/implementation/04-backstitch-style-traceability.md`, document that
  `exclude` / `extend_exclude` are top-level `[tool.backstitch]` keys ([CFG-6.7];
  Task 9 item 10). **Do not edit active spec text in this slice** — spec
  requirements stay read-only per the plan header; a `[CFG-6.7]` table-placement
  clarification belongs in a **separate spec-revision PR** after implementation,
  not bundled into Task 20.

**Verify:** links resolve; `uv run backstitch check --repo-root .` still passes.

---

### Task 21 — Final gates and commit slices

**Outcome:** Definition of done per `AGENTS.md`.

**Commands (all must pass):**

```bash
uv run ruff check backstitch tests
uv run ruff format --check backstitch tests
uv run mypy backstitch
uv run pytest tests/ -q
uv run pytest tests/acceptance/ -q
uv run backstitch check --repo-root .
uv run backstitch check --repo-root . --show-suppressions
```

**Commit discipline:** one commit per task group (0–2, 3–5, 6–8, 9–11, 12–14, 15–17, 18–21) minimum; message cites spec SHA.

**Worktree lifecycle:** `.worktrees/` is required through **Task 21 and the
independent review** in the Independent Review Loop section. Do not delete
worktrees mid-plan — Tasks 2–14 copy sources from them. After review sign-off,
maintainer may remove worktrees; the plan must not depend on them post-closeout.

**Done when:** `git log` shows committed slices; working tree clean.

## Testing Plan

### Harness summary

| Suite | Purpose |
|-------|---------|
| `tests/test_markdown_specs.py` | Parser contracts on fixtures |
| `tests/test_python_refs.py` | Code ref contracts |
| `tests/test_resolver.py` | Graph + issue codes on fixtures |
| `tests/test_settings.py` | Config discovery, extend, strict keys |
| `tests/test_exclusions.py` | Suppression precedence |
| `tests/test_python_noqa.py` | [EXC-9] comment-form noqa scope containment |
| `tests/test_target_roots.py` | Weft discovery |
| `tests/test_cli.py` | Subprocess exit codes |
| `tests/test_cli_config.py` | Config CLI + discovery |
| `tests/test_analysis_*.py` | Semantic pipeline |
| `tests/test_issue_code_coverage.py` | [SC-11] enumeration gate |
| `tests/test_backstitch_corpus_traceability.py` | Self-corpus |
| `tests/acceptance/` | [SC-10] probes |
| `tests/test_behavior_freeze.py` | Golden resolver output |

### What must stay real

- Filesystem fixtures (not in-memory fake Markdown strings unless also checked in as files)
- `subprocess` CLI invocations
- `ast.parse` / `tokenize` in parsers
- `git` worktree layout in target_roots tests (use `tmp_path` with `.worktrees` segment)

### What may be faked

- `run_prompt` callable in `analyze_packets` tests
- `llm` module via `sys.modules` injection **only** in `test_analysis_llm.py`
- Missing Weft repo (skip test)

## Verification and Gates

### Per-task

Run the **Verify** command block at the end of each task before proceeding.

### Final ([DOM-10], [SC-10], AGENTS.md)

| Gate | Command | Success |
|------|---------|---------|
| Lint | `uv run ruff check backstitch tests` | exit 0 |
| Format | `uv run ruff format --check backstitch tests` | exit 0 |
| Types | `uv run mypy backstitch` | exit 0 |
| Unit/integration | `uv run pytest tests/ -q` | all pass |
| Acceptance | `uv run pytest tests/acceptance/ -q` | all pass |
| Self-corpus | `uv run backstitch check --repo-root .` | exit 0, 0 errors, 0 warnings |
| Suppressions audit | `uv run backstitch check --repo-root . --show-suppressions` | every suppression explained in impl doc |
| Issue codes | `uv run pytest tests/test_issue_code_coverage.py -q` | all codes covered |
| Committed | `git status` | clean tree |

### Stop-and-re-evaluate triggers

- Any acceptance probe fails → fix before new features
- Self-corpus warning → fix mapping paths, not broad suppressions
- Unknown config key only warns → settings loader regressed [CFG-8]
- `import llm` during `check` subprocess → boundary violation
- New regex copy for section IDs → DRY violation

## Independent Review Loop

**Reviewer:** agent family different from implementer (e.g. implementer = Grok → reviewer = Claude or Codex).

**Read:** this plan, spec baseline SHA, diff after Task 21.

**Prompt:**

> Read `docs/plans/2026-07-02-backstitch-four-way-reconciliation-plan.md` and the final diff on `main`. You have not seen the worktrees. Could you reproduce this implementation confidently from the plan alone? List errors, ambiguities, and spec mismatches. Do not implement.

**Author response:** address each finding in plan or code; update Deviation Log if intentional.

## Out of Scope

- `docs/specs/05-backstitch-invariants.md` [INV-*] implementation
- Plugin frameworks, non-Python language parsers
- Automatic code/doc fixes
- User-global config (`~/.config/backstitch/`)
- fable `select`/`ignore` top-level config keys
- Porting codex-backstitch code
- Weft product changes
- CI workflow edits (unless required for pytest path)
- Empty `code_roots` / docs-only corpus policy ([CFG-6] open question — blocked on
  agent-guidance partnership; `.backstitch.toml` there depends on the answer)

## Fresh-Eyes Review (plan author)

**Review pass 1 findings (fixed in this revision):**

1. **Ambiguity:** "port from fable" without naming anti-patterns → added explicit do-not-port list and `filter_report` removal.
2. **Error:** implement `warn_unused_keys` ≠ spec → replaced with [CFG-8] `allow_unknown_keys` strict behavior.
3. **Error:** fable `CODE_BACKLINK_MISSING` vs [SC-11] names → explicit rename task in Task 5.
4. **Error:** fable kebab-case config vs [CFG-6] snake_case → documented in Task 9.
5. **Ambiguity:** self-corpus "zero errors" vs "zero warnings" → Task 17 requires both.
6. **Gap:** path ladder missing from fable → dedicated Task 6 before CLI config.
7. **Gap:** chicken-and-egg acceptance dir → Task 0 creates `tests/acceptance/`.
8. **Ambiguity:** traceability markers split across tasks → Task 3 defers, Task 12 lands.
9. **Bad decision avoided:** using fable `toml_config` as config layer — rejected; settings.py is canonical.

**Review pass 2:** Plan is implementable by a zero-context engineer with worktree read access. Remaining risk: implementer copies implement resolver bug — mitigated by "fable resolver only" rule and anchor probe in acceptance. Remaining risk: self-corpus mapping debt — mitigated by zero-warning gate and fix-token-not-suppress rule.

**Review pass 3 (final):** Task dependency order verified: 0→1→2→3→4→5→6→7→8 (check only) →9→10→11→12 (config+suppressions) →13 (full CLI) →14 (analyze) →15→16 (acceptance) →17 (dogfood) →18–21. No material direction change from bake-off consensus (fable core + implement subsystems + opus llm/tests).

**Review pass 4 (independent Agent 1, incorporated):** Fixed implement-copy drift
for unknown suppression codes ([EXC-4]), `meta_spec_globs` / `process_spec_globs`
(Task 1 config from implement), `extend_exclude` dogfood TOML ([CFG-6.7]),
top-level `profile` string rejection ([CFG-6.1]), false pytest/collect-only and
fixture path/count gates, and read-only-spec vs Task-20-backlink clarification.

**Review pass 5 (independent Agent 2, incorporated):** Python noqa pipeline on
fable's `python_refs.py` with [EXC-9] scope containment (Task 12); context-dependent
`SPEC_SECTION_AMBIGUOUS` severity (Task 5 + Task 15); fable crash-path fixes at
port time (Tasks 8/14); Weft signature-count test shape (Task 18);
`resolve_model_name` precedence (Tasks 13/14); [CFG-4.3] expansion order and
`analyze` discovery anchor (Task 9); `suppressed_issues` / [EXC-7] (Task 12);
committed-config probe closure (Task 17); worktree lifecycle (Task 21).

**Review pass 6 (independent Agents 1 & 3, incorporated):** `[tool.backstitch]`
top-level `extend_exclude` TOML (not under `[profile]`); empty Deviation Log
discipline; `CodeRef.ref_context` model change; mapping ambiguity test;
`MAPPING_PATH_MISSING` severity gate; `scan_repository(exclude_globs)` seam (Task 5);
`ERROR_SEVERITY_CODES` always-error-only rule; CFG-6.7 placement in implementation
doc (spec revision out-of-band); Task 12a–12e ordering; Task 17 verify includes
committed-config probe.

**Review pass 7 (independent, incorporated):** Task 2 marks fable
`expected.json` as reference-only; Task 19 regenerates golden first and uses
fable→reconciled diff as intentional-changes ledger (not pass-as-copied).

**Review pass 8 (incorporated):** Task 3 removes fable `.md` mapping skip + fence
length rule; Task 6 ties plan-root `.md` tests to parser fix; `ref_context` split
into `asserted_backlink` / `docstring_prose` / `comment`; Task 20 spec edit
removed (implementation doc only; spec revision is out-of-band); Task 21 adds
`--show-suppressions`.

**Review pass 9 (incorporated):** Task 9 item 10 aligned with read-only spec rule
(no Task 20 spec edit); Task 3 bare `.md` path classification + tests; Task 6
`plan_roots` in suffix/basename lookup for `.md` tokens.

*Author self-review passes 1–3 above are planning notes, not verification evidence
(per decision-hierarchy Completion Gate). Passes 4–9 are independent reviews with
reproduced findings.*

## Related Plans (for spec backlink)

Add to governing specs when implementation starts:

- `docs/plans/2026-07-02-backstitch-four-way-reconciliation-plan.md`