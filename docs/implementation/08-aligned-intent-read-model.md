# Aligned Intent Read Model

Spec: `docs/specs/07-verification-and-evidence-cases.md` [EVC-2], [EVC-4],
[EVC-7], [EVC-8], [EVC-10.2]

Plan: `docs/plans/2026-07-15-agent-guided-evidence-cases-plan.md`

Backstitch treats repository source as the only alignment authority. A spec
section or invariant is an obligation. Mappings, code backlinks, invariant
binds, binding tests, and source-authored skips are the durable decisions.
Evidence summaries and discovered candidates are read models over those
decisions. They cannot approve evidence or edit source.

## One Immutable Source View

`obligation_api.py` is the typed application boundary for the five public
obligation reads. One normalized request owns capture, runtime construction,
operation selection, cursor and discovery failures, response budgets, and
deadlines; one result carries the complete core envelope plus failure state.
`operation_progress.py` owns the discrete deadline/progress state machine.
One absolute monotonic deadline crosses capture, catalog, relations, closure,
candidate detail, packet materialization, and packet accounting. Deadline
checkpoints carry the phase of the work being done; separately, best-effort
progress events move only forward through the closed phase table. A failed
sink disables later progress without changing the domain result.
`obligation_runtime.py` is the reusable domain boundary beneath it. It combines
the bounded config loader with `repository_snapshot.py`, converges declared
mapping targets, and returns one frozen view. `check_pipeline.py` and
`resolver.py` consume that view without reopening repository source.

The former live-scan resolver entry points are removed. Deterministic checks
enter through `check_pipeline.build_check_report_from_snapshot()`, and
`resolver.scan_snapshot_with_artifacts()` projects only the accepted snapshot
before the pure `resolver.resolve()` graph step.

The snapshot identity contains exact source hashes, the path/kind catalog,
missing roots, normalized semantic settings, and algorithm versions. Applied
config layers have a separate ordered, path-free hash lane because [CFG-3]
allows parent and user-level config outside `--repo-root`. The loader retains
the exact bytes and original file identity. Capture validates the same leaf
address before and after each attempt without following symlinks. Absolute
config paths remain operational metadata and never enter semantic identity.

Only directories and regular files enter the accepted catalog. A stable
non-source symlink or special object is absent rather than becoming an
existence fact. A configured source, config, root component, or exact mapping
target that is a symlink or non-regular object fails closed.

## Obligation And Evidence Owners

The final aligned-intent split has nine owners: `repository_snapshot.py`,
`operation_progress.py`, `obligation_runtime.py`, `obligations.py`,
`evidence_summary.py`, `evidence_discovery.py`, `obligation_api.py`,
`alignment_guide.py`, and `alignment_eval.py`. Runtime capture,
deadline/progress state, orchestration, inventory, evidence, discovery,
transport, installed guidance, and qualification therefore remain separate
without creating another source of alignment authority.

`obligations.py` projects the existing trace graph into intent, alignment,
disposition, rung, and gate state. It does not build a second graph.
`evidence_summary.py` reports only declarations already present in source,
with exact snapshot-backed spans and receipts. Broken reciprocal declarations
stay visible. Both owners share the same exact-before-suffix, per-declaration
mapping association. One broken declaration keeps its required role partial
even when another declaration for that role is complete.

Primary evidence receipts use the closed markdown/Python locators and their
normative parser-owned spans. Each mapping, backlink, invariant, or binding
marker also has a one-line `source-declaration` receipt. Complete evidence
atoms merge all such declarations before pagination, so repeated markers in
one owner cannot alias a cursor or disappear between pages. One-sided mapping
rows keep the authored target token and the mapping-line receipt instead of
masquerading as code evidence. Locator construction asserts the closed grammar
before a public row is returned.

Whole-file evidence uses a `python-file` locator derived from the exact
captured repository path. It deliberately does not reuse `python-module`:
module identity belongs to import/static discovery and can be ambiguous across
overlapping roots, while an exact path-qualified evidence atom remains
addressable, including outside configured code/test roots.

`evidence_discovery.py` builds the deterministic candidate universe. Tree-sitter
owns Python acceptance, definition locators, spans, static references, binding
events, and exact source order through `code_parser.py`'s value seam.
`evidence_discovery.py` resolves those parser-owned records conservatively; it
does not reparse source with the running Python AST. Results therefore do not
change with the host interpreter's grammar version.

Source spelling and runtime lookup have separate normalization lanes. Locators
use NFC source names and assign ordinals after NFC normalization. Static Python
binding lookup uses Python's NFKC identifier keys, so compatibility-equivalent
definitions cannot produce a false exact edge. Comprehension targets, pattern
aliases, implicit `__class__` cells, branch-dependent writes, and scope
directives are parser-owned shadow facts. Relative imports that have no valid
package base, mixed-resolution import statements, and package
attribute/submodule collisions remain unresolved. Lexical ownership edges join
modules, definitions, and references so fixed-point expansion can move through
the complete captured source structure without claiming runtime execution.

