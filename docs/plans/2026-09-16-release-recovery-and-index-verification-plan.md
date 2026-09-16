# Release Recovery And Indexed-Artifact Verification Plan

Status: Completed — source implementation and independent review passed;
external qualification is deferred to the next real release

Class: 4 — risky. The work changes a maintainer CLI contract and an asynchronous
publication workflow across the irreversible PyPI boundary. No product spec
change is required because `docs/implementation/05-release-publishing.md` owns
the release process as an operational contract.

## Goal

Adopt the parts of SimpleBroker's release process that close real Backstitch
failure modes without importing its multi-package complexity:

1. allow an immutable release tag to start a replacement release-gate run when
   GitHub has no rerunnable run
2. prevent a new same-tag attempt from cancelling the running attempt that may
   be at or beyond the PyPI publication boundary (GitHub may still supersede an
   older pending attempt)
3. verify that PyPI serves the exact wheel and source distribution that the
   gate built, then smoke-test those downloaded files before making the GitHub
   Release public
4. remove `--skip-checks` from real release creation because it suppresses
   release qualifications that hosted CI does not duplicate, including the
   cloud-live provider test, serial benchmarks, and self-corpus gate; recovery
   uses the explicit immutable-tag path

The design must preserve Backstitch's stronger existing controls: exact-SHA CI
and local-LLM qualification, write-once tags, locked builds, pre-publication
wheel and sdist smoke tests, attestations, draft-first publication, exact
release-target and asset validation, and immutable GitHub Releases.

## Source Documents And Baseline

Source specs:

- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-11], [DOM-15]
- `docs/specs/02-backstitch-core.md` [SC-5], [SC-10]

Operational contract and prior plans:

- `docs/implementation/05-release-publishing.md`
- `docs/plans/2026-08-24-release-supply-chain-and-publication-hardening-plan.md`
- `../simplebroker/.github/workflows/release-gate.yml`
- `../simplebroker/bin/release.py` (`_remote_tag_reuse_note`)
- `../simplebroker/bin/packaging-smoke` and its implementation/tests

Baseline:

- `69e15587312d148724cb1ca060ddcc41c4d38f74` — Backstitch code,
  specifications, tests, and release-publishing implementation note at plan
  authoring time
- SimpleBroker is a design input, not a governing contract. Recheck its exact
  behavior at implementation time; do not copy code or package-topology rules
  without reconciling them to Backstitch's single-package model.

## Context And Key Files

Read these before editing:

- `.github/workflows/release-gate.yml` currently runs only on a `v*` tag push
  and uses `release-gate-${{ github.ref }}` with
  `cancel-in-progress: true`. It builds and smokes the local wheel and sdist,
  stages a complete draft, publishes to PyPI, then validates and publishes the
  GitHub draft.
- `bin/release.py` owns release preparation, local prechecks, exact-SHA hosted
  checks, tag creation/reuse, and operator output. `_remote_tag_reuse_note`
  currently says to rerun Actions manually but cannot give a launch command.
  `--skip-checks` suppresses local prechecks for both new and recovery-shaped
  invocations, while hosted exact-SHA qualification remains mandatory.
- `.github/scripts/release_publication.py` owns draft replacement, exact tag
  and release-target checks, exact asset checks, the immutable publish
  transition, and a bounded PyPI visibility poll used only for an already
  published rerun. The current workflow does **not** reach that rerun branch:
  `stage-github-release` calls `replace_draft` first, which rejects a published
  release, and a rerun after PyPI but before GitHub publication would attempt a
  duplicate upload. This plan must repair that state machine, not merely add a
  post-upload check.
- `tests/test_release_workflow.py`, `tests/test_release_script.py`, and
  `tests/test_release_publication_script.py` contain the release contract
  tests. Tests must assert parsed jobs, dependencies, inputs, and observable
  behavior rather than incidental YAML text or private call order.
