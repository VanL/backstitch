# Evidence Spike Hardening Plan

Status: Slice 7 complete (2026-07-17); intentionally uncommitted. The reviewed
plan passed through round 4. Slice-0 reproduction exposed one false
implementation assumption in the selected fix for finding #10. The narrowly
corrected contract and complete implementation boundary passed round 5. Slice
0 and the Spec-Promotion Slice are complete. Slices 1, 3, 5a, 5b, and 6 passed
their independent reviews; Slices 2 and 4 passed their stop gates. All
implementation slices 0-6 are complete. The 2026-07-17 post-implementation
review confirmed the implementation faithful with all gates green and added
Slice 7 (post-review residuals). Slice 7's scoped outside review completed
2026-07-17 over four rounds: independent reviewer BLOCKED-narrow round 1
(1 P1 / 4 P2, all applied, PASS-on-correction granted); codex BLOCKED rounds
1-3 (8, 3, then 1 P1 — parser-boundary newline design, obligation-lane
projection legality, the declared [EVC-9.1] bare-CR micro-delta, and NFC
canonicalization order — all applied), codex PASS round 4. Slice 7 is
cleared for implementation and is now complete; the [EVC-9.1] micro-delta
promoted in Slice 7's own spec step per its Deviation Log row.

Corrections 1-15 from round 1 remain applied.

Plan type: implementation with spec revision (new invariants plus removal of
the non-firing `analyze.packet_warnings` configuration affordance).

Class: 5 (normative invariant additions to `docs/specs/05-backstitch-invariants.md`),
with class-4 hardening because [DOM-5] risky triggers fire: semantic-cache
lock-lifecycle changes, shared scan-pipeline consolidation, and
performance-critical changes to the deterministic lane.

Risk level: medium-high. Most changes restore or strengthen already-specified
behavior. Finding #10 removes a documented but unreachable config branch; its
small contract delta is explicit below. The main risk remains regression in
shared seams.

## Goal

Bring the uncommitted aligned-intent spike from "thesis demonstrated" to
"excellent": fix the ten confirmed review findings and the four confirmed
near-misses, collapse every duplicated shared mechanism to one canonical
owner, restore the deterministic lane's performance contract, and encode the
lessons as named, tested invariants so backstitch itself gates the properties
this phase established. The spike's architecture is sound and unchanged; this
plan pays down its edge behavior, duplication, and speed debt before anything
lands.

## Source Documents

- Review findings: the 2026-07-16 implementation review (10 CONFIRMED findings
  reported via the session review harness; reproductions in scratchpad)
- `docs/plans/2026-07-15-agent-guided-evidence-cases-plan.md` (parent plan;
  this plan is its hardening successor and inherits its product model)
- `docs/specs/02-backstitch-core.md` [SC-5], [SC-7], [SC-10], [SC-15]
- `docs/specs/03-backstitch-configuration.md` [CFG-8] (no fake affordances)
- `docs/specs/05-backstitch-invariants.md` [INV-3], [INV-5], [INV-7]
- `docs/specs/06-semantic-gates.md` [SEM-3], [SEM-4], [SEM-7]
- `docs/specs/07-verification-and-evidence-cases.md` [EVC-7], [EVC-8], [EVC-9.1]
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/testing-patterns.md`

## Spec Baseline

- Planning baseline: the current dirty worktree over commit `25346a9`, as
  verified by the parent plan's Current Implementation Closure Verification
  Record (1,616 non-live tests green, self-corpus gate zero findings).
- The parent plan's specs (06, 07, 08 plus core/config/invariant deltas) are
  promoted and Active in the worktree. This plan adds invariants to spec 05
  and makes the explicit finding-#10 correction in specs 06 and 07 described
  below. Every other behavioral fix restores conformance to Active spec text.
- Pre-promotion spec hash: `docs/specs/05-backstitch-invariants.md` at
  planning time is SHA-256
  `c6bb038b98297cb6d79c80b594a20c1af6345555b39f4495c1b30e6727ed0d24`.
  The Spec-Promotion Slice verifies this hash before editing and records the
  post-promotion hash in its slice record.
- Finding-#10 pre-promotion hashes at the Slice-0 replan point are:
  `docs/specs/06-semantic-gates.md` SHA-256
  `1c9b5cab30540a7109744e033926d97b8ff51b146e3c047e5675dc44ec238fcf`
  and `docs/specs/07-verification-and-evidence-cases.md` SHA-256
  `41fe9fbb7db2a133da459bdf576e859a1c50e1d3c167328ca6f7b855dfcdafd0`.
- Worktree checkpoint identity protocol: the baseline is a dirty worktree, so
  commits cannot serve as checkpoints, and a plain `git diff` would silently
  omit untracked files. Before starting each slice: run `git add -A -N`
  (intent-to-add, so every untracked file enters the diff surface without
  staging content), then write
  `git diff HEAD --binary > <scratch>/checkpoint-slice-<N>.patch` in the
  session scratch directory, and record a manifest of every untracked file
  path with its SHA-256 hash alongside the patch. All checkpoint patches are
  taken with `--binary`. The pair (binary checkpoint patch, untracked-file
  manifest with hashes) is the slice's checkpoint identity; every slice
  record cites the checkpoint it started from. Restore = apply the binary
  patch and verify every manifest entry's hash. See Rollback for the full
  restore procedure.

## Proposed Spec Delta

Strategy B (atomic with bindings) for
`docs/specs/05-backstitch-invariants.md`, plus Strategy A active text-first
edits to the already-mapped [SEM-3] and [EVC-9.1] sections for finding #10.
The Spec-Promotion Slice
(immediately after Slice 0) lands the new invariant section together with
`Tests-invariant:` binding markers on the already-written Slice 0 pin tests,
so no `INVARIANT_UNTESTED` window ever exists and the invariants are
executable obligations per [INV-5] from the moment they are declared.

Late-binding justification: every binding marker lands at promotion, but the
bound tests for INV.CFG.2, INV.PERF.1, and INV.SCAN.1 cannot pass until
their fix slices land (the #7 default fix in Slice 3, the perf restoration
in Slice 5a, and the live-path deletion in Slice 5b respectively). All
three — INV.CFG.2, INV.PERF.1, and INV.SCAN.1 — receive the same disclosed
strict-xfail treatment: each invariant statement describes the target
property, which is knowingly false at promotion time, and its pin is marked
strict-xfail until its owning slice flips it. In particular the INV.SCAN.1
enumeration pin stays strict-xfail until Slice 5b deletes the live twin;
there is no exemption-row workaround that would let it pass while the twin
still exists. Binding validity (no `INVARIANT_UNTESTED`, no
`INVARIANT_UNKNOWN`) holds from promotion onward. INV.CANON.1 and
INV.LINE.1 bindings go green at Slice 1.

Insertion point (§4c-style):

| Target file | Pre-promotion SHA-256 | Insertion point | New content |
|---|---|---|---|
| `docs/specs/05-backstitch-invariants.md` | `c6bb038b98297cb6d79c80b594a20c1af6345555b39f4495c1b30e6727ed0d24` | immediately after the `## 10. Documentation And Traceability [INV-10]` section body (after its `_Implementation mapping_:` block), before `## Related Plans` — i.e. after the last existing invariant section | new section `## 11. Phase Hardening Invariants [INV-11]`, exact markdown below |

Exact proposed markdown, in spec 05's [INV-3] declaration format (top-level
`Invariant:` paragraphs in an ID-bearing section plus the section's
`_Implementation mapping_:` block; `Tests-invariant:` bindings live in the
test docstrings listed after the block):

```markdown
## 11. Phase Hardening Invariants [INV-11]

Invariant: [INV.CANON.1] exactly one production implementation of canonical
JSON serialization, of the sha256-hex token grammar, of the deterministic
issue sort key, and of bounded no-follow file reading exists in the package;
every consumer imports the owner module named in the closed allowed-owner
table in `tests/test_canonical_owners.py`, proven by AST-level enumeration
of the package.

Invariant: [INV.LINE.1] production line-number arithmetic over source bytes
or snippet text splits on `\n` only, through the one shared line-slicing
helper; no production module outside the closed exemption table in
`tests/test_canonical_owners.py` calls `splitlines`, performs ad-hoc
`split("\n")` line splitting outside the shared helper, or does manual
newline-count arithmetic — the enumeration test covers all three call-site
forms. Receipts, packet spans, and shown-region reconstruction agree
byte-for-byte on any input, including `\r`, `\f`, `\v`, `\x85`, U+2028, and
U+2029.

Invariant: [INV.SCAN.1] one scan pipeline exists: every repository read used
by resolve, discovery, packets, and reports consumes the captured immutable
byte image, and only the owner modules named in the closed allowed-owner
table in `tests/test_canonical_owners.py` open repository files, proven by
AST-level enumeration; no live-filesystem twin path exists in the package.

Invariant: [INV.PERF.1] the advertised default `backstitch check` invocation
performs zero static-syntax parses and at most one repository snapshot
capture; `backstitch obligation list` parses each unique file at most once
per invocation. Wall-clock budgets are non-normative and live only in marked
performance tests.

Invariant: [INV.CFG.2] for every config key whose settings-dataclass default
is a concrete value, the packaged-default TOML value equals that dataclass
default; keys whose dataclass default is None-means-packaged are exempt. On
conflict the packaged TOML is canonical and the dataclass is corrected. A
single enumerating test proves the equality.

_Implementation mapping_:
- `backstitch/grammar.py`
- `backstitch/models.py`
- `backstitch/repository_snapshot.py`
- `backstitch/settings.py`
- `backstitch/semantic_packets.py`
- `backstitch/code_parser.py`
- `backstitch/obligation_runtime.py`
```

The mapping lists only modules that exist at promotion time
(`semantic_packets.py` is the strongest current `canonical_json_bytes` copy;
`code_parser.py` and `obligation_runtime.py` own the INV.PERF.1 work
bounds). When Slice 1 creates `backstitch/canonical.py` as the consolidated
owner, it adds that path to the mapping block and records the mapping
refresh (non-normative) in its slice record.

`Tests-invariant:` bindings land at promotion in:
`tests/test_canonical_owners.py` (INV.CANON.1, INV.SCAN.1, and the
INV.LINE.1 call-site enumeration covering `splitlines`, ad-hoc
`split("\n")`, and manual newline-count arithmetic), the Slice 0
line-terminator receipt pins covering every character INV.LINE.1 names —
`\r`, `\f`, `\v`, `\x85`, U+2028, U+2029 — (INV.LINE.1), the Slice 0
defaults-equality pin (INV.CFG.2), and the Slice 0 deterministic-work pins
(INV.PERF.1).

Finding #10 correction (Strategy A, existing active mapped sections): the
review correctly proved that the `analyze.packet_warnings` setting cannot
fire, but the original plan selected an invalid remedy. [EVC-9.1] requires the
complete counterevidence universe and says overflow is fatal with no
warning-based truncation. There is therefore no conforming "trace-mode bound
omission" warning to emit. Remove the dead config affordance instead, retain
the schema field as an exact empty compatibility field, and make nonempty v3
packet warnings invalid at load. Every schema-3 analysis report, for both
current-repository and historical-snapshot scope, must likewise reject nonzero
`packet_warning_count` or nonempty `packet_warning_debt`; only the legacy
schema-1 report validator retains warning debt as historical presentation
vocabulary. Existing mappings/backlinks for
[SEM-3], [SEM-7], [EVC-8.7], and [EVC-9.1] remain unchanged; Slice 2 updates
all code consumers and repository configuration.

| Target file | Pre-promotion SHA-256 | Exact edit |
|---|---|---|
| `docs/specs/06-semantic-gates.md` | `1c9b5cab30540a7109744e033926d97b8ff51b146e3c047e5675dc44ec238fcf` | Insert the markdown below in [SEM-3] immediately after its opening current-schema paragraph. In [SEM-7], retain the exact warning-debt record shape but label it legacy schema-1 validation/presentation only; remove warning-dependent schema-3 status text; replace lines 718-720's three-sentence warning policy with the schema-3-empty/legacy-schema-1 rule below. Remove the `packet_warnings = "error"` exit-table clause, the TOML example key, the config-validation row, and the packaged-default clause. |
| `docs/specs/07-verification-and-evidence-cases.md` | `41fe9fbb7db2a133da459bdf576e859a1c50e1d3c167328ca6f7b855dfcdafd0` | In [EVC-8.7], remove `warning` from row 5's preflight condition, remove the `packet_warnings = error` completeness clause and the `allow`/`report` sentence, and state that every schema-3 report requires zero/empty warning fields. In [EVC-9.1], replace the existing `Issues use...` / `Warnings are...` / fatal-overflow paragraph at lines 2160-2162 with the exact-empty paragraph below. |

Exact [SEM-3] insertion markdown:

```markdown
Schema-3 `packet_warnings` is a compatibility field and is exactly `[]`.
Current packet generation and loading reject nonempty schema-3 warnings:
required text or universe budget overflow is fatal under [EVC-9.1], never a
warning-based truncation. The analyzer exposes no `packet_warnings` policy
setting. Every schema-3 analysis report has `packet_warning_count = 0` and
`packet_warning_debt = []`, regardless of current or historical scope.
```

Exact [SEM-7]/[EVC-8.7] current-report and historical-replay rule:

```markdown
Schema-3 analysis reports have `packet_warning_count = 0` and
`packet_warning_debt = []` for both current-repository and historical-snapshot
scope. The legacy schema-1 report validator may preserve packet-warning count
and ordered debt for historical validation and presentation only; that
vocabulary cannot satisfy a schema-3 gate and has no current policy authority.
```

Exact [EVC-9.1] replacement markdown for existing lines 2160-2162:

```markdown
Issues use [SC-6]'s canonical model-visible issue shape and order.
`packet_warnings` is exactly the empty list for schema 3. Packet construction
emits no truncation warning: any required text or universe budget overflow is
fatal.
```

