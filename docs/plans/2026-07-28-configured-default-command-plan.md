# Configured Default Command Plan

Plan type: implementation with spec revision.

Status: implemented and verified; final independent review PASS. The
owner-authorized landing commit includes this plan and its implementation.

Class: 5 because this is a new, previously undocumented feature that changes
the public CLI and configuration contracts. Class-4 hardening also applies:
bare `backstitch` changes from a required-subcommand error into
repository-configured execution, and one allowed value can enter the
provider-touching semantic lane.

Risk level: medium. The implementation is small, but the boundary is
load-bearing: config must select only a closed Backstitch command, explicit
subcommands must retain their current meaning, bare dispatch must not create a
second configuration path, and packaged defaults must never trigger model work.

## Goal

Allow a repository to choose what the bare `backstitch` invocation does:

```toml
[tool.backstitch]
default_command = "check"
```

The initial closed choices are `check` and `analyze`. Bare invocation treats
the current working directory as the repository root and otherwise delegates
to the selected command's existing handler, settings, output, and exit-code
contracts. This is a single-command default, not a workflow engine or shell
command list.

## Requested Outcomes

- [x] Add `default_command = false | "check" | "analyze"` as a strict
  top-level configuration key. `false` is the packaged default and disables an
  inherited default.
- [x] Make bare `backstitch` dispatch to configured `check` or current-repository
  `analyze`, using the current working directory as `--repo-root`.
- [x] Preserve explicit command behavior: `backstitch check`, `backstitch
  analyze ...`, and every other explicit command ignore `default_command`.
- [x] Resolve configuration exactly once per invocation, including bare
  invocation.
- [x] Preserve the deterministic/provider boundary: bare `check` cannot import
  `llm`; bare `analyze` retains its current deterministic preflight and provider
  budget controls.
- [x] Preserve the current missing-command failure class when no default is
  configured: exit `2`, one line-safe error, and no command execution.
- [x] Dogfood the feature through Backstitch's repository default. The initial
  reviewed value was `check`; owner direction after implementation changed it
  to `analyze`, with explicit `check` retained as the hermetic self-corpus
  gate.
- [x] Document the config, trust/cost boundary, downgrade constraint, and exact
  equivalences in the README and implementation guide.
- [x] Add firing tests for every allowed value, the disabled state, invalid
  values, precedence, explicit-command precedence, help/version short-circuit,
  exit classes, and the no-provider deterministic boundary.
- [x] Forward remaining arguments to the selected default command, including
  leading-path shorthand and `--model`; this follow-up depends on
  `docs/plans/2026-07-28-evidence-stable-semantic-result-reuse-plan.md` so
  model precedence can keep cache/provenance truth.

## Source Documents

- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10], [DOM-11], [DOM-15]
- `docs/specs/02-backstitch-core.md` [SC-5], [SC-5.1], [SC-8], [SC-10],
  [SC-16]
- `docs/specs/03-backstitch-configuration.md` [CFG-3], [CFG-5], [CFG-5.1],
  [CFG-6], [CFG-7], [CFG-8], [CFG-9], [CFG-10]
- `docs/specs/05-backstitch-invariants.md` [INV-11], especially [INV.PERF.1]
  and [INV.CFG.2]
- `docs/specs/06-semantic-gates.md` [SEM-7], [SEM-9]
- `docs/specs/07-verification-and-evidence-cases.md` [EVC-5.1], [EVC-11],
  [EVC-12]
- `README.md`, especially Quick Start, Command Reference, and Semantic Review
- `docs/implementation/04-backstitch-style-traceability.md`
- `docs/implementation/07-deterministic-semantic-gate.md`
- `docs/implementation/08-aligned-intent-read-model.md`
- `docs/plans/2026-07-27-canonical-config-resolution-plan.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`

## Spec Baseline

- `b33804a03f25168ea02bb4c9dc732c8cabaa2c75`:
  `docs/specs/02-backstitch-core.md` and
  `docs/specs/03-backstitch-configuration.md` at plan authoring time.
- Plan type: implementation with spec revision.
- Promotion baseline:
  `b33804a03f25168ea02bb4c9dc732c8cabaa2c75` plus the 2026-07-28 worktree
  spec diff in `docs/specs/02-backstitch-core.md`,
  `docs/specs/03-backstitch-configuration.md`, and
  `docs/specs/05-backstitch-invariants.md`. The promotion gate reported
  120 sections, 295 mappings, 373 code refs, 790 edges, 8 invariants, and
  zero errors, warnings, or infos; `git diff --check` passed.
- Implementation compliance after promotion is against that promotion
  baseline, not against the appendix text in this plan.

## Current Structure And Required Reading

Read these files before implementation:

- `backstitch/cli.py`
  - `build_parser()` currently makes the top-level subparser required, so
    argparse rejects a bare invocation before config discovery.
  - `main()` merges global and command-local config controls, resolves one
    `BackstitchSettings`, and directly dispatches command handlers.
  - `_settings_anchor()` derives command-specific discovery anchors.
  - `_cmd_check()` is the deterministic handler.
  - `_cmd_analyze()` current-repository mode already builds the deterministic
    obligation/check runtime and exits `1` before provider work when effective
    deterministic policy fails. A preceding `check` would duplicate this scan.
- `backstitch/settings.py`
  - `_TOP_LEVEL_KEYS`, `_TABLE_KEYS`, and the per-table key sets form the
    strict accepted schema.
  - `resolve_config()` is the sole configuration assembler.
  - `BackstitchSettings` is the immutable invocation snapshot.
  - `settings_to_json()` owns `config show` output.
  - `_GENERIC_OPTION_LEAVES` is a closed set. A key omitted from it cannot be
    changed with `--option`.
  - `resolve_config()` receives an environment mapping, but
    `_resolve_invocation_settings()` currently decides whether to include
    `LLM_MODEL` before calling it, based on the already parsed explicit
    command. Bare dispatch cannot preserve this behavior by preloading config
    and then resolving again.
- `backstitch/defaults.toml`
  - This is the lowest-precedence packaged layer. It must explicitly set
    `default_command = false`; packaged installation must not cause bare
    invocation to scan or call a provider.
- `pyproject.toml`
  - This repository's `[tool.backstitch]` table should set
    `default_command = "analyze"` as the owner-selected provider-capable
    dogfood path. Hermetic verification must use explicit `check`.
- `tests/test_settings.py`
  - Owns schema, merge, `extend`, strict-validation, and typed-settings tests.
- `tests/test_cli_config.py`
  - Owns public subprocess proofs for config discovery, global controls,
    precedence, and one-resolution dispatch.
- `tests/test_cli.py`
  - Owns public CLI output/exit behavior and the `llm` import quarantine.
