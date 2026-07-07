# Repository Map

Quick pointers to the key guidance documents in this repository.

## Root Entry Points

| Path | Purpose |
|------|---------|
| `AGENTS.md` | Canonical agent entry point |
| `CLAUDE.md` | Alias for tools that expect Claude-style root guidance |
| `pyproject.toml` | Package metadata, dependency declarations, console script, and Python tool configuration |
| `bin/release.py` | Maintainer release helper for version updates, checks, release commit, and tag push |

## Source Package

| Path | Purpose |
|------|---------|
| `backstitch/` | Python package for the backstitch CLI and traceability implementation |
| `backstitch/grammar.py` | Single section-ID regex shared by both parsers ([SC-4]) |
| `backstitch/models.py` | Frozen graph/issue datatypes; canonical `ISSUE_CODES` ([SC-11]) |
| `backstitch/artifact_contracts.py` | Packet JSONL and deterministic-report validation at trust boundaries ([SC-6], [SC-13]) |
| `backstitch/config.py` | `ProfileConfig` and overrides ([SC-3]) |
| `backstitch/profiles.py` | Built-in `backstitch-style-v1` profile ([SC-3]) |
| `backstitch/markdown_specs.py` | Traceability layer over `markdown-it-py` CommonMark tokens: sections, mappings, markers ([SC-4], [EXC-4]) |
| `backstitch/python_refs.py` | Code parser: backlinks, noqa spans ([SC-4], [EXC-5]) |
| `backstitch/resolver.py` | Pure `resolve()` + `scan_repository` ([SC-4], [SC-9]) |
| `backstitch/check_pipeline.py` | Shared scan + suppression pipeline for deterministic command consumers ([SC-5], [EXC-6], [EXC-7]) |
| `backstitch/reporting.py` | Text/JSON rendering, suppressed view ([SC-6], [EXC-7]) |
| `backstitch/settings.py` | TOML discovery/validation ([CFG-*]) |
| `backstitch/exclusions.py` | Suppression engine ([EXC-*]) |
| `backstitch/target_roots.py` | Worktree-safe sibling discovery ([SC-12]) |
| `backstitch/analysis_packets.py` | Bounded packet generation ([SC-6], [SC-7]) |
| `backstitch/analysis_results.py` | Result JSONL load/summarize ([SC-6]) |
| `backstitch/analysis_llm.py` | Lazy-`llm` adapter boundary ([SC-7], [SC-8]) |
| `backstitch/doctor.py` | Environment doctor checks ([SC-14]) |
| `backstitch/cli.py` | Parser/dispatch, command option merging, output writes, and exit-code mapping ([SC-5], [CFG-7]) |
| `tests/acceptance/` | The thirteen [SC-10] acceptance probes |
| `tests/live/` | Opt-in live LLM smoke/contract test ([SC-7], `BACKSTITCH_LIVE_LLM=1`) |
| `.github/workflows/ci.yml` | Hermetic CI + post-merge/manual live-LLM job |
| `.github/workflows/local-llm.yml` | Separate manual Ollama live-LLM canary outside the release-gated `CI` workflow |
| `.github/workflows/release-gate.yml` | Tag-triggered PyPI/GitHub release gate |
| `.github/scripts/require_green_workflows.py` | Release-gate helper that waits for required green workflow runs |

## Shared Agent Context

| Path | Purpose |
|------|---------|
| `docs/agent-context/README.md` | Context hub and read order |
| `docs/agent-context/context.index.yaml` | Machine-readable context index |
| `docs/agent-context/decision-hierarchy.md` | Conflict-resolution order |
| `docs/agent-context/principles.md` | Shared execution principles |
| `docs/agent-context/engineering-principles.md` | Engineering rules and warning signs |

## Runbooks

| Path | Purpose |
|------|---------|
| `docs/agent-context/runbooks/writing-plans.md` | Plan-writing standard |
| `docs/agent-context/runbooks/hardening-plans.md` | Required hardening checklist for risky or boundary-crossing plans |
| `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md` | Independent review workflow and agent bootstrap |
| `docs/agent-context/runbooks/writing-specs.md` | Spec-writing standard |
| `docs/agent-context/runbooks/writing-implementation-docs.md` | Implementation-doc standard |
| `docs/agent-context/runbooks/testing-patterns.md` | Testing and verification guidance |
| `docs/agent-context/runbooks/maintaining-traceability.md` | Documentation-maintenance gate |
| `docs/agent-context/runbooks/skills-lifecycle.md` | Skill promotion and maintenance guidance |

## Core Documentation Corpus

| Path | Purpose |
|------|---------|
| `docs/specs/00-specs-index.md` | Numbered entry point for specs |
| `docs/specs/01-development-documentation-operating-model.md` | Governing spec for the documentation workflow |
| `docs/specs/02-backstitch-core.md` | Preliminary product spec for deterministic traceability and `llm` semantic analysis |
| `docs/plans/README.md` | Plan directory rules |
| `docs/plans/2026-06-18-backstitch-style-spec-code-traceability-tool-plan.md` | Active implementation plan for the traceability tool |
| `docs/implementation/00-implementation-index.md` | Numbered entry point for implementation docs |
| `docs/implementation/01-documentation-system.md` | Why the documentation system is shaped this way |
| `docs/implementation/03-agent-inventory.md` | Current observed agent availability and review preference |
| `docs/implementation/04-backstitch-style-traceability.md` | Traceability implementation rationale and verification map |
| `docs/implementation/05-release-publishing.md` | Release helper, publishing gate, rollback, and operator notes |
| `docs/lessons.md` | Canonical lessons ledger |

## Skills

| Path | Purpose |
|------|---------|
| `skills/README.md` | Skill directory purpose and conventions |
| `skills/_template/SKILL.md` | Starter template for new reusable skills |

## Update Guidance

When the repository grows:

- add new important entry points here
- keep descriptions short and navigational
- prefer linking to the document that explains a concept, not every file that
  happens to mention it
