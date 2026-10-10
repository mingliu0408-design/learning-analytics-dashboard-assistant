"""Build the RQ2-V2 Stage 4M DEV specialist-composition analysis offline.

This module has no provider client, network path, TEST adapter, learned model,
or production integration.  It reads only frozen repository artifacts, checks
their SHA-256 bindings and populations, and then performs deterministic joins,
compositions, scoring, family-cluster bootstrap resampling, and reporting.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import random
import re
import subprocess
from typing import Any, Iterable, Mapping, Sequence

from ..track_j_p1_protocol import p1_protocol as p1
from ..track_j_p1_protocol import run_p1_dev_selection as stage4j


TRACK_DIR = Path(__file__).resolve().parent
STAGE4_DIR = TRACK_DIR.parent
REPO_ROOT = TRACK_DIR.parents[2]

DEV_DIR = STAGE4_DIR / "dev_protocol"
TRACK_G_DIR = STAGE4_DIR / "track_g_b0_b1"
TRACK_I_DIR = STAGE4_DIR / "track_i_b4"
TRACK_J_DIR = STAGE4_DIR / "track_j_p1_protocol"
TRACK_K0_DIR = STAGE4_DIR / "track_k0_specialists"
TRACK_K_DIR = STAGE4_DIR / "track_k_rag_specialist_execution"
TRACK_L_DIR = STAGE4_DIR / "track_l_memory_specialist_execution"

STAGE4M_STARTING_HEAD = "1aabe2c4f2c1f4b2cc23ea3b4b93eec96cf667b7"
SOURCE_COMMITS = (
    "4dc4cd7d4e5cc0065f0acc194f3dce4beac27e32",
    "84b1e8051b8d33fd2d185c6b32250a4622e8fd0a",
    "956fcfbb2c20ac2d43ff9f947fa8b5bb9e154731",
)
INTEGRATED_COMMITS = (
    "a2f6759afa984f98741e15c1fcd16625a2cd9c36",
    "4fab9eb6204611a961e8f65eb8a5c427afbcf2ea",
    "608637c1fa99f689be76012dc5c297519aba7889",
)
EXPECTED_BRANCH = "research/rq2-v2-stage4-m-specialist-composition"
EXPECTED_MODEL = "gpt-4o-mini-2024-07-18"

P2_ID = "R2V2-P2_RAG_SPECIALIST_COMPOSITION"
P3_ID = "R2V2-P3_RAG_MEMORY_SPECIALISTS"
P4_ID = "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION"
METHOD_ORDER = ("B4", "P1", "P2", "P3", "P4")
FACTORIAL_ORDER = ("B4", "P2", "P4", "P3")
CAPABILITY_NAMES = ("rag_required", "memory_required", "planning_required")
CAPABILITY_LABELS = ("RAG", "MEMORY", "PLANNING")
BOOTSTRAP_SEED = 20260831
BOOTSTRAP_REPLICATES = 10_000
INPUT_PRICE_PER_MILLION = Decimal("0.15")
OUTPUT_PRICE_PER_MILLION = Decimal("0.60")
TEST_IDENTIFIER_PATTERN = re.compile(
    r"(?:^|[-_])(?:TEST|TST)(?:$|[-_])", re.IGNORECASE
)

METHOD_SPECS: dict[str, dict[str, Any]] = {
    "B4": {
        "method_id": "R2V2-B4_JOINT_LLM",
        "status": "FROZEN_AFTER_DEV_EXECUTION",
        "development_status": "FROZEN_JOINT_BASELINE",
        "rag_source": "B4",
        "memory_source": "B4",
        "planning_source": "B4",
    },
    "P1": {
        "method_id": "R2V2-P1_HYBRID_NESTED_OOF",
        "status": "FROZEN_AFTER_DEV_SELECTION",
        "development_status": "FROZEN_NESTED_DEV_SELECTION",
        "rag_source": "P1_COMPLETE_SIGNATURE",
        "memory_source": "P1_COMPLETE_SIGNATURE",
        "planning_source": "P1_COMPLETE_SIGNATURE",
    },
    "P2": {
        "method_id": P2_ID,
        "status": "FROZEN_AFTER_DEV_COMPOSITION_EVALUATION",
        "development_status": "PREDECLARED_PRIMARY_SPECIALIST_EXTENSION",
        "rag_source": "RAG_SPECIALIST",
        "memory_source": "B4",
        "planning_source": "B4",
    },
    "P3": {
        "method_id": P3_ID,
        "status": "FROZEN_AFTER_DEV_COMPOSITION_EVALUATION",
        "development_status": "PREDECLARED_SECONDARY_SPECIALIST_EXTENSION",
        "rag_source": "RAG_SPECIALIST",
        "memory_source": "MEMORY_SPECIALIST",
        "planning_source": "B4",
    },
    "P4": {
        "method_id": P4_ID,
        "status": "FROZEN_POST_DEV_EXPLORATORY_ABLATION_BEFORE_TEST",
        "development_status": "POST_DEV_EXPLORATORY_ABLATION_FROZEN_BEFORE_TEST",
        "rag_source": "B4",
        "memory_source": "MEMORY_SPECIALIST",
        "planning_source": "B4",
    },
}

# Every frozen input used by Stage 4M is checked before any generated output is
# written.  Paths are relative to STAGE4_DIR.
SOURCE_ARTIFACTS: dict[str, tuple[str, str]] = {
    "dev_gold": (
        "dev_protocol/dev_capability_gold_v1.csv",
        "8d3422198a99422b3e314c60819f3553ff27cd42394ed2d9f68c0eb3ce858b56",
    ),
    "dev_folds": (
        "dev_protocol/dev_cv_folds_v1.csv",
        "2a3a4161c81bddfcfe51b238ac5940c64df87a25beed26e54671b64c76c5ab46",
    ),
    "dev_grouping": (
        "dev_protocol/dev_atomic_group_map_v1.csv",
        "f1ac8973c590155ee3730de194b4c2afd6d05531744bef70a163be2428d4bd6f",
    ),
    "b4_predictions": (
        "track_i_b4/b4_dev_predictions_v2.csv",
        "f0e776492779341fd4e1feb6d11f2a915246162697f222b1c7c933882e552d39",
    ),
    "b4_attempts": (
        "track_i_b4/b4_dev_attempt_records_v2.jsonl",
        "a8e8a66394d159e1af88a153654c63437176ba869dbf0c02f12c43ec1138b1a7",
    ),
    "b4_usage": (
        "track_i_b4/b4_dev_usage_and_cost_v2.json",
        "503d079b8bebdd613eaaede7c10b7ff31e32e227c02f759a642efe29a8b84c1d",
    ),
    "b4_configuration": (
        "track_i_b4/b4_final_frozen_configuration_v2.json",
        "12a75dd33298f6e1078b326e7c922eb92f2675ee87c7f7858fdf19494072d470",
    ),
    "b4_prompt": (
        "track_i_b4/b4_prompt_template_frozen_v1.txt",
        "62dd0072b40f812bea9d2400bf5053c1d727187c47cab3c8777a341e0a185541",
    ),
    "b4_schema": (
        "track_i_b4/b4_response_schema_v2.json",
        "8017f1677e3ddc0bdd5042cff1c87e1e8ef4053da10b5c86da2cf45c35319876",
    ),
    "b4_final_examples": (
        "track_i_b4/b4_final_dev_examples_v1.csv",
        "34f12e80a654bb79a7103e35a14c5df058e4a54c8831c27d73756355754fb5b3",
    ),
    "b4_final_prompt_package": (
        "track_i_b4/b4_final_full_dev_prompt_package_v1.json",
        "245a4f74d2428017ab36fc5eaba41c6f617b5ec01c099153b23524a0d33734d5",
    ),
    "rag_predictions": (
        "track_k_rag_specialist_execution/rag_specialist_predictions_v1.csv",
        "b867030addc64d7a02e65513e593b9fb5c013e3d3cf18fea103564d260ac58ff",
    ),
    "rag_attempts": (
        "track_k_rag_specialist_execution/rag_specialist_attempt_records_v1.jsonl",
        "81580dd1516bfe5e344cee89961baf648ad4a01e8616283af1517d226c1a4b5b",
    ),
    "rag_usage": (
        "track_k_rag_specialist_execution/rag_specialist_usage_and_cost_v1.json",
        "90820e5fb35f99c587caa34040036064e0945945a281b93ecf1414a4bd9bfcd3",
    ),
    "rag_configuration": (
        "track_k_rag_specialist_execution/rag_specialist_frozen_configuration_v1.json",
        "19fc104b55ed92ec6c9a988fe6664d5f062f92e473a5ff4d77f8c88aa871c7cc",
    ),
    "rag_prompt": (
        "track_k0_specialists/rag_specialist_prompt_frozen_v1.txt",
        "e0e34a097ec0449e2cedfa305d43c7aad7b096ca5fb0a64dc54ad39e9c035d5c",
    ),
    "rag_schema": (
        "track_k0_specialists/rag_specialist_schema_v1.json",
        "3a304b91bc642e8d04f59077b4f1240bf5f242105f888cfdb634ffa858901866",
    ),
    "rag_final_examples": (
        "track_k0_specialists/rag_specialist_final_examples_v1.csv",
        "ed6a66364d952041b3a2ce45c11c836646e9fe17e8d5173d8f6b6f4040261221",
    ),
    "rag_final_prompt_package": (
        "track_k0_specialists/rag_specialist_final_full_dev_prompt_package_v1.json",
        "60c5d9de78bf60c2b186c46ab3c935511c2a994bc8974a2bc965e5aa2ffc6f55",
    ),
    "memory_predictions": (
        "track_l_memory_specialist_execution/memory_specialist_predictions_v1.csv",
        "386f3695af5fa966e4c851d431a574c88ea803feccf6190534380cb106626b85",
    ),
    "memory_attempts": (
        "track_l_memory_specialist_execution/memory_specialist_attempt_records_v1.jsonl",
        "d13e83f8ae8aff6216d79e1e71b2bcf530d9fbb73e643561e1ca90d6fa50ad72",
    ),
    "memory_usage": (
        "track_l_memory_specialist_execution/memory_specialist_usage_and_cost_v1.json",
        "b28a8bc87b4d661bc30f7ced1a8a2bf848f9bf29c0291a12261b820d315cc1cf",
    ),
    "memory_configuration": (
        "track_l_memory_specialist_execution/memory_specialist_frozen_configuration_v1.json",
        "8813854b4a73e4c07416e26db0b72f28ab1923f415053f8d48ad31b0eca0a3c3",
    ),
    "memory_prompt": (
        "track_k0_specialists/memory_specialist_prompt_frozen_v1.txt",
        "c8a53b27f16b84ef0373ddfdd20eab997cc986eab10a93a138ede06571ebab04",
    ),
    "memory_schema": (
        "track_k0_specialists/memory_specialist_schema_v1.json",
        "41a0f015b3fd7589bd1a08bd1d3e2a7c8bd5491b22c2531ef43ead634642a3d7",
    ),
    "memory_final_examples": (
        "track_k0_specialists/memory_specialist_final_examples_v1.csv",
        "42d813fbd2082245bb6ca2065fb007c0d8d6b7b8e79e21aa70f7f97251785808",
    ),
    "memory_final_prompt_package": (
        "track_k0_specialists/memory_specialist_final_full_dev_prompt_package_v1.json",
        "ba27b9ee29960d0dfe67389f685e3338ff90b4ed71b57756a0e3abe890eb6875",
    ),
    "p1_predictions": (
        "track_j_p1_protocol/p1_nested_oof_predictions_v1.csv",
        "2f12e03015ec8fc4898000c18f52e38509000e15ba5a018a8f7e8664d97d79fd",
    ),
    "p1_configuration": (
        "track_j_p1_protocol/p1_final_policy_frozen_v1.json",
        "011f11ce244b564f87b4a555d8d0b0d4e2113bc9b77ab58c6ba2d5118d58d855",
    ),
    "p1_cost": (
        "track_j_p1_protocol/p1_counterfactual_cost_v1.json",
        "51f2a583a26466ef2cb8e656a0b7f9621f54a8894c76a24cb69f00e37ae0eb40",
    ),
    "clarification_predictions": (
        "track_g_b0_b1/clarification_oof_predictions_v1.csv",
        "792308cbd4382466778721b6eafebd023a516e684ee19cd39483af1cbde72aa8",
    ),
    "clarification_gate": (
        "track_g_b0_b1/clarification_gate_frozen_v1.json",
        "ca411f9ef8711811b3aa5408b79e28463cef432fe3fc31bf106d3fa80a350438",
    ),
    "p2_contract": (
        "track_k0_specialists/p2_rag_specialist_composition_contract_v1.json",
        "532bd513cc9b5f11003036ecbbc492f0305e359ae48f6cb133a05fe43d26f6ad",
    ),
    "p3_contract": (
        "track_k0_specialists/p3_capability_specialists_composition_contract_v1.json",
        "36e4c0589979f762568d29680a6d76b8c6116680072c051d00b2c5739e030288",
    ),
    "specialist_evaluation_protocol": (
        "track_k0_specialists/specialist_evaluation_protocol_v1.json",
        "92d9e675b5871e3c5af8865404893030ae9e7bbf611130d62463a42ab3b360bc",
    ),
    "stage4j_metric_implementation": (
        "track_j_p1_protocol/run_p1_dev_selection.py",
        "9f337a4b2c5861837c4a95de6fccef2fb379fd2de2daf0ecac48dff7b1b2eb3f",
    ),
    "stage4j_p1_semantics": (
        "track_j_p1_protocol/p1_protocol.py",
        "b2c865a0e5379b635f94787df035a4d3cb61005cdd1c450d137e17dae819729d",
    ),
}

EXAMPLE_SET_HASHES = {
    "B4": "020ec80b8b592a62c9975b47bf5bc63c9dd86c029da05a6a4afd43440291aff2",
    "RAG_SPECIALIST": "a932596e126ab66c054173bd1b9c454cbba9988e9d0b418da2d80c3e1df1e6eb",
    "MEMORY_SPECIALIST": "57a7aecd53710a1587388711177d7564f4560f1a8729939d445268d2514d3eb4",
}


class Stage4MError(RuntimeError):
    """Raised when a frozen input or deterministic analysis invariant differs."""


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    approximate_cost_usd: Decimal


@dataclass(frozen=True)
class Stage4MRecord:
    base: stage4j.DevRecord
    rag_specialist: bool
    memory_specialist: bool
    p1_signature: p1.CapabilitySignature
    rag_usage: Usage
    memory_usage: Usage

    @property
    def annotation_case_id(self) -> str:
        return self.base.annotation_case_id


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage4MError(f"expected one JSON object: {path}")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _json_text(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _jsonl_text(rows: Iterable[Mapping[str, Any]]) -> str:
    return "".join(
        json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + "\n"
        for row in rows
    )


def _csv_text(rows: Iterable[Mapping[str, Any]], fields: Sequence[str]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(fields), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    return buffer.getvalue()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="")
    temporary.replace(path)


def _parse_bool(value: Any) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise Stage4MError(f"expected Boolean value, received {value!r}")


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _signature(values: Sequence[bool]) -> p1.CapabilitySignature:
    if len(values) != 3:
        raise Stage4MError("complete capability signature requires three bits")
    return p1.CapabilitySignature(*values)


def _signature_text(value: p1.CapabilitySignature) -> str:
    return "".join("1" if bit else "0" for bit in value.bits)


def _safe_div(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator), 12) if denominator else 0.0


def _cost(input_tokens: int, output_tokens: int) -> Decimal:
    return (
        Decimal(input_tokens) * INPUT_PRICE_PER_MILLION
        + Decimal(output_tokens) * OUTPUT_PRICE_PER_MILLION
    ) / Decimal(1_000_000)


def _cost_text(value: Decimal) -> str:
    return format(value, ".8f")


def _unique_rows(
    rows: Sequence[Mapping[str, Any]], source: str
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        case_id = str(row.get("annotation_case_id", ""))
        if not case_id or TEST_IDENTIFIER_PATTERN.search(case_id):
            raise Stage4MError(f"empty or prohibited case ID in {source}: {case_id}")
        if case_id in result:
            raise Stage4MError(f"duplicate case ID in {source}: {case_id}")
        result[case_id] = row
    return result


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _patch_id(commit: str) -> str:
    shown = subprocess.run(
        ["git", "show", "--pretty=format:", "--binary", commit],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    patched = subprocess.run(
        ["git", "patch-id", "--stable"],
        cwd=REPO_ROOT,
        input=shown.stdout,
        check=True,
        capture_output=True,
    )
    return patched.stdout.decode("utf-8").split()[0]


def verify_git_integration() -> dict[str, Any]:
    if _git("branch", "--show-current") != EXPECTED_BRANCH:
        raise Stage4MError("Stage 4M branch differs from the authorized branch")
    history = _git(
        "rev-list", "--reverse", f"{STAGE4M_STARTING_HEAD}..HEAD"
    ).splitlines()
    if history[:3] != list(INTEGRATED_COMMITS):
        raise Stage4MError("K0, K, and L are not the first three integrations in order")
    if len(history) not in {3, 4}:
        raise Stage4MError("unexpected commit count after the Stage 4M starting HEAD")
    if len(history) == 4:
        subject = _git("show", "-s", "--format=%s", history[3])
        if subject != "RQ2-V2 Stage 4M: evaluate and freeze specialist compositions on DEV":
            raise Stage4MError("unexpected fourth commit after the three integrations")
    previous = STAGE4M_STARTING_HEAD
    bindings = []
    for source, integrated in zip(SOURCE_COMMITS, INTEGRATED_COMMITS, strict=True):
        if _git("rev-parse", f"{integrated}^") != previous:
            raise Stage4MError("integrated specialist commit parent differs")
        source_patch = _patch_id(source)
        integrated_patch = _patch_id(integrated)
        if source_patch != integrated_patch:
            raise Stage4MError(f"integrated patch differs from source commit {source}")
        bindings.append(
            {
                "source_commit": source,
                "integrated_commit": integrated,
                "stable_patch_id": source_patch,
            }
        )
        previous = integrated
    return {"status": "PASS", "ordered_integrations": bindings}


def _verify_usage(
    attempts: Sequence[Mapping[str, Any]], usage: Mapping[str, Any], usage_key: str
) -> Usage:
    input_tokens = sum(int(row["input_tokens"]) for row in attempts)
    output_tokens = sum(int(row["output_tokens"]) for row in attempts)
    total_tokens = sum(int(row["total_tokens"]) for row in attempts)
    if input_tokens + output_tokens != total_tokens:
        raise Stage4MError("attempt token arithmetic differs")
    frozen = usage[usage_key]
    if (
        int(frozen["input_tokens"]) != input_tokens
        or int(frozen["output_tokens"]) != output_tokens
        or int(frozen["total_tokens"]) != total_tokens
        or int(frozen["physical_attempts"]) != len(attempts)
    ):
        raise Stage4MError("frozen usage totals differ from attempt records")
    observed_cost = _cost(input_tokens, output_tokens)
    if Decimal(str(usage["approximate_cost_usd"]["total"])) != observed_cost:
        raise Stage4MError("frozen approximate cost differs from token arithmetic")
    return Usage(input_tokens, output_tokens, total_tokens, observed_cost)


def verify_sources() -> dict[str, Any]:
    git_binding = verify_git_integration()
    artifacts = []
    for role, (relative, expected) in SOURCE_ARTIFACTS.items():
        path = STAGE4_DIR / relative
        if not path.is_file():
            raise Stage4MError(f"required frozen artifact missing: {relative}")
        observed = sha256_file(path)
        if observed != expected:
            raise Stage4MError(f"frozen artifact hash mismatch: {relative}")
        artifacts.append(
            {
                "role": role,
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "sha256": observed,
                "size_bytes": path.stat().st_size,
            }
        )

    if stage4j.verify_frozen_stage4j0()["status"] != "PASS":
        raise Stage4MError("Stage 4J-0 frozen verification failed")
    if stage4j.verify_b4_binding()["status"] != "PASS":
        raise Stage4MError("frozen B4 verification failed")
    stage4j.verify_source_hashes()

    b4 = _load_json(TRACK_I_DIR / "b4_final_frozen_configuration_v2.json")
    rag = _load_json(TRACK_K_DIR / "rag_specialist_frozen_configuration_v1.json")
    memory = _load_json(
        TRACK_L_DIR / "memory_specialist_frozen_configuration_v1.json"
    )
    p1_freeze = _load_json(TRACK_J_DIR / "p1_final_policy_frozen_v1.json")
    if (
        b4.get("B4_MODEL_STATUS") != "FROZEN_AFTER_DEV_EXECUTION"
        or b4.get("model_snapshot") != EXPECTED_MODEL
        or b4.get("prompt_sha256") != SOURCE_ARTIFACTS["b4_prompt"][1]
        or b4.get("response_schema_v2_sha256") != SOURCE_ARTIFACTS["b4_schema"][1]
        or b4.get("execution_evidence", {}).get("valid_predictions") != 64
        or b4.get("full_dev_examples", {}).get("example_set_sha256")
        != EXAMPLE_SET_HASHES["B4"]
    ):
        raise Stage4MError("B4 frozen configuration binding differs")
    if (
        rag.get("RAG_SPECIALIST_STATUS") != "FROZEN_AFTER_DEV_EXECUTION"
        or rag.get("model_snapshot") != EXPECTED_MODEL
        or rag.get("prompt_sha256") != SOURCE_ARTIFACTS["rag_prompt"][1]
        or rag.get("schema_sha256") != SOURCE_ARTIFACTS["rag_schema"][1]
        or rag.get("actual_logical_terminal_results") != 64
        or rag.get("final_full_dev_examples_and_order", {}).get(
            "specialist_example_set_sha256"
        )
        != EXAMPLE_SET_HASHES["RAG_SPECIALIST"]
    ):
        raise Stage4MError("RAG Specialist frozen configuration binding differs")
    if (
        memory.get("MEMORY_SPECIALIST_STATUS") != "FROZEN_AFTER_DEV_EXECUTION"
        or memory.get("model_snapshot") != EXPECTED_MODEL
        or memory.get("prompt_sha256") != SOURCE_ARTIFACTS["memory_prompt"][1]
        or memory.get("schema_sha256") != SOURCE_ARTIFACTS["memory_schema"][1]
        or memory.get("execution_evidence", {}).get("valid_predictions") != 64
        or memory.get("final_full_dev_examples_and_order", {}).get(
            "specialist_example_set_sha256"
        )
        != EXAMPLE_SET_HASHES["MEMORY_SPECIALIST"]
    ):
        raise Stage4MError("Memory Specialist frozen configuration binding differs")
    if (
        p1_freeze.get("P1_MODEL_STATUS") != "FROZEN_AFTER_DEV_SELECTION"
        or p1_freeze.get("final_policy_id") != "P1-C08-NONUNANIMOUS"
        or p1_freeze.get("decision_count") != 64
    ):
        raise Stage4MError("P1 frozen policy binding differs")
    p2_contract = _load_json(
        TRACK_K0_DIR / "p2_rag_specialist_composition_contract_v1.json"
    )
    p3_contract = _load_json(
        TRACK_K0_DIR / "p3_capability_specialists_composition_contract_v1.json"
    )
    if p2_contract.get("composition_id") != P2_ID:
        raise Stage4MError("P2 predeclared composition ID differs")
    if p3_contract.get("composition_id") != P3_ID:
        raise Stage4MError("P3 predeclared composition ID differs")
    return {
        "schema_version": "rq2-v2-stage4m-source-verification-v1",
        "status": "PASS_ALL_FROZEN_SOURCE_BINDINGS",
        "git_integration": git_binding,
        "artifacts": artifacts,
        "model_snapshot": EXPECTED_MODEL,
        "component_statuses": {
            "B4": b4["B4_MODEL_STATUS"],
            "RAG_SPECIALIST": rag["RAG_SPECIALIST_STATUS"],
            "MEMORY_SPECIALIST": memory["MEMORY_SPECIALIST_STATUS"],
            "P1": p1_freeze["P1_MODEL_STATUS"],
        },
        "prompt_schema_hashes": {
            "B4": {
                "prompt_sha256": SOURCE_ARTIFACTS["b4_prompt"][1],
                "schema_sha256": SOURCE_ARTIFACTS["b4_schema"][1],
            },
            "RAG_SPECIALIST": {
                "prompt_sha256": SOURCE_ARTIFACTS["rag_prompt"][1],
                "schema_sha256": SOURCE_ARTIFACTS["rag_schema"][1],
            },
            "MEMORY_SPECIALIST": {
                "prompt_sha256": SOURCE_ARTIFACTS["memory_prompt"][1],
                "schema_sha256": SOURCE_ARTIFACTS["memory_schema"][1],
            },
        },
        "full_dev_example_set_hashes": dict(EXAMPLE_SET_HASHES),
        "test_identifiers_present": False,
        "test_access": False,
        "rq3_access": False,
        "stage4m_provider_calls": 0,
    }


def _attempt_usage(row: Mapping[str, Any]) -> Usage:
    input_tokens = int(row["input_tokens"])
    output_tokens = int(row["output_tokens"])
    total_tokens = int(row["total_tokens"])
    if input_tokens + output_tokens != total_tokens:
        raise Stage4MError("per-case token arithmetic differs")
    return Usage(input_tokens, output_tokens, total_tokens, _cost(input_tokens, output_tokens))


def load_records() -> tuple[list[Stage4MRecord], dict[str, Any]]:
    base_records = stage4j.load_normalized_records()
    base_by_id = {row.annotation_case_id: row for row in base_records}
    if len(base_by_id) != 64:
        raise Stage4MError("frozen DEV Gold does not contain 64 unique ANSWER cases")

    b4_predictions = _unique_rows(
        _load_csv(TRACK_I_DIR / "b4_dev_predictions_v2.csv"), "B4 predictions"
    )
    rag_predictions = _unique_rows(
        _load_csv(TRACK_K_DIR / "rag_specialist_predictions_v1.csv"),
        "RAG Specialist predictions",
    )
    memory_predictions = _unique_rows(
        _load_csv(TRACK_L_DIR / "memory_specialist_predictions_v1.csv"),
        "Memory Specialist predictions",
    )
    p1_predictions = _unique_rows(
        _load_csv(TRACK_J_DIR / "p1_nested_oof_predictions_v1.csv"),
        "P1 nested OOF predictions",
    )
    rag_attempts = _unique_rows(
        _load_jsonl(TRACK_K_DIR / "rag_specialist_attempt_records_v1.jsonl"),
        "RAG Specialist attempts",
    )
    memory_attempts = _unique_rows(
        _load_jsonl(TRACK_L_DIR / "memory_specialist_attempt_records_v1.jsonl"),
        "Memory Specialist attempts",
    )

    gold_answer_rows = _unique_rows(
        [
            row
            for row in _load_csv(DEV_DIR / "dev_capability_gold_v1.csv")
            if row["partition"] == "DEV" and row["final_dialogue_action"] == "ANSWER"
        ],
        "DEV Gold ANSWER rows",
    )
    grouping_rows = _unique_rows(
        [
            row
            for row in _load_csv(DEV_DIR / "dev_atomic_group_map_v1.csv")
            if row["annotation_case_id"] in base_by_id
        ],
        "scenario-family and contrast metadata",
    )
    validation_fold_rows = _unique_rows(
        [
            row
            for row in _load_csv(DEV_DIR / "dev_cv_folds_v1.csv")
            if row["fold_role"] == "VALIDATION"
            and row["final_dialogue_action"] == "ANSWER"
        ],
        "outer-fold validation rows",
    )
    sources = {
        "human_gold": set(gold_answer_rows),
        "joint_b4": set(b4_predictions),
        "rag_specialist": set(rag_predictions),
        "memory_specialist": set(memory_predictions),
        "p1_nested_oof": set(p1_predictions),
        "scenario_family_and_contrast": set(grouping_rows),
        "outer_folds": set(validation_fold_rows),
        "page_metadata": set(gold_answer_rows),
    }
    expected_ids = set(base_by_id)
    for source, identifiers in sources.items():
        if identifiers != expected_ids:
            raise Stage4MError(f"64-case join differs for {source}")

    rag_attempt_rows = list(rag_attempts.values())
    memory_attempt_rows = list(memory_attempts.values())
    _verify_usage(
        rag_attempt_rows,
        _load_json(TRACK_K_DIR / "rag_specialist_usage_and_cost_v1.json"),
        "actual_provider_usage",
    )
    _verify_usage(
        memory_attempt_rows,
        _load_json(TRACK_L_DIR / "memory_specialist_usage_and_cost_v1.json"),
        "actual_provider_usage",
    )

    records: list[Stage4MRecord] = []
    for case_id in sorted(expected_ids, key=lambda value: value.encode("utf-8")):
        base = base_by_id[case_id]
        b4_row = b4_predictions[case_id]
        rag_row = rag_predictions[case_id]
        memory_row = memory_predictions[case_id]
        p1_row = p1_predictions[case_id]
        rag_attempt = rag_attempts[case_id]
        memory_attempt = memory_attempts[case_id]
        fold_row = validation_fold_rows[case_id]
        group_row = grouping_rows[case_id]
        gold_row = gold_answer_rows[case_id]

        fold_values = {
            base.outer_fold,
            str(b4_row["fold_id"]),
            str(rag_row["fold_id"]),
            str(memory_row["fold_id"]),
            str(p1_row["outer_fold"]),
            str(rag_attempt["fold_id"]),
            str(memory_attempt["fold_id"]),
            str(fold_row["fold_id"]),
        }
        if len(fold_values) != 1:
            raise Stage4MError(f"fold mismatch for {case_id}")
        if {
            base.scenario_family_id,
            str(p1_row["scenario_family_id"]),
            str(group_row["scenario_family_id"]),
            str(gold_row["scenario_family_id"]),
        } != {base.scenario_family_id}:
            raise Stage4MError(f"scenario-family mismatch for {case_id}")
        if {
            base.current_page,
            str(p1_row["current_page"]),
            str(group_row["current_page"]),
            str(gold_row["current_page"]),
        } != {base.current_page}:
            raise Stage4MError(f"page metadata mismatch for {case_id}")
        if (
            str(group_row["dev_contrast_group_id"]) != base.dev_contrast_group_id
            or str(group_row["dev_contrast_axis"]) != base.dev_contrast_axis
        ):
            raise Stage4MError(f"contrast metadata mismatch for {case_id}")

        for source_name, prediction_row, attempt_row in (
            ("RAG Specialist", rag_row, rag_attempt),
            ("Memory Specialist", memory_row, memory_attempt),
        ):
            if (
                prediction_row["terminal_status"] != "VALID_PREDICTION"
                or int(prediction_row["attempts_used"]) != 1
                or prediction_row["requested_model"] != EXPECTED_MODEL
                or prediction_row["returned_model"] != EXPECTED_MODEL
                or attempt_row["requested_model"] != EXPECTED_MODEL
                or attempt_row["returned_model"] != EXPECTED_MODEL
                or attempt_row.get("provider_error") is not None
                or not bool(attempt_row.get("schema_validation", {}).get("valid"))
            ):
                raise Stage4MError(f"invalid frozen {source_name} result for {case_id}")
        if (
            b4_row["terminal_status"] != "VALID_PREDICTION"
            or b4_row["returned_model"] != EXPECTED_MODEL
        ):
            raise Stage4MError(f"invalid frozen B4 result for {case_id}")

        rag_value = _parse_bool(rag_row["rag_required"])
        memory_value = _parse_bool(memory_row["memory_required"])
        if bool(rag_attempt["parsed_json"]["rag_required"]) != rag_value:
            raise Stage4MError(f"RAG Specialist attempt/prediction mismatch: {case_id}")
        if bool(memory_attempt["parsed_json"]["memory_required"]) != memory_value:
            raise Stage4MError(f"Memory Specialist attempt/prediction mismatch: {case_id}")
        p1_signature = _signature(
            [
                _parse_bool(p1_row["predicted_rag_required"]),
                _parse_bool(p1_row["predicted_memory_required"]),
                _parse_bool(p1_row["predicted_planning_required"]),
            ]
        )
        if (
            str(p1_row["predicted_capability_signature"])
            != _signature_text(p1_signature)
            or str(p1_row["gold_capability_signature"])
            != _signature_text(base.gold)
        ):
            raise Stage4MError(f"P1 signature mismatch for {case_id}")
        records.append(
            Stage4MRecord(
                base=base,
                rag_specialist=rag_value,
                memory_specialist=memory_value,
                p1_signature=p1_signature,
                rag_usage=_attempt_usage(rag_attempt),
                memory_usage=_attempt_usage(memory_attempt),
            )
        )

    if Counter(row.base.outer_fold for row in records) != Counter(
        {f"DEV-CV-FOLD-{index}": 16 for index in range(1, 5)}
    ):
        raise Stage4MError("outer-fold population differs from 16 cases per fold")
    families = Counter(row.base.scenario_family_id for row in records)
    if len(families) != 32 or set(families.values()) != {2}:
        raise Stage4MError("core DEV family structure differs from 32 pairs")
    axes = Counter(
        (row.base.dev_contrast_group_id, row.base.dev_contrast_axis)
        for row in records
        if row.base.dev_contrast_group_id
        and row.base.dev_contrast_axis in {"RAG", "MEMORY", "PLANNING"}
    )
    if len(axes) != 8 or set(axes.values()) != {4}:
        raise Stage4MError("eligible capability contrast structure differs from eight groups")
    return records, {
        "join_key": "annotation_case_id",
        "case_count": 64,
        "identical_case_sets": sorted(sources),
        "outer_fold_counts": dict(sorted(Counter(row.base.outer_fold for row in records).items())),
        "family_count": 32,
        "eligible_capability_contrast_group_count": 8,
        "test_identifier_count": 0,
    }


def compose_signature(
    method: str,
    *,
    b4: p1.CapabilitySignature | None,
    rag_specialist: bool | None,
    memory_specialist: bool | None,
) -> p1.CapabilitySignature | None:
    """Apply one exact frozen composition, returning incomplete on a missing part."""

    if method == "P2":
        if b4 is None or rag_specialist is None:
            return None
        return _signature((rag_specialist, b4.memory_required, b4.planning_required))
    if method == "P3":
        if b4 is None or rag_specialist is None or memory_specialist is None:
            return None
        return _signature((rag_specialist, memory_specialist, b4.planning_required))
    if method == "P4":
        if b4 is None or memory_specialist is None:
            return None
        return _signature((b4.rag_required, memory_specialist, b4.planning_required))
    raise Stage4MError(f"unknown specialist composition: {method}")


def build_prediction_maps(
    records: Sequence[Stage4MRecord],
) -> dict[str, dict[str, p1.CapabilitySignature]]:
    predictions: dict[str, dict[str, p1.CapabilitySignature]] = {
        method: {} for method in METHOD_ORDER
    }
    for row in records:
        case_id = row.annotation_case_id
        predictions["B4"][case_id] = row.base.b4
        predictions["P1"][case_id] = row.p1_signature
        for method in ("P2", "P3", "P4"):
            output = compose_signature(
                method,
                b4=row.base.b4,
                rag_specialist=row.rag_specialist,
                memory_specialist=row.memory_specialist,
            )
            if output is None:
                continue
            predictions[method][case_id] = output
    expected = {row.annotation_case_id for row in records}
    for method, values in predictions.items():
        if set(values) != expected:
            raise Stage4MError(
                f"{method} is incomplete; missing outputs were not substituted"
            )
    if set(predictions) != set(METHOD_ORDER):
        raise Stage4MError("unexpected method inventory")
    return predictions


NORMALIZED_FIELDS = (
    "schema_version",
    "annotation_case_id",
    "scenario_family_id",
    "outer_fold",
    "current_page",
    "contrast_group_id",
    "contrast_axis",
    "gold_rag_required",
    "gold_memory_required",
    "gold_planning_required",
    "gold_capability_signature",
    "b4_rag_required",
    "b4_memory_required",
    "b4_planning_required",
    "b4_capability_signature",
    "rag_specialist_required",
    "memory_specialist_required",
    "p1_rag_required",
    "p1_memory_required",
    "p1_planning_required",
    "p1_capability_signature",
    "b4_input_tokens",
    "b4_output_tokens",
    "b4_total_tokens",
    "b4_approximate_cost_usd",
    "rag_specialist_input_tokens",
    "rag_specialist_output_tokens",
    "rag_specialist_total_tokens",
    "rag_specialist_approximate_cost_usd",
    "memory_specialist_input_tokens",
    "memory_specialist_output_tokens",
    "memory_specialist_total_tokens",
    "memory_specialist_approximate_cost_usd",
    "identifier_and_gold_role",
)


def normalized_csv_rows(records: Sequence[Stage4MRecord]) -> list[dict[str, Any]]:
    rows = []
    for row in records:
        base = row.base
        values: dict[str, Any] = {
            "schema_version": "rq2-v2-stage4m-specialist-composition-normalized-dev-v1",
            "annotation_case_id": row.annotation_case_id,
            "scenario_family_id": base.scenario_family_id,
            "outer_fold": base.outer_fold,
            "current_page": base.current_page,
            "contrast_group_id": base.dev_contrast_group_id,
            "contrast_axis": base.dev_contrast_axis,
            "gold_capability_signature": _signature_text(base.gold),
            "b4_capability_signature": _signature_text(base.b4),
            "rag_specialist_required": _bool_text(row.rag_specialist),
            "memory_specialist_required": _bool_text(row.memory_specialist),
            "p1_capability_signature": _signature_text(row.p1_signature),
            "b4_input_tokens": base.b4_input_tokens,
            "b4_output_tokens": base.b4_output_tokens,
            "b4_total_tokens": base.b4_total_tokens,
            "b4_approximate_cost_usd": _cost_text(base.b4_cost_usd),
            "rag_specialist_input_tokens": row.rag_usage.input_tokens,
            "rag_specialist_output_tokens": row.rag_usage.output_tokens,
            "rag_specialist_total_tokens": row.rag_usage.total_tokens,
            "rag_specialist_approximate_cost_usd": _cost_text(
                row.rag_usage.approximate_cost_usd
            ),
            "memory_specialist_input_tokens": row.memory_usage.input_tokens,
            "memory_specialist_output_tokens": row.memory_usage.output_tokens,
            "memory_specialist_total_tokens": row.memory_usage.total_tokens,
            "memory_specialist_approximate_cost_usd": _cost_text(
                row.memory_usage.approximate_cost_usd
            ),
            "identifier_and_gold_role": "OFFLINE_JOIN_AND_SCORING_ONLY_NOT_COMPOSITION_TRIGGER",
        }
        for prefix, signature in (
            ("gold", base.gold),
            ("b4", base.b4),
            ("p1", row.p1_signature),
        ):
            for capability, bit in zip(
                ("rag", "memory", "planning"), signature.bits, strict=True
            ):
                values[f"{prefix}_{capability}_required"] = _bool_text(bit)
        rows.append(values)
    return rows


def normalized_json_rows(records: Sequence[Stage4MRecord]) -> list[dict[str, Any]]:
    rows = []
    for row in records:
        base = row.base
        rows.append(
            {
                "schema_version": "rq2-v2-stage4m-specialist-composition-normalized-dev-v1",
                "annotation_case_id": row.annotation_case_id,
                "scenario_family_id": base.scenario_family_id,
                "outer_fold": base.outer_fold,
                "current_page": base.current_page,
                "contrast_group_id": base.dev_contrast_group_id,
                "contrast_axis": base.dev_contrast_axis,
                "field_roles": {
                    "identifiers_and_gold": "OFFLINE_JOIN_AND_SCORING_ONLY_NOT_COMPOSITION_TRIGGERS",
                    "composition_inputs": [
                        "b4_complete_signature",
                        "rag_specialist_bit",
                        "memory_specialist_bit",
                    ],
                },
                "gold": base.gold.as_dict(),
                "gold_capability_signature": _signature_text(base.gold),
                "b4": base.b4.as_dict(),
                "b4_capability_signature": _signature_text(base.b4),
                "rag_specialist": {"rag_required": row.rag_specialist},
                "memory_specialist": {"memory_required": row.memory_specialist},
                "p1": row.p1_signature.as_dict(),
                "p1_capability_signature": _signature_text(row.p1_signature),
                "usage": {
                    "b4": {
                        "input_tokens": base.b4_input_tokens,
                        "output_tokens": base.b4_output_tokens,
                        "total_tokens": base.b4_total_tokens,
                        "approximate_cost_usd": _cost_text(base.b4_cost_usd),
                    },
                    "rag_specialist": {
                        "input_tokens": row.rag_usage.input_tokens,
                        "output_tokens": row.rag_usage.output_tokens,
                        "total_tokens": row.rag_usage.total_tokens,
                        "approximate_cost_usd": _cost_text(
                            row.rag_usage.approximate_cost_usd
                        ),
                    },
                    "memory_specialist": {
                        "input_tokens": row.memory_usage.input_tokens,
                        "output_tokens": row.memory_usage.output_tokens,
                        "total_tokens": row.memory_usage.total_tokens,
                        "approximate_cost_usd": _cost_text(
                            row.memory_usage.approximate_cost_usd
                        ),
                    },
                },
            }
        )
    return rows


CORE_PREDICTION_FIELDS = (
    "schema_version",
    "method_id",
    "method_status",
    "method_development_status",
    "annotation_case_id",
    "scenario_family_id",
    "outer_fold",
    "current_page",
    "contrast_group_id",
    "contrast_axis",
    "composition_complete",
    "composition_status",
    "rag_source",
    "memory_source",
    "planning_source",
    "predicted_rag_required",
    "predicted_memory_required",
    "predicted_planning_required",
    "predicted_capability_signature",
)


def core_prediction_rows(
    method: str,
    records: Sequence[Stage4MRecord],
    predictions: Mapping[str, p1.CapabilitySignature],
) -> list[dict[str, Any]]:
    spec = METHOD_SPECS[method]
    return [
        {
            "schema_version": "rq2-v2-stage4m-specialist-core-oof-prediction-v1",
            "method_id": spec["method_id"],
            "method_status": spec["status"],
            "method_development_status": spec["development_status"],
            "annotation_case_id": row.annotation_case_id,
            "scenario_family_id": row.base.scenario_family_id,
            "outer_fold": row.base.outer_fold,
            "current_page": row.base.current_page,
            "contrast_group_id": row.base.dev_contrast_group_id,
            "contrast_axis": row.base.dev_contrast_axis,
            "composition_complete": "true",
            "composition_status": "COMPLETE",
            "rag_source": spec["rag_source"],
            "memory_source": spec["memory_source"],
            "planning_source": spec["planning_source"],
            "predicted_rag_required": _bool_text(
                predictions[row.annotation_case_id].rag_required
            ),
            "predicted_memory_required": _bool_text(
                predictions[row.annotation_case_id].memory_required
            ),
            "predicted_planning_required": _bool_text(
                predictions[row.annotation_case_id].planning_required
            ),
            "predicted_capability_signature": _signature_text(
                predictions[row.annotation_case_id]
            ),
        }
        for row in records
    ]


def _family_relative_to_b4(
    records: Sequence[Stage4MRecord],
    predictions: Mapping[str, p1.CapabilitySignature],
    b4_predictions: Mapping[str, p1.CapabilitySignature],
) -> dict[str, Any]:
    families: dict[str, list[Stage4MRecord]] = defaultdict(list)
    for row in records:
        families[row.base.scenario_family_id].append(row)
    details = []
    improved: list[str] = []
    harmed: list[str] = []
    unchanged: list[str] = []
    for family_id, items in sorted(families.items()):
        b4_correct = sum(
            b4_predictions[item.annotation_case_id] == item.base.gold for item in items
        )
        method_correct = sum(
            predictions[item.annotation_case_id] == item.base.gold for item in items
        )
        if method_correct > b4_correct:
            classification = "IMPROVED"
            improved.append(family_id)
        elif method_correct < b4_correct:
            classification = "HARMED"
            harmed.append(family_id)
        else:
            classification = "UNCHANGED"
            unchanged.append(family_id)
        details.append(
            {
                "scenario_family_id": family_id,
                "b4_exact_correct_utterance_count": b4_correct,
                "method_exact_correct_utterance_count": method_correct,
                "relative_to_b4": classification,
                "method_both_utterances_exact_correct": method_correct == 2,
                "method_prediction_consistent": len(
                    {predictions[item.annotation_case_id] for item in items}
                )
                == 1,
            }
        )
    return {
        "definition": "Improved or harmed means a higher or lower number of exact-correct utterances within the fixed two-utterance family than B4.",
        "improved_family_count": len(improved),
        "improved_family_ids": improved,
        "harmed_family_count": len(harmed),
        "harmed_family_ids": harmed,
        "unchanged_family_count": len(unchanged),
        "unchanged_family_ids": unchanged,
        "families": details,
    }


def _contrast_by_axis(contrast: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for axis in CAPABILITY_LABELS:
        rows = [row for row in contrast["groups"] if row["axis"] == axis]
        count = len(rows)
        within = sum(row["predicted_within_family_consistent"] for row in rows)
        vector = sum(row["gold_contrast_change_vector_matched"] for row in rows)
        pattern = sum(row["gold_family_pattern_matched"] for row in rows)
        result[axis] = {
            "eligible_contrast_groups": count,
            "within_family_prediction_consistent_groups": within,
            "within_family_prediction_consistency_rate": _safe_div(within, count),
            "capability_change_vector_consistent_groups": vector,
            "capability_change_vector_consistency_rate": _safe_div(vector, count),
            "complete_gold_family_pattern_matched_groups": pattern,
            "complete_gold_family_pattern_match_rate": _safe_div(pattern, count),
            "groups": rows,
        }
    return result


def build_metrics(
    records: Sequence[Stage4MRecord],
    predictions: Mapping[str, Mapping[str, p1.CapabilitySignature]],
) -> dict[str, Any]:
    base_records = [row.base for row in records]
    methods: dict[str, Any] = {}
    for method in METHOD_ORDER:
        values = predictions[method]
        core = stage4j.core_metrics(base_records, values)
        contrast = stage4j.contrast_metrics(base_records, values)
        methods[method] = {
            "method_id": METHOD_SPECS[method]["method_id"],
            "method_status": METHOD_SPECS[method]["status"],
            "method_development_status": METHOD_SPECS[method][
                "development_status"
            ],
            "valid_prediction_coverage": {
                "valid_prediction_count": len(values),
                "required_case_count": 64,
                "rate": _safe_div(len(values), 64),
                "incomplete_case_count": 64 - len(values),
                "missing_output_substitution_count": 0,
            },
            **core,
            "family_metrics": stage4j.family_metrics(base_records, values),
            "family_relative_to_b4": _family_relative_to_b4(
                records, values, predictions["B4"]
            ),
            "contrast_metrics": contrast,
            "contrast_metrics_by_axis": _contrast_by_axis(contrast),
            "page_stratified_metrics": stage4j.stratified_metrics(
                base_records, values, "current_page"
            ),
            "fold_stratified_metrics": stage4j.stratified_metrics(
                base_records, values, "outer_fold"
            ),
            "prediction_distribution": stage4j.prediction_distribution(values),
        }
    return {
        "schema_version": "rq2-v2-stage4m-specialist-composition-metrics-v1",
        "population": "64_FROZEN_DEV_ANSWER_CASES",
        "metric_definition_source": {
            "path": SOURCE_ARTIFACTS["stage4j_metric_implementation"][0],
            "sha256": SOURCE_ARTIFACTS["stage4j_metric_implementation"][1],
            "semantics": "SAME_CORE_FAMILY_CONTRAST_PAGE_AND_FOLD_DEFINITIONS_AS_STAGE_4J",
        },
        "methods": methods,
        "governance": {
            "dev_only": True,
            "test_executed": False,
            "rq3_access": False,
            "stage4m_provider_calls": 0,
            "winner_selected": False,
        },
    }


def _binary_metrics(
    rows: Sequence[Stage4MRecord],
    capability_index: int,
    predictor: Mapping[str, bool],
) -> dict[str, Any]:
    tp = fp = fn = tn = 0
    for row in rows:
        truth = row.base.gold.bits[capability_index]
        predicted = predictor[row.annotation_case_id]
        if truth and predicted:
            tp += 1
        elif not truth and predicted:
            fp += 1
        elif truth and not predicted:
            fn += 1
        else:
            tn += 1
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    return {
        "case_count": len(rows),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "accuracy": _safe_div(tp + tn, len(rows)),
        "precision": precision,
        "recall": recall,
        "f1": _safe_div(2 * precision * recall, precision + recall),
        "specificity": _safe_div(tn, tn + fp),
        "specificity_numerator_tn": tn,
        "specificity_denominator_tn_plus_fp": tn + fp,
        "positive_prediction_count": tp + fp,
        "positive_prediction_rate": _safe_div(tp + fp, len(rows)),
    }


def _target_family_metrics(
    rows: Sequence[Stage4MRecord],
    capability_index: int,
    predictor: Mapping[str, bool],
) -> dict[str, Any]:
    families: dict[str, list[Stage4MRecord]] = defaultdict(list)
    for row in rows:
        families[row.base.scenario_family_id].append(row)
    if any(len(items) != 2 for items in families.values()):
        raise Stage4MError("target family metrics require complete two-case families")
    both = consistent = 0
    for items in families.values():
        values = [predictor[item.annotation_case_id] for item in items]
        truths = [item.base.gold.bits[capability_index] for item in items]
        both += int(values == truths)
        consistent += int(len(set(values)) == 1)
    count = len(families)
    return {
        "family_count": count,
        "family_both_utterances_correct_count": both,
        "family_both_utterances_correct_rate": _safe_div(both, count),
        "family_prediction_consistent_count": consistent,
        "family_prediction_consistency_rate": _safe_div(consistent, count),
    }


def _target_contrast_detail(
    rows: Sequence[Stage4MRecord],
    capability_index: int,
    predictor: Mapping[str, bool],
) -> dict[str, Any]:
    families: dict[str, list[Stage4MRecord]] = defaultdict(list)
    for row in rows:
        families[row.base.scenario_family_id].append(row)
    if len(families) != 2 or any(len(items) != 2 for items in families.values()):
        raise Stage4MError("target contrast group is malformed")
    predicted_family: dict[str, bool] = {}
    gold_family: dict[str, bool] = {}
    internally_consistent = True
    for family, items in families.items():
        predicted = {predictor[item.annotation_case_id] for item in items}
        gold = {item.base.gold.bits[capability_index] for item in items}
        if len(predicted) != 1 or len(gold) != 1:
            internally_consistent = False
        else:
            predicted_family[family] = next(iter(predicted))
            gold_family[family] = next(iter(gold))
    vector_match = False
    if internally_consistent:
        left, right = sorted(families)
        vector_match = (
            int(predicted_family[right]) - int(predicted_family[left])
            == int(gold_family[right]) - int(gold_family[left])
        )
    gold_pattern = all(
        predictor[row.annotation_case_id] == row.base.gold.bits[capability_index]
        for row in rows
    )
    return {
        "within_family_prediction_consistent": internally_consistent,
        "target_change_vector_matches_gold": vector_match,
        "target_gold_pattern_matched": gold_pattern,
    }


COMPONENT_AUDIT_FIELDS = (
    "schema_version",
    "component",
    "stratum_type",
    "stratum_value",
    "case_count",
    "specialist_tp",
    "specialist_fp",
    "specialist_fn",
    "specialist_tn",
    "specialist_accuracy",
    "specialist_precision",
    "specialist_recall",
    "specialist_f1",
    "specialist_specificity",
    "specialist_specificity_numerator_tn",
    "specialist_specificity_denominator_tn_plus_fp",
    "specialist_positive_prediction_count",
    "specialist_positive_prediction_rate",
    "b4_tp",
    "b4_fp",
    "b4_fn",
    "b4_tn",
    "b4_accuracy",
    "b4_precision",
    "b4_recall",
    "b4_f1",
    "b4_specificity",
    "b4_specificity_numerator_tn",
    "b4_specificity_denominator_tn_plus_fp",
    "b4_positive_prediction_count",
    "b4_positive_prediction_rate",
    "agreement_count",
    "agreement_rate",
    "specialist_only_correct_count",
    "b4_only_correct_count",
    "both_correct_count",
    "both_wrong_count",
    "specialist_family_count",
    "specialist_family_both_correct_count",
    "specialist_family_both_correct_rate",
    "specialist_family_prediction_consistent_count",
    "specialist_family_prediction_consistency_rate",
    "b4_family_count",
    "b4_family_both_correct_count",
    "b4_family_both_correct_rate",
    "b4_family_prediction_consistent_count",
    "b4_family_prediction_consistency_rate",
    "specialist_within_family_prediction_consistent",
    "specialist_target_change_vector_matches_gold",
    "specialist_target_gold_pattern_matched",
    "b4_within_family_prediction_consistent",
    "b4_target_change_vector_matches_gold",
    "b4_target_gold_pattern_matched",
)


def build_component_audit(records: Sequence[Stage4MRecord]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for component, index, axis in (("RAG", 0, "RAG"), ("MEMORY", 1, "MEMORY")):
        specialist = {
            row.annotation_case_id: (
                row.rag_specialist if component == "RAG" else row.memory_specialist
            )
            for row in records
        }
        b4 = {
            row.annotation_case_id: row.base.b4.bits[index] for row in records
        }

        def comparison(
            subset: Sequence[Stage4MRecord], stratum_type: str, stratum_value: str
        ) -> dict[str, Any]:
            specialist_metrics = _binary_metrics(subset, index, specialist)
            b4_metrics = _binary_metrics(subset, index, b4)
            agreement = specialist_only = b4_only = both_correct = both_wrong = 0
            for item in subset:
                truth = item.base.gold.bits[index]
                specialist_value = specialist[item.annotation_case_id]
                b4_value = b4[item.annotation_case_id]
                agreement += int(specialist_value == b4_value)
                specialist_correct = specialist_value == truth
                b4_correct = b4_value == truth
                specialist_only += int(specialist_correct and not b4_correct)
                b4_only += int(b4_correct and not specialist_correct)
                both_correct += int(specialist_correct and b4_correct)
                both_wrong += int(not specialist_correct and not b4_correct)
            row: dict[str, Any] = {
                "schema_version": "rq2-v2-stage4m-specialist-component-transition-audit-v1",
                "component": component,
                "stratum_type": stratum_type,
                "stratum_value": stratum_value,
                "case_count": len(subset),
                "agreement_count": agreement,
                "agreement_rate": _safe_div(agreement, len(subset)),
                "specialist_only_correct_count": specialist_only,
                "b4_only_correct_count": b4_only,
                "both_correct_count": both_correct,
                "both_wrong_count": both_wrong,
            }
            for prefix, values in (
                ("specialist", specialist_metrics),
                ("b4", b4_metrics),
            ):
                for name, value in values.items():
                    if name != "case_count":
                        row[f"{prefix}_{name}"] = value
            return row

        overall = comparison(records, "OVERALL", "ALL_64_DEV_ANSWER_CASES")
        result.append(overall)
        family_row = comparison(records, "FAMILY_SUMMARY", "ALL_32_FAMILIES")
        for prefix, predictor in (("specialist", specialist), ("b4", b4)):
            values = _target_family_metrics(records, index, predictor)
            family_row[f"{prefix}_family_count"] = values["family_count"]
            family_row[f"{prefix}_family_both_correct_count"] = values[
                "family_both_utterances_correct_count"
            ]
            family_row[f"{prefix}_family_both_correct_rate"] = values[
                "family_both_utterances_correct_rate"
            ]
            family_row[f"{prefix}_family_prediction_consistent_count"] = values[
                "family_prediction_consistent_count"
            ]
            family_row[f"{prefix}_family_prediction_consistency_rate"] = values[
                "family_prediction_consistency_rate"
            ]
        result.append(family_row)

        families: dict[str, list[Stage4MRecord]] = defaultdict(list)
        pages: dict[str, list[Stage4MRecord]] = defaultdict(list)
        folds: dict[str, list[Stage4MRecord]] = defaultdict(list)
        contrasts: dict[str, list[Stage4MRecord]] = defaultdict(list)
        for item in records:
            families[item.base.scenario_family_id].append(item)
            pages[item.base.current_page].append(item)
            folds[item.base.outer_fold].append(item)
            if (
                item.base.dev_contrast_axis == axis
                and item.base.dev_contrast_group_id
            ):
                contrasts[item.base.dev_contrast_group_id].append(item)
        for stratum_type, groups in (
            ("FAMILY", families),
            ("PAGE", pages),
            ("FOLD", folds),
        ):
            for name, items in sorted(groups.items()):
                result.append(comparison(items, stratum_type, name))

        contrast_summary = comparison(
            [item for items in contrasts.values() for item in items],
            "TARGET_CONTRAST_SUMMARY",
            axis,
        )
        specialist_details = []
        b4_details = []
        for group_id, items in sorted(contrasts.items()):
            row = comparison(items, "TARGET_CONTRAST_GROUP", group_id)
            specialist_detail = _target_contrast_detail(items, index, specialist)
            b4_detail = _target_contrast_detail(items, index, b4)
            for prefix, detail in (
                ("specialist", specialist_detail),
                ("b4", b4_detail),
            ):
                for name, value in detail.items():
                    row[f"{prefix}_{name}"] = _bool_text(value)
            result.append(row)
            specialist_details.append(specialist_detail)
            b4_details.append(b4_detail)
        for prefix, details in (
            ("specialist", specialist_details),
            ("b4", b4_details),
        ):
            contrast_summary[f"{prefix}_within_family_prediction_consistent"] = (
                sum(item["within_family_prediction_consistent"] for item in details)
            )
            contrast_summary[f"{prefix}_target_change_vector_matches_gold"] = sum(
                item["target_change_vector_matches_gold"] for item in details
            )
            contrast_summary[f"{prefix}_target_gold_pattern_matched"] = sum(
                item["target_gold_pattern_matched"] for item in details
            )
        result.append(contrast_summary)
    return result


def _flatten_factorial_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "macro_f1": metrics["macro_f1"],
        "micro_f1": metrics["micro_f1"],
        "rag_f1": metrics["per_label"]["rag_required"]["f1"],
        "memory_f1": metrics["per_label"]["memory_required"]["f1"],
        "planning_f1": metrics["per_label"]["planning_required"]["f1"],
        "exact_capability_set_match": metrics["exact_capability_set_match"],
        "exact_correct_case_count": metrics["exact_capability_set_correct_count"],
        "example_based_f1": metrics["example_based_f1"],
        "jaccard": metrics["jaccard"],
        "hamming_loss": metrics["hamming_loss"],
        "under_routing_case_count": metrics["under_routing"]["case_count"],
        "under_routing_rate": metrics["under_routing"]["case_rate"],
        "over_routing_case_count": metrics["over_routing"]["case_count"],
        "over_routing_rate": metrics["over_routing"]["case_rate"],
        "mean_predicted_capability_count": metrics["prediction_distribution"][
            "mean_predicted_capability_count"
        ],
    }


FACTORIAL_FIELDS = (
    "schema_version",
    "row_type",
    "factorial_cell",
    "method",
    "effect_definition",
    "rag_source",
    "memory_source",
    "planning_source",
    "method_development_status",
    "case_count",
    "macro_f1",
    "micro_f1",
    "rag_f1",
    "memory_f1",
    "planning_f1",
    "exact_capability_set_match",
    "exact_correct_case_count",
    "example_based_f1",
    "jaccard",
    "hamming_loss",
    "under_routing_case_count",
    "under_routing_rate",
    "over_routing_case_count",
    "over_routing_rate",
    "mean_predicted_capability_count",
    "interpretation_boundary",
)


def build_factorial_rows(metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    methods = metrics["methods"]
    cells = {
        "B4": "A_JOINT_RAG_JOINT_MEMORY",
        "P2": "B_SPECIALIST_RAG_JOINT_MEMORY",
        "P4": "C_JOINT_RAG_SPECIALIST_MEMORY",
        "P3": "D_SPECIALIST_RAG_SPECIALIST_MEMORY",
    }
    rows: list[dict[str, Any]] = []
    flat: dict[str, dict[str, Any]] = {}
    for method in FACTORIAL_ORDER:
        flat[method] = _flatten_factorial_metrics(methods[method])
        rows.append(
            {
                "schema_version": "rq2-v2-stage4m-specialist-factorial-ablation-v1",
                "row_type": "FACTORIAL_CELL",
                "factorial_cell": cells[method],
                "method": method,
                "rag_source": METHOD_SPECS[method]["rag_source"],
                "memory_source": METHOD_SPECS[method]["memory_source"],
                "planning_source": METHOD_SPECS[method]["planning_source"],
                "method_development_status": METHOD_SPECS[method][
                    "development_status"
                ],
                "case_count": 64,
                **flat[method],
                "interpretation_boundary": "OBSERVED_DEV_RESULT_NOT_TEST_EFFECT_OR_CAUSAL_POPULATION_ESTIMATE",
            }
        )
    effects = (
        ("RAG_ONLY_AT_JOINT_MEMORY", "P2_MINUS_B4", {"P2": 1, "B4": -1}),
        ("MEMORY_ONLY_AT_JOINT_RAG", "P4_MINUS_B4", {"P4": 1, "B4": -1}),
        ("REPLACE_BOTH", "P3_MINUS_B4", {"P3": 1, "B4": -1}),
        (
            "RAG_MEMORY_INTERACTION",
            "P3_MINUS_P2_MINUS_P4_PLUS_B4",
            {"P3": 1, "P2": -1, "P4": -1, "B4": 1},
        ),
    )
    for name, definition, coefficients in effects:
        values = {}
        for field in _flatten_factorial_metrics(methods["B4"]):
            values[field] = round(
                sum(coefficients[method] * float(flat[method][field]) for method in coefficients),
                12,
            )
        rows.append(
            {
                "schema_version": "rq2-v2-stage4m-specialist-factorial-ablation-v1",
                "row_type": "OBSERVED_DEV_EFFECT",
                "factorial_cell": name,
                "effect_definition": definition,
                **values,
                "interpretation_boundary": "OBSERVED_DEV_DIFFERENCE_NOT_TEST_EFFECT_OR_CAUSAL_POPULATION_ESTIMATE",
            }
        )
    return rows


CASE_TRANSITION_FIELDS = (
    "schema_version",
    "method",
    "method_id",
    "annotation_case_id",
    "scenario_family_id",
    "outer_fold",
    "current_page",
    "contrast_group_id",
    "contrast_axis",
    "gold_signature",
    "b4_signature",
    "composition_signature",
    "transition_category",
    "composition_correct_b4_incorrect",
    "b4_correct_composition_incorrect",
    "both_correct",
    "both_incorrect",
    "complete_signatures_differ",
    "changed_capabilities",
    "corrected_changed_capabilities",
    "harmed_changed_capabilities",
    "changed_capability_causing_exact_transition",
    "fixed_under_routing",
    "fixed_over_routing",
    "introduced_new_error",
    "b4_under_routed",
    "composition_under_routed",
    "b4_over_routed",
    "composition_over_routed",
)


def build_case_transitions(
    records: Sequence[Stage4MRecord],
    predictions: Mapping[str, Mapping[str, p1.CapabilitySignature]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for method in ("P2", "P3", "P4"):
        for item in records:
            gold = item.base.gold
            b4 = predictions["B4"][item.annotation_case_id]
            composition = predictions[method][item.annotation_case_id]
            b4_correct = b4 == gold
            composition_correct = composition == gold
            if composition_correct and not b4_correct:
                category = "COMPOSITION_CORRECT_B4_INCORRECT"
            elif b4_correct and not composition_correct:
                category = "B4_CORRECT_COMPOSITION_INCORRECT"
            elif b4_correct and composition_correct:
                category = "BOTH_CORRECT"
            else:
                category = "BOTH_INCORRECT"
            changed = [
                label
                for label, left, right in zip(
                    CAPABILITY_LABELS, b4.bits, composition.bits, strict=True
                )
                if left != right
            ]
            corrected = [
                label
                for label, truth, left, right in zip(
                    CAPABILITY_LABELS, gold.bits, b4.bits, composition.bits, strict=True
                )
                if left != truth and right == truth
            ]
            harmed = [
                label
                for label, truth, left, right in zip(
                    CAPABILITY_LABELS, gold.bits, b4.bits, composition.bits, strict=True
                )
                if left == truth and right != truth
            ]
            b4_missing = {i for i, (truth, pred) in enumerate(zip(gold.bits, b4.bits, strict=True)) if truth and not pred}
            composition_missing = {
                i
                for i, (truth, pred) in enumerate(
                    zip(gold.bits, composition.bits, strict=True)
                )
                if truth and not pred
            }
            b4_extra = {i for i, (truth, pred) in enumerate(zip(gold.bits, b4.bits, strict=True)) if not truth and pred}
            composition_extra = {
                i
                for i, (truth, pred) in enumerate(
                    zip(gold.bits, composition.bits, strict=True)
                )
                if not truth and pred
            }
            cause = corrected if composition_correct and not b4_correct else harmed if b4_correct and not composition_correct else []
            rows.append(
                {
                    "schema_version": "rq2-v2-stage4m-specialist-composition-case-transition-v1",
                    "method": method,
                    "method_id": METHOD_SPECS[method]["method_id"],
                    "annotation_case_id": item.annotation_case_id,
                    "scenario_family_id": item.base.scenario_family_id,
                    "outer_fold": item.base.outer_fold,
                    "current_page": item.base.current_page,
                    "contrast_group_id": item.base.dev_contrast_group_id,
                    "contrast_axis": item.base.dev_contrast_axis,
                    "gold_signature": _signature_text(gold),
                    "b4_signature": _signature_text(b4),
                    "composition_signature": _signature_text(composition),
                    "transition_category": category,
                    "composition_correct_b4_incorrect": _bool_text(composition_correct and not b4_correct),
                    "b4_correct_composition_incorrect": _bool_text(b4_correct and not composition_correct),
                    "both_correct": _bool_text(b4_correct and composition_correct),
                    "both_incorrect": _bool_text(not b4_correct and not composition_correct),
                    "complete_signatures_differ": _bool_text(b4 != composition),
                    "changed_capabilities": "|".join(changed),
                    "corrected_changed_capabilities": "|".join(corrected),
                    "harmed_changed_capabilities": "|".join(harmed),
                    "changed_capability_causing_exact_transition": "|".join(cause),
                    "fixed_under_routing": _bool_text(bool(b4_missing) and not composition_missing),
                    "fixed_over_routing": _bool_text(bool(b4_extra) and not composition_extra),
                    "introduced_new_error": _bool_text(bool(harmed)),
                    "b4_under_routed": _bool_text(bool(b4_missing)),
                    "composition_under_routed": _bool_text(bool(composition_missing)),
                    "b4_over_routed": _bool_text(bool(b4_extra)),
                    "composition_over_routed": _bool_text(bool(composition_extra)),
                }
            )
    return rows


def transition_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for method in ("P2", "P3", "P4"):
        items = [row for row in rows if row["method"] == method]
        categories = Counter(str(row["transition_category"]) for row in items)
        result[method] = {
            "case_count": len(items),
            "transition_categories": dict(sorted(categories.items())),
            "complete_signature_changed_count": sum(
                row["complete_signatures_differ"] == "true" for row in items
            ),
            "fixed_under_routing_count": sum(
                row["fixed_under_routing"] == "true" for row in items
            ),
            "fixed_over_routing_count": sum(
                row["fixed_over_routing"] == "true" for row in items
            ),
            "introduced_new_error_count": sum(
                row["introduced_new_error"] == "true" for row in items
            ),
        }
    return result


def _sum_usage(values: Sequence[Usage]) -> Usage:
    input_tokens = sum(value.input_tokens for value in values)
    output_tokens = sum(value.output_tokens for value in values)
    total_tokens = sum(value.total_tokens for value in values)
    cost = sum((value.approximate_cost_usd for value in values), Decimal("0"))
    if input_tokens + output_tokens != total_tokens or cost != _cost(
        input_tokens, output_tokens
    ):
        raise Stage4MError("combined usage arithmetic differs")
    return Usage(input_tokens, output_tokens, total_tokens, cost)


def _usage_dict(value: Usage, logical_calls: int) -> dict[str, Any]:
    return {
        "logical_component_calls": logical_calls,
        "input_tokens": value.input_tokens,
        "output_tokens": value.output_tokens,
        "total_tokens": value.total_tokens,
        "approximate_cost_usd": _cost_text(value.approximate_cost_usd),
    }


COST_TABLE_FIELDS = (
    "schema_version",
    "method",
    "cost_basis",
    "logical_component_calls",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "approximate_cost_usd",
    "component_inventory",
    "interpretation",
)


def build_cost_report(
    records: Sequence[Stage4MRecord],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    b4 = Usage(
        input_tokens=sum(row.base.b4_input_tokens for row in records),
        output_tokens=sum(row.base.b4_output_tokens for row in records),
        total_tokens=sum(row.base.b4_total_tokens for row in records),
        approximate_cost_usd=sum(
            (row.base.b4_cost_usd for row in records), Decimal("0")
        ),
    )
    if b4.input_tokens + b4.output_tokens != b4.total_tokens or b4.approximate_cost_usd != _cost(
        b4.input_tokens, b4.output_tokens
    ):
        raise Stage4MError("B4 per-case cost arithmetic differs")
    rag = _sum_usage([row.rag_usage for row in records])
    memory = _sum_usage([row.memory_usage for row in records])
    frozen_b4 = _load_json(TRACK_I_DIR / "b4_dev_usage_and_cost_v2.json")
    frozen_rag = _load_json(TRACK_K_DIR / "rag_specialist_usage_and_cost_v1.json")
    frozen_memory = _load_json(
        TRACK_L_DIR / "memory_specialist_usage_and_cost_v1.json"
    )
    for observed, frozen in (
        (b4, frozen_b4),
        (rag, frozen_rag),
        (memory, frozen_memory),
    ):
        if _cost_text(observed.approximate_cost_usd) != frozen[
            "approximate_cost_usd"
        ]["total"]:
            raise Stage4MError("component cost differs from frozen cost report")

    p1_cost = _load_json(TRACK_J_DIR / "p1_counterfactual_cost_v1.json")
    nested = p1_cost["nested_p1_counterfactual"]
    final = p1_cost["final_selected_policy_counterfactual"]
    combined = {
        "B4": (b4, 64, ["B4"]),
        "P2": (_sum_usage([b4, rag]), 128, ["B4", "RAG_SPECIALIST"]),
        "P4": (
            _sum_usage([b4, memory]),
            128,
            ["B4", "MEMORY_SPECIALIST"],
        ),
        "P3": (
            _sum_usage([b4, rag, memory]),
            192,
            ["B4", "RAG_SPECIALIST", "MEMORY_SPECIALIST"],
        ),
    }
    counterfactual = {
        method: {
            **_usage_dict(usage, calls),
            "components": components,
            "interpretation": "COUNTERFACTUAL_COMPONENT_GENERATION_FOR_ONE_64_CASE_DEV_RUN",
        }
        for method, (usage, calls, components) in combined.items()
    }
    counterfactual["P1_NESTED_OOF"] = {
        "logical_component_calls": nested["counterfactual_logical_b4_calls"],
        "input_tokens": nested["counterfactual_input_tokens"],
        "output_tokens": nested["counterfactual_output_tokens"],
        "total_tokens": nested["counterfactual_total_tokens"],
        "approximate_cost_usd": nested["counterfactual_approximate_cost_usd"],
        "components": ["CONDITIONAL_B4"],
        "interpretation": "FROZEN_STAGE4J_NESTED_OOF_COUNTERFACTUAL",
    }
    counterfactual["P1_FINAL_FULL_DEV_POLICY"] = {
        "logical_component_calls": final["counterfactual_logical_b4_calls"],
        "input_tokens": final["counterfactual_input_tokens"],
        "output_tokens": final["counterfactual_output_tokens"],
        "total_tokens": final["counterfactual_total_tokens"],
        "approximate_cost_usd": final["counterfactual_approximate_cost_usd"],
        "components": ["CONDITIONAL_B4"],
        "interpretation": "FROZEN_STAGE4J_FINAL_POLICY_COUNTERFACTUAL",
    }

    historical_total = _sum_usage([b4, rag, memory])
    report = {
        "schema_version": "rq2-v2-stage4m-specialist-composition-cost-v1",
        "pricing_reference": {
            "date": "2026-08-31",
            "input_usd_per_1m_tokens": "0.15",
            "output_usd_per_1m_tokens": "0.60",
            "costs_are_approximate_not_billing_statements": True,
        },
        "actual_historical_experimental_calls_already_made": {
            "B4": _usage_dict(b4, 64),
            "RAG_SPECIALIST": _usage_dict(rag, 64),
            "MEMORY_SPECIALIST": _usage_dict(memory, 64),
            "successful_logical_calls_total": 192,
            "input_tokens_total": historical_total.input_tokens,
            "output_tokens_total": historical_total.output_tokens,
            "total_tokens": historical_total.total_tokens,
            "approximate_cost_usd_total": _cost_text(
                historical_total.approximate_cost_usd
            ),
        },
        "counterfactual_deployment_component_calls": counterfactual,
        "stage4m_new_provider_calls": 0,
        "stage4m_new_provider_cost_usd": "0.00000000",
        "interpretation_boundaries": [
            "Historical calls were already made in frozen B4, Stage 4K, and Stage 4L executions.",
            "Composition costs count the frozen components that would need generation for a fresh 64-case run.",
            "P1 values are copied from the frozen Stage 4J counterfactual report.",
            "Higher-cost specialist compositions are not described as cost-saving methods.",
        ],
    }
    table = []
    for method in (
        "B4",
        "P1_NESTED_OOF",
        "P1_FINAL_FULL_DEV_POLICY",
        "P2",
        "P4",
        "P3",
    ):
        value = counterfactual[method]
        table.append(
            {
                "schema_version": "rq2-v2-stage4m-specialist-composition-cost-table-v1",
                "method": method,
                "cost_basis": value["interpretation"],
                "logical_component_calls": value["logical_component_calls"],
                "input_tokens": value["input_tokens"],
                "output_tokens": value["output_tokens"],
                "total_tokens": value["total_tokens"],
                "approximate_cost_usd": value["approximate_cost_usd"],
                "component_inventory": "|".join(value["components"]),
                "interpretation": "COUNTERFACTUAL_NOT_STAGE4M_NEW_CALLS",
            }
        )
    return report, table


def _bootstrap_contribution(
    items: Sequence[Stage4MRecord],
    predictions: Mapping[str, p1.CapabilitySignature],
) -> dict[str, Any]:
    tp = [0, 0, 0]
    fp = [0, 0, 0]
    fn = [0, 0, 0]
    exact = under = over = 0
    jaccard = 0.0
    for item in items:
        truth = item.base.gold
        predicted = predictions[item.annotation_case_id]
        for index, (gold_bit, pred_bit) in enumerate(
            zip(truth.bits, predicted.bits, strict=True)
        ):
            tp[index] += int(gold_bit and pred_bit)
            fp[index] += int(not gold_bit and pred_bit)
            fn[index] += int(gold_bit and not pred_bit)
        gold_set = {i for i, value in enumerate(truth.bits) if value}
        pred_set = {i for i, value in enumerate(predicted.bits) if value}
        exact += int(truth == predicted)
        union = gold_set | pred_set
        jaccard += 1.0 if not union else len(gold_set & pred_set) / len(union)
        under += int(bool(gold_set - pred_set))
        over += int(bool(pred_set - gold_set))
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "exact": exact,
        "jaccard_sum": jaccard,
        "under": under,
        "over": over,
        "case_count": len(items),
    }


def _bootstrap_vector(contributions: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    tp = [sum(int(item["tp"][index]) for item in contributions) for index in range(3)]
    fp = [sum(int(item["fp"][index]) for item in contributions) for index in range(3)]
    fn = [sum(int(item["fn"][index]) for item in contributions) for index in range(3)]
    label_f1 = []
    for index in range(3):
        precision = _safe_div(tp[index], tp[index] + fp[index])
        recall = _safe_div(tp[index], tp[index] + fn[index])
        label_f1.append(_safe_div(2 * precision * recall, precision + recall))
    count = sum(int(item["case_count"]) for item in contributions)
    return {
        "macro_f1": round(sum(label_f1) / 3, 12),
        "exact_capability_set_match": _safe_div(
            sum(int(item["exact"]) for item in contributions), count
        ),
        "jaccard": round(
            sum(float(item["jaccard_sum"]) for item in contributions) / count, 12
        ),
        "under_routing": _safe_div(
            sum(int(item["under"]) for item in contributions), count
        ),
        "over_routing": _safe_div(
            sum(int(item["over"]) for item in contributions), count
        ),
    }


def _percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise Stage4MError("percentile requires at least one value")
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] * (1 - fraction) + ordered[upper] * fraction, 12)


def build_bootstrap(
    records: Sequence[Stage4MRecord],
    predictions: Mapping[str, Mapping[str, p1.CapabilitySignature]],
    metrics: Mapping[str, Any],
    *,
    replicates: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    families: dict[str, list[Stage4MRecord]] = defaultdict(list)
    for row in records:
        families[row.base.scenario_family_id].append(row)
    family_ids = sorted(families)
    if len(family_ids) != 32 or any(len(families[name]) != 2 for name in family_ids):
        raise Stage4MError("bootstrap requires 32 fixed two-case family clusters")
    methods = ("B4", "P2", "P3", "P4")
    contributions = {
        method: [
            _bootstrap_contribution(families[family], predictions[method])
            for family in family_ids
        ]
        for method in methods
    }
    metric_names = (
        "macro_f1",
        "exact_capability_set_match",
        "jaccard",
        "under_routing",
        "over_routing",
    )
    distributions = {
        method: {metric: [] for metric in metric_names} for method in methods
    }
    difference_pairs = {
        "P2_MINUS_B4": ("P2", "B4"),
        "P3_MINUS_B4": ("P3", "B4"),
        "P4_MINUS_B4": ("P4", "B4"),
        "P4_MINUS_P3": ("P4", "P3"),
    }
    differences = {
        name: {metric: [] for metric in metric_names}
        for name in difference_pairs
    }
    rng = random.Random(BOOTSTRAP_SEED)
    for _ in range(replicates):
        sampled = [rng.randrange(len(family_ids)) for _ in family_ids]
        vectors = {
            method: _bootstrap_vector([contributions[method][index] for index in sampled])
            for method in methods
        }
        for method in methods:
            for metric in metric_names:
                distributions[method][metric].append(vectors[method][metric])
        for name, (left, right) in difference_pairs.items():
            for metric in metric_names:
                differences[name][metric].append(
                    round(vectors[left][metric] - vectors[right][metric], 12)
                )

    method_intervals: dict[str, Any] = {}
    for method in methods:
        method_intervals[method] = {}
        for metric in metric_names:
            if metric in {"under_routing", "over_routing"}:
                point = metrics["methods"][method][metric]["case_rate"]
            else:
                point = metrics["methods"][method][metric]
            method_intervals[method][metric] = {
                "point_estimate": point,
                "percentile_95_interval": [
                    _percentile(distributions[method][metric], 0.025),
                    _percentile(distributions[method][metric], 0.975),
                ],
            }
    difference_intervals: dict[str, Any] = {}
    for name, (left, right) in difference_pairs.items():
        difference_intervals[name] = {}
        for metric in metric_names:
            if metric in {"under_routing", "over_routing"}:
                left_point = metrics["methods"][left][metric]["case_rate"]
                right_point = metrics["methods"][right][metric]["case_rate"]
            else:
                left_point = metrics["methods"][left][metric]
                right_point = metrics["methods"][right][metric]
            difference_intervals[name][metric] = {
                "point_estimate": round(left_point - right_point, 12),
                "percentile_95_interval": [
                    _percentile(differences[name][metric], 0.025),
                    _percentile(differences[name][metric], 0.975),
                ],
            }
    return {
        "schema_version": "rq2-v2-stage4m-specialist-composition-bootstrap-v1",
        "audit_label": "POST_EXECUTION_EXPLORATORY_UNCERTAINTY_AUDIT",
        "selection_use": "PROHIBITED_NON_SELECTION_AUDIT",
        "resampling_unit": "scenario_family_id",
        "cluster_count": 32,
        "cases_per_cluster": 2,
        "seed": BOOTSTRAP_SEED,
        "replicates": replicates,
        "interval_method": "95_PERCENTILE_LINEAR_INTERPOLATION_AT_2_5_AND_97_5_PERCENT",
        "methods": method_intervals,
        "paired_differences": difference_intervals,
        "interpretation_boundaries": [
            "Not part of Stage 4K-0 method selection.",
            "Not used to alter or discard any method.",
            "Intervals are descriptive and do not by themselves establish statistical significance.",
            "DEV family-cluster uncertainty is not independent TEST evidence.",
        ],
    }


END_TO_END_FIELDS = (
    "schema_version",
    "method",
    "method_id",
    "annotation_case_id",
    "scenario_family_id",
    "outer_fold",
    "current_page",
    "dev_atomic_component_id",
    "dev_contrast_group_id",
    "dev_contrast_axis",
    "gold_dialogue_action",
    "predicted_dialogue_action",
    "core_composition_applied",
    "gold_route_signature",
    "predicted_route_signature",
    "gold_rag_required",
    "gold_memory_required",
    "gold_planning_required",
    "predicted_rag_required",
    "predicted_memory_required",
    "predicted_planning_required",
    "full_route_exact",
)


def _action_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    per_class = {}
    for action in ("ANSWER", "CLARIFY"):
        tp = sum(
            row["gold_dialogue_action"] == action
            and row["predicted_dialogue_action"] == action
            for row in rows
        )
        fp = sum(
            row["gold_dialogue_action"] != action
            and row["predicted_dialogue_action"] == action
            for row in rows
        )
        fn = sum(
            row["gold_dialogue_action"] == action
            and row["predicted_dialogue_action"] != action
            for row in rows
        )
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        per_class[action] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": _safe_div(2 * precision * recall, precision + recall),
        }
    correct = sum(
        row["gold_dialogue_action"] == row["predicted_dialogue_action"]
        for row in rows
    )
    return {
        "accuracy": _safe_div(correct, len(rows)),
        "macro_f1": round(sum(value["f1"] for value in per_class.values()) / 2, 12),
        "per_class": per_class,
    }


def _route_bits(signature: str) -> tuple[int, int, int] | None:
    if len(signature) == 3 and set(signature) <= {"0", "1"}:
        return tuple(int(value) for value in signature)  # type: ignore[return-value]
    return None


def _end_to_end_contrast(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        group_id = str(row["dev_contrast_group_id"])
        axis = str(row["dev_contrast_axis"])
        if group_id and axis in {"RAG", "MEMORY", "PLANNING", "CLARIFICATION"}:
            groups[(group_id, axis)].append(row)
    details = []
    within_count = vector_count = pattern_count = 0
    for (group_id, axis), items in sorted(groups.items()):
        families: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in items:
            families[str(row["scenario_family_id"])].append(row)
        if len(families) != 2 or any(len(values) != 2 for values in families.values()):
            raise Stage4MError(f"malformed end-to-end contrast group: {group_id}")
        predicted: dict[str, str] = {}
        gold: dict[str, str] = {}
        internally_consistent = True
        for family, values in families.items():
            predicted_values = {str(value["predicted_route_signature"]) for value in values}
            gold_values = {str(value["gold_route_signature"]) for value in values}
            if len(predicted_values) != 1 or len(gold_values) != 1:
                internally_consistent = False
            else:
                predicted[family] = next(iter(predicted_values))
                gold[family] = next(iter(gold_values))
        vector_match = False
        if internally_consistent:
            left, right = sorted(families)
            predicted_left = _route_bits(predicted[left])
            predicted_right = _route_bits(predicted[right])
            gold_left = _route_bits(gold[left])
            gold_right = _route_bits(gold[right])
            if None not in {predicted_left, predicted_right, gold_left, gold_right}:
                vector_match = tuple(
                    right_value - left_value
                    for left_value, right_value in zip(
                        predicted_left, predicted_right, strict=True  # type: ignore[arg-type]
                    )
                ) == tuple(
                    right_value - left_value
                    for left_value, right_value in zip(
                        gold_left, gold_right, strict=True  # type: ignore[arg-type]
                    )
                )
            else:
                vector_match = predicted == gold
        pattern_match = internally_consistent and predicted == gold
        within_count += int(internally_consistent)
        vector_count += int(vector_match)
        pattern_count += int(pattern_match)
        details.append(
            {
                "contrast_group_id": group_id,
                "axis": axis,
                "within_family_prediction_consistent": internally_consistent,
                "directed_full_route_change_consistent_with_gold": vector_match,
                "complete_gold_route_pattern_matched": pattern_match,
            }
        )
    total = len(groups)
    return {
        "eligible_contrast_groups": total,
        "within_family_prediction_consistent_groups": within_count,
        "within_family_prediction_consistency_rate": _safe_div(within_count, total),
        "directed_full_route_change_consistent_groups": vector_count,
        "contrast_consistency_rate": _safe_div(vector_count, total),
        "complete_gold_route_pattern_matched_groups": pattern_count,
        "gold_pattern_match_rate": _safe_div(pattern_count, total),
        "groups": details,
    }


def build_end_to_end(
    records: Sequence[Stage4MRecord],
    predictions: Mapping[str, Mapping[str, p1.CapabilitySignature]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    gold = _unique_rows(_load_csv(DEV_DIR / "dev_capability_gold_v1.csv"), "all DEV Gold")
    grouping = _unique_rows(
        _load_csv(DEV_DIR / "dev_atomic_group_map_v1.csv"), "all DEV grouping"
    )
    clarification = _unique_rows(
        _load_csv(TRACK_G_DIR / "clarification_oof_predictions_v1.csv"),
        "clarification OOF predictions",
    )
    if set(gold) != set(grouping) or set(gold) != set(clarification) or len(gold) != 72:
        raise Stage4MError("end-to-end 72-case join differs")
    record_ids = {row.annotation_case_id for row in records}
    output_rows: dict[str, list[dict[str, Any]]] = {}
    output_metrics: dict[str, Any] = {}
    for method in METHOD_ORDER:
        rows: list[dict[str, Any]] = []
        for case_id in sorted(gold, key=lambda value: value.encode("utf-8")):
            gold_row = gold[case_id]
            group_row = grouping[case_id]
            gate_row = clarification[case_id]
            gold_action = str(gold_row["final_dialogue_action"])
            predicted_action = str(gate_row["predicted_dialogue_action"])
            if predicted_action not in {"ANSWER", "CLARIFY"}:
                raise Stage4MError(f"invalid clarification result: {case_id}")
            if gold_action == "CLARIFY":
                gold_signature = "CLARIFY"
                gold_bits = ("NOT_APPLICABLE",) * 3
            else:
                gold_value = _signature(
                    (
                        _parse_bool(gold_row["final_rag_required"]),
                        _parse_bool(gold_row["final_memory_required"]),
                        _parse_bool(gold_row["final_planning_required"]),
                    )
                )
                gold_signature = _signature_text(gold_value)
                gold_bits = tuple(_bool_text(value) for value in gold_value.bits)
            if predicted_action == "CLARIFY":
                predicted_signature = "CLARIFY"
                predicted_bits = ("NOT_APPLICABLE",) * 3
                applied = False
            else:
                if case_id not in record_ids or case_id not in predictions[method]:
                    raise Stage4MError(
                        f"predicted ANSWER lacks a frozen {method} core output: {case_id}"
                    )
                predicted_value = predictions[method][case_id]
                predicted_signature = _signature_text(predicted_value)
                predicted_bits = tuple(
                    _bool_text(value) for value in predicted_value.bits
                )
                applied = True
            rows.append(
                {
                    "schema_version": "rq2-v2-stage4m-specialist-end-to-end-oof-v1",
                    "method": method,
                    "method_id": METHOD_SPECS[method]["method_id"],
                    "annotation_case_id": case_id,
                    "scenario_family_id": gold_row["scenario_family_id"],
                    "outer_fold": gate_row["outer_fold"],
                    "current_page": gold_row["current_page"],
                    "dev_atomic_component_id": group_row["dev_atomic_component_id"],
                    "dev_contrast_group_id": group_row["dev_contrast_group_id"],
                    "dev_contrast_axis": group_row["dev_contrast_axis"],
                    "gold_dialogue_action": gold_action,
                    "predicted_dialogue_action": predicted_action,
                    "core_composition_applied": _bool_text(applied),
                    "gold_route_signature": gold_signature,
                    "predicted_route_signature": predicted_signature,
                    "gold_rag_required": gold_bits[0],
                    "gold_memory_required": gold_bits[1],
                    "gold_planning_required": gold_bits[2],
                    "predicted_rag_required": predicted_bits[0],
                    "predicted_memory_required": predicted_bits[1],
                    "predicted_planning_required": predicted_bits[2],
                    "full_route_exact": _bool_text(
                        gold_signature == predicted_signature
                    ),
                }
            )
        families: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in rows:
            families[str(row["scenario_family_id"])].append(row)
        if len(families) != 36 or any(len(items) != 2 for items in families.values()):
            raise Stage4MError("end-to-end family structure differs from 36 pairs")
        both_correct = sum(
            all(item["full_route_exact"] == "true" for item in items)
            for items in families.values()
        )
        prediction_consistent = sum(
            len({item["predicted_route_signature"] for item in items}) == 1
            for items in families.values()
        )
        exact_count = sum(row["full_route_exact"] == "true" for row in rows)
        output_rows[method] = rows
        output_metrics[method] = {
            "method_id": METHOD_SPECS[method]["method_id"],
            "population_count": 72,
            "full_route_signature_exact_count": exact_count,
            "full_route_signature_exact_match": _safe_div(exact_count, 72),
            "dialogue_action": _action_metrics(rows),
            "predicted_clarify_count": sum(
                row["predicted_dialogue_action"] == "CLARIFY" for row in rows
            ),
            "core_composition_applied_count": sum(
                row["core_composition_applied"] == "true" for row in rows
            ),
            "family_both_correct": {
                "family_count": 36,
                "correct_count": both_correct,
                "rate": _safe_div(both_correct, 36),
            },
            "family_prediction_consistency": {
                "family_count": 36,
                "consistent_count": prediction_consistent,
                "rate": _safe_div(prediction_consistent, 36),
            },
            "contrast_consistency": _end_to_end_contrast(rows),
        }
    return output_rows, {
        "schema_version": "rq2-v2-stage4m-specialist-end-to-end-metrics-v1",
        "shared_clarification_gate_sha256": SOURCE_ARTIFACTS[
            "clarification_gate"
        ][1],
        "clarification_gate_modified": False,
        "methods": output_metrics,
        "test_executed": False,
        "stage4m_provider_calls": 0,
    }


def verify_offline_implementation() -> dict[str, Any]:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    prohibited = {
        "openai",
        "anthropic",
        "requests",
        "httpx",
        "urllib",
        "socket",
        "aiohttp",
    }
    found = sorted(imported & prohibited)
    if found:
        raise Stage4MError(f"network or provider import detected: {found}")
    return {
        "status": "PASS_OFFLINE_IMPLEMENTATION",
        "prohibited_imports_found": found,
        "provider_client_present": False,
        "network_path_present": False,
    }


def build_freeze_configuration(
    method: str, normalized_dev_sha256: str
) -> dict[str, Any]:
    if method not in {"P2", "P3", "P4"}:
        raise Stage4MError("only P2, P3, and P4 receive Stage 4M freezes")
    spec = METHOD_SPECS[method]
    components: dict[str, Any] = {
        "B4": {
            "method": "R2V2-B4_JOINT_LLM",
            "prediction_sha256": SOURCE_ARTIFACTS["b4_predictions"][1],
            "configuration_sha256": SOURCE_ARTIFACTS["b4_configuration"][1],
            "model_snapshot": EXPECTED_MODEL,
            "prompt_sha256": SOURCE_ARTIFACTS["b4_prompt"][1],
            "schema_sha256": SOURCE_ARTIFACTS["b4_schema"][1],
            "final_full_dev_example_set_sha256": EXAMPLE_SET_HASHES["B4"],
        }
    }
    if method in {"P2", "P3"}:
        components["RAG_SPECIALIST"] = {
            "method": "R2V2-RAG_SPECIALIST",
            "prediction_sha256": SOURCE_ARTIFACTS["rag_predictions"][1],
            "configuration_sha256": SOURCE_ARTIFACTS["rag_configuration"][1],
            "model_snapshot": EXPECTED_MODEL,
            "prompt_sha256": SOURCE_ARTIFACTS["rag_prompt"][1],
            "schema_sha256": SOURCE_ARTIFACTS["rag_schema"][1],
            "final_full_dev_example_set_sha256": EXAMPLE_SET_HASHES[
                "RAG_SPECIALIST"
            ],
        }
    if method in {"P3", "P4"}:
        components["MEMORY_SPECIALIST"] = {
            "method": "R2V2-MEMORY_SPECIALIST",
            "prediction_sha256": SOURCE_ARTIFACTS["memory_predictions"][1],
            "configuration_sha256": SOURCE_ARTIFACTS["memory_configuration"][1],
            "model_snapshot": EXPECTED_MODEL,
            "prompt_sha256": SOURCE_ARTIFACTS["memory_prompt"][1],
            "schema_sha256": SOURCE_ARTIFACTS["memory_schema"][1],
            "final_full_dev_example_set_sha256": EXAMPLE_SET_HASHES[
                "MEMORY_SPECIALIST"
            ],
        }
    rules = {
        "P2": {
            "rag_required": "RAG_SPECIALIST.rag_required",
            "memory_required": "B4.memory_required",
            "planning_required": "B4.planning_required",
        },
        "P3": {
            "rag_required": "RAG_SPECIALIST.rag_required",
            "memory_required": "MEMORY_SPECIALIST.memory_required",
            "planning_required": "B4.planning_required",
        },
        "P4": {
            "rag_required": "B4.rag_required",
            "memory_required": "MEMORY_SPECIALIST.memory_required",
            "planning_required": "B4.planning_required",
        },
    }
    status_keys = {"P2": "P2_STATUS", "P3": "P3_STATUS", "P4": "P4_STATUS"}
    result = {
        "schema_version": f"rq2-v2-stage4m-{method.lower()}-composition-frozen-v1",
        status_keys[method]: spec["status"],
        "composition_id": spec["method_id"],
        "method_development_status": spec["development_status"],
        "components": components,
        "composition_rule": rules[method],
        "planning_always_from_frozen_b4": True,
        "join_key": "annotation_case_id",
        "population": "64_FROZEN_DEV_ANSWER_CASES",
        "missing_or_invalid_component_behavior": {
            "composition_status": "INCOMPLETE",
            "imputation_allowed": False,
            "fallback_or_router_substitution_allowed": False,
            "coverage_reported_separately": True,
        },
        "dev_source_sha256": SOURCE_ARTIFACTS["dev_gold"][1],
        "normalized_dev_sha256": normalized_dev_sha256,
        "TEST_STATUS": "NOT_EXECUTED",
        "test_winner_designated": False,
        "stage4_integration_executed": False,
        "rq3_access": False,
        "stage4m_new_provider_calls": 0,
    }
    if method == "P2":
        result["predeclared_contract_sha256"] = SOURCE_ARTIFACTS["p2_contract"][1]
        result["predeclared_in_stage4k0"] = True
        result["predeclared_role"] = "PRIMARY_RAGATE_INSPIRED_EXTENSION"
    elif method == "P3":
        result["predeclared_contract_sha256"] = SOURCE_ARTIFACTS["p3_contract"][1]
        result["predeclared_in_stage4k0"] = True
        result["predeclared_role"] = "SECONDARY_SPECIALIST_EXTENSION"
    else:
        result["predeclared_in_stage4k0"] = False
        result["disclosure_file"] = "P4_POST_DEV_EXTENSION_DISCLOSURE.md"
        result["exploratory_role"] = "TRANSPARENT_2X2_FACTORIAL_ABLATION"
    return result


def build_p4_disclosure() -> str:
    return """# P4 Post-DEV Extension Disclosure