- `tests/acceptance/test_probe_config.py` and
  `tests/acceptance/test_probe_selfacceptance.py`
  - Own black-box config honesty and self-corpus default-invocation floors.
- `tests/test_evidence_spike_cache_perf_pins.py` and
  `tests/test_evidence_spike_boundary_pins.py`
  - Own [INV.PERF.1]'s one-capture/default-check proof and [INV.CFG.2]'s
    packaged-versus-dataclass-default enumeration.
- `.github/workflows/semantic-refresh.yml`,
  `.github/workflows/semantic-pr-report.yml`, and
  `tests/test_release_workflow.py`
  - Own the enforceable hostile-target boundary: semantic workflows name
    `analyze`, target an explicit root, select trusted tool config, and use only
    static workflow-owned overlays. The CLI cannot infer whether one invocation
    is “local” or “hostile automation.”

Comprehension gates before editing:

1. Why would implementing bare `backstitch` as `main(["analyze", ...])`
   recursively violate the one-resolution boundary and create a recursion
   hazard?
2. Where does current-repository `analyze` stop on deterministic findings, and
   why does that make `["check", "analyze"]` both redundant and unable to
   bypass alignment readiness?
3. Which argparse actions (`--help`, `--version`) exit during parsing and
   therefore must remain incapable of config discovery or command execution?
4. Which config values can originate from a hostile target in semantic
   workflows, and why must this feature add no external executable, argument
   string, or provider-control source?
5. How does `_resolve_invocation_settings()` currently filter `LLM_MODEL` by
   explicit command, and how can the canonical resolver select that environment
   layer after reading `default_command` without a second file read or settings
   snapshot?

## Contract Decisions

| Input | Required behavior |
|---|---|
| `backstitch` with effective `default_command = "check"` | Exactly the existing `check` handler with repo root `Path.cwd()` and no dedicated CLI overrides. Configured `check.output`, if any, retains its ordinary write behavior. |
| `backstitch` with effective `default_command = "analyze"` | Exactly current-repository `analyze` with repo root `Path.cwd()`; deterministic failure still prevents provider work, while a permitted cache miss may retain the existing credential/network/cost behavior. |
| `backstitch` with effective `default_command = false` | Exit `2` with a line-safe missing-command error; run no command. |
| `backstitch check ...` with any configured default | Run explicit `check`; never redirect to the configured default. |
| Any other explicit subcommand with any configured default | Run that explicit subcommand unchanged. |
| Any config-consuming explicit command with an invalid `default_command` | Ignore the key for command selection, but reject the invalid known config value with exit `2` before command work. |
| `backstitch --config PATH` with no subcommand | Resolve exactly `PATH` at the current-directory anchor, then use its effective default. |
| `backstitch --no-config` with no subcommand | Use packaged settings (`default_command = false`) and return the missing-command exit `2`. |
| Bare invocation plus global `--option KEY VALUE` | Apply the option in the one normal resolution; it may configure the selected command but cannot set `default_command` itself. |
| `backstitch --help` / `backstitch --version` | Exit through argparse without reading repository config or executing a command. |
| Invalid type or value for `default_command` | Exit `2` during configuration resolution before snapshot, provider, cache, or output activity. |

`default_command` is deliberately not in `_GENERIC_OPTION_LEAVES`. The file
setting is the explicit consent boundary that turns bare invocation into work;
explicit CLI users already have the ordinary command names.

For local interactive use, typing bare `backstitch` explicitly delegates
command choice and that command's documented side effects to the selected or
discovered repository config. This includes configured `check.output` writes
and `analyze` cache/provider work. This accepted convenience boundary does not
apply to hostile-target or secret-bearing automation: those workflows must
continue to name `analyze`, select the trusted tool config explicitly, and
supply only workflow-owned static overrides under [SEM-9]/[EVC-11]. No
automated security boundary may replace its explicit command with bare
dispatch.

The command value is data, not syntax. No code may:

- split it as shell text;
- accept operands, flags, separators, or whitespace-bearing command lines;
- invoke a shell or external subprocess to dispatch it;
- call `main()` recursively;
- sequence more than one command; or
- accept commands whose required operational inputs have no defined bare
  meaning.

The initial values are therefore only `check` and `analyze`. Adding another
value later is a public-contract change with its own default-input definition
and firing test.

## Invariants And Constraints

1. **One resolver.** Bare and explicit invocations each call
   `resolve_config()` exactly once. Handler code receives the resulting frozen
   `BackstitchSettings`; it never rediscovers or remerges config.
   The canonical resolver must accept the explicit command or absence of one,
   load file layers once, derive the effective closed default when needed, and
   only then decide whether the `LLM_MODEL` environment layer applies.
2. **One dispatch path.** Bare selection must feed the same internal handler
   dispatch used by explicit commands. Do not copy `_cmd_check()` or
   `_cmd_analyze()` behavior into a new runner.
3. **Explicit syntax wins.** A parsed explicit subcommand always wins over
   `default_command` for selection and dispatch. Strict config validation still
   validates the known key for every config-consuming command; an invalid
   value is exit `2` even when an explicit command was named.
4. **No workflow engine.** The setting is one closed command name, not an
   ordered list, shell line, token list, or named workflow.
5. **No implicit model work.** Packaged defaults disable bare dispatch.
   Provider work occurs only when a repository or explicitly selected config
   says `default_command = "analyze"`, the local operator invokes bare
   `backstitch`, and the existing deterministic, completeness, cache, and
   budget preflights allow it. Secret-bearing hostile-target automation never
   uses bare dispatch.
6. **Analyze remains the composite gate.** Do not implement a separate
   `check`-then-`analyze` sequence. Current `analyze --repo-root` owns its
   deterministic preflight and exits before provider work on failing
   deterministic policy.
7. **Exit truth is delegated.** Once selected, the command's existing `0`,
   `1`, and `2` meanings remain unchanged. Default selection adds no aggregate
   or remapped exit code.
8. **Output truth is delegated.** Bare dispatch adds no preamble, wrapper JSON,
   progress text, or summary that would change the selected command's stdout
   contract.
9. **Provider quarantine survives.** Bare `check`, help, version, invalid
   config, and missing default do not import `llm`, read credentials, make
   network calls, or touch semantic cache state.
10. **Strict config survives.** Unknown keys and invalid values stay exit `2`;
    `allow_unknown_keys` retains its existing behavior. `config show` exposes
    the normalized effective default as `null`, `"check"`, or `"analyze"`.
11. **No new dependency.** Use argparse, the canonical resolver, and existing
    handlers only.
12. **No source writes.** The feature changes dispatch only. It does not alter
    Backstitch's observe/classify/gate boundary in [SC-16].
