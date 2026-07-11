# Local LLM Release-Gate Stabilization

Status: complete. Corrective commit `60f4d2c` passed local and GitHub x86 model
gates; `v0.3.0` was published to PyPI and GitHub Release with attestations.
Plan type: implementation with spec revision.
Risk level: high. This changes a release-blocking live-model contract and ends
with retagging an unpublished release. PyPI publication is a one-way door.

## Goal

Make the credential-free local-LLM release gate repeatable and explicit: use a
stable ordered pair of real invariant packets with bounded target and binding-
test evidence, and put deterministic inference controls on the request that
actually reaches Ollama. Constrain the already-required output shape at the
test-owned endpoint boundary without changing the production adapter or
repairing model output. After the fix passes every repository gate and an
independent review, move the unpublished `v0.3.0` tag to the fix commit with
`bin/release.py all --retag` and verify publication on PyPI and GitHub.

## Source Documents

- `docs/specs/02-backstitch-core.md` [SC-7], [SC-10]
- `docs/specs/03-backstitch-configuration.md` [CFG-9]
- `docs/plans/2026-07-03-local-llm-eval-lane-plan.md`
- `docs/plans/2026-07-06-analyze-json-mode-plan.md`
- `docs/implementation/04-backstitch-style-traceability.md`
- `docs/implementation/05-release-publishing.md`
- `docs/implementation/06-choosing-a-local-model.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`

## Spec Baseline

- `3b3bac2905ddfab25c7cce8d49e3666b39dffc58` —
  `docs/specs/02-backstitch-core.md` [SC-7] at plan authoring time.
- Promotion baseline: `3b3bac2905ddfab25c7cce8d49e3666b39dffc58` plus
  the 2026-07-10 worktree diff in `docs/specs/02-backstitch-core.md` adding the
  reviewed [SC-7] local-gate paragraphs and this plan backlink. Strategy B is
  atomic: tests, harness code, and reciprocal docs remain in this same slice.

## Context And Key Files

- `tests/live/test_live_llm.py` owns the real local provider proof. It
  generates packets, selects the local subset, configures `llm`, proxies the
  OpenAI-compatible endpoint, invokes the public CLI, and validates the result.
- `tests/test_live_llm_helpers.py` owns hermetic tests for the proxy and packet
  selector. Its current selector test is synthetic and cannot detect changes
  in the repository's generated packet corpus.
- `.github/workflows/local-llm.yml` creates a bounded Ollama model and runs the
  live test. Its Modelfile says `temperature 0`, but Ollama 0.31.1's OpenAI
  route supplies request temperature `1.0` when the request omits it.
- `backstitch/analysis_llm.py` is the production provider-neutral adapter. It
  must not learn about the local test kind, loopback endpoints, or Ollama.
- `bin/release.py` runs cloud, local, hermetic, static, self-corpus, build, git,
  and tag steps. `--retag` deletes and recreates an unpublished remote tag when
  it points to the wrong commit; it never publishes directly.
- `docs/specs/05-backstitch-invariants.md` declares the invariant packets. The
  chosen current packets are `invariant::INV.RES.1` and
  `invariant::INV.RES.2`; each has one bounded target snippet, one bounded
  binding-test snippet, and no packet warnings.

Comprehension gates before editing:

1. Which bytes are currently recorded by `_CountingProxy`: the adapter's
   original request or the bytes actually forwarded upstream?
2. Why can a section packet's linked test path not carry line evidence under
   [SC-7], while an invariant packet's `binding_tests` snippet can?
3. At what exact point does release rollback change from tag deletion to a
   mandatory fix-forward release?

## Invariants And Constraints

- Preserve the production `default_adapter` and all cloud/custom-provider
  behavior. Deterministic controls belong only to the test-owned local proxy.
- Apply inference controls to every completion request forwarded by the proxy,
  including the transport preflight; `recording` controls retention only, not
  transport behavior.
- The exact body forwarded to Ollama must contain `temperature: 0` and a fixed
  nonzero integer seed. The analyze-phase recording must capture that forwarded
  body and assert the model, every selected packet ID, temperature, and seed.
