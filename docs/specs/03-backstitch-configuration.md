# Backstitch Configuration Specification

Status: Active

This spec defines how `backstitch` discovers, loads, validates, and applies
project configuration from TOML files. It governs defaults for CLI commands
without replacing explicit CLI flags.

Related behavior:

- `docs/specs/02-backstitch-core.md` [SC-3], [SC-5], [SC-7], [SC-12]
- `docs/specs/08-intent-coverage.md` [COV-4], [COV-5], [COV-9]

## 1. Purpose And Scope [CFG-1]

`backstitch` must support repository-local configuration so teams can commit
stable defaults for profiles, scan roots, strictness, semantic-analysis model
selection, and sibling target discovery.

This spec owns:

- config file discovery and precedence
- supported TOML file shapes (standalone and `pyproject.toml`)
- the v1 configuration schema
- merge semantics for `extend`
- validation and error reporting for malformed config
- how loaded config interacts with CLI flags and environment variables

This spec does not own:

- built-in profile definitions ([SC-3])
- deterministic issue semantics ([SC-4], [SC-11])
- semantic packet or result contracts ([SC-6], [SC-7])
- a plugin or macro language for custom parsers
- user-level global config outside a repository (for example
  `~/.config/backstitch/config.toml`) in v1

_Implementation mapping_:
- `backstitch/settings.py`

## 2. Mental Model [CFG-2]

Configuration is resolved once per command invocation from a **discovery
anchor** directory. The loader walks upward toward the user's home directory,
selecting the nearest applicable config file.

Important concepts:

- **Discovery anchor**: the directory where upward search begins. This is
  command-specific ([CFG-3]).
- **Config directory**: the directory containing the selected config file. Path
  values in config are resolved relative to this directory unless they are
  absolute.
- **Effective settings**: the merged result of packaged defaults, `extend`
  inheritance, discovered file values, environment overrides where applicable,
  and CLI flags.
- **Profile overlay**: config may set a built-in profile name and override
  profile fields such as roots and globs without defining a new parser profile.

Configuration must reduce repetition. It must not hide behavior that changes
deterministic outcomes without an explicit, inspectable source.

Effective settings always start with Backstitch's packaged default TOML. A
repository may have no discovered config, but there is never "no config" at
runtime; there is at least the packaged default layer. `--no-config` skips
repository discovery and explicit repository config, not packaged defaults.

_Implementation mapping_:
- `backstitch/settings.py`

## 3. Discovery [CFG-3]

### 3.1 Discovery anchors

| Command | Discovery anchor |
|---------|------------------|
| `check` | `--repo-root` after `resolve()` |
| `coverage` | positional path or `--repo-root` after `resolve()`, otherwise current working directory |
| `packets` | `--repo-root` after `resolve()` |
| `obligation list` / `obligation OBLIGATION_ID` | `--repo-root` after `resolve()`, or current working directory when omitted |
| `analyze --repo-root` | repository root after `resolve()` |
| `analyze --packets` | parent directory of `--packets` after `resolve()` |
| `eval` | parent directory of `--corpus` manifest after `resolve()` |
| `cache cleanup-lock` | no discovery; all cache/staleness inputs are explicit |
| `summarize-analysis` | no discovery in v1; CLI args only |
| `guide alignment` | no discovery; installed code-owned guide only |
| optional `mcp` | required `--repo-root` after `resolve()` |
| `doctor` | current working directory after `resolve()` |

If `--config` is provided ([CFG-5]), discovery is skipped and that file is the
sole config source (still subject to CLI/env precedence above file values).

Implicit discovery recognizes only `.backstitch.toml` and a `pyproject.toml`
that contains `[tool.backstitch]`. An explicit `--config PATH` may name any
TOML filename. An `extend` value may also name any TOML filename. Neither
mechanism adds that basename to implicit discovery or gives the basename
special validation or trust semantics.

### 3.2 Upward search

From the discovery anchor, examine each directory in this order:

1. the anchor directory itself
2. each parent directory

The stopping rule has exactly two cases, decided once up front by whether
`$HOME` (expanded and resolved) is an ancestor of the resolved anchor:

- `$HOME` is an ancestor: examine each directory up to and **including**
  `$HOME`, then stop. The search never ascends above `$HOME`.
- `$HOME` is not an ancestor (anchor outside the home tree): examine each
  directory up to and **including** the filesystem root, then stop. `$HOME`
  is irrelevant to such a walk and is never visited.

The intent of the `$HOME` bound is to keep a user's own tree from being
shadowed by configs above it, not to pretend `$HOME` appears on paths it is
not on.

At each directory, evaluate config candidates in this order:

1. `.backstitch.toml`
2. `pyproject.toml` containing a `[tool.backstitch]` table

Use the first candidate found. Do not merge `.backstitch.toml` and
`pyproject.toml` from the same directory.

When considering `pyproject.toml`, ignore files that lack `[tool.backstitch]`,
matching the `ruff`/`mypy` pattern of only treating `pyproject.toml` as a
backstitch config when the tool section exists.

### 3.3 Closest file wins

Unlike mypy/ruff per-file cascade, v1 uses **one** discovered file: the nearest
config file to the anchor along the ancestor chain. Parent-directory configs are
ignored once a closer file is found.

Nested inheritance across directories is supported only through the `extend`
field inside a config file ([CFG-6]).

_Implementation mapping_:
- `backstitch/cli.py`
- `backstitch/settings.py`

## 4. File Formats [CFG-4]

### 4.1 Standalone `.backstitch.toml`

Standalone files use the same key layout as the body of `[tool.backstitch]`,
without the `tool.backstitch` prefix. Example:

```toml
extend = "../shared/.backstitch.toml"

[profile]
name = "backstitch-style-v1"
spec_roots = ["docs/specs"]
code_roots = ["backstitch", "tests"]

[check]
warnings_as_errors = false
format = "text"

[analyze]
model = "gpt-4o-mini"
concurrency = 1

[target_roots]
weft = "../weft"
```

### 4.2 `pyproject.toml` section

Project metadata files must use a `[tool.backstitch]` table:

```toml
[tool.backstitch.profile]
name = "backstitch-style-v1"
spec_roots = ["docs/specifications"]
code_roots = ["weft", "tests"]

[tool.backstitch.check]
format = "json"

[tool.backstitch.analyze]
model = "gpt-4o-mini"

[tool.backstitch.target_roots]
weft = "../weft"
```

### 4.3 Path and environment expansion

String paths in config must support:

- `~` and `~/...` expansion to the user home directory
- `${VAR}` and `$VAR` environment variable expansion

Order matters and is fixed: expand `~` and environment variables **first**;
then, only if the expanded result is still relative, resolve it against the
directory containing the config file. The reverse order breaks both forms —
prefixing `~/x` with the config directory leaves a mid-path `~` that no
longer expands, and prefixing `$ABS_ROOT/x` produces a malformed path when
the variable holds an absolute path. An expanded absolute result is used
as-is.

