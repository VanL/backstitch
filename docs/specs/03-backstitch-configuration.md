# Backstitch Configuration Specification

Status: Active

This spec defines how `backstitch` discovers, loads, validates, and applies
project configuration from TOML files. It governs defaults for CLI commands
without replacing explicit CLI flags.

Related core behavior: `docs/specs/02-backstitch-core.md` [SC-3], [SC-5], [SC-7],
[SC-12].

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
- **Effective settings**: the merged result of `extend` inheritance, discovered
  file values, environment overrides where applicable, and CLI flags.
- **Profile overlay**: config may set a built-in profile name and override
  profile fields such as roots and globs without defining a new parser profile.

Configuration must reduce repetition. It must not hide behavior that changes
deterministic outcomes without an explicit, inspectable source.

_Implementation mapping_:
- `backstitch/settings.py`

## 3. Discovery [CFG-3]

### 3.1 Discovery anchors

| Command | Discovery anchor |
|---------|------------------|
| `check` | `--repo-root` after `resolve()` |
| `packets` | `--repo-root` after `resolve()` |
| `analyze` | parent directory of `--packets` after `resolve()` |
| `summarize-analysis` | no discovery in v1; CLI args only |

If `--config` is provided ([CFG-5]), discovery is skipped and that file is the
sole config source (still subject to CLI/env precedence above file values).

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
- `backstitch/settings.py`

## 5. Precedence [CFG-5]

Effective settings are assembled in this order (later sources override earlier
ones):

1. built-in profile defaults from `backstitch/profiles.py`
2. discovered config file, after `extend` merge ([CFG-6])
3. environment variables where this spec defines them
4. explicit CLI flags and options

Environment variables in v1:

| Variable | Affects | Notes |
|----------|---------|-------|
| `BACKSTITCH_WEFT_ROOT` | sibling Weft discovery | overrides `target_roots.weft` |
| `LLM_MODEL` | `analyze` model fallback | overrides `analyze.model` when `--model` omitted |

CLI flags always beat config and environment for the same setting.

`--config PATH` selects a specific file and bypasses upward discovery. Relative
`PATH` values are resolved against the process working directory.

_Implementation mapping_:
- `backstitch/settings.py`
- `backstitch/cli.py`
- `backstitch/analysis_llm.py`
- `backstitch/target_roots.py`

## 6. Schema [CFG-6]

### 6.1 Top-level keys

| Key | Type | Applies to | Meaning |
|-----|------|------------|---------|
| `extend` | string | all commands | Load and merge another config first |
| `allow_unknown_keys` | bool | load time | Downgrade unknown-key errors to warnings (default `false`) |
| `exclude` | array of glob strings | scan | Replace default scan excludes ([CFG-6.7]); applies to spec discovery and code scan |
| `extend_exclude` | array of glob strings | scan | Append to the active exclude list ([CFG-6.7]); applies to spec discovery and code scan |

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
| `planned_spec_globs` | array of strings | Weft-style planned docs |
| `exploratory_spec_globs` | array of strings | Weft-style exploratory docs |

Array overrides replace the built-in profile lists; they do not append unless
`extend` already established a base list and the child file repeats the full
intended list.

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

### 6.5 `[analyze]` / `[tool.backstitch.analyze]`

| Key | Type | Maps from |
|-----|------|-----------|
| `model` | string | CLI `--model` default |
| `concurrency` | integer | CLI `--concurrency` |

### 6.6 `[target_roots]` / `[tool.backstitch.target_roots]`

| Key | Type | Maps from |
|-----|------|-----------|
| `weft` | string | `BACKSTITCH_WEFT_ROOT` / sibling discovery ([SC-12]) |

Additional sibling names are reserved for future spec revisions.

### 6.7 Scan boundaries (ruff `exclude` analogue)

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

### 6.8 `extend` merge semantics

When `extend = "../other.toml"` is present:

1. Load the referenced file first (recursively applying its own `extend`).
2. Deep-merge tables: child keys override parent keys.
3. Scalar values in the child override the parent.
4. Array values in the child replace parent arrays for that key.
5. Resolve `extend` paths relative to the directory of the file that contains
   the `extend` key.

