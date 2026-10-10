"""RQ2-D0-R2 exact reference binding and grouping-semantics repair.

This package is contract and synthetic-validation code only.  Importing it must
not inspect raw Track B, generate a real blinding key, create a real D1 lock, or
produce reviewer packets.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DOC_ROOT = ROOT / "docs/thesis_mainline/rq2"

START_BRANCH = "research/rq2-d0-r1-d1-prearm-repair"
START_HEAD = "484f90d00c69748e84945e96c7c732ba23884919"
START_PARENT = "efe00bdee99c99f02b48db99f3880dfc9bee8761"
RESULT_BRANCH = "research/rq2-d0-r2-exact-reference-policy-repair"

R1_REVIEW_ZIP_NAME = "RQ2_D0_R1_D1_PREARM_REPAIR_REVIEW_2026-08-28.zip"
R1_REVIEW_ZIP_SHA256 = (
    "f7dc5ba36fb1c3d3a53ea85d1c7a24bba145ef528cbdce5c5ec7292c685176a5"
)
D0_REVIEW_ZIP_NAME = "RQ2_D0_TRACK_B_FINAL_CONTRACT_REVIEW_2026-08-27.zip"
D0_REVIEW_ZIP_SHA256 = (
    "fe2870e5fb47f17a34f1adf768c005043dff457a7941dee2ae95e9ab937c0ed7"
)
C1_R1_REVIEW_ZIP_NAME = (
    "RQ2_C1_R1_OFFLINE_SAFETY_ISOLATION_REPAIR_REVIEW_2026-08-27.zip"
)
C1_R1_REVIEW_ZIP_SHA256 = (
    "571168da5c1f6a42401542a5fe3d8f6c6121cab8717295bbd19a71e5fdbc713a"
)
SAFE_SCHEMA_ZIP_NAME = "RQ2_TRACK_B_SAFE_SCHEMA_AUTHORITY_2026-08-27.zip"
SAFE_SCHEMA_ZIP_SHA256 = (
    "11a1bcba3b4a6589f8947a3f24ec3b227f43a57a8d5fcf4ceb5adc5c568fd30e"
)

REFERENCE_CONTRACT_ID = "RQ2_TRACK_B_CONTAMINATION_REFERENCE_AUTHORITY_V1"
AUTHORITY_COMMITMENT_DOMAIN = b"RQ2_TRACK_B_CONTAMINATION_AUTHORITY_V1_1\x00"
NORMALISER_CONTRACT_ID = (
    "RQ2D0_V1_NFKC_CASEFOLD_REMOVE_UNICODE_PUNCTUATION_COLLAPSE_WHITESPACE_"
    "CANONICAL_JSON_HISTORY_V1"
)

MANIFEST_RELATIVE_PATH = (
    "evaluation/capability_routing_rq2d0_r1_v1/"
    "track_b_contamination_reference_manifest_v1.json"
)
BUNDLE_RELATIVE_PATH = (
    "evaluation/capability_routing_rq2d0_r1_v1/local_contamination/"
    "track_b_contamination_reference_bundle_v1.jsonl"
)
SOURCE_RESOLUTION_RELATIVE_PATH = (
    "evaluation/capability_routing_rq2d0_r1_v1/"
    "contamination_reference_source_resolution_v1.json"
)

MANIFEST_FILE_SHA256 = (
    "b8126ba2ee7f07283e3c453ea9da530e310ece8970e91fb2fa702278359088b6"
)
MANIFEST_SIZE_BYTES = 4_791
BUNDLE_FILE_SHA256 = (
    "70c97fc6ac07994593fe207a4a95dbff08b67ce1f8ca7d068f067b01cc993a1f"
)
BUNDLE_SIZE_BYTES = 393_475
BUNDLE_RECORD_COUNT = 680
SOURCE_RESOLUTION_FILE_SHA256 = (
    "276a6a8d2ce37e6ead5ffb1bab265f0e608b0c62f3723116630ee001a4862a9c"
)
SOURCE_RESOLUTION_SIZE_BYTES = 4_034

PARTITION_SPECS = (
    (
        "RQ1_TRAIN",
        318,
        "057c427c6bbaa2ce6b6f71d3355ce5e3f5e886119e7a0bebc5bf9408a201069a",
        "RQ1_EXPANDED_TRAIN_MANIFEST_V2",
        "623bcdeaad62ae20559c616dc57aedfb22bd2d006f0beb6888da88d549c40805",
    ),
    (
        "RQ1_DEV",
        84,
        "041056bdbc7e450da35dea240bd3fc7fa8b48c18e02c1b2c397cf350908495a2",
        "RQ1_FUNCTIONAL_QA_DEV_MANIFEST_V2",
        "7765ffbbe48fcde543b60561f22a03cef596235af07eed58540aacb64334f09f",
    ),
    (
        "C0_FROZEN_62_CANDIDATES",
        62,
        "4167fd7683a6ea29ee8b21e0b6d553729498878d6a5d73bb6f241e74b1e9f269",
        "C0_APPROVED_INTENT_INDEX_V1",
        "b4cac34df91c074a4a2fa85e4ccc52623563f3358fe44938771f8303f00b6be9",
    ),
    (
        "TRACK_A_SAFE_IDENTITIES",
        128,
        "cb8ce0f5ebf23f65a44e2f03daefcd9f4ceef9ff23b44998a00c19d42167da6f",
        "PRIMARY_V3_TRACK_A_RQ1_FINAL_GOLD_V1",
        "5d40f0a4a6b460e77271ee9815fce1b0954c1d7e05c7a4cd2f5d8e28ff09eb8f",
    ),
    (
        "AUTHENTIC22",
        22,
        "72c4c0f78d291322494c4412678b8467ea5453b66656d82cf711b5d782928b47",
        "AUTHENTIC_CODEBOOK_CALIBRATION_GOLD_V1",
        "96e23f1131c14e5fb627d711a19295594a56bd3daaaef4cdf0ebce71a7af0346",
    ),
    (
        "SYNTHETIC35",
        35,
        "5f442ae5f8c9c93d49de593f1a6cd4b335ec16f485494c271dd157b095b517d2",
        "SYNTHETIC_COVERAGE_STRESS_GOLD_V1",
        "9e01b400a6daf9fed13e6cca2bdfe2d714785741b34f2266bbf6c36e8ca08399",
    ),
    (
        "CONTEXT_MISSING3",
        3,
        "38c1093c3b04bcbade15aa21b3e0c35441a3bbe8099cb3758c9ca4a040095592",
        "AUTHENTIC_CONTEXT_MISSING_QUALITATIVE_REGISTRY_V1",
        "2f89ccaec37b890ec97a415b76169996d2ae0a6d8f20ebb910410f1c5801c412",
    ),
    (
        "CONTROLLED_MECHANISM_FIXTURE28",
        28,
        "6b5ff5a55d583cd534a48f1ae8d1e6a9159670c0b269b4b97c1e5c6546cafba0",
        "RQ2_P2_CONTROLLED_MECHANISM_FIXTURE_BANK_V1",
        "eb2210162a810a4e733af03218117f783a28ca8d52214231ae4fcd20cc956c5e",
    ),
)

HARD_PARTITIONS = (
    "RQ1_TRAIN",
    "RQ1_DEV",
    "C0_FROZEN_62_CANDIDATES",
    "TRACK_A_SAFE_IDENTITIES",
    "SYNTHETIC35",
)
SENSITIVITY_PARTITIONS = (
    "AUTHENTIC22",
    "CONTEXT_MISSING3",
    "CONTROLLED_MECHANISM_FIXTURE28",
)

SAFE_JSON_FILENAMES = (
    "rq2d0_r2_preflight_report_v1.json",
    "frozen_contamination_reference_authority_v1_1.json",
    "exact_reference_binding_contract_v1.json",
    "track_b_contamination_policy_v1_2.json",
    "track_b_grouping_semantics_contract_v1.json",
    "track_b_packet_generation_state_machine_v1_2.json",
    "rq2d0_r2_synthetic_validation_v1.json",
)
DOC_FILENAMES = (
    "RQ2D0_R2_EXACT_REFERENCE_AUTHORITY_BINDING.md",
    "RQ2D0_R2_CONTAMINATION_IDENTITY_AND_GROUPING_SEMANTICS.md",
    "RQ2D0_R2_FINAL_D1_PREARM_RUNBOOK.md",
)
CHECKSUM_NAME = "rq2d0_r2_output_checksums_v1.sha256"
REVIEW_ZIP_NAME = "RQ2_D0_R2_EXACT_REFERENCE_POLICY_REPAIR_REVIEW_2026-08-28.zip"


def canonical_json_bytes(value: Any, *, pretty: bool = True) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2 if pretty else None,
            sort_keys=True,
            separators=None if pretty else (",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
