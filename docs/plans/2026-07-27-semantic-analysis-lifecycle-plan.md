# Semantic Analysis Lifecycle Plan

Status: Independent same-model review PASS (round 2, 2026-07-27); Claude
cross-model review PASS after focused follow-up (2026-07-27); Slices 1-4
implemented and final independent review PASS, but uncommitted; the landing
gate remains pending an owner-authorized commit.

Plan type: implementation with spec revision.

Class: 5 (changes the normative ownership and CI lifecycle of semantic cache
objects and run reports), with class-4 hardening because the work crosses a
secret-bearing CI boundary and changes persistence, cleanup, and rollout
expectations.

Risk level: medium-high. The cache engine and its three modes already implement
the required local behavior. The main risk is not cache lookup. It is putting
the right bytes, configuration, credentials, and write targets on the right
side of the CI trust boundary without turning a disposable accelerator into
semantic authority.

## Goal

Give Backstitch the same clear lifecycle separation that mature analysis tools
use:

1. each invocation that reaches artifact publication creates a fresh
   operational report for the current source; earlier failures remain explicit
   errors and logs rather than fabricated reports;
2. immutable semantic cache objects memoize only expensive provider work whose
   complete inference identity is unchanged;
3. normal refresh reuses valid hits, calls the provider only for misses, and
   writes successful misses;
4. zero-call replay remains an explicit mode that fails closed on any miss;
5. deliberate resampling remains explicit through cache-off execution or a
   changed search epoch;
6. local and CI caches are disposable, ignored acceleration state rather than
   committed review evidence; and
7. a trusted, report-only CI envelope may analyze an exact untrusted pull
   request revision as data without executing pull-request code or exposing
   provider credentials to pull-request-controlled configuration.

This plan removes the current committed-cache mental model. It does not add a
durable snapshot product. If Backstitch later needs provider-free replay from a
clean checkout for an indefinite period, that is a distinct reviewed-snapshot
feature with its own authority and retention contract.

## Source Documents

- `docs/specs/06-semantic-gates.md` [SEM-2], [SEM-3], [SEM-4], [SEM-7],
  [SEM-9], [SEM-10]
- `docs/specs/07-verification-and-evidence-cases.md` [EVC-5.1], [EVC-8.2],
  [EVC-9.1], [EVC-11], [EVC-12]
- `docs/implementation/07-deterministic-semantic-gate.md`
- `docs/plans/2026-07-11-deterministic-semantic-gate-plan.md`
- `docs/plans/2026-07-16-evidence-spike-hardening-plan.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- archive branch `semantic-evidence-archive` at
  `74b28160316edae4cd5790ea7cf81c813aa810da`, which preserves the removed
  schema-2 cache and historical review artifacts

## Spec Baseline

- Planning branch and commit: `main` at
  `66c84d83f8934cdd869b97ab23e28670d95773c7`.
- The semantic implementation is an uncommitted, active worktree over that
  commit. The files below are therefore identified by current-worktree hashes,
  not falsely attributed to `HEAD`:
  - `docs/specs/06-semantic-gates.md`:
    `bf0258a5bea9bc0a68b05372c646c3f383a1276216a2a577c8527cbb96f4f166`
  - `docs/specs/07-verification-and-evidence-cases.md`:
    `db696d34fa81da362f5d6ea4bd4327ec345e7477321e3cfecc4361940c17acdb`
  - `docs/implementation/07-deterministic-semantic-gate.md`:
    `d7e75c004c0f5bddb4a2511b5fc87d91b2e8cb4666d61997b311719c48bfb55d`
- `.backstitch/` is absent from the current worktree. Historical
  `.backstitch/review/` and `.backstitch/semantic-cache/` content was preserved
  on the archive branch above before removal.
- Before implementation, create a binary worktree checkpoint and untracked-file
  hash manifest using the protocol in the evidence-spike hardening plan. Do not
  use a restore-to-`HEAD` operation as rollback for this dirty worktree.

## Lifecycle Model

The terms below are normative for this plan:

| Concern | Owner | Lifecycle | Authority |
|---|---|---|---|
| source snapshot and packet set | one `analyze` invocation | recaptured for every current-source run | currentness input |
| analyzer/verifier cache objects | `semantic_cache.py` | immutable, content-addressed, reusable, disposable | performance only |
| lock, guard, and cleanup audit objects | `semantic_cache.py` | local coordination under [SEM-4] | integrity only |
| result JSONL | one invocation | regenerated from current packets and valid cached/live raw results | policy-neutral run output |
| analysis/eval reports | one publishable invocation or workflow run | regenerated and retained as local files or short-lived CI artifacts; pre-publication failures remain explicit logs/errors | operational/review evidence |
| reviewed durable snapshot | no owner in this plan | not implemented | none |

The existing mode names remain unchanged:

| Mode | Reads cache | Provider calls | Writes cache | Intended use |
|---|---:|---:|---:|---|
| `require` | yes | never | no | explicit offline/zero-call replay; any miss exits 2 |
| `read-write` | yes | misses only | successful misses | normal update and trusted CI refresh |
| `off` | no | every work item | no | deliberate uncached sampling or diagnosis |

`search_epoch` remains part of inference identity. Changing it is the supported
way to force a new sample while retaining old immutable objects for other
identities. A policy-only change must reuse the same raw results with zero
provider calls and regenerate the current report.

Cache absence and cache corruption are different:

- absence is an ordinary miss in `read-write`, and is rebuildable through
  bounded provider work;
- absence is a deliberate failure in `require`;
- corruption or provenance mismatch remains exit 2 in every cached mode and
  must not be silently converted into a provider miss.

That last rule is stricter than many compiler caches. It is necessary because a
hostile or damaged object should not be allowed to choose whether Backstitch
spends money or silently changes the analyzed identity.

## Proposed Spec Delta

Promotion strategy: Strategy A for active prose in already-mapped sections,
plus Strategy B for the [SEM-9]/[SEM-10] mapping addition and reciprocal
`tests/test_release_workflow.py` backlink. No new stable reference code is
required. The Spec-Promotion Slice changes the normative prose in [SEM-2],
[SEM-4], [SEM-7], [SEM-9], [SEM-10], [EVC-11], and [EVC-12] before workflow
or documentation implementation, and atomically lands that one mapping pair.
If implementation discovers that another production or test owner is needed,
stop and revise this plan to use an additional atomic mapping/backlink update.
Slice 3 did discover one such owner: the trusted PR identity helper at
`.github/scripts/resolve_semantic_pr.py`. The completion correction therefore
adds it to [SEM-9]'s implementation mapping together with its reciprocal
module-docstring backlink. Workflow YAML remains test-owned contract input
outside parsed code roots.

### [SEM-2] mental model

Replace `trusted immutable cache lookup` in the flow with `validated untrusted
immutable cache lookup`, and add:

```markdown
The raw-result cache is an optimization, not evidence authority. Every current
invocation derives a fresh source snapshot and packet set and validates every
reused object against the complete inference identity. Every invocation that
reaches publication regenerates policy-neutral result JSONL plus the
operational report. A failure before report publication remains an explicit
error and log event; no report is fabricated. Cached raw results may survive
across runs; a prior run report is never an input to a later run.
```

### [SEM-4] cache ownership and disposal

Add immediately after the cache path layout:

```markdown
The semantic cache is disposable acceleration state. Repository defaults place
it below `.backstitch/`, the repository ignores that directory, and no cache
object is reviewed or committed as ordinary source. Removing an idle cache
root is supported: the next `read-write` run rebuilds needed objects, while a
`require` run reports misses. Fine-grained pruning and concurrent whole-root
deletion are not current Backstitch commands.

