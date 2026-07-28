"""Semantic configuration contract tests.

Spec: docs/specs/03-backstitch-configuration.md [CFG-5.1], [CFG-6], [CFG-8],
[CFG-9]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-12.2]
"""

from __future__ import annotations

import tomllib
from dataclasses import asdict
from pathlib import Path

import pytest

from backstitch.config import resolve_profile_root
from backstitch.diagnostics import default_registry, resolve_level
from backstitch.settings import (
    ConfigLoadError,
    VerifySettings,
    resolve_config,
)

SEMANTIC_CODES = {
    "SEMANTIC_CONFIRMED_MISMATCH": "BSA001",
    "SEMANTIC_PROBABLE_MISMATCH": "BSA002",
    "SEMANTIC_MISSING_TRACE": "BSA003",
    "SEMANTIC_WEAK_BINDING": "BSA004",
    "SEMANTIC_AMBIGUOUS": "BSA005",
    "SEMANTIC_SUPPRESSION_RATIONALE_INSUFFICIENT": "BSA006",
    "SEMANTIC_SUPPRESSION_SCOPE_OVERBROAD": "BSA007",
    "SEMANTIC_SUPPRESSION_RISK_UNADDRESSED": "BSA008",
}
VERIFICATION_STATES = (
    "evidence_bound",
    "verification_indeterminate",
    "independently_verified",
    "mechanically_verified",
    "human_verified",
    "disputed_by_verifier",
    "human_rejected",
)
PACKAGED_LEVELS = {
    "SEMANTIC_CONFIRMED_MISMATCH": (
        "warning",
        "warning",
        "warning",
        "warning",
        "warning",
        "info",
        "info",
    ),
    "SEMANTIC_PROBABLE_MISMATCH": (
        "info",
        "info",
        "warning",
        "warning",
        "warning",
        "info",
        "info",
    ),
    "SEMANTIC_MISSING_TRACE": (
        "warning",
        "warning",
        "warning",
        "warning",
        "warning",
        "info",
        "info",
    ),
    "SEMANTIC_WEAK_BINDING": (
        "warning",
        "warning",
        "warning",
        "warning",
        "warning",
        "info",
        "info",
    ),
    "SEMANTIC_AMBIGUOUS": (
        "info",
        "info",
        "info",
        "info",
        "info",
        "info",
        "info",
    ),
    "SEMANTIC_SUPPRESSION_RATIONALE_INSUFFICIENT": (
        "warning",
        "warning",
        "warning",
        "warning",
        "warning",
        "info",
        "info",
    ),
    "SEMANTIC_SUPPRESSION_SCOPE_OVERBROAD": (
        "warning",
        "warning",
        "warning",
        "warning",
        "warning",
        "info",
        "info",
    ),
    "SEMANTIC_SUPPRESSION_RISK_UNADDRESSED": (
        "warning",
        "warning",
        "warning",
        "warning",
        "warning",
        "info",
        "info",
    ),
}


def _write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / ".backstitch.toml"
    path.write_text(body, encoding="utf-8")
    return path


def _valid_cached_analyze_lines() -> list[str]:
    return [
        "[analyze]",
        'backend_id = "llm"',
        'plugin_id = "plugin"',
        'plugin_distribution_name = "plugin-dist"',
        'model = "model"',
        'model_revision = "revision"',
        'json_mode = "require"',
        'cache_mode = "read-write"',
    ]


VERIFY_BASE_VALUES = {
    "enabled": "true",
    "provider_source": '"override"',
    "concurrency": "2",
    "cache_path": '"cache/verify"',
    "cache_mode": '"require"',
    "search_epochs": '["epoch-a", "epoch-b"]',
    "json_mode": '"require"',
    "temperature": "0.25",
    "seed": "7",
    "max_tokens": "513",
    "required_verdicts": "2",
    "minimum_support_score": "0.75",
    "indeterminate": '"allow"',
    "maximum_provider_calls": "11",
    "maximum_prompt_bytes": "2000",
    "lock_wait_timeout_seconds": "9",
    "maximum_runtime_seconds": "12",
    "maximum_estimated_cost_microusd": "100",
}
VERIFY_PROVIDER_VALUES = {
    "backend_id": '"llm"',
    "plugin_id": '"verify-plugin"',
    "plugin_distribution_name": '"verify-dist"',
    "model": '"verify-model"',
    "model_revision": '"verify-revision"',
    "input_cost_microusd_per_million_tokens": "10",
    "output_cost_microusd_per_million_tokens": "20",
    "input_token_overhead": "30",
    "cost_rate_source": '"provider page, reviewed 2026-07-16"',
}
VERIFY_EVAL_VALUES = {
    "mode": '"report"',
    "qualification_corpus": '"eval/corpus.json"',
    "qualification_corpus_sha256": f'"sha256:{"a" * 64}"',
    "qualification_report": '"eval/report.json"',
    "qualification_report_sha256": f'"sha256:{"b" * 64}"',
    "trials": "2",
    "interval_method": '"wilson"',
    "confidence_level": "0.95",
    "minimum_positive_units": "0",
    "minimum_negative_units": "0",
    "minimum_evidence_sufficiency_rate": "0.0",
    "minimum_conditional_precision": "0.0",
    "minimum_conditional_recall": "0.0",
    "minimum_end_to_end_recall": "0.0",
    "minimum_recall_lower_bound": "0.0",
    "maximum_false_positive_rate": "1.0",
    "maximum_false_positive_upper_bound": "1.0",
    "maximum_indeterminate_rate": "1.0",
    "maximum_uncached_flip_rate": "1.0",
    "require_all_critical": "false",
}


def _enabled_verify_body(
    *,
    base_overrides: dict[str, str] | None = None,
    remove_base: set[str] | None = None,
    provider_overrides: dict[str, str] | None = None,
    remove_provider: set[str] | None = None,
    include_provider: bool = True,
    eval_overrides: dict[str, str] | None = None,
    remove_eval: set[str] | None = None,
    include_eval: bool = False,
    extra_eval_lines: tuple[str, ...] = (),
    extra_lines: tuple[str, ...] = (),
) -> str:
    base = {**VERIFY_BASE_VALUES, **(base_overrides or {})}
    provider = {**VERIFY_PROVIDER_VALUES, **(provider_overrides or {})}
    evaluation = {**VERIFY_EVAL_VALUES, **(eval_overrides or {})}
    lines = ["[verify]"]
    lines.extend(
        f"{key} = {value}"
        for key, value in base.items()
        if key not in (remove_base or set())
    )
    lines.extend(extra_lines)
    if include_provider:
        lines.append("[verify.provider]")
        lines.extend(
            f"{key} = {value}"
            for key, value in provider.items()
            if key not in (remove_provider or set())
        )
    if include_eval:
        lines.append("[verify.eval]")
        lines.extend(
            f"{key} = {value}"
            for key, value in evaluation.items()
            if key not in (remove_eval or set())
        )
        lines.extend(extra_eval_lines)
    return "\n".join(lines) + "\n"


