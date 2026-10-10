"""Read-only identity gate and leakage-safe loader for the RQ2-B Gold.

The natural-language inputs, human labels, and split-only metadata are split
at the load boundary.  In particular, neither source role nor scenario family
is present on :class:`RoutingCaseInput`; callers must explicitly opt in to the
separate label or split objects when evaluating predictions.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]

CAPABILITIES = (
    "dashboard_evidence",
    "course_retrieval",
    "episodic_memory",
    "planning",
    "safe_direct_response",
    "clarification",
)

EXPECTED_GOLD_BUNDLE_SHA256 = (
    "9957bbea0e723203718155f8974db5476c23d8a5239a4c66e76b2ade9a5ea18c"
)
EXPECTED_GOLD_MANIFEST_SHA256 = (
    "1c41fd4f81d41fde15dcf10981b242ce7615071e1177ce555f7e1aebae85c831"
)
EXPECTED_GOLD_POLICY_SHA256 = (
    "c0810ad557bcc99f8b3d97d8f8e1bc690b59f6fb889d010511e2b17716047ab9"
)
EXPECTED_COVERAGE_SHA256 = (
    "05af9a8f74e3395b340b5f6bcd0555c45fe02130aa2616886385ad208029aa7c"
)
EXPECTED_CANONICALISATION_MANIFEST_SHA256 = (
    "704631a25c023ebae063aac0c4c03362025899ceb3c472afee531f97dff3c8c5"
)
EXPECTED_SOURCE_MAPPING_SHA256 = (
    "c7b840ebb7e8809a1f9223924db9088f75f788f650d82b1332fe5fad5aafc09e"
)
EXPECTED_COMBINED_BANK_SHA256 = (
    "2046ee91e83feb1194544698419ec1710bd471246fa4d1f43990b28c92840f22"
)
EXPECTED_SYNTHETIC_SOURCE_SHA256 = (
    "a791a154638e59436867c50e3fcfc4d15e2d2fef47ee2c52937892b49b0092a6"
)

R2B_OUTPUT_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/rq2a_r2b_output_checksums_v1.sha256"
)
CANONICALISATION_MANIFEST_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/"
    "adjudication_canonicalisation_manifest_v1.json"
)
GOLD_MANIFEST_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/"
    "source_separated_capability_gold_manifest_v1.json"
)
GOLD_POLICY_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/capability_gold_policy_v1_1.json"
)
COVERAGE_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/synthetic_coverage_validation_v1.json"
)
ATTESTATION_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/"
    "human_adjudicator_independence_attestation_v1.json"
)
AMENDMENT_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/"
    "synthetic_clarification_eligibility_amendment_v1.json"
)
AUTHENTIC_LABELS_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/"
    "authentic_codebook_calibration_gold_labels_v1.jsonl"
)
SYNTHETIC_LABELS_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/"
    "synthetic_coverage_stress_gold_labels_v1.jsonl"
)
REGISTRY_LABELS_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/"
    "authentic_context_missing_registry_labels_v1.jsonl"
)
AUTHENTIC_FULL_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/local_gold/"
    "authentic_codebook_calibration_gold_v1.jsonl"
)
SYNTHETIC_FULL_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/local_gold/"
    "synthetic_coverage_stress_gold_v1.jsonl"
)
REGISTRY_FULL_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/local_gold/"
    "authentic_context_missing_qualitative_registry_v1.jsonl"
)
COMBINED_FULL_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/local_gold/"
    "combined_capability_development_gold_v1.jsonl"
)
SOURCE_MAPPING_RELATIVE = Path(
    "evaluation/capability_routing_v1_r1c/local_artifacts/"
    "source_blinded_review_id_mapping_v1_3.jsonl"
)
COMBINED_BANK_RELATIVE = Path(
    "evaluation/capability_routing_v1_r1c/local_case_bank/"
    "combined_calibration_review_bank_v1_3.jsonl"
)
SYNTHETIC_SOURCE_RELATIVE = Path(
    "evaluation/capability_routing_v1_r1c/local_case_bank/"
    "synthetic_coverage_stress_bank_v1.jsonl"
)
R1C_BANK_MANIFEST_RELATIVE = Path(
    "evaluation/capability_routing_v1_r1c/"
    "combined_calibration_bank_manifest_v1_3.json"
)

EXPECTED_MEMBERS: dict[Path, tuple[str, int]] = {
    AUTHENTIC_LABELS_RELATIVE: (
        "adf46c2b2f6e7cdf8f35a29cbae14a35e0d23f11d81638331fe1dec838c07d99",
        22,
    ),
    SYNTHETIC_LABELS_RELATIVE: (
        "e8b6ebfd04d3048b0bfec67513c3b60f413a9c66731e40a45337b5fc2d5e99e9",
        35,
    ),
    REGISTRY_LABELS_RELATIVE: (
        "d5b56bee1cba8d96da7b64dc72c9cfa8c16289a984ffbaf34e7ca94b82137ee1",
        3,
    ),
    AUTHENTIC_FULL_RELATIVE: (
        "96e23f1131c14e5fb627d711a19295594a56bd3daaaef4cdf0ebce71a7af0346",
        22,
    ),
    SYNTHETIC_FULL_RELATIVE: (
        "9e01b400a6daf9fed13e6cca2bdfe2d714785741b34f2266bbf6c36e8ca08399",
        35,
    ),
    REGISTRY_FULL_RELATIVE: (
        "2f89ccaec37b890ec97a415b76169996d2ae0a6d8f20ebb910410f1c5801c412",
        3,
    ),
    COMBINED_FULL_RELATIVE: (
        "7ce41b4c6691cdcbfe16bf5669b1fd00fe98eca6eb3ec792e4b609aa47be8541",
        57,
    ),
}

LABEL_FIELDS = (
    "review_case_id",
    "source_role",
    "gold_inclusion_status",
    "gold_decision_source",
    "context_link_valid",
    "context_sufficient",
    "capability_unambiguous",
    "context_resolution_required",
    *CAPABILITIES,
    "forbidden_capabilities",
    "missing_context_disposition",
)
FULL_TEXT_EXTRA_FIELDS = (
    "canonical_case_id",
    "source_bank_alias",
    "current_query",
    "current_page",
    "necessary_conversation_history",
    "turn_index",
    "query_rewrite_performed",
    "assistant_context_attached",
)
FULL_TEXT_FIELDS = frozenset((*LABEL_FIELDS, *FULL_TEXT_EXTRA_FIELDS))

# These may be consumed by evaluation code but must never be attributes of the
# router-input object below.
GOLD_ONLY_FIELDS = frozenset(
    {
        "source_role",
        "gold_inclusion_status",
        "gold_decision_source",
        "context_link_valid",
        "context_sufficient",
        "capability_unambiguous",
        "context_resolution_required",
        *CAPABILITIES,
        "forbidden_capabilities",
        "missing_context_disposition",
    }
)


class GoldPreflightError(RuntimeError):
    """Raised when a frozen input or a leakage boundary is violated."""


@dataclass(frozen=True)
class RoutingCaseInput:
    """The complete and exclusive natural-language input visible to a router."""

    case_id: str
    current_query: str
    current_page: str
    conversation_history: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class CapabilityLabels:
    """Human Gold retained outside the router-input object."""

    case_id: str
    context_resolution_required: bool
    dashboard_evidence: bool
    course_retrieval: bool
    episodic_memory: bool
    planning: bool
    safe_direct_response: bool
    clarification: bool
    forbidden_capabilities: tuple[str, ...]
    context_sufficient: str
    capability_unambiguous: str
    context_link_valid: str
    gold_inclusion_status: str
    gold_decision_source: str
    missing_context_disposition: str | None

    @property
    def required_capabilities(self) -> tuple[str, ...]:
        return tuple(name for name in CAPABILITIES if getattr(self, name))


@dataclass(frozen=True)
class SplitMetadata:
    """Opaque identity/source/split metadata, never a prediction feature."""

    case_id: str
    canonical_case_id: str
    source_role: str
    scenario_family: str | None


@dataclass(frozen=True)
class GoldExample:
    router_input: RoutingCaseInput
    labels: CapabilityLabels
    split: SplitMetadata


@dataclass(frozen=True)
class GoldPreflightResult:
    authentic_gold: tuple[GoldExample, ...]
    synthetic_gold: tuple[GoldExample, ...]
    authentic_context_missing_registry: tuple[GoldExample, ...]
    identity: Mapping[str, Any]

    @property
    def combined_gold(self) -> tuple[GoldExample, ...]:
        return tuple(
            sorted(
                (*self.authentic_gold, *self.synthetic_gold),
                key=lambda example: example.router_input.case_id,
            )
        )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )


def _verified_bytes(root: Path, relative: Path, expected_sha256: str) -> bytes:
    path = root / relative
    if not path.is_file() or path.is_symlink():
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
    value = path.read_bytes()
    if sha256_bytes(value) != expected_sha256:
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
    return value


def _json(relative: Path, root: Path) -> dict[str, Any]:
    value = json.loads((root / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
    return value


def _jsonl_bytes(value: bytes) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in value.decode("utf-8").splitlines() if line]
    if not all(isinstance(row, dict) for row in rows):
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
    return rows


def _validate_output_checksums(root: Path) -> int:
    manifest = root / R2B_OUTPUT_CHECKSUM_RELATIVE
    if not manifest.is_file() or manifest.is_symlink():
        raise GoldPreflightError("BLOCKED_RQ2_B_STARTING_STATE_MISMATCH")
    observed: set[str] = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        try:
            expected, relative = line.split("  ", 1)
        except ValueError as exc:
            raise GoldPreflightError(
                "BLOCKED_RQ2_B_STARTING_STATE_MISMATCH"
            ) from exc
        if relative in observed or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise GoldPreflightError("BLOCKED_RQ2_B_STARTING_STATE_MISMATCH")
        observed.add(relative)
        path = root / relative
        if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
            raise GoldPreflightError("BLOCKED_RQ2_B_STARTING_STATE_MISMATCH")
    if len(observed) != 27:
        raise GoldPreflightError("BLOCKED_RQ2_B_STARTING_STATE_MISMATCH")
    return len(observed)


def _validate_bundle(root: Path, manifest: Mapping[str, Any]) -> None:
    members = manifest.get("gold_members")
    if not isinstance(members, Mapping) or set(members) != {
        relative.as_posix() for relative in EXPECTED_MEMBERS
    }:
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
    for relative, (expected_sha256, expected_count) in EXPECTED_MEMBERS.items():
        descriptor = members.get(relative.as_posix())
        if not isinstance(descriptor, Mapping):
            raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
        path = root / relative
        data = _verified_bytes(root, relative, expected_sha256)
        if (
            descriptor.get("sha256") != expected_sha256
            or descriptor.get("record_count") != expected_count
            or descriptor.get("size_bytes") != len(data)
            or descriptor.get("local_only") != ("/local_gold/" in relative.as_posix())
        ):
            raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
    descriptor = {
        "schema_version": "source-separated-gold-bundle-descriptor-v1",
        "gold_members": dict(sorted(members.items())),
        "supporting_contract_sha256": {
            "human_adjudicator_independence_attestation_v1.json": sha256_file(
                root / ATTESTATION_RELATIVE
            ),
            "synthetic_clarification_eligibility_amendment_v1.json": sha256_file(
                root / AMENDMENT_RELATIVE
            ),
            "capability_gold_policy_v1_1.json": sha256_file(root / GOLD_POLICY_RELATIVE),
            "synthetic_coverage_validation_v1.json": sha256_file(root / COVERAGE_RELATIVE),
        },
    }
    if (
        manifest.get("source_separated_gold_bundle_sha256")
        != EXPECTED_GOLD_BUNDLE_SHA256
        or sha256_bytes(canonical_json_bytes(descriptor))
        != EXPECTED_GOLD_BUNDLE_SHA256
    ):
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")


def _label_values(row: Mapping[str, Any]) -> CapabilityLabels:
    if set(row) != set(LABEL_FIELDS):
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
    for name in ("context_resolution_required", *CAPABILITIES):
        if row.get(name) not in {"YES", "NO"}:
            raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
    forbidden = row.get("forbidden_capabilities")
    if not isinstance(forbidden, list) or any(name not in CAPABILITIES for name in forbidden):
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
    active = {name for name in CAPABILITIES if row[name] == "YES"}
    if active & set(forbidden):
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
    return CapabilityLabels(
        case_id=str(row["review_case_id"]),
        context_resolution_required=row["context_resolution_required"] == "YES",
        **{name: row[name] == "YES" for name in CAPABILITIES},
        forbidden_capabilities=tuple(name for name in CAPABILITIES if name in forbidden),
        context_sufficient=str(row["context_sufficient"]),
        capability_unambiguous=str(row["capability_unambiguous"]),
        context_link_valid=str(row["context_link_valid"]),
        gold_inclusion_status=str(row["gold_inclusion_status"]),
        gold_decision_source=str(row["gold_decision_source"]),
        missing_context_disposition=(
            str(row["missing_context_disposition"])
            if row.get("missing_context_disposition") is not None
            else None
        ),
    )


def _history(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
    # Copy only the production-input history.  Reviewer/adjudicator fields can
    # therefore never hitchhike into a router call through shared row objects.
    return tuple(dict(item) for item in value)


def _build_examples(
    *,
    full_rows: Sequence[Mapping[str, Any]],
    label_rows: Sequence[Mapping[str, Any]],
    mapping_by_review: Mapping[str, Mapping[str, Any]],
    scenario_family_by_canonical: Mapping[str, str],
    required_source: str,
) -> tuple[GoldExample, ...]:
    label_by_id = {str(row["review_case_id"]): row for row in label_rows}
    if len(label_by_id) != len(label_rows):
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
    examples: list[GoldExample] = []
    for row in full_rows:
        if set(row) != FULL_TEXT_FIELDS:
            raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
        case_id = str(row["review_case_id"])
        label_row = label_by_id.get(case_id)
        source = mapping_by_review.get(case_id)
        if label_row is None or source is None:
            raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
        if any(row[field] != label_row[field] for field in LABEL_FIELDS):
            raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
        canonical_case_id = str(row["canonical_case_id"])
        if (
            source.get("source_bank") != required_source
            or str(source.get("canonical_case_id")) != canonical_case_id
            or row.get("source_role") != required_source
        ):
            raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
        family = scenario_family_by_canonical.get(canonical_case_id)
        if required_source == "synthetic" and not family:
            raise GoldPreflightError("BLOCKED_RQ2_B_FAMILY_SPLIT_MISMATCH")
        if required_source != "synthetic" and family is not None:
            raise GoldPreflightError("BLOCKED_RQ2_B_FAMILY_SPLIT_MISMATCH")
        router_input = RoutingCaseInput(
            case_id=case_id,
            current_query=str(row["current_query"]),
            current_page=str(row["current_page"]),
            conversation_history=_history(row["necessary_conversation_history"]),
        )
        if set(vars(router_input)) & GOLD_ONLY_FIELDS or "scenario_family" in vars(router_input):
            raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_FEATURE_LEAKAGE")
        examples.append(
            GoldExample(
                router_input=router_input,
                labels=_label_values(label_row),
                split=SplitMetadata(
                    case_id=case_id,
                    canonical_case_id=canonical_case_id,
                    source_role=required_source,
                    scenario_family=family,
                ),
            )
        )
    if set(label_by_id) != {item.router_input.case_id for item in examples}:
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
    return tuple(sorted(examples, key=lambda item: item.router_input.case_id))


def load_and_validate_gold(root: Path = ROOT) -> GoldPreflightResult:
    """Validate every frozen identity and return leakage-separated datasets."""

    checksum_count = _validate_output_checksums(root)
    _verified_bytes(
        root,
        CANONICALISATION_MANIFEST_RELATIVE,
        EXPECTED_CANONICALISATION_MANIFEST_SHA256,
    )
    _verified_bytes(root, GOLD_POLICY_RELATIVE, EXPECTED_GOLD_POLICY_SHA256)
    _verified_bytes(root, COVERAGE_RELATIVE, EXPECTED_COVERAGE_SHA256)
    _verified_bytes(root, SOURCE_MAPPING_RELATIVE, EXPECTED_SOURCE_MAPPING_SHA256)
    _verified_bytes(root, COMBINED_BANK_RELATIVE, EXPECTED_COMBINED_BANK_SHA256)
    _verified_bytes(root, SYNTHETIC_SOURCE_RELATIVE, EXPECTED_SYNTHETIC_SOURCE_SHA256)
    manifest_bytes = _verified_bytes(
        root, GOLD_MANIFEST_RELATIVE, EXPECTED_GOLD_MANIFEST_SHA256
    )
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict):
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
    if (
        manifest.get("status") != "HUMAN_GOLD_FROZEN"
        or manifest.get("authentic_gold_count") != 22
        or manifest.get("synthetic_gold_count") != 35
        or manifest.get("context_missing_registry_count") != 3
        or manifest.get("combined_gold_count") != 57
        or manifest.get("human_only_freeze") is not True
        or manifest.get("gold_frozen_before_unblinding") is not True
        or any(
            manifest.get(field) is not False
            for field in (
                "hidden_proposal_used_to_form_gold",
                "legacy_output_used_to_form_gold",
                "c0_used_to_form_gold",
                "intent_prediction_used_to_form_gold",
            )
        )
    ):
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
    _validate_bundle(root, manifest)

    member_rows: dict[Path, list[dict[str, Any]]] = {}
    for relative, (expected_hash, expected_count) in EXPECTED_MEMBERS.items():
        rows = _jsonl_bytes(_verified_bytes(root, relative, expected_hash))
        if len(rows) != expected_count:
            raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
        member_rows[relative] = rows

    mapping = _jsonl_bytes(
        _verified_bytes(root, SOURCE_MAPPING_RELATIVE, EXPECTED_SOURCE_MAPPING_SHA256)
    )
    if len(mapping) != 60 or any(
        set(row) != {"review_case_id", "canonical_case_id", "source_bank"}
        for row in mapping
    ):
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
    mapping_by_review = {str(row["review_case_id"]): row for row in mapping}
    if len(mapping_by_review) != 60 or Counter(
        str(row["source_bank"]) for row in mapping
    ) != {"authentic": 25, "synthetic": 35}:
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")

    combined_bank = _jsonl_bytes(
        _verified_bytes(root, COMBINED_BANK_RELATIVE, EXPECTED_COMBINED_BANK_SHA256)
    )
    if len(combined_bank) != 60 or len(
        {str(row.get("canonical_case_id")) for row in combined_bank}
    ) != 60:
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
    combined_by_canonical = {
        str(row["canonical_case_id"]): row for row in combined_bank
    }
    for source in mapping:
        bank = combined_by_canonical.get(str(source["canonical_case_id"]))
        if bank is None or bank.get("source_bank") != source["source_bank"]:
            raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")

    # The split projection is deliberately constructed before any Gold row is
    # combined with it, and discards all expected-route/proposal-like metadata.
    synthetic_source = _jsonl_bytes(
        _verified_bytes(root, SYNTHETIC_SOURCE_RELATIVE, EXPECTED_SYNTHETIC_SOURCE_SHA256)
    )
    if len(synthetic_source) != 35:
        raise GoldPreflightError("BLOCKED_RQ2_B_FAMILY_SPLIT_MISMATCH")
    scenario_family_by_canonical = {
        str(row.get("case_id")): str(row.get("scenario_family") or "")
        for row in synthetic_source
    }
    if (
        len(scenario_family_by_canonical) != 35
        or any(not family for family in scenario_family_by_canonical.values())
        or len(set(scenario_family_by_canonical.values())) != 18
    ):
        raise GoldPreflightError("BLOCKED_RQ2_B_FAMILY_SPLIT_MISMATCH")
    synthetic_mapping_ids = {
        str(row["canonical_case_id"])
        for row in mapping
        if row["source_bank"] == "synthetic"
    }
    if set(scenario_family_by_canonical) != synthetic_mapping_ids:
        raise GoldPreflightError("BLOCKED_RQ2_B_FAMILY_SPLIT_MISMATCH")
    # Identity link includes text/history parity, but only the four input
    # fields and the case/family split projection survive this function.
    for source_row in synthetic_source:
        combined = combined_by_canonical[str(source_row["case_id"])]
        if (
            source_row.get("current_query") != combined.get("current_query")
            or source_row.get("current_page") != combined.get("current_page")
            or source_row.get("conversation_history")
            != combined.get("necessary_conversation_history")
        ):
            raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")

    authentic = _build_examples(
        full_rows=member_rows[AUTHENTIC_FULL_RELATIVE],
        label_rows=member_rows[AUTHENTIC_LABELS_RELATIVE],
        mapping_by_review=mapping_by_review,
        scenario_family_by_canonical=scenario_family_by_canonical,
        required_source="authentic",
    )
    synthetic = _build_examples(
        full_rows=member_rows[SYNTHETIC_FULL_RELATIVE],
        label_rows=member_rows[SYNTHETIC_LABELS_RELATIVE],
        mapping_by_review=mapping_by_review,
        scenario_family_by_canonical=scenario_family_by_canonical,
        required_source="synthetic",
    )
    registry = _build_examples(
        full_rows=member_rows[REGISTRY_FULL_RELATIVE],
        label_rows=member_rows[REGISTRY_LABELS_RELATIVE],
        mapping_by_review=mapping_by_review,
        scenario_family_by_canonical=scenario_family_by_canonical,
        required_source="authentic",
    )
    combined_rows = member_rows[COMBINED_FULL_RELATIVE]
    expected_combined = sorted(
        [
            *member_rows[AUTHENTIC_FULL_RELATIVE],
            *member_rows[SYNTHETIC_FULL_RELATIVE],
        ],
        key=lambda row: str(row["review_case_id"]),
    )
    if combined_rows != expected_combined:
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
    all_case_ids = {
        example.router_input.case_id for example in (*authentic, *synthetic, *registry)
    }
    if len(all_case_ids) != 60 or len(authentic) != 22 or len(synthetic) != 35 or len(registry) != 3:
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")

    r1c_manifest = _json(R1C_BANK_MANIFEST_RELATIVE, root)
    if (
        r1c_manifest.get("local_synthetic_bank_sha256")
        != EXPECTED_SYNTHETIC_SOURCE_SHA256
        or r1c_manifest.get("local_combined_bank_sha256")
        != EXPECTED_COMBINED_BANK_SHA256
        or r1c_manifest.get("source_blinded_mapping_sha256")
        != EXPECTED_SOURCE_MAPPING_SHA256
        or r1c_manifest.get("synthetic_case_count") != 35
    ):
        raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_IDENTITY")
    return GoldPreflightResult(
        authentic_gold=authentic,
        synthetic_gold=synthetic,
        authentic_context_missing_registry=registry,
        identity={
            "status": "PASS",
            "gold_bundle_sha256": EXPECTED_GOLD_BUNDLE_SHA256,
            "gold_manifest_sha256": EXPECTED_GOLD_MANIFEST_SHA256,
            "gold_policy_sha256": EXPECTED_GOLD_POLICY_SHA256,
            "coverage_validation_sha256": EXPECTED_COVERAGE_SHA256,
            "output_checksum_count": checksum_count,
            "authentic_gold_count": 22,
            "synthetic_gold_count": 35,
            "authentic_context_missing_registry_count": 3,
            "combined_gold_count": 57,
            "synthetic_family_count": 18,
            "scenario_family_used_only_for_split": True,
            "router_input_gold_field_count": 0,
        },
    )


def assert_router_inputs_leakage_safe(
    inputs: Iterable[RoutingCaseInput],
) -> None:
    """Static/runtime boundary assertion suitable for tests and finalisation."""

    expected = {"case_id", "current_query", "current_page", "conversation_history"}
    for value in inputs:
        if set(vars(value)) != expected or set(vars(value)) & GOLD_ONLY_FIELDS:
            raise GoldPreflightError("BLOCKED_RQ2_B_GOLD_FEATURE_LEAKAGE")
