"""Shared scalar and closed-record contract validation mechanics.

Spec: docs/specs/05-backstitch-invariants.md [INV-11]
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, cast

from backstitch.grammar import is_prefixed_sha256, is_sha256_hex


@dataclass(frozen=True, slots=True)
class ValidationPolicy:
    """Family-specific behavior retained by thin validation wrappers."""

    require_nfc: bool = False


@dataclass(frozen=True, slots=True)
class ContractValidators:
    """Mechanics shared by one artifact family's error and text policy."""

    error_cls: type[Exception]
    policy: ValidationPolicy

    def _raise(self, message: str) -> None:
        raise self.error_cls(message)

    def closed_record(
        self,
        value: object,
        fields: frozenset[str] | set[str],
        name: str,
        *,
        mismatch_message: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            self._raise(f"{name} must be an object")
        row = cast(dict[str, Any], value)
        actual = set(row)
        expected = set(fields)
        if actual != expected:
            self._raise(
                mismatch_message
                or f"{name} has invalid keys "
                f"(missing={sorted(expected - actual)}, extra={sorted(actual - expected)})"
            )
        return row

    def nonblank(self, value: object, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            self._raise(f"{name} must be a nonblank string")
        assert isinstance(value, str)
        if self.policy.require_nfc and unicodedata.normalize("NFC", value) != value:
            self._raise(f"{name} must be NFC")
        return value

    def boolean(self, value: object, name: str) -> bool:
        if not isinstance(value, bool):
            self._raise(f"{name} must be a boolean")
        return cast(bool, value)

    def integer(self, value: object, name: str, *, minimum: int = 0) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            self._raise(f"{name} must be an integer greater than or equal to {minimum}")
        return cast(int, value)

    def digest(self, value: object, name: str, *, prefixed: bool = False) -> str:
        valid = is_prefixed_sha256(value) if prefixed else is_sha256_hex(value)
        if not valid:
            label = "sha256:<lowercase digest>" if prefixed else "lowercase SHA-256"
            self._raise(f"{name} must be {label}")
        assert isinstance(value, str)
        return value

    def relative_path(self, value: object, name: str) -> str:
        path = self.nonblank(value, name)
        if "\\" in path:
            self._raise(f"{name} must use POSIX syntax")
        pure = PurePosixPath(path)
        if (
            pure.is_absolute()
            or pure.as_posix() != path
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            self._raise(f"{name} must be a contained relative path")
        return pure.as_posix()


def make_validators(
    error_cls: type[Exception], policy: ValidationPolicy | None = None
) -> ContractValidators:
    """Build validators for one artifact family without erasing its policy."""

    return ContractValidators(error_cls, policy or ValidationPolicy())
