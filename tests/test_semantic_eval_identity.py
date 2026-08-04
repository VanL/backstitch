"""Canonical semantic-eval epoch identity.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-10.1]
"""

from __future__ import annotations

from typing import cast

import pytest

from backstitch.semantic_eval_identity import (
    EvalSearchDomain,
    derive_eval_search_epoch,
)

_CORPUS_SHA256 = (
    "sha256:b5cbed195b945b5f3951faca69c2e9ee2c75cc66b563dd57ea206bc73d0f6027"
)


@pytest.mark.parametrize(
    ("domain", "base", "trial", "expected"),
    (
        (
            "eval-analyze",
            "analysis-v1",
            0,
            "eval-analyze:"
            "9c9839b1c40b1eba100b3553a48427f255714266dce4468473bc4a513f760fa0",
        ),
        (
            "eval-verify",
            "verify-a",
            7,
            "eval-verify:"
            "65035d22c4b7c9a52c07e655a6dc4cc7a7e8a49092f456a48b07179e229eeff3",
        ),
    ),
)
def test_eval_search_epoch_bytes_are_stable(
    domain: EvalSearchDomain,
    base: str,
    trial: int,
    expected: str,
) -> None:
    assert derive_eval_search_epoch(domain, base, _CORPUS_SHA256, trial) == expected
    assert expected.count(":") == 1


def test_eval_search_epoch_rejects_unknown_domain() -> None:
    with pytest.raises(ValueError, match="domain"):
        derive_eval_search_epoch(
            cast(EvalSearchDomain, "evaluation"),
            "analysis-v1",
            _CORPUS_SHA256,
            0,
        )


@pytest.mark.parametrize(
    ("base", "corpus_sha256", "trial"),
    (
        ("analysis-v2", _CORPUS_SHA256, 0),
        ("analysis-v1", "sha256:" + "0" * 64, 0),
        ("analysis-v1", _CORPUS_SHA256, 1),
    ),
)
def test_eval_search_epoch_binds_every_input(
    base: str, corpus_sha256: str, trial: int
) -> None:
    assert derive_eval_search_epoch(
        "eval-analyze", base, corpus_sha256, trial
    ) != derive_eval_search_epoch("eval-analyze", "analysis-v1", _CORPUS_SHA256, 0)
