# Input Validation Invariants: Raise the Review-Round Rules into Spec 02

Status: implemented (promotion slice landed; see Promotion Baseline)
Plan type: spec-authoring with atomic promotion (strategy B)

## Goal

Nineteen independent review rounds on the reconciliation implementation kept
finding the same small set of rules violated one field at a time: partial
record validation, blank strings passing as identifiers, `bool` leaking
through `int` checks, lying summary counts, silently deleted sections. The
implementation now enforces all of them (rounds 8–19, commits `b2c7a94`
through `5672102`), but the spec still states these contracts by example
(JSON shapes) rather than by rule — which is exactly why reviewers had to
rediscover the rule per field.

This plan promotes the recurring rules into a new `[SC-13] Input Validation
Invariants` section of `docs/specs/02-backstitch-core.md`, adds one
sharpening sentence to `[SC-7]`, adds acceptance probe 13 (self-acceptance
round-trip) to `[SC-10]`, and closes the trace graph atomically.

No behavior changes except the enumerated blank-string tightenings in task
2c. Beyond those, the spec is being raised to say what the code already
enforces; any further mismatch discovered during promotion is a deviation
log row and its own explicit fix, not a silent adjustment.

## Source Documents

- `docs/specs/02-backstitch-core.md` — [SC-5], [SC-6], [SC-7], [SC-10],
  [SC-11]
- `docs/specs/04-backstitch-traceability-exclusions.md` — [EXC-4], [EXC-5]
  (cited, not edited)
- Review-round remediation commits `b2c7a94`..`5672102` and their regression
  tests in `tests/test_review_remediation.py`
- `docs/agent-context/runbooks/writing-plans.md` §4b–4d (this plan follows
  the spec-changing-work slice order)

## Spec Baseline

- `5672102` (repo HEAD at plan authoring; last spec-touching commit
  `88b8ba0`) — docs/specs/02-backstitch-core.md,
  docs/specs/03-backstitch-configuration.md,
  docs/specs/04-backstitch-traceability-exclusions.md
- Promotion baseline identifier: `06f8ea3` (the promotion-slice commit)

## Context and Key Files

- `backstitch/artifact_contracts.py` — packet JSONL validators,
  issue-record validation helpers, and deterministic-report validators
- `backstitch/analysis_results.py` — `validate_analysis_row`,
  `render_analysis_summary` count validation
- `backstitch/analysis_llm.py` — `_packet_evidence_bounds`, `_error_record`
- `backstitch/settings.py` — strict config type checks ([CFG-8] enforcement)
- `tests/test_review_remediation.py` — the firing tests for every invariant
  below (rounds 11–19 sections)
- `tests/acceptance/` — probe suite ([SC-10]); gains probe 13

## Invariants and Constraints (for this plan's execution)

- Zero behavior change, with an ENUMERATED set of blank-string tightenings
  (task 2c) that make [SC-13.2] total rather than field-by-field: packet
  `title` non-blank; optional symbol fields (`owners[].symbol`, issue
  `symbol` via the shared `_is_issue_record`, edge `code_symbol`, mapping
  `target_symbol`) and `code_refs[].anchor` non-blank when present;
  `validate_analysis_row` strips `packet_id`. Real producers cannot emit
  blanks in any of these (symbols come from AST names, anchors from
  non-blank titles), so self-acceptance ([SC-13.5], probe 13) and the Weft
  corpus gate guard against over-tightening. Nothing else changes.
- `uv run pytest tests/` (336 tests) must pass unmodified except for the
  new probe and the firing tests for the enumerated tightenings.
- The self-corpus gate stays at zero errors, zero warnings at every commit
  of this plan — which is why strategy B (atomic) is chosen: the new
  section's mapping block and the reciprocal code backlinks land together.
- No new issue codes; [SC-11] is untouched.
- If spec-text drafting reveals the code enforces something *different* from
  what a rule below states, stop, add a Deviation Log row, and resolve it
  explicitly before landing.

## Proposed Spec Delta

Promotion strategy (see `writing-plans.md` §4d — strategy B, atomic):
requirement text, mapping block, reciprocal code backlinks, and probe 13
land in one change, because an [SC-13] mapping block without backlinks would
carry `CODE_BACKLINK_RECIPROCAL_MISSING` warnings between commits.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| docs/specs/02-backstitch-core.md | B — atomic | new [SC-13] after §12; one sentence in [SC-7]; probe 13 in [SC-10]; Related Plans |

