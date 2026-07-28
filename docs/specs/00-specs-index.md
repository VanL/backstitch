# Specs Index

This directory contains the repository's source-of-truth specs for intended
behavior.

Use this numbered index as the canonical starting point for specs. Keep
`README.md` as a thin pointer so directory browsing and numbered read order
stay aligned instead of competing.

## Rules

- Specs define intended behavior, invariants, and verification expectations.
- Specs use stable reference codes so plans and code can cite exact
  requirements.
- Specs backlink related plans under `## Related Plans`.
- If behavior changes materially, update the spec before or with the code.

## Recommended Starting Points

1. `01-development-documentation-operating-model.md`
2. `02-backstitch-core.md`
3. `03-backstitch-configuration.md`
4. `04-backstitch-traceability-exclusions.md`
5. `05-backstitch-invariants.md` (Status: Active)
6. `06-semantic-gates.md` (Status: Active)
7. `07-verification-and-evidence-cases.md` (Status: Active)
8. `08-intent-coverage.md` (Status: Proposed)

Product identity — the boundary rule, evidence-class rule, the two lanes and
policy layer, the metric identity rule, and the contract-coverage matrix — is
stated in `02-backstitch-core.md` [SC-16]; feature debates test against it
first.
Diagnostic identity, short codes, default policy, and the packaged defaults
layer are governed by `02-backstitch-core.md` [SC-11]/[SC-15] and
`03-backstitch-configuration.md` [CFG-5]/[CFG-6].
Semantic cache identity, evidence state, packaged policy, repository-applied
policy, completeness, and CI gating are governed by
`06-semantic-gates.md` [SEM-1] through [SEM-10].
Obligations, readiness, read-only evidence discovery, source-derived packets,
and the blinded adversarial verify stage are governed by
`07-verification-and-evidence-cases.md` [EVC-1] through [EVC-12].
Definition-level intent coverage, exemptions, the diff ratchet, drift
coverage, and the uncovered-definition triage loop are governed by
`08-intent-coverage.md` [COV-1] through [COV-9].

## Naming

- Use stable filenames.
- Numbered prefixes are recommended when the corpus is expected to grow.
- Prefer concise, descriptive titles over ticket-like names.

## Related Surfaces

- `docs/plans/` for execution
- `docs/implementation/` for rationale and repository maps
- `skills/` for reusable workflow instructions
- `tests/acceptance/` for the [SC-10] acceptance probe suite (once an
  implementation lands)
