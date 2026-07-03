# Writing Implementation Plans

Plans must be detailed enough that a skilled developer with little or no
repository context can implement them correctly without guesswork.

Write every plan as if the implementer is technically strong but:

- has zero context for the codebase
- knows almost nothing about the local tooling or domain
- will make poor local design choices if the plan leaves room for them
- and tends to choose mock-heavy or shallow verification unless the real proof
  is named

If the plan is ambiguous, assume the implementer will choose the wrong file,
the wrong abstraction, and the wrong test seam.

For risky or boundary-crossing work, the plan is not review-ready or
implementation-ready until it also satisfies the companion runbook:

- `docs/agent-context/runbooks/hardening-plans.md`

Role split:

- this runbook defines the required plan shape, mandatory sections, and minimum
  blockers before implementation
- `hardening-plans.md` defines the rewrite criteria, rationale, and generic
  examples for risky work

## Audience Assumptions

- Strong engineer, limited or zero project context.
- Unfamiliar with repo-specific helper paths unless you point to them.
- Prone to over-abstracting or future-proofing if reuse paths are not explicit.
- Prone to adding weak tests unless the production path is spelled out.
- Will follow the plan literally, including ambiguities.

## Planning Standard

Plans are executable documents, not rough notes.

- Document everything needed to succeed on the first pass:
  source specs, files to touch, files to read first, helpers to reuse,
  invariants to preserve, tests to write, and commands to run.
- State what must not change, not just what should be added.
- Break work into bite-sized, dependency-ordered tasks. Each task should be
  small enough to implement and verify independently.
- Plan for independent review, not just author self-checking.
- Prefer over-prescribing boundaries and load-bearing behavior to leaving room
  for implementer inference.
- Prefer explicit local reuse over invention.
- Apply YAGNI aggressively.
- For risky changes, write rollback and rollout notes early enough to shape the
  task breakdown instead of appending them at the end.
- Required reading should describe the current structure and load-bearing
  behavior, not only name files.
- Prefer red-green TDD when the behavior can be expressed cleanly as a failing
  test first. If not, say why and name the smallest concrete proof that should
  replace it.

If a first draft is structurally complete but still feels easy to implement
wrong, or if the change is risky, use the companion runbook:

- `docs/agent-context/runbooks/hardening-plans.md`

## When Hardening Is Mandatory

Treat `hardening-plans.md` as required input when any of these are true:

- the change introduces async, deferred, queued, or background work
- the same core logic must run in more than one execution context
- a public contract, storage format, CLI shape, or compatibility surface is
  changing
- rollback depends on backward compatibility or rollout order
- the work introduces new persistence, temp-file, or cleanup lifecycle
- the change contains a one-way door or destructive edge

## File Placement

- Put plans in `docs/plans/`.
- Prefer descriptive filenames.
- Use a date prefix for new plans when possible:
  `YYYY-MM-DD-short-name-plan.md`.

## Required Plan Sections

### 1. Goal

One short paragraph on what is changing and why.

### 2. Source Documents

Link the source spec(s) and any existing plan, README, or implementation note
that defines the desired outcome.

Use exact spec files and section identifiers when they exist. Prefer:

```text
Source specs:
- docs/specs/00-some-spec.md [ABC-2], [ABC-4]
- docs/specs/01-another-spec.md [XYZ-1.2]
```

If no spec exists, say so plainly:

```text
Source spec: None — bug fix / refactor / tooling change
```

### 3. Context and Key Files

For the change, list:

- files to modify
- files to read first
- style or guidance docs to consult
- shared helpers or patterns that must be reused
- what the important existing files, entry points, or contracts currently do
- which current class, function, command, route, or module owns the behavior
- which registrations, imports, auth rules, cleanup jobs, or lock semantics are
  load-bearing today when they matter

For complex or risky changes, required reading should not stop at file paths.
Add one or two comprehension questions so the implementer can verify they
understood the load-bearing behavior before editing.

