# Core Specification

This fixture spec exercises the backstitch-style-v1 grammar: heading section
IDs, invariant bullets, implementation mapping blocks, and anchor targets.

## Runtime Behaviour [CORE-1]

The runtime must frobnicate exactly once per call.

_Implementation mapping_:

- `src/runtime.py`
- `src/runtime.py::Runtime.frobnicate`

## Persistence Rules [CORE-2]

Writes go through the runtime save path.

- **CORE.2.1**: writes are atomic.
- **CORE.2.2**: partial writes are never visible to readers.

_Implementation mapping_:

- `src/missing_module.py`
- `Runtime.save`

## Reference Forms [CORE-3]

Prose may mention codes like [NOT-A-SECTION] without defining a section; only
headings and bold invariant bullets define sections.

## Ambiguity Case Original [DUP-1]

This ID is deliberately duplicated in 02-Weft_Style.md.