def _analyze_provider_lines() -> list[str]:
    return [
        "[analyze]",
        'backend_id = "llm"',
        'plugin_id = "analyze-plugin"',
        'plugin_distribution_name = "analyze-dist"',
        'model = "analyze-model"',
        'model_revision = "analyze-revision"',
        'cost_rate_source = "provider page, reviewed 2026-07-16"',
        "input_cost_microusd_per_million_tokens = 10",
        "output_cost_microusd_per_million_tokens = 20",
        "input_token_overhead = 30",
    ]


def test_packaged_semantic_defaults_are_exact(tmp_path: Path) -> None:
    settings = resolve_config(tmp_path, use_repo_config=False)
    analyze = asdict(settings.analyze)
    dispositions = analyze.pop("dispositions")

    assert analyze == {
        "backend_id": "llm",
        "plugin_id": "",
        "plugin_distribution_name": "",
        "model": "",
        "model_revision": "",
        "concurrency": 1,
        "json_mode": "prefer",
        "temperature": 0.0,
        "seed": 42,
        "max_tokens": 512,
        "cache_path": str(
            (
                Path(__file__).parents[1] / "backstitch/.backstitch/semantic-cache"
            ).resolve()
        ),
        "cache_mode": "off",
        "search_epoch": "1",
        "require_complete": False,
        "required_kinds": (),
        "minimum_packets": 0,
        "maximum_packets": 1000,
        "maximum_prompt_bytes": 10_000_000,
        "finding_handling": "report",
        "maximum_provider_calls": 1000,
        "lock_wait_timeout_seconds": 300,
        "maximum_runtime_seconds": 1800,
        "maximum_estimated_cost_microusd": 0,
        "input_cost_microusd_per_million_tokens": 0,
        "output_cost_microusd_per_million_tokens": 0,
        "input_token_overhead": 256,
        "cost_rate_source": "",
    }
    assert dispositions == ()
    assert asdict(settings.verify) == {"enabled": False}


def test_repository_dogfood_semantic_configuration_is_explicit() -> None:
    root = Path(__file__).parents[1]
    with (root / "pyproject.toml").open("rb") as handle:
        backstitch = tomllib.load(handle)["tool"]["backstitch"]
    analyze = backstitch["analyze"]

    assert analyze == {
        "backend_id": "llm",
        "plugin_id": "openai",
        "plugin_distribution_name": "llm",
        "model": "gpt-4.1-mini",
        "model_revision": "gpt-4.1-mini-2025-04-14",
        "concurrency": 1,
        "cache_path": ".backstitch/semantic-cache",
        "cache_mode": "require",
        "search_epoch": "1",
        "json_mode": "require",
        "temperature": 0.0,
        "seed": 42,
        "max_tokens": 512,
        "require_complete": True,
        "required_kinds": ["section", "invariant", "suppression"],
        "minimum_packets": 1,
        "maximum_packets": 100,
        "maximum_prompt_bytes": 1_500_000,
        "finding_handling": "require_disposition",
        "maximum_provider_calls": 100,
        "lock_wait_timeout_seconds": 300,
        "maximum_runtime_seconds": 1800,
        "maximum_estimated_cost_microusd": 1_000_000,
        "input_cost_microusd_per_million_tokens": 400_000,
        "output_cost_microusd_per_million_tokens": 1_600_000,
        "input_token_overhead": 256,
        "cost_rate_source": (
            "OpenAI GPT-4.1 mini model page "
            "(https://developers.openai.com/api/docs/models/gpt-4.1-mini), "
            "reviewed 2026-07-15"
        ),
    }
    assert backstitch["verify"] == {
        "enabled": False,
        "provider_source": "analyze",
        "concurrency": 1,
        "cache_path": ".backstitch/semantic-cache",
        "cache_mode": "require",
        "search_epochs": ["1"],
        "json_mode": "require",
        "temperature": 0.0,
        "seed": 42,
        "max_tokens": 512,
        "required_verdicts": 1,
        "minimum_support_score": 0.90,
        "indeterminate": "report",
        "maximum_provider_calls": 100,
        "maximum_prompt_bytes": 1_000_000,
        "lock_wait_timeout_seconds": 300,
        "maximum_runtime_seconds": 1800,
        "maximum_estimated_cost_microusd": 1_000_000,
        "eval": {
            "mode": "report",
            "qualification_corpus": "",
            "qualification_corpus_sha256": "",
            "qualification_report": "",
            "qualification_report_sha256": "",
            "trials": 2,
            "interval_method": "wilson",
            "confidence_level": 0.95,
            "minimum_positive_units": 1,
            "minimum_negative_units": 1,
            "minimum_evidence_sufficiency_rate": 0.0,
            "minimum_conditional_precision": 0.0,
            "minimum_conditional_recall": 0.0,
            "minimum_end_to_end_recall": 0.0,
            "minimum_recall_lower_bound": 0.0,
            "maximum_false_positive_rate": 1.0,
            "maximum_false_positive_upper_bound": 1.0,
            "maximum_indeterminate_rate": 1.0,
            "maximum_uncached_flip_rate": 1.0,
            "require_all_critical": False,
        },
    }
    assert asdict(resolve_config(root).verify) == {"enabled": False}

    update_settings = resolve_config(
        root,
        explicit=root / "pyproject.toml",
        cli_options=(
            ("analyze.cache_mode", "read-write"),
            ("verify.enabled", "true"),
            ("verify.cache_mode", "read-write"),
        ),
    )
    assert isinstance(update_settings.verify, VerifySettings)
    assert update_settings.analyze.cache_mode == "read-write"
    assert update_settings.verify.cache_mode == "read-write"


