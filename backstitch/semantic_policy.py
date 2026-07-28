"""Policy-neutral semantic finding identity and policy projection.

Cached semantic results remain frozen inference facts. This module owns the
separate semantic authority boundary that assigns stable finding identity,
applies trusted dispositions, materializes semantic policy with rule
provenance, and projects report diagnostics.

Spec: docs/specs/06-semantic-gates.md [SEM-2], [SEM-6];
docs/specs/07-verification-and-evidence-cases.md [EVC-6]
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, Protocol, TypeAlias, cast

from backstitch.canonical import canonical_json_bytes
from backstitch.diagnostics import DiagnosticLevel, DiagnosticsSettings, Severity
from backstitch.grammar import is_sha256_hex
from backstitch.semantic_evidence import CanonicalSemanticResult

VerificationState = Literal[
    "evidence_bound",
    "verification_indeterminate",
    "independently_verified",
    "mechanically_verified",
    "human_verified",
    "disputed_by_verifier",
    "human_rejected",
]
VerificationStateInput = VerificationState | Literal["corroborated"]
FindingHandling = Literal["allow", "report", "require_disposition"]
DispositionStatus = Literal["accepted", "rejected"]
CanonicalResult: TypeAlias = CanonicalSemanticResult | Mapping[str, Any]

SEMANTIC_VERIFICATION_STATES: tuple[VerificationState, ...] = (
    "evidence_bound",
    "verification_indeterminate",
    "independently_verified",
    "mechanically_verified",
    "human_verified",
    "disputed_by_verifier",
    "human_rejected",
)
VERIFIER_VERIFICATION_STATES: frozenset[VerificationState] = frozenset(
    {
        "verification_indeterminate",
        "independently_verified",
        "disputed_by_verifier",
    }
)
FAILURE_AUTHORITATIVE_STATES: frozenset[VerificationState] = frozenset(
    {"mechanically_verified", "human_verified"}
)


class SemanticPolicyError(ValueError):
    """Semantic policy is incomplete, ambiguous, or exceeds its authority."""


class DispositionError(ValueError):
    """A semantic disposition violates the closed policy contract."""


class PolicyRuleOriginLike(Protocol):
    """Structural boundary implemented by settings.PolicyRuleOrigin."""

    @property
    def source(self) -> str: ...

    @property
    def position(self) -> int: ...


class SemanticDispositionLike(Protocol):
    """Structural boundary implemented by settings.SemanticDisposition."""

    @property
    def code(self) -> str: ...

    @property
    def packet_id(self) -> str: ...

    @property
    def packet_hash(self) -> str: ...

    @property
    def finding_hash(self) -> str: ...

    @property
    def status(self) -> str: ...

    @property
    def reason(self) -> str: ...


class VerificationAggregateLike(Protocol):
    """Structural boundary implemented by semantic_verification's aggregate."""

    @property
    def context(self) -> str: ...


@dataclass(frozen=True, slots=True)
class SemanticDefinition:
    classification: str
    code: str
    short_code: str


SEMANTIC_DEFINITIONS: tuple[SemanticDefinition, ...] = (
    SemanticDefinition("confirmed_mismatch", "SEMANTIC_CONFIRMED_MISMATCH", "BSA001"),
    SemanticDefinition("probable_mismatch", "SEMANTIC_PROBABLE_MISMATCH", "BSA002"),
    SemanticDefinition("missing_trace", "SEMANTIC_MISSING_TRACE", "BSA003"),
    SemanticDefinition("weak_binding", "SEMANTIC_WEAK_BINDING", "BSA004"),
    SemanticDefinition("ambiguous", "SEMANTIC_AMBIGUOUS", "BSA005"),
    SemanticDefinition(
        "rationale_insufficient",
        "SEMANTIC_SUPPRESSION_RATIONALE_INSUFFICIENT",
        "BSA006",
    ),
    SemanticDefinition(
        "scope_overbroad",
        "SEMANTIC_SUPPRESSION_SCOPE_OVERBROAD",
        "BSA007",
    ),
    SemanticDefinition(
        "risk_unaddressed",
        "SEMANTIC_SUPPRESSION_RISK_UNADDRESSED",
        "BSA008",
    ),
)
_DEFINITION_BY_CLASSIFICATION = MappingProxyType(
    {item.classification: item for item in SEMANTIC_DEFINITIONS}
)
_DEFINITION_BY_CODE = MappingProxyType(
    {item.code: item for item in SEMANTIC_DEFINITIONS}
)


