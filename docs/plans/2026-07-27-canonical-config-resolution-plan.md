# Canonical Configuration Resolution And CLI Overrides Plan

Plan type: implementation with spec revision.

Class: 5 because this plan changes normative configuration and CLI behavior.
Class-4 hardening also applies because the public CLI shape changes and the
same resolution boundary is used by local commands and a secret-bearing
hostile-target workflow.

Risk level: medium-high. The value parser is small. The risk is allowing
configuration to be resolved in more than one place, applying precedence
differently by command, or letting pull-request-controlled bytes select
provider settings.

## Goal

Give Backstitch one canonical configuration resolver and one typed,
invocation-scoped configuration object. The resolver owns packaged defaults,
config discovery or explicit selection, recursive `extend`, the defined
environment variables, dedicated CLI flags, and repeatable generic
`--option KEY VALUE` overlays in this precedence order:

1. packaged defaults;
2. extended parents and the selected or discovered config;
3. environment variables explicitly defined by the specs;
4. CLI options and flags.

The CLI resolves configuration once and passes the resulting immutable
`BackstitchSettings` object into command and core code. Tests may construct or
replace that object and pass it directly. No command or downstream service
reimplements discovery or precedence.

The change also removes the filename-specific refresh configuration design.
Backstitch implicitly discovers only `.backstitch.toml` and a qualifying
`pyproject.toml`; `--config PATH` and `extend` may name any TOML file. Trusted
semantic workflows select the trusted checkout's `pyproject.toml` explicitly
and apply static runtime changes with `--option`.

## Requested Outcomes

- [x] Specify the canonical resolver owner, boundary, inputs, result, and
  precedence.
- [x] Specify repeatable `--option KEY VALUE`, including parsing, conflicts,
  failure behavior, and path semantics.
- [x] Preserve the existing implicit discovery names while allowing arbitrary
  TOML filenames through `--config` and `extend`.
- [x] Keep trusted semantic workflow configuration outside hostile target
  control without assigning security meaning to a filename.
- [x] Define dependency-ordered implementation slices and firing tests.
- [x] Remove the legacy refresh TOML file and, during implementation, remove
  its filename from active specs, tests, runtime code, workflows, and current
  user/implementation docs.

## Source Documents

- `docs/specs/02-backstitch-core.md` [SC-5]
- `docs/specs/03-backstitch-configuration.md` [CFG-2], [CFG-3], [CFG-4],
  [CFG-5], [CFG-6], [CFG-7], [CFG-8], [CFG-9]
- `docs/specs/06-semantic-gates.md` [SEM-4], [SEM-7], [SEM-9], [SEM-10]
- `docs/specs/07-verification-and-evidence-cases.md` [EVC-5], [EVC-5.1],
  [EVC-8.3], [EVC-10.1], [EVC-11], [EVC-12]
- `docs/implementation/02-repository-map.md`
- `docs/implementation/07-deterministic-semantic-gate.md`
- `docs/plans/2026-07-27-semantic-analysis-lifecycle-plan.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `../simplebroker/simplebroker/_constants.py`, especially
  `resolve_config(...)`
- `../simplebroker/README.md`, “One config path” and configuration snapshot
  guidance

The SimpleBroker comparison supplies one pattern, not an API to copy:
configuration is normalized through one helper and passed into operational
objects. Backstitch must not copy SimpleBroker's module-level environment
snapshot because Backstitch has command-specific discovery anchors and a
hostile-target/trusted-tool split.

## Spec Baseline

- Diff base: `main` at
  `66c84d83f8934cdd869b97ab23e28670d95773c7`.
- Plan type: implementation with spec revision.
- The governing specs already contain uncommitted semantic-gate work over that
  commit. The exact plan-authoring baselines are:
  - `docs/specs/02-backstitch-core.md`:
    `e375fd1f99acbc21508e5e5d29cb7f19c384e88d01c37ad5ae3b79bb323c46e4`
  - `docs/specs/03-backstitch-configuration.md`:
    `c346a5a4de805593b2e9e9e7a0573501ef513d01d806b5838b29f77f170b40c1`
  - `docs/specs/06-semantic-gates.md`:
    `fc71aa81448ae5bc4ae3b921c13d115940c73124fbd74ca7c2147930bd6c4258`
  - `docs/specs/07-verification-and-evidence-cases.md`:
    `192908c044c3d4c1119f131e9247c8986ad1773712bb7d8c7f5a0bbe7534daa5`
- This plan revises those specs. Implementation compliance is against the
  promotion baseline recorded after independent review and the
  spec-promotion slice, not against this pre-promotion baseline.

## Current Structure And Required Reading

Read these files before implementation:

- `backstitch/settings.py`
  - `load_settings(...)` currently owns defaults, discovery, `extend`, merge,
    path expansion, strict parsing, and provenance.
  - `_merge_config_layers(...)` has load-bearing special rules for
    `diagnostics.levels` and the `profile.code_roots` /
    `profile.test_roots` pair.
  - `_load_config_chain(...)` currently contains a filename-specific refresh
    validator that must be removed, not generalized.
  - `BackstitchSettings` is already the immutable typed result and carries
    config path and layer provenance.
- `backstitch/cli.py`
  - `_resolve_settings(...)` serves only some commands.
  - `analyze`, `eval`, `doctor`, `config`, and obligation paths call
    `load_settings(...)` separately.
  - profile roots, analyze model, and concurrency are applied after settings
    load in command-specific code.
  - global and per-command `--config` / `--no-config` spellings are merged in
    `main(...)`.
- `backstitch/alignment_eval.py`
  - four production-evaluation helpers resolve the same fixture configuration
    independently. The top-level evaluation owner must resolve once per
    fixture/context and pass the settings snapshot down.
- `backstitch/analysis_llm.py` and `backstitch/target_roots.py`
  - inspect where `LLM_MODEL` and `BACKSTITCH_WEFT_ROOT` are currently read.
    The canonical resolver must own their place in the precedence cascade
    without importing provider code for deterministic commands.
- `pyproject.toml`
  - contains the repository's qualifying `[tool.backstitch]` config.
    `analyze.cache_mode = "require"` is the default zero-call posture.
    `[tool.backstitch.verify]` currently contains only `enabled = false`;
    trusted runtime enablement therefore needs the dormant complete verifier
    configuration to live here before a CLI overlay may enable it.
- `.github/workflows/semantic-refresh.yml` and
  `.github/workflows/semantic-pr-report.yml`
  - both run trusted code and configuration.
  - the pull-request workflow checks out the hostile target separately and
    must keep using an explicit path below `TOOL_ROOT`.
- `tests/test_settings.py`, `tests/test_semantic_settings.py`,
  `tests/test_cli.py`, `tests/test_semantic_eval.py`, and
  `tests/test_release_workflow.py`
  - these are the primary unit and workflow-contract test owners.

Comprehension gate before editing:

1. Which function currently reads each configuration source, and which CLI
   paths apply overrides after typed parsing?
2. Which settings have special merge or identity rules that a generic
   dictionary update would bypass?
3. Why must the pull-request workflow select config from `TOOL_ROOT` even
   though the command's `--repo-root` points to `TARGET_ROOT`?
4. Can a deterministic command resolve settings without importing `llm` or
   reading provider credentials?

If any answer is unclear, stop before changing the resolver.

## Invariants And Constraints

1. **One resolution owner.** `backstitch.settings.resolve_config(...)` is the
   only public helper that assembles effective Backstitch settings. Private
   helpers may discover, read, merge, expand, and parse, but no second public
   loader or command-local precedence path may remain.
2. **Resolve once, pass the snapshot.** Each CLI invocation resolves at most
   once. Command handlers and core services receive `BackstitchSettings`;
   they do not reread repository config or Backstitch environment overrides.
   Evaluation code resolves once per independently rooted fixture/context and
   passes the result through that operation.
3. **Tests inject after the boundary.** Unit tests below configuration
   resolution use a real `BackstitchSettings` object, commonly constructed
   with dataclass defaults or `replace(...)`. Resolver and public-CLI tests
   exercise the real filesystem, TOML parser, environment mapping, and CLI
   parser.
4. **Precedence is singular.** Packaged defaults < extended/selected config <
   defined environment < CLI. Dedicated flags and generic `--option` values
   enter the same final CLI layer.
5. **Discovery and selection stay distinct.** Implicit discovery examines only
   `.backstitch.toml` and qualifying `pyproject.toml`. Explicit `--config` and
   `extend` accept arbitrary TOML filenames. No basename has special schema or
   trust semantics.
6. **Strict schema remains authoritative.** Generic options do not bypass
   unknown-key, type, range, cross-field, model-identity, provider-composition,
   path-containment, or budget validation.
7. **No partial side effects.** A malformed option or invalid effective config
   exits `2` before snapshot capture, cache/lock mutation, adapter
   construction, provider traffic, or output publication.
8. **No provider coupling in deterministic resolution.** Resolution may apply
   the specified `LLM_MODEL` string, but it does not import `llm`, resolve the
   provider's own default model, read credentials, or make network calls.
9. **Existing config merge rules survive.** Array replacement,
   `diagnostics.levels` ordering, `extend_exclude`, profile root-pair reset,
   per-file path anchoring, and final containment checks retain their current
   specified semantics.
10. **Trusted PR inputs remain data.** The trusted checkout supplies the
    executable, explicit config path, prompt, provider controls, option keys
    and values, cache root, and output root. No option key or value is formed
    from pull-request payload fields or target repository bytes.
11. **Dedicated flags remain supported.** This plan does not remove ergonomic
    flags such as `--model`, `--concurrency`, `--profile`, or root flags.
12. **No false security from filenames.** Trust follows checkout identity,
    explicit source path, static workflow text, and validation. It never
    follows a filename.
13. **Migrate stale tests; do not restore the file.** The removed refresh TOML
    is not a compatibility fixture. Any test that reads it, copies it, checks
    whether it is tracked/ignored, or expects its special validation is stale
    and must be rewritten against supported config selection and
    `--option`. Restoring the file to make those tests pass is a regression.
14. **Dirty-tree discipline.** Touch only files named by a slice. Do not
    reformat or absorb unrelated uncommitted semantic-gate work.

Fatal failures are CLI syntax errors, unknown or structural option keys,
duplicate/conflicting CLI assignments, invalid typed values, invalid final
settings, and unreadable or unstable config. Existing cache restore and report
artifact behavior remains governed by [SEM-9]; this plan does not reclassify
those workflow failures.

## Canonical Design

### Resolution request and result

`resolve_config(...)` accepts explicit, testable inputs:

- discovery anchor;
- optional explicit config path;
- whether repository config is enabled;
- an environment mapping, defaulting to the process environment only at the
  invocation boundary;
- ordered generic CLI option pairs;
- normalized values from dedicated CLI flags.

It returns one immutable `BackstitchSettings` snapshot with effective values,
selected path, layer identities, diagnostic rule origins, and enough
provenance for `config show`.

Do not add a mutable global settings singleton. Do not make every core function
accept raw mappings. Callers below the resolution boundary receive the typed
snapshot.

### Generic CLI grammar

The repeatable grammar is:

```text
backstitch [--config PATH | --no-config] \
  [--option KEY VALUE]... COMMAND ...
