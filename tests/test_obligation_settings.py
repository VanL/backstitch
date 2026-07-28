"""Obligation/read-model configuration contract tests.

Spec: docs/specs/03-backstitch-configuration.md [CFG-6.6], [CFG-8]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.3.1]
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from backstitch.settings import ConfigLoadError, resolve_config


def _config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / ".backstitch.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_packaged_obligation_defaults_are_exact(tmp_path: Path) -> None:
    settings = resolve_config(tmp_path, use_repo_config=False)

    assert asdict(settings.obligations) == {
        "section_required_roles": ("implementation",),
        "page_size": 5,
        "maximum_page_size": 100,
        "maximum_response_bytes": 65_536,
        "maximum_candidate_items": 2_000,
        "maximum_catalog_items": 100_000,
        "maximum_lexical_seeds": 10,
        "maximum_snapshot_files": 20_000,
        "maximum_file_bytes": 5_000_000,
        "maximum_snapshot_bytes": 100_000_000,
        "maximum_work_units": 2_000_000,
        "maximum_packet_bytes": 10_000_000,
        "maximum_packet_report_bytes": 10_000_000,
        "maximum_call_seconds": 10.0,
        "snapshot_capture_attempts": 3,
        "static_neighbor_depth": 1,
    }


@pytest.mark.parametrize(
    ("body", "match"),
    [
        (
            '[obligations]\nsection_required_roles = ["test"]\n',
            "must contain implementation",
        ),
        (
            '[obligations]\nsection_required_roles = ["implementation", "implementation"]\n',
            "must not contain duplicates",
        ),
        ("[obligations]\npage_size = 101\n", "page_size.*maximum_page_size"),
        (
            "[obligations]\nmaximum_snapshot_bytes = 100\n",
            "maximum_snapshot_bytes.*maximum_file_bytes",
        ),
        ("[obligations]\nmaximum_response_bytes = 100\n", "at least 16384"),
        ("[obligations]\nsnapshot_capture_attempts = 11\n", "at most 10"),
        ("[obligations]\nstatic_neighbor_depth = 4\n", "at most 3"),
        ("[obligations]\nmaximum_call_seconds = nan\n", "finite"),
        ("[obligations]\ntyop = 1\n", "obligations.tyop"),
    ],
)
def test_invalid_obligation_settings_are_rejected(
    tmp_path: Path, body: str, match: str
) -> None:
    with pytest.raises(ConfigLoadError, match=match):
        resolve_config(tmp_path, explicit=_config(tmp_path, body))


def test_obligation_roles_normalize_to_canonical_order(tmp_path: Path) -> None:
    settings = resolve_config(
        tmp_path,
        explicit=_config(
            tmp_path,
            '[obligations]\nsection_required_roles = ["test", "implementation"]\n',
        ),
    )

    assert settings.obligations.section_required_roles == ("implementation", "test")