### [SC-7] — insert after the paragraph ending "…not an aborted run."

> Evidence in a model result is packet-local in both dimensions: the path
> must have been shown in the packet, and a path carries **line** evidence
> only if line-bounded content was shown for it. Linked tests and owners
> with empty snippets name a path without shown lines; citing any line
> against them is fabricated evidence and invalidates the row.

### [SC-10] — append to the required-probes list

> 13. self-acceptance round-trip: a `check --format json` report of this
>     repository passes `summarize-analysis` validation unchanged (paired
>     with an empty analysis-results file); packets generated from this
>     repository pass `analyze`'s packet loading; and the per-packet error
>     records `analyze` emits for malformed model output pass
>     `validate_analysis_row` — every machine-readable artifact the tool
>     writes survives the tool's own reading

### New section — insert after `## 12. Sibling Target Discovery [SC-12]`, before `## Related Plans`

> ## 13. Input Validation Invariants [SC-13]
>
> Every record backstitch accepts across a trust boundary — packet JSONL
> read by `analyze`, analysis-result JSONL and deterministic reports read by
> `summarize-analysis`, model output, configuration files — is validated
> against the rules below. These are stated as rules, not examples: a
> validator that checks only the fields its own code path consumes does not
> satisfy this section.
>
> - **[SC-13.1] Validation is total over required shape.** An input record
>   is validated against the full record contract of its producer — every
>   required field present, every type exact, every enumerated vocabulary
>   closed (issue codes, severities, classifications, edge kinds, section
>   kinds, mapping kinds, reference contexts) — not against the projection
>   the consumer happens to read. Unknown extra keys are tolerated: the
>   contract closes vocabularies and types, not the key set. (Passthrough
>   paths preserve extras; validating loaders that build typed records
>   need not.)
>   For configuration, key and value-type strictness is [CFG-8]'s rule;
>   suppression-code vocabularies are validated in the CLI and exclusions
>   layer ([EXC-8]).
> - **[SC-13.2] Blank means absent.** An empty or whitespace-only string is
>   never a valid identifier — packet ID, path locator, section ID, symbol,
>   anchor — nor a valid summary or title. Where such a field is required,
>   blank is malformed input; where it is optional, the only way to omit it
>   is `null`, never `""` or `"   "`. A `rationale` discharges the
>   confidence-or-rationale requirement ([SC-7]) only when non-blank;
>   free-text fields (messages, raw reference text, snippets, section text)
>   are type-checked only.
> - **[SC-13.3] Numbers are exact.** `bool` is never accepted where an
>   integer is required. Line numbers are 1-based (`line >= 1`, or `null`
>   where the contract allows no line). Counts are non-negative integers.
>   Confidence is a number in `[0, 1]`.
> - **[SC-13.4] Composite documents are self-consistent.** A packet's
>   `packet_id` equals `spec_path#section_id`. A report's summary counts
>   equal what its own contents tally (issue severities; section, ref, and
>   mapping list lengths). A report's edges reference only sections the
>   report itself contains. Inconsistency is malformed input, not a value
>   judgment left to the consumer.
> - **[SC-13.5] Self-acceptance.** Every machine-readable artifact
>   backstitch emits — deterministic JSON reports, packet JSONL,
>   analysis-result JSONL — passes backstitch's own validation of that
>   artifact type. This bounds [SC-13.1]–[SC-13.4] from both sides:
>   validators must reject forgeries and must accept everything the tool
>   actually produces (probe 13, [SC-10]). Human-facing text output has no
>   validating consumer and is out of scope.
> - **[SC-13.6] Malformed directives are diagnostics.** A suppression or
>   marker directive that does not parse ([EXC-4], [EXC-5]) is an error or
>   warning naming the directive — never a silent no-op, and never silent
>   deletion of the section or content it is attached to.
> - **[SC-13.7] Rejection happens at the input boundary.** Malformed input
>   is rejected before downstream side effects: before model selection and
>   before any model call. Output-write failures are discovered when the
>   write happens and are exit `2` ([SC-5]); they are not required to be
>   pre-checked. Per-packet containment of model failures follows [SC-7].
>
> Severity of a validation failure is [SC-5] exit `2` for invocation inputs
> (packet files, report files, configuration) and a per-row input problem
> for analysis-result rows, consistent with [SC-7].
>
> _Implementation mapping_:
> - `backstitch/artifact_contracts.py`
> - `backstitch/cli.py`
> - `backstitch/analysis_results.py`
> - `backstitch/analysis_llm.py`
> - `backstitch/settings.py`
> - `backstitch/exclusions.py`

