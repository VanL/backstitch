# Ruff Complexity And Suppression Policy

Backstitch enforces Ruff's `C901` rule at a maximum complexity of 10 through
the ordinary lint configuration. The governing contract is
[`docs/specs/02-backstitch-core.md`](../specs/02-backstitch-core.md) [SC-17]
and [SC-17.1]. The implementation plan and frozen activation audit are:

- `docs/plans/2026-08-05-ruff-complexity-and-suppression-registry-plan.md`
- `docs/plans/artifacts/2026-08-05-ruff-suppression-activation-ledger.tsv`

## Design

Complexity is a review trigger, not an instruction to split every function.
An extraction is accepted only when the helper owns a coherent value, phase,
or lifecycle. Validators retain first-error order; cache code retains lease,
guard, reservation, and cleanup ownership; publication paths retain their
atomic order. A function may remain above 10 when splitting it would shuttle
mutable state or obscure a closed decision table.

The activation audit found 152 `C901` diagnostics and one intentional `F401`
probe. Refactoring retired 43 temporary groups. The active registry now has
110 directives: 109 `C901` findings and the governed `F401` importability
probe. Retired IDs remain gaps and are never reused. The activation ledger is
kept unchanged as the historical owner-approved input; the live registry in
[SC-17.1] is current authority.

## Ownership

`pyproject.toml` owns normal Ruff rule selection and the complexity ceiling.
The canonical lint path vector covers the repository plus the intended
extensionless Python tools. CI and release checks use that same vector.

`docs/specs/02-backstitch-core.md` [SC-17.1] owns the human suppression
registry. A governed source directive identifies its group and rule beside the
affected symbol. `bin/ruff_suppression_index.py` parses real Ruff JSON and real
Python source, reconciles those directives with the human rows, and owns only
the generated source-symbol index between its marker comments.

`tests/test_ruff_policy.py` proves the exact pin, enabled-rule inventory,
discovery surface, CI/release command parity, and active-spec seam.
`tests/test_ruff_suppression_index.py` covers registry parsing, symbol
identity, reconciliation, hostile input, atomic rewrite, and byte-preserving
failure behavior.

## Editing A Suppression

Do not add an ordinary `# noqa: C901`. First decide whether a local refactor
creates a better owner. If a finding must remain, add or revise all three
parts in one change:

1. a substantive human row in [SC-17.1], including the protected invariant,
   real proof, rejected alternative, lifetime, and approval;
2. the exact governed source marker beside the resolved symbol;
3. the generated index, refreshed with
   `uv run --frozen --no-sync python bin/ruff_suppression_index.py --write`.

Then run the same command with `--check`, the canonical Ruff command, and the
real proof named by the registry row. Do not reuse a retired group ID, hide a
finding with a per-file ignore, raise the ceiling, or move C901 into a CI-only
side lane.

## Verification Boundary

The index check fails closed on malformed registry rows, stale or ambiguous
symbols, marker/rule/count disagreement, malformed Ruff output, duplicate
authority, and generated-region drift. Rewrite mode validates first and uses
an atomic same-directory replacement; `--check` is non-mutating.

Repository completion also requires normal Ruff, the suppression-index check,
the acceptance probes, and `backstitch check --repo-root .`. These gates prove
that every live raw diagnostic is either fixed or represented exactly once by
a reviewed active row.

Owner extraction increases the self-corpus definition graph, so the repository
overrides the packaged obligation work limit to 3,000,000. Provider capability
is not a corpus budget: the reviewed 1.6 MB per-request analyzer limit remains
unchanged. [SC-17.1] is instead skipped from model evaluation because the live
registry is generated policy data already proved exhaustively by the real Ruff
and index gates. The isolated self-repository acceptance probe must still
complete both cold and replay artifact flows under the committed work, packet,
prompt, call, runtime, cost, and provider-request limits.
