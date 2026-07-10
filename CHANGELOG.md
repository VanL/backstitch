# Changelog

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