```

Config-consuming commands also accept the same option after the subcommand,
consistent with their current `--config` / `--no-config` spellings.

- `KEY` is a canonical dotted path in standalone `.backstitch.toml` shape,
  such as `analyze.cache_mode`, `verify.enabled`, or
  `diagnostics.fail_on`. It never includes the `tool.backstitch` prefix. Split
  it on literal dots with no quoted segments or escaping; each segment must be
  nonempty. Map entries whose names contain dots, such as individual
  `lint.per-file-ignores` or `lint.per-section-ignores` entries, are therefore
  not addressable through `--option`; attempts stop at a non-leaf table and
  exit `2`.
- `VALUE` is one shell argument and may not contain NUL, CR, or LF. Parse it by
  constructing exactly one synthetic TOML assignment,
  `value = <argument>`. If that parse succeeds, the synthetic document must
  contain exactly the one top-level `value` key; the parsed value itself may
  be a scalar, array, or inline table. Any additional top-level key/table is
  exit `2`. If the one-assignment TOML parse fails, treat the entire argument
  as a bare string. Thus `read-write` is a string, `true` is a boolean, `3` is
  an integer, and `'["error", "warning"]'` is an array. Quote strings that
  would otherwise parse as another TOML type; use `""` for the empty string.
- The key must resolve to a known, runtime-consulted configurable leaf.
  Unknown keys, non-table traversal, assignments to a whole table, and
  reserved/non-consulted leaves such as `packets.output` are exit `2`.
- Load-time structure keys `extend`, `allow_unknown_keys`, and
  `defaults.schema_version` are not runtime-overridable and are exit `2`.
- Repeating the same generic key is exit `2`. Supplying a dedicated flag and a
  generic option for the same canonical key is also exit `2`, even when the
  values are equal. This avoids a second within-CLI precedence language.
- Each accepted option contributes to the one final CLI layer. Existing
  key-specific merge and pair-reset semantics apply to that layer.
- CLI-supplied artifact paths are relative to the process working directory.
  Scan roots retain their existing target-repository-relative meaning.
  CLI values never inherit the selected config file's directory merely
  because a config was also selected.
- `--no-config` with `--option` is valid: the cascade is packaged defaults,
  defined environment, CLI.
- `config show` applies and renders the same effective options used at runtime.
  `config path` resolves and validates the same request, then prints only the
  selected path. `--config`, `--no-config`, and `--option` are all rejected
  when supplied globally to `summarize-analysis`, `guide`, or
  `cache cleanup-lock`, because those commands do not consume configuration.

### Dedicated flags and environment

The CLI adapter maps each dedicated setting flag to its canonical key before
resolution. The canonical resolver applies the defined environment variables,
then the normalized CLI layer, then performs final typed and relational
validation.

The closed dedicated-setting map is:

| CLI flag | Canonical key | Commands |
|---|---|---|
| `--profile` | `profile.name` | `check`, `packets` |
| `--spec-root` | `profile.spec_roots` | `check`, `packets` |
| `--plan-root` | `profile.plan_roots` | `check`, `packets` |
| `--code-root` | `profile.code_roots` | `check`, `packets` |
| `--test-root` | `profile.test_roots` | `check`, `packets` |
| `--format` | `check.format` | `check` only |
| `--output` | `check.output` | `check` only |
| `--warnings-as-errors` / `--no-warnings-as-errors` | `check.warnings_as_errors` | `check` |
| `--model` | `analyze.model` | `analyze`, `doctor` |
| `--concurrency` | `analyze.concurrency` | `analyze` |

All other command flags are operational arguments, not setting aliases. In
particular, `--repo-root`, non-check `--format`/`--output`, analyze report and
packet paths, packet `--output`, obligation `--limit`, and config selection
controls never conflict with a generic setting key.

`LLM_MODEL` and `BACKSTITCH_WEFT_ROOT` remain the only environment inputs named
by [CFG-5]. This plan does not invent a generic environment namespace.
Provider-library default-model selection may occur later in an explicitly
provider-touching command when the resolved model remains blank; it is not a
second Backstitch configuration cascade.

### Trusted semantic workflows

The repository keeps one qualifying `[tool.backstitch]` configuration in
`pyproject.toml`. It stores the exact dormant complete verifier descriptor
specified in [EVC-5], [CFG-6] §6.7, and the proposed [SEM-9.1], with
`verify.enabled = false`. It retains `analyze.cache_mode = "require"` plus
`verify.cache_mode = "require"` as the zero-call defaults.

The verifier has two valid disabled forms:

1. minimal disabled: exactly `enabled = false`;
2. dormant complete: `enabled = false` plus every required enabled base-table
   key, the provider table required by `provider_source` when applicable, and
   an optional but complete `verify.eval` table.

No partial dormant form is valid. Dormant fields undergo the same strict
unknown-key, type, range, nonblank, provider-identity, cost, path, and internal
cross-field validation as enabled fields, but disabled verification performs
no adapter construction, qualification-artifact load, cache access, or
provider call. CLI/environment layers are applied to the merged raw
configuration before this final shape validation. Therefore setting
`verify.enabled = true` can activate only a complete dormant descriptor; it
cannot make the minimal disabled form complete.

Trusted refresh commands explicitly select the trusted checkout's
`pyproject.toml` and pass only literal workflow-owned overlays:

```text
--option analyze.cache_mode read-write
--option verify.enabled true
--option verify.cache_mode read-write
```

The exact set may change only through spec/plan review if another setting is
proven necessary. The pull-request workflow uses
`--config "${TOOL_ROOT}/pyproject.toml"` while analyzing
`--repo-root "${TARGET_ROOT}"`. It must not discover target configuration or
interpolate event payload or target content into `--option`.

## Rollback And Rollout

There is no storage migration and no one-way door. Configuration files remain
TOML, cache keys and objects do not change, and existing dedicated flags remain
accepted.

Roll out in this order:

1. promote the reviewed spec delta;
2. land the canonical resolver and CLI behavior with firing tests;
3. move the dormant complete verifier descriptor into `pyproject.toml`;
4. update trusted workflows and their static contract tests in the same slice;
5. update current docs and close mappings/backlinks;
6. run the complete non-live and self-corpus gates;
7. after landing, manually dispatch the trusted refresh only with explicit
   provider-spend authorization.

If the resolver or workflow migration must be rolled back, disable the trusted
refresh and PR report workflows and retain the default `require` posture.
Do not restore a special refresh filename as a rollback mechanism. Revert the
generic option wiring, canonical resolver call-site migration, and workflow
commands as one compatibility unit; existing dedicated flags remain the
fallback local interface.

Post-rollout success signals:

- `config show` and runtime commands report/use identical effective values;
- each config-consuming invocation resolves once;
- static workflow tests prove the trusted config path and literal option set;
- a trusted refresh reuses hits and calls the provider only for misses;
- default zero-call invocations still fail closed on a miss;
- no active spec, test, runtime module, workflow, README, implementation doc,
  or ignore rule depends on the removed refresh filename.

## Proposed Spec Delta

Promotion strategy: **A**, adding new active subsections without implementation
mapping blocks. The spec-promotion slice adds the exact temporary
`_Traceability: ignore SPEC_SECTION_UNMAPPED_` marker shown below to
[SC-5.1], [CFG-5.1], and [SEM-9.1]. The implementation slice that adds each
mapping and reciprocal backlink removes that section's marker atomically.
[EVC-12.2] is covered by spec 07's existing exact per-file suppression during
its implementation window. No production code may cite `[SC-5.1]`,
`[CFG-5.1]`, `[SEM-9.1]`, or `[EVC-12.2]` before that atomic mapping slice.

### `docs/specs/02-backstitch-core.md` [SC-5.1]

Insert the following immediately after [SC-5]'s `_Implementation mapping_`
block and before the next `##` heading:

~~~~markdown
### 5.1 Configuration Inputs [SC-5.1]

_Traceability: ignore SPEC_SECTION_UNMAPPED_

Every command that consumes Backstitch settings accepts the configuration
selection and repeatable generic override grammar defined in [CFG-5.1]:

```bash
backstitch --config PATH --option KEY VALUE <command> ...
backstitch --no-config --option KEY VALUE <command> ...
```

`--config PATH` may name any TOML filename. It is explicit selection, not an
additional discovery convention. `--config`, `--no-config`, and `--option`
must all be rejected rather than silently ignored by commands that do not
consume configuration. Invalid option syntax or an invalid effective
configuration is exit `2` before command side effects.
~~~~

### `docs/specs/03-backstitch-configuration.md` [CFG-3], [CFG-5.1],
[CFG-7], [CFG-8], [CFG-9], plus §6.5 and §6.7

Add to [CFG-3] after the explicit-selection sentence:

```markdown
Implicit discovery recognizes only `.backstitch.toml` and a `pyproject.toml`
that contains `[tool.backstitch]`. An explicit `--config PATH` may name any
TOML filename. An `extend` value may also name any TOML filename. Neither
mechanism adds that basename to implicit discovery or gives the basename
special validation or trust semantics.
```

Insert after [CFG-5]'s implementation mapping:

~~~~markdown
### 5.1 Canonical Resolution And Generic CLI Overlays [CFG-5.1]

_Traceability: ignore SPEC_SECTION_UNMAPPED_

`backstitch.settings.resolve_config(...)` is the sole public owner for
assembling effective Backstitch settings. It accepts the command's discovery
anchor, explicit-selection state, an environment mapping, repeatable generic
CLI option pairs, and normalized dedicated CLI values. It returns one
immutable `BackstitchSettings` snapshot including selected-path and layer
provenance.

Each invocation resolves settings once and passes that snapshot into command
and core code. Downstream code must not rediscover files, reread Backstitch
environment overrides, or apply another precedence rule. Tests below the
resolution boundary may construct or replace a `BackstitchSettings` value and
pass it directly; resolver and public-CLI tests use the real filesystem, TOML
parser, environment mapping, and argument parser.

The repeatable CLI form is `--option KEY VALUE`. `KEY` is a known,
runtime-consulted dotted leaf path in standalone `.backstitch.toml` shape and
never includes `tool.backstitch`. Split `KEY` on literal dots with no quoted
segments or escaping; every segment is nonempty. Individual map entries whose
names contain dots, including `lint.per-file-ignores` and
`lint.per-section-ignores` entries, are not addressable; traversal stops at a
non-leaf table and is exit `2`. Reserved/non-consulted leaves such as
`packets.output` are not runtime-overridable.

`VALUE` is one argument and may not contain NUL, CR, or LF. Parse it by
constructing exactly one synthetic TOML assignment, `value = <argument>`. If
that parse succeeds, the synthetic document must contain exactly one
top-level key named `value`; that value may itself be a scalar, array, or
inline table. An additional top-level key or table is exit `2`. If the
one-assignment parse fails, treat the entire argument as a bare string. Quote
a string that would otherwise parse as a boolean, number, date, array, or
inline table. The empty string is `""`.

