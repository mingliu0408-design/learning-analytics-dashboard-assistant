"""Strict structured write policy for persistent learner Memory.

No extraction model is called here.  A future extractor may only propose the
six fields in :class:`StructuredMemoryCandidate`; deterministic policy remains
authoritative and all tests use mock candidates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import math
import re
import unicodedata
from typing import Any, Mapping

from .c4_memory_store import (
    CONSENT_STATUSES,
    MEMORY_TYPES,
    C4MemoryStore,
    C4MemoryStoreError,
    MemoryRecord,
    normalise_timestamp,
    sha256_object,
    sha256_text,
)


OPERATIONS = ("ADD", "UPDATE", "SUPERSEDE", "DELETE", "NOOP")
MINIMUM_WRITE_CONFIDENCE = 0.80
ALLOWED_CLAIM_BASES = ("EXPLICIT_USER_STATEMENT", "VERIFIED_SYSTEM_EVENT")
FORBIDDEN_CLAIM_BASES = (
    "ASSISTANT_ADVICE",
    "MODEL_INFERENCE",
    "INFERRED_PERSONALITY",
    "INFERRED_ABILITY",
    "UNVERIFIED_DASHBOARD_INTERPRETATION",
    "UNRELATED_SENSITIVE_INFORMATION",
)
CANDIDATE_FIELDS = (
    "operation",
    "memory_type",
    "content",
    "target_memory_id",
    "confidence",
    "evidence_span",
)
SENSITIVE_IDENTIFIER_RE = re.compile(
    r"\b(?:passport(?:\s+number)?|social\s+security(?:\s+number)?|ssn|"
    r"bank\s+account|credit\s+card|national\s+id|driver(?:'s)?\s+licen[cs]e|"
    r"medical\s+record|home\s+address|phone\s+number|email\s+address)\b",
    flags=re.IGNORECASE,
)


class C4MemoryWriteError(ValueError):
    """Raised only for malformed candidate contracts, not policy rejection."""


def canonicalise_content(value: str) -> str:
    if not isinstance(value, str):
        raise C4MemoryWriteError("CONTENT_MUST_BE_STRING")
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        raise C4MemoryWriteError("EMPTY_CONTENT")
    if len(value) > 4000:
        raise C4MemoryWriteError("CONTENT_TOO_LONG")
    return value


def _normalised_evidence(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().casefold()


@dataclass(frozen=True)
class StructuredMemoryCandidate:
    operation: str
    memory_type: str | None
    content: str | None
    target_memory_id: str | None
    confidence: float
    evidence_span: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StructuredMemoryCandidate":
        if not isinstance(value, Mapping):
            raise C4MemoryWriteError("CANDIDATE_MUST_BE_OBJECT")
        keys = set(value)
        required = set(CANDIDATE_FIELDS)
        if keys != required:
            missing = sorted(required - keys)
            extra = sorted(keys - required)
            raise C4MemoryWriteError(f"STRICT_CANDIDATE_KEYS_MISMATCH:missing={missing}:extra={extra}")
        if not isinstance(value["operation"], str):
            raise C4MemoryWriteError("OPERATION_MUST_BE_STRING")
        if value["memory_type"] is not None and not isinstance(value["memory_type"], str):
            raise C4MemoryWriteError("MEMORY_TYPE_MUST_BE_STRING_OR_NULL")
        if value["content"] is not None and not isinstance(value["content"], str):
            raise C4MemoryWriteError("CONTENT_MUST_BE_STRING_OR_NULL")
        if value["target_memory_id"] is not None and not isinstance(value["target_memory_id"], str):
            raise C4MemoryWriteError("TARGET_MEMORY_ID_MUST_BE_STRING_OR_NULL")
        if not isinstance(value["evidence_span"], str):
            raise C4MemoryWriteError("EVIDENCE_SPAN_MUST_BE_STRING")
        confidence = value["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise C4MemoryWriteError("CONFIDENCE_MUST_BE_NUMBER")
        candidate = cls(
            operation=value["operation"],
            memory_type=value["memory_type"],
            content=value["content"],
            target_memory_id=value["target_memory_id"],
            confidence=float(confidence),
            evidence_span=value["evidence_span"],
        )
        candidate.validate_shape()
        return candidate

    def validate_shape(self) -> None:
        if self.operation not in OPERATIONS:
            raise C4MemoryWriteError("INVALID_OPERATION")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise C4MemoryWriteError("INVALID_CONFIDENCE")
        if not self.evidence_span.strip() and self.operation != "NOOP":
            raise C4MemoryWriteError("EMPTY_EVIDENCE_SPAN")
        if self.operation in {"ADD", "UPDATE", "SUPERSEDE"}:
            if self.memory_type not in MEMORY_TYPES:
                raise C4MemoryWriteError("INVALID_MEMORY_TYPE")
            if self.content is None:
                raise C4MemoryWriteError("CONTENT_REQUIRED")
            canonicalise_content(self.content)
        elif self.memory_type is not None:
            raise C4MemoryWriteError("MEMORY_TYPE_MUST_BE_NULL")
        if self.operation == "ADD" and self.target_memory_id is not None:
            raise C4MemoryWriteError("ADD_TARGET_MUST_BE_NULL")
        if self.operation in {"UPDATE", "SUPERSEDE", "DELETE"} and not self.target_memory_id:
            raise C4MemoryWriteError("TARGET_MEMORY_ID_REQUIRED")
        if self.operation == "NOOP" and self.target_memory_id is not None:
            raise C4MemoryWriteError("NOOP_TARGET_MUST_BE_NULL")
        if self.operation == "SUPERSEDE" and self.memory_type != "CORRECTION":
            raise C4MemoryWriteError("SUPERSEDE_REQUIRES_CORRECTION_TYPE")
        if self.memory_type == "CORRECTION" and self.operation != "SUPERSEDE":
            raise C4MemoryWriteError("CORRECTION_REQUIRES_SUPERSEDE")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WritePolicyResult:
    accepted: bool
    requested_operation: str
    applied_operation: str
    reason_code: str
    memory_id: str | None
    target_memory_id: str | None
    duplicate_memory_id: str | None
    before_status: str | None
    after_status: str | None
    record: MemoryRecord | None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.record is not None:
            value["record"] = self.record.as_dict()
        return value


class C4MemoryWriter:
    """Apply structured candidates under deterministic, fail-closed policy."""

    def __init__(
        self,
        store: C4MemoryStore,
        *,
        minimum_confidence: float = MINIMUM_WRITE_CONFIDENCE,
    ) -> None:
        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError("INVALID_MINIMUM_CONFIDENCE")
        self.store = store
        self.minimum_confidence = float(minimum_confidence)

    def _reject(
        self,
        *,
        student_id: str,
        candidate: StructuredMemoryCandidate,
        reason_code: str,
        event_at: str,
        duplicate_memory_id: str | None = None,
    ) -> WritePolicyResult:
        self.store.record_noop(
            student_id,
            reason_code=reason_code,
            event_at=event_at,
            memory_id=duplicate_memory_id,
            target_memory_id=candidate.target_memory_id,
        )
        return WritePolicyResult(
            accepted=False,
            requested_operation=candidate.operation,
            applied_operation="NOOP",
            reason_code=reason_code,
            memory_id=None,
            target_memory_id=candidate.target_memory_id,
            duplicate_memory_id=duplicate_memory_id,
            before_status=None,
            after_status=None,
            record=None,
        )

    @staticmethod
    def _memory_id(
        *,
        student_id: str,
        source_session_id: str,
        source_turn_id: str,
        candidate: StructuredMemoryCandidate,
        content_sha256: str,
        created_at: str,
    ) -> str:
        identity = {
            "student_id": student_id,
            "source_session_id": source_session_id,
            "source_turn_id": source_turn_id,
            "operation": candidate.operation,
            "memory_type": candidate.memory_type,
            "target_memory_id": candidate.target_memory_id,
            "content_sha256": content_sha256,
            "created_at": created_at,
        }
        return "mem_" + sha256_object(identity)[:24]

    def apply_candidate(
        self,
        *,
        student_id: str,
        source_session_id: str,
        source_turn_id: str,
        source_text: str,
        candidate: StructuredMemoryCandidate | Mapping[str, Any],
        source_role: str = "USER",
        claim_basis: str = "EXPLICIT_USER_STATEMENT",
        unrelated_sensitive_information: bool = False,
        importance: float = 0.5,
        consent_status: str = "GRANTED",
        event_at: str | datetime | None = None,
        valid_from: str | datetime | None = None,
        valid_to: str | datetime | None = None,
    ) -> WritePolicyResult:
        if not isinstance(candidate, StructuredMemoryCandidate):
            candidate = StructuredMemoryCandidate.from_mapping(candidate)
        else:
            candidate.validate_shape()
        observed_at = normalise_timestamp(event_at)
        source_role = str(source_role).upper()
        claim_basis = str(claim_basis).upper()

        if candidate.operation == "NOOP":
            return self._reject(
                student_id=student_id,
                candidate=candidate,
                reason_code="EXPLICIT_NOOP",
                event_at=observed_at,
            )
        if not self.store.is_memory_enabled(student_id):
            return self._reject(
                student_id=student_id,
                candidate=candidate,
                reason_code="MEMORY_DISABLED_FOR_LEARNER",
                event_at=observed_at,
            )
        if source_role == "ASSISTANT" or claim_basis == "ASSISTANT_ADVICE":
            return self._reject(
                student_id=student_id,
                candidate=candidate,
                reason_code="ASSISTANT_ADVICE_NOT_LEARNER_FACT",
                event_at=observed_at,
            )
        if claim_basis in FORBIDDEN_CLAIM_BASES:
            return self._reject(
                student_id=student_id,
                candidate=candidate,
                reason_code=claim_basis,
                event_at=observed_at,
            )
        if claim_basis not in ALLOWED_CLAIM_BASES:
            return self._reject(
                student_id=student_id,
                candidate=candidate,
                reason_code="UNAUTHORISED_CLAIM_BASIS",
                event_at=observed_at,
            )
        if (claim_basis == "EXPLICIT_USER_STATEMENT" and source_role != "USER") or (
            claim_basis == "VERIFIED_SYSTEM_EVENT" and source_role != "SYSTEM"
        ):
            return self._reject(
                student_id=student_id,
                candidate=candidate,
                reason_code="SOURCE_ROLE_BASIS_MISMATCH",
                event_at=observed_at,
            )
        if unrelated_sensitive_information:
            return self._reject(
                student_id=student_id,
                candidate=candidate,
                reason_code="UNRELATED_SENSITIVE_INFORMATION",
                event_at=observed_at,
            )
        if candidate.operation in {"ADD", "UPDATE", "SUPERSEDE"} and SENSITIVE_IDENTIFIER_RE.search(
            str(candidate.content or "")
        ):
            return self._reject(
                student_id=student_id,
                candidate=candidate,
                reason_code="UNRELATED_SENSITIVE_INFORMATION",
                event_at=observed_at,
            )
        if candidate.confidence < self.minimum_confidence:
            return self._reject(
                student_id=student_id,
                candidate=candidate,
                reason_code="LOW_CONFIDENCE",
                event_at=observed_at,
            )
        source_norm = _normalised_evidence(source_text)
        evidence_norm = _normalised_evidence(candidate.evidence_span)
        if not source_norm or not evidence_norm or evidence_norm not in source_norm:
            return self._reject(
                student_id=student_id,
                candidate=candidate,
                reason_code="EVIDENCE_SPAN_NOT_IN_SOURCE",
                event_at=observed_at,
            )
        if consent_status not in CONSENT_STATUSES or consent_status == "WITHDRAWN":
            return self._reject(
                student_id=student_id,
                candidate=candidate,
                reason_code="CONSENT_NOT_ACTIVE",
                event_at=observed_at,
            )
        if not 0.0 <= importance <= 1.0:
            raise C4MemoryWriteError("INVALID_IMPORTANCE")

        target = None
        if candidate.target_memory_id is not None:
            target = self.store.get_memory(student_id, candidate.target_memory_id)
            if target is None:
                return self._reject(
                    student_id=student_id,
                    candidate=candidate,
                    reason_code="TARGET_MEMORY_NOT_FOUND_OR_CROSS_LEARNER",
                    event_at=observed_at,
                )
            if target.status != "ACTIVE":
                return self._reject(
                    student_id=student_id,
                    candidate=candidate,
                    reason_code="TARGET_MEMORY_NOT_ACTIVE",
                    event_at=observed_at,
                )
            if not (
                target.valid_from <= observed_at
                and (target.valid_to is None or observed_at < target.valid_to)
            ):
                return self._reject(
                    student_id=student_id,
                    candidate=candidate,
                    reason_code="TARGET_MEMORY_NOT_TEMPORALLY_VALID",
                    event_at=observed_at,
                )

        if candidate.operation == "DELETE":
            try:
                deleted = self.store.delete_memory(
                    student_id,
                    str(candidate.target_memory_id),
                    event_at=observed_at,
                    reason_code="EXPLICIT_USER_DELETE",
                )
            except C4MemoryStoreError as exc:
                return self._reject(
                    student_id=student_id,
                    candidate=candidate,
                    reason_code=str(exc),
                    event_at=observed_at,
                )
            return WritePolicyResult(
                accepted=True,
                requested_operation="DELETE",
                applied_operation="DELETE",
                reason_code="EXPLICIT_USER_DELETE",
                memory_id=deleted.memory_id,
                target_memory_id=deleted.memory_id,
                duplicate_memory_id=None,
                before_status=target.status if target else None,
                after_status="DELETED",
                record=deleted,
            )

        content = canonicalise_content(str(candidate.content))
        content_norm = _normalised_evidence(content)
        if content_norm not in evidence_norm:
            return self._reject(
                student_id=student_id,
                candidate=candidate,
                reason_code="CONTENT_NOT_SUPPORTED_BY_EVIDENCE_SPAN",
                event_at=observed_at,
            )
        content_sha = sha256_text(content)
        duplicate = self.store.find_active_duplicate(
            student_id,
            str(candidate.memory_type),
            content_sha,
            at=observed_at,
        )
        if duplicate is not None:
            return self._reject(
                student_id=student_id,
                candidate=candidate,
                reason_code="DUPLICATE_ACTIVE_FACT",
                event_at=observed_at,
                duplicate_memory_id=duplicate.memory_id,
            )
        if candidate.operation == "UPDATE" and target is not None and candidate.memory_type != target.memory_type:
            return self._reject(
                student_id=student_id,
                candidate=candidate,
                reason_code="UPDATE_TYPE_MISMATCH",
                event_at=observed_at,
            )

        starts_at = normalise_timestamp(valid_from or observed_at)
        ends_at = normalise_timestamp(valid_to) if valid_to is not None else None
        if ends_at is not None and ends_at <= starts_at:
            raise C4MemoryWriteError("INVALID_VALIDITY_INTERVAL")
        memory_id = self._memory_id(
            student_id=student_id,
            source_session_id=source_session_id,
            source_turn_id=source_turn_id,
            candidate=candidate,
            content_sha256=content_sha,
            created_at=observed_at,
        )
        version = (target.version + 1) if target is not None else 1
        conflict_key = (
            (target.conflict_key or target.memory_id)
            if target is not None
            else "conflict_" + sha256_object({"student_id": student_id, "memory_id": memory_id})[:20]
        )
        record = MemoryRecord(
            memory_id=memory_id,
            student_id=student_id,
            memory_type=str(candidate.memory_type),
            content=content,
            source_session_id=str(source_session_id),
            source_turn_id=str(source_turn_id),
            created_at=observed_at,
            valid_from=starts_at,
            valid_to=ends_at,
            last_confirmed_at=observed_at,
            status="ACTIVE",
            importance=float(importance),
            confidence=float(candidate.confidence),
            supersedes_memory_id=target.memory_id if target is not None else None,
            consent_status=consent_status,
            content_sha256=content_sha,
            version=version,
            conflict_key=conflict_key,
            deletion_event_sha256=None,
        )
        if candidate.operation == "ADD":
            self.store.add_memory(record)
            before_status = None
        else:
            try:
                self.store.replace_memory(
                    student_id=student_id,
                    target_memory_id=str(candidate.target_memory_id),
                    replacement=record,
                    operation=candidate.operation,
                    reason_code=(
                        "EXPLICIT_USER_CORRECTION"
                        if candidate.operation == "SUPERSEDE"
                        else "EXPLICIT_USER_UPDATE"
                    ),
                )
            except C4MemoryStoreError as exc:
                return self._reject(
                    student_id=student_id,
                    candidate=candidate,
                    reason_code=str(exc),
                    event_at=observed_at,
                )
            before_status = target.status if target else None
        return WritePolicyResult(
            accepted=True,
            requested_operation=candidate.operation,
            applied_operation=candidate.operation,
            reason_code=(
                "EXPLICIT_USER_CORRECTION"
                if candidate.operation == "SUPERSEDE"
                else "WRITE_AUTHORISED"
            ),
            memory_id=record.memory_id,
            target_memory_id=candidate.target_memory_id,
            duplicate_memory_id=None,
            before_status=before_status,
            after_status="ACTIVE",
            record=record,
        )
