"""Shared fail-closed identities for the RQ3-REAL-C4 I1-R1 repair."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable, Mapping, Sequence


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RESTRICTED = HERE / "restricted_internal"
DOWNLOADS = Path("/Users/liuming/Downloads")
STARTING_HEAD = "795ec13ae752c0f52d83aaf2a7692d092490e286"
BRANCH = "research/rq3-real-c4-i1-route-integration"
SEED = 20260901
MODEL = "gpt-4o-mini-2024-07-18"
GENERATION_PROMPT_SHA256 = (
    "41748d1f3a69ce6623e607551a8473228c0724871e16e392ecd7872b4e550b21"
)
GENERATION_SCHEMA_V2_SHA256 = (
    "485dbdc6af48577808d3e6a51fc9811e54f7a8f670f50f92c5bbb64ee382f873"
)
GENERATION_CONFIGURATION_V2_SHA256 = (
    "3a589b593c964288ab5976718dd4fcb1e2d45186d978ee201b235a7aaf25059c"
)
HMAC_KEY_COMMITMENT = (
    "199db23c86b0dd824edaff2d5b40da12761c9aa76bf2fb9d902952ab376481b5"
)

SCIENTIFIC_SHA256 = {
    "c4_real_p3_route_source_manifest_v1.json": "01c921e8087e2d26599a860cf495a036461b7c884d620e2f6d4906636124d85a",
    "c4_real_p3_routes_frozen_v1.csv": "93bb24252e879158836df6a2ca9a6f23a1c659d90cd3c4e32fc1a5794e4256fb",
    "c4_real_p3_routes_frozen_v1.jsonl": "522267d1ce0871426c1c094ee0dd2dc2a1ca23337a77d459f9206f9869fa5268",
    "c4_real_precomputed_p3_route_cache_frozen_v1.json": "1bba37fefb3d266f8b2a5fc108a7e250d70a42d174d3aed8886d3e46e1155478",
    "c4_real_b4_unused_route_bits_source_audit_v1.json": "3ae4ff64d8339bf4e4cbd71dd41a3dcd3ff7b88612760d6fbe1ce4445c2278c2",
    "c4_real_memory_preconditioning_receipts_v1.jsonl": "5b1eb6a84bc97e5524bace086f346c4d27214bb5805a8f8efc2ad1535d6bec9d",
    "c4_real_memory_preconditioning_selected_envelopes_v1.jsonl": "db4cdc14606356224a5ab64bff328d0142c26cbbc05d98ddf21ef0377ab6bc0e",
    "c4_real_memory_preconditioning_summary_v1.json": "cc70af5b40429a21be2b33260e07d03650355abd1094756b3239da7b436fc0ad",
    "c4_real_condition_mechanism_records_frozen_v1.jsonl": "053217a461985280746b981c4184633e7b4fe21c6b980a1e86fab249ef21e7c0",
    "c4_real_condition_execution_traces_frozen_v1.jsonl": "321f8ba37727d0b659dde9e5d3d9fcddf1f6aba58328473eb9f24cbe001b36b5",
    "c4_real_condition_dashboard_evidence_frozen_v1.jsonl": "2e5021c659cc4a04236213d6fc9926000ba1568e5f533ac81cdf75d186014139",
    "c4_real_condition_rag_results_frozen_v1.jsonl": "6fbc8856ae477ca34c592e565db1900046f8bf4d86be47933d7715d4640419aa",
    "c4_real_condition_memory_results_frozen_v1.jsonl": "5cd2467ba025b5436d72a32be736930f6c1283889e9a3cf6bdbecf63b949f63e",
    "c4_real_condition_planner_results_frozen_v1.jsonl": "4a9d59e0a16ca480f8e4855a9321a7ade10d8ec703bf68716b1bffe7f885bc87",
    "c4_real_condition_compiled_evidence_frozen_v1.jsonl": "2c9606f5eeb649bb33448aad82c0c34ec3cf92cb13dd2ec670fab250232a0310",
    "c4_real_mechanism_replay_summary_v1.json": "19c92fb882f906247bfa1c194a8d7832fed1fddee02fdfa8b366de678d81ddad",
    "c4_real_condition_applicability_maps_frozen_v1.jsonl": "1f5b159b3d80506c32265624a8f4e5866af4dba996dd0f62abf53dff93f31084",
}

V1_REQUEST_ARTIFACT_SHA256 = {
    "c4_real_unique_generation_request_manifest_frozen_v1.jsonl": "ebf47f37f042b441fa2be42f3fe6d72930304c5e25f1f57d42c70fdf2557082b",
    "c4_real_generation_request_deduplication_summary_v1.json": "505bb278b1b19e3cd4bda97bc2d25ed8e3a2c61de6b3bd208a69e2890a264684",
    "c4_real_generation_shard_summary_v1.json": "ec39dd81bcc66d27c083c04525e4289d676e15b3f11a43dfe286ce19bfacbc34",
    "c4_real_restricted_mapping_metadata_v1.json": "7e85a68b998c03909d918979baec91be4541126df2364e33e68456b1f03774f7",
    "c4_real_generation_package_manifest_v1.json": "96f9214d9218f7855bdeedbb57ca9ca10fa212b97f1c7d66610cd9458e81509c",
}

V1_RESTRICTED_SHA256 = {
    "c4_real_condition_generation_payload_registry_frozen_v1.jsonl": "69635803376d5e6d953b9ec3d747651f79e7a0000c3eaafe669df34b127db8b6",
    "c4_real_condition_to_unique_request_mapping_frozen_v1.csv": "c7372095ed184ed0bdb18b52e8f9c0b5a8ef968bc583bc7b22cc652dd49838fe",
    "c4_real_response_to_condition_mapping_frozen_v1.csv": "432a8ea549b65bf7b45901f89affbae41ce6143ac5f180eb98ae347b2b02b217",
    "c4_real_response_to_mode_mapping_frozen_v1.csv": "7a59cfc7d4fe76df9370bd304cdb3a8e3c4708d1c6db268e74601d9d6494fb81",
    "c4_real_response_to_scenario_mapping_frozen_v1.csv": "c15f4dc5e96f34916b8d1123c40375b380ca3525a8eb54e38660d2343331f562",
}

OLD_PACKAGE_SHA256 = {
    "A": "515e34c32f27f01bff743072fd58c5a8dc29f9feb550f54f99893bcf7485d5cf",
    "B": "d4d079c5509115f7140e1675ebf6ebb4234ba5b1af0ddd1da4d5fa4d0a93ee01",
    "C": "3276d303a2b8a62be4c732eef65069fc22b87d754d40a1ac0b8f3bb3c42f3086",
}
OLD_PACKAGE_PATHS = {
    shard: DOWNLOADS
    / f"C4_REAL_GENERATION_SHARD_{shard}_EXECUTION_PACKAGE_R1_2026-09-01.zip"
    for shard in "ABC"
}
NEW_PACKAGE_PATHS = {
    shard: DOWNLOADS
    / f"C4_REAL_GENERATION_SHARD_{shard}_EXECUTION_PACKAGE_R2_2026-09-01.zip"
    for shard in "ABC"
}

AUDIT_PHRASES = (
    "Reviewed output-level Dashboard evidence",
    "raw DataFrames were not available in I0",
    "TRACK_M_RESEARCH_ONLY_NOT_C4_INTEGRATED",
    "P3_GATE_NOT_EXECUTED_IN_TRACK_M",
    "NO_ELIGIBLE_ACTIVE_MEMORY",
    "Frozen legacy lexical scoring",
    "FROZEN_OUTPUT_LEVEL_EVIDENCE_PACK",
    "FROZEN_STRUCTURED_OUTPUT",
    "FROZEN_TYPED_EMPTY_OUTPUT_LEVEL_PACK",
)
V2_PROHIBITED_MESSAGE_KEYS = frozenset(
    {
        "schema_version",
        "evidence_type",
        "source_kind",
        "source_type",
        "typed_absence",
        "limitations",
    }
)
V2_PROHIBITED_TEXT = re.compile(
    r"(?:TRACK_M_RESEARCH_ONLY_NOT_C4_INTEGRATED|"
    r"P3_GATE_NOT_EXECUTED_IN_TRACK_M|NO_ELIGIBLE_ACTIVE_MEMORY|"
    r"FROZEN_(?:OUTPUT_LEVEL_EVIDENCE_PACK|STRUCTURED_OUTPUT|TYPED_EMPTY_OUTPUT_LEVEL_PACK)|"
    r"Reviewed output-level Dashboard evidence|raw DataFrames were not available in I0|"
    r"Frozen legacy lexical scoring|no dense representation|"
    r"c4-real-provider-evidence-projection-v1)",
    re.IGNORECASE,
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} is not an object")
        rows.append(value)
    return rows


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def assert_sha256(path: Path, expected: str, label: str) -> None:
    observed = sha256_file(path)
    if observed != expected:
        raise ValueError(f"{label} SHA-256 mismatch: {observed}")