- `docs/implementation/05-release-publishing.md`,
  `docs/implementation/02-repository-map.md`, and the README release section
  describe the operator-facing process.
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md` governs the
  final acceptance probes.

Expected comprehension answers must be recorded in this plan's execution log
before implementation starts. A wrong answer blocks editing until the cited
owner is reread:

1. **Where is the publication one-way door?** PyPI accepting a version. Before
   that point a failed run can replace its exact matching draft; after it, the
   version and remote tag must not be moved or replaced, and recovery is either
   an exact idempotent completion or a new fix-forward version.
2. **Why is `workflow_dispatch` safe only from a tag ref?** GitHub executes the
   workflow definition and code from the selected ref. A branch dispatch would
   make `github.ref_name` look like a release tag input while allowing mutable
   source. The gate must reject every ref except `refs/tags/v*` before build or
   publication and must still prove the remote tag points at `github.sha`.
3. **What must indexed verification compare?** For a fresh publication, the
   exact filenames and SHA-256 digests in PyPI's version metadata must equal
   the wheel and sdist produced by the current run. For recovery after PyPI
   acceptance, they must equal the preserved exact draft or public-release
   distribution assets; no fresh-build equality is assumed. The verifier must
   download the indexed URLs, verify their bytes, and smoke-test both outside
   the checkout. Merely observing `backstitch X.Y.Z` in project metadata is
   insufficient.

## Invariants And Constraints

- Remote `v*` tags remain write-once. No recovery path may create, move,
  delete, or replace an existing remote tag.
- A manual dispatch is valid only when `github.ref` is an existing `v*` tag and
  the remote tag resolves to `github.sha`. Invalid dispatches fail before any
  build, draft mutation, attestation, or publication step.
- A new same-tag release run never cancels the currently running release run.
  GitHub may supersede an older pending attempt in the same concurrency group;
  the process does not promise an unbounded queue. Different tags retain
  independent concurrency groups.
- The exact release commit must still have successful `CI` and `local-llm`
  runs. Dispatch is recovery transport, not a qualification bypass.
- A fresh publication builds once and uses that run's stored distributions.
  Recovery after PyPI publication treats the preserved exact GitHub draft (or
  public release) assets as the artifact ledger; it must not assume a second
  build is byte-reproducible. A recovery run may skip building when the exact
  ledger already exists.
- PyPI verification is fail-closed. Missing files, extra release files,
  filename mismatch, digest mismatch, download failure, timeout, install
  failure, wrong import origin, or smoke-command failure prevents GitHub
  publication.
- The expected PyPI release set is exactly one wheel and one sdist. Attestation
  bundles are GitHub assets, not PyPI distributions.
- Each downloaded distribution is installed into a fresh environment outside
  the checkout. Import origin, `backstitch --version`, alignment-guide JSON,
  and `backstitch check --repo-root <checkout>` remain the smoke contract.
- GitHub draft target-SHA and exact-asset validation remains the final owner of
  the public-release transition. Indexed verification must not duplicate or
  weaken that state machine.
- PyPI state is inspected before any draft mutation or upload. Only `absent`
  and `exact` are valid states. A partial release, wrong release set, or digest
  mismatch is fatal; the workflow never relies on a broad `skip-existing`
  publisher option.
- Network retries are bounded and distinguish eventual-consistency absence
  from malformed metadata and integrity mismatch. Only absence and explicitly
  retryable transport errors retry; a digest or release-set mismatch is fatal
  immediately.
- Do not add runtime dependencies. The verifier should use the standard
  library plus existing `uv`/Python tooling available in the release job.
- Removing `--skip-checks` is intentional. Do not replace it with another
  generic bypass. Dry runs remain non-mutating and print their planned checks;
  immutable-tag recovery runs through Actions directly.
- No changes to package versioning, tag namespace, required hosted workflows,
  repository settings, action allowlist, or Trusted Publishing identity are in
  scope.

## Hidden Couplings And Failure Priorities

- GitHub evaluates `workflow_dispatch` from the selected ref. Old tags created
  before this trigger lands cannot gain the trigger retroactively. Their only
  safe recovery is rerunning an existing Actions run or publishing a new
  version; documentation and helper output must say this.
- `github.ref`, `github.ref_name`, `github.sha`, checkout refs, tag-version
  validation, and the remote-tag query jointly establish immutable identity.
  Do not weaken any one because another appears redundant.
- A later same-tag run may start after the first has already published to PyPI
  or GitHub. It must classify existing state before draft mutation or upload,
  preserve the exact matching draft/public assets as its ledger, and converge
  by validation rather than overwrite immutable state.
- Current `replace_draft` behavior is only safe on the pre-PyPI path. It must
  never run against a draft whose distribution assets are the ledger for an
  already published PyPI version.
- PyPI may acknowledge upload before its JSON endpoint and files are globally
  visible. Bounded visibility polling belongs between PyPI publication and
  GitHub publication.
- A true integrity mismatch after PyPI acceptance is fatal even though it
  leaves a draft GitHub Release. Publishing a knowingly mismatched draft would
  hide the stronger problem. Operator recovery is a reviewed manual completion
  of the exact draft only after independent verification, or a new fix-forward
  version when integrity cannot be established.
- Logging and retry diagnostics are useful but secondary. Failure to format an
  optional diagnostic must not obscure the underlying fatal reason; there is
  no best-effort path for identity or artifact-integrity checks.

## Rollout, One-Way Door, And Rollback

Roll out in this order:

1. Land all source, tests, and docs together. Do not push a release tag from a
   commit that has only part of this design.
2. Exercise a manual dispatch against a non-release branch and prove it fails
   in the ref guard before build. This is a safe negative probe.
3. Exercise dispatch against an existing non-production test tag only if the
   repository has an owner-approved disposable tag namespace covered by the
   same protections. Otherwise defer the positive external probe to the next
   real release; do not create a throwaway `v*` version.
4. The first real release after landing is the positive acceptance event.
   Confirm that the running release was not cancelled, exact indexed digests,
   both indexed smoke tests, exact GitHub target/assets, and final immutability
   from the run log and public services. Do not intentionally launch a second
   run near publication merely to demonstrate concurrency. Observe the
   recovery behavior when it is naturally needed, unless the owner separately
   authorizes a controlled dispatch.

Before any new release tag is pushed, rollback is a normal revert of this
change. After a tag containing the new workflow exists, reverting `main` does
not change that tag's frozen workflow. Never move the tag to apply a fix.

After PyPI accepts a version, source rollback cannot unpublish it. If indexed
verification exposes a real mismatch, leave the GitHub Release as a draft,
preserve the logs and artifacts, and issue a new version. If the verifier
itself is conclusively defective but the indexed bytes independently match,
an owner may manually complete the already staged exact draft using the
existing publication helper from a clean checkout of the tag; the incident and
evidence must be recorded before the transition. This is break-glass recovery,
not an automated fallback.

## Dependency-Ordered Tasks

### Slice 0 — Contract tests first

Add failing tests for externally visible contracts before production edits:

- parse the release workflow and prove it accepts both `push.tags: v*` and
  `workflow_dispatch`
- prove the concurrency group remains tag/ref-specific and
  `cancel-in-progress` is false
- prove a dispatch ref guard precedes all jobs capable of building or mutating
  release state, and that downstream jobs depend on it
- prove publication-state inspection precedes draft mutation and PyPI upload;
  the indexed-verification job follows any required upload and precedes public
  GitHub publication
- prove the release helper's remote-tag note contains the exact guarded
  dispatch command and the old-tag limitation
- prove `--skip-checks` is rejected rather than silently accepted
- specify the full absent/draft/public plus absent/exact PyPI state matrix and
  PyPI release-set, digest, retry, download, installation, import-origin, and
  smoke-command behavior at the verifier's public seam

Tests may inspect workflow structure, job dependencies, permissions, and
commands. They must not assert incidental line positions, comments, or exact
private helper choreography.

**Stop and re-evaluate:** stop if the tests require a new YAML dependency or a
general workflow parser. Use the repository's existing active-workflow and
named-step helpers unless they cannot express an actual contract.

### Slice 1 — Safe same-tag dispatch and serialization

In `.github/workflows/release-gate.yml`:

1. add `workflow_dispatch`
2. change release concurrency to `cancel-in-progress: false`; document and
   test the actual guarantee that a new run does not cancel the running run,
   while GitHub may supersede an older pending run
3. add a first job that fails unless `github.ref` matches `refs/tags/v*`
4. make `require-ci` depend on that job so no build or release mutation can run
   for a branch dispatch
5. retain the current remote-tag-to-`github.sha` proof in
   `verify-tag-current`

In `bin/release.py`, revise `_remote_tag_reuse_note` to print:

```text
gh workflow run release-gate.yml --ref vX.Y.Z
```

The note must say the command is valid only when that immutable tag already
contains the dispatch trigger. It must direct older tags to rerun an existing
Actions run when available or choose a new version. The helper must not attempt
to dispatch automatically.

**Stop and re-evaluate:** stop if enabling dispatch requires broader token
permissions, changes checkout identity, or permits an arbitrary version input.
The ref is the sole release identity.

### Slice 2 — Make recovery an explicit publication state machine

Before any draft replacement or PyPI upload, add a read-only state-resolution
job backed by `release_publication.py`. It must validate the remote tag SHA and
classify GitHub Release and PyPI state. Expose only the minimum typed outputs
needed for workflow conditions; do not infer state independently in shell.

The allowed matrix is:

| GitHub state | PyPI state | Required action |
|--------------|------------|-----------------|
| absent | absent | Build, stage the exact draft, publish to PyPI, verify indexed bytes, publish the draft |
| exact draft | absent | Build; replace the pre-PyPI draft with this run's exact artifacts, publish to PyPI, verify, publish |
| exact draft | exact | Preserve the draft as the artifact ledger; compare its wheel/sdist bytes with PyPI, smoke indexed bytes, then publish that draft; do not build, replace, or upload |
| exact immutable public release | exact | Validate target/assets and compare its wheel/sdist bytes with PyPI; smoke indexed bytes; perform no mutation or upload |
| absent | exact | Fail: the required GitHub artifact ledger is missing |
| exact immutable public release | absent | Fail: public services disagree |
| any wrong target, asset set, mutable public release, partial PyPI release, or digest mismatch | any | Fail before mutation |

For `exact` PyPI classification, identity means the expected package/version
and exactly one wheel plus one sdist are present. When a GitHub draft or public
release exists, `exact` additionally requires the indexed filenames and
SHA-256 digests to match its downloaded distribution assets. A mere version
presence check is never enough.

Workflow jobs and conditions must implement these branches explicitly:

- build and draft staging run only for the two `PyPI absent` states
- Trusted Publishing runs only after an exact draft has been staged for an
  `absent` PyPI version
- indexed verification runs for both fresh publication and exact recovery
- final GitHub publication runs only after indexed verification and only for
  an exact draft; the already-public branch is validation-only success

Do not make skipped-job behavior implicit. Use explicit state outputs and
conditions so every allowed row has a test that proves which mutation-capable
jobs run.

**Stop and re-evaluate:** stop if state is checked only after draft replacement
or upload, if a generic publisher `skip-existing` option substitutes for the
matrix, or if recovery depends on a fresh build matching old archive bytes.

### Slice 3 — Verify the distributions PyPI actually serves

Add `.github/scripts/verify_pypi_release.py` as the narrowly owned indexed-byte
and install-smoke verifier. Keep GitHub draft mutation in
`release_publication.py`; the new verifier's public CLI receives:

- package name
- exact version
- paths to the expected local wheel and sdist
- a temporary work root or creates one safely
- repository root for the final `backstitch check` smoke probe

The verifier must:

1. poll `https://pypi.org/pypi/<normalized-name>/<version>/json` with bounded
   delays until the exact version is visible
