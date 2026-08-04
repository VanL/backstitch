"""Canonical identity for semantic qualification search epochs.

Producer and authoritative validation share only this encoder. Validation
still reconstructs every input independently from trusted corpus and report
structure.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-10.1]
Spec: docs/specs/02-backstitch-core.md [SC-17]
"""

from __future__ import annotations

import hashlib
from typing import Literal

from backstitch.canonical import canonical_json_bytes
from backstitch.grammar import is_sha256_hex

EvalSearchDomain = Literal["eval-analyze", "eval-verify"]
_EVAL_SEARCH_DOMAINS = frozenset({"eval-analyze", "eval-verify"})


def derive_eval_search_epoch(
    domain: EvalSearchDomain,
    base: str,
    corpus_sha256: str,
    trial_index: int,
) -> str:
    """Bind one closed eval lane to its base epoch, corpus, and trial."""

    if domain not in _EVAL_SEARCH_DOMAINS:
        raise ValueError("eval search epoch domain is invalid")
    if not isinstance(base, str) or not base.strip():
        raise ValueError("base search epoch must be nonblank")
    if not isinstance(corpus_sha256, str) or not (
        corpus_sha256.startswith("sha256:")
        and is_sha256_hex(corpus_sha256.removeprefix("sha256:"))
    ):
        raise ValueError(
            "qualification corpus sha256 must be sha256:<lowercase digest>"
        )
    if (
        isinstance(trial_index, bool)
        or not isinstance(trial_index, int)
        or trial_index < 0
    ):
        raise ValueError("trial index must be a nonnegative integer")
    payload = {
        "base_search_epoch": base,
        "qualification_corpus_sha256": corpus_sha256,
        "trial_index": trial_index,
    }
    return f"{domain}:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