13. **Environment equivalence.** Bare analyze observes `LLM_MODEL` exactly as
    explicit analyze does; bare check excludes it exactly as explicit check
    does. A model/revision mismatch irrelevant to check must not make bare
    check fail.

## Hidden Couplings And Failure Priorities

- Making subparsers optional changes parser construction for every invocation.
  The manual missing-command branch must restore exit `2` when no default is
  available.
- Bare invocation cannot know the command until after config resolution, while
  the normal resolver anchor currently depends on the command. Its contract is
  therefore explicitly current-directory anchored. Do not infer an anchor
  from a command that has not been selected yet.
- `LLM_MODEL` is currently filtered by explicit command before
  `resolve_config()`. Pre-reading config to discover the default and then
  calling the resolver would create a two-read TOCTOU and violate the canonical
  snapshot. Always passing `LLM_MODEL` would make bare check differ from
  explicit check. Selection must move inside the one canonical resolution:
  merge packaged/repository layers, validate the closed default selector, then
  apply only the environment inputs relevant to the effective explicit/default
  command.
- The synthetic/default namespace needs command-specific argparse defaults.
  It may be created only from a closed in-process token tuple such as
  `("analyze", "--repo-root", ".")`; it must reuse the already resolved
  settings and must not reapply config controls.
- `--help` and `--version` are parser short-circuits. Turning them into
  config-consuming paths would be a regression and, for `analyze`, a possible
  cost/security defect.
- `extend` can inherit scalar settings. `false` exists so a child config can
  disable an inherited default without discarding the rest of its parent.
- Old Backstitch releases reject `default_command` as unknown. Release and
  rollback instructions must therefore account for config/binary order.
- An invalid `default_command` is a fatal invocation/config failure. A selected
  command's exit `1` remains a target-repository finding. No best-effort
  fallback from an invalid or failed default to another command is allowed.
- A discovered config is not trusted input in secret-bearing hostile-target
  automation. This feature accepts its side effects only for a local operator
  who deliberately invokes bare `backstitch`; automated semantic workflows
  remain explicit-command, explicit-trusted-config paths. This is enforced by
  workflow source and `tests/test_release_workflow.py`, not by pretending the
  CLI can detect an invocation's operator or trust context.

## Rollout, Rollback, And One-Way Doors

There is no persistence migration, generated state, or one-way data door.
Implementation and spec/docs can be reverted together.

Compatibility is ordered:

1. Ship a Backstitch release that understands `default_command`.
2. Only then add the key to downstream repository configs.
3. Before downgrading to an older release, remove `default_command` from those
   configs; strict old binaries will otherwise reject it as an unknown key.

Backstitch's own `pyproject.toml` can add `default_command = "analyze"` in the
same implementation change because the updated code and config land together.
If the change is rolled back before release, revert that line first or in the
same revert.

Post-release success is observable without telemetry: in a configured
repository, bare output and exit code are byte/semantically equivalent to the
selected explicit command; in an unconfigured repository, bare invocation
still performs no scan or model work and exits `2`.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| Verification infrastructure | No release-script change planned | The nested serial benchmark probe now removes outer-worker `PYTEST_XDIST_WORKER` metadata before launching its `-n 0` subprocess | The required full xdist gate exposed a pre-existing false failure: the probe passed serially but inherited the outer worker marker under xdist, which says nothing about whether the nested pytest disabled xdist | None; test-harness correction only |
| [CFG-9] repository dogfood | Backstitch's committed overlay selected `"check"` | Owner-directed follow-up selects `"analyze"`; `config show` verifies the choice without provider work and explicit `check` remains the hermetic self-corpus gate | The repository owner explicitly chose provider-capable bare analysis after the initial implementation and accepted the already documented credential/cache/cost boundary | Promote the revised [CFG-9] verification text in the same worktree |
| [CFG-5], [SEM-3], [SEM-4] model override | Different cached `LLM_MODEL`/`--model` values were rejected to protect revision and cost identity | Owner-directed follow-up keeps ordinary precedence and preserves one evidence-stable result across model changes; new work uses a complete trusted model descriptor | The complete prior result, including its selected evidence and producer provenance, remains defensible while the full packet/review contract is unchanged; clearing the environment or cache is not acceptable | `docs/plans/2026-07-28-evidence-stable-semantic-result-reuse-plan.md` and promoted [CFG-5]/[CFG-6], [SEM-3]/[SEM-4]/[SEM-9], [EVC-6] text |

## Proposed Spec Delta

Promotion strategy: **A — in-file edit, active files, text first**.

