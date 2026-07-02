"""Semantic analysis over packets through the ``llm`` Python API.

Spec: docs/specs/02-backstitch-core.md [SC-7]

The adapter boundary exists so tests prove prompt construction, iteration,
parsing, and malformed-output handling with fakes; only the default adapter
touches ``llm`` and real models. Findings are advisory [SC-7].
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from backstitch.analysis_results import validate_analysis_row

ModelAdapter = Callable[[str], str]

_FENCE_RE = re.compile(r"^```[\w-]*\n(?P<body>.*)\n```\s*$", re.DOTALL)


def default_adapter(model_name: str | None = None) -> ModelAdapter:
    """Build the real adapter for an ``llm`` model.

    With no name, ``llm``'s configured default model is used (whatever
    ``llm models default`` reports).
    """

    import llm

    model = llm.get_model(model_name) if model_name else llm.get_model()

    def call(prompt: str) -> str:
        return str(model.prompt(prompt).text())

    return call


def build_prompt(packet: dict[str, Any]) -> str:
    """Compose the review prompt: instructions, then the bounded packet."""

    body = {k: v for k, v in packet.items() if k != "instructions"}
    return f"{packet['instructions']}\n\n{json.dumps(body)}"


def _packet_evidence_bounds(
    packet: dict[str, Any],
) -> dict[str, tuple[tuple[int, int], ...]]:
    """What the model was shown, as path -> allowed line ranges ([SC-7]).

    Owner snippets and the spec section text are line-bounded, so evidence
    must fall inside one of those ranges. Linked tests are named by PATH
    only -- the model never saw their content, so a path with no ranges is
    known to the packet but cannot carry line evidence.
    """

    bounds: dict[str, list[tuple[int, int]]] = {}
    spec_path = packet.get("spec_path")
    # Blank paths never name a packet member: an empty or whitespace-only
    # string must not become a citable evidence path (load-time validation
    # rejects these, but analyze_packets is also a library entry point).
    if isinstance(spec_path, str) and spec_path.strip():
        ranges = bounds.setdefault(spec_path, [])
        start = packet.get("section_start_line")
        text = packet.get("section_text")
        if isinstance(start, int) and isinstance(text, str) and text.splitlines():
            ranges.append((start, start + len(text.splitlines()) - 1))
    for test in packet.get("tests", ()):
        if isinstance(test, str) and test.strip():
            bounds.setdefault(test, [])
    for owner in packet.get("owners", ()):
        if (
            not isinstance(owner, dict)
            or not isinstance(owner.get("path"), str)
            or not owner["path"].strip()
        ):
            continue
        ranges = bounds.setdefault(owner["path"], [])
        start = owner.get("start_line")
        snippet = owner.get("snippet")
        # An EMPTY snippet (directory mappings) showed no line content:
        # like tests, the path is known but carries no valid line evidence.
        if isinstance(start, int) and isinstance(snippet, str) and snippet.splitlines():
            ranges.append((start, start + len(snippet.splitlines()) - 1))
    return {path: tuple(ranges) for path, ranges in bounds.items()}


def _parse_model_output(raw: str, packet: dict[str, Any]) -> dict[str, Any] | str:
    packet_id = packet["packet_id"]
    text = raw.strip()
    fence = _FENCE_RE.match(text)
    if fence:
        text = fence.group("body").strip()
    try:
        row = json.loads(text)
    except json.JSONDecodeError:
        return "model output is not valid JSON"
    validated = validate_analysis_row(
        row, None, allowed_evidence=_packet_evidence_bounds(packet)
    )
    if isinstance(validated, str):
        return f"model output invalid: {validated}"
    if validated.packet_id != packet_id:
        return (
            f"model output packet_id `{validated.packet_id}` does not match the packet"
        )
    assert isinstance(row, dict)
    return row


def _error_record(packet_id: str, message: str) -> dict[str, Any]:
    # [SC-7]: one bad response yields one `ambiguous`/error record for the
    # packet -- a consumer of the results JSONL never loses a packet-level
    # result to a model failure. `packet_id` comes from the packet, never
    # the response, and the record passes validate_analysis_row.
    return {
        "packet_id": packet_id,
        "classification": "ambiguous",
        "summary": f"analysis error: {message}",
        "rationale": message,
        "evidence": [],
        "error": message,
    }


def analyze_packets(
    packets: Iterable[dict[str, Any]],
    adapter: ModelAdapter,
    concurrency: int = 1,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Run the adapter over every packet; collect rows and per-packet errors.

    Every packet yields exactly one row: a failed packet yields an
    `ambiguous`/error record ([SC-7]) and its message is also collected in
    ``errors`` for stderr. Output rows keep packet order regardless of
    concurrency. A failure on one packet never aborts the others.
    """

    packet_list = list(packets)

    def run_one(packet: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        packet_id = packet.get("packet_id", "<missing packet_id>")
        if "instructions" not in packet:
            message = "packet has no `instructions` field"
            return _error_record(packet_id, message), f"{packet_id}: {message}"
        try:
            raw = adapter(build_prompt(packet))
        except Exception as exc:  # noqa: BLE001 - adapter is an external boundary
            message = f"model call failed: {exc}"
            return _error_record(packet_id, message), f"{packet_id}: {message}"
        parsed = _parse_model_output(raw, packet)
        if isinstance(parsed, str):
            return _error_record(packet_id, parsed), f"{packet_id}: {parsed}"
        return parsed, None

    if concurrency <= 1:
        outcomes = [run_one(packet) for packet in packet_list]
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            outcomes = list(pool.map(run_one, packet_list))

    rows = [row for row, _ in outcomes]
    errors = [error for _, error in outcomes if error is not None]
    return rows, errors


def analyze_exit_code(rows: list[dict[str, Any]], errors: list[str]) -> int:
    """Exit 2 when analysis produced nothing but failures; 0 otherwise.

    [SC-5]: exit 1 is reserved for deterministic findings about the target
    repository, and semantic findings are advisory -- `analyze` never
    returns 1. Total failure (every packet errored; rows include the
    per-packet error records) is a statement about the tool or the model,
    so it is exit 2. Partial failure still exits 0 because the output is
    usable; total failure must be scriptable without scraping stderr.
    """

    return 2 if errors and len(errors) == len(rows) else 0


def render_results_jsonl(rows: list[dict[str, Any]]) -> str:
    """Render analysis rows as JSONL, one result per line."""

    return "".join(json.dumps(row) + "\n" for row in rows)


def resolve_model_name(
    explicit: str | None = None,
    *,
    configured: str | None = None,
) -> str | None:
    """[CFG-5] model precedence: --model, LLM_MODEL, config, llm default.

    CLI beats env beats config -- [CFG-5]'s assembly order puts environment
    variables ABOVE the config file, so `LLM_MODEL` overrides
    `analyze.model` whenever --model is omitted.

    Returns ``None`` to mean "let ``llm`` use its configured default" so the
    lazy-import boundary stays in ``default_adapter``.
    """

    import os

    if explicit is not None and explicit.strip():
        return explicit.strip()
    env = os.environ.get("LLM_MODEL", "").strip()
    if env:
        return env
    if configured is not None and configured.strip():
        return configured.strip()
    return None
