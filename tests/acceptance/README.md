# Acceptance Probe Suite

These modules implement the thirteen acceptance probes required by
`docs/specs/02-backstitch-core.md` [SC-10]. They are black-box subprocess
probes, not unit tests: each asserts an exit-code class, structured report
fields, and that no traceback reaches stderr. An implementation that fails
any probe is not a candidate for integration, regardless of its own test
suite passing.

See also `docs/agent-context/runbooks/adversarial-acceptance-probes.md` for
the generic pattern these probes instantiate.
