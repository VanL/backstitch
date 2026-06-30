# Repository Map

Quick pointers to the key guidance documents in this repository.

## Root Entry Points

| Path | Purpose |
|------|---------|
| `AGENTS.md` | Canonical agent entry point |
| `CLAUDE.md` | Alias for tools that expect Claude-style root guidance |
| `pyproject.toml` | Package metadata, dependency declarations, console script, and Python tool configuration |

## Source Package

| Path | Purpose |
|------|---------|
| `backstitch/` | Python package for the backstitch CLI and traceability implementation |

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
