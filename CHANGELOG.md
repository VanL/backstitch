# Changelog

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
