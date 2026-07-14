# Agent-Guidance Propagation Plan (2026-07-14 wave)

Status: Active
Class: 5+P — normative spec sections land in the spec tree ([DOM-14],
[DOM-15]) and the change is [DOM-6]-material to future process.
Hardening: N/A — no [DOM-5] risky trigger fires (docs and guidance only).
Source: agent-guidance @ `2f7eff6` (2026-07-14); source content carried
seven independent review rounds there today, plus a taut adaptation
review (grok, PASS). This repo's review is scoped to the adaptation.

## 1. Goal

Adopt the 2026-07-14 agent-guidance wave: coalescing layer ([DOM-14] +
skill + state file, with lessons-format adaptation), task classification
([DOM-15] + fixture checker), the performative-overengineering review
lens, the external-skill-suites crosswalk, and four skills.

## 2. Invariants and Constraints

- **The mandatory zero-warning self-corpus gate is not waivable.** The
  DOM spec is meta-classified (`pyproject.toml meta_spec_globs`), so
  [DOM-14]/[DOM-15] add no mapping obligations — verified: 92 sections,
  0/0/0 after transplant.
- **Lessons-format adaptation:** this ledger uses dated H2 sections
  (`## 2026-07-01: …`), not dated bullets. The coalescing derivation
  counts `^## 20` sections; `docs/coalescing.md` documents the local
  command. The Golden Rules and the four-way bake-off incident record
  are importance-floored: the bake-off section is the ecosystem's
  incident-of-record (agent-guidance's ledger points here) and is
  exemplar-class — never a fold candidate.
- **Dirty-tree discipline:** unrelated WIP (ci.yml, README, cli.py,
  specs 00/02/03/05, pyproject, test_release_workflow, two draft plans,
  .codecov.yml) is untouched; none of this plan's files overlap it.
- Copied skills cite this plan and the source SHA, never foreign plan
  paths.
- Follow-up (out of scope here): encode the [DOM-15] fixture table as
  firing tests in this repo's real harness, per the spec's
  enumerable-contract rule — backstitch is the first adopter with a
  suite that can.

## 3. Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## 4. Tasks and Gates

1. Transplants (heading-anchored, taut-hardened script): [DOM-14],
   [DOM-15], DOM-5 routing, DOM-11 lens, §15, §10 amendment (local
   anchor differs — no principle-4 coda here), plan lifecycle, prompt
   lens ×2, retired-citation form, classify-before-preflight, AGENTS
   bullet, call-agent pointer in review-loops.
2. New files: state file, crosswalk, four skills (adapted),
   `bin/check-dom15-fixtures`.
3. Bespoke: lessons startup note; context.index.yaml; agent-context
   README; plans README registration + Retired Plans ledger.
4. Gates: self-corpus check 0/0/0; `python3 bin/check-dom15-fixtures`
   exit 0; relevant pytest subset green.
5. Scoped adaptation review (grok, read-only) — dispositions below.
6. First coalescing sweep in the same unit of work (standing rule).

## 5. Review Findings and Dispositions

Round 1 (grok, scoped, 2026-07-14): **BLOCKED** — and correctly: the
transplant script had died at a local-anchor assertion (this repo's
locally re-authored §10 lacks the canonical coda) and the resume only
fixed §10, silently omitting six downstream transplants. The reviewer
caught the gap the author's success-message reading missed.

| # | Finding | Disposition |
|---|---|---|
| P1-1 | Coalescing skill derivation still bullet-grep; this ledger is dated-H2 | **Accepted.** Skill (all three repos) now defers to the state file's declared derivation command; the bullet grep is the dated-bullet default |
| P1-2 | Harvest gate / retired-citation form never landed | **Accepted.** Both transplanted (lifecycle into writing-plans; citation form into maintaining-traceability) |
| P1-3 | Six operational transplants missing (lifecycle, prompts ×2, classify-preflight, AGENTS bullet, call-agent pointer) | **Accepted.** All landed; each verified by grep; writing-plans' prompt needed a local-wrapping anchor |
| P2-1 | Lessons-format claim overstates uniformity | **Accepted in state file wording** — derivation counts dated-H2 sections; non-dated H2 titles simply don't count (conservative) |
| P2-2 | Residual guidance-repo fold-up wording | **Rejected with reasoning:** [DOM-14]'s fold-up tier is explicitly boundary-scoped "(for the guidance repo)" — inert here by its own text |
| P2-3 | checked_through lacks real SHA until landing | **Accepted** — pinned at commit |
| P2-4 | brainstorming triviality not keyed to [DOM-15] | **Accepted, fixed canonically** in all three repos |
| P2-5 | debugging skill relative-path style | **Accepted, fixed canonically** in all three repos |

Round 2 (grok, scoped): **PASS** — all six transplants verified present, coalescing derivation defers to the state file, no new defects.
