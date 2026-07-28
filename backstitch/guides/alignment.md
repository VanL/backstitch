# Backstitch alignment quick start

Repository source is the authority. Backstitch itself remains read-only: it
reads source but does not ratify or edit trace relations.
An authorized coding agent may prepare or apply an ordinary source diff within
the caller's authority.
That working-tree edit is not ratified or landed until a human reviews it.

Use two separate phases. Bootstrap asks which current code or tests are
plausible candidates for an obligation. Human review records accepted evidence
in repository source. Gate then rebuilds a current evidence packet from those
source declarations and reports whether the packet appears to support the
obligation. A candidate report is never gate authority.

1. Run `backstitch obligation list --repo-root .` to find spec sections and
   invariants that the repository is expected to implement or test.
2. Run `backstitch obligation OBLIGATION_ID --summarize-evidence` to inspect
   declared mappings, backlinks, invariant targets, and binding tests.
3. Run `backstitch obligation OBLIGATION_ID --find-evidence` to inspect
   deterministic source candidates. A candidate is advice, not evidence. Rerun
   this command after source changes to refresh the snapshot-bound report.
4. Inspect one candidate with `--candidate CANDIDATE_ID`. Review its suggested
   mapping, backlink, invariant-target, or binding-test guidance before editing
   source.
5. A human reviews and lands the ordinary source diff. Rerun `backstitch check`
   and the obligation detail. Only supported declarations in captured source
   establish evidence. Profile and configuration facts can still change scope
   and readiness; candidate or model output cannot establish alignment.
6. When the obligation reports executable readiness and semantic review is
   wanted, run `backstitch analyze --repo-root PATH`. Current analysis derives
   its packet from current human-reviewed source declarations; it does not
   consume an earlier candidate report.

Candidate trace states describe existing source declarations:

- `declared`: the required reciprocal evidence relation is complete.
- `partially_declared`: some declaration exists, but a required role or the
  reciprocal side is missing.
- `untraced`: no relevant declaration associates the candidate with the
  obligation.
- `conflicted`: ambiguous, duplicate, malformed, or contradictory declarations
  prevent one relation answer.

The supported reciprocal section forms are a spec mapping and a code backlink:

```markdown
_Implementation mapping_:
- `pkg/widget.py::Widget.run`
```

```python
class Widget:
    def run(self) -> None:
        """Spec: docs/specs/01-widget.md [WIDGET-1]"""
```

An invariant is declared in an ID-bearing spec section or a Python owner with
`Invariant: [INV.WIDGET.1] statement`. For a spec-declared invariant, declare
its implementation target with the owning section's ordinary mapping form:

```markdown
_Implementation mapping_:
- `pkg/widget.py::Widget.run`
```

The target must be a captured regular parseable Python file.
It selects an exact owner or the whole module: `pkg/widget.py::Widget.run` or
`pkg/widget.py`. A directory, non-Python file, syntax-invalid file, missing
owner, or target classified only as test code is not an atomic implementation
target.

For a code-declared invariant, the Python owner that contains the `Invariant:`
marker is already the implementation target. It needs no separate target
marker. A concrete test binds either form with
`Tests-invariant: [INV.WIDGET.1]` in the test definition's docstring. Invariant
readiness requires an implementation target and a binding test; it does not
require the section mapping/backlink pair used for ordinary section
obligations.

## Adding and removing evidence

To add evidence, edit only the source declarations shown above. Then run
`backstitch check --repo-root .` and inspect the obligation again. Discovery
advice is not evidence before the source declaration exists.

To remove evidence:

1. Run `backstitch obligation OBLIGATION_ID --summarize-evidence` and review the
   exact declarations and source coordinates.
2. Remove only the reviewed declarations. For ordinary section evidence,
   remove both sides together: the spec mapping and matching code `Spec:`
   backlink. For invariant evidence, remove the reviewed implementation-target
   mapping or `Tests-invariant:` marker without disturbing unrelated entries.
3. Rerun `backstitch check --repo-root .`, then rerun the evidence summary and
   obligation detail. Resolve any accidental one-sided trace before landing.

Human approval remains the authority for adding, removing, and landing evidence.

A source-authored `skip-obligation` marker is an auditable semantic disposition;
it does not repair alignment or suppress ordinary trace diagnostics.

```markdown
## Contract [WIDGET-1] <!-- backstitch: skip-obligation [WIDGET-1] "Owned by an external conformance gate." -->
```

Audit skips with `backstitch check --repo-root . --show-suppressions`. Backstitch
shows and processes skips; authoring or removing one remains an ordinary
human-reviewed source change.
