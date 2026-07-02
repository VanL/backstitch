"""Built-in traceability profiles.

Spec: docs/specs/02-backstitch-core.md [SC-3]
"""

from __future__ import annotations

from backstitch.config import ProfileConfig

BACKSTITCH_STYLE_V1 = ProfileConfig(
    name="backstitch-style-v1",
    spec_roots=("docs/specs",),
    plan_roots=("docs/plans",),
    code_roots=("backstitch", "tests"),
    planned_spec_globs=(),
    exploratory_spec_globs=(),
)

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
