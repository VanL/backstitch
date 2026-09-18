# Choosing A Local Model

Spec: docs/specs/02-backstitch-core.md [SC-7], [SC-14]
Plan: docs/plans/2026-07-06-local-model-catalog-and-doctor-plan.md

`backstitch analyze` can run against any local OpenAI-compatible endpoint
with no credential (see README's local-lane section for provisioning and
`backstitch doctor --probe` to verify a setup). This page is the model
catalog: measured rows only, from the live-gate bake-off harness. **Model
availability and quality drift — re-check the measurement date before
trusting a row.**

## Docker comparison, 2026-09-18

The main-branch CI incumbent is `qwen2.5-coder:14b-instruct-q4_K_M` through
Ollama. The older sweep below predates that selection. The Bonsai comparison
uses the existing schema-3 report-only smoke corpus: one clean return contract
and one mutation. Each completed semantic run made two analyzer calls and
one verifier call through the production evaluator, then exercised zero-call
cache replay.

Plan and retained execution references:
`docs/plans/2026-09-18-bonsai2-qwen-comparison-plan.md`.

| Environment | Model / runtime | Correct controls | Eval seconds | Peak container GiB | Replay calls |
|---|---|---|---:|---:|---:|
| Local Docker, ARM64 / M4 Max | Qwen14B Q4_K_M / pinned Ollama | 2/2 | 170.083 | 12.675 | 0 |
| Local Docker, ARM64 / M4 Max | Bonsai 2 27B PQ2_0 / Prism llama.cpp, non-thinking | 2/2 | 1122.514 | 8.506 | 0 |
| Hosted Docker, x86_64 | Qwen14B Q4_K_M / pinned Ollama | 2/2 | 361.104 | 12.799 | 0 |
| Hosted Docker, x86_64 | Bonsai 2 PQ2_0, no repacking | No result | Timeout: 1860.104 | Not comparable | Not reached |

Both containers have a four-vCPU quota, 16 GiB memory limit, no swap and no GPU.
Both use four inference threads, context 4096, temperature 0, seed 42, and
1024 output tokens per request. For the three successful runs, all three responses pass the
production schema/evidence path. No OOM event or response truncation occurred.
Bonsai took 6.60 times as long for this local workload while using about 33%
less peak container memory. Memory is cgroup high-water usage, including caches,
not weight size or process RSS. Latency excludes provisioning; Ollama loads on
its first request, whereas the llama.cpp server loads before readiness.

This is a deployment comparison, not a controlled isolation of quantization.
Runtime, architecture, prompt tokenization and output lengths differ. Qwen
reused 838 prompt tokens on the second analyzer call; Bonsai processed that
prompt fully. The ratio therefore includes deployment-level prompt caching. It does
not compare GPU inference or Bonsai's advertised thinking-mode quality. One
trial over two simple cases establishes neither broad accuracy nor uncached
stability. The canonical reports correctly withhold qualification.