CI may restore and save only immutable `packets/`, `results/`, and
`verify-results/` object trees through a trusted cache service. Lock, guard,
audit, staging, and report trees are never transferred as reusable cache
state. Restored bytes are untrusted and receive the same complete validation
as local bytes. Cache restoration failure changes only expected call count,
cost, or `require`-mode availability; it cannot change cache authority.
```

Retain the existing mode table and add:

```markdown
`read-write` is the normal update mode. An inference-relevant source, packet,
prompt, provider, request, contract, or epoch change creates a miss only for
affected work identities. A policy-only change is not a miss. `off` is an
uncached run, not a cache-refresh alias: it neither reads nor publishes cache
objects. Changing `search_epoch` is the explicit resampling mechanism when new
immutable cache objects should be retained.
```

No cache schema, key preimage, publication algorithm, single-flight state
machine, cleanup-lock contract, or corruption behavior changes.

### [SEM-7] fresh run products

Add after the canonical-result/operational-report distinction:

```markdown
Every invocation that reaches artifact publication constructs its result and
report from that invocation's current or historical input, valid cache hits,
live misses, and current policy. A failure before report publication remains
an explicit error and log event. A prior result file or report is never used as
a semantic cache and never satisfies completeness. Run artifacts may be
overwritten atomically by later invocations and may be retained as short-lived
CI artifacts; they are not ordinary repository source.
```

### [SEM-9] repository and CI lifecycle

Replace exactly the three paragraphs beginning `The rollout rungs remain
report-only baseline`, `The report-only rung commits the corpus`, and
`Required replay runs the same eval command` with:

```markdown
Backstitch's applied configuration keeps `require` as the explicit zero-call
profile. `.backstitch-refresh.toml` selects `read-write` for bounded update
runs. A clean checkout may therefore miss in the zero-call profile until a
validated external cache has been restored; this is an honest availability
failure, not a reason to commit cache objects.

Trusted refresh and pull-request report workflows may restore disposable
immutable object trees, run `read-write`, save successful immutable objects,
and upload every fresh report the invocation was able to publish. A
pre-report failure remains an explicit workflow error/log. Reports have bounded
retention. Neither workflow commits or pushes cache or report content.
Cache-service eviction is expected and affects only provider work, cost, or
zero-call availability.
```

Replace exactly the paragraph beginning `The semantic replay lane is
main/release only in v1` with this narrow v1 boundary:

```markdown
A pull-request semantic lane is report-only and manually dispatched from the
default-branch workflow definition. The workflow binds its tool checkout to
the run's exact trusted default-branch `github.sha`; the Backstitch source and
locked dependencies, configuration and prompt, provider settings, cache
namespace, and output roots all come from that checkout. It resolves an open
pull request through the GitHub API, validates the requested lowercase 40-hex
head SHA and readable `head.repo.full_name`, checks out that exact SHA from the
API-confirmed head repository into a separate target directory with
credentials, submodules, and LFS disabled, and asserts the resulting `HEAD`.
It repeats the API identity validation immediately before provider work.

The target repository is hostile input data. No target workflow, config,
dependency manifest, hook, plugin, executable, or generated command is run or
installed. The trusted Backstitch executable reads the target through
`--repo-root` while using an explicitly selected trusted config. Provider
credentials exist only on the credential check and provider-call steps.
Repository permissions are read-only. Cache and output paths are outside the
target. Provider-call, prompt-byte, packet-count, runtime, and cost ceilings
come from trusted configuration.

The artifact-upload step runs on every outcome and includes every report
Backstitch was able to publish. A failure before report publication remains a
workflow error and log record; the workflow does not fabricate a successful
report. The lane creates no commit, push, pull-request comment, status
mutation, disposition, threshold, or semantic merge authority. Promotion
beyond report-only requires the existing measured evaluation gate and a
separate authority review.
```

The main refresh remains `repository_dispatch` and trusted-main-only. Add a
second event type for a PR report request rather than `pull_request_target` or
a pull-request-authored workflow. The event payload contains only pull request
number and expected head SHA; both are validated before use.

### [EVC-11] hostile-repository boundary

Add these anti-gaming requirements:

```markdown
- semantic CI may treat repository bytes as hostile input only when the
  executable, locked dependencies, config, prompt, provider controls, mutable
  roots, and workflow definition are independently trusted;
- no secret-bearing semantic step executes or installs target-repository code,
  hooks, plugins, workflows, configuration, or commands;
- a report-only pull-request run binds to an API-confirmed exact head revision,
  rechecks that binding immediately before provider work, and has no repository
  write or semantic failure authority;
- restored semantic cache bytes remain untrusted and cannot bypass complete
  packet, identity, provenance, schema, and evidence validation.
```

### [SEM-10] verification changes

In [SEM-10], replace:

```markdown
- mutation and negative-control metrics are reproducible from committed cache
```

with:

```markdown
- mutation and negative-control metrics are reproducible from validated
  immutable cache objects produced by trusted evaluation and replayed under
  the exact identity; persistence or commitment of those objects grants no
  evaluation or policy authority
