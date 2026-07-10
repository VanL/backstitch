# Configurable Diagnostics, Stable Codes, And Default TOML

Status: implementation and strict self-corpus remediation verified locally
after independent review; changes are uncommitted.
Plan type: implementation with spec revision.
Risk level: high. This changes public report fields, diagnostic identity,
configuration semantics, suppression behavior, and exit-code policy. The
`hardening-plans.md` checklist applies.

## Goal

Make Backstitch diagnostics work like mature static-analysis tools: every
reported condition has a stable automation/suppression key, a short display
alias, and a configurable reporting level. Move built-in defaults into a
packaged TOML file so Backstitch always starts from an inspectable default
configuration layer, then applies repository configuration and CLI overrides.

The requested behavior is:

- stable diagnostic keys inspired by Ruff rule codes, mypy error codes, and
  Coverage.py warning names
- an initial allocation list for current and near-future diagnostic codes,
  including suppression-hygiene codes
- a default TOML file that owns built-in profile, exclude, diagnostics, and
  reporting policy defaults
- configurable diagnostic levels so a project can make all target findings
  errors, all infos, or any mix
- short codes for terminal/editor display while preserving descriptive long
  codes as canonical automation keys

## Source Documents

Source specs:

- `docs/specs/02-backstitch-core.md` [SC-5], [SC-6], [SC-10], [SC-11],
  [SC-13]
- `docs/specs/03-backstitch-configuration.md` [CFG-1] through [CFG-10]
- `docs/specs/04-backstitch-traceability-exclusions.md` [EXC-1] through
  [EXC-10]

Implementation context:

- `docs/implementation/04-backstitch-style-traceability.md`
- `backstitch/models.py`
- `backstitch/resolver.py`
- `backstitch/reporting.py`
- `backstitch/check_pipeline.py`
- `backstitch/settings.py`
- `backstitch/exclusions.py`
- `backstitch/analysis_packets.py`
- `backstitch/analysis_results.py`
- `backstitch/analysis_llm.py`
- `backstitch/doctor.py`
- `pyproject.toml`

External analogues checked during plan authoring:

- Ruff rule codes and selectors:
  <https://docs.astral.sh/ruff/linter/> and
  <https://docs.astral.sh/ruff/rules/>
- mypy error codes, `ignore-without-code`, and `unused-ignore`:
  <https://mypy.readthedocs.io/en/stable/error_codes.html> and
  <https://mypy.readthedocs.io/en/stable/error_code_list2.html>
- Coverage.py warning names, `disable_warnings`, and report-error downgrade:
  <https://coverage.readthedocs.io/en/latest/messages.html> and
  <https://coverage.readthedocs.io/en/7.15.0/config.html>

Runbooks:

- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/writing-specs.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/agent-context/runbooks/testing-patterns.md`

## Spec Baseline

- Baseline commit: `fc7427180fcbc99eb19ae5771a2231546ddd026b`
- Worktree state at plan authoring: clean
- Governing specs at baseline:
  - `docs/specs/02-backstitch-core.md`
  - `docs/specs/03-backstitch-configuration.md`
  - `docs/specs/04-backstitch-traceability-exclusions.md`
- Promotion baseline identifier: promoted in this implementation slice from
  baseline `fc7427180fcbc99eb19ae5771a2231546ddd026b`.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Context And Key Files

Read first, in this order:

1. `backstitch/models.py`
   - Current contract: `Issue` has `code`, `severity`, locator fields, and
     free-text `message`. `Severity` is `Literal["error", "warning", "info"]`.
     `ISSUE_CODES` and `ERROR_SEVERITY_CODES` are hard-coded inventories that
     mirror [SC-11].
   - Load-bearing point: tests parse the [SC-11] table and compare it to
     `ISSUE_CODES`. This must become a registry/defaults-TOML check, not a
     hand-maintained Python set check.
2. `backstitch/resolver.py`
   - Current contract: issue severity is chosen at emission sites. The module
     deliberately has no code-to-severity table. Two existing codes are
     context-dependent: `SPEC_SECTION_AMBIGUOUS` and `MAPPING_PATH_MISSING`.
   - Load-bearing point: resolver purity matters. The resolver should emit
     diagnostic identity and context; policy application should stay a small,
     reusable post-processing step rather than making resolver behavior depend
     on CLI state.
3. `backstitch/settings.py`
   - Current contract: config discovery finds one repo config, optionally with
     `extend`, and falls back to Python dataclass defaults when no config is
     found.
   - Load-bearing point: after this work, "no repo config" still means one
     config layer exists: the packaged default TOML. `--no-config` skips repo
     discovery, not packaged defaults.
4. `backstitch/check_pipeline.py`
   - Current contract: scan, build suppression index, apply suppression once,
     return report plus suppressed findings and warnings.
   - Load-bearing point: policy level application and suppression order must be
     explicit. A finding hidden by `level = "off"` must remain auditable under
     `--show-suppressions`, same as explicit suppressions.
5. `backstitch/exclusions.py`
   - Current contract: error-severity issues are never suppressed; suppression
     warnings are currently raw strings on stderr.
   - Load-bearing point: with configurable levels, "error" is policy, not
     immutable truth. Suppressibility must be policy-driven, and suppression
     hygiene findings must become structured diagnostics with stable codes.
6. `backstitch/reporting.py`
   - Current contract: text output groups by `error`, `warning`, then `info`;
     JSON mirrors `Report.to_dict()`.
   - Load-bearing point: display should show both short and long code without
     making the message text an API.
7. `backstitch/analysis_packets.py`, `analysis_results.py`, `analysis_llm.py`,
   and `doctor.py`
   - Current contract: packet warnings, analysis error rows, analysis-load
     problems, and doctor checks are not deterministic `Issue` records.
   - Load-bearing point: do not accidentally convert semantic classifications
     or doctor statuses into target-repository failures. Name future codes for
     these surfaces, but implement only the agreed scope.

Comprehension checks before editing:

1. Where is the current distinction between target-repository failure
   (`exit 1`) and invocation/tool failure (`exit 2`) enforced?
2. Why must a diagnostic's canonical code remain separate from its effective
   level?
3. Which two current issue codes are context-dependent, and why would a flat
   code-to-level default table lose information?
4. What currently makes a suppression auditable, and how would `level = "off"`
   hide findings if it bypassed that path?

## Invariants And Constraints

- **Diagnostic identity is not severity.** `code` identifies what happened.
  `context` refines the situation when one code has multiple policy defaults.
  `severity`/`level` is policy. Exit code is command outcome.
- **Default and effective levels are distinct.** `default_severity` is computed
  from the packaged default policy only. Effective `severity` is computed from
  all active config layers and CLI compatibility overrides. A repository
  override must not rewrite `default_severity`.
- **Long code is canonical.** Short codes are stable aliases for display and
  input convenience, never the sole identity. JSON should include both once
  short codes ship.
- **Message text is not API.** Tests and automation must assert structured
  fields: code, short code, context, effective level, default level, path, line,
  section, symbol, and suppression reason where relevant.
- **No short-code reuse.** Removed or redirected diagnostics reserve their
  short code forever. Renames use explicit alias/redirect metadata and produce
  a suppression-hygiene diagnostic when stale names are used.
- **The packaged default TOML is the first config layer.** Repo config and
  explicit `--config` layer on top of it. `--no-config` skips repo config only;
  it still uses packaged defaults.
- **Code still validates vocabularies.** Moving defaults into TOML does not
  mean accepting unknown strings. The registry loader validates duplicate short
  codes, invalid levels, invalid selectors, unknown aliases, and implemented
  diagnostics without firing tests.
- **Exit `2` is not configurable.** Bad TOML, invalid CLI args, malformed input
  artifacts, output write failures, and internal failures are invocation/tool
  failures. They do not become infos because a repo sets all target diagnostics
  to `info`.
- **Semantic findings stay advisory.** `analyze` classifications remain
  separate from deterministic target diagnostics. This plan may allocate codes
  for model-output and analysis-input problems, but implementation must not make
  semantic classifications CI-failing findings.
- **Doctor statuses stay statuses.** `doctor` check names (`llm-import`,
  `model`, `credential`, `json-mode`, `memory`, `endpoint`) remain the doctor
  contract. Do not duplicate them as target diagnostics unless a later spec
  explicitly merges doctor into the diagnostic report stream.
- **Suppression remains auditable.** Findings disabled by suppression or by
  `level = "off"` must be recoverable with `--show-suppressions` or a renamed
  equivalent audit view. `off` is not a report severity and must not appear in
  `report.issues`.
- **Warnings-as-errors stays compatibility glue.** The existing
  `--warnings-as-errors` and `[check].warnings_as_errors` behavior remains
  accepted during migration, but it should translate into `fail_on` policy
  rather than changing diagnostic identity or effective levels.
- **No new runtime dependency.** TOML parsing uses `tomllib`; packaged defaults
  use `importlib.resources`. Do not add a dependency for config merging or
  schema validation.

## Rollback And Rollout

Rollback is straightforward only if the rollout preserves compatibility:

- Keep accepting current long issue codes in config and inline suppressions.
- Keep JSON field `severity` for at least the first implementation slice. If a
  new field `level` is added, either make it an alias of `severity` or defer it
  to a later compatibility slice.
- Keep `--warnings-as-errors` and `[check].warnings_as_errors` as compatibility
  inputs that map to `diagnostics.fail_on = ["error", "warning"]`.
- If the packaged default TOML loader fails in production, revert by restoring
  Python defaults in `settings.py`, `models.py`, and `profiles.py`; do not
  partially keep TOML diagnostics while Python profile defaults are restored.
- Do not land code that emits new spec citations before the spec-promotion
  slice. This plan uses promotion strategy A for spec text first, then code
  and reciprocal mappings in later slices.

There are no data migrations and no persistent storage changes. The main
one-way door is public diagnostic identity. Do not rename or renumber codes
after the registry ships without an alias/redirect entry.

## Proposed Spec Delta

Promotion strategy: **A - in-file active spec edits, text first.**

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/02-backstitch-core.md` | A | [SC-5], [SC-6], [SC-10], [SC-11], [SC-13], new [SC-15] |
| `docs/specs/03-backstitch-configuration.md` | A | [CFG-2], [CFG-5], [CFG-6], [CFG-8], [CFG-9] |
| `docs/specs/04-backstitch-traceability-exclusions.md` | A | [EXC-2], [EXC-4], [EXC-5], [EXC-6], [EXC-8], [EXC-9] |

Spec-promotion also adds this plan to each touched spec's `## Related Plans`.

### `docs/specs/02-backstitch-core.md` - [SC-5] CLI Contract

Insert after the exit-code list:

> Diagnostic policy controls which deterministic target-repository findings
> are rendered as `error`, `warning`, `info`, or `off`, and which rendered
> levels cause `check` and `packets` to exit `1`. This policy never changes
> exit `2`: invalid CLI arguments, malformed configuration, malformed input
> artifacts, output write failures, and internal failures remain invocation or
> tool failures and are not configurable as target diagnostics.
>
> `--warnings-as-errors` and `[check].warnings_as_errors` are compatibility
> shorthands for adding `warning` to the command's effective `fail_on` levels.
> They do not mutate diagnostic identity or the configured level written in JSON
> reports.

### `docs/specs/02-backstitch-core.md` - [SC-6] Report And Data Contracts

Replace the issue-record sentence with:

> Issue records must include stable diagnostic identity and locator fields:
> canonical `code`, stable `short_code`, optional `context`, effective
> `severity` (`error`, `warning`, or `info`), `default_severity` from
> Backstitch's packaged default policy before repository policy overrides,
> path, line where available, message, and enough target metadata for a human
> or agent to locate the problem. `message` is presentation, not API.
> Automation and tests must key on structured fields.

Add after the issue-record sentence:

> `off` is a diagnostic policy result, not a report severity. A diagnostic
> whose effective level is `off` is omitted from `issues`, excluded from report
> summary counts, and recoverable only through the suppression/audit view with
> reason `diagnostic level off`. `fail_on` and `suppressible_levels` may
> contain only `error`, `warning`, and `info`; `off` is invalid in those lists.

Add after the JSON report block:

> Human-facing text output should render both short and canonical codes, for
> example `[BSS001 SPEC_FILE_MISSING]`. Machine-readable JSON keeps the
> canonical long code as the primary key and includes `short_code` as a display
> alias.

### `docs/specs/02-backstitch-core.md` - [SC-10] Verification Expectations

Add to required proof surfaces:

> - default diagnostic registry validation: every implemented diagnostic code
>   in the packaged defaults TOML has a unique short code, valid default level,
>   valid status, and at least one firing test; every emitted diagnostic code is
>   present in that registry
> - diagnostic-policy tests proving all-error, all-info, mixed-level, `off`,
>   and `fail_on` behavior through the real CLI and JSON report path
> - suppression-hygiene tests proving unused, unknown, malformed,
>   unsuppressible, duplicate, broad, deprecated, and redirected suppressions
>   produce structured diagnostics with stable codes where implemented
> - compatibility tests proving `--warnings-as-errors` and
>   `[check].warnings_as_errors` still affect exit behavior but do not rewrite
>   diagnostic identity

