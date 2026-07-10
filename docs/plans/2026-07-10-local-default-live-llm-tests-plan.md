# Local-Default Live LLM Pytest Policy

Status: implementation, verification, and independent-review remediation
complete. Changes are uncommitted.
Plan type: implementation with spec revision.
Risk level: boundary-crossing. This changes the default local test network and
credential behavior and the current CI execution policy.

## Goal

Run the live LLM contract test in an ordinary local `pytest` invocation by
repository default, while current CI explicitly disables that default. Keep CI
enablement reversible: a dedicated job can opt in later without a code change.

## Requested Outcomes

- `pyproject.toml` owns the local default through a typed pytest ini key.
- `uv run pytest -q` locally collects and runs `live_llm` tests without
  requiring `BACKSTITCH_LIVE_LLM=1`.
- Current hermetic CI explicitly overrides the ini key to false and proves the
  live module skips when directly collected.
- The cloud CI job requires a repository variable plus a main-branch
  push or manual-main event, not only a secret-bearing pull-request-capable job.
- `BACKSTITCH_LIVE_LLM=1` remains an explicit enablement path for dedicated or
  manual lanes and downstream configurations whose ini default is false.

## Source And Baseline

Governing source:

- `docs/specs/02-backstitch-core.md` [SC-7], [SC-10]
- `docs/implementation/04-backstitch-style-traceability.md`
- `README.md`
- `pyproject.toml`
- `tests/conftest.py`
- `tests/live/test_live_llm.py`
- `.github/workflows/ci.yml`

Baseline commit: `fc7427180fcbc99eb19ae5771a2231546ddd026b`.
The governing files are already modified in the uncommitted diagnostics and
invariant worktree. At plan start the sorted changed-path manifest hashes to
`5dc1d3779915bd689287c2db90f8fa987c9f41d3eaac955339d6a514e91b0bae`.
This change revises the live-test contract itself; compliance after promotion
is against the current worktree plus the promoted [SC-7]/[SC-10] text.

Promotion strategy: A, in-file text-first. Promote [SC-7] and [SC-10] before
the pytest hook cites or implements the new policy. No glob rung is involved.
Promotion baseline identifier: uncommitted
`docs/specs/02-backstitch-core.md` SHA-256
`01ba063d44b7d58720aa8b199bb1c438232016202d9b9685263789e66cce79da`,
applied over the baseline worktree above.

## Deviation Log

| Contract | Planned | Revised | Reason |
|----------|---------|---------|--------|
| Future CI enablement | Repository variable only | Repository variable plus main-branch push/manual-main event guard and read-only permissions | Independent review reproduced a same-repository PR secret/cost boundary |

## Invariants And Boundaries

- Deterministic Backstitch commands remain unable to import or call `llm`.
- Hermetic unit and acceptance tests still use fakes; only `live_llm` tests may
  call a provider.
- Current CI disablement is workflow policy, not a permanent product invariant.
  Do not gate on the generic `CI` environment variable in Python.
- CI provider secrets must never reach pull-request code or non-main refs.
  Workflow permissions stay read-only.
- A live test that is enabled but lacks a usable model or credential fails. It
  must not silently skip.
- `-m "not live_llm"` remains a valid explicit deselection.
- The collection hook owns only marker enablement. It must not select models,
  credentials, endpoints, packet counts, or strictness.
- No new dependency. Use pytest's native `addini` and collection hooks.

Hidden coupling: `pyproject.toml` is loaded before test collection, while the
existing module-level `skipif` is evaluated during collection. The gate must
move to `tests/conftest.py`; leaving both gates would make the ini key a no-op.

Anti-mocking: verify the enabled local default with the real live test and the
production adapter. The CI-disabled proof may stop at collection/skip because
its contract is specifically that no provider call occurs.

Rollback: set `run_live_llm = false`, restore the old explicit opt-in wording,
and remove the CI `-o` override. No report, packet, result, or runtime schema is
changed. There is no one-way door.

## Proposed Spec Delta

Revise [SC-7] so the live gate is an explicit pytest policy rather than only an
environment variable:

- repository pytest configuration may enable live tests by default for local
  runs;
- automation may explicitly disable the policy without editing code;
- `BACKSTITCH_LIVE_LLM=1` remains an independent explicit enablement path;
- an enabled live gate preserves the existing fail-loud credential, transport,
  and structured-result contracts;
- current CI disablement is not a permanent ban on future CI live lanes.
- future CI enablement must exclude pull-request and non-main code from the
  provider-secret boundary.

Extend [SC-10] verification to require both observable paths:

- ordinary local pytest configuration enables and actually runs the live test;
- the current CI command explicitly disables it, direct collection reports a
  skip, and the future cloud lane requires an explicit repository-variable
  opt-in plus a main-branch event.