### `## Related Plans` — add

> - `docs/plans/2026-07-03-input-validation-invariants-plan.md` (implementing)

## Tasks

1. **Independent review** of this plan and the delta above (different agent
   family; prompt per §8 below). Incorporate or answer every point.
2. **Spec-promotion slice (strategy B, one commit):**
   a. Apply the three [SC-*] edits and the Related Plans line exactly as
      written above (deviations go to the Deviation Log).
   b. Add reciprocal backlinks: one `Spec: docs/specs/02-backstitch-core.md
      [SC-13]` line in the module docstrings of `cli.py`,
      `analysis_results.py`, `analysis_llm.py`, `settings.py`, AND
      `exclusions.py` — every module in the [SC-13] mapping block, so the
      atomic landing carries no reciprocal-backlink debt.
   c. Apply the enumerated blank-string tightenings, each with a firing
      test: `_packet_shape_error` requires non-blank `title`; optional
      symbol fields (`owners[].symbol`, `_is_issue_record`'s `symbol`,
      edge `code_symbol`, mapping `target_symbol`) and `code_refs[].anchor`
      are `null` or non-blank; `validate_analysis_row` rejects
      whitespace-only `packet_id`.
   d. Add probe 13 in `tests/acceptance/` per the [SC-10] text: generate a
      real self-corpus report, assert `summarize-analysis` exit 0 against
      an empty analysis-results file; generate real self-corpus packets,
      assert `artifact_contracts.load_packets` accepts them; feed a garbage
      adapter response through `analyze_packets`, assert the rendered rows
      load with zero errors. (The round-18 negative-control test overlaps;
      keep both — the probe is the acceptance contract, the regression
      test pins the original finding.)
   e. Add an invariant-to-test map comment in
      `tests/test_review_remediation.py`'s module docstring: [SC-13.1] →
      rounds 16/18/19 tests, [SC-13.2] → rounds 12/13/15/19, [SC-13.3] →
      rounds 11/15/18, [SC-13.4] → rounds 12/17, [SC-13.5] → round 14/18 +
      probe 13, [SC-13.6] →
      `test_section_marker_overrides_file_level_ignore`, the round-9/10
      malformed-marker tests
      (`test_malformed_traceability_marker_is_invocation_error`,
      `test_empty_html_ignore_marker_is_rejected` — confirm exact names at
      execution and correct here), and
      `test_unknown_noqa_code_warns_under_allow_unknown`, [SC-13.7] →
      rounds 5/11/12.
   f. Gates: full pytest, acceptance suite, ruff check/format, mypy,
      `git diff --check`, self-corpus 0/0 (default and
      `--show-suppressions`).
   g. Commit; record the promotion baseline identifier in this plan.