Do not make the implementer infer the file list from later prose.
If the reader could still open the file cold and guess wrong about where or how
to edit, this section is incomplete.

### 4. Invariants and Constraints

Call out what must stay true. At minimum, consider:

- behavior or contract invariants
- boundaries that must not split into parallel paths
- compatibility constraints
- hidden couplings or state that crosses boundaries
- which failures are fatal versus best-effort
- which auxiliary failures must not downgrade a successful core operation
- lifecycle constraints for deferred work, temp files, or queued inputs
- rollback compatibility that must hold during rollout
- one-way doors that need a higher verification or rollout bar
- review gates such as no drive-by refactor, no silent CLI change, or no new
  dependency

State invariants before or alongside the task breakdown, not after it. If the
plan only says what to build and not what must not move, it is not ready.

### 4a. Deviation Log

Every plan that implements against a spec carries a `## Deviation Log`
section, empty at the start, appended to whenever implementation departs
from the recorded baseline (see the decision hierarchy: deviation is
legitimate; undeclared deviation is not). One row per departure:

```markdown
## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
```

The `Spec proposal` column holds the pointer to the spec-revision slice or
proposal that reconciles the deviation, or `pending` — it must not stay
`pending` past the plan's completion gate. An empty deviation log at the end
of a plan is a claim ("we built exactly what the baseline says"), and like
any claim it should survive a spot-check against the diff.

### 4b. Spec Baseline

Every plan that implements against a committed spec records where
implementation started:

```markdown
## Spec Baseline

- `abc123def` — docs/specs/02-backstitch-core.md, docs/specs/03-backstitch-configuration.md
  at plan authoring time
```

Rules:

- use the commit SHA when the spec is committed
- if the plan **revises** the spec, say so explicitly (`Plan type: implementation
  with spec revision`)
- after the **spec-promotion slice** (see §4d), record a **promotion baseline
  identifier** — where the proposed delta was applied to `docs/specs/`.
  Use a commit SHA when that slice is committed; otherwise use diff base plus
  worktree state and the spec file diff (same spirit as the spec baseline).
  Mid-implementation compliance claims are against the promotion baseline, not
  the pre-promotion identifier. Do not require an intermediate commit before
  continuing when the user wants uncommitted review — require a recorded
  identifier and a rerunnable verification gate instead
- spec-authoring-only plans record the baseline they started from and the
  identifier after the spec lands

### 4c. Proposed Spec Delta

When a plan changes intended behavior, include exact proposed spec text for
review — not a summary. The active spec at the baseline SHA remains the
governing contract until promotion; the delta is the **review target** and
**implementation target** after promotion.

```markdown
## Proposed Spec Delta

Promotion strategy (see §4d — pick one):

| Spec file | Strategy | `[REF-*]` sections touched |
|-----------|----------|----------------------------|
| docs/specs/02-backstitch-core.md | A — in-file, active, text without mapping block first | [SC-4] paragraph after … |

### [SC-4] — insert after "MAPPING_BLOCK_OWNERLESS" paragraph

> (exact proposed markdown — replacement or insertion text)
```

Rules:

- inline exact sections when the delta is small; link
  `docs/plans/YYYY-MM-DD-<name>-spec-draft.md` when it is large
- every touched requirement must cite stable `[REF-*]` codes
- name the **promotion strategy** (§4d) — not merely "add to spec"
- **v1 planned/exploratory rungs are per-file, not per-section** (see §4d).
  Per-section meta/ignore is available via [EXC-4] inline markers. Do not mark an
  existing active file as `planned`/`exploratory` via globs just to stage one
  paragraph — that downgrades every section in the file
- clarification-only deltas (behavior already matches code) still belong here
  so reviewers see the exact wording
- do not treat plan-only text as a second governing contract after promotion —
  once promoted, `docs/specs/` is canonical

### 4d. Spec-Changing Work — Slice Order

