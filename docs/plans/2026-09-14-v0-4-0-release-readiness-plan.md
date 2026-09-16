# Backstitch 0.4.0 Release Readiness Plan (2026-09-14)

Status: active; semantic response and CI recovery prerequisite completed

Class: 3+P. The work changes which external corpus participates in the
release precheck, a material verification-process boundary. It also performs
external repository-policy rollout and may cross the irreversible PyPI
publication boundary. No product spec changes are planned.

## Goal

Prepare and, only after every fail-closed gate succeeds, publish Backstitch
0.4.0. Remove Weft corpus ownership from Backstitch's suite, complete release
notes and plan state, configure the already-documented GitHub policy,
and obtain exact-SHA hosted evidence before tagging.

## Source Documents

- `docs/implementation/05-release-publishing.md` owns the release flow and
  repository policy.
- `docs/specs/02-backstitch-core.md` [SC-7], [SC-10], [SC-12] own the live
  proxy boundary, self-corpus behavior, and target-root behavior. Production
  discovery is not changed.
- `docs/plans/2026-08-23-gpt-5-6-luna-responses-plan.md` owns the pending
  model migration evidence.
- `docs/plans/2026-09-14-review-findings-remediation-plan.md` owns the seven
  completed remediation slices.
- User direction in this thread authorizes implementing the identified
  release-readiness steps.

Source spec baseline: `7c6d293`. No normative spec delta is proposed.

## Current Structure

- `tests/test_weft_corpus_traceability.py` makes Backstitch own a mutable
  external repository's debt baseline. A neighboring checkout enters a suite
  described as hermetic, while CI without that checkout skips the same test.
- `bin/release.py` requires a clean `main`, executes hermetic, benchmark,
  protected OpenAI, local-LLM, lint, type, and self-corpus checks, then pushes
  a release commit and waits for exact-SHA `CI` and `local-llm` success before
  creating the tag.
- `.github/workflows/release-gate.yml` installs the exact wheel and sdist
  before attestation and publication.
- At plan entry, `bin/release.py --check-repository-settings` reported that
  the documented external GitHub controls were absent. The execution log
  records their later rollout and current verified state.

Comprehension check: production Weft discovery is a supported target-root
feature and is outside this release cleanup. The cross-repository debt test is
deleted rather than copied, vendored, pinned, or retained behind an environment
switch. Weft can test Backstitch from its own repository if that relationship
is useful. The release helper remains fail-closed; no `--skip-checks`, tag
movement, or publication bypass is allowed.

## Invariants And Constraints

- Backstitch's suite owns no Weft content or mutable Weft debt baseline and is
  independent of neighboring checkout presence.
- Production sibling discovery and [SC-12] tests remain unchanged.
- The seven remediation commits remain intact and independently revertible.
- Existing user work is preserved. The untracked 2026-08-27 plan is recorded
  as superseded by the completed remediation plan, not discarded.
- GitHub settings must match the exact allowlist and tag policy already owned
  by `docs/implementation/05-release-publishing.md`; do not broaden them.
- PyPI acceptance and a pushed release tag are one-way doors. They occur only
  after local gates, exact-SHA CI, and exact-SHA local-LLM are green.
- The protected OpenAI qualification remains real. Provider failure blocks
  release; no receipt or freshness process is introduced.
- No native Windows runtime work, new test framework, dependency, or product
  behavior change is in scope.

## Deviation Log

| Baseline | Planned behavior | Actual behavior | Rationale |
|---|---|---|---|
| `5afb7e3` hosted pre-release gate | Existing local-LLM gate passes before release | The proxy was mutating production requests despite [SC-7], and its stale 128-token override truncated JSON mid-summary. The proxy is now observational: production configuration owns the existing 1024-token bound and the proxy only validates and records the exact request. | A failing release gate is a stop condition. Removing test-only transport behavior restores the specified ownership boundary and is simpler than maintaining a parallel decoder contract. |

## Tasks