def _default_levels() -> dict[tuple[str, VerificationState], DiagnosticLevel]:
    by_code: dict[str, tuple[DiagnosticLevel, ...]] = {
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
    return {
        (definition.code, state): levels[index]
        for definition in SEMANTIC_DEFINITIONS
        for index, state in enumerate(SEMANTIC_VERIFICATION_STATES)
        for levels in (by_code[definition.code],)
    }


SEMANTIC_DEFAULT_LEVELS: Mapping[tuple[str, VerificationState], DiagnosticLevel] = (
    MappingProxyType(_default_levels())
)


@dataclass(frozen=True, slots=True)
class WinningPolicyRule:
    source: str
    position: int
    selector: str
    level: DiagnosticLevel

    def to_row(self) -> dict[str, object]:
        return {
            "source": self.source,
            "position": self.position,
            "selector": self.selector,
            "level": self.level,
        }


@dataclass(frozen=True, slots=True)
class SemanticPolicyEntry:
    code: str
    verification_state: VerificationState
    default_level: DiagnosticLevel
    level: DiagnosticLevel
    winning_rule: WinningPolicyRule


@dataclass(frozen=True, slots=True)
class SemanticPolicy:
    entries: tuple[SemanticPolicyEntry, ...]
    effective_policy_layers: tuple[str, ...]
    fail_on: tuple[Severity, ...]

    def entry_for(self, code: str, verification_state: str) -> SemanticPolicyEntry:
        state = _normalize_verification_state(verification_state)
        for entry in self.entries:
            if entry.code == code and entry.verification_state == state:
                return entry
        raise SemanticPolicyError(f"unknown semantic policy entry: {code}:{state}")


@dataclass(frozen=True, slots=True)
class SemanticDiagnosticEvidence:
    role: str
    path: str
    start_line: int
    end_line: int
    excerpt: str
    excerpt_sha256: str

    def to_row(self) -> dict[str, object]:
        return {
            "role": self.role,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "excerpt": self.excerpt,
            "excerpt_sha256": self.excerpt_sha256,
        }


@dataclass(frozen=True, slots=True)
class SemanticDiagnostic:
    code: str
    short_code: str
    classification: str
    packet_kind: str
    packet_id: str
    packet_hash: str
    finding_hash: str
    verification_state: VerificationState
    evidence: tuple[SemanticDiagnosticEvidence, ...]
    default_severity: DiagnosticLevel
    severity: DiagnosticLevel
    summary: str
    rationale: str
    analysis_key: str
    winning_policy_rule: WinningPolicyRule
    _fail_on: tuple[Severity, ...]

    @property
    def is_failure(self) -> bool:
        return (
            self.verification_state in FAILURE_AUTHORITATIVE_STATES
            and self.severity != "off"
            and self.severity in self._fail_on
        )

    def to_row(self) -> dict[str, object]:
        return {
            "code": self.code,
            "short_code": self.short_code,
            "classification": self.classification,
            "packet_kind": self.packet_kind,
            "packet_id": self.packet_id,
            "packet_hash": self.packet_hash,
            "finding_hash": self.finding_hash,
            "verification_state": self.verification_state,
            "evidence": [item.to_row() for item in self.evidence],
            "default_severity": self.default_severity,
            "severity": self.severity,
            "summary": self.summary,
            "rationale": self.rationale,
            "analysis_key": self.analysis_key,
            "winning_policy_rule": self.winning_policy_rule.to_row(),
        }


@dataclass(frozen=True, slots=True)
class FindingDebt:
    code: str
    packet_id: str
    packet_hash: str
    finding_hash: str
    verification_state: VerificationState

    def to_row(self) -> dict[str, object]:
        return {
            "code": self.code,
            "packet_id": self.packet_id,
            "packet_hash": self.packet_hash,
            "finding_hash": self.finding_hash,
            "verification_state": self.verification_state,
        }


@dataclass(frozen=True, slots=True)
class SemanticProjection:
    diagnostic: SemanticDiagnostic | None
    used_disposition: SemanticDispositionLike | None
    undisposed_finding: FindingDebt | None


@dataclass(frozen=True, slots=True)
class SemanticProjectionRun:
    diagnostics: tuple[SemanticDiagnostic, ...]
    undisposed_findings: tuple[FindingDebt, ...]
    finding_debt: tuple[FindingDebt, ...]
    unused_dispositions: tuple[SemanticDispositionLike, ...]
    finding_handling: FindingHandling

    @property
    def requires_disposition(self) -> bool:
        return self.finding_handling == "require_disposition" and bool(
            self.undisposed_findings
        )


_LEVEL_AUTHORITY = {"off": 0, "info": 1, "warning": 2, "error": 3}


def _normalize_verification_state(value: str) -> VerificationState:
    if value == "corroborated":
        return "evidence_bound"
    if value not in SEMANTIC_VERIFICATION_STATES:
        raise SemanticPolicyError(f"unknown semantic verification state: {value}")
    return value


def _verifier_context(aggregate: VerificationAggregateLike) -> VerificationState:
    context = getattr(aggregate, "context", None)
    if context not in VERIFIER_VERIFICATION_STATES:
        raise SemanticPolicyError(
            "verification aggregate context must be independently_verified, "
            "disputed_by_verifier, or verification_indeterminate"
        )
    return cast(VerificationState, context)


def materialize_semantic_policy(
    settings: DiagnosticsSettings,
    rule_origins: Sequence[PolicyRuleOriginLike],
    effective_policy_layers: Sequence[str],
) -> SemanticPolicy:
    """Resolve all 56 current semantic code/state cells with exact provenance."""

    if len(rule_origins) != len(settings.levels):
        raise SemanticPolicyError(
            "policy rule origins must be aligned one-to-one with diagnostics levels"
        )
    layers = tuple(effective_policy_layers)
    if not layers or any(
        not isinstance(layer, str) or not layer.strip() for layer in layers
    ):
        raise SemanticPolicyError("effective policy layers must be nonblank strings")
    if len(set(layers)) != len(layers):
        raise SemanticPolicyError("effective policy layers must not contain duplicates")
    for origin in rule_origins:
        if (
            not isinstance(origin.source, str)
            or not origin.source.strip()
            or isinstance(origin.position, bool)
            or not isinstance(origin.position, int)
            or origin.position < 0
        ):
            raise SemanticPolicyError(
                "policy rule origins must have valid source and position"
            )
        if origin.source not in layers:
            raise SemanticPolicyError(
                f"policy rule origin source is absent from effective layers: {origin.source}"
            )

    entries: list[SemanticPolicyEntry] = []
    for definition in SEMANTIC_DEFINITIONS:
        for state in SEMANTIC_VERIFICATION_STATES:
            level = settings.default_level
            winner: WinningPolicyRule | None = None
            for rule, origin in zip(settings.levels, rule_origins, strict=True):
                selector = _first_matching_selector(
                    rule.selectors,
                    definition,
                    state,
                )
                if selector is not None:
                    level = rule.level
                    winner = WinningPolicyRule(
                        source=origin.source,
                        position=origin.position,
                        selector=selector,
                        level=rule.level,
                    )
            if winner is None:
                raise SemanticPolicyError(
                    f"semantic policy has no winning rule for {definition.code}:{state}"
                )
            entry = SemanticPolicyEntry(
                code=definition.code,
                verification_state=state,
                default_level=SEMANTIC_DEFAULT_LEVELS[(definition.code, state)],
                level=level,
                winning_rule=winner,
            )
            _validate_failure_authority(entry, settings.fail_on, definition)
            entries.append(entry)
    return SemanticPolicy(
        entries=tuple(entries),
        effective_policy_layers=layers,
        fail_on=settings.fail_on,
    )


def _first_matching_selector(
    selectors: Sequence[str],
    definition: SemanticDefinition,
    state: VerificationState,
) -> str | None:
    for selector in selectors:
        selector_code, separator, selector_context = selector.partition(":")
        if separator and selector_context != state:
            continue
        if selector_code == "*":
            return selector
        if selector_code.endswith("*"):
            prefix = selector_code[:-1]
            if definition.code.startswith(prefix) or definition.short_code.startswith(
                prefix
            ):
                return selector
            continue
        if selector_code in (definition.code, definition.short_code):
            return selector
    return None


def _is_wildcard(selector: str) -> bool:
    return "*" in selector.partition(":")[0]


def _is_exact_authority_selector(
    selector: str,
    definition: SemanticDefinition,
    state: VerificationState,
) -> bool:
    selector_code, separator, context = selector.partition(":")
    return (
        bool(separator)
        and context == state
        and selector_code in (definition.code, definition.short_code)
        and "*" not in selector_code
    )


def _validate_failure_authority(
    entry: SemanticPolicyEntry,
    fail_on: tuple[Severity, ...],
    definition: SemanticDefinition,
) -> None:
    if (
        _is_wildcard(entry.winning_rule.selector)
        and _LEVEL_AUTHORITY[entry.level] > _LEVEL_AUTHORITY[entry.default_level]
    ):
        raise SemanticPolicyError(
            "wildcard semantic policy cannot raise packaged severity: "
            f"{entry.winning_rule.selector}"
        )
    if entry.level not in fail_on:
        return
    exact = _is_exact_authority_selector(
        entry.winning_rule.selector,
        definition,
        entry.verification_state,
    )
    if entry.verification_state == "independently_verified" and exact:
        if definition.short_code in {"BSA006", "BSA007", "BSA008"}:
            raise SemanticPolicyError(
                "suppression semantic findings have no independently_verified "
                "failure authority without a future measured qualification"
            )
        # The current analysis owner validates the required qualification
        # artifact before cache/provider construction. Policy materialization
        # preserves the user's explicit request so it can fail closed with the
        # actionable qualification problem instead of silently lowering it.
        return
    if entry.verification_state not in FAILURE_AUTHORITATIVE_STATES or not exact:
        raise SemanticPolicyError(
            "semantic failure authority requires an exact canonical or short code "
            "with human_verified or mechanically_verified context until "
            "independent-verification qualification is available: "
            f"{entry.code}:{entry.verification_state}"
        )


def finding_hash(result: CanonicalResult) -> str:
    """Hash only the structured semantic finding identity fields."""

    classification = _result_field(result, "classification")
    if (
        not isinstance(classification, str)
        or classification not in _DEFINITION_BY_CLASSIFICATION
    ):
        raise ValueError(f"classification has no semantic finding: {classification!r}")
    definition = _DEFINITION_BY_CLASSIFICATION[classification]
    evidence = _result_field(result, "evidence")
    if not isinstance(evidence, (list, tuple)):
        raise ValueError("canonical semantic result evidence must be a sequence")
    identity_evidence: list[dict[str, object]] = []
    for item in evidence:
        identity_evidence.append(
            {
                "role": _evidence_field(item, "role"),
                "path": _evidence_field(item, "path"),
                "start_line": _evidence_field(item, "start_line"),
                "end_line": _evidence_field(item, "end_line"),
                "excerpt_sha256": _evidence_field(item, "excerpt_sha256"),
            }
        )
    preimage = {
        "finding_contract_version": 1,
        "code": definition.code,
        "classification": classification,
        "packet_kind": _result_field(result, "kind"),
        "packet_id": _result_field(result, "packet_id"),
        "packet_hash": _result_field(result, "packet_hash"),
        "evidence": identity_evidence,
    }
    return hashlib.sha256(canonical_json_bytes(preimage)).hexdigest()


def project_semantic_result(
    result: CanonicalResult,
    policy: SemanticPolicy,
    dispositions: Sequence[SemanticDispositionLike] = (),
    *,
    trusted_verification_state: VerificationStateInput = "evidence_bound",
) -> SemanticProjection:
    """Project one canonical result without mutating its cached inference row."""

    disposition_by_identity = _validated_dispositions(dispositions)
    return _project_one(
        result,
        policy,
        disposition_by_identity,
        trusted_verification_state,
    )


def project_semantic_results(
    results: Sequence[CanonicalResult],
    policy: SemanticPolicy,
    dispositions: Sequence[SemanticDispositionLike] = (),
    *,
    finding_handling: str = "report",
    mechanically_verified_findings: Collection[str] = (),
    verification_aggregates: Mapping[str, VerificationAggregateLike] | None = None,
) -> SemanticProjectionRun:
    """Compose trusted observations, then project ordered finding audit state.

    Inputs are keyed by ``finding_hash`` so verifier integration cannot relabel
    a result by position. The aggregate objects stay owned by the caller and
    therefore remain available for the report even when a human or mechanical
    observation wins policy precedence.
    """

    if finding_handling not in ("allow", "report", "require_disposition"):
        raise SemanticPolicyError(
            f"unknown semantic finding handling: {finding_handling}"
        )
    mechanical_hashes = frozenset(mechanically_verified_findings)
    if any(not is_sha256_hex(item) for item in mechanical_hashes):
        raise SemanticPolicyError(
            "mechanically verified finding identities must be lowercase SHA-256"
        )
    aggregate_by_hash = dict(verification_aggregates or {})
    aggregate_states: dict[str, VerificationState] = {}
    for aggregate_finding_hash, aggregate in aggregate_by_hash.items():
        if not is_sha256_hex(aggregate_finding_hash):
            raise SemanticPolicyError(
                "verification aggregate finding identities must be lowercase SHA-256"
            )
        aggregate_states[aggregate_finding_hash] = _verifier_context(aggregate)
    disposition_by_identity = _validated_dispositions(dispositions)
    used: set[tuple[str, str, str, str]] = set()
    observed_finding_hashes: set[str] = set()
    diagnostics: list[SemanticDiagnostic] = []
    undisposed: list[FindingDebt] = []
    for result in results:
        classification = _result_field(result, "classification")
        result_finding_hash = None if classification == "ok" else finding_hash(result)
        trusted_state: VerificationState = "evidence_bound"
        if result_finding_hash is not None:
            observed_finding_hashes.add(result_finding_hash)
            if result_finding_hash in mechanical_hashes:
                trusted_state = "mechanically_verified"
            elif result_finding_hash in aggregate_states:
                trusted_state = aggregate_states[result_finding_hash]
        projection = _project_one(
            result,
            policy,
            disposition_by_identity,
            trusted_state,
        )
        if projection.diagnostic is not None:
            diagnostics.append(projection.diagnostic)
        if projection.undisposed_finding is not None:
            undisposed.append(projection.undisposed_finding)
        if projection.used_disposition is not None:
            used.add(_disposition_identity(projection.used_disposition))
    unknown_mechanical = mechanical_hashes - observed_finding_hashes
    unknown_aggregates = aggregate_states.keys() - observed_finding_hashes
    if unknown_mechanical or unknown_aggregates:
        raise SemanticPolicyError(
            "verification observations must address a projected semantic finding"
        )
    unused = tuple(
        disposition
        for disposition in dispositions
        if _disposition_identity(disposition) not in used
    )
    debt = tuple(undisposed) if finding_handling != "allow" else ()
    return SemanticProjectionRun(
        diagnostics=tuple(diagnostics),
        undisposed_findings=tuple(undisposed),
        finding_debt=debt,
        unused_dispositions=unused,
        finding_handling=cast(FindingHandling, finding_handling),
    )


def _project_one(
    result: CanonicalResult,
    policy: SemanticPolicy,
    disposition_by_identity: Mapping[
        tuple[str, str, str, str], SemanticDispositionLike
    ],
    trusted_verification_state: VerificationStateInput,
) -> SemanticProjection:
    trusted_state = _normalize_verification_state(trusted_verification_state)
    classification = _result_field(result, "classification")
    if classification == "ok":
        return SemanticProjection(None, None, None)
    if (
        not isinstance(classification, str)
        or classification not in _DEFINITION_BY_CLASSIFICATION
    ):
        raise ValueError(f"classification has no semantic finding: {classification!r}")
    definition = _DEFINITION_BY_CLASSIFICATION[classification]
    identity_hash = finding_hash(result)
    identity = (
        definition.code,
        cast(str, _result_field(result, "packet_id")),
        cast(str, _result_field(result, "packet_hash")),
        identity_hash,
    )
    disposition = disposition_by_identity.get(identity)
    state = trusted_state
    if disposition is not None:
        state = (
            "human_verified" if disposition.status == "accepted" else "human_rejected"
        )
    entry = policy.entry_for(definition.code, state)
    diagnostic = SemanticDiagnostic(
        code=definition.code,
        short_code=definition.short_code,
        classification=classification,
        packet_kind=cast(str, _result_field(result, "kind")),
        packet_id=cast(str, _result_field(result, "packet_id")),
        packet_hash=cast(str, _result_field(result, "packet_hash")),
        finding_hash=identity_hash,
        verification_state=state,
        evidence=_diagnostic_evidence(result),
        default_severity=entry.default_level,
        severity=entry.level,
        summary=cast(str, _result_field(result, "summary")),
        rationale=cast(str, _result_field(result, "rationale")),
        analysis_key=cast(str, _result_field(result, "analysis_key")),
        winning_policy_rule=entry.winning_rule,
        _fail_on=policy.fail_on,
    )
    finding = None
    if disposition is None:
        finding = FindingDebt(
            code=definition.code,
            packet_id=diagnostic.packet_id,
            packet_hash=diagnostic.packet_hash,
            finding_hash=identity_hash,
            verification_state=state,
        )
    return SemanticProjection(diagnostic, disposition, finding)


def _diagnostic_evidence(
    result: CanonicalResult,
) -> tuple[SemanticDiagnosticEvidence, ...]:
    raw = _result_field(result, "evidence")
    if not isinstance(raw, (list, tuple)):
        raise ValueError("canonical semantic result evidence must be a sequence")
    return tuple(
        SemanticDiagnosticEvidence(
            role=cast(str, _evidence_field(item, "role")),
            path=cast(str, _evidence_field(item, "path")),
            start_line=cast(int, _evidence_field(item, "start_line")),
            end_line=cast(int, _evidence_field(item, "end_line")),
            excerpt=cast(str, _evidence_field(item, "excerpt")),
            excerpt_sha256=cast(str, _evidence_field(item, "excerpt_sha256")),
        )
        for item in raw
    )


def _result_field(result: CanonicalResult, name: str) -> object:
    if isinstance(result, CanonicalSemanticResult):
        return getattr(result, name)
    try:
        return result[name]
    except KeyError:
        raise ValueError(f"canonical semantic result is missing {name!r}") from None


def _evidence_field(item: object, name: str) -> object:
    if isinstance(item, Mapping):
        try:
            return item[name]
        except KeyError:
            raise ValueError(
                f"canonical semantic evidence is missing {name!r}"
            ) from None
    try:
        return getattr(item, name)
    except AttributeError:
        raise ValueError(f"canonical semantic evidence is missing {name!r}") from None


def _validated_dispositions(
    dispositions: Sequence[SemanticDispositionLike],
) -> dict[tuple[str, str, str, str], SemanticDispositionLike]:
    validated: dict[tuple[str, str, str, str], SemanticDispositionLike] = {}
    for disposition in dispositions:
        if disposition.code not in _DEFINITION_BY_CODE:
            raise DispositionError(
                "semantic disposition code must be a canonical long code"
            )
        if (
            not isinstance(disposition.packet_id, str)
            or not disposition.packet_id.strip()
        ):
            raise DispositionError("semantic disposition packet_id must be nonblank")
        if not is_sha256_hex(disposition.packet_hash):
            raise DispositionError(
                "semantic disposition packet_hash must be lowercase SHA-256"
            )
        if not is_sha256_hex(disposition.finding_hash):
            raise DispositionError(
                "semantic disposition finding_hash must be lowercase SHA-256"
            )
        if disposition.status not in ("accepted", "rejected"):
            raise DispositionError(
                "semantic disposition status must be accepted or rejected"
            )
        if not isinstance(disposition.reason, str) or not disposition.reason.strip():
            raise DispositionError("semantic disposition reason must be nonblank")
        identity = _disposition_identity(disposition)
        if identity in validated:
            raise DispositionError("duplicate semantic disposition identity")
        validated[identity] = disposition
    return validated


def _disposition_identity(
    disposition: SemanticDispositionLike,
) -> tuple[str, str, str, str]:
    return (
        disposition.code,
        disposition.packet_id,
        disposition.packet_hash,
        disposition.finding_hash,
    )
