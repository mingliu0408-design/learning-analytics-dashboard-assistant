"""Pseudonymous scope-ID validation, domain-separated hashing, and namespace binding."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any


SCOPE_HASH_CONTRACT_ID = "RQ2_MEMORY_SCOPE_V1"
SCOPE_HASH_DOMAIN = b"RQ2_MEMORY_SCOPE_V1\x00"
STORAGE_NAMESPACE_PREFIX = "persistent-memory-v1:"
MAX_SCOPE_ID_UTF8_BYTES = 256
FIXED_TEST_SCOPE_ID = "student-001"
FIXED_TEST_SCOPE_HASH = (
    "7009109fb754ac52ffee19d6f31728e3104738435141358c56f4aaa461b7d684"
)


class ScopeContractError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def validate_pseudonymous_student_scope_id_v1(student_scope_id: str) -> None:
    if not isinstance(student_scope_id, str) or not student_scope_id:
        raise ScopeContractError("INVALID_PSEUDONYMOUS_SCOPE_ID")
    if student_scope_id != student_scope_id.strip():
        raise ScopeContractError("SCOPE_ID_SURROUNDING_WHITESPACE")
    if "\x00" in student_scope_id:
        raise ScopeContractError("SCOPE_ID_NUL_PROHIBITED")
    if unicodedata.normalize("NFC", student_scope_id) != student_scope_id:
        raise ScopeContractError("SCOPE_ID_NOT_NFC")
    try:
        encoded = student_scope_id.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ScopeContractError("INVALID_PSEUDONYMOUS_SCOPE_ID") from exc
    if len(encoded) > MAX_SCOPE_ID_UTF8_BYTES:
        raise ScopeContractError("SCOPE_ID_TOO_LONG")


def derive_student_scope_hash_v1(student_scope_id: str) -> str:
    validate_pseudonymous_student_scope_id_v1(student_scope_id)
    return hashlib.sha256(
        SCOPE_HASH_DOMAIN + student_scope_id.encode("utf-8")
    ).hexdigest()


def derive_storage_namespace_v1(student_scope_hash: str) -> str:
    if not isinstance(student_scope_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", student_scope_hash
    ):
        raise ScopeContractError("INVALID_STUDENT_SCOPE_HASH")
    return STORAGE_NAMESPACE_PREFIX + student_scope_hash


def validate_storage_namespace_v1(
    storage_namespace: str, student_scope_hash: str
) -> None:
    expected = derive_storage_namespace_v1(student_scope_hash)
    if (
        not isinstance(storage_namespace, str)
        or "/" in storage_namespace
        or "\\" in storage_namespace
        or ".." in storage_namespace
        or "://" in storage_namespace
        or storage_namespace != expected
    ):
        raise ScopeContractError("STORAGE_NAMESPACE_MISMATCH")


def student_scope_hash_contract() -> dict[str, Any]:
    return {
        "schema_version": "student-scope-hash-contract-v1",
        "stage": "RQ2-C0-R4",
        "status": "FROZEN",
        "contract_id": SCOPE_HASH_CONTRACT_ID,
        "identifier_role": "LOCAL_PSEUDONYMOUS_OPAQUE_IDENTIFIER",
        "raw_pii_prohibited_before_interface": True,
        "identifier_schema": {
            "non_empty": True,
            "unicode_normalisation": "NFC_REQUIRED",
            "surrounding_whitespace": "PROHIBITED",
            "nul_character": "PROHIBITED",
            "maximum_utf8_bytes": MAX_SCOPE_ID_UTF8_BYTES,
            "casefold": False,
            "trim": False,
            "punctuation_removal": False,
        },
        "hash_algorithm": "SHA-256",
        "domain_separator_hex": SCOPE_HASH_DOMAIN.hex(),
        "salt_used": False,
        "secret_used": False,
        "environment_value_used": False,
        "random_value_used": False,
        "password_hashing_claim": False,
        "fixed_test_vector": {
            "student_scope_id": FIXED_TEST_SCOPE_ID,
            "expected_hash": FIXED_TEST_SCOPE_HASH,
        },
        "storage_namespace": {
            "derivation": "persistent-memory-v1:<derived_student_scope_hash>",
            "caller_supplied_arbitrary_namespace_allowed": False,
            "path_inference_allowed": False,
            "path_separators_allowed": False,
            "path_traversal_allowed": False,
            "uri_allowed": False,
            "absolute_path_allowed": False,
        },
    }
