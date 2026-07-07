# Local Model Catalog And `backstitch doctor`

Status: doctor implemented (2026-07-06). Tasks 2 (spec promotion: [SC-5],
[SC-8], new [SC-14] with mapping, [CFG-3] doctor anchor row), 5 and 6
(`backstitch/doctor.py`, CLI wiring, `tests/test_doctor.py` — 21 hermetic
tests; live proof against the running Docker Ollama lane: healthy `--probe`
all-pass exit 0, broken env fail/skips exit 2 with remedies), and the
doctor-scope parts of Task 7 (repo map, implementation index, traceability
doc, README pointer) are complete. Task 4 is partial: the catalog doc
exists with the one measured row (`llama3.2:3b` baseline) and explicit
pending-sweep notes; Task 3 (LM Studio bake-off sweep) has not run. The
Task 7 "twelve → thirteen probes" addendum was already fixed by the
concurrent organization refactor (verified — no occurrences remain).
Plan reviewed through three codex rounds pre-implementation (round-3
verdict: "Yes"); post-implementation adversarial codex review ran two
rounds (round 1: five P1s, all fixed with firing tests; round 2 verified
every fix and answered "Does the implementation faithfully satisfy the
promoted [SC-14]/[SC-5]/[SC-8]/[CFG-3] contracts as written? **Yes**" with
no findings). Details in Independent Review Incorporation.
Plan type: implementation with spec revision.
Risk level: moderate — a public CLI shape changes (new `doctor` subcommand),
so the hardening checklist applies; the change is additive, has no async or
persistence lifecycle, and contains no one-way doors.

## Goal

Give users a working on-ramp to the credential-free local analysis lane in
two parts: (1) a measured, versioned **model catalog** in docs ("choosing a
local model", sized from ~3B to ~32B, seeded by a bake-off run through the
existing live-gate harness), and (2) a provider-neutral **`backstitch
doctor`** command that diagnoses the user's existing `llm`/model/endpoint
configuration and points at that catalog. Doctor encodes the environment
failure modes already met in practice (unresolvable model, missing
credential, endpoint up but model absent, `llm` version drift, constrained
decoding unavailable) as machine-checkable checks with remedies.

Explicitly **not** in this plan: an auto-recommender (`backstitch
recommend` or `doctor --suggest`). That is deferred until the catalog has
measured rows and external users exist (see Out Of Scope).

## Requested Outcomes

- A bake-off evidence table for candidate local models (~7B–~32B) produced
  by the same harness that gates the local live lane: lenient-gate pass
  rate, strict-mode pass rate, wall-clock per run, memory footprint, and a
  qualitative note on rationale quality — plus the already-recorded
  `llama3.2:3b` baseline.
- A versioned docs page (`docs/implementation/06-choosing-a-local-model.md`)
  holding that table with its measurement date and re-check caveat; README
  points at it. The catalog lives in docs, never in the shipped package —
  model availability rots faster than releases.
- `backstitch doctor`: static environment diagnosis by default (no network
  I/O), `--probe` for endpoint reachability, `--format text|json`, exit `0`
  iff no check reports `fail` (skips never affect the exit code) and exit
  `2` otherwise (never `1`, which [SC-5] reserves for statements about the
  target repository).
- Spec coverage: `doctor` added to the [SC-5] CLI contract, the [SC-8] lazy
  `llm` import boundary extended to name the `doctor` execution path, and a
  new [SC-14] section defining doctor's checks and output contract.

## Source Documents

- `docs/specs/02-backstitch-core.md` [SC-5] (CLI contract, exit-code
  dichotomy), [SC-7] (semantic analysis, advisory), [SC-8] (lazy `llm`
  import; `check`/`packets` structurally incapable), [SC-10] (subprocess
  quarantine proof), [SC-13] (input validation posture)
- `docs/specs/03-backstitch-configuration.md` [CFG-5] (model resolution
  precedence), [CFG-9] (local wiring is `llm` environment config; no
  provider-specific handling in backstitch runtime modules)
- `docs/plans/2026-07-03-local-llm-eval-lane-plan.md` (the lane this
  onboards users to; bake-off method and recorded `llama3.2:3b` evidence)