All touched sections already have implementation mappings to the correct
owners, so the spec-promotion slice changes normative text and backlinks
without adding or moving mapping blocks. No code cites a new spec section.
The later code slice updates reciprocal module/test citations where needed.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/02-backstitch-core.md` | A | [SC-5], [SC-10] |
| `docs/specs/03-backstitch-configuration.md` | A | [CFG-5], [CFG-5.1], [CFG-6], [CFG-7], [CFG-8], [CFG-9], [CFG-10] |
| `docs/specs/05-backstitch-invariants.md` | A | [INV-11] [INV.PERF.1], [INV.CFG.2] |

### `docs/specs/02-backstitch-core.md` [SC-5]

Insert after “`backstitch` must expose a console script named `backstitch`.”:

> A repository may configure one bare-invocation default through [CFG-6]
> `default_command`. After argparse handles `--help` and `--version`, an
> invocation with no explicit subcommand resolves configuration exactly once
> with the current working directory as its discovery anchor. Effective
> `"check"` dispatches the existing `check` command with that directory as
> `--repo-root`; effective `"analyze"` dispatches current-repository `analyze`
> with that directory as `--repo-root`. Effective `false` is the packaged
> default and returns exit `2` with a line-safe missing-command error.
>
> An explicit subcommand always wins selection and never redirects through
> `default_command`; ordinary strict config validation still rejects an invalid
> known `default_command` value. Bare dispatch delegates stdout, stderr, exit
> codes, configuration, snapshot,
> cache, budget, and provider behavior to the selected existing handler.
> In particular, current-repository `analyze` retains its deterministic
> preflight and performs no provider work when effective deterministic policy
> fails.
>
> `default_command` is a closed command name, not command-line syntax. V1
> accepts only `"check"` and `"analyze"`; it accepts no arguments, separators,
> external executables, multiple steps, or recursive dispatch. Other commands
> require an explicit invocation until a later spec defines their complete
> bare-input meaning.
>
> For local use, invoking bare `backstitch` explicitly delegates command
> selection and the selected command's documented side effects to the effective
> repository configuration. A configured check output may write its report;
> configured analyze may read credentials, write cache state, make bounded
> provider calls, and incur bounded cost under its existing contract. Bare
> dispatch is forbidden in secret-bearing hostile-target automation: those
> workflows continue to name the semantic command, select trusted tool
> configuration explicitly, and use only workflow-owned static overrides under
> [SEM-9] and [EVC-11].
> The CLI does not infer whether an invocation is local or automated; the
> hostile-target prohibition is a workflow contract enforced by trusted
> workflow source and its firing tests.

### `docs/specs/02-backstitch-core.md` [SC-10]

Insert in the required public CLI proof surface:

> - black-box bare-invocation tests proving configured `check` and `analyze`
>   use the current repository, preserve their explicit-command exit/output
>   contracts, and dispatch through one configuration resolution;
> - a no-default probe proving bare invocation exits `2` without importing
>   `llm`, scanning source, touching cache state, or reaching a provider;
> - help/version and explicit-command probes proving they do not execute or
>   redirect through the configured default; and
> - one firing test for each `default_command` value, the disabling `false`
>   value, every invalid type/value family, and `extend` override/disable
>   behavior; and
> - explicit-versus-bare environment tests proving `LLM_MODEL` applies to bare
>   analyze but remains irrelevant to bare check, with one file/config
>   resolution and one immutable settings snapshot.

### `docs/specs/03-backstitch-configuration.md` [CFG-5]

Insert after the precedence list:

> `default_command` follows ordinary scalar file-layer precedence. A child
> config may replace an inherited command or set `false` to disable it. No
> environment variable, dedicated flag, or generic `--option` key changes the
> selected default command. Global config selection and generic options for
> the eventually selected command still participate in the one normal
> resolution. The canonical resolver receives the explicit command or its
> absence, merges packaged and file layers once, validates and selects the
> effective default when needed, and only then applies command-relevant
> environment values. `LLM_MODEL` therefore applies to bare analyze exactly as
> it does to explicit analyze and remains absent from bare check exactly as it
> does from explicit check.

### `docs/specs/03-backstitch-configuration.md` [CFG-5.1]

Insert after the paragraph defining reserved/non-consulted generic leaves:

> `default_command` is also not a generic-option leaf. It selects whether bare
> invocation dispatches at all and is accepted only from the packaged or
> selected/discovered file layers. Once file configuration selects the
> command, other valid global `--option KEY VALUE` pairs apply normally to the
> already selected command's settings.

### `docs/specs/03-backstitch-configuration.md` [CFG-6]

Add this row to the top-level-key table in §6.1:

> | `default_command` | `false` \| `"check"` \| `"analyze"` | bare invocation | Select one current-directory command; `false` disables bare dispatch |

Insert after that table:

> The packaged value is `false`. `"check"` is equivalent to explicit
> `backstitch check --repo-root .`; `"analyze"` is equivalent to explicit
> `backstitch analyze --repo-root .`, where `.` is the process working
> directory. The equivalence is handler-level: the same resolved settings,
> output contract, exit classes, deterministic preflight, cache policy, and
> provider controls apply.
>
> The value is deliberately not a string containing arguments and not an
> array. Command-specific setting defaults belong in their existing tables,
> such as `[analyze].model` and `[check].format`. Operational arguments that
> lack a config key require an explicit command. A config that needs no bare
> action uses `false`; blank strings and every other boolean, string, array,
> table, integer, or floating-point value are invalid.

### `docs/specs/03-backstitch-configuration.md` [CFG-7]

Insert before the existing CLI-additions examples:

> With no explicit subcommand, global `--config`, `--no-config`, and
> `--option` controls retain their normal syntax. Resolution anchors at the
> current working directory. `--config PATH` may select a file whose
> `default_command` enables dispatch; `--no-config` observes the packaged
> `false` value and therefore returns the missing-command exit `2`.
> `--help` and `--version` remain parser-only operations and do not resolve
> repository configuration.
>
> Bare invocation is a local convenience over repository configuration, not a
> hostile-target automation primitive. Selecting `"analyze"` authorizes the
> same credential, network, cache, and bounded-cost behavior as explicit
> current-repository analyze. Selecting `"check"` authorizes the same configured
> report output behavior as explicit check. Secret-bearing hostile-target
> workflows must not use bare invocation; [SEM-9] and [EVC-11]'s explicit
> trusted-command/config/override boundary remains mandatory.
> This restriction is enforced at the workflow contract and test boundary;
> the CLI does not guess operator intent or trust from the same process inputs.

### `docs/specs/03-backstitch-configuration.md` [CFG-8]

Add these failure cases:

> - `default_command` has a type or value other than `false`, `"check"`, or
>   `"analyze"`: exit `2` before command, snapshot, cache, provider, or output
>   work;
> - an explicit config-consuming command has an invalid `default_command`:
>   the explicit command still wins selection, but strict validation rejects
>   the invalid known value with exit `2` before command work;
> - bare invocation resolves effective `default_command = false`: exit `2`
>   with the missing-command error and no fallback command; and
> - bare invocation has an invalid global config control or generic option:
>   exit `2` before default dispatch.

### `docs/specs/03-backstitch-configuration.md` [CFG-9]

Add these verification requirements:

> - packaged defaults set `default_command = false`, while Backstitch's
>   committed repository config sets `"analyze"`; `config show` proves that
>   selection without provider work, explicit `backstitch check` remains the
>   zero-error, zero-warning hermetic self-corpus gate, and controlled-adapter
>   tests prove bare analyze equivalence;
> - standalone and `pyproject.toml` configs can select each allowed command;
> - an extended child inherits, replaces, and disables a parent default under
>   ordinary scalar precedence;
> - `config show` renders normalized `default_command` as `null`, `"check"`,
>   or `"analyze"`;
> - explicit commands, `--help`, and `--version` never redirect through the
>   configured default;
> - default `check` remains structurally provider-free, and default `analyze`
>   retains the current deterministic-before-provider boundary; and
> - bare analyze includes `LLM_MODEL` in the canonical environment layer while
>   bare check excludes it; both paths resolve file configuration exactly once
>   and pass the same immutable settings snapshot into the selected handler;
> - a configured `check.output` write and a bounded provider-capable analyze
>   invocation match their explicit-command behavior in local tests, while
>   trusted hostile-target workflows are statically checked to retain explicit
>   commands and trusted config selection; and
> - direct resolver tests distinguish legacy non-CLI resolution, explicit
>   command resolution, and bare-command selection, and prove identical
>   settings/model provenance reaches explicit and bare analyze without a
>   second raw config assembly; and
> - malformed values, disabled bare invocation, and invalid global controls
>   fire their exact exit-`2` paths with no traceback.

### `docs/specs/03-backstitch-configuration.md` [CFG-10]

Add:

> - `README.md` documents configured bare invocation, its exact command
>   equivalences, and the explicit trust/cost warning for `"analyze"`.

### `docs/specs/05-backstitch-invariants.md` [INV-11]

Replace [INV.PERF.1] with:

> Invariant: [INV.PERF.1] the advertised explicit `backstitch check`
> invocation, and bare `backstitch` when effective configuration selects
> `check`, perform zero static-syntax parses and at most one repository snapshot
> capture; bare dispatch also resolves file configuration exactly once.
> `backstitch obligation list` parses each unique file at most once per
> invocation. Wall-clock budgets are non-normative and live only in marked
> performance tests.

Append to [INV.CFG.2]:

> The normalized optional `default_command` setting is covered explicitly:
> packaged `false` normalizes to `None`, while repository `"check"` and
> `"analyze"` values normalize to the corresponding closed command literals.

### Related-plan backlinks

Add this plan under `## Related Plans` in all three touched specs:

> - `docs/plans/2026-07-28-configured-default-command-plan.md`
>   (planned)

## Dependency-Ordered Tasks

### 1. Spec-promotion slice

- Files:
  - `docs/specs/02-backstitch-core.md`
  - `docs/specs/03-backstitch-configuration.md`
  - `docs/specs/05-backstitch-invariants.md`
- Apply the exact proposed text above using strategy A.
- Add the related-plan backlinks.
- Do not edit implementation mappings in this slice; their present owners
  already cover `cli.py`, `settings.py`, and the public tests.
- Run:
  - `uv run backstitch check --repo-root . --show-suppressions`
  - `git diff --check`
- Record the promotion baseline identifier in `## Spec Baseline`.
- Stop and re-plan if promotion creates warning/error trace debt, if an
  existing mapping changes owner due to heading placement, or if review
  requires a new stable section rather than edits to existing sections.
- Done signal: the promoted specs are the single normative contract, their
  backlinks resolve, and the self-corpus has zero errors and warnings.

### 2. Write failing public contract tests

- Files:
  - `tests/test_settings.py`
  - `tests/test_cli_config.py`
  - `tests/test_cli.py`
  - `tests/acceptance/test_probe_config.py`
  - `tests/acceptance/test_probe_selfacceptance.py`
- Add red tests before runtime code:
  1. packaged `false`, repository `"check"`, and selected `"analyze"` values;
  2. invalid string, `true`, blank string, list, and table families;
  3. standalone and `pyproject.toml` shapes;
  4. parent inheritance, child replacement, and child `false` disable;
  5. bare configured check equivalence on clean and broken repositories;
  6. bare configured analyze equivalence on a deterministic-failure fixture,
     proving exit `1` before provider import/call;
  7. no-default and `--no-config` exit `2` with no traceback or command work;
  8. explicit commands ignore the configured default for selection, while a
     config-consuming explicit command still rejects an invalid known
     `default_command`;
  9. `--help` and `--version` do not read a deliberately invalid discovered
     config and do not execute the default;
  10. `--config PATH` selects a bare default from the named file;
  11. valid global `--option` settings apply to the selected command, while
      `--option default_command ...` is rejected;
  12. bare analyze includes `LLM_MODEL` and enforces its existing
      model/revision identity checks, while bare check excludes an incompatible
      ambient `LLM_MODEL` and still runs; the selected handler receives the
      same immutable settings and
      model-source provenance as its explicit equivalent, not only that the
      public resolver was called once;
  13. configured `check.output` and provider-capable local default analyze
      retain the corresponding explicit-command side effects, while
      secret-bearing hostile-target workflow definitions remain explicit;
  14. `config show` exposes the normalized value;
  15. [INV.PERF.1] proves bare default check resolves config once, derives zero
      static-syntax facts, and enters snapshot capture once;
  16. Backstitch's committed config renders `"analyze"` through `config show`,
      while explicit self-check exits `0` with zero errors and warnings;
  17. direct resolver tests cover all three invocation-hint states: omitted
      private sentinel preserving legacy non-CLI environment behavior,
      explicit command, and `None` for bare selection; and
  18. release-workflow tests prove both secret-bearing semantic workflows keep
      explicit `backstitch analyze`, explicit target root, trusted tool config,
      and the exact static override set; bare `backstitch` is absent from those
      steps.
- Use real TOML, filesystem discovery, `python -m backstitch` subprocesses, and
  the real check/analyze preflight. Do not mock argparse, config loading,
  filesystem discovery, handler dispatch, or `llm` import state.
- A controlled provider adapter may be used only in a narrowly scoped existing
  semantic harness; the primary default-analyze proof should use a
  deterministic failure so provider construction is observably unreachable.
- Run the focused tests and capture the expected failures.
- Stop and re-plan if proving `analyze` dispatch requires a second packet or
  semantic runner, or if tests cannot distinguish one resolution from
  recursive `main()` dispatch.
- Done signal: tests fail only because the schema and bare dispatch do not yet
  exist.

### 3. Add the typed config contract

- Files:
  - `backstitch/defaults.toml`
  - `backstitch/settings.py`
  - `pyproject.toml`
  - focused tests from Task 2
- Add top-level `default_command` to the strict accepted schema.
- Parse `false` to normalized `None`; parse `"check"` and `"analyze"` to a
  closed typed value. Reject `true` and all other values.
- Add `default_command` to `BackstitchSettings` and `settings_to_json()`.
- Keep it out of `_GENERIC_OPTION_LEAVES`.
- Extend the canonical resolver API with a three-state invocation-command hint:
  1. an omitted private sentinel means “non-CLI/legacy caller” and preserves
     the caller-provided environment behavior;
  2. a required closed explicit command name means explicit CLI semantics; and
  3. `None` means bare CLI dispatch and selects the effective file default
     after packaged/repository merge.
  Do not use `None` as the public default because existing direct callers omit
  the hint. Validate explicit hints against the closed config-consuming command
  set. After the packaged/repository merge validates the default selector,
  choose the effective explicit/default command inside that same call and
  apply `LLM_MODEL` only for analyze/eval/doctor/config semantics. Keep
  `BACKSTITCH_WEFT_ROOT` behavior unchanged.
- Audit every production `resolve_config()` caller. CLI calls pass the explicit
  command or `None`; `alignment_eval.py` and other non-CLI production callers
  intentionally retain the omitted sentinel unless their contract requires an
  explicit hint. Record any migration rather than changing semantics silently.
- Remove command filtering of `LLM_MODEL` from the CLI wrapper once the
  canonical resolver owns it. Do not pre-read config or call the resolver
  twice.
- Reuse ordinary scalar layer merging; do not add a custom precedence path.
- Set packaged `default_command = false`.
- Set this repository's `[tool.backstitch] default_command = "analyze"`.
- Update module/test spec citations if the promoted sections require a more
  precise backlink.