Generic options and dedicated setting flags form one final CLI layer after the
defined environment layer. Existing key-specific merge and paired-root rules
apply. A repeated generic key, an assignment to an unknown/non-leaf/reserved
key, or a dedicated flag plus generic option for the same canonical key is
exit `2`. `extend`, `allow_unknown_keys`, and `defaults.schema_version` are
load-time structure and cannot be set by `--option`.

The complete dedicated-setting alias map is:

| CLI flag | Canonical key | Commands |
|---|---|---|
| `--profile` | `profile.name` | `check`, `packets` |
| `--spec-root` | `profile.spec_roots` | `check`, `packets` |
| `--plan-root` | `profile.plan_roots` | `check`, `packets` |
| `--code-root` | `profile.code_roots` | `check`, `packets` |
| `--test-root` | `profile.test_roots` | `check`, `packets` |
| `--format` | `check.format` | `check` only |
| `--output` | `check.output` | `check` only |
| `--warnings-as-errors` / `--no-warnings-as-errors` | `check.warnings_as_errors` | `check` |
| `--model` | `analyze.model` | `analyze`, `doctor` |
| `--concurrency` | `analyze.concurrency` | `analyze` |

All other flags are operational arguments rather than setting aliases.
`--repo-root`, non-check `--format`/`--output`, analyze report and packet
paths, packet `--output`, obligation `--limit`, and config selection controls
therefore never conflict with a generic setting key.

CLI artifact paths are relative to the process working directory. Scan roots
retain their target-repository-relative meaning. CLI values never acquire the
selected config file's directory as their base. `--no-config` and `--option`
may be combined, yielding defaults, then defined environment, then CLI.

`config show` applies and renders the same effective option layer as runtime
commands. `config path` resolves and validates the same request, then prints
only the selected path. `summarize-analysis`, `guide`, and
`cache cleanup-lock` reject global `--config`, `--no-config`, and `--option`
because they do not consume configuration.

Configuration resolution performs no provider import, credential read,
network call, snapshot capture, cache mutation, or output publication.
Malformed options and invalid final settings are exit `2` before those
effects. Provider-library default-model selection may occur later only in an
explicitly provider-touching command when the resolved model is blank; it is
not a second Backstitch configuration source.
~~~~

Replace the final filename-specific paragraph of §6.5 with:

```markdown
When `extend` names `pyproject.toml`, the loader selects the target file's
`[tool.backstitch]` table before merging. Other TOML filenames contribute
their top-level tables. `extend` filenames are otherwise unrestricted and
carry no special validation or trust semantics.
```

Replace §6.7's first two sentences with:

```markdown
Packaged defaults contain exactly `enabled = false`. A disabled verifier has
one of two strict shapes: minimal disabled contains exactly
`enabled = false`; dormant complete contains `enabled = false` plus every
enabled base-table key required by [EVC-5], the provider table required by
`provider_source` when applicable, and an optional but complete
`[verify.eval]` table. Partial dormant tables are invalid. Dormant fields
receive the same unknown-key, type, range, nonblank, provider-identity, cost,
path, and internal cross-field validation as enabled fields, while disabled
verification performs no adapter construction, qualification-artifact load,
cache access, or provider call. CLI layers apply before final shape
validation, so `--option verify.enabled true` can activate a dormant complete
table but makes a minimal disabled table fail for missing required keys.
```

Add these forms to [CFG-7]'s CLI block:

```bash
backstitch --option KEY VALUE <command> ...
backstitch <command> --option KEY VALUE ...
```

Add after that block:

```markdown
`--option` is repeatable and follows [CFG-5.1]. `config show` applies and
renders the same final option layer as runtime commands. `config path` resolves
and validates the same request, then prints only the selected path. A command
that does not consume configuration rejects all configuration controls.
```

Delete [CFG-8]'s filename-specific refresh-file failure bullet. Add:

```markdown
- `--option` has the wrong arity, contains NUL/CR/LF, has a malformed dotted
  key, names an unknown, non-leaf, reserved/non-consulted, or load-time key,
  repeats a key, conflicts with a dedicated CLI flag, parses as more than one
  synthetic TOML assignment, or produces a value that fails the existing
  type, range, identity, containment, or cross-field validation
```

Add to [CFG-9]:

```markdown
- firing public-CLI tests for generic scalar, boolean, numeric, array, inline,
  quoted-ambiguous, and empty-string values; repeated distinct keys; duplicate
  keys; NUL/CR/LF and multi-assignment rejection; unknown, non-leaf,
  reserved/non-consulted, and load-time keys; empty key segments, quoted key
  segments, and attempts to address dotted map-entry names; every
  dedicated-setting alias conflict; every named operational non-alias; options
  before and after the subcommand; `--no-config`; and `config show`
- precedence tests proving CLI over defined environment over selected config
  over extended parents over packaged defaults, with all config-consuming
  commands using the same resolver
- injection tests proving command/core code accepts a resolved
  `BackstitchSettings` snapshot without reading repository config or
  Backstitch environment overrides again
- explicit-selection and `extend` tests using arbitrary TOML filenames, plus
  discovery tests proving those filenames are not implicitly discovered
- verifier-shape tests for minimal disabled, dormant complete, rejected
  partial dormant, CLI activation of dormant complete, and rejected CLI
  activation of minimal disabled
```

### `docs/specs/06-semantic-gates.md` [SEM-9], [SEM-9.1]

In [SEM-9], replace only these two sentences:

```markdown
Backstitch's applied configuration keeps `require` as the explicit zero-call
profile. `.backstitch-refresh.toml` selects `read-write` for bounded update
runs.
```

with:

```markdown
Backstitch's applied configuration keeps `require` as the explicit zero-call
profile. Trusted bounded updates use the explicit config selection and static
runtime overlays in [SEM-9.1].
```

Keep the following clean-checkout availability sentence unchanged.

Replace the paragraph beginning `All nonsecret controls live in
pyproject.toml` with:

```markdown
All persistent nonsecret controls live in `pyproject.toml`. Runtime-only
bounded changes use [CFG-5.1] through static trusted CLI options.
Output/report paths remain explicit CLI arguments. No filename is reserved
for refresh behavior or receives special validation.
```

Insert the following immediately after [SEM-9]'s `_Implementation mapping_`
block and before the next `##` heading:

~~~~markdown
### 9.1 Trusted Runtime Overrides [SEM-9.1]

_Traceability: ignore SPEC_SECTION_UNMAPPED_

Backstitch's qualifying `[tool.backstitch]` configuration retains `require` as
the explicit zero-call default for analyzer and verifier cache reads. It stores
this exact dormant complete verifier descriptor:

```toml
[tool.backstitch.verify]
enabled = false
provider_source = "analyze"
concurrency = 1
cache_path = ".backstitch/semantic-cache"
cache_mode = "require"
search_epochs = ["1"]
json_mode = "require"
temperature = 0.0
seed = 42
max_tokens = 512
required_verdicts = 1
minimum_support_score = 0.90
indeterminate = "report"
maximum_provider_calls = 100
maximum_prompt_bytes = 1000000
lock_wait_timeout_seconds = 300
maximum_runtime_seconds = 1800
maximum_estimated_cost_microusd = 1000000

[tool.backstitch.verify.eval]
mode = "report"
qualification_corpus = ""
qualification_corpus_sha256 = ""
qualification_report = ""
qualification_report_sha256 = ""
trials = 2
interval_method = "wilson"
confidence_level = 0.95
minimum_positive_units = 1
minimum_negative_units = 1
minimum_evidence_sufficiency_rate = 0.0
minimum_conditional_precision = 0.0
minimum_conditional_recall = 0.0
minimum_end_to_end_recall = 0.0
minimum_recall_lower_bound = 0.0
maximum_false_positive_rate = 1.0
maximum_false_positive_upper_bound = 1.0
maximum_indeterminate_rate = 1.0
maximum_uncached_flip_rate = 1.0
require_all_critical = false
```

A trusted bounded update explicitly selects that config and uses [CFG-5.1]
with exactly these literal workflow-owned overlays:

```text
--option analyze.cache_mode read-write
--option verify.enabled true
--option verify.cache_mode read-write
```

There is no implicit or reserved refresh-config filename. Trust comes from the
exact trusted checkout, explicit config path, static workflow-owned option
keys and values, and normal strict validation.

The pull-request report workflow selects
`${TOOL_ROOT}/pyproject.toml` while analyzing `${TARGET_ROOT}` and uses the
same three literal overlays. Neither pull-request event data nor
target-repository bytes may supply a config path, option key, or option value.
Target configuration is not discovered. Any change to the trusted option set
is a reviewed workflow/config contract change. The default zero-call path,
honest cache-miss availability failure, cache authority, provider-call
ceilings, report-only authority, and hostile-input restrictions otherwise
remain unchanged.
~~~~

### `docs/specs/07-verification-and-evidence-cases.md` [EVC-5],
[EVC-5.1], [EVC-8.3], [EVC-10.1], [EVC-11], [EVC-12.2]

Replace [EVC-5]'s disabled-form paragraph with:

```markdown
When disabled, Backstitch makes no verify call, reads or writes no verifier
cache object, and projects no independent verification context. Two disabled
shapes are valid. Minimal disabled contains exactly `enabled = false`.
Dormant complete contains `enabled = false` plus every enabled base-table key
shown above, the provider table required by `provider_source` when applicable,
and an optional but complete `verify.eval` table. Partial dormant forms are
invalid. Dormant fields receive the same unknown-key, type, range, nonblank,
provider-identity, cost, path, and internal cross-field validation as enabled
fields, but disabled state performs no adapter construction,
qualification-artifact load, cache access, or provider call.

Config/environment/CLI layers apply before final verify-shape validation.
Therefore `--option verify.enabled true` activates a dormant complete
descriptor and applies ordinary enabled validation, while applying it to the
minimal disabled form is exit `2` for missing required fields.
`provider_source` is exactly `analyze` or `override` in enabled and dormant
complete forms.
```

In each [EVC-5.1] analyze grammar, add this line immediately after the existing
`[--config PATH | --no-config]` line:

```text
  [--option KEY VALUE]...
```

Add after [EVC-5.1]'s grammar block:

```markdown
The configuration selection and override grammar composes with [CFG-5.1].
Configuration controls may appear globally before `analyze` or in the
positions shown here, but may not assign the same generic key twice or combine
a generic key with its dedicated alias.
```

Add after [EVC-8.3]'s exact grammar block:

```markdown
Every grammar above for a command that consumes configuration composes with
[CFG-5.1]'s global or command-local
`[--config PATH | --no-config] [--option KEY VALUE]...` grammar. This includes
`obligation`; `guide`, conditional `mcp`, and other commands consume
configuration only where their own governing sections explicitly say so.
```

In each duplicate [EVC-8.3] analyze grammar, also add this line immediately
after the existing `[--config PATH | --no-config]` line:

```text
  [--option KEY VALUE]...
```

In [EVC-10.1]'s promoting `backstitch eval` grammar, add this line immediately
after `[--config PATH | --no-config]`:

```text
  [--option KEY VALUE]...
```

Add after that grammar:

```markdown
The evaluation command's configuration controls compose with [CFG-5.1].
Trusted refresh may therefore activate a dormant complete verifier and change
analyzer/verifier cache modes through the exact static options in [SEM-9.1].
```

Add to [EVC-11]:

```markdown
- secret-bearing hostile-target workflows obtain generic CLI option keys and
  values only from static trusted workflow text; event payload fields and
  target bytes cannot select or construct configuration
```

Insert after [EVC-12.1]:

```markdown
### 12.2 Canonical Configuration Resolution [EVC-12.2]

Firing tests must prove the full defaults/config/environment/CLI cascade
through the public CLI and the canonical resolver. They cover every
`--option` value family and error family in [CFG-5.1], the exact
dedicated-setting alias map, operational non-aliases, minimal and dormant
disabled verifier shapes, arbitrary explicit and extended TOML filenames,
command-specific anchors, single resolution per invocation, direct
typed-settings injection below the boundary, and rejection before
provider/cache/output effects.

Workflow contract tests must prove that trusted refresh and hostile-target PR
analysis explicitly select the trusted checkout's `pyproject.toml`, use the
exact reviewed literal options from [SEM-9.1], and never derive config or
option text from event payload or target repository data. Tests use real
temporary files, TOML parsing, environment mappings, CLI parsing, and command
dispatch. They must not mock the canonical resolver, config discovery,
`extend`, settings validation, or the trusted/target path split.
```

Each touched spec receives a `## Related Plans` backlink to this plan.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Promotion Baseline

- Promotion diff base: `main` at
  `66c84d83f8934cdd869b97ab23e28670d95773c7`.
- Promoted in the worktree after Claude cross-model review round 3 PASS:
  - `docs/specs/02-backstitch-core.md`:
    `73cb94bbe5d88940e92f82eba63753ec549694c32cab6b451c0f9111f3acbaac`
  - `docs/specs/03-backstitch-configuration.md`:
    `07e1440bd90d7d25bb3d6fea5dcc3967167721503ce998aab63634ecc5c24853`
  - `docs/specs/06-semantic-gates.md`:
    `3148c80cda46417d742128bdce238bb55d08d3a798da15400447d03f7ef27622`
  - `docs/specs/07-verification-and-evidence-cases.md`:
    `0bb8380ce14faf5bd661f03773b91f84addc3afb6b6673e58ae9645c56391602`
- Promotion verification:
  - `uv run backstitch check --repo-root .`:
    exit `0`, 120 sections, 245 mappings, 344 code refs, 697 edges,
    zero errors, warnings, and infos.
  - `uv run backstitch check --repo-root . --show-suppressions`:
    exit `0`, the same zero-issue summary, 207 auditable suppressions; the
    three new unmapped sections are suppressed only by their exact
    `inline_spec` markers.
- Implementation compliance begins from these promoted bytes. If a governing
  spec changes during implementation, record a deviation before continuing.

## Dependency-Ordered Tasks

### Spec-Promotion Slice: Promote The Reviewed Contract

Outcome: apply the exact reviewed delta above to the four active specs and add
their reciprocal `## Related Plans` backlinks.

Files to touch:

- `docs/specs/02-backstitch-core.md`
- `docs/specs/03-backstitch-configuration.md`
- `docs/specs/06-semantic-gates.md`
- `docs/specs/07-verification-and-evidence-cases.md`
- this plan's promotion-baseline and review-log sections