The parser uses a small host-independent decoder for the plain string literals
that can orient dynamic static-reference advice. Its older `ast.literal_eval`
call is limited to text extraction from a tree-sitter-accepted docstring node;
it cannot admit syntax, mint a locator, or select a static candidate. A literal
outside that decoder's conservative subset yields no guessed relation.

`markdown_specs.py` identifies the semantic requirement/search text for each
obligation while it owns CommonMark structure. `resolver.py` carries that text
with the scan artifacts. Valid skip directives and trace declaration blocks do
not become lexical evidence merely because they share the requirement span.
The same parser preserves malformed terminal section-ID heading syntax as a
`SPEC_SECTION_HEADING_INVALID` issue instead of dropping it as ordinary prose.
`obligation_runtime.py` projects that issue's exact line from the accepted
snapshot bytes; `obligations.py` returns it as unaddressable intent without
minting a fallback identity. Headings with no terminal ID marker remain
ordinary ID-less structure.

Candidates have content-addressed structural identities, byte receipts,
closed discovery bases, conservative neighbors, and one trace state.
Suggestions name supported declaration forms, but always carry the warning
that advice is not evidence. Candidate discovery never changes readiness by
similarity alone.

Multi-obligation packet construction prepares the parser/static-relation
catalog once for the accepted snapshot. Each obligation receives a clone of
only the mutable derivation fields, so lexical scores, declaration flags, and
closure bases cannot leak between obligations. The logical work budget still
starts with the catalog's exact charged work: reuse changes execution cost, not
budget truth or result bytes.

`analysis_packets.plan_source_aligned_packets()` is the sole packet producer.
Its authoritative `PacketPlan` retains the exact packet and model-request
bytes consumed by reports, publication, preflight, and analysis without a
second derivation. `generate_source_aligned_packets()` is only a compatibility
projection of a complete plan. The former `generate_packets()` path is
removed. The producer consumes the immutable obligation runtime and prepares
the shared discovery catalog once;
`packet_application.publish_packets()` owns the provider-free packet command's
runtime construction, deterministic gate, optional report, and final artifact
set;
`artifact_publication.publish_artifact_set()` owns staged publication of the
complete packet/result/report artifact set.

A path-only Python mapping declares exactly the module owner at that file. It
does not mark every definition and reference in the file as human-declared.
Lexical seeds are limited to the ten highest-scoring class, function, or method
definitions by default; whole modules, references, and report issues enter
through source declaration, issue attribution, or conservative static reach.
This keeps bootstrap suggestions reviewable and prevents a generic unresolved
reference or filename match from injecting thousands of advisory candidates.

## Public Read Loop

The CLI exposes one aggregate:

```text
backstitch obligation list
backstitch obligation OBLIGATION_ID
backstitch obligation OBLIGATION_ID --summarize-evidence
backstitch obligation OBLIGATION_ID --find-evidence
backstitch obligation OBLIGATION_ID --candidate CANDIDATE_ID
backstitch guide alignment
backstitch check
```

`obligation_api.py` also owns the transport-neutral envelopes, content-bound
cursors, closed problem vocabulary, canonical JSON, and the compact text view.
The CLI selects the normalized operation, supplies the resolved profile and
settings, renders the returned envelope, chooses stdout or stderr, and maps the
application failure bit to process exit `2`. It does not capture, build an
inventory, discover candidates, or implement a second failure-order policy.
Text keeps the resolved root outside core JSON, retains page cursors and repair
actions, and shows the selected evidence or candidate facts needed for the
bootstrap loop. Default detail uses
the same discovery owner to report candidate counts. Therefore default detail,
discovery, and candidate detail require a complete readable semantic catalog;
list, declared-evidence summary, and deterministic `check` can still report a
stable unreadable input.

Every complete response is checked against the response-byte limit. Work and
item ceilings abort the whole discovery operation; wall time may abort only the
complete operation. Snapshot capture checks before and after each file read;
deterministic discovery checks at every charged work-unit boundary. Blocking
operating-system reads and scheduler suspension remain outside the cooperative
100-millisecond tolerance. There is no partial page, guessed candidate,
provider import, network call, or source write. Once capture succeeds, any
unexpected downstream failure returns `INTERNAL_ERROR` with that accepted
snapshot rather than relabeling the failure as invalid user input.

`obligation_api.apply_response_byte_budget()` owns this byte check over
canonical core JSON before either JSON or text rendering. Public callers do
not implement a second response-size policy.

## Human Review Boundary

The shipped workflow has two product phases. Bootstrap asks: "Given obligation
X, what current code or tests are plausible candidates for fulfilling X?" It
captures the current tree and returns a disposable candidate report with exact
receipts, discovery reasons, trace states, and supported declaration forms. It
is safe and expected to rerun bootstrap after repository changes. A saved
candidate report is historical once its snapshot differs.

