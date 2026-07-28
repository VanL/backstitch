# Lessons Learned

Startup context is the Golden Rules plus dated sections after the
watermark in `docs/coalescing.md`; the rest of this ledger is
searchable history.

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
information deterministically. Materialize owner/docstring metadata into plain
value records before later traversals; do not retain native nodes as parsed
output or repeatedly query point metadata while walking child collections.

## Role roots must be overridden as a pair (2026-07-10)

When one scan tree contains both production and test code, `test_roots` are a
role classification inside `code_roots`, not a second discovery universe. An
explicit code-root override must therefore reset inherited test roots unless
the caller also supplies them; a lone test-root override can retain inherited
code roots. Dogfood this rule with real declarations and binds. Otherwise a
committed production/test code-root list can appear healthy while every bind is
silently parsed outside test scope as soon as an override changes one side.

## Verify effective requests, not stored model defaults (2026-07-10)

A model manifest can say `temperature 0` while an OpenAI-compatible request
omits temperature and the server applies a different request default. Stored
configuration proves intent, not effective inference behavior. A release gate
that depends on deterministic model behavior must inspect the bytes forwarded
to the serving endpoint and assert each load-bearing control there. Keep those
controls at a test-owned transport boundary when production provider behavior
must remain neutral.

## Retagging needs a fresh compare-and-swap boundary (2026-07-10)

An unpublished tag observed before long release checks is stale state by the
time mutation begins. Push the reviewed branch first, then recheck publication,
active release workflows, and the remote tag. Delete only with a force-with-
lease tied to that fresh tag SHA. Once PyPI accepts an artifact, retag rollback
is no longer valid; the only safe path is a new fix-forward version.

## Fixed sampling inputs do not guarantee cross-hardware model output (2026-07-10)

Temperature zero and a fixed seed make the request explicit, but quantized
inference can still choose different near-tie tokens across ARM and x86 kernels.
A small-model CI gate must not depend on lucky formatting from one machine.
Constrain the output properties the deterministic validator already requires
at a test-owned serving boundary, then leave the ordinary parser as final
authority. If a server enforces schemas only for nonstreaming requests, bridge
that response back to the unchanged streaming client without repairing the
assistant content. Transport control, decoder control, and semantic validation
are three distinct proofs.

## Give semantic models closed evidence coordinates (2026-07-15)

A probabilistic model should select trusted evidence, not reconstruct source
coordinates. Derive exact end lines locally, expose a closed list of allowed
regions, and require the response to copy one of those regions verbatim. Remove
fully contained duplicate regions before inference so one returned span cannot
match two allowed choices. Provider schemas can guide generation, but the local
normalizer remains authoritative unless strict enforcement has been proved at
the transport boundary.

## Repository policy and eval-fixture policy are separate scopes (2026-07-15)

An isolated semantic-eval fixture inherits request, evidence, cache, and budget
controls from repository configuration. It must not inherit full-repository
inventory floors or human disposition requirements. Those controls describe a
different corpus and can make a valid fixture fail before inference begins.
Neutralize them explicitly in the eval projection, then test the effective
settings rather than trusting the source configuration.

## Cached model and revision form one identity pair (2026-07-15)

An environment model override cannot safely replace only the configured model
while retaining its declared revision. That creates a false cache identity and
can send unsupported parameters to a different provider model. In cached modes,
reject a model override that disagrees with a nonblank configured model unless
configuration declares the matching model and revision together.

## Pin actions before a workflow receives a secret (2026-07-15)

A manual-only workflow is still a secret-bearing supply-chain boundary.
Mutable major tags on checkout or tool-setup actions can run before the trusted
command and exfiltrate a job-scoped credential. Pin every third-party action in
that workflow to an exact reviewed commit, and expose the secret only on the
small set of steps that validate or consume it. Trigger restrictions and
read-only repository permissions do not replace either control.

## Manual dispatch is branch-selectable (2026-07-15)

