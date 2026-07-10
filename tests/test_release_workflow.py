from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"


def _workflow_text(path: str) -> str:
    return (WORKFLOW_DIR / path).read_text(encoding="utf-8")


def _active_workflow_text(path: str) -> str:
    lines: list[str] = []
    for raw in _workflow_text(path).splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(raw.rstrip())
    return "\n".join(lines)


def _index(text: str, needle: str) -> int:
    position = text.find(needle)
    assert position != -1, f"missing expected workflow text: {needle}"
    return position


def test_ci_checks_release_helper_format_and_types() -> None:
    workflow = _workflow_text("ci.yml")

    assert workflow.count("uses: astral-sh/setup-uv@v7") == 3
    assert workflow.count("enable-cache: false") == 3
    assert "uv run ruff format --check" in workflow
    assert "tests\n" in workflow
    assert (
        "uv run mypy backstitch bin/release.py tests --config-file pyproject.toml"
        in workflow
    )
    assert "uv run backstitch check --repo-root ." in workflow


def test_local_pytest_enables_live_while_ci_explicitly_disables_it() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        pytest_options = tomllib.load(handle)["tool"]["pytest"]["ini_options"]
    assert pytest_options["run_live_llm"] is True

    workflow = _workflow_text("ci.yml")
    assert '-m "not live_llm"' in workflow
    assert (
        "env -u BACKSTITCH_LIVE_LLM uv run pytest "
        "tests/live/test_live_llm.py -q -o run_live_llm=false" in workflow
    )
    assert "grep -Eq 'SKIPPED \\[1\\]'" in workflow


def test_ci_live_llm_requires_explicit_repository_opt_in() -> None:
    workflow = _workflow_text("ci.yml")
    live_section = workflow.split("  live-llm:", 1)[1]

    assert "name: live LLM" in live_section
    assert "vars.BACKSTITCH_CI_LIVE_LLM == '1'" in live_section
    assert "github.ref == 'refs/heads/main'" in live_section
    assert "github.event_name == 'push'" in live_section
    assert "github.event_name == 'workflow_dispatch'" in live_section
    assert "github.event_name == 'pull_request'" not in live_section
    assert "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}" in live_section
    # The cloud job must pin the kind so an environment-leaked
    # BACKSTITCH_LIVE_LLM_KIND=local cannot reroute it to the Ollama lane
    # (bin/release.py pins the same value; see test_release_script.py).
    assert "BACKSTITCH_LIVE_LLM_KIND: openai" in live_section
    assert 'if [ -z "${OPENAI_API_KEY}" ]; then' in live_section
    assert "skipping live LLM tests without failure" in live_section
    assert "uv run pytest tests/live/test_live_llm.py -q" in live_section
    assert "permissions:\n  contents: read" in workflow


