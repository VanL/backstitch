"""Configuration loader tests: discovery, extend, strict unknown keys.

Spec: docs/specs/03-backstitch-configuration.md [CFG-3], [CFG-4], [CFG-5.1],
[CFG-6], [CFG-8], [CFG-9]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-12.2]
Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-3], [EXC-6]
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import backstitch.repository_snapshot as repository_snapshot
import backstitch.settings as settings_module
from backstitch.settings import (
    DEFAULT_EXCLUDES,
    ConfigLoadError,
    discover_config_path,
    expand_path_value,
    is_excluded,
    resolve_config,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_documented_suppression_settings_parse_and_canonicalize(
    tmp_path: Path,
) -> None:
    config = tmp_path / "suppression.toml"
    config.write_text(
        """
[lint]
require_suppression_declarations = true

[[lint.suppressions]]
mechanism = "ignore"
path = "tests/*"
sections = ["CFG-9", "CFG-8"]
codes = ["BSC003", "CODE_REF_UNMAPPED_FROM_SPEC"]
declaration = "docs/specs/04-backstitch-traceability-exclusions.md#SUP-TEST"
""".lstrip(),
        encoding="utf-8",
    )

    resolved = resolve_config(tmp_path, explicit=config, environment={})

    assert resolved.lint.require_suppression_declarations is True
    assert len(resolved.lint.suppressions) == 1
    rule = resolved.lint.suppressions[0]
    assert rule.sections == ("CFG-8", "CFG-9")
    assert rule.codes == (
        "CODE_REF_UNMAPPED_FROM_SPEC",
        "SPEC_MAPPING_RECIPROCAL_MISSING",
    )
    assert rule.origin.source == str(config.resolve())
    assert rule.origin.position == 0


def test_documented_suppression_bool_uses_generic_cli_override(
    tmp_path: Path,
) -> None:
    resolved = resolve_config(
        tmp_path,
        use_repo_config=False,
        environment={},
        cli_options=(("lint.require_suppression_declarations", "true"),),
    )
    assert resolved.lint.require_suppression_declarations is True


@pytest.mark.parametrize(
    "body",
    [
        "[lint]\nrequire_suppression_declarations = 1\n",
        "[lint]\nsuppressions = {}\n",
        (
            "[[lint.suppressions]]\n"
            'mechanism = "meta"\npath = "docs/*.md"\nsections = ["CFG-8"]\n'
            'codes = []\ndeclaration = "docs/specs/04-x.md#SUP-X"\n'
        ),
        (
            "[[lint.suppressions]]\n"
            'mechanism = "ignore"\npath = "docs/*.md"\nsections = []\n'
            'codes = []\ndeclaration = "docs/specs/04-x.md#SUP-X"\n'
        ),
        (
            "[[lint.suppressions]]\n"
            'mechanism = "ignore"\npath = "docs/*.md"\nsections = []\n'
            'codes = ["BSS007"]\ndeclaration = "../outside.md#SUP-X"\n'
        ),
        (
            "[[lint.suppressions]]\n"
            'mechanism = "drop"\npath = "docs/*.md"\nsections = []\n'
            'codes = ["BSS007"]\ndeclaration = "docs/specs/04-x.md#SUP-X"\n'
        ),
        (
            "[[lint.suppressions]]\n"
            'mechanism = "ignore"\npath = "/docs/*.md"\nsections = []\n'
            'codes = ["BSS007"]\ndeclaration = "docs/specs/04-x.md#SUP-X"\n'
        ),
        (
            "[[lint.suppressions]]\n"
            'mechanism = "ignore"\npath = "docs/*.md"\nsections = ["bad"]\n'
            'codes = ["BSS007"]\ndeclaration = "docs/specs/04-x.md#SUP-X"\n'
        ),
        (
            "[[lint.suppressions]]\n"
            'mechanism = "ignore"\npath = "docs/*.md"\nsections = ["CFG-8", "CFG-8"]\n'
            'codes = ["BSS007"]\ndeclaration = "docs/specs/04-x.md#SUP-X"\n'
        ),
        (
            "[[lint.suppressions]]\n"
            'mechanism = "ignore"\npath = "docs/*.md"\nsections = []\n'
            'codes = ["BSS007", "SPEC_SECTION_UNMAPPED"]\n'
            'declaration = "docs/specs/04-x.md#SUP-X"\n'
        ),
    ],
)
def test_documented_suppression_settings_reject_invalid_shapes(
    tmp_path: Path,
    body: str,
) -> None:
    config = tmp_path / "bad.toml"
    config.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigLoadError):
        resolve_config(tmp_path, explicit=config, environment={})


@pytest.mark.parametrize(
    "missing",
    ("mechanism", "path", "sections", "codes", "declaration"),
)
def test_documented_suppression_settings_require_every_closed_field(
    tmp_path: Path,
    missing: str,
) -> None:
    values = {
        "mechanism": '"ignore"',
        "path": '"docs/*.md"',
        "sections": "[]",
        "codes": '["BSS007"]',
        "declaration": '"docs/specs/04-x.md#SUP-X"',
    }
    config = tmp_path / "missing.toml"
    config.write_text(
        "[[lint.suppressions]]\n"
        + "\n".join(f"{key} = {value}" for key, value in values.items() if key != missing)
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError, match="missing required keys"):
        resolve_config(tmp_path, explicit=config, environment={})


def test_structured_suppression_unknown_field_uses_existing_hatch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "future.toml"
    config.write_text(
        """
