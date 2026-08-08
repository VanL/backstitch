# Writing Specs

Specs define exact intended behavior. They are the source of truth for
what the system should do now, not a narration of how the current code
happens to work. Program theory (`docs/program-theory.md`) supplies the
conceptual model and design judgment; it does not replace these
contracts, and they do not restate it.

## Theory Boundary

Before specifying behavior that changes a core concept, its owner, a
durable principle, or a non-goal, read `docs/program-theory.md` and
cite the governing account. A spec may refine a theory principle into
observable obligations. It may not silently contradict theory, and
theory may not duplicate the resulting exact behavior — when the two
diverge, revise one or the other explicitly. (In backstitch the theory
itself binds this both ways: its D3 rule is cite-don't-restate against
[SC-16] and the spec tree.)

## Purpose

Use specs to document:

- system behavior and user-visible outcomes
- invariants and boundaries
- interfaces, contracts, and data shapes
- failure modes and edge cases
- verification expectations

Do not use specs for temporary implementation notes or task checklists.

Write specs so a strong zero-context agent can use them reliably, not just so a
human reader finds them reasonable.

Agent-usable spec writing should make these explicit whenever they matter:

- owner
- boundary
- verification
- required action

## File Placement

- Put specs in `docs/specs/`.
- Prefer stable filenames. Numbered prefixes are useful when the directory is a
  long-lived corpus.
- Add a `README.md` in the directory to explain the reading order and naming
  scheme.

## Reference Codes

Specs should use stable reference codes such as `[DOM-1]`, `[API-4]`, or
`[AUTH-2.3]`.

Rules:

- use codes on the requirements people will need to cite later
- prefer stable codes over prose-only references
- extend the existing code family instead of inventing a second style
- update backlinks when a section is split or replaced

## Recommended Spec Sections

### 1. Purpose and Scope

Explain what the spec governs and what it does not.

### 2. Mental Model

Describe the core concepts needed to reason about the system correctly.

### 3. Requirements

State the intended behavior using stable section or requirement codes.

### 4. Invariants and Constraints

Call out what must remain true even as the implementation evolves.

### 5. Interfaces and Data Contracts

Describe public behavior, payloads, state transitions, or file formats as
needed.

### 6. Failure Modes and Edge Cases

State what should happen under conflict, error, unsupported input, timing race,
or partial failure.

### 7. Verification Expectations

Name the evidence required to prove the behavior.

### 8. Related Plans

Link dated plans in `docs/plans/` that implement or materially revise the spec.

### 9. Status and Per-Section Control

Backstitch uses **three** complementary mechanisms for spec-file status and
per-section traceability policy. Do not conflate them.

#### Prose `Status:` header (adoption / authoring)

The `Status:` line at the top of a spec file (e.g. `Status: Proposed`,
`Status: Active`) expresses **whether the spec is adopted for implementation**
— see [SC-2] gating on `05-backstitch-invariants.md` [INV-*]. The
deterministic scanner does **not** read this header in v1.

#### Glob rungs (scanner classification, per-file only)

[SC-3] classifies **whole files** under `spec_roots` via profile globs:

| Rung | Configuration | Shipped code cites the file |
|------|---------------|----------------------------|
| **exploratory** | path matches `exploratory_spec_globs` | `CODE_REF_EXPLORATORY_SPEC` (warning) |
| **planned** | path matches `planned_spec_globs` | `CODE_REF_PLANNED_SPEC` (warning) |
| **active** | neither glob matches | normal graph rules |

**v1 has no per-section planned/exploratory rung** — you cannot mark one
`[SC-*]` paragraph inside `02-backstitch-core.md` as `planned` via globs
without marking the entire file. **Per-section meta/ignore is available**
via inline `_Traceability:` markers ([EXC-4.2] in
`docs/specs/04-backstitch-traceability-exclusions.md`; implemented in
`backstitch/exclusions.py`, keyed by `(file, section_id)`).

