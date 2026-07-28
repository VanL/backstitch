"""Installed alignment guide artifact ([EVC-8.1])."""

from __future__ import annotations

import hashlib
from importlib.resources import files
from typing import Any

from backstitch import __version__
from backstitch.canonical import canonical_json_bytes

GUIDE_SCHEMA_VERSION = 1
GUIDE_ID = "alignment"
GUIDE_VERSION = 2
GUIDE_CONTENT_SHA256_BY_VERSION = {
    1: "45e678f3eca717d65313b7bea6617a2b2a532e7b1ca20376cf249c7234acc04b",
    2: "195587dac2541df9a367c6f65347eefccde06236ef16a1fb0e07861774ae3dcb",
}


def load_alignment_guide() -> dict[str, Any]:
    """Return the closed, content-addressed installed guide artifact."""

    content = files("backstitch").joinpath("guides", "alignment.md").read_text("utf-8")
    content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if content_sha256 != GUIDE_CONTENT_SHA256_BY_VERSION.get(GUIDE_VERSION):
        raise RuntimeError(
            "installed alignment guide content changed without a version/hash update"
        )
    return {
        "guide_schema_version": GUIDE_SCHEMA_VERSION,
        "guide_id": GUIDE_ID,
        "guide_version": GUIDE_VERSION,
        "backstitch_version": __version__,
        "content_sha256": content_sha256,
        "content": content,
    }


def render_alignment_guide(fmt: str) -> str:
    """Render exact Markdown or canonical JSON with one final newline."""

    artifact = load_alignment_guide()
    if fmt == "text":
        return str(artifact["content"])
    return canonical_json_bytes(artifact).decode("utf-8") + "\n"
