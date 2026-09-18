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
   output 1024; verifier runtime limit 1800 seconds and overall CLI timeout
   1860 seconds. Any two-trial or native-Metal
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

Local results favor Qwen latency and Bonsai memory usage. Hosted Qwen passed;
Bonsai required a separately recorded runtime workaround. The hosted recovery timed out on its first request. Further CPU-runtime
diagnosis was requested by the owner; this plan remains active.

- Owner clarified all local inference must use Docker with the CI profile: four
  vCPUs, 16 GiB RAM. Both dedicated containers disable swap and GPU. The preliminary
  incumbent attempt used a different Ollama image and allowed swap, so was stopped
  and excluded. Bonsai primary mode is explicitly non-thinking; the 1024-token
  output budget is unchanged. No native-Metal results enter this comparison.

- Probe review passed with accepted reporting-headroom correction: subprocess
  timeout 1860 seconds, verifier runtime budget still 1800, CI test step
  33 minutes.
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

- Recovery execution commit: 10c14ee1cff81b36f76269ab48126c60c1fca237;
  run https://github.com/VanL/backstitch/actions/runs/35372921176. Bonsai passed
  hosted readiness with --no-repack and reached production evaluation. The local
  and hosted CPUs differ despite matching quotas; do not compare their absolute
  latencies as if the CPU hardware were identical.
- Retained report SHA256 identities:
  local-bonsai.json: 264f8ab689199416272cea363cbf7fa34bc0edae9d32ba0c36432000437c859f;
  local-qwen-final.json: ad860c00a19e810fcae3acc1a4f07896b7bc1da208aedccca51ceb728caaabc4;
  ci-qwen/ci-qwen.json: ebb83661c30b5aed2f392e216d508a05dc127a0f909cfbbec94f2ef4317912c2.
  Local Qwen peak was 13609443328 bytes (12.675 GiB), no OOM events.
- Review of the recovery accepted the bounded retry and required explicit flag
  differences, preservation of the first failure, and CPU-model inspection before
  interpreting a hosted latency ratio. Repacking diagnosis remains qualified.

- Documentation review identified stale July JSON-object transport claims;
  these are now historical and distinguished from the current production
  streaming JSON-schema path used here. Existing lessons and runbooks already
  cover effective wire controls, hardware variance and schema enforcement;
  evaluated for improvement, with no new durable rule warranted.

## Reproduction and artifact boundary

The disposable execution commits retain the complete probe and workflow even
though the final tree restores both files to baseline. To repeat the experiment,
check out 4dfe28bd4336885b65e89c1ea1eb45c23ce64786 on an experiment branch
for the original pair, or 10c14ee1cff81b36f76269ab48126c60c1fca237 for the
Bonsai-only no-repack retry, and dispatch local-llm on that branch. The workflow
pins downloads, verifies Docker limits, executes production eval, and uploads
reports and runtime evidence. It is an experiment, not a default-lane change.

Qwen manifest digest:
9ec8897f747e246e970bc5cfdda85d22f1123dc2e3d34978a010a75968716849.
Ollama image (reported version 0.34.0):
sha256:684d8674b4315fa18f4f0e973a118ec2652ed96f67563277839985175858e0ba.
Prism runtime archive SHA256: local ARM64
238f34e59c955eed38433ac5bfc0406ff48c4452768c2cc691c630678c34700d;
hosted x64 a1fd3a575e70532567845815a042428831771661b857e80f06422fb08904cb7f.
Model bytes are pinned; Ubuntu base is pinned, while the Docker build's apt
package resolution is not fully pinned. Container inspections retain effective
configuration. Hosted artifact retention is 14 days; downloaded copies and local
reports remain in the ignored .cache/bonsai-comparison/results directory.


## Follow-up: diagnose hosted runtime failure

The no-repack run timed out at 1860.104 s with exactly one request, byte-identical
to the first successful local request. No report or verdict was produced. Docker
was still running, no OOM events occurred, and cgroup CPU usage was 7528.715 s.
The hosted retry used AMD EPYC 7763. Its 733900800-byte cgroup peak cannot be
used as total model memory. File mapping charge ownership is a hypothesis,
not yet an established explanation.

The owner requested continued diagnosis. Pinned source shows the x86 PQ2 dot
kernel uses explicit SIMD only for VNNI variants, falling back to scalar loops
on the retry host's AVX2 CPU. Test that hypothesis before changing a runtime:
run bounded direct streaming requests (tiny/plain, full/plain, full/schema),
then repeat the discriminating tiny/full plain requests with a runtime copy
containing only the Haswell backend on the same host. Keep four CPU cores,
16 GiB, swap disabled, the model bytes and no-repack setting. These one-token,
120-second diagnostic probes are not semantic scores. Capture verbose runtime
logs, actual loaded libraries, process RSS/mappings, memory accounting and
sampled thread stacks. Restart between probes to isolate cancellation/cache
state. GDB samples may perturb timing, so do not present them as benchmarks.
All diagnostic harness changes remain disposable, retained in execution commits
and restored before final results-only closure. Default policy and gold remain
unchanged. Local tiny-request harness validation precedes hosted dispatch.