1. Delete `tests/test_weft_corpus_traceability.py`. Do not copy, vendor, pin,
   or replace Weft with an environment-enrolled baseline in this repository.
   Correct only the live stale claim in the 2026-08-23 Luna plan's execution
   log; completed historical plan evidence remains historical and unchanged.
   Leave production target-root discovery alone. The pre-change failure was
   observed against the incidental sibling checkout; post-change proof is the
   complete hermetic suite plus `tests/test_target_roots.py`. Do not add a
   meta-test asserting that the deleted test remains absent.
2. Mark the 2026-08-27 publication plan superseded by the completed
   2026-09-14 remediation plan and index it, preserving its historical text.
3. Update `CHANGELOG.md` for the Luna Responses migration, intent-coverage and
   semantic features, supply-chain hardening, seven remediation fixes, and
   truthful POSIX support. Prepare version 0.4.0 through the release helper,
   not by hand.
4. Run focused tests, actual protected OpenAI qualification, and the
   zero-warning self-corpus check. Independently review the completed source
   delta. The release helper owns the one final full local gate; do not run a
   duplicate full release suite as ceremony.
5. The user's instruction to implement the identified release steps authorizes
   the required GitHub settings mutation. Before mutation, capture the current
   repository immutable-release flag, Actions permissions and SHA-pinning
   flag, `pypi` environment deployment policy, and release-tag rulesets. Apply
   only the exact checker-owned values in
   `docs/implementation/05-release-publishing.md`: immutable releases enabled;
   selected Actions with full-SHA pinning, GitHub-owned actions allowed,
   verified creators disabled, and exactly the four listed third-party
   patterns; `pypi` custom deployment policy exactly `v*`; and one active
   `Protect release tags` ruleset over `refs/tags/v*` with only update and
   deletion prevention, no exclusions or bypass actors. Re-run the checker
   after each logical group and finally; stop on any mismatch.
6. Push the release candidate through `bin/release.py --version 0.4.0`. Wait
   for exact-SHA `CI` and `local-llm`. If either fails, fix forward and repeat
   with no tag. Once green, allow the helper to create the immutable tag.
7. Wait for the tag release workflow. Verify PyPI 0.4.0, both distributions,
   attestation, immutable GitHub Release, and matching SHAs. Close this plan
   and the Luna plan only after their remote evidence exists.

## Verification

```bash
uv run pytest tests/test_target_roots.py -q
uv run pytest tests -q -n auto --dist loadgroup -m "not live_llm and not benchmark"
uv run pytest tests -q -n 0 -m benchmark
env -u LLM_MODEL BACKSTITCH_LIVE_LLM=1 BACKSTITCH_LIVE_LLM_KIND=openai \
  PYTEST_ADDOPTS='-x --maxfail=1' uv run pytest tests/live/test_live_llm.py -q -s
uv run ruff format --check backstitch bin .github/scripts tests
uv run --frozen --no-sync ruff check . bin/check-doc-paths bin/check-dom15-fixtures bin/coalesce-check
uv run mypy backstitch bin/release.py tests --config-file pyproject.toml
python bin/check-doc-paths
python bin/check-dom15-fixtures
uv run backstitch check --repo-root .
bin/release.py --check-repository-settings
```

Hosted success is exact-SHA green `CI` and `local-llm`, followed by a green
`Release Gate (backstitch)` for `v0.4.0` and matching PyPI/GitHub artifacts.

## Rollback And Stop Conditions

Before the tag, revert the narrow source/docs commits if needed. Preserve the
pre-mutation GitHub snapshot so reversible Actions/environment/ruleset settings
can be restored explicitly; enabling immutable releases may be irreversible
and therefore occurs only after the other settings have been validated. Stop
before tagging on any dirty tree, local failure, policy
mismatch, provider qualification failure, or hosted workflow failure. After
the release tag is pushed or PyPI accepts 0.4.0, never move or replace the tag
or artifacts; recover with a new version.

## Independent Review

Before implementation, review the Weft decoupling boundary for correctness
and YAGNI. Before release, review the complete delta and every
gate result. Tests must enforce correctness, not review choreography or a
temporary freshness rule.

## Execution Log