_Implementation mapping_:
- `backstitch/config.py`
- `backstitch/settings.py`

## 5. Precedence [CFG-5]

Effective settings are assembled in this order (later sources override or
append after earlier sources according to each key's merge rules):

1. packaged default TOML
2. discovered config file, after `extend` merge ([CFG-6])
3. environment variables where this spec defines them
4. explicit CLI flags and options

`default_command` follows ordinary scalar file-layer precedence. A child
config may replace an inherited command or set `false` to disable it. No
environment variable, dedicated flag, or generic `--option` key changes the
selected default command. Global config selection and generic options for
the eventually selected command still participate in the one normal
resolution. The canonical resolver receives the explicit command or its
absence, merges packaged and file layers once, validates and selects the
effective default when needed, and only then applies command-relevant
environment values. `LLM_MODEL` therefore applies to bare analyze exactly as
it does to explicit analyze and remains absent from bare check exactly as it
does from explicit check. Dedicated arguments supplied without a subcommand
are parsed for the closed default-command candidates before resolution, but
their setting overrides are deferred by command owner. After file precedence
selects the effective default, the resolver applies only that command's
dedicated overrides at ordinary CLI precedence. This preserves one config read
and prevents `--model` or check-only flags from leaking across commands.

Environment variables in v1:

| Variable | Affects | Notes |
|----------|---------|-------|
| `BACKSTITCH_WEFT_ROOT` | sibling Weft discovery | overrides `target_roots.weft` |
| `LLM_MODEL` | `analyze` model fallback | overrides `analyze.model` when `--model` is omitted; cached modes resolve the winning model through the closed descriptor catalog below |

CLI flags always beat config and environment for the same setting.
When a file layer declares a nonblank flat `analyze.model`, a different
winning `--model` or `LLM_MODEL` value must name one key in
`[analyze.models]`, in every cache mode. The matching entry supplies the
complete revision, backend/plugin/distribution identity, and cost inputs for
that model. An unknown winning model is exit `2`; Backstitch never retains
another model's descriptor. The existing cache-off runtime fallback remains
only when file configuration declares no nonblank model: the selected model
uses packaged blank optional identity/cost fields and no result cache.

When enabled verification uses `provider_source = "analyze"`, the complete
resolved analyze descriptor is atomic even when analyze cache mode is `off`:
model, revision, backend/plugin/distribution identity, input/output rates,
token overhead, and cost-rate source travel together. `--model` and
`LLM_MODEL` may be absent or equal the config-declared model; neither may
replace it while retaining the other identity or cost fields. A different
reused model requires an atomic configuration change to the complete analyze
descriptor ([EVC-5]).

`code_roots` and `test_roots` form one ordered override pair. A layer that
replaces `code_roots` and omits `test_roots` resets test roots to empty. A
layer that supplies `test_roots` replaces them and otherwise retains effective
code roots. After all configuration and CLI layers, validate test-root
containment against the final effective code roots.

`--config PATH` selects a specific file and bypasses upward discovery. Relative
`PATH` values are resolved against the process working directory.

Coverage report mode follows this ordinary precedence. Coverage ratchet mode
is narrower: [COV-5]/[COV-9] reject explicit `--config`, `--no-config`,
`--profile`, every `--option`, home/environment/external layers, and every
gate-affecting value not owned by packaged defaults or a no-follow
repository-owned config layer present at both current and merge-base state.
Only the root alias, `format`, `output`, and `--require-ratchet REF` are
operational CLI inputs. `--require-ratchet` asserts the literal effective
mode/base pair and never overrides either.

_Implementation mapping_:
- `backstitch/defaults.toml`
- `backstitch/diagnostics.py`
- `backstitch/settings.py`
- `backstitch/cli.py`
- `backstitch/analysis_llm.py`
- `backstitch/doctor.py`
- `backstitch/target_roots.py`

### 5.1 Canonical Resolution And Generic CLI Overlays [CFG-5.1]

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

Filesystem discovery and Git-blob lookup are source adapters only. Both
produce the same ordered configuration-layer envelope and call one effective
settings assembler/finalizer. That owner alone performs merge, provenance
projection, model selection, typed parsing, unknown-key and cross-field
checks, and final paired-root containment.

After [CFG-4]'s user and environment expansion, final profile-root containment
is lexical for every adapter. Join a relative root to the target repository
root, normalize `.` and `..`, and compare normalized path equality or
ancestry. Containment does not call `Path.resolve`, `realpath`, `stat`, or
another filesystem operation; physical symlink and no-follow enforcement
belongs to repository capture. Given equal defaults, environment, and layer
bytes with no CLI overlay, both adapters yield equal non-operational settings
and identical profile-root containment. Operational output, cache,
verification-evaluation-report, and target-root addresses may differ only in
adapter normalization: the filesystem adapter may preserve its physical
canonicalization, while the blob adapter validates and normalizes them
lexically because they are not historical gate authority. Operational source
provenance may also differ. Blob-backed resolution never consults the checkout
or live filesystem.

The repeatable CLI form is `--option KEY VALUE`. `KEY` is a known,
runtime-consulted dotted leaf path in standalone `.backstitch.toml` shape and
never includes `tool.backstitch`. Split `KEY` on literal dots with no quoted
segments or escaping; every segment is nonempty. Individual map entries whose
names contain dots, including `lint.per-file-ignores` and
`lint.per-section-ignores` entries, are not addressable; traversal stops at a
non-leaf table and is exit `2`. Reserved/non-consulted leaves such as
`packets.output` are not runtime-overridable.

`default_command` is also not a generic-option leaf. It selects whether bare
invocation dispatches at all and is accepted only from the packaged or
selected/discovered file layers. Once file configuration selects the
command, other valid global `--option KEY VALUE` pairs apply normally to the
already selected command's settings.

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

The analyze descriptor leaves `backend_id`, `plugin_id`,
`plugin_distribution_name`, `model_revision`,
`capability_schema_version`, `capability_revision`, `request_constraints`,
`maximum_input_bytes`,
`input_cost_microusd_per_million_tokens`,
`output_cost_microusd_per_million_tokens`, `input_token_overhead`, and
`cost_rate_source` are also reserved from generic `--option`. The dedicated
`--model` flag and generic `--option analyze.model VALUE` are equivalent
selectors and conflict under the ordinary same-key rule. Either selects one
complete trusted descriptor; no CLI form constructs or partially edits a
descriptor.

`analyze.reasoning_effort` and `verify.reasoning_effort` are ordinary known
request-value leaves, not descriptor leaves. A trusted static option such as
`--option analyze.reasoning_effort '"max"'` may set one under the same scalar
precedence and same-key conflict rules as the other request settings.

Every leaf below `verify.provider` is likewise reserved from generic
`--option`, including `backend_id`, `plugin_id`,
`plugin_distribution_name`, `model`, `adapter_model_id`, `model_revision`,
`capability_schema_version`, `capability_revision`, `request_constraints`,
`maximum_input_bytes`, both cost-rate fields, `input_token_overhead`, and
`cost_rate_source`. The override provider descriptor is file-owned and atomic;
no CLI form constructs or partially edits it.

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

_Implementation mapping_:

- `backstitch/config.py`
- `backstitch/filesystem_io.py`
- `backstitch/settings.py`
- `backstitch/cli.py`
- `backstitch/analysis_llm.py`
- `backstitch/doctor.py`
- `backstitch/target_roots.py`
- `tests/test_cli_config.py`
- `tests/test_config_parity.py`
- `tests/test_doctor.py`
- `tests/test_settings.py`
- `tests/test_semantic_settings.py`

## 6. Schema [CFG-6]

_Implementation mapping_:

- `backstitch/config.py`
- `backstitch/diagnostics.py`
- `backstitch/settings.py`
- `backstitch/target_roots.py`

### 6.1 Top-level keys

| Key | Type | Applies to | Meaning |
|-----|------|------------|---------|
| `extend` | string | all commands | Load and merge another config first |
| `allow_unknown_keys` | bool | load time | Downgrade unknown-key errors to warnings (default `false`) |
| `default_command` | `false` \| `"check"` \| `"analyze"` | bare invocation | Select one current-directory command; `false` disables bare dispatch |
| `exclude` | array of glob strings | scan | Replace default scan excludes ([CFG-6.7]); applies to spec discovery and code scan |
| `extend_exclude` | array of glob strings | scan | Append to the active exclude list ([CFG-6.7]); applies to spec discovery and code scan |

The packaged value is `false`. `"check"` is equivalent to explicit
`backstitch check --repo-root .`; `"analyze"` is equivalent to explicit
`backstitch analyze --repo-root .`, where `.` is the process working
directory. The equivalence is handler-level: the same resolved settings,
output contract, exit classes, deterministic preflight, cache policy, and
provider controls apply.

The value is deliberately not a string containing arguments and not an
array. Command-specific setting defaults belong in their existing tables,
such as `[analyze].model` and `[check].format`. Operational arguments that
lack a config key require an explicit command. A config that needs no bare
action uses `false`; blank strings and every other boolean, string, array,
table, integer, or floating-point value are invalid.

The profile name has exactly one spelling: `[profile].name` (that is,
`[tool.backstitch.profile]` `name` in `pyproject.toml`). There is no
top-level `profile` string key — TOML cannot represent `profile = "x"` and a
`[profile]` table in the same document, so offering both spellings creates a
"which wins" rule for a state that cannot exist. A top-level `profile` key
is an unknown key ([CFG-8]).

Scan-boundary keys (`exclude`, `extend_exclude`) are top-level
`[tool.backstitch]` keys in `pyproject.toml` (siblings of
`[tool.backstitch.profile]`), not fields inside `[profile]`. TOML table scope
would treat a key written under `[profile]` as a profile override; those keys
are not valid profile fields and must error under strict unknown-key handling
([CFG-8]).

### 6.2 `[profile]` / `[tool.backstitch.profile]`

Overrides fields for the selected built-in profile:

| Key | Type | Maps from |
|-----|------|-----------|
| `name` | string | Built-in profile name ([SC-3]); CLI `--profile` |
| `spec_roots` | array of strings | CLI `--spec-root` |
| `plan_roots` | array of strings | future CLI |
| `code_roots` | array of strings | CLI `--code-root` |
| `test_roots` | array of strings | Test-role classifiers within effective code roots; CLI `--test-root` |
| `planned_spec_globs` | array of strings | Weft-style planned docs |
| `exploratory_spec_globs` | array of strings | Weft-style exploratory docs |

Array overrides replace the built-in profile lists; they do not append unless
`extend` already established a base list and the child file repeats the full
intended list.

Test roots use normal path expansion. A configuration layer that explicitly
replaces `code_roots` and omits `test_roots` resets test roots to empty. A layer
that supplies `test_roots` replaces them and otherwise retains effective code
roots. After all configuration and CLI layers, each nonempty effective test
root must be equal to or nested under a final effective code root; invalid
containment is exit `2`. The CLI applies the same rule: `--code-root` without
`--test-root` resets test roots, while explicit `--test-root` values are
validated after all overrides. `--test-root` without `--code-root` retains
inherited code roots and validates against them. Empty effective test roots do
not suppress invariant diagnostics.

### 6.3 `[check]` / `[tool.backstitch.check]`

| Key | Type | Maps from |
|-----|------|-----------|
| `format` | `"text"` \| `"json"` | CLI `--format` |
| `warnings_as_errors` | bool | CLI `--warnings-as-errors` |
| `output` | string | CLI `--output` |

### 6.4 `[packets]` / `[tool.backstitch.packets]`

| Key | Type | Maps from |
|-----|------|-----------|
| `output` | string | CLI `--output` default only when command allows optional output in a later revision; in v1 store for forward compatibility but require CLI `--output` |

`packets.output` is reserved in v1. The command continues to require
`--output` on the CLI ([SC-5]).

### 6.5 `[analyze]` / `[tool.backstitch.analyze]` [CFG-6.5]

| Key | Type | Maps from |
|-----|------|-----------|
| `model` | string | CLI `--model` default |
| `concurrency` | integer | CLI `--concurrency` |
| `result_reuse` | `"evidence-stable"` \| `"exact-inference"` | Cross-provider analyzer-result selection ([SEM-4]) |
| `models` | table keyed by exact model selector | Trusted cached-model descriptor catalog |

All other semantic inference, cache, completeness, budget, finding, and
disposition keys are defined exactly in [SEM-9]. They are strict known keys
under `[analyze]` and `[[analyze.dispositions]]`; unknown or mistyped semantic
keys, including the historical-only `[analyze.eval]` producer spelling, follow
[CFG-8]. Current evaluation configuration lives only under `[verify.eval]`.
Packaged values are conservative. A repository's applied TOML owns stricter
policy, and workflow YAML must not duplicate those non-secret controls.

`result_reuse` defaults to `"evidence-stable"`. It carries forward one
complete, previously selected evidence-bound inference result while its
[SEM-3] review identity is unchanged. `"exact-inference"` preserves the
existing rule that only the winning model/provider's exact `analysis_key` is
a hit. Neither value reuses a result across packet, prompt, request,
analysis-contract, or search-epoch changes. Changing `search_epoch` remains
the explicit durable resampling mechanism.

`require_complete` governs result completeness after the authoritative packet
set has been selected: when true, every selected packet must have one valid
result under [SEM-3]/[SEM-9]. It does not relax current-source obligation
readiness, make a partial packet plan executable, bypass packet or request
budgets, or turn `ALIGNMENT_DEBT` into an advisory result. Help and
`config show` describe it as result completeness, not source completeness.

`[analyze.models]` is a closed catalog whose quoted child keys are canonical
Model Monster `pkg:service` PURLs in the form
`pkg:service/{service_namespace}/{service_name}[@{version}][?{qualifiers}]`.
The namespace is required and in DNS order; a subpath is forbidden. The key is
the canonical identity selector accepted by `LLM_MODEL` and `--model`. Each child
contains exactly the nonblank raw `adapter_model_id` passed to the provider,
`backend_id`, `plugin_id`,
`plugin_distribution_name`, `model_revision`,
`capability_schema_version`, `capability_revision`, `request_constraints`,
`maximum_input_bytes`,
`input_cost_microusd_per_million_tokens`,
`output_cost_microusd_per_million_tokens`, `input_token_overhead`, and
`cost_rate_source`. Unknown child fields, blank or whitespace-bearing selector
keys, partial descriptors, wrong types, and invalid ranges are
exit `2`. The flat `[analyze]` identity/cost fields remain the descriptor for
the flat `model`, preserving existing configuration. A catalog child whose
selector equals the nonblank flat model is invalid; one selector has exactly
one descriptor owner. `adapter_model_id` aliases must also be unique across the
flat descriptor and catalog.

The capability portion of every file-owned descriptor is closed.
`capability_schema_version` is exactly integer `1`;
`capability_revision` is a nonblank version string; and
`maximum_input_bytes` is a positive integer conservative ceiling for one
complete provider request, not the aggregate corpus prompt budget. A request
larger than that ceiling fails before credential access or a provider call.

`request_constraints` is a closed mapping with exactly `json_mode`,
`temperature`, `seed`, `max_tokens`, and `reasoning_effort`. Each authored
TOML value is a closed record containing `presence` plus only its applicable
constraint keys. `presence` is `required`, `optional`, or `forbidden`.
`json_mode` uses nonempty duplicate-free `allowed_values` drawn from
`require` and `off`; configured `prefer` is a resolution instruction and must
resolve to one of those effective wire values before validation. `temperature`
uses nonempty duplicate-free finite-number `allowed_values`. `seed` and
`max_tokens` use integer `minimum` and `maximum`, with minimum no greater than
maximum. `reasoning_effort` uses nonempty duplicate-free `allowed_values`
drawn from `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, and `max`. An
allowed-value constraint omits both bounds. A range constraint omits
`allowed_values`. A forbidden field omits all three constraint members.
Unknown or inapplicable authored keys are invalid. The resolver expands
authored TOML into [SEM-3]'s one exact runtime record by inserting null for
every omitted inapplicable member. Thus TOML needs no null literal and the
normalized descriptor has one closed canonical shape. A required field must
be present in the frozen effective request; a forbidden field must be absent;
an optional field is validated when present. Backstitch validates but never
silently corrects, adds, or removes an explicitly configured incompatible
value.

`json_mode` and `max_tokens` are required request settings in analyze and an
enabled verifier. `temperature`, `seed`, and `reasoning_effort` are optional
request settings. When no effective config layer supplies an optional setting,
it is absent from `EffectiveRequest`, `RequestIdentity`, and the provider
request. Absence of `reasoning_effort` accepts the provider default; no
sentinel value represents omission. Ordinary scalar precedence applies when a
layer supplies an optional value. Because this schema has no deletion
sentinel, a child config cannot erase an optional value inherited through
`extend`; it must stop extending that source or the inherited value must
satisfy the newly selected descriptor. An incompatible inherited value fails
with its exact config key before provider work.

`adapter_model_id` is the analyzer's raw transport selector and resolves to
`analyzer_model_id`; it never replaces the catalog PURL's stable
identity. An enabled verifier retains its independently resolved raw selector
as `verifier_model_id` under [EVC-5]. Both raw IDs remain outside
`request_constraints` and semantic cache identity, while their selected
descriptor and provenance remain reportable.

The flat descriptor is one atomic non-packaged file-layer group containing
exactly `model`, `backend_id`, `plugin_id`, `plugin_distribution_name`,
`model_revision`, `capability_schema_version`, `capability_revision`,
`request_constraints`, `maximum_input_bytes`, both cost-rate fields,
`input_token_overhead`, and
`cost_rate_source`, plus optional `adapter_model_id` (which defaults to
`model`). If a discovered, selected, parent, or child file layer
supplies any group member, that same layer must supply the complete group.
The group replaces the inherited flat descriptor as one unit; field-by-field
inheritance is invalid. Packaged defaults may retain blank optional descriptor
members for the documented cache-off fallback, but no repository file layer
may construct a partial descriptor.

The catalog PURL is the inference-contract `provider.model_id`;
`adapter_model_id` is transport configuration and does not replace that stable
identity. Catalog descriptors are file-owned trusted configuration. Environment and
CLI layers select a model through `--model`, `--option analyze.model`, or
`LLM_MODEL` by canonical identity or its unique `adapter_model_id` alias. The
resolved `model` is always restored to the canonical identity. These layers
cannot synthesize, partially override, or import a descriptor
from a target repository. A positive global analyze cost ceiling
requires the selected descriptor's explicit nonnegative rates and overhead
and nonblank source. `config show` renders the selected effective descriptor
and a sorted `available_models` list; it does not duplicate inactive descriptor
bodies into the invocation snapshot.

`extend` merges `[analyze.models]` by exact selector key. A later layer may add
a selector or replace one complete descriptor; descriptor children are atomic
and never deep-merge field by field. A partial replacement is invalid rather
than inheriting omitted identity or cost fields. The flat descriptor group
uses the same replace-not-deep-merge rule across `extend`. The sorted
`available_models` list is the lexical ordering of the final nonblank flat
model plus all catalog selectors, with duplicates removed; adapter aliases are
not listed.

_Implementation mapping_:

- `backstitch/settings.py`

When `extend` names `pyproject.toml`, the loader selects the target file's
`[tool.backstitch]` table before merging. Other TOML filenames contribute
their top-level tables. `extend` filenames are otherwise unrestricted and
carry no special validation or trust semantics.

### 6.6 `[obligations]` / `[tool.backstitch.obligations]` [CFG-6.6]

The complete initial table and packaged defaults are:

```toml
[tool.backstitch.obligations]
section_required_roles = ["implementation"]
page_size = 5
maximum_page_size = 100
maximum_response_bytes = 65536
maximum_candidate_items = 2000
maximum_catalog_items = 100000
maximum_lexical_seeds = 10
maximum_snapshot_files = 20000
maximum_file_bytes = 5000000
maximum_snapshot_bytes = 100000000
maximum_work_units = 2000000
maximum_packet_bytes = 10000000
maximum_packet_report_bytes = 10000000
maximum_call_seconds = 10.0
snapshot_capture_attempts = 3
static_neighbor_depth = 1
```

Types, ranges, cross-field constraints, and the distinction between
snapshot-identity settings and presentation/deadline settings are exactly
[EVC-8.2] and [EVC-8.3.1]. There is no repository ID, case root, manifest path,
proposal limit, activation option, or source-write option.

_Implementation mapping_:

- `backstitch/settings.py`

### 6.7 `[verify]` / `[tool.backstitch.verify]`

Packaged defaults contain exactly `enabled = false`. A disabled verifier has
one of two strict shapes: minimal disabled contains exactly
`enabled = false`; dormant complete contains `enabled = false` plus every
enabled base-table key required by [EVC-5], the provider table required by
`provider_source` when applicable, and an optional but complete
`[verify.eval]` table. Partial dormant tables are invalid. Dormant fields
receive the same unknown-key, type, range, nonblank, provider-identity, cost,
path, and internal cross-field validation as enabled fields, while disabled
verification performs no adapter construction, evaluation-corpus/report load,
cache access, or provider call. CLI layers apply before final shape
validation, so `--option verify.enabled true` can activate a dormant complete
table but makes a minimal disabled table fail for missing required keys.
The complete enabled base table, nested override provider table, types, ranges,
all-or-nothing `provider_source` rule, provider identity, cost, cache,
aggregation, and budget semantics are exactly [EVC-5].
The nested override provider is one atomic non-packaged file-layer group. It
contains exactly `backend_id`, `plugin_id`, `plugin_distribution_name`,
canonical-PURL `model`, nonblank raw `adapter_model_id`, `model_revision`,
`capability_schema_version`, `capability_revision`, `request_constraints`,
`maximum_input_bytes`, both cost-rate fields, `input_token_overhead`, and
`cost_rate_source`. Its authored capability constraints use [CFG-6.5]'s
concise TOML form and normalize to [SEM-3]'s closed null-bearing runtime
record; the `request_constraints` child set contains exactly the five fields
defined in [CFG-6.5]. If any group member is present, every member must be
present in that same file layer. The group replaces an inherited override as a unit; partial
inheritance, unknown or blank members, and generic-option edits are exit `2`.
This is a strict backward break for prior override tables with the historical
raw `model` spelling or without capability fields; Backstitch does not guess
their stable identity, transport selector, or capabilities.
The qualification subtable is exactly [EVC-10.1]:

```toml
[tool.backstitch.verify.eval]
mode = "report"
qualification_corpus = "tests/semantic_eval/v3/manifest.json"
qualification_corpus_sha256 = "sha256:<digest>"
qualification_report = "docs/evidence/verify-eval-report.json"
qualification_report_sha256 = "sha256:<digest>"
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

`verify.eval` is the sole promoting evaluation path. The superseded
`analyze.eval` table is always an unknown settings key. Only schema-2 report
objects remain readable through an explicit bounded historical report API;
that artifact API does not parse producer TOML and grants no current policy
authority. Enforce-mode paths, hashes, thresholds, sample
floors, strong-selector report binding, and composed analyzer/verifier identity
rules are exactly [EVC-6] and [EVC-10.1].

### 6.8 `[target_roots]` / `[tool.backstitch.target_roots]`

| Key | Type | Maps from |
|-----|------|-----------|
| `weft` | string | `BACKSTITCH_WEFT_ROOT` / sibling discovery ([SC-12]) |

Additional sibling names are reserved for future spec revisions.

### 6.9 Scan boundaries (ruff `exclude` analogue)

`exclude` and `extend_exclude` are configured at the top level of
`[tool.backstitch]` / `.backstitch.toml` — the same scope as `extend` and
`allow_unknown_keys` (§6.1) — not inside `[profile]`. They govern which paths
are skipped during spec discovery (`spec_roots`) and Python scan
(`code_roots`); they do not suppress findings on scanned files (that is
`[lint]`, per the exclusions spec [EXC-*]).

| Key | Type | Meaning |
|-----|------|---------|
| `exclude` | array of glob strings | Skip matching paths under `code_roots` and spec discovery |
| `extend_exclude` | array of glob strings | Additional excludes merged with defaults |

Default excludes in v1:

```text
.git
.venv
venv
__pycache__
.pytest_cache
.mypy_cache
.ruff_cache
dist
build
.worktrees
```

`exclude` replaces the default list. `extend_exclude` appends to the active
exclude list.

Placement example — valid:

```toml
[tool.backstitch]
extend_exclude = ["tests/fixtures/**"]

[tool.backstitch.profile]
name = "backstitch-style-v1"
spec_roots = ["docs/specs"]
code_roots = ["backstitch", "tests"]
```

Invalid under strict load — `extend_exclude` is not a profile field:

```toml
[tool.backstitch.profile]
extend_exclude = ["tests/fixtures/**"]  # -> unknown key ([CFG-8])
```

### 6.10 `extend` merge semantics

When `extend = "../other.toml"` is present:

1. Load the referenced file first (recursively applying its own `extend`).
2. Deep-merge tables: child keys override parent keys.
3. Scalar values in the child override the parent.
4. Array values in the child replace parent arrays for that key.
5. Resolve `extend` paths relative to the directory of the file that contains
   the `extend` key.

`diagnostics.levels` arrays append across config layers rather than replacing
earlier rules. Other arrays keep their replace semantics unless this spec says
otherwise.

Circular `extend` chains must error.

`exclude`, `extend_exclude`, `[profile]`, `[check]`, `[packets]`, `[analyze]`,
`[obligations]`, `[verify]`, `[target_roots]`, `[lint]`, `[diagnostics]`, and
`[coverage]` all have defaults in the packaged default TOML. Python dataclass
defaults may mirror those values for type construction, but the packaged TOML
is the behavioral source of truth.

### 6.11 Traceability exclusions

Lint-style suppressions (`meta_spec_globs`, `lint.per-file-ignores`,
`lint.per-section-ignores`, and related keys) are defined in
`docs/specs/04-backstitch-traceability-exclusions.md` [EXC-6] and are active
in v1. They are intentionally separate from `exclude` / `extend_exclude`,
which skip scanning.

[EXC-6] also defines `lint.require_suppression_declarations` and the closed
`[[lint.suppressions]]` array. Both standalone and `pyproject.toml` spellings
use the normal table prefix. They are parsed only by the canonical [CFG-5.1]
resolver and are present in the immutable settings snapshot.

### 6.12 Analogues intentionally omitted in v1

The following mypy/ruff options do **not** have v1 analogues:

- mypy-style per-module override tables like `[tool.mypy-foo.*]`
  (traceability suppression per file or section is available and lives in
  [EXC-6], not here)
- `include` / `files` default path lists (repo-scoped commands use
  `--repo-root` instead)
- formatter/linter rule toggles
- namespace package discovery flags

These may be proposed in a later spec revision with separate reference codes.

### 6.13 `[diagnostics]` / `[tool.backstitch.diagnostics]`

| Key | Type | Meaning |
|-----|------|---------|
| `default_level` | `"error"` \| `"warning"` \| `"info"` \| `"off"` | Base level before matching rules |
| `fail_on` | array of levels | Levels that make target-diagnostic commands exit `1` |
| `suppressible_levels` | array of levels | Effective levels eligible for suppression |

Diagnostic levels are configured by ordered array-of-table rules:

```toml
[[tool.backstitch.diagnostics.levels]]
select = ["MAPPING_PATH_INEXACT", "BSS007", "BSX*"]
level = "warning"
```

Rule selectors support canonical long codes, short codes, `*`, family prefixes
ending in `*`, and context selectors such as
`MAPPING_PATH_MISSING:plan-artifact`. Later matching rules win. Rules from
higher-precedence config layers are evaluated after packaged default rules, so
a repository can make every target diagnostic advisory with:

```toml
[tool.backstitch.diagnostics]
fail_on = []

[[tool.backstitch.diagnostics.levels]]
select = ["*"]
level = "info"
```

`off` hides the diagnostic from normal output but keeps it visible in the
suppression/audit view.

### 6.14 `[coverage]` / `[tool.backstitch.coverage]`

The coverage table is closed:

| Key | Type and range | Packaged value |
|---|---|---|
| `mode` | `"report"` or `"ratchet"` | `"report"` |
| `format` | `"text"` or `"json"` | `"text"` |
| `output` | nonblank path string or absent | absent |
| `granularity` | exact literal `"definition"` | `"definition"` |
| `inherited_counts` | boolean | `false` |
| `ratchet_base` | string; nonblank only when ratchet runs | `""` |
| `maximum_baseline_files` | positive integer, excluding booleans | `20000` |
| `maximum_file_bytes` | positive integer, excluding booleans | `5000000` |
| `maximum_baseline_bytes` | positive integer, excluding booleans | `100000000` |
| `maximum_history_commits` | positive integer, excluding booleans | `1000` |
| `maximum_git_command_seconds` | positive finite number | `10.0` |
| `maximum_git_commands` | positive integer, excluding booleans | `64` |
| `maximum_git_output_bytes` | positive integer, excluding booleans | `100000000` |
| `maximum_commit_message_bytes` | positive integer, excluding booleans | `1000000` |
| `maximum_runtime_seconds` | positive finite number | `60.0` |
| `exemptions` | array of closed exemption tables below | `[]` |
| `floors` | table keyed by canonical repository-relative directory scope | `{}` |

Each `[[coverage.exemptions]]` row contains exactly one of `path` or `glob`
plus `reason`. Selectors are nonblank repository-relative POSIX strings with
no absolute prefix, backslash, `.`/`..` segment, CR, LF, or NUL. `path` uses
canonical path equality; `glob` uses the existing repository-glob matcher.
Reasons obey [COV-4]'s NFC, line-safety, and 4096-byte rules. A floor child
contains only optional `direct` and `accounted` finite numbers in `[0,1]` and
must contain at least one. Its canonical scope must equal or be nested within
a final effective code root.

Coverage scalars use ordinary later-layer replacement. `coverage.exemptions`
is an array and therefore replaces across `extend`; authored row order remains
provenance but not classification priority. `coverage.floors` follows ordinary
deep-table merge by exact canonical scope, with a later `direct` or
`accounted` leaf replacing that leaf. Selectors and floor scopes are anchored
to the accepted repository root, not the contributing config directory.
Configured `output` follows the existing contributing-layer path anchoring;
CLI `--output` follows current-working-directory anchoring. The immutable
settings snapshot retains contributing-layer provenance for every effective
coverage and policy input required by [COV-5].

`format` and `output` are presentation-only and may be set by dedicated
coverage flags. All other leaves are behavior or authority inputs. Report mode
admits normal generic-option precedence for runtime-consulted scalar leaves;
`exemptions`, `floors`, and their members are non-leaf and cannot be addressed
through `--option`. Ratchet mode rejects every generic option and explicit
config/profile selection as [COV-9] requires.

## 7. CLI Additions [CFG-7]

With no explicit subcommand, global `--config`, `--no-config`, and
`--option` controls retain their normal syntax. Resolution anchors at the
current working directory. `--config PATH` may select a file whose
`default_command` enables dispatch; `--no-config` observes the packaged
`false` value and therefore returns the missing-command exit `2`.
`--help` and `--version` remain parser-only operations and do not resolve
repository configuration. Remaining arguments are forwarded to the selected
default command. A leading path is its `--repo-root` shorthand, so
`backstitch .` is valid; bare analyze also accepts `--model`, with the same
CLI-over-environment-over-file precedence as explicit analyze.

Bare invocation is a local convenience over repository configuration, not a
hostile-target automation primitive. Selecting `"analyze"` authorizes the
same credential, network, cache, and bounded-cost behavior as explicit
current-repository analyze. Selecting `"check"` authorizes the same configured
report output behavior as explicit check. Secret-bearing hostile-target
workflows must not use bare invocation; [SEM-9] and [EVC-11]'s explicit
trusted-command/config/override boundary remains mandatory.
This restriction is enforced at the workflow contract and test boundary;
the CLI does not guess operator intent or trust from the same process inputs.

`backstitch` must add:

```bash
backstitch --config PATH <command> ...
backstitch --no-config <command> ...
backstitch --option KEY VALUE <command> ...
backstitch <command> --option KEY VALUE ...
backstitch config show [--repo-root PATH]
backstitch config path [--repo-root PATH]
```

`--option` is repeatable and follows [CFG-5.1]. `config show` applies and
renders the same final option layer as runtime commands. `config path` resolves
and validates the same request, then prints only the selected path. A command
that does not consume configuration rejects all configuration controls.

`--no-config` skips repository discovery and explicit repository config, then
runs with packaged defaults plus CLI/env overrides. It exists so behavior with
and without repository configuration can be compared and tested in isolation;
`--config` and `--no-config` together are a usage error (exit `2`).

Boolean config keys that have CLI equivalents must expose **both** flag
polarities — for example `--warnings-as-errors | --no-warnings-as-errors` on
`check`. The explicit negation exists so CI and tests can override a
config-set `warnings_as_errors = true` for one invocation without editing
files; CLI always beats config ([CFG-5]).

`config show` exit behavior follows the same strictness as loading: a valid
config prints the effective resolved settings as JSON on stdout and exits
`0`; unknown keys under the default strict mode print the load diagnostics
and exit `2` (there are no "effective settings" to show for a config that
does not load); under `allow_unknown_keys = true` it prints the effective
settings, warns about the unknown keys on stderr, and exits `0`.

`config path` continues to report only the discovered or explicit repository
configuration path. It does not print the packaged default resource path. When
no repository config is found, or when `--no-config` is used, it prints nothing
and exits `0`. `config show` is the command that displays the packaged default
layer and the full effective settings.

Existing commands keep their flags. When a flag is provided, it overrides config
for that invocation.

Update [SC-5] usage examples to show optional config-driven defaults:

```bash
backstitch check --repo-root .
backstitch analyze --packets packets.jsonl --packet-report packet-report.json --output analysis.jsonl
```

_Implementation mapping_:
- `backstitch/cli.py`

## 8. Failure Modes And Edge Cases [CFG-8]

The loader must fail with exit code `2` and a clear message when:

- `--config` points to a missing or unreadable file
- TOML syntax is invalid — including any TOML file examined during the
  discovery walk ([CFG-3]): a `pyproject.toml` that does not parse cannot be
  checked for a `[tool.backstitch]` table and must be exit `2` naming the
  file, never a silent skip to the next ancestor
- `extend` is cyclic or points to a missing file
- a required typed field has the wrong type
- `profile` names an unknown built-in profile
- `check.format` or `analyze.concurrency` is outside supported values
- duplicate short diagnostic codes in the packaged registry
- implemented diagnostics missing a default level rule
- diagnostic selectors that match no known implemented, deprecated, or
  redirected code, unless `allow_unknown_keys = true`
- invalid diagnostic level values
- reserved diagnostic codes used as ordinary suppressions
- a nonempty effective `test_root` is not equal to or nested under any final
  effective `code_root`
- any semantic value, range, enum, duplicate, path, cross-field combination,
  cost contract, eval qualification setting, disposition, or failure-authority
  rule violates [SEM-5], [SEM-6], or [SEM-9]
- any obligation limit, role set, snapshot/packet relation, verifier enabled
  shape, provider-source/override relation, verify-eval selector, composed
  identity, or qualification rule violates [EVC-5], [EVC-6], [EVC-8.3.1], or
  [EVC-10.1]
- current analyze, historical analyze, obligation, guide, or conditional MCP
  flags violate [EVC-5.1] or [EVC-8.3]
- `--option` has the wrong arity, contains NUL/CR/LF, has a malformed dotted
  key, names an unknown, non-leaf, reserved/non-consulted, or load-time key,
  repeats a key, conflicts with a dedicated CLI flag, parses as more than one
  synthetic TOML assignment, or produces a value that fails the existing
  type, range, identity, containment, or cross-field validation
- `default_command` has a type or value other than `false`, `"check"`, or
  `"analyze"`: exit `2` before command, snapshot, cache, provider, or output
  work
- an explicit config-consuming command has an invalid `default_command`:
  the explicit command still wins selection, but strict validation rejects
  the invalid known value with exit `2` before command work
- bare invocation resolves effective `default_command = false`: exit `2`
  with the missing-command error and no fallback command
- bare invocation has an invalid global config control or generic option:
  exit `2` before default dispatch
- any coverage key is unknown, has the wrong type/range, violates the closed
  exemption/floor shape, has an invalid repository-relative selector/scope,
  or uses ratchet without a nonblank base
- coverage ratchet receives a forbidden CLI/config/profile/option source, a
  gate input with non-repository provenance, a mismatched
  `--require-ratchet`, an unavailable ref/merge base/object, or a configured
  budget that is exceeded

For `analyze.concurrency`: values below `1` are invalid (exit `2`). Support
for values above `1` is optional in v1 — an implementation that declines must
reject them with exit `2` and a clear message, and one that accepts them must
preserve [SC-7] deterministic output ordering. Silently accepting a
concurrency value and running serially is not permitted.

Unknown keys inside backstitch's namespace (`[tool.backstitch]` or a
`.backstitch.toml` document) are load errors: exit `2`, naming the key and the
file. A typo'd key that silently does nothing is a fake affordance — the
configuration appears to work while changing nothing, which is precisely the
failure mode this tool exists to catch. Setting `allow_unknown_keys = true`
downgrades unknown keys to stderr warnings; it is the forward-compatibility
escape hatch for configs shared with newer backstitch versions, and it must
never suppress type errors on *known* keys. `config show` follows the same
rule — exit `2` with diagnostics in strict mode, settings plus stderr
warnings under the hatch ([CFG-7]).