Human review is the bridge. The human accepts or rejects suggestions and lands
ordinary reciprocal source declarations. Gate then ignores candidate
dispositions, resolves those current source declarations, builds a current
evidence packet, and reports whether the packet appears to support the
obligation. Backstitch explains the supported forms and recomputes after the
diff. The human remains the final arbiter because no candidate artifact, model
response, cache entry, or future MCP call can become alignment authority.

## Product-Qualification Boundary

`alignment_eval.py` is an evaluation-only consumer of the read model. It
rederives each frozen candidate artifact through production snapshot, report,
obligation, and discovery code. The artifact records what the tested product
surfaced. It does not provide the expected labels.

When discovery semantics change, Phase B's deterministic candidate artifacts
must be refreshed and re-reviewed. Phase A participant sessions are not rerun
merely to validate a later discovery-only artifact: phase-specific identities
keep that evidence historical and separate. The 2026-07-16 lexical/module
authority correction refreshed only Phase B's mechanically derived artifacts;
it did not replay or relabel any Phase A participant observation.

The 2026-07-29 discovery-v2 migration is a historical compatibility fixture,
not a current qualification. The provider-free maintenance command
`uv run python tests/product_eval/generate_alignment_bootstrap.py --write`
rederives only the seven production candidate observations and their binding
hashes; the same command without `--write` is the drift check. It never changes
reviewed gold or critical labels.

Discovery-v2 omits 13 reviewed rejected rows (nine module-wide candidates and
four raw unresolved-reference intermediates), newly surfaces one previously
reviewed static definition, and schema-2 role diagnostics newly surface one
`SPEC_MAPPING_TEST_ONLY` report issue. Independent review retained all 13
absent rows as capture misses and labeled the new issue rejected, critical,
and partially declared. The resulting valid product observation captures 49
of 62 eligible candidates and 23 of 30 critical candidates, so it fails the
capture and all-critical checks. The root manifest also retains a historical
common tested-product digest. Therefore `require_current_product = true`
rejects the fixture, both prior phase results are historical, and no current
bootstrap/discovery qualification claim follows from the refreshed Phase B
projection.

Independent gold is bound to the full parser-derived source candidate catalog.
It may include eligible candidates omitted by obligation selection, so capture
can fail without making the observation malformed. Expected trace state is
independent from discovered trace state, so precision can fail for a valid
candidate run. Section first diffs require the exact reciprocal mapping and
backlink; spec-invariant implementation targets use a spec mapping and their
binding-test targets use a binding-test relation. A matching declaration set
counts as correct only when production readiness says the revised obligation
is executable.

The top preregistration manifest indexes both qualification phases and owns the
common tested product identity. It hashes a canonical inventory of
`pyproject.toml`, `uv.lock`, and non-cache package files, plus the exact
installed guide and repository skill. Each result binds a canonical
phase-specific qualification projection, so a valid Phase-B-only change does
not erase Phase A evidence. Plan and result loading repeat no-follow reads and
reject symlink, special-file, or byte drift.

Phase B session observations bind both source and output artifact paths and
hashes to the one canonical candidate run. Each task also binds the exact
sorted human-accepted candidate IDs handed to the participant. Product search
quality is still measured against full independent gold, including accepted
candidates discovery omitted. First-diff guidance is measured only for
human-accepted candidates the product surfaced, as one cumulative original-
based diff containing the union of declarations missing from the original
tree. A partial candidate contributes only its missing side; an untraced
candidate contributes both. None of these evaluation records enters runtime
readiness or evidence.

Interaction-cost accounting is deliberately separate from outcome proof. Each
task logs every allowlisted read-only Backstitch call in execution order and
binds it to the source revision in force. Byte-bound CLI observations remain a
smaller proof subset. The validator recomputes the call count from the complete
log and rejects proof observations absent from that log; it never treats the
number of proof artifacts as the participant's total product-call cost.

Phase fixtures are released to each participant one at a time. Elapsed time is
the runner-observed handoff-to-submission interval, not CLI duration or the
first-to-last call interval. Authority-comprehension rows likewise preserve
the participant's raw boolean `answer`; the result validator compares that raw
value with the frozen rubric and derives the session pass. These boundaries
keep cost and comprehension evidence separate from recorder judgment.

Discovery qualification binds a complete public proof call, not a synthesized
candidate envelope. The closed Phase B proof uses `--limit 100`, which exceeds
every frozen candidate set, requires `next_cursor = null`, and is rerun
byte-for-byte by the validator. Default-size pages still measure participant
review behavior and remain in the call ledger.

Phase B therefore measures the bootstrap bridge: candidate capture, false
surfacing, exact trace state, critical misses, and post-human-selection
authoring guidance. It does not measure whether a participant can infer the
human's accepted/rejected decision, nor whether that decision is correct.

The optional MCP adapter remains deferred until CLI dogfood measures a concrete
call, byte, or context-cost problem that the adapter would solve. The semantic
packet and current-analysis lanes remain separate evidence products: this read
model is their required source-derived input, but bootstrap qualification does
not grant semantic-policy authority. That authority remains unavailable until
the schema-3 corpus and exact analyzer/verifier report satisfy their own review
and qualification gate.
