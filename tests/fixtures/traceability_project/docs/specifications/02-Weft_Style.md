# Weft Style Forms

This fixture mirrors reference forms observed in the Weft corpus.

## Queue Names

A heading without a section ID contributes only an anchor target.

### Advanced Routing [ROUTE-A1.1]

_Implementation mapping_: `src/runtime.py` — `Runtime`, `Runtime.frobnicate`.

## Layered Mapping [LAYER-1]

_Implementation mapping per layer_:

- `src/runtime.py::Runtime.save`
- [LAYER-1.1] Persistence details — `src/runtime.py`

Prose after a blank line ends the block, so `src/not_a_mapping.py` here is
not a mapping target.

## Duplicate Title

First duplicate anchor.

## Duplicate Title

Second duplicate anchor.

## Directory Ownership [DIRMAP-1]

_Implementation mapping_: `src/`, `docs/specifications/01-Core.md`,
`frobnicate_all()`.

## Ambiguity Case Duplicate [DUP-1]

Deliberate duplicate of the ID defined in 01-Core.md.

## Fenced Examples [FENCE-1]

```text
## Phantom Heading [PHANTOM-9]

_Implementation mapping_: `src/phantom.py`
```