2. require metadata for exactly one wheel and one sdist and reject unexpected
   distribution types or filenames
3. compute SHA-256 for the workflow's local distributions and require exact
   filename/digest equality with PyPI metadata
4. fetch metadata only over HTTPS from `pypi.org`; download artifacts without
   credentials over HTTPS, with bounded redirects and response-size limits,
   and require the final response host to be `files.pythonhosted.org`; validate
   each downloaded SHA-256 before use
5. create separate clean virtual environments outside the checkout, install
   each downloaded file, prove `backstitch` imports from that environment, and
   run the same four smoke probes as the pre-publication build job
6. clean temporary files on success and failure without hiding the primary
   error

Add a `verify-pypi-release` job after the conditional publisher. For a fresh
publication it downloads this run's distributions as the expected ledger. For
recovery it downloads the preserved draft/public release distributions as the
expected ledger. It checks out the exact SHA for the repository smoke probe,
installs only the tools needed for verification, and runs the verifier.
`publish-github-release` must require successful indexed verification rather
than depending directly on the publisher.

Consolidate duplicate PyPI polling only when that leaves one clear owner and
preserves the GitHub publication state machine. The existing
`publish_draft()` already-public shortcut may be removed or narrowed once the
new preflight state owner makes it unreachable; do not leave two competing
rerun state machines.