When no repository config file is discovered, commands still load the packaged
default TOML and then apply CLI/env overrides.

An empty effective test-root set is a valid partial scan, not a switch that
disables invariant diagnostics. Required declarations found in the selected
code roots remain untested when their tests were intentionally omitted.

A malformed structured suppression table or declaration-reference value is
a config error and exits `2` before snapshot capture or provider work.
Config-time reference validation is syntax-only: nonblank repo-relative
POSIX path, one valid `#SUP-ID`, no absolute path, backslash, glob, control
character, or extra fragment. Whether that path is inside an effective
`spec_root`, exists in the accepted snapshot, and owns a valid declaration is
snapshot-derived target truth governed by [EXC-8], not a second config read.

_Implementation mapping_:
- `backstitch/diagnostics.py`
- `backstitch/exclusions.py`
- `backstitch/grammar.py`
- `backstitch/settings.py`

## 9. Verification Expectations [CFG-9]

<!-- backstitch: meta because docs/specs/04-backstitch-traceability-exclusions.md#SUP-VERIFICATION-META -->

Required proof:

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
- unit tests for discovery boundaries, including stop-at-`$HOME` behavior
- unit tests for `.backstitch.toml` precedence over `pyproject.toml` in the same
  directory
- unit tests for `extend` merge and cycle detection
- unit tests for path/`~`/env expansion
- CLI subprocess tests proving config changes default `--profile`, roots, and
  `analyze` model selection
