#!/usr/bin/env python3
"""Build the offline RQ3 REAL C4 R3D1-R2 pre-execution repair.

The builder reads the immutable R3D1-R1 Judge and Human Packages, performs the
independent audits required by R3D1-R2, stages every derived artifact, runs only
offline/mocked tests, and then materialises new R2 files once.  It has no
Provider transport, scoring, rating, or Streamlit path.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import hmac
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any, Iterable, Mapping, Sequence
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

try:
    from judge_package_validator_v2 import validate_package_dir
    from judge_result_parser_v2 import (
        PRIMARY_CRITERIA,
        SCORE_FIELDS,
        TRANSPORT_SCHEMA_VERSION,
        canonical_json_bytes,
        parse_judge_result,
    )
except ImportError:  # pragma: no cover - repository package import
    from .judge_package_validator_v2 import validate_package_dir
    from .judge_result_parser_v2 import (
        PRIMARY_CRITERIA,
        SCORE_FIELDS,
        TRANSPORT_SCHEMA_VERSION,
        canonical_json_bytes,
        parse_judge_result,
    )


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
REAL = REPO / "evaluation/rq3_real_c4"
R1 = REAL / "r3d1_response_integration"
I1 = REAL / "i1_route_integration"
RESTRICTED = I1 / "restricted_internal"
PROTOCOL = REPO / "evaluation/rq3_v2/rq3_0b4_evaluation_protocol"
DOWNLOADS = Path("/Users/liuming/Downloads")

EXPECTED_BRANCH = "research/rq3-real-c4-i1-route-integration"
START_HEAD = "9843abca705f466e7a8abdb28d29905866fe4d7a"
HMAC_KEY_COMMITMENT = (
    "199db23c86b0dd824edaff2d5b40da12761c9aa76bf2fb9d902952ab376481b5"
)
RESPONSE_SET_RECEIPT_SHA256 = (
    "925f778b431e096d0fec3335850aed48313e4ae94176ccbca26d2567752924b3"
)
RUBRIC_SHA256 = "be955850ab2669b8d7380b96a1ab335dc344d89d54dd85d649118a4d86385350"
APPLICABILITY_SHA256 = (
    "bee7bf9d681004f4ab5be549053b7dbeb2f7726361217251495a167257460b0e"
)
R1_UNIQUE_JUDGE_MANIFEST_SHA256 = (
    "e00b762c579309ad929e1f4dc7e46f1da17ffa30168748d13a2c15fa787abda1"
)
JUDGE_MODEL = "gpt-4.1-2025-04-14"
TEMPERATURE = 0
MAX_OUTPUT_TOKENS = 2048
HUMAN_DOMAIN = "C4_REAL_HUMAN_RATING_R2"

R1_PACKAGE_HASHES = {
    "C4_REAL_JUDGE_SHARD_A_EXECUTION_PACKAGE_R1_2026-09-02.zip": (
        "d50a5285b9f95f3a6cdf9c1aaabc368759f30967b72aa01c604a0f084e916622"
    ),
    "C4_REAL_JUDGE_SHARD_B_EXECUTION_PACKAGE_R1_2026-09-02.zip": (
        "7618d3ce5ae6d9f93380a941f88135f051e62e7ff2d15c6774ebfae9262a7c73"
    ),
    "C4_REAL_JUDGE_SHARD_C_EXECUTION_PACKAGE_R1_2026-09-02.zip": (
        "498a5497ae63994e6c9cf1fe72668ff5fc65c0b458201797863b8fcae76a0163"
    ),
    "C4_REAL_HUMAN_RATER_A_PACKET_2026-09-02.zip": (
        "c4b43280014e9575ab66dd6d93b8d3999fdd6e1a1b7a70dd3bf551243b660967"
    ),
    "C4_REAL_HUMAN_RATER_B_PACKET_2026-09-02.zip": (
        "f99d25599ccd798e5f88233c05eceb816ab9cb29feba32fe6559110c7ae8b53b"
    ),
}
R2_EXTERNAL_NAMES = [
    *[
        f"C4_REAL_JUDGE_SHARD_{shard}_EXECUTION_PACKAGE_R2_2026-09-02.zip"
        for shard in "ABC"
    ],
    *[
        f"C4_REAL_HUMAN_RATER_{role}_PACKET_R2_2026-09-02.zip"
        for role in "AB"
    ],
]
RESTRICTED_R2_MAPPING_NAME = (
    "c4_real_human_rating_item_to_condition_mapping_frozen_r2.csv"
)
R1_JUDGE_ALLOWED = {
    "README.md",
    "BLINDED_JUDGE_REQUESTS.jsonl",
    "JUDGE_PROMPT.txt",
    "JUDGE_SCHEMA.json",
    "JUDGE_CONFIGURATION.json",
    "PRIMARY_RUBRIC.json",
    "APPLICABILITY_CONTRACT.json",
    "EXECUTION_CONTRACT.json",
    "judge_execution_runner_v1.py",
    "judge_result_parser_v1.py",
    "validate_package.py",
    "test_package.py",
    "PACKAGE_SOURCE_HASHES.json",
}
R1_HUMAN_ALLOWED = {
    "HUMAN_RATER_GUIDE.md",
    "PACKET_MANIFEST.json",
    "human_rater_attestation_A.md",
    "human_rating_packet_A.csv",
}
RATING_FIELDS = (
    "clarity",
    "personalisation",
    "actionability",
    "context_awareness",
    "motivation_and_engagement",
    "reliability",
    "multi_page_cohesiveness",
    "error_handling",
)
VISIBLE_FIELDS = (
    "student_query",
    "current_lad_page",
    "visible_conversation_history",
    "condition_visible_dashboard_evidence",
    "condition_visible_course_evidence",
    "condition_visible_learner_memory",
    "condition_visible_planning_support",
    "candidate_response",
    "applicability_flags",
)
COMPLEX_VISIBLE_FIELDS = {
    "visible_conversation_history",
    "condition_visible_dashboard_evidence",
    "condition_visible_course_evidence",
    "condition_visible_learner_memory",
    "condition_visible_planning_support",
    "applicability_flags",
}
HUMAN_PUBLIC_FIELDS = ["rating_item_id", *VISIBLE_FIELDS]
for _rating_field in RATING_FIELDS:
    HUMAN_PUBLIC_FIELDS.extend(
        (f"{_rating_field}_rating", f"{_rating_field}_rationale")
    )


class BuildError(RuntimeError):
    """Raised when an immutable input or staged R2 invariant differs."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BuildError(message)


def pretty_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(dict(row)) + b"\n" for row in rows)


def csv_bytes(fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({name: row.get(name, "") for name in fieldnames})
    return buffer.getvalue().encode("utf-8")


def load_csv_bytes(data: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"), newline="")))


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def read_zip(path: Path) -> dict[str, bytes]:
    with ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), f"duplicate ZIP member: {path.name}")
        require(all(not info.is_dir() for info in archive.infolist()), "ZIP directory present")
        return {name: archive.read(name) for name in names}


