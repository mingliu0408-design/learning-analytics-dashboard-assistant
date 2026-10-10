"""Build exact source-blinded label-only and local full-text Track-B Gold."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any, Sequence

from . import (
    FULL_GOLD_RELATIVE,
    FULL_GOLD_SHA256,
    FULL_GOLD_SIZE,
    GOLD_ALIAS,
    GOLD_FIELDS,
    GOLD_INCLUSION_STATUS,
    LABEL_GOLD_FIELDS,
    LABEL_GOLD_RELATIVE,
    LABEL_GOLD_SHA256,
    LABEL_GOLD_SIZE,
    ROOT,
    SOURCE_ROLE,
    canonical_jsonl_bytes,
    durable_write,
    normalise_forbidden,
    sha256_bytes,
    sha256_file,
)
from .human_decision_precedence import ResolvedDecision


class SourceBlindedGoldBuildError(RuntimeError):
    pass


def build_gold_rows(
    decisions: Sequence[ResolvedDecision],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(decisions) != 48 or [item.review_case_id for item in decisions] != sorted(
        item.review_case_id for item in decisions
    ):
        raise SourceBlindedGoldBuildError("resolved decisions are not sorted 48-case Gold")
    label_rows: list[dict[str, Any]] = []
    full_rows: list[dict[str, Any]] = []
    for decision in decisions:
        labels: dict[str, Any] = dict(decision.labels)
        # Naturalness remains the canonical CSV string; this is part of the frozen identity.
        labels["forbidden_capabilities"] = list(
            normalise_forbidden(labels["forbidden_capabilities"])
        )
        label = {
            "review_case_id": decision.review_case_id,
            "source_role": SOURCE_ROLE,
            "gold_inclusion_status": GOLD_INCLUSION_STATUS,
            "gold_decision_source": decision.gold_decision_source,
            **labels,
            "query_rewrite_performed": False,
            "assistant_context_attached": False,
        }
        if set(label) != set(LABEL_GOLD_FIELDS):
            raise SourceBlindedGoldBuildError("label-only Gold schema mismatch")
        full = {
            **label,
            **{
                field: value
                for field, value in decision.visible.items()
                if field != "review_case_id"
            },
        }
        label_rows.append(label)
        full_rows.append(full)
    return label_rows, full_rows


def build_gold_bytes(
    decisions: Sequence[ResolvedDecision],
) -> tuple[bytes, bytes, list[dict[str, Any]], list[dict[str, Any]]]:
    label_rows, full_rows = build_gold_rows(decisions)
    return (
        canonical_jsonl_bytes(label_rows),
        canonical_jsonl_bytes(full_rows),
        label_rows,
        full_rows,
    )


def write_gold(
    decisions: Sequence[ResolvedDecision], root: Path = ROOT
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    label_bytes, full_bytes, label_rows, full_rows = build_gold_bytes(decisions)
    if (
        sha256_bytes(label_bytes) != LABEL_GOLD_SHA256
        or len(label_bytes) != LABEL_GOLD_SIZE
        or sha256_bytes(full_bytes) != FULL_GOLD_SHA256
        or len(full_bytes) != FULL_GOLD_SIZE
    ):
        raise SourceBlindedGoldBuildError("BLOCKED_RQ2_D2B_GOLD_IDENTITY_MISMATCH")
    # Required freeze order: local full-text Gold is persisted before tracked label-only Gold.
    full_path = root / FULL_GOLD_RELATIVE
    label_path = root / LABEL_GOLD_RELATIVE
    durable_write(full_path, full_bytes)
    durable_write(label_path, label_bytes, mode=0o644)
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", FULL_GOLD_RELATIVE.as_posix()],
        cwd=root,
        check=False,
    ).returncode == 0
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", FULL_GOLD_RELATIVE.as_posix()],
        cwd=root,
        capture_output=True,
        check=False,
    ).returncode == 0
    if (
        not ignored
        or tracked
        or sha256_file(label_path) != LABEL_GOLD_SHA256
        or label_path.stat().st_size != LABEL_GOLD_SIZE
        or sha256_file(full_path) != FULL_GOLD_SHA256
        or full_path.stat().st_size != FULL_GOLD_SIZE
        or not label_bytes.endswith(b"\n")
        or label_bytes.startswith(b"\xef\xbb\xbf")
        or b"\r\n" in label_bytes
        or not full_bytes.endswith(b"\n")
        or full_bytes.startswith(b"\xef\xbb\xbf")
        or b"\r\n" in full_bytes
    ):
        raise SourceBlindedGoldBuildError("Gold persistence or canonical JSONL mismatch")
    # Parse only to verify canonical row count and schema; no row content is emitted.
    observed_label = [json.loads(line) for line in label_bytes.decode("utf-8").splitlines()]
    observed_full = [json.loads(line) for line in full_bytes.decode("utf-8").splitlines()]
    if len(observed_label) != 48 or len(observed_full) != 48:
        raise SourceBlindedGoldBuildError("Gold record count mismatch")
    second_label, second_full, _, _ = build_gold_bytes(decisions)
    if second_label != label_bytes or second_full != full_bytes:
        raise SourceBlindedGoldBuildError("Gold double build is not byte-identical")
    return label_rows, full_rows, {
        "schema_version": "track-b-source-blinded-gold-build-v1",
        "stage": "RQ2-D2B",
        "status": "PASS",
        "gold_alias": GOLD_ALIAS,
        "label_only_gold": {
            "relative_path": LABEL_GOLD_RELATIVE.as_posix(),
            "sha256": LABEL_GOLD_SHA256,
            "size_bytes": LABEL_GOLD_SIZE,
            "record_count": 48,
            "tracked": True,
            "contains_query_or_history": False,
        },
        "full_text_gold": {
            "relative_path": FULL_GOLD_RELATIVE.as_posix(),
            "sha256": FULL_GOLD_SHA256,
            "size_bytes": FULL_GOLD_SIZE,
            "record_count": 48,
            "tracked": False,
            "ignored": True,
            "local_only": True,
            "contains_rationale": False,
        },
        "canonical_jsonl": {
            "encoding": "UTF-8_WITHOUT_BOM",
            "newline": "LF_ONLY",
            "sort_keys": True,
            "ensure_ascii": False,
            "separators": [",", ":"],
            "final_lf": True,
            "record_order": "review_case_id_ASCENDING",
        },
        "double_build_byte_identical": True,
    }