- Invalid or non-object completion JSON is a loud proxy failure, never an
  unseeded fallback request.
- The local gate uses at least two packets. It keeps the existing rule that
  individual error rows are tolerated but total failure exits `2` and fails.
- The local subset is an explicit ordered tuple of invariant packet IDs emitted
  by `packets --kind invariant`. Every required packet must occur exactly once
  and contain at least one qualifying target item and one qualifying binding-
  test item. A qualifying item has a nonblank path, a positive integer
  `start_line`, and a nonblank snippet. Missing, duplicate, warned, or evidence-
  poor packets fail before any provider call. There is no smallest-first or
  best-effort fallback.
- Cloud packet generation and selection remain unchanged.
- Keep the prompt byte ceiling. Do not pin content hashes or byte lengths,
  which legitimately move when bound code and tests change.
- No new dependency, CLI flag, config key, runtime fallback, or provider-
  specific production branch.
- The worktree must be clean before the real release helper runs. Do not use
  `--skip-checks`.
- Do not weaken or retry the live gate merely to obtain green CI. A rerun is
  evidence only after deterministic controls and stable inputs are present.

## Hidden Couplings

- `packets` defaults to section packets. The local path must request
  `--kind invariant`; the cloud path must retain its current section behavior.
- `summarize-analysis` and the deterministic report must continue accepting
  invariant result identities after the live analyze step.
- `urllib.request.Request` must receive the mutated bytes after the proxy strips
  the incoming `Content-Length`, so it recalculates the correct length.
- The Modelfile temperature check remains useful configuration evidence, but it
  does not prove effective OpenAI-route sampling. Tests and docs must stop
  claiming otherwise.
- The branch push from `bin/release.py` starts the new SHA's `CI` and
  `local-llm` workflows before the replacement tag starts the Release Gate.
  The Release Gate chooses required workflows by SHA, not by the old run IDs.
- PyPI may succeed before GitHub Release creation. Publication status must be
  checked directly before any rollback attempt.
- The current helper inspects publication/tag state before long prechecks, then
  deletes the old remote tag before pushing the reviewed branch. The fix must
  push the branch first, refuse if an earlier Release Gate is active, then re-
  query PyPI/GitHub/tag state immediately before tag mutation and delete the
  remote tag only with a compare-and-swap lease against the re-observed SHA.
  Checking active work before the publication snapshot prevents an old gate
  from publishing between those reads and disappearing from the active set.

## Fatal Versus Best-Effort

Fatal before release: malformed proxy request JSON, missing deterministic
controls, curated packet drift, total model failure, any required local or CI
gate failure, self-corpus warnings/errors, review blockers, build failure, or a
dirty release worktree.

Best-effort only where [SC-7] already permits it: one local packet may yield a
contained model error if the other produces a valid result. Model
classification wording remains advisory.

## Rollback And One-Way Door

Before tag push, rollback is an ordinary revert or correction of the fix
commit. After the replacement tag is pushed but before PyPI publication,
cancel the new Release Gate, verify PyPI `0.3.0` is still absent, then delete
the remote and local replacement tag if aborting. A branch-push failure occurs
before tag mutation and leaves the old tag untouched. A leased-deletion failure
means the remote tag changed and the helper must stop for a fresh state check.
If the replacement tag push fails after guarded deletion, recheck publication
and tag state before retrying that tag push; do not create another version
implicitly.

Once PyPI accepts either `0.3.0` distribution artifact, publication is a one-
way door. Do not delete or replace it. Any defect discovered after that point
must be fixed forward with a new version, even if GitHub Release creation has
not yet completed.

## Proposed Spec Delta

Promotion strategy: **B — atomic**. After independent plan review, update the
existing active [SC-7] local-endpoint contract, its nearby implementation
mapping/backlink, tests, and code in one worktree slice so the zero-warning
self-corpus gate never observes partial reciprocal state.

