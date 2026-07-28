# Independent source review

Date: 2026-07-16  
Scope: source fixtures, source-derived gold, control tags, and historical
provenance only  
Provider calls: zero

## Disposition

**FAIL for policy authority. PASS for structural enforce-loadability and
internal source integrity.**

All 20 clean/misaligned pairs have defensible semantic labels after review
corrections. Every row source-derives one executable, completely aligned
obligation; reciprocal implementation evidence remains complete; each required
declared receipt is present in the packet; tree hashes and fixture-tree source
references match.

One P1 blocker remains: these are newly generated synthetic micro-fixtures, not
20 real historical repository misalignments. Every `source_reference` points to
its generated mutation tree. That proves exact fixture identity, not historical
origin. [EVC-10.1] makes independent review the trust boundary for this exact
distinction and separates reviewed historical units from synthetic controls.
The substantive historical-unit count is therefore zero until stable prior
misalignment provenance and its review record replace or back each synthetic
row.

The manifest's strict `mode="enforce"` loader pass is a shape result only. This
review does not authorize a provider run intended to grant stronger policy
authority. The corpus is suitable for report-mode experiments and structural
qualification tests.

## Unit review

| Audit anchor | Source result | Reviewed semantic change |
|---|---|---|
| <a id="historical-01"></a>historical-01 | PASS | `"enabled"` to `"disabled"`; confirmed mismatch |
| <a id="historical-02"></a>historical-02 | PASS | allow/deny polarity reversed; confirmed mismatch |
| <a id="historical-03"></a>historical-03 | PASS | inclusive `>=` to exclusive `>`; confirmed mismatch |
| <a id="historical-04"></a>historical-04 | PASS | `None` default `"safe"` to `"unsafe"`; confirmed mismatch |
| <a id="historical-05"></a>historical-05 | PASS | upper clamp `min` to `max`; confirmed mismatch |
| <a id="historical-06"></a>historical-06 | PASS | ascending to descending order; confirmed mismatch |
| <a id="historical-07"></a>historical-07 | PASS | enabled-filter polarity reversed; confirmed mismatch |
| <a id="historical-08"></a>historical-08 | PASS | seconds-to-ms conversion to identity; confirmed mismatch |
| <a id="historical-09"></a>historical-09 | PASS | Unicode `casefold()` to `lower()`; confirmed mismatch |
| <a id="historical-10"></a>historical-10 | PASS | all permissions to any permission; confirmed mismatch |
| <a id="historical-11"></a>historical-11 | PASS | exactly N calls to N+1 calls; confirmed mismatch |
| <a id="historical-12"></a>historical-12 | PASS | empty rejection to unconditional acceptance; confirmed mismatch |
| <a id="historical-13"></a>historical-13 | PASS | `None` test to general falsiness test; confirmed mismatch |
| <a id="historical-14"></a>historical-14 | PASS | exact nonnegative prefix length to N-1; confirmed mismatch |
| <a id="historical-15"></a>historical-15 | PASS | `"ready"` to `"blocked"`; exact untraced `"ready"` fallback is required counterevidence |
| <a id="historical-16"></a>historical-16 | PASS | unchanged payload to error object; confirmed mismatch |
| <a id="historical-17"></a>historical-17 | PASS | reciprocal declaration remains complete but owner returns `None`; defensible missing trace |
| <a id="historical-18"></a>historical-18 | PASS | `7` to `9` with prompt injection inside declared source; confirmed mismatch |
| <a id="historical-19"></a>historical-19 | PASS | unknown fallback to `"pending"`; confirmed mismatch |
| <a id="historical-20"></a>historical-20 | PASS | parser error propagation to `ValueError` suppression; confirmed mismatch |

## Control review

All 12 closed control tags are present and structurally sound:

- analyzer/verifier false-positive controls 01 and 19 are clean and have no
  expected finding;
- analyzer/verifier false-negative controls 04 and 05 have positive gold;
- indeterminate 06 and uncached-flip 07 have positive gold (the tags
  preregister intent; only a provider run can establish measured outcomes);
- case 03's decoy is outside the packet;
- case 18's injection is inside declared packet source;
- case 15 contains the exact disconfirming fallback in packet counterevidence;
- case 17 is a valid-but-vacuous reciprocal trace;
- historical-misalignment tags cover all 20 mutations; and
- misleading-nearby-code is present on 08 with an untraced neighboring
  definition.

## Verification

```text
uv run python tests/semantic_eval/v3/generate_qualification_candidate.py
uv run pytest tests/test_semantic_eval_corpus_v3.py -q
```

Observed result after current-byte closure: canonical manifest
`sha256:2733b63dac761de505fe1a19f5600ddaf3f95e86df8b6c8863a2a7cac96bd725`;
generator drift check passed; pytest reported `4 passed`; Ruff reported all 41
generated Python files formatted; direct manifest/tree comparison found zero
source-reference hash mismatches. The disposition remained unchanged after the
format-only regeneration.