def test_enabled_verify_override_parses_every_base_and_provider_key(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path, _enabled_verify_body())

    verify = asdict(resolve_config(tmp_path, explicit=config).verify)

    assert verify == {
        "enabled": True,
        "provider_source": "override",
        "concurrency": 2,
        "cache_path": str((tmp_path / "cache/verify").resolve()),
        "cache_mode": "require",
        "search_epochs": ("epoch-a", "epoch-b"),
        "json_mode": "require",
        "temperature": 0.25,
        "seed": 7,
        "max_tokens": 513,
        "required_verdicts": 2,
        "minimum_support_score": 0.75,
        "indeterminate": "allow",
        "maximum_provider_calls": 11,
        "maximum_prompt_bytes": 2000,
        "lock_wait_timeout_seconds": 9,
        "maximum_runtime_seconds": 12,
        "maximum_estimated_cost_microusd": 100,
        "provider": {
            "backend_id": "llm",
            "plugin_id": "verify-plugin",
            "plugin_distribution_name": "verify-dist",
            "model": "verify-model",
            "model_revision": "verify-revision",
            "input_cost_microusd_per_million_tokens": 10,
            "output_cost_microusd_per_million_tokens": 20,
            "input_token_overhead": 30,
            "cost_rate_source": "provider page, reviewed 2026-07-16",
        },
        "eval": None,
    }


def test_disabled_verify_accepts_a_complete_dormant_descriptor(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        _enabled_verify_body(base_overrides={"enabled": "false"}),
    )

    settings = resolve_config(tmp_path, explicit=config, environment={})

    assert asdict(settings.verify) == {"enabled": False}


def test_cli_option_activates_a_complete_dormant_descriptor(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        _enabled_verify_body(base_overrides={"enabled": "false"}),
    )

    settings = resolve_config(
        tmp_path,
        explicit=config,
        environment={},
        cli_options=(("verify.enabled", "true"),),
    )

    assert isinstance(settings.verify, VerifySettings)
    assert settings.verify.enabled is True


def test_cli_option_cannot_activate_minimal_disabled_verification(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigLoadError, match="verify.provider_source"):
        resolve_config(
            tmp_path,
            use_repo_config=False,
            environment={},
            cli_options=(("verify.enabled", "true"),),
        )


@pytest.mark.parametrize(
    "key", tuple(key for key in VERIFY_BASE_VALUES if key != "enabled")
)
def test_enabled_verify_requires_every_base_key(tmp_path: Path, key: str) -> None:
    config = _write_config(
        tmp_path,
        _enabled_verify_body(remove_base={key}),
    )

    with pytest.raises(ConfigLoadError, match=rf"verify\.{key}"):
        resolve_config(tmp_path, explicit=config)


@pytest.mark.parametrize("key", tuple(VERIFY_PROVIDER_VALUES))
def test_verify_override_requires_every_provider_key(
    tmp_path: Path,
    key: str,
) -> None:
    config = _write_config(
        tmp_path,
        _enabled_verify_body(remove_provider={key}),
    )

    with pytest.raises(ConfigLoadError, match=r"verify\.provider"):
        resolve_config(tmp_path, explicit=config)


def test_verify_provider_resolution_is_all_or_nothing(tmp_path: Path) -> None:
    missing_override = _write_config(
        tmp_path,
        _enabled_verify_body(include_provider=False),
    )
    with pytest.raises(ConfigLoadError, match="provider"):
        resolve_config(tmp_path, explicit=missing_override)

    analyze_body = "\n".join(_analyze_provider_lines()) + "\n"
    analyze_verify = _enabled_verify_body(
        base_overrides={
            "provider_source": '"analyze"',
            "maximum_estimated_cost_microusd": "100",
        },
        include_provider=False,
    )
    analyze_config = _write_config(tmp_path, analyze_body + analyze_verify)
    settings = resolve_config(tmp_path, explicit=analyze_config)
    verify = settings.verify
    assert isinstance(verify, VerifySettings)
    assert verify.provider_source == "analyze"
    assert verify.provider is None

    analyze_with_override = _write_config(
        tmp_path,
        analyze_body
        + _enabled_verify_body(
            base_overrides={"provider_source": '"analyze"'},
        ),
    )
    with pytest.raises(ConfigLoadError, match="must be absent"):
        resolve_config(tmp_path, explicit=analyze_with_override)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("enabled", "1"),
        ("provider_source", '"fallback"'),
        ("concurrency", "0"),
        ("cache_path", '"   "'),
        ("cache_mode", '"sometimes"'),
        ("search_epochs", '"epoch"'),
        ("search_epochs", '["epoch", 1]'),
        ("json_mode", '"sometimes"'),
        ("temperature", "nan"),
        ("temperature", "2.1"),
        ("seed", "-1"),
        ("max_tokens", "0"),
        ("required_verdicts", "0"),
        ("minimum_support_score", "1.1"),
        ("indeterminate", '"error"'),
        ("maximum_provider_calls", "-1"),
        ("maximum_prompt_bytes", "0"),
        ("lock_wait_timeout_seconds", "0"),
        ("maximum_runtime_seconds", "false"),
        ("maximum_estimated_cost_microusd", "-1"),
    ],
)
def test_enabled_verify_base_types_and_ranges_are_strict(
    tmp_path: Path,
    key: str,
    value: str,
) -> None:
    config = _write_config(
        tmp_path,
        _enabled_verify_body(base_overrides={key: value}),
    )

    with pytest.raises(ConfigLoadError, match=key):
        resolve_config(tmp_path, explicit=config)


@pytest.mark.parametrize(
    ("epochs", "verdicts"),
    [
        ('["epoch", "epoch"]', "2"),
        ('["epoch", "   "]', "2"),
        ("[]", "1"),
        ('["epoch-a", "epoch-b"]', "1"),
    ],
)
def test_verify_epochs_are_nonblank_unique_and_match_required_verdicts(
    tmp_path: Path,
    epochs: str,
    verdicts: str,
) -> None:
    config = _write_config(
        tmp_path,
        _enabled_verify_body(
            base_overrides={
                "search_epochs": epochs,
                "required_verdicts": verdicts,
            }
        ),
    )

    with pytest.raises(ConfigLoadError, match=r"search_epochs|required_verdicts"):
        resolve_config(tmp_path, explicit=config)


