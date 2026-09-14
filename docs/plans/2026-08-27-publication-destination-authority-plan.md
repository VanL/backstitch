# Publication Destination Authority Plan (2026-08-27)

Status: superseded before implementation by
`docs/plans/2026-09-14-review-findings-remediation-plan.md`. This draft is
retained as design history; its proposed CLI destination-alias guard was not
adopted. The successor removed repository-configured destinations and reused
atomic publication with a smaller authority boundary.

> **For agentic workers:** execute task-by-task in dependency order. Steps use
> checkbox (`- [ ]`) syntax for tracking. Do not start code slices before the
> spec-promotion slice and its independent delta review (see [DOM-15] class-5
> row and `runbooks/writing-plans.md` §4d).

**Class:** 5 — normative spec text changes ([CFG-5.1], [CFG-6], [CFG-7],
[CFG-9], [SC-5], [COV-9]). A [DOM-5] risky trigger also fires — a public
contract and CLI-compatibility surface is changing (configuration keys are
removed; a new rejection and a new publication guarantee are added) — so the
hardening-plans checklist applies and independent review precedes
implementation.

**Plan type:** implementation with spec revision.

## 1. Goal

Repository configuration must never choose a publication destination.
Today a scanned repository's `.backstitch.toml` can set `check.output` or
`coverage.output` and direct the report write to any path the invoking user
can write — through symlinks, outside the repository, over the selected
config file (review finding 1, P1). Separately, `check --output` publishes
with a plain `write_text`, so a failed write leaves a truncated report even
though the repository already owns an atomic same-directory publication
helper (review finding 4, P2).

