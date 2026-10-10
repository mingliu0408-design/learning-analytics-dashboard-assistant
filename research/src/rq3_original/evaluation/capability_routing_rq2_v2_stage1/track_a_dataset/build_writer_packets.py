"""Build the two deterministic, blinded Track A human-writer packets."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import random
from typing import Any, Iterable


PACKAGE_ROOT = Path(__file__).resolve().parent
MASTER_PATH = PACKAGE_ROOT / "scenario_blueprints.jsonl"
PACKET_PATHS = {
    "A": PACKAGE_ROOT / "writer_packet_A.csv",
    "B": PACKAGE_ROOT / "writer_packet_B.csv",
}
SHUFFLE_SEEDS = {"A": 20260830, "B": 30082026}
WRITER_FIELDS = (
    "review_case_id",
    "scenario_family_id",
    "utterance_id",
    "current_page",
    "dashboard_context",
    "visible_conversation_history",
    "student_background",
    "request_goal",
    "natural_student_query",
)


def load_master(path: Path = MASTER_PATH) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} is not a JSON object")
        rows.append(value)
    return rows


def _numeric_suffix(blueprint: dict[str, Any]) -> str:
    review_case_id = str(blueprint["review_case_id"])
    prefix = "R2V2-W-"
    suffix = review_case_id.removeprefix(prefix)
    if not review_case_id.startswith(prefix) or len(suffix) != 3 or not suffix.isdigit():
        raise ValueError(f"invalid blinded review_case_id: {review_case_id}")
    return suffix


def writer_row(writer: str, blueprint: dict[str, Any]) -> dict[str, str]:
    suffix = _numeric_suffix(blueprint)
    return {
        "review_case_id": str(blueprint["review_case_id"]),
        "scenario_family_id": f"R2V2-SF-{suffix}",
        "utterance_id": f"R2V2-U-{suffix}-{writer}",
        "current_page": str(blueprint["current_page"]),
        "dashboard_context": str(blueprint["controlled_dashboard_context"]),
        "visible_conversation_history": json.dumps(
            blueprint["visible_conversation_history"],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "student_background": str(blueprint["writer_facing_student_background"]),
        "request_goal": str(blueprint["writer_facing_request_goal"]),
        "natural_student_query": "",
    }


def expected_packet_rows(
    writer: str, blueprints: Iterable[dict[str, Any]] | None = None
) -> list[dict[str, str]]:
    if writer not in SHUFFLE_SEEDS:
        raise ValueError(f"unknown writer: {writer}")
    rows = [writer_row(writer, row) for row in (blueprints or load_master())]
    random.Random(SHUFFLE_SEEDS[writer]).shuffle(rows)
    return rows


def _assert_existing_packet_is_unfilled(path: Path, expected_review_ids: set[str]) -> None:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 54:
        raise ValueError(f"refusing to replace packet with unexpected row count: {path}")
    if {str(row.get("review_case_id", "")) for row in rows} != expected_review_ids:
        raise ValueError(f"refusing to replace packet with unexpected review IDs: {path}")
    if any(str(row.get("natural_student_query", "")) for row in rows):
        raise ValueError(f"refusing to replace packet containing writer queries: {path}")


def build_packets(*, overwrite_empty_only: bool = False) -> dict[str, Any]:
    blueprints = load_master()
    expected_review_ids = {str(row["review_case_id"]) for row in blueprints}
    outputs: dict[str, Any] = {}
    for writer, output_path in PACKET_PATHS.items():
        if output_path.exists():
            if not overwrite_empty_only:
                raise FileExistsError(f"refusing to overwrite writer packet: {output_path}")
            _assert_existing_packet_is_unfilled(output_path, expected_review_ids)
        rows = expected_packet_rows(writer, blueprints)
        mode = "w" if output_path.exists() else "x"
        with output_path.open(mode, encoding="utf-8", newline="") as handle:
            csv_writer = csv.DictWriter(
                handle,
                fieldnames=WRITER_FIELDS,
                lineterminator="\n",
            )
            csv_writer.writeheader()
            csv_writer.writerows(rows)
        outputs[writer] = {
            "path": str(output_path),
            "row_count": len(rows),
            "shuffle_seed": SHUFFLE_SEEDS[writer],
            "replacement_mode": "EMPTY_PACKET_ONLY" if mode == "w" else "CREATE",
        }
    return {"status": "PASS", "packets": outputs}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overwrite-empty-only", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            build_packets(overwrite_empty_only=args.overwrite_empty_only),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
