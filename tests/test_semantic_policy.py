"""Semantic finding identity, policy authority, and diagnostic projection."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from backstitch.diagnostics import (
    DiagnosticLevel,
    DiagnosticLevelRule,
    DiagnosticsSettings,
    Severity,
)
from backstitch.semantic_policy import (
    SEMANTIC_DEFAULT_LEVELS,
    SEMANTIC_DEFINITIONS,
    SEMANTIC_VERIFICATION_STATES,
    VERIFIER_VERIFICATION_STATES,
    DispositionError,
    SemanticPolicy,
    SemanticPolicyError,
    VerificationState,
    finding_hash,
    materialize_semantic_policy,
    project_semantic_result,
    project_semantic_results,
)
from backstitch.settings import SemanticDisposition, resolve_config


@dataclass(frozen=True, slots=True)
class _Origin:
    source: str
    position: int


@dataclass(frozen=True, slots=True)
class _Disposition:
    code: str
    packet_id: str
    packet_hash: str
    finding_hash: str
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class _Aggregate:
    context: str
    event: dict[str, object]


def _canonical_result(
    classification: str = "confirmed_mismatch",
) -> dict[str, object]:
    if classification in {
        "rationale_insufficient",
        "scope_overbroad",
        "risk_unaddressed",
    }:
        evidence: list[dict[str, object]] = [
            {
                "role": "requirement",
                "path": "docs/specs/01-x.md",
                "start_line": 6,
                "end_line": 6,
                "excerpt": "Generated code cannot carry a stable backlink.",
                "excerpt_sha256": hashlib.sha256(
                    b"Generated code cannot carry a stable backlink."
                ).hexdigest(),
            }
        ]
        if classification in {"scope_overbroad", "risk_unaddressed"}:
            evidence.insert(
                0,
                {
                    "role": "counterevidence",
                    "path": "generated/x.py",
                    "start_line": 11,
                    "end_line": 11,
                    "excerpt": "dangerous_call()",
                    "excerpt_sha256": hashlib.sha256(
                        b"dangerous_call()"
                    ).hexdigest(),
                },
            )
        return {
            "schema_version": 3,
            "packet_id": "suppression::docs/specs/01-x.md#SUP-X",
            "kind": "suppression",
            "packet_hash": "a" * 64,
            "analysis_key": "b" * 64,
            "classification": classification,
            "confidence": 0.9,
            "rationale": "The shown issue is not justified by the declaration.",
            "summary": "Suppression needs review.",
            "evidence": evidence,
            "verification_state": "evidence_bound",
        }
    return {
        "schema_version": 2,
        "packet_id": "docs/specs/01-x.md#X-1",
        "kind": "section",
        "packet_hash": "a" * 64,
        "analysis_key": "b" * 64,
        "classification": classification,
        "confidence": 0.9,
        "rationale": "The shown implementation conflicts with the requirement.",
        "summary": "The implementation returns two.",
        "evidence": [
            {
                "role": "implementation",
                "path": "pkg/x.py",
                "start_line": 11,
                "end_line": 11,
                "excerpt": "    return 2",
                "excerpt_sha256": hashlib.sha256(b"    return 2").hexdigest(),
            },
            {
                "role": "requirement",
                "path": "docs/specs/01-x.md",
                "start_line": 6,
                "end_line": 6,
                "excerpt": "Must return one.",
                "excerpt_sha256": hashlib.sha256(b"Must return one.").hexdigest(),
            },
        ],
        "verification_state": "evidence_bound",
    }


def _packaged_policy(
    *,
    fail_on: tuple[Severity, ...] = ("error",),
    extra_rules: tuple[DiagnosticLevelRule, ...] = (),
    extra_origins: tuple[_Origin, ...] = (),
) -> SemanticPolicy:
    rules = tuple(
        DiagnosticLevelRule(selectors=(f"{code}:{state}",), level=level)
        for (code, state), level in SEMANTIC_DEFAULT_LEVELS.items()
    )
    origins = tuple(
        _Origin("packaged:backstitch/defaults.toml", position)
        for position in range(3, 3 + len(rules))
    )
    settings = DiagnosticsSettings(
        default_level="warning",
        levels=rules + extra_rules,
        fail_on=fail_on,
    )
    layers: tuple[str, ...] = ("packaged:backstitch/defaults.toml",)
    if extra_origins:
        layers += tuple(dict.fromkeys(origin.source for origin in extra_origins))
    return materialize_semantic_policy(
        settings,
        origins + extra_origins,
        layers,
    )


def test_closed_semantic_registry_covers_every_code_and_classification() -> None:
    assert {
        definition.classification: (definition.code, definition.short_code)
        for definition in SEMANTIC_DEFINITIONS
    } == {
        "confirmed_mismatch": ("SEMANTIC_CONFIRMED_MISMATCH", "BSA001"),
        "probable_mismatch": ("SEMANTIC_PROBABLE_MISMATCH", "BSA002"),
        "missing_trace": ("SEMANTIC_MISSING_TRACE", "BSA003"),
        "weak_binding": ("SEMANTIC_WEAK_BINDING", "BSA004"),
        "ambiguous": ("SEMANTIC_AMBIGUOUS", "BSA005"),
        "rationale_insufficient": (
            "SEMANTIC_SUPPRESSION_RATIONALE_INSUFFICIENT",
            "BSA006",
        ),
        "scope_overbroad": ("SEMANTIC_SUPPRESSION_SCOPE_OVERBROAD", "BSA007"),
        "risk_unaddressed": (
            "SEMANTIC_SUPPRESSION_RISK_UNADDRESSED",
            "BSA008",
        ),
    }
    assert SEMANTIC_VERIFICATION_STATES == (
        "evidence_bound",
        "verification_indeterminate",
        "independently_verified",
        "mechanically_verified",
        "human_verified",
        "disputed_by_verifier",
        "human_rejected",
    )


def test_legacy_corroborated_input_normalizes_without_becoming_producer_state() -> None:
    policy = _packaged_policy()

    entry = policy.entry_for("SEMANTIC_CONFIRMED_MISMATCH", "corroborated")
    projected = project_semantic_result(
        _canonical_result(),
        policy,
        trusted_verification_state="corroborated",
    )

    assert entry.verification_state == "evidence_bound"
    assert projected.diagnostic is not None
    assert projected.diagnostic.verification_state == "evidence_bound"
    assert all(state != "corroborated" for _, state in SEMANTIC_DEFAULT_LEVELS.keys())
    assert VERIFIER_VERIFICATION_STATES == frozenset(
        {
            "verification_indeterminate",
            "independently_verified",
            "disputed_by_verifier",
        }
    )


def test_packaged_settings_materialize_the_exact_semantic_matrix() -> None:
    settings = resolve_config(Path.cwd(), use_repo_config=False)

    policy = materialize_semantic_policy(
        settings.diagnostics,
        settings.policy_rule_origins,
        settings.config_layers,
    )

    assert {
        (entry.code, entry.verification_state): entry.level for entry in policy.entries
    } == SEMANTIC_DEFAULT_LEVELS
    assert [entry.winning_rule.position for entry in policy.entries] == list(
        range(3, 3 + len(SEMANTIC_DEFAULT_LEVELS))
    )


@pytest.mark.parametrize(
    ("code", "state", "expected"),
    [(code, state, level) for (code, state), level in SEMANTIC_DEFAULT_LEVELS.items()],
)
def test_packaged_policy_fires_every_default_code_state_cell(
    code: str, state: VerificationState, expected: DiagnosticLevel
) -> None:
    policy = _packaged_policy()

    entry = policy.entry_for(code, state)

    assert entry.default_level == expected
    assert entry.level == expected
    assert entry.winning_rule.source == "packaged:backstitch/defaults.toml"
    assert entry.winning_rule.selector == f"{code}:{state}"
    expected_position = 3 + list(SEMANTIC_DEFAULT_LEVELS).index((code, state))
    assert entry.winning_rule.position == expected_position


def test_policy_requires_origins_aligned_one_to_one_with_rules() -> None:
    settings = DiagnosticsSettings(
        levels=(
            DiagnosticLevelRule(
                selectors=("SEMANTIC_AMBIGUOUS:evidence_bound",), level="info"
            ),
        )
    )

    with pytest.raises(SemanticPolicyError, match="aligned"):
        materialize_semantic_policy(
            settings,
            (),
            ("packaged:backstitch/defaults.toml",),
        )


def test_later_rule_wins_and_records_first_matching_selector_and_exact_origin() -> None:
    source = "/repo/.backstitch.toml"
    rule = DiagnosticLevelRule(
        selectors=(
            "BSA001:human_verified",
            "SEMANTIC_CONFIRMED_MISMATCH:human_verified",
        ),
        level="info",
    )
    policy = _packaged_policy(
        extra_rules=(rule,),
        extra_origins=(_Origin(source, 0),),
    )

    entry = policy.entry_for("SEMANTIC_CONFIRMED_MISMATCH", "human_verified")

    assert entry.level == "info"
    assert entry.winning_rule.to_row() == {
        "source": source,
        "position": 0,
        "selector": "BSA001:human_verified",
        "level": "info",
    }
    assert policy.effective_policy_layers == (
        "packaged:backstitch/defaults.toml",
        source,
    )


@pytest.mark.parametrize(
    "state",
    [
        "evidence_bound",
        "verification_indeterminate",
        "disputed_by_verifier",
        "human_rejected",
    ],
)
def test_non_authoritative_states_can_never_gain_failure_authority(
    state: str,
) -> None:
    rule = DiagnosticLevelRule(
        selectors=(f"SEMANTIC_AMBIGUOUS:{state}",),
        level="error",
    )
    with pytest.raises(SemanticPolicyError, match="failure authority"):
        _packaged_policy(
            extra_rules=(rule,),
            extra_origins=(_Origin("/repo/policy.toml", 0),),
        )


def test_exact_independent_authority_request_is_preserved_for_qualification_owner() -> (
    None
):
    rule = DiagnosticLevelRule(
        selectors=("SEMANTIC_CONFIRMED_MISMATCH:independently_verified",),
        level="error",
    )
    policy = _packaged_policy(
        extra_rules=(rule,),
        extra_origins=(_Origin("/repo/policy.toml", 0),),
    )

    projection = project_semantic_result(
        _canonical_result(),
        policy,
        trusted_verification_state="independently_verified",
    )

    assert projection.diagnostic is not None
    assert projection.diagnostic.severity == "error"
    assert projection.diagnostic.is_failure is False


@pytest.mark.parametrize("short_code", ["BSA006", "BSA007", "BSA008"])
def test_unmeasured_suppression_codes_cannot_gain_independent_failure_authority(
    short_code: str,
) -> None:
    rule = DiagnosticLevelRule(
        selectors=(f"{short_code}:independently_verified",),
        level="error",
    )

    with pytest.raises(SemanticPolicyError, match="future measured qualification"):
        _packaged_policy(
            extra_rules=(rule,),
            extra_origins=(_Origin("/repo/policy.toml", 0),),
        )


def test_evidence_bound_level_in_fail_on_is_rejected_even_when_not_error() -> None:
    with pytest.raises(SemanticPolicyError, match="failure authority"):
        _packaged_policy(fail_on=("warning",))


@pytest.mark.parametrize(
    "selector",
    [
        "SEMANTIC_CONFIRMED_MISMATCH:human_verified",
        "BSA001:human_verified",
        "SEMANTIC_CONFIRMED_MISMATCH:mechanically_verified",
        "BSA001:mechanically_verified",
    ],
)
def test_exact_long_and_short_human_or_mechanical_rules_can_grant_authority(
    selector: str,
) -> None:
    rule = DiagnosticLevelRule(selectors=(selector,), level="error")
    policy = _packaged_policy(
        extra_rules=(rule,),
        extra_origins=(_Origin("/repo/policy.toml", 0),),
    )

    state = selector.partition(":")[2]
    assert policy.entry_for("SEMANTIC_CONFIRMED_MISMATCH", state).level == "error"


def test_wildcard_cannot_grant_failure_authority() -> None:
    rule = DiagnosticLevelRule(selectors=("BSA*:human_verified",), level="error")

    with pytest.raises(SemanticPolicyError, match="wildcard|failure authority"):
        _packaged_policy(
            extra_rules=(rule,),
            extra_origins=(_Origin("/repo/policy.toml", 0),),
        )


def test_wildcard_may_lower_but_cannot_raise_packaged_severity() -> None:
    lower = DiagnosticLevelRule(selectors=("BSA*",), level="info")
    policy = _packaged_policy(
        extra_rules=(lower,),
        extra_origins=(_Origin("/repo/policy.toml", 0),),
    )
    assert (
        policy.entry_for("SEMANTIC_CONFIRMED_MISMATCH", "evidence_bound").level
        == "info"
    )

    raise_ = DiagnosticLevelRule(selectors=("BSA*",), level="warning")
    with pytest.raises(SemanticPolicyError, match="wildcard.*raise"):
        _packaged_policy(
            extra_rules=(raise_,),
            extra_origins=(_Origin("/repo/policy.toml", 0),),
        )


def test_backstitch_applied_policy_neutralizes_the_strict_wildcard() -> None:
    repo_root = Path(__file__).parents[1]
    settings = resolve_config(repo_root, explicit=repo_root / "pyproject.toml")

    policy = materialize_semantic_policy(
        settings.diagnostics,
        settings.policy_rule_origins,
        settings.config_layers,
    )

    entry = policy.entry_for("SEMANTIC_CONFIRMED_MISMATCH", "evidence_bound")
    assert entry.level == "info"
    assert entry.winning_rule.selector == "BSA*"
    assert entry.winning_rule.source == str((repo_root / "pyproject.toml").resolve())


def test_finding_hash_uses_only_structured_identity_and_evidence_hash_subset() -> None:
    result = _canonical_result()
    evidence = cast(list[dict[str, object]], result["evidence"])
    expected_preimage = {
        "finding_contract_version": 1,
        "code": "SEMANTIC_CONFIRMED_MISMATCH",
        "classification": "confirmed_mismatch",
        "packet_kind": "section",
        "packet_id": result["packet_id"],
        "packet_hash": result["packet_hash"],
        "evidence": [
            {
                key: item[key]
                for key in (
                    "role",
                    "path",
                    "start_line",
                    "end_line",
                    "excerpt_sha256",
                )
            }
            for item in evidence
        ],
    }
    expected = hashlib.sha256(
        json.dumps(
            expected_preimage,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    assert finding_hash(result) == expected

    for field, replacement in (
        ("summary", "Changed prose."),
        ("rationale", "Changed rationale."),
        ("confidence", 0.1),
        ("verification_state", "human_verified"),
        ("analysis_key", "c" * 64),
    ):
        changed = copy.deepcopy(result)
        changed[field] = replacement
        assert finding_hash(changed) == expected, field
    changed = copy.deepcopy(result)
    changed_evidence = cast(list[dict[str, object]], changed["evidence"])
    changed_evidence[0]["excerpt"] = "presentation text changed"
    assert finding_hash(changed) == expected


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("packet_id",), "other"),
        (("packet_hash",), "c" * 64),
        (("kind",), "invariant"),
        (("classification",), "probable_mismatch"),
        (("evidence", 0, "path"), "pkg/y.py"),
        (("evidence", 0, "start_line"), 10),
        (("evidence", 0, "end_line"), 12),
        (("evidence", 0, "excerpt_sha256"), "d" * 64),
    ],
)
def test_every_finding_identity_field_changes_hash(
    path: tuple[object, ...], replacement: object
) -> None:
    result = _canonical_result()
    changed = copy.deepcopy(result)
    if len(path) == 1:
        changed[path[0]] = replacement  # type: ignore[index]
    else:
        changed[path[0]][path[1]][path[2]] = replacement  # type: ignore[index]
    assert finding_hash(changed) != finding_hash(result)


@pytest.mark.parametrize(
    ("classification", "code"),
    [
        ("confirmed_mismatch", "SEMANTIC_CONFIRMED_MISMATCH"),
        ("probable_mismatch", "SEMANTIC_PROBABLE_MISMATCH"),
        ("missing_trace", "SEMANTIC_MISSING_TRACE"),
        ("weak_binding", "SEMANTIC_WEAK_BINDING"),
        ("ambiguous", "SEMANTIC_AMBIGUOUS"),
        (
            "rationale_insufficient",
            "SEMANTIC_SUPPRESSION_RATIONALE_INSUFFICIENT",
        ),
        ("scope_overbroad", "SEMANTIC_SUPPRESSION_SCOPE_OVERBROAD"),
        ("risk_unaddressed", "SEMANTIC_SUPPRESSION_RISK_UNADDRESSED"),
    ],
)
def test_every_non_ok_classification_projects_one_stable_diagnostic(
    classification: str, code: str
) -> None:
    result = _canonical_result(classification)
    projected = project_semantic_result(result, _packaged_policy())

    assert projected.diagnostic is not None
    assert projected.diagnostic.code == code
    assert projected.diagnostic.finding_hash == finding_hash(result)


def test_ok_result_projects_no_diagnostic() -> None:
    projected = project_semantic_result(_canonical_result("ok"), _packaged_policy())
    assert projected.diagnostic is None
    assert projected.undisposed_finding is None


@pytest.mark.parametrize(
    ("status", "expected_state"),
    [("accepted", "human_verified"), ("rejected", "human_rejected")],
)
def test_exact_disposition_changes_only_projected_verification_state(
    status: str, expected_state: str
) -> None:
    result = _canonical_result()
    original = copy.deepcopy(result)
    disposition = SemanticDisposition(
        code="SEMANTIC_CONFIRMED_MISMATCH",
        packet_id=str(result["packet_id"]),
        packet_hash=str(result["packet_hash"]),
        finding_hash=finding_hash(result),
        status=status,
        reason="Reviewed against the shown evidence.",
    )

    run = project_semantic_results(
        (result,),
        _packaged_policy(),
        dispositions=(disposition,),
        finding_handling="require_disposition",
    )

    assert run.diagnostics[0].verification_state == expected_state
    assert run.unused_dispositions == ()
    assert run.undisposed_findings == ()
    assert run.requires_disposition is False
    assert result == original


@pytest.mark.parametrize(
    ("context", "expected_state"),
    [
        ("independently_verified", "independently_verified"),
        ("disputed_by_verifier", "disputed_by_verifier"),
        ("verification_indeterminate", "verification_indeterminate"),
    ],
)
def test_every_verifier_aggregate_context_projects_by_finding_identity(
    context: str, expected_state: str
) -> None:
    result = _canonical_result()
    identity_hash = finding_hash(result)
    aggregate = _Aggregate(context=context, event={"context": context})
    original_event = copy.deepcopy(aggregate.event)

    run = project_semantic_results(
        (result,),
        _packaged_policy(),
        finding_handling="report",
        verification_aggregates={identity_hash: aggregate},
    )

    assert run.diagnostics[0].verification_state == expected_state
    assert run.undisposed_findings[0].verification_state == expected_state
    assert run.finding_debt == run.undisposed_findings
    assert aggregate.event == original_event


@pytest.mark.parametrize(
    ("status", "mechanical", "verifier_context", "expected_state"),
    [
        (None, False, None, "evidence_bound"),
        (None, True, None, "mechanically_verified"),
        (None, False, "independently_verified", "independently_verified"),
        (None, False, "disputed_by_verifier", "disputed_by_verifier"),
        (None, False, "verification_indeterminate", "verification_indeterminate"),
        (None, True, "independently_verified", "mechanically_verified"),
        (None, True, "disputed_by_verifier", "mechanically_verified"),
        (None, True, "verification_indeterminate", "mechanically_verified"),
        ("accepted", False, None, "human_verified"),
        ("accepted", False, "disputed_by_verifier", "human_verified"),
        ("accepted", True, None, "human_verified"),
        ("accepted", True, "disputed_by_verifier", "human_verified"),
        ("rejected", False, None, "human_rejected"),
        ("rejected", False, "independently_verified", "human_rejected"),
        ("rejected", True, None, "human_rejected"),
        ("rejected", True, "independently_verified", "human_rejected"),
    ],
)
def test_context_composition_fires_every_transition_and_precedence_pair(
    status: str | None,
    mechanical: bool,
    verifier_context: str | None,
    expected_state: str,
) -> None:
    result = _canonical_result()
    identity_hash = finding_hash(result)
    dispositions: tuple[_Disposition, ...] = ()
    if status is not None:
        dispositions = (
            _Disposition(
                code="SEMANTIC_CONFIRMED_MISMATCH",
                packet_id=str(result["packet_id"]),
                packet_hash=str(result["packet_hash"]),
                finding_hash=identity_hash,
                status=status,
                reason="Human reviewed the finding.",
            ),
        )
    mechanical_findings = (identity_hash,) if mechanical else ()
    aggregates = (
        {}
        if verifier_context is None
        else {
            identity_hash: _Aggregate(
                context=verifier_context,
                event={"context": verifier_context},
            )
        }
    )

    run = project_semantic_results(
        (result,),
        _packaged_policy(),
        dispositions=dispositions,
        finding_handling="report",
        mechanically_verified_findings=mechanical_findings,
        verification_aggregates=aggregates,
    )

    assert run.diagnostics[0].verification_state == expected_state
    if status is None:
        assert run.undisposed_findings[0].verification_state == expected_state
    else:
        assert run.undisposed_findings == ()
        assert run.unused_dispositions == ()


@pytest.mark.parametrize(
    ("mechanical_findings", "aggregates", "message"),
    [
        (("not-a-hash",), {}, "mechanically verified finding identities"),
        ((), {"not-a-hash": _Aggregate("independently_verified", {})}, "identities"),
        (
            (),
            {"c" * 64: _Aggregate("not-a-context", {})},
            "aggregate context",
        ),
        (
            (),
            {"c" * 64: _Aggregate("independently_verified", {})},
            "projected semantic finding",
        ),
    ],
)
def test_verification_observation_inputs_fail_closed(
    mechanical_findings: tuple[str, ...],
    aggregates: dict[str, _Aggregate],
    message: str,
) -> None:
    with pytest.raises(SemanticPolicyError, match=message):
        project_semantic_results(
            (_canonical_result(),),
            _packaged_policy(),
            mechanically_verified_findings=mechanical_findings,
            verification_aggregates=aggregates,
        )


def test_accepted_disposition_can_activate_an_exact_human_error_rule() -> None:
    result = _canonical_result()
    disposition = SemanticDisposition(
        code="SEMANTIC_CONFIRMED_MISMATCH",
        packet_id=str(result["packet_id"]),
        packet_hash=str(result["packet_hash"]),
        finding_hash=finding_hash(result),
        status="accepted",
        reason="Human review confirmed the mismatch.",
    )
    policy = _packaged_policy(
        extra_rules=(
            DiagnosticLevelRule(selectors=("BSA001:human_verified",), level="error"),
        ),
        extra_origins=(_Origin("/repo/policy.toml", 0),),
    )

    projection = project_semantic_result(
        result,
        policy,
        dispositions=(disposition,),
    )

    assert projection.diagnostic is not None
    assert projection.diagnostic.is_failure is True
    assert set(projection.diagnostic.to_row()) == {
        "code",
        "short_code",
        "classification",
        "packet_kind",
        "packet_id",
        "packet_hash",
        "finding_hash",
        "verification_state",
        "evidence",
        "default_severity",
        "severity",
        "summary",
        "rationale",
        "analysis_key",
        "winning_policy_rule",
    }


def test_unmatched_disposition_is_unused_and_finding_debt_is_exact() -> None:
    result = _canonical_result()
    disposition = _Disposition(
        code="SEMANTIC_CONFIRMED_MISMATCH",
        packet_id=str(result["packet_id"]),
        packet_hash="c" * 64,
        finding_hash=finding_hash(result),
        status="accepted",
        reason="Reviewed.",
    )

    run = project_semantic_results(
        (result,),
        _packaged_policy(),
        dispositions=(disposition,),
        finding_handling="report",
    )

    assert run.unused_dispositions == (disposition,)
    assert run.undisposed_findings[0].to_row() == {
        "code": "SEMANTIC_CONFIRMED_MISMATCH",
        "packet_id": result["packet_id"],
        "packet_hash": result["packet_hash"],
        "finding_hash": finding_hash(result),
        "verification_state": "evidence_bound",
    }
    assert run.finding_debt == run.undisposed_findings
    assert run.requires_disposition is False


@pytest.mark.parametrize(
    ("handling", "has_debt", "requires"),
    [
        ("allow", False, False),
        ("report", True, False),
        ("require_disposition", True, True),
    ],
)
def test_finding_handling_exposes_debt_and_required_failure(
    handling: str, has_debt: bool, requires: bool
) -> None:
    run = project_semantic_results(
        (_canonical_result(),),
        _packaged_policy(),
        finding_handling=handling,
    )
    assert bool(run.finding_debt) is has_debt
    assert run.requires_disposition is requires


def test_policy_projection_producers_use_only_finding_vocabulary() -> None:
    run = project_semantic_results(
        (_canonical_result(),),
        _packaged_policy(),
        finding_handling="report",
    )

    assert set(run.__dataclass_fields__) == {
        "diagnostics",
        "undisposed_findings",
        "finding_debt",
        "unused_dispositions",
        "finding_handling",
    }
    with pytest.raises(TypeError, match="candidate_handling"):
        project_semantic_results(  # type: ignore[call-arg]
            (_canonical_result(),),
            _packaged_policy(),
            candidate_handling="report",
        )


def test_duplicate_invalid_and_noncanonical_dispositions_are_rejected() -> None:
    result = _canonical_result()
    valid = _Disposition(
        code="SEMANTIC_CONFIRMED_MISMATCH",
        packet_id=str(result["packet_id"]),
        packet_hash=str(result["packet_hash"]),
        finding_hash=finding_hash(result),
        status="accepted",
        reason="Reviewed.",
    )
    with pytest.raises(DispositionError, match="duplicate"):
        project_semantic_results(
            (result,), _packaged_policy(), dispositions=(valid, valid)
        )
    with pytest.raises(DispositionError, match="canonical long code"):
        project_semantic_results(
            (result,),
            _packaged_policy(),
            dispositions=(
                _Disposition(
                    "BSA001",
                    valid.packet_id,
                    valid.packet_hash,
                    valid.finding_hash,
                    "accepted",
                    "Reviewed.",
                ),
            ),
        )
    with pytest.raises(DispositionError, match="reason"):
        project_semantic_results(
            (result,),
            _packaged_policy(),
            dispositions=(
                _Disposition(
                    valid.code,
                    valid.packet_id,
                    valid.packet_hash,
                    valid.finding_hash,
                    "accepted",
                    " ",
                ),
            ),
        )


def test_off_diagnostic_remains_in_audit_projection_without_exit_effect() -> None:
    rule = DiagnosticLevelRule(
        selectors=("SEMANTIC_CONFIRMED_MISMATCH:evidence_bound",), level="off"
    )
    policy = _packaged_policy(
        extra_rules=(rule,),
        extra_origins=(_Origin("/repo/policy.toml", 0),),
    )

    projected = project_semantic_result(_canonical_result(), policy)

    assert projected.diagnostic is not None
    assert projected.diagnostic.severity == "off"
    assert projected.diagnostic.is_failure is False
    assert projected.diagnostic.to_row()["winning_policy_rule"] == {
        "source": "/repo/policy.toml",
        "position": 0,
        "selector": "SEMANTIC_CONFIRMED_MISMATCH:evidence_bound",
        "level": "off",
    }