Circular `extend` chains must error.

### 6.9 Traceability exclusions

Lint-style suppressions (`meta_spec_globs`, `lint.per-file-ignores`,
`lint.per-section-ignores`, and related keys) are defined in
`docs/specs/04-backstitch-traceability-exclusions.md` [EXC-6] and are active
in v1. They are intentionally separate from `exclude` / `extend_exclude`,
which skip scanning.

### 6.10 Analogues intentionally omitted in v1

The following mypy/ruff options do **not** have v1 analogues:

- mypy-style per-module override tables like `[tool.mypy-foo.*]`
  (traceability suppression per file or section is available and lives in
  [EXC-6], not here)
- `include` / `files` default path lists (repo-scoped commands use
  `--repo-root` instead)
- formatter/linter rule toggles
- namespace package discovery flags

These may be proposed in a later spec revision with separate reference codes.

_Implementation mapping_:
- `backstitch/settings.py`
- `backstitch/config.py`
- `backstitch/profiles.py`
- `backstitch/markdown_specs.py`
- `backstitch/python_refs.py`
- `backstitch/resolver.py`
- `backstitch/target_roots.py`

## 7. CLI Additions [CFG-7]

`backstitch` must add:

```bash
backstitch --config PATH <command> ...
backstitch --no-config <command> ...
backstitch config show [--repo-root PATH]
backstitch config path [--repo-root PATH]
```

`--no-config` skips discovery entirely and runs with built-in defaults plus
CLI/env overrides. It exists so behavior with and without repository
configuration can be compared and tested in isolation; `--config` and
`--no-config` together are a usage error (exit `2`).

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

`config path` prints the absolute path of the discovered config file, or prints
nothing and exits `0` when no config is found.

Existing commands keep their flags. When a flag is provided, it overrides config
for that invocation.

Update [SC-5] usage examples to show optional config-driven defaults:

```bash
backstitch check --repo-root .
backstitch analyze --packets packets.jsonl --output analysis.jsonl
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

When no config file is discovered, commands behave as they do today using
built-in defaults plus CLI/env overrides.

_Implementation mapping_:
- `backstitch/settings.py`

## 9. Verification Expectations [CFG-9]

Required proof:

- unit tests for discovery boundaries, including stop-at-`$HOME` behavior
- unit tests for `.backstitch.toml` precedence over `pyproject.toml` in the same
  directory
- unit tests for `extend` merge and cycle detection
- unit tests for path/`~`/env expansion
- CLI subprocess tests proving config changes default `--profile`, roots, and
  `analyze` model selection
- tests proving CLI flags and `BACKSTITCH_WEFT_ROOT` override config
- `config show` / `config path` subprocess tests
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
- `ruff` and `mypy` over new loader modules

Do not call external LLMs in config tests. Use fake adapters for `analyze`
configuration integration tests. Optional live LLM tests belong to [SC-7]'s
semantic-analysis verification path and must not be used as no-op-prevention
proof for configuration keys.

_Implementation mapping_:
- `tests/test_settings.py`
- `tests/test_cli.py`

## 10. Documentation And Traceability [CFG-10]

Implementation must update:

- `docs/specs/02-backstitch-core.md` cross-links for [SC-3], [SC-5], [SC-7],
  [SC-12]
- `docs/implementation/04-backstitch-style-traceability.md` (configuration
  boundary and precedence)
- `docs/implementation/02-repository-map.md` (new modules)
- `docs/specs/00-specs-index.md`

_Implementation mapping_:
- `docs/implementation/02-repository-map.md`
- `docs/implementation/04-backstitch-style-traceability.md`

## Related Plans

- `docs/plans/2026-07-03-live-llm-tests-plan.md` (implementing)
- `docs/plans/2026-07-02-backstitch-four-way-reconciliation-plan.md` (implementing)
- `docs/plans/2026-07-01-backstitch-toml-configuration-plan.md`
- `docs/plans/2026-07-02-backstitch-traceability-exclusions-plan.md`