- tests proving CLI flags and `BACKSTITCH_WEFT_ROOT` override config
- `config show` / `config path` subprocess tests
- `config show` must include the packaged default config layer and resolved
  diagnostic policy
- `config path` must keep its repository-config meaning: it prints no path for
  packaged defaults and prints nothing under `--no-config`
- tests must prove `--no-config` still loads packaged defaults
- tests must prove a repo-level `select = ["*"]` rule can override packaged
  default specific rules
- tests must prove short codes and long codes canonicalize to the same
  diagnostic identity
- tests cover packaged `test_roots`, paired config and CLI overrides, a lone
  `--test-root`, containment failure, production-only code-root overrides, and
  a custom test path not named `tests`
- a dogfood-delta test: this repository's committed configuration must produce
  an observable difference against `--no-config`, asserted by a test, so a
  regression that makes config loading silently no-op fails CI instead of
  passing quietly
- no-op prevention per key: every config key that affects behavior has at
  least one test proving it changes observable output (report content, exit
  code, packet content, or model selection) compared with `--no-config` or
  the built-in default. This catches the partial-implementation failure where
  `config show` reflects a key that `check`, `packets`, or `analyze` never
actually consults
- every `[obligations]`, enabled/disabled `[verify]`, nested provider, and
  `[verify.eval]` key has a firing or no-op-prevention test; tests cover
  snapshot-identity versus presentation-only changes, provider reuse and
  override, absent/equal/different CLI and environment models, qualification
  report identity, and strong-selector authorization
