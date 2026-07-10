"""Built-in traceability profiles.

Spec: docs/specs/02-backstitch-core.md [SC-3]
"""

from __future__ import annotations

from typing import Any

from backstitch.config import ProfileConfig
from backstitch.diagnostics import load_default_config_raw


def _tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("packaged profile defaults must be arrays of strings")
    return tuple(value)


def _load_backstitch_style_v1() -> ProfileConfig:
    profile = load_default_config_raw()["profile"]
    return ProfileConfig(
        name=profile["name"],
        spec_roots=_tuple(profile["spec_roots"]),
        plan_roots=_tuple(profile["plan_roots"]),
        code_roots=_tuple(profile["code_roots"]),
        test_roots=_tuple(profile["test_roots"]),
        planned_spec_globs=_tuple(profile["planned_spec_globs"]),
        exploratory_spec_globs=_tuple(profile["exploratory_spec_globs"]),
        meta_spec_globs=_tuple(profile.get("meta_spec_globs", [])),
    )


BACKSTITCH_STYLE_V1 = _load_backstitch_style_v1()

_PROFILES: dict[str, ProfileConfig] = {
    BACKSTITCH_STYLE_V1.name: BACKSTITCH_STYLE_V1,
}


def get_profile(name: str) -> ProfileConfig:
    """Return a built-in profile by name.

    Raises ``ValueError`` for unknown names so the CLI can map the failure
    to exit code 2 [SC-5].
    """

    try:
        return _PROFILES[name]
    except KeyError:
        raise ValueError(f"unknown profile: {name!r}") from None