`R2V2-P4_MEMORY_SPECIALIST_COMPOSITION` is classified as
`POST_DEV_EXPLORATORY_ABLATION_FROZEN_BEFORE_TEST`.

- P4 was added only after the RAG and Memory Specialist DEV component results were available.
- TEST had not been accessed or executed.
- P4 was added to complete the 2x2 factorial comparison of joint versus specialist RAG and Memory bits.
- P4 requires no new model call or prompt.
- P4 is exploratory and must not be represented as a Stage 4K-0 predeclared primary method.
- P4 is frozen before any TEST execution.

The exact rule is: RAG from frozen joint B4, Memory from the frozen Memory
Specialist, and Planning from frozen joint B4. Missing or invalid components
make the case incomplete; no imputation, fallback, or router substitution is
allowed. No additional composition is defined.
"""


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _component_overall(
    component_rows: Sequence[Mapping[str, Any]], component: str
) -> Mapping[str, Any]:
    return next(
        row
        for row in component_rows
        if row["component"] == component and row["stratum_type"] == "OVERALL"
    )


def build_results_markdown(
    source_verification: Mapping[str, Any],
    metrics: Mapping[str, Any],
    component_rows: Sequence[Mapping[str, Any]],
    factorial_rows: Sequence[Mapping[str, Any]],
    transitions: Mapping[str, Any],
    cost_rows: Sequence[Mapping[str, Any]],
    bootstrap: Mapping[str, Any],
    end_to_end: Mapping[str, Any],
) -> str:
    lines = [
        "# RQ2-V2 Stage 4M Specialist Composition DEV Results",
        "",
        "`READY_FOR_RQ2_V2_STAGE_4_INTEGRATION_WITH_SPECIALISTS`",
        "",
        "This is an offline DEV analysis. Stage 4M made zero provider calls and did not access or execute TEST or RQ3. No Stage 4 Integration was performed.",
        "",
        "## Frozen source bindings",
        "",
        "| Component | Status | Model | Prediction SHA-256 | Prompt SHA-256 | Schema SHA-256 |",
        "|---|---|---|---|---|---|",
        f"| B4 | FROZEN_AFTER_DEV_EXECUTION | {EXPECTED_MODEL} | `{SOURCE_ARTIFACTS['b4_predictions'][1]}` | `{SOURCE_ARTIFACTS['b4_prompt'][1]}` | `{SOURCE_ARTIFACTS['b4_schema'][1]}` |",
        f"| RAG Specialist | FROZEN_AFTER_DEV_EXECUTION | {EXPECTED_MODEL} | `{SOURCE_ARTIFACTS['rag_predictions'][1]}` | `{SOURCE_ARTIFACTS['rag_prompt'][1]}` | `{SOURCE_ARTIFACTS['rag_schema'][1]}` |",
        f"| Memory Specialist | FROZEN_AFTER_DEV_EXECUTION | {EXPECTED_MODEL} | `{SOURCE_ARTIFACTS['memory_predictions'][1]}` | `{SOURCE_ARTIFACTS['memory_prompt'][1]}` | `{SOURCE_ARTIFACTS['memory_schema'][1]}` |",
        f"| P1 nested OOF | FROZEN_AFTER_DEV_SELECTION | n/a | `{SOURCE_ARTIFACTS['p1_predictions'][1]}` | n/a | n/a |",
        "",
        f"All required case sets matched on 64 unique `annotation_case_id` values. Integrated commits: `{', '.join(INTEGRATED_COMMITS)}`.",
        "",
        "## Specialist component comparison",
        "",
        "| Component | Predictor | Accuracy | Precision | Recall | F1 | Specificity | Positive rate |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for component in ("RAG", "MEMORY"):
        row = _component_overall(component_rows, component)
        for predictor, label in (("specialist", "Specialist"), ("b4", "B4 bit")):
            lines.append(
                f"| {component} | {label} | {_fmt(row[f'{predictor}_accuracy'])} | {_fmt(row[f'{predictor}_precision'])} | {_fmt(row[f'{predictor}_recall'])} | {_fmt(row[f'{predictor}_f1'])} | {_fmt(row[f'{predictor}_specificity'])} | {_fmt(row[f'{predictor}_positive_prediction_rate'])} |"
            )
        lines.append(
            f"| {component} | paired transitions | agreement {row['agreement_count']}/64 | specialist-only correct {row['specialist_only_correct_count']} | B4-only correct {row['b4_only_correct_count']} | both correct {row['both_correct_count']} | both wrong {row['both_wrong_count']} |  |"
        )

    lines.extend(
        [
            "",
            "## Full 64-case composition metrics",
            "",
            "| Method | Macro-F1 | Micro-F1 | Exact set | Example F1 | Jaccard | Hamming | Under-route | Over-route | Mean capabilities |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for method in METHOD_ORDER:
        value = metrics["methods"][method]
        lines.append(
            f"| {method} | {_fmt(value['macro_f1'])} | {_fmt(value['micro_f1'])} | {value['exact_capability_set_correct_count']}/64 ({_fmt(value['exact_capability_set_match'])}) | {_fmt(value['example_based_f1'])} | {_fmt(value['jaccard'])} | {_fmt(value['hamming_loss'])} | {value['under_routing']['case_count']}/64 ({_fmt(value['under_routing']['case_rate'])}) | {value['over_routing']['case_count']}/64 ({_fmt(value['over_routing']['case_rate'])}) | {_fmt(value['prediction_distribution']['mean_predicted_capability_count'])} |"
        )

    lines.extend(
        [
            "",
            "## 2x2 factorial ablation",
            "",
            "Observed DEV differences are descriptive; they are not independent TEST effects or causal population estimates.",
            "",
            "| Effect | Macro-F1 | Exact set | Jaccard | Under-route | Over-route |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in factorial_rows:
        if row["row_type"] == "OBSERVED_DEV_EFFECT":
            lines.append(
                f"| {row['effect_definition']} | {_fmt(row['macro_f1'])} | {_fmt(row['exact_capability_set_match'])} | {_fmt(row['jaccard'])} | {_fmt(row['under_routing_rate'])} | {_fmt(row['over_routing_rate'])} |"
            )

    lines.extend(
        [
            "",
            "## Family and capability-contrast results",
            "",
            "| Method | Families both exact | Family prediction consistency | Improved families vs B4 | Harmed families vs B4 | Contrast vector match | Gold-pattern match |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for method in METHOD_ORDER:
        value = metrics["methods"][method]
        family = value["family_metrics"]
        relative = value["family_relative_to_b4"]
        contrast = value["contrast_metrics"]
        lines.append(
            f"| {method} | {family['both_utterances_exact_correct_count']}/32 ({_fmt(family['both_utterances_exact_correct_rate'])}) | {family['prediction_consistent_count']}/32 ({_fmt(family['prediction_consistency_rate'])}) | {relative['improved_family_count']} | {relative['harmed_family_count']} | {contrast['consistent_contrast_groups']}/8 ({_fmt(contrast['contrast_consistency_rate'])}) | {contrast['gold_pattern_matched_groups']}/8 ({_fmt(contrast['gold_pattern_match_rate'])}) |"
        )

    lines.extend(
        [
            "",
            "## Case transitions versus B4",
            "",
            "| Method | Composition correct/B4 wrong | B4 correct/composition wrong | Both correct | Both wrong | Signature changed | Fixed under | Fixed over | Introduced new error |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for method in ("P2", "P3", "P4"):
        value = transitions[method]
        categories = value["transition_categories"]
        lines.append(
            f"| {method} | {categories.get('COMPOSITION_CORRECT_B4_INCORRECT', 0)} | {categories.get('B4_CORRECT_COMPOSITION_INCORRECT', 0)} | {categories.get('BOTH_CORRECT', 0)} | {categories.get('BOTH_INCORRECT', 0)} | {value['complete_signature_changed_count']} | {value['fixed_under_routing_count']} | {value['fixed_over_routing_count']} | {value['introduced_new_error_count']} |"
        )

    lines.extend(
        [
            "",
            "## Calls, tokens, and approximate cost",
            "",
            "| Method | Logical component calls | Input tokens | Output tokens | Total tokens | Approx. USD |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in cost_rows:
        lines.append(
            f"| {row['method']} | {row['logical_component_calls']} | {row['input_tokens']} | {row['output_tokens']} | {row['total_tokens']} | {row['approximate_cost_usd']} |"
        )
    lines.extend(
        [
            "",
            "These are counterfactual component-generation costs from frozen usage records. Stage 4M itself made 0 provider calls. Higher-cost compositions are not cost-saving methods.",
            "",
            "## Exploratory family-cluster bootstrap",
            "",
            f"Label: `{bootstrap['audit_label']}`. Seed `{bootstrap['seed']}`; {bootstrap['replicates']:,} replicates; scenario family is the resampling unit.",
            "",
            "| Method | Metric | Point | 95% percentile interval |",
            "|---|---|---:|---:|",
        ]
    )
    for method in ("B4", "P2", "P3", "P4"):
        for metric_name, value in bootstrap["methods"][method].items():
            low, high = value["percentile_95_interval"]
            lines.append(
                f"| {method} | {metric_name} | {_fmt(value['point_estimate'])} | [{_fmt(low)}, {_fmt(high)}] |"
            )
    lines.extend(
        [
            "",
            "Paired intervals are descriptive and are not used to claim statistical significance or select a method.",
            "",
            "## End-to-end 72-case DEV routing",
            "",
            "| Method | Full route exact | Dialogue action accuracy / Macro-F1 | Families both correct | Family prediction consistency | Contrast consistency | Gold-pattern match |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for method in METHOD_ORDER:
        value = end_to_end["methods"][method]
        contrast = value["contrast_consistency"]
        lines.append(
            f"| {method} | {value['full_route_signature_exact_count']}/72 ({_fmt(value['full_route_signature_exact_match'])}) | {_fmt(value['dialogue_action']['accuracy'])} / {_fmt(value['dialogue_action']['macro_f1'])} | {value['family_both_correct']['correct_count']}/36 ({_fmt(value['family_both_correct']['rate'])}) | {value['family_prediction_consistency']['consistent_count']}/36 ({_fmt(value['family_prediction_consistency']['rate'])}) | {contrast['directed_full_route_change_consistent_groups']}/{contrast['eligible_contrast_groups']} ({_fmt(contrast['contrast_consistency_rate'])}) | {contrast['complete_gold_route_pattern_matched_groups']}/{contrast['eligible_contrast_groups']} ({_fmt(contrast['gold_pattern_match_rate'])}) |"
        )
    lines.extend(
        [
            "",
            "## Frozen statuses",
            "",
            "- P2: `FROZEN_AFTER_DEV_COMPOSITION_EVALUATION`",
            "- P3: `FROZEN_AFTER_DEV_COMPOSITION_EVALUATION`",
            "- P4: `FROZEN_POST_DEV_EXPLORATORY_ABLATION_BEFORE_TEST`",
            "- TEST: `NOT_EXECUTED`; no TEST winner designated.",
            "- Stage 4M provider calls: `0`.",
            "- RQ3 access: `false`.",
            "",
        ]
    )
    return "\n".join(lines)


def build_interpretation_markdown(
    metrics: Mapping[str, Any],
    component_rows: Sequence[Mapping[str, Any]],
    cost_report: Mapping[str, Any],
) -> str:
    rag = _component_overall(component_rows, "RAG")
    memory = _component_overall(component_rows, "MEMORY")
    rag_f1_delta = round(float(rag["specialist_f1"]) - float(rag["b4_f1"]), 12)
    memory_f1_delta = round(
        float(memory["specialist_f1"]) - float(memory["b4_f1"]), 12
    )
    p2_delta = round(
        metrics["methods"]["P2"]["macro_f1"]
        - metrics["methods"]["B4"]["macro_f1"],
        12,
    )
    p4_delta = round(
        metrics["methods"]["P4"]["macro_f1"]
        - metrics["methods"]["B4"]["macro_f1"],
        12,
    )
    p3_delta = round(
        metrics["methods"]["P3"]["macro_f1"]
        - metrics["methods"]["B4"]["macro_f1"],
        12,
    )
    if rag_f1_delta > 0:
        rag_statement = "The frozen RAG Specialist has higher DEV RAG-bit F1 than B4"
    elif rag_f1_delta < 0:
        rag_statement = "The frozen RAG Specialist has lower DEV RAG-bit F1 than B4"
    else:
        rag_statement = "The frozen RAG Specialist and B4 have equal DEV RAG-bit F1"
    if memory_f1_delta > 0:
        memory_statement = "The frozen Memory Specialist has higher DEV Memory-bit F1 than B4"
    elif memory_f1_delta < 0:
        memory_statement = "The frozen Memory Specialist has lower DEV Memory-bit F1 than B4"
    else:
        memory_statement = "The frozen Memory Specialist and B4 have equal DEV Memory-bit F1"
    association = (
        "the larger isolated observed change is associated with Memory specialization"
        if abs(p4_delta) > abs(p2_delta)
        else "the larger isolated observed change is associated with RAG specialization"
        if abs(p2_delta) > abs(p4_delta)
        else "the isolated observed RAG and Memory changes have equal magnitude"
    )
    costs = cost_report["counterfactual_deployment_component_calls"]
    return f"""# Specialist Decomposition Interpretation