- superseded case-root, case-manifest, proposal, activation, source-write, and
  `analyze.eval` producer keys are exercised as unknown keys. Under the
  explicit `allow_unknown_keys = true` forward-compatibility hatch they remain
  named warnings and confer no behavior or authority; they are never silently
  accepted as aliases
- the full [SEM-9] matrix has firing tests for packaged defaults, exact types
  and ranges, zero sentinels, cache/json combinations, plugin distribution
  identity, path anchoring, cost overhead, eval thresholds/sample units,
  duplicate dispositions, and final semantic failure authority
- packaged defaults set `default_command = false`, while Backstitch's
  committed repository config sets `"analyze"`; `config show` proves that
  selection without provider work, explicit `backstitch check` remains the
  zero-error, zero-warning hermetic self-corpus gate, and controlled-adapter
  tests prove bare analyze equivalence
- standalone and `pyproject.toml` configs can select each allowed command
- an extended child inherits, replaces, and disables a parent default under
  ordinary scalar precedence
- `config show` renders normalized `default_command` as `null`, `"check"`,
  or `"analyze"`
- explicit commands, `--help`, and `--version` never redirect through the
  configured default
- default `check` remains structurally provider-free, and default `analyze`
  retains the current deterministic-before-provider boundary
- bare analyze includes `LLM_MODEL` in the canonical environment layer while
  bare check excludes it; both paths resolve file configuration exactly once
  and pass the same immutable settings snapshot into the selected handler
