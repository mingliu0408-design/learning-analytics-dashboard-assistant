"""Canonical local-only component and composite input-binding fingerprints."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
import hashlib
import json
import math
import re
from typing import Any

from evaluation.capability_routing_rq2c0_r4_v1.composite_payload_episode_validator_v1_3 import (
    COMPOSITE_VALIDATOR_ID,
)
from evaluation.capability_routing_rq2c0_r4_v1.payload_linkage_schema import (
    MemoryEpisodeV1_2,
    MemoryPayloadRefV1_2,
    MemoryPayloadV1_2,
)

from . import INTERVAL_CONTRACT_ID, R5_VALIDATOR_ID


EPISODE_DOMAIN = b"RQ2_MEMORY_EPISODE_BINDING_V1\x00"
PAYLOAD_REF_DOMAIN = b"RQ2_MEMORY_PAYLOAD_REF_BINDING_V1\x00"
PAYLOAD_DOMAIN = b"RQ2_MEMORY_PRIVATE_PAYLOAD_BINDING_V1\x00"
BUNDLE_DOMAIN = b"RQ2_VALIDATED_MEMORY_BUNDLE_V1_4\x00"
CONTRACT_HASH_DOMAIN = b"RQ2_VALIDATION_CONTRACT_V1_4\x00"


class FingerprintError(ValueError):
    pass


@dataclass(frozen=True)
class ComponentFingerprintsV1:
    episode_fingerprint: str
    payload_ref_fingerprint: str
    payload_fingerprint: str
    input_binding_fingerprint: str


def _canonical_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _canonical_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise FingerprintError("CANONICAL_MAPPING_KEY_NOT_STRING")
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise FingerprintError("NON_FINITE_NUMBER_PROHIBITED")
        return value
    raise FingerprintError("UNSUPPORTED_CANONICAL_VALUE")


def canonical_component_bytes_v1(value: Any) -> bytes:
    try:
        return json.dumps(
            _canonical_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        if isinstance(exc, FingerprintError):
            raise
        raise FingerprintError("CANONICAL_SERIALISATION_FAILED") from exc


def _domain_hash(domain: bytes, payload: bytes) -> str:
    return hashlib.sha256(domain + payload).hexdigest()


def episode_fingerprint_v1(episode: MemoryEpisodeV1_2) -> str:
    return _domain_hash(EPISODE_DOMAIN, canonical_component_bytes_v1(episode))


def payload_ref_fingerprint_v1(payload_ref: MemoryPayloadRefV1_2) -> str:
    return _domain_hash(PAYLOAD_REF_DOMAIN, canonical_component_bytes_v1(payload_ref))


def payload_fingerprint_v1(payload: MemoryPayloadV1_2) -> str:
    return _domain_hash(PAYLOAD_DOMAIN, canonical_component_bytes_v1(payload))


def input_binding_fingerprint_v1_4(
    episode_fingerprint: str,
    payload_ref_fingerprint: str,
    payload_fingerprint: str,
) -> str:
    values = (episode_fingerprint, payload_ref_fingerprint, payload_fingerprint)
    if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in values):
        raise FingerprintError("INVALID_COMPONENT_FINGERPRINT")
    payload = (
        episode_fingerprint.encode("ascii")
        + b"\x00"
        + payload_ref_fingerprint.encode("ascii")
        + b"\x00"
        + payload_fingerprint.encode("ascii")
        + b"\x00"
        + COMPOSITE_VALIDATOR_ID.encode("ascii")
        + b"\x00"
        + R5_VALIDATOR_ID.encode("ascii")
    )
    return _domain_hash(BUNDLE_DOMAIN, payload)


def component_fingerprints_v1(
    episode: MemoryEpisodeV1_2,
    payload_ref: MemoryPayloadRefV1_2,
    payload: MemoryPayloadV1_2,
) -> ComponentFingerprintsV1:
    episode_hash = episode_fingerprint_v1(episode)
    reference_hash = payload_ref_fingerprint_v1(payload_ref)
    payload_hash = payload_fingerprint_v1(payload)
    return ComponentFingerprintsV1(
        episode_fingerprint=episode_hash,
        payload_ref_fingerprint=reference_hash,
        payload_fingerprint=payload_hash,
        input_binding_fingerprint=input_binding_fingerprint_v1_4(
            episode_hash, reference_hash, payload_hash
        ),
    )


def validation_contract_hash_v1_4() -> str:
    descriptor = {
        "bundle_schema": "ValidatedPersistentMemoryBundleV1_4",
        "fingerprint_contract": "VALIDATED_MEMORY_BUNDLE_FINGERPRINT_V1",
        "identifier_contract": "GOVERNED_OPAQUE_IDENTIFIER_V1",
        "interval_contract": INTERVAL_CONTRACT_ID,
        "r4_validator_id": COMPOSITE_VALIDATOR_ID,
        "r5_validator_id": R5_VALIDATOR_ID,
    }
    return _domain_hash(CONTRACT_HASH_DOMAIN, canonical_component_bytes_v1(descriptor))


def bundle_fingerprint_contract() -> dict[str, Any]:
    return {
        "schema_version": "bundle-fingerprint-contract-v1",
        "stage": "RQ2-C0-R5",
        "status": "FROZEN",
        "contract_id": "VALIDATED_MEMORY_BUNDLE_FINGERPRINT_V1",
        "canonical_json": {
            "dataclass_fields_by_name": True,
            "mapping_keys_sorted": True,
            "sequence_order_preserved": True,
            "string_exact": True,
            "ensure_ascii": False,
            "sort_keys": True,
            "separators": [",", ":"],
            "nan_and_infinity_allowed": False,
            "encoding": "UTF-8",
        },
        "episode_domain_hex": EPISODE_DOMAIN.hex(),
        "payload_ref_domain_hex": PAYLOAD_REF_DOMAIN.hex(),
        "private_payload_domain_hex": PAYLOAD_DOMAIN.hex(),
        "composite_domain_hex": BUNDLE_DOMAIN.hex(),
        "r4_validator_id": COMPOSITE_VALIDATOR_ID,
        "r5_validator_id": R5_VALIDATOR_ID,
        "validation_contract_hash": validation_contract_hash_v1_4(),
        "private_payload_text_participates_in_local_fingerprint": True,
        "private_payload_text_tracked": False,
        "private_payload_text_review_zip_eligible": False,
        "integrity_binding": True,
        "secret_mac": False,
        "digital_signature": False,
        "caller_identity_authentication": False,
    }
