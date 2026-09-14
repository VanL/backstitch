# Changelog

## Unreleased

- Changed the default semantic model to GPT-5.6 Luna through the Responses API
  at maximum reasoning effort. Explicitly omitted reasoning effort continues
  to accept the selected model's provider default; bounded live release
  qualification covers Luna and the protected GPT-5.5 comparison.
- Added configured semantic analysis, immutable evidence and verification
  caches, evidence-stable reuse, aligned-intent obligations, intent coverage,
  Git ratchets, and typed recovery guidance across JSON and text reports.
- Hardened report publication: repository configuration can no longer choose
  output destinations, semantic cache/source overlap is rejected before any
  provider work, and `check --output` uses atomic replacement.
- Hardened the release chain with exact-SHA workflow requirements, immutable
  tag and release policy checks, pinned Actions, trusted PyPI publication,
  artifact attestations, and separate clean-install smoke tests for the built
  wheel and source distribution before attestation.
- Made architecture enforcement exhaustive for every package module and
  declared the actual platform boundary: repository commands support POSIX
  systems, including Linux and macOS; Windows is not currently supported.
- Removed Backstitch's mutable external Weft debt baseline from the test suite.
  External repositories own their own Backstitch integration evidence.

- Added opt-in documented suppression governance with spec-owned rationales,
  structured ignore/meta rules, deterministic audit provenance, first-class
  suppression obligations and semantic packets/results, cache replay, policy
  and disposition integration, and live suppression lifecycle coverage.
- Migrated Backstitch's own suppressions from legacy meta/per-file settings to
  five declared structured rules. The self-corpus audit is narrower (192
  records from 206), contains no undocumented rationale, and is mechanically
  pinned against scope broadening.
- Added deterministic semantic evidence discovery, immutable analysis and
  verification caches, qualification-gated model use, bounded trusted refresh
  workflows, and report-only hostile pull-request analysis.
- Added the aligned-intent obligation read model, evidence candidate workflow,
  public obligation commands, alignment guides, and frozen product-evaluation
  corpora.
- Centralized configuration in one invocation-scoped resolver with packaged
  defaults, explicit or discovered TOML, defined environment inputs, and
  repeatable `--option KEY VALUE` overlays. Dedicated CLI flags share the same
  final layer, and commands receive the resolved typed settings snapshot.
- Removed filename-specific refresh configuration. Trusted semantic workflows
  now select the trusted checkout's `pyproject.toml` explicitly and apply the
  reviewed literal runtime overrides.
- Expanded acceptance, adversarial, semantic-evaluation, configuration,
  workflow-boundary, coverage, and scale tests. Wall-clock tests use one
  `benchmark` marker and run in the dedicated serial lane. Each command now
  uses a warm-up plus a five-run median, with runner-qualified relative
  comparisons and loose always-on catastrophic ceilings.

## 0.3.0 - 2026-07-10

- Added first-class invariant traceability. Code and spec declarations can use
  required or draft invariant markers, tests bind them with
  `Tests-invariant:`, and deterministic checks report missing, unknown,
  duplicate, misplaced, and malformed bindings.
- Added invariant semantic-review packets and results. `packets --kind` now
  supports `section`, `invariant`, and `all`; invariant packets include bounded
  target and binding-test evidence plus a deterministic content hash.
- Added stable canonical and short diagnostic codes, context-aware default
  levels, ordered reporting-policy rules, configurable `fail_on` and
  suppressibility, and auditable `off` or explicitly suppressed findings.
- Moved built-in profile, root, exclusion, diagnostic, and reporting defaults
  into packaged TOML. `config show` exposes the effective layers and policy;
  `--no-config` skips repository configuration but retains packaged defaults.
- Added explicit test-role roots within code roots, paired root-override rules,
  containment validation, and `--test-root` support for checks and packets.
- Extended deterministic reports with diagnostic metadata, invariants, and
  binds. Producers emit the new schema; loaders retain narrowly defined legacy
  report, section-packet, and section-result compatibility.
- Made this repository's traceability policy strict: every visible diagnostic
  is error-level. The self-corpus passes with zero visible findings and keeps
  all test/meta suppressions available through `--show-suppressions`.
- Changed local pytest policy to run the real live-LLM contract test by default.
  The hermetic CI matrix explicitly disables it; the optional cloud CI job is
  restricted to configured main-branch events with read-only permissions.
- Stabilized the credential-free local-LLM release gate with a curated pair of
  real invariant packets, request-level temperature and seed controls, and
  packet-bounded schema decoding across a test-owned nonstream/SSE bridge. The
  release helper now rechecks publication, active workflows, and tag state
  before a lease-guarded unpublished retag.
- Updated GitHub Actions to current Node 24-compatible majors and disabled
  `setup-uv` caching across CI and release workflows to avoid post-job cache
  failures and warning noise.
- Expanded firing tests and black-box acceptance probes for every invariant
  diagnostic, report/packet/result compatibility, marker isolation, role-root
  behavior, deterministic ordering, hash stability, and self-application.

## 0.2.0 - 2026-07-08

- Added the GitHub release path: local release helper, tag-gated CI release
  workflow, artifact attestation, PyPI Trusted Publishing, and GitHub Release
  upload.
- Added regular, cloud live-LLM, and local Ollama-backed live-LLM release
  gates so tags are pushed only after local prechecks pass; the regular suite
  now runs with `pytest-xdist`, and local LLM readiness is prewarmed in
  parallel by pulling/recreating the bounded Ollama served model before the
  local live test.
- Added the local-LLM GitHub Actions lane and made the release gate wait for
  both `CI` and `local-llm` on the release commit before publishing.
- Moved Markdown and Python structure parsing onto parser-owned boundaries:
  `markdown-it-py` for Markdown block structure and `tree-sitter-python` for
  runtime-independent Python structure.
- Added the local model catalog and `backstitch doctor` checks for LLM provider
  and local endpoint readiness.
- Expanded acceptance probes, self-corpus checks, traceability docs, and
  release workflow tests.