- `docs/plans/2026-07-06-analyze-json-mode-plan.md` (constrained decoding;
  the `json_object` capability check doctor reports on; the llm 0.31
  dependency-contract test this plan's doctor check mirrors)
- `backstitch/cli.py` (`build_parser`, `_cmd_analyze` — read first, see
  Context) and `backstitch/analysis_llm.py` (`resolve_model_name`,
  `default_adapter`)
- `tests/test_analysis_llm.py` (fake-model boundary pattern;
  `test_llm_chat_options_map_json_object_to_response_format`)
- `tests/test_live_llm_helpers.py` (loopback HTTP test-server pattern for
  hermetic reachability tests)
- `tests/live/test_live_llm.py` (`_read_json_url`, `_assert_model_listed` —
  the reachability logic doctor productizes; `_select_live_packets` and the
  gate flow the bake-off reuses)
- `docs/agent-context/runbooks/writing-plans.md` §4b–§4d,
  `hardening-plans.md` (checklist applied — CLI shape change),
  `writing-specs.md` (section/mapping format)

## Spec Baseline

- `6e4b423` (repo HEAD at plan authoring) for
  `docs/specs/02-backstitch-core.md` and
  `docs/specs/03-backstitch-configuration.md`. Sections [SC-1]–[SC-13] are
  active; the new section lands as `## 14. Environment Doctor [SC-14]`
  between [SC-13] and `## Related Plans`.
- Environment change at implementation start (2026-07-06, worktree over
  `df320ab`): the organization-refactor plan landed in the working tree
  concurrently — `cli.py` is now a thin dispatcher over
  `check_pipeline.py`/`artifact_contracts.py`, and the [SC-10] `llm`
  quarantine subprocess test this plan's Task 5 was going to add **now
  exists** in `tests/test_cli.py` (covering exactly `check` and
  `packets`). Task 5 therefore verifies doctor stays out of that command
  list instead of creating the test. `_cmd_analyze`'s contract-relevant
  shape (handler-level lazy imports, `resolve_model_name` precedence) is
  unchanged; stale line numbers in Context are superseded by the refactor.
- Promotion baseline identifier: worktree over `df320ab` with the
  organization refactor present, after the spec-promotion edits below;
  verified by `uv run backstitch check --repo-root .` (exit 0, zero
  errors, zero warnings).

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Context And Key Files

Read first, in this order:

1. `backstitch/cli.py` — `build_parser()` registers subcommands
   (`check` line ~47, `packets` ~125, `analyze` ~143, `summarize-analysis`
   ~159, `config` ~178) each with a `_cmd_*` handler returning the exit
   code. `_cmd_analyze` (line ~561) is the template for an `llm`-touching
   handler: the `llm`-adjacent imports are **inside the handler** ([SC-8]),
   config loads via `load_settings` unless `--no-config`, and the model is
   resolved by `resolve_model_name(args.model,
   configured=settings.analyze.model)` — that helper (in
   `backstitch/analysis_llm.py`, ~line 219) is the single owner of
   [CFG-5] precedence: `--model` > `LLM_MODEL` > config > `llm` default
   (environment overrides config, [CFG-5]; firing test in
   `tests/test_review_remediation.py`). Doctor MUST call the same helper,
   never reimplement precedence.
2. `backstitch/analysis_llm.py` — `default_adapter` shows the capability
   check doctor reports on (`"json_object" in model.Options.model_fields`)
   and the lazy-import pattern. `_resolve_live_model()` in
   `tests/live/test_live_llm.py` shows the `needs_key`/`llm.get_key`
   credential preflight doctor generalizes.
3. `tests/live/test_live_llm.py` — `_read_json_url` + `_assert_model_listed`
   are the `--probe` reachability logic (GET `<api_base>/models`, OpenAI
   `{"data": [{"id": ...}]}` shape, explicit timeout, diagnostic on
   failure). Doctor ports this logic into `backstitch/` rather than
   importing from tests.
4. `docs/implementation/04-backstitch-style-traceability.md` — the "llm
   quarantine" and "constrained decoding" bullets doctor's docs must stay
   consistent with.

Comprehension checks before editing:

1. Why must doctor never exit `1`? (Answer: [SC-5] reserves `1` for
   deterministic statements about the **target repository**; doctor makes
   statements about the invocation environment and the tool, which is the
   exit-`2` side of the dichotomy.)
2. Why does `_cmd_doctor` import `llm` inside the handler, and what does
   [SC-8] claim proves the boundary? (Answer: [SC-8] requires lazy import
   and says "[SC-10] proves it with a subprocess test" — but **no such
   test exists in `tests/` as of `cc1e41c`** (verified 2026-07-06; the
   implementation doc repeats the claim). This plan's Task 5 adds the
   missing test, closing a latent spec-compliance gap that predates
   doctor.)
3. Why does the model catalog live in `docs/` and not inside the `doctor`
   command? (Answer: [CFG-9] forbids provider-specific handling in runtime
   modules, and a shipped catalog becomes a bug the moment upstream tags
   move — docs staleness is cheap, package staleness is not.)

## Invariants And Constraints

- **No provider names in `backstitch/` code — including remedy strings.**
  Doctor's checks use only the `llm` API surface (`get_model`,
  `needs_key`, `get_key`, `Options`, `api_base`) and generic HTTP. Remedy
  text points at the catalog doc path generically
  (`docs/implementation/06-choosing-a-local-model.md`), which is where
  provider names live. This keeps the provider-name grep test over
  `backstitch/doctor.py` unconditional — no carveout to fight it.
  ([CFG-9] invariant carried over from the local-lane plan.)