**Stop and re-evaluate:** stop if the implementation rebuilds artifacts,
resolves `backstitch==X.Y.Z` through pip instead of downloading metadata-named
files, imports Backstitch from the checkout, or creates a second GitHub release
publication path.

### Slice 4 — Remove the ambiguous local-check bypass

Remove `--skip-checks` from `bin/release.py`, its tests, and operator docs.
Every real helper-driven release runs local prechecks, then exact-SHA hosted
checks. This is not mere duplication: `build_precheck_commands()` includes the
cloud-live provider test, serial benchmark lane, and self-corpus checks that
the required hosted workflows do not all reproduce. A dry run remains fast
because it only prints commands. Recovery of an existing immutable tag uses
the explicit Actions dispatch/rerun path and does not rerun the
release-preparation helper.

Do not turn this into a general CLI redesign. Preserve `core`, `all`,
`--version`, `--publish`, `--dry-run`, and `--check-repository-settings` unless
a separate plan authorizes their change.

Before removal, search in-repo automation and recent release records for real
consumers. **Stop and re-evaluate:** stop if a documented automation outside
this repo depends on `--skip-checks`, or if the cloud-live credential is not
operationally available to maintainers. Record the consumer or credential gap
and decide whether a bounded deprecation or a narrower named qualification
policy is needed; do not retain a generic bypass by default.