| Spec file | Strategy | Section touched |
|-----------|----------|-----------------|
| `docs/specs/02-backstitch-core.md` | B — atomic | [SC-7] local-endpoint live-test paragraphs |

### [SC-7] — insert after the local-endpoint paragraph ending “when it is not”

> A repository-owned local-endpoint automation gate must make its model input
> and inference controls explicit. It must generate invariant packets through
> the public `packets --kind invariant` command and select an ordered,
> repository-owned set of at least two real invariant packet IDs. Every
> selected packet must occur exactly once, have no packet warnings, and carry
> at least one qualifying target item and one qualifying binding-test item. A
> qualifying item has a nonblank path, a positive integer `start_line`, and a
> nonblank snippet. Invalid curated input fails before model listing or any
> completion request, with no smallest-packet or best-effort fallback.
>
> When an OpenAI-compatible endpoint supplies request defaults that override
> stored model parameters, the local test harness must put `temperature = 0`
> and a fixed nonzero seed on every completion request that reaches the
> endpoint. Its transport proof must record the forwarded analyze requests and
> assert the selected model, packet IDs, temperature, and seed. This tuning is
> test-owned: it must not add provider-specific behavior to Backstitch's
> production adapter or alter cloud/custom-provider calls.

## Tasks

1. **Independent plan and delta review.** Give this plan, [SC-7], the existing
   local-lane plan, live test, helper tests, adapter, and release implementation
   note to a separate review agent. Address every finding before code.
   - Stop if the reviewer cannot explain how the controls reach Ollama without
     changing production behavior.
   - Done: review completed. Both P1 findings and all P2 findings were accepted:
     corpus validation is moved before transport, retagging gains a pre-mutation
     publication/workflow/tag recheck plus leased deletion and branch-first
     push, invalid proxy JSON is specified precisely, invariant evidence shape
     is exact, and recording-off controls get a direct proof.

2. **Atomic spec promotion plus proxy controls, red to green.** Update [SC-7]
   and its related-plan backlink. First change the hermetic forwarding test to
   require exact upstream and recorded `temperature: 0` and seed values and
   observe failure. Add invalid/non-object completion-body cases: the proxy must
   return HTTP `400`, make zero upstream calls, retain zero bodies, and emit no
   handler traceback. Add separate recording-off and recording-on cases: both
   forward exact temperature/seed controls, only the latter retains a body, and
   retained bytes equal forwarded bytes. Then mutate and validate completion
   bodies in `_CountingProxy` before forwarding and record the forwarded bytes.
   - Files: `docs/specs/02-backstitch-core.md`,
     `tests/test_live_llm_helpers.py`, `tests/live/test_live_llm.py`.
   - Do not mock the proxy boundary: use the real loopback HTTP servers already
     in the helper tests.
   - Stop if implementation needs a production adapter or CLI change.
   - Done: each new test was observed red, then the targeted helper suite is green.

3. **Curated invariant corpus, red to green.** First add a selector test where
   a smaller unrelated packet cannot displace the ordered curated IDs; add
   missing, duplicate, warning, missing-target-snippet, and missing-binding-
   snippet failures one case at a time. Add a real self-corpus test that invokes
   the shipped `packets --kind invariant` CLI and asserts the curated IDs and
   evidence shape. Then implement the narrow selector, reorder local generation
   and validation before model listing/transport preflight, and make local
   generation use invariant packets while cloud stays unchanged. Add a provider-
   call counter proving invalid curated input produces zero completion calls.
   - Files: `tests/test_live_llm_helpers.py`, `tests/live/test_live_llm.py`.
   - Stop rather than falling back if a curated ID or evidence contract has
     legitimately changed; that requires an explicit corpus decision.
   - Done: targeted tests pass and generated local prompts remain under budget.