Modify the existing "every issue code" requirement:

> Every implemented diagnostic code in the default registry has at least one
> test that proves it fires. Reserved codes may appear in the registry only with
> `status = "reserved"` and must not be accepted as emitted issue codes or
> ordinary suppressions until promoted to `implemented`.

### `docs/specs/02-backstitch-core.md` - [SC-11] Issue Codes

Rename the section heading to:

```markdown
## 11. Diagnostic Codes And Default Policy [SC-11]
```

Replace the severity table introduction with:

> Deterministic target-repository diagnostics use stable canonical codes. The
> default reporting level is policy, supplied by Backstitch's packaged default
> TOML, not by hard-coded Python inventories. The table below records the
> initial implemented deterministic diagnostics; the packaged registry is the
> machine-readable source of truth.

Keep the current long-code table but add columns:

| Code | Short | Default level | Context | Meaning |
|------|-------|---------------|---------|---------|

Initial implemented allocation:

| Code | Short | Default level | Context | Meaning |
|------|-------|---------------|---------|---------|
| `SCAN_ROOT_MISSING` | `BST001` | error | none | Configured spec, plan, or code root not found |
| `FILE_UNREADABLE` | `BST002` | error | none | File could not be read; scan continues |
| `SPEC_FILE_MISSING` | `BSS001` | error | none | Referenced spec file does not exist |
| `SPEC_SECTION_MISSING` | `BSS002` | error | none | File-qualified section reference not found in that file |
| `SPEC_SECTION_AMBIGUOUS` | `BSS003` | error/warning | `asserted`, `weak` | Bare ID matches multiple sections |
| `SPEC_SECTION_DUPLICATE` | `BSS004` | warning | none | Section ID defined more than once |
| `SPEC_ANCHOR_MISSING` | `BSS005` | error | none | File#anchor reference not found |
| `REF_RANGE_UNSUPPORTED` | `BSS006` | error | none | Section range could not be expanded |
| `SPEC_SECTION_UNMAPPED` | `BSS007` | info | none | Spec section has no implementation mapping |
| `MAPPING_PATH_MISSING` | `BSM001` | error/warning | `required`, `plan-artifact` | Mapping path missing |
| `MAPPING_PATH_INEXACT` | `BSM002` | warning | none | Mapping token resolved via unique suffix/basename match |
| `TARGET_PATH_AMBIGUOUS` | `BSM003` | error | none | Mapping token matches multiple paths; no edge emitted |
| `MAPPING_SYMBOL_MISSING` | `BSM004` | error | none | Explicit `path::symbol` names a symbol absent from that file |
| `MAPPING_SYMBOL_UNRESOLVED` | `BSM005` | warning | none | Advisory bare symbol in mapping could not be resolved |
| `MAPPING_BLOCK_OWNERLESS` | `BSM006` | warning | none | Mapping block has no preceding ID-bearing heading |
| `PYTHON_SYNTAX_ERROR` | `BSC001` | warning | none | Python file could not be parsed |
| `CODE_REF_BARE_UNRESOLVED` | `BSC002` | warning | none | Known-prefix bare reference matches no section |
| `SPEC_MAPPING_RECIPROCAL_MISSING` | `BSC003` | warning | none | Code backlink without spec mapping |
| `CODE_BACKLINK_RECIPROCAL_MISSING` | `BSC004` | warning | none | Spec mapping without code backlink |
| `CODE_REF_BROAD` | `BSC005` | warning | none | Document-only code reference |
| `CODE_REF_PLANNED_SPEC` | `BSC006` | warning | none | Shipped code cites planned spec |
| `CODE_REF_EXPLORATORY_SPEC` | `BSC007` | warning | none | Shipped code cites exploratory spec |
| `CODE_REF_UNMAPPED_FROM_SPEC` | `BSC008` | info | none | Code cites spec without spec mapping to file |

Add after the rationale:

> Short codes are stable aliases. They may be accepted in configuration and
> suppression syntax, but reports and `config show` canonicalize to the long
> code. Short codes are never reused.
>
> For context-dependent diagnostics, `default_severity` records the default
> level for that exact emitted context. Repository policy may override the
> effective `severity`, but must not erase `context` or `default_severity`.

### `docs/specs/02-backstitch-core.md` - new [SC-15]

Insert a new section before `## Related Plans`:

```markdown
## 15. Diagnostic Registry And Policy [SC-15]

Backstitch ships a packaged default TOML file that is always loaded as the
lowest-precedence configuration layer. The default TOML owns:

- built-in profile defaults formerly held only in Python
- default scan excludes
- diagnostic registry entries
- default diagnostic policy (`default_level`, ordered level rules,
  `fail_on`, and suppressible levels)

Repository config and explicit `--config` files layer on top of packaged
defaults. `--no-config` skips repository discovery but still loads packaged
defaults.

Diagnostic registry entries have:

- canonical long code
- unique short code
- status: `implemented`, `reserved`, `deprecated`, or `redirected`
- default summary
- optional replacement code for redirected/deprecated entries
- optional allowed contexts

Only `implemented` diagnostics may be emitted by the current version.
Reserved diagnostics document the allocation list but are not valid emitted
issue codes or ordinary suppressions until promoted. Deprecated and redirected
codes are accepted as aliases only when the registry names their replacement;
using them produces a suppression-hygiene diagnostic unless the relevant
hygiene code is disabled by policy.

Diagnostic policy is an ordered rule list. Each rule names selectors and a
target level (`error`, `warning`, `info`, or `off`). Later configuration
layers are applied after earlier layers; later matching rules win. Selectors
support canonical long codes, short codes, `*`, code-family prefixes ending in
`*`, and context selectors of the form `CODE:context` or `SHORT:context`.
This lets a repository append one rule selecting `*` to make all target
diagnostics errors or infos.

`off` is a reporting policy result, not a report severity and not silent
deletion. Off-level diagnostics are omitted from `issues`, excluded from
summary counts, and must be recoverable through the suppression audit view with
reason `diagnostic level off`. `off` is invalid in `fail_on` and
`suppressible_levels`.

The initial reserved diagnostic allocation is:

| Code | Short | Status | Intended surface |
|------|-------|--------|------------------|
| `CONFIG_TOML_INVALID` | `BST003` | reserved | Config loading |
| `CONFIG_FILE_MISSING` | `BST004` | reserved | Config loading |
| `CONFIG_EXTEND_MISSING` | `BST005` | reserved | Config loading |
| `CONFIG_EXTEND_CYCLE` | `BST006` | reserved | Config loading |
| `CONFIG_UNKNOWN_KEY` | `BST007` | reserved | Config validation |
| `CONFIG_TYPE_INVALID` | `BST008` | reserved | Config validation |
| `CONFIG_VALUE_INVALID` | `BST009` | reserved | Config validation |
| `CONFIG_PROFILE_UNKNOWN` | `BST010` | reserved | Config validation |
| `REPORT_JSON_INVALID` | `BST011` | reserved | Artifact loading |
| `REPORT_SHAPE_INVALID` | `BST012` | reserved | Artifact loading |
| `REPORT_SUMMARY_MISMATCH` | `BST013` | reserved | Artifact loading |
| `OUTPUT_WRITE_FAILED` | `BST014` | reserved | Invocation failure |
| `REPO_ROOT_INVALID` | `BST015` | reserved | Invocation failure |
| `INTERNAL_ERROR` | `BST016` | reserved | Tool failure |
| `SUPPRESSION_UNUSED` | `BSX001` | implemented | Suppression hygiene |
| `SUPPRESSION_WITHOUT_CODE` | `BSX002` | reserved | Suppression hygiene |
| `SUPPRESSION_UNKNOWN_CODE` | `BSX003` | implemented | Suppression hygiene |
| `SUPPRESSION_INVALID_SYNTAX` | `BSX004` | implemented | Suppression hygiene |
| `SUPPRESSION_UNSUPPRESSIBLE_CODE` | `BSX005` | implemented | Suppression hygiene |
| `SUPPRESSION_REDIRECTED_CODE` | `BSX006` | reserved | Suppression hygiene |
| `SUPPRESSION_DEPRECATED_CODE` | `BSX007` | reserved | Suppression hygiene |
| `SUPPRESSION_DUPLICATE_CODE` | `BSX008` | reserved | Suppression hygiene |
| `SUPPRESSION_BROAD_CODE` | `BSX009` | reserved | Suppression hygiene |
| `SUPPRESSION_REASON_MISSING` | `BSX010` | reserved | Suppression hygiene |
| `PACKET_JSON_INVALID` | `BSP001` | reserved | Packet loading |
| `PACKET_SHAPE_INVALID` | `BSP002` | reserved | Packet loading |
| `PACKET_SECTION_TRUNCATED` | `BSP003` | reserved | Packet generation |
| `PACKET_OWNER_TRUNCATED` | `BSP004` | reserved | Packet generation |
| `PACKET_OWNER_OMITTED` | `BSP005` | reserved | Packet generation |
| `PACKET_OWNER_NOT_FILE` | `BSP006` | reserved | Packet generation |
| `PACKET_OWNER_UNREADABLE` | `BSP007` | reserved | Packet generation |
| `PACKET_SYMBOL_NOT_FOUND` | `BSP008` | reserved | Packet generation |
| `ANALYSIS_ROW_INVALID` | `BSP009` | reserved | Analysis loading |
| `ANALYSIS_PACKET_UNKNOWN` | `BSP010` | reserved | Analysis loading |
| `MODEL_OUTPUT_INVALID` | `BSP011` | reserved | Analysis model boundary |
| `MODEL_PACKET_ID_MISMATCH` | `BSP012` | reserved | Analysis model boundary |
| `MODEL_CALL_FAILED` | `BSP013` | reserved | Analysis model boundary |
```

### `docs/specs/03-backstitch-configuration.md` - [CFG-2], [CFG-5]

Add to the mental model:

> Effective settings always start with Backstitch's packaged default TOML. A
> repository may have no discovered config, but there is never "no config" at
> runtime; there is at least the packaged default layer. `--no-config` skips
> repository discovery and explicit repository config, not packaged defaults.

Add to the `config path` contract:

> `config path` continues to report only the discovered or explicit repository
> configuration path. It does not print the packaged default resource path.
> When no repository config is found, or when `--no-config` is used, it prints
> nothing and exits `0`. `config show` is the command that displays the
> packaged default layer and the full effective settings.

Replace [CFG-5] assembly order with:

> Effective settings are assembled in this order (later sources override or
> append after earlier sources according to each key's merge rules):
>
> 1. packaged default TOML
> 2. discovered config file, after `extend` merge
> 3. environment variables where this spec defines them
> 4. explicit CLI flags and options

### `docs/specs/03-backstitch-configuration.md` - [CFG-6]

Add a new subsection after `[check]`:

```markdown
### 6.x `[diagnostics]` / `[tool.backstitch.diagnostics]`

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
[[tool.backstitch.diagnostics.levels]]
select = ["*"]
level = "info"

[tool.backstitch.diagnostics]
fail_on = []
```

`off` hides the diagnostic from normal output but keeps it visible in the
suppression/audit view.
```

Add merge rule:

> `diagnostics.levels` arrays append across config layers rather than replacing
> earlier rules. Other arrays keep their existing replace semantics unless this
> spec says otherwise.

Add packaged defaults note:

> `exclude`, `extend_exclude`, `[profile]`, `[check]`, `[packets]`,
> `[analyze]`, `[target_roots]`, `[lint]`, and `[diagnostics]` all have
> defaults in the packaged default TOML. Python dataclass defaults may mirror
> those values for type construction, but the packaged TOML is the behavioral
> source of truth.

### `docs/specs/03-backstitch-configuration.md` - [CFG-8], [CFG-9]

Add loader failure modes:

> - duplicate short diagnostic codes in the packaged registry
> - implemented diagnostics missing a default level rule
> - diagnostic selectors that match no known implemented, deprecated, or
>   redirected code, unless `allow_unknown_keys = true`
> - invalid diagnostic level values
> - reserved diagnostic codes used as ordinary suppressions

Add verification requirements:

> - `config show` must include the packaged default config layer and resolved
>   diagnostic policy
> - `config path` must keep its current repository-config meaning: it prints no
>   path for packaged defaults and prints nothing under `--no-config`
> - tests must prove `--no-config` still loads packaged defaults
> - tests must prove a repo-level `select = ["*"]` rule can override packaged
>   default specific rules
> - tests must prove short codes and long codes canonicalize to the same
>   diagnostic identity

### `docs/specs/04-backstitch-traceability-exclusions.md`

Modify the mental model:

> Suppressions operate on stable diagnostic codes. The canonical long code is
> preferred; short codes are accepted as aliases and canonicalized. Bare
> suppressions without codes are invalid by default. Suppression directives are
> themselves checked by structured suppression-hygiene diagnostics.

Replace "Markers must not suppress error-severity issue codes" with:

> Suppressibility is based on the effective diagnostic level after policy
> application and the configured `diagnostics.suppressible_levels`. By default,
> `warning` and `info` diagnostics are suppressible and `error` diagnostics are
> not. Attempts to suppress a non-suppressible effective level emit
> `SUPPRESSION_UNSUPPRESSIBLE_CODE`.

Add to [EXC-8]:

> Suppression-hygiene diagnostics use stable codes:
>
> - `SUPPRESSION_UNUSED`
> - `SUPPRESSION_UNKNOWN_CODE`
> - `SUPPRESSION_INVALID_SYNTAX`
> - `SUPPRESSION_UNSUPPRESSIBLE_CODE`
> - future reserved codes listed in [SC-15]
>
> These diagnostics enter the same report stream as other target diagnostics
> when they arise from repository files or repository configuration. Invocation
> failures while loading a requested config file still follow [SC-5] exit `2`.

## Proposed Default TOML Shape

The implementation should add `backstitch/defaults.toml` with this shape. The
full file will include all implemented and reserved registry rows from [SC-11]
and [SC-15].

```toml
[defaults]
schema_version = 1

exclude = [
  ".git",
  ".venv",
  "venv",
  "__pycache__",
  ".pytest_cache",
  ".mypy_cache",
  ".ruff_cache",
  "dist",
  "build",
  ".worktrees",
]

[profile]
name = "backstitch-style-v1"
spec_roots = ["docs/specs"]
plan_roots = ["docs/plans"]
code_roots = ["backstitch", "tests"]
planned_spec_globs = []
exploratory_spec_globs = []
meta_spec_globs = []

[check]
format = "text"
warnings_as_errors = false

[analyze]
concurrency = 1

[diagnostics]
default_level = "warning"
fail_on = ["error"]
suppressible_levels = ["warning", "info"]

[[diagnostics.levels]]
select = [
  "SCAN_ROOT_MISSING",
  "FILE_UNREADABLE",
  "SPEC_FILE_MISSING",
  "SPEC_SECTION_MISSING",
  "SPEC_ANCHOR_MISSING",
  "REF_RANGE_UNSUPPORTED",
  "TARGET_PATH_AMBIGUOUS",
  "MAPPING_SYMBOL_MISSING",
  "SPEC_SECTION_AMBIGUOUS:asserted",
  "MAPPING_PATH_MISSING:required",
]
level = "error"

[[diagnostics.levels]]
select = [
  "SPEC_SECTION_UNMAPPED",
  "CODE_REF_UNMAPPED_FROM_SPEC",
]
level = "info"

[[diagnostics.levels]]
select = [
  "SPEC_SECTION_AMBIGUOUS:weak",
  "MAPPING_PATH_MISSING:plan-artifact",
]
level = "warning"

[diagnostics.registry.SPEC_FILE_MISSING]
short = "BSS001"
status = "implemented"
summary = "Referenced spec file does not exist"

[diagnostics.registry.SUPPRESSION_UNUSED]
short = "BSX001"
status = "implemented"
summary = "Suppression matched no diagnostic"
```

`exclude` is top-level in the standalone default TOML shape, matching current
[CFG-6.7]. It is not a `[profile]` field. Optional values with no TOML `null`
representation, such as `packets.output`, are omitted rather than represented
as empty strings.

Exact final key names may be tightened during spec promotion, but the
semantics above are not optional without updating the deviation log.

## Tasks

1. **Independent plan review before implementation.**
   - Files to read: this plan, `docs/specs/02-backstitch-core.md`,
     `docs/specs/03-backstitch-configuration.md`,
     `docs/specs/04-backstitch-traceability-exclusions.md`,
     `backstitch/models.py`, `backstitch/settings.py`,
     `backstitch/exclusions.py`.
   - Prompt: "Read the plan and Proposed Spec Delta. Could you implement this
     confidently and correctly against the delta as if promoted? Find bad
     ideas, latent ambiguities, missing invariants, and weak verification."
   - Done signal: feedback is recorded in this plan under
     `## Independent Review Incorporation`, and each point is accepted,
     rejected with reason, or marked out of scope.

2. **Spec-promotion slice.**
   - Files to touch:
     - `docs/specs/02-backstitch-core.md`
     - `docs/specs/03-backstitch-configuration.md`
     - `docs/specs/04-backstitch-traceability-exclusions.md`
   - Apply the exact proposed spec delta or update this plan's deviation log
     before changing direction.
   - Add this plan under each touched spec's `## Related Plans`.
   - Do not add implementation mappings for new spec text until code and tests
     land in the relevant slice.
   - Verify by inspection plus `uv run pytest tests/test_models.py -q` after
     code catches up. During the spec-only slice, expected traceability debt is
     `SPEC_SECTION_UNMAPPED` info only.
   - Done signal: promotion baseline identifier recorded in `## Spec Baseline`.

3. **Add the diagnostic registry loader and packaged defaults.**
   - Files to touch:
     - new `backstitch/defaults.toml`
     - new `backstitch/diagnostics.py`
     - `backstitch/models.py`
     - `tests/test_models.py`
     - new or updated `tests/test_diagnostics.py`
   - Implement registry loading through `importlib.resources` and `tomllib`.
   - Validate unique long codes, unique short codes, valid statuses, valid
     default summaries, valid redirects, valid contexts, and no emitted
     implemented code missing a registry row.
   - Replace hard-coded `ISSUE_CODES` and `ERROR_SEVERITY_CODES` as behavioral
     sources. Compatibility constants may remain as derived values if tests or
     callers need them.
   - Stop gate: if registry loading makes import-time failures hard to diagnose,
     introduce an explicit `load_default_diagnostics()` call with clear
     exception types; do not hide registry parse failures as generic internal
     errors.
   - Tests:
     - registry rejects duplicate short codes
     - registry rejects invalid levels/statuses
     - current implemented diagnostics match [SC-11]
     - reserved diagnostics are visible in registry but cannot be emitted as
       ordinary issue records
   - Done signal: registry tests pass and no code path still owns a separate
     hand-maintained issue-code inventory.

4. **Represent diagnostic context and effective policy on issues.**
   - Files to touch:
     - `backstitch/models.py`
     - `backstitch/resolver.py`
     - `backstitch/markdown_specs.py`
     - `backstitch/python_refs.py`
     - `tests/test_resolver.py`
     - `tests/test_issue_code_coverage.py`
   - Extend `Issue` with `short_code`, `context`, and `default_severity`
     while keeping `severity` as the effective level for compatibility.
   - Resolver/parser emission sites provide context for:
     - `SPEC_SECTION_AMBIGUOUS`: `asserted` or `weak`
     - `MAPPING_PATH_MISSING`: `required` or `plan-artifact`
- Do not make resolver depend on CLI arguments or discovered config. It
  emits identity plus default context; policy is applied afterward.
- `default_severity` must be computed from the packaged default policy, not
  from the fully merged effective config.
- Tests:
  - context-dependent codes retain correct `default_severity`
  - short code is populated from registry
  - a repo override of a warning to error/info/off leaves JSON
    `default_severity` at the packaged default
  - structured tests stop relying on message wording
   - Done signal: existing resolver behavior is unchanged under packaged
     default policy, except for added structured fields.

5. **Implement ordered diagnostic policy.**
   - Files to touch:
     - `backstitch/diagnostics.py`
     - `backstitch/settings.py`
     - `backstitch/check_pipeline.py`
     - `backstitch/cli.py`
     - `tests/test_settings.py`
     - `tests/test_cli_config.py`
     - `tests/test_check_pipeline.py`
   - Add `DiagnosticsSettings` with:
     - `default_level`
     - ordered `levels` rules
     - `fail_on`
     - `suppressible_levels`
   - Implement selector resolution for:
     - `*`
     - canonical long code
     - short code
     - family prefix ending in `*`
     - context selectors `CODE:context` and `SHORT:context`
- Apply policy after scan emission and before suppression/exit decisions.
- Apply policy in two passes: packaged-default-only policy populates
  `default_severity`; the full layered effective policy populates report
  `severity` or moves the diagnostic to the audit collection when the result is
  `off`.
- Preserve `--warnings-as-errors` and `[check].warnings_as_errors` by
  modifying effective `fail_on`, not by rewriting levels.
   - Tests:
     - all-error repo config exits `1` for formerly warning/info findings
     - all-info repo config exits `0` with findings rendered as info
     - mixed policy overrides a single code
  - context selector overrides one context only
  - repo `select = ["*"]` overrides packaged specific defaults
  - `off` hides from default output and appears in audit output
  - `off` is rejected in `fail_on` and `suppressible_levels`
  - packet generation obeys `fail_on`, all-error, all-info, and `off` policy
    through a real `packets` subprocess test
   - Stop gate: if ordered rules make `config show` misleading, add a rendered
     resolved-policy section that lists each implemented code's final level.
   - Done signal: `check`, `packets`, text output, and JSON output all use the
     same policy path.

6. **Move built-in settings into packaged default TOML.**
   - Files to touch:
     - `backstitch/defaults.toml`
     - `backstitch/settings.py`
     - `backstitch/profiles.py`
     - `backstitch/config.py`
     - `backstitch/cli.py`
     - `tests/test_settings.py`
     - `tests/test_config.py`
   - Load packaged defaults before repo config for every command.
   - Rework `discover_config_path` and `load_settings` so "no discovered repo
     config" still yields settings sourced from `backstitch/defaults.toml`.
   - `--no-config` skips repo discovery only.
   - Keep built-in profile names valid, but source their default fields from
     packaged TOML. If a thin Python registry remains for profile names, it must
     derive values from TOML and be tested against TOML.
   - Tests:
     - no repo config still reports a packaged config layer in `config show`
     - `--no-config` and no-config discovery both use packaged defaults
     - repo config overrides packaged defaults
     - explicit `--config` layers over packaged defaults
     - `extend` still works and diagnostics rules append in order
   - Done signal: changing packaged default TOML in a fixture changes behavior
     through the real settings loader; no duplicated defaults remain as an
     authoritative Python source.

7. **Convert suppression diagnostics from raw warnings to structured issues.**
   - Files to touch:
     - `backstitch/exclusions.py`
     - `backstitch/check_pipeline.py`
     - `backstitch/reporting.py`
     - `backstitch/settings.py`
     - `tests/test_exclusions.py`
     - `tests/test_python_noqa.py`
     - `tests/test_review_remediation.py`
   - Implement at least:
     - `SUPPRESSION_UNUSED`
     - `SUPPRESSION_UNKNOWN_CODE`
     - `SUPPRESSION_INVALID_SYNTAX`
     - `SUPPRESSION_UNSUPPRESSIBLE_CODE`
   - Keep future hygiene codes reserved until each has a firing test.
   - Suppression diagnostics from repository files/config enter the report with
     locator metadata. Config-load failures for explicit missing/malformed files
     remain exit `2` and are not converted into target diagnostics in this
     slice.
   - Bare suppressions without codes remain invalid. If compatibility pressure
     requires accepting them, add `SUPPRESSION_WITHOUT_CODE` and update the
     deviation log.
   - Tests:
     - stale ignore emits `SUPPRESSION_UNUSED`
     - unknown code emits structured diagnostic under the compatibility hatch
       and exits `2` under strict load where current spec requires it
     - error-level suppression emits `SUPPRESSION_UNSUPPRESSIBLE_CODE`
     - malformed inline directive emits `SUPPRESSION_INVALID_SYNTAX`
     - all structured suppression diagnostics obey diagnostic policy
   - Done signal: no suppression warning that affects repository state remains
     only a raw stderr string.

8. **Update rendering, JSON validation, and artifact consumers.**
   - Files to touch:
     - `backstitch/reporting.py`
     - `backstitch/artifact_contracts.py`
     - `backstitch/analysis_packets.py`
     - `backstitch/analysis_results.py`
     - `tests/test_reporting.py`
     - `tests/test_artifact_contracts.py`
     - `tests/acceptance/`
   - Text output renders `[SHORT LONG]`.
   - JSON report validates `short_code`, `context`, `default_severity`, and
     effective `severity`.
   - Packet generation carries the richer issue records without treating
     semantic packet warnings as deterministic issue codes.
   - `summarize-analysis` continues to separate deterministic counts from
     semantic advisory findings.
   - Tests:
     - self-acceptance accepts new JSON report shape
     - old malformed-report probes still exit `2`
     - packet loader validates richer issue records
   - Done signal: acceptance probe 13 passes with the new report and packet
     shapes.

9. **Documentation and traceability reconciliation.**
   - Files to touch:
     - `docs/implementation/04-backstitch-style-traceability.md`
     - `docs/implementation/02-repository-map.md`
     - `docs/specs/00-specs-index.md`
     - `README.md` if command examples or config examples need updates
     - this plan's status and deviation log
   - Add implementation mappings/backlinks for the promoted spec text.
   - Remove or narrow temporary markers, if any were added during spec
     promotion.
   - Evaluate whether this work exposes a durable lesson for `docs/lessons.md`.
   - Done signal: `uv run backstitch check --repo-root .` exits `0` with zero
     errors and zero warnings under the repository's committed config.

10. **Independent implementation review.**
    - Run after the meaningful slices that change:
      - registry/defaults loading
      - diagnostic policy application
      - suppression-hygiene diagnostics
      - final reconciliation
    - Reviewer reads the promoted specs, this plan, implementation doc, and
      touched files.
    - Done signal: every review finding is reproduced or explicitly rejected
      with reasoning; resulting changes are verified.

## Testing Plan

Use real TOML files, real subprocesses, and real parser/resolver paths. Do not
mock the settings loader, resolver, suppression engine, or report renderer.
Fakes remain appropriate only for external model calls in existing semantic
analysis tests.

Targeted tests:

- `tests/test_diagnostics.py`
  - registry shape
  - short-code uniqueness
  - selector matching
  - ordered policy resolution
  - reserved/deprecated/redirected status handling
- `tests/test_settings.py` and `tests/test_cli_config.py`
  - packaged defaults always load
  - repo config overlays packaged defaults
  - `--no-config` skips repo config only
  - diagnostics rules append in source order
  - `config show` exposes config layers and resolved policy
  - `config path` prints only repository config paths and prints nothing for
    packaged defaults or `--no-config`
- `tests/test_resolver.py` and `tests/test_issue_code_coverage.py`
  - current deterministic diagnostics still fire
  - context-dependent diagnostics expose context and default severity
  - implemented codes all have firing tests
- `tests/test_exclusions.py` and `tests/test_python_noqa.py`
  - suppression hygiene codes fire
  - suppressibility follows effective level policy
  - audit output recovers suppressed/off diagnostics
- `tests/test_cli.py`
  - all-error and all-info CLI behavior
  - `fail_on = []`
  - `--warnings-as-errors` compatibility
  - exit `2` failures remain non-configurable
  - `packets` subprocess behavior for `fail_on`, all-error, all-info, and
    `off`, using a real output file
- `tests/test_artifact_contracts.py`, `tests/test_analysis_packets.py`, and
  acceptance probes
  - richer issue records validate
  - packet and analysis boundaries remain separate

Final commands:

```bash
uv run pytest tests/test_diagnostics.py tests/test_settings.py tests/test_cli_config.py -q
uv run pytest tests/test_models.py tests/test_issue_code_coverage.py tests/test_exclusions.py tests/test_python_noqa.py -q
uv run pytest tests/test_reporting.py tests/test_artifact_contracts.py tests/test_analysis_packets.py -q
uv run pytest tests/acceptance -q
uv run pytest -q
uv run ruff check backstitch tests bin/release.py
uv run ruff format --check backstitch tests bin/release.py
uv run mypy backstitch bin/release.py tests
uv run backstitch check --repo-root .
```

Success criteria:

- all commands exit `0`
- default self-corpus has zero errors and zero warnings
- every suppression/off-policy hidden finding is auditable
- every implemented diagnostic code has a firing test
- every reserved diagnostic code is rejected as an emitted issue until promoted

## Verification And Gates

Per-slice gates are named in `## Tasks`.

### 2026-07-10 strict self-corpus remediation

After the repository enabled a final `select = ["*"]`, `level = "error"`
rule, the advertised self-corpus command exited `1` with 23
`CODE_REF_UNMAPPED_FROM_SPEC` errors. The same records had previously been
info-level debt. This follow-up repairs the debt without changing diagnostic
policy or adding suppressions.

The 23 records divide into two evidence-backed classes:

- 18 references identify real implementation owners omitted from reciprocal
  mappings in [SC-3], [SC-4], [SC-5], [SC-6], [SC-8], [SC-11], [CFG-3],
  [CFG-5], [CFG-8], and [EXC-4]. Add those files to the owning sections.
- Five references are not implementation ownership: three production comments
  cite verification-only [CFG-9], one production docstring cites
  verification-only [EXC-9], and one exclusions rationale cites [SC-11] even
  though [EXC-8] already owns that behavior. Remove only those over-broad
  citations and retain their behavioral citations.

Required gate: rerun the strict self-corpus command with
`--show-suppressions`; it must exit `0` with zero visible errors, warnings, and
infos. Existing meta-spec and test-file suppressions must remain auditable, and
no invariant finding may be suppressed. Then rerun static checks, acceptance
tests, and the full suite before restoring the plan's verified status.

Observed result: the strict self-corpus command exits `0` with 58 sections,
144 mappings, 269 code references, 3 invariants, and zero visible findings.
Its 159 existing suppressions remain auditable (146 test-file code-reference
records and 13 meta-spec section records), with no suppressed invariant
finding. Diff hygiene, Ruff, format, mypy, all 18 acceptance probes, and the
full suite pass; the full suite skips only the opt-in live-LLM test.

Verification run on 2026-07-08:

| Command | Result |
|---------|--------|
| `uv run pytest tests/test_diagnostics.py tests/test_exclusions.py tests/test_settings.py tests/test_issue_code_coverage.py -q` | Pass |
| `uv run ruff check backstitch tests bin/release.py` | Pass |
| `uv run ruff format --check backstitch tests bin/release.py` | Pass |
| `uv run mypy backstitch bin/release.py tests` | Pass |
| `uv run pytest tests/acceptance -q` | Pass |
| `uv run pytest -q` | Pass; one live LLM test skipped because `BACKSTITCH_LIVE_LLM=1` was not set |
| `uv run backstitch check --repo-root . --show-suppressions` | Pass; exit 0, 0 errors, 0 warnings, 33 infos, suppressed diagnostics auditable |

Task 2 prerequisite rerun on 2026-07-09 used base
`fc7427180fcbc99eb19ae5771a2231546ddd026b`. The uncommitted implementation,
spec, and test baseline contains 31 changed paths excluding this plan and the
invariant plan; its sorted per-file SHA-256 manifest hashes to
`6d351d49dd2450f739dc05cdb930dad32681e90dffe5707bdebd3117a0ebf4eb`.
Targeted diagnostics tests, acceptance probes, the full suite, Ruff, format,
mypy, `config show`, and the self-corpus audit all passed. The full suite had
one expected opt-in live-LLM skip; self-corpus remained 0 errors, 0 warnings,
33 infos.

Final gate before claiming implementation complete:

- Promoted specs, implementation doc, code, and tests form a closed traceability
  chain.
- `backstitch/defaults.toml` is the behavioral source of truth for default
  profile, exclude, diagnostics, and report policy.
- `config show` proves the packaged defaults layer is visible.
- `check`, `packets`, text rendering, JSON rendering, suppression audit, and
  exit decisions all use the same effective diagnostic policy.
- No test parses rendered messages for structure.
- `uv run backstitch check --repo-root .` exits `0`, zero errors, zero warnings,
  and suppressions are auditable with `--show-suppressions`.

Post-deploy/user-facing success signals:

- Users can set one rule selecting `*` to make every target diagnostic an
  error or info.
- Users can suppress by canonical long code or short code.
- Stale or invalid suppressions are reported as structured diagnostics, not
  raw strings.
- Existing users of `--warnings-as-errors` see the same exit behavior.

## Independent Review Loop

Preferred review path: different agent family if available; otherwise a
same-family reviewer in strict plan-review mode.

Review prompt:

> Read `docs/plans/2026-07-08-configurable-diagnostics-plan.md`, especially
> `## Proposed Spec Delta`. Also read `docs/specs/02-backstitch-core.md`,
> `docs/specs/03-backstitch-configuration.md`,
> `docs/specs/04-backstitch-traceability-exclusions.md`,
> `backstitch/models.py`, `backstitch/settings.py`,
> `backstitch/exclusions.py`, and `backstitch/check_pipeline.py`. Look for
> errors, bad ideas, missing invariants, weak verification, and implementation
> traps. Do not implement. Could you implement this confidently and correctly
> against the delta as if promoted?

The authoring agent must incorporate or answer every finding under
`## Independent Review Incorporation` before implementation starts.

## Independent Review Incorporation

Review agent: `019f4251-112b-76a3-b733-9baa11be3647` ("Peirce"), completed
2026-07-08. Initial verdict: not yet confidently implementable because of
default TOML table scope and incomplete `off` lifecycle. Findings addressed:

| Finding | Disposition | Plan change |
|---------|-------------|-------------|
| Default TOML put `exclude` under `[profile]`, conflicting with [CFG-6.7]. | Accepted. | Moved `exclude` to top-level in the default TOML sketch and added a note that it is not a profile field. |
| `off` was underspecified as a report/audit state. | Accepted. | Spec delta now states `off` is not a report severity, never appears in `report.issues`, is excluded from summary counts, is invalid in `fail_on` and `suppressible_levels`, and is recoverable only through audit output. |
| `packets` exit-policy change lacked explicit tests. | Accepted. | Task 5 and the Testing Plan now require real `packets` subprocess tests for `fail_on`, all-error, all-info, and `off`. |
| `packets.output = ""` in packaged defaults would become a real path. | Accepted. | Removed `[packets] output = ""` from the default TOML sketch and added a rule to omit optional values that have no TOML `null` representation. |
| `default_severity` could collapse into effective severity. | Accepted. | Added an invariant and Task 4/5 requirements for two policy evaluations: packaged-default-only for `default_severity`, fully layered policy for effective `severity`. Added an override test. |
| `config path` semantics were ambiguous once packaged defaults always load. | Accepted. | Config spec delta now says `config path` reports only repository config paths, prints nothing for packaged defaults or `--no-config`, and `config show` owns layer display. |

Implementation review agent: `019f427f-ea6f-7d03-86f6-4ad3cf246c8f`
("Pasteur"), completed 2026-07-08. Review was read-only against the promoted
specs, this plan, implementation docs, and changed code. Findings addressed:

| Finding | Disposition | Change |
|---------|-------------|--------|
| Reserved diagnostics could be accepted as ordinary suppressions and could be emitted by constructing an `Issue` with a reserved code. | Accepted. | `Issue` metadata resolution and suppression parsing now require implemented ordinary diagnostics. Reserved registry entries remain visible but cannot be emitted or used as ordinary suppressions. Added diagnostics and exclusion tests. |
| Context selectors such as `SPEC_FILE_MISSING:any` were accepted for diagnostics that define no contexts. | Accepted. | Policy selector validation now rejects context selectors for contextless diagnostics. Added a policy test. |
| Repository config accepted `diagnostics.registry`, but the parser ignored it because only packaged defaults own the registry. | Accepted. | Repo configs are validated before merge so `diagnostics.registry` is rejected by default; the packaged default TOML is the only layer allowed to define registry entries. Added a settings test. |
| The generic firing gate excluded all `SUPPRESSION_*` diagnostics, leaving implemented hygiene codes without registry-driven firing proof. | Accepted. | Added CLI firing fixtures for each implemented suppression-hygiene code and a registry coverage assertion for the current `SUPPRESSION_*` set. |
| The implementation doc claimed reserved-code rejection coverage before it existed. | Accepted. | The coverage now exists through `test_reserved_diagnostics_cannot_be_emitted`, reserved-code suppression tests, and the repo `diagnostics.registry` rejection test. |

Claude adversarial review: attempted through the `/claude` skill on
2026-07-08, but the skill auth gate failed because Claude CLI had no local
credentials and `ANTHROPIC_API_KEY` was unset. No Claude findings were
available to incorporate.

Task 2 audit reviewer `019f4953-31df-7e61-b6b3-27f9035735d0` ("Hilbert")
found seven remaining contract/test gaps on 2026-07-09. All reproduced
findings were fixed: suppression hygiene now stays structured from producer to
policy, artifact issue validation enforces context/default identity, diagnostic
aliases resolve replacement chains, wildcard-context selectors are rejected,
all packet policy modes have discriminating subprocess tests, `default_level`
and `suppressible_levels` have production-path no-op prevention tests, and all
`--no-config` help surfaces name packaged defaults. Focused re-review agent
`019f4963-db53-7e41-ae6e-164806c57af0` ("Singer") found two weak follow-ups;
after strengthening packet test discrimination and completing every help
surface, its final verdict was "No findings."

## Out Of Scope

- No automatic code/documentation fixes.
- No editor/LSP integration beyond structured report fields.
- No provider-specific doctor changes.
- No semantic-classification CI policy.
- No migration of doctor checks into deterministic issue records.
- No implementation of every reserved diagnostic code in the initial runtime
  slice. Reserved codes document the allocation list; they become implemented
  only with firing tests.
- No new parser or language support.
- No new dependency.

## Fresh-Eyes Checklist

- Does the plan name the exact config syntax to implement?
- Can an implementer tell how `select = ["*"]` overrides packaged defaults?
- Does the plan preserve exit `2` as non-configurable?
- Does the plan explain what happens to context-dependent diagnostics?
- Does the plan say where suppressions become structured diagnostics?
- Does every new public contract have a test path?
- Does the plan avoid treating short codes as the primary identity?
- Does the plan prevent hidden/off diagnostics from becoming unauditable?