## Context and Key Files

Findings-to-seams map (finding numbers from the 2026-07-16 review):

| # | Defect | Files |
|---|---|---|
| 1 | Wrapped invariant statement -> v3 packet rejected at load | `analysis_packets.py:632`, `artifact_contracts.py:702` |
| 2 | Malformed mapping token bricks check + obligation repo-wide | `markdown_specs.py:459`, `obligation_runtime.py:389`, `repository_snapshot.py:444` |
| 3 | check 6x slower; obligation list 6.1s; packets 38.7s | `code_parser.py:211`, `obligation_runtime.py:212,331`, `cli.py:456`, `evidence_discovery.py:1957,429` |
| 4 | Invariant-targeted skip reason leaks into model-visible requirement | `markdown_specs.py:402-440`, `exclusions.py:231` |
| 5 | splitlines vs \n: wrong receipts (\r), uncitable regions (\f...) | `evidence_discovery.py:300`, `evidence_summary.py:59,159`, `obligation_runtime.py:184`, `semantic_packets.py:166`, `semantic_evidence.py:124` |
| 6 | Verify lock cleanup masks provider error, leaks lock | `semantic_cache.py:1922` (verify), `:1064` (analysis twin) |
| 7 | maximum_lexical_seeds 100 vs packaged 10 (identity-bearing) | `settings.py:416`, `defaults.toml:39` |
| 8 | SnapshotCaptureError / EvidenceDiscoveryError -> "internal error" | `cli.py:534,542,776-779,891` |
| 9 | packets/analyze exit 1 with zero output | `cli.py:539,776`; test pins stderr `== ""` |
| 10 | `packet_warnings` knob can never fire; remove it and enforce empty v3 warnings | `analysis_packets.py:888`, `artifact_contracts.py`, `semantic_analysis.py:500`, `settings.py:325` |
| NM1 | analyze_packets pre-loop KeyError aborts batch (library seam) | `analysis_llm.py:416` |
| NM2 | semantic_cache stat identity weaker than its two siblings | `semantic_cache.py:384` |
| NM3 | Stolen lock -> corrupt_cache instead of serving published result | `semantic_cache.py:1056,1915` |
| NM4 | UTF-8 validation before semantic filter poisons discovery | `evidence_discovery.py:591` |
| D1 | canonical JSON ownership is wider than the reviewed x4 inventory; consolidate identity encoders and narrowly classify presentation encoders | closed inventory in `tests/test_canonical_owners.py` |
| D2 | sha256-hex regex x5; candidate-ref regex x2 | `grammar.py` is the declared home |
| D3 | issue sort key x3 | `resolver.py:786`, `check_pipeline.py:139`, `semantic_reports.py:2357` |
| D4 | bounded reads/stat identity have more owners and weaker variants than the reviewed x3 inventory | closed inventory in `tests/test_canonical_owners.py` |
| D5 | contract-validator families are triplicated but intentionally vary by NFC policy, digest prefix, integer minimum, and return type | `semantic_eval_reports.py`, `semantic_reports.py`, `alignment_eval.py` |
| D6 | live scan pipeline + legacy generate_packets kept beside snapshot path | `resolver.py:1161`, `analysis_packets.py:944` |
| D7 | SEMANTIC_ prefix string-classification is load-bearing | `diagnostics.py:323`, registry TOML |
| D8 | CLI owns transport-neutral semantics; core owns text rendering | `cli.py:1595-1640`, `obligation_api.py:673` |
| D9 | 4th path matcher missing backslash normalization | `repository_snapshot.py:504` vs `settings.py:666` |
| D10 | staging/publication protocol duplicated, packets copy weaker | `cli.py:559-579` vs `816-860` |

## Invariants and Constraints

1. No behavior that current Active specs define may change except where a
   finding shows the code violates the spec; fixes restore conformance.
2. Byte-stability of the deterministic report (INV.RES.1) must hold across
   every slice; the report snapshot test runs per slice.
3. The lazy-`llm` import boundary is untouched and re-proven per slice.
4. One canonical owner per shared mechanism, on the plan's schedule: D1-D5
   have their canonical owners after Slice 1; D6 and D10 reach theirs by
   Slice 5b (the live-scan twin and the duplicated staging protocol are
   disclosed intermediates until then). Once a mechanism has its canonical
   owner, a second implementation appearing later is a defect, enforced by
   INV.CANON.1 tests.
5. Every fix lands with its failing-test-first regression pin (Slice 0 probes
   fail on the current tree for the right reason before any fix).
6. No new config keys, no new CLI surface, no new dependencies.
7. Anti-mocking rules of the parent plan apply unchanged.

## Hidden Couplings and Risk Register

- **Packet identity**: fixing #1 (real multi-line requirement spans) and #5
  (line arithmetic) changes packet bytes -> packet_hash -> cache keys for
  affected packets. This is a legitimate identity change (the old bytes were
  wrong), but every cached fixture, golden, and eval artifact bound to old
  hashes must be regenerated in the same slice; stale-fixture failures are
  the expected signal, not collateral to suppress.
- **Sort-key consolidation (D3)** must be proven byte-identical before the
  validator copy is replaced, or packet reports would be rejected.