3. **Closeout:** update
   `docs/implementation/04-backstitch-style-traceability.md` (boundaries
   section gains "validation is total; validators mirror producers, bounded
   by self-acceptance"); add a `docs/lessons.md` entry: *specs that state
   contracts by example invite validating the visible fields; stating them
   by rule invites a sweep — 19 review rounds compressed to 7 rules*;
   final gate rerun; mark this plan implemented.

## Testing Plan

No new unit tests beyond probe 13 and the docstring map — the firing tests
for every [SC-13.x] already exist in `tests/test_review_remediation.py`
(rounds 11–19) and `tests/test_issue_code_coverage.py`. Task 2d makes that
traceability explicit so [SC-13] never becomes a declared-but-untested
contract ([SC-10] last bullet).

## Verification and Gates

- `uv run pytest tests/` — all pass, including new probe 13
- `uv run pytest tests/acceptance -q`
- `uv run ruff check backstitch tests && uv run ruff format --check backstitch tests`
- `uv run mypy backstitch`
- `uv run backstitch check --repo-root .` — exit 0, zero errors, zero
  warnings (and with `--show-suppressions`)
- `git diff --check`

## Independent Review Loop

- Reviewer: an agent from a different family than the plan author.
- Read: this plan (especially the delta), `docs/specs/02-backstitch-core.md`
  at the baseline, `tests/test_review_remediation.py`, and
  `backstitch/artifact_contracts.py` validators.
- Prompt: "Read the plan at docs/plans/2026-07-03-input-validation-invariants-plan.md
  and its `## Proposed Spec Delta`, including the named promotion strategy.
  Carefully examine the plan, the proposed spec text, and the associated
  code. Look for errors, bad ideas, and latent ambiguities — in particular:
  does any [SC-13.x] rule overstate or understate what the implementation
  enforces? Don't do any implementation, but answer carefully: Could you
  implement this confidently and correctly against the delta as promoted,
  if asked?"
- Feedback handled per §8 of `writing-plans.md`: update, answer, or scope
  out — explicitly.

## Independent Review Round 1 (Codex, 2026-07-03)

Verdict: "could not implement confidently as promoted — delta overclaims
current enforcement." All findings verified against the code before
revising; every one resolved by narrowing the delta or naming the change:

- **P1 blank-string overclaim** (blank `rationale` with confidence
  accepted; packet `title` type-only; blank symbols tolerated) — verified.
  [SC-13.2] narrowed to the enforced field set; rationale scoped to the
  discharging-field case; free-text fields declared type-checked only;
  packet `title` became the plan's single named tightening.
- **P1 full-record overclaim** (extra keys tolerated and preserved;
  `_error_record` carries an `error` key) — verified. [SC-13.1] now states
  extras are tolerated by design: closed vocabularies and types, not a
  closed key set.
- **P1 "every artifact" overclaim** (`config show`, text reports have no
  validating consumer) — [SC-13.5] scoped to the three machine-readable
  artifact types; probe 13 extended to cover packet JSONL round-trip.
- **P2 side-effects wording** (`analyze` discovers unwritable `--output`
  after model calls) — [SC-13.7] reworded to input-boundary rejection;
  output-write failures exit 2 when they occur, no pre-check required.
- **P2 config scope** (suppression-code vocabulary validated in CLI /
  exclusions, not settings) — [SC-13.1] cites [CFG-8]/[EXC-8] split;
  `exclusions.py` added to the mapping.
- **P2 probe 13 underspecified** — probe text now names the empty
  analysis-results pairing.
- **P2 optional-omission rule vs `rationale` default** — null-only rule
  narrowed to optional path/identifier fields.
- **P3 vague [SC-13.6] test map** — task 2e names the tests.

## Independent Review Round 2 (Codex, 2026-07-03)

Verdict: intent implementable, wording not yet — two P1s, two P2s, all
verified and resolved:

- **P1 blank symbols/anchors** ("identifier" still overclaimed: owner
  `symbol`, issue `symbol`, edge `code_symbol`, mapping `target_symbol`,
  `code_refs[].anchor` type-checked only) — resolved by EXPANDING the
  tightening set rather than shrinking the rule: [SC-13.2] now names
  symbols and anchors, and task 2c enumerates the non-blank tightenings
  that make it true. Self-acceptance + Weft gate bound the risk.
- **P1 `exclusions.py` backlink gap** (mapped in [SC-13] but absent from
  task 2b — would land reciprocal-backlink debt) — task 2b now lists all
  five mapped modules.
- **P2 "preserved" overclaim** (`validate_analysis_row` builds a typed
  record, dropping extras) — [SC-13.1] now says tolerated; passthrough
  paths preserve, validating loaders need not.
- **P2 whitespace `packet_id` in standalone `validate_analysis_row`** —
  added to the tightening set (strip check).

## Independent Review Round 3 (Codex, 2026-07-03)

Verdict: **"Yes"** — implementable against the delta as promoted, after
two items:

- **P1 Goal contradiction** ("No runtime behavior changes" vs task 2c
  tightenings) — Goal reworded: no behavior changes *except* the
  enumerated task-2c tightenings.
- **P3 blank `summary`** — confirmed already enforced: round 15 added
  `not summary.strip()` in `validate_analysis_row`, pinned by
  `test_whitespace_only_semantic_summary_is_rejected`. No task needed.
- P2: round-2 resolutions confirmed consistent across invariants, delta,
  and task 2c.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Out of Scope

- No new issue codes and no [SC-11] changes.
- No changes to specs 03/04/05; [EXC-4]/[EXC-5] are cited, not edited.
  Spec 03's type-strictness is already normative via [CFG-8]; [SC-13.3]
  states the general rule and settings.py enforcement is mapped.
- No `--packets` flag for `summarize-analysis` (validation-scope decision
  recorded in round 13; its help text already states the boundary).
- No relitigation of individual round fixes; this plan only names the rules
  they instantiate.
