#!/usr/bin/env python3
"""Refresh provider-free Phase B alignment discovery observations.

The fixture trees and independently reviewed gold remain inputs. This tool
rederives only the frozen production candidate artifacts and the hashes that
bind them. It does not add, remove, or relabel gold candidates.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-10.2]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, cast

from backstitch.alignment_eval import _candidate_artifact_value, _validate_tree
from backstitch.canonical import canonical_json_bytes
from backstitch.settings import resolve_config

ROOT = Path(__file__).parent / "alignment-bootstrap"
PHASE_B = ROOT / "phase-b"


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    return cast(dict[str, Any], value)


def _derived_files() -> dict[Path, bytes]:
    phase_manifest = _load_object(PHASE_B / "fixtures.json")
    fixtures = phase_manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise RuntimeError("Phase B fixtures must be an array")

    derived: dict[Path, bytes] = {}
    for index, value in enumerate(fixtures):
        if not isinstance(value, dict):
            raise RuntimeError(f"Phase B fixtures[{index}] must be an object")
        row = cast(dict[str, Any], value)
        fixture_id = cast(str, row["fixture_id"])
        tree = _validate_tree(
            phase_base=PHASE_B,
            fixture_path=row["fixture_path"],
            tree_manifest_path=row["tree_manifest_path"],
            declared_tree_sha256=row["tree_manifest_sha256"],
            context=f"Phase B fixture {fixture_id}",
        )
        settings = resolve_config(tree.root, environment={})
        artifact = _candidate_artifact_value(
            tree,
            cast(str, row["task_obligation_id"]),
            settings,
        )
        artifact_bytes = canonical_json_bytes(artifact)
        artifact_path = PHASE_B / cast(str, row["candidate_artifact_path"])
        derived[artifact_path] = artifact_bytes
        row["candidate_artifact_sha256"] = (
            "sha256:" + hashlib.sha256(artifact_bytes).hexdigest()
        )

    phase_bytes = canonical_json_bytes(phase_manifest)
    derived[PHASE_B / "fixtures.json"] = phase_bytes

    root_manifest = _load_object(ROOT / "manifest.json")
    root_manifest["phase_b_fixture_manifest_sha256"] = (
        "sha256:" + hashlib.sha256(phase_bytes).hexdigest()
    )
    derived[ROOT / "manifest.json"] = canonical_json_bytes(root_manifest)
    return derived


def write() -> None:
    for path, raw in _derived_files().items():
        path.write_bytes(raw)


def check() -> None:
    changed = [
        path.relative_to(ROOT).as_posix()
        for path, expected in _derived_files().items()
        if path.read_bytes() != expected
    ]
    if changed:
        raise SystemExit(f"alignment bootstrap observations drifted: {changed}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    arguments = parser.parse_args()
    if arguments.write:
        write()
    else:
        check()


if __name__ == "__main__":
    main()
