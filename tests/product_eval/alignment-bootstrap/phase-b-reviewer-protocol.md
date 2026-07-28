# Alignment bootstrap Phase B reviewer protocol

Status: preregistered evaluation protocol. It is not runtime alignment state.

## Inputs and access

The owner gives each participant only the installed public help, `backstitch
guide alignment`, the installed repository skill, and the assigned fixture.
Participants must not read product implementation source, fixture manifests,
full gold labels, or another participant's record. Each participant is a
distinct human or agent identity and sets `public_help_only = true`.

For each fixture the owner also supplies the exact Unicode-sorted candidate IDs
whose frozen human disposition is `accepted`. This accepted projection is an
input to the trace-authoring exercise, not a participant answer and not a
Backstitch verdict. No rejected, irrelevant, critical, or expected-trace-state
labels are revealed.

The result binds the Phase B qualification digest. That digest covers only the
Phase B fixture manifest, this protocol, Phase B session count, critical set and
thresholds, and the common tested distribution, guide, and skill identities.

## Fixed tasks and timing

The owner releases fixtures to a participant one at a time in frozen fixture
order. The participant cannot inspect a later fixture before its task timer
starts. Public help, the installed guide, and the repository skill may be
inspected before the first task and are not charged to a task.

Prompt: "Use Backstitch's public interface to find plausible evidence for
`docs/specs/01-core.md#CAND-1` and report every surfaced candidate and its trace
state. The owner has separately supplied the human-accepted candidate IDs; do
not infer or change that disposition. Submit one cumulative first diff from the
original tree containing every missing declaration needed to complete the
reciprocal relation for every supplied candidate that Backstitch surfaced and
whose trace is incomplete. Do not re-add a declaration already present in the
original tree. Record an accepted candidate that Backstitch omitted as a
discovery miss, not an authoring task. Do not ask Backstitch to edit or ratify
source."

Timing starts at the task handoff that first makes that fixture, prompt, and
accepted projection visible. It ends when the participant submits the final
public CLI observation and reviewed source diff, if any. The runner records
handoff and submission boundaries from its monotonic wall clock; first-call or
CLI-duration timing is invalid. Tool calls, reviewed diff attempts, review
rounds, elapsed milliseconds, changed source paths, and changed source lines
are recorded without estimates.

Every task-scoped read-only Backstitch call is recorded in `backstitch_calls`;
the smaller `cli_observations` array contains only source/tree/output-bound
commands used to recompute the outcome. Before submission, the participant runs
the exact complete proof command `backstitch obligation
docs/specs/01-core.md#CAND-1 --find-evidence --limit 100 --repo-root . --format
json`; this actual output must end with `next_cursor = null` and is matched
against the frozen candidate artifact. Default pages and cursor calls used for
review remain in the task call ledger. A stored or hand-written envelope is not
an observation.

## Human disposition and first-diff rule

`accepted` means a human reviewer selected the candidate into the intended
trace. `rejected` means the candidate is relevant and plausible enough that
discovery must surface it for human judgment, but the reviewer did not select
it. `irrelevant` is a negative control that discovery should omit. Accepted and
rejected rows form the candidate-capture denominator. Irrelevant rows do not;
they count only when surfaced. A critical row is always accepted or rejected,
never irrelevant.

The full labels remain hidden measurement gold. Candidate capture, trace-state
precision, irrelevant rate, and critical capture compare Backstitch's frozen
public discovery output with that gold. They do not score a participant's
ability to reproduce the human disposition.

A participant who believes a supplied human disposition contradicts the
fixture flags a possible preregistration defect and stops that task. The owner
reviews it without coaching. A confirmed defect produces new reviewed bytes
and a new phase qualification; the participant never silently relabels or
ratifies it.

An accepted candidate that is already declared needs no source diff. An
accepted untraced or partially declared candidate needs exactly its missing
reciprocal source declarations in the first diff. The first diff is correct only
when its parser-derived declaration set exactly equals the fixture manifest's
ordered `required_trace_declarations`. Each declaration names the frozen gold
candidate it traces; that row binds the exact candidate ID, path, structural
locator, and raw receipt. For a section candidate the complete set is the
reciprocal mapping and backlink. A spec-invariant implementation target uses
`spec_mapping`; its binding-test target uses `binding_test`. The diff must also
make the exact target obligation executable. Later repair does not rescue
first-diff correctness. Every source revision is a complete unified diff from a
fresh copy of the original tree.

## Freeze and review

An independent reviewer verifies the Phase B fixture bytes, complete gold set,
human-accepted projection, critical set, prompt, label rubric, first-diff rule,
thresholds, and hashes before any participant sees product output. Changing a
Phase B judged input creates a new Phase B qualification digest and result. It
does not invalidate an accepted Phase A result when the common product, guide,
and skill identities are unchanged. Prior results stay in the record and are
never rewritten to fit new output.

Every candidate artifact is rederived byte-for-byte through production
snapshot, report, obligation, and discovery code before the plan loads. It is
the frozen production observation, not the expected label source. Independently
reviewed gold fixes expected trace state and may include exact source-bound
eligible candidates that production omitted; those rows count as uncaptured.
Every surfaced candidate must match one exact gold row. Neither artifact nor
gold becomes a runtime trace relation, evidence-packet member, or alignment
authority.