The [first hosted run](https://github.com/VanL/backstitch/actions/runs/35371764892)
passed Qwen but Bonsai exited 139 during model loading, without an OOM kill.
[Upstream issue 180](https://github.com/PrismML-Eng/llama.cpp/issues/180) reports
a matching PQ2 CPU repacking crash and a `--no-repack` workaround. A local
Docker load/generation check passed with that option. The separately identified
[hosted retry](https://github.com/VanL/backstitch/actions/runs/35372921176)
disables repacking and retains the same resource and inference budgets; it
timed out after 1860.104 seconds during the first request, producing no report.
The container remained running, with no OOM event; this establishes failure to
meet the execution budget, not a semantic miss. The runtime diagnosis below localizes the bottleneck. The first crash is a setup failure, not a semantic score.
Hosted jobs can receive different CPU models: the Qwen job used AMD EPYC 9V45,
the first Bonsai attempt used Intel Xeon Platinum 8573C, and the retry used
AMD EPYC 7763. Their resource
quotas match, not their physical CPU identity. Hosted cgroup peaks include
provisioning inside each container; Qwen pulls
weights there, whereas Bonsai mounts a host download. Treat these peaks as
operational high-water marks, not a clean inference-memory comparison. The
Bonsai retry reported only about 0.68 GiB charged to its cgroup. The follow-up
measured 7.28–7.33 GiB process RSS, mostly file-backed pages, confirming that
the cgroup number is not total model residency. Exact charge ownership was not
traced.


### Hosted CPU diagnosis

The [bounded diagnostic run](https://github.com/VanL/backstitch/actions/runs/35378869111)
on AMD EPYC 7763 sent requests directly to the same pinned server. A tiny
23-token prompt without a schema, the full prompt without a schema, and the
full prompt with its production schema each timed out after 120 seconds with
only SSE heartbeats and no generated token. The one-token generation cap makes
these diagnostic probes, not accuracy or qualification tests. Repeating the
tiny/full plain requests with a forced Haswell backend gave the same outcome;
process mappings confirmed automatic selection already used that backend.

Across all five probes, all four sampled compute-thread program counters fell
inside `ggml_vec_dot_pq2_0_q8_0`. Raw GDB symbols were unresolved; mapping the
addresses through each process's library mappings and the matching pinned ELF
symbol table identified function start 0xd82d0, size 0x356, with sample offsets
0xbe–0x313. Independent disassembly review confirmed scalar shifts, masks,
integer multiplies and adds at the sampled instructions.

The [pinned PQ2 kernel](https://github.com/PrismML-Eng/llama.cpp/blob/prism-b10685-7dffb15/ggml/src/ggml-cpu/arch/x86/quants.c#L561)
has explicit SIMD paths for VNNI, which the EPYC 7763 lacks. The sampled
Haswell path therefore uses its scalar fallback. This localizes the observed
bottleneck to numerical computation during prompt processing; schema parsing
and Backstitch's transport are unnecessary to reproduce it. Samples do not
establish eventual completion time or exclude pathological behavior inside the
kernel. GDB sampling can perturb timing, so these probe durations are bounds,
not throughput benchmarks.

Fixing the separate Hadamard repack loading crash alone would not add a PQ2
fast path on this CPU: the pinned
[repack dispatch](https://github.com/PrismML-Eng/llama.cpp/blob/prism-b10685-7dffb15/ggml/src/ggml-cpu/repack.cpp#L5352)
requires AVX512-VNNI. A supported faster kernel or a guaranteed compatible CPU
needs a separate validation run. Four-vCPU/16-GiB limits do not specify the
instruction set. Keep Qwen as the incumbent for this CI deployment; Bonsai's
local memory saving does not offset the demonstrated hosted execution failure.
Neither model is formally qualified by this two-case experiment.

## Earlier measured rows

Correction (2026-07-10): the 2026-07-06 Ollama measurements verified the
Modelfile stored `temperature 0`, but the `llm` OpenAI request omitted the
field. Pinned Ollama 0.31.1 therefore applied request default `1.0`, overriding
the stored value. The pass counts remain historical observations, not
temperature-zero measurements. The CI harness now puts temperature zero and a
fixed seed on the forwarded request and verifies both fields.

CI correction (2026-07-10): temperature and seed stabilize sampling inputs but
do not make quantized inference byte-identical across ARM and x86 kernels. A
GitHub x86 run produced snippet-relative or malformed evidence that the strict
parser correctly rejected, while the ARM run produced one valid row. The local
CI harness now derives a packet-bounded JSON Schema, requests one nonstreaming
completion (the route where pinned Ollama enforces it), and relays the exact
assistant content back to the unchanged streaming adapter. This is test-owned;
ordinary custom endpoints at that time used the production adapter's JSON-
object request. The September comparison above instead observes the current
production streaming path with packet-bounded `json_schema` requests; it does
not use the older live-test nonstreaming bridge.

| Model (bounds) | Environment | Lenient gate | Strict | s/run | JSON constrained? | Notes |
|---|---|---|---|---|---|---|
| `llama3.2:3b` (num_ctx 4096, num_predict 1024; stored temp 0, effective temp 1.0) | Docker Ollama, 16 vCPU / 16.8 GB VM, CPU-only (2026-07-06) | 8/8 | 4/5 | **yes** (Ollama enforces) | Historical pre-stabilization row. Rationales are boilerplate; classifications advisory-only. This was the earlier CI model; the current incumbent is Qwen14B above. |
| `qwen/qwen3-8b` (ctx 4096, temp 0) | LM Studio native/Metal, 128 GB host (2026-07-06) | 8/8 | 2/3 | **no** (LM Studio ignores it) | Valid JSON is the model's own discipline, not the decoder's. |
| `qwen/qwen3-14b` (ctx 4096, temp 0) | LM Studio native/Metal, 128 GB host (2026-07-06) | 8/8 | 2/3 | **no** | Strict miss was a raw "not valid JSON" — the tail constrained decoding would have caught. |
| `openai/gpt-oss-20b` (ctx 4096, temp 0) | LM Studio native/Metal, 128 GB host (2026-07-06) | 8/8 | **3/3** | **no** | Best of the sweep: cleanest JSON and fastest (MoE, ~3.6B active), even without enforcement. |

Pending rows (downloads interrupted): `qwen2.5-coder:7b`,
`qwen2.5-coder:32b`. Until measured, treat sizing as the rough memory
guidance below, not evidence.

## Constrained decoding: enforcement is server-dependent

The July adapter requested JSON objects
(`response_format: {"type": "json_object"}`). The current typed-descriptor
production path with required JSON mode requests packet-bounded `json_schema`. A request alone does
not establish that a server enforces it: a library capability declaration
is not evidence of server behavior. Measured through the real adapter with a
prose-only "torture" prompt (2026-07-06):

| Server | Valid JSON under a prose-only prompt | Behavior |
|---|---|---|
| **Ollama** | 4/4 | Enforces `json_object` at the decoder — syntactically invalid output is impossible. |
| **LM Studio** | 0/4 | Silently ignores `json_object` (the tested version wanted the newer `json_schema` type, or `text`) and returns free prose. |

Consequence for the rows above: the Ollama row's JSON validity is
decoder-guaranteed; the LM Studio rows' validity is the **model's own**
formatting discipline. That is why a strong small model on LM Studio can
still pass 8/8 lenient, and why its occasional strict miss is a raw
"not valid JSON" that constrained decoding would have prevented. If you need
guaranteed-valid rows on LM Studio, verify schema enforcement on the deployed
server. The July result does not establish enforcement for the current
`json_schema` request path.

## Sizing guidance (rule of thumb, not evidence)

Quantized (q4-class) weights need roughly: 3B ≈ 2 GB, 7–9B ≈ 5–6 GB,
12–14B ≈ 8–10 GB, 20B-MoE ≈ 13 GB, 32B ≈ 18–20 GB — plus context KV cache
and everything else on the machine. `backstitch doctor` reports detected
memory. Small models (≤3B) prove plumbing, not judgment: expect
rubber-stamp rationales and occasional content-invalid rows even with
constrained decoding. Readable findings start around the 14B–20B class.

## Verified OpenAI-compatible servers

- **Ollama** (`http://127.0.0.1:11434/v1`) — the CI lane
  (`.github/workflows/local-llm.yml`, digest-pinned, Modelfile-bounded, with
  request-level temperature/seed and packet-bounded schema decoding applied by
  the test proxy).
- **LM Studio** (`http://127.0.0.1:1234/v1` by default) — native
  Metal-accelerated dev lane; model ids come from `GET /v1/models`, and
  context/temperature bounds are per-model load settings.

Point the live lane (or your own `analyze` runs) at either via
`extra-openai-models.yaml` (`api_base`), and the opt-in live test via
`BACKSTITCH_LOCAL_LLM_UPSTREAM` / `BACKSTITCH_LOCAL_LLM_SERVED_MODEL` —
both loopback addresses satisfy the lane's non-local guard.

## Comparability caveat

Docker-on-macOS is CPU-only; native LM Studio uses the GPU. Wall-clock
numbers across those environments are not comparable — every measured row
names its environment, and rows must never be merged across environments.
