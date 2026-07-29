# Spec contract semantic control 25

## Nondiscriminating Prose [SPEC-25]

`rule_25_nondiscriminating_prose()` returns `allow` exactly for the state `ready` and returns `deny` for every other state.

_Implementation mapping_:

- `src/feature.py::rule_25_nondiscriminating_prose`