def zip_bytes(members: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(members):
            require(not Path(name).is_absolute() and ".." not in Path(name).parts, "unsafe ZIP path")
            require(len(Path(name).parts) == 1, "nested ZIP path")
            info = ZipInfo(name, date_time=(2026, 9, 2, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, members[name])
    return buffer.getvalue()


def extract_blind_request(provider_payload: Mapping[str, Any]) -> dict[str, Any]:
    content = provider_payload["messages"][0]["content"]
    begin = "BEGIN_BLIND_JUDGE_REQUEST_JSON\n"
    end = "\nEND_BLIND_JUDGE_REQUEST_JSON"
    require(content.count(begin) == 1 and content.count(end) == 1, "blind request boundary")
    value = json.loads(content.split(begin, 1)[1].rsplit(end, 1)[0])
    require(isinstance(value, dict), "blind request is not an object")
    return value


def estimated_input_tokens(provider_payload: Mapping[str, Any]) -> int:
    message_bytes = sum(
        len(canonical_json_bytes(message)) for message in provider_payload["messages"]
    )
    response_format_bytes = len(canonical_json_bytes(provider_payload["response_format"]))
    return math.ceil((message_bytes + response_format_bytes + 16) / 4)


def materialize_once(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(mode)


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise BuildError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_starting_state() -> dict[str, Any]:
    require(Path.cwd().resolve() == REPO.resolve(), "working directory differs")
    branch = git("branch", "--show-current").strip()
    head = git("rev-parse", "HEAD").strip()
    require(branch == EXPECTED_BRANCH, "branch differs")
    require(head == START_HEAD, "starting HEAD differs")
    require(
        subprocess.run(["git", "diff", "--quiet"], cwd=REPO).returncode == 0,
        "tracked worktree differs",
    )
    require(
        subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO).returncode == 0,
        "index differs",
    )
    untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
    allowed_prefix = str(HERE.relative_to(REPO)) + "/"
    require(bool(untracked), "R2 source files are unexpectedly absent")
    require(
        all(path.startswith(allowed_prefix) for path in untracked),
        "untracked file escaped authorized R2 scope",
    )

    require(RESTRICTED.is_dir(), "restricted_internal directory is absent")
    key_path = RESTRICTED / "c4_real_i1_blinding_hmac_key.bin"
    r1_mapping_path = (
        RESTRICTED / "c4_real_human_rating_item_to_condition_mapping_frozen_v1.csv"
    )
    require(key_path.is_file() and r1_mapping_path.is_file(), "HMAC key or R1 mapping absent")
    key = key_path.read_bytes()
    require(len(key) == 32 and sha256_bytes(key) == HMAC_KEY_COMMITMENT, "HMAC key differs")
    require(stat.S_IMODE(key_path.stat().st_mode) == 0o600, "HMAC key mode differs")
    for path in (key_path, r1_mapping_path):
        require(
            subprocess.run(
                ["git", "check-ignore", "-q", str(path.relative_to(REPO))],
                cwd=REPO,
            ).returncode
            == 0,
            f"restricted prerequisite is not ignored: {path.name}",
        )

    for name, expected in R1_PACKAGE_HASHES.items():
        path = DOWNLOADS / name
        require(path.is_file(), f"R1 Package absent: {name}")
        require(sha256_file(path) == expected, f"R1 Package hash differs: {name}")
    require(
        sha256_file(R1 / "C4_REAL_R3_FINAL_RESPONSE_SET_FREEZE.json")
        == RESPONSE_SET_RECEIPT_SHA256,
        "response-set receipt hash differs",
    )
    require(
        sha256_file(R1 / "c4_real_unique_judge_request_manifest_frozen_v1.jsonl")
        == R1_UNIQUE_JUDGE_MANIFEST_SHA256,
        "R1 combined Judge manifest hash differs",
    )
    for name in R2_EXTERNAL_NAMES:
        require(not (DOWNLOADS / name).exists(), f"R2 external target exists: {name}")
    require(
        not (RESTRICTED / RESTRICTED_R2_MAPPING_NAME).exists(),
        "restricted R2 mapping target exists",
    )
    return {"branch": branch, "head": head, "key": key}


def audit_r1_judge_packages() -> dict[str, Any]:
    all_rows: list[dict[str, Any]] = []
    common: dict[str, bytes] = {}
    package_observations: dict[str, Any] = {}
    for shard in "ABC":
        name = f"C4_REAL_JUDGE_SHARD_{shard}_EXECUTION_PACKAGE_R1_2026-09-02.zip"
        members = read_zip(DOWNLOADS / name)
        require(set(members) == R1_JUDGE_ALLOWED, f"R1 Judge {shard} allowlist differs")
        source_hashes = json.loads(members["PACKAGE_SOURCE_HASHES.json"])
        for member_name, expected in source_hashes["member_sha256"].items():
            require(
                sha256_bytes(members[member_name]) == expected,
                f"R1 Judge {shard} member hash differs: {member_name}",
            )
        for common_name in (
            "JUDGE_PROMPT.txt",
            "JUDGE_SCHEMA.json",
            "PRIMARY_RUBRIC.json",
            "APPLICABILITY_CONTRACT.json",
        ):
            if common_name in common:
                require(common[common_name] == members[common_name], "R1 common member differs")
            common[common_name] = members[common_name]
        rows = [
            json.loads(line)
            for line in members["BLINDED_JUDGE_REQUESTS.jsonl"].splitlines()
            if line
        ]
        require(len(rows) == 49, f"R1 Judge {shard} request count differs")
        require(all(row["shard_id"] == shard for row in rows), "R1 Shard label differs")
        all_rows.extend(rows)
        config = json.loads(members["JUDGE_CONFIGURATION.json"])
        require(config["judge_calls"] == 0, "R1 Judge config records a call")
        package_observations[shard] = {
            "package_sha256": R1_PACKAGE_HASHES[name],
            "request_count": len(rows),
            "member_count": len(members),
            "existing_judge_output_members": 0,
            "judge_calls_recorded": 0,
        }

    require(len(all_rows) == 147, "R1 Judge total request count differs")
    require(
        len({row["logical_judge_request_id"] for row in all_rows}) == 147,
        "R1 Judge logical identity collision",
    )
    distribution = Counter(
        extract_blind_request(row["provider_payload"])["frozen_applicability_map"][
            "applicable_primary_count"
        ]
        for row in all_rows
    )
    require(dict(sorted(distribution.items())) == {4: 8, 5: 49, 6: 43, 7: 33, 8: 14}, "applicability distribution differs")
    require(sha256_bytes(common["PRIMARY_RUBRIC.json"]) == RUBRIC_SHA256, "rubric differs")
    require(
        sha256_bytes(common["APPLICABILITY_CONTRACT.json"]) == APPLICABILITY_SHA256,
        "applicability contract differs",
    )
    old_parser_text = (R1 / "judge_result_parser_v1.py").read_text("utf-8")
    require(
        'semantic["overall_applicable_mean"]' in old_parser_text
        and '"overall_applicable_mean"' in old_parser_text,
        "R1 mean field not found",
    )
    require("abs_tol=1e-9" in old_parser_text, "R1 exact-tolerance comparison not found")
    old_prompt = common["JUDGE_PROMPT.txt"].decode("utf-8")
    require("Compute overall_applicable_mean" in old_prompt, "R1 mean request not found")
    require("rejected if inconsistent" in old_prompt, "R1 rejection instruction not found")
    return {
        "rows": all_rows,
        "common": common,
        "packages": package_observations,
        "distribution": dict(sorted(distribution.items())),
    }


def canonical_human_payload(row: Mapping[str, str]) -> tuple[bytes, dict[str, Any]]:
    value: dict[str, Any] = {}
    for field in VISIBLE_FIELDS:
        value[field] = json.loads(row[field]) if field in COMPLEX_VISIBLE_FIELDS else row[field]
    return canonical_json_bytes(value), value


def audit_r1_human_packages(rubric_bytes: bytes) -> dict[str, Any]:
    packets: dict[str, Any] = {}
    rows_by_role: dict[str, list[dict[str, str]]] = {}
    guide: str | None = None
    for role in "AB":
        name = f"C4_REAL_HUMAN_RATER_{role}_PACKET_2026-09-02.zip"
        members = read_zip(DOWNLOADS / name)
        expected_names = {
            "HUMAN_RATER_GUIDE.md",
            "PACKET_MANIFEST.json",
            f"human_rater_attestation_{role}.md",
            f"human_rating_packet_{role}.csv",
        }
        require(set(members) == expected_names, f"R1 Human {role} allowlist differs")
        role_guide = members["HUMAN_RATER_GUIDE.md"].decode("utf-8")
        if guide is None:
            guide = role_guide
        require(guide == role_guide, "R1 Human guides differ")
        rows = load_csv_bytes(members[f"human_rating_packet_{role}.csv"])
        require(len(rows) == 108, f"R1 Human {role} row count differs")
        blank_fields = [
            field
            for field in rows[0]
            if field.endswith("_rating") or field.endswith("_rationale")
        ]
        require(
            all(not row[field] for row in rows for field in blank_fields),
            f"R1 Human {role} contains a rating/rationale",
        )
        rows_by_role[role] = rows
        packets[role] = {
            "package_sha256": R1_PACKAGE_HASHES[name],
            "condition_level_rows": len(rows),
            "ratings_completed": 0,
            "rationales_completed": 0,
        }
    assert guide is not None
    groups_a = Counter(sha256_bytes(canonical_human_payload(row)[0]) for row in rows_by_role["A"])
    groups_b = Counter(sha256_bytes(canonical_human_payload(row)[0]) for row in rows_by_role["B"])
    require(groups_a == groups_b, "R1 Human A/B visible payload multisets differ")
    rubric = json.loads(rubric_bytes)
    anchors = [
        text
        for criterion in rubric["criteria"]
        for text in criterion["behavioural_anchors"].values()
    ]
    na_rules = [criterion["na_rule"] for criterion in rubric["criteria"]]
    anchor_present = sum(text in guide for text in anchors)
    na_present = sum(text in guide for text in na_rules)
    require(anchor_present < len(anchors), "R1 guide unexpectedly has all complete anchors")
    require(na_present < len(na_rules), "R1 guide unexpectedly has all exact NA rules")
    return {
        "rows_by_role": rows_by_role,
        "packets": packets,
        "condition_level_rows": len(rows_by_role["A"]),
        "groups": groups_a,
        "distinct_payloads": len(groups_a),
        "duplicate_extra_rows": sum(groups_a.values()) - len(groups_a),
        "maximum_group_size": max(groups_a.values()),
        "group_size_distribution": dict(sorted(Counter(groups_a.values()).items())),
        "guide_complete_anchor_strings_present": anchor_present,
        "guide_complete_anchor_strings_required": len(anchors),
        "guide_exact_na_rules_present": na_present,
        "guide_exact_na_rules_required": len(na_rules),
    }


def build_r2_prompt(r1_prompt_bytes: bytes) -> bytes:
    r1 = r1_prompt_bytes.decode("utf-8")
    before, remainder = r1.split("OUTPUT PROCEDURE\n\n", 1)
    _old_output, after = remainder.split("\n\nThe runtime inserts", 1)
    lines = before.splitlines()
    require(lines[0].startswith("RQ3-0B4 BLIND RESPONSE-QUALITY JUDGE PROMPT"), "R1 title differs")
    lines[0] = (
        "RQ3-0B4 BLIND RESPONSE-QUALITY JUDGE PROMPT R2 — "
        "provider-compatible local-aggregate transport"
    )
    before_r2 = "\n".join(lines) + ("\n" if before.endswith("\n") else "")
    output = """OUTPUT PROCEDURE

1. Score all eight primary criteria according to the frozen map.
2. Write one short, criterion-specific rationale for every primary field, including a short applicability explanation for NA.
3. Score the two secondary audits separately.
4. Do not return or echo the opaque result ID. It is attached by the local parser from the frozen request record after successful validation.
5. OVERALL_APPLICABLE_MEAN remains the arithmetic mean of applicable primary integer scores only, excluding EVIDENCE_FAITHFULNESS and UNSUPPORTED_CLAIM_COUNT. Do not calculate or return overall_applicable_mean; it is computed exclusively by the local parser.
6. Return exactly one JSON object matching c4_real_judge_schema_r2_provider_compatible.json. Encode every primary score and EVIDENCE_FAITHFULNESS as a JSON string; use one of "1", "2", "3", "4", "5", or "NA" where NA is permitted. Encode UNSUPPORTED_CLAIM_COUNT as a non-negative decimal-integer JSON string. The local parser restores the unchanged V1 numeric/NA semantics and attaches or calculates the two local fields. Return no Markdown, prose wrapper, code fence, extra field, or missing field."""
    result = before_r2 + output + "\n\nThe runtime inserts" + after
    require(result.endswith("\n"), "R2 Prompt must end with newline")
    require(result.count("{{BLIND_JUDGE_REQUEST_JSON}}") == 1, "R2 placeholder differs")
    return result.encode("utf-8")


def build_r2_schema(r1_schema_bytes: bytes) -> bytes:
    schema = json.loads(r1_schema_bytes)
    require(schema["additionalProperties"] is False, "R1 schema is not strict")
    properties = schema["properties"]
    required = schema["required"]
    for field in ("response_blind_id", "overall_applicable_mean"):
        require(field in properties and field in required, f"R1 field absent: {field}")
        del properties[field]
        required.remove(field)
    properties["schema_version"] = {
        "type": "string",
        "enum": [TRANSPORT_SCHEMA_VERSION],
    }
    expected = {
        *SCORE_FIELDS.values(),
        "evidence_faithfulness",
        "unsupported_claim_count",
        "criterion_rationales",
        "schema_version",
    }
    require(set(properties) == expected and set(required) == expected, "R2 schema fields differ")
    return pretty_json_bytes(schema)


def build_provider_payload(
    blind_request: Mapping[str, Any], prompt_bytes: bytes, schema: Mapping[str, Any]
) -> dict[str, Any]:
    prompt = prompt_bytes.decode("utf-8")
    rendered = prompt.replace(
        "{{BLIND_JUDGE_REQUEST_JSON}}",
        canonical_json_bytes(dict(blind_request)).decode("utf-8"),
    )
    return {
        "model": JUDGE_MODEL,
        "messages": [{"role": "system", "content": rendered}],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "c4_real_judge_response_r3d1_r2_provider_compatible",
                "strict": True,
                "schema": dict(schema),
            },
        },
    }


