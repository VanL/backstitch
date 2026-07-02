# Backstitch TOML Configuration Plan

Status: archival — written against the `implement-backstitch` branch during
the four-way bake-off. The go-forward base is `impl-fable-5`; a new
reconciliation plan will supersede this one. Where this plan and
`docs/specs/03-backstitch-configuration.md` disagree, the spec is
authoritative (notably: unknown config keys are load errors by default, not
warnings).

Source specs:

- `docs/specs/03-backstitch-configuration.md` [CFG-1]–[CFG-10]
- `docs/specs/02-backstitch-core.md` [SC-3], [SC-5], [SC-7], [SC-12]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-11]

Depends on: `implement-backstitch` branch (current CLI, profiles, target roots,
`resolve_model_name`)

## Goal

Add repository-local TOML configuration for `backstitch`, discovered by walking
up from a command-specific anchor directory until `$HOME` (never above it).
Support standalone `.backstitch.toml` and `[tool.backstitch]` in `pyproject.toml`,
with `.backstitch.toml` taking precedence in the same directory.

Use mypy and ruff configuration patterns as design guidance: closest-config
wins, optional `extend`, `pyproject.toml` only when the tool section exists,
`exclude`/`extend-exclude` scan boundaries, `warn_unused_keys` diagnostics, and
CLI/`--config` overrides — while keeping the v1 schema narrow and aligned with
existing `ProfileConfig`, CLI flags, and env overrides.

## Source Documents

Read in this order:

1. `AGENTS.md`
2. `docs/agent-context/decision-hierarchy.md`
3. `docs/agent-context/runbooks/writing-plans.md`
4. `docs/agent-context/runbooks/hardening-plans.md` (required — public contract
   change)
5. `docs/agent-context/runbooks/writing-specs.md`
6. `docs/specs/03-backstitch-configuration.md` [CFG-1]–[CFG-10]
7. `docs/specs/02-backstitch-core.md` [SC-3], [SC-5], [SC-7], [SC-12]
8. `pyproject.toml` — note `[tool.mypy]`, `[tool.ruff]`, `[tool.ruff.lint]`
   patterns in this repository
9. `backstitch/cli.py`, `backstitch/config.py`, `backstitch/profiles.py`,
   `backstitch/target_roots.py`, `backstitch/analysis_llm.py`

Comprehension checks before implementation:

- Why must discovery stop at `$HOME` rather than the filesystem root?
- Why must `.backstitch.toml` beat `pyproject.toml` in the same directory?
- Why must `backstitch check` remain free of `llm` calls even if
  `[tool.backstitch.analyze]` sets a model?
- When both config and `--spec-root` are present, which wins?

## Context and Key Files

### Current behavior (branch `implement-backstitch`)

| Path | Current role |
|------|----------------|
| `backstitch/cli.py` | Argparse for `check`, `packets`, `analyze`, `summarize-analysis`; defaults hard-coded |
| `backstitch/config.py` | `ProfileConfig` dataclass + `with_overrides()` |
| `backstitch/profiles.py` | Built-in `backstitch-style-v1` defaults; `weft_profile()` helper |
| `backstitch/target_roots.py` | `BACKSTITCH_WEFT_ROOT` env + sibling discovery |
| `backstitch/analysis_llm.py` | `resolve_model_name()` — CLI → `LLM_MODEL` → `llm.get_default_model()` |
| `backstitch/resolver.py` | No exclude globs today; scans all files under roots |
| `tests/test_cli.py` | Subprocess CLI tests |
| `pyproject.toml` | `[tool.mypy]`, `[tool.ruff]` — precedent for `[tool.backstitch]` |

There is no config loader today. CLI flags are the only project-level defaults
besides built-in profiles.

### mypy / ruff options mapped to backstitch v1

| Source tool | Option | Backstitch v1 analogue | Notes |
|-------------|--------|------------------------|-------|
| ruff | closest config wins | [CFG-3] upward discovery | No per-directory merge across ancestors without `extend` |
| ruff | `.ruff.toml` > `pyproject.toml` | `.backstitch.toml` > `pyproject.toml` | Same directory only |
| ruff | `extend` | `extend` | Deep-merge tables; child scalars/arrays win |
| ruff | `exclude` / `extend-exclude` | `exclude` / `extend_exclude` | Applied during spec/code file discovery |
| ruff | `--config` | `--config` | Bypass discovery |
| mypy | walk up to repo/root | walk up to `$HOME` | User-requested boundary |
| mypy | `warn_unused_configs` | `warn_unused_keys` | stderr warning, non-fatal by default |
| mypy | `[tool.mypy]` in pyproject | `[tool.backstitch]` | Ignore pyproject without section |
| mypy | per-module sections | — | Out of scope v1 |
| ruff | `per-file-ignores` | — | Out of scope v1 |
| mypy | `files` / `packages` | — | Replaced by `--repo-root` + profile roots |
| ruff | `line-length`, lint `select` | — | Not applicable |

### Files to create