### Slice 5 — Documentation and operator recovery

Update:

- `docs/implementation/05-release-publishing.md` with tag-scoped dispatch,
  running-run preservation (and pending-run limitation), the exact recovery command and old-tag limitation,
  indexed artifact verification, failure meanings, and break-glass recovery
- `docs/implementation/02-repository-map.md` if a new verifier file is added
- the README release section only where its short operator flow changes

State plainly that source recovery improvements apply only to tags whose
frozen workflow contains them. Do not imply that merging to `main` repairs an
old immutable tag.

**Stop and re-evaluate:** stop if documentation suggests deleting/moving a tag,
republishing a PyPI version, or bypassing exact-SHA checks.

## Testing Plan

Keep real:

- wheel and sdist creation with the locked build frontend
- installation of local artifacts and downloaded artifacts into distinct real
  virtual environments
- import-origin checks and all smoke commands
- workflow dependency and permission inspection
- SHA-256 computation over real fixture files
- temporary-directory cleanup

Limited mocks/fakes are acceptable for:

- PyPI JSON responses and file downloads in unit tests, using a local HTTP
  server or injected transport whose returned bytes are still hashed
- bounded sleep so retry tests do not wait in wall-clock time
- subprocess outcomes only in focused error-mapping tests; at least one
  integration test must execute the real install-and-smoke path from local
  distribution files

Required cases include:

- branch dispatch rejected before build
- valid immutable-tag dispatch follows normal exact-SHA qualification
- a new same-tag run cannot cancel the running release; tests do not claim that
  GitHub preserves every pending attempt
- every allowed publication-state row selects only its named build, staging,
  upload, verification, and final-publication actions
- absent-GitHub/exact-PyPI, public-GitHub/absent-PyPI, partial PyPI, wrong
  target/assets, and mutable-public-release states fail before mutation
- an exact draft with exact PyPI artifacts is preserved and completed without
  rebuild, replacement, or upload