- **Lock-cleanup fix (#6)** touches the [SEM-4]-governed protocol; the fix
  must preserve single-flight and no-replace semantics. Death-injection tests
  from the parent plan rerun unmodified.
- **Deleting the live scan path (D6)** removes the only non-snapshot
  reference implementation; the snapshot-equality test that guarded drift is
  retired with it, so resolver behavior tests must already run through the
  snapshot path first.
- **Perf memoization (#3)** must not cache across snapshot identities;
  memos are keyed by content hash and scoped to one capture/invocation.
- **packet_warnings (#10)**: the reviewed defect is real but the original
  chosen remedy was not. [EVC-9.1] forbids warning-based truncation and requires
  the complete universe. Slice 2 removes the dead config key, keeps v3
  `packet_warnings` exactly empty, and rejects nonempty v3 warnings. No packet
  identity churn is attributed to #10.

## Rollback and One-Way-Door Posture

The baseline is an uncommitted worktree, so a bare restore-to-HEAD
(`git checkout`/`git restore` against HEAD without a recorded checkpoint)
would destroy the spike itself and is prohibited. Checkpoint-apply restore
is the sanctioned rollback mechanism: the prohibition is on unrecorded
restore-to-HEAD, not on restoring through a recorded checkpoint. Rollback
uses the patch-checkpoint protocol from Spec Baseline: before each slice,
run `git add -A -N` so untracked files enter the diff surface, write
`git diff HEAD --binary > <scratch>/checkpoint-slice-<N>.patch`, and record
the untracked-file manifest with SHA-256 hashes. To roll a slice back,
return the tracked tree to the checkpoint's recorded base (safe only
because the binary checkpoint patch captures the full delta, untracked
files included), apply the checkpoint patch with `git apply --binary`, and
verify the restored tree against the checkpoint identity — every manifest
path present with its recorded SHA-256 — before resuming. Untracked new
files added by the slice are removed by name from the slice record's
changed-files list, never by a blanket clean. The only
semi-one-way door is packet-identity churn (#1 and #5), which is acceptable
now precisely because nothing has landed: no external cache or committed
artifact binds the wrong hashes yet. This is the cheapest moment the project
will ever have to correct packet identity — a stated reason this plan blocks
landing the spike until complete. No data deletion, no schema version bumps.

## Tasks

Slices run strictly serially, in this order: 0, Spec-Promotion, 1, 2, 3, 4,
5a (measured performance fixes only), 5b (D6 deletion + D8 move + D10
unification, with its own independent review gate and a coverage-diff
migration gate before any deletion), 6 (docs, traceability, registry
family). No slice starts before its predecessor's stop gate is recorded.
Slice 2 is the single fixture-regeneration owner: no other slice regenerates
packet fixtures, goldens, or eval artifacts; a later slice that would
invalidate a fixture reopens Slice 2's regeneration step rather than
regenerating ad hoc.

Gate expectations: at Slice 0 the unit-suite gate is expected red on every
new pin (each failing for its documented reason) while the self-corpus
`backstitch check` gate stays green. Pins owned by Slices 4, 5a, and 5b are
marked strict-xfail until their owning slice flips them, so the first
all-green run of the full non-performance suite is the Slice 3 stop gate.

### Slice 0: Regression pins (failing tests first)

Write failing tests for every finding: wrapped two-line invariant statement
end-to-end through packets+load; `../escape.py` / `/abs/x.py` / `src\util.py`
mapping tokens degrade to per-target diagnostics in both `check` (exit 1,
named token+file+line) and `obligation list` (structured problem naming the
token); line-terminator fixtures covering every character INV.LINE.1 names —
bare `\r`, `\f`, `\v`, `\x85`, U+2028, and U+2029 — proving receipt bytes
and shown-region agreement; invariant-targeted skip reason absent from
`project_section_packet_requirement().text`; packets/analyze mapping
SnapshotCaptureError/EvidenceDiscoveryError to non-"internal" messages;
packets exit-1 renders the deterministic report (replace the stderr `== ""`
assertion); defaults-equality enumeration test (INV.CFG.2, catches #7);
finding-#10 config-removal pins (packaged defaults omit the key, explicit use
is an unknown-config error, nonempty schema-3 warnings are rejected, and a
schema-3 analysis report in either current-repository or historical-snapshot
scope independently rejects nonzero warning count and nonempty warning debt);
analyze_packets one-malformed-packet containment;
UTF-8-after-filter fixture; duplicate-mapping-token fixture (no
AssertionError); lock-cleanup unit test injecting provider failure under
guard contention (problem records provider_failure, no lock leaked); NM2 pin
(semantic_cache stat identity must equal the shared stat-identity tuple of
its two siblings); NM3 pin (a stolen lock with a published identical-key
result serves the published result as a hit, not corrupt_cache);
budget-vs-torn race pin (mid-read growth past `maximum_file_bytes` after a
passing fstat classifies as torn-capture retry, not budget failure); prompt
hash-at-use pin (the prompt bytes hashed into the analysis identity are the
same bytes sent in the request); deterministic-work pins for INV.PERF.1
(default `check` performs zero static-syntax parses and at most one snapshot
capture; `obligation list` parses each unique file at most once), plus
marked `tests/performance/` wall-clock budget tests (non-normative, see
Testing Plan).

D5 pre-work also lands here: record the closed D5 validator-function
inventory and write behavior-preservation characterization tests before any
factory exists. The live families are not semantically identical: the tests
pin intentional NFC, digest-prefix, integer-minimum, and return-type policies
so consolidation cannot silently widen or narrow a consumer. The closed
inventory (the triplicated scalar-validator families as
of the 2026-07-16 tree) is:

| Family | `semantic_eval_reports.py` | `semantic_reports.py` | `alignment_eval.py` |
|---|---|---|---|
| closed record / field set | `_closed` | `_exact_record`, `_closed_counts` | `_object` |
| non-blank string | `_nonblank` | `_nonblank_string`, `_packet_report_nonblank` | `_nonblank` |
| sha256-hex digest | `_digest` | `_analysis_digest`, `_packet_report_digest` | `_sha256`, `_canonical_sha256` |
| non-negative / bounded int | `_integer` | `_nonnegative_int`, `_analysis_nonnegative_int`, `_positive_analysis_int` | `_nonnegative_integer`, `_session_count` |
| relative path | `_relative_path` | — | `_relative_path` |
| boolean | `_boolean` | — | — |

Firing tests for the D5-D10 consolidations are written against the intended
canonical owners and marked strict-xfail until their owning slice.

Every pin's docstring embeds its full reproduction recipe so a zero-context
implementer needs no session scratchpad: the wrapped two-line invariant
fixture text, the exact `../escape.py` / `/abs/x.py` / `src\util.py` mapping
tokens, the probe byte sequences for `\r`, `\f`, `\v`, `\x85`, U+2028, and
U+2029, and the contention/death-injection setup for the lock-cleanup pin.

Stop gate: each new test fails on the current tree for the documented
reason (expected-red per the gate expectations above); strict-xfail markers
are in place for pins owned by later slices.

### Spec-Promotion Slice: promote [INV-11] with bindings

Promote the Proposed Spec Delta into specs 05, 06, and 07 exactly as written
above: verify all three pre-promotion SHA-256 values, apply the finding-#10
[SEM-3]/[EVC-9.1] text-first corrections, and insert the
`## 11. Phase Hardening Invariants [INV-11]` section at the stated insertion
point, and land the `Tests-invariant:` binding markers on the Slice 0 pins
and `tests/test_canonical_owners.py` in the same change (Strategy B, atomic
with bindings, per [INV-5]). The same change also adds the reciprocal
code-side `Spec: [INV-11]` backlink markers in each mapped module —
`grammar.py`, `models.py`, `repository_snapshot.py`, `settings.py`,
`semantic_packets.py`, `code_parser.py`, `obligation_runtime.py` — closing
spec-to-code reciprocity atomically with the promotion. The invariant statements intentionally describe
the post-hardening steady state; bindings whose tests stay strict-xfail
until Slices 3/5a/5b are justified in the Proposed Spec Delta. Record the
post-promotion SHA-256 for each touched spec in the slice record. Stop gate: self-corpus
`backstitch check` stays green with the new invariants reported as bound
(zero `INVARIANT_UNTESTED`, `INVARIANT_UNKNOWN`, `INVARIANT_DUPLICATE`);
`backstitch obligation list` shows the new invariants as obligations.

### Slice 1: One canonical owner (D1-D5, D9, NM2)

Create/extend the single owners and migrate all consumers in the same change:
create `backstitch/canonical.py` housing `canonical_json_bytes` (with
`allow_nan=False`) and the shared `\n`-only line-slicing helper (split and
span primitives; the only production call sites of `str.splitlines` /
`bytes.splitlines` outside the exemption table below live here — none, after
migration, since the helper splits on `\n` explicitly); `SHA256_HEX_RE` and
the candidate-ref grammar in `grammar.py`; `issue_sort_key` beside `Issue`
in `models.py` (prove byte-identical to all three copies first); bounded
no-follow read + one stat-identity tuple exported from `repository_snapshot`
and consumed by every closed-inventory caller (upgrading NM2's weaker
identity); a `contract_validation.make_validators(error_cls, policy)` factory
with thin family-preserving wrappers replacing the triplicated mechanics only
after the Slice 0 D5 characterization tests pass, and public re-exports for
the names `alignment_eval` currently imports privately from
`evidence_discovery`; `settings.is_excluded` replacing
`repository_snapshot._is_excluded`. Add `backstitch/canonical.py` to the
[INV-11] `_Implementation mapping_:` block AND add the reciprocal code-side
`Spec: [INV-11]` backlink marker inside `backstitch/canonical.py` in the
same change, so mapping and backlink land atomically and reciprocity never
breaks post-promotion (non-normative mapping refresh, recorded in the slice
record). Delete every superseded copy in the same commit.

INV.CANON.1, INV.SCAN.1, and the INV.LINE.1 call-site rule are enforced by
AST-level enumeration tests in `tests/test_canonical_owners.py`, which holds
the closed allowed-owner table (mechanism -> sole owner module) and the
closed exemption tables. The INV.LINE.1 enumeration covers all three
call-site forms, not `splitlines` alone: `splitlines` calls, ad-hoc
`split("\n")` line splitting outside the shared helper, and manual
newline-count arithmetic. The INV.SCAN.1 enumeration test carries no
exemption row for the legacy live-scan path: it is marked strict-xfail
until Slice 5b deletes the path itself, per the late-binding justification
in the Proposed Spec Delta (R2-2) — the test never passes while the live
twin exists.

`splitlines()` call-site enumeration (grep of the 2026-07-16 tree; the
INV.LINE.1 boundary is exactly this set plus the exemption table):

| File | Sites (line) | Disposition |
|---|---|---|
| `alignment_eval.py` | 1237, 1275, 2314, 2315, 2646 | migrate — span slicing and diffs over snapshot bytes |
| `analysis_llm.py` | 332, 333, 349, 350, 368, 369 | migrate — model-claimed span widths |
| `analysis_packets.py` | 86, 175, 299, 308 | migrate — packet excerpt/statement line math |
| `analysis_results.py` | 385 | migrate — line scan feeding spans |
| `artifact_contracts.py` | 238, 428, 507, 599, 1174 | migrate — snippet/section line-count validators |
| `code_parser.py` | 179 | migrate — source line table for receipts |
| `evidence_discovery.py` | 303, 682 | migrate — receipts and line counts (finding #5) |
| `evidence_summary.py` | 59, 159 | migrate — shown-region reconstruction (finding #5) |
| `exclusions.py` | 294 | migrate — skip-directive line numbers |
| `markdown_specs.py` | 616, 695, 947, 1243 | exempt — markdown-it token content is already `\n`-normalized before tokenization and positions come from token maps; no receipt bytes derive from these splits |
| `obligation_runtime.py` | 184 | migrate — line tuple feeding receipts (finding #5) |
| `python_refs.py` | 272, 473, 571 | migrate — declaration statement/marker line math |
| `semantic_eval_reports.py` | 745 | migrate — shown-region logic twin |
| `semantic_packets.py` | 166, 176, 186, 209, 261 | migrate — snippet/section span math (finding #5) |
| `semantic_reports.py` | 1786, 2922 | migrate — JSONL is `\n`-delimited and `splitlines` would split on unescaped U+2028 inside valid JSON strings |

Stop gate: grep proves zero remaining private twins and zero unexempted
`splitlines`, ad-hoc `split("\n")`, or manual newline-count call sites;
full suite green except later-slice xfails; the INV.CANON.1 and INV.LINE.1
enumeration tests in `tests/test_canonical_owners.py` pass.

### Slice 2: Model-boundary correctness (#1, #4, #5, #10)

Fix invariant requirement spans to carry the true multi-line range (producer
emits correct start/end for wrapped statements; validator unchanged); route
all line arithmetic through the Slice-1 `\n`-only helper; mask every resolved
skip directive from requirement projections regardless of target kind (fix
the `valid_skips` filter and the RESERVED_SKIP_MARKER_RE fall-through); remove
the dead `analyze.packet_warnings` config key and policy branches, keep v3
`packet_warnings` exactly `[]`, and reject nonempty schema-3 warnings at load
per the promoted [SEM-3]/[EVC-9.1] correction. Remove the repository's own
`packet_warnings = "report"` setting from `pyproject.toml` in the same change,
and make every schema-3 analysis-report validation require
`packet_warning_count = 0` and `packet_warning_debt = []`, regardless of
current or historical scope; retain warning debt only in the legacy schema-1
report validator as historical presentation vocabulary with no policy or exit
authority.
Slice 2 is the single fixture-regeneration owner for the whole plan:
regenerate every affected packet fixture, golden, and eval artifact here, in
one auditable step; any later slice that invalidates a fixture reopens this
step. Stop gate: Slice-0 pins pass; packet identity changes are enumerated
in the slice record.

### Slice 3: Input hardening and error surface (#2, #7, #8, #9, NM1, NM4,
plus duplicate-token AssertionError and the budget-vs-torn race)

Malformed mapping tokens become per-target deterministic issues (reusing the
existing MAPPING_PATH_* family) filtered before `additional_paths`, in both
lanes; `_validate_semantic_utf8` filters to semantic files before the
unreadable check; mid-read growth past `maximum_file_bytes` after a passing
fstat classifies as torn-capture retry, not budget failure; duplicate
identical mapping tokens produce one deduplicated row (no assertion crash);
packets/analyze catch SnapshotCaptureError and EvidenceDiscoveryError and
render the same clean diagnostics as check/obligation; packets/analyze
exit-1 renders the deterministic report before exiting; `--limit` messages
quote the effective configured bound; `analyze_packets` moves identity
construction inside per-packet containment. Fix #7: the
`maximum_lexical_seeds` dataclass default changes from 100 to 10 — the
packaged TOML and the spec table are canonical, and no non-test artifact
captured under a 100-seed default exists — after which the Slice 0
INV.CFG.2 enumeration pin goes green. Stop gate: hostile-input probes
green; no "internal error" reachable from repository content; first
all-green run of the full non-performance suite (later-slice pins remain
strict-xfail).

### Slice 4: Cache and concurrency (#6, NM3, prompt hash-at-use)

This slice conforms to [SEM-4] explicitly: lock removal happens only by the
owner or an explicit cleanup-lock, and always under the guard — there is no
guard bypass. On provider failure, the original provider error is always
primary: it is chained (`raise ... from`) and mapped into the existing
closed problem vocabulary as `provider_failure`; no new problem fields are
introduced. Cleanup runs under the guard; when the cleanup guard cannot be
acquired within its bounded window, the owned lock is preserved (never
removed guard-free) and cleanup is deferred with a bounded protocol — the
next guarded acquisition of the same key, or bounded deferred cleanup
retries under the guard for a stated bound (the bound is stated in the
slice record), completes it. The terminal state under a persistently
unavailable guard is named: if the guard remains unavailable past the
bound, the path emits explicit guidance naming `backstitch cache
cleanup-lock` as the authorized remover — the operator command that removes
the lock under the guard. The preserved lock is a disclosed intermediate
state, never the terminal one: it never outlives `lock_stale_seconds`
without that guidance being surfaced. This conforms to [SEM-4]: the only
authorized removers are the owner and the explicit cleanup-lock command,
both operating under the guard. A cleanup failure is logged as audit
detail, never surfaced as a problem field, and never displaces the provider
error. On ownership loss, the owner
checks for a published identical-key result and serves it as a hit instead
of corrupt_cache (NM3); prompt bytes are read once at identity-build time
and the same bytes used in the request. [SEM-4] death-injection suite reruns
unchanged. Stop gate: contention tests prove provider_failure surfaces as
the primary problem and no lock is ever removed outside the guard. The
bounded-window requirement distinguishes two outcomes: when the guard
becomes available within the bounded deferred-cleanup retries, the lock is
removed under the guard; under persistent guard unavailability the lock is
deliberately preserved past the window, the past-bound path surfaces the
`backstitch cache cleanup-lock` guidance as the authorized removal route,
and eventual removal happens under the guard whenever it next becomes
available. The gate never requires removal within the window under
persistent guard unavailability — the tested properties are bounded
retries, guarded-only removal, preserved-lock-with-guidance after
exhaustion, and eventual guarded removal on guard recovery.

### Slice 5a: Measured performance fixes (#3, queue/memory items)

Measured perf fixes only — no deletions or moves. Static syntax facts become
opt-in (`parse_python_static_facts` entry point or flag; check's path never
pays); per-path parse memo inside obligation runtime keyed by content hash;
single snapshot capture for `check` when all derived targets are already
captured; markdown parse memo keyed by `(raw_sha256, flags)`; heapq for the
ambiguity worklist; `_Node` stores coordinates and slices bytes from the
snapshot on demand. Stop gate: the INV.PERF.1 deterministic-work pins pass
(zero static-syntax parses, at most one capture, at-most-once parsing per
file in `obligation list`); the marked non-normative wall-clock budget tests
pass with margin and observed timings are recorded.

### Slice 5b: Consolidation deletions and moves (D6, D8, D10)

Split out with its own independent review gate: an independent reviewer
passes this slice separately before Slice 6 starts. A coverage-diff
migration gate precedes any deletion: run coverage over the tests slated for
deletion, diff it against snapshot-path coverage, and migrate every unique
coverage item to the snapshot path first — only then delete the live scan
pipeline and legacy `generate_packets` producer plus their dead tests (D6),
flipping the INV.SCAN.1 enumeration pin from strict-xfail to green in the
same change. Fix the stale
`artifact_contracts.py:57` docstring. Move envelope/budget/problem synthesis
from `cli.py` into `obligation_api` (D8) with the response byte-budget
measured on canonical core JSON: this is conformance-restoring, not a spec
delta — [EVC-8.5] defines text output as a rendering of the same core
result with JSON authoritative for automation and requires
`BUDGET_EXHAUSTED` when "a full required response cannot fit", and
[EVC-8.6] requires the same canonical core result object from every
adapter, golden-tested by byte-comparing canonical core JSON; a budget
measured on rendered text would make budget outcomes adapter- and
rendering-dependent, contradicting that contract. Unify the
staging/publication protocol into one helper used by packets and analyze
(D10). Stop gate: coverage-diff gate recorded; suite green after deletions
(the INV.SCAN.1 enumeration pin has flipped from strict-xfail to green);
independent slice review passed.

### Slice 6: Registry family, docs, traceability, self-application

Replace the SEMANTIC_ prefix classification with an explicit registry
`family` field (D7) and regenerate `deterministic_issue_codes` from it; add
the parent-plan deviation row for the 8-module split; update
`docs/implementation/08-aligned-intent-read-model.md` and the repository map;
confirm every [INV-11] binding promoted in the Spec-Promotion Slice is now
green (no remaining xfail); run the full gate battery plus
`backstitch obligation list --repo-root .` and record the obligation
dashboard counts in this plan — the new invariants must appear as evaluated
obligations with active evidence. Stop gate: self-corpus gate green
including the new invariants; obligation list shows them bound.

### Slice 7: Post-Review Residuals

Added 2026-07-17 by the post-implementation review (findings table in the
`## Post-Implementation Review (2026-07-17)` section below). Runs after
Slice 6, under this plan's existing rules: failing pins first (7.0 is
expected red on the current tree before any fix), single canonical owner per
mechanism, anti-mocking posture unchanged, checkpoint protocol per Spec
Baseline before starting. With one declared exception, fixes restore
conformance to already-promoted [INV-11] and [EVC-*] text: 7.1 carries
exactly one micro spec delta amending [EVC-9.1]'s bare-CR clause, which is
self-contradictory as written (exact replacement text, promotion strategy,
and pre-edit spec hash are declared inside 7.1); 7.2 is spec-neutral (its
grammar question is resolved against [EVC-8.2]'s written invalid set, and
its obligation-lane shape resolves onto existing [EVC-8.3] fields — see
the review section). This slice does not start until its scoped outside
review passes.

Slice 7 starting checkpoint:
`/tmp/backstitch-evidence-spike.pddboQ/checkpoint-slice-7.patch`
(13,092,385 bytes; SHA-256
`970e09f0d406577e86caf86d71252f86793bb7d965e8d0bb7c5ed03b095e3816`).
The companion 1,262-path intent-to-add manifest is
`/tmp/backstitch-evidence-spike.pddboQ/checkpoint-slice-7-untracked.sha256`
(207,349 bytes; SHA-256
`c71060be308490d41aff18b6b3e5ca3907fdc8c2e7e8938d86ba88d85d77b3c1`).
`git diff --cached --quiet` exits 0; no content is staged.

Read first: the Post-Implementation Review findings table below; [EVC-8.2]
canonical path grammar in `docs/specs/07-verification-and-evidence-cases.md`
(the invalid set enumerates absolute path, backslash, NUL, empty component,
dot-dot component, and surrogate — not single-dot; "no other dot component
is retained" means non-root `.` components normalize away; a declared-token
collision onto one canonical path "fails as invalid input"); the [SC-4]
resolution ladder in `docs/specs/02-*.md`; the [EVC-8.4] core result
envelope (success carries a result and no problems; failure carries a null
result and problems — there is no mixed shape); the [EVC-9.1]
requirement-text newline rule (CRLF and CR normalize to LF, one output
line per physical source line — self-contradictory for a mid-line bare CR
and amended by 7.1's declared micro-delta); [INV-11] INV.LINE.1 and
INV.CANON.1 in `docs/specs/05-backstitch-invariants.md`; the Slice 1
`splitlines()`
disposition table above (whose `markdown_specs.py` exemption justification
finding 1 disproves); the Slice 4 record's prompt-bytes claim (which
finding 5 contradicts).

Task order is execution order: the span-primitive consolidation (7.3, the
former 7.6) is resequenced ahead of the eval-lane port (7.4, the former
7.3) so the eval lane adopts the final strict primitive rather than
migrating twice.

7.0 — Regression and evasion pins (failing first). Files:
`tests/test_evidence_spike_boundary_pins.py`,
`tests/test_canonical_owners.py`, and the focused existing modules for
cache, alignment-eval, and obligation behavior. Byte policy, stated here
because every newline pin asserts against it: receipts always hash raw
physical bytes addressed at LF-only line coordinates; parser output is a
projection and is never receipt input. Pins:

- Exotic-newline spec fixtures for all seven break-like sequences — CRLF
  (`\r\n`), bare `\r`, `\f`, `\v`, `\x85`, U+2028, U+2029 — one per
  sequence inside an invariant statement, plus a stray `\r` that shifts
  every subsequent markdown-it parser line number, each asserting correct
  requirement spans and receipt bytes under the byte policy above (the
  bare-`\r` fixture additionally asserts amended-[EVC-9.1] requirement
  text: a mid-line bare CR is preserved as content, per 7.1's declared
  micro-delta); and an ordinary-LF control fixture pinning that pure-LF
  inputs are byte-for-byte unchanged by 7.1.
- Path pins, split by cause: (a) a valid `./`-prefixed mapping token
  NORMALIZES to its canonical path and resolution SUCCEEDS in `check` and
  in the obligation lane; (b) genuinely malformed tokens (dot-dot,
  backslash, NUL, empty component, absolute, surrogate code point)
  degrade per-target in
  `check` AND per-target in the obligation lane (list still serves the
  other obligations, no command-global exit 2); (c) a collision pin —
  `./pkg` and `pkg` declared together must fail per [EVC-8.2]'s capture
  rule (two declared tokens normalizing to the same canonical path are
  invalid input), never silently coalesce.
- Candidate-projection eval-lane fixtures for an over-claimed span (end
  past line count) and an absent path (structured error, not KeyError).
- Verify-lane contention pins for BOTH timeout routes: the wait-loop
  (`semantic_cache.py:1962`) and the initial guard acquisition (`:2012`),
  each timing out while a published identical-key result exists (must
  serve the published result, mirroring the analyzer).
- A prompt-mutation preflight test (mutate the prompt resource after
  identity freeze; preflight and budget math must consume the frozen
  identity bytes), alongside 7.6's per-consumer firing tests.
- Owner-pin evasion pins, one per known evasion vector: a
  `json.dumps(..., sort_keys=True, separators=(",", ":"))` spelling that
  omits `ensure_ascii` (byte-identical output, currently invisible to the
  detector); a from-import alias spelling (`from json import dumps as d`);
  `separators` passed as a non-literal (through a local constant); a
  newline-counting helper whose name does not contain `byte` (defeating
  the current name heuristic); and a span-primitive inventory pin
  enumerating `lf_split`-wrapping span helpers and slice/join spellings.

7.1 — Fix `backstitch/markdown_specs.py` exotic-newline handling at the
parser seam (the [EXC-4] parser-owned boundary). Required design — this
REPLACES both the earlier normalize-at-ingestion wording and round 1's
single coordinate-map-for-all-sequences wording, because the seven
break-like sequences split into TWO verified classes (markdown-it-py
repro, 2026-07-17: paragraph `map` line counts advance only for `\r` and
`\r\n`; `\f`, `\v`, `\x85`, U+2028, and U+2029 remain literal in-line
token content):

- (a) CR and CRLF — the only sequences markdown-it actually treats as
  line breaks — get the parser-to-source coordinate MAP: markdown parsing
  operates on the parser's projection of the source, and ALL receipt and
  span emission goes through an explicit parser-line-to-LF-physical-line
  map back to LF-only physical coordinates of the original bytes; bytes
  are never mutated. Where the map is infeasible at a site, that site
  REJECTS the file with a named diagnostic rather than mis-addressing.
- (b) `\f`, `\v`, `\x85`, U+2028, U+2029 — which markdown-it does NOT
  break on — are misaddressed today only by backstitch's own local
  universal-newline splitting (`str.splitlines()` over token content and
  spans, e.g. `markdown_specs.py:971`): replace those local splits with
  LF-only indexing so the five characters remain ordinary in-line
  content. They are NEVER projected into parser line breaks:
  manufacturing breaks markdown-it did not produce would override its
  block classification, which [SC-4] forbids.

Declared micro spec delta ([EVC-9.1] — the one spec edit in this slice):
scoped review exposed a real contradiction in the promoted text. The
[EVC-9.1] requirement-text rule
(`docs/specs/07-verification-and-evidence-cases.md`, ~line 2131) requires
the parser to normalize "CRLF and CR to LF" AND to preserve "one output
line per physical source line" — unsatisfiable for a mid-line bare CR
under [INV.LINE.1]'s LF-only physical coordinates: `alpha\rbeta` is one
LF-physical line, but CR-to-LF conversion yields two output lines.
Resolution: CRLF-only normalization — equivalently, normalization applies
only to a CR at a physical-line boundary (immediately preceding LF); a
bare CR elsewhere is preserved as content in the model projection. The
delta uses promotion Strategy A (active text-first edit to the existing
mapped section); pre-edit SHA-256 of
`docs/specs/07-verification-and-evidence-cases.md` is
`5a9774fa7219010316c57ed30d3f47a3f25f25b422ee7ded4fff86d5ecb57e8f`. The
exact replacement — the sentence

```text
In both cases it UTF-8 replacement-decodes raw bytes, normalizes CRLF and
CR to LF, preserves one output line per physical source line, and joins
lines with `\n` without a final terminator.
```

becomes

```text
In both cases it UTF-8 replacement-decodes raw bytes, normalizes CRLF to
LF, preserves a bare CR that is not part of a CRLF pair as literal
in-line content, preserves exactly one output line per LF-delimited
physical source line, and joins lines with `\n` without a final
terminator.
```

The snippet rule inherits the amendment unchanged ("A snippet uses the
same decode/newline rule"), so its `end_line - start_line + 1`
logical-line count holds under LF-only arithmetic. The delta lands with
7.1 and has a Deviation Log row below.

Reconcile the CRLF expectation at `tests/test_analysis_packets.py:560`
with amended [EVC-9.1]: the test currently expects `\r\n` retained inside
requirement `text`, but CRLF still normalizes to LF under the amendment —
the test pins non-conforming behavior and is corrected in this task (text
becomes the LF-normalized projection; physical coordinates are unchanged;
receipts still hash raw bytes). Remove the false exemption justification
from the `tests/test_canonical_owners.py` exemption table and migrate or
re-justify each `markdown_specs.py` site honestly. This task is
INV.LINE.1 conformance-restoring in mechanism and carries exactly one
declared spec change: the [EVC-9.1] bare-CR micro-delta above.

7.2 — Canonical path normalization and obligation-lane degradation. Build
ONE exposed canonicalizer with this explicit normalization ORDER: (i)
surrogate code-point rejection, before any Unicode processing; (ii)
Unicode NFC normalization of the token (canonical paths are NFC per
[EVC-8.2], so canonically-equivalent spellings converge before collision
detection); (iii) removal of exactly one permitted trailing directory
slash (`pkg/` addresses catalog path `pkg` per [EVC-8.2]; `pkg//` remains
invalid because its empty component survives to rejection); (iv) root `.`
sentinel resolution (the repository root is the one special row `.`);
(v) single-dot component removal; then (vi) rejection, on the normalized
NFC form, of empty components, dot-dot components, NUL, backslash, and
absolute paths — with surrogates already rejected at step (i), this
completes the [EVC-8.2] invalid set, which round 1 stated without the
surrogate and NFC requirements. Collision detection runs on the final
NFC-canonical form, so canonically-equivalent declared tokens cannot
evade the required collision failure. Use the canonicalizer across target
capture, resolver keys, symbol inventories, and `Edge.code_path` emission
(the `resolver.py:243` ladder area) — not just
`repository_snapshot._normalize_lookup_path`. Collision behavior: two
declared tokens normalizing to the same canonical path fail capture per
[EVC-8.2] (7.0 pin (c), which adds an NFC-equivalence collision fixture
and a `pkg//` invalid fixture).

Output shape for the obligation lane (`cli.py:1447`), corrected to a
LEGAL projection after reading [EVC-8.3]'s closed row and result schemas
(spec 07, `obligation list` rows and `obligation.get` at ~lines
1460-1534): obligation rows carry NO diagnostic field; the
`blocking_reason_codes` / `blocking_reasons` vocabulary is closed
(`IMPLEMENTATION_UNTRACED` through `SKIPPED`) and excludes
MAPPING_PATH_*; and the `unaddressable_intent` row's diagnostic is
reserved for identity defects per [EVC-2.1]. Round 1's "MAPPING_PATH_*
projected into per-obligation rows" is therefore not schema-legal and is
replaced. A malformed mapping surfaces entirely through fields that
already exist: (1) it is an honest one-sided declaration row in
`--summarize-evidence`, whose `declared_target` preserves the unresolved
or ineligible token ([EVC-8.3]: "a broken mapping is an honest one-sided
declaration row"); (2) the affected obligation's existing readiness
fields — `alignment_state`, `disposition`, `gate_state`, and
closed-vocabulary blocking reasons such as `IMPLEMENTATION_PARTIAL` or
`IMPLEMENTATION_UNTRACED` — reflect the unsatisfied role, with NO new
fields; (3) the exact MAPPING_PATH_* resolver diagnostics stay
first-class in the evidence universe per [EVC-7] (`resolver_issue` is a
closed discovery basis, "every raw resolver issue targeted to the
obligation" seeds its candidates, and `issue_target` is the closed
relation kind), and in `backstitch check`'s per-target degradation.
`obligation list` keeps serving every other obligation with no
command-global exit 2, and no problems are emitted alongside a result —
[EVC-8.4]'s envelope forbids the mixed shape (success carries a result
and no problems; failure carries a null result and problems). Because
existing fields legally carry the failure, no [EVC-8.4] schema delta is
needed and 7.2 is spec-neutral.

[SC-4] reconciliation: rung 1 calls the exact spelling "the only spelling that
resolves without a finding", but [EVC-8.2] already removes a trailing
slash "before lookup" (`pkg/` addresses catalog path `pkg`), so rung 1
exactness cannot mean byte-identical spelling — it means exact
CANONICAL-path matching. Canonicalization therefore runs before the
ladder; `./pkg` resolves silently at rung 1; the finding-bearing rungs
(2-3) remain reserved for inferred suffix/basename matches. The
[EVC-8.2] descriptor walker keeps its strict rejection of any dot
component still present post-normalization (defense in depth at the open
boundary). Conforms to [EVC-8.2] as written (single-dot is not in the
invalid set; non-root dot components are normalized, not retained).

7.3 — Consolidate the four span-primitive spellings into ONE canonical
helper in `backstitch/canonical.py` taking an explicit policy argument
(`clamped` versus `strict`), and harden the AST owner pins. The current
spellings — `canonical.lf_slice` truncation, the two `_line_span` clamps
in `evidence_discovery.py` (`:293`) and `evidence_summary.py`, and the
strict `_span_bytes` in `semantic_eval_reports.py` — all migrate to the
helper. Span-policy behavior matrix, pinned per cell:

| Case | policy=clamped | policy=strict |
|---|---|---|
| empty input | empty bytes | error (no addressable lines) |
| zero or negative start | clamp start to line 1 | error |
| reversed span (end < start) | empty bytes | error |
| start past EOF | empty bytes | error |
| end past EOF | clamp end to line count | error |
| terminal LF | the final LF terminates the last line; no phantom line N+1 | same (shared line arithmetic) |

Caller behavior changes, enumerated: the two `_line_span` clamp sites
keep clamped semantics via `policy=clamped` (no behavior change);
`_span_bytes` keeps strict semantics via `policy=strict` (no behavior
change); every `lf_slice` caller is audited and dispositioned in the
slice record — validated-span paths move to strict (the eval lane's
behavior change lands in 7.4: rejection instead of silent truncation),
display-only paths keep clamped. INV.LINE.1's singular-helper wording is
satisfied without a spec edit: one function with an explicit policy
parameter is exactly one owner of the slicing arithmetic with declared
variants, not a second implementation. AST pin hardening closes finding
7's remaining evasion vectors: the detectors resolve imports and aliases
before matching (module-import, from-import, and `as`-alias bindings map
back to canonical targets); `separators` values are matched by constant
propagation, and non-literal separators are rejected by the pin outright;
the newline-count detector becomes structural — matching the counting
expression shape — instead of firing only on names containing `byte`; and
the span-helper inventory is defined syntactically as direct `lf_split`
calls, aliased `lf_split` calls, and the slice/join pattern over split
lines. `cli.py:564` and `:807` receive an explicit display-only exemption
row with the stated reason: they render error details into failure
messages, not identities. Each closed evasion has its 7.0 evasion pin.

7.4 — Port the gold lane's path-existence and `end <= line_count` span
validation into `alignment_eval._candidate_projection` (`:2584`), built on
7.3's strict-policy primitive; failures raise `AlignmentEvalError`, never
a bare `KeyError`; no silent `lf_slice` truncation of over-claimed spans
in the eval lane.

7.5 — Add the verify-lane `lock_timeout` -> published-result fallback in
`backstitch/semantic_cache.py` on BOTH contention routes — the wait-loop
(`:1962`) and the initial guard acquisition (`:2012`) — mirroring the
analyzer twin, implemented as one shared fallback helper used by the
analyzer and verifier paths per the canonical-owner discipline (a fix
landing in only one twin is the defect class this plan exists to remove).
Both routes have 7.0 pins.

7.6 — Define and enforce the prompt-identity lifecycle: identities are
frozen exactly once per run and threaded through report validation,
preflight, cost accounting, cache inspection, and execution; after the
freeze, no consumer reads prompt resources again. Migrate all EIGHT
prompt-read sites to the frozen `identity.prompt_bytes`:
`semantic_analysis.py:458` (correcting this plan's earlier `:485`
citation), `:588`, `:1372`; `semantic_reports.py:2477`, `:2768`;
`semantic_eval.py:399`, `:838`; and `analysis_llm.py:305`/`:439` — the
legacy adapter seam, decided as migrate rather than exempt-with-reason
because it builds the inference identity adjacently and must consume the
same frozen bytes. An ownership pin (AST or seam-level) forbids
prompt-resource reads after freeze, and each of the eight sites gets a
per-consumer firing test. Then append the dated correction note under the
Slice 4 record (append-only; do not rewrite the original text) stating
that its "budget/preflight calculations consume those same bytes" claim
did not hold for these sites until this slice.

7.7 — Documentation residuals: add
`docs/implementation/02-repository-map.md` rows for `canonical.py` and
`contract_validation.py` and refresh the stale `grammar.py` entry; fix the
deleted-`scan_repository` reference at
`docs/implementation/04-backstitch-style-traceability.md:29`; fix the stale
"xfails remain" docstring at
`tests/test_evidence_spike_cache_perf_pins.py:3`. Verification is by
inspection, stated explicitly: these fixes have no runtime surface and
inspection-only acceptance is deliberate. The `canonical.py`
repository-map row is additionally covered by an INV.CANON.1
cross-reference note tying the row to the invariant's owner inventory.

Stop gate: all 7.0 pins green, including the owner-pin evasion pins; full
non-live battery, performance budgets, self-corpus gate (zero errors,
warnings, and unsuppressed issues), and `obligation list` all green; zero
xfail anywhere in the non-live suite.

Independent slice review: a scoped outside review of this slice's text
gates the start of implementation (recorded in the Status header); a second
independent review runs after the stop gate, per this plan's review loop.

## Testing Plan

Anti-mocking rules inherit from the parent plan. Real repositories, real
subprocesses for CLI behavior, real filesystem publication, real lock files
under real contention (threads/processes, not mocks). Every touched
enumerable contract element keeps or gains a firing test.

Wall-clock performance budgets are explicitly non-normative: they live only
here and in marked `tests/performance/` tests, never in spec text. The
budgets are `backstitch check` on the self-corpus within 0.7s and
`backstitch obligation list` within 3s, each with generous CI-variance
headroom; the marked tests can be excluded on constrained runners but run by
default locally. The normative INV.PERF.1 contract is the deterministic work
bound (zero static-syntax parses, at most one snapshot capture, at-most-once
parsing per unique file), tested machine-independently.

## Required Reading and Comprehension Gates

Before touching Slices 2 or 4, the implementer answers these in the slice
record; the conforming answers are stated so drift is detectable:

1. Which fields form the snapshot identity preimage? Conforming answer: the
   [EVC-8.2] snapshot preimage fields, exactly as enumerated there — no
   additions, no omissions.
2. Who may remove a verify lock, and under what guard state? Conforming
   answer: only the owner or an explicit cleanup-lock, and always under the
   guard, per [SEM-4]; there is no guard-free removal path.
3. What bytes feed `packet_hash`? Conforming answer: the canonical
   model-visible projection JSON (`canonical_json_bytes` of the packet
   projection), not rendered text and not trusted metadata.

## Verification Commands and Gates

Per slice and before any completion claim:

```text
uv run pytest --ignore=tests/live -q
uv run pytest tests/acceptance -q
uv run pytest tests/performance -q
uv run ruff check backstitch tests && uv run ruff format --check backstitch tests
uv run mypy backstitch
uv run backstitch check --repo-root .            # exit 0, zero findings
uv run backstitch check --repo-root . --show-suppressions
uv run backstitch obligation list --repo-root .  # dashboard recorded
time uv run backstitch check --repo-root .       # observed wall time recorded
git diff --check
```

## Independent Review Loop

Class 5: independent review of this plan before implementation (different
agent family preferred), plus the codex second review requested by the owner.
Independent slice review after Slices 1, 3, 5a, 5b (its own mandatory gate
before Slice 6, per the serial order), and 6. Findings are
incorporated or explicitly dispositioned in the review record below. Fresh-
eyes review before completion: reviewer starts from public help on a clean
fixture, exercises the hostile-input probes, and re-times the deterministic
lane.

## Out of Scope

- any new product surface, config keys, CLI commands, or MCP work
- the parent plan's Phase A/B rerun, Linux runner identity, and packet-report
  size ceiling residuals (tracked there; this plan does not subsume them)
- refactoring `_resolve_references` and the report-validator extraction
  beyond what Slice 1's shared validators require (recorded as follow-up
  candidates, not silently attempted here)
- committing/landing: this plan completes uncommitted; landing is a separate
  owner decision after both reviews pass

## Execution Record

### Slice 0 baseline and expected-red record (complete, 2026-07-17)

- Baseline commit: `25346a988ad2022237160261aa61d2692d5baaa4`.
- Checkpoint: `/tmp/backstitch-evidence-spike.pddboQ/checkpoint-slice-0.patch`
  (SHA-256 `2d32666d05bad9b873edbd556cbefaae4dd0ee532bd96d472d07e2c162ef1a4d`).
- Untracked manifest:
  `/tmp/backstitch-evidence-spike.pddboQ/checkpoint-slice-0-untracked.sha256`
  (1,256 files; SHA-256
  `dace5911afef23e352fcb5e7a6755d97751ca4353746c91896ca4b9880e7b8ed`).
  The literal `git ls-files --others` command returns zero entries after
  `git add -A -N`; the manifest therefore derives from
  `git diff --name-only --diff-filter=A -z HEAD`, which enumerates the same
  intent-to-add paths without losing their pre-slice untracked identity.
- Baseline verification rerun before pins:
  `uv run pytest --ignore=tests/live -q` exited 0;
  `uv run backstitch check --repo-root .` exited 0 with zero errors, warnings,
  and infos.
- Expected-red pins are being recorded in
  `tests/test_evidence_spike_boundary_pins.py`,
  `tests/test_evidence_spike_cache_perf_pins.py`,
  `tests/test_canonical_owners.py`, and focused existing test modules. Slices
  4/5a/5b owner pins are strict-xfail and fail under `--runxfail` for their
  named pre-fix reason.
- Integrated expected-red gate after formatting/lint: 26 intended failures,
  8 passes, and 17 strict xfails across the focused Slice-0 suite. Running the
  17 strict xfails with `--runxfail` produced 17 failures at their named
  production seams. The additional six-case schema-3 report finding-#10 pin
  has four intended failures (count-only and internally consistent debt under
  both scopes) and two passes where the older count-consistency rule already
  rejects debt-only forgeries. All touched test files
  pass Ruff after correcting one initially misplaced test insertion that had
  split an existing test body.
- Non-normative wall-clock pins live in
  `tests/performance/test_evidence_spike_wall_clock.py`, are marked
  `performance` plus strict-xfail until Slice 5a, and fail under `--runxfail`
  at 1.835 s for default `check` (0.7 s budget) and 6.036 s for `obligation
  list` (3.0 s budget). The earlier shell characterization was approximately
  1.79 s / 7.76 s; both measurements confirm the intended seam.
- After removing premature binding syntax from late-slice pin docstrings and
  making fixture reproductions parser-safe, `uv run backstitch check
  --repo-root .` again exits 0 with 115 sections, 230 mappings, 335 code refs,
  669 edges, 3 invariants, 3 binds, and zero issues. Exact `Tests-invariant:`
  markers still land atomically in the Spec-Promotion Slice as planned.
- Final integrated Slice-0 gate: 30 expected failures at the named production
  seams, 17 passing characterization/boundary cases, and 19 strict xfails.
  `git diff --check` passes for every Slice-0 file.
- Pre-promotion rollback checkpoint:
  `/tmp/backstitch-evidence-spike.pddboQ/checkpoint-spec-promotion.patch`
  (12,918,896 bytes; SHA-256
  `5109517bcc6853a402a08041c9246af946b0a4a2f91f94f5f2b7b88612d0f191`).
  The companion intent-to-add manifest is
  `/tmp/backstitch-evidence-spike.pddboQ/checkpoint-spec-promotion-untracked.sha256`
  (SHA-256
  `5a5c84d474b11b5f2bcd26d9b192abf617fbf54de51b465177cbf5cced6aee8e`).
  `git diff --cached --stat` remains empty: no file contents were staged.

### Spec-Promotion Slice record (complete, 2026-07-17)

- All three pre-promotion hashes matched the plan exactly before editing.
- Post-promotion SHA-256 values:
  `docs/specs/05-backstitch-invariants.md`
  `1d536638c5dedde1894035d0d7849d0c89ea11f6a8bd2158ad39b25ff695d581`;
  `docs/specs/06-semantic-gates.md`
  `bf0258a5bea9bc0a68b05372c646c3f383a1276216a2a577c8527cbb96f4f166`;
  `docs/specs/07-verification-and-evidence-cases.md`
  `5a9774fa7219010316c57ed30d3f47a3f25f25b422ee7ded4fff86d5ecb57e8f`.
- [INV-11] and the exact finding-#10 SEM/EVC corrections landed together
  with 11 `Tests-invariant:` binds and reciprocal [INV-11] backlinks in the
  seven mapped modules. `git diff --check`, Ruff formatting, and Ruff lint all
  pass on the promotion surface.
- `uv run backstitch check --repo-root .` exits 0 with 116 sections, 237
  mappings, 341 code refs, 683 edges, 8 invariants, 14 binds, and zero issues.
- `uv run backstitch obligation list --repo-root . --format json --limit 100`
  reports INV.CANON.1, INV.LINE.1, INV.SCAN.1, INV.PERF.1, and INV.CFG.2 as
  `executable` with complete alignment. The default 50-row page lists only the
  three earlier code invariants, so the explicit 100-row gate is required to
  observe the new spec-declared rows without pagination.
- Slice-1 starting checkpoint:
  `/tmp/backstitch-evidence-spike.pddboQ/checkpoint-slice-1.patch`
  (12,925,391 bytes; SHA-256
  `cb35757a302d6c0a5b454a6af10cf64b635864878a4c7c00ab131e59630ef0e5`).
  Its companion intent-to-add manifest SHA-256 is
  `5a5c84d474b11b5f2bcd26d9b192abf617fbf54de51b465177cbf5cced6aee8e`;
  staged content remains empty.

### Slice 1 canonical-owner record (complete, 2026-07-17)

- Added `backstitch/canonical.py` as the sole canonical-JSON and LF-only
  line-primitive owner; extended `backstitch/grammar.py` for SHA-256 and
  candidate references; moved deterministic issue ordering beside `Issue`;
  and migrated every inventoried consumer. The closed AST inventory passes
  for canonical JSON, SHA/candidate grammar, issue sorting, LF arithmetic,
  no-follow reads/stat identity, and exclusions. Only the planned Slice-6
  diagnostic-family pin remains xfailed in `tests/test_canonical_owners.py`.
- Added `backstitch/contract_validation.py` and retained each artifact
  family's error class, NFC/surrogate policy, digest form, integer minimum,
  path return type, and boolean behavior through thin wrappers. The D5
  characterization suite passes.
- `repository_snapshot.read_regular_nofollow` now owns bounded stable reads
  for repository, configuration, alignment-eval, and semantic-eval callers;
  `settings.is_excluded` and the shared six-field stat identity are their sole
  owners. The owner test was strengthened to catch colon-join candidate-ref
  constructors and the previous `open`/`lstat`/`fstat`/`read` stable-reader
  twin shape.
- The [INV-11] mapping refresh added `backstitch/canonical.py` and
  `backstitch/contract_validation.py` with reciprocal code backlinks in the
  same slice. The current spec-05 SHA-256 is
  `7a03f3940d3c403ca5505218d185dfb38443992238de159055c6e1409c7aced2`.
- Focused canonical-owner, settings, snapshot, semantic-eval, alignment-eval,
  cache, and discovery suites pass with only the expected Slice-6 xfail.
  `uv run ruff check backstitch tests`, `uv run ruff format --check
  backstitch tests`, and `uv run mypy backstitch` pass. The self-corpus check
  exits 0 with 116 sections, 239 mappings, 343 code refs, 8 invariants, and
  zero errors, warnings, or infos. The promoted invariant acceptance probe
  now asserts all 8 invariants and 14 binds and passes.
- The full non-live, non-performance run exposed 26 failures: 25 were the
  exact Slice-2/3 expected-red pins, while one was a stale acceptance count
  from before promotion. The acceptance expectation was corrected and its
  targeted probe passes; the 25 later-slice pins remain intentionally red.
  The full all-green gate remains assigned to Slice 3 by this plan.
- Scoped `git diff --check` passes for the Slice-1 surface. The repository-wide
  command still names two pre-existing trailing-space lines in
  `tests/semantic_eval/v3/qualification-candidate/independent-review.md`;
  they were present in the starting checkpoint and were not cleaned outside
  this plan's scope.
- Independent review first found two hidden candidate/read owners and one
  surrogate-validation regression. After those fixes, the strengthened owner
  detector exposed the configuration reader as the final bounded-read twin.
  It too was migrated, its implementation-coupled tests were moved to the
  shared-reader boundary, and the follow-up independent review returned PASS
  with no scope expansion or remaining in-scope reader twin.
- Slice-2 starting checkpoint:
  `/tmp/backstitch-evidence-spike.pddboQ/checkpoint-slice-2.patch`
  (12,936,774 bytes; SHA-256
  `8b97552ce73917b02a7891e5aaeb94cbe5832bac15746acf737d6cb4cad21b39`).
  Staged content remains empty; implementation is still intentionally
  uncommitted per the plan's Out of Scope section.

### Slice 2 model-boundary record (complete, 2026-07-17)

- Finding #1 now carries the true inclusive end line for wrapped invariant
  requirements through packet production and the unchanged strict v3 loader.
  Finding #4 masks every parser-resolved same-path skip directive regardless
  of target kind and also masks the reserved-marker fallback. Finding #5 uses
  the Slice-1 LF-only boundary: CR remains ordinary content rather than an
  invented line break.
- Finding #10 removed `analyze.packet_warnings` from settings, packaged
  defaults, repository configuration, analyzer policy, and result production.
  Schema-3 packets require `packet_warnings == []`; current and historical
  schema-3 analysis reports require warning count zero and empty debt. Legacy
  schema-1 report and schema-1/2 packet warning vocabulary remains intact.
- Focused packet/Markdown/semantic/report/settings/analysis/artifact tests all
  pass. The Slice-0 #10 config, loader, and six-case report pins contribute 8
  passing cases. Phase-C, semantic-eval, replay acceptance, and behavior-golden
  verification passes. Ruff formatting/lint and full package MyPy pass.
- The single-owner regeneration audit found no frozen artifact with an
  affected shape. Phase-C uses only one-line invariants, section-only or
  zero-packet skip cases, and LF bytes; both semantic-eval v3 corpora are
  section-only, skip-free, and LF-only; the legacy v1 invariant is one line;
  finding #10 is packet-identity neutral. Therefore no fixture was regenerated.
  The unchanged audit anchors are: Phase-C manifest
  `2244a9ba5a7b5e09e376ffaa9d053bf6c073a1d8349b1d7525f27928267072ad`,
  v3 smoke manifest
  `35b63a39da2456715edd8563c4866a5e92e85a8494c46c74b403ce9e0714f7f2`,
  qualification-candidate manifest
  `b5f63053bc14683e5802210ebf6eb78dfa3e19b8d799cdbba0baf8cb1937a71a`,
  and behavior golden
  `083d1154ce0623328b1b528c3784bd2714ce8e5c9d6b0d626c5f6fd09595675f`.
  The no-write qualification generator check exits 0.
- Packet identity changes are bounded and enumerated: wrapped requirement end
  lines change current self-packets for INV.CANON.1, INV.LINE.1, INV.SCAN.1,
  INV.PERF.1, and INV.CFG.2. No prior frozen v3 self-packet artifact exists.
  Section identity changes only for a leaked foreign-target/reserved skip;
  non-LF receipt identity changes only when those bytes exist. No audited
  frozen corpus meets either condition.
- The full non-live, non-performance suite now has exactly 16 failures, all
  named Slice-3 expected-red pins, plus the 10 planned strict xfails owned by
  Slices 4, 5a, 5b, and 6. Self-corpus exits 0 with 116 sections, 239 mappings,
  343 code refs, 8 invariants, and zero errors, warnings, or infos.
- Slice-3 starting checkpoint:
  `/tmp/backstitch-evidence-spike.pddboQ/checkpoint-slice-3.patch`
  (12,937,812 bytes; SHA-256
  `c5f0f58751dd1d568fea29ebc21447f6a6aac301bb0a402703f4b90ee0190d79`).

### Slice 3 hostile-input and error-surface record (complete, 2026-07-17)

- Unsafe mapping tokens are filtered before `additional_paths`. Check emits
  located MAPPING_PATH_* deterministic issues; obligation projection emits one
  existing-shape `INVALID_INPUT` problem per malformed target. Details remain
  exactly `{field, reason}` under active [EVC-8.4], with token, source path,
  and line encoded in reason. Multi-target problems use canonical [EVC-8.4]
  order, proven by a fixture whose source order is the reverse of output order.
- Identical same-line unresolved mapping tokens now merge to one evidence atom
  while retaining both source declaration receipts. Non-semantic unreadable
  additional paths are filtered before semantic UTF-8/readability validation.
- Packets/current-analyze map typed snapshot/discovery failures without the
  catch-all `internal error` label and render deterministic reports before
  exit 1. Effective `--limit` errors quote the configured maximum. Per-packet
  identity and prompt construction is inside the containment loop.
- The concrete `maximum_lexical_seeds` dataclass default now matches the
  canonical packaged value 10. Mid-read growth after a matching opening fstat
  is classified as torn capture/retry; a stable file already over budget still
  produces `budget_exceeded`.
- All 16 Slice-3 expected-red cases are green. The full non-live,
  non-performance suite exits 0 with only the planned later-slice strict
  xfails. Phase-C was aligned with the required report-before-exit behavior and
  its full suite passes. Ruff lint/format, full package MyPy, focused hostile
  probes, and self-corpus all pass; self-corpus remains at 116 sections, 239
  mappings, 343 code refs, 8 invariants, and zero issues.
- The initial located-problem test incorrectly coupled raw backslash tokens to
  JSON-encoded substring representation; it now inspects parsed structured
  details. Independent review then caught that an optional `line` detail would
  violate active [EVC-8.4], that only the first malformed target was projected,
  and that source order was not canonical problem order. All three were fixed;
  the follow-up review verdict is PASS with no remaining P1/P2 or scope
  expansion.
- Slice-4 starting checkpoint:
  `/tmp/backstitch-evidence-spike.pddboQ/checkpoint-slice-4.patch`
  (12,948,873 bytes; SHA-256
  `f4e6f355e201737405d0257f3e0c501c0f5481240636c9611e0816b5ea497f67`).

### Slice 4 cache and concurrency record (complete, 2026-07-17)

- Provider exceptions remain the chained cause and the sole existing
  `provider_failure` problem; cleanup failures never replace them or alter a
  problem field. Cleanup exhaustion is audit/log detail with the exact
  `backstitch cache cleanup-lock` recovery guidance.
- Owned-failure cleanup performs exactly 8 guarded attempts. Each guard attempt
  is bounded by `poll_interval_seconds`, so the nominal retry window is at most
  `8 * poll_interval_seconds` plus scheduler/filesystem overhead. Transient
  contention removes the unchanged owned lock under the guard. Persistent
  contention preserves it, logs guidance, and leaves process-local deferred
  state for the next guarded participant; explicit cleanup retains its own
  guarded audit-before-removal path with deferred draining disabled.
- Analyzer and verifier ownership loss, including an absent lock, now serve a
  valid identical-key published result as a hit. Changed/absent ownership
  without a valid result retains corruption handling and never removes a
  replacement lock. Analyzer/verifier twin tests cover transient and persistent
  cleanup, guarded-only unlink, preserved-lock guidance, next-guard recovery,
  and identical-result recovery.
- Analyzer and verifier prompt bytes are captured once with their frozen
  identities. Descriptor hashing, validation, budget/preflight calculations,
  cache inspection, and provider dispatch all consume those same bytes; later
  prompt-resource mutation cannot change or reject the request.
- A read-only protocol audit caught three first-pass gaps before closure:
  cleanup guidance was entering the public problem message; absent-lock
  ownership loss skipped result recovery; and several verifier budget/preflight
  consumers still reread prompt resources. It also required analyzer twin
  tests. All were corrected without new problem fields or commands.
- Correction (2026-07-17, Slice 7.6): the preceding claim that analyzer
  descriptor validation, budget/preflight calculations, cache inspection, and
  dispatch all consumed the same frozen prompt bytes did not yet hold at the
  eight residual consumer sites enumerated in Slice 7.6. Slice 7.6 freezes each
  analyzer inference identity once at run entry and threads that identity or
  its prompt bytes through those consumers, including semantic-eval replay and
  the legacy adapter seam. The original execution record remains above
  unchanged.
- The full semantic test family passes (627 cases). The full non-live,
  non-performance suite exits 0 with only the six Slice-5a/5b strict xfails and
  the Slice-6 diagnostic-family xfail. Ruff lint/format, full MyPy, and
  self-corpus pass; self-corpus has 116 sections, 239 mappings, 344 code refs,
  8 invariants, and zero issues.
- Slice-5a starting checkpoint:
  `/tmp/backstitch-evidence-spike.pddboQ/checkpoint-slice-5a.patch`
  (12,967,023 bytes; SHA-256
  `5f26bdf16c16d367650be96717abe2c894098a1a9cee48b12ba0404da1cd625f`).

### Slice 5a measured-performance record (complete, 2026-07-17)

- Static syntax facts are opt-in; the advertised default check derives none.
  Python parse products are invocation-scoped and keyed by repository path plus
  content hash. The obligation-list pin now covers both an in-root symbol and
  an exact out-of-root `path::symbol` target, with each unique file parsed at
  most once.
- Default check enters the snapshot capture owner once. The owner retains the
  existing bounded [EVC-8.2] target-set convergence internally; the self-corpus
  proof distinguishes one external owner invocation from its two current
  internal whole-capture attempts. Markdown parse products are shared by
  `(raw_sha256, flags)` without retaining path-specific parsed-spec state.
- Ambiguity expansion uses a heap while preserving candidate-ID ordering and
  work accounting. Discovery nodes retain coordinates rather than copied source
  spans and slice exact bytes from the authority-checked immutable snapshot on
  demand.
- The first independent pass found that an out-of-root symbol target populated
  no parse memo and was reparsed during atomic-ownership derivation. It also
  found that pruning definition discovery had accidentally pruned valid
  expression-nested backlink comments. Both correctness defects received
  regressions and were fixed: symbol inventory writes through to the shared
  memo, while full comment discovery remains separate from pruned owner
  discovery. A stale-config test was repaired to prove changed file identity
  even after the original bytes are restored. Follow-up verdict: **PASS**, no
  unresolved P1/P2 findings.
- Five final subprocess samples measured default `check` at median 0.66s
  (range 0.65-0.67s, budget 0.7s) and `obligation list` at median 0.68s
  (range 0.67-0.69s, budget 3.0s). The pre-slice measured baselines were 1.80s
  and 5.93s respectively. Both marked performance tests pass.
- The full non-live, non-performance suite exits 0 with only the three Slice-5b
  strict xfails and the Slice-6 diagnostic-family xfail. The complete
  performance directory, full MyPy, Ruff lint/format, and scoped diff check
  pass. Self-corpus exits 0 with 116 sections, 239 mappings, 344 code refs,
  8 invariants, and zero unsuppressed issues; configured suppressions remain
  visible under `--show-suppressions`.
- No deletion, response-budget move, publication-protocol consolidation,
  fixture regeneration, or other Slice-5b work entered this slice.
- Slice-5b starting checkpoint:
  `/tmp/backstitch-evidence-spike.pddboQ/checkpoint-slice-5b.patch`
  (12,983,884 bytes; SHA-256
  `61b84c5a3fe4d0b378817530014bd8a56b26c573ea4d0d7140e744488421bfbd`).

### Slice 5b consolidation record (complete, 2026-07-17)

- The required D6 coverage-diff gate ran before deletion. The clean initial
  comparison found 103 shared resolver lines and 63 shared branches exercised
  only through live-scan tests, plus 141 packet-producer lines and 64 branches
  not reached by clean schema-3 tests. Raw pre-migration evidence is retained
  in `/tmp/backstitch-d6-legacy-{resolver,packets}.{coverage,json}` and
  `/tmp/backstitch-d6-snapshot-clean.{coverage,json}`.
- Existing resolver, ladder, SC-10 issue-code, behavior-freeze, check-policy,
  analysis-summary, review-remediation, and snapshot tests were migrated to the
  captured-snapshot/runtime path. Schema-3 packet tests added the three active
  behaviors absent from the clean comparison: relevant-issue filter/order;
  sorted and deduplicated invariant targets/binds including a module owner; and
  fatal `PACKET_BUDGET_EXHAUSTED` with no partial publication. The post-migration
  comparison left zero shared resolver/check lines or branches exclusive to the
  live path; evidence is in
  `/tmp/backstitch-d6-migrated-{resolver,packets}.{coverage,json}`.
- Only after that gate passed, the live `scan_repository*` pipeline,
  `check_pipeline.build_check_report`, legacy schema-2 `generate_packets`
  producer, its exclusive helper call graph, and superseded direct-producer
  tests were deleted. Schema-1/2 artifact loaders, validators, and migration
  diagnostics remain. The forbidden production owner inventory is empty and
  the INV.SCAN.1 pin passes normally and under `--runxfail`.
- D8 moved response-byte budget ownership to
  `obligation_api.apply_response_byte_budget`. It measures canonical core JSON
  bytes before adapter rendering, returns the existing closed
  `BUDGET_EXHAUSTED` shape, and preserves budget-before-deadline ordering. Exact
  canonical-byte and JSON/text outcome tests pass; no deferred MCP surface was
  added.
- D10 moved ordered staging/currentness/publication/cleanup behind the single
  `semantic_reports.publish_artifact_set` owner. Packets and analyze share its
  failed-path and prior-publication accounting; analyze's final currentness
  check remains between staging and publication. Helper, packets, and analyze
  failure proofs use actual filesystem replacement failures and verify partial
  publication, later absence, and temporary-file cleanup.
- Independent review found two P2s: the first stale-comment replacement falsely
  attributed a legacy packet field inventory to schema 3, and publication
  failure tests still mocked the publication primitive. The comment now
  distinguishes legacy schema-less, schema-2 migration, and current schema-3
  roles; all three tests now use real directory-destination failures. Follow-up
  verdict: **PASS**, no unresolved P1/P2 findings.
- All 11 evidence-spike hardening pins pass under `--runxfail`; 38 acceptance
  probes pass. The full non-live suite, including performance tests, exits 0
  with only the Slice-6 diagnostic-family xfail. Full MyPy and Ruff lint/format
  pass. Self-corpus exits 0 with 116 sections, 239 mappings, 339 code refs,
  8 invariants, and zero unsuppressed issues; 199 configured suppressions remain
  visible under `--show-suppressions`. `obligation list --limit 100` exits 0.
- Repository-wide `git diff --check` still reports only the two pre-existing
  trailing-space lines in the qualification-candidate independent review; the
  scoped Slice-5b diff check passes. Staged content remains empty and the work
  remains intentionally uncommitted.
- Slice-6 starting checkpoint:
  `/tmp/backstitch-evidence-spike.pddboQ/checkpoint-slice-6.patch`
  (13,031,661 bytes; SHA-256
  `b079c730a62c6d68902b301c0768ba2bf97fb0975dd6768f6f9849e471b5ca2e`).

### Slice 6 registry, documentation, and self-application record (complete, 2026-07-17)

- All 72 diagnostic registry entries now carry a required closed `family`:
  35 implemented deterministic, 32 reserved deterministic, and 5 implemented
  semantic. `deterministic_issue_codes()` selects exactly the implemented
  deterministic family. Missing and invalid family values have firing tests;
  no `SEMANTIC_` prefix classifier or diagnostic-family xfail remains.
- The parent aligned-intent plan records the accepted eight-module split:
  `alignment_eval`, `alignment_guide`, `evidence_discovery`,
  `evidence_summary`, `obligation_api`, `obligation_runtime`, `obligations`,
  and `repository_snapshot`. The deviation adds no public contract. The
  repository map and aligned-intent implementation note describe the final
  immutable-snapshot, obligation, evidence, packet, diagnostic, and publication
  owners, including removal of the live scan and legacy packet producer.
- `backstitch obligation list --repo-root . --format json --limit 100` exits 0
  with schema 1, `bootstrap_state = intent_found`, 100 first-page entries, a
  non-null next cursor, and zero envelope problems. First-page counts are:
  gate state 56 executable / 44 not executable; alignment 56 complete / 17
  partial / 27 untraced; disposition 100 evaluate; rung 85 active / 15 meta;
  blockers 17 `IMPLEMENTATION_PARTIAL`, 27 `IMPLEMENTATION_UNTRACED`, and 15
  `OUT_OF_GATE_SCOPE`.
- The promoted INV-11 rows `INV.CANON.1`, `INV.LINE.1`, `INV.SCAN.1`,
  `INV.PERF.1`, and `INV.CFG.2` all appear in that page as active, complete,
  evaluate, executable obligations with no blocker. Every hardening and
  canonical-owner pin passes under `--runxfail`; there are no remaining xfails
  in the non-live suite.
- Final five-run timings were default `check` median 0.66s (range 0.65-0.66s)
  and `obligation list` median 0.68s (range 0.67-0.68s), within the marked 0.7s
  and 3.0s budgets.
- Final independent review caught one remaining test-only `SEMANTIC_` prefix
  classifier after production had moved to registry families. The model/spec
  inventory test now derives deterministic membership from `family`; a full
  code/test search finds no prefix classifier. Follow-up verdict: **PASS**, no
  unresolved P1/P2 findings.
- The full non-live suite, including performance tests, passes at 100%. All 38
  acceptance probes pass; full MyPy over 42 source files and Ruff lint/format
  over 121 files pass. The D6 forbidden producer inventory is empty; D8 and
  D10 each retain one canonical owner. Final self-corpus after this closure
  record has 116 sections, 239 mappings, 339 code refs, 8 invariants, and zero
  unsuppressed issues; 199 configured suppressions remain auditable.
- Repository-wide `git diff --check` reports only the two documented
  pre-existing trailing-space lines in the qualification-candidate independent
  review; scoped checks pass. `git diff --cached --quiet` exits 0. No content is
  staged, no commit was created, and the owner must explicitly direct landing.

### Slice 7 post-review residuals record (complete, 2026-07-17)

- The Slice-7 starting checkpoint is
  `/tmp/backstitch-evidence-spike.pddboQ/checkpoint-slice-7.patch`
  (13,092,385 bytes; SHA-256
  `970e09f0d406577e86caf86d71252f86793bb7d965e8d0bb7c5ed03b095e3816`).
  Its 1,262-path intent-to-add manifest is
  `/tmp/backstitch-evidence-spike.pddboQ/checkpoint-slice-7-untracked.sha256`
  (207,349 bytes; SHA-256
  `c71060be308490d41aff18b6b3e5ca3907fdc8c2e7e8938d86ba88d85d77b3c1`).
  No content was staged.
- Slice 7.0 established the required failing-first baseline: 229 focused
  cases produced 45 expected failures and 184 passes before production edits.
  The pins cover all seven exotic-newline sequences plus ordinary LF,
  canonical-path causes and collisions, eval candidate bounds, both verifier
  timeout routes, prompt mutation and all eight consumers, the complete span
  matrix, and the owner-detector evasions.
- Slice 7.1 routes every Markdown parser coordinate through the CR/CRLF
  parser-to-LF-source map, uses LF-only local splitting for the five
  non-breaking exotic characters, and preserves raw receipt bytes. The sole
  Slice-7 spec edit is the exact approved [EVC-9.1] bare-CR micro-delta.
  The pre-edit spec hash matched
  `5a9774fa7219010316c57ed30d3f47a3f25f25b422ee7ded4fff86d5ecb57e8f`;
  the post-edit hash is
  `db696d34fa81da362f5d6ea4bd4327ec345e7477321e3cfecc4361940c17acdb`.
- Slice 7.2 applies the declared canonical-path order across capture,
  resolver keys, inventories, and emitted edge paths. Invalid mappings
  degrade per target in check and through existing obligation/evidence fields;
  collision detection precedes coalescing. The final NUL correction recovers
  the exact authored NUL from the raw Markdown code span before
  classification, so check, one-sided evidence, excerpt, and receipt bytes
  preserve the ineligible token rather than markdown-it's U+FFFD projection.
- Slice 7.3 leaves one `canonical.lf_slice` owner with explicit strict or
  clamped policy at every caller and hardens owner enumeration against the
  reviewed alias, constant, and structural evasions. Slice 7.4 rejects absent
  paths and out-of-range eval spans with structured `AlignmentEvalError`
  before identity or receipt hashing. The one stale acceptance symbol and the
  canonical-path behavior-freeze/snapshot expectations were updated as direct
  integration corrections.
- Slice 7.5 uses one generic lock-timeout adoption gate across both analyzer
  and both verifier contention routes. It matches only
  `stage=lock`, `code=lock_timeout`, and an existing result path, then invokes
  the existing identical-key validating loader; it does not remove locks,
  relax validation, or change cache formats.
- Slice 7.6 freezes each analyzer identity once per packet at run entry and
  each eval identity once per unique packet/effective-epoch pair. Report
  validation, preflight, prompt budgets, cost accounting, cache inspection,
  primary/replay execution, and the legacy adapter consume those frozen bytes.
  Schema-1 report paths require supplied identities without a schema-field
  change. The owner inventory now rejects missing, explicit-`None`,
  unresolved-optional, and cast-only prompt authorities. The dated append-only
  correction under the Slice-4 record records when its prompt-byte claim
  became true.
- Slice 7.7 adds the `canonical.py` and `contract_validation.py` repository-map
  owners, refreshes `grammar.py`, replaces the deleted live-scan reference
  with `scan_snapshot_with_artifacts`, and removes the stale xfail prose.
  These are deliberately inspection-only changes with no runtime surface.
- The first independent implementation review found two Slice-7-local P2s:
  the NUL pin stopped at the canonicalizer instead of traversing real Markdown
  capture, and the prompt owner detector accepted explicit `None` authorities.
  Both received failing pins and narrow corrections. The scoped follow-up
  review verdict is **PASS**: 12 correction pins and 98 combined affected
  tests pass, literal U+FFFD remains unchanged, valid frozen prompt paths
  remain accepted, and no P1/P2, scope expansion, or correction-specific
  residual remains.
- Final gates: `uv run pytest --ignore=tests/live -q` passes all 1,746
  collected non-live tests with zero xfails; all 38 acceptance probes and both
  marked performance cases pass separately. Cold self-corpus commands measured
  0.67s for default check (0.7s budget) and 0.69s for obligation list (3.0s
  budget). Self-corpus reports 116 sections, 239 mappings, 340 code refs, 686
  edges, 8 invariants, 15 binds, and zero errors, warnings, or active infos;
  all 203 configured/meta suppressions remain visible under
  `--show-suppressions`. `obligation list --limit 100` returns schema 1, 100
  entries, a next cursor, and zero problems; every promoted INV-11 obligation
  is active, complete, evaluate, executable, and unblocked.
- Ruff lint/format over 121 files and MyPy over 42 source files pass. The
  Slice-7-scoped diff check passes. Repository-wide `git diff --check` still
  reports only the two documented pre-existing trailing-space lines in
  `tests/semantic_eval/v3/qualification-candidate/independent-review.md`.
  `git diff --cached --quiet` exits 0. Live provider tests were statically
  checked but intentionally not executed by the non-live gate. No content is
  staged, no commit was created, and the owner must explicitly direct landing.

## Post-Implementation Review (2026-07-17)

An independent multi-agent implementation review, adversarially verified
with reproductions, confirmed the implementation faithful to this plan and
all gates green: default `check` 0.657s, `obligation list` 0.653s,
self-corpus at 8 invariants / 15 binds, zero xfails in the non-live suite.
Ten residual findings remain; none blocks the implemented slices, and the
fixes restore conformance to already-promoted [INV-11]/[EVC-*] text, with
one declared exception: 7.1 amends [EVC-9.1]'s self-contradictory bare-CR
clause via the micro spec delta declared in that task. They are scoped as
Slice 7 above.

| # | Location | Finding | Severity |
|---|---|---|---|
| 1 | `backstitch/markdown_specs.py:971` | The `splitlines` exemption's justification is false: markdown-it does NOT normalize `\f`/`\v`/`\x85`/U+2028/U+2029 (they split statements, shifting derived end lines), and a stray `\r` shifts every subsequent parser line number — spec-side requirement spans and receipts can hash the wrong physical bytes while gates stay green. Reproduced. | HIGH |
| 2 | `backstitch/repository_snapshot.py:504` + `backstitch/cli.py:1447` | A valid `./`-prefixed mapping token is hard-rejected (any `.` component), and the obligation lane turns it into a command-global exit 2 (`check` degrades per-target; the obligation lane blocks entirely). | HIGH |
| 3 | `backstitch/alignment_eval.py:2584` | The candidate-projection eval lane misses the gold lane's path-existence and `end <= line_count` checks; `lf_slice` silent truncation validates over-claimed spans; an absent path raises a bare `KeyError`. | MED |
| 4 | `backstitch/semantic_cache.py:1962` | The verify lane lacks the analyzer's `lock_timeout` -> published-result fallback (asymmetric twins). | MED |
| 5 | `backstitch/semantic_analysis.py:458` (also `:588`, `:1372`; `semantic_reports.py:2477`, `:2768`; `semantic_eval.py:399`, `:838`; `analysis_llm.py:305`/`:439`) | Analyzer preflight gates — and the legacy adapter seam, the eighth site — reread prompt resources instead of consuming the frozen identity bytes; contradicts the Slice 4 record's claim; residual TOCTOU. (The original review cited `:485`; the prompt-byte read is the `model_request_bytes` sum at `:458` — citation corrected in scoped review.) | MED |
| 6 | `backstitch/evidence_discovery.py:293` | Four span-primitive spellings with three out-of-range policies (`canonical.lf_slice` truncate; two `_line_span` clamps in `evidence_discovery`/`evidence_summary`; strict `_span_bytes` in `semantic_eval_reports`), invisible to the AST pin because they wrap `lf_split`. | MED |
| 7 | `tests/test_canonical_owners.py:94` | The canonical-JSON detector is evadable: omitting `ensure_ascii` is byte-identical (`cli.py:564`, `:807` are already in the blind spot); from-import aliasing and non-literal separators also evade it; the newline-count detector only fires on a name literally containing `byte`. | MED |
| 8 | `docs/implementation/02-repository-map.md` | Missing rows for `canonical.py` and `contract_validation.py`; the `grammar.py` entry is stale. | LOW |
| 9 | `docs/implementation/04-backstitch-style-traceability.md:29` | References the deleted `scan_repository`. | LOW |
| 10 | `tests/test_evidence_spike_cache_perf_pins.py:3` | Stale "xfails remain" docstring. | LOW |

Finding-to-task coverage (updated 2026-07-17 after the scoped Slice 7
review; task numbers reflect the resequenced order, span consolidation 7.3
ahead of the eval-lane port 7.4):

| Finding | Fixed by | Failing-first coverage |
|---|---|---|
| 1 | 7.1 | 7.0 exotic-newline pins (all seven sequences incl. CRLF, plus ordinary-LF control) under the stated raw-bytes/LF-coordinates byte policy |
| 2 | 7.2 | 7.0 path pins (a) `./` normalization succeeds, (b) malformed per-target degradation, (c) [EVC-8.2] collision failure |
| 3 | 7.4 | 7.0 eval-lane fixtures (over-claimed span, absent path) |
| 4 | 7.5 | 7.0 contention pins for both routes (`:1962` wait-loop, `:2012` guard acquisition) |
| 5 | 7.6 | 7.0 prompt-mutation pin, ownership pin, and eight per-consumer firing tests |
| 6 | 7.3 | 7.0 span-primitive inventory pin plus the per-cell policy-matrix pins |
| 7 | 7.3 | 7.0 evasion pins: `ensure_ascii` omission, from-import aliasing, non-literal separators, structural newline-count detector |
| 8-10 | 7.7 | Inspection-only, stated explicitly; `canonical.py` row also carries the INV.CANON.1 cross-reference note |

Slice 4 record correction: the Slice 4 record's claim that
"budget/preflight calculations consume those same bytes" is contradicted by
finding 5 and must be corrected in that record when the 7.6 fix lands — not
by rewriting the record, but by appending a dated correction note under it
(execution records are append-only).

Deviation-log judgment (corrected 2026-07-17 after scoped round 2; the
round-1 wording claimed full spec neutrality and no micro-delta, which the
codex review disproved): Slice 7 is spec-neutral with exactly one declared
exception. 7.2 is spec-neutral: [EVC-8.2]'s canonical-path grammar
enumerates its invalid set — absolute path, backslash, NUL, empty
component, dot-dot component, surrogate — without single-dot, and states
that no non-root dot component "is retained", i.e. `.` components normalize
away rather than invalidate the token; the current hard-reject is therefore
over-strict relative to the promoted text, 7.2 is conformance-restoring,
and its obligation-lane output resolves onto existing [EVC-8.3] fields with
no schema delta. 7.1's mechanism is likewise conformance-restoring, but it
carries one declared micro spec delta: [EVC-9.1]'s requirement that bare CR
normalize to LF while preserving one output line per physical source line
is unsatisfiable for a mid-line bare CR under [INV.LINE.1]'s LF-only
physical coordinates; the exact replacement text, Strategy A promotion, and
pre-edit spec-07 SHA-256 are declared in 7.1, and a Deviation Log row is
appended below. The extension itself re-enters review per the plan
lifecycle: Slice 7 awaits its scoped outside review (Status header) before
implementation.

## Deviation Log

Append-only.

| Date | Slice | Spec ref | Deviation and reason | Spec proposal | Verification | Disposition |
|---|---|---|---|---|---|---|
| 2026-07-17 | 0 | [CFG-8], [SEM-3], [EVC-9.1] | The reviewed finding #10 is real, but the plan's selected remedy (emit a trace-mode bound-omission warning) conflicts with [EVC-9.1]'s complete-universe and fatal-overflow rules. | Proposed Spec Delta now removes the unreachable config affordance and makes schema-3 warnings exactly empty. | Original ReportFindings transcript recovered; live `rg`/spec inspection; two expected-red configuration/loader pins. | Accepted; narrow round-5 review required before promotion. |
| 2026-07-17 | 7 | [EVC-9.1], [INV.LINE.1] | [EVC-9.1]'s "normalizes CRLF and CR to LF" plus "one output line per physical source line" is unsatisfiable for a mid-line bare CR under [INV.LINE.1]'s LF-only physical coordinates; a markdown-it-py repro confirms CR/CRLF are the only parser line breaks while `\f`/`\v`/`\x85`/U+2028/U+2029 stay in-line content. | 7.1's declared micro-delta: CRLF-only normalization; a bare CR not part of a CRLF pair is preserved as in-line content; exact replacement wording, Strategy A, and pre-edit spec-07 SHA-256 recorded in task 7.1. | markdown-it repro (2026-07-17); 7.0 exotic-newline pins including the bare-`\r` fixture asserting the amended text. | Accepted; lands with 7.1 after the scoped Slice 7 re-review passes. |

## Review Record

Both reviews ran 2026-07-16 against the plan as first written. Verdict:
**BLOCKED** — architecture and findings verified accurate (the independent
reviewer spot-checked every sampled file:line claim and confirmed all of
them); blockers concentrate in the spec-delta formulation, sequencing, and
rollback. All P1 findings are accepted. Required corrections before this plan
is implementable:

1. **Spec baseline (codex P1):** record SHA-256 of the pre-promotion spec 05
   and a checkpoint identity for the dirty worktree (see 10 below).
2. **Promotion sequencing (both):** promote the invariant text in an early
   spec-promotion slice, not Slice 6; label the strategy B (atomic with
   bindings) where bindings land together, with the late-binding justification
   argued explicitly; add the §4c insertion-point table with exact spec-05
   markdown in declaration format, including implementation bindings per
   [INV-5] so the invariants are executable obligations, not prose.
3. **INV.PERF.1 (both):** restate normatively as deterministic work bounds —
   the default `check` path performs zero static-syntax parses and at most one
   snapshot capture — and keep wall-clock budgets (0.7s / 3s) as marked
   `tests/performance/` budgets outside spec text.
4. **INV.CFG.2 (codex):** narrow to keys with duplicated concrete effective
   defaults (packaged profile/check defaults use None-means-packaged and are
   exempt), or make packaged TOML the sole default owner.
5. **INV.CANON.1 / INV.SCAN.1 (codex):** define the closed module/owner
   inventory (AST-level enumeration test with an allowed-owner table) so the
   "exactly one implementation" claims are executable.
6. **INV.LINE.1 (codex):** Slice 1 explicitly creates the line-slicing
   helper; enumerate and migrate every covered `splitlines()` call site or
   narrow the invariant boundary to the enumerated modules.
7. **Finding #7 fix assignment (independent):** Slice 3 fixes the dataclass
   default to 10 (packaged TOML and spec are canonical; no artifact captured
   under 100 exists outside tests); the INV.CFG.2 test then pins it.
8. **Slice 4 / [SEM-4] (codex):** no guard bypass — preserve the owned lock
   when the guard cannot be acquired and define bounded deferred cleanup;
   map cleanup failure into the existing closed problem vocabulary without
   losing the provider failure (no new problem fields; if impossible, a
   [SEM-7] delta is declared instead of implied).
9. **Ordering (both):** drop the "2-5 parallelizable" claim; serial order
   0, 1, 2, 3, 4, 5a (perf), 5b (D6/D8/D10 split out with its own review
   gate and a migration/coverage-diff gate before any deletion), 6-promotion
   moved earlier per item 2. Single fixture-regeneration owner (Slice 2).
10. **Rollback (codex):** git checkout would destroy the uncommitted spike;
    replace with a checkpoint protocol — `git stash create` / patch snapshot
    of the worktree recorded before each slice, restore by patch.
11. **Durable evidence (codex):** copy the review reproductions (wrapped
    invariant, malformed token, \r/\f probes, contention repro) into
    Slice 0's test docstrings or a plan appendix so a zero-context
    implementer needs no session scratchpad.
12. **Slice 0 completeness (both):** add pins for NM2, NM3, budget-vs-torn,
    prompt hash-at-use, and firing tests for D5-D10 consolidations (D5 first
    enumerates the exact validator functions and proves semantic equivalence
    before any factory); state which gates are expected red at Slice 0 and
    that the first all-green gate is Slice 3.
13. **D8 budget semantics (independent):** measuring the response budget on
    canonical core JSON vs rendered text is a behavior change — cite the
    governing [EVC-8.5] text if conformance-restoring, else declare it in the
    spec delta.
14. **Deviation log (independent):** add the runbook's `Spec proposal`
    column.
15. **Comprehension gates (independent):** add required-reading questions for
    the verify-lock protocol, snapshot identity preimage, and packet-hash
    construction.

- Independent plan review: BLOCKED, 4 P1 / 6 P2 — all accepted as above.
- Codex second review (codex-cli 0.144.3): 15 P1 / 5 P2 — all accepted as
  above; P2s on packet-identity cache disposition, heap total-key
  equivalence, and legacy-path caller migration fold into items 9-12.
- Next action: apply corrections 1-15 to this plan, then re-run both
  reviewers; implementation starts only on a PASS.
- Corrections 1-15 applied to the plan body on 2026-07-16; awaiting
  re-review.
- Round-2 corrections (R2-1..R2-6) applied to the plan body on 2026-07-16;
  independent reviewer passed round 2; awaiting codex round-3 gate.
- Round 3 (after R2-1..R2-6): codex confirmed four of six corrections
  resolved. Two surgical partials remained: the `canonical.py` mapping needed
  its reciprocal code-side backlink in the same change, and Slice 4's stop
  gate demanded lock removal that is impossible under persistent guard
  unavailability.
- Round 4: both partials were corrected in the plan body. Codex verdict:
  **PASS**. The plan is cleared for implementation beginning at Slice 0.
- Round 5 trigger (Slice 0): exact reproductions recovered from the original
  ReportFindings transcript. Duplicate unresolved same-line mapping tokens now
  have a firing expected-red pin. Live spec/code inspection disproved the
  chosen #10 remedy and exposed wider D1/D4 inventories plus intentional D5
  policy variation. The plan body now reflects those facts; a narrow
  independent review of the corrected #10 delta is required before promotion.
- Round 5, completeness pass 1: Claude review was unavailable because no local
  Claude credential or API key is configured, so a fresh read-only same-family
  reviewer was used and that limitation is explicit. Verdict: **FAIL**, 2 P1,
  0 P2. The corrected design was accepted as correct, minimal, and
  implementable, but the written delta omitted the active [SEM-7]/[EVC-8.7]
  warning-policy text and the implementation inventory omitted
  `pyproject.toml` plus strict schema-3 report warning validation. Both P1s are
  incorporated in the plan and a firing report-validation expected-red pin is
  added; round-5 re-review is pending.
- Round 5, completeness pass 2: verdict **FAIL**, 2 P1 / 2 P2. The reviewer
  corrected the report boundary from current scope only to every schema-3
  report, noted that the first red pin coupled count and debt, required an
  explicit [EVC-9.1] replacement rather than insertion, and preserved the
  exact warning-debt record shape as legacy schema-1 vocabulary. All four
  points are incorporated; the pin now independently covers count-only,
  debt-only, and matching count/debt forgeries under both schema-3 scopes.
- Round 5, completeness pass 3: **PASS**, no P1 or P2. The reviewer confirmed
  every schema-3 scope is closed to warning debt, legacy debt is limited to
  schema-1 validation/presentation, [EVC-9.1] has an explicit replacement,
  the legacy debt shape remains specified, `pyproject.toml` is in Slice 2,
  and the independent six-case pin produces the planned 4-failed/2-passed red
  state. Claude authentication remained unavailable, so all round-5 passes
  used the disclosed fresh same-family read-only reviewer.
- Slice 7 addendum, scoped round 1 (2026-07-17): the independent reviewer
  returned **BLOCKED-narrow**, 1 P1 / 4 P2 — the P1 covered finding 7's
  remaining evasion vectors (from-import aliasing, non-literal separators,
  the name-based newline-count heuristic); the P2s covered the explicit
  exotic-newline byte policy, the eighth prompt-read site
  (`analysis_llm.py:305`/`:439`) plus the `:485`-vs-`:458` citation fix,
  the 7.7 verification statement, and the [EVC-8.2] collision pin. The
  codex reviewer returned **BLOCKED**, 8 P1 / 3 P2 — P1s covered the 7.1
  coordinate-map design replacing the non-conforming
  normalize-at-ingestion remedy, splitting the `./`-normalization pin from
  the malformed-token pin, the [EVC-8.4]-conforming obligation-lane output
  shape, canonicalizer completeness with the [SC-4] reconciliation, both
  verifier contention routes behind one shared helper, the frozen
  prompt-identity lifecycle with per-consumer tests, and the span-policy
  behavior matrix with 7.6-before-7.3 resequencing; P2s covered the
  ordinary-LF control pin with the full seven-sequence newline set, the
  `tests/test_analysis_packets.py:560` CRLF/[EVC-9.1] reconciliation, the
  syntactic span-helper AST inventory, and the CLI JSON display-only
  exemption decision. All accepted corrections from both scoped reviews
  were applied to the Slice 7 addendum on 2026-07-17, including the task
  renumbering (span consolidation is now 7.3, ahead of the eval-lane port
  7.4) and the updated finding-to-task coverage table; Slice 7 still
  awaits a passing scoped re-review before implementation.
- Slice 7 addendum, scoped round 2 (2026-07-17): codex returned
  **BLOCKED**, 3 P1 — round-1 findings 5-8 and all P2s were confirmed
  resolved. The three P1s: (1) 7.1 applied the coordinate-map remedy to
  all seven sequences when markdown-it breaks only on CR/CRLF, and its
  bare-CR handling exposed a genuine contradiction inside promoted
  [EVC-9.1] (CR-to-LF normalization versus one output line per physical
  source line); (2) 7.2's "MAPPING_PATH_* projected into per-obligation
  rows" output shape is illegal under [EVC-8.3]'s closed row schemas and
  closed blocking-reason vocabulary; (3) the 7.2 canonicalizer omitted
  [EVC-8.2]'s surrogate-code-point rejection and stated no normalization
  order. All three corrections were applied to the addendum on
  2026-07-17: 7.1 is now two distinct fixes (CR/CRLF coordinate map;
  LF-only replacement of local universal-newline splitting for the five
  non-break characters, verified by markdown-it-py repro) plus one
  declared [EVC-9.1] micro-delta with exact replacement wording, Strategy
  A, the pre-edit spec-07 SHA-256, and a Deviation Log row; 7.2 adopts
  the legal existing-field projection ([EVC-7] resolver-issue evidence
  path, one-sided `--summarize-evidence` rows, and closed-vocabulary
  readiness fields — no new fields, no [EVC-8.4] schema delta); the
  canonicalizer gains surrogate rejection and the explicit four-step
  normalization order, with the surrogate case added to the 7.0
  malformed-path pins. The spec-neutrality claim is corrected throughout:
  7.2 is spec-neutral; 7.1 carries exactly one declared micro-delta.
  Slice 7 still awaits a passing scoped re-review before implementation.

## Definition of Done

- All ten findings and four near-misses have passing regression pins that
  failed first; duplication items D1-D10 resolved to canonical owners.
- New invariants promoted with binding tests; self-corpus gate and obligation
  dashboard green including them.
- INV.PERF.1 deterministic work bounds met; the non-normative wall-clock
  budgets pass with observed timings recorded.
- Both reviews passed with findings dispositioned.
- Worktree state reported honestly: uncommitted until the owner directs
  landing.
