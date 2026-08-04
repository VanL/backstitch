# Intent Coverage Implementation

Intent coverage measures whether each physical Python definition is connected
to an authored decision. It is a reach metric, not a claim that the decision
text is good. The active contract is
[`docs/specs/08-intent-coverage.md`](../specs/08-intent-coverage.md).
Plan: `docs/plans/2026-07-29-architecture-quality-remediation-plan.md`.

## Ownership

`code_parser.py` owns physical source projections. `python_refs.py` owns the
canonical definition inventory and structural-locator grammar.
`intent_coverage.py` projects that inventory onto the existing resolved trace
graph and computes exemptions, requirement state, floors, and triage order.
`intent_coverage_reporting.py` owns the closed coverage artifact.
`coverage_application.py` owns accepted repository state, current and
historical projection, ratchet orchestration, report construction, gate
classification, and durable publication.
`git_baseline.py` owns bounded Git access and diff-derived facts.
`artifact_publication.py` owns durable same-directory output replacement.
`intent_history.py` reconstructs immutable revision graphs from object-database
blobs and computes exact section, mapping-set, implementation, and
connected-test projections. Historical configuration supplies ordered blob
layers to `settings._assemble_settings`, the same typed merge/final-validation
owner used by current configuration. Blob-side path normalization is lexical
and never follows the checkout; final code/test-root containment is therefore
source-independent. `cli.py` retains coverage argument validation, text/JSON
rendering, stdout emission, and public exit mapping.

The split matters. Coverage must not reopen live source, invent a second Python
parser, reinterpret suppressed graph issues, or let rounded display rates
drive enforcement.

## Classification Boundary

Classification precedence is direct, exempt, inherited, uncovered. Exact
symbol and non-module owner relations are direct. Whole-file relations are
inherited so a blanket mapping remains visible instead of inflating the direct
metric. Exemption is intentionally cheap: trivial glue should get a reasoned
one-line exemption instead of vacuous specification text.

The reverse view is kept separately. An active requirement with no mapping
continues to use the shared unmapped-section diagnostic; a declaration whose
targets do not resolve emits the coverage-specific unimplemented finding.
This prevents duplicate findings for the same missing edge.

## Trust and Failure Boundary

Report mode is repository-state only and does not require Git. Ratchet mode
accepts gate policy only from ordinary repository discovery, then uses a
closed Git executable, child environment, command budget, byte budget, and
deadline. It never fetches, invokes a shell, runs hooks, or executes target
code. A failure to prove the baseline is invocation failure, not a zero
baseline.

JSON is content-bound with canonical JSON and a final SHA-256. The validator
recomputes identities, partitions, joins, aggregates, ordering, and the report
hash before publication. Generic mutable output replacement uses
`artifact_publication.atomic_replace_bytes()`: it fsyncs the completed staging
file, atomically replaces the final, then fsyncs the containing directory.

Current-range first-parent transitions, the synthetic dirty transition, and
bounded stale-document trends are implemented. The Git owner reads the oldest
inspected parent tree and all bounded transition changes through constant-count
object-database batches. One shared revision projector reuses overlapping
current-range and stale-history states; reverse path indexes restrict each
drift-predicate evaluation to edges influenced by changed files. A truncated
walk emits `history_complete = false`, never a complete zero. Schema 1 omits
the section, mapping, and connected-test hashes from its public drift rows, so
the typed internal event retains those source facts solely for validator
recomputation of the public event ID.

## Rollout

The safe rollout has two stages. First, repository-state BSN001, BSN002,
BSN005, BSN006, and BSN008 findings remain advisory while maintainers review
the worklist and set defensible floors. Patch, malformed-exemption, floor, and
policy findings remain strict. Second, ratchet mode may be enabled only after
the reviewed baseline passes and CI pins the literal base with
`--require-ratchet`.

Backstitch's initial self-report must also satisfy the plan's stop conditions:
inherited coverage must not dominate direct coverage, and production
exemptions must remain below ten percent. A failed stop condition blocks
ratchet activation rather than licensing weaker metrics or manufactured spec
text.

The 2026-07-28 dogfood run stopped rollout as designed: 185 definitions were
direct, 2,925 inherited, 582 uncovered, and none exempt. No floor, repository
ratchet mode, or CI ratchet assertion is enabled while inherited coverage
dominates direct coverage.