4. **Documentation and traceability reconciliation.** Correct durable claims
   that the old OpenAI-compatible live path effectively ran at temperature
   zero. Document the curated invariant IDs, request-level controls, why the
   proxy is the correct test-only boundary, and the historical limitation of
   the old bake-off. Update the plan status, promotion baseline, execution log,
   and reciprocal related-plan links.
   - Files: `.github/workflows/local-llm.yml`,
     `docs/implementation/04-backstitch-style-traceability.md`,
     `docs/implementation/05-release-publishing.md`,
     `docs/implementation/06-choosing-a-local-model.md`,
     `docs/plans/2026-07-03-local-llm-eval-lane-plan.md`, this plan, and any
     nearby test guard that pins the corrected workflow comment.
   - Stop if a historical measurement cannot be distinguished from current
     effective behavior; preserve the record and label the limitation instead
     of rewriting history.
   - Done: docs agree with the tested request path and self-corpus reports zero
     errors and zero warnings.

5. **Retag mutation hardening, red to green.** Add release-helper tests before
   changing implementation. The public behavior must be: push the reviewed
   branch before any tag mutation; refuse if an earlier Release Gate for the
   tag is not completed; then immediately re-inspect PyPI, GitHub Release,
   local tag, and remote tag; refuse if publication appeared; recompute the tag
   action from the refreshed state; and delete a replacement remote tag with
   `--force-with-lease=refs/tags/<tag>:<observed-sha>`. Only after that guarded
   deletion may the helper recreate and push the tag.
   - Files: `bin/release.py`, `tests/test_release_script.py`,
     `docs/implementation/05-release-publishing.md`.
   - Use the existing GitHub auth and JSON request helpers; add no dependency.
   - Mock only external HTTP/git command boundaries in unit tests. The real dry
     run and final release remain end-to-end proofs.
   - Stop if safe deletion cannot be expressed as a lease-guarded git push or
     if active workflow state cannot be queried without broader permissions.
   - Done: command-order, refreshed-publication refusal, active-gate refusal,
     changed-tag refusal, and lease syntax tests pass.

6. **Verification and independent implementation review.** Run the targeted
   helper tests, the real local Ollama test, the full hermetic suite, acceptance
   probes, lint, formatting, strict typing, release tests, build, and default
   self-corpus gate. Give the diff, promoted [SC-7], this plan, and command
   output to an independent reviewer. Address all verified findings, rerunning
   affected gates.
   - Done: the first coverage audit found and closed the missing successful
     retag path. Adversarial review found and closed the active-run/publication
     read-order race, direct-prewarm seed gap, and stale historical status.
     Completion review strengthened hermetic HTTP isolation, both publication
     destinations, refreshed local-tag behavior, and zero-provider-call proof.

7. **Commit and release.** Commit only the intentional stabilization and docs
   changes with no agent attribution. Confirm `git log` and a clean tree. Run
   `bin/release.py all --dry-run --retag`; require `v0.3.0 (replace_remote)`.
   Then run `bin/release.py all --retag` without `--skip-checks`. Monitor the
   new SHA's CI, local-LLM, and Release Gate workflows to completion. Finally
   verify PyPI contains exactly the wheel and sdist and GitHub Release contains
   those plus the Sigstore bundle.

8. **Cross-hardware constrained-decoding correction.** The first corrected
   `main` local workflow proved temperature/seed controls but produced two
   invalid evidence rows on x86, while ARM local runs produced one or two valid
   rows. Keep the validator and total-failure exit unchanged. For recorded
   analyze calls only, derive a strict JSON Schema from the real packet's
   identity, result vocabulary, and canonical evidence bounds; forward one
   nonstreaming request because pinned Ollama does not reliably enforce the
   schema while streaming; then relay the exact assistant content as SSE to the
   unchanged adapter. Reject malformed prompts and upstream envelopes without
   fallback. Require the adapter's incoming `json_object` before replacement,
   and reject a repeated packet ID before recording or forwarding so SDK
   retries and the adapter compatibility fallback cannot create a second
   upstream request.
   Bound summary/rationale lengths, evidence count, and request output tokens
   so nonstream constrained decoding cannot consume the full served-model
   prediction ceiling.
   - Files: `tests/live/test_live_llm.py`,
     `tests/test_live_llm_helpers.py`, [SC-7], implementation/model docs, this
     plan, workflow comments, changelog, and lessons.
   - Done locally: red proxy/schema/count tests turned green; the real pinned
     Ollama test passed through the nonstream/SSE bridge. Corrective independent
     review and the full release gate remain pending.