## Slices

1. Promote the [SC-7]/[SC-10] delta and backlink this plan.
2. Add typed `run_live_llm = true` pytest config. Register it in
   `tests/conftest.py`, move marker skipping there, and remove the module-level
   environment-only skip.
3. Add `-o run_live_llm=false` to current CI's direct skip proof and assert one
   skip. Keep the cloud job present, but require
   `BACKSTITCH_CI_LIVE_LLM == "1"`, a main-branch push/manual-main event, and
   read-only workflow permissions.
4. Update workflow assertions, README, repository map, implementation rationale,
   and the prior live-plan status language.
5. Verify local enabled, explicit disabled, current CI shape, static checks,
   acceptance, full suite, packet modes, and strict self-corpus.
6. Run an independent adversarial review. Reproduce each finding before acting.

Stop if pytest cannot register a typed project ini key without a new
dependency, if disabling still allows provider activity, or if the ordinary
local run does not execute the live body.

## Verification

```bash
env -u BACKSTITCH_LIVE_LLM uv run pytest tests/live/test_live_llm.py -q
env -u BACKSTITCH_LIVE_LLM uv run pytest tests/live/test_live_llm.py -q -o run_live_llm=false
BACKSTITCH_LIVE_LLM=1 uv run pytest tests/live/test_live_llm.py -q -o run_live_llm=false
uv run pytest tests/test_pytest_policy.py -q
uv run pytest tests/test_release_workflow.py -q
uv run pytest tests/acceptance -q
uv run pytest -q
uv run ruff check backstitch tests bin/release.py
uv run ruff format --check backstitch tests bin/release.py
uv run mypy backstitch bin/release.py tests
uv run backstitch check --repo-root . --show-suppressions
```

Success requires the first command to execute the live body and pass without
the legacy opt-in variable. The second must collect exactly one skipped test
and make no provider call. The third proves the environment override executes
the real live body even when ini policy is false. The full local suite must
have no live skip.

## Review Path

Use Grok as the independent reviewer because it is the available different
model family already used for this work. Ask it to look for errors, bad ideas,
latent ambiguities, and unnecessary or performative overengineering, and to
answer: "If asked, could you implement this plan as written confidently and
correctly?"

Pre-implementation review evidence: Grok CLI 0.2.93 was installed and
authenticated, and two tool-less plan-mode attempts completed after emitting
plugin warnings but wrote zero response bytes. This is an unavailable review,
not a pass. Retry against the completed diff before final status.

Completed-diff review: Claude was installed but unauthenticated. A final Grok
consult returned only setup prose and no verdict. Fresh read-only Codex review
found two P1 issues and four P2 issues:

| Finding | Disposition |
|---------|-------------|
| Repository-variable-only cloud job exposed secrets/cost to same-repository PR code. | Accepted. Restrict to main push/manual-main, add read-only permissions, and pin the guard in workflow tests and [SC-10]. |
| Policy combinations and environment override lacked firing proof. | Accepted. Add a four-state truth-table test, correct the unset-environment live command, and run the real provider with ini false plus environment override. |
| CI comment claimed exactly one skip without checking it. | Accepted. Capture pytest output and grep for `SKIPPED [1]`; pin the exact command in workflow tests. |
| "Current CI disables" depended on external repository-variable state. | Accepted. Docs now distinguish the always-hermetic matrix from the separately gated cloud job. |
| Paid/flaky local default harms offline feedback. | User-owned tradeoff, retained. README names cost/flake behavior and gives explicit hermetic commands. |
| Status/backlinks remained implementing. | Accepted and reconciled after remediation and all gates passed. |

Correction review: the same read-only Codex session re-read the current files,
ran the policy/workflow/disabled-live focused tests, reported no remaining P1
or P2 findings, and answered the confidence question `Yes` because the six
remediations are explicit, tested, and aligned.

## Final Evidence

| Gate | Result |
|------|--------|
| Local default, `BACKSTITCH_LIVE_LLM` unset | Real provider test executed and passed |
| Environment override with `run_live_llm=false` | Real provider test executed and passed |
| Explicit disabled policy | Exactly one `SKIPPED [1]`; no provider call |
| Policy truth table + workflow contracts | 13 tests passed |
| Full local suite, environment unset | Passed with no skip |
| Acceptance probes | 18 passed |
| Ruff check / format / mypy | Passed; 77 formatted files, 68 typed source files |
| Strict self-corpus | Exit 0; 58 sections, 149 mappings, 271 code refs, 3 invariants, zero visible findings, 155 auditable suppressions, no suppressed invariant finding |
| Packet modes | 45 section, 3 invariant, 48 mixed; all exit 0 |

The work remains uncommitted, so the repository ready-to-land commit gate is
not claimed.
