# Lessons Learned

Use this file for durable, project-level lessons that should influence future
sessions.

## When To Add A Lesson

- A correction exposed a repeated failure mode.
- A missing document or runbook caused rework.
- A plan or spec was too ambiguous to execute safely.
- A completed change revealed a stronger general rule than the repo previously
  encoded.

## Golden Rules

Universal principles that inform every change. The dated sections below are the
incident log; these are the durable rules distilled from it.

1. **Canonicalize once, at the boundary.** Normalize data at ingest and write
   boundaries through one shared helper. Never add runtime dual-case fallback
   readers — they hide contract bugs.
2. **Fix forward, never fall back.** Do not add read-time fallback modes to mask
   drift or corruption. Detect invariant violations and surface them; repair
   with forward migrations.
3. **One canonical contract across all consumers.** Same keys, shapes, and
   vocabulary everywhere. Mixed legacy keys cause cascading mismatches.
4. **Validate at write time, fail fast.** Catch errors at the point of creation,
   not in downstream batch gates or runtime checks.
5. **Update all consumers in the same change.** When renaming keys, tightening
   schemas, or changing contracts, update all producers and consumers together.
   Partial renames pass isolated checks but fail at runtime.
6. **Test what you ship.** Add a regression test with each behavior-changing
   fix. Generate fixtures through production code paths, not synthesis.
7. **Plans fail at boundaries, not in the middle.** For risky work, name what
   must not change, hidden couplings, anti-mocking rules, rollout and rollback
   constraints, and post-deploy success signals before implementation starts.
8. **If a document is human-clear but agent-ambiguous, tighten it immediately.**
   Missing owner, boundary, verification path, or required action makes agents
   guess wrong even when the prose feels obvious to a human.
9. **Agents suggest dependencies; humans add them.** An agent must not introduce
   a new dependency on its own — propose it with justification (purpose, why the
   standard library or an already-vendored dependency will not do, the cost of
   taking it on). The human decides whether it enters the manifest.
10. **Flag concerns and calibrate uncertainty, even when you did exactly what
    was asked.** Surface risks noticed in passing; distinguish verified from
    unverified claims with precise language ("I have not confirmed X") rather
    than a vague "this should work"; report blockers with precise causes.
11. **Handle the error path, not just the happy path.** A feature whose success
    path works but whose error, empty, or timeout path is silently ignored is
    incomplete. Name the failure cases in the plan and test at least one. Do not
    paper over an unexpected null or empty — find out why first.
12. **Formatting is owned by the project formatters — run them; do not
    hand-format, and do not reformat incidentally.** Use `ruff format` and `ruff
    check` (configured in `pyproject.toml` under `[tool.ruff]`) plus mypy, and
    let those tools decide style. In a behavior change, keep the diff to the
    lines the task requires and do not let a formatter reflow untouched code.
    Keep formatting-only churn in its own change; if a line changed only because
    "I was in there," revert it.
13. **Enumerable contracts get executable gates.** Any list a document asserts
    — issue codes, exit codes, edge cases, config keys — must be mirrored by a
    machine check that enumerates it (a firing test per element, a no-op
    prevention test per key). Prose binds only what gets checked; agents
    comply uniformly with gates and unevenly with everything else. (Same rule,
    other homes: `docs/agent-context/engineering-principles.md` §12 for the
    durable statement, `runbooks/testing-patterns.md` Pattern 6 for the fix.)
14. **Parser boundaries belong to the parser.** When a mature parser library is
    already a dependency, keep local code as an interpretation layer over its
    tokens. Do not reimplement block-boundary, fence, indentation, or delimiter
    rules in parallel; pin the intentional handoff with tests for the edge cases
    where the old local parser diverged.

## 2026-07-01: Four-Way Implementation Bake-Off

Four agents (Codex, Claude Fable, Grok, Claude Opus) implemented the full tool
from the same baseline in isolated worktrees. All four passed every automated
gate (pytest, ruff, strict mypy); all four diverged on everything not
machine-checked. Durable lessons:

- **Every implementation violated its own declared contract**, not just the
  shared one: spec text broken by its own author, a unit test contradicted by
  its call site, a ledger-identified defect shipped anyway. Deficiency is
  measurable against self-declared intent — gate it there (Golden Rule 13).