Checking out `main` does not make a `workflow_dispatch` run main-only. GitHub
selects the workflow definition before checkout, and a manual dispatch can
target another ref. For a repository-secret workflow that must use only the
default-branch definition, use an event whose documented `GITHUB_REF` and
`GITHUB_SHA` are the default branch, such as a typed `repository_dispatch`.
If branch-selectable dispatch is required, move the credential to a protected
environment secret restricted to the trusted branch.

## A recorded digest does not bind an artifact to its source (2026-07-15)

Cross-row consistency can prove that every trial repeats the same claimed
manifest facts, but it cannot prove those facts came from the manifest named by
a digest string inside the artifact. Promotion-grade validation must read the
authoritative source, verify its bytes against the digest, and compare every
source-owned field. Keep manifest-free validation explicitly scoped to
internal consistency so callers cannot mistake coherence for provenance.

## Expected labels must not be projections of the system under test (2026-07-16)

A content-addressed evaluation can still be tautological. If frozen production
output defines the complete gold set or supplies the expected classification,
candidate capture and precision cannot fail without first making the observation
malformed. Keep the production artifact as the observation under test. Bind
independently reviewed gold to source-derived identities and allow eligible
source candidates that output omitted to remain in the denominator. Mutation
tests should make each quality metric fail through a valid observation, not
launder product errors into `INVALID_OBSERVATION`.

## Proof observations are not an interaction-cost log (2026-07-16)

A minimal set of byte-bound outputs can prove a task outcome while omitting the
summary, discovery, detail, pagination, or check calls that the participant
needed to reach it. Do not infer authoring cost from proof artifacts. Record a
complete ordered log of the allowed task-scoped product calls, recompute the
count from that log, bind each entry to the source revision in force, and
require every proof observation to occur in the log. Keep unproved auxiliary
outputs out of the qualification evidence boundary.

## A path-only trace names one source owner, not every parser node (2026-07-16)

A whole-file mapping can be complete reciprocal evidence without declaring
every definition and reference inside that file. Candidate discovery must seed
the exact module owner for a path-only Python declaration. Treating every AST
node in the file as declared both overstates human authority and explodes the
counterevidence closure. Keep source-owner identity separate from the static
graph nodes used to find nearby advice.

## Parse once per snapshot, derive separately per obligation (2026-07-16)

Repository-wide candidate discovery has a large obligation-independent parse
and static-resolution phase. Rebuilding it for each obligation makes runtime
roughly proportional to obligations times repository size and cannot satisfy a
scale gate. Prepare one snapshot-bound catalog, then clone only mutable
obligation derivation state. Preserve deterministic work accounting as if the
catalog were read for each addressed operation; a cache must improve execution
without changing budget truth or leaking trace state between obligations.

## Structured-output support must be proved at the wire and normalization layers (2026-07-16)

A wrapper may advertise an option name that the selected provider model no
longer accepts, and a local server may accept a JSON Schema request yet return
non-JSON text. Resolve the exact wire parameter before traffic, retain the
logical request identity and output ceiling, inspect the forwarded schema in a
live contract test, and still run the closed local normalizer. Transport
acceptance is not semantic or syntactic conformance.

## Authority preflight and execution must share the same resolved input (2026-07-16)

A CLI can correctly reject unqualified failure authority before repository or
provider work, yet the shared runner can still make the qualified path
impossible if it repeats the check without the resolved qualification settings.
Pass the complete authority input through the request boundary and fire a test
at the shared runner, not only at the CLI preflight. Preserve the structured
problem details at the outer error boundary; a line-safe message alone is not
enough to diagnose selector, digest, derivation, and composition mismatches.

## Run the exact CI scope before closure (2026-07-16)

Focused type, lint, and format checks can all pass while the release command
still fails on newly added test modules or frozen adversarial fixture trees.
Before closure, run the exact CI command over its full configured paths. Keep
frozen fixture bytes outside the package's lint, format, and type surfaces;
their manifests and drift tests are the correct validators. Fix real test-code
typing defects with precise annotations and casts instead of broad file
exclusions or blanket ignores.
