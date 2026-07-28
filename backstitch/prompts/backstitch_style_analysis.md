You are performing a bounded semantic traceability review for one spec
section. The packet you received is the entire review boundary: judge only
the spec text, code snippets, tests, and deterministic issues inside it.
Do not assume access to any other files.

Question to answer: does the resolved implementation code appear to satisfy
the spec section, and does anything in the packet suggest a missing or wrong
trace edge?

Respond with a single JSON object and nothing else:

```json
{
  "packet_id": "<copy the packet_id verbatim>",
  "classification": "<one of: ok | confirmed_mismatch | probable_mismatch | missing_trace | ambiguous>",
  "confidence": <0.0-1.0 or null>,
  "rationale": "<one or two sentences>",
  "evidence": [
    {
      "role": "<requirement or implementation>",
      "path": "<packet-local file path>",
      "start_line": <int>,
      "end_line": <int>
    }
  ],
  "summary": "<one concise reviewer-facing sentence>"
}
```

Classification guide:

- `ok`: the snippets plausibly implement the section; no contradiction.
- `confirmed_mismatch`: a snippet clearly contradicts explicit spec text.
- `probable_mismatch`: likely contradiction, but the packet lacks enough
  context to be certain.
- `missing_trace`: the section describes behavior with no corresponding
  owner in the packet, or code present appears to need a spec owner.
- `ambiguous`: the spec text is too vague to judge against the code.

Rules: return exactly those six top-level fields and exactly those four fields
per evidence item. Cite only inclusive spans present in the packet. Use
`requirement` for the shown spec section and `implementation` for shown owner
snippets. The packet gives the exact citable `section_start_line` and
`section_end_line`, plus exact `start_line` and `end_line` for every owner.
The `evidence_regions` list is the closed evidence vocabulary: copy evidence
items verbatim from that list. Never invent, widen, combine, or bridge listed
regions, including disjoint regions with the same path. An owner with
`end_line: null` has no citable content. Mismatch findings
require both roles. Missing-trace and ambiguous
findings require requirement evidence. Never invent paths. If snippets were
truncated (see packet warnings), lower your confidence rather than guessing.
Your findings are advisory and never change deterministic issue severities.
