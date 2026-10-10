"""Build the 25 authentic user-turn cases in a local-only case bank."""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

from evaluation.learned_intent_ranking.rq1c.final_input_schema import (
    deterministic_normalised_query,
)

from . import (
    AUTHENTIC_BANK_ALIAS,
    AUTHENTIC_PAGE_DISTRIBUTION,
    AUTHENTIC_USER_TURN_COUNT,
    HERE,
    HIGH_CONFIDENCE_CONTEXT_CASE_IDS,
    LOCAL_AUTHENTIC_BANK_RELATIVE,
    ROOT,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    id_set_sha256,
    sha256_bytes,
    sha256_file,
)
from .authentic_source_authority import load_authentic_rows


class AuthenticCaseBuildError(RuntimeError):
    pass


def _text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_authentic_cases(root: Path = ROOT) -> list[dict[str, Any]]:
    rows, _ = load_authentic_rows(root)
    cases: list[dict[str, Any]] = []
    for source_row_index, row in enumerate(rows, start=1):
        if row["role"] != "user":
            continue
        user_turn_index = len(cases) + 1
        case_id = f"AUTH-{user_turn_index:04d}"
        query = row["message"]
        history: list[dict[str, Any]] = []
        status = "NOT_APPLICABLE"
        if case_id in HIGH_CONFIDENCE_CONTEXT_CASE_IDS:
            if source_row_index <= 1 or rows[source_row_index - 2]["role"] != "assistant":
                raise AuthenticCaseBuildError("pre-registered context candidate is not adjacent")
            previous = rows[source_row_index - 2]
            history = [
                {
                    "role": "assistant",
                    "content": previous["message"],
                    "source_row_index": source_row_index - 1,
                    "assistant_generated": True,
                }
            ]
            status = "HUMAN_CONFIRMATION_REQUIRED"
        cases.append(
            {
                "case_id": case_id,
                "graph": row["graph"],
                "current_page": row["graph"],
                "current_query": query,
                "source_row_index": source_row_index,
                "current_user_turn_index": user_turn_index,
                "turn_index": user_turn_index,
                "raw_query_sha256": _text_sha(query),
                "normalised_query_sha256": _text_sha(
                    deterministic_normalised_query(query)
                ),
                "source_role": "user",
                "authentic_student_language": True,
                "assistant_generated": False,
                "source_bank": "authentic",
                "source_bank_alias": AUTHENTIC_BANK_ALIAS,
                "candidate_conversation_history": history,
                "context_link_status": status,
                "assistant_context_is_capability_gold": False,
                "session_inference_performed": False,
            }
        )
    if len(cases) != AUTHENTIC_USER_TURN_COUNT:
        raise AuthenticCaseBuildError("authentic case count mismatch")
    if len({row["case_id"] for row in cases}) != len(cases):
        raise AuthenticCaseBuildError("authentic case IDs are not unique")
    observed_context_ids = {
        row["case_id"] for row in cases if row["candidate_conversation_history"]
    }
    if observed_context_ids != set(HIGH_CONFIDENCE_CONTEXT_CASE_IDS):
        raise AuthenticCaseBuildError("context-link candidate set mismatch")
    if any(
        row["source_role"] != "user" or row["assistant_generated"]
        for row in cases
    ):
        raise AuthenticCaseBuildError("assistant turn became a current query")
    return cases


def write_authentic_case_bank(root: Path = ROOT) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases = build_authentic_cases(root)
    path = root / LOCAL_AUTHENTIC_BANK_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_jsonl_bytes(cases))
    pages = Counter(row["current_page"] for row in cases)
    query_hashes = sorted(row["raw_query_sha256"] for row in cases)
    summary = {
        "schema_version": "authentic-case-summary-v1",
        "stage": "RQ2-A-R1B",
        "status": "PASS",
        "bank_alias": AUTHENTIC_BANK_ALIAS,
        "case_count": len(cases),
        "unique_case_id_count": len({row["case_id"] for row in cases}),
        "case_id_set_sha256": id_set_sha256([row["case_id"] for row in cases]),
        "query_hash_set_sha256": sha256_bytes(
            ("\n".join(query_hashes) + "\n").encode("utf-8")
        ),
        "local_case_bank_sha256": sha256_file(path),
        "local_case_bank_size_bytes": path.stat().st_size,
        "source_role_distribution": {"user": len(cases)},
        "page_distribution": dict(sorted(pages.items())),
        "expected_page_distribution": AUTHENTIC_PAGE_DISTRIBUTION,
        "context_link_candidate_count": len(HIGH_CONFIDENCE_CONTEXT_CASE_IDS),
        "context_link_candidate_case_ids": list(HIGH_CONFIDENCE_CONTEXT_CASE_IDS),
        "other_case_count_with_blank_candidate_history": (
            len(cases) - len(HIGH_CONFIDENCE_CONTEXT_CASE_IDS)
        ),
        "assistant_turns_used_as_current_query": 0,
        "assistant_context_is_capability_gold": False,
        "automatic_session_inference_performed": False,
        "full_cases_local_only": True,
        "tracked_query_text": False,
        "tracked_assistant_text": False,
    }
    (HERE / "authentic_case_summary_v1.json").write_bytes(
        canonical_json_bytes(summary)
    )
    return cases, summary