| Path | Purpose |
|------|---------|
| `docs/specs/03-backstitch-configuration.md` | Source-of-truth config spec [CFG-*] |
| `backstitch/settings.py` | Discovery, load, merge, validate, effective settings |
| `tests/test_settings.py` | Loader unit tests |
| `tests/fixtures/config_project/.backstitch.toml` | Discovery/merge fixtures |
| `tests/fixtures/config_project/pyproject.toml` | pyproject precedence fixture |

### Files to modify

| Path | Change |
|------|--------|
| `backstitch/cli.py` | Global `--config`; `config show`/`config path`; apply settings |
| `backstitch/config.py` | Optional: `ProfileConfig.from_settings()` helper |
| `backstitch/target_roots.py` | Accept configured `weft` path before sibling discovery |
| `backstitch/markdown_specs.py` | Honor `exclude` globs during discovery |
| `backstitch/python_refs.py` or resolver | Honor `exclude` for code scans |
| `backstitch/analysis_llm.py` | Consult settings model before env/llm default |
| `docs/specs/00-specs-index.md` | Add spec 03 |
| `docs/specs/02-backstitch-core.md` | Cross-link config spec; relax [SC-5] `--model` wording |
| `docs/implementation/02-repository-map.md` | New module map |
| `docs/implementation/04-backstitch-style-traceability.md` | Config precedence |
| `pyproject.toml` | Example `[tool.backstitch]` for this repo (optional but recommended) |

## Invariants and Constraints

These must remain true:

- `backstitch check` and packet **input generation** must not call `llm` or
  network services ([SC-4], [SC-5]), regardless of config contents.
- Deterministic issue codes and severities must not change because config exists
  ([SC-11]).
- CLI explicit flags override config for the same setting ([CFG-5]).
- `BACKSTITCH_WEFT_ROOT` and `LLM_MODEL` env vars override config values ([CFG-5]).
- Built-in profile names remain the only profile identifiers in v1 ([SC-3]).
- Config must not introduce a parser plugin language ([SC-8]).
- Discovery must never search above `$HOME` ([CFG-3]).
- No new runtime dependencies: use stdlib `tomllib` (Python 3.14+).
- Backward compatibility: repos without config files behave exactly as today.

### Hidden couplings

- `exclude` must be applied consistently in **both** spec discovery and code scan
  paths, or files will appear in one graph view but not another.
- `extend` path resolution must use the containing file's directory, not the
  discovery anchor or cwd.
- `analyze` settings apply only when `resolve_model_name()` runs; do not import
  `llm` during config load.
- Worktree checkouts must resolve relative config paths against the config file
  location, not the worktree path tricks in `target_roots.py`.

### Rollback / rollout

- Rollback: remove new modules and CLI subcommand; revert spec docs. No migration
  needed because config is opt-in.
- Rollout: land spec + implementation together; add example `[tool.backstitch]`
  to this repo only after loader tests pass.
- Success signal: `backstitch config show --repo-root .` prints JSON with
  expected profile/roots on a fixture repo.

## Tasks

### 1. Spec and index (complete with this plan)

- Files: `docs/specs/03-backstitch-configuration.md`,
  `docs/specs/00-specs-index.md`, `docs/specs/02-backstitch-core.md` backlinks
- Outcome: [CFG-1]–[CFG-10] published; core spec cross-links updated
- Done when: spec backlinks to this plan and cites [SC-*] cross-links

### 2. Add settings model and TOML loader

- Files: `backstitch/settings.py`
- Read first: [CFG-3], [CFG-4], [CFG-6], [CFG-8]
- Implement:
  - `discover_config(anchor: Path, *, config_path: Path | None) -> Path | None`
  - `load_settings(path: Path) -> RawSettings`
  - `resolve_settings(raw, *, config_dir: Path) -> BackstitchSettings`
  - `apply_extend()` with cycle detection
  - `expand_path_value()` for `~` and env vars
  - dataclasses for `ProfileSettings`, `CheckSettings`, `AnalyzeSettings`,
    `TargetRootSettings`, `ScanSettings`
- Reuse `ProfileConfig` shape from `backstitch/config.py`; do not fork profile
  fields into a parallel type hierarchy
- Stop gate: if `extend` merge semantics are unclear in tests, stop and revise
  spec before wiring CLI

### 3. Wire CLI resolution layer

- Files: `backstitch/cli.py`
- Add global `--config` on root parser (stored before subcommand dispatch)
- Add `config show` and `config path` subcommands
- For each command, build effective args:
  1. defaults
  2. discovered settings
  3. env overrides (target roots, analyze model)
  4. argparse values (treat `None`/unset as “not provided” so config can show
     through)
- Update `_profile_for_args()` to accept settings overlay
- Done signal: `check --repo-root fixture` uses config profile/roots when flags
  omitted

### 4. Apply scan excludes

- Files: `backstitch/markdown_specs.py`, code scan entry in `resolver.py` or
  `python_refs.py`
- Read first: current `discover_spec_files()` and code root walking
- Implement glob filtering using `pathlib.Path.match` or `fnmatch` with
  repo-relative patterns
