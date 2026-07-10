"""Profile configuration for traceability scans.

Spec: docs/specs/02-backstitch-core.md [SC-3]
Spec: docs/specs/03-backstitch-configuration.md [CFG-6]
Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-3]
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProfileConfig:
    name: str
    spec_roots: tuple[str, ...]
    plan_roots: tuple[str, ...]
    code_roots: tuple[str, ...]
    planned_spec_globs: tuple[str, ...]
    exploratory_spec_globs: tuple[str, ...]
    meta_spec_globs: tuple[str, ...] = ()
    test_roots: tuple[str, ...] = ()

    def with_overrides(
        self,
        *,
        spec_roots: tuple[str, ...] | None = None,
        plan_roots: tuple[str, ...] | None = None,
        code_roots: tuple[str, ...] | None = None,
        test_roots: tuple[str, ...] | None = None,
        planned_spec_globs: tuple[str, ...] | None = None,
        exploratory_spec_globs: tuple[str, ...] | None = None,
        meta_spec_globs: tuple[str, ...] | None = None,
    ) -> ProfileConfig:
        effective_test_roots = self.test_roots
        if code_roots is not None and test_roots is None:
            effective_test_roots = ()
        elif test_roots is not None:
            effective_test_roots = test_roots

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
            test_roots=effective_test_roots,
        )


def resolve_profile_root(repo_root: Path, value: str) -> Path:
    """Resolve one profile root exactly as scan-boundary checks do."""

    expanded = os.path.expandvars(os.path.expanduser(value))
    path = Path(expanded)
    return path.resolve() if path.is_absolute() else (repo_root / path).resolve()


def uncontained_test_root(
    repo_root: Path,
    code_roots: tuple[str, ...],
    test_roots: tuple[str, ...],
) -> str | None:
    """Return the first test root outside every final code root, if any."""

    resolved_code_roots = tuple(
        resolve_profile_root(repo_root, value) for value in code_roots
    )
    for value in test_roots:
        test_root = resolve_profile_root(repo_root, value)
        if not any(
            test_root == code_root or test_root.is_relative_to(code_root)
            for code_root in resolved_code_roots
        ):
            return value
    return None