def build_r2_judge_records(
    r1_rows: Sequence[Mapping[str, Any]], prompt_bytes: bytes, schema_bytes: bytes
) -> list[dict[str, Any]]:
    schema = json.loads(schema_bytes)
    output: list[dict[str, Any]] = []
    for old in r1_rows:
        blind_request = extract_blind_request(old["provider_payload"])
        payload = build_provider_payload(blind_request, prompt_bytes, schema)
        output.append(
            {
                "schema_version": "c4-real-unique-judge-request-frozen-r2",
                "logical_judge_request_id": old["logical_judge_request_id"],
                "judge_result_blind_id": old["judge_result_blind_id"],
                "provider_payload_sha256": sha256_bytes(canonical_json_bytes(payload)),
                "estimated_input_tokens": estimated_input_tokens(payload),
                "shard_id": old["shard_id"],
                "provider_payload": payload,
            }
        )
    require(len(output) == 147, "R2 Judge request count differs")
    for shard in "ABC":
        require(sum(row["shard_id"] == shard for row in output) == 49, "R2 Shard size differs")
    for old, new in zip(r1_rows, output):
        require(old["logical_judge_request_id"] == new["logical_judge_request_id"], "Judge logical ID changed")
        require(old["judge_result_blind_id"] == new["judge_result_blind_id"], "Judge result ID changed")
        require(old["shard_id"] == new["shard_id"], "Judge Shard changed")
        require(
            extract_blind_request(old["provider_payload"])
            == extract_blind_request(new["provider_payload"]),
            "substantive blind Judge input changed",
        )
    return output


