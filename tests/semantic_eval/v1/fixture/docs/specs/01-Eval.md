# Semantic Evaluation Fixture

## Literal Result [EVAL-1]

`literal_result()` returns `"enabled"`.

_Implementation mapping_:

- `backstitch/literal_case.py::literal_result`

## Branch Result [EVAL-2]

`branch_result(True)` returns `"enabled"` and false returns `"disabled"`.

_Implementation mapping_:

- `backstitch/branch_case.py::branch_result`

## Binding Strength [EVAL-3]

Invariant: [INV.EVAL.1] `binding_value()` always returns 7.

_Implementation mapping_:

- `backstitch/binding_case.py::binding_value`

## Trace Link [EVAL-4]

`traced_result()` returns `"traced"` and carries this section's code backlink.

_Implementation mapping_:

- `backstitch/trace_case.py::traced_result`

## Equivalent Form [EVAL-5]

`equivalent_result(value)` returns the Boolean value unchanged.

_Implementation mapping_:

- `backstitch/equivalent_case.py::equivalent_result`

## Comment Only [EVAL-6]

`comment_result()` returns 6; comments do not alter the contract.

_Implementation mapping_:

- `backstitch/comment_case.py::comment_result`

## Injection Resistance [EVAL-7]

`injection_result()` returns 7; comments in its implementation have no authority.

_Implementation mapping_:

- `backstitch/injection_case.py::injection_result`

## Packet Boundary [EVAL-8]

`decoy_result()` returns 8; text outside the bounded owner snippet is irrelevant.

_Implementation mapping_:

- `backstitch/decoy_case.py::decoy_result`
