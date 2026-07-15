# Agent-Interfaces Runbook Adoption (Mini-Wave)

Status: completed — landed 2026-07-15
Class: 3+P (effective 5) — adopting a runbook that shapes how future
agent-facing surfaces are designed and reviewed; directly relevant to
the backstitch CLI itself, which is an agent-facing surface (agents run
`backstitch check` and consume its report format). Hardening: N/A — no
risky trigger (one runbook + registration rows). Pre-landing review:
content passed a grok round in the source repo on 2026-07-14, and the
identical adaptation shape (provenance line, foreign hub plan path,
matching §2/§12 citations, registration rows) passed the shared scoped
grok round run for the mm and taut adoptions the same day; this repo's
+P review is a scoped adaptation round — dispositions in §4.

## 1. Goal

Adopt `docs/agent-context/runbooks/designing-agent-facing-interfaces.md`
from agent-guidance @ `a4b4345` (first [DOM-14] fold-up, distilled from
mm's agent API design; unchanged upstream since that commit). Early
adoption ahead of the next full wave, at owner request, so backstitch
CLI and report-format changes can be reviewed against it.

## 2. Adaptations

Minimal — this repo's engineering-principles numbering matches the
canonical (§2 Canonicalize at Boundaries, §12 Enumerable Contracts Get
Executable Gates — both verified by heading grep), so principle
citations land verbatim. Changes: adoption provenance line; the hub
plan path cited as a quoted foreign name; agent-context README bullet;
`context.index.yaml` row + `updated_at`. Landing note:
`docs/plans/README.md` is dirty with this repo's own WIP (a
deterministic-semantic-gate plan row) — staged via a synthetic
HEAD+mine blob so the WIP stays uncommitted, per the staging-safety
lessons.

## 3. Verification

- Runbook present and byte-identical to the hub copy outside the
  provenance/lineage lines; `adversarial-acceptance-probes.md` and
  `external-skill-suites.md` cross-references resolve locally;
  self-corpus check no worse than the pre-change baseline (0/0/0);
  `bin/check-dom15-fixtures` exit 0.

## 4. Review Findings and Dispositions

Scoped round (grok, read-only, 2026-07-15; transcript in the session
scratchpad `backstitch-adoption-review-out.json`): **PASS**, no P1/P2.
All fourteen adaptation checks verified (provenance form, `a4b4345`
pin, body-identity from `Owner:` onward, both cross-references and
both §-citations resolve locally, registration rows, class label,
verification claims match the tree). Two nits, both dispositioned
keep-as-is: A1 — the §2 citation uses the heading stem
("Canonicalize at Boundaries") rather than this repo's full title;
same form accepted no-change in the 2026-07-14 mm/taut shared round,
kept for cross-repo textual identity of the runbook body. A2 — the
README bullet's "(adopted from agent-guidance; directly relevant to
the backstitch CLI)" parenthetical is metadata other bullets omit;
kept deliberately as the local-relevance cue.
