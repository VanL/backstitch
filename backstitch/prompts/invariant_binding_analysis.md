You are reviewing whether the shown tests bind one declared invariant to the
shown target code. Use only the supplied packet. Do not infer repository
content that is absent from the packet.

Describe a concrete target-code change that violates this invariant while
every shown test still passes. If none exists, cite the specific assertion
lines in shown binding-test snippets that would fail.

Return exactly one JSON object with these fields:

- `packet_id`: the supplied packet ID
- `classification`: one of `ok`, `weak_binding`, `confirmed_mismatch`,
  `probable_mismatch`, or `ambiguous`
- `summary`: a concise explanation
- `confidence`: a number from zero through one, or null
- `rationale`: one or two sentences supporting the classification
- `evidence`: an array of objects with exactly `role`, `path`, 1-based
  inclusive `start_line`, and `end_line`

Use `ok` only when the shown binding tests contain concrete assertions that
would fail for the proposed violating change. Use `weak_binding` when the
tests are related but the shown assertions do not establish the invariant.
Use mismatch classifications only for target behavior that conflicts with the
invariant. Use `ambiguous` when the bounded packet cannot support a stronger
judgment.

Use `requirement` for the declaration excerpt, `implementation` for target
snippets, and `test` for binding-test snippets. `ok` requires test evidence.
`weak_binding` and mismatch findings require requirement and implementation
evidence. `ambiguous` requires requirement evidence. Return exactly the six
top-level fields and no extra evidence fields. Every declaration, target, and
binding test gives its exact citable `start_line` and `end_line`. The
`evidence_regions` list is the closed evidence vocabulary: copy evidence items
verbatim from that list. Never invent, widen, combine, or bridge listed
regions, including disjoint regions with the same path. A target or binding
test with `end_line: null` has no citable content.
