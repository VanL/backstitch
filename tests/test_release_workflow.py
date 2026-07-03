from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"


def _workflow_text(path: str) -> str:
    return (WORKFLOW_DIR / path).read_text(encoding="utf-8")


def test_ci_checks_release_helper_format_and_types() -> None:
    workflow = _workflow_text("ci.yml")

    assert "uv run ruff format --check" in workflow
    assert "tests/test_release_workflow_gate.py" in workflow
    assert (
        "uv run mypy backstitch bin/release.py --config-file pyproject.toml" in workflow
    )
    assert "uv run backstitch check --repo-root ." in workflow


def test_ci_runs_live_llm_when_repository_secret_is_available() -> None:
    workflow = _workflow_text("ci.yml")
    live_section = workflow.split("  live-llm:", 1)[1]

    assert "name: live LLM" in live_section
    assert "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}" in live_section
    assert 'if [ -z "${OPENAI_API_KEY}" ]; then' in live_section
    assert "skipping live LLM tests without failure" in live_section
    assert "uv run pytest tests/live/test_live_llm.py -q" in live_section
    assert "if: ${{ github.event_name" not in live_section


def test_release_gate_waits_for_ci_before_publishing() -> None:
    workflow = _workflow_text("release-gate.yml")

    require_position = workflow.index("Require CI workflow to be green")
    publish_position = workflow.index("publish-to-pypi:")

    assert require_position < publish_position
    assert '--workflow "CI"' in workflow
    assert "verify-tag-current:" in workflow
    assert "expected: ${EXPECTED_SHA}" in workflow


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

    assert "uses: astral-sh/setup-uv@v5" in workflow
    assert 'python-version: "3.14"' in workflow
    assert "uv build" in workflow


def test_github_release_uploads_only_distributions_and_attestation() -> None:
    workflow = _workflow_text("release-gate.yml")
    github_release_section = workflow.split("  github-release:", 1)[1]

    assert "dist/*.tar.gz" in github_release_section
    assert "dist/*.whl" in github_release_section
    assert "attestations/*.sigstore.json" in github_release_section
    assert "dist/*\n" not in github_release_section
    assert "subject-path" not in github_release_section