- **Default doctor performs no network I/O and no model generation.**
  Reachability requires `--probe`. Generation probes are out of scope for
  v1 entirely (the live lane owns generation proof; a doctor generation
  against a keyed cloud model would silently spend money).
- **`--probe` never sends a credential.** It performs unauthenticated GETs
  only; a `401`/`403` response counts as "reachable" (the server answered).
- **Exit contract: `0` iff no check has status `fail` (skips never affect
  the exit code), `2` when any check fails or doctor itself cannot run.
  Never `1`.** ([SC-5] dichotomy.)
- **Lazy `llm` import: no top-level `llm` import in `cli.py` or
  `doctor.py`.** `llm` may be imported only inside doctor
  execution/check functions (the check engine lives in `doctor.py`, so
  the boundary is function-level there, not "handler-only" in `cli.py`).
  `check`/`packets` stay structurally incapable of importing `llm`,
  proven by the quarantine test Task 5 adds.
- **Doctor writes no backstitch state and creates no files itself** (v1:
  stdout only — no `--output` flag, YAGNI). Caveat, verified against llm
  0.31: `llm.get_model()`/`llm.get_key()` reach `llm.user_dir()`, which
  `mkdir`s llm's own user directory — an `llm` behavior doctor inherits,
  not a doctor write; the spec text says exactly this.
- **No traceback may reach the user** ([SC-5]); every failure is a check
  result or a one-line `backstitch: error: ...` + exit `2`.
- **No new dependency.** RAM detection is stdlib best-effort
  (`os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")` on POSIX,
  "unknown" elsewhere) and the memory check is informational only — it can
  never fail the run.
- **Model resolution reuse.** `resolve_model_name` is the only precedence
  owner. Doctor takes `--model`, `--config`, `--no-config` flags with
  `analyze`'s exact semantics (config anchored at cwd for doctor, since
  there is no packets file — name this in the spec delta).
- **Fatal vs best-effort within doctor:** an unresolvable model or missing
  required credential is a failed check (exit `2`); memory detection
  failure and absent-`api_base` reachability are skips, not failures.
- **Catalog is docs-only.** The shipped package contains no model names
  except test fixtures and the live-lane defaults that already exist.

## Hidden Couplings

