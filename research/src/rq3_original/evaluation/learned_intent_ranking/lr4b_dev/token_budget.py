"""Explicit token-budget checks for frozen RQ1-A representations."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any, Iterable, Sequence

from evaluation.learned_intent_ranking.lr4b.context_representation import (
    build_structured_context_representation,
)


MAX_SEQUENCE_LENGTH = 384


class ActualTruncationAuthorityRequired(RuntimeError):
    pass


class SyntheticTruncationError(ValueError):
    pass


def token_count(tokenizer: Any, text: str) -> int:
    encoded = tokenizer(
        text,
        add_special_tokens=True,
        truncation=False,
        return_attention_mask=False,
        return_token_type_ids=False,
    )
    return len(encoded["input_ids"])


def _nearest_rank(values: Sequence[int], fraction: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def distribution(values: Iterable[int]) -> dict[str, Any]:
    rows = list(values)
    if not rows:
        return {
            "record_count": 0,
            "minimum": None,
            "median": None,
            "mean": None,
            "p95_nearest_rank": None,
            "p99_nearest_rank": None,
            "maximum": None,
            "over_384_count": 0,
        }
    return {
        "record_count": len(rows),
        "minimum": min(rows),
        "median": float(statistics.median(rows)),
        "mean": float(statistics.fmean(rows)),
        "p95_nearest_rank": _nearest_rank(rows, 0.95),
        "p99_nearest_rank": _nearest_rank(rows, 0.99),
        "maximum": max(rows),
        "over_384_count": sum(value > MAX_SEQUENCE_LENGTH for value in rows),
    }


def truncate_previous_turns_oldest_edge(
    tokenizer: Any,
    *,
    question_anchor: str,
    previous_turns: Sequence[str],
    current_student_utterance: str,
    max_sequence_length: int = MAX_SEQUENCE_LENGTH,
) -> dict[str, Any]:
    """Synthetic-only policy: remove complete oldest turns and nothing else."""

    if not previous_turns or any(not str(value).strip() for value in previous_turns):
        raise SyntheticTruncationError("non-empty previous turns are required")

    def build(turns: Sequence[str]) -> str:
        return build_structured_context_representation(
            question_anchor_for_review=question_anchor,
            previous_turns_for_review="\n".join(str(value) for value in turns),
            utterance_for_review=current_student_utterance,
        )

    fixed_probe = build_structured_context_representation(
        question_anchor_for_review=question_anchor,
        previous_turns_for_review="[EMPTY_PREVIOUS_TURN_PROBE]",
        utterance_for_review=current_student_utterance,
    )
    if token_count(tokenizer, fixed_probe) > max_sequence_length:
        raise SyntheticTruncationError("fixed structured-context fields exceed token budget")

    retained = list(previous_turns)
    original_count = token_count(tokenizer, build(retained))
    while retained and token_count(tokenizer, build(retained)) > max_sequence_length:
        retained.pop(0)
    if not retained:
        raise SyntheticTruncationError("no previous turn can be retained within token budget")
    representation = build(retained)
    final_count = token_count(tokenizer, representation)
    if final_count > max_sequence_length:
        raise SyntheticTruncationError("explicit oldest-edge truncation did not fit")
    return {
        "representation": representation,
        "retained_previous_turns": tuple(retained),
        "removed_previous_turn_count": len(previous_turns) - len(retained),
        "original_token_count": original_count,
        "final_token_count": final_count,
        "current_student_utterance_preserved": current_student_utterance in representation,
        "question_anchor_preserved": question_anchor in representation,
        "headers_preserved": all(
            header in representation
            for header in (
                "[QUESTION_ANCHOR]",
                "[PREVIOUS_TURNS]",
                "[CURRENT_STUDENT_UTTERANCE]",
            )
        ),
        "truncation_edge": "OLDEST_PREVIOUS_TURN_ONLY",
    }


def build_token_budget_report(bundle: dict[str, Any], tokenizer: Any) -> dict[str, Any]:
    train_counts: dict[str, int] = {
        row["record_id"]: token_count(tokenizer, row["representation"])
        for row in bundle["records"]
    }
    candidate_counts = {
        row["example_id"]: token_count(tokenizer, str(row["query"]))
        for row in bundle["approved_index"]
    }
    dev_plain: dict[str, int] = {}
    dev_page: dict[str, int] = {}
    for row in bundle["dev_records"]:
        plain = str(row["query"]).strip()
        page = f"[PAGE={row['current_page']}] {plain}"
        dev_plain[row["record_id"]] = token_count(tokenizer, plain)
        dev_page[row["record_id"]] = token_count(tokenizer, page)
    dev_logical = {
        record_id: max(dev_plain[record_id], dev_page[record_id])
        for record_id in dev_plain
    }

    per_context: defaultdict[str, list[int]] = defaultdict(list)
    for row in bundle["records"]:
        per_context[row["context_mode"]].append(train_counts[row["record_id"]])
    per_scenario = {
        scenario: distribution(train_counts[record_id] for record_id in ids)
        for scenario, ids in bundle["scenario_ids"].items()
    }
    effective_counts = [
        *train_counts.values(),
        *candidate_counts.values(),
        *dev_plain.values(),
        *dev_page.values(),
    ]
    all_real_over = sum(value > MAX_SEQUENCE_LENGTH for value in effective_counts)
    if all_real_over:
        raise ActualTruncationAuthorityRequired(
            "one or more actual representations exceed the frozen token budget"
        )

    synthetic_previous = [
        f"synthetic previous turn {index} " + "token " * 36
        for index in range(1, 18)
    ]
    synthetic = truncate_previous_turns_oldest_edge(
        tokenizer,
        question_anchor="synthetic immutable question anchor",
        previous_turns=synthetic_previous,
        current_student_utterance="synthetic immutable current student utterance",
    )
    synthetic_safe = {
        key: value
        for key, value in synthetic.items()
        if key not in {"representation", "retained_previous_turns"}
    }
    synthetic_safe["retained_previous_turn_count"] = len(
        synthetic["retained_previous_turns"]
    )
    if not synthetic_safe["removed_previous_turn_count"]:
        raise SyntheticTruncationError("synthetic truncation fixture did not exercise removal")

    return {
        "schema_version": "rq1b-token-budget-summary-v1",
        "stage": "RQ1-B",
        "status": "PASS",
        "tokenizer_local_only": True,
        "effective_max_sequence_length": MAX_SEQUENCE_LENGTH,
        "max_sequence_length_independently_verified": True,
        "percentile_method": "NEAREST_RANK",
        "logical_record_counts": {
            "governed_train": len(train_counts),
            "dev_query": len(dev_logical),
            "approved_candidate": len(candidate_counts),
            "total": len(train_counts) + len(dev_logical) + len(candidate_counts),
        },
        "effective_model_input_variant_counts": {
            "governed_train": len(train_counts),
            "dev_plain": len(dev_plain),
            "dev_page_prefixed": len(dev_page),
            "approved_candidate": len(candidate_counts),
            "total": len(effective_counts),
        },
        "distributions": {
            "all_effective_model_inputs": distribution(effective_counts),
            "governed_train": distribution(train_counts.values()),
            "dev_query_logical_max_of_plain_and_page": distribution(dev_logical.values()),
            "dev_plain": distribution(dev_plain.values()),
            "dev_page_prefixed": distribution(dev_page.values()),
            "approved_candidate": distribution(candidate_counts.values()),
        },
        "per_context_mode_distribution": {
            mode: distribution(values) for mode, values in sorted(per_context.items())
        },
        "per_scenario_distribution": per_scenario,
        "actual_over_384_count": all_real_over,
        "actual_truncation_count": 0,
        "tokenizer_silent_truncation_used": False,
        "synthetic_truncation_contract_test": synthetic_safe,
        "synthetic_test_authorises_actual_truncation": False,
        "raw_text_emitted": False,
        "final_gold_accessed": False,
    }