## Component evidence

{rag_statement}: Specialist F1 {_fmt(rag['specialist_f1'])} versus B4 F1
{_fmt(rag['b4_f1'])}, an observed difference of {_fmt(rag_f1_delta)}. This is a
frozen DEV comparison and is stated exactly as measured; it is not treated as
independent TEST evidence.

{memory_statement}: Specialist F1 {_fmt(memory['specialist_f1'])} versus B4 F1
{_fmt(memory['b4_f1'])}, an observed difference of {_fmt(memory_f1_delta)}.

## Composition decomposition

P2 was the predeclared primary RAGate-inspired extension. Its DEV Macro-F1
change relative to B4 is {_fmt(p2_delta)}. P3 was the predeclared secondary
RAG-plus-Memory Specialist extension; its change is {_fmt(p3_delta)}. P4 was
added after the component DEV results as an exploratory factorial ablation;
its change is {_fmt(p4_delta)}. In this fixed 2x2 table, {association}. This
wording is an observed decomposition, not a causal attribution. In particular,
P3 performance is not attributed to RAG specialization when the isolated P4
Memory replacement accounts for the larger observed change.

## Accuracy and cost

The frozen counterfactual component-generation costs are B4
${costs['B4']['approximate_cost_usd']}, P2 ${costs['P2']['approximate_cost_usd']},
P4 ${costs['P4']['approximate_cost_usd']}, and P3
${costs['P3']['approximate_cost_usd']}. These estimates use actual frozen token
records and a common reference price. P2, P3, and P4 are not described as
cost-saving methods. Stage 4M made no new provider calls.