def test_local_llm_workflow_is_separate_and_guarded() -> None:
    workflow = _workflow_text("local-llm.yml")
    active = _active_workflow_text("local-llm.yml")

    assert "name: local-llm" in active
    assert "workflow_dispatch:" in active
    # Graduated to run on push to main so the release commit has a green
    # local-llm run for the release gate to require. Still NOT on
    # pull_request: fork-PR exposure is a separate threat-model-gated step.
    assert "push:" in active
    assert "branches: [main]" in active
    assert "pull_request:" not in active
    assert "permissions:" in active
    assert "contents: read" in active
    assert "concurrency:" in active
    assert "group: local-llm-${{ github.ref }}" in active
    assert "cancel-in-progress: false" in active
    assert "2 vCPU / 8 GB" in workflow

    assert "uses: astral-sh/setup-uv@v7" in active
    assert 'python-version: "3.11"' in active
    assert "enable-cache: false" in active
    assert "ollama/ollama@sha256:" in active
    assert "ollama/ollama:latest" not in active
    assert "timeout-minutes: 20" in active
    assert "timeout-minutes: 15" in active
    assert "OLLAMA_CONTEXT_LENGTH:" in active
    assert "OLLAMA_NUM_PREDICT:" in active
    assert "PARAMETER num_ctx ${OLLAMA_CONTEXT_LENGTH}" in workflow
    assert "PARAMETER num_predict ${OLLAMA_NUM_PREDICT}" in workflow
    assert "BACKSTITCH_LOCAL_LLM_BASE_MODEL:" in active
    assert "BACKSTITCH_LOCAL_LLM_BASE_MODEL: llama3.2:3b" in active
    assert "BACKSTITCH_LOCAL_LLM_SERVED_MODEL: backstitch-local-model:latest" in active
    # Deterministic-output tuning from the local bake-off: temperature 0 in the
    # Modelfile, proven server-side alongside num_ctx/num_predict.
    assert "PARAMETER temperature 0" in workflow
    assert 'grep -Eq "^temperature[[:space:]]+0([[:space:]]|$)"' in workflow
    assert "BACKSTITCH_LIVE_LLM_KIND: local" in active
    assert "BACKSTITCH_LOCAL_LLM_ALLOW_NONLOCAL" not in active
    assert "127.0.0.1:11434:11434" in active

    assert "id: restore" in active
    assert "id: pull" in active
    assert "id: model-poll" in active
    assert "restore-keys" not in active
    assert active.count("path: ${{ env.OLLAMA_CACHE_DIR }}") == 2
    assert "continue-on-error: true" in active
    assert (
        "if: ${{ !cancelled() && steps.pull.outcome == 'success' && "
        "steps.model-poll.outcome == 'success' && "
        "steps.restore.outputs.cache-hit != 'true' && "
        "github.ref == 'refs/heads/main' }}"
    ) in active

    # A failed save (permissions/unreadable files) must fail the job on
    # trusted runs instead of hiding behind continue-on-error; "key already
    # exists" does not produce a failure outcome in actions/cache/save@v5.
    assert "if: ${{ !cancelled() && steps.save.outcome == 'failure' }}" in active
    # The context-bound verification greps must be anchored at both ends so
    # neither a prefixed key (foo_num_ctx) nor a longer value (40960 vs 4096)
    # can satisfy the check.
    assert (
        'grep -Eq "^num_ctx[[:space:]]+${OLLAMA_CONTEXT_LENGTH}([[:space:]]|$)"'
        in workflow
    )
    assert (
        'grep -Eq "^num_predict[[:space:]]+${OLLAMA_NUM_PREDICT}([[:space:]]|$)"'
        in workflow
    )
    # Per-run weight provenance: manifest checksums are the only trace of what
    # actually ran (the cache key is tag-based and tags are mutable), and the
    # evidence must be non-empty, not best-effort.
    assert "sha256sum" in active
    assert 'test -n "${manifests}"' in workflow

    test_position = _index(active, "Run local live LLM tests")
    chown_position = _index(active, "Normalize Ollama cache ownership")
    save_position = _index(active, "Save Ollama model cache")
    assert test_position < chown_position < save_position
    save_check_position = _index(active, "Fail on broken cache save")
    assert save_position < save_check_position


def test_release_gate_waits_for_ci_before_publishing() -> None:
    workflow = _workflow_text("release-gate.yml")

    require_position = workflow.index("Require CI and local-llm workflows to be green")
    publish_position = workflow.index("publish-to-pypi:")

    assert require_position < publish_position
    assert '--workflow "CI"' in workflow
    # The Docker/Ollama local-llm lane (Linux-only) must be green on the
    # release commit before publishing, following simplebroker's model of
    # requiring the service-backed test workflow by name.
    assert '--workflow "local-llm"' in workflow
    assert "verify-tag-current:" in workflow
    assert "expected: ${EXPECTED_SHA}" in workflow


def test_release_gate_verifies_tag_matches_package_version() -> None:
    workflow = _workflow_text("release-gate.yml")

    assert "Verify tag matches package version" in workflow
    assert 'TAG_VERSION="${TAG_NAME#v}"' in workflow
    assert 'PACKAGE_PYPROJECT="${PACKAGE_DIR}/pyproject.toml"' in workflow
    assert "tomllib.load" in workflow
    assert "tag {tag} != pyproject version {package_version}" in workflow


def test_release_gate_uses_trusted_publishing_and_attestations() -> None:
    workflow = _workflow_text("release-gate.yml")

    assert "environment:" in workflow
    assert "name: pypi" in workflow
    assert "uses: pypa/gh-action-pypi-publish@" in workflow
    assert "uses: actions/attest@" in workflow
    assert "attestations: write" in workflow
    assert "artifact-metadata: write" in workflow
    assert "id-token: write" in workflow


def test_release_gate_builds_with_backstitch_python_version() -> None:
    workflow = _workflow_text("release-gate.yml")

    assert "uses: astral-sh/setup-uv@v7" in workflow
    assert 'python-version: "3.11"' in workflow
    assert "enable-cache: false" in workflow
    assert "uv build" in workflow


def test_github_release_uploads_only_distributions_and_attestation() -> None:
    workflow = _workflow_text("release-gate.yml")
    github_release_section = workflow.split("  github-release:", 1)[1]

    assert "dist/*.tar.gz" in github_release_section
    assert "dist/*.whl" in github_release_section
    assert "attestations/*.sigstore.json" in github_release_section
    assert "dist/*\n" not in github_release_section
    assert "subject-path" not in github_release_section