- The pre-change Weft failure was reproduced against the incidental sibling
  checkout. Backstitch's mutable Weft debt test was deleted without a copied,
  vendored, pinned, environment-enrolled, or absence-enforcing replacement.
  Production target-root tests remained green. The self-corpus suppression
  count moved from 240 to the observed 237 records.
- The 2026-08-27 publication plan was preserved and indexed as superseded by
  the completed remediation plan. `CHANGELOG.md` now describes the 0.4.0
  payload.
- The protected real-provider qualification passed for GPT-5.6 Luna and the
  GPT-5.5 comparison, one accepted attempt each.
- Before GitHub mutation, immutable releases were disabled; Actions allowed
  all actions without SHA pinning; the `pypi` environment had no deployment
  policy; and no repository rulesets existed. The reversible Actions policy,
  exact four-pattern allowlist, `pypi` custom `v*` tag policy, and exact
  release-tag ruleset were applied and inspected first. Immutable releases
  were then enabled. The final live repository-settings checker passed all
  four groups.
- Independent source review found one formatting defect in the adjusted
  self-corpus count. It was corrected and folded into the Weft-decoupling
  commit. No source or GitHub-policy blocker remained.
- The canonical release helper's first attempt stopped before mutation because
  no local Ollama endpoint was running. With the workflow-pinned image and
  model configuration running, both macOS and hosted Linux reproduced the same
  malformed invariant results. Exact response capture showed the local proxy's
  stale 128-token request limit truncating JSON mid-summary. Review then found
  the proxy's request mutation violated [SC-7]. The correction removes proxy
  mutation, validates the adapter's exact production schema, and lets the
  production descriptor supply the workflow's existing 1024-token limit.
- The corrected exact local lane exceeded its 900-second aggregate analyze
  timeout on this macOS host. This does not qualify the change. The existing
  hosted Linux `local-llm` lane must pass at the candidate SHA within its own
  15-minute step limit before release work may continue; neither timeout is
  being raised without runner evidence.
- Hosted Linux at `5b02612` completed both real-model analyses in about 158
  seconds. Results reached the post-analysis wire assertion, where the run
  correctly exposed one stale expectation for the deleted nonstream bridge:
  actual production requests used `stream = true` with usage enabled. The
  assertion now pins that production behavior; no timeout or model bound changed.
- Hosted Linux at `53e9809` then completed real analysis and exposed a product
  contract gap: the provider schema admitted an invariant `weak_binding`
  response without the `requirement` evidence that [SEM-5] normalization
  requires. Main CI also exposed a cross-runtime Wilson-report defect and
  three over-specified tests. The bounded recovery plan completed at `f70d966`:
  exact-SHA CI run `34991793052` and hosted local-LLM run `34991792986` passed.
  Release work may resume without broadening this plan's original no-spec-change
  scope. The longstanding zero-job
  semantic workflows remain separate diagnosis work until their exact GitHub
  validation error is known; they are not made a release gate here.
- The documentation-only closure commit then encountered three Ollama 0.31.1
  `llama-server` segmentation faults while loading the unchanged model, before
  Backstitch analysis began. The workflow now pins Ollama 0.34.0. Because the
  image digest is part of the existing model-cache key, this update also gets a
  clean model download without adding cache deletion or retry machinery.
- A hosted Linux bake-off at run `35009892768` qualified
  `qwen2.5-coder:14b-instruct-q4_K_M` against the unchanged live semantic lane.
  The test passed in 11:05 within the existing 15-minute limit, with 5 GB of
  memory available and no swap used. The workflow and release helper now use
  that code-focused model; context and output bounds remain unchanged.
- A release rehearsal on the ARM64 local CI analogue exposed an Ollama CPU
  scaling cliff rather than a model-capacity failure. With the container free
  to see 16 CPUs, automatic 16-thread inference produced 0.40 tokens/second;
  the same image and model produced 31.8 tokens/second when both the container
  and served model were bounded to the public `ubuntu-latest` four-vCPU shape.
  The exact local live gate then passed in 134.12 seconds. The workflow now
  makes its four-CPU/16-GiB boundary explicit, and the release helper records
  the same four-thread model parameter. Its local live command also has a real
  25-minute aggregate deadline rather than relying on per-request timeouts.
