"""Built-in traceability profiles.

Spec: docs/specs/02-backstitch-core.md [SC-3]
"""

from __future__ import annotations

from typing import Any, Protocol

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


class ProfileOverridesView(Protocol):
    """Profile override values consumed by the profile projector."""

    @property
    def spec_roots(self) -> tuple[str, ...] | None: ...

    @property
    def plan_roots(self) -> tuple[str, ...] | None: ...

    @property
    def code_roots(self) -> tuple[str, ...] | None: ...

    @property
    def test_roots(self) -> tuple[str, ...] | None: ...

    @property
    def planned_spec_globs(self) -> tuple[str, ...] | None: ...

    @property
    def exploratory_spec_globs(self) -> tuple[str, ...] | None: ...

    @property
    def meta_spec_globs(self) -> tuple[str, ...] | None: ...


class ProfileSettingsView(Protocol):
    """Resolved settings fields needed to construct one scan profile."""

    @property
    def profile(self) -> str | None: ...

    @property
    def profile_overrides(self) -> ProfileOverridesView: ...


def get_profile(name: str) -> ProfileConfig:
    """Return a built-in profile by name.

    Raises ``ValueError`` for unknown names so the CLI can map the failure
    to exit code 2 [SC-5].
    """

    try:
        return _PROFILES[name]
    except KeyError:
        raise ValueError(f"unknown profile: {name!r}") from None


def configured_profile(
    settings: ProfileSettingsView,
    *,
    name: str | None = None,
) -> ProfileConfig:
    """Project immutable resolved settings onto one built-in profile."""

    profile = get_profile(name or settings.profile or "backstitch-style-v1")
    config_overrides: dict[str, tuple[str, ...]] = {}
    for field in (
        "spec_roots",
        "plan_roots",
        "code_roots",
        "test_roots",
        "planned_spec_globs",
        "exploratory_spec_globs",
        "meta_spec_globs",
    ):
        value = getattr(settings.profile_overrides, field)
        if value is not None:
            config_overrides[field] = value
    if config_overrides:
        profile = profile.with_overrides(**config_overrides)
    return profile