Verification:

- exact-section inspection against `## Proposed Spec Delta`;
- `rg` proves no active spec contains the removed refresh filename;
- `uv run backstitch check --repo-root .` remains exit `0` with zero errors
  and zero warnings;
- `uv run backstitch check --repo-root . --show-suppressions` remains
  auditable.

Done signal: promoted hashes are recorded and no production code cites the new
sections. The three temporary section-scoped markers are present and no
broader spec-file suppression was added.

Stop and re-plan if promotion requires changing another normative contract,
adding a config discovery name, or weakening the trusted/target split.

### Slice 1: Build The Canonical Resolver With Failing Tests First

Outcome: replace the public `load_settings(...)` surface with
`resolve_config(...)`; add typed request/override records only where they make
the boundary explicit; apply defined environment and CLI layers before final
validation.

Files to touch:

- `backstitch/settings.py`
- `backstitch/analysis_llm.py`
- `backstitch/target_roots.py`
- `tests/test_settings.py`
- `tests/test_semantic_settings.py`
- `tests/test_obligation_settings.py`
- `tests/test_obligation_runtime.py`
- `tests/test_semantic_analysis.py`
- `tests/test_semantic_policy.py`
- `tests/test_phase_c_eval.py`
- `tests/test_review_remediation.py`
- `tests/test_evidence_spike_boundary_pins.py`
- `tests/acceptance/conftest.py`
- `tests/acceptance/test_probe_semantic_replay.py`

The listed test-file edits include the mechanical public-helper rename. If
another test imports `load_settings`, add only that mechanical call-site
migration to this slice and record it in the slice evidence; do not retain a
public compatibility alias.

Required behavior:

- parse and validate generic dotted leaf assignments;
- implement the exact single-assignment TOML-or-bare-string value parser;
- implement minimal-disabled and dormant-complete verifier shapes before
  deleting the old filename validator that currently contains the only code
  copy of the verifier values;
- preserve existing merge, path-source, model identity, composition, budget,
  and containment rules;
- remove the filename-specific refresh validator;
- expose one immutable resolved snapshot with provenance;
- keep resolution provider-free.

Use red-green TDD. The first failing tests must cover precedence, structural
key rejection, duplicate/conflict rejection, arbitrary filenames, and
side-effect-free failure.

Done signal: focused resolver tests pass, `rg` finds no production
`load_settings(...)` call, and no replacement resolver exists outside
`backstitch/settings.py`.

Stop and re-plan if a generic option requires a second schema, bypasses
`_parse_settings(...)`, changes cache identity semantics, or needs a new
dependency.

### Slice 2: Resolve Once At Invocation Boundaries And Pass Settings

Outcome: the CLI and evaluation entry points resolve once, then pass
`BackstitchSettings` into command/core code. Dedicated flags enter the same CLI
layer as generic options.

Files to touch:

- `backstitch/cli.py`
- `backstitch/alignment_eval.py`
- command/core call sites that currently read settings implicitly
- `tests/test_cli.py`
- `tests/test_phase_c_eval.py`
- affected command tests

Required behavior:

- support `--option KEY VALUE` before and after config-consuming subcommands;
- reject generic/dedicated conflicts and options on non-config commands;
- make `config show` use the exact runtime resolver;
- make `config path` use resolver provenance;
- inject settings directly in command/core unit tests;
- preserve lazy provider imports and command-specific discovery anchors.

Add the [SC-5.1] and [CFG-5.1] implementation mappings and reciprocal code
backlinks atomically in this slice, and remove those two temporary
`SPEC_SECTION_UNMAPPED` markers in the same change.

Done signal: a resolution-call counter at the public boundary proves one call
per invocation; lower-layer injection tests pass without a config file or
environment patch.

Stop and re-plan if command handlers still need ambient Backstitch config, if
main dispatch requires provider imports, or if the change starts redesigning
unrelated command arguments.

### Slice 3: Migrate Repository And Trusted Workflow Configuration

Outcome: keep the full disabled verifier descriptor in `pyproject.toml`;
replace refresh-file selection with explicit trusted config plus literal CLI
options; remove every active dependency on the old filename.

Files to touch:

- `pyproject.toml`
- `.github/workflows/semantic-refresh.yml`
- `.github/workflows/semantic-pr-report.yml`
- `tests/test_release_workflow.py`
- `tests/test_semantic_eval.py`
- `tests/test_semantic_settings.py`
- `.gitignore` if it contains a filename-specific rule

Required behavior:

- transcribe the exact dormant verifier TOML from promoted [SEM-9.1], not from
  the deleted file or memory;
- default analyzer and verifier cache modes remain `require`;
- verifier remains disabled unless a trusted invocation sets
  `verify.enabled`;
- workflow option keys/values are literal trusted YAML;
- PR analysis selects `${TOOL_ROOT}/pyproject.toml` while reading
  `${TARGET_ROOT}`;
- no target or event value is interpolated into `--config` or `--option`;
- no test asserts that a removed filename is absent; tests assert supported
  behavior and trusted path/option ownership.
- stale tests must be migrated in this slice; the deleted file must not be
  restored as test data or as a test-suite compatibility shortcut.

Add [SEM-9.1] and [EVC-12.2] mappings/backlinks atomically with their
production/test owners, and remove [SEM-9.1]'s temporary
`SPEC_SECTION_UNMAPPED` marker in the same change.

Done signal: workflow contract tests pass and targeted `rg` finds no old
filename in active source, tests, workflows, README, implementation docs, or
specs. Historical plans are records and are not rewritten by this slice.

Stop and re-plan if enabling verification requires a second config file, a
workflow-generated TOML file, target-controlled input, or any relaxation of
the existing report-only boundary. Also stop if any test can pass only by
restoring the deleted refresh file; that indicates the supported replacement
contract or fixture setup is still incomplete.

### Slice 4: Documentation And Traceability Reconciliation

Outcome: document the canonical resolver and current lifecycle, close all
mapping/backlink debt, and remove stale user guidance.

Files to touch:

- `README.md`
- `docs/implementation/02-repository-map.md`
- `docs/implementation/07-deterministic-semantic-gate.md`
- `docs/plans/README.md`
- the four governing specs
- this plan
- `docs/lessons.md` only if implementation exposes a reusable correction not
  already captured by the repository planning guidance

Required documentation:

- explain why Backstitch has one invocation-scoped resolver;
- show the precedence cascade and repeatable CLI form;
- show zero-call default and trusted read-write examples;
- preserve the hostile-target/trusted-tool distinction;
- state that arbitrary explicit/extended filenames do not become discovery
  names.

Done signal: spec-plan-implementation-code-test traceability is closed; no
temporary inline suppression is needed.

Stop and re-plan if documentation would need to claim a second supported
configuration API or a stronger semantic workflow authority than [SEM-9].

### Slice 5: Final Verification And Independent Implementation Review

Run in sequence:

```bash
uv run pytest -q tests/test_settings.py tests/test_semantic_settings.py
uv run pytest -q tests/test_cli.py tests/test_semantic_eval.py
uv run pytest -q tests/test_release_workflow.py tests/test_phase_c_eval.py
uv run pytest -q tests/acceptance
uv run pytest -q -m "not live_llm and not performance"
uv run ruff check .
uv run ruff format --check .
uv run mypy backstitch
uv run backstitch check --repo-root .
uv run backstitch check --repo-root . --show-suppressions
git diff --check
```