- Run the settings and config-show test groups.
- Stop and re-plan if the implementation needs a second settings object,
  environment source, filename convention, or command-specific loader.
- Done signal: every config value and merge branch fires, `config show` is
  correct, and explicit commands remain unchanged.

### 4. Add one safe bare-dispatch wrapper

- Files:
  - `backstitch/cli.py`
  - `tests/test_cli_config.py`
  - `tests/test_cli.py`
  - acceptance tests from Task 2
- Make the top-level subparser optional only at parse time.
- Split the current post-resolution handler selection into one shared internal
  dispatch helper used by both explicit and configured-default paths.
- For an explicit command, preserve current anchor, config merge, and dispatch
  byte-for-byte where practical.
- For no command:
  1. merge global config controls;
  2. resolve settings once at `Path.cwd()` with invocation command `None`, so
     the resolver selects the default before applying command-relevant
     environment values;
  3. return the missing-command exit when the normalized default is `None`;
  4. create the selected command namespace from a hard-coded token tuple
     (`check` with its existing `.` default, or `analyze --repo-root .`);
  5. call the shared dispatcher with the already resolved settings.
- Do not call `main()` recursively and do not invoke a subprocess.
- Do not add a runner abstraction, command registry, workflow datatype,
  aggregate result, or shell parser.
- Preserve argparse's early `--help`/`--version` exits.
- Preserve local side-effect equivalence: do not silently discard configured
  `check.output`, analyze cache writes, or provider calls. The safety boundary
  is packaged `false`, local operator invocation, existing analyze
  budgets/preflights, and the prohibition on bare dispatch in secret-bearing
  hostile-target workflows.
- Run the focused public CLI and acceptance tests.
- Stop and re-plan if dispatch needs command strings from config, a second
  resolver call, output interception, or changes inside `_cmd_check()` /
  `_cmd_analyze()` beyond accepting their existing namespaces.
- Done signal: bare and explicit forms share handlers, one-resolution tests
  pass, default check is provider-free, and default analyze retains its
  deterministic preflight.

### 5. Documentation and traceability reconciliation

- Files:
  - `README.md`
  - `docs/implementation/04-backstitch-style-traceability.md`
  - `docs/implementation/07-deterministic-semantic-gate.md`
  - `docs/implementation/02-repository-map.md` if its `cli.py`,
    `settings.py`, or defaults descriptions become incomplete
  - `docs/plans/README.md`
  - `.github/workflows/semantic-refresh.yml` and
    `.github/workflows/semantic-pr-report.yml` (inspection; edit only if the
    explicit trusted command boundary is missing)
  - `tests/test_release_workflow.py`
  - touched module/test docstrings if needed
  - this plan
- Add a README example showing both allowed defaults and state explicitly that
  `"analyze"` may use credentials, network, cache, and provider budget only
  after its existing deterministic preflight.
- State that command arguments remain in existing config tables or explicit
  invocations; `default_command` is not a shell line.
- Explain the current-directory anchor, missing-default exit, `false` disable,
  explicit-command precedence, and old-version downgrade requirement.
- Explain that local bare invocation delegates configured output/provider side
  effects, while secret-bearing hostile-target workflows must keep explicit
  commands and trusted config/overrides.
- Strengthen `tests/test_release_workflow.py` so the named analyze steps in
  both secret-bearing workflows must contain explicit `backstitch analyze`,
  explicit target root, trusted tool config, and the exact static options, and
  cannot use a bare Backstitch invocation. This is the enforcement owner for
  the workflow contract; no CLI “local versus hostile” inference is added.
- Update the implementation guide with the one-resolution/default-dispatch
  rationale and owner.
- Reconcile spec mappings, reciprocal source/test citations, and related-plan
  backlinks. No temporary suppressions should remain.
- Update the plan status/evidence only with observed commands and results.
- Evaluate the planning/hardening runbooks for a durable omission; do not edit
  them unless implementation exposes one.
- Stop and re-plan if documentation would need to promise multiple commands,
  per-step arguments, or automatic provider work beyond the promoted spec.
- Done signal: the trace chain closes:
  `[SC-5]/[CFG-*] <-> plan <-> implementation doc <-> cli/settings/tests`.

### 6. Final verification and independent completed-work review

- Run every command in `## Verification And Gates`.
- Give an independent reviewer the promoted specs, this plan, implementation
  note, complete diff, and observed gate output.
- Reproduce every actionable finding before changing code.
- Append dispositions to the review log. Re-review accepted fixes only.
- Completion requires a commit when the owner authorizes landing. If the owner
  requests uncommitted review, report the exact changed files and do not call
  the feature complete.
- Done signal: all gates pass, review has no unresolved blocker, explicit
  self-check reports zero errors and warnings, `config show` reports the
  committed `"analyze"` default without provider work, and `git log` verifies
  the landing commit when authorized.

## Testing Plan

The primary proof is public subprocess behavior through
`python -m backstitch`; internal settings tests support it but do not replace
it.

Required behavior matrix:

| Case | Expected |
|---|---|
| packaged/no-config bare invocation | exit `2`, no traceback, no `llm`, no scan/provider/cache work |
| configured `check`, clean repo | same exit and report as explicit `check --repo-root .` |
| configured `check`, failing repo | same exit `1` and deterministic report as explicit check |
| configured `analyze`, deterministic failing repo | same exit `1` as explicit current analyze; provider unreachable |
| configured `analyze`, permitted controlled cache miss | same bounded provider/cache behavior as explicit current analyze |
| explicit check with default analyze | explicit deterministic check only |
| explicit analyze with default check | explicit analyze behavior unchanged |
| explicit config-consuming command with invalid default | exit `2` strict config failure; no redirection or command work |
| help/version with configured analyze and invalid repo config sentinel | exit `0`; no config/provider work |
| selected config | bare dispatch uses exactly the selected file |
| `--no-config` | packaged disabled state, exit `2` |
| parent/child config | inherit, replace, and disable behave by scalar precedence |
| incompatible ambient `LLM_MODEL`, default check | ignored exactly as for explicit check |
| ambient `LLM_MODEL`, default analyze | applied exactly as for explicit analyze, including model/revision checks |
| direct resolver with omitted hint | preserves legacy caller-provided environment semantics |
| configured `check.output` | same report write and failure semantics as explicit check |
| invalid values | exit `2` before side effects |
| config show | `null`, `"check"`, or `"analyze"` |
| Backstitch self-corpus | committed config renders default analyze; explicit check exits `0` with zero errors/warnings |

Anti-mocking posture:

- Do not mock argparse, TOML parsing, config discovery, `extend`, the
  filesystem, the check pipeline, command dispatch, subprocess exit codes, or
  module import state.
- It is acceptable to count `resolve_config()` at the public dispatch seam in
  one focused in-process test, but the equivalence and failure cases must
  remain real subprocess tests.
- Do not mock `_cmd_check()` or `_cmd_analyze()` as the sole proof that the
  correct command ran.
- Provider output is not under test. Prove default-analyze routing first with
  a deterministic failure that must occur before provider construction.

## Verification And Gates

Per-task focused gates:

```bash
uv run pytest tests/test_settings.py tests/test_cli_config.py tests/test_cli.py -q
uv run pytest \
  tests/test_semantic_analysis.py \
  tests/test_evidence_spike_cache_perf_pins.py \
  tests/test_evidence_spike_boundary_pins.py -q
uv run pytest tests/test_release_workflow.py -q
uv run pytest \
  tests/acceptance/test_probe_config.py \
  tests/acceptance/test_probe_selfacceptance.py -q
```

Final gates:

```bash
uv run pytest tests/acceptance -q
uv run pytest tests -q -n auto --dist loadgroup -m "not live_llm and not benchmark"
uv run ruff check backstitch tests bin
uv run ruff format --check backstitch bin .github/scripts tests
uv run mypy backstitch bin/release.py tests
uv run backstitch check --repo-root . --show-suppressions
uv run backstitch config show --repo-root .
git diff --check
```

Success requirements:

- all commands exit `0`;
- explicit self-check reports zero errors and zero warnings, and `config show`
  reports the committed `"analyze"` default without provider work;
- every new config value and failure branch has a firing test;
- no test or runtime path introduces a second config resolution;
- resolver tests prove one raw configuration assembly and identical immutable
  settings/model provenance, not merely one public function call;
- bare check/analyze preserve the explicit commands' different `LLM_MODEL`
  environment scopes;
- default check, help/version, missing default, and invalid config remain
  provider-free and traceback-free;
- no live-LLM or benchmark gate is silently claimed. Run those only when the
  release/implementation scope independently requires them, and record the
  exact result or residual risk.
- secret-bearing semantic workflow tests prove explicit command, target root,
  trusted config, and static-option ownership; no bare invocation appears in
  those provider-bearing steps.

## Independent Review Loop

Before the spec-promotion slice, give an independent reviewer:

- this plan, including `## Proposed Spec Delta`;
- `docs/specs/02-backstitch-core.md` [SC-5], [SC-10], [SC-16];
- `docs/specs/03-backstitch-configuration.md` [CFG-5]–[CFG-10];
- `docs/specs/05-backstitch-invariants.md` [INV-11];
- `docs/specs/07-verification-and-evidence-cases.md` [EVC-5.1], [EVC-11],
  [EVC-12];
- `backstitch/cli.py`, `backstitch/settings.py`,
  `backstitch/defaults.toml`, and `pyproject.toml`;
- the named public CLI/config/acceptance tests.

Review stance:

> Find errors, bad ideas, latent ambiguity, trust/cost mistakes, missing firing
> cases, and performative overengineering. Challenge whether a zero-context
> engineer can implement the plan confidently against the proposed delta as if
> promoted. In particular, verify one config resolution, explicit-command
> precedence, argparse help/version behavior, command-aware `LLM_MODEL`
> resolution, the deterministic-before-provider boundary, local side-effect
> consent versus hostile-target automation, `extend` disable semantics, and
> rollback to an older strict binary.
> Prefer removing unnecessary machinery. Do not implement.

Each finding receives an explicit accepted, rejected, or out-of-scope
disposition in the review log. A finding that changes command choices,
configuration authority, provider authority, or blast radius requires focused
re-review before promotion.

After implementation, use a different-agent or strict fresh-eyes review over
the promoted contract and complete diff. Plan approval is not implementation
approval.

## Review Log

### 2026-07-28: independent design and boundary review, round 1

Verdict: **BLOCKED** pending resolution of ambient provider authority and the
one-pass environment/config coupling. The plan was revised before a full-text
round-2 review.

| Finding | Disposition |
|---|---|
| F1: bare dispatch cannot preserve `LLM_MODEL` semantics by resolving once outside the canonical resolver because the effective command comes from file config | Accepted. The plan now moves command-aware environment selection into the one canonical resolution after packaged/repository merge. It explicitly forbids a pre-read plus second resolve and adds explicit/bare environment-equivalence tests. |
| F2: repository-selected bare analyze could read credentials, write cache, call a provider, and incur cost without an explicit `analyze` token | Accepted as a real risk; the proposed zero-call-only restriction is declined because it would make configured `"analyze"` materially different from the requested/defaulted command and would prevent the motivating provider-backed use case. The revised contract defines local bare invocation as explicit delegation to selected repository config, keeps packaged default disabled, retains all analyze budgets/preflights, warns in user docs, and forbids bare invocation in secret-bearing hostile-target automation. This authority choice requires round-2 review. |
| F3: configured `check.output` can write or replace a path during bare check | Accepted as the deterministic analogue of F2. The revised contract preserves handler equivalence rather than silently ignoring the setting, documents the side effect, packages `false`, and confines bare invocation to local operator use. |
| F4: packaged `"check"` would make every unconfigured repository perform work and would change current compatibility without repository opt-in | Declined. The plan retains packaged `false` and opts only Backstitch's own committed config into `"check"` for self-dogfood. `--no-config` therefore preserves a no-work missing-command exit. |
| F5: [INV.PERF.1], [INV.CFG.2], and their enumerating tests were missing from the first draft | Accepted. The proposed delta, source list, task files, and verification matrix now include both invariants and their concrete test owners. |
| F6: the plan did not state downgrade order for older strict binaries | Already addressed. Tool support ships before downstream config; the key is removed before downgrade. |

Round 2 must decide whether the explicit local-delegation boundary is coherent
with [SC-16], [SEM-9], and [EVC-11]. If review cannot accept that boundary,
implementation remains blocked and the owner must choose between zero-call
implicit analyze, an out-of-repository consent mechanism, or removing
`"analyze"` from the initial enum.

### 2026-07-28: independent full-text review, round 2

Verdict: **BLOCKED** on two resolver/workflow owners and two contract-proof
ambiguities. The reviewer otherwise accepted the closed selector, packaged
`false`, shared handler dispatch, and local provider-capable analyze decision
as coherent with [SC-16].