- an exact public release with exact PyPI artifacts is validation-only success
- PyPI metadata absent then visible succeeds within the bound
- malformed metadata, wrong version/name, missing or extra distribution,
  filename mismatch, local digest mismatch, downloaded digest mismatch, and
  exhausted visibility retry all fail closed
- wheel and sdist each install and smoke independently outside the checkout
- old remote-tag guidance never claims dispatch can repair a tag that lacks the
  trigger
- `--skip-checks` produces argparse's nonzero unknown-option result

## Verification And Gates

Run after each relevant slice, then rerun the complete set from the final tree:

```bash
uv run --frozen --no-sync pytest -q \
  tests/test_release_workflow.py \
  tests/test_release_script.py \
  tests/test_release_publication_script.py \
  tests/test_verify_pypi_release.py \
  tests/test_release_workflow_gate.py
bin/bump_uv.py --check
uv run --frozen --no-sync ruff format --check backstitch bin .github/scripts tests
uv run --frozen --no-sync ruff check . bin/check-doc-paths bin/check-dom15-fixtures bin/coalesce-check
uv run --frozen --no-sync python bin/ruff_suppression_index.py --check
uv run --frozen --no-sync mypy backstitch bin/release.py \
  .github/scripts/verify_pypi_release.py tests --config-file pyproject.toml
uv run --frozen --no-sync python -m py_compile \
  .github/scripts/require_green_workflows.py \
  .github/scripts/release_publication.py \
  .github/scripts/verify_pypi_release.py
uv run --frozen --no-sync pytest tests -q -n auto --dist loadgroup -m "not live_llm and not benchmark"
uv run --frozen --no-sync pytest tests -q -n 0 -m benchmark
env -u BACKSTITCH_LIVE_LLM uv run --frozen --no-sync pytest \
  tests/live/test_live_llm.py -q -o run_live_llm=false
uv run --frozen --no-sync pytest tests/acceptance -q
uv sync --frozen --group release
uv run --frozen --no-sync python -m build --no-isolation
uv run --frozen --no-sync backstitch check --repo-root .
```

The final self-corpus command must exit 0 with zero errors and zero warnings.

External rollout evidence, required before calling the release-process change
operationally qualified:

- a non-tag manual dispatch fails at the ref guard before build
- the first real release run records exact local/PyPI filename and digest
  agreement for one wheel and one sdist
- both downloaded artifacts pass their isolated smoke probes
- the public GitHub Release still targets the exact tag SHA, has the exact
  expected assets, and is immutable
- if a same-tag recovery run is naturally needed, it converges through the
  exact state-machine branch without replacing or re-uploading published bytes

## Independent Review Loop

Before implementation, an independent reviewer must inspect the plan against
the baseline source and SimpleBroker reference, then answer:

1. Can any dispatch reach build or mutation from a mutable ref?
2. Can any same-tag run cancel another near the PyPI boundary?
3. Does indexed verification prove bytes, or only metadata/version presence?
4. Can a retry overwrite or weaken immutable state?
5. Is the post-PyPI failure and break-glass story explicit and safe?
6. Does removing `--skip-checks` strand a real in-repo operator path?

Record each finding and disposition below. Implementation remains blocked
until every material finding is incorporated or explicitly rejected with
evidence. After implementation, run a second independent review over the diff
and verification evidence before landing.

## Review Record

Independent pre-implementation review: PASS after two rounds on 2026-09-16.

The first round found eight issues. The plan now:

- defines the complete pre-mutation GitHub/PyPI state matrix instead of
  assuming the current workflow is rerunnable
- preserves the exact draft/public assets as the recovery ledger instead of
  assuming independent builds are byte-reproducible
- states GitHub's real concurrency guarantee: the running job is preserved,
  but an older pending job may be superseded
- inspects PyPI before upload and never substitutes `skip-existing` for state
  classification
- fixes the download trust boundary to HTTPS `pypi.org` metadata and final
  `files.pythonhosted.org` artifact responses with digest checks