- Default excludes from [CFG-6.7]
- Stop gate: if excludes only apply to code scans, fix before merging

### 5. Integrate target root and analyze settings

- Files: `backstitch/target_roots.py`, `backstitch/analysis_llm.py`
- `discover_sibling_repo("weft")` consults `settings.target_roots.weft` before
  sibling search
- `resolve_model_name()` order becomes: explicit CLI → settings.analyze.model →
  `LLM_MODEL` → `llm.get_default_model()`
- Tests must prove env still beats config

### 6. Tests

- Files: `tests/test_settings.py`, extend `tests/test_cli.py`,
  `tests/test_target_roots.py`, `tests/test_analysis_llm.py`
- Fixture repos under `tests/fixtures/config_project/`
- Cases:
  - nearest config wins across parent/child directories
  - stop at `$HOME` (mock `Path.home()`)
  - `.backstitch.toml` beats `pyproject.toml`
  - pyproject without `[tool.backstitch]` ignored
  - malformed TOML → exit 2
  - `extend` chain + cycle
  - CLI override of `profile`, `spec_roots`, `model`
  - `config show` JSON snapshot
  - `exclude` skips `.venv` and custom glob

### 7. Documentation and spec backlinks

- Files: `docs/specs/02-backstitch-core.md`, implementation docs,
  `docs/specs/03-backstitch-configuration.md` Related Plans
- Update [SC-5] examples: `--model` optional when config or llm default exists
- Add repository map entries for `backstitch/settings.py`

### 8. Optional dogfood config

- File: `pyproject.toml` in backstitch repo
- Add minimal `[tool.backstitch]` mirroring current built-in profile
- Verify `backstitch config path --repo-root .` finds it only when standalone
  `.backstitch.toml` absent

## Testing Plan

Harness: `pytest` unit tests + subprocess CLI tests (existing pattern in
`tests/test_cli.py`).

Keep real:

- TOML parsing and discovery logic
- filesystem fixture layouts
- argparse + settings merge integration

May mock:

- `Path.home()` for boundary tests
- `llm.get_default_model()` only when testing analyze fallback order

Must not mock:

- `tomllib` loading
- config file precedence
- CLI subprocess exit codes

Contract proofs:

- same deterministic report with or without config when defaults match
- config changes defaults without flags
- flags still win
- `check` never imports `llm` (assert via test that inspects module imports or
  defers to existing invariant tests)

Commands:

```bash
uv run pytest tests/test_settings.py tests/test_cli.py -q
uv run pytest -q
uv run mypy backstitch
uv run ruff check backstitch tests
uv run backstitch config show --repo-root tests/fixtures/clean_project
uv run backstitch check --repo-root tests/fixtures/clean_project
```

## Verification and Gates

Per-task: run targeted `pytest` file for the task.

Final gates before completion:

- all tests green
- `mypy` + `ruff` clean
- `backstitch check --repo-root .` still exits 0 on backstitch repo
- spec/plan/implementation docs aligned ([DOM-4])
- independent review completed ([DOM-11])

Post-land signal: contributors can add `.backstitch.toml` or `[tool.backstitch]`
to target repos (including Weft) and drop repetitive CLI flags.

## Independent Review Loop

- Reviewer: different agent family than the authoring agent
- Read: this plan, `docs/specs/03-backstitch-configuration.md`, `backstitch/cli.py`,
  `backstitch/settings.py` (once written), and mypy/ruff sections of
  `pyproject.toml`
- Prompt:

> Read the plan at `docs/plans/2026-07-01-backstitch-toml-configuration-plan.md`
> and spec `docs/specs/03-backstitch-configuration.md`. Examine discovery
> boundaries, precedence, and schema scope. Could you implement this confidently
> without inventing parallel config systems? List ambiguities, missing tests, and
> contract risks.

Author must address each finding or record explicit out-of-scope reasoning.

## Out of Scope

- user-level global config in `~/.config/backstitch/`
- XDG config dir fallback
- per-directory cascading merges without `extend`
- custom profiles beyond built-in names
- new CLI commands beyond `config show` and `config path`
- changing deterministic severities via config
- `packets --output` becoming optional
- TOML-driven prompt template overrides
- config hot-reload or watch mode

## Fresh-Eyes Review

Checklist applied to this plan:

- [x] discovery anchor per command named
- [x] `$HOME` stop rule explicit
- [x] same-directory precedence explicit
- [x] precedence table includes CLI, env, config, defaults
- [x] mypy/ruff analogue table with omissions called out
- [x] files to create/modify listed
- [x] invariants before tasks
- [x] rollback story (opt-in config)
- [x] anti-mocking guidance
- [x] verification commands named
- [x] spec authorship included as task 1
- [x] independent review loop present

Residual risks to watch during implementation:

- argparse defaults currently mask config (must use `None` sentinels)
- `exclude` semantics need one helper shared by spec and code scanners
- `extend` relative paths from worktrees must be tested with nested fixtures