allow_unknown_keys = true

[[lint.suppressions]]
mechanism = "ignore"
path = "tests/*"
sections = []
codes = ["BSC003"]
declaration = "docs/specs/04-x.md#SUP-X"
future_field = "ignored"
""".lstrip(),
        encoding="utf-8",
    )
    resolved = resolve_config(tmp_path, explicit=config, environment={})
    assert len(resolved.lint.suppressions) == 1
    assert "lint.suppressions[0].future_field" in capsys.readouterr().err


def test_structured_suppression_array_replaces_across_extend(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "parent.toml"
    parent.write_text(
        """
[[lint.suppressions]]
mechanism = "ignore"
path = "parent/*"
sections = []
codes = ["BSC003"]
declaration = "docs/specs/04-x.md#SUP-PARENT"
""".lstrip(),
        encoding="utf-8",
    )
    child = tmp_path / "child.toml"
    child.write_text(
        """
extend = "parent.toml"

[[lint.suppressions]]
mechanism = "meta"
path = "docs/meta.md"
sections = []
codes = []
declaration = "docs/specs/04-x.md#SUP-CHILD"
""".lstrip(),
        encoding="utf-8",
    )
    resolved = resolve_config(tmp_path, explicit=child, environment={})
    assert [rule.path for rule in resolved.lint.suppressions] == ["docs/meta.md"]
    assert resolved.lint.suppressions[0].origin.source == str(child.resolve())


def test_resolve_config_applies_cli_over_environment_over_explicit_config(
    tmp_path: Path,
) -> None:
    config = tmp_path / "arbitrary-name.toml"
    config.write_text('[analyze]\nmodel = "config-model"\n', encoding="utf-8")

    resolved = resolve_config(
        tmp_path,
        explicit=config,
        environment={"LLM_MODEL": "environment-model"},
        cli_options=(("analyze.model", "cli-model"),),
    )

    assert resolved.analyze.model == "cli-model"
    assert resolved.analyze_model_source == "--option analyze.model"
    assert resolved.config_path == config.resolve()


def test_resolve_config_precedence_fires_at_every_layer(tmp_path: Path) -> None:
    parent = tmp_path / "parent.toml"
    parent.write_text('[analyze]\nmodel = "parent-model"\n', encoding="utf-8")
    child = tmp_path / "child.toml"
    child.write_text(
        'extend = "parent.toml"\n[analyze]\nmodel = "child-model"\n',
        encoding="utf-8",
    )
    inherited = tmp_path / "inherited.toml"
    inherited.write_text('extend = "parent.toml"\n', encoding="utf-8")

    assert (
        resolve_config(tmp_path, use_repo_config=False, environment={}).analyze.model
        == ""
    )
    assert (
        resolve_config(tmp_path, explicit=inherited, environment={}).analyze.model
        == "parent-model"
    )
    child_settings = resolve_config(tmp_path, explicit=child, environment={})
    assert child_settings.analyze.model == "child-model"
    assert child_settings.analyze_model_source == "config [analyze].model"

    environment_settings = resolve_config(
        tmp_path,
        explicit=child,
        environment={"LLM_MODEL": "environment-model"},
    )
    assert environment_settings.analyze.model == "environment-model"
    assert environment_settings.analyze_model_source == "LLM_MODEL environment variable"

    cli_settings = resolve_config(
        tmp_path,
        explicit=child,
        environment={"LLM_MODEL": "environment-model"},
        cli_options=(("analyze.model", "cli-model"),),
    )
    assert cli_settings.analyze.model == "cli-model"
    assert cli_settings.analyze_model_source == "--option analyze.model"


@pytest.mark.parametrize(
    "key",
    (
        "extend",
        "allow_unknown_keys",
        "defaults.schema_version",
        "verify",
        "lint.per-file-ignores.src.module.py",
        "packets.output",
        "unknown.value",
    ),
)
def test_resolve_config_rejects_non_runtime_option_keys(
    tmp_path: Path,
    key: str,
) -> None:
    with pytest.raises(ConfigLoadError, match="not runtime-overridable"):
        resolve_config(
            tmp_path,
            use_repo_config=False,
            environment={},
            cli_options=((key, "value"),),
        )


@pytest.mark.parametrize(
    "key",
    ("", ".analyze.model", "analyze..model", "analyze.model.", '"analyze".model'),
)
def test_resolve_config_rejects_malformed_option_keys(
    tmp_path: Path,
    key: str,
) -> None:
    with pytest.raises(ConfigLoadError, match="invalid --option key"):
        resolve_config(
            tmp_path,
            use_repo_config=False,
            environment={},
            cli_options=((key, "value"),),
        )


def test_resolve_config_rejects_duplicate_and_dedicated_option_conflicts(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigLoadError, match="repeats key"):
        resolve_config(
            tmp_path,
            use_repo_config=False,
            environment={},
            cli_options=(
                ("analyze.model", "first"),
                ("analyze.model", "second"),
            ),
        )

    with pytest.raises(ConfigLoadError, match="conflicts"):
        resolve_config(
            tmp_path,
            use_repo_config=False,
            environment={},
            cli_options=(("analyze.model", "generic"),),
            cli_overrides={"analyze.model": "dedicated"},
        )


@pytest.mark.parametrize(
    ("key", "value", "attribute", "expected"),
    (
        ("analyze.model", "bare-model", "model", "bare-model"),
        ("analyze.model", '"true"', "model", "true"),
        ("analyze.model", '""', "model", ""),
        ("analyze.concurrency", "3", "concurrency", 3),
        ("analyze.temperature", "0.25", "temperature", 0.25),
        (
            "analyze.required_kinds",
            '["suppression", "section"]',
            "required_kinds",
            ("section", "suppression"),
        ),
    ),
)
def test_resolve_config_parses_generic_option_values(
    tmp_path: Path,
    key: str,
    value: str,
    attribute: str,
    expected: object,
) -> None:
    resolved = resolve_config(
        tmp_path,
        use_repo_config=False,
        environment={},
        cli_options=((key, value),),
    )

    assert getattr(resolved.analyze, attribute) == expected


def test_resolve_config_parses_boolean_and_inline_table_values(
    tmp_path: Path,
) -> None:
    resolved = resolve_config(
        tmp_path,
        use_repo_config=False,
        environment={},
        cli_options=(("check.warnings_as_errors", "true"),),
    )
    assert resolved.check.warnings_as_errors is True

    with pytest.raises(ConfigLoadError, match="analyze.model must be a string"):
        resolve_config(
            tmp_path,
            use_repo_config=False,
            environment={},
            cli_options=(("analyze.model", '{value = "model"}'),),
        )


def test_generic_diagnostic_rules_append_with_cli_provenance(
    tmp_path: Path,
) -> None:
    resolved = resolve_config(
        tmp_path,
        use_repo_config=False,
        environment={},
        cli_options=(
            (
                "diagnostics.levels",
                '[{select = ["BSC001"], level = "info"}]',
            ),
        ),
    )

    assert resolved.policy_rule_origins[-1].source == "cli"
    assert len(resolved.policy_rule_origins) == len(resolved.diagnostics.levels)


@pytest.mark.parametrize("value", ("bad\x00value", "bad\rvalue", "bad\nvalue"))
def test_resolve_config_rejects_control_characters_in_option_values(
    tmp_path: Path,
    value: str,
) -> None:
    with pytest.raises(ConfigLoadError, match="NUL, CR, or LF"):
        resolve_config(
            tmp_path,
            use_repo_config=False,
            environment={},
            cli_options=(("analyze.model", value),),
        )


def test_resolve_config_rejects_multiple_synthetic_toml_assignments(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigLoadError, match="exactly one TOML assignment"):
        resolve_config(
            tmp_path,
            use_repo_config=False,
            environment={},
            cli_options=(("analyze.model", "1\nother = 2"),),
        )


def _write_extend_chain(
    root: Path,
    count: int,
    *,
    layer_size: int | None = None,
) -> tuple[Path, ...]:
    paths = tuple(root / f"layer-{index}.toml" for index in range(count))
    for index, path in enumerate(paths):
        body = (
            f'extend = "{paths[index + 1].name}"\n'
            if index + 1 < count
            else '[profile]\nname = "backstitch-style-v1"\n'
        ).encode()
        if layer_size is not None:
            assert len(body) < layer_size
            body += b"#" + (b"x" * (layer_size - len(body) - 1))
        path.write_bytes(body)
    return paths


# --- Discovery [CFG-3] -------------------------------------------------


def test_discover_prefers_backstitch_toml_over_pyproject(tmp_path: Path) -> None:
    (tmp_path / ".backstitch.toml").write_text(
        '[profile]\nname = "backstitch-style-v1"\n', encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        '[tool.backstitch.profile]\nname = "backstitch-style-v1"\n',
        encoding="utf-8",
    )
    assert discover_config_path(tmp_path) == (tmp_path / ".backstitch.toml").resolve()


def test_discover_pyproject_when_standalone_absent(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.backstitch.profile]\nname = "backstitch-style-v1"\n',
        encoding="utf-8",
    )
    assert discover_config_path(tmp_path) == (tmp_path / "pyproject.toml").resolve()


def test_arbitrary_explicit_and_extended_names_do_not_become_discovery_names(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "parent-settings.any.toml"
    parent.write_text('[analyze]\nmodel = "parent-model"\n', encoding="utf-8")
    child = tmp_path / "selected-settings.any.toml"
    child.write_text(
        f'extend = "{parent.name}"\n[analyze]\nconcurrency = 2\n',
        encoding="utf-8",
    )

    resolved = resolve_config(
        tmp_path,
        explicit=child,
        environment={},
    )

    assert resolved.analyze.model == "parent-model"
    assert resolved.analyze.concurrency == 2
    assert discover_config_path(tmp_path) is None


def test_load_reuses_the_bounded_discovery_bytes_for_winning_pyproject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.backstitch.profile]\nname = "backstitch-style-v1"\n',
        encoding="utf-8",
    )
    real_read = settings_module._read_config_source
    reads: list[Path] = []

    def counting_read(path: Path, budget: object):  # type: ignore[no-untyped-def]
        reads.append(path)
        return real_read(path, budget)  # type: ignore[arg-type]

    monkeypatch.setattr(settings_module, "_read_config_source", counting_read)

    settings = resolve_config(tmp_path)

    assert settings.config_path == pyproject.resolve()
    assert reads == [pyproject.resolve()]


def test_discover_nearest_child_config(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    child = root / "nested" / "deep"
    child.mkdir(parents=True)
    config = root / ".backstitch.toml"
    config.write_text('[profile]\nname = "backstitch-style-v1"\n', encoding="utf-8")
    assert discover_config_path(child) == config.resolve()


def test_discover_examines_home_itself_then_stops(tmp_path: Path) -> None:
    home = tmp_path / "home"
    anchor = home / "projects" / "app"
    anchor.mkdir(parents=True)
    config = home / ".backstitch.toml"
    config.write_text('[profile]\nname = "backstitch-style-v1"\n', encoding="utf-8")
    assert discover_config_path(anchor, home=home) == config.resolve()


def test_discover_never_ascends_above_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    anchor = home / "projects" / "app"
    anchor.mkdir(parents=True)
    # Config sits ABOVE $HOME; the walk must stop at $HOME and miss it.
    (tmp_path / ".backstitch.toml").write_text(
        '[profile]\nname = "backstitch-style-v1"\n', encoding="utf-8"
    )
    assert discover_config_path(anchor, home=home) is None


def test_discover_outside_home_ignores_home_bound(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    outside = tmp_path / "outside"
    anchor = outside / "project"
    anchor.mkdir(parents=True)
    config = outside / ".backstitch.toml"
    config.write_text('[profile]\nname = "backstitch-style-v1"\n', encoding="utf-8")
    assert discover_config_path(anchor, home=home) == config.resolve()


def test_discover_skips_pyproject_without_backstitch_table(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    parent_config = tmp_path / ".backstitch.toml"
    parent_config.write_text(
        '[profile]\nname = "backstitch-style-v1"\n', encoding="utf-8"
    )
    assert discover_config_path(root) == parent_config.resolve()


def test_invalid_pyproject_during_walk_errors(tmp_path: Path) -> None:
    # [CFG-8]: a pyproject.toml that does not parse cannot be checked for a
    # [tool.backstitch] table -- never a silent skip to the next ancestor.
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text("not [ valid toml", encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        discover_config_path(root)
    assert "pyproject.toml" in str(excinfo.value)


def test_explicit_config_missing_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigLoadError) as excinfo:
        discover_config_path(tmp_path, explicit=tmp_path / "missing.toml")
    assert "missing.toml" in str(excinfo.value)


def test_explicit_config_symlink_is_rejected_without_following_it(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.toml"
    target.write_text('[profile]\nname = "backstitch-style-v1"\n', encoding="utf-8")
    link = tmp_path / "config.toml"
    link.symlink_to(target)

    with pytest.raises(ConfigLoadError, match="regular file"):
        resolve_config(tmp_path, explicit=link)


def test_discovered_config_symlink_is_rejected_without_following_it(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.toml"
    target.write_text('[profile]\nname = "backstitch-style-v1"\n', encoding="utf-8")
    (tmp_path / ".backstitch.toml").symlink_to(target)

    with pytest.raises(ConfigLoadError, match="regular file"):
        resolve_config(tmp_path)


def test_extend_config_symlink_is_rejected_without_following_it(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.toml"
    target.write_text('[profile]\nname = "backstitch-style-v1"\n', encoding="utf-8")
    (tmp_path / "parent.toml").symlink_to(target)
    child = tmp_path / "child.toml"
    child.write_text('extend = "parent.toml"\n', encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="regular file"):
        resolve_config(tmp_path, explicit=child)


def test_analyze_discovers_config_from_packets_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [CFG-3]: the discovery anchor for `analyze` is the parent directory of
    # --packets, not the process cwd. The loader anchors wherever it is told;
    # this proves anchoring at the packets parent finds that project's config
    # even when cwd is elsewhere.
    project = tmp_path / "project"
    project.mkdir()
    config = project / ".backstitch.toml"
    config.write_text('[analyze]\nmodel = "from-packets-dir"\n', encoding="utf-8")
    packets = project / "packets.jsonl"
    packets.write_text("", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    settings = resolve_config(packets.resolve().parent)
    assert settings.config_path == config.resolve()
    assert settings.analyze.model == "from-packets-dir"


# --- Loading and schema [CFG-4], [CFG-6] --------------------------------


def test_resolve_config_from_fixture_project() -> None:
    project = FIXTURES / "config_project"
    settings = resolve_config(project)
    assert settings.profile == "backstitch-style-v1"
    assert settings.profile_overrides.spec_roots == ("docs/specifications",)
    assert settings.profile_overrides.code_roots == ("src",)
    assert settings.profile_overrides.test_roots == ()
    assert settings.check.format == "json"
    assert settings.check.warnings_as_errors is True
    assert settings.analyze.model == "gpt-configured"
    # Top-level extend_exclude appends to the default exclude list CFG §6.7.
    assert settings.exclude == (*DEFAULT_EXCLUDES, "vendored/**")


def test_no_config_returns_defaults(tmp_path: Path) -> None:
    home = tmp_path / "home"
    anchor = home / "project"
    anchor.mkdir(parents=True)
    settings = resolve_config(anchor, home=home)
    assert settings.config_path is None
    assert settings.profile == "backstitch-style-v1"
    assert settings.exclude == DEFAULT_EXCLUDES
    assert settings.allow_unknown_keys is False
    assert settings.config_layers == ("packaged:backstitch/defaults.toml",)
    assert settings.diagnostics.fail_on == ("error",)
    assert settings.profile_overrides.test_roots == ("tests",)


def test_profile_test_roots_without_code_roots_retain_packaged_code_roots(
    tmp_path: Path,
) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text('[profile]\ntest_roots = ["tests/unit"]\n', encoding="utf-8")
    settings = resolve_config(tmp_path, explicit=config)
    assert settings.profile_overrides.code_roots == ("backstitch", "tests")
    assert settings.profile_overrides.test_roots == ("tests/unit",)


def test_profile_test_root_outside_code_roots_is_invalid(tmp_path: Path) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text(
        '[profile]\ncode_roots = ["pkg"]\ntest_roots = ["qa"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigLoadError, match="test root 'qa'"):
        resolve_config(tmp_path, explicit=config)


def test_profile_table_name_loads(tmp_path: Path) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text('[profile]\nname = "backstitch-style-v1"\n', encoding="utf-8")
    settings = resolve_config(tmp_path, explicit=config)
    assert settings.profile == "backstitch-style-v1"


def test_unknown_profile_name_errors(tmp_path: Path) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text('[profile]\nname = "no-such-profile"\n', encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        resolve_config(tmp_path, explicit=config)
    assert "no-such-profile" in str(excinfo.value)


def test_process_spec_globs_merged_into_meta(tmp_path: Path) -> None:
    # EXC §3.2: process_spec_globs is a v1 alias of meta_spec_globs; both
    # keys merge at load time.
    config = tmp_path / ".backstitch.toml"
    config.write_text(
        "\n".join(
            [
                "[profile]",
                'name = "backstitch-style-v1"',
                'meta_spec_globs = ["docs/specs/01-*.md"]',
                'process_spec_globs = ["docs/specs/02-*.md"]',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    settings = resolve_config(tmp_path, explicit=config)
    assert settings.profile_overrides.meta_spec_globs == (
        "docs/specs/01-*.md",
        "docs/specs/02-*.md",
    )


def test_process_spec_globs_alone_populates_meta(tmp_path: Path) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text(
        '[profile]\nprocess_spec_globs = ["docs/specs/02-*.md"]\n',
        encoding="utf-8",
    )
    settings = resolve_config(tmp_path, explicit=config)
    assert settings.profile_overrides.meta_spec_globs == ("docs/specs/02-*.md",)


def test_packets_output_is_parsed(tmp_path: Path) -> None:
    # CFG §6.4: packets.output is reserved in v1 but must be stored, not
    # silently dead schema.
    config = tmp_path / ".backstitch.toml"
    config.write_text('[packets]\noutput = "out/packets.jsonl"\n', encoding="utf-8")
    settings = resolve_config(tmp_path, explicit=config)
    assert settings.packets.output == str(
        (tmp_path / "out" / "packets.jsonl").resolve()
    )


# --- Strict unknown keys [CFG-8] ----------------------------------------


def test_unknown_key_exits_two(tmp_path: Path) -> None:
    # Loader-level contract behind CLI exit 2: unknown key -> ConfigLoadError
    # naming key and file; the CLI maps ConfigLoadError to exit 2 (Task 12/13).
    config = tmp_path / ".backstitch.toml"
    config.write_text(
        'unknown_key = true\n[profile]\nname = "backstitch-style-v1"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigLoadError) as excinfo:
        resolve_config(tmp_path, explicit=config)
    message = str(excinfo.value)
    assert "unknown_key" in message
    assert ".backstitch.toml" in message


def test_unknown_nested_key_exits_two(tmp_path: Path) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text("[check]\ncolor = true\n", encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        resolve_config(tmp_path, explicit=config)
    assert "check.color" in str(excinfo.value)


@pytest.mark.parametrize(
    "table_name", ["check", "packets", "analyze", "target_roots", "lint"]
)
def test_known_table_scalar_reports_type_error(
    tmp_path: Path,
    table_name: str,
) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text(f'{table_name} = "not-a-table"\n', encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        resolve_config(tmp_path, explicit=config)
    message = str(excinfo.value)
    assert f"[{table_name}] must be a table" in message
    assert "unknown config key" not in message


def test_top_level_profile_string_exits_two(tmp_path: Path) -> None:
    # CFG §6.1: the only profile-name spelling is [profile].name; a
    # top-level profile string is an unknown key.
    config = tmp_path / ".backstitch.toml"
    config.write_text('profile = "backstitch-style-v1"\n', encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        resolve_config(tmp_path, explicit=config)
    assert "profile" in str(excinfo.value)


def test_exclude_under_profile_is_unknown_key(tmp_path: Path) -> None:
    # CFG §6.7: exclude/extend_exclude are top-level scan-boundary keys,
    # not profile fields; writing one under [profile] errors under strict
    # load rather than silently doing nothing.
    config = tmp_path / ".backstitch.toml"
    config.write_text(
        '[profile]\nextend_exclude = ["tests/fixtures/**"]\n', encoding="utf-8"
    )
    with pytest.raises(ConfigLoadError) as excinfo:
        resolve_config(tmp_path, explicit=config)
    assert "extend_exclude" in str(excinfo.value)


def test_warn_unused_keys_is_itself_unknown(tmp_path: Path) -> None:
    # The implement-branch warn_unused_keys switch was removed; only
    # allow_unknown_keys exists ([CFG-8]).
    config = tmp_path / ".backstitch.toml"
    config.write_text("warn_unused_keys = true\n", encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        resolve_config(tmp_path, explicit=config)
    assert "warn_unused_keys" in str(excinfo.value)


def test_allow_unknown_keys_downgrades_to_stderr_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text(
        "allow_unknown_keys = true\nunknown_key = true\n"
        '[profile]\nname = "backstitch-style-v1"\n',
        encoding="utf-8",
    )
    settings = resolve_config(tmp_path, explicit=config)
    assert settings.profile == "backstitch-style-v1"
    assert settings.allow_unknown_keys is True
    captured = capsys.readouterr()
    assert "unknown_key" in captured.err


def test_allow_unknown_keys_never_masks_type_errors(tmp_path: Path) -> None:
    # [CFG-8]: the escape hatch must never suppress type errors on known keys.
    config = tmp_path / ".backstitch.toml"
    config.write_text(
        "allow_unknown_keys = true\n[analyze]\nconcurrency = 0\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigLoadError) as excinfo:
        resolve_config(tmp_path, explicit=config)
    assert "concurrency" in str(excinfo.value)


def test_invalid_check_format_errors(tmp_path: Path) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text('[check]\nformat = "yaml"\n', encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        resolve_config(tmp_path, explicit=config)
    assert "format" in str(excinfo.value)


def test_invalid_toml_errors_naming_file(tmp_path: Path) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text("not [ valid toml", encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        resolve_config(tmp_path, explicit=config)
    assert ".backstitch.toml" in str(excinfo.value)


# --- extend merge CFG §6.8 ---------------------------------------------


def test_extend_merge_overrides_parent(tmp_path: Path) -> None:
    base = tmp_path / "base.toml"
    base.write_text(
        "\n".join(
            [
                "[profile]",
                'spec_roots = ["docs/base"]',
                "[analyze]",
                'model = "gpt-base"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    child = tmp_path / "child.toml"
    child.write_text(
        'extend = "base.toml"\n[analyze]\nmodel = "gpt-child"\n',
        encoding="utf-8",
    )
    settings = resolve_config(tmp_path, explicit=child)
    assert settings.profile_overrides.spec_roots == ("docs/base",)
    assert settings.analyze.model == "gpt-child"


def test_extend_code_roots_without_test_roots_resets_parent_test_roots(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.toml"
    base.write_text(
        '[profile]\ncode_roots = ["src", "qa"]\ntest_roots = ["qa"]\n',
        encoding="utf-8",
    )
    child = tmp_path / "child.toml"
    child.write_text(
        'extend = "base.toml"\n[profile]\ncode_roots = ["pkg"]\n',
        encoding="utf-8",
    )
    settings = resolve_config(tmp_path, explicit=child)
    assert settings.profile_overrides.code_roots == ("pkg",)
    assert settings.profile_overrides.test_roots == ()


def test_diagnostics_levels_append_across_extend(tmp_path: Path) -> None:
    base = tmp_path / "base.toml"
    base.write_text(
        "\n".join(
            [
                "[[diagnostics.levels]]",
                'select = ["PYTHON_SYNTAX_ERROR"]',
                'level = "info"',
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
                "[[diagnostics.levels]]",
                'select = ["PYTHON_SYNTAX_ERROR"]',
                'level = "error"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    settings = resolve_config(tmp_path, explicit=child)
    assert settings.diagnostics.levels[-2].level == "info"
    assert settings.diagnostics.levels[-1].level == "error"


def test_diagnostics_rejects_off_in_fail_on(tmp_path: Path) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text('[diagnostics]\nfail_on = ["off"]\n', encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        resolve_config(tmp_path, explicit=config)
    assert "fail_on" in str(excinfo.value)


def test_repo_config_cannot_define_diagnostic_registry(tmp_path: Path) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text(
        "\n".join(
            [
                "[diagnostics.registry.MY_CODE]",
                'short = "BST999"',
                'status = "implemented"',
                'summary = "not allowed here"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigLoadError) as excinfo:
        resolve_config(tmp_path, explicit=config)
    assert "diagnostics.registry" in str(excinfo.value)


def test_extend_resolves_relative_to_containing_file(tmp_path: Path) -> None:
    shared = tmp_path / "shared" / "base.toml"
    shared.parent.mkdir()
    shared.write_text('[analyze]\nmodel = "gpt-shared"\n', encoding="utf-8")
    nested = tmp_path / "project" / "nested"
    nested.mkdir(parents=True)
    child = nested / ".backstitch.toml"
    child.write_text('extend = "../../shared/base.toml"\n', encoding="utf-8")
    settings = resolve_config(nested, explicit=child)
    assert settings.analyze.model == "gpt-shared"


def test_extend_cycle_errors(tmp_path: Path) -> None:
    a = tmp_path / "a.toml"
    b = tmp_path / "b.toml"
    a.write_text('extend = "b.toml"\n', encoding="utf-8")
    b.write_text('extend = "a.toml"\n', encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        resolve_config(tmp_path, explicit=a)
    assert "extend" in str(excinfo.value).lower()


def test_extend_missing_target_errors(tmp_path: Path) -> None:
    child = tmp_path / "child.toml"
    child.write_text('extend = "missing.toml"\n', encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        resolve_config(tmp_path, explicit=child)
    assert "missing.toml" in str(excinfo.value)


def test_extend_chain_retains_exact_identities_and_reads_each_layer_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "parent.toml"
    parent_bytes = b'[analyze]\nmodel = "parent"\n'
    parent.write_bytes(parent_bytes)
    child = tmp_path / "child.toml"
    child_bytes = b'extend = "parent.toml"\n[analyze]\nmodel = "child"\n'
    child.write_bytes(child_bytes)
    expected_paths = {parent.resolve(), child.resolve()}
    read_counts = dict.fromkeys(expected_paths, 0)
    real_read = repository_snapshot.read_regular_nofollow

    def counting_read(root: Path, relative: str, **kwargs: object) -> object:
        path = (root / relative).resolve()
        if path in expected_paths:
            read_counts[path] += 1
        return real_read(root, relative, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(repository_snapshot, "read_regular_nofollow", counting_read)

    settings = resolve_config(tmp_path, explicit=child)

    assert read_counts == {parent.resolve(): 1, child.resolve(): 1}
    assert [
        (item.path, item.raw_sha256) for item in settings.config_layer_identities
    ] == [
        (str(parent.resolve()), hashlib.sha256(parent_bytes).hexdigest()),
        (str(child.resolve()), hashlib.sha256(child_bytes).hexdigest()),
    ]


def test_config_chain_file_count_limit_accepts_64_and_rejects_65(
    tmp_path: Path,
) -> None:
    paths = _write_extend_chain(tmp_path, 65)

    assert resolve_config(tmp_path, explicit=paths[1]).profile == "backstitch-style-v1"
    with pytest.raises(ConfigLoadError, match="64 config files"):
        resolve_config(tmp_path, explicit=paths[0])


def test_config_file_byte_limit_accepts_exact_and_rejects_overflow(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config.toml"
    body = b'[profile]\nname = "backstitch-style-v1"\n'
    exact = body + b"#" + (b"x" * (1_000_000 - len(body) - 1))
    config.write_bytes(exact)

    assert resolve_config(tmp_path, explicit=config).profile == "backstitch-style-v1"

    config.write_bytes(exact + b"x")
    with pytest.raises(ConfigLoadError, match="1,000,000 raw bytes"):
        resolve_config(tmp_path, explicit=config)


def test_config_chain_byte_limit_accepts_exact_and_rejects_overflow(
    tmp_path: Path,
) -> None:
    accepted = _write_extend_chain(tmp_path, 5, layer_size=1_000_000)

    assert resolve_config(tmp_path, explicit=accepted[0]).profile == (
        "backstitch-style-v1"
    )

    overflow_root = tmp_path / "overflow"
    overflow_root.mkdir()
    overflow = _write_extend_chain(overflow_root, 6, layer_size=900_000)
    with pytest.raises(ConfigLoadError, match="5,000,000 raw bytes"):
        resolve_config(tmp_path, explicit=overflow[0])


def test_unreadable_config_is_a_config_load_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "config.toml"
    config.write_text('[profile]\nname = "backstitch-style-v1"\n', encoding="utf-8")
    real_read = repository_snapshot.read_regular_nofollow

    def unreadable_read(root: Path, relative: str, **kwargs: object) -> object:
        if (root / relative).resolve() == config.resolve():
            raise repository_snapshot.StableReadError("denied")
        return real_read(root, relative, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(repository_snapshot, "read_regular_nofollow", unreadable_read)

    with pytest.raises(ConfigLoadError, match="could not read config"):
        resolve_config(tmp_path, explicit=config)


def test_config_changed_during_its_read_is_a_config_load_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "config.toml"
    config.write_text('[profile]\nname = "backstitch-style-v1"\n', encoding="utf-8")
    real_read = repository_snapshot.read_regular_nofollow

    def changed_read(root: Path, relative: str, **kwargs: object) -> object:
        if (root / relative).resolve() == config.resolve():
            raise repository_snapshot.StableReadError(
                "file changed during its bounded read"
            )
        return real_read(root, relative, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(repository_snapshot, "read_regular_nofollow", changed_read)

    with pytest.raises(ConfigLoadError, match="changed during its bounded read"):
        resolve_config(tmp_path, explicit=config)


# --- Path expansion CFG §4.3 -------------------------------------------


def test_expand_tilde_before_relative_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    base = tmp_path / "config"
    base.mkdir()
    value = expand_path_value("~/project", base_dir=base)
    assert value == str((home / "project").resolve())


def test_expand_absolute_env_without_double_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ABS_ROOT", str(tmp_path / "abs"))
    base = tmp_path / "config"
    base.mkdir()
    value = expand_path_value("$ABS_ROOT/child", base_dir=base)
    assert value == str((tmp_path / "abs" / "child").resolve())


def test_expand_relative_env_resolves_against_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REL_PART", "sub")
    value = expand_path_value("${REL_PART}/child", base_dir=tmp_path)
    assert value == str((tmp_path / "sub" / "child").resolve())


# --- Scan-boundary excludes CFG §6.7 -----------------------------------


def test_exclude_replaces_defaults(tmp_path: Path) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text('exclude = ["only-this/**"]\n', encoding="utf-8")
    settings = resolve_config(tmp_path, explicit=config)
    assert settings.exclude == ("only-this/**",)


def test_is_excluded_matches_directory_segments() -> None:
    assert is_excluded(".venv/lib/python.py", (".venv",))
    assert is_excluded("src/module.py", (".venv",)) is False
    assert is_excluded("tests/fixtures/x/y.md", ("tests/fixtures/**",))