Then run an independent implementation review against the promoted spec,
plan, code, tests, workflow YAML, and implementation docs. Address every
finding or record a reasoned disposition in the append-only review log.

Done signal: all commands pass; the default self-corpus invocation exits `0`
with zero errors and zero warnings; suppressions are auditable; the review has
no open P1/P2 finding; the slice is committed only when the user authorizes
landing.

## Testing Plan

The contract matrix must include:

| Contract | Required proof |
|---|---|
| Precedence | One key fires at every layer; CLI > env > selected child > extended parent > packaged default |
| Discovery | Only `.backstitch.toml` and qualifying `pyproject.toml` are implicit |
| Explicit names | Arbitrarily named TOML works through `--config` and `extend` but is not discovered |
| Generic values | Bare string, quoted ambiguous string, bool, int, float, array, inline value, and empty string |
| Key errors | malformed/empty/quoted segments, dotted map-entry names, unknown, non-leaf, structural, duplicate, and dedicated-flag conflict |
| Path sources | config-relative file paths, CWD-relative CLI artifact paths, target-relative scan roots |
| Cross-field validation | model/revision, verifier composition, profile roots, budgets, and enabled verifier completeness |
| Command anchors | check/packets/obligation repository root, analyze current/historical anchors, eval corpus anchor, doctor CWD |
| Single resolution | exactly one resolver call per config-consuming invocation |
| Injection | core/command unit accepts a typed settings object without ambient config reads |
| Side-effect boundary | invalid option/config precedes snapshot, cache, adapter, provider, and output work |
| Trusted refresh | analyze and eval use the exact trusted config path and exact literal read-write/enable options |
| Hostile PR | target config and payload cannot influence config path, option key, or option value |

Do not mock:

- config discovery or recursive `extend`;
- TOML parsing or strict settings validation;
- the canonical resolver in public-CLI tests;
- the trusted-tool/hostile-target path split in workflow tests;
- cache/provider/output constructors in boundary-order tests where their
  non-invocation is the behavior under proof.

Provider adapters may be controlled counters or fail-if-called fakes. No live
provider call is required for implementation verification.

## Verification Gates

Per-slice gates are listed with each task. Final completion additionally
requires:

- every new public flag, structural-key rejection, precedence layer, and
  trusted workflow option has a firing test;
- active specs contain no filename-specific refresh contract;
- active source/tests/workflows/docs contain no old refresh filename;
- historical plans remain unchanged unless a separate archival task is
  authorized;
- default `backstitch check --repo-root .` is exit `0`, zero errors, zero
  warnings;
- `--show-suppressions` remains auditable;
- the implementation diff contains no provider credential, generated config
  file, committed cache, or report artifact.

## Independent Review Loop

Before the spec-promotion slice, use Claude through direct `claude -p` and give
it:

- this plan, including the exact `## Proposed Spec Delta`;
- the four governing specs;
- `backstitch/settings.py` and the relevant config call sites in
  `backstitch/cli.py` and `backstitch/alignment_eval.py`;
- `pyproject.toml`;
- both trusted semantic workflows;
- the SimpleBroker comparison files.

Review stance:

> Find errors, bad ideas, latent ambiguity, security-boundary mistakes, missing
> firing cases, and performative overengineering. Check whether one
> zero-context engineer could implement the plan confidently against the delta
> as if promoted. In particular, challenge whether there is truly one resolver,
> whether typed-settings injection is clean, and whether hostile target or
> event data can influence provider configuration. Do not implement.

Append each finding and disposition to the review log. Any finding that changes
invariants, ownership, authority, or blast radius requires a focused re-review
of the changed delta before promotion.

Run a second independent review after Slice 5. Plan approval is not
implementation approval.

## Implementation Evidence

Implemented Slices 1 through 4 and ran the Slice 5 gates on 2026-07-27.
The work remains uncommitted because the user has not authorized landing.

- `resolve_config(...)` is the only public settings assembler. The CLI resolves
  once per config-consuming invocation and passes an immutable
  `BackstitchSettings` snapshot through command handlers.
- The resolver applies packaged defaults, selected/discovered config and
  `extend`, the two defined environment inputs, then generic and dedicated CLI
  settings. It also records the winning analyzer-model source so `doctor`
  does not reread `LLM_MODEL`.
- Public CLI tests cover the full option grammar, value and failure families,
  alias conflicts, named operational non-aliases, command anchors, one
  resolver call per command, injection below the boundary, and failure before
  provider/cache/output effects.
- `pyproject.toml` owns the dormant verifier descriptor. Both trusted workflows
  select trusted `pyproject.toml` explicitly and use exactly the three literal
  [SEM-9.1] overlays.
- Targeted search found no active `.backstitch-refresh.toml` reference in
  source, tests, workflows, README, implementation docs, specs, or
  `.gitignore`. Historical plans remain unchanged.

Observed verification:

- all three focused Slice 5 pytest groups exited `0`;
- `tests/acceptance` exited `0` with 41 probes;
- the complete non-live, non-performance pytest suite exited `0`;
- Ruff check and format check exited `0`;
- mypy exited `0` with no issues in 42 source files;
- default self-corpus check exited `0`: 120 sections, 270 mappings,
  355 code references, 741 edges, 8 invariants, 15 binds, and zero errors,
  warnings, or infos;
- suppression audit exited `0` with the same clean summary and 206 auditable
  suppressions;
- exact `git diff --check` reports only two trailing-space Markdown hard
  breaks in
  `tests/semantic_eval/v3/qualification-candidate/independent-review.md`.
  That file predates this plan's work, is a hash-pinned frozen qualification
  artifact (`sha256:7fc5337c41417d472645bf90ea1bf0f7722e2678c3f6e2d781aca62badc555cd`),
  and changing it invalidates its corpus digest. The scoped check excluding
  that artifact exits `0`; the exception is retained rather than mutating
  unrelated frozen evidence.

## Review Log

### 2026-07-27: Claude cross-model review, round 1

Invocation: direct `claude -p` from the repository root. Verdict: **REVISE**.
The reviewer could not read `../simplebroker` because its session restricted
parent-directory access; the author had already inspected those files
directly, and no correction depends on the comparison.

