# Bonsai 2 versus Qwen local and CI comparison

Class: 3. Experimental verification spans a local runtime and hosted CI; no
product contract or default model changes. Owner: repository owner; execution
and evidence collection: the task agent. Baseline: a207c67cf9a3847c0513c59a4a7c6913c2609740.

## Goal and source documents

Run the incumbent Qwen2.5-Coder-14B Q4_K_M and Bonsai 2 27B locally first,
then on the four-core Linux CI runner. Compare integration and the frozen v3
clean/mutated semantic smoke corpus. This is exploratory evidence, not formal
qualification. Sources: docs/program-theory.md; docs/agent-context/README.md,
decision-hierarchy.md, principles.md, engineering-principles.md, lessons.md;
docs/lessons.md; writing-plans, hardening-plans and adversarial-acceptance-probes
runbooks; docs/specs/02-backstitch-core.md [SC-7], [SC-10];
docs/specs/06-semantic-gates.md [SEM-8], [SEM-9];
docs/plans/2026-09-15-ci-workflow-and-qwen-qualification-plan.md;
tests/semantic_eval/v3/README.md. No spec delta.

## Existing structure and boundaries

The local live test owns the schema/counting proxy and production CLI adapter
exercise. The previous disposable Qwen assessment at 16a36d3 supplies a reusable
production-evaluator smoke probe. The existing local-llm workflow provisions
Ollama on a bounded CPU host. Reuse these mechanisms; do not create a second
semantic evaluator or edit frozen gold. Likely changes: a model-neutral live
comparison probe under tests/live, the branch's local-llm workflow, this plan,
its index row, and the model catalog for durable results. Experimental runtime,
weights and raw local results live under ignored .cache/bonsai-comparison.

Comprehension checks and expected answers: (1) Does live-test success qualify
semantic accuracy? No: its aligned packets establish integration only.
(2) Can the two-case v3 corpus authorize policy? No: it is expressly report-only;
replays prove cache fidelity, not uncached stability. Execution answers: both
boundaries are understood and apply to every result in this comparison.

## Invariants, rollout and rollback

Keep the incumbent default on main, existing semantic validators, packet and
response contracts, gold labels, and all thresholds unchanged. Never repair raw
model output. Label native-Metal versus Docker-CPU timing separately; compare
both models on the same CPU host before claiming speed advantage. A reasoning
budget change is a separate run, not a silent retry. Pin model bytes/runtime
revision, effective request controls and result artifacts. Model failures and
timeouts are observations; setup failures are not quality scores. New dependencies
stay isolated experimental executables, outside the project manifest.

Run local before CI. The disposable branch may adapt local-llm for this experiment;
no main merge, release, default-model promotion, secret exposure, or corpus
revision. Branch commits/push are execution prerequisites for the requested CI
run. Rollback is leaving main unchanged and stopping only task-owned servers.
Do not stop the existing Ollama container. Retain evidence and weights for review.
Bound each run; preserve failures, timings and logs, including on CI cancellation.

## Tasks and verification

1. Pin and provision the Prism runtime and weights; inspect its documented server
   controls. Inspect incumbent runtime controls and reuse available model bytes.
2. Independently review the plan and reusable test design before implementation.
3. Run incumbent and candidate through production integration, then the frozen
   semantic smoke pair with analyzer/verifier and zero-call replay. Use one trial for both models at temperature 0, seed 42, context 4096 and
   output 1024; evaluator deadline 1800 seconds. Any two-trial or native-Metal
   follow-up is a separate diagnostic. Primary CPU runs use four threads and
   the same 16 GiB container cap. Retain raw reports,
   server logs, effective controls, elapsed time and available memory telemetry.
4. Review any test/workflow changes and run focused checks. After local observations,
   commit/push only the experimental files and run CPU CI for both candidates with
   bounded time, read-only token and always-uploaded artifacts. Observe to terminal
   status and download results. Reuse existing pinned Actions and uv environment.
5. Record the actual local and hosted outcomes in this plan and the model catalog;
   run documentation checks, relevant tests and the hermetic self-corpus gate
   (zero errors/warnings). Independently review conclusions and final diff.

