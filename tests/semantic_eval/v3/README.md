# Schema-3 semantic evaluation corpora

This directory keeps two different evidence products separate.

`manifest.json` is the small, non-authoritative corpus for deterministic runner
and loader tests. It is preregistered for report mode only. It does not qualify
stronger policy, make a historical-recall claim, or satisfy the enforce corpus
floors.

`qualification-candidate/manifest.json` is an enforce-shaped preregistration
corpus. It has 20 source-reviewed synthetic misalignment controls encoded in
the schema's historical-unit rows and all [EVC-10.1] control tags. Its source
coordinates are generated through the provider-free production derivation
path. It is not policy authority: the fresh synthetic sources do not establish
the contract's real-historical trust boundary, no model run or qualification
report is committed here, and a human must separately resolve the historical
source blocker before reviewing and pinning any passing report.

For the smoke corpus, the gold records were derived by direct inspection of the
fixture source and the public identity/receipt formulas before any semantic
product output was run. The clean variant is a negative control. The mutation
preserves executable reciprocal trace declarations while changing the declared
implementation from returning `1` to returning `2`.

Frozen content digests:

- manifest canonical object:
  `sha256:b5cbed195b945b5f3951faca69c2e9ee2c75cc66b563dd57ea206bc73d0f6027`
- manifest raw file (one final LF):
  `sha256:35b63a39da2456715edd8563c4866a5e92e85a8494c46c74b403ce9e0714f7f2`
- clean tree manifest:
  `sha256:dd1e5a17ad78f890dc06f1f18807e0440cce438c571b630f2636504802153220`
- returns-two tree manifest:
  `sha256:d724a9ec871bab6b8f1e4934a87368c8d38db3c7560779b56d377b2fe11b5990`

The qualification-candidate corpus has its own generation and review record in
[`qualification-candidate/README.md`](qualification-candidate/README.md).