- **Self-reports systematically overstate.** A branch whose ledger said
  "ship-ready, whole-branch review PASSED" failed its own advertised default
  invocation. Status documents are claims, not evidence; every completion
  assertion needs a rerun (see decision-hierarchy Completion Gate).
- **Evaluator findings are claims too.** Two independent external reviews of
  the same four implementations contained factual errors (wrong exit-code
  outcomes, missed defects) that only reproduction caught. Reviews of reviews
  need the same evidence bar as reviews of code.
- **Message text must never become API.** One implementation parsed values
  back out of rendered messages, which forced verbatim message pins in tests
  and made wording load-bearing. Structured fields are the contract; messages
  are presentation (testing-patterns Pattern 5).
- **Divergence was productive; deficiency was the failure.** The winners of
  individual dimensions all differed from the overall winner, and the merged
  spec harvested ideas from every branch. Guard invariants, not convergence
  (engineering principle 13).

## Starter Lessons

- Keep canonical agent guidance in shared repo-owned docs and make root agent
  files point to that context instead of carrying divergent copies.
- Non-trivial plans must be executable by a zero-context engineer: exact
  source references, exact files, invariants, verification commands, and a
  fresh-eyes review are required.
- Specs define intended behavior; implementation docs explain why the current
  design exists. Blending those roles causes drift.
- Documentation maintenance is part of the completion gate. If code changes
  without plan/spec/implementation alignment, the work is incomplete.
- Non-trivial plans should be reviewed by an independent agent, and the
  authoring agent should answer each review point by updating the plan or
  documenting why the current path is still the best choice.
- Prefer symlinks from tool-specific root guidance files such as `CLAUDE.md`
  to `AGENTS.md` when the environment supports them; thin pointer files are the
  fallback.
- Optimize docs for agent usability, not just human readability. If something
  is human-clear but agent-ambiguous, call it out and suggest a specific fix.
  Check for missing owner, boundary, verification, or required action.

## Specs: state contracts as rules, not examples (2026-07-03)

Nineteen independent review rounds on the reconciliation implementation
reduced to about seven general rules (now [SC-13]) being rediscovered one
field at a time — because the spec stated its record contracts by example
(JSON shapes), which invites validating only the visible fields. A rule
("all identifiers non-blank, all vocabularies closed, validation total")
invites a sweep. Corollary, proved during promotion: rules drafted from
memory overclaim — three codex review rounds each caught the delta claiming
more than the validators enforced. Verify each codifying rule against the
implementation before promotion, and point reviewers at rule-vs-code.

## Cohesion over file size: floors, not line counts (2026-07-06)

Do not flag or split a file for its size alone — size is not a review
finding. Agents grep and read by offset, so a large well-named module like
`backstitch/resolver.py` (~900 lines, docstring naming its phases and purity
contract) is a pre-joined index; splitting coupled code creates false seams
that breed parallel-implementation drift. What IS a finding, at any size:
an implicit coupling with no marker at the edit point, or a state machine
with no name and no contract test. Structural coupling (flat surface,
shared schema) is safe when marked; behavioral coupling (live state)
justifies extraction only to create the testable boundary. Durable
statement: `docs/agent-context/engineering-principles.md` §14.

## Markdown parsing boundary: delegate structure, test interpretation (2026-07-07)

The old Markdown spec parser spent code and review attention deciding whether a
line was inside a fence or indented code block. That is the wrong ownership
boundary once `markdown-it-py` is already in the project: CommonMark block
structure belongs to the parser, while Backstitch owns only the traceability
syntax layered on parser tokens. The migration lesson is not "use this one
library"; it is "do not keep a shadow parser beside the real parser." Future
parser changes should name the handoff, then add edge fixtures for the exact
legacy divergences before changing behavior.

## Native parser bindings: prefer stable primitives over convenience accessors (2026-07-07)

During the Python `tree-sitter` migration, repeated traversal that asked the
0.26 binding for `Node.start_point` / `Node.end_point` caused native crashes
after earlier parser work had apparently succeeded. The safer boundary is to
treat parser byte offsets as the primitive contract and derive 1-indexed line
numbers through one project-owned line index. Future parser integrations should
smoke-test the binding API under repeated traversal and avoid making
convenience accessors load-bearing when byte offsets can provide the same
information deterministically.