Real inference, production packet/eval logic, response validation and replay must
not be mocked. Frozen gold is the independent expectation. No new product tests
unless product behavior changes, which requires replanning. Stop and replan if
comparison requires relaxing validation or editing gold; report the actual
compatibility blocker instead. The larger synthetic corpus remains out of scope
because existing review identified incompatible labels and provenance limits.

## Review and execution log

- Plan created before test/workflow edits. Hardware: Apple M4 Max, 128 GiB;
  incumbent Ollama container already serves the expected Qwen artifact. Main CI
  at baseline shows failure while local-llm passes; unrelated CI diagnosis is
  outside this experiment and must not be represented as a new regression.
- Independent review requested three clarifications, all accepted: identical
  one-trial primary budgets, actual model-specific weight identities in the
  descriptor, and stdout/stderr/exit/elapsed evidence even when no report is
  produced. Missing reports are execution failures, never zero quality scores.
  Effective configuration and model/runtime identities accompany every result.

## Deviations and conclusion

None yet. Completion requires concrete local and hosted outcomes, or an explicit
reproduced external blocker. Update the index at closure and cite commit/run IDs.

- Owner clarified all local inference must use Docker with the CI profile: four
  vCPUs, 16 GiB RAM. Both dedicated containers disable swap and GPU. The preliminary
  incumbent attempt used a different Ollama image and allowed swap, so was stopped
  and excluded. Bonsai primary mode is explicitly non-thinking; the 1024-token
  output budget is unchanged. No native-Metal results enter this comparison.

- Probe review passed with accepted reporting-headroom correction: subprocess
  timeout 1860 seconds, inference budget still 1800, CI test step 33 minutes.
  Model requests are observed without altering schema, stream, or returned text.
- Disposable CI workflow review passed after canonicalizing the Ollama alias to
  comparison-qwen:latest. Both matrix members assert Docker limits and pinned
  model identity. Runtime archives: Prism prism-b10685-7dffb15, arm64 local /
  x64 hosted; Bonsai weights revision 6ed5e12bf84b7a63069882c91dd9e9218647d17b,
  PQ2_0 SHA256 3907dc1658db1f78a9826bf8d5bcb8dc65db0d466388937af57f2294fae62ec1.
  The experimental workflow and test are not intended for main-branch promotion.
- Initial checks: live-helper tests passed; Ruff, focused mypy, doc-path and
  DOM-15 gates passed; self-corpus check found zero errors, warnings and infos.

- Local Docker primary results (ARM64, four-vCPU quota, 16 GiB, swap disabled):
  Bonsai non-thinking PQ2_0 completed in 1122.514 s; Qwen14B Q4_K_M completed
  in 170.083 s. Each preserved the clean control, detected the mutation, made
  two analyzer calls plus one verifier call, then replayed with zero calls and
  three cache hits. Neither is qualified: one trial leaves uncached flip rate
  unmeasured, and this two-case corpus is non-authoritative. Independent artifact
  review confirmed Bonsai's semantic results, request controls and replay hashes.
  Local Bonsai peak cgroup memory: 9133428736 bytes (8.506 GiB), no OOM events.
  The comparison is served-deployment latency, not an isolated quantizer test.
  Raw local evidence is retained under .cache/bonsai-comparison/results.

- First hosted run: https://github.com/VanL/backstitch/actions/runs/35371764892
  at execution commit 4dfe28bd4336885b65e89c1ea1eb45c23ce64786. Qwen passed
  both controls, verifier and zero-call replay in 361.104 s, peak 13743202304
  bytes (12.799 GiB), no OOM. Bonsai exited 139 while loading, before inference;
  Docker reports OOMKilled=false. This is a runtime setup failure, not a quality
  miss. Preserved artifacts are under results/ci-qwen and results/ci-bonsai-first.
- Recovery independently reviewed: upstream PrismML-Eng/llama.cpp issue 180
  reports this release/model's CPU repacking segfault and --no-repack workaround.
  The match is a plausible diagnosis, not a locally captured stack trace. Local
  four-CPU/16-GiB Docker with --no-repack loaded and answered a short arithmetic
  prompt correctly before dispatching a Bonsai-only hosted retry. That diagnostic
  is not a repeat semantic score. The retry changes only runtime repacking,
  preserves all model bytes/budgets/gold, and makes readiness checks bounded and
  fail promptly on container exit. It is a separately labeled configuration.