## Testing Plan

Use vertical red-green slices. The primary proofs are real loopback HTTP, the
public `backstitch packets` CLI, the public `analyze` subprocess, and the real
Ollama endpoint. Do not mock `_CountingProxy`, packet generation, the CLI, or
Ollama in the live gate. Fakes remain appropriate only for the existing
production model-adapter unit boundary.

Per-slice commands:

- `uv run pytest tests/test_live_llm_helpers.py -q`
- `BACKSTITCH_LIVE_LLM=1 BACKSTITCH_LIVE_LLM_KIND=local uv run pytest tests/live/test_live_llm.py -q --tb=short`

Final gates:

- `uv run pytest tests -q -n auto --dist loadgroup -m "not live_llm"`
- `env -u BACKSTITCH_LIVE_LLM uv run pytest tests/live/test_live_llm.py -q -o run_live_llm=false`
- configured real local live test through the release helper environment
- `uv run pytest tests/acceptance -q`
- `uv run pytest tests/test_release_script.py tests/test_release_workflow.py tests/test_release_workflow_gate.py -q`
- `uv run ruff check .`
- `uv run ruff format --check backstitch bin .github/scripts tests`
- `uv run mypy backstitch bin/release.py tests --config-file pyproject.toml`
- `python3 -m py_compile .github/scripts/require_green_workflows.py`
- `uv build`
- `uv run backstitch check --repo-root .` with exit `0`, zero errors, zero warnings

## Rollout And Observable Success

Roll out in this order: reviewed fix commit, clean local gates, real release
helper prechecks, branch push, replacement tag push, required workflow gates,
PyPI publication, GitHub Release creation. Success is observable only when:

- the new SHA's `local-llm` workflow is green without retry;
- the Release Gate completes successfully;
- PyPI `backstitch==0.3.0` exposes one wheel and one sdist;
- GitHub Release `v0.3.0` exposes those files plus one Sigstore bundle; and
- the remote tag points to the reviewed fix/release commit.

## Independent Review Loop

Plan review: a separate agent reads this plan, its exact proposed [SC-7] delta,
the baseline spec, live test, helper tests, adapter, and release implementation
note. The reviewer must answer whether the plan can be implemented confidently
against the delta as if promoted, with findings first.

Implementation review: a fresh separate agent reads the promoted spec, plan,
full diff, test evidence, and release dry-run output. Each finding is reproduced
before action; the author records acceptance, rejection, or out-of-scope reason.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [SC-7] | Curated packets plus temperature zero and seed 42 make the small-model gate repeatable | ARM local runs passed, but x86 CI produced snippet-relative and malformed evidence for both packets | Quantized inference is not byte-identical across CPU kernels; sampling controls cannot constrain the already-required evidence shape | Promoted: test-owned packet-bounded schema decoding over a nonstream/SSE bridge; no output repair or validator relaxation |

## Execution Log

- 2026-07-10: CI failure investigated. Hermetic CI passed; local Ollama failed
  both implicitly selected ownerless section packets. Same failure reproduced
  locally with matching image and model manifests. Actual forwarded requests
  omitted temperature and pinned Ollama applied effective temperature `1.0`.
- 2026-07-10: Fix and release plan drafted. Awaiting independent review.
- 2026-07-10: Independent review found five issues. Accepted all: explicit
  pre-provider corpus validation order; branch-first, refreshed, lease-guarded
  retagging with active-gate refusal; deterministic HTTP 400 for invalid proxy
  JSON; exact invariant evidence shape; and recording-off request-control proof.
- 2026-07-10: Reviewed [SC-7] delta promoted with strategy B. Promotion
  baseline recorded above; test and harness implementation follows in the same
  atomic worktree slice.
- 2026-07-10: Implemented the test-owned request controls, curated invariant
  selector, pre-provider corpus validation, and branch-first lease-guarded
  retag checks. Targeted helper and release suites pass.
