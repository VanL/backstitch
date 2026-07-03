"""Optional live LLM smoke and contract test ([SC-7] live path).

Spec: docs/specs/02-backstitch-core.md [SC-7]
Plan: docs/plans/2026-07-03-live-llm-tests-plan.md

Skipped unless ``BACKSTITCH_LIVE_LLM=1``. When enabled it drives the real CLI
(``packets`` -> ``analyze`` -> ``check`` -> ``summarize-analysis``) over this
repository's own specs, calling a real provider through the production
``default_adapter``. It asserts structured contracts and command behavior --
never model wording or classification.

Exit codes here prove the command path and artifact health, not model success:
``analyze`` exits 0 on partial failure ([SC-7]) and ``summarize-analysis`` exits
0 regardless of analysis-row quality. The load-bearing model assertion is that
no result row carries an ``error`` field, because ``analysis_llm._error_record``
intentionally emits a schema-valid ``ambiguous`` row for a contained
provider/model failure.
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backstitch.analysis_results import load_analysis_results, validate_analysis_row

# Function-level skip (not a module-level `pytest.skip(allow_module_level=True)`)
# so the test is COLLECTED and reported as skipped. A module-level skip makes
# `pytest tests/live/test_live_llm.py` collect nothing and exit 5 (no tests
# ran), which would fail the hermetic CI step that proves the gate skips.
# Collection stays hermetic: `import llm` lives inside the test body, not here.
pytestmark = [
    pytest.mark.live_llm,
    pytest.mark.skipif(
        os.environ.get("BACKSTITCH_LIVE_LLM") != "1",
        reason="live LLM tests are opt-in; set BACKSTITCH_LIVE_LLM=1 to run",
    ),
]

# Canonical default model. MUST stay byte-identical to
# DEFAULT_BACKSTITCH_LIVE_LLM_MODEL in .github/workflows/ci.yml -- treat the two
# copies as one value. Re-check `uv run llm models list` and OpenAI's model docs
# before changing it; availability changes faster than this repo.
DEFAULT_BACKSTITCH_LIVE_LLM_MODEL = "gpt-5.4-mini"

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_SPEC = "docs/specs/02-backstitch-core.md"
DEFAULT_LIVE_PACKETS = 1
MAX_LIVE_PACKETS = 5


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the CLI as a subprocess using the running interpreter.

    Uses ``sys.executable -m backstitch`` so the subprocess shares this test's
    venv, ``backstitch``, and ``llm`` install rather than whatever bare
    ``python`` resolves to on PATH.
    """

    return subprocess.run(
        [sys.executable, "-m", "backstitch", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )


def _assert_no_traceback(result: subprocess.CompletedProcess[str], label: str) -> None:
    assert "Traceback (most recent call last)" not in result.stderr, (
        f"{label} printed a traceback:\n{result.stderr}"
    )


def _resolve_live_model() -> str:
    import llm

    model_name = os.environ.get("LLM_MODEL") or DEFAULT_BACKSTITCH_LIVE_LLM_MODEL
    try:
        model = llm.get_model(model_name)
    except llm.UnknownModelError as exc:
        pytest.fail(
            f"live model {model_name!r} is not registered in llm; set LLM_MODEL "
            f"or update DEFAULT_BACKSTITCH_LIVE_LLM_MODEL ({exc})"
        )
    # Provider-general credential preflight driven by the model's own declared
    # key requirement -- do not guess a provider. A keyless (local) model needs
    # no credential; the plan asks that new providers extend this explicitly.
    needs_key = getattr(model, "needs_key", None)
    if needs_key:
        env_var = getattr(model, "key_env_var", None) or ""
        key = llm.get_key(key_alias=needs_key, env_var=env_var)
        if not key:
            hint = f" or `{env_var}`" if env_var else ""
            pytest.fail(
                f"live gate enabled but no credential for provider key "
                f"{needs_key!r}; store one with `llm keys set {needs_key}`{hint}"
            )
    return model_name


def _select_live_packets(all_packets_text: str) -> list[dict[str, object]]:
    """Deterministically choose the bounded live subset from generated packets.

    There is no packet-filter subcommand and calling ``analyze_packets``
    directly is forbidden, so the filtering lives here: keep packets from the
    live spec whose owners include a semantic-analysis module, then prefer the
    smallest (fewest bytes) for reproducibility and lower model-format flake.
    """

    candidates: list[tuple[int, dict[str, object]]] = []
    for index, raw in enumerate(all_packets_text.splitlines()):
        raw = raw.strip()
        if not raw:
            continue
        packet = json.loads(raw)
        if packet.get("spec_path") != LIVE_SPEC:
            continue
        owner_paths = [
            str(owner.get("path", "")) for owner in packet.get("owners", [])
        ]
        if any(
            path == "backstitch/cli.py"
            or fnmatch.fnmatch(path, "backstitch/analysis_*.py")
            for path in owner_paths
        ):
            candidates.append((index, packet))
    candidates.sort(
        key=lambda item: (len(json.dumps(item[1])), str(item[1]["packet_id"]), item[0])
    )
    return [packet for _, packet in candidates[:DEFAULT_LIVE_PACKETS]]


def test_live_llm_analysis_contract(tmp_path: Path) -> None:
    live_model = _resolve_live_model()

    all_packets = tmp_path / "all-packets.jsonl"
    live_packets = tmp_path / "live-packets.jsonl"
    analysis = tmp_path / "analysis.jsonl"
    report = tmp_path / "report.json"

    # 1. Generate the full packet corpus through the real CLI.
    gen = _run_cli(
        "packets", "--repo-root", ".", "--output", str(all_packets)
    )
    _assert_no_traceback(gen, "packets")
    assert gen.returncode == 0, gen.stderr
    all_text = all_packets.read_text(encoding="utf-8")
    assert all_text.strip(), "packets produced empty output"

    # 2. Build the bounded live subset in-process and write it out.
    subset = _select_live_packets(all_text)
    assert subset, (
        f"no packets from {LIVE_SPEC} own a semantic-analysis module; the "
        "dogfood corpus stopped exercising the live semantic path"
    )
    assert len(subset) <= MAX_LIVE_PACKETS
    expected_packet_ids = {str(packet["packet_id"]) for packet in subset}
    live_packets.write_text(
        "".join(json.dumps(packet) + "\n" for packet in subset), encoding="utf-8"
    )

    # 3. Real provider call through the public analyze command.
    ana = _run_cli(
        "analyze",
        "--packets", str(live_packets),
        "--model", live_model,
        "--concurrency", "1",
        "--no-config",
        "--output", str(analysis),
    )
    _assert_no_traceback(ana, "analyze")
    assert ana.returncode == 0, ana.stderr

    # 4. Deterministic report over the full repo (committed config, not
    #    --no-config) so summarize can resolve subset packet IDs against the
    #    same report surface a normal user produces.
    chk = _run_cli(
        "check", "--repo-root", ".", "--format", "json", "--output", str(report)
    )
    _assert_no_traceback(chk, "check")
    assert chk.returncode == 0, chk.stderr

    # 5. Summary consumer accepts the model output.
    summ = _run_cli(
        "summarize-analysis",
        "--deterministic-report", str(report),
        "--analysis-results", str(analysis),
    )
    _assert_no_traceback(summ, "summarize-analysis")
    assert summ.returncode == 0, summ.stderr

    # --- Row-level contract assertions (these carry the real weight) ---
    analysis_text = analysis.read_text(encoding="utf-8")
    raw_rows = [
        json.loads(line) for line in analysis_text.splitlines() if line.strip()
    ]
    assert len(raw_rows) == len(subset), (
        f"expected one result row per live packet ({len(subset)}), "
        f"got {len(raw_rows)}"
    )

    # Load-bearing model assertion: a contained provider/model failure is a
    # schema-valid `ambiguous` row WITH an `error` field, so this is the only
    # check that distinguishes real analysis from a caught failure.
    errored = [row for row in raw_rows if "error" in row]
    assert not errored, f"live analysis rows carry error fields: {errored}"

    for row in raw_rows:
        result = validate_analysis_row(row, expected_packet_ids)
        assert not isinstance(result, str), f"invalid result row: {result}"
        assert str(row["packet_id"]) in expected_packet_ids

    # Independent of summarize's exit code: summarize renders analysis-load
    # problems and still exits 0 when the report is valid.
    load = load_analysis_results(analysis_text, expected_packet_ids)
    assert load.errors == (), f"analysis load errors: {load.errors}"
