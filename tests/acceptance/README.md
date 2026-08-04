# Acceptance Probe Suite

These modules implement the acceptance probes and full hermetic dogfood
journeys required by `docs/specs/02-backstitch-core.md` [SC-10]. They run the
installed console script, assert exit-code classes and structured artifacts,
and reject any traceback on stderr. An implementation that fails a probe is
not a candidate for integration, regardless of its unit-test results.

`command_surface_manifest.py` assigns every public command leaf to a dogfood
receipt and every non-command lifecycle surface to a callable acceptance test.
The manifest test fails when a command is added without an owner or a
lifecycle owner disappears. The local model under
`fixtures/local_llm_plugin/` is a discoverable test-only `llm` plugin. It
replaces only remote computation while settings, preparation, packet planning,
application orchestration, adapters, cache, and public artifact loaders stay
real. It also drives the during-execution currentness race. It needs no
credential or network access.

The installed after-preparation race waits on the TTY-only progress boundary
through a POSIX pseudoterminal. Python's standard library has no Windows
ConPTY equivalent, so that single process-level probe is skipped on Windows.
Portable unit tests still fire the progress renderer and synchronous
pre-execution mutation boundary there. The normal hermetic acceptance job runs
the process-level probe on Ubuntu; remote wheel jobs remain the installation
portability authority.

See also `docs/agent-context/runbooks/adversarial-acceptance-probes.md` for
the generic pattern these probes instantiate.
