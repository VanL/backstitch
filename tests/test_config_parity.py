"""Filesystem/blob config parity at the shared finalization boundary.

Spec: docs/specs/03-backstitch-configuration.md [CFG-4], [CFG-5.1], [CFG-9]
Spec: docs/specs/08-intent-coverage.md [COV-5]
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from backstitch.settings import (
    BackstitchSettings,
    ConfigLoadError,
    DisabledVerifySettings,
    resolve_config,
    resolve_repository_config_from_blobs,
)


def _nonoperational(settings: BackstitchSettings) -> BackstitchSettings:
    verify = settings.verify
    if not isinstance(verify, DisabledVerifySettings):
        verify = replace(verify, cache_path="")
    return replace(
        settings,
        check=replace(settings.check, output=None),
        packets=replace(settings.packets, output=None),
        coverage=replace(settings.coverage, output=None),
        analyze=replace(settings.analyze, cache_path=""),
        verify=verify,
        target_roots=replace(settings.target_roots, weft=None),
        config_path=None,
        config_dir=None,
        config_layers=(),
        config_layer_identities=(),
        policy_rule_origins=(),
        ratchet_policy_provenance=(),
        analyze_model_source="",
    )


def _identity_projection(
    settings: BackstitchSettings,
) -> tuple[tuple[str, str, bytes], ...]:
    return tuple(
        (identity.path, identity.raw_sha256, identity.raw_bytes)
        for identity in settings.config_layer_identities
    )


def _assert_source_parity(
    current: BackstitchSettings,
    historical: BackstitchSettings,
) -> None:
    assert _nonoperational(historical) == _nonoperational(current)
    assert historical.config_path == current.config_path
    assert historical.config_dir == current.config_dir
    assert historical.config_layers == current.config_layers
    assert _identity_projection(historical) == _identity_projection(current)
    assert historical.policy_rule_origins == current.policy_rule_origins
    assert historical.ratchet_policy_provenance == current.ratchet_policy_provenance
    assert historical.analyze_model_source == current.analyze_model_source


@pytest.mark.parametrize(
    "body",
    (
        '[profile]\ncode_roots = ["src", "tests"]\ntest_roots = ["tests"]\n',
        (
            '[profile]\ncode_roots = ["src"]\ntest_roots = ["src/tests"]\n'
            "[coverage]\ninherited_counts = true\n"
        ),
        (
            'default_command = "check"\n'
            '[profile]\ncode_roots = ["src", "qa"]\ntest_roots = ["qa"]\n'
        ),
        ('default_command = "analyze"\n[profile]\nname = "backstitch-style-v1"\n'),
        (
            '[profile]\ncode_roots = ["src/./pkg"]\n'
            'test_roots = ["src/other/../pkg/tests"]\n'
        ),
    ),
)
def test_equal_layers_produce_equal_nonoperational_settings(
    tmp_path: Path,
    body: str,
) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text(body, encoding="utf-8")

    current = resolve_config(tmp_path, explicit=config, environment={})
    historical = resolve_repository_config_from_blobs(
        tmp_path,
        ".backstitch.toml",
        {".backstitch.toml": body.encode()},
    )

    _assert_source_parity(current, historical)


def test_extended_layers_share_merge_and_root_reset(tmp_path: Path) -> None:
    parent = (
        '[profile]\ncode_roots = ["src", "qa"]\ntest_roots = ["qa"]\n'
        "[coverage]\ninherited_counts = true\n"
    )
    child = 'extend = "base.toml"\n[profile]\ncode_roots = ["pkg"]\n'
    (tmp_path / "base.toml").write_text(parent, encoding="utf-8")
    config = tmp_path / ".backstitch.toml"
    config.write_text(child, encoding="utf-8")

    current = resolve_config(tmp_path, explicit=config, environment={})
    historical = resolve_repository_config_from_blobs(
        tmp_path,
        ".backstitch.toml",
        {
            ".backstitch.toml": child.encode(),
            "base.toml": parent.encode(),
        },
    )

    _assert_source_parity(current, historical)
    assert historical.profile_overrides.test_roots == ()


def test_file_model_selection_matches_across_sources(tmp_path: Path) -> None:
    body = "\n".join(
        (
            "[analyze]",
            'backend_id = "llm"',
            'plugin_id = "parity-plugin"',
            'plugin_distribution_name = "parity-dist"',
            'model = "pkg:service/parity.test/parity-model"',
            'adapter_model_id = "parity-model"',
            'model_revision = "parity-revision"',
            "capability_schema_version = 1",
            'capability_revision = "parity-capability-v1"',
            "maximum_input_bytes = 1000000",
            (
                "request_constraints = { "
                'json_mode = { presence = "required", '
                'allowed_values = ["require", "off"] }, '
                'temperature = { presence = "required", '
                "allowed_values = [0.0, 1.0] }, "
                'seed = { presence = "required", minimum = 0, '
                "maximum = 2147483647 }, "
                'max_tokens = { presence = "required", minimum = 1, '
                "maximum = 16384 }, "
                'reasoning_effort = { presence = "forbidden" } }'
            ),
            "input_cost_microusd_per_million_tokens = 10",
            "output_cost_microusd_per_million_tokens = 20",
            "input_token_overhead = 30",
            'cost_rate_source = "parity fixture rates, reviewed 2026-07-29"',
            "",
        )
    )
    config = tmp_path / ".backstitch.toml"
    config.write_text(body, encoding="utf-8")

    current = resolve_config(tmp_path, explicit=config, environment={})
    historical = resolve_repository_config_from_blobs(
        tmp_path,
        ".backstitch.toml",
        {".backstitch.toml": body.encode()},
    )

    _assert_source_parity(current, historical)
    assert (
        current.analyze.model
        == historical.analyze.model
        == "pkg:service/parity.test/parity-model"
    )
    assert current.analyze.model_revision == "parity-revision"
    assert current.analyze.available_models == historical.analyze.available_models
    assert current.analyze.available_models == ("pkg:service/parity.test/parity-model",)
    assert current.analyze_model_source == "config [analyze].model"


def test_unknown_key_rejection_matches_across_sources(tmp_path: Path) -> None:
    body = b'unknown_key = true\n[profile]\ncode_roots = ["src"]\n'
    config = tmp_path / ".backstitch.toml"
    config.write_bytes(body)

    with pytest.raises(ConfigLoadError) as current_error:
        resolve_config(tmp_path, explicit=config, environment={})
    with pytest.raises(ConfigLoadError) as historical_error:
        resolve_repository_config_from_blobs(
            tmp_path,
            ".backstitch.toml",
            {".backstitch.toml": body},
        )

    assert "unknown config key `unknown_key`" in str(current_error.value)
    assert "unknown config key `unknown_key`" in str(historical_error.value)
