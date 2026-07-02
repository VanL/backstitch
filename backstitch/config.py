"""Profile configuration for traceability scans.

Spec: docs/specs/02-backstitch-core.md [SC-3]
Spec: docs/specs/03-backstitch-configuration.md [CFG-6]
Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-3]
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProfileConfig:
    name: str
    spec_roots: tuple[str, ...]
    plan_roots: tuple[str, ...]
    code_roots: tuple[str, ...]
    planned_spec_globs: tuple[str, ...]
    exploratory_spec_globs: tuple[str, ...]
    meta_spec_globs: tuple[str, ...] = ()

    def with_overrides(
        self,
        *,
        spec_roots: tuple[str, ...] | None = None,
        plan_roots: tuple[str, ...] | None = None,
        code_roots: tuple[str, ...] | None = None,
        planned_spec_globs: tuple[str, ...] | None = None,
        exploratory_spec_globs: tuple[str, ...] | None = None,
        meta_spec_globs: tuple[str, ...] | None = None,
    ) -> ProfileConfig:
        return ProfileConfig(
            name=self.name,
            spec_roots=spec_roots if spec_roots is not None else self.spec_roots,
            plan_roots=plan_roots if plan_roots is not None else self.plan_roots,
            code_roots=code_roots if code_roots is not None else self.code_roots,
            planned_spec_globs=(
                planned_spec_globs
                if planned_spec_globs is not None
                else self.planned_spec_globs
            ),
            exploratory_spec_globs=(
                exploratory_spec_globs
                if exploratory_spec_globs is not None
                else self.exploratory_spec_globs
            ),
            meta_spec_globs=(
                meta_spec_globs if meta_spec_globs is not None else self.meta_spec_globs
            ),
        )
