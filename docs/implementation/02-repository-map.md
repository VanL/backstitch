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
| `backstitch/defaults.toml` | Packaged lowest-precedence defaults for profile, excludes, diagnostics, and policy ([SC-15], [CFG-5]) |
| `backstitch/diagnostics.py` | Diagnostic registry with explicit deterministic/semantic families, short-code aliases, selector matching, and ordered policy application ([SC-11], [SC-15]) |
| `backstitch/canonical.py` | Sole canonical JSON, canonical repository-path, and LF-only line/slicing primitive owner ([INV-11] [INV.CANON.1], [INV.LINE.1]) |
| `backstitch/contract_validation.py` | Shared scalar and closed-record validation mechanics with artifact-family error and NFC policy preserved at thin wrappers ([INV-11]) |
| `backstitch/grammar.py` | Sole section-ID, SHA-256 token, and candidate-reference grammar owner shared across parsers and contract validators ([SC-4], [INV-11] [INV.CANON.1]) |
| `backstitch/models.py` | Frozen section, invariant, bind, graph, and issue datatypes; compatibility diagnostic inventories derived from the registry ([SC-6], [SC-11], [INV-4]) |
| `backstitch/artifact_contracts.py` | Mixed section/invariant/suppression packet JSONL, hash, and deterministic-report validation at trust boundaries ([SC-6], [SC-13], [INV-5], [EVC-4]) |
| `backstitch/config.py` | `ProfileConfig` and paired code/test-root overrides ([SC-3], [CFG-6]) |
| `backstitch/profiles.py` | Built-in `backstitch-style-v1` profile ([SC-3]) |
| `backstitch/markdown_specs.py` | Traceability layer over `markdown-it-py` CommonMark tokens: sections, mappings, suppression declarations, exclusions, and invariant declarations ([SC-4], [EXC-4], [INV-3]) |
| `backstitch/code_parser.py` | Runtime-independent `tree-sitter-python` seam: owner spans, doc blocks, comments, statement spans ([SC-4], [SC-10]) |
| `backstitch/python_refs.py` | Python traceability interpretation over the parser seam: backlinks, noqa spans, invariant declarations, and test bindings ([SC-4], [EXC-5], [INV-3]) |
| `backstitch/resolver.py` | Pure section/invariant `resolve()` plus accepted-snapshot artifact projection; the former live repository scan entry points are removed ([SC-4], [SC-9], [INV-4]) |
| `backstitch/check_pipeline.py` | Shared accepted-snapshot, policy, suppression, and audit pipeline for deterministic command consumers ([SC-5], [SC-15], [EXC-6], [EXC-7]) |
| `backstitch/repository_snapshot.py` | Immutable no-follow source/config capture, path catalog, target convergence, and clone-independent snapshot identity ([EVC-8.2]) |
| `backstitch/obligation_runtime.py` | Shared snapshot/config orchestration for deterministic obligation and check reads ([EVC-8.2]) |
| `backstitch/obligations.py` | Source-derived section, invariant, and suppression obligation inventory, readiness, disposition, blockers, and bootstrap entries ([EVC-2], [EVC-8.3]) |
| `backstitch/evidence_summary.py` | Exact declared-evidence rows, reciprocity, source spans, and receipts from the accepted snapshot ([EVC-4.1], [EVC-8.3]) |
| `backstitch/evidence_discovery.py` | Deterministic structural/lexical candidate discovery, conservative Python relations, trace states, receipts, and review guidance ([EVC-7]) |
| `backstitch/obligation_api.py` | Transport-neutral obligation envelopes, canonical-core response-byte enforcement, closed problems/guidance, and content-bound pagination ([EVC-8.4]) |
| `backstitch/alignment_guide.py` | Installed versioned alignment quick start shared by public agent and human workflows ([EVC-8.1]) |
| `backstitch/alignment_eval.py` | Closed Phase A/B product preregistration, authoritative product identities, independently source-bound gold, and result recomputation ([EVC-10.2]) |
| `backstitch/reporting.py` | Text/JSON rendering, suppressed view ([SC-6], [EXC-7]) |
| `backstitch/settings.py` | Sole invocation-scoped config resolver: packaged defaults, repository TOML, defined environment, generic/dedicated CLI layers, strict validation, and immutable settings provenance ([CFG-5.1], [SC-5.1]) |
| `backstitch/exclusions.py` | Canonical documented-suppression rule engine and decisions ([EXC-*]) |
| `backstitch/target_roots.py` | Worktree-safe sibling discovery ([SC-12]) |
| `backstitch/analysis_packets.py` | Sole source-aligned packet producer over one immutable obligation runtime; the former `generate_packets` path is removed ([SC-6], [SC-7], [EVC-9.1], [INV-5]) |
| `backstitch/analysis_results.py` | Discriminated section/invariant/suppression result JSONL validation and kind-separated summaries ([SC-6], [INV-5]) |
| `backstitch/analysis_llm.py` | Lazy-`llm` adapter, evidence-locality, and weak-binding normalization boundary ([SC-7], [SC-8], [INV-5]) |
| `backstitch/semantic_packets.py` | Canonical schema-3 section/invariant and schema-4 suppression projections, exact model-visible evidence regions, and code-owned prompt descriptors ([SEM-3], [EVC-9.1]) |
| `backstitch/semantic_identity.py` | Offline provider/request/contract fingerprint and content-addressed analysis key ([SEM-3]) |
| `backstitch/semantic_evidence.py` | Closed model-result normalization and trusted packet-local excerpt reconstruction ([SEM-5]) |
| `backstitch/semantic_cache.py` | Immutable untrusted semantic cache, single flight, no-replace publication, and audited lock cleanup ([SEM-4]) |
| `backstitch/semantic_policy.py` | Semantic finding identity, dispositions, policy provenance, and diagnostic projection ([SEM-2], [SEM-6]) |
| `backstitch/semantic_reports.py` | Closed packet/analysis reports and staged publication of complete packet/result/report artifact sets ([SEM-7]) |
| `backstitch/semantic_analysis.py` | Unified cache, completeness, budget, policy, publication, and exit-code runner ([SEM-1], [SEM-7]) |
| `backstitch/semantic_eval.py` | Closed mutation/control corpus runner, metrics, Wilson intervals, and qualification ([SEM-8]) |
| `backstitch/semantic_eval_reports.py` | Closed eval-report validation, cross-field consistency, and self-acceptance loading ([SEM-8], [SC-13]) |
| `backstitch/prompts/` | Packaged section, invariant, and suppression semantic-review prompts ([SC-7], [INV-5]) |
| `backstitch/doctor.py` | Environment doctor checks ([SC-14]) |
| `backstitch/cli.py` | Parser/dispatch, one-shot settings resolution and injection, command option normalization, output writes, and exit-code mapping ([SC-5], [SC-5.1], [CFG-5.1], [CFG-7]) |
| `tests/acceptance/` | Black-box [SC-10] probes, including invariant and suppression lifecycle dogfood and artifact compatibility |
| `tests/semantic_eval/v1/` | Historical analyzer-only mutation corpus retained for migration tests ([SEM-8]) |
| `tests/semantic_eval/v3/` | Current schema-3 runner smoke corpus and non-authoritative qualification candidate ([EVC-10.1]) |
| `tests/product_eval/alignment-bootstrap/` | Content-addressed obligation/discovery product fixtures, production observations, independent gold, and reviewer protocol ([EVC-10.2]) |
| `tests/live/` | Local-default live LLM smoke/contract test ([SC-7]); pytest policy or `BACKSTITCH_LIVE_LLM=1` controls enablement |
| `.github/workflows/ci.yml` | Hermetic secret-free CI; live LLM tests are explicitly deselected |
| `.github/workflows/semantic-refresh.yml` | Default-branch `repository_dispatch` cloud refresh with required secret and artifact-only review output ([SEM-9]) |
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
| `docs/specs/02-backstitch-core.md` | Core product spec for deterministic traceability and `llm` semantic analysis |
| `docs/specs/05-backstitch-invariants.md` | Active first-class invariant declaration, binding, packet, and semantic-analysis contract |
| `docs/plans/2026-07-09-backstitch-invariant-traceability-plan.md` | Invariant implementation, review, and verification record |
| `docs/plans/README.md` | Plan directory rules |
| `docs/plans/2026-06-18-backstitch-style-spec-code-traceability-tool-plan.md` | Active implementation plan for the traceability tool |
| `docs/implementation/00-implementation-index.md` | Numbered entry point for implementation docs |
| `docs/implementation/01-documentation-system.md` | Why the documentation system is shaped this way |
| `docs/implementation/03-agent-inventory.md` | Current observed agent availability and review preference |
| `docs/implementation/04-backstitch-style-traceability.md` | Traceability implementation rationale and verification map |
| `docs/implementation/05-release-publishing.md` | Release helper, publishing gate, rollback, and operator notes |
| `docs/implementation/07-deterministic-semantic-gate.md` | Semantic identity, cache, evidence, authority, eval, and rollout rationale |
| `docs/implementation/08-aligned-intent-read-model.md` | Immutable snapshot, obligation/readiness, evidence summary, discovery, CLI, and human-authority rationale |
| `docs/lessons.md` | Canonical lessons ledger |

## Skills

| Path | Purpose |
|------|---------|
| `skills/README.md` | Skill directory purpose and conventions |
| `skills/_template/SKILL.md` | Starter template for new reusable skills |
| `skills/interface-review/SKILL.md` | Review an agent-facing surface (REST/MCP/CLI/doc) against `designing-agent-facing-interfaces.md` |

## Update Guidance

When the repository grows:

- add new important entry points here
- keep descriptions short and navigational
- prefer linking to the document that explains a concept, not every file that
  happens to mention it
