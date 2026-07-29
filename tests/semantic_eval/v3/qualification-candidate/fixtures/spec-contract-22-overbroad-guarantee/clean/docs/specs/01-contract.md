# Spec contract semantic control 22

## Overbroad Guarantee [SPEC-22]

`rule_22_overbroad_guarantee()` clamps integers below `0` to `0`, above `100` to `100`, and preserves values inside that inclusive range.

_Implementation mapping_:

- `src/feature.py::rule_22_overbroad_guarantee`