def test_verify_rejects_unknown_and_disabled_extra_keys(tmp_path: Path) -> None:
    unknown = _write_config(
        tmp_path,
        _enabled_verify_body(extra_lines=("lock_stale_seconds = 1",)),
    )
    with pytest.raises(ConfigLoadError, match="verify.lock_stale_seconds"):
        resolve_config(tmp_path, explicit=unknown)

    unknown_provider = _write_config(
        tmp_path,
        _enabled_verify_body(provider_overrides={"typo": "1"}),
    )
    with pytest.raises(ConfigLoadError, match="verify.provider.typo"):
        resolve_config(tmp_path, explicit=unknown_provider)

    disabled_extra = _write_config(
        tmp_path,
        "[verify]\nenabled = false\nconcurrency = 1\n",
    )
    with pytest.raises(ConfigLoadError, match="verify.provider_source"):
        resolve_config(tmp_path, explicit=disabled_extra)


def test_verify_cache_and_cost_cross_field_rules_are_strict(tmp_path: Path) -> None:
    prefer_cached = _write_config(
        tmp_path,
        _enabled_verify_body(base_overrides={"json_mode": '"prefer"'}),
    )
    with pytest.raises(ConfigLoadError, match="prefer"):
        resolve_config(tmp_path, explicit=prefer_cached)

    blank_source = _write_config(
        tmp_path,
        _enabled_verify_body(provider_overrides={"cost_rate_source": '""'}),
    )
    with pytest.raises(ConfigLoadError, match="cost_rate_source"):
        resolve_config(tmp_path, explicit=blank_source)

    prefer_off = _write_config(
        tmp_path,
        _enabled_verify_body(
            base_overrides={
                "json_mode": '"prefer"',
                "cache_mode": '"off"',
                "maximum_provider_calls": "0",
                "maximum_estimated_cost_microusd": "0",
            },
            provider_overrides={"cost_rate_source": '""'},
        ),
    )
    settings = resolve_config(tmp_path, explicit=prefer_off)
    verify = settings.verify
    assert isinstance(verify, VerifySettings)
    assert verify.maximum_provider_calls == 0
    assert verify.provider is not None
    assert verify.provider.cost_rate_source == ""


def test_verify_analyze_reuse_requires_explicit_cost_inputs_for_positive_budget(
    tmp_path: Path,
) -> None:
    analyze_lines = _analyze_provider_lines()
    analyze_lines = [
        line
        for line in analyze_lines
        if not line.startswith(
            (
                "input_cost_microusd_per_million_tokens",
                "output_cost_microusd_per_million_tokens",
                "input_token_overhead",
            )
        )
    ]
    config = _write_config(
        tmp_path,
        "\n".join(analyze_lines)
        + "\n"
        + _enabled_verify_body(
            base_overrides={"provider_source": '"analyze"'},
            include_provider=False,
        ),
    )

    with pytest.raises(ConfigLoadError, match="explicit analyze rate"):
        resolve_config(tmp_path, explicit=config)


@pytest.mark.parametrize(
    "body",
    [
        'verify = "not-a-table"\n',
        _enabled_verify_body(
            include_provider=False,
            extra_lines=("provider = 1",),
        ),
        _enabled_verify_body(extra_lines=("eval = 1",)),
    ],
)
def test_verify_tables_reject_wrong_shapes(tmp_path: Path, body: str) -> None:
    config = _write_config(tmp_path, body)

    with pytest.raises(ConfigLoadError, match="verify"):
        resolve_config(tmp_path, explicit=config)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("backend_id", '"   "'),
        ("plugin_id", '""'),
        ("plugin_distribution_name", '""'),
        ("model", '""'),
        ("model_revision", '""'),
        ("input_cost_microusd_per_million_tokens", "-1"),
        ("output_cost_microusd_per_million_tokens", "true"),
        ("input_token_overhead", "-1"),
        ("cost_rate_source", "1"),
    ],
)
def test_verify_override_provider_values_are_strict(
    tmp_path: Path,
    key: str,
    value: str,
) -> None:
    config = _write_config(
        tmp_path,
        _enabled_verify_body(provider_overrides={key: value}),
    )

    with pytest.raises(ConfigLoadError, match=key):
        resolve_config(tmp_path, explicit=config)


def test_verify_eval_report_parses_every_key_and_anchors_paths(
    tmp_path: Path,
) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    parent = shared / "parent.toml"
    parent.write_text(
        _enabled_verify_body(include_eval=True),
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()
    child = project / "child.toml"
    child.write_text('extend = "../shared/parent.toml"\n', encoding="utf-8")

    verify = resolve_config(project, explicit=child).verify

    assert isinstance(verify, VerifySettings)
    assert verify.cache_path == str((shared / "cache/verify").resolve())
    evaluation = asdict(verify)["eval"]
    assert evaluation == {
        "mode": "report",
        "qualification_corpus": str((shared / "eval/corpus.json").resolve()),
        "qualification_corpus_sha256": f"sha256:{'a' * 64}",
        "qualification_report": str((shared / "eval/report.json").resolve()),
        "qualification_report_sha256": f"sha256:{'b' * 64}",
        "trials": 2,
        "interval_method": "wilson",
        "confidence_level": 0.95,
        "minimum_positive_units": 0,
        "minimum_negative_units": 0,
        "minimum_evidence_sufficiency_rate": 0.0,
        "minimum_conditional_precision": 0.0,
        "minimum_conditional_recall": 0.0,
        "minimum_end_to_end_recall": 0.0,
        "minimum_recall_lower_bound": 0.0,
        "maximum_false_positive_rate": 1.0,
        "maximum_false_positive_upper_bound": 1.0,
        "maximum_indeterminate_rate": 1.0,
        "maximum_uncached_flip_rate": 1.0,
        "require_all_critical": False,
    }


@pytest.mark.parametrize("key", tuple(VERIFY_EVAL_VALUES))
def test_verify_eval_requires_every_key(tmp_path: Path, key: str) -> None:
    config = _write_config(
        tmp_path,
        _enabled_verify_body(include_eval=True, remove_eval={key}),
    )

    with pytest.raises(ConfigLoadError, match=r"verify\.eval"):
        resolve_config(tmp_path, explicit=config)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("mode", '"audit"'),
        ("qualification_corpus", "1"),
        ("qualification_corpus_sha256", '"SHA256:ABC"'),
        ("qualification_report", "false"),
        ("qualification_report_sha256", '"sha256:abc"'),
        ("trials", "0"),
        ("interval_method", '"bootstrap"'),
        ("confidence_level", "0.0"),
        ("confidence_level", "1.0"),
        ("minimum_positive_units", "true"),
        ("minimum_negative_units", "-1"),
        ("minimum_evidence_sufficiency_rate", "nan"),
        ("minimum_conditional_precision", "true"),
        ("minimum_conditional_recall", "-0.1"),
        ("minimum_end_to_end_recall", "1.1"),
        ("minimum_recall_lower_bound", "nan"),
        ("maximum_false_positive_rate", "-0.1"),
        ("maximum_false_positive_upper_bound", "1.1"),
        ("maximum_indeterminate_rate", "nan"),
        ("maximum_uncached_flip_rate", "false"),
        ("require_all_critical", "1"),
    ],
)
def test_verify_eval_types_ranges_and_hashes_are_strict(
    tmp_path: Path,
    key: str,
    value: str,
) -> None:
    config = _write_config(
        tmp_path,
        _enabled_verify_body(
            include_eval=True,
            eval_overrides={key: value},
        ),
    )

    with pytest.raises(ConfigLoadError, match=key):
        resolve_config(tmp_path, explicit=config)