- 2026-07-10: Verification passes: full hermetic pytest suite, disabled-live
  policy check, 18 acceptance probes, Ruff lint and format, strict mypy, Python
  byte compilation, package build, and self-corpus check with zero errors,
  warnings, or infos. Suppressions remain auditable with
  `--show-suppressions`.
- 2026-07-10: The exact real Ollama gate passed after formatting with the
  pinned `llama3.2:3b` base, `backstitch-local-model:latest` served ID, context
  4096, prediction bound 1024, and the stabilized request controls.
- 2026-07-10: Independent implementation, coverage, and completion reviews
  found no production defect after correction. Accepted review findings added
  the successful real-retag proof, reversed active-run/publication read order
  to close the one-way-door race, seeded direct prewarm traffic, corrected the
  historical plan status, and strengthened hermetic boundary tests.
- 2026-07-10: Post-review verification is green. Fresh-context assessed
  coverage is 85 percent (35 of 41 changed path families), the full hermetic
  and acceptance suites pass, and the second exact real Ollama run passed on
  the final reviewed worktree.
- 2026-07-10: Committed `93b31d5`, passed the authoritative dry-run review, and
  ran `bin/release.py all --retag`. All local helper checks including cloud and
  local live providers passed; branch and tag moved to that commit.
- 2026-07-10: New-SHA CI passed, but x86 `local-llm` run `29136132546` failed
  both invariant rows on invalid evidence, so Release Gate `29136134794`
  stopped before build or publication. PyPI and GitHub Release remained absent.
  Root cause: the same greedy request can diverge across ARM and x86 inference
  kernels, and streaming JSON-object mode does not constrain evidence shape.
- 2026-07-10: Added the test-owned nonstream schema/SSE bridge. Hermetic tests
  prove exact schema bounds, replacement of `json_object`, one request per
  packet, unchanged assistant-content relay, upstream-free prompt rejection,
  and malformed-envelope failure. The exact real pinned Ollama gate passes
  through the bridge without changing the production parser or adapter.
- 2026-07-10: Corrective review reproduced six upstream calls on a malformed
  completion because the OpenAI client and adapter both retry. Added incoming
  `json_object` proof plus per-phase packet-ID admission: duplicate attempts are
  rejected before recording or forwarding. A real `default_adapter` regression
  test now proves one malformed upstream call, one recorded request, and
  failure; exact-content SSE tests cover whitespace, escapes, and Unicode.
- 2026-07-10: Bounded constrained output to 48-character summaries,
  72-character rationales, one evidence item, and 128 output tokens after an
  unbounded nonstream request hit Ollama's own ten-minute cutoff at 97 generated
  tokens. The final real two-packet gate passed in about five minutes. Two
  independent corrective reviewers approved the final slice with no remaining
  blockers.
- 2026-07-10: Committed `60f4d2c`, passed the second authoritative dry-run and
  independent release-readiness review, then ran
  `bin/release.py all --retag` without skipped checks. Main and tag CI passed;
  x86 `local-llm` run `29137721906` passed; Release Gate `29137723988` passed.
- 2026-07-10: Publication verified. PyPI exposes exactly
  `backstitch-0.3.0-py3-none-any.whl` and `backstitch-0.3.0.tar.gz`; GitHub
  Release `v0.3.0` exposes those distributions plus
  `backstitch-v0.3.0.sigstore.json`. PyPI and GitHub distribution SHA-256
  digests match (`412909f9...60f99` wheel, `c0f8a18e...54573` sdist), the tag
  points to `60f4d2c`, and an isolated PyPI install reports `backstitch 0.3.0`.

## Out Of Scope

- Changing semantic-analysis classifications or relaxing evidence validation.
- Adding retries, majority voting, a larger model, or a cloud fallback.
- Adding public inference-option flags or config keys.
- Changing the production adapter, cloud live lane, or custom-provider behavior.
- Publishing a version other than the already prepared, still-unpublished
  `0.3.0` unless an external publication appears before retagging.
