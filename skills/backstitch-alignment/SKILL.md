---
name: backstitch-alignment
description: Use Backstitch to bootstrap or maintain spec-to-code alignment. Trigger when inventorying obligations, reviewing declared evidence, finding untraced implementation or test candidates, or preparing a human-reviewed traceability change.
---

# Backstitch Alignment

Treat repository source as the alignment authority. Use Backstitch to read,
check, and advise. Do not let tool output or model judgment ratify alignment.
Treat bootstrap and gate as separate phases: discovery reports plausible
current candidates; a human records accepted evidence in source; current
analysis derives the gate packet only from those source declarations.

1. Run `backstitch guide alignment` and `backstitch obligation --help`. Follow
   the installed guide and current command help when this adapter differs.
2. Run `backstitch obligation list` to inventory addressable obligations and
   unaddressable intent.
3. Run `backstitch obligation <OBLIGATION_ID>` to inspect one obligation's
   current alignment, disposition, readiness, blockers, and next actions.
4. Run `backstitch obligation <OBLIGATION_ID> --summarize-evidence` to inspect
   exact source-declared evidence and broken or one-sided trace declarations.
5. Run `backstitch obligation <OBLIGATION_ID> --find-evidence` to get bounded
   candidates. Use `--candidate <CANDIDATE_ID>` only for full detail on a
   discovery-minted candidate. Rerun discovery after source changes rather than
   treating an older candidate report as current.
6. Follow the mapping, backlink, invariant-target, or binding-test guidance in
   the installed guide. Treat every candidate as advice until a supported
   declaration exists in source.
7. As an authorized coding agent, prepare or apply an ordinary source diff
   within the caller's authority. Backstitch itself remains read-only. The
   working-tree edit is not ratified or landed until a human reviews it.
8. To remove evidence, start with `--summarize-evidence`, review the exact
   declaration coordinates, and remove only the intended declarations. For a
   section relation, remove both sides together so the mapping and matching
   backlink do not become an accidental one-sided trace.
9. After human review, rerun `backstitch check --repo-root .`, the evidence
   summary, and the obligation detail. Resolve partial or conflicted state
   before landing. Human approval remains the authority for evidence changes.
10. Run current-source analysis only when the obligation reports executable
    readiness. Do not pass candidate dispositions into the gate; current source
    declarations are the only evidence-selection authority.

Audit skips with `backstitch check --repo-root . --show-suppressions`. Keep them
visible and separate from alignment state. Never use a skip, derived packet,
cache entry, or semantic verdict to hide missing traceability.