def test_verify_eval_report_mode_allows_blank_paths_and_hashes(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        _enabled_verify_body(
            include_eval=True,
            eval_overrides={
                "qualification_corpus": '""',
                "qualification_corpus_sha256": '""',
                "qualification_report": '""',
                "qualification_report_sha256": '""',
            },
        ),
    )

    verify = resolve_config(tmp_path, explicit=config).verify

    assert isinstance(verify, VerifySettings)
    evaluation = verify.eval
    assert evaluation is not None
    assert evaluation.qualification_corpus == ""
    assert evaluation.qualification_report == ""


def test_verify_eval_enforce_accepts_only_the_promoting_contract(
    tmp_path: Path,
) -> None:
    enforce_values = {
        "mode": '"enforce"',
        "trials": "2",
        "minimum_positive_units": "1",
        "minimum_negative_units": "1",
        "minimum_evidence_sufficiency_rate": "0.1",
        "minimum_conditional_precision": "0.1",
        "minimum_conditional_recall": "0.1",
        "minimum_end_to_end_recall": "0.1",
        "minimum_recall_lower_bound": "0.1",
        "maximum_false_positive_rate": "0.0",
        "maximum_false_positive_upper_bound": "0.9",
        "maximum_indeterminate_rate": "0.9",
        "maximum_uncached_flip_rate": "0.9",
        "require_all_critical": "true",
    }
    config = _write_config(
        tmp_path,
        _enabled_verify_body(include_eval=True, eval_overrides=enforce_values),
    )

    verify = resolve_config(tmp_path, explicit=config).verify
    assert isinstance(verify, VerifySettings)
    assert verify.eval is not None
    assert verify.eval.mode == "enforce"


def test_verify_eval_enforce_allows_blank_candidate_report_binding(
    tmp_path: Path,
) -> None:
    enforce_values = {
        "mode": '"enforce"',
        "qualification_report": '""',
        "qualification_report_sha256": '""',
        "minimum_positive_units": "1",
        "minimum_negative_units": "1",
        "minimum_evidence_sufficiency_rate": "0.1",
        "minimum_conditional_precision": "0.1",
        "minimum_conditional_recall": "0.1",
        "minimum_end_to_end_recall": "0.1",
        "minimum_recall_lower_bound": "0.1",
        "maximum_false_positive_rate": "0.0",
        "maximum_false_positive_upper_bound": "0.9",
        "maximum_indeterminate_rate": "0.9",
        "maximum_uncached_flip_rate": "0.9",
        "require_all_critical": "true",
    }
    config = _write_config(
        tmp_path,
        _enabled_verify_body(include_eval=True, eval_overrides=enforce_values),
    )

    verify = resolve_config(tmp_path, explicit=config).verify

    assert isinstance(verify, VerifySettings)
    assert verify.eval is not None
    assert verify.eval.mode == "enforce"
    assert verify.eval.qualification_report == ""
    assert verify.eval.qualification_report_sha256 == ""


@pytest.mark.parametrize("mode", ["report", "enforce"])
@pytest.mark.parametrize(
    "blank_key",
    ["qualification_report", "qualification_report_sha256"],
)
def test_verify_eval_rejects_half_present_report_binding(
    tmp_path: Path,
    mode: str,
    blank_key: str,
) -> None:
    overrides = {
        "mode": f'"{mode}"',
        "qualification_report": '"eval/report.json"',
        "qualification_report_sha256": f'"sha256:{"b" * 64}"',
        blank_key: '""',
    }
    if mode == "enforce":
        overrides.update(
            {
                "minimum_positive_units": "1",
                "minimum_negative_units": "1",
                "minimum_evidence_sufficiency_rate": "0.1",
                "minimum_conditional_precision": "0.1",
                "minimum_conditional_recall": "0.1",
                "minimum_end_to_end_recall": "0.1",
                "minimum_recall_lower_bound": "0.1",
                "maximum_false_positive_rate": "0.0",
                "maximum_false_positive_upper_bound": "0.9",
                "maximum_indeterminate_rate": "0.9",
                "maximum_uncached_flip_rate": "0.9",
                "require_all_critical": "true",
            }
        )
    config = _write_config(
        tmp_path,
        _enabled_verify_body(include_eval=True, eval_overrides=overrides),
    )

    with pytest.raises(ConfigLoadError, match="report path and hash.*both blank"):
        resolve_config(tmp_path, explicit=config)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("qualification_corpus", '""'),
        ("qualification_corpus_sha256", '""'),
        ("trials", "1"),
        ("minimum_positive_units", "0"),
        ("minimum_negative_units", "0"),
        ("minimum_evidence_sufficiency_rate", "0.0"),
        ("minimum_conditional_precision", "0.0"),
        ("minimum_conditional_recall", "0.0"),
        ("minimum_end_to_end_recall", "0.0"),
        ("minimum_recall_lower_bound", "0.0"),
        ("maximum_false_positive_rate", "0.1"),
        ("maximum_false_positive_upper_bound", "1.0"),
        ("maximum_indeterminate_rate", "1.0"),
        ("maximum_uncached_flip_rate", "1.0"),
        ("require_all_critical", "false"),
    ],
)
def test_verify_eval_enforce_rejects_each_nonpromoting_value(
    tmp_path: Path,
    key: str,
    value: str,
) -> None:
    enforce_values = {
        "mode": '"enforce"',
        "minimum_positive_units": "1",
        "minimum_negative_units": "1",
        "minimum_evidence_sufficiency_rate": "0.1",
        "minimum_conditional_precision": "0.1",
        "minimum_conditional_recall": "0.1",
        "minimum_end_to_end_recall": "0.1",
        "minimum_recall_lower_bound": "0.1",
        "maximum_false_positive_rate": "0.0",
        "maximum_false_positive_upper_bound": "0.9",
        "maximum_indeterminate_rate": "0.9",
        "maximum_uncached_flip_rate": "0.9",
        "require_all_critical": "true",
        key: value,
    }
    config = _write_config(
        tmp_path,
        _enabled_verify_body(include_eval=True, eval_overrides=enforce_values),
    )

    with pytest.raises(ConfigLoadError, match=r"verify\.eval.*enforce|enforce"):
        resolve_config(tmp_path, explicit=config)