**Owner:** plan author defines slice order; implementer follows it literally.
**Boundary:** applies when intended behavior in `docs/specs/` changes or new
sections are added under `spec_roots`. **Verification:** each slice names
commands; final gate includes traceability reconciliation (below).
**Required action:** pick a plan type; never implement against plan appendix
text while leaving `docs/specs/` at the baseline SHA.

#### Plan types

| Type | When | First slice |
|------|------|-------------|
| **Implementation** (default) | Behavior decided; code will cite spec paths under `spec_roots` | Spec-promotion slice (strategy §4d), then code |
| **Spec-authoring** | Harvest, clarification, merge — spec is the primary deliverable | Apply delta to `docs/specs/`; no separate "promotion" task |
| **Exploration** | Intended behavior not yet decided | No implementation against a governing spec; spike only. When decided, open a new plan and promote first |

Exploration is not "park the spec in the plan." Once behavior is cited from
shipped code, the text must live under `spec_roots` using a named promotion
strategy (§4d) so traceability tools can see it.

#### Default slice order (implementation with spec revision)

1. **Plan** — baseline, proposed delta (with promotion strategy), invariants,
   tasks, deviation log (empty)
2. **Independent review** — critiques plan **and** proposed delta
3. **Spec-promotion slice** — apply delta to `docs/specs/` per chosen
   strategy; update `## Related Plans`; record promotion baseline identifier
4. **Slices 1…N** — code, tests, implementation docs against **promoted** spec
5. **Deviation handling** — if reality disagrees with promoted text: deviation
   log row, explicit spec edit slice, continue against revised spec
6. **Final slice: Traceability reconciliation** — backlinks, implementation
   doc, lessons/runbooks; close graph debt (see below)

Do **not** make "copy appendix into spec" the **last** slice by default.
Promotion belongs in the **spec-promotion slice** (early, before code cites new
paths) so later tasks are judged against one governing spec.

**Naming:** call this slice **spec-promotion slice**, not "slice 0". In
backstitch work, "slice 0" already means creating the [SC-10] acceptance
probe suite (`AGENTS.md` definition of done).

#### Two status systems (do not conflate)

Backstitch repos may use **both**:

| Mechanism | What it governs | Scanner sees it? |
|-----------|-----------------|------------------|
| **Prose `Status:` header** on a spec file (e.g. `Status: Proposed`) | Human/agent adoption — "do not implement [INV-*] until activated" ([SC-2]) | **No** — unless paired with globs or `meta_spec_globs` |
| **Glob rungs** (`planned_spec_globs`, `exploratory_spec_globs`) | Per-**file** scanner classification ([SC-3]) | **Yes** — `CODE_REF_PLANNED_SPEC` / `CODE_REF_EXPLORATORY_SPEC` warnings |

Example: `docs/specs/05-backstitch-invariants.md` is `Status: Proposed` in
prose but **active** to the scanner when rung globs are empty — hence
`SPEC_SECTION_UNMAPPED` **infos**, not a glob warning. Plans must say which
mechanism they use:

- **Whole-spec not yet adopted** — prose `Status: Proposed` + explicit
  out-of-scope for implementation ([SC-2]); accept info-level unmapped debt,
  **`_Traceability: meta_` file preamble** ([EXC-4.1], lighter than editing
  `meta_spec_globs`), or `meta_spec_globs` if mapping must not be required
- **In-flight product behavior** — glob rung on a **dedicated new file** under
  a configured pattern, one of the in-file strategies below, or per-section
  inline `_Traceability:` markers ([EXC-4.2]) when only one section's debt
  needs control without a config change

#### Status rungs (v1: per-file only for planned/exploratory)

[SC-3] classifies **whole files** via profile globs — not individual
`[REF-*]` sections. Marking `02-backstitch-core.md` as `planned` stages every
section in that file, not one paragraph. **Per-section policy** (meta
classification, ignoring specific issue codes on one section) uses inline
`_Traceability:` markers ([EXC-4.2]) — not rung globs. See
`runbooks/writing-specs.md` §9.