- **[SC-10] quarantine test does not exist yet.** [SC-8] claims a
  subprocess test proves `llm ∉ sys.modules` for deterministic commands,
  and `docs/implementation/04-backstitch-style-traceability.md` repeats
  the claim — but no such test exists in `tests/` (verified 2026-07-06,
  found during this plan's adversarial review). Task 5 adds it: a
  subprocess per deterministic command (`check`, `packets`) that invokes
  the CLI in-process and asserts `"llm" not in sys.modules` afterward.
  `doctor` and `analyze` are deliberately NOT in that list. Adding the
  test makes the existing spec and doc claims true — no spec text change
  needed for this item.
- **`resolve_model_name` raises/returns on unknown models via
  `default_adapter`'s `KeyError` path in analyze.** Doctor must catch
  `llm.UnknownModelError` (a `KeyError` subclass) itself and convert it to
  a failed check with the resolution source in the message — not exit with
  the analyze-style one-liner, and not print a traceback.
- **`--format json` output is a new machine contract.** Keep it minimal and
  spec it in [SC-14]: `{"checks": [{"name", "status"
  ("pass"|"fail"|"skip"), "detail", "remedy"}], "ok": bool}`. The guard is
  the enumerable-contract rule: every check name, status value, flag, and
  exit code gets a firing test.
- **Native server is LM Studio, not Ollama.** The host's installed local
  server is LM Studio (`http://127.0.0.1:1234/v1` by default) — different
  port (no clash with the Docker Ollama), different model identifiers
  (read `GET /v1/models`, never assume Ollama tags), and no Modelfile
  (context/temperature bounds are per-model load settings; output caps
  are server defaults since `analyze` sends none). The live-lane env
  contract already supports this via
  `BACKSTITCH_LOCAL_LLM_UPSTREAM`/`_ENDPOINT` and the loopback allowlist.
- **Bake-off comparability.** The recorded `llama3.2:3b` 8/8 evidence was
  measured in the 16-vCPU Docker VM (CPU-only, Ollama). Native LM Studio
  (Metal) numbers are not comparable wall-clock-wise and are bounded
  differently; the catalog table must carry an environment column so
  CPU-Docker-Ollama and Metal-LM-Studio rows are never conflated.
- **README length.** The testing section is already long; the catalog gets
  a one-line pointer from README, not another table.

## Proposed Spec Delta

Promotion strategy per file:

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/02-backstitch-core.md` | A — in-file: [SC-5] and [SC-8] are text edits to already-mapped sections; new [SC-14] lands text-first without a mapping block (mapping + code + backlink land together in the doctor code slice) | [SC-5], [SC-8], new [SC-14], Related Plans |
| `docs/specs/03-backstitch-configuration.md` | A — in-file: one row added to [CFG-3]'s already-mapped discovery-anchor table | [CFG-3], Related Plans |

### [SC-5] — add after the `summarize-analysis` command block

> Required environment-diagnosis command:
>
> ```bash
> backstitch doctor
> backstitch doctor --probe --format json
> ```
>
> `doctor` diagnoses the semantic-analysis environment (the `llm`
> installation, model resolution, credentials, constrained-decoding
> capability, and — with `--probe` — endpoint reachability) per [SC-14]. It
> accepts `--model`, `--config`, and `--no-config` with `analyze`'s
> semantics, anchoring config discovery at the current working directory.
> `doctor` exits `0` when no check reports `fail` (skipped checks never
> affect the exit code) and `2` when any check fails or doctor itself
> cannot run; it never exits `1`, which is reserved for statements about
> the target repository.

### [SC-8] — replace the final paragraph's first sentence

Replace:

> `llm` must be imported lazily and only inside the `analyze` execution
> path.

with:

> `llm` must be imported lazily and only inside the `analyze` and `doctor`
> execution paths.

(The rest of the paragraph — `check`/`packets` structurally incapable,
[SC-10] subprocess proof — is unchanged.)

### New section — insert before `## Related Plans`

> ## 14. Environment Doctor [SC-14]
>
> `backstitch doctor` reports the health of the semantic-analysis
> environment as an ordered list of named checks, emitted in exactly the
> order they are defined below (output order is part of the contract for
> both text and JSON formats). Each check yields
> `pass`, `fail`, or `skip` with a one-line detail and, on failure, a
> one-line remedy naming the required action. Checks are provider-neutral:
> they consult only the `llm` library's public surface and generic HTTP,
> never provider identities.
>
> Required checks:
>
> - `llm-import`: the `llm` package imports; its installed version is
>   reported. Failure to import is a failure; the version itself is
>   informational (the declared constraint is open-ended, so API drift is
>   guarded by the hermetic dependency-contract test, not by a version
>   comparison here).
> - `model`: the model resolves via the [CFG-5] precedence (`--model`,
>   then `LLM_MODEL`, then config, then the `llm` default — environment
>   overrides config), reporting which source won. An unresolvable model
>   is a failure naming the attempted name.
> - `credential`: when the resolved model declares a key requirement, a
>   credential is discoverable the same way `analyze` would find it; a
>   keyless model (local `api_base`) passes with that fact in the detail.
> - `json-mode`: reports whether the resolved model's options declare
>   `json_object` (constrained decoding available to `analyze`). Absence
>   is a reported fact, not a failure.
> - `memory` (informational, never a failure): best-effort detected
>   physical memory plus a pointer to the local-model catalog in the
>   implementation docs.
> - `endpoint` (only with `--probe`; skipped without it and skipped for
>   models with no `api_base`): the model's `api_base` answers an
>   unauthenticated `GET <api_base>/models` within a bounded timeout. A
>   connection failure, timeout, or HTTP status other than `200`, `401`,
>   or `403` is a failure. On `200`, the served model name — the model's
>   `model_name` attribute when present, otherwise its `model_id` (the
>   identifier `llm`'s OpenAI wrapper actually sends to the server; an
>   `api_base` registration resolves an alias while the server lists the
>   served upstream name) — must appear in the returned OpenAI-style
>   `data[].id` list, else the check fails with the ids seen. On `401` or
>   `403` the endpoint counts as reachable and the check passes with a
>   detail stating that the model list is authentication-gated and
>   membership was not verified. No credential is ever sent; no generation
>   is performed.
>
> Allowed statuses per check (an implementation must not emit others):
> `llm-import` — `pass`/`fail`; `model` — `pass`/`fail`, `skip` when
> `llm-import` failed; `credential` — `pass`/`fail`, `skip` when the model
> is unresolved; `json-mode` — `pass` (the detail states whether
> constrained decoding is available), `skip` when the model is unresolved;
> `memory` — `pass` only (undetectable memory is a `pass` with an
> "unknown" detail); `endpoint` — `pass`/`fail`, `skip` without `--probe`,
> when the model is unresolved, or when the model has no `api_base`.
>
> `--format json` emits `{"checks": [{"name": ..., "status":
> "pass"|"fail"|"skip", "detail": ..., "remedy": ...}], "ok": <bool>}`;
> `remedy` is empty for non-failures. `ok` is `true` and the exit code is
> `0` if and only if no check has status `fail`; otherwise the exit code
> is `2` — never `1` ([SC-5]). Skipped checks never affect the exit code.
> Doctor performs no model generation and no network I/O without
> `--probe`, mutates no backstitch state and writes nothing itself
> (consulting `llm` may create `llm`'s own user directory — that is
> `llm.user_dir()` behavior doctor inherits, not a doctor write), and
> must not import `llm` at module import time ([SC-8]).

### `docs/specs/03-backstitch-configuration.md` [CFG-3] — add one row to the §3.1 discovery-anchor table

> | `doctor` | current working directory after `resolve()` |

(The table currently lists `check`, `packets`, `analyze`, and
`summarize-analysis`; [CFG-3] owns command discovery anchors, so doctor's
cwd anchor must be recorded there, not only in [SC-5].) `## Related Plans`
gains this plan as `(implementing)`. Doctor introduces no config key: it
reads the same `[analyze]` settings analyze reads, which [CFG-5] already
governs.

## Rollout And Rollback

Rollout: slices below, dependency-ordered; everything is additive. The
bake-off (Task 3) runs on the author's machine and touches no repo runtime;
the native lane uses the already-installed LM Studio (no new software), and
the Docker Ollama container stays as the CI-shaped lane.

Rollback: remove the `doctor` subparser/handler/tests and the catalog doc;
revert the [SC-5]/[SC-8]/[SC-14] edits in a spec-revision slice. No
persistence, no migration, no one-way doors. The catalog doc can outlive a
doctor rollback (it is independently useful).

## Tasks

1. **Independent plan review.** Different agent family (codex). Reviewer
   reads this plan including the Proposed Spec Delta, `backstitch/cli.py`,
   `backstitch/analysis_llm.py`, and the two source plans; stance per the
   writing-plans runbook: "could you implement this confidently and
   correctly against the delta as if promoted?" Findings folded in below.

2. **Spec-promotion slice.**
   - Files: `docs/specs/02-backstitch-core.md`,
     `docs/specs/03-backstitch-configuration.md`.
   - Apply the delta exactly: [SC-5] insertion, [SC-8] sentence
     replacement, [SC-14] section text **without** a mapping block
     (strategy A — no code may cite [SC-14] until Task 5 lands mapping +
     code + backlink together); add this plan to both `## Related Plans`.
   - Record the promotion baseline identifier in Spec Baseline above.
   - Verify: `uv run backstitch check --repo-root .` → exit 0, zero
     errors, zero warnings ([SC-14] unmapped yields info-class debt only).

3. **Bake-off evidence sweep.** (No repo runtime changes; may run in
   parallel with Task 2.)
   - Native lane: **LM Studio** (already installed on the host — the
     machine owner's chosen local server; do not install Ollama natively).
     Start its OpenAI-compatible server (`lms server start`, default
     `http://127.0.0.1:1234/v1`) and point the harness at it via
     `BACKSTITCH_LOCAL_LLM_UPSTREAM`/`BACKSTITCH_LOCAL_LLM_ENDPOINT` —
     loopback, so the lane's non-local guard is satisfied, and no port
     clash with the Docker Ollama on 11434 (both can stay up). This also
     dogfoods the lane's provider-neutrality claim: nothing in the test or
     adapter may need editing for a different OpenAI-compatible server; if
     anything does, stop and record it as a finding before proceeding.
   - `BACKSTITCH_LOCAL_LLM_SERVED_MODEL` must equal the id LM Studio lists
     on `GET /v1/models` (LM Studio uses its own identifiers, not Ollama
     tags — read the list, do not guess).
   - Bounding differs from CI: LM Studio has no Modelfile. For
     comparability with the CI config, set context length 4096 and
     temperature 0 in LM Studio's per-model load settings (or `lms` CLI
     flags) and record exactly what was set per model; output-length caps
     come from server/model defaults since `analyze` sends none — record
     that too. Before the sweep, probe one small model to confirm LM
     Studio accepts `response_format: {"type": "json_object"}` (the
     adapter requests it; a rejection exercises the fallback and must be
     recorded, not hidden).
   - Candidates (LM Studio catalog equivalents of): `qwen3:8b`,
     `qwen2.5-coder:7b`, `qwen3:14b`, `gpt-oss:20b`, and
     `qwen2.5-coder:32b` (the host has 128 GB unified memory — measured
     2026-07-06 via `os.sysconf` — so the 32B row is comfortably in
     scope). Baseline row: the recorded `llama3.2:3b` Docker evidence (do
     not re-run).
   - Per candidate: 8 lenient gate runs via `BACKSTITCH_LIVE_LLM=1
     BACKSTITCH_LIVE_LLM_KIND=local
     BACKSTITCH_LOCAL_LLM_SERVED_MODEL=<served-id> uv run pytest
     tests/live/test_live_llm.py -q`, then 3 strict runs with
     `BACKSTITCH_LIVE_LLM_STRICT=1` **added to the same command** (the
     test only enters strict mode when that variable is set — omitting it
     silently measures more lenient runs); record wall-clock per run, peak
     memory if observable, and keep one `analysis.jsonl` sample per model
     (pytest `--basetemp`) for the qualitative rationale note.
   - Stop-and-re-evaluate gate: if a candidate cannot finish a single run
     inside the 300 s per-call timeouts, record the fact and move on — do
     not raise timeouts to force a row.
   - Done: a filled table (model, params, environment, lenient rate,
     strict rate, s/run, memory, qualitative note, date).

4. **Catalog doc slice.**
   - New file: `docs/implementation/06-choosing-a-local-model.md` —
     the bake-off table, sizing guidance by available memory, the
     Docker-CPU-Ollama vs native-Metal-LM-Studio caveat, the measurement
     date, a "re-check before trusting; model availability drifts"
     warning, the provisioning pointer back to README's local-lane
     section, and a short "verified OpenAI-compatible servers" note naming
     Ollama (`127.0.0.1:11434/v1`, the CI lane) and LM Studio
     (`127.0.0.1:1234/v1`, the native dev lane on this host) with the env
     vars that point the live lane at either.
   - Update `docs/implementation/00-implementation-index.md`,
     `docs/implementation/02-repository-map.md`, and add the one-line
     README pointer.
   - Verification is by inspection (docs-only) plus the doc gates in
     Verification And Gates.

5. **Doctor code slice (static checks).**
   - Files: `backstitch/cli.py` (subparser + `_cmd_doctor`), new
     `backstitch/doctor.py` (check engine + check implementations, so the
     CLI handler stays thin), `tests/test_doctor.py`; [SC-14] mapping
     block + reciprocal backlinks land in this same slice (strategy A
     closes here).
   - Red-green: write `tests/test_doctor.py` first — fake the `llm`
     boundary exactly as `tests/test_analysis_llm.py` does (monkeypatch
     `llm.get_model`; fake models with/without `needs_key`, `api_base`,
     `json_object` in `Options.model_fields`). Enumerable contract: one
     firing test per check name, per status value, per flag, per exit
     code; a `--format json` shape test; a no-traceback subprocess test on
     a broken environment; a test that `backstitch doctor` with the fake
     env exits 0/2 correctly.
   - Checks implemented: `llm-import` (import + version report only — do
     NOT import `llm.default_plugins.*` in runtime code, that would put a
     provider-named module in `backstitch/` against [CFG-9]; the
     class-level API-drift contract stays pinned by the existing hermetic
     test `test_llm_chat_options_map_json_object_to_response_format`),
     `model`, `credential`, `json-mode` (on the resolved model's `Options`
     surface only), `memory` (info-only). `endpoint` reports `skip`
     without `--probe`.
   - Reuse: `resolve_model_name` for precedence.
   - **Add the missing [SC-10] quarantine test** (it does not exist —
     see Hidden Couplings): for each deterministic command (`check`,
     `packets`), a subprocess runs
     `python -c "import sys; from backstitch.cli import main; main([...]);
     assert 'llm' not in sys.modules"` against a minimal fixture repo.
     `doctor` and `analyze` are excluded by design. This closes a latent
     [SC-8] compliance gap that predates this plan and makes the existing
     claim in `04-backstitch-style-traceability.md` true.
   - Done: hermetic suite green; `uv run backstitch doctor` on this repo
     reports honestly (expected: pass rows for the pinned llm, model per
     config, keyless or keyed per environment).

6. **Doctor probe slice (`--probe`).**
   - Files: `backstitch/doctor.py`, `tests/test_doctor.py`.
   - Port the reachability logic from the live module (`GET
     <api_base>/models`, joined-URL trailing-slash handling, bounded
     stdlib timeout, OpenAI `data[].id` shape, model-name membership);
     `401`/`403` = reachable; no credential header ever attached.
   - Hermetic tests with loopback `http.server` fixtures (pattern:
     `tests/test_live_llm_helpers.py`): listed model → pass; reachable but
     model absent → fail with ids in detail; connection refused → fail;
     `401` → reachable; no `api_base` on the model → skip.
   - Done: suite green; manual proof recorded in the plan log against a
     real local server — LM Studio natively (`127.0.0.1:1234/v1`) and/or
     the Docker Ollama lane — via `backstitch doctor --probe` with the
     lane env set.

7. **Traceability reconciliation.**
   - Mappings/backlinks complete ([SC-14] ↔ `backstitch/doctor.py`,
     `backstitch/cli.py`, `tests/test_doctor.py`); README/traceability doc
     ([04]) updated to mention doctor next to the quarantine bullet;
     repository map row for `backstitch/doctor.py`; lessons captured if
     any; final gates below.
   - While updating SC-10-adjacent docs, correct stale "twelve probes"
     wording to the current thirteen-probe acceptance suite in
     `tests/acceptance/README.md`, `docs/implementation/02-repository-map.md`,
     and `docs/implementation/04-backstitch-style-traceability.md`. This is
     existing doc drift, but this plan already touches the [SC-10] quarantine
     proof and the same implementation docs, so it should not leave the stale
     count behind.

## Testing Plan

- Harness: the default hermetic suite (`tests/test_doctor.py`), pytest.
- The `llm` model boundary is the one acceptable fake (monkeypatched
  `llm.get_model`, fake model classes) — same posture as
  `tests/test_analysis_llm.py`. HTTP reachability is tested against real
  loopback `http.server` instances, never by mocking `urllib`.
- Not mocked: check-engine logic, JSON rendering, exit-code mapping,
  argument parsing, URL joining, and the actual installed `llm` in the
  existing dependency-contract test
  (`test_llm_chat_options_map_json_object_to_response_format`), which
  remains the API-drift guard.
- Keyless-behavior tests must register the model via a temp
  `LLM_USER_PATH` + `extra-openai-models.yaml` (the live-lane pattern):
  constructing llm's `Chat(..., api_base=...)` directly keeps
  `needs_key = "openai"`, so the direct path would falsely fail the
  `credential` check (verified against llm 0.31 during plan review).
- The `--probe` port of `_read_json_url` must special-case `401`/`403` as
  reachable-but-auth-gated; the live-lane helper deliberately fails all
  HTTP errors, so this is a divergence to implement and test, not copy.
- Contract bias: the `--format json` shape, exit codes `0`/`2`, **each
  allowed status of each check** (per the [SC-14] allowed-status table —
  not all checks can validly reach all three statuses), and the
  no-traceback rule each have a named test.
- Live proof (opt-in, not CI): `backstitch doctor --probe` against a real
  local server (LM Studio natively and/or the Docker Ollama lane), and one
  deliberately broken env (unset model / stopped server) showing fail rows
  + exit 2.
- Invariants protected: [SC-8] quarantine (the subprocess test Task 5
  adds — it does not exist before this plan), [SC-5] exit dichotomy,
  [CFG-9] provider neutrality (a test greps `backstitch/doctor.py` for
  provider-name strings — crude but firing).

## Verification And Gates

Per-task gates named above. Final:

```bash
uv run pytest tests -q
uv run pytest tests/acceptance -q
uv run ruff check . && uv run ruff format --check .
uv run mypy backstitch bin/release.py --config-file pyproject.toml
uv run backstitch check --repo-root .   # exit 0, zero errors, zero warnings
```

Observed-success signals: doctor exit 0 with honest pass rows on this
repo's configured environment; exit 2 with named fail rows + remedies on a
deliberately broken one; catalog doc renders with measured rows and an
environment column; no new warnings in the self-corpus gate.

Residual risk to name at completion: catalog numbers age (dated table +
re-check warning is the mitigation, not a fix); doctor's `--probe` proves
reachability, not generation health (the live lane owns that); RAM
detection is best-effort and platform-dependent.

## Independent Review Incorporation

Codex (different agent family, read-only, high effort) reviewed the draft
plan, the proposed delta, the named code, and the installed `llm` 0.31.
Verdict on the draft: **not implementable confidently until the P1s were
resolved**. All findings folded in:

- **P1 model precedence was wrong** in the plan and the [SC-14] delta
  (`--model > config > LLM_MODEL`): [CFG-5], `resolve_model_name`
  (`analysis_llm.py:219`), and its firing test all say environment
  overrides config (`--model > LLM_MODEL > config > llm default`). Fixed
  in both places.
- **P1 "mutates nothing" was unimplementable** through the named `llm`
  API: `llm.get_model()`/`get_key()` reach `llm.user_dir()`, which
  `mkdir`s. Invariant weakened to "writes nothing itself; consulting llm
  may create llm's own user directory" in both the invariant and the spec
  text.
- **P1 endpoint 401/403 semantics were self-contradictory** (membership
  required but auth challenges "reachable"). [SC-14] now defines the full
  status mapping: connection/timeout/other-HTTP → fail; 200 → served-name
  membership required; 401/403 → pass with auth-gated detail, membership
  unverified. Testing plan notes this diverges from the live helper.
- **P1 wrong model identifier for `/models` membership**: local
  registrations resolve an alias while the server lists the served name.
  [SC-14] now checks `model.model_name` when present, else the resolved
  name.
- **P1 skip/exit ambiguity**: exit contract is now uniformly "`ok` true
  and exit 0 iff no check has status `fail`; skips never affect the exit
  code" in Requested Outcomes, Invariants, [SC-5] delta, and [SC-14].
- **P2 stale `llm-contract` mention + weak version comparison**: the
  runtime check is import + version report only; API drift stays guarded
  by the existing hermetic dependency-contract test; testing-plan wording
  fixed.
- Codex also verified the plan's `llm` 0.31 claims and contributed the
  keyless-registration caveat now recorded in the Testing Plan (direct
  `Chat(api_base=...)` keeps `needs_key="openai"`; only the
  `extra-openai-models.yaml` registration path is keyless).

Self-found during fresh-eyes (pre-codex, also folded in): the original
`llm-contract` runtime check would have imported a provider-named module
into `backstitch/` against [CFG-9] (dropped in favor of the hermetic
test); the bake-off assumed native Ollama while the host actually runs LM
Studio (Task 3 rewritten accordingly); host memory measured at 128 GB,
putting the 32B row in scope.

Codex round 2 (adversarial re-review of the revised plan, asked literally
"If requested, could you implement this plan confidently and correctly as
written?"): confirmed all five round-1 P1s resolved, verdict still **No**
on four new P1s and two P2s — all folded in:

- **P1 [CFG-3] owns command discovery anchors**, so "no CFG text change"
  left two specs out of sync; the delta now adds a `doctor` row to the
  [CFG-3] §3.1 anchor table.
- **P1 the bake-off's "3 strict runs" omitted `BACKSTITCH_LIVE_LLM_STRICT=1`**
  and would silently have measured more lenient runs; command fixed.
- **P1 the [SC-10] `llm ∉ sys.modules` quarantine test this plan told the
  implementer to "confirm" does not exist** — [SC-8] and the traceability
  doc both claim it, but `tests/` has no such test (verified 2026-07-06).
  Task 5 now adds it, closing a latent spec-compliance gap that predates
  this plan.
- **P1 "each check's three statuses" was unimplementable** (`memory` can
  never fail; `llm-import` has no meaningful skip); [SC-14] now carries an
  allowed-statuses-per-check table and the testing plan requires coverage
  per allowed status.
- **P2 stale Ollama references** in Rollout, Task 6, and the live-proof
  lines after the LM Studio rewrite; all now name LM Studio natively with
  Docker Ollama as the CI-shaped lane.
- **P2 `/models` membership fallback**: `model_name` else `model_id` (what
  `llm`'s wrapper actually sends), not the resolved alias.

Post-implementation adversarial codex review (round 1, 2026-07-06):
verdict on the initial implementation was **No** — five P1s, all fixed
with firing tests in the same slice:

- **Credential discovery diverged from analyze's path**: a key attached
  to the resolved model (`model.key`, which llm 0.31 honors first at
  execution) would have failed doctor's check; doctor now checks the
  attached key before stored/env lookup.
- **The probe silently followed redirects**, hiding non-200/401/403
  statuses and probing a different URL than `<api_base>/models`; a
  no-redirect opener now surfaces 3xx as a failure (tested with a real
  302 server).
- **Unbounded `response.read()`**: a huge or drip-fed body could stall
  doctor past any budget; reads are now capped (`PROBE_MAX_BODY_BYTES`)
  under a wall-clock deadline (tested with an oversized payload).
- **The `extra-openai-models.yaml` remedy string plus a test carve-out
  contradicted the provider-neutrality invariant as written**; the
  filename is gone from runtime strings (remedies point at the README
  local-lane section) and the grep test has no carve-outs.
- **Hostile model names with newlines broke the one-line detail
  contract**; all details/remedies are whitespace-normalized (tested).

Its two P2 test-gap findings also landed: the loopback fixture now
asserts the exact probe path and the absence of an Authorization header,
plus new 302/403/oversized-body/llm-import-failure tests.

Pre-implementation plan review history — codex round 3 (adversarial, same
literal question): verified all round-2 findings genuinely resolved in
the text; **no P1 findings**; verdict — **"If requested, could you
implement this plan confidently and correctly as written? Yes."** Three P2 refinements, all folded in: the lazy-import
invariant restated as "no top-level `llm` import in `cli.py` or
`doctor.py`; `llm` only inside doctor execution/check functions" (so the
check engine is not forced into `cli.py`); provider names banned from
runtime remedy strings outright so the [CFG-9] grep test has no carveout
to fight (remedies point at the catalog doc path, where provider names
live); and [SC-14] now states that check output order is the defined
order, for both formats.

## Out Of Scope

- `backstitch recommend`, `doctor --suggest`, or any auto-selection of a
  model — deferred until the catalog has measured rows and external users
  exist; revisit in its own plan.
- Any model catalog inside the shipped package, including as data files.
- Generation probes from doctor (paid-call risk; the live lane owns
  generation proof).
- Installing or managing Ollama/models from doctor (no side effects).
- Changes to `analyze`, the adapter, the live lane, or CI workflows.
- Windows-specific memory detection beyond stdlib best-effort.

## Decisions

- **`doctor`, not `recommend`.** Diagnosis of the existing setup is
  durable, provider-neutral logic; recommendation is catalog data that
  belongs in docs until it has evidence and users.
- **Doctor never exits `1`.** [SC-5] reserves `1` for target-repository
  statements; doctor speaks about the environment, so failures are exit
  `2`.
- **Default is offline.** Network checks are opt-in via `--probe`;
  generation is excluded from v1 entirely.
- **Catalog placement**: `docs/implementation/06-choosing-a-local-model.md`
  with README pointer; measured rows only, environment column mandatory.