- cached `LLM_MODEL` and `--model` selection resolves the exact matching flat
  or catalog descriptor, rejects unknown/partial/ambiguous descriptors before
  cache/provider work, and never retains another model's revision or rates
- every flat descriptor member is atomic across file and `extend` layers; a
  partial child cannot inherit identity or rates, every non-model descriptor
  leaf is rejected through generic `--option`, and both `--model` forms still
  select a complete trusted descriptor
- both `result_reuse` values fire through real immutable cache objects:
  evidence-stable selection retains the baseline result and its producer
  provenance, while exact-inference selection uses only the selected
  provider's `analysis_key`
- a configured `check.output` write and a bounded provider-capable analyze
  invocation match their explicit-command behavior in local tests, while
  trusted hostile-target workflows are statically checked to retain explicit
  commands and trusted config selection
- direct resolver tests distinguish legacy non-CLI resolution, explicit
  command resolution, and bare-command selection, and prove identical
  settings/model provenance reaches explicit and bare analyze without a
  second raw config assembly
- malformed values, disabled bare invocation, and invalid global controls
  fire their exact exit-`2` paths with no traceback
- every coverage scalar, exemption selector/reason branch, and floor leaf has
  a firing or no-op-prevention test; tests cover packaged values, report-mode
  precedence, `extend` replacement/deep merge, path anchoring, unknown keys,
  invalid types/ranges/shapes, and `config show`
