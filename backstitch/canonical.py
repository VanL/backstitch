"""Canonical byte encodings and LF-only source-line primitives.

Spec: docs/specs/05-backstitch-invariants.md [INV-11]
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal, cast, overload


@dataclass(frozen=True, slots=True)
class CanonicalRepositoryPath:
    """One safe repository path in native and NFC-canonical spelling."""

    native: str
    canonical: str


def canonical_repository_path(raw: str) -> CanonicalRepositoryPath | None:
    """Normalize one authored repository path in the canonical contract order."""

    if any("\ud800" <= character <= "\udfff" for character in raw):
        return None

    canonical = unicodedata.normalize("NFC", raw)
    native = raw
    if canonical.endswith("/"):
        canonical = canonical[:-1]
        native = native[:-1]
    if canonical == ".":
        return CanonicalRepositoryPath(native=".", canonical=".")

    canonical_parts = canonical.split("/")
    native_parts = native.split("/")
    retained = tuple(
        (native_part, canonical_part)
        for native_part, canonical_part in zip(
            native_parts, canonical_parts, strict=True
        )
        if canonical_part != "."
    )
    normalized_native = "/".join(item[0] for item in retained)
    normalized_canonical = "/".join(item[1] for item in retained)
    if (
        not normalized_canonical
        or normalized_canonical.startswith("/")
        or "\x00" in normalized_canonical
        or "\\" in normalized_canonical
        or any(part in ("", "..") for part in normalized_canonical.split("/"))
    ):
        return None
    return CanonicalRepositoryPath(
        native=normalized_native,
        canonical=normalized_canonical,
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Return the one canonical JSON encoding used for stable identities."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


@overload
def lf_split(value: str, *, keepends: bool = False) -> tuple[str, ...]: ...


@overload
def lf_split(value: bytes, *, keepends: bool = False) -> tuple[bytes, ...]: ...


def lf_split(
    value: str | bytes, *, keepends: bool = False
) -> tuple[str, ...] | tuple[bytes, ...]:
    """Split only on LF, matching ``splitlines`` terminal-LF behavior."""

    if isinstance(value, str):
        if value == "":
            return ()
        text_parts = value.split("\n")
        if keepends:
            text_lines = [part + "\n" for part in text_parts[:-1]]
            if text_parts[-1] != "":
                text_lines.append(text_parts[-1])
            return tuple(text_lines)
        if text_parts[-1] == "":
            text_parts.pop()
        return tuple(text_parts)
    if value == b"":
        return ()
    byte_parts = value.split(b"\n")
    if keepends:
        byte_lines = [part + b"\n" for part in byte_parts[:-1]]
        if byte_parts[-1] != b"":
            byte_lines.append(byte_parts[-1])
        return tuple(byte_lines)
    if byte_parts[-1] == b"":
        byte_parts.pop()
    return tuple(byte_parts)


def lf_line_count(value: str | bytes) -> int:
    """Return the number of LF-delimited physical lines."""

    return len(lf_split(value))


@overload
def lf_slice(
    value: str,
    start_line: int,
    end_line: int,
    *,
    policy: Literal["clamped", "strict"],
) -> str: ...


@overload
def lf_slice(
    value: bytes,
    start_line: int,
    end_line: int,
    *,
    policy: Literal["clamped", "strict"],
) -> bytes: ...


def lf_slice(
    value: str | bytes,
    start_line: int,
    end_line: int,
    *,
    policy: Literal["clamped", "strict"],
) -> str | bytes:
    """Return one inclusive 1-based LF-only span under an explicit policy."""

    if policy not in ("clamped", "strict"):
        raise ValueError("line span policy must be clamped or strict")
    lines: tuple[str, ...] | tuple[bytes, ...]
    if isinstance(value, str):
        lines = lf_split(value, keepends=True)
        empty: str | bytes = ""
    else:
        lines = lf_split(value, keepends=True)
        empty = b""

    line_count = len(lines)
    if policy == "strict":
        if line_count == 0:
            raise ValueError("line span cannot address an empty value")
        if (
            start_line < 1
            or end_line < start_line
            or start_line > line_count
            or end_line > line_count
        ):
            raise ValueError("line span is outside the LF-delimited value")
        start = start_line
        end = end_line
    else:
        if line_count == 0 or end_line < start_line or start_line > line_count:
            return empty
        start = max(1, start_line)
        end = min(end_line, line_count)
        if end < start:
            return empty

    if isinstance(value, str):
        return "".join(cast(tuple[str, ...], lines)[start - 1 : end])
    return b"".join(cast(tuple[bytes, ...], lines)[start - 1 : end])


def lf_end_line(start_line: int, value: str | bytes) -> int | None:
    """Return the inclusive end line for nonempty LF-delimited text."""

    count = lf_line_count(value)
    return None if count == 0 else start_line + count - 1