@pytest.mark.parametrize("key", ["qualification_corpus", "qualification_report"])
def test_verify_eval_paths_must_stay_contained_in_their_config_layer(
    tmp_path: Path,
    key: str,
) -> None:
    config = _write_config(
        tmp_path,
        _enabled_verify_body(
            include_eval=True,
            eval_overrides={key: '"../outside.json"'},
        ),
    )

    with pytest.raises(ConfigLoadError, match=rf"{key}.*contained"):
        resolve_config(tmp_path, explicit=config)


def test_verify_eval_unknown_key_is_rejected(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        _enabled_verify_body(include_eval=True, extra_eval_lines=("typo = 1",)),
    )

    with pytest.raises(ConfigLoadError, match="verify.eval.typo"):
        resolve_config(tmp_path, explicit=config)


@pytest.mark.parametrize(
    "key",
    ["minimum_candidate_capture_rate", "minimum_trace_state_precision"],
)
def test_verify_eval_rejects_product_stage_metric_keys(
    tmp_path: Path,
    key: str,
) -> None:
    config = _write_config(
        tmp_path,
        _enabled_verify_body(
            include_eval=True,
            remove_eval={
                "minimum_candidate_capture_rate",
                "minimum_trace_state_precision",
            },
            extra_eval_lines=(f"{key} = 0.0",),
        ),
    )

    with pytest.raises(ConfigLoadError, match=rf"verify\.eval\.{key}"):
        resolve_config(tmp_path, explicit=config)


def test_packaged_semantic_registry_and_full_matrix() -> None:
    registry = default_registry()
    settings = resolve_config(Path.cwd(), use_repo_config=False)

    for code, short in SEMANTIC_CODES.items():
        definition = registry.require(code)
        assert definition.short_code == short
        assert definition.status == "implemented"
        assert definition.contexts == VERIFICATION_STATES
        assert (
            tuple(
                resolve_level(code, context=state, policy=settings.diagnostics)
                for state in VERIFICATION_STATES
            )
            == PACKAGED_LEVELS[code]
        )


def test_required_kinds_normalize_to_canonical_order(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        '[analyze]\nrequired_kinds = ["suppression", "invariant", "section"]\n',
    )
    settings = resolve_config(tmp_path, explicit=config)
    assert settings.analyze.required_kinds == (
        "section",
        "invariant",
        "suppression",
    )


@pytest.mark.parametrize(
    "value",
    [
        '["section", "section"]',
        '["section", "unknown"]',
        '"section"',
    ],
)
def test_required_kinds_reject_duplicates_unknowns_and_wrong_type(
    tmp_path: Path,
    value: str,
) -> None:
    config = _write_config(tmp_path, f"[analyze]\nrequired_kinds = {value}\n")
    with pytest.raises(ConfigLoadError, match="required_kinds"):
        resolve_config(tmp_path, explicit=config)


def test_cache_path_anchors_at_winning_extended_layer(tmp_path: Path) -> None:
    base_dir = tmp_path / "shared"
    base_dir.mkdir()
    base = base_dir / "base.toml"
    base.write_text('[analyze]\ncache_path = "cache/base"\n', encoding="utf-8")
    child_dir = tmp_path / "project"
    child_dir.mkdir()
    child = child_dir / ".backstitch.toml"
    child.write_text('extend = "../shared/base.toml"\n', encoding="utf-8")
    inherited = resolve_config(child_dir, explicit=child)
    assert inherited.analyze.cache_path == str((base_dir / "cache/base").resolve())

    child.write_text(
        'extend = "../shared/base.toml"\n[analyze]\ncache_path = "cache/child"\n',
        encoding="utf-8",
    )
    overridden = resolve_config(child_dir, explicit=child)
    assert overridden.analyze.cache_path == str((child_dir / "cache/child").resolve())