| Rung | Config | Shipped code cites the file |
|------|--------|----------------------------|
| **exploratory** | path matches `exploratory_spec_globs` | `CODE_REF_EXPLORATORY_SPEC` (warning) |
| **planned** | path matches `planned_spec_globs` | `CODE_REF_PLANNED_SPEC` (warning) |
| **active** | neither glob matches | normal graph rules |

Many repos (including backstitch's default profile) have **empty** rung globs —
only **active** exists until config adds patterns. Do not assume
`planned`/`exploratory` are available without naming the glob change in the
plan.

**Why promotion still matters early:** file-qualified refs to a path under
`spec_roots` before the section exists get `SPEC_SECTION_MISSING` (**error**).
Bare `[REF-*]` refs with a known prefix but no matching section get
`CODE_REF_BARE_UNRESOLVED` (**warning**) instead — still debt on a
zero-warning gate, but a different code. Parking draft text only in the plan
does not create a scannable section.

**Note:** file-qualified refs must target paths under `spec_roots`. Paths under
`plan_roots` alone are not resolved as spec citations — do not use
`docs/plans/…` as a stand-in for spec text.

#### Promotion strategies (pick one in the plan)

**A — In-file edit, active file, text first (default for paragraph edits in
repos with empty rung globs):** In the spec-promotion slice, land requirement
text in an existing active spec file **without** an `_Implementation mapping_`
block for the new/changed sections. That yields `SPEC_SECTION_UNMAPPED`
(**info**) only — compatible with a zero-warning self-corpus gate. In a later
slice, add mapping block + code + reciprocal backlink **together**. Slices
between promotion and that mapping slice **must not cite the new sections** —
a code backlink to an unmapped section is
`SPEC_MAPPING_RECIPROCAL_MISSING` (**warning**), the same class of debt the
two-PR trap forbids on `main`.

**Per-section control during the window:** when one new `[REF-*]` section needs
its unmapped or backlink debt classified or suppressed **without** a config
change, place `_Traceability: ignore …` or `_Traceability: meta_` immediately
after that section's heading ([EXC-4.2]). Remove or narrow the marker in the
traceability reconciliation slice. Prefer this over `meta_spec_globs` or glob
rung edits for a single paragraph — see `writing-specs.md` §9.

**B — Atomic:** Land requirement text, mapping block, code, and reciprocal
backlink in **one** change. Promotion and implementation are the same slice;
use when the delta is small or the team prefers a single landing.

**C — New file under a glob rung:** Add a **new** spec file whose path matches
`planned_spec_globs` or `exploratory_spec_globs` (requires config change if
globs are empty). Shipped code may cite it with warning-class debt until
graduation. Use for substantial new behavior, not a paragraph inside an active
corpus file.

**D — Spec-authoring / clarification only:** No code cites new behavior; land
text as **active** (or prose `Status:` update for whole-spec adoption). No
mapping block required unless reciprocity is already claimed.

Do **not** use strategy C's globs to stage a single paragraph inside an
already-active file.

#### Two-PR / stacked-commit trap

Two ordering failures produce warning-class graph debt a zero-warning repo
cannot leave on `main`:

- **Mapping before code:** an active section **with** an `_Implementation
  mapping_` block lands before the reciprocal code backlink →
  `CODE_BACKLINK_RECIPROCAL_MISSING` (**warning**)
- **Code before mapping (strategy A):** promoted-but-unmapped sections cited
  from code before the mapping slice → `SPEC_MAPPING_RECIPROCAL_MISSING`
  (**warning**)

Mitigations (pick one explicitly in the plan):

- **Strategy A** — no mapping block in the spec-promotion slice; **no code
  cites the new sections** until the slice that adds mapping + code +
  reciprocal backlink **together**
- **Strategy B** — atomic land
- **Strategy C** — new file under a planned/exploratory glob (file-level rung)
- **Inline [EXC-4] markers** — per-section `_Traceability: ignore …` or
  `_Traceability: meta_` on the in-flight section when debt on that section
  must be controlled without editing committed profile globs; remove or narrow
  in the final slice
- do **not** mark an existing active corpus file as planned via globs just to
  avoid this trap

#### Graduating glob rungs (heavy — not routine)

Moving a file from planned/exploratory to **active** is not a one-line edit:

- narrowing or removing a glob affects **every** file matching that pattern
- filename-convention rungs (e.g. `*A-*.md`) often require **renaming the
  file**, which breaks path-qualified citations until backlinks are updated

Name graduation steps, citation updates, and verification in the plan.

#### Final slice: traceability reconciliation

The last implementation slice is not "tidy prose." It closes the graph:

- complete mappings and reciprocal backlinks; clear warning-class graph debt
- remove or narrow temporary inline `_Traceability:` markers added for
  in-flight per-section control ([EXC-4.2])
- graduate glob rungs only when strategy C was used and graduation steps are
  named (see above)
- run the project's self-corpus / traceability gate. For **backstitch
  implementation work**, `backstitch check --repo-root .` with **zero errors
  and zero warnings** on the default invocation is **mandatory** for
  completion (`AGENTS.md`, [SC-10]) — not waivable via a "residual-risk
  budget." Residual risk documents blockers or unfinished work; it does not
  redefine done
- update promotion baseline identifier in plan closeout if the spec moved again

### 5. Tasks

Use a numbered, dependency-ordered checklist. Each task should be small enough
to implement and verify independently.

For each task, include:

- outcome
- exact files to touch
- what to read before editing
- helpers or patterns to reuse
- tests to add or update
- stop-and-re-evaluate gates when the implementation starts drifting
- per-task done signal

When relevant, tasks should also say:

- whether the task is introducing a wrapper or the core work
- whether rollback depends on the task remaining backward-compatible
- whether the task touches a one-way door that needs narrower sequencing
- what new evidence would force replanning instead of continuing implementation

Prefer:

```text
2. Update the existing serializer path to emit the new field.
   - Files to touch: src/serializer.py, tests/test_serializer.py
   - Read first: docs/specs/00-api.md [API-3]
   - Reuse the current response builder; do not add a second formatter
   - Verify with the targeted test file
```

Not:

```text
2. Update serialization
```

### 6. Testing Plan

Every plan must say what to test and how.

Include:

- which harness or layer to use
- which test file(s) to update or add
- which commands to run
- what observable behavior should prove the change
- which invariants the tests protect
- what should not be mocked

Bias the testing plan toward contract and behavior:

- public request/response shapes
- durable side effects
- externally visible state transitions
- compatibility behavior

Do not leave the implementer to infer the anti-mocking posture. If a real
dependency must stay real, say so explicitly.

If the plan says only “write tests” without naming what must stay real, what
may be mocked, and which contract the proof protects, the testing plan is
incomplete.

For docs-only changes, say that verification is by inspection and document
quality gates instead of runtime behavior.

### 7. Verification and Gates

List the exact commands to run and what success looks like.

Every plan should distinguish:

- per-task verification
- final gates before claiming completion

For changes that affect runtime behavior, also say:

- how success will be observed after deploy
- what rollout sequencing matters
- what rollback path exists
- what operational signal should confirm the change worked

For risky changes, write the rollback notes before implementation starts. If
you cannot describe rollback or safe rollout cleanly, stop and revise the plan
before coding.

### 8. Independent Review Loop

Every non-trivial plan should say how independent review will happen.

At minimum, include:

- which other agent or agent family should review the plan
- which files and docs the reviewer should read — including **`## Proposed Spec
  Delta`** when the plan changes intended behavior
- the review prompt or review stance
- how feedback will be handed back to the plan author

Recommended prompt:

> Read the plan at [path] and its `## Proposed Spec Delta` (if present).
> Carefully examine the plan, the proposed spec text, and the associated code.
> Look for errors, bad ideas, and latent ambiguities. Don't do any
> implementation, but answer carefully: Could you implement this confidently and
> correctly against the **delta as if promoted** if asked?

The authoring agent must then consider each review point explicitly and either:

- update the plan
- explain why the current path is still the best choice
- or mark the point out of scope with reasoning

If the reviewer says they could not implement the plan confidently and
correctly, treat that as a blocker until the ambiguity is resolved or the
limitation is recorded explicitly.

### 9. Out of Scope

State what is explicitly not changing. This reduces scope creep.

### 10. Fresh-Eyes Review

Before considering the plan complete, re-read it as if you are a new engineer.

Check for:

- missing file paths
- ambiguous phrases like “update the logic”
- unstated invariants
- missing test harness or verification commands
- tasks that are too large to review safely
- hidden assumptions about local style or tooling
- accidental drift away from the requested direction

Fix those gaps and re-read the plan again.

If tightening the plan would require materially changing scope, architecture, or
direction, stop and report that instead of quietly rewriting the task.

## Plan Hardening Checklist

Before treating a plan as review-ready, confirm that it covers these when
relevant:

- invariants named before tasks
- hidden couplings and boundary-crossing state called out
- wrapper logic separated from core work when the same logic spans contexts
- stop-and-re-evaluate gates included for risky tasks
- explicit out-of-scope notes
- anti-mocking guidance
- contract-focused tests
- fatal versus best-effort error-path priorities
- post-deploy success signals
- current-file or current-contract context
- rollout sequencing and rollback
- rollback written early enough to shape the design
- one-way doors
- required reading with comprehension questions

## Blockers Before Implementation

Do not start implementation on risky work if the plan is missing any of these:

- invariants that say what must not change
- enough current-structure context to find the right edit point
- anti-mocking guidance for the important proof
- rollback or rollout notes when order or compatibility matters
- an independent review loop
- deferred-processing lifecycle constraints
- required reading with comprehension questions

For **spec-changing implementation** plans, also do not start **code** slices
until:

- `## Spec Baseline` and `## Proposed Spec Delta` exist
- independent review of the delta has completed
- the **spec-promotion slice** has landed in the worktree (or the plan is typed
  **spec-authoring**, where spec landing is the work)
- promotion baseline **identifier** is recorded (commit SHA or diff base +
  worktree state — not necessarily a commit)
- promotion **strategy** (A/B/C/D) and gate-preservation plan are explicit

For the deeper rationale and examples behind this checklist, see:

- `docs/agent-context/runbooks/hardening-plans.md`

## Backlink Rule

When a plan implements a spec in `docs/specs/`, add a backlink in that spec
under `## Related Plans` or `## Plans`.

When the touched spec already contains nearby implementation notes such as
`_Implementation snapshot_`, `_Implementation status_`, or
`_Implementation mapping_`, update those notes in the same change.

## Anti-Patterns

- “Update the system” without naming the file, path, or invariant involved
- citing only a whole spec document when section codes exist
- assuming the implementer knows local helpers or style rules
- tasks that bundle several unrelated edits into one step
- “add tests” without naming the layer, harness, or regression
- plans that lean on mocks for core behavior
- plans that require independent review but never say who reviews them or how
  feedback is handled
- plans that describe what to build but not what must not change
- plans that omit rollback, rollout, or one-way doors on risky changes
- plans that introduce async or deferred processing without input-lifecycle
  answers
- future-proofing or abstraction decisions left to the implementer
- over-scoping with unrelated cleanup
- spec-changing work without `## Proposed Spec Delta` or promotion baseline
  identifier
- implementing code that cites `spec_roots` before the spec-promotion slice
  lands
- treating plan appendix text as the governing contract after promotion
- assigning a per-**section** rung inside an active file (v1 rungs are
  per-file only)
- editing `meta_spec_globs` or glob rungs to control one in-flight section
  when an inline `_Traceability:` marker ([EXC-4.2]) would suffice
- landing **active** mapped spec sections before reciprocal code when the repo
  enforces a zero-warning self-corpus gate (use strategy A or B instead)
- waiving the backstitch self-corpus gate via a "residual-risk budget"
