# Choosing A Local Model

Spec: docs/specs/02-backstitch-core.md [SC-7], [SC-14]
Plan: docs/plans/2026-07-06-local-model-catalog-and-doctor-plan.md

`backstitch analyze` can run against any local OpenAI-compatible endpoint
with no credential (see README's local-lane section for provisioning and
`backstitch doctor --probe` to verify a setup). This page is the model
catalog: measured rows only, from the live-gate bake-off harness. **Model
availability and quality drift — re-check the measurement date before
trusting a row.**

## Measured rows

| Model (bounds) | Environment | Lenient gate | Strict | s/run | JSON constrained? | Notes |
|---|---|---|---|---|---|---|
| `llama3.2:3b` (num_ctx 4096, num_predict 1024, temp 0) | Docker Ollama, 16 vCPU / 16.8 GB VM, CPU-only (2026-07-06) | 8/8 | 4/5 | **yes** (Ollama enforces) | Rationales are boilerplate; classifications advisory-only. The CI lane's committed default. |
| `qwen/qwen3-8b` (ctx 4096, temp 0) | LM Studio native/Metal, 128 GB host (2026-07-06) | 8/8 | 2/3 | **no** (LM Studio ignores it) | Valid JSON is the model's own discipline, not the decoder's. |
| `qwen/qwen3-14b` (ctx 4096, temp 0) | LM Studio native/Metal, 128 GB host (2026-07-06) | 8/8 | 2/3 | **no** | Strict miss was a raw "not valid JSON" — the tail constrained decoding would have caught. |
| `openai/gpt-oss-20b` (ctx 4096, temp 0) | LM Studio native/Metal, 128 GB host (2026-07-06) | 8/8 | **3/3** | **no** | Best of the sweep: cleanest JSON and fastest (MoE, ~3.6B active), even without enforcement. |

Pending rows (downloads interrupted): `qwen2.5-coder:7b`,
`qwen2.5-coder:32b`. Until measured, treat sizing as the rough memory
guidance below, not evidence.

## Constrained decoding: enforcement is server-dependent

The `analyze` adapter always *requests* provider-enforced JSON
(`response_format: {"type": "json_object"}`) when the `llm` model accepts the
option, but **whether the server honors it is not something `backstitch
doctor` can tell you** — its `json-mode` check reports the library capability,
not the server's behavior. Measured through the real adapter with a
prose-only "torture" prompt (2026-07-06):

| Server | Valid JSON under a prose-only prompt | Behavior |
|---|---|---|
| **Ollama** | 4/4 | Enforces `json_object` at the decoder — syntactically invalid output is impossible. |
| **LM Studio** | 0/4 | Silently ignores `json_object` (its API wants the newer `json_schema` type, or `text`) and returns free prose. |

Consequence for the rows above: the Ollama row's JSON validity is
decoder-guaranteed; the LM Studio rows' validity is the **model's own**
formatting discipline. That is why a strong small model on LM Studio can
still pass 8/8 lenient, and why its occasional strict miss is a raw
"not valid JSON" that constrained decoding would have prevented. If you need
guaranteed-valid rows on LM Studio, load the model with a JSON schema in its
own settings; `analyze` does not send one.

## Sizing guidance (rule of thumb, not evidence)

Quantized (q4-class) weights need roughly: 3B ≈ 2 GB, 7–9B ≈ 5–6 GB,
12–14B ≈ 8–10 GB, 20B-MoE ≈ 13 GB, 32B ≈ 18–20 GB — plus context KV cache
and everything else on the machine. `backstitch doctor` reports detected
memory. Small models (≤3B) prove plumbing, not judgment: expect
rubber-stamp rationales and occasional content-invalid rows even with
constrained decoding. Readable findings start around the 14B–20B class.

## Verified OpenAI-compatible servers

- **Ollama** (`http://127.0.0.1:11434/v1`) — the CI lane
  (`.github/workflows/local-llm.yml`, digest-pinned, Modelfile-bounded).
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