- names the verifier test owner and type-check gate
- avoids an unsafe synthetic concurrency exercise on the first real release
- grounds `--skip-checks` removal in distinct local release qualifications

The rereview found one stale comprehension answer that still assumed a fresh
build during recovery. It was corrected to distinguish current-run artifacts
from the preserved draft/public artifact ledger. No implementation blockers
remain.

Independent completed-work review: PASS after two rounds on 2026-09-16. The
first round found a release-blocking transient-404 race and brittle workflow
tests. State resolution now performs bounded absence retries whenever a
matching GitHub artifact ledger exists, so a `404 -> exact` transition selects
the no-build/no-replacement/no-upload recovery branch. Workflow tests now
parse job blocks, dependencies, and conditions and evaluate all four safe
state rows against the actual expressions. Rereview found no remaining
blockers.

## Deviation Log

| Baseline/owner | Planned behavior | Actual behavior | Rationale | Reconciliation |
|----------------|------------------|-----------------|-----------|----------------|

## Execution Log

### 2026-09-16 — implementation entry

Comprehension answers recorded before implementation edits:

1. PyPI accepting a version is the one-way door. Before it, an exact matching
   draft may be replaced. After it, neither version nor tag may move; recovery
   validates and completes the preserved exact artifact ledger or issues a new
   fix-forward version.
2. Manual dispatch is safe only from `refs/tags/v*` because GitHub executes the
   workflow and code at the selected ref. The preflight ref guard and the
   independent remote-tag-to-`github.sha` proof both remain mandatory before
   build or mutation.
3. Fresh publication compares PyPI filenames and SHA-256 digests with the
   current run's wheel and sdist. Recovery compares them with the preserved
   exact draft/public distribution assets and assumes nothing about a fresh
   build. Both indexed files are downloaded, hashed, installed separately
   outside the checkout, and smoke-tested.

Pre-edit consumer check: repository search found `--skip-checks` only in the
release helper, its tests, and the release implementation note. No in-repo
automation consumes it. External consumers remain unknowable from source; the
flag is maintainer-only and the operational contract will record its removal.

Implemented slices:

- tag-only manual dispatch, a fail-closed ref guard, and running-attempt
  preservation through `cancel-in-progress: false`
- pre-mutation GitHub/PyPI state resolution with bounded transient-404
  recovery and explicit mutation conditions
- exact indexed filename/digest verification, bounded trusted downloads, and
  real isolated wheel/sdist smoke tests
- removal of the generic `--skip-checks` path and guarded recovery guidance
- release implementation notes and repository map updates

Verification evidence before landing:

- release-focused suite, including real wheel/sdist build and isolated install
  probes: passed
- Ruff format/check, suppression index, mypy, `py_compile`, UV policy, and YAML
  parse: passed
- non-live/non-benchmark suite: passed under the canonical xdist command
- benchmark lane: passed; runner qualification remains reported as unavailable
  under its existing contract
- disabled-live probe: one expected skip
- acceptance suite: passed
- frozen release sync and locked build: passed; one wheel and one sdist built
- hermetic self-corpus: exit 0 with zero errors and zero warnings
- independent completed-work rereview: PASS

External negative dispatch and first-real-release evidence remain rollout
gates. They require GitHub Actions and the next real publication; they are not
local source-completion gates.

Final commit SHA is recorded when this plan lands. Do not record transient
worktree state.

## Out Of Scope

- SimpleBroker's multi-package batching, extension dependency ordering,
  backend compatibility floors, tag namespaces, and database-service matrices
- changing Backstitch's supported Python versions or build frontend
- changing GitHub repository policy, Trusted Publishing identity, release
  asset set, or attestation format
- auto-dispatching recovery from `bin/release.py`
- retrofitting immutable old tags with a workflow trigger
- a generic downloader, package installer, or release framework
- unrelated release-helper cleanup or test rewrites

## Fresh-Eyes Review

Before requesting implementation review, reread only the goal, invariants,
rollout/rollback, tasks, and tests. Confirm that every task maps to a named
failure mode, every named file exists, no task depends on moving an immutable
tag, and the plan does not weaken an existing Backstitch control merely to
match SimpleBroker.