| Finding | Disposition |
|---|---|
| R2-F1: `str | None` would give existing omitted-hint direct resolver callers accidental bare semantics and could suppress their caller-provided `LLM_MODEL` | Accepted. The resolver contract is now three-state: omitted private sentinel preserves legacy non-CLI behavior; a closed explicit command selects explicit CLI environment scope; `None` alone means bare selection. Production callers are audited and direct tests fire every state. |
| R2-F2: the hostile-workflow prohibition had no named enforcement owner | Accepted. Both semantic workflow files and `tests/test_release_workflow.py` are now required reading/task inputs. The spec delta states that the CLI cannot detect trust context; workflow source/tests enforce explicit analyze, target root, trusted config, and static overrides. |
| R2-F3: “explicit commands ignore the default” could be read as ignoring an invalid known config value | Accepted. The plan and exact delta distinguish dispatch selection from strict schema validation. Explicit commands do not redirect, but invalid `default_command` still fails every config-consuming invocation with exit `2`. |
| R2-F4: counting `resolve_config()` calls alone would not prove one raw assembly or identical model provenance | Accepted. Tests now compare the immutable settings/model-source snapshot delivered to bare and explicit handlers and cover each resolver hint state, in addition to counting the public call. |

Round 3 is a focused verification of R2-F1 through R2-F4 and any new defect
introduced by their fixes.

### 2026-07-28: focused independent review, round 3

Verdict: **PASS**.

The reviewer verified R2-F1 through R2-F4 against the revised plan:

- the omitted private sentinel, explicit command, and bare `None` resolver
  states are distinct and test-owned;
- hostile-target protection is correctly owned by workflow source and workflow
  tests rather than unverifiable CLI intent detection;
- explicit-command precedence affects dispatch only, while invalid known config
  remains exit `2`; and
- verification requires one raw assembly plus identical immutable
  settings/model-source provenance.

No new defect was found in the accepted fixes. The plan and proposed spec delta
are cleared for the spec-promotion slice.

### 2026-07-28: spec-promotion review

Verdict: **PASS**. The reviewer compared all three promoted specs with the
exact proposed delta, found no semantic omission or contradiction, and
independently reproduced the zero-error, zero-warning self-corpus and
`git diff --check` gates.

### 2026-07-28: settings implementation review

Initial verdict: **BLOCKED** because `settings.py` and `cli.py` duplicated the
config-consuming command inventory. The inventory was centralized as
`settings.CONFIG_CONSUMING_COMMANDS`, used by both resolver validation and CLI
classification, and the focused settings/CLI/static gates were rerun.

Final verdict: **PASS**. Strict values, normalization, scalar/extend
precedence, generic-option exclusion, the three resolver states, and
command-scoped environment behavior were accepted.

### 2026-07-28: CLI/runtime implementation review

Initial verdict: **BLOCKED** on four proof gaps, with no runtime defect found:
extend-only inheritance, failing-check equivalence and explicit-analyze
precedence, full bare/explicit settings identity, and the no-scan/no-cache
disabled boundary. Each missing firing test was added and passed.

Final verdict: **PASS**. The reviewer confirmed one config resolution, fixed
in-process CWD dispatch through shared handlers, explicit-command precedence,
full immutable settings/provenance equality, deterministic/provider
boundaries, and the closed disabled path.

### 2026-07-28: final complete-diff review

Verdict: **PASS** with no findings. The reviewer confirmed the resolver states,
single-resolution snapshot reuse, explicit-command precedence and strict
validation, deterministic/provider boundaries, hostile-workflow controls,
documentation alignment, and the narrow outer-xdist marker correction in the
nested serial benchmark probe. The owner-authorized landing commit now closes
the prior process-level residual.

## Implementation And Verification Record

Implementation uses one normalized `default_command` field in
`BackstitchSettings`, one shared config-consuming command inventory, and a
three-state resolver command hint. Bare CLI dispatch parses the remaining
arguments against only the selected `check` or `analyze` parser, treats a
leading path as `--repo-root` shorthand, and calls the existing handler with
the already resolved settings snapshot. It does not re-enter `main`, start a
subprocess, or reread configuration.

Verification completed on 2026-07-28:

- all focused settings, CLI/config, semantic-analysis, performance-pin,
  workflow, and named acceptance suites passed;
- `uv run pytest tests/acceptance -q` passed after adding the new
  [INV.PERF.1] bind to the closed acceptance inventory;
- `uv run pytest tests -q -n auto --dist loadgroup -m "not live_llm and not benchmark"`
  passed;
- Ruff check, Ruff format check, and mypy passed over their full repository
  targets;
- explicit self-check exited `0` and reported 120 sections, 295 mappings,
  373 code refs, 790 edges, 8 invariants, 16 binds, and zero errors, warnings,
  or infos; controlled-adapter tests proved bare/explicit analyze equivalence;
- after the owner-directed follow-up, `config show` rendered
  `default_command = "analyze"` without entering provider work;
- `git diff --check` passed.

The first full xdist run exposed a pre-existing false failure in the nested
serial benchmark probe: its `-n 0` subprocess inherited outer-worker xdist
markers. The test harness now removes only those inherited markers before the
nested launch. Serial and xdist reproductions proved the correction, and the
full required xdist suite then passed. No benchmark or live-LLM lane was run
or claimed.

## Out Of Scope

- ordered or named workflows;
- multiple default commands;
- command strings, argument strings, token arrays, shell syntax, pipes, or
  external executables;
- making `packets`, `eval`, `obligation`, `config`, `cache`, `guide`,
  `summarize-analysis`, or `doctor` defaultable without a separate contract for
  their required inputs and side effects;
- adding config keys for currently operational-only CLI arguments;
- changing `analyze` to run after deterministic failure;
- combining check and semantic reports into a new wrapper output;
- changing semantic cache, identity, policy, cost, credential, or provider
  behavior;
- changing config discovery names, anchors for explicit commands, or the
  canonical precedence cascade;
- compatibility shims that silently ignore `default_command` on old releases;
- a new dependency or general command registry;
- unrelated CLI/parser cleanup.

## Fresh-Eyes Review Checklist

- Can a zero-context implementer state why this is one command rather than a
  workflow?
- Are `check` and `analyze` the only closed values everywhere?
- Is `false` the packaged value and an explicit child-config disable?
- Does bare resolution have exactly one unambiguous current-directory anchor?
- Is configuration resolved once and passed into the existing handler?
- Are explicit commands, help, and version provably unchanged?
- Can default check remain structurally incapable of importing `llm`?
- Does default analyze retain deterministic preflight, cache, budget, and
  provider boundaries without a wrapper?
- Are all output and exit contracts delegated rather than recomposed?
- Is downgrade ordering explicit for older strict binaries?
- Does every enumerable config value and failure class have a firing test?
- Can rollback remove the repository config key and implementation together?
- Does `config show` prove the configured analyze default while explicit
  `backstitch check --repo-root .` remains the only hermetic self-corpus gate?
