# Analyze Adapter JSON Mode (Constrained Decoding)

Status: implemented in this slice.
Plan type: implementation, no spec delta.
Risk level: low — one capability-gated option on the existing adapter call;
no new config key, no CLI change, no new dependency, hermetic boundary
unchanged.

## Goal

Have `default_adapter` request provider-enforced JSON output
(`json_object=True`, i.e. OpenAI-style `response_format: {"type":
"json_object"}`) whenever the resolved `llm` model supports that option, so
syntactically invalid model output becomes impossible on providers with
constrained decoding, instead of a per-packet error row.

## Motivation (measured, 2026-07-06)

Probes through the production adapter and parser against the local live
lane's bounded `llama3.2:3b` (details in
`docs/plans/2026-07-03-local-llm-eval-lane-plan.md`):

- Baseline prompt: per-row parse validity swung 40–90% across sessions; every
  syntax failure was a pure JSON slip (missing final `}` when the model
  pretty-prints; missing opening quote on a string value).
- Prompt-level fixes do not work at this model size: a concrete few-shot
  example row scored 0/8 (the model parrots the example's `packet_id`);
  strict formatting directives were a statistical wash and introduced
  dropped-field failures.
- `json_object=True` through the same registration: 9/12 rows valid with
  **zero** syntax failures; the remaining rejects were content-level
  (invalid evidence path, one missing field) — exactly what row validation
  exists to catch.
- Verified end-to-end: Ollama's OpenAI-compatible surface enforces JSON mode
  at the decoder (it cannot emit invalid JSON even when the prompt asks for
  pretty-printing), and `llm` 0.31 forwards `json_object=True` as
  `response_format` for any `extra-openai-models.yaml` registration.

## Design

- Capability-gated, provider-neutral: pass `json_object=True` only when
  `"json_object"` is a field of the resolved model's `Options` class
  (`model.Options.model_fields`). Models without the option (non-OpenAI
  plugins) get the unchanged call. No provider names are consulted, keeping
  [CFG-9]'s no-provider-specific-handling rule intact.
- Always-on when supported, no config key: constrained decoding cannot make
  a conforming model worse at the row contract, classifications remain
  advisory ([SC-7]), and the prompt already satisfies OpenAI's requirement
  that JSON mode be mentioned in the prompt ("Respond with a single JSON
  object").
- **Reject-tolerant fallback (codex P1).** The `Options` field proves only
  that the *llm wrapper* accepts the option — every `api_base` registration
  is llm's OpenAI `Chat` class — not that the server behind it accepts
  `response_format`. A server that rejects (rather than ignores) it must not
  be worse off than before this change: a failed JSON-mode call falls back
  to the bare call for that prompt and disables JSON mode for the rest of
  the adapter's life. If the bare call also fails, the exception propagates
  and analyze contains it per packet exactly as before. Both behaviors have
  firing hermetic tests, plus a dependency-contract test pinning that llm's
  `Chat.Options` declares `json_object` and `build_kwargs` maps it to
  `response_format: {"type": "json_object"}` (so an llm upgrade that drops
  the mapping fails loudly instead of silently losing constrained decoding).
- The fenced-output tolerance in `_parse_model_output` stays: models without
  JSON mode still go through the same parser.

## No Spec Delta

[SC-7] pins the analyze flow, exit-code semantics, row validation, and the
hermetic fake-adapter proof — not decoder options on the real adapter call.
[SC-7]'s local-endpoint paragraph ("no change to the runtime adapter")
states what the local lane must not *require*; the adapter evolving for all
lanes does not contradict it. The [SC-7] implementation mapping already
covers `backstitch/analysis_llm.py` and `tests/test_analysis_llm.py`.

## Tasks

1. Hermetic tests in `tests/test_analysis_llm.py`: `default_adapter` passes
   `json_object=True` to `model.prompt` when the model's `Options` declares
   the field, and passes no such option when it does not (both proven with
   fake models at the one acceptable fake boundary).
2. Implement the capability gate in `backstitch/analysis_llm.py`.
3. Re-measure the local live gate pass rate (bounded `llama3.2:3b`, 8 runs)
   and record the result here and in the local-lane plan/README numbers.
4. Update `docs/implementation/04-backstitch-style-traceability.md`'s
   adapter description.
5. Full gates + independent (codex) review + commit.

## Verification

- `uv run pytest tests -q` (hermetic; new adapter tests firing)
- `uv run pytest tests/acceptance -q`
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy
  backstitch bin/release.py --config-file pyproject.toml`
- `uv run backstitch check --repo-root .` → exit 0, zero errors/warnings
- Local live gate, 8 consecutive runs, bounded `llama3.2:3b` — record pass
  rate against the pre-change 7/8 baseline.

Measured result (2026-07-06, 16 vCPU / 16.8 GB Docker Desktop VM, bounded
`llama3.2:3b` @ num_ctx 4096 / num_predict 1024 / temperature 0): the
lenient gate passed **8/8 consecutive runs with zero contained error rows**
(pre-change baseline: 7/8 gate passes, with per-row syntax-slip error rows
tolerated by the lenient contract). Explicit strict-mode runs
(`BACKSTITCH_LIVE_LLM_STRICT=1`) passed 4 of 5 across the session — one
content-level reject — so strict remains non-required, per plan.

## Independent Review

Codex review of the initial diff: one P1 — the capability gate proved
wrapper support, not server support, so an OpenAI-compatible server that
*rejects* `response_format` would have flipped from working to total
failure. Fixed with the reject-tolerant fallback above. Two P2s, both
applied: the dependency-contract test against llm's `Chat` (fakes alone
would not catch an llm upgrade dropping the `json_object` →
`response_format` mapping), and a stale 7/8-era passage in
`docs/implementation/04-backstitch-style-traceability.md`.

## Residual Risk

- Cloud-lane JSON mode (gpt-5-series) is exercised by the existing
  secret-gated live job and the release precheck, not in this slice — a
  cloud model rejecting `response_format` would surface there as one
  fallback retry per adapter, then pre-change behavior. Named, not silently
  skipped.
- Providers whose `Options` declares `json_object` but whose server ignores
  it degrade to exactly the pre-change behavior (parser + row validation
  still gate).
- The fallback treats *any* exception on the JSON-mode call as possible
  rejection, so one transient network blip disables constrained decoding
  for the remainder of that analyze run — an acceptable degradation to the
  pre-change baseline, never below it.
