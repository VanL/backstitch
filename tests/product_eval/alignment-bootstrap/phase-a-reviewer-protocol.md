# Alignment bootstrap Phase A reviewer protocol

Status: preregistered evaluation protocol. It is not runtime alignment state.

## Inputs and access

The owner gives each participant only the installed public help, `backstitch
guide alignment`, the installed repository skill, and the assigned fixture.
Participants must not read product implementation source, fixture manifests,
gold labels, or another participant's record. Each participant is a distinct
human or agent identity and sets `public_help_only = true`.

The result binds the Phase A qualification digest. That digest covers only the
Phase A fixture manifest, this protocol, Phase A session count and thresholds,
and the common tested distribution, guide, and skill identities.

## Fixed tasks and timing

The owner releases fixtures to a participant one at a time in frozen fixture
order. The participant cannot inspect a later fixture before its task timer
starts. Public help, the installed guide, and the repository skill may be
inspected before the first task and are not charged to a task.

Prompt: "Use Backstitch's public interface to bring
`docs/specs/01-core.md#BOOT-1` to an executable alignment state. The complete,
partial, skipped, and untraced fixtures are authoring tasks and pass only when
BOOT-1 is executable. For the no-intent fixture, diagnose the empty bootstrap
result with the exact bootstrap state, blocking reason codes, and next action
codes; do not invent BOOT-1."

For each fixture, timing starts at the task handoff that first makes that
fixture and prompt visible. It ends when the participant submits that task's
final public CLI observation and reviewed source diff, if any. The runner
records the handoff and submission boundaries from its monotonic wall clock;
first-call or CLI-duration timing is invalid. Tool calls, reviewed diff
attempts, review rounds, elapsed milliseconds, changed source paths, and
changed source lines are recorded without estimates.

Every task-scoped read-only Backstitch call is recorded in `backstitch_calls`;
the smaller `cli_observations` array contains only the source/tree/output-bound
commands used to recompute the outcome. Proof observations never stand in for
unrecorded summary, discovery, candidate-detail, or deterministic-check calls.
An incomplete authoring fixture records the initial production `obligation
list` result before the first edit and reruns the exact public obligation detail
command from the final revised tree. A stored or hand-written envelope is not
an observation.

## Authority comprehension rubric

Each participant answers these propositions true or false, in order:

1. Repository source is the alignment authority. (True.)
2. Candidates are advice. (True.)
3. Backstitch neither edits nor ratifies source relations. (True.)
4. Semantic success cannot repair incomplete alignment. (True.)

A result records each participant's raw boolean `answer`; it never records a
recorder-asserted `correct` value. The validator compares those answers with the
frozen answers above and derives the session pass. A session passes only when
all four answers match. Participant answers are evaluation ground truth only.
They never enter runtime alignment, readiness, candidate state, packet
membership, or semantic policy.

## Freeze and review

An independent reviewer verifies the Phase A fixture bytes, prompt, authority
rubric, thresholds, and hashes before any participant sees product output.
Changing a Phase A judged input creates a new Phase A qualification digest and
result. A Phase-B-only change does not invalidate an accepted Phase A result.
Prior results stay in the record and are never rewritten to fit new output.

The parent manifest binds the canonical tested-distribution inventory and exact
installed guide and repository-skill bytes. Validation rederives those
identities from authoritative regular no-follow inputs before accepting a plan
or result.