```

Then add executable gates for:

- all three cache modes through the public CLI;
- identical source and identity in `read-write`: zero calls and fresh report;
- one inference-relevant packet change: exactly one analyzer miss/call;
- a policy-only change: zero calls and changed projected report;
- changed search epoch: misses without deleting old objects;
- deleted cache: bounded rebuild in `read-write`, failure before adapter
  construction in `require`;
- corrupt restored cache: exit 2, never provider fallback;
- publishable runs regenerate reports, while pre-report failures stay explicit
  and never reuse or fabricate a report;
- reports and cache roots ignored by Git and absent from tracked source;
- CI restore/save includes only packet/result object trees;
- cache restore/save failure priority;
- manual PR dispatch validates PR number and exact current head SHA;
- trusted tool/config/output/cache roots are disjoint from target source;
- target config, hooks, dependencies, workflows, executables, and plugins are
  never consumed;
- provider credentials are absent from checkout, validation, artifact upload,
  and cache-service steps;
- artifact upload runs on success and failure, includes any report Backstitch
  produced, and relies on logs for pre-report failures;
- no PR lane commit, push, comment, status mutation, or merge authority.

### [EVC-12] verification additions

Append these exact numbered items after current item 33:

```markdown
34. Public-CLI cache lifecycle probes use real temporary cache roots and
    provider call counters to fire `off`, `read-write`, and `require`; exact
    hit, miss, packet-change, policy-only, search-epoch, deleted-cache,
    corrupt-cache, restore-failure-reset, fresh-publishable-report, and
    pre-report-failure branches all preserve [SEM-4] and [SEM-7].
35. Trusted semantic workflow probes bind the tool checkout to the run's exact
    default-branch SHA, bind the target checkout to the API-confirmed readable
    head repository and SHA, revalidate immediately before provider work, keep
    secrets and every executable/configurable input outside the target, move
    only immutable packet/result cache trees under distinct trusted workflow
    prefixes, and give the pull-request lane no repository write or semantic
    failure authority. Real hostile-target subprocess fixtures prove successful
    data-only analysis separately from fail-closed captured-root symlink
    rejection.