- ratchet tests enumerate every forbidden provenance/CLI contribution,
  repository-owned layer condition, literal `--require-ratchet REF` match and
  mismatch, and show that presentation-only format/output overrides cannot
  change the canonical policy identity
- `ruff` and `mypy` over new loader modules

`lint.require_suppression_declarations` and every field of
`lint.suppressions` have firing, wrong-type, closed-shape, precedence,
`extend`, `config show`, and generic `--option` coverage where the value is a
scalar option leaf. `lint.suppressions` itself is not settable through
`--option`; [CFG-5.1]'s existing unknown/non-leaf rejection applies.

Do not call external LLMs in config tests. Use fake adapters for `analyze`
configuration integration tests. Optional live LLM tests — whether against a
cloud provider or a local OpenAI-compatible endpoint — belong to [SC-7]'s
semantic-analysis verification path and must not be used as no-op-prevention
proof for configuration keys. Local-endpoint model wiring (`api_base` and
model registration via `llm`'s `extra-openai-models.yaml`) is `llm`/provider
environment configuration, not a backstitch configuration key, and must not
introduce provider-specific handling into backstitch's configuration loader or
runtime modules. A local-endpoint live test uses an ephemeral per-test `llm`
configuration directory (for example via `LLM_USER_PATH`) and does not read
the global `llm` config; this wiring is outside Backstitch config and must not
be treated as proof for any Backstitch config key.

## 10. Documentation And Traceability [CFG-10]

<!-- backstitch: meta because docs/specs/04-backstitch-traceability-exclusions.md#SUP-DOCUMENTATION-META -->

Implementation must update:

- `docs/specs/02-backstitch-core.md` cross-links for [SC-3], [SC-5], [SC-7],
  [SC-12]
- `docs/implementation/04-backstitch-style-traceability.md` (configuration
  boundary and precedence)
- `docs/implementation/02-repository-map.md` (new modules)
- `docs/specs/00-specs-index.md`
- `README.md` documents configured bare invocation, its exact command
  equivalences, and the explicit trust/cost warning for `"analyze"`

## Related Plans

- `docs/plans/2026-08-23-gpt-5-6-luna-responses-plan.md`
  (active implementation plan; request capabilities, Responses migration,
  and release qualification)
- `docs/plans/2026-07-29-usability-remediation-plan.md`
  (active usability implementation plan; [CFG-5.1] and [CFG-6.5])
- `docs/plans/2026-07-29-architecture-quality-remediation-plan.md`
  (active implementation plan; [CFG-4], [CFG-5.1], and [CFG-9])
- `docs/plans/2026-07-28-intent-coverage-implementation-plan.md`
  (active implementation plan; [CFG-3], [CFG-5], [CFG-6], [CFG-8], and
  [CFG-9] coverage registrations)
- `docs/plans/2026-07-28-evidence-stable-semantic-result-reuse-plan.md`
  (specification and implementation plan)
- `docs/plans/2026-07-28-configured-default-command-plan.md`
  (implemented and independently reviewed; uncommitted)
- `docs/plans/2026-07-28-documented-suppression-governance-plan.md`
  (implemented and independently reviewed)

- `docs/plans/2026-07-15-agent-guided-evidence-cases-plan.md`
  (implementing)
- `docs/plans/2026-07-11-deterministic-semantic-gate-plan.md`
  (implementing)
- `docs/plans/2026-07-27-canonical-config-resolution-plan.md`
  (implementation and verification recorded)
- `docs/plans/2026-07-09-backstitch-invariant-traceability-plan.md`
  (implemented)
- `docs/plans/2026-07-08-configurable-diagnostics-plan.md` (implementing)
- `docs/plans/2026-07-06-local-model-catalog-and-doctor-plan.md` (implementing)
- `docs/plans/2026-07-06-backstitch-organization-refactor-plan.md` (implementing)
- `docs/plans/2026-07-03-live-llm-tests-plan.md` (implementing)
- `docs/plans/2026-07-02-backstitch-four-way-reconciliation-plan.md` (implementing)
- `docs/plans/2026-07-01-backstitch-toml-configuration-plan.md`
- `docs/plans/2026-07-02-backstitch-traceability-exclusions-plan.md`