def synthetic_score_payload(applicability: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    rationales: dict[str, str] = {}
    numeric: list[int] = []
    for index, criterion in enumerate(PRIMARY_CRITERIA):
        field = SCORE_FIELDS[criterion]
        if applicability["criteria"][criterion]:
            score = (index % 5) + 1
            result[field] = str(score)
            numeric.append(score)
        else:
            result[field] = "NA"
        rationales[field] = "Synthetic transport-contract fixture; not a response rating."
    result.update(
        {
            "evidence_faithfulness": "3",
            "unsupported_claim_count": "0",
            "criterion_rationales": rationales,
            "schema_version": TRANSPORT_SCHEMA_VERSION,
        }
    )
    return {"provider": result, "mean": sum(numeric) / len(numeric)}


def audit_semantic_equivalence_and_old_mean(r1_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    old_parser = load_module("r3d1_r1_parser_for_r2_audit", R1 / "judge_result_parser_v1.py")
    comparisons = 0
    old_failures: dict[str, Any] = {}
    for row in r1_rows:
        request = extract_blind_request(row["provider_payload"])
        applicability = request["frozen_applicability_map"]
        fixture = synthetic_score_payload(applicability)
        r2_value = fixture["provider"]
        r1_value = {
            "response_blind_id": row["judge_result_blind_id"],
            **r2_value,
            "overall_applicable_mean": str(fixture["mean"]),
            "schema_version": "rq3-judge-response-v2-transport",
        }
        old_semantic = old_parser.parse_judge_result(
            r1_value,
            applicability,
            expected_judge_result_blind_id=row["judge_result_blind_id"],
        )
        new_semantic = parse_judge_result(
            r2_value,
            applicability,
            expected_judge_result_blind_id=row["judge_result_blind_id"],
        )
        require(old_semantic == new_semantic, "R1/R2 semantic parse differs")
        comparisons += 1

        count = applicability["applicable_primary_count"]
        if count in {6, 7} and str(count) not in old_failures:
            scores: dict[str, Any] = {}
            rationales: dict[str, str] = {}
            applicable_seen = 0
            numeric: list[int] = []
            for criterion in PRIMARY_CRITERIA:
                field = SCORE_FIELDS[criterion]
                if applicability["criteria"][criterion]:
                    score = 2 if applicable_seen == 0 else 1
                    applicable_seen += 1
                    scores[field] = str(score)
                    numeric.append(score)
                else:
                    scores[field] = "NA"
                rationales[field] = "Synthetic exact-mean transport fixture."
            exact = sum(numeric) / len(numeric)
            rounded = f"{exact:.2f}"
            candidate = {
                "response_blind_id": row["judge_result_blind_id"],
                **scores,
                "evidence_faithfulness": "3",
                "unsupported_claim_count": "0",
                "overall_applicable_mean": rounded,
                "criterion_rationales": rationales,
                "schema_version": "rq3-judge-response-v2-transport",
            }
            rejected = False
            error_code = None
            try:
                old_parser.parse_judge_result(
                    candidate,
                    applicability,
                    expected_judge_result_blind_id=row["judge_result_blind_id"],
                )
            except old_parser.JudgeResultError as exc:
                rejected = True
                error_code = old_parser.retryable_failure_code(exc)
            require(rejected, f"R1 rounded {count}-criterion mean was not rejected")
            old_failures[str(count)] = {
                "applicable_primary_count": count,
                "synthetic_integer_score_sum": sum(numeric),
                "exact_local_mean": exact,
                "normally_rounded_two_decimal_transport": rounded,
                "absolute_difference": abs(float(rounded) - exact),
                "r1_absolute_tolerance": 1e-9,
                "r1_rejected": rejected,
                "r1_retry_class": error_code,
            }
    require(comparisons == 147 and set(old_failures) == {"6", "7"}, "semantic audit incomplete")
    return {
        "synthetic_contract_comparisons": comparisons,
        "semantic_outputs_identical": True,
        "semantic_schema_version": "rq3-judge-response-v1",
        "fixture_values_are_not_response_ratings": True,
        "r1_normally_rounded_failure_examples": old_failures,
        "r2_provider_mean_field_absent": True,
        "r2_local_mean_only": True,
    }


def r2_rating_id(key: bytes, payload_bytes: bytes) -> str:
    message = HUMAN_DOMAIN.encode("utf-8") + b"\x00rating-item-id\x00" + payload_bytes
    return "HR2-" + hmac.new(key, message, hashlib.sha256).hexdigest()[:24].upper()


def order_digest(key: bytes, role: str, rating_id: str) -> str:
    message = (
        HUMAN_DOMAIN + "\x00reviewer-" + role + "-order\x00" + rating_id
    ).encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def build_human_guide(rubric_bytes: bytes) -> bytes:
    rubric = json.loads(rubric_bytes)
    lines = [
        "# C4 REAL independent human-rater guide R2",
        "",
        "Status: `FROZEN_UNRATED_PACKET_R3D1_R2`",
        "",
        "Rate only the candidate response shown in each row against evidence supplied in that same row. Evaluate only supplied evidence; do not infer an experimental condition, route, hidden information, expected capability, expected winner, or material not shown. Work independently and do not compare against the other rater or an LLM Judge.",
        "",
        "Use integer scores 1–5 for applicable criteria and `NA` exactly when the frozen applicability flag is false. Applicability was frozen before response scoring. A poor, incomplete, or incorrect response on an applicable criterion receives a low score, not `NA`. Do not reward length, detail, confidence, fluent wording, or verbosity by itself. Write one short, criterion-specific rationale for every criterion, including a short applicability explanation for `NA`.",
        "",
        "## Frozen primary rubric",
        "",
    ]
    for criterion in rubric["criteria"]:
        lines.extend(
            [
                f"### {criterion['criterion_name']}",
                "",
                f"Definition: {criterion['original_meaning_preserved']}",
                "",
                f"NA rule: {criterion['na_rule']}",
                "",
                "Behavioural anchors:",
                "",
            ]
        )
        for score in ("1", "2", "3", "4", "5"):
            lines.append(f"- {score}: {criterion['behavioural_anchors'][score]}")
        lines.append("")
    lines.extend(
        [
            "## Practical CSV viewing",
            "",
            "Open the CSV in a spreadsheet application, select the long-text columns, enable text wrapping, and adjust row height or column width for reading. Do not edit, truncate, reformat, sort, or replace evidence, applicability flags, candidate responses, or item IDs. Enter ratings and rationales only in their designated blank cells.",
            "",
            "After all rows are complete, complete the separate attestation. Do not inspect restricted mappings, condition identities, Judge material, or the other rater's packet.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def human_attestation(role: str) -> bytes:
    return f"""# C4 REAL human-rater {role} attestation R2

Packet status: `UNRATED_TEMPLATE_R2`

Reviewer role: `{role}`

- Independent rating completed: 
- Experimental condition identities remained unseen: 
- Other reviewer's ratings remained unseen: 
- LLM Judge outputs remained unseen: 
- Full R2 rubric and applicability rules were followed: 
- No response text, evidence, applicability flag, or item identifier was changed: 

Reviewer signature: 

Completion date/time: 

Notes: 
""".encode("utf-8")


def build_human_items(
    rows_a: Sequence[Mapping[str, str]], key: bytes
) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows_a:
        payload_bytes, payload = canonical_human_payload(row)
        digest = sha256_bytes(payload_bytes)
        group = groups.setdefault(
            digest,
            {"payload_bytes": payload_bytes, "payload": payload, "source_rows": []},
        )
        require(group["payload_bytes"] == payload_bytes, "Human visible-payload hash collision")
        group["source_rows"].append(dict(row))
    require(len(groups) == 44, "unique Human-visible item count differs")
    require(sum(len(group["source_rows"]) for group in groups.values()) == 108, "Human mapping count differs")

    r1_mapping_rows = load_csv(
        RESTRICTED / "c4_real_human_rating_item_to_condition_mapping_frozen_v1.csv"
    )
    r1_mapping = {row["rating_item_id"]: row for row in r1_mapping_rows}
    require(len(r1_mapping) == 108, "R1 restricted Human mapping count differs")
    unique_items: list[dict[str, Any]] = []
    restricted_rows: list[dict[str, str]] = []
    seen_r1_ids: set[str] = set()
    for digest, group in sorted(groups.items()):
        rating_id = r2_rating_id(key, group["payload_bytes"])
        payload = group["payload"]
        public: dict[str, Any] = {"rating_item_id": rating_id, **payload}
        for field in RATING_FIELDS:
            public[f"{field}_rating"] = ""
            public[f"{field}_rationale"] = ""
        unique_items.append(public)
        for source_row in group["source_rows"]:
            r1_id = source_row["rating_item_id"]
            require(r1_id in r1_mapping, "R1 Human item lacks restricted mapping")
            seen_r1_ids.add(r1_id)
            old = r1_mapping[r1_id]
            restricted_rows.append(
                {
                    "r2_rating_item_id": rating_id,
                    "human_visible_payload_sha256": digest,
                    "r1_rating_item_id": r1_id,
                    "replay_record_id": old["replay_record_id"],
                    "scenario_id": old["scenario_id"],
                    "mode_id": old["mode_id"],
                    "generation_logical_request_id": old[
                        "generation_logical_request_id"
                    ],
                    "generation_response_blind_id": old[
                        "generation_response_blind_id"
                    ],
                    "judge_logical_request_id": old["judge_logical_request_id"],
                    "judge_result_blind_id": old["judge_result_blind_id"],
                    "complete_visible_payload_byte_identical": "true",
                }
            )
    require(seen_r1_ids == set(r1_mapping), "R1 Human sample mapping was not preserved")
    require(len({row["rating_item_id"] for row in unique_items}) == 44, "R2 Human ID collision")
    require(len(restricted_rows) == 108, "R2 restricted mapping count differs")
    require(len({row["scenario_id"] for row in restricted_rows}) == 12, "selected family count changed")
    restricted_rows.sort(key=lambda row: (row["r2_rating_item_id"], row["replay_record_id"]))
    group_sizes = Counter(len(group["source_rows"]) for group in groups.values())
    metadata = {
        "condition_level_sample_mappings": len(restricted_rows),
        "unique_human_visible_items": len(unique_items),
        "duplicate_mappings": len(restricted_rows) - len(unique_items),
        "maximum_exact_duplicate_group_size": max(
            len(group["source_rows"]) for group in groups.values()
        ),
        "duplicate_group_size_distribution": dict(sorted(group_sizes.items())),
        "selected_family_count": len({row["scenario_id"] for row in restricted_rows}),
    }
    return unique_items, restricted_rows, metadata


def public_human_csv(rows: Sequence[Mapping[str, Any]]) -> bytes:
    serialised: list[dict[str, str]] = []
    for row in rows:
        output: dict[str, str] = {}
        for field in HUMAN_PUBLIC_FIELDS:
            value = row[field]
            output[field] = (
                canonical_json_bytes(value).decode("utf-8")
                if field in COMPLEX_VISIBLE_FIELDS
                else str(value)
            )
        serialised.append(output)
    return csv_bytes(HUMAN_PUBLIC_FIELDS, serialised)


def build_human_packages(
    unique_items: Sequence[Mapping[str, Any]],
    key: bytes,
    guide_bytes: bytes,
    rubric_bytes: bytes,
) -> tuple[dict[str, bytes], dict[str, Any], dict[str, bytes]]:
    orders = {
        role: sorted(unique_items, key=lambda row: order_digest(key, role, row["rating_item_id"]))
        for role in "AB"
    }
    ids = {role: [row["rating_item_id"] for row in orders[role]] for role in "AB"}
    require(set(ids["A"]) == set(ids["B"]) and ids["A"] != ids["B"], "Human A/B order invariant")
    item_set_hash = sha256_bytes(canonical_json_bytes(sorted(ids["A"])))
    visible_set_hash = sha256_bytes(
        canonical_json_bytes(
            sorted(sha256_bytes(canonical_human_payload_from_typed(row)) for row in unique_items)
        )
    )
    external: dict[str, bytes] = {}
    tracked_csv: dict[str, bytes] = {}
    package_metadata: dict[str, Any] = {}
    for role in "AB":
        csv_name = f"human_rating_packet_{role}.csv"
        attestation_name = f"human_rater_attestation_{role}.md"
        csv_data = public_human_csv(orders[role])
        attestation = human_attestation(role)
        manifest = {
            "schema_version": "c4-real-human-rater-packet-r2-v1",
            "status": "FROZEN_UNRATED_TEMPLATE_R2",
            "reviewer_role": role,
            "unique_rating_item_count": len(unique_items),
            "item_set_sha256": item_set_hash,
            "human_visible_payload_set_sha256": visible_set_hash,
            "order_sha256": sha256_bytes(canonical_json_bytes(ids[role])),
            "member_sha256": {
                "HUMAN_RATER_GUIDE_R2.md": sha256_bytes(guide_bytes),
                "PRIMARY_RUBRIC.json": sha256_bytes(rubric_bytes),
                csv_name: sha256_bytes(csv_data),
                attestation_name: sha256_bytes(attestation),
            },
            "ratings_completed": 0,
            "rationales_completed": 0,
        }
        members = {
            "HUMAN_RATER_GUIDE_R2.md": guide_bytes,
            "PRIMARY_RUBRIC.json": rubric_bytes,
            csv_name: csv_data,
            attestation_name: attestation,
            "PACKET_MANIFEST.json": pretty_json_bytes(manifest),
        }
        validate_human_package(members, role)
        archive = zip_bytes(members)
        filename = f"C4_REAL_HUMAN_RATER_{role}_PACKET_R2_2026-09-02.zip"
        external[filename] = archive
        tracked_csv[role] = csv_data
        package_metadata[role] = {
            "file_name": filename,
            "sha256": sha256_bytes(archive),
            "regular_file_count": len(members),
            "unique_rating_item_count": len(unique_items),
            "ratings_completed": 0,
            "rationales_completed": 0,
            "order_sha256": manifest["order_sha256"],
            "member_sha256": {
                name: sha256_bytes(data) for name, data in sorted(members.items())
            },
        }
    manifest = {
        "schema_version": "c4-real-human-packet-manifest-r2-v1",
        "status": "PASS_UNIQUE_VISIBLE_ITEMS_TWO_BLINDED_UNRATED_PACKETS",
        "unique_rating_item_count": len(unique_items),
        "same_unique_item_set": True,
        "different_deterministic_orders": True,
        "item_set_sha256": item_set_hash,
        "human_visible_payload_set_sha256": visible_set_hash,
        "guide_sha256": sha256_bytes(guide_bytes),
        "primary_rubric_sha256": sha256_bytes(rubric_bytes),
        "packages": package_metadata,
        "ratings_completed": 0,
        "rationales_completed": 0,
        "condition_identity_exposed": False,
        "duplicate_mapping_count_per_item_exposed": False,
        "restricted_mapping_or_hmac_key_included": False,
    }
    return external, manifest, tracked_csv


def canonical_human_payload_from_typed(row: Mapping[str, Any]) -> bytes:
    return canonical_json_bytes({field: row[field] for field in VISIBLE_FIELDS})


def validate_human_package(members: Mapping[str, bytes], role: str) -> None:
    expected = {
        "HUMAN_RATER_GUIDE_R2.md",
        "PRIMARY_RUBRIC.json",
        f"human_rating_packet_{role}.csv",
        f"human_rater_attestation_{role}.md",
        "PACKET_MANIFEST.json",
    }
    require(set(members) == expected, "Human R2 Package allowlist differs")
    require(sha256_bytes(members["PRIMARY_RUBRIC.json"]) == RUBRIC_SHA256, "Human rubric differs")
    rows = load_csv_bytes(members[f"human_rating_packet_{role}.csv"])
    require(len(rows) == 44, "Human R2 Package item count differs")
    require(list(rows[0]) == HUMAN_PUBLIC_FIELDS, "Human R2 CSV fields differ")
    require(len({row["rating_item_id"] for row in rows}) == 44, "Human R2 ID collision")
    require(
        len({sha256_bytes(canonical_human_payload(row)[0]) for row in rows}) == 44,
        "Human R2 visible payload duplication remains",
    )
    blank_fields = [
        field for field in HUMAN_PUBLIC_FIELDS if field.endswith(("_rating", "_rationale"))
    ]
    require(all(not row[field] for row in rows for field in blank_fields), "Human rating not blank")
    forbidden_columns = {
        "scenario_id",
        "family_id",
        "mode",
        "condition",
        "route",
        "p3",
        "gold",
        "expected_winner",
        "judge_result_id",
        "duplicate_mapping_count",
    }
    require(not forbidden_columns.intersection(rows[0]), "Human forbidden column present")
    joined = b"".join(members.values())
    require(b"c4_real_i1_blinding_hmac_key.bin" not in joined, "HMAC key reference leaked")
    require(RESTRICTED_R2_MAPPING_NAME.encode() not in joined, "restricted mapping leaked")


def common_configuration(
    prompt_hash: str,
    schema_hash: str,
    parser_hash: str,
    runner_hash: str,
) -> dict[str, Any]:
    return {
        "schema_version": "c4-real-judge-configuration-r3d1-r2-v1",
        "status": "FROZEN_UNEXECUTED_REQUIRES_NEW_DIRECT_AUTHORIZATION_R2",
        "model": JUDGE_MODEL,
        "endpoint": "OpenAI Chat Completions",
        "endpoint_path": "/v1/chat/completions",
        "temperature": TEMPERATURE,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "automatic_sdk_retries": 0,
        "manual_retry": {
            "maximum_retries": 1,
            "permitted_only_after": [
                "INVALID_JSON",
                "STRICT_SCHEMA_VALIDATION_FAILED",
                "APPLICABILITY_CONTRACT_VIOLATION",
            ],
            "request_bytes": "IDENTICAL",
            "correction_message_added": False,
        },
        "streaming": False,
        "tools": "NONE",
        "serial_execution": True,
        "minimum_seconds_between_initial_request_starts": 15.0,
        "judge_prompt_sha256": prompt_hash,
        "provider_schema_sha256": schema_hash,
        "primary_rubric_sha256": RUBRIC_SHA256,
        "applicability_contract_sha256": APPLICABILITY_SHA256,
        "local_parser_sha256": parser_hash,
        "execution_runner_sha256": runner_hash,
        "semantic_contract": "AUTHORITATIVE_RQ3_0B4_V1_UNCHANGED",
        "semantic_schema_version": "rq3-judge-response-v1",
        "transport_schema_version": TRANSPORT_SCHEMA_VERSION,
        "primary_outcome": "OVERALL_APPLICABLE_MEAN",
        "secondary_audits_excluded_from_primary_mean": True,
        "provider_outputs_result_blind_id": False,
        "provider_outputs_overall_applicable_mean": False,
        "result_blind_id_attached_locally": True,
        "overall_applicable_mean_computed_locally": True,
        "judge_calls": 0,
    }


def execution_contract(configuration_hash: str) -> dict[str, Any]:
    return {
        "schema_version": "c4-real-judge-execution-contract-r2-v1",
        "status": "FROZEN_FOR_FUTURE_SEPARATELY_AUTHORIZED_EXECUTION_R2",
        "python_executable": "/opt/anaconda3/bin/python3",
        "python_version": "3.13.5",
        "openai_sdk_version": "1.109.1",
        "openai_client_max_retries": 0,
        "automatic_sdk_retries": 0,
        "serial_execution": True,
        "minimum_seconds_between_initial_request_starts": 15.0,
        "required_cli_arguments": [
            "--package-zip",
            "--authorization-record",
            "--output-dir",
            "--execute",
        ],
        "authorization_environment_variable": "C4_REAL_JUDGE_EXECUTION_AUTHORIZATION",
        "authorization_environment_value": "AUTHORIZED_C4_REAL_JUDGE_EXECUTION_R2",
        "authorization_record_schema_version": (
            "c4-real-judge-execution-authorization-r2-v1"
        ),
        "authorization_record_exact_binding_fields": [
            "schema_version",
            "authorization_id",
            "authorized_by",
            "authorized_at_utc",
            "package_id",
            "shard_id",
            "request_count",
            "maximum_physical_attempts",
            "package_zip_sha256",
            "blinded_judge_manifest_sha256",
            "status",
        ],
        "authorization_status_required": "AUTHORIZED",
        "bindings_verified_before_runtime_and_client_construction": True,
        "preflight_start_receipt_before_runtime_and_client_construction": True,
        "attempt_terminal_error_status_journals_flush_and_fsync": True,
        "existing_output_directory_permitted": False,
        "output_directory_created_atomically": True,
        "automatic_resume": False,
        "raw_invalid_output_preserved": True,
        "returned_model_identity_verified": JUDGE_MODEL,
        "provider_error_fields_sanitized": True,
        "authorization_headers_recorded": False,
        "complete_or_incomplete_status_always_written_after_output_creation": True,
        "non_retryable_error_policy": "STOP_ENTIRE_SHARD",
        "manual_retry": {
            "maximum_retries": 1,
            "byte_identical": True,
            "correction_message": False,
            "permitted_only_after": [
                "INVALID_JSON",
                "STRICT_SCHEMA_VALIDATION_FAILED",
                "APPLICABILITY_CONTRACT_VIOLATION",
            ],
        },
        "condition_comparisons_inside_worker": False,
        "configuration_sha256": configuration_hash,
        "execution_authorized_in_package": False,
    }


def build_judge_packages(
    records: Sequence[Mapping[str, Any]],
    prompt_bytes: bytes,
    schema_bytes: bytes,
    rubric_bytes: bytes,
    applicability_bytes: bytes,
) -> tuple[dict[str, bytes], dict[str, Any], dict[str, Any], dict[str, Any]]:
    runner_bytes = (HERE / "judge_execution_runner_v2.py").read_bytes()
    parser_bytes = (HERE / "judge_result_parser_v2.py").read_bytes()
    validator_bytes = (HERE / "judge_package_validator_v2.py").read_bytes()
    test_bytes = (HERE / "judge_package_offline_tests_v2.py").read_bytes()
    common = common_configuration(
        sha256_bytes(prompt_bytes),
        sha256_bytes(schema_bytes),
        sha256_bytes(parser_bytes),
        sha256_bytes(runner_bytes),
    )
    external: dict[str, bytes] = {}
    packages: dict[str, Any] = {}
    configs: dict[str, Any] = {}
    contracts: dict[str, Any] = {}
    for shard in "ABC":
        shard_rows = [dict(row) for row in records if row["shard_id"] == shard]
        requests = jsonl_bytes(shard_rows)
        package_id = f"C4_REAL_JUDGE_SHARD_{shard}_R2_2026-09-02"
        config = {
            **common,
            "package_id": package_id,
            "shard_id": shard,
            "request_count": len(shard_rows),
            "maximum_physical_attempts": len(shard_rows) * 2,
            "blinded_judge_manifest_sha256": sha256_bytes(requests),
        }
        config_bytes = pretty_json_bytes(config)
        contract = execution_contract(sha256_bytes(config_bytes))
        contract_bytes = pretty_json_bytes(contract)
        readme = f"""# C4 REAL Judge Shard {shard} execution Package R2

Status: `FROZEN_UNEXECUTED_REQUIRES_NEW_DIRECT_AUTHORIZATION_R2`

This blinded Package contains 49 frozen Judge requests. R3D1-R2 authorizes no Judge call and this Package has not been executed. Future execution requires the exact environment gate, a separately supplied strict authorization record bound to this ZIP and its request manifest, all four required CLI arguments, and `/opt/anaconda3/bin/python3`.

The runner is serial, uses `max_retries=0`, spaces consecutive initial request starts by at least 15.0 seconds, permits one byte-identical retry only for the three named invalid-output classes, refuses resume or any existing output directory, and stops the complete Shard on every non-retryable or second-invalid failure.
""".encode("utf-8")
        members: dict[str, bytes] = {
            "README.md": readme,
            "BLINDED_JUDGE_REQUESTS.jsonl": requests,
            "JUDGE_PROMPT.txt": prompt_bytes,
            "JUDGE_SCHEMA.json": schema_bytes,
            "JUDGE_CONFIGURATION.json": config_bytes,
            "PRIMARY_RUBRIC.json": rubric_bytes,
            "APPLICABILITY_CONTRACT.json": applicability_bytes,
            "EXECUTION_CONTRACT.json": contract_bytes,
            "judge_execution_runner_v2.py": runner_bytes,
            "judge_result_parser_v2.py": parser_bytes,
            "validate_package.py": validator_bytes,
            "test_package.py": test_bytes,
        }
        source_hashes = {
            "schema_version": "c4-real-judge-package-source-hashes-r2-v1",
            "package_id": package_id,
            "shard_id": shard,
            "member_sha256": {
                name: sha256_bytes(data) for name, data in sorted(members.items())
            },
        }
        members["PACKAGE_SOURCE_HASHES.json"] = pretty_json_bytes(source_hashes)
        with tempfile.TemporaryDirectory(prefix=f"c4-judge-r2-{shard.lower()}-") as tmp:
            package_dir = Path(tmp) / "package"
            package_dir.mkdir()
            for name, data in members.items():
                (package_dir / name).write_bytes(data)
            validation = validate_package_dir(package_dir)
            require(validation["status"] == "PASS", f"Judge R2 {shard} validation failed")
            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            tests = subprocess.run(
                ["/opt/anaconda3/bin/python3", "-B", "test_package.py"],
                cwd=package_dir,
                env=env,
                capture_output=True,
                text=True,
            )
            require(
                tests.returncode == 0,
                f"Judge R2 {shard} offline tests failed:\n{tests.stdout}\n{tests.stderr}",
            )
            match = re.search(r"Ran (\d+) tests?", tests.stdout + tests.stderr)
            if match is None:
                raise BuildError("Package unittest count not found")
            test_count = int(match.group(1))
        archive = zip_bytes(members)
        filename = f"C4_REAL_JUDGE_SHARD_{shard}_EXECUTION_PACKAGE_R2_2026-09-02.zip"
        external[filename] = archive
        packages[shard] = {
            "package_id": package_id,
            "file_name": filename,
            "sha256": sha256_bytes(archive),
            "regular_file_count": len(members),
            "request_count": len(shard_rows),
            "estimated_input_tokens": sum(row["estimated_input_tokens"] for row in shard_rows),
            "maximum_physical_attempts": len(shard_rows) * 2,
            "blinded_judge_manifest_sha256": sha256_bytes(requests),
            "configuration_sha256": sha256_bytes(config_bytes),
            "execution_contract_sha256": sha256_bytes(contract_bytes),
            "package_validation": "PASS",
            "offline_package_tests_passed": test_count,
            "offline_package_tests_failed": 0,
            "member_sha256": {
                name: sha256_bytes(data) for name, data in sorted(members.items())
            },
        }
        configs[shard] = config
        contracts[shard] = contract
    manifest = {
        "schema_version": "c4-real-judge-package-manifest-r2-v1",
        "status": "PASS_THREE_BLINDED_R2_PACKAGES_FROZEN_UNEXECUTED",
        "packages": packages,
        "judge_calls": 0,
        "credentials_included": False,
        "restricted_mapping_or_hmac_key_included": False,
        "scenario_family_mode_condition_identity_included": False,
        "gold_or_expected_winner_included": False,
        "generation_attempt_history_included": False,
        "existing_judge_outputs_included": False,
    }
    return external, manifest, configs, contracts


def preexecution_audit_markdown(audit: Mapping[str, Any]) -> bytes:
    distribution = audit["judge"]["applicable_primary_count_distribution"]
    failure = audit["judge"]["r1_exact_mean_failure"]
    return f"""# C4 REAL R3D1-R2 independent pre-execution audit

Status: `PASS_PREEXECUTION_AUDIT_NO_EVALUATION_CALLS`

This audit was computed independently from all three immutable R1 Judge ZIPs and both immutable R1 Human ZIPs before building R2. It performs transport and exact-payload checks only; it does not score candidate responses or compare experimental modes.

## Judge audit

- Requests inspected: `147`
- Applicable-primary distribution: 4 → `{distribution['4']}`, 5 → `{distribution['5']}`, 6 → `{distribution['6']}`, 7 → `{distribution['7']}`, 8 → `{distribution['8']}`
- Current R1 parser requires Provider field `overall_applicable_mean`, recomputes it locally, and compares at absolute tolerance `1e-9`.
- Normally rounded two-decimal fixtures were independently rejected for 6 and 7 applicable criteria with retry class `APPLICABILITY_CONTRACT_VIOLATION`: `{failure['r1_normally_rounded_failure_examples']['6']['normally_rounded_two_decimal_transport']}` versus `{failure['r1_normally_rounded_failure_examples']['6']['exact_local_mean']}`, and `{failure['r1_normally_rounded_failure_examples']['7']['normally_rounded_two_decimal_transport']}` versus `{failure['r1_normally_rounded_failure_examples']['7']['exact_local_mean']}`.
- The retry would resend the identical request, so this transport-only mismatch could consume the sole invalid-output retry.

## Human packet audit

- Condition-level rows inspected: `108`
- Distinct complete Human-visible payloads: `44`
- Duplicate extra mappings: `64`
- Maximum exact duplicate group size: `8`
- R1 guide full criterion-specific anchor texts present: `{audit['human']['guide_complete_anchor_strings_present']} / {audit['human']['guide_complete_anchor_strings_required']}`
- R1 guide exact criterion-specific NA rules present: `{audit['human']['guide_exact_na_rules_present']} / {audit['human']['guide_exact_na_rules_required']}`

All five R1 Packages remained byte-identical, unexecuted or unrated, and are recorded as `SUPERSEDED_UNEXECUTED_OR_UNRATED_BY_R3D1_R2`. No Provider, Judge, scoring, rating, analysis, route, generation, or Streamlit action occurred.
""".encode("utf-8")


def compatibility_note(
    prompt_hash_r1: str,
    prompt_hash_r2: str,
    schema_hash_r1: str,
    schema_hash_r2: str,
    semantic_audit: Mapping[str, Any],
) -> bytes:
    return f"""# C4 REAL Judge Provider contract R1/R2 compatibility note

R2 changes only the Provider output transport and execution hardening before any Judge result exists. The eight primary criteria, definitions, 1–5 anchors, NA rules, frozen applicability, EVIDENCE_FAITHFULNESS, UNSUPPORTED_CLAIM_COUNT, OVERALL_APPLICABLE_MEAN definition, evidence inputs, blind design, model, temperature, and maximum output tokens are unchanged.

- R1 Prompt SHA-256: `{prompt_hash_r1}`
- R2 Prompt SHA-256: `{prompt_hash_r2}`
- R1 Provider schema SHA-256: `{schema_hash_r1}`
- R2 Provider schema SHA-256: `{schema_hash_r2}`
- Substantive blind-request payloads preserved: `147 / 147`
- Synthetic structural parse comparisons, not response ratings: `{semantic_audit['synthetic_contract_comparisons']} / 147` identical
- Semantic schema after parsing: `{semantic_audit['semantic_schema_version']}` unchanged

R1 asked the Provider to echo the opaque result ID and calculate an aggregate decimal. R2 requests neither. After strict validation, the local parser attaches the request record's opaque result ID and computes the arithmetic mean from applicable primary integer scores only. EVIDENCE_FAITHFULNESS and UNSUPPORTED_CLAIM_COUNT remain secondary and are excluded. The returned semantic object still contains the opaque ID, all eight primary scores, evidence faithfulness, unsupported-claim count, local overall applicable mean, all eight rationales, and the unchanged semantic schema version.
""".encode("utf-8")


def human_method_note() -> bytes:
    return b"""# C4 REAL R3D1-R2 Human-visible exact-item deduplication method

The frozen 12-family selection and all 108 condition-level sample mappings are preserved. R3D1-R2 canonicalises exactly the nine Human-visible fields named in the authorization and groups only complete byte-identical canonical payloads. Rating-item ID, row order, blank rating cells, and blank rationale cells are excluded. Candidate response alone, answer-text hash, scenario, family, and mode are never deduplication keys.

Each of the 44 distinct visible payloads receives one new opaque HMAC-derived R2 item ID under domain `C4_REAL_HUMAN_RATING_R2`. The ignored restricted mapping retains all 108 condition records, so a completed rating can be mapped back only to records whose complete Human-visible payload is byte-identical. This avoids asking a human to rate the same visible item repeatedly and avoids treating duplicated copies as independent observations. Human-human and Human-LLM agreement must therefore use the 44 unique rated items, not 108 duplicated rows.

This is a pre-evaluation data-transport rule. It contains no rating, score, mode comparison, winner inference, or statistical result.
"""


def status_markdown() -> bytes:
    return b"""# RQ3 REAL C4 R3D1-R2 status

`RQ3_REAL_R3D1_R2_STATUS = READY_FOR_C4_REAL_JUDGE_EXECUTION_AND_INDEPENDENT_HUMAN_REVIEW_R2`

The R2 Judge and Human Packages are frozen and remain unexecuted/unrated. Judge execution and Human rating are not authorized by this status and require their own direct downstream authorization or independent review action.

- Provider calls: `0`
- Judge calls: `0`
- Response-quality scores produced: `0`
- Human ratings completed: `0`
- Streamlit launches: `0`
"""


def main() -> int:
    state = assert_starting_state()
    judge_audit = audit_r1_judge_packages()
    human_audit = audit_r1_human_packages(judge_audit["common"]["PRIMARY_RUBRIC.json"])
    require(
        (human_audit["condition_level_rows"], human_audit["distinct_payloads"], human_audit["duplicate_extra_rows"], human_audit["maximum_group_size"])
        == (108, 44, 64, 8),
        "independent Human audit differs",
    )

    prompt_r2 = build_r2_prompt(judge_audit["common"]["JUDGE_PROMPT.txt"])
    schema_r2 = build_r2_schema(judge_audit["common"]["JUDGE_SCHEMA.json"])
    judge_r2_records = build_r2_judge_records(judge_audit["rows"], prompt_r2, schema_r2)
    semantic_audit = audit_semantic_equivalence_and_old_mean(judge_audit["rows"])

    unique_human_items, restricted_mapping_rows, human_counts = build_human_items(
        human_audit["rows_by_role"]["A"], state["key"]
    )
    require(human_counts["duplicate_mappings"] == 64, "Human duplicate mapping count differs")
    guide_r2 = build_human_guide(judge_audit["common"]["PRIMARY_RUBRIC.json"])
    rubric = json.loads(judge_audit["common"]["PRIMARY_RUBRIC.json"])
    require(
        all(
            text in guide_r2.decode("utf-8")
            for criterion in rubric["criteria"]
            for text in criterion["behavioural_anchors"].values()
        ),
        "R2 Human guide lacks a full anchor",
    )
    require(
        all(
            criterion["na_rule"] in guide_r2.decode("utf-8")
            for criterion in rubric["criteria"]
        ),
        "R2 Human guide lacks an exact NA rule",
    )

    judge_external, judge_manifest, configs, contracts = build_judge_packages(
        judge_r2_records,
        prompt_r2,
        schema_r2,
        judge_audit["common"]["PRIMARY_RUBRIC.json"],
        judge_audit["common"]["APPLICABILITY_CONTRACT.json"],
    )
    human_external, human_manifest, tracked_human_csv = build_human_packages(
        unique_human_items,
        state["key"],
        guide_r2,
        judge_audit["common"]["PRIMARY_RUBRIC.json"],
    )

    restricted_fields = [
        "r2_rating_item_id",
        "human_visible_payload_sha256",
        "r1_rating_item_id",
        "replay_record_id",
        "scenario_id",
        "mode_id",
        "generation_logical_request_id",
        "generation_response_blind_id",
        "judge_logical_request_id",
        "judge_result_blind_id",
        "complete_visible_payload_byte_identical",
    ]
    restricted_mapping_bytes = csv_bytes(restricted_fields, restricted_mapping_rows)
    restricted_metadata = {
        "schema_version": "c4-real-human-restricted-mapping-metadata-r2-v1",
        "status": "PASS_RESTRICTED_EXACT_VISIBLE_PAYLOAD_MAPPING_FROZEN",
        "key_commitment": HMAC_KEY_COMMITMENT,
        "hmac_domain_separation": HUMAN_DOMAIN,
        "mapping_filename": RESTRICTED_R2_MAPPING_NAME,
        "mapping_rows": len(restricted_mapping_rows),
        "unique_rating_item_count": len(unique_human_items),
        "duplicate_mapping_count": len(restricted_mapping_rows) - len(unique_human_items),
        "mapping_sha256": sha256_bytes(restricted_mapping_bytes),
        "raw_mapping_content_in_metadata": False,
        "r1_mapping_overwritten": False,
    }

    supersession_records = []
    for name, digest in R1_PACKAGE_HASHES.items():
        supersession_records.append(
            {
                "file_name": name,
                "sha256": digest,
                "artifact_class": "JUDGE" if "JUDGE" in name else "HUMAN_RATER",
                "calls_or_ratings_completed": 0,
                "r3d1_r2_status": "SUPERSEDED_UNEXECUTED_OR_UNRATED_BY_R3D1_R2",
                "bytes_modified": False,
                "deleted_or_overwritten": False,
            }
        )
    supersession = {
        "schema_version": "c4-real-r3d1-r1-package-supersession-r2-v1",
        "status": "PASS_ALL_FIVE_R1_PACKAGES_PRESERVED_AND_SUPERSEDED",
        "records": supersession_records,
    }

    audit = {
        "schema_version": "c4-real-r3d1-r2-preexecution-audit-v1",
        "status": "PASS_INDEPENDENT_PREEXECUTION_AUDIT",
        "audit_scope": "TRANSPORT_AND_EXACT_VISIBLE_PAYLOAD_ONLY_NOT_RESPONSE_QUALITY",
        "judge": {
            "requests_inspected": len(judge_audit["rows"]),
            "applicable_primary_count_distribution": {
                str(key): value for key, value in judge_audit["distribution"].items()
            },
            "r1_parser_requires_provider_overall_applicable_mean": True,
            "r1_parser_local_recomputation_absolute_tolerance": 1e-9,
            "r1_identical_retry_after_mismatch": True,
            "r1_exact_mean_failure": semantic_audit,
            "packages": judge_audit["packages"],
        },
        "human": {
            key: value
            for key, value in human_audit.items()
            if key not in {"rows_by_role", "groups", "packets"}
        },
        "r1_human_packages": human_audit["packets"],
        "provider_calls": 0,
        "judge_calls": 0,
        "response_quality_scores": 0,
        "human_ratings": 0,
        "mode_level_means": "NOT_COMPUTED_PROHIBITED",
        "streamlit_launches": 0,
    }

    combined_judge_manifest = jsonl_bytes(judge_r2_records)
    configuration_set = {
        "schema_version": "c4-real-judge-configuration-set-r3d1-r2-v1",
        "status": "FROZEN_UNEXECUTED_R2",
        "common_semantic_contract": "AUTHORITATIVE_RQ3_0B4_V1_UNCHANGED",
        "shard_configurations": configs,
        "shard_configuration_sha256": {
            shard: judge_manifest["packages"][shard]["configuration_sha256"]
            for shard in "ABC"
        },
        "judge_calls": 0,
    }
    execution_contract_set = {
        "schema_version": "c4-real-judge-execution-contract-set-r2-v1",
        "status": "FROZEN_UNEXECUTED_R2",
        "shard_contracts": contracts,
        "shard_execution_contract_sha256": {
            shard: judge_manifest["packages"][shard]["execution_contract_sha256"]
            for shard in "ABC"
        },
    }
    judge_receipt = {
        "schema_version": "c4-real-judge-protocol-freeze-receipt-r2-v1",
        "status": "FROZEN_READY_FOR_SEPARATELY_AUTHORIZED_EXECUTION_R2",
        "semantic_rubric_unchanged": True,
        "semantic_schema_version": "rq3-judge-response-v1",
        "judge_model": JUDGE_MODEL,
        "temperature": TEMPERATURE,
        "maximum_output_tokens": MAX_OUTPUT_TOKENS,
        "prompt_sha256": sha256_bytes(prompt_r2),
        "schema_sha256": sha256_bytes(schema_r2),
        "parser_sha256": sha256_file(HERE / "judge_result_parser_v2.py"),
        "runner_sha256": sha256_file(HERE / "judge_execution_runner_v2.py"),
        "validator_sha256": sha256_file(HERE / "judge_package_validator_v2.py"),
        "package_test_sha256": sha256_file(HERE / "judge_package_offline_tests_v2.py"),
        "rubric_sha256": RUBRIC_SHA256,
        "applicability_sha256": APPLICABILITY_SHA256,
        "combined_unique_judge_manifest_sha256": sha256_bytes(combined_judge_manifest),
        "unique_judge_request_count": len(judge_r2_records),
        "shards": {
            shard: {
                "request_count": judge_manifest["packages"][shard]["request_count"],
                "estimated_input_tokens": judge_manifest["packages"][shard][
                    "estimated_input_tokens"
                ],
                "maximum_physical_attempts": judge_manifest["packages"][shard][
                    "maximum_physical_attempts"
                ],
                "configuration_sha256": judge_manifest["packages"][shard][
                    "configuration_sha256"
                ],
                "execution_contract_sha256": judge_manifest["packages"][shard][
                    "execution_contract_sha256"
                ],
                "package_sha256": judge_manifest["packages"][shard]["sha256"],
            }
            for shard in "ABC"
        },
        "maximum_physical_attempts": len(judge_r2_records) * 2,
        "judge_calls": 0,
    }
    human_receipt = {
        "schema_version": "c4-real-human-validation-freeze-receipt-r2-v1",
        "status": "FROZEN_READY_FOR_INDEPENDENT_HUMAN_REVIEW_R2",
        "selected_family_count": human_counts["selected_family_count"],
        "condition_level_sample_mappings": human_counts[
            "condition_level_sample_mappings"
        ],
        "unique_human_visible_item_count": human_counts[
            "unique_human_visible_items"
        ],
        "duplicate_mapping_count": human_counts["duplicate_mappings"],
        "maximum_exact_duplicate_group_size": human_counts[
            "maximum_exact_duplicate_group_size"
        ],
        "same_unique_item_set": True,
        "different_deterministic_orders": True,
        "full_criterion_specific_behavioural_anchors_in_guide": True,
        "exact_criterion_specific_na_rules_in_guide": True,
        "guide_sha256": sha256_bytes(guide_r2),
        "primary_rubric_sha256": RUBRIC_SHA256,
        "package_sha256": {
            role: human_manifest["packages"][role]["sha256"] for role in "AB"
        },
        "ratings_completed": 0,
        "rationales_completed": 0,
    }
    source_preservation = {
        "schema_version": "c4-real-r3d1-r2-source-preservation-v1",
        "status": "PASS_FROZEN_R3_RESPONSES_CONDITIONS_AND_R1_PACKAGES_UNCHANGED",
        "starting_head": START_HEAD,
        "response_set_receipt_sha256": RESPONSE_SET_RECEIPT_SHA256,
        "canonical_response_jsonl_sha256": sha256_file(
            R1 / "c4_real_r3_canonical_unique_responses_frozen_v1.jsonl"
        ),
        "canonical_response_csv_sha256": sha256_file(
            R1 / "c4_real_r3_canonical_unique_responses_frozen_v1.csv"
        ),
        "condition_response_jsonl_sha256": sha256_file(
            RESTRICTED / "c4_real_r3_condition_response_records_frozen_v1.jsonl"
        ),
        "condition_response_csv_sha256": sha256_file(
            RESTRICTED / "c4_real_r3_condition_response_records_frozen_v1.csv"
        ),
        "r1_human_mapping_sha256": sha256_file(
            RESTRICTED / "c4_real_human_rating_item_to_condition_mapping_frozen_v1.csv"
        ),
        "hmac_key_commitment": HMAC_KEY_COMMITMENT,
        "r1_package_sha256": R1_PACKAGE_HASHES,
        "canonical_response_identities": 147,
        "distinct_answer_text_hashes": 146,
        "permitted_duplicate_text_groups": 1,
        "permitted_duplicate_text_records": 2,
        "condition_response_mappings": 558,
        "exact_payload_duplicate_condition_mappings": 411,
        "validator_v2_valid_responses": 147,
        "g2_responses_included": 0,
    }
    build_summary = {
        "schema_version": "c4-real-r3d1-r2-build-summary-v1",
        "status": "PASS_R3D1_R2_ARTIFACTS_MATERIALIZED_ONCE",
        "judge_requests": len(judge_r2_records),
        "judge_shards": {shard: 49 for shard in "ABC"},
        "judge_package_tests_passed": {
            shard: judge_manifest["packages"][shard]["offline_package_tests_passed"]
            for shard in "ABC"
        },
        "human_condition_mappings": 108,
        "human_unique_visible_items": 44,
        "human_duplicate_mappings": 64,
        "provider_calls": 0,
        "judge_calls": 0,
        "scoring_calls": 0,
        "human_rating_actions": 0,
        "streamlit_launches": 0,
    }

    tracked = {
        "C4_REAL_R3D1_R2_PREEXECUTION_AUDIT.md": preexecution_audit_markdown(audit),
        "c4_real_r3d1_r2_preexecution_audit_v1.json": pretty_json_bytes(audit),
        "c4_real_judge_prompt_r2_provider_compatible.txt": prompt_r2,
        "c4_real_judge_schema_r2_provider_compatible.json": schema_r2,
        "C4_REAL_JUDGE_PROVIDER_CONTRACT_R1_R2_COMPATIBILITY_NOTE.md": compatibility_note(
            sha256_bytes(judge_audit["common"]["JUDGE_PROMPT.txt"]),
            sha256_bytes(prompt_r2),
            sha256_bytes(judge_audit["common"]["JUDGE_SCHEMA.json"]),
            sha256_bytes(schema_r2),
            semantic_audit,
        ),
        "c4_real_unique_judge_request_manifest_frozen_r2.jsonl": combined_judge_manifest,
        "c4_real_judge_configuration_set_frozen_r2.json": pretty_json_bytes(configuration_set),
        "c4_real_judge_execution_contract_set_r2.json": pretty_json_bytes(execution_contract_set),
        "c4_real_judge_package_manifest_r2_v1.json": pretty_json_bytes(judge_manifest),
        "C4_REAL_JUDGE_PROTOCOL_FREEZE_RECEIPT_R2.json": pretty_json_bytes(judge_receipt),
        "HUMAN_RATER_GUIDE_R2.md": guide_r2,
        "human_rating_packet_A_R2.csv": tracked_human_csv["A"],
        "human_rating_packet_B_R2.csv": tracked_human_csv["B"],
        "human_rater_attestation_A_R2.md": human_attestation("A"),
        "human_rater_attestation_B_R2.md": human_attestation("B"),
        "C4_REAL_HUMAN_VISIBLE_ITEM_DEDUPLICATION_METHOD.md": human_method_note(),
        "c4_real_human_packet_manifest_r2_v1.json": pretty_json_bytes(human_manifest),
        "c4_real_human_restricted_mapping_metadata_r2_v1.json": pretty_json_bytes(
            restricted_metadata
        ),
        "C4_REAL_HUMAN_VALIDATION_FREEZE_RECEIPT_R2.json": pretty_json_bytes(
            human_receipt
        ),
        "c4_real_r3d1_r1_package_supersession_r2_v1.json": pretty_json_bytes(
            supersession
        ),
        "c4_real_r3d1_r2_source_preservation_manifest_v1.json": pretty_json_bytes(
            source_preservation
        ),
        "c4_real_r3d1_r2_build_summary_v1.json": pretty_json_bytes(build_summary),
        "STATUS.md": status_markdown(),
    }
    external = {**judge_external, **human_external}
    for name in tracked:
        require(not (HERE / name).exists(), f"tracked R2 target exists: {name}")
    for name in external:
        require(not (DOWNLOADS / name).exists(), f"external R2 target exists: {name}")

    for name, data in tracked.items():
        materialize_once(HERE / name, data)
    materialize_once(
        RESTRICTED / RESTRICTED_R2_MAPPING_NAME,
        restricted_mapping_bytes,
        0o600,
    )
    for name, data in external.items():
        materialize_once(DOWNLOADS / name, data)

    restricted_path = RESTRICTED / RESTRICTED_R2_MAPPING_NAME
    require(stat.S_IMODE(restricted_path.stat().st_mode) == 0o600, "R2 mapping mode differs")
    require(
        subprocess.run(
            ["git", "check-ignore", "-q", str(restricted_path.relative_to(REPO))],
            cwd=REPO,
        ).returncode
        == 0,
        "R2 restricted mapping is not ignored",
    )
    for name, expected in R1_PACKAGE_HASHES.items():
        require(sha256_file(DOWNLOADS / name) == expected, f"R1 Package changed: {name}")
    print(json.dumps(build_summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