```

## Context and Key Files

| File | Current responsibility | Planned change |
|---|---|---|
| `backstitch/semantic_cache.py` | immutable cache validation, single-flight, publication, and explicit stale-lock cleanup | no behavioral redesign; retain as sole cache owner |
| `backstitch/semantic_analysis.py` | orchestrates cache/live analysis and regenerates result/report data | add or strengthen tests only unless a fresh-report defect is reproduced |
| `backstitch/cli.py` | constructs no adapter in `require`; validates mutable-root overlap | preserve behavior; add public-boundary probes |
| `backstitch/settings.py` and `backstitch/defaults.toml` | define `off`, `read-write`, `require`, paths, epochs, and budgets | no new key or mode |
| `pyproject.toml` | applied zero-call dogfood profile (`require`) | keep zero-call profile |
| `.backstitch-refresh.toml` | explicit bounded update profile (`read-write`) | remain the trusted refresh override |
| `.gitignore` | ignores ordinary tool caches but not `.backstitch/` | add root-scoped `/.backstitch/` |
| `.github/workflows/semantic-refresh.yml` | manually analyzes trusted main, uploads report plus cache as artifact | separate reports from reusable cache; restore/save immutable objects only |
| new `.github/workflows/semantic-pr-report.yml` | none | trusted manual report-only analysis of an exact PR head |
| new `.github/scripts/resolve_semantic_pr.py` | none | own exact API-confirmed PR identity resolution and fail-closed revalidation for the trusted workflow |
| `tests/test_semantic_cache.py` | real-filesystem cache behavior | lifecycle and corruption pins |
| `tests/acceptance/test_probe_semantic_replay.py` | public zero-call replay | add rebuild/update/fresh-report probes without root cache fixtures |
| `tests/test_release_workflow.py` | static workflow trust pins; becomes a mapped [SEM-9]/[SEM-10] contract owner | pin both workflows' trigger, SHA, secret, path, permission, and no-write rules; add reciprocal module backlink atomically with spec mappings |
| `README.md` | user-facing cache and CI workflow | explain update, replay, cold/resample, disposal, and PR report trigger |
| `docs/implementation/07-deterministic-semantic-gate.md` | implementation ownership and operator flow | replace committed-cache lifecycle with disposable cache/fresh report model |

## Invariants and Constraints

1. The inference identity, packet hash, analyzer/verifier object schemas,
   canonical bytes, and validation rules do not change.
2. `require` constructs no provider adapter and makes zero provider calls,
   including on a cache miss, corruption, or invalid configuration.
3. `read-write` never calls for a valid hit and never rewrites an existing
   immutable object.
4. Corruption and stale provenance remain fatal. They are not self-healed by a
   live call.
5. Policy, rendering, output paths, suppressions, and concurrency remain
   excluded from raw-result identity.
6. Each current-source run captures and recaptures source under [EVC-5.1].
   Cache reuse cannot grant currentness.
7. Run reports are outputs, never cache inputs.
8. Cache service state is optional and untrusted. A cache outage cannot change
   findings for a run that otherwise has the same raw results.
9. Only immutable packet/result directories cross CI cache-service boundaries.
   Locks, guards, audits, staging files, and reports do not.
10. No cache or report content is committed on `main`. The archive branch
    remains unchanged historical evidence.
11. The PR lane's target tree is never trusted, executed, installed, or used
    for configuration. Its bytes are analyzed through the existing snapshot
    and no-follow path boundary.
12. The PR lane remains manually dispatched and report-only. It gains no write
    token and no semantic failure authority.
13. No new dependency, config key, cache mode, cache schema, CLI cache-clean
    command, provider, model, policy promotion, or disposition is introduced.

## Hidden Couplings and Risk Register

- **Config origin versus repo root:** `--repo-root` selects analyzed bytes;
  `--config` selects policy and provider controls. PR analysis must prove these
  can come from different roots and that config extension stays in trusted
  `main`.
- **Workflow code versus target checkout:** a default-branch
  `repository_dispatch` protects workflow source only if every executed
  command and installed dependency also comes from the trusted checkout. The
  tool checkout must bind to the run's exact `github.sha`, not a moving
  `main`.
- **Mutable-path overlap:** the target directory, trusted tool directory,
  cache root, and report root must be distinct. Existing current-analysis
  overlap checks still protect only paths Backstitch knows; workflow tests must
  prove the layout itself.
- **PR head movement:** resolving a PR once and analyzing later creates a
  time-of-check/time-of-use gap. Revalidate open state, base branch, repository,
  readable API-confirmed `head.repo.full_name`, and exact head SHA immediately
  before the provider step. Checkout the confirmed head repository, including
  forks, and assert its checked-out `HEAD` equals that SHA.
- **Cache transfer:** transferring `locks/` could create false contention or
  stale-owner cleanup pressure. Transferring `guards/` and `audit/` has no
  acceleration value. Only the three immutable object trees move.
- **Poisoned saved entry:** a successfully restored corrupt object must keep
  failing with exit 2, so the newest immutable service entry can make the
  stable restore prefix unavailable. Operational recovery is an explicit
  trusted cache-prefix epoch bump or deletion of the service entry, never
  automatic local object deletion or provider fallback.
- **Cache save races:** GitHub cache entries are immutable. Each successful
  writer uses a unique trusted run key and a stable restore prefix. A
  key-already-exists race is harmless; unreadable files or action failure is
  operational, not semantic corruption.
- **Eviction and cost:** an evicted cache turns hits into bounded provider calls
  in `read-write`. It can therefore increase cost or cause a configured budget
  exit 2. The report must expose this; the workflow must not call it a semantic
  regression.
- **Artifact versus cache retention:** reports are review artifacts with a
  short explicit retention. Cache service eviction policy owns accelerator
  retention. Uploading the cache as a report artifact would conflate them.
- **Prompt injection in target bytes:** target text can influence model output,
  but the model has no tool or credential access, output is closed and
  validated, evidence is packet-local, and the lane is report-only. This does
  not make the result true; it contains the effect.
- **Trusted analyzer versus changed analyzer:** the PR lane analyzes the PR
  source tree with the exact trusted default-branch `github.sha` Backstitch
  build. It does not exercise a Backstitch implementation modified by the PR.
  Secret-free hermetic CI owns tests of PR code; combining those concerns
  would execute untrusted code in the credentialed boundary.
- **External action supply chain:** every action in a secret-bearing workflow,
  including cache restore/save, must be pinned to a reviewed full commit SHA.
  Mutable major-version tags are prohibited in the new lane.
- **Provider data exposure:** source packets are intentionally sent to the
  configured provider. This plan protects the credential and execution
  boundary; it does not make provider submission suitable for repositories
  whose policy forbids external code processing.

## Error Priority

Fatal, exit 2:

- invalid or moved PR identity;
- untrusted/ambiguous config origin;
- cache corruption or stale provenance;
- target/mutable-root overlap;
- provider, normalization, completeness, budget, snapshot-currentness, or
  required report-publication failure;
- missing provider credential in a refresh/report workflow;
- an API-confirmed head repository that cannot be read or fetched with the
  workflow's read-only token.

Operational acceleration failures:

- cache restore miss allows a `read-write` run to continue within trusted
  budgets; a restore action failure first removes and recreates the idle cache
  root so partially extracted bytes cannot enter analysis, then continues as a
  visible cold run;
- cache save failure occurs after semantic outputs exist. It must be surfaced
  clearly in the workflow result, but it must not alter the analysis report or
  rewrite semantic exit status.

The workflow may choose to fail its own operational job on a cache-save
infrastructure error, as the local-LLM workflow does, but that failure must be
labelled cache persistence failure rather than analysis failure.

A repeatedly corrupt restored service entry is remediated by a reviewed bump
of the workflow-owned cache-prefix epoch (or explicit service-entry deletion).
This abandons the accelerator entry only. It does not reinterpret corruption,
change semantic status, delete local objects during a run, or authorize a
provider retry.

## Rollback and One-Way-Door Posture

There is no cache-format migration and no destructive data change. The old
schema-2 material is already preserved on `semantic-evidence-archive`.

Rollback is ordered:

1. disable/remove the PR report workflow first; it is isolated and has no
   authority or durable repository writes;
2. remove cache restore/save steps from trusted refresh; `read-write` continues
   correctly with a local empty cache at higher provider cost;
3. restore report-only artifact upload behavior, but do not reintroduce cache
   artifacts or tracked `.backstitch` content without a new plan;
4. revert documentation/spec lifecycle wording together if the ownership model
   itself is rejected.

`require`, `read-write`, and `off` remain compatible through every slice.
Adding `/.backstitch/` to `.gitignore` is reversible and does not delete local
content. GitHub cache eviction is expected and irreversible per entry, but no
semantic authority depends on an entry. No one-way door is introduced.

## Tasks

The baseline gate and slices run serially. Each records its starting
checkpoint, changed files, commands, observed results, residual risks, and
review disposition. No slice may absorb adjacent cleanup.

### Baseline Reproduction Gate

Before changing specs or behavior:

1. prove through the public CLI that `require` constructs no adapter and makes
   zero calls on hit and miss;
2. prove `read-write` uses all valid hits, calls exactly for misses, and writes
   successful immutable objects;
3. prove `off` neither reads nor writes cache objects;
4. prove a policy-only change reprojects cached raw results with zero calls;
5. prove a changed inference-relevant packet or epoch misses only the affected
   identities;
6. prove deleting a temp cache causes rebuild in `read-write` and miss failure
   in `require`;
7. prove corrupt cache does not fall back to the provider;
8. prove every invocation that reaches publication regenerates a report with
   current operational counters while canonical result bytes stay stable for
   the same raw result, and prove a pre-report failure does not reuse or
   fabricate one;
9. prove an absolute explicit config outside `--repo-root` keeps its extend
   chain, cache path, provider identity, and policy anchored to the config
   layers while spec/code/test roots still resolve against the target;
10. prove tests use only temporary cache roots and no repository
   `.backstitch/` fixture;
11. capture the current workflow assertions and the expected-red assertions
    for ignored cache/report state and separated CI cache paths.
12. run the current self-corpus semantic analysis with the applied dogfood
    packet/prompt/runtime/provider budgets and record whether it reaches
    publication. If the existing trace-precision scale debt still exceeds
    `maximum_prompt_bytes`, record that as a residual and use a bounded
    fixture-backed lifecycle run for post-deploy signals; do not change
    evidence precision or budgets in this plan.

Expected result: core cache pins should already pass. Ownership and workflow
pins should fail for the documented current behavior. If a core pin fails,
stop and revise the affected later slice. Do not assume a lifecycle-only
change when an engine defect has been reproduced.

### Spec-Promotion Slice

Verify the Spec Baseline hashes, then apply the exact Proposed Spec Delta.
For [SEM-9] and [SEM-10], atomically add
`tests/test_release_workflow.py` to the implementation mappings and add its
reciprocal module-docstring backlink:
`Spec: docs/specs/06-semantic-gates.md [SEM-9], [SEM-10]`. Workflow YAML under
`.github/workflows/` is outside the configured parsed code roots, so it is
contract input read by that mapped test, not a separately mapped code owner;
the Python test enumerates its closed allowed and prohibited text. Record that
the repository's `tests/*` per-file diagnostic suppressions make the spec-side
mapping check the enforcing half of this atomic pair. Run the documentation
and self-corpus gates. Record post-promotion hashes.

If Slice 3 extracts trusted PR identity logic into a Python helper, add
`.github/scripts/resolve_semantic_pr.py` to [SEM-9]'s mapping and add its
reciprocal [SEM-9] module backlink atomically. This is production workflow
support code, unlike the YAML contract input, and must not remain only
indirectly test-owned.

Stop if the change would require a new cache schema, key field, mode, CLI
command, or stable reference code. Those are outside the reviewed delta.

### Slice 1: Repository ownership and operator documentation

1. Add root-scoped `/.backstitch/` to `.gitignore`.
2. Add a test proving `.backstitch/review` and
   `.backstitch/semantic-cache` are ignored while
   `.backstitch-refresh.toml` remains tracked/visible.
3. Keep `pyproject.toml` in `require` and `.backstitch-refresh.toml` in
   `read-write`; add comments only where needed to name their distinct roles.
4. Update `README.md` and the implementation guide with four explicit
   operator flows:
   - normal update: trusted `read-write`;
   - offline replay: `require`;
   - uncached diagnosis: `off`;
   - retained resample: change `search_epoch`, then run `read-write`.
5. State that an idle `.backstitch/` directory may be deleted as a whole and
   rebuilt. Preserve the existing explicit stale-lock cleanup command for
   per-key abandoned locks. Do not imply concurrent root deletion is safe.
6. Remove all instructions to review or commit ordinary cache objects. Explain
   the separate future durable-snapshot option without designing it.

Stop if documentation needs a new command to be truthful. Record the missing
operator need as a follow-up instead of inventing cache pruning in this slice.

### Slice 2: Trusted-main refresh cache lifecycle

1. Update `semantic-refresh.yml` to create separate cache and report roots.
2. Restore only `packets/`, `results/`, and `verify-results/` using
   `actions/cache/restore`, pinned to a reviewed full commit SHA. Use a
   trusted, versioned `semantic-refresh` prefix, an explicit cache-prefix
   epoch, and a unique run key; no key component comes from analyzed source. A
   restore service failure is visible but
   `continue-on-error`; before analysis, a following cache-preparation step
   removes and recreates the idle cache root so partial extraction cannot be
   mistaken for a cold cache. A successfully restored corrupt object remains
   exit 2 and is never automatically deleted or rebuilt.
3. Run the existing trusted-main analyze and eval commands with their current
   trusted config, provider ceilings, exact action pins, and `continue-on-error`
   aggregation.
4. Save only the three immutable object trees when cache preparation
   succeeded and both `steps.analyze.outcome` and `steps.eval.outcome` are
   exactly `success`. This condition covers either successful restore or
   explicit cold-root reset and excludes every analysis/eval/cache-corruption
   failure. Pin `actions/cache/save` to the same reviewed action commit. Keep a
   later cache-save infrastructure failure labelled separately from the
   already-determined analysis/eval outcomes.
5. Upload only `.backstitch/review/` as the bounded-retention review artifact.
   Do not upload cache, locks, guards, audit, or staging content.
6. Preserve contents-read permission, manual `repository_dispatch`,
   trusted-main checkout, credential scoping, no skip-on-missing-secret, and
   no commit/push behavior.
7. Add static workflow tests for cache path allowlist, full-SHA pins, key
   provenance, error priority, secret scope, report retention, and prohibited
   write operations.

Stop if cache action semantics require making the cache authoritative or
moving provider credentials to job scope.

### Slice 3: Trusted report-only pull-request lane

Create `.github/workflows/semantic-pr-report.yml` with this closed shape:

1. trigger only on default-branch `repository_dispatch` type
   `semantic-pr-report`; accept `client_payload.pull_request_number` and
   `client_payload.head_sha`;
2. permissions are exactly `contents: read` and `pull-requests: read`;
3. checkout the run's exact trusted default-branch `${{ github.sha }}` into a
   named tool directory with a pinned checkout action, disabled credential
   persistence, no submodules, and no LFS; assert the checked-out tool `HEAD`
   equals `${{ github.sha }}` rather than resolving moving `main`;
4. install locked dependencies from that directory before any target checkout;
5. query the GitHub API using quoted environment values, require a positive
   decimal PR number, lowercase 40-hex expected SHA, open state, `main` base,
   exact base repository, and a non-null readable `head.repo.full_name`;
6. checkout that API-confirmed head repository, including a fork, at the exact
   confirmed target SHA into a separate target directory with a pinned action,
   no persisted credentials, no submodules, and no LFS; assert target `HEAD`
   equals the confirmed SHA;
7. re-query and revalidate all identity fields immediately before the
   provider-call step;
8. create cache and report roots outside the target; restore/save only the
   immutable cache directories under the same trusted-key and failed-restore
   reset rules as Slice 2, but under a distinct versioned
   `semantic-pr-report` prefix so PR-derived entries cannot dominate
   trusted-main refresh restoration; save only when cache preparation and
   analysis outcomes are exactly successful;
9. run the trusted installed Backstitch executable from the tool directory
   against the target `--repo-root`, with an explicit absolute config path
   into the trusted tool checkout and explicit output paths outside target;
10. scope `OPENAI_API_KEY` only to the credential check and analyze step;
11. never use the target as a shell working directory or add it to executable,
    import, plugin, hook, or dependency lookup paths;
12. always run the bounded-retention artifact-upload step, including any
    report Backstitch published and relying on workflow logs for failures that
    occurred before report publication;
13. enforce operational completion without interpreting findings as merge
    authority; do not comment, create a check/status, commit, push, or execute
    any target file.

Add tests that parse the active workflow and fire every allowed/prohibited
boundary. Add two local subprocess acceptance fixtures:

1. a successful hostile-data fixture containing a hostile `pyproject.toml`,
   workflow, hook, executable, plugin declaration, and prompt-injection text;
   it proves Backstitch uses trusted config, reads target bytes as data, writes
   only outside target, and executes no marker payload;
2. a captured-root symlink fixture that must fail with exit 2, zero provider
   calls, no marker execution, and no target write.

Mock only the GitHub API and provider transport in workflow-unit tests; keep
filesystem layout, config loading, snapshot capture, cache validation, and CLI
subprocess real.

Stop if GitHub cannot bind a fork PR to the exact API-confirmed commit without
passing a secret-bearing token into target-controlled execution. Do not switch
to `pull_request_target`, automatic PR execution, or a write-capable token as a
workaround. Before implementing the full lane, spike one same-repository head
and one readable fork head. An API-confirmed private fork that the read-only
`GITHUB_TOKEN` cannot fetch is a fatal identity/checkout failure and remains
unsupported; token scope is not widened to make it reachable.

### Slice 4: Traceability, user docs, and final integration

1. Update the implementation guide's owner/boundary/verification/action
   sections for local, trusted-main, and trusted-PR flows.
2. Update README trigger examples and clearly state who can dispatch the PR
   report and what data is sent to the provider.
3. Update `docs/plans/README.md` and this plan's execution/deviation records.
4. Search for stale `committed cache`, cache-as-artifact, and pre-merge
   deferral language. Change only semantic lifecycle references governed by
   this plan.
5. Run the complete verification matrix and independent final review.

## Testing Plan

What must stay real:

- temp-directory cache object publication and validation;
- packet/result canonical bytes and content-addressed paths;
- subprocess invocation of the public CLI;
- config resolution from a trusted directory distinct from target repo root;
- immutable snapshot/no-follow traversal of hostile target fixtures;
- filesystem proof that no target marker executes and no target path changes;
- workflow YAML text and expression boundaries.

Permitted mocks:

- provider transport, to count calls and return closed deterministic rows;
- GitHub API responses in local workflow-support tests;
- cache-service action outcome in workflow logic tests.

Do not mock `semantic_cache.py`, config loading, repository capture, path
overlap validation, report publication, or the CLI adapter-construction
boundary. Live provider tests remain smoke tests and do not replace the
deterministic call-count suite.

Every touched enumeration fires: the three cache-mode values, search epoch,
cache hit/miss/corruption, report status/exit paths, workflow event types,
permission values, cache object directories, PR identity validation branches,
and artifact/cache failure priorities.

## Verification Commands and Gates

Per implementation slice:

```text
uv run pytest --ignore=tests/live -q
uv run pytest tests/acceptance -q
uv run ruff check backstitch tests bin
uv run ruff format --check backstitch bin .github/scripts tests
uv run mypy backstitch bin/release.py tests
uv run backstitch check --repo-root .
uv run backstitch check --repo-root . --show-suppressions
git diff --check
```

Additional lifecycle gates:

```text
git check-ignore -v .backstitch/review/example.json
git check-ignore -v .backstitch/semantic-cache/results/example.json
git ls-files .backstitch
uv run pytest tests/test_semantic_cache.py \
  tests/acceptance/test_probe_semantic_replay.py \
  tests/test_release_workflow.py -q
```

Required observed results:

- advertised self-corpus invocation exits 0 with zero errors and warnings;
- suppressions are explicit and auditable;
- `git ls-files .backstitch` prints nothing;
- no non-live test reads or writes the repository root `.backstitch/`;
- workflow tests prove full action SHAs and no secret/job-level credential;
- hostile-target acceptance leaves the target byte-for-byte unchanged and no
  execution marker exists;
- cache deletion changes call count/cost availability, not recomputed raw
  semantics for deterministic provider fixtures;
- cache corruption exits 2 without a provider call.

Before a slice is declared complete, it must be committed and verified in
`git log` unless the owner explicitly asks to review it uncommitted. This plan
does not authorize commits on the owner's behalf.

## Post-Deploy Signals

If the Baseline Reproduction Gate proves the current self-corpus completes
within applied budgets, record these signals for the first five trusted-main
refreshes and first five PR reports. If the known trace-precision scale debt
still exceeds the prompt budget, do not claim those lanes operationally
successful: record the debt as residual and collect the same lifecycle signals
from five bounded fixture-backed runs until a separate plan resolves scale.

Record:

- cache hits, misses, and provider calls;
- estimated cost and runtime;
- cache restore hit/miss/failure and save outcome;
- analysis exit separately from cache persistence outcome;
- exact analyzed commit SHA and report artifact name;
- absence of repository writes, PR comments, and status mutations.

Success means repeated unchanged runs trend to zero provider calls after a
restored cache; changed evidence produces bounded misses; reports remain fresh;
and cache eviction produces a visible cold run rather than incorrect reuse.
Any target execution marker, secret exposure, unvalidated head movement,
target-tree write, or authority mutation disables the PR workflow immediately.

## Independent Review Loop

Before implementation, an independent reviewer must check:

1. that this plan does not turn cache objects into evidence authority;
2. that the PR workflow boundary keeps all executable/configurable material on
   trusted `main`;
3. that error priority and cache transfer do not weaken [SEM-4];
4. that the spec delta is exact enough to implement without a new contract;
5. that no durable snapshot, pruning system, or semantic promotion slipped
   into scope.

Independent implementation review occurs after Slice 2 and after Slice 3.

## Fresh-Eyes Completion Review

The final reviewer starts from the README flows and an empty cache without
using the implementation record as a guide. Through public commands, they
exercise update, replay, uncached diagnosis, retained resampling, cache
deletion, cache corruption, and the hostile-target fixture. They inspect the
result/report/cache filesystem boundaries, compare provider-call counts to the
documented mode table, and verify the active workflows from their public
triggers and permissions. Any undocumented prerequisite or inferred trust
step reopens the owning slice.

## Out of Scope

- a committed or otherwise durable reviewed semantic snapshot
- clean-checkout zero-call availability without an external cache
- semantic findings as a required PR check or merge gate
- automatic execution on `pull_request` or `pull_request_target`
- PR comments, check runs, status writes, commits, pushes, or dispositions
- provider/model changes, evaluation thresholds, or policy promotion
- cache schema/key changes, mutable cache indexes, remote object databases, or
  cross-repository cache sharing
- a cache prune/clean CLI, concurrent whole-root deletion, retention tuning,
  or changes to `cleanup-lock`
- archiving, rewriting, or deleting the `semantic-evidence-archive` branch
- changing unrelated workflows, including the local-LLM cache lifecycle
- executing or installing target-repository code for any reason
- using the credentialed semantic lane to test a Backstitch binary or
  dependencies built from the target pull request

## Deviation Log

Append-only.

| Date | Slice | Spec ref | Deviation and reason | Proposed response | Verification | Disposition |
|---|---|---|---|---|---|---|
| 2026-07-27 | 3/4 | [SEM-9] | The reviewed workflow shape extracted API validation into a new Python helper, so the initial test-only mapping was no longer complete. | Revise the plan and atomically map `.github/scripts/resolve_semantic_pr.py` with its reciprocal backlink. | Documentation gate, helper tests, and final independent review. | Accepted; bounded traceability correction. |

## Execution Record

### Baseline Reproduction Gate (complete, 2026-07-27)

- Starting commit: `66c84d83f8934cdd869b97ab23e28670d95773c7` on
  `main`, with the pre-existing dirty worktree preserved.
- Binary checkpoint:
  `/tmp/backstitch-semantic-lifecycle.KH8baF/checkpoint.patch`
  (SHA-256
  `991bd0fa873e33c1001c637d66a90450ff129e08ae0451286ec894f903d13ecf`,
  4,250,253 bytes).
- Pre-checkpoint untracked manifest:
  `/tmp/backstitch-semantic-lifecycle.KH8baF/untracked.sha256`
  (SHA-256
  `32cf59dd62fcf62a8a8619f19b421c5008e1d738bad4ecadebd5c18f5c6f742d`,
  one path). `git add -A -N` then brought every untracked path into the
  binary diff surface without staging content.
- The three Spec Baseline hashes matched exactly before edits.
- Existing cache/replay/workflow suite:
  `uv run pytest tests/test_semantic_cache.py
  tests/acceptance/test_probe_semantic_replay.py
  tests/test_release_workflow.py -q` passed (77 tests).
- Added green contract pins for idle whole-cache-root deletion and for
  explicit trusted config outside the target root. No core cache defect was
  reproduced.
- Self-corpus semantic baseline:
  `env -u LLM_MODEL uv run backstitch analyze --repo-root . ...` exited 2
  with `ALIGNMENT_DEBT` before packet/prompt budget evaluation. The current
  obligation inventory contains pre-existing active partial/untraced sections,
  so the known 23 MB versus 1.5 MB prompt-scale measurement is not currently
  reachable. This plan does not repair that alignment or scale debt; the
  fixture-backed lifecycle signal fallback remains required.

### Spec-Promotion Slice (complete, 2026-07-27)

- Promoted the reviewed [SEM-2], [SEM-4], [SEM-7], [SEM-9], [SEM-10],
  [EVC-11], and [EVC-12] lifecycle text before workflow implementation.
- Added the reciprocal [SEM-9]/[SEM-10] backlink to
  `tests/test_release_workflow.py`.
- Post-promotion hashes:
  - `docs/specs/06-semantic-gates.md`:
    `e9e2fc0027f889c5fcc4ec105349ae276ba021feac585e40c769a69429d9daa6`
  - `docs/specs/07-verification-and-evidence-cases.md`:
    `af16e902c801594b3751902c705a0b3f4dea6f9535d066013c6776e7d14d2331`
- `uv run backstitch check --repo-root .` passed with 0 errors, 0 warnings,
  and 0 infos after promotion.

### Slice 1: Repository Ownership and Operator Documentation

Implementation and verification complete; uncommitted (2026-07-27).

- Added the root-scoped `/.backstitch/` ignore rule and a firing repository
  contract test. `git check-ignore` accepts representative report and
  semantic-cache paths; `git ls-files .backstitch` is empty.
- Updated the README and semantic implementation guide with the normal
  `read-write` update, explicit `require` replay, cache-off diagnosis,
  retained `search_epoch` resampling, idle whole-root disposal, fresh-report
  lifecycle, and separate future durable-snapshot boundary.
- `git diff --check` and `uv run backstitch check --repo-root .` passed after
  the documentation change.

### Slice 2: Trusted-Main Refresh Cache Lifecycle

Implementation and verification complete; uncommitted (2026-07-27).

- Bound the trusted checkout to `${{ github.sha }}` and asserted its exact
  `HEAD`; credential persistence, submodules, and LFS are disabled.
- Added pinned `actions/cache` v5.1.0 restore/save steps at
  `caa296126883cff596d87d8935842f9db880ef25`. Only `packets/`, `results/`,
  and `verify-results/` cross the cache-service boundary under the
  `semantic-refresh-v1-cache-v1-` prefix.
- A restore-service failure is visible and resets the idle cache root before
  analysis. Successfully restored corruption remains an analysis failure and
  is not deleted or rebuilt automatically.
- Cache save requires successful cache preparation, analyze, and eval
  outcomes. Its infrastructure failure is aggregated and labelled separately.
  Artifact upload contains only the fresh report root with 14-day retention.
- Added closed workflow-contract assertions for action pins, cache paths,
  secret-bearing steps, restore-failure reset, save predicate, retention,
  ordering, and prohibited repository writes.
- Independent review initially found one P1: an explicit `!cancelled()` guard
  had disabled GitHub's implicit `success()` gate and could have let a
  secret-bearing eval step run after rejected checkout identity. It also found
  a P2 in the open-ended static assertions. Both were corrected; focused
  re-review returned PASS.
- Focused workflow tests passed (13 tests). The broader cache, settings,
  semantic-analysis, public replay, and workflow suite also passed.

### Slice 3 Pre-Implementation Spike (complete, 2026-07-27)

- Initial read-only inspection found no open pull request and no remote
  `refs/pull/*/head` on `origin`. The owner then authorized temporary PRs.
- Same-repository draft PR #1 bound `VanL/backstitch` to
  `3508ebd2fca353e1b318ea6402b843af4046dae8`. The spike validated open state,
  `main` base, exact base/head repository, lowercase 40-hex head SHA, fetched
  that exact SHA, asserted checkout `HEAD`, and repeated the API validation.
- Readable-fork draft PR #2 bound `modelmonster/backstitch` to
  `5b557a40b325c7aea0a32d7b573c50018c99c503`. The same closed validation
  passed, including an anonymous exact-SHA fetch that required no widened
  token.
- Both PRs were closed and both marker branches were deleted. Deleting the
  temporary `modelmonster/backstitch` fork, which now retains only its ordinary
  fork state, returned HTTP 403 because the authenticated `gh` token lacks
  `delete_repo`; that external cleanup remains explicit and does not widen
  token scope.

### Slice 3: Trusted Report-Only Pull-Request Lane

Implementation and verification complete; uncommitted (2026-07-27).

- Added a default-branch `repository_dispatch` workflow with exactly
  contents-read and pull-requests-read permissions. It binds trusted
  Backstitch to `${{ github.sha }}`, installs only its locked dependencies,
  and checks out the API-confirmed PR repository and SHA separately with
  persisted credentials, submodules, and LFS disabled.
- Added a trusted resolver that validates canonical PR number and lowercase
  full head SHA, open state, `main` base, exact base repository, readable
  closed-shape head repository, and exact head SHA. It repeats repository/SHA
  validation immediately before the provider step and contains API, timeout,
  incomplete-response, and output-I/O failures as exit 2 without tracebacks.
- The PR cache uses the distinct
  `semantic-pr-report-v1-cache-v1-` namespace. Only immutable packet/result
  trees are restored or saved; restore-service failure resets the idle root,
  restored corruption remains fatal, and save requires successful preparation
  plus analysis. Fresh reports use runner-temporary storage and are always
  offered for 14-day artifact upload.
- Provider credentials occur only on the credential check and trusted analyze
  steps. The target is never an install source, config source, working
  directory, executable path, import path, plugin path, hook source, cache
  root, or output root. The lane creates no repository or merge-authority
  write.
- Added closed workflow tests for trigger, permissions, action pins, step
  order, secret scope, tool/target identities, payload use, root separation,
  cache allowlist/reset/save rules, report retention, error labels, and
  prohibited writes. Resolver tests fire malformed identity branches plus the
  environment, mocked API, `GITHUB_OUTPUT`, revalidation, token non-disclosure,
  output failure, and timeout boundaries.
- Added two public-CLI hostile-filesystem probes. The first captures a
  non-skipped packet from a target containing hostile build/plugin/hook/
  workflow/executable/config/prompt text, sends that packet through one
  controlled provider call, then replays it through the public current-source
  CLI with one cache hit and zero calls while proving no marker execution or
  target mutation. The second rejects a symlinked captured root before
  provider work with exit 2 and no target mutation.
- Independent review found no P1. Its two P2 findings removed unvalidated
  payload data from workflow metadata and strengthened the hostile fixture
  through the provider seam. Its P3 added resolver main-boundary error
  containment and tests. Focused re-review returned PASS with 45 targeted
  tests plus Ruff, formatting, and mypy green.
- Final fresh-eyes review found three bounded P2 gaps: incomplete HTTP
  responses could escape the resolver, [EVC-12] did not yet exercise the full
  lifecycle through subprocess CLI calls, and the new resolver plus lifecycle
  plan links were not fully traced. The resolver now catches
  `HTTPException`, the public probe covers construction/call counts across all
  modes, one-packet mutation, epoch change, deletion/rebuild, corruption, and
  fresh report replacement, and the helper has an atomic [SEM-9] mapping and
  backlink.

### Final Integration Verification (complete in worktree; uncommitted, 2026-07-27)

- `uv run pytest --ignore=tests/live -q`: the first run had one timing-only
  failure when default self-check took 0.737 seconds against its local
  0.700-second performance budget. The exact failing test passed immediately
  on isolated rerun, and a second complete non-live run passed.
- `uv run pytest tests/acceptance -q`: passed, including the public lifecycle
  replay and hostile-target probes (41 tests after the completion correction).
- `uv run ruff check backstitch tests bin .github/scripts`: passed.
- `uv run ruff format --check backstitch bin .github/scripts tests`: passed
  after formatting the touched lifecycle test files.
- Scoped mypy over the new resolver and lifecycle test owners passed. The
  repository-wide command still reports two errors in pre-existing checkpoint
  content outside this plan:
  `tests/test_analysis_packets.py:668` passes `"standalone"` to a narrower
  `SourceObligationSkip` literal, and `tests/live/test_live_llm.py:944` passes
  `str` where `prompt_instruction_bytes` requires a section/invariant literal.
  Both paths and edits are present in the pre-implementation checkpoint; this
  plan does not change them.
- `uv run backstitch check --repo-root .` and the
  `--show-suppressions` form both passed with 0 errors, 0 warnings, and
  0 infos. The latter reported the existing auditable suppression inventory.
- Both representative `.backstitch/` report/cache paths are ignored and
  `git ls-files .backstitch` is empty. `.backstitch-refresh.toml` remains
  visible and tracked.
- Scoped `git diff --check` passed. Repository-wide `git diff --check` still
  reports the two intentional Markdown hard-break lines in the pre-existing
  qualification-candidate independent review; those exact lines are present
  in the pre-implementation checkpoint.
- A fresh-eyes read also found a pre-existing [SEM-9] contradiction:
  `.backstitch-refresh.toml` contains accepted `[verify]` and `[verify.eval]`
  overrides, while [SEM-9] says the file permits only the one `[analyze]`
  override. The mismatch predates this plan and is not changed here. It
  remains an explicit residual that prevents an unqualified claim that the
  current refresh file complies with every [SEM-9] sentence.
- The completion-correction suite passed 46 focused tests. Ruff, formatting,
  scoped mypy, both self-corpus checks, and the complete non-live suite passed
  after the corrections. Final focused independent re-review returned
  **PASS** with no remaining P1/P2 findings.
- Later Class-2 gate hygiene on 2026-07-27 corrected the two checkpoint-era
  test annotations named above: the skip fixture now uses the parser's
  canonical `traceability` form, and the live prompt-budget path validates and
  narrows the closed packet-kind vocabulary. Repository-wide mypy now passes
  all 122 checked source files.
- The worktree remains intentionally uncommitted. Per the repository landing
  gate, this record does not claim ready-to-land completion until the owner
  authorizes and verifies a commit.

## Review Record

### Round 1: BLOCKED (2026-07-27)

The independent reviewer returned three P1, four P2, and one P3 findings. All
were accepted and corrected:

1. [SEM-10]'s remaining `committed cache` bullet now has an exact replacement
   using trusted, validated immutable objects with no authority.
2. A failed restore action now requires idle-root removal/recreation before a
   cold run; successfully restored corruption remains fatal.
3. Tool checkout binds to the run's exact `github.sha`; target checkout uses
   the API-confirmed `head.repo.full_name` and SHA, asserts `HEAD`, supports
   forks, and revalidates immediately before provider work.
4. Report wording now distinguishes publishable runs from pre-report failures.
5. [SEM-9]/[SEM-10] mapping and the reciprocal
   `tests/test_release_workflow.py` backlink land atomically; workflow YAML is
   explicitly test-owned contract input outside parsed code roots.
6. Cache save eligibility is the exact successful cache-preparation plus
   successful analyze/eval outcome predicate.
7. The successful hostile-data and failing captured-symlink probes are
   separate fixtures.
8. The runbook path is corrected and the pre-implementation work is named the
   Baseline Reproduction Gate rather than reserved Slice 0.

### Round 2: PASS (2026-07-27)

The same reviewer verified the eight round-1 corrections against the current
plan and found no remaining blocker. Verdict: **PASS**.

### Claude Cross-Model Round 1: PASS with one required P2 correction (2026-07-27)

Direct invocation: `claude -p`, model `claude-fable-5`, read-only repository
tools, session `fd84f352-9a85-409c-a75d-a4e2ceaec00c`, duration 559.9 seconds.
Claude found no P1 and returned PASS, but required one P2 correction before
spec promotion. All findings were accepted:

1. The previously claimed [EVC-12] change had no exact numbered delta. Exact
   items 34 and 35 now specify the public cache lifecycle and trusted-workflow
   real-boundary probes.
2. [SEM-9] replacement anchors now quote the opening text of all four replaced
   paragraphs.
3. The reciprocal test backlink now uses the repository's `Spec:` module
   docstring grammar, and the `tests/*` suppression asymmetry is recorded.
4. A corrupt saved service entry now has an explicit trusted prefix-epoch bump
   or service-entry deletion remediation without provider fallback.
5. Trusted-main refresh and PR-report caches now use distinct prefixes.
6. Unreadable private-fork heads fail closed without token widening, and an
   early same-repository/readable-fork spike is required.
7. The Baseline Reproduction Gate now measures the known self-corpus prompt
   budget risk and scopes post-deploy signals to fixture-backed runs if that
   pre-existing scale debt remains.

### Claude Cross-Model Round 2: PASS (2026-07-27)

Claude resumed the same read-only `claude-fable-5` session and verified only
the seven corrections above. Duration: 44.6 seconds. Verdict: **PASS**; no
P1/P2 findings remain. Claude confirmed that the plan is ready for the
Baseline Reproduction Gate and Spec-Promotion Slice.
