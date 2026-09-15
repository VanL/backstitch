"""Deterministic local ``llm`` plugin used only by hermetic acceptance tests."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path

import llm


def _append_event(event: dict[str, object]) -> None:
    path_value = os.environ.get("BACKSTITCH_DOGFOOD_MODEL_LEDGER")
    if path_value is None:
        return
    path = Path(path_value)
    line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as output:
        output.write(line)


class BackstitchAcceptanceModel(llm.Model):
    """A local model that emits closed results from the request identity only."""

    supports_schema = True

    class Options(llm.Options):
        json_object: bool | None = None
        temperature: float | None = None
        seed: int | None = None
        max_tokens: int | None = None

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    def execute(
        self,
        prompt: llm.Prompt,
        stream: bool,
        response: llm.Response,
        conversation: llm.Conversation | None,
    ) -> Iterator[str]:
        del stream, conversation
        prompt_text = prompt.prompt or ""
        request = json.loads(prompt_text.rsplit("\n\n", 1)[1])
        options = prompt.options.model_dump(exclude_none=True)
        prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()

        if "verify_contract_version" in request:
            packet = request["packet"]
            claim = request["claim"]
            regions = packet["evidence_regions"]
            result = {
                "packet_id": packet["packet_id"],
                "claim_hash": hashlib.sha256(
                    json.dumps(claim, sort_keys=True, separators=(",", ":")).encode(
                        "utf-8"
                    )
                ).hexdigest(),
                "verdict": "support",
                "support_score": 1.0,
                "summary": "Hermetic verifier received the closed request.",
                "evidence": [
                    next(region for region in regions if region["role"] == role)
                    for role in ("requirement", "implementation")
                ],
            }
            role = "verifier"
        else:
            mismatch = os.environ.get(
                "BACKSTITCH_DOGFOOD_MODEL_MODE"
            ) == "eval" and "return 2" in json.dumps(
                request, sort_keys=True, separators=(",", ":")
            )
            finding_evidence = (
                [
                    next(
                        region
                        for region in request["evidence_regions"]
                        if region["role"] == role
                    )
                    for role in ("requirement", "implementation")
                ]
                if mismatch
                else []
            )
            ok_evidence = (
                [
                    next(
                        region
                        for region in request["evidence_regions"]
                        if region["role"]
                        == ("test" if request["kind"] == "invariant" else "requirement")
                    )
                ]
                if request["kind"] in {"invariant", "suppression"}
                else []
            )
            result = {
                "packet_id": request["packet_id"],
                "assessment": {
                    "classification": "confirmed_mismatch" if mismatch else "ok",
                    "evidence": {
                        region["role"]: [
                            {
                                key: region[key]
                                for key in ("path", "start_line", "end_line")
                            }
                        ]
                        for region in (finding_evidence if mismatch else ok_evidence)
                    },
                },
                "confidence": 1.0,
                "summary": "Hermetic analyzer received the closed packet.",
                "rationale": "The response is deterministic and provider-free.",
            }
            role = "analyzer"

        response.response_json = {
            "id": f"backstitch-acceptance-{prompt_hash[:16]}",
            "model": self.model_id,
            "model_revision": "fixture-v1",
        }
        response.set_usage(
            input=max(1, len(prompt_text.encode("utf-8")) // 4),
            output=32,
        )
        _append_event(
            {
                "role": role,
                "model_id": self.model_id,
                "prompt_sha256": prompt_hash,
                "request_options": options,
            }
        )
        mutation_path = os.environ.get("BACKSTITCH_DOGFOOD_MUTATE_ON_CALL")
        if role == "analyzer" and mutation_path is not None:
            path = Path(mutation_path)
            path.write_text(
                path.read_text(encoding="utf-8")
                + "\n# mutated during hermetic model execution\n",
                encoding="utf-8",
            )
        yield json.dumps(result, sort_keys=True, separators=(",", ":"))


@llm.hookimpl
def register_models(register: object) -> None:
    register(BackstitchAcceptanceModel("backstitch-acceptance-local"))
    register(BackstitchAcceptanceModel("backstitch-acceptance-verifier"))