This plan removes `check.output`, `coverage.output`, and the reserved
`packets.output` from the configuration schema (destination authority stays
with the invocation's `--output` flag), makes `check --output` publication
atomic through the existing `backstitch/artifact_publication.py` owner, and
adds a destination guard for explicit `--output` on `check` and `coverage`:
exit `2` when the resolved destination aliases a selected configuration
layer file (the no-follow stat identity of the directory entry
publication replaces).

Owner decision recorded 2026-08-27 (this session): removal, not a
constrained configuration-output policy.

## 2. Source Documents

Source specs:

- `docs/specs/02-backstitch-core.md` [SC-5], [SC-16] (identity framing only)
- `docs/specs/03-backstitch-configuration.md` [CFG-5], [CFG-5.1], [CFG-6]
  (§6.3, §6.4, §6.14), [CFG-7], [CFG-9]
- `docs/specs/08-intent-coverage.md` [COV-9]
- `docs/specs/07-verification-and-evidence-cases.md` [EVC-5.1] — precedent
  for the destination-overlap rule shape; **not edited** by this plan

Origin: independent review 2026-08-27, findings 1 (P1,
repository-controlled publication) and 4 (P2, non-atomic check
publication), both reproduced and confirmed in-session against
`7d1bb154665e7fca1d8cf2c16d5fd62a0e9cd2db`.

## 3. Context and Key Files

Read first (in this order):

1. `docs/specs/03-backstitch-configuration.md` [CFG-5] (precedence),
   [CFG-5.1] (alias map, generic `--option` rules), §6.3/§6.4/§6.14
   (closed tables)
2. `docs/specs/02-backstitch-core.md` [SC-5] — the CLI contract: bare
   dispatch paragraph (~line 338), exit-code taxonomy paragraph
   (~line 669: exit `1` is about the target, exit `2` about the
   invocation/tool)
3. `docs/specs/08-intent-coverage.md` [COV-9]
4. `backstitch/artifact_publication.py` — the existing publication owner
   (`atomic_replace_bytes` at line 35: same-directory `mkstemp`, fsync,
   `os.replace`, directory fsync)
5. `backstitch/semantic_application.py:303` (`_current_paths`) — the
   analyze-side destination rule this plan's guard mirrors
6. `docs/agent-context/runbooks/adversarial-acceptance-probes.md` —
   required before declaring integration-ready

### Current behavior (what exists today)

- `backstitch/cli.py:543-554` (inside `_dedicated_cli_overrides`,
  defined at line 528): the `check` and `coverage` subcommands fold
  `args.output` into the generic override layer as
  `overrides["check.output"]` / `overrides["coverage.output"]`.
  `--output` is therefore a *setting alias* today, per the [CFG-5.1]
  alias map.
- `backstitch/settings.py`:
  - `_CHECK_KEYS` (line 134) = `{"format", "warnings_as_errors", "output"}`
  - `_PACKETS_KEYS` (line 135) = `{"output"}` (reserved, parsed, never
    consulted — dead schema by the repo's own [CFG-5] comment standard)
  - `_COVERAGE_KEYS` (line 136) includes `"output"`
  - `_COVERAGE_PRESENTATION_KEYS` (line 159) =
    `{"coverage.format", "coverage.output"}` (ratchet policy-identity
    exclusions; also consulted at line 2251 in the raw-body walk)
  - `CheckSettings.output` (line 488), `PacketsSettings` (line 495),
    `CoverageSettings.output`
  - `_parse_optional_output_path` (line 2570) — helper used by the check
    parse (line 2606) and packets parse (line 2689)
  - `_expand_named_output_paths` (line 2342) — expands
    `check.output`/`packets.output`/`coverage.output`/
    `analyze.cache_path`/`verify.cache_path` with contributing-layer
    anchoring and symlink resolution; a second extend-chain re-anchoring
    comment mentions `check.output` at line 2396
  - coverage table parse: `output` validation at line 2803, expansion at
    ~line 2844
- `backstitch/cli.py:609-652` (`_cmd_check`): reads
  `settings.check.output` (line 635, with the [CFG-5] comment at 632)
  and publishes via `output.write_text` (line 647) — non-atomic,
  follows symlinks, no aliasing check. Unwritable path → `_error` →
  exit `2` (contract pinned by spec 02 [SC-5] and the comment at 644).
- `backstitch/coverage_application.py`: `CoverageRequest` (line 131) has
  no output field; `_coverage_result` sets
  `CoverageResult.output_path` from `settings.coverage.output`
  (lines 1199-1203); `publish_coverage` (line 1253) already publishes
  through `artifact_publication.atomic_replace_bytes`.
- `backstitch check --repo-root .` (the hermetic self-corpus gate)
  discovers the `[tool.backstitch]` layer in this repo's
  `pyproject.toml` (line 71); that layer sets no output keys, so this
  plan does not change the gate's own inputs.
- `settings_to_json` (`settings.py:1935` region) renders
  `"check": asdict(settings.check)` and
  `"packets": asdict(settings.packets)` into `config show` output — a
  production consumer of the removed surfaces: the `check.output` field
  disappears from the rendered dict automatically when the dataclass
  field goes, but the `"packets"` entry must be deleted by hand along
  with `PacketsSettings`, and `config show`'s rendered shape loses both.
- The unknown-key path has a spec'd hatch: `allow_unknown_keys = true`
  (§6.1, default `false`) downgrades unknown-key errors to warnings.
  Removed keys under the hatch are warned about and ignored — never
  consulted — so the security property holds either way; only the
  loud-failure claim is scoped to the strict default.

### Comprehension questions (answers go in the execution log before editing)

1. Where does CLI `--output` for `check` enter effective settings today,
   and why is the resulting value provenance-free?
   **Expected:** `cli.py:546-547` folds it into
   `overrides["check.output"]`; `CheckSettings.output` is a bare
   `str | None` with no origin record, so at `cli.py:635` a
   config-chosen and a CLI-chosen destination are indistinguishable.
2. Why is coverage publication already truncation-safe but still part of
   finding 1?
   **Expected:** `publish_coverage` uses `atomic_replace_bytes`
   (old-complete-or-new-complete), but the destination itself can come
   from repository config (`settings.coverage.output`), and atomicity
   does not constrain who chose the target.
3. After removal, why must `"output"` leave the skip-set at
   `settings.py:2251` and `_COVERAGE_PRESENTATION_KEYS`?
   **Expected:** those sets exclude presentation-only keys from the
   canonical ratchet policy identity; once `coverage.output` is an
   unknown key, any config carrying it fails resolution before identity
   computation, so the entries are dead and keeping them would
   misdocument the schema.

## 4. Invariants and Constraints

Must not change:

- **Exit-code taxonomy** ([SC-5]): findings are exit `1`; invocation,
  configuration, and output-publication failures are exit `2` with a
  one-line error and no traceback. The new destination-guard and
  unknown-key rejections are exit `2`.
- **stdout report bytes** for `check`/`coverage` runs without `--output`
  are byte-identical before and after this change.
- **CWD anchoring for CLI artifact paths** ([CFG-5.1]): `--output`
  remains resolved against the process working directory, exactly as
  packet/analyze `--output` paths are today.
- **Coverage publication stays on the `artifact_publication` owner** —
  no second publication path may appear; `check` joins the same owner.
- **Ratchet-mode rejection surface** ([COV-5]/[COV-9]) is otherwise
  unchanged: `--format`, the root alias, `--output`, and
  `--require-ratchet` remain the only operational CLI inputs.
- **Analyze/verify path machinery is untouched**: `_current_paths`,
  cache-path expansion rows for `analyze.cache_path` /
  `verify.cache_path`, and everything under [EVC-5.1] stay as they are
  (review finding 2 is a separate change).
- **Unknown-key rejection style**: removed keys fail through the
  existing closed-table unknown-key path and its existing
  `ConfigLoadError` message format — do not invent a bespoke
  "this key was removed" error type.
- **No agent self-attribution** in commits; **no new dependencies**.

Hidden couplings to respect:

- The blob-backed config adapter shares the same closed-key parser, and
  ratchet resolves historical configs at the merge base **and at every
  first-parent transition** in the audit window
  (`coverage_application.py:662` region,
  `resolve_repository_config_from_blobs`). A historical committed config
  carrying a removed key fails resolution anywhere in that window under
  strict handling (warn-and-ignore under the `allow_unknown_keys`
  hatch). **Accepted compatibility break** (pre-1.0, internal
  positioning; contract churn explicitly authorized): recovery is
  editing the config and moving the ratchet base forward, which discards
  part of the ratchet audit window — also accepted. Record this in the
  spec delta, not just here.
- `config show` renders settings via dataclass fields — removing the
  fields removes them from `config show` output automatically; parity
  tests (`tests/test_config_parity.py`, `tests/test_cli_config.py`) may
  pin the rendered shape and need updating, not silencing.
- `_expand_named_output_paths` also feeds the extend-chain re-anchoring
  path (comment at `settings.py:2396`); both tables lose the
  check/packets/coverage rows, and the cache-path rows must remain.

Error-path priorities: every failure this plan touches is **fatal**
(exit `2`). Nothing here is best-effort. The publication guarantee is
previous-state-or-new-complete, not previous-bytes-preserved: a failure
before `os.replace` leaves the previous state (the previous complete
bytes, or absence when no destination existed); a post-replace
directory `fsync` failure reports exit `2` with the complete new bytes
already in place. Neither case may downgrade to exit `1` or a warning.

One-way doors: none mechanical — rollback is a clean revert. The
contract removal is one-way only in the social sense (configs written
against the old schema break loudly); that is the intended outcome.

Stop-and-re-evaluate gates (any of these forces a pause and plan
revision, not silent continuation):

- you find a consumer of `settings.check.output`,
  `settings.coverage.output`, or `settings.packets.output` not listed in
  this plan
- the guard needs filesystem access beyond `Path.resolve(strict=False)`
  on parent directories plus a no-follow `os.stat` of the destination
  entry and each selected config layer (anything more means the identity
  model is drifting)
- ratchet tests fail for a reason other than the documented
  historical-config break
- you are tempted to keep the keys "parsed but ignored" for
  compatibility — that is the dead-schema pattern this repo forbids

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Spec Baseline

- `7d1bb154665e7fca1d8cf2c16d5fd62a0e9cd2db` —
  docs/specs/02-backstitch-core.md, docs/specs/03-backstitch-configuration.md,
  docs/specs/08-intent-coverage.md at plan authoring time.
- Plan type: implementation with spec revision.
- Promotion baseline identifier: record after the spec-promotion slice
  (diff base `7d1bb15` plus worktree spec diff, or the promotion commit
  SHA if committed).

## Proposed Spec Delta

Promotion strategy:

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| docs/specs/02-backstitch-core.md | A — in-file edits to existing active sections; no new sections, no mapping-block changes | [SC-5] |
| docs/specs/03-backstitch-configuration.md | A — same | [CFG-5], [CFG-5.1], [CFG-6] §6.3/§6.4/§6.14, [CFG-7], [CFG-9] |
| docs/specs/08-intent-coverage.md | A — same | [COV-9] |

No new `[REF-*]` sections are created, so the two-PR mapping trap does
not arise; existing `_Implementation mapping_` blocks are unchanged.

### [SC-5] — replace the bare-dispatch side-effects paragraph (currently beginning "For local use, invoking bare `backstitch` explicitly delegates…", ~line 338)

> For local use, invoking bare `backstitch` explicitly delegates command
> selection and the selected command's documented side effects to the
> effective repository configuration. Repository configuration never
> chooses a publication destination: `check` without a CLI `--output` in
> the forwarded arguments writes its report to stdout, while configured
> analyze may read credentials, write cache state, make bounded provider
> calls, and incur bounded cost under its existing contract. Bare
> dispatch is forbidden in secret-bearing hostile-target automation:
> those workflows continue to name the semantic command, select trusted
> tool configuration explicitly, and use only workflow-owned static
> overrides under [SEM-9] and [EVC-11].

(The trailing "The CLI does not infer…" sentences of the paragraph are
retained verbatim.)

### [SC-5] — insert a new paragraph immediately after the exit-code paragraph ending "…even though the scan itself may have succeeded."

> `check` and `coverage` accept their report destination only from the
> invocation: CLI `--output` is an operational argument anchored at the
> process working directory, and no configuration key names a report
> destination ([CFG-6]). Publication to `--output` is atomic through the
> same-directory staged-replacement owner: after any outcome the
> destination holds its previous state — the complete previous bytes,
> or absence when nothing existed there — or the complete new report; a
> failed publication is exit `2`; missing parent directories are created
> (matching coverage's existing behavior); and replacement targets the
> final path itself — it never follows a symlink at the final path
> component. Destination identity is the directory entry publication
> will replace: the resolved parent directory plus the final name. That
> entry must not be the same filesystem object as any selected
> configuration layer file — compared without following a
> final-component symlink, so a name alias on a case-folding filesystem
> or a hard link is rejected while a symlink pointing at a layer is
> merely replaced. Identity inspection fails closed: only a provably
> absent entry is no alias, and a violating destination — or an
> inspection failure of the destination entry or of any selected
> configuration layer — is exit `2` before capture. Committed configurations that predate this rule and still
> carry `check.output`, `coverage.output`, or `packets.output` fail
> resolution as unknown keys under the default strict handling —
> including ratchet baseline and transition resolution from historical
> blobs — while `allow_unknown_keys = true` downgrades them to the
> ordinary unknown-key warning; either way the keys are never consulted.
> The recovery is removing the key and passing `--output` at the
> invocation.

### [CFG-5.1] — alias map table

Remove the row:

> `| --output | check.output | check only |`

Replace the sentence after the table ("`--repo-root`, non-check
`--format`/`--output`, analyze report and packet paths, packet
`--output`, obligation `--limit`, and config selection controls
therefore never conflict with a generic setting key.") with:

> `--repo-root`, every `--output` path, non-check `--format`, analyze
> report and packet paths, obligation `--limit`, and config selection
> controls therefore never conflict with a generic setting key.

### [CFG-5.1] — reserved-leaf sentence (~line 334)

Replace "Reserved/non-consulted leaves such as `packets.output` are not
runtime-overridable." with:

> Publication destinations (`check`, `coverage`, `packets`, and the
> analyze report/output paths) have no configuration leaf at all and are
> therefore never addressable through `--option`.

### [CFG-5] — ratchet operational-input sentence (~line 277)

Replace "Only the root alias, `format`, `output`, and
`--require-ratchet REF` are operational CLI inputs." with:

> Only the root alias, `--format`, `--output`, and
> `--require-ratchet REF` are operational CLI inputs.

### [CFG-6] §6.3 — `[check]` table

Remove the row `| output | string | CLI --output |`.

### [CFG-6] §6.4 — `[packets]` table

Replace the table and the two sentences that follow it with:

> The `[packets]` / `[tool.backstitch.packets]` table is empty in v1.
> The command requires CLI `--output` ([SC-5]); publication destinations
> are never configuration, so every key in this table is unknown and
> receives §6.1's unknown-key handling.

### [CFG-6] §6.14 — `[coverage]` table and prose

- Remove the row `| output | nonblank path string or absent | absent |`.
- Replace "Configured `output` follows the existing contributing-layer
  path anchoring; CLI `--output` follows current-working-directory
  anchoring." with:

> CLI `--output` follows current-working-directory anchoring; no
> configuration key names a coverage report destination.

- Replace "`format` and `output` are presentation-only and may be set by
  dedicated coverage flags." with:

> `format` is presentation-only and may be set by the dedicated coverage
> flag.

### [CFG-7] — bare-dispatch authorization sentence (~line 980)

Replace "Selecting `"check"` authorizes the same configured report
output behavior as explicit check." with:

> Selecting `"check"` authorizes the same report behavior as explicit
> check: stdout, unless the forwarded arguments themselves carry
> `--output`.

### [CFG-9] — verification bullets

Replace "a configured `check.output` write and a bounded
provider-capable analyze invocation match their explicit-command
behavior in local tests, while trusted hostile-target workflows are
statically checked to retain explicit commands and trusted config
selection" with:

> bare `check` dispatch writes to stdout and matches explicit-command
> behavior in local tests; configured `check.output`,
> `coverage.output`, and `packets.output` keys are rejected as unknown
> keys with exit `2` under the default strict handling (warned and
> ignored under `allow_unknown_keys = true`, never consulted either
> way); trusted hostile-target workflows are statically
> checked to retain explicit commands and trusted config selection

Replace "presentation-only format/output overrides cannot change the
canonical policy identity" with:

> the presentation-only format override cannot change the canonical
> policy identity

### [COV-9] — CLI contract sentences

Replace "`--format` and `--output` override their config keys." with:

> `--format` overrides its config key; `--output` is an invocation-only
> operational argument — no configuration key names a coverage report
> destination, and a `coverage.output` key is handled as an unknown key
> under [CFG-6] §6.1 (an error by default, warned and ignored under
> `allow_unknown_keys = true`, never consulted either way).

Replace "Output publication is atomic." (in the exit-code paragraph)
with:

> Output publication is atomic, creates missing parent directories,
> replaces the final path itself without following a final-component
> symlink, and rejects (exit `2`, before capture) a destination whose
> directory entry (resolved parent plus final name, compared without
> following a final-component symlink) is the same filesystem object as
> a selected configuration layer file, or whose identity inspection —
> of the entry or of any selected layer — fails.

### [COV-5] — configuration example (~line 585)

Delete the line `# output = "coverage.json"    # optional; absent means
stdout` from the `[tool.backstitch.coverage]` example block — a
commented-out example of a now-invalid key would document the removed
surface.

### All three specs — `## Related Plans`

Add under each spec's `## Related Plans` heading:

> - `docs/plans/2026-08-27-publication-destination-authority-plan.md` —
>   removes configuration-owned publication destinations; atomic check
>   publication; destination guard.

## Rollback and Rollout

- **Rollback:** revert the landing commit(s). Spec text and code land
  together (single working set; one commit or a spec+code pair landed
  back-to-back), so a revert restores both the old schema and the old
  write path with no intermediate broken state. No data, cache, or
  artifact migration exists; `artifact_publication` is untouched.
- **Rollout sequencing:** none beyond slice order below. There is no
  deploy; consumers are repo-local invocations and CI.
- **Post-landing success signals:** hermetic self-corpus gate exit `0`;
  acceptance probes green; a fixture config carrying `check.output`
  observably exits `2` with a one-line unknown-key error; fault-injected
  (pre-replace) check publication leaves the previous report bytes
  intact.

## 5. Tasks

### Task 1 — Spec-promotion slice

**Files:** `docs/specs/02-backstitch-core.md`,
`docs/specs/03-backstitch-configuration.md`,
`docs/specs/08-intent-coverage.md`

- [ ] Apply every edit in `## Proposed Spec Delta` exactly, including
      the three `## Related Plans` backlinks.
- [ ] Record the promotion baseline identifier in `## Spec Baseline`.
- [ ] Run `backstitch check --repo-root .` — expect exit `0`, zero
      errors, zero warnings (prose/table edits inside existing mapped
      sections must not disturb the graph). If a traceability issue
      fires, stop: the edit strayed outside the delta.
- [ ] Gate: independent review of plan + delta must be complete before
      this slice (class 5). Do not begin Task 2 until both are done.

### Task 2 — Remove the configuration keys (settings schema)

**Files:** modify `backstitch/settings.py`; tests in
`tests/test_settings.py`, `tests/test_cli_config.py`

- [ ] **Write failing tests first** in `tests/test_settings.py`
      (follow the file's existing config-text fixture style):

```python
def test_check_output_key_is_rejected(tmp_path: Path) -> None:
    # Spec: docs/specs/03-backstitch-configuration.md [CFG-6] §6.3
    with pytest.raises(ConfigLoadError, match="check"):
        _resolve_with_config(tmp_path, '[check]\noutput = "report.json"\n')


def test_coverage_output_key_is_rejected(tmp_path: Path) -> None:
    # Spec: docs/specs/03-backstitch-configuration.md [CFG-6] §6.14
    with pytest.raises(ConfigLoadError, match="coverage"):
        _resolve_with_config(tmp_path, '[coverage]\noutput = "cov.json"\n')


def test_packets_output_key_is_rejected(tmp_path: Path) -> None:
    # Spec: docs/specs/03-backstitch-configuration.md [CFG-6] §6.4
    with pytest.raises(ConfigLoadError, match="packets"):
        _resolve_with_config(tmp_path, '[packets]\noutput = "p.jsonl"\n')
```

      Reuse the module's existing resolve helper (the same one the
      current tests at lines 1033/1219 use) instead of `_resolve_with_config`
      if it has a different name — match the file's local idiom. Add
      matching `--option check.output` / `--option coverage.output`
      exit-`2` cases beside the existing generic-option tests.
- [ ] Run them; expect FAIL (keys currently accepted).
- [ ] Edit `backstitch/settings.py`:
      - line 134: `_CHECK_KEYS = frozenset({"format", "warnings_as_errors"})`
      - line 135: `_PACKETS_KEYS: frozenset[str] = frozenset()`
      - `_COVERAGE_KEYS` (line 136): delete `"output"`
      - line 159: `_COVERAGE_PRESENTATION_KEYS = frozenset({"coverage.format"})`
      - line 2251: `if top_level == "coverage" and key == "format":`
      - delete `CheckSettings.output` (line 492) and the `output=` argument
        in `_parse_check_settings` (line 2604-2609)
      - delete `PacketsSettings` (line 495), the
        `BackstitchSettings.packets` field (line 763), the parse
        call at line 2689, **and** the
        `"packets": asdict(settings.packets)` entry in
        `settings_to_json` (line ~1936) — `config show` output loses its
        `packets` key entirely (the `check`/`coverage` entries shrink
        automatically when their dataclass fields go); grep
        `PacketsSettings\|\.packets\b` in `backstitch/` afterward —
        stop and re-evaluate if any non-test consumer remains
      - delete `CoverageSettings.output` and the coverage-table `output`
        validation/expansion (lines 2803-2805, ~2844-2852)
      - delete `_parse_optional_output_path` (line 2570) once both its
        callers (check line 2606, packets line 2689) are gone
      - `_expand_named_output_paths` (line 2342): remove the
        `("check", "output")`, `("packets", "output")`,
        `("coverage", "output")` rows; keep both cache-path rows; rename
        the function `_expand_named_cache_paths` and update the
        extend-chain comment at line 2396 that references `check.output`
- [ ] Rework every existing assertion that pins the old behavior — the
      complete inventory (verified against the tree at the baseline):
      - `tests/test_settings.py` lines 607, 1033, 1098, 1209, 1219,
        1483-1489, 1796-1801 (reserved packets storage) — each becomes a
        rejection assertion or is deleted where the new tests above
        already cover it
      - `tests/test_settings.py` ~1520-1560 (ratchet policy-layer
        flatten tests): remove `coverage.output` from the
        included/excluded gate-key expectations to match the shrunk
        `_COVERAGE_PRESENTATION_KEYS`
      - `tests/test_cli_config.py` line 514 (`--option check.output`
        CWD-anchoring case — replace the key with a surviving
        path-valued key or delete) and line 582 (remove the
        `check.output` row from the CLI-beats-config table)
      - `tests/test_config_parity.py` line 23 (`_nonoperational`
        helper): drop the `check.output` / `packets.output` /
        `coverage.output` `replace(...)` normalizations along with the
        fields
      - `tests/test_review_remediation.py` line 323
        (`test_config_show_includes_packets_settings`): invert — a
        `[packets]` table with `output` is now an unknown-key exit `2`,
        and `config show` output carries no `packets` key
      - `tests/test_review_remediation.py` line 912
        (`test_extended_config_paths_resolve_against_defining_file`):
        the extended `[check] output` fixture now fails resolution —
        repoint the test at a surviving contributing-layer-anchored path
        key (e.g. `analyze.cache_path`) so the anchoring contract it
        protects keeps a firing test, or delete it if that contract is
        already covered elsewhere
- [ ] Add one ratchet firing test for the accepted break: a
      merge-base/historical blob config carrying `coverage.output` fails
      ratchet resolution with the unknown-key error under strict
      handling (a transition-commit variant is deliberately omitted —
      same parser path, no new firing coverage).
- [ ] Add one parameterized hatch firing test: for each of
      `check.output`, `coverage.output`, `packets.output`, a config
      setting the key under `allow_unknown_keys = true` resolves with
      the ordinary unknown-key warning, the resolved settings carry no
      such field, and running the command publishes nothing to the
      configured path.
- [ ] Run: `uv run pytest tests/test_settings.py tests/test_cli_config.py tests/test_config_parity.py tests/test_review_remediation.py -q`
      — expect PASS.
- [ ] Commit: `feat(config): remove publication-destination keys from repository configuration`

### Task 3 — `--output` becomes an operational argument; coverage threading

**Files:** modify `backstitch/cli.py`,
`backstitch/coverage_application.py`; tests in
`tests/test_coverage_application.py`, `tests/test_cli.py`

- [ ] **Failing test first** (`tests/test_cli.py`, using the file's
      existing CLI-runner fixture): `check --output out.json` writes the
      report and exits by gate result; `coverage --output cov.json`
      writes the report; both with no config file present (proving the
      flag no longer routes through the settings layer).
- [ ] Edit `backstitch/cli.py` `_dedicated_cli_overrides` (defined at
      line 528; the foldings sit at lines 543-554): delete the two
      `args.output` foldings; keep `check.format`,
      `check.warnings_as_errors`, `coverage.format` foldings unchanged.
- [ ] Edit `_cmd_check` (lines 609-652): replace the
      `settings.check.output` read (and its now-stale [CFG-5] comment at
      lines 632-635) with `output = args.output`; the comment keeps only
      the `check.format` half.
- [ ] Edit `backstitch/coverage_application.py`:

```python
@dataclass(frozen=True, slots=True)
class CoverageRequest:
    """Resolved repository, profile, and settings for one coverage run."""

    repo_root: Path
    profile: ProfileConfig
    settings: BackstitchSettings
    output_path: Path | None = None
```

      Thread it through: `run_coverage` passes
      `request.output_path` into `_coverage_result` as a new
      `output_path: Path | None` parameter, and lines 1199-1203 become
      `output_path=output_path`. `publish_coverage` is unchanged.
- [ ] Edit `_cmd_coverage` (lines 655-691): pass
      `output_path=args.output` into `CoverageRequest`.
- [ ] Migrate `tests/test_coverage_application.py` explicitly — the
      `_settings(output=...)` helper at line 40 builds
      `CoverageSettings(output=...)`, which stops existing in Task 2.
      Move the output into the `CoverageRequest(output_path=...)` at
      each call site instead. **Hazard:** because the new field
      defaults to `None`, a missed call site compiles and silently stops
      testing publication — after the migration, grep the file for
      `output` and confirm every test that previously asserted a
      written report file still asserts one.
- [ ] Run: `uv run pytest tests/test_cli.py tests/test_coverage_application.py -q`
      — expect PASS.
- [ ] Invert `tests/test_review_remediation.py:120-144`: the fixture
      config keeps `output = "configured-report.json"` under `[check]`;
      the assertions become exit `2`, a one-line stderr error naming the
      unknown key, and `configured-report.json` **not** existing.
- [ ] Invert `tests/test_cli_config.py:135`
      (`test_bare_default_check_preserves_configured_output`): bare
      dispatch over a config carrying `[check] output` is now the same
      unknown-key exit `2`; assert no `bare-report.json` is created.
- [ ] Commit: `feat(cli): report destinations come only from the invocation`

### Task 4 — Atomic check publication and the destination guard

**Files:** modify `backstitch/cli.py`; tests in `tests/test_cli.py`,
`tests/test_artifact_publication.py`

- [ ] **Failing tests first** (`tests/test_cli.py`):

```python
def test_check_output_replaces_symlink_without_following(tmp_path, ...):
    # Spec: docs/specs/02-backstitch-core.md [SC-5] (atomic publication)
    external = tmp_path / "external" / "victim.txt"
    external.parent.mkdir()
    external.write_text("precious", encoding="utf-8")
    dest = tmp_path / "report.json"
    dest.symlink_to(external)
    # run: check --repo-root <fixture repo> --format json --output <dest>
    # assert: external still reads "precious"; dest is now a regular
    # file (not a symlink) containing the report


def test_check_output_symlink_to_config_replaces_link_not_config(...):
    # A symlink's own inode differs from the config layer's, so the
    # guard does NOT reject — and publication replaces the symlink
    # itself, never the config:
    # dest = tmp_path/"report.json" symlinked to <repo>/.backstitch.toml
    # run: check --repo-root <repo> --output <dest>
    # assert: exit by gate result (not 2); .backstitch.toml bytes
    # unchanged; dest is now a regular file containing the report


def test_check_output_hardlink_to_config_is_rejected(...):
    # Portable firing test for stat identity (a case-alias like
    # .BACKSTITCH.toml only misbehaves on case-folding filesystems; a
    # hard link shares the inode everywhere):
    # os.link(<repo>/.backstitch.toml, dest); run check --output <dest>
    # assert exit 2, "overlaps selected configuration"


def test_check_output_publication_failure_preserves_previous_bytes(...):
    # Fault injection scoped to PRE-replace failure: monkeypatch
    # os.replace (the seam tests/test_artifact_publication.py already
    # exercises) to raise OSError for the destination; run check
    # --output over an existing complete report file.
    # assert: exit 2, one-line "cannot write --output" stderr, no
    # traceback, destination bytes unchanged. (The general guarantee is
    # previous-state-or-new-complete; the post-replace fsync-failure
    # branch is proved at the artifact_publication layer — see below.)


def test_check_output_equal_to_selected_config_is_rejected(...):
    # run: check --repo-root <repo> --output <repo>/.backstitch.toml
    # assert exit 2, "overlaps selected configuration"


def test_check_output_equal_to_extend_layer_config_is_rejected(...):
    # repo config `extend = "../shared/parent.toml"`; run check
    # --output <shared>/parent.toml
    # assert exit 2 — every selected layer counts, not just the primary


def test_check_output_creates_missing_parent_directories(...):
    # run: check --output <tmp>/new-dir/report.json (no new-dir yet)
    # assert: success path; report written — this replaces the old
    # missing-parent expectation in test_check_unwritable_output_exits_two


def test_check_output_relative_path_anchors_at_cwd(...):
    # run: check --repo-root <repo> --output report.json with
    # cwd=<other-dir>; assert <other-dir>/report.json is written
    # ([CFG-5.1]: CLI artifact paths anchor at the process working
    # directory) — same case for coverage


def test_output_uninspectable_identity_is_rejected(...):
    # Fail-closed firing tests, parameterized over BOTH branches and
    # BOTH commands: in-process invocation with os.stat monkeypatched
    # to raise PermissionError (a) for the destination entry -> exit 2,
    # "cannot inspect --output"; (b) for a selected config layer path
    # -> exit 2, "cannot inspect selected configuration". Run each for
    # check and coverage.
```

      Add the same guard cases for `coverage --output`. Fill runner
      details from the file's existing CLI test idiom; assertions above
      are the contract. Also rework
      `tests/test_cli.py:1538` (`test_check_unwritable_output_exits_two`):
      its missing-parent fixture now succeeds (parents are created);
      keep the exit-`2` unwritable contract firing with a
      **regular file as the parent path component**
      (`<tmp>/file.txt/report.json` → `ENOTDIR`) — deterministic under
      any privilege, unlike permission-mode fixtures.
- [ ] Add the missing publication-owner test in
      `tests/test_artifact_publication.py`: monkeypatch
      `_fsync_directory` to raise `OSError` after a successful
      `os.replace`; assert the call raises AND the destination already
      holds the complete new bytes — pinning the
      previous-state-or-new-complete contract's post-replace branch
      (the existing test at line 55 proves only successful fsync
      ordering).
- [ ] Implement in `backstitch/cli.py` — one module-private helper used
      by both commands. **Identity must match what publication
      targets:** `os.replace` replaces the final directory entry itself
      and never follows a final-component symlink. Lexical path equality
      is wrong twice over — `output.resolve(strict=False)` follows the
      final symlink and judges the wrong path, and string comparison
      misses name aliases on case-folding filesystems. The correct
      identity is the no-follow stat identity of the directory entry: a
      provably absent entry (`ENOENT`/`ENOTDIR`) cannot alias an
      existing layer, a symlink's own inode differs from the layer's
      (allowed — replacement swaps the link), and a case alias or hard
      link shares the inode (rejected).

      The guard **fails closed**: only a provably absent directory
      entry (`ENOENT`/`ENOTDIR`) is "no alias"; any other inspection
      failure means identity is unknown and is exit `2` before capture:

```python
def _output_destination_error(
    output: Path | None,
    *,
    settings: BackstitchSettings,
) -> str | None:
    if output is None:
        return None
    # The directory entry os.replace will replace.
    destination = output.parent.resolve(strict=False) / output.name
    try:
        candidate = os.stat(destination, follow_symlinks=False)
    except (FileNotFoundError, NotADirectoryError):
        return None  # no entry exists, so it cannot alias a layer
    except OSError as exc:
        return f"cannot inspect --output {output}: {exc}"
    for identity in settings.config_layer_identities:
        try:
            layer = os.stat(identity.path, follow_symlinks=False)
        except OSError as exc:
            return (
                f"cannot inspect selected configuration"
                f" {identity.path}: {exc}"
            )
        if (candidate.st_dev, candidate.st_ino) == (
            layer.st_dev,
            layer.st_ino,
        ):
            return (
                f"--output {output} overlaps selected configuration:"
                f" {identity.path}"
            )
    return None
```

- [ ] In `_cmd_check`, call
      `_output_destination_error(args.output, settings=settings)`
      **before** `check_repository` (spec: "exit `2` before capture");
      on error `return _error(message)`. Same placement in
      `_cmd_coverage` before `run_coverage`.
- [ ] Replace the `write_text` publication in `_cmd_check`
      (lines 643-649):

```python
    if output is not None:
        from backstitch import artifact_publication

        # Unwritable/failed publication stays exit 2 with a one-line
        # error ([SC-5]); the destination must hold either the previous
        # or the complete new bytes.
        try:
            artifact_publication.atomic_replace_bytes(
                output, rendered.encode("utf-8")
            )
        except OSError as exc:
            return _error(f"cannot write --output {output}: {exc}")
    else:
        sys.stdout.write(rendered)
```

      (Match the module's lazy-import style used by the other `_cmd_*`
      functions.)
- [ ] Run: `uv run pytest tests/test_cli.py -q` — expect PASS, including
      the pre-existing unwritable-`--output` exit-`2` tests.
- [ ] Commit: `feat(check): atomic report publication with destination guard`

### Task 5 — Acceptance probes

**Files:** `tests/acceptance/test_probe_config.py` (rejection probe),
`tests/acceptance/test_probe_boundaries.py` (guard probe)

- [ ] Add an installed-CLI probe: a target repo whose `.backstitch.toml`
      sets `[check] output = "..."` → `check` exits `2`, stderr is one
      line-safe error naming the key, stdout empty, no report file
      created. Mirror the existing probe style (run the console script,
      assert exit-code class, reject tracebacks).
- [ ] Add a guard probe: `check --output` naming the target repo's
      selected config file exits `2` with no capture side effects.
- [ ] Rework the missing-parent probe in
      `tests/acceptance/test_probe_boundaries.py` (~line 85): its
      `tmp_path/"no-dir"/"out.json"` check-output case now succeeds
      (parents are created). Keep its exit-`2` contract firing with a
      regular file as the parent component
      (`tmp_path/"file.txt"/"out.json"`), same idiom as the unit test.
- [ ] Verify no existing probe drives configured outputs (session grep
      found only CLI `--output` uses); if one surfaces, invert it here
      rather than deleting it.
- [ ] Run: `uv run pytest tests/acceptance -q` — expect PASS (POSIX
      host).
- [ ] Commit: `test(acceptance): probe configuration-owned destination rejection`

### Task 6 — Traceability reconciliation and closeout

- [ ] Full gates (see §7). Fix anything that fires.
- [ ] Confirm the deviation log is empty or every row has a spec
      proposal; update the promotion baseline identifier if specs moved.
- [ ] Record a lesson in `docs/lessons.md` only if implementation
      exposed a reusable correction (e.g., an unlisted consumer).
- [ ] Flip this plan's row in `docs/plans/README.md` to `completed` in
      the same change as the completion claim; verify the landing
      commits exist via `git log`.

## 6. Testing Plan

- **Harness:** `pytest` via `uv run pytest`; CLI behavior tested through
  the real argument parser and real filesystem/TOML (the [CFG-5.1] rule:
  resolver and public-CLI tests use the real stack). Acceptance probes
  run the installed console script.
- **Do not mock:** configuration resolution, the filesystem, TOML
  parsing, `artifact_publication` internals, or the CLI parser. The
  *only* permitted fault-injection seam is the OS boundary —
  `os.replace`/`os.fsync` as already used by
  `tests/test_artifact_publication.py`, plus `os.stat` for the guard's
  fail-closed branches.
- **Contract proofs:** unknown-key exit `2` for each removed key
  (config file and `--option` forms — these are the firing tests for
  the touched enumerable contract elements); `--output` operational
  behavior with no config; previous-state-or-new-complete on
  publication failure (pre-replace failure preserves the previous
  state; post-replace fsync failure proved at the publication owner);
  symlink-not-followed at the final component; guard exit `2` for
  config-layer destinations (primary and extend layers) and for
  uninspectable destinations; missing parents created; stdout parity
  when `--output` is absent.
- **Regression floors:** existing unwritable-`--output` exit-`2` tests,
  ratchet-mode tests (presentation-key identity now `format`-only), and
  `config show` parity tests.

## 7. Verification and Gates

Per-task: the commands listed in each task.

Final gates, all from the current tree:

```bash
uv run pytest -q
```

```bash
uv run ruff check . && uv run mypy backstitch
```

```bash
backstitch check --repo-root .
```

Expected: full suite PASS; lints clean; hermetic self-corpus gate exit
`0` with zero errors and zero warnings; `--show-suppressions` unchanged
(no suppression touched). Acceptance suite (`tests/acceptance/`) passes
on the POSIX host. Completion additionally requires the [DOM-15] gates:
landing commits visible in `git log` and the status-index row flipped.

## 8. Independent Review Loop

- Class 5: an independent reviewer — preferably a different agent family
  than the author (this plan was authored by a Claude agent; prefer a
  GPT/Codex-family reviewer) — reviews **this plan and the
  `## Proposed Spec Delta`** before the spec-promotion slice, and the
  completed work before closure.
- Reviewer inputs: this plan; specs 02/03/08 at the baseline SHA;
  `backstitch/cli.py`, `backstitch/settings.py`,
  `backstitch/coverage_application.py`,
  `backstitch/artifact_publication.py`.
- Review prompt: the standard prompt in
  `docs/agent-context/runbooks/writing-plans.md` §8, with emphasis on:
  (a) is the destination guard's containment rule the right strength,
  (b) is the historical-ratchet-baseline break acceptable as recorded,
  (c) any unlisted consumer of the removed keys.
- Author must answer every review point: update, defend, or mark out of
  scope with reasoning, in this file's review notes.

## 9. Out of Scope

- Review finding 2 (semantic cache mutual-containment preflight),
  finding 3 (coverage text renderer dropping typed issues), finding 5
  (Windows claim), finding 6 (distribution smoke tests), finding 7
  (architecture rank inventory) — each is its own change.
- Parent-directory symlink traversal for user-chosen destinations
  (invocation authority accepts it; only the final component is
  no-follow).
- Any change to analyze/verify/packet path machinery beyond deleting the
  dead `packets.output` reservation.
- Provenance recording for who chose a destination — moot once only the
  invocation can choose one.
- Constrained (repo-contained) configuration outputs — considered and
  rejected by owner decision 2026-08-27 in favor of removal.
- Scan-root containment in the destination guard — considered and
  dropped after independent review round 1: with configuration removed
  the destination is always invocation-chosen; no-follow entry identity
  plus no-follow replacement closes the symlink-alias vectors
  mechanically; a containment rule would forbid every repository-local
  report under `code_roots = ["."]`; and git already protects tracked
  sources against explicit user-directed overwrites. The guard protects
  only the selected configuration layers, whose corruption would
  silently change what governs subsequent runs.
- Making the three removed keys fatal even under
  `allow_unknown_keys = true` — rejected as special-case machinery: the
  keys are never consulted either way, so the hatch's ordinary
  warn-and-ignore contract is sufficient.

## 10. Fresh-Eyes Review

Author pass completed 2026-08-27 against the baseline: every named line
anchor, key set, helper, test file, and spec sentence was
existence-checked in-session (`settings.py` 134/135/136/159/2251/2342/
2396/2570/2606/2689/2803; `cli.py` 543-554/609-652/632/647;
`coverage_application.py` 131/1199-1203/1253; the quoted spec sentences
at their cited sections; test anchors in `test_settings.py`,
`test_cli_config.py`, `test_review_remediation.py`;
`tests/acceptance/` probe files). Remaining known unknowns are flagged
as stop-gates rather than assumed: unlisted consumers of the removed
keys, and `config show` shape pins.

Round-1 independent review (below) corrected two anchors this pass
missed (`_dedicated_cli_overrides` naming; the pyproject
`[tool.backstitch]` layer) and surfaced the consumers now folded into
Tasks 2-4 — the pass checked cited lines but not every enclosing name
or repository-wide consumer, which the reviewer's sweep did.

## 11. Independent Review Log (append-only)

### Round 1 — Codex (GPT family), 2026-08-27, verdict NO

All twelve findings were verified against the tree; dispositions:

| # | Finding | Disposition |
|---|---------|-------------|
| P1 | Guard canonicalized the followed symlink target, not the replaced directory entry | **Adopted** — guard now uses parent-resolved identity (`parent.resolve() / name`); inverse-symlink test added |
| P1 | Spec delta contradicted the `allow_unknown_keys` hatch | **Adopted** — delta text scoped to strict default; hatch path documented (warn-and-ignore, never consulted). Special-case fatality rejected (out of scope §9) |
| P1 | `settings_to_json` consumes `settings.packets` | **Adopted** — deletion added to Task 2; `config show` shape change documented |
| P1 | `atomic_replace_bytes` creates parents, breaking the missing-parent exit-`2` test | **Adopted** — parents-created behavior specified (matches coverage today); `test_check_unwritable_output_exits_two` reworked to a permission-denied fixture |
| P1 | "Previous bytes intact" invariant overstated (post-replace fsync failure) | **Adopted** — invariant restated as old-complete-or-new-complete; fault test scoped to pre-replace |
| P1 | Coverage test migration underspecified; silent-default hazard | **Adopted** — explicit `_settings(output=...)` migration step with grep check |
| P1 | Five additional consumers unscheduled | **Adopted** — all five added to Tasks 2-3 inventory |
| P1 | Guard tests did not enumerate the contract | **Adopted in narrowed form** — with root containment dropped, enumeration is primary + extend config layers, both commands |
| P2 | Scan-root containment not justified by the defect | **Adopted** — guard narrowed to config-layer equality; rationale in §9 |
| P2 | Ratchet break also fires at first-parent transitions; audit-window loss | **Adopted (facts recorded; one merge-base firing test added). Declined:** transition-commit test variant — same parser path, no new firing coverage |
| P2 | Self-corpus gate reads pyproject `[tool.backstitch]`, not packaged defaults only | **Adopted** — context corrected; conclusion (gate unaffected) stands, that layer sets no output keys |
| P2 | `_options_from_args` does not exist | **Adopted** — corrected to `_dedicated_cli_overrides` (cli.py:528) |

### Round 2 — Codex (GPT family), 2026-08-27, verdict NO

Both round-1 declines were **accepted** by the reviewer (transition
resolution shares the blob resolver at `coverage_application.py:662`
and `:687` with existing committed-policy tests; hatch fatality would
add machinery without strengthening the never-consulted property).
Round-1 P1s 3, 6, 7 confirmed resolved. New/residual findings, all
verified and dispositioned:

| # | Finding | Disposition |
|---|---------|-------------|
| P1 | Lexical entry equality bypassed by name aliases on case-folding filesystems | **Adopted** — guard identity is now the no-follow stat identity `(st_dev, st_ino)` of the directory entry; portable hardlink firing test added; stop-gate revised to permit the no-follow stat |
| P1 | Hatch contradiction persisted in the §6.4 and [COV-9] delta texts | **Adopted** — both now defer to §6.1 unknown-key handling; parameterized three-key hatch firing test added to Task 2 |
| P1 | "After any outcome old-or-new bytes" unsatisfiable for absent destinations; post-replace fsync-failure branch untested (existing test proves only success ordering) | **Adopted** — guarantee restated as previous-state-or-new-complete (absence is a valid previous state); `_fsync_directory` fault test added to `tests/test_artifact_publication.py` |
| P1 | Acceptance probe `test_probe_boundaries.py:85` still pins missing-parent failure | **Adopted** — probe reworked to a regular-file-as-parent (`ENOTDIR`) case in Task 5 |
| P1 | [COV-5] example (~08:585) retains a commented `# output = "coverage.json"` line | **Adopted** — deletion added to the spec delta |
| P2 | Add a CWD-anchoring proof for relative `--output`; avoid permission-mode fixtures (privilege-dependent, and the claimed idiom does not exist) | **Adopted** — relative-path test added for both commands; unwritable fixtures use a regular-file parent (`ENOTDIR`), deterministic under any privilege |

### Round 3 — Codex (GPT family), 2026-08-27, verdict NO

All five round-2 P1s confirmed resolved except a fail-open defect the
round-2 revision itself introduced:

| # | Finding | Disposition |
|---|---------|-------------|
| P1 | The stat-identity guard failed open: a bare `except OSError: return False` treated `EACCES`/`EIO` as "not an alias", publishing when identity is unknown | **Adopted** — guard fails closed: only `ENOENT`/`ENOTDIR` on the candidate proves no alias; any other inspection failure (destination or layer) is exit `2` before capture; fail-closed firing test added; spec delta text extended ("violating or uninspectable") |
| P2 | Testing-plan summary still said "previous-bytes-preserved on publication failure" | **Adopted** — restated as previous-state-or-new-complete |

### Round 4 — Codex (GPT family), 2026-08-27, verdict NO

Round-3 P1 confirmed resolved in the guard code; two coverage gaps in
its surrounding text, no other new defect found:

| # | Finding | Disposition |
|---|---------|-------------|
| P1 | Spec delta named only an "uninspectable destination"; the code also rejects on an uninspectable selected layer, and tests fired only the destination branch | **Adopted** — [SC-5]/[COV-9] delta text covers both inspection failures; fail-closed firing tests parameterized over both branches and both commands |
| P2 | Testing rules permitted only `os.replace`/`os.fsync` fault seams, contradicting the required `os.stat` test | **Adopted** — `os.stat` added to the permitted seams |

### Round 5 — Codex (GPT family), 2026-08-27, verdict YES

No findings. Round-4 P1 confirmed resolved ([SC-5]/[COV-9] cover both
inspection-failure branches; firing tests cover both branches for both
commands; `os.stat` is a permitted seam). "The plan and proposed spec
delta are aligned and sufficiently precise. No new blocking or advisory
defect found."

**Plan-review gate satisfied**: independent different-family review of
the plan and spec delta is complete. Remaining review obligations per
[DOM-15] class 5: independent review of the completed work before
closure.