## Evidence boundary

- P2 is a predeclared primary DEV extension.
- P3 is a predeclared secondary DEV extension.
- P4 is a post-DEV exploratory factorial ablation, disclosed as such.
- All three compositions are frozen before TEST.
- The family-cluster bootstrap is a post-execution descriptive audit and was not used to alter or discard a method.
- None of these DEV results designates a TEST winner or establishes final generalization.
- TEST, RQ3, production integration, and Stage 4 Integration remain unexecuted.
"""


def build_status_markdown() -> str:
    return """# RQ2-V2 Stage 4M Status

`READY_FOR_RQ2_V2_STAGE_4_INTEGRATION_WITH_SPECIALISTS`

- Starting HEAD: `1aabe2c4f2c1f4b2cc23ea3b4b93eec96cf667b7`
- Integrated K0: `a2f6759afa984f98741e15c1fcd16625a2cd9c36`
- Integrated K: `4fab9eb6204611a961e8f65eb8a5c427afbcf2ea`
- Integrated L: `608637c1fa99f689be76012dc5c297519aba7889`
- Frozen DEV ANSWER join: 64/64 complete on unique `annotation_case_id`
- P2: `FROZEN_AFTER_DEV_COMPOSITION_EVALUATION`
- P3: `FROZEN_AFTER_DEV_COMPOSITION_EVALUATION`
- P4: `FROZEN_POST_DEV_EXPLORATORY_ABLATION_BEFORE_TEST`
- Stage 4M provider calls: 0
- TEST access/execution: 0 / not executed
- RQ3 access/execution: 0 / not executed
- Stage 4 Integration: not executed
- Production integration: not executed
- TEST winner: not designated