Many repos (including backstitch's default profile) ship with **empty** rung
globs — every scanned spec file is **active** until config adds patterns.

#### Inline `_Traceability:` markers ([EXC-4])

Section-scoped markers immediately after a heading or invariant bullet:

```markdown
## 5. Planning Standard [DOM-5]

_Traceability: meta_
```

or

```markdown
_Traceability: ignore SPEC_SECTION_UNMAPPED, CODE_BACKLINK_RECIPROCAL_MISSING_
```

Section markers override file-level preamble markers for that section only
([EXC-4.1]–[EXC-4.2]). HTML comment form is equivalent. `meta` applies the
full [EXC-3] meta classification policy to that section — same suppression
table as a `meta_spec_globs` file match, not a shorthand for one code.

#### Choosing a mechanism

| Situation | Use |
|-----------|-----|
| Whole spec not yet adopted | Prose `Status: Proposed` + governing-spec out-of-scope text; accept info-level `SPEC_SECTION_UNMAPPED`, **`_Traceability: meta_` file preamble** ([EXC-4.1], lighter than editing `meta_spec_globs`), or `meta_spec_globs` in committed config |
| Substantial in-flight behavior in a **new** file | New file path matching `planned_spec_globs` or `exploratory_spec_globs` |
| Paragraph edit inside an existing active file | Promotion strategy A or B in `runbooks/writing-plans.md` §4d — not a glob on the parent file |
| Control one in-flight section's unmapped/backlink debt **without a config change** | Inline `_Traceability: ignore …` or `_Traceability: meta_` on that section ([EXC-4.2]); remove or narrow when the graph is closed in the final slice |

**Owner:** spec/plan author names mechanism and promotion strategy.
**Boundary:** rungs and scanned text require `spec_roots`; `plan_roots` are not
a substitute in v1.
**Verification:** [SC-11] issue codes; self-corpus gate for backstitch work.
**Required action:** promote draft plan text into `docs/specs/` in the
**spec-promotion slice** (see `writing-plans.md` §4d), not only in the plan
appendix.

## Spec Maintenance Rules

- Update the spec before or with the code change when intended behavior shifts.
  For implementation plans, that means **before code that cites the new
  behavior** — usually as the first implementation slice after review, using
  the plan's `## Proposed Spec Delta` and promotion strategy (see
  `runbooks/writing-plans.md` §4c–4d).
- Keep `## Related Plans` current.
- If an implementation note exists for the touched area, update it in the same
  change.
- If no spec exists for material new behavior, add one instead of burying the
  decision in a plan or commit message.
- If a change is intentionally spec-free, make that explicit in the plan.
- If a section is understandable to a human but likely ambiguous to an agent,
  rewrite it with clearer structure, references, examples, or explicit
  boundaries.
- When you notice that kind of ambiguity during work, notify the user and
  suggest a concrete improvement.
- Adding or editing a normative enumerated list (exit codes, issue codes,
  config keys, flag sets, command inventories) lands its executable gate in
  the **same change** — a new or updated firing test, manifest, or checker —
  or names an explicit judgment floor for why the list stays ungated. New
  prose enumerations drift fastest precisely because no existing gate covers
  them yet (see `engineering-principles.md` §12, Enumerable Contracts Get
  Executable Gates — this repo's numbering).
- Writing a gate is not wiring it: every gate names its execution
  path — CI where wired, explicit manual execution otherwise; an
  **unstated** path is the same ungated-convention defect one level
  up. The defect this rule targets is a gate that silently never runs
  anywhere, not the existence of deliberate manual tooling. Wiring
  examples (not the exhaustive set — adapt to the repository's actual
  CI): a test-suite-borne subprocess check invoked portably, or a
  dedicated workflow. A history-dependent gate (one that resolves
  commit SHAs or retrieval cues) must either run on full history or
  detect a shallow clone and skip loudly with a printed reason —
  silently passing and falsely failing on a shallow clone are both
  invalid. (Wording clarified 2026-08-07 by owner direction after the
  taut landing; was: "names its execution path to CI", which read as
  mandating CI for every tool.)

## Anti-Patterns

- specs that only describe current file layout
- vague requirements with no stable references
- prose that sounds clear in discussion but leaves an agent guessing about the
  boundary, owner, or required action
- missing verification guidance for an otherwise clear requirement
- mixing active task checklists into the spec body
- documenting speculative future behavior as if it were required now
- letting the spec drift while code and plans move underneath it
- leaving proposed spec text only in a plan while shipped code cites paths
  under `spec_roots` — file-qualified refs promote `SPEC_SECTION_MISSING`
  (errors); bare known-prefix refs promote `CODE_REF_BARE_UNRESOLVED`
  (warnings); both are invisible to the scanner if the text never lands in
  `docs/specs/`
- parking speculative behavior only in `docs/plans/` when it should be
  **exploratory** under `spec_roots` — the traceability tool cannot report what
  it does not scan
- treating prose `Status: Proposed` as if it were a glob rung — the scanner
  may still classify the file as active
- assigning a planned/exploratory glob to an existing active corpus file just
  to stage one section — rungs are per-file
- promoting rule-form spec text without verifying each rule against what
  the implementation actually enforces — memory-drafted rules overclaim
- adding or editing a normative enumerated list without its executable gate
  in the same change — a fresh enumeration is an ungated contract at birth