def test_explicit_trusted_config_keeps_mutable_paths_outside_target_root(
    tmp_path: Path,
) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    parent = trusted / "parent.toml"
    parent.write_text(
        "\n".join(
            [
                "[profile]",
                'spec_roots = ["docs/specs"]',
                'code_roots = ["pkg"]',
                'test_roots = ["pkg/tests"]',
                "[analyze]",
                'backend_id = "llm"',
                'plugin_id = "openai"',
                'plugin_distribution_name = "llm"',
                'model = "trusted-model"',
                'model_revision = "trusted-revision"',
                'json_mode = "require"',
                'cache_path = "cache/semantic"',
                'cache_mode = "read-write"',
                "[[diagnostics.levels]]",
                'select = ["BSA*"]',
                'level = "info"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    child = trusted / "child.toml"
    child.write_text('extend = "parent.toml"\n', encoding="utf-8")

    settings = resolve_config(target, explicit=child.resolve())

    assert settings.config_layers[-2:] == (
        str(parent.resolve()),
        str(child.resolve()),
    )
    assert settings.analyze.cache_path == str((trusted / "cache/semantic").resolve())
    assert settings.analyze.model == "trusted-model"
    assert settings.policy_rule_origins[-1].source == str(parent.resolve())
    assert settings.profile_overrides.spec_roots == ("docs/specs",)
    assert settings.profile_overrides.code_roots == ("pkg",)
    assert settings.profile_overrides.test_roots == ("pkg/tests",)
    assert (
        resolve_profile_root(target, settings.profile_overrides.spec_roots[0])
        == (target / "docs/specs").resolve()
    )
    assert (
        resolve_profile_root(target, settings.profile_overrides.code_roots[0])
        == (target / "pkg").resolve()
    )


def test_config_layers_and_policy_origins_include_entire_extend_chain(
    tmp_path: Path,
) -> None:
    grandparent = tmp_path / "grandparent.toml"
    grandparent.write_text(
        '[[diagnostics.levels]]\nselect = ["BSA005:evidence_bound"]\nlevel = "info"\n',
        encoding="utf-8",
    )
    parent = tmp_path / "parent.toml"
    parent.write_text(
        'extend = "grandparent.toml"\n'
        '[[diagnostics.levels]]\nselect = ["BSA005:verification_indeterminate"]\nlevel = "info"\n',
        encoding="utf-8",
    )
    child = tmp_path / "child.toml"
    child.write_text(
        'extend = "parent.toml"\n'
        '[[diagnostics.levels]]\nselect = ["BSA005:human_verified"]\nlevel = "warning"\n',
        encoding="utf-8",
    )

    settings = resolve_config(tmp_path, explicit=child)
    assert settings.config_layers == (
        "packaged:backstitch/defaults.toml",
        str(grandparent.resolve()),
        str(parent.resolve()),
        str(child.resolve()),
    )
    assert len(settings.policy_rule_origins) == len(settings.diagnostics.levels)
    assert tuple(
        (origin.source, origin.position) for origin in settings.policy_rule_origins[-3:]
    ) == (
        (str(grandparent.resolve()), 0),
        (str(parent.resolve()), 0),
        (str(child.resolve()), 0),
    )


def test_dispositions_replace_parent_array_and_are_closed(tmp_path: Path) -> None:
    base = tmp_path / "base.toml"
    base.write_text(
        "\n".join(
            [
                "[[analyze.dispositions]]",
                'code = "SEMANTIC_AMBIGUOUS"',
                'packet_id = "old"',
                f'packet_hash = "{"a" * 64}"',
                f'finding_hash = "{"b" * 64}"',
                'status = "rejected"',
                'reason = "superseded"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    child = tmp_path / "child.toml"
    child.write_text(
        "\n".join(
            [
                'extend = "base.toml"',
                "[[analyze.dispositions]]",
                'code = "SEMANTIC_CONFIRMED_MISMATCH"',
                'packet_id = "new"',
                f'packet_hash = "{"c" * 64}"',
                f'finding_hash = "{"d" * 64}"',
                'status = "accepted"',
                'reason = "human review"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    settings = resolve_config(tmp_path, explicit=child)
    assert len(settings.analyze.dispositions) == 1
    assert settings.analyze.dispositions[0].packet_id == "new"


@pytest.mark.parametrize(
    "code",
    [
        "SEMANTIC_SUPPRESSION_RATIONALE_INSUFFICIENT",
        "SEMANTIC_SUPPRESSION_SCOPE_OVERBROAD",
        "SEMANTIC_SUPPRESSION_RISK_UNADDRESSED",
    ],
)
def test_suppression_disposition_codes_are_canonical_inputs(
    tmp_path: Path,
    code: str,
) -> None:
    config = _write_config(
        tmp_path,
        "\n".join(
            [
                "[[analyze.dispositions]]",
                f'code = "{code}"',
                'packet_id = "suppression::docs/specs/x.md#SUP-X"',
                f'packet_hash = "{"a" * 64}"',
                f'finding_hash = "{"b" * 64}"',
                'status = "accepted"',
                'reason = "reviewed"',
            ]
        )
        + "\n",
    )

    settings = resolve_config(tmp_path, explicit=config)

    assert settings.analyze.dispositions[0].code == code


@pytest.mark.parametrize(
    ("line", "match"),
    [
        ('code = "BSA001"', "canonical"),
        ('packet_hash = "ABC"', "packet_hash"),
        ('finding_hash = "abc"', "finding_hash"),
        ('status = "maybe"', "status"),
        ('reason = "   "', "reason"),
        ('extra = "no"', "extra"),
    ],
)
def test_disposition_validation_is_strict(
    tmp_path: Path,
    line: str,
    match: str,
) -> None:
    values = {
        "code": 'code = "SEMANTIC_CONFIRMED_MISMATCH"',
        "packet_hash": f'packet_hash = "{"a" * 64}"',
        "finding_hash": f'finding_hash = "{"b" * 64}"',
        "status": 'status = "accepted"',
        "reason": 'reason = "reviewed"',
    }
    key = line.split(" =", 1)[0]
    values[key] = line
    body = ["[[analyze.dispositions]]", values["code"], 'packet_id = "packet"']
    body.extend(
        [
            values["packet_hash"],
            values["finding_hash"],
            values["status"],
            values["reason"],
        ]
    )
    if key == "extra":
        body.append(line)
    config = _write_config(tmp_path, "\n".join(body) + "\n")
    with pytest.raises(ConfigLoadError, match=match):
        resolve_config(tmp_path, explicit=config)


def test_duplicate_disposition_identity_is_invalid(tmp_path: Path) -> None:
    record = [
        'code = "SEMANTIC_CONFIRMED_MISMATCH"',
        'packet_id = "packet"',
        f'packet_hash = "{"a" * 64}"',
        f'finding_hash = "{"b" * 64}"',
        'status = "accepted"',
        'reason = "reviewed"',
    ]
    config = _write_config(
        tmp_path,
        "\n".join(
            ["[[analyze.dispositions]]", *record, "[[analyze.dispositions]]", *record]
        )
        + "\n",
    )
    with pytest.raises(ConfigLoadError, match="duplicate disposition"):
        resolve_config(tmp_path, explicit=config)


@pytest.mark.parametrize(
    "body",
    [
        "[analyze]\nlock_stale_seconds = 1\n",
        '[analyze.eval]\nmode = "report"\n',
    ],
)
def test_superseded_analyze_producer_keys_are_rejected(
    tmp_path: Path,
    body: str,
) -> None:
    config = _write_config(tmp_path, body)
    with pytest.raises(ConfigLoadError, match="unknown config key"):
        resolve_config(tmp_path, explicit=config)


def test_superseded_analyze_eval_is_only_a_named_unknown_under_the_hatch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _write_config(
        tmp_path,
        'allow_unknown_keys = true\n[analyze.eval]\nmode = "enforce"\n',
    )

    settings = resolve_config(tmp_path, explicit=config)

    assert not hasattr(settings.analyze, "eval")
    assert "unknown config key `analyze.eval`" in capsys.readouterr().err


def test_legacy_analyzer_only_eval_settings_type_is_removed() -> None:
    import backstitch.settings as settings_module

    assert not hasattr(settings_module, "AnalyzeEvalSettings")


def test_candidate_handling_is_a_canonicalizing_one_release_alias(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        '[analyze]\ncandidate_handling = "allow"\n',
    )

    settings = resolve_config(tmp_path, explicit=config)

    assert settings.analyze.finding_handling == "allow"
    assert "candidate_handling" not in asdict(settings.analyze)


@pytest.mark.parametrize("key", ["finding_handling", "candidate_handling"])
def test_finding_handling_and_its_alias_share_one_strict_value_contract(
    tmp_path: Path,
    key: str,
) -> None:
    config = _write_config(tmp_path, f'[analyze]\n{key} = "ignore"\n')

    with pytest.raises(ConfigLoadError, match=key):
        resolve_config(tmp_path, explicit=config)


@pytest.mark.parametrize("finding_value", ["allow", "report"])
def test_finding_and_candidate_handling_cannot_coexist_across_layers(
    tmp_path: Path,
    finding_value: str,
) -> None:
    parent = tmp_path / "parent.toml"
    parent.write_text(
        '[analyze]\ncandidate_handling = "allow"\n',
        encoding="utf-8",
    )
    child = tmp_path / "child.toml"
    child.write_text(
        f'extend = "parent.toml"\n[analyze]\nfinding_handling = "{finding_value}"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError, match="cannot both be supplied"):
        resolve_config(tmp_path, explicit=child)


def test_unknown_key_in_replaced_parent_disposition_is_rejected(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "parent.toml"
    parent.write_text(
        "\n".join(
            [
                "[[analyze.dispositions]]",
                'code = "SEMANTIC_AMBIGUOUS"',
                'packet_id = "parent"',
                f'packet_hash = "{"a" * 64}"',
                f'finding_hash = "{"b" * 64}"',
                'status = "rejected"',
                'reason = "reviewed"',
                'typo = "must not be hidden by replacement"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    child = tmp_path / "child.toml"
    child.write_text(
        "\n".join(
            [
                'extend = "parent.toml"',
                "[[analyze.dispositions]]",
                'code = "SEMANTIC_AMBIGUOUS"',
                'packet_id = "child"',
                f'packet_hash = "{"c" * 64}"',
                f'finding_hash = "{"d" * 64}"',
                'status = "rejected"',
                'reason = "reviewed"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError, match=r"parent\.toml.*typo|typo.*parent\.toml"):
        resolve_config(tmp_path, explicit=child)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("concurrency", "true"),
        ("temperature", "nan"),
        ("temperature", "2.1"),
        ("seed", "-1"),
        ("max_tokens", "0"),
        ("minimum_packets", "-1"),
        ("maximum_provider_calls", "-1"),
        ("lock_wait_timeout_seconds", "0"),
        ("maximum_runtime_seconds", "false"),
    ],
)
def test_analyze_types_and_ranges_are_strict(
    tmp_path: Path,
    key: str,
    value: str,
) -> None:
    config = _write_config(tmp_path, f"[analyze]\n{key} = {value}\n")
    with pytest.raises(ConfigLoadError, match=key):
        resolve_config(tmp_path, explicit=config)


def test_cached_modes_require_identity_and_compatible_json_mode(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path, '[analyze]\ncache_mode = "require"\njson_mode = "off"\n'
    )
    with pytest.raises(ConfigLoadError, match="cached modes"):
        resolve_config(tmp_path, explicit=config)

    lines = _valid_cached_analyze_lines()
    lines[-2] = 'json_mode = "prefer"'
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ConfigLoadError, match="prefer"):
        resolve_config(tmp_path, explicit=config)


def test_cached_config_defers_model_until_cli_and_environment_precedence(
    tmp_path: Path,
) -> None:
    lines = _valid_cached_analyze_lines()
    lines[4] = 'model = ""'
    config = _write_config(tmp_path, "\n".join(lines) + "\n")

    settings = resolve_config(
        tmp_path,
        explicit=config,
        environment={"LLM_MODEL": "runtime-model"},
    )

    assert settings.analyze.cache_mode == "read-write"
    assert settings.analyze.model == "runtime-model"


def test_resolver_rejects_model_override_that_breaks_cached_identity(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path, "\n".join(_valid_cached_analyze_lines()) + "\n")

    with pytest.raises(ConfigLoadError, match="model/revision pair"):
        resolve_config(
            tmp_path,
            explicit=config,
            environment={"LLM_MODEL": "different-model"},
        )


def test_positive_cost_ceiling_requires_explicit_rates_overhead_and_source(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        '[analyze]\nmaximum_estimated_cost_microusd = 1\ncost_rate_source = "2026-07-14 provider page"\n',
    )
    with pytest.raises(ConfigLoadError, match="explicit"):
        resolve_config(tmp_path, explicit=config)

    config.write_text(
        "\n".join(
            [
                "[analyze]",
                "maximum_estimated_cost_microusd = 1",
                "input_cost_microusd_per_million_tokens = 0",
                "output_cost_microusd_per_million_tokens = 10",
                "input_token_overhead = 256",
                'cost_rate_source = "2026-07-14 provider page"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert (
        resolve_config(
            tmp_path, explicit=config
        ).analyze.maximum_estimated_cost_microusd
        == 1
    )

    config.write_text(
        "\n".join(
            [
                "[analyze]",
                "maximum_estimated_cost_microusd = 1",
                "input_cost_microusd_per_million_tokens = 0",
                "output_cost_microusd_per_million_tokens = 10",
                "input_token_overhead = 256",
                'cost_rate_source = ""',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigLoadError, match="cost_rate_source"):
        resolve_config(tmp_path, explicit=config)


def test_positive_cost_inputs_may_come_from_an_effective_parent_layer(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "parent.toml"
    parent.write_text(
        "\n".join(
            [
                "[analyze]",
                "input_cost_microusd_per_million_tokens = 0",
                "output_cost_microusd_per_million_tokens = 10",
                "input_token_overhead = 256",
                'cost_rate_source = "2026-07-14 provider page"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    child = tmp_path / "child.toml"
    child.write_text(
        'extend = "parent.toml"\n[analyze]\nmaximum_estimated_cost_microusd = 1\n',
        encoding="utf-8",
    )

    settings = resolve_config(tmp_path, explicit=child)
    assert settings.analyze.maximum_estimated_cost_microusd == 1
    assert settings.analyze.output_cost_microusd_per_million_tokens == 10


def test_packet_count_cross_field_is_validated(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        "[analyze]\nminimum_packets = 2\nmaximum_packets = 1\n",
    )
    with pytest.raises(ConfigLoadError, match="maximum_packets"):
        resolve_config(tmp_path, explicit=config)
