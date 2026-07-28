# Historical Semantic Evidence Archive

This branch preserves the raw review outputs and semantic-cache state from the
2026-07-15 evidence-spike runs before they were removed from the main
worktree.

These files are historical evidence, not a current authoritative replay set:

- `.backstitch/review/analysis-report.json` records `status = "incomplete"`
  and `analysis_exit_code = 2`.
- The review packet and result rows use semantic schema version 2.
- All 260 cached result objects contain semantic schema-version-2 results.
- The current semantic producer contract is schema version 3 and does not
  consume schema-version-2 packets as current-run inputs.
- The cache also contains objects from runs outside the final 59-row review
  artifact. They are retained here for auditability rather than mixed into a
  rebuilt current cache.

The archive was captured from local `main` at
`66c84d83f8934cdd869b97ab23e28670d95773c7`. No claim is made that the archived
run passed or is suitable for promotion.
