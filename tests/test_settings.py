"""Configuration loader tests: discovery, extend, strict unknown keys.

Spec: docs/specs/03-backstitch-configuration.md [CFG-3], [CFG-4], [CFG-6],
[CFG-8], [CFG-9]
Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-3], [EXC-6]
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backstitch.settings import (
    DEFAULT_EXCLUDES,
    ConfigLoadError,
    discover_config_path,
    expand_path_value,
    is_excluded,
    load_settings,
)

FIXTURES = Path(__file__).parent / "fixtures"


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
    settings = load_settings(packets.resolve().parent)
    assert settings.config_path == config.resolve()
    assert settings.analyze.model == "from-packets-dir"


# --- Loading and schema [CFG-4], [CFG-6] --------------------------------


def test_load_settings_from_fixture_project() -> None:
    project = FIXTURES / "config_project"
    settings = load_settings(project)
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
    settings = load_settings(anchor, home=home)
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
    settings = load_settings(tmp_path, explicit=config)
    assert settings.profile_overrides.code_roots == ("backstitch", "tests")
    assert settings.profile_overrides.test_roots == ("tests/unit",)


def test_profile_test_root_outside_code_roots_is_invalid(tmp_path: Path) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text(
        '[profile]\ncode_roots = ["pkg"]\ntest_roots = ["qa"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigLoadError, match="test root 'qa'"):
        load_settings(tmp_path, explicit=config)


def test_profile_table_name_loads(tmp_path: Path) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text('[profile]\nname = "backstitch-style-v1"\n', encoding="utf-8")
    settings = load_settings(tmp_path, explicit=config)
    assert settings.profile == "backstitch-style-v1"


def test_unknown_profile_name_errors(tmp_path: Path) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text('[profile]\nname = "no-such-profile"\n', encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        load_settings(tmp_path, explicit=config)
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
    settings = load_settings(tmp_path, explicit=config)
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
    settings = load_settings(tmp_path, explicit=config)
    assert settings.profile_overrides.meta_spec_globs == ("docs/specs/02-*.md",)


def test_packets_output_is_parsed(tmp_path: Path) -> None:
    # CFG §6.4: packets.output is reserved in v1 but must be stored, not
    # silently dead schema.
    config = tmp_path / ".backstitch.toml"
    config.write_text('[packets]\noutput = "out/packets.jsonl"\n', encoding="utf-8")
    settings = load_settings(tmp_path, explicit=config)
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
        load_settings(tmp_path, explicit=config)
    message = str(excinfo.value)
    assert "unknown_key" in message
    assert ".backstitch.toml" in message


def test_unknown_nested_key_exits_two(tmp_path: Path) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text("[check]\ncolor = true\n", encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        load_settings(tmp_path, explicit=config)
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
        load_settings(tmp_path, explicit=config)
    message = str(excinfo.value)
    assert f"[{table_name}] must be a table" in message
    assert "unknown config key" not in message


def test_top_level_profile_string_exits_two(tmp_path: Path) -> None:
    # CFG §6.1: the only profile-name spelling is [profile].name; a
    # top-level profile string is an unknown key.
    config = tmp_path / ".backstitch.toml"
    config.write_text('profile = "backstitch-style-v1"\n', encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        load_settings(tmp_path, explicit=config)
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
        load_settings(tmp_path, explicit=config)
    assert "extend_exclude" in str(excinfo.value)


def test_warn_unused_keys_is_itself_unknown(tmp_path: Path) -> None:
    # The implement-branch warn_unused_keys switch was removed; only
    # allow_unknown_keys exists ([CFG-8]).
    config = tmp_path / ".backstitch.toml"
    config.write_text("warn_unused_keys = true\n", encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        load_settings(tmp_path, explicit=config)
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
    settings = load_settings(tmp_path, explicit=config)
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
        load_settings(tmp_path, explicit=config)
    assert "concurrency" in str(excinfo.value)


def test_invalid_check_format_errors(tmp_path: Path) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text('[check]\nformat = "yaml"\n', encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        load_settings(tmp_path, explicit=config)
    assert "format" in str(excinfo.value)


def test_invalid_toml_errors_naming_file(tmp_path: Path) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text("not [ valid toml", encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        load_settings(tmp_path, explicit=config)
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
    settings = load_settings(tmp_path, explicit=child)
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
    settings = load_settings(tmp_path, explicit=child)
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
    settings = load_settings(tmp_path, explicit=child)
    assert settings.diagnostics.levels[-2].level == "info"
    assert settings.diagnostics.levels[-1].level == "error"


def test_diagnostics_rejects_off_in_fail_on(tmp_path: Path) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text('[diagnostics]\nfail_on = ["off"]\n', encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        load_settings(tmp_path, explicit=config)
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
        load_settings(tmp_path, explicit=config)
    assert "diagnostics.registry" in str(excinfo.value)


def test_extend_resolves_relative_to_containing_file(tmp_path: Path) -> None:
    shared = tmp_path / "shared" / "base.toml"
    shared.parent.mkdir()
    shared.write_text('[analyze]\nmodel = "gpt-shared"\n', encoding="utf-8")
    nested = tmp_path / "project" / "nested"
    nested.mkdir(parents=True)
    child = nested / ".backstitch.toml"
    child.write_text('extend = "../../shared/base.toml"\n', encoding="utf-8")
    settings = load_settings(nested, explicit=child)
    assert settings.analyze.model == "gpt-shared"


def test_extend_cycle_errors(tmp_path: Path) -> None:
    a = tmp_path / "a.toml"
    b = tmp_path / "b.toml"
    a.write_text('extend = "b.toml"\n', encoding="utf-8")
    b.write_text('extend = "a.toml"\n', encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        load_settings(tmp_path, explicit=a)
    assert "extend" in str(excinfo.value).lower()


def test_extend_missing_target_errors(tmp_path: Path) -> None:
    child = tmp_path / "child.toml"
    child.write_text('extend = "missing.toml"\n', encoding="utf-8")
    with pytest.raises(ConfigLoadError) as excinfo:
        load_settings(tmp_path, explicit=child)
    assert "missing.toml" in str(excinfo.value)


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
    settings = load_settings(tmp_path, explicit=config)
    assert settings.exclude == ("only-this/**",)


def test_is_excluded_matches_directory_segments() -> None:
    assert is_excluded(".venv/lib/python.py", (".venv",))
    assert is_excluded("src/module.py", (".venv",)) is False
    assert is_excluded("tests/fixtures/x/y.md", ("tests/fixtures/**",))