This readiness status records offline artifact completion only. It is not
authorization for Stage 4 Integration, TEST, RQ3, or production work.
"""


def _family_contrast_report(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "rq2-v2-stage4m-family-contrast-analysis-v1",
        "population": "64_FROZEN_DEV_ANSWER_CASES_32_TWO_UTTERANCE_FAMILIES",
        "eligible_capability_contrast_groups": 8,
        "clarification_excluded_from_core_comparison": True,
        "methods": {
            method: {
                "family_metrics": metrics["methods"][method]["family_metrics"],
                "families_relative_to_b4": metrics["methods"][method][
                    "family_relative_to_b4"
                ],
                "contrast_metrics": metrics["methods"][method]["contrast_metrics"],
                "contrast_metrics_by_axis": metrics["methods"][method][
                    "contrast_metrics_by_axis"
                ],
            }
            for method in METHOD_ORDER
        },
    }


GENERATED_OUTPUT_NAMES = (
    "specialist_composition_source_verification_v1.json",
    "specialist_composition_normalized_dev_v1.csv",
    "specialist_composition_normalized_dev_v1.jsonl",
    "p2_core_oof_predictions_v1.csv",
    "p3_core_oof_predictions_v1.csv",
    "p4_core_oof_predictions_v1.csv",
    "specialist_factorial_ablation_v1.csv",
    "specialist_component_transition_audit_v1.csv",
    "specialist_composition_case_transition_v1.csv",
    "specialist_composition_metrics_v1.json",
    "specialist_family_contrast_analysis_v1.json",
    "specialist_composition_cost_v1.json",
    "specialist_composition_cost_table_v1.csv",
    "specialist_composition_bootstrap_v1.json",
    "b4_end_to_end_oof_predictions_v1.csv",
    "p1_end_to_end_oof_predictions_v1.csv",
    "p2_end_to_end_oof_predictions_v1.csv",
    "p3_end_to_end_oof_predictions_v1.csv",
    "p4_end_to_end_oof_predictions_v1.csv",
    "specialist_end_to_end_metrics_v1.json",
    "p2_rag_specialist_composition_frozen_v1.json",
    "p3_rag_memory_specialists_frozen_v1.json",
    "p4_memory_specialist_composition_frozen_v1.json",
    "P4_POST_DEV_EXTENSION_DISCLOSURE.md",
    "SPECIALIST_COMPOSITION_DEV_RESULTS.md",
    "SPECIALIST_DECOMPOSITION_INTERPRETATION.md",
    "STATUS.md",
)


def build(output_dir: Path = TRACK_DIR) -> dict[str, Any]:
    # All fail-closed source checks and calculations happen before any generated
    # output is written.
    source_verification = verify_sources()
    source_verification["offline_implementation"] = verify_offline_implementation()
    records, join_verification = load_records()
    source_verification["population_and_join_verification"] = join_verification
    predictions = build_prediction_maps(records)
    metrics = build_metrics(records, predictions)
    component_rows = build_component_audit(records)
    factorial_rows = build_factorial_rows(metrics)
    transition_rows = build_case_transitions(records, predictions)
    transitions = transition_summary(transition_rows)
    cost_report, cost_rows = build_cost_report(records)
    bootstrap = build_bootstrap(records, predictions, metrics)
    end_rows, end_metrics = build_end_to_end(records, predictions)

    files: dict[str, str] = {}
    files["specialist_composition_source_verification_v1.json"] = _json_text(
        source_verification
    )
    normalized_csv = _csv_text(normalized_csv_rows(records), NORMALIZED_FIELDS)
    files["specialist_composition_normalized_dev_v1.csv"] = normalized_csv
    files["specialist_composition_normalized_dev_v1.jsonl"] = _jsonl_text(
        normalized_json_rows(records)
    )
    for method, filename in (
        ("P2", "p2_core_oof_predictions_v1.csv"),
        ("P3", "p3_core_oof_predictions_v1.csv"),
        ("P4", "p4_core_oof_predictions_v1.csv"),
    ):
        files[filename] = _csv_text(
            core_prediction_rows(method, records, predictions[method]),
            CORE_PREDICTION_FIELDS,
        )
    files["specialist_factorial_ablation_v1.csv"] = _csv_text(
        factorial_rows, FACTORIAL_FIELDS
    )
    files["specialist_component_transition_audit_v1.csv"] = _csv_text(
        component_rows, COMPONENT_AUDIT_FIELDS
    )
    files["specialist_composition_case_transition_v1.csv"] = _csv_text(
        transition_rows, CASE_TRANSITION_FIELDS
    )
    metrics["case_transition_summary_vs_b4"] = transitions
    files["specialist_composition_metrics_v1.json"] = _json_text(metrics)
    files["specialist_family_contrast_analysis_v1.json"] = _json_text(
        _family_contrast_report(metrics)
    )
    files["specialist_composition_cost_v1.json"] = _json_text(cost_report)
    files["specialist_composition_cost_table_v1.csv"] = _csv_text(
        cost_rows, COST_TABLE_FIELDS
    )
    files["specialist_composition_bootstrap_v1.json"] = _json_text(bootstrap)
    for method in METHOD_ORDER:
        files[f"{method.lower()}_end_to_end_oof_predictions_v1.csv"] = _csv_text(
            end_rows[method], END_TO_END_FIELDS
        )
    files["specialist_end_to_end_metrics_v1.json"] = _json_text(end_metrics)

    normalized_hash = sha256_bytes(normalized_csv.encode("utf-8"))
    files["p2_rag_specialist_composition_frozen_v1.json"] = _json_text(
        build_freeze_configuration("P2", normalized_hash)
    )
    files["p3_rag_memory_specialists_frozen_v1.json"] = _json_text(
        build_freeze_configuration("P3", normalized_hash)
    )
    files["p4_memory_specialist_composition_frozen_v1.json"] = _json_text(
        build_freeze_configuration("P4", normalized_hash)
    )
    files["P4_POST_DEV_EXTENSION_DISCLOSURE.md"] = build_p4_disclosure()
    files["SPECIALIST_COMPOSITION_DEV_RESULTS.md"] = build_results_markdown(
        source_verification,
        metrics,
        component_rows,
        factorial_rows,
        transitions,
        cost_rows,
        bootstrap,
        end_metrics,
    )
    files["SPECIALIST_DECOMPOSITION_INTERPRETATION.md"] = (
        build_interpretation_markdown(metrics, component_rows, cost_report)
    )
    files["STATUS.md"] = build_status_markdown()

    if set(files) != set(GENERATED_OUTPUT_NAMES):
        missing = sorted(set(GENERATED_OUTPUT_NAMES) - set(files))
        extra = sorted(set(files) - set(GENERATED_OUTPUT_NAMES))
        raise Stage4MError(f"generated output inventory differs: missing={missing}, extra={extra}")
    for method in ("P2", "P3", "P4"):
        for row in core_prediction_rows(method, records, predictions[method]):
            if TEST_IDENTIFIER_PATTERN.search(str(row["annotation_case_id"])):
                raise Stage4MError("TEST identifier detected in core composition output")
    for method, rows in end_rows.items():
        if any(
            TEST_IDENTIFIER_PATTERN.search(str(row["annotation_case_id"]))
            for row in rows
        ):
            raise Stage4MError(f"TEST identifier detected in {method} end-to-end output")

    manifest = {
        "schema_version": "rq2-v2-stage4m-output-sha256-manifest-v1",
        "hash_algorithm": "SHA-256",
        "path_base": "track_m_specialist_composition",
        "files": [
            {
                "path": name,
                "sha256": sha256_bytes(files[name].encode("utf-8")),
                "size_bytes": len(files[name].encode("utf-8")),
            }
            for name in sorted(files)
        ],
        "generated_output_count_excluding_manifest": len(files),
        "stage4m_new_provider_calls": 0,
        "test_executed": False,
        "rq3_access": False,
    }
    files["STAGE4M_OUTPUT_SHA256_MANIFEST.json"] = _json_text(manifest)

    for name, text in sorted(files.items()):
        _atomic_write_text(output_dir / name, text)
    return {
        "status": "READY_FOR_RQ2_V2_STAGE_4_INTEGRATION_WITH_SPECIALISTS",
        "output_directory": str(output_dir),
        "generated_file_count": len(files),
        "core_case_count": 64,
        "end_to_end_case_count": 72,
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "stage4m_new_provider_calls": 0,
        "test_access": False,
        "rq3_access": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the offline RQ2-V2 Stage 4M specialist analysis."
    )
    parser.add_argument("--output-dir", type=Path, default=TRACK_DIR)
    arguments = parser.parse_args(argv)
    print(json.dumps(build(arguments.output_dir), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
