"""ProfileConfig contract: meta classification is a first-class profile field.

Spec: docs/specs/02-backstitch-core.md [SC-3]
Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-3]
"""

from __future__ import annotations

import pytest

from backstitch.config import ProfileConfig
from backstitch.profiles import BACKSTITCH_STYLE_V1, get_profile


def test_profile_config_exposes_meta_spec_globs() -> None:
    profile = ProfileConfig(
        name="x",
        spec_roots=("docs/specs",),
        plan_roots=(),
        code_roots=("pkg",),
        planned_spec_globs=(),
        exploratory_spec_globs=(),
        meta_spec_globs=("docs/specs/01-*.md",),
    )
    assert profile.meta_spec_globs == ("docs/specs/01-*.md",)


def test_builtin_profile_defaults_match_sc3() -> None:
    profile = get_profile("backstitch-style-v1")
    assert profile is BACKSTITCH_STYLE_V1
    assert profile.spec_roots == ("docs/specs",)
    assert profile.plan_roots == ("docs/plans",)
    assert profile.code_roots == ("backstitch", "tests")
    assert profile.meta_spec_globs == ()


def test_with_overrides_supports_weft_shape() -> None:
    weft = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specifications",),
        code_roots=("weft", "tests"),
        planned_spec_globs=("docs/specifications/*A-*.md",),
        exploratory_spec_globs=(
            "docs/specifications/13B-*.md",
            "docs/specifications/13C-*.md",
        ),
    )
    assert weft.spec_roots == ("docs/specifications",)
    assert weft.plan_roots == ("docs/plans",)


def test_unknown_profile_raises_value_error() -> None:
    with pytest.raises(ValueError):
        get_profile("no-such-profile")