| Finding | Disposition |
|---|---|
| F1: dormant verifier shape contradicted [EVC-5] and [CFG-6] §6.7 | Accepted. The delta now defines minimal-disabled and dormant-complete shapes in both specs, requires final post-overlay validation, and adds firing cases. |
| F2: [EVC-5.1]/[EVC-8.3] exact grammars omitted `--option` | Accepted. Both exact grammar sections now receive explicit reconciliation text; [EVC-5.1] also gains the repeated option line. |
| F3: Strategy A promotion would fire strict `SPEC_SECTION_UNMAPPED` diagnostics | Accepted. Promotion adds exact temporary section markers for [SC-5.1], [CFG-5.1], and [SEM-9.1]; mapping slices remove them atomically. |
| F4: the complete verifier values were not pinned before deleting their old code/file copy | Accepted. [SEM-9.1]'s exact proposed text now contains the complete dormant verifier and eval TOML, and Slice 3 must transcribe it. |
| F5: deleting whole [SEM-9] paragraphs would also delete durable availability, persistent-control, and output-path rules | Accepted. The delta now replaces only exact filename-specific sentences and explicitly preserves/restates the durable rules. |
| F6: `packets.output` would become an accepted no-op | Accepted. Generic options now require runtime-consulted leaves and explicitly reject `packets.output` and other reserved/non-consulted leaves. |
| F7: TOML-or-string parsing did not exclude multi-assignment payloads | Accepted. NUL/CR/LF are rejected; parsing uses one synthetic assignment and requires exactly one resulting key before any string fallback rule. |
| F8: the dedicated-flag conflict map was open-ended | Accepted. The plan and [CFG-5.1] delta now contain a closed alias table and an explicit operational non-alias list. |
| F9: the public-helper rename omitted test call sites | Accepted. Slice 1 names every current test importer and narrowly permits a recorded mechanical migration if another is found. No compatibility alias is allowed. |
| F10: non-consuming commands treated `--option` differently from `--config`/`--no-config` | Accepted. All three controls are rejected on `summarize-analysis`, `guide`, and `cache cleanup-lock`. |
| F11: [SC-5.1]'s insertion point could capture remaining [SC-5] prose | Accepted. The exact locator is now immediately before [SC-5]'s implementation-mapping block. |
| F12: the plan cited nonexistent stable code `[CFG-6.5]` and nested ambiguous fences | Accepted. The locator is now “§6.5 final paragraph”; exact deltas with inner code fences use four-tilde outer fences. |

Because F1, F2, F3, and F5 changed normative scope or promotion mechanics,
the revised delta requires a focused Claude re-review before promotion.

### 2026-07-27: Claude cross-model review, round 2

Invocation: direct `claude -p` from the repository root. Verdict: **REVISE**.
Claude confirmed F1-F10 and F12 resolved. F11 remained open because its first
correction placed new subsections before parent mapping blocks, which would
have reassigned those mappings to the new headings.

| Finding | Disposition |
|---|---|
| NEW-1: [SC-5.1]/[SEM-9.1] locators would steal parent mappings and break the promotion gate | Accepted. Both new subsections now insert after the parent mapping block and before the next `##` heading. |
| NEW-2: [EVC-10.1]'s exact eval grammar omitted `--option` even though trusted eval needs the overlays | Accepted. The delta adds the repeated option line and a [CFG-5.1]/[SEM-9.1] composition rule. |
| NEW-3a: the one-top-level-key rule could be misread as rejecting inline-table values | Accepted. The rule now says the parsed `value` may be a scalar, array, or inline table; only extra top-level document keys/tables fail. |
| NEW-3b: dotted KEY quoting and dotted map-entry names were undefined | Accepted. KEY splits on literal dots with no quoting/escaping; empty segments and attempts to address dotted map-entry names fail at the non-leaf boundary. |
| NEW-4: [SEM-9.1] did not directly require the PR workflow to use the same three overlays | Accepted. The PR paragraph now says it uses the same three literal overlays. |
| NEW-5: duplicate [EVC-8.3] analyze grammars relied only on a composition paragraph | Accepted. The exact repeated option line is added to both duplicate analyze grammars. |

The revised locator and grammar changes require a narrow final re-review before
promotion. They do not change ownership, authority, or blast radius.

### 2026-07-27: Claude cross-model review, round 3

Invocation: direct `claude -p` from the repository root. Verdict: **PASS**.
Claude verified NEW-1 through NEW-5 resolved against the actual mapping-owner,
marker, grammar, spec-anchor, and workflow behavior; it reported no new
findings and judged the proposed delta safe for spec promotion.

### 2026-07-27: Claude cross-model implementation review

Invocation: direct `claude -p` from the repository root after Slice 5.
Verdict: **REVISE**. Static inspection found the implementation substantially
correct and the hostile-target/trusted-tool boundary sound. The following
findings were then addressed:

| Finding | Disposition |
|---|---|
| I1: empty `--profile` bypassed generic/dedicated conflict detection | Accepted. Dedicated values now use presence rather than truthiness; a firing public-CLI test covers the empty value. |
| I2: `doctor` reread `LLM_MODEL` and mislabeled `--model` | Accepted. The canonical snapshot records analyzer-model provenance; doctor receives the resolved value/source and contains no Backstitch environment read. |
| I3: wrong `--option` arity lacked a firing test | Accepted. A public argparse test proves exit `2`. |
| I4: multi-assignment rejection was not fireable | Accepted. The parser distinguishes a successfully parsed second assignment before applying the NUL/CR/LF rejection; both families have firing tests. |
| I5: named operational non-aliases lacked exhaustive proof | Accepted. Public dispatch tests cover repository roots, non-check formats/outputs, packet output/report, obligation limit, analyze packet/report paths, and config selection alongside a generic option. |
| I6: eval, doctor, and packets anchors lacked direct proof | Accepted. A public-CLI matrix covers check, packets, obligation, current/historical analyze, eval, and doctor discovery anchors. |
| I7: one-resolution proof covered only `config path`; global/local duplicate coverage was indirect | Accepted. The counter now covers every config-consuming command and both analyze modes; a public-CLI test covers the global/local duplicate. |
| I8: semantic-refresh option assertions were count-only | Accepted. Each refresh/eval step now requires exact set equality, literal values, and no event-payload reference. |
| I9: test citations and stale implementation-pending text | Accepted. Reciprocal mappings/citations now include doctor and its tests; all four governing backlinks record implementation and verification. |
| I10: two assertions were overly broad and one test retained the old helper name | Accepted. Assertions now prove exact selected values and exact missing verifier keys; the stale test name uses `resolve_config`. |
| I11: alignment evaluation resolves the same root in definition and task validation, and a replay subprocess inherits environment | Dispositioned. Definition validation and task validation are separate contexts under invariant 2's explicit fixture/context boundary; each resolves once and passes its snapshot through that operation. A replay is a separate public CLI invocation whose environment layer is specified behavior. Changing either boundary would expand this plan. |
| I12: the reviewer could not run gates | Resolved by implementation evidence above. All gates ran locally; only the frozen-artifact `git diff --check` exception remains and is recorded. |

A focused direct `claude -p` confirmation was attempted after these
corrections, but Claude exited before inspection because the account had
reached its usage limit. No PASS is claimed for that blocked attempt. The
completed implementation review has no unaddressed correctness or required
coverage finding.

## Out Of Scope

- a generic Backstitch environment-variable namespace;
- removal of existing dedicated CLI flags;
- a new implicit config filename;
- profiles as a new persistence or inheritance system;
- cache-key, cache-object, lock, cleanup, report, or snapshot lifecycle changes;
- semantic policy promotion, merge authority, PR comments, or status checks;
- provider credential configuration;
- executing or installing target-repository code;
- rewriting historical plans to erase obsolete decisions;
- unrelated CLI parser cleanup;
- copying SimpleBroker's config keys, mutable dictionaries, or module-level
  environment snapshot.

## Fresh-Eyes Review Checklist

- Can a new engineer name the sole resolver and every permitted caller?
- Does the plan distinguish config source selection from setting precedence?
- Are generic value parsing and all ambiguity cases deterministic?
- Are path bases explicit for file-authored and CLI-authored values?
- Can tests inject settings without bypassing public resolver tests?
- Is the verifier fully describable before CLI enablement?
- Is every hostile-target-controlled input excluded from configuration?
- Can rollback avoid resurrecting the removed special file?
- Are new mappings and reciprocal backlinks scheduled atomically?
- Does every enumerable contract element have a firing test?
