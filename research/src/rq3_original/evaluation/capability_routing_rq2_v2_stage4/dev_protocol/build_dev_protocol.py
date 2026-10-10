"""Build the DEV-only grouping map, CV freeze, and Stage 4-0 protocol.

Only standard-library parsing and deterministic metadata optimisation are used.
No Router is imported, trained, called, or scored.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
import hashlib
import io
import itertools
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
import zipfile

from . import (
    ANSWER_SIGNATURES,
    CAPABILITY_NAMES,
    DEV_ALLOWED_MEMBERS,
    DEV_CV_SEED,
    DEV_RELEASE_BASENAME,
    DEV_RELEASE_SHA256,
    FEATURE_PROFILE,
    FOLD_IDS,
    LAD_PAGES,
    MODEL_IDS,
    PACKAGE_ROOT,
    READY_STATUS,
    ROUTING_SIGNATURES,
    STAGE3C_RELEASE_BASENAME,
    STAGE3C_RELEASE_SHA256,
)
from .protocol_contract import (
    CLARIFICATION_BOUNDARY,
    METRIC_CONTRACT,
    MODEL_FEATURE_CONTRACT,
    TIE_BREAK_CONTRACT,
)


DEFAULT_DEV_ZIP = Path("/Users/liuming/Downloads") / DEV_RELEASE_BASENAME
DEFAULT_STAGE3C_ZIP = Path("/Users/liuming/Downloads") / STAGE3C_RELEASE_BASENAME
STAGE3C_ASSIGNMENT_MEMBER = "split_assignment_restricted_v1.csv"

DEV_CSV_FIELDS = (
    "annotation_case_id",
    "scenario_family_id",
    "current_query",
    "current_page",
    "dashboard_context",
    "visible_conversation_history",
    "final_dialogue_action",
    "final_rag_required",
    "final_memory_required",
    "final_planning_required",
    "final_naturalness",
    "partition",
)
GROUP_FIELDS = (
    "annotation_case_id",
    "scenario_family_id",
    "dev_atomic_component_id",
    "dev_contrast_group_id",
    "dev_contrast_axis",
    "final_family_routing_signature",
    "current_page",
)
FOLD_FIELDS = (
    "annotation_case_id",
    "scenario_family_id",
    "dev_atomic_component_id",
    "fold_id",
    "fold_role",
    "final_dialogue_action",
    "final_routing_signature",
    "current_page",
)

STATIC_PROTOCOL_FILES = (
    "__init__.py",
    "build_dev_protocol.py",
    "build_review_zip.py",
    "protocol_contract.py",
    "test_dev_protocol.py",
    "validate_dev_protocol.py",
)
GENERATED_PROTOCOL_FILES = (
    *DEV_ALLOWED_MEMBERS,
    "DEV_SOURCE_MANIFEST.json",
    "dev_atomic_group_map_v1.csv",
    "dev_atomic_group_map_v1.jsonl",
    "dev_cv_folds_v1.csv",
    "dev_cv_folds_v1.jsonl",
    "DEV_CV_BALANCE_REPORT.md",
    "DEV_CV_OPTIMIZATION_REPORT.json",
    "stage4_dev_protocol_v1.json",
    "STAGE4_DEV_PROTOCOL.md",
    "STATUS.md",
)
SHA256_MANIFEST_NAME = "STAGE4_DEV_PROTOCOL_SHA256_MANIFEST.json"
REVIEW_PAYLOAD_FILES = tuple(sorted((*STATIC_PROTOCOL_FILES, *GENERATED_PROTOCOL_FILES)))
REVIEW_ARCHIVE_FILES = (*REVIEW_PAYLOAD_FILES, SHA256_MANIFEST_NAME)


class ProtocolBuildError(RuntimeError):
    """Raised when a source or deterministic freeze invariant differs."""


@dataclass(frozen=True)
class Family:
    family_id: str
    annotation_ids: tuple[str, str]
    component_id: str
    contrast_group_id: str
    contrast_axis: str
    action: str
    signature: str
    page: str


@dataclass(frozen=True)
class Component:
    component_id: str
    families: tuple[Family, ...]

    @property
    def family_count(self) -> int:
        return len(self.families)

    @property
    def clarify_family_count(self) -> int:
        return sum(family.action == "CLARIFY" for family in self.families)


@dataclass(frozen=True)
class FoldCandidate:
    mask: int
    component_indexes: tuple[int, ...]
    signature_score: int
    page_scaled_score: int
    component_score: int
    tie_hash: str
    signature_counts: Mapping[str, int]
    page_counts: Mapping[str, int]


@dataclass(frozen=True)
class FoldSolution:
    folds: tuple[FoldCandidate, ...]
    components: tuple[Component, ...]
    objective: tuple[int, int, int]
    candidate_count: int
    search_nodes: int
    selection_sha256: str


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    lines = [
        json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for row in rows
    ]
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def _csv_bytes(rows: Iterable[Mapping[str, Any]], fields: Sequence[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(fields), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    return stream.getvalue().encode("utf-8")


def _seed_hash(purpose: str, value: str) -> str:
    return sha256_bytes(f"{DEV_CV_SEED}|{purpose}|{value}".encode("utf-8"))


def signature_from_dev_row(row: Mapping[str, str]) -> str:
    action = row.get("final_dialogue_action")
    labels = (
        row.get("final_rag_required"),
        row.get("final_memory_required"),
        row.get("final_planning_required"),
    )
    if action == "CLARIFY":
        if labels != ("NOT_APPLICABLE",) * 3:
            raise ProtocolBuildError("CLARIFY row must use three NOT_APPLICABLE labels")
        return "CLARIFY"
    if action != "ANSWER" or any(label not in {"YES", "NO"} for label in labels):
        raise ProtocolBuildError("invalid final human Capability labels")
    return "".join("1" if label == "YES" else "0" for label in labels)


def _validate_history(value: str) -> None:
    try:
        history = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProtocolBuildError("visible_conversation_history is not valid JSON") from exc
    if not isinstance(history, list):
        raise ProtocolBuildError("visible_conversation_history must decode to a list")
    for turn in history:
        if (
            not isinstance(turn, dict)
            or set(turn) != {"role", "content"}
            or turn["role"] not in {"user", "assistant"}
            or not isinstance(turn["content"], str)
        ):
            raise ProtocolBuildError("invalid visible conversation turn")


def validate_dev_rows(rows: Sequence[Mapping[str, str]]) -> None:
    if len(rows) != 72:
        raise ProtocolBuildError(f"DEV release must contain 72 rows, observed {len(rows)}")
    annotation_ids = [row.get("annotation_case_id", "") for row in rows]
    if any(not value for value in annotation_ids) or len(set(annotation_ids)) != 72:
        raise ProtocolBuildError("DEV annotation IDs must be non-empty and unique")
    if any(row.get("partition") != "DEV" for row in rows):
        raise ProtocolBuildError("DEV release contains a non-DEV record")

    family_rows: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        family_rows[row.get("scenario_family_id", "")].append(row)
        _validate_history(row.get("visible_conversation_history", ""))
        signature_from_dev_row(row)
        if row.get("final_naturalness") not in {"NATURAL", "ACCEPTABLE"}:
            raise ProtocolBuildError("invalid final human naturalness label")
    if len(family_rows) != 36 or any(len(values) != 2 for values in family_rows.values()):
        raise ProtocolBuildError("DEV must contain exactly two utterances in each of 36 families")

    for values in family_rows.values():
        invariant_fields = (
            "current_page",
            "final_dialogue_action",
            "final_rag_required",
            "final_memory_required",
            "final_planning_required",
        )
        if any(len({row[field] for row in values}) != 1 for field in invariant_fields):
            raise ProtocolBuildError("family-level final route or page is inconsistent")

    actions = Counter(row["final_dialogue_action"] for row in rows)
    if actions != Counter({"ANSWER": 64, "CLARIFY": 8}):
        raise ProtocolBuildError(f"DEV action counts differ: {dict(actions)}")


def load_dev_release(path: Path) -> tuple[dict[str, bytes], list[dict[str, str]]]:
    path = Path(path)
    if not path.is_file() or sha256_file(path) != DEV_RELEASE_SHA256:
        raise ProtocolBuildError("DEV source ZIP hash differs from the authorized SHA-256")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(DEV_ALLOWED_MEMBERS) or set(names) != set(DEV_ALLOWED_MEMBERS):
            raise ProtocolBuildError("DEV source ZIP member allowlist differs")
        payloads = {name: archive.read(name) for name in DEV_ALLOWED_MEMBERS}

    manifest = json.loads(payloads["DEV_SHA256_MANIFEST.json"].decode("utf-8"))
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ProtocolBuildError("DEV SHA-256 manifest has no file list")
    observed_names = {str(entry.get("name")) for entry in entries}
    expected_hashed_names = set(DEV_ALLOWED_MEMBERS) - {"DEV_SHA256_MANIFEST.json"}
    if observed_names != expected_hashed_names:
        raise ProtocolBuildError("DEV SHA-256 manifest member set differs")
    for entry in entries:
        name = str(entry["name"])
        if (
            sha256_bytes(payloads[name]) != entry.get("sha256")
            or len(payloads[name]) != entry.get("size_bytes")
        ):
            raise ProtocolBuildError(f"DEV member hash or size differs: {name}")

    csv_stream = io.StringIO(payloads["dev_capability_gold_v1.csv"].decode("utf-8-sig"))
    reader = csv.DictReader(csv_stream)
    if tuple(reader.fieldnames or ()) != DEV_CSV_FIELDS:
        raise ProtocolBuildError("DEV CSV field schema differs")
    csv_rows = [dict(row) for row in reader]
    jsonl_rows = [
        json.loads(line)
        for line in payloads["dev_capability_gold_v1.jsonl"].decode("utf-8").splitlines()
        if line.strip()
    ]
    if csv_rows != jsonl_rows:
        raise ProtocolBuildError("DEV CSV and JSONL records are not byte-semantically equal")
    validate_dev_rows(csv_rows)
    return payloads, csv_rows


def extract_dev_group_rows(
    path: Path, dev_rows: Sequence[Mapping[str, str]]
) -> tuple[list[dict[str, str]], int]:
    """Stream the restricted assignment and retain only authorized DEV fields.

    Non-DEV rows are discarded immediately.  No restricted row, writer field,
    or full assignment is returned or written.
    """

    path = Path(path)
    if not path.is_file() or sha256_file(path) != STAGE3C_RELEASE_SHA256:
        raise ProtocolBuildError("Stage 3C source ZIP hash differs from the authorized SHA-256")
    dev_by_id = {row["annotation_case_id"]: row for row in dev_rows}
    selected: list[dict[str, str]] = []
    family_utterance_pairs: set[tuple[str, str]] = set()
    with zipfile.ZipFile(path) as archive:
        try:
            raw = archive.open(STAGE3C_ASSIGNMENT_MEMBER)
        except KeyError as exc:
            raise ProtocolBuildError("Stage 3C restricted assignment member is absent") from exc
        with raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {
                "annotation_case_id",
                "canonical_scenario_family_id",
                "utterance_id",
                "current_page",
                "final_family_routing_signature",
                "atomic_component_id",
                "contrast_group_id",
                "contrast_axis",
                "partition",
            }
            if not required.issubset(reader.fieldnames or ()):
                raise ProtocolBuildError("Stage 3C assignment fields differ")
            for source_row in reader:
                if source_row["partition"] != "DEV":
                    continue
                case_id = source_row["annotation_case_id"]
                if case_id not in dev_by_id:
                    raise ProtocolBuildError("Stage 3C DEV row is absent from DEV-only release")
                pair = (
                    source_row["canonical_scenario_family_id"],
                    source_row["utterance_id"],
                )
                if pair in family_utterance_pairs:
                    raise ProtocolBuildError("duplicate DEV family/utterance combination")
                family_utterance_pairs.add(pair)
                selected.append(
                    {
                        "annotation_case_id": case_id,
                        "scenario_family_id": source_row["canonical_scenario_family_id"],
                        "dev_atomic_component_id": source_row["atomic_component_id"],
                        "dev_contrast_group_id": source_row["contrast_group_id"],
                        "dev_contrast_axis": source_row["contrast_axis"],
                        "final_family_routing_signature": source_row[
                            "final_family_routing_signature"
                        ],
                        "current_page": source_row["current_page"],
                    }
                )

    if len(selected) != 72 or {row["annotation_case_id"] for row in selected} != set(dev_by_id):
        raise ProtocolBuildError("Stage 3C DEV selection does not exactly join the DEV release")
    for row in selected:
        source = dev_by_id[row["annotation_case_id"]]
        if (
            row["scenario_family_id"] != source["scenario_family_id"]
            or row["current_page"] != source["current_page"]
            or row["final_family_routing_signature"] != signature_from_dev_row(source)
        ):
            raise ProtocolBuildError("sanitized Stage 3C DEV metadata differs from DEV Gold")
    selected.sort(key=lambda row: row["annotation_case_id"])
    return selected, len(family_utterance_pairs)


def build_families(
    dev_rows: Sequence[Mapping[str, str]], group_rows: Sequence[Mapping[str, str]]
) -> tuple[Family, ...]:
    dev_by_id = {row["annotation_case_id"]: row for row in dev_rows}
    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in group_rows:
        grouped[row["scenario_family_id"]].append(row)
    families: list[Family] = []
    for family_id, rows in grouped.items():
        if len(rows) != 2:
            raise ProtocolBuildError("grouping map must contain two rows per family")
        first = rows[0]
        invariant_fields = (
            "dev_atomic_component_id",
            "dev_contrast_group_id",
            "dev_contrast_axis",
            "final_family_routing_signature",
            "current_page",
        )
        if any(len({row[field] for row in rows}) != 1 for field in invariant_fields):
            raise ProtocolBuildError("grouping metadata differs within a family")
        actions = {dev_by_id[row["annotation_case_id"]]["final_dialogue_action"] for row in rows}
        if len(actions) != 1:
            raise ProtocolBuildError("dialogue action differs within a family")
        families.append(
            Family(
                family_id=family_id,
                annotation_ids=tuple(sorted(row["annotation_case_id"] for row in rows)),
                component_id=first["dev_atomic_component_id"],
                contrast_group_id=first["dev_contrast_group_id"],
                contrast_axis=first["dev_contrast_axis"],
                action=next(iter(actions)),
                signature=first["final_family_routing_signature"],
                page=first["current_page"],
            )
        )
    if len(families) != 36:
        raise ProtocolBuildError("grouping map must contain 36 families")
    return tuple(sorted(families, key=lambda family: family.family_id))


def build_components(families: Sequence[Family]) -> tuple[Component, ...]:
    grouped: dict[str, list[Family]] = defaultdict(list)
    for family in families:
        grouped[family.component_id].append(family)
    if len(grouped) != 24:
        raise ProtocolBuildError("DEV grouping map must contain 24 atomic components")
    components = [
        Component(
            component_id=component_id,
            families=tuple(sorted(values, key=lambda family: family.family_id)),
        )
        for component_id, values in grouped.items()
    ]
    sizes = Counter(component.family_count for component in components)
    if sizes != Counter({1: 12, 2: 12}):
        raise ProtocolBuildError("DEV components must be 12 paired and 12 singleton")
    for component in components:
        if component.family_count == 2:
            groups = {family.contrast_group_id for family in component.families}
            axes = {family.contrast_axis for family in component.families}
            if len(groups) != 1 or "" in groups or len(axes) != 1 or "" in axes:
                raise ProtocolBuildError("paired DEV component lacks one contrast group and axis")
        elif any(family.contrast_group_id or family.contrast_axis for family in component.families):
            raise ProtocolBuildError("singleton DEV component contains contrast metadata")
    return tuple(
        sorted(
            components,
            key=lambda component: _seed_hash("component-order", component.component_id),
        )
    )


def _candidate_for_indexes(
    indexes: tuple[int, ...], components: Sequence[Component], total_pages: Counter[str]
) -> FoldCandidate | None:
    families = [family for index in indexes for family in components[index].families]
    if len(families) != 9 or sum(family.action == "CLARIFY" for family in families) != 1:
        return None
    answer_families = [family for family in families if family.action == "ANSWER"]
    for bit in range(3):
        values = {family.signature[bit] for family in answer_families}
        if values != {"0", "1"}:
            return None
    signature_counts = Counter(family.signature for family in families)
    if any(signature_counts[signature] >= 4 for signature in ANSWER_SIGNATURES):
        return None
    page_counts = Counter(family.page for family in families)
    if set(page_counts) != set(LAD_PAGES):
        return None

    signature_score = sum((signature_counts[signature] - 1) ** 2 for signature in ROUTING_SIGNATURES)
    page_scaled_score = sum(
        (4 * page_counts[page] - total_pages[page]) ** 2 for page in LAD_PAGES
    )
    component_score = (len(indexes) - 6) ** 2
    component_payload = ",".join(components[index].component_id for index in indexes)
    return FoldCandidate(
        mask=sum(1 << index for index in indexes),
        component_indexes=indexes,
        signature_score=signature_score,
        page_scaled_score=page_scaled_score,
        component_score=component_score,
        tie_hash=_seed_hash("fold-candidate", component_payload),
        signature_counts={signature: signature_counts[signature] for signature in ROUTING_SIGNATURES},
        page_counts={page: page_counts[page] for page in LAD_PAGES},
    )


def optimise_folds(families: Sequence[Family]) -> FoldSolution:
    components = build_components(families)
    clarify = [
        index for index, component in enumerate(components) if component.clarify_family_count == 1
    ]
    double_answer = [
        index
        for index, component in enumerate(components)
        if component.family_count == 2 and component.clarify_family_count == 0
    ]
    single_answer = [
        index for index, component in enumerate(components) if component.family_count == 1
    ]
    if len(clarify) != 4 or len(double_answer) != 8 or len(single_answer) != 12:
        raise ProtocolBuildError("unexpected clarify/answer component structure")
    total_pages = Counter(family.page for family in families)

    candidates: list[FoldCandidate] = []
    for clarify_index in clarify:
        for double_count in range(4):
            single_count = 7 - 2 * double_count
            if single_count < 0:
                continue
            for doubles in itertools.combinations(double_answer, double_count):
                for singles in itertools.combinations(single_answer, single_count):
                    indexes = tuple(sorted((clarify_index, *doubles, *singles)))
                    candidate = _candidate_for_indexes(indexes, components, total_pages)
                    if candidate is not None:
                        candidates.append(candidate)
    if not candidates:
        raise ProtocolBuildError("no fold candidate satisfies the hard requirements")
    if len({candidate.tie_hash for candidate in candidates}) != len(candidates):
        raise ProtocolBuildError("seeded fold-candidate hash collision")

    by_component: dict[int, list[FoldCandidate]] = defaultdict(list)
    for candidate in candidates:
        for index in candidate.component_indexes:
            by_component[index].append(candidate)
    for values in by_component.values():
        values.sort(
            key=lambda candidate: (
                candidate.signature_score,
                candidate.page_scaled_score,
                candidate.component_score,
                candidate.tie_hash,
            )
        )

    full_mask = (1 << len(components)) - 1
    best_key: tuple[Any, ...] | None = None
    best_folds: tuple[FoldCandidate, ...] | None = None
    search_nodes = 0

    def search(
        used_mask: int,
        chosen: list[FoldCandidate],
        signature_score: int,
        page_score: int,
        component_score: int,
    ) -> None:
        nonlocal best_key, best_folds, search_nodes
        search_nodes += 1
        partial_objective = (signature_score, page_score, component_score)
        if best_key is not None and partial_objective > best_key[:3]:
            return
        if len(chosen) == 4:
            if used_mask != full_mask:
                return
            tie_key = tuple(sorted(candidate.tie_hash for candidate in chosen))
            key = (*partial_objective, tie_key)
            if best_key is None or key < best_key:
                best_key = key
                best_folds = tuple(chosen)
            return
        remaining_mask = full_mask ^ used_mask
        anchor = next(index for index in range(len(components)) if remaining_mask & (1 << index))
        for candidate in by_component[anchor]:
            if candidate.mask & used_mask:
                continue
            search(
                used_mask | candidate.mask,
                [*chosen, candidate],
                signature_score + candidate.signature_score,
                page_score + candidate.page_scaled_score,
                component_score + candidate.component_score,
            )

    search(0, [], 0, 0, 0)
    if best_key is None or best_folds is None:
        raise ProtocolBuildError("no exact four-fold cover satisfies the hard requirements")
    ordered_folds = tuple(sorted(best_folds, key=lambda candidate: candidate.tie_hash))
    selection_payload = "|".join(candidate.tie_hash for candidate in ordered_folds)
    return FoldSolution(
        folds=ordered_folds,
        components=components,
        objective=(int(best_key[0]), int(best_key[1]), int(best_key[2])),
        candidate_count=len(candidates),
        search_nodes=search_nodes,
        selection_sha256=_seed_hash("selected-four-fold-partition", selection_payload),
    )


def validation_family_fold_map(solution: FoldSolution) -> dict[str, str]:
    result: dict[str, str] = {}
    for fold_id, candidate in zip(FOLD_IDS, solution.folds):
        for index in candidate.component_indexes:
            for family in solution.components[index].families:
                if family.family_id in result:
                    raise ProtocolBuildError("family selected into more than one validation fold")
                result[family.family_id] = fold_id
    if len(result) != 36:
        raise ProtocolBuildError("validation fold assignment does not cover all families")
    return result


def render_group_artifacts(group_rows: Sequence[Mapping[str, str]]) -> dict[str, bytes]:
    csv_rows = [dict(row) for row in group_rows]
    jsonl_rows = []
    for source in group_rows:
        row = {field: source[field] for field in GROUP_FIELDS if source.get(field, "") != ""}
        jsonl_rows.append(row)
    return {
        "dev_atomic_group_map_v1.csv": _csv_bytes(csv_rows, GROUP_FIELDS),
        "dev_atomic_group_map_v1.jsonl": _jsonl_bytes(jsonl_rows),
    }


def render_fold_artifacts(
    dev_rows: Sequence[Mapping[str, str]],
    group_rows: Sequence[Mapping[str, str]],
    solution: FoldSolution,
) -> tuple[dict[str, bytes], list[dict[str, str]]]:
    dev_by_id = {row["annotation_case_id"]: row for row in dev_rows}
    family_folds = validation_family_fold_map(solution)
    ledger: list[dict[str, str]] = []
    for fold_id in FOLD_IDS:
        for group_row in sorted(group_rows, key=lambda row: row["annotation_case_id"]):
            source = dev_by_id[group_row["annotation_case_id"]]
            ledger.append(
                {
                    "annotation_case_id": group_row["annotation_case_id"],
                    "scenario_family_id": group_row["scenario_family_id"],
                    "dev_atomic_component_id": group_row["dev_atomic_component_id"],
                    "fold_id": fold_id,
                    "fold_role": (
                        "VALIDATION"
                        if family_folds[group_row["scenario_family_id"]] == fold_id
                        else "TRAINING"
                    ),
                    "final_dialogue_action": source["final_dialogue_action"],
                    "final_routing_signature": group_row["final_family_routing_signature"],
                    "current_page": group_row["current_page"],
                }
            )
    return (
        {
            "dev_cv_folds_v1.csv": _csv_bytes(ledger, FOLD_FIELDS),
            "dev_cv_folds_v1.jsonl": _jsonl_bytes(ledger),
        },
        ledger,
    )


def _fold_distribution(families: Sequence[Family], components: int) -> dict[str, Any]:
    signatures = Counter(family.signature for family in families)
    pages = Counter(family.page for family in families)
    axes_family = Counter(family.contrast_axis or "NONE" for family in families)
    component_axes: dict[str, str] = {}
    for family in families:
        component_axes.setdefault(family.component_id, family.contrast_axis or "NONE")
    axes_component = Counter(component_axes.values())
    answer = [family for family in families if family.action == "ANSWER"]
    capabilities = {
        capability: {
            "YES": sum(family.signature[index] == "1" for family in answer),
            "NO": sum(family.signature[index] == "0" for family in answer),
        }
        for index, capability in enumerate(CAPABILITY_NAMES)
    }
    family_actions = Counter(family.action for family in families)
    return {
        "families": len(families),
        "utterances": len(families) * 2,
        "atomic_components": components,
        "family_actions": {action: family_actions[action] for action in ("ANSWER", "CLARIFY")},
        "utterance_actions": {
            action: family_actions[action] * 2 for action in ("ANSWER", "CLARIFY")
        },
        "routing_signatures_families": {
            signature: signatures[signature] for signature in ROUTING_SIGNATURES
        },
        "capability_yes_no_answer_families": capabilities,
        "lad_pages_families": {page: pages[page] for page in LAD_PAGES},
        "contrast_axes_families": dict(sorted(axes_family.items())),
        "contrast_axes_components": dict(sorted(axes_component.items())),
    }


def build_optimization_report(solution: FoldSolution) -> dict[str, Any]:
    folds: dict[str, Any] = {}
    for fold_id, candidate in zip(FOLD_IDS, solution.folds):
        families = [
            family
            for index in candidate.component_indexes
            for family in solution.components[index].families
        ]
        folds[fold_id] = _fold_distribution(families, len(candidate.component_indexes))
    return {
        "schema_version": "rq2-v2-stage4-dev-cv-optimization-report-v1",
        "seed": DEV_CV_SEED,
        "selection_method": (
            "EXHAUSTIVE_ATOMIC_EXACT_COVER_LEXICOGRAPHIC_OBJECTIVES_WITH_SEEDED_SHA256_FINAL_TIEBREAK"
        ),
        "lexical_family_id_selection_used": False,
        "candidate_validation_subsets": solution.candidate_count,
        "branch_and_bound_nodes_visited": solution.search_nodes,
        "hard_requirements_feasible": True,
        "all_five_lad_pages_per_validation_fold_feasible": True,
        "exactly_one_of_every_signature_required": False,
        "objective_order": [
            "routing_signature_family_count_sum_squared_deviation_from_one",
            "page_family_count_scaled_sum_squared_deviation",
            "atomic_component_count_sum_squared_deviation_from_six",
            "seeded_sha256_final_tiebreak",
        ],
        "objective_values": {
            "routing_signature_ssd": solution.objective[0],
            "page_scaled_ssd": solution.objective[1],
            "page_ssd": solution.objective[1] / 16,
            "atomic_component_count_ssd": solution.objective[2],
        },
        "selection_sha256": solution.selection_sha256,
        "folds": folds,
    }


def render_balance_report(report: Mapping[str, Any]) -> bytes:
    objective = report["objective_values"]
    folds = report["folds"]
    lines = [
        "# RQ2-V2 Stage 4-0 DEV CV Balance Report",
        "",
        "Status: deterministic four-fold assignment is feasible with all hard requirements met.",
        "",
        f"- DEV CV seed: `{DEV_CV_SEED}`",
        "- Fold unit: atomic DEV component; no family or contrast component crosses folds.",
        "- Every validation fold contains all five LAD pages (feasible and achieved).",
        "- Exactly one of every route signature was not imposed; atomic pairs can make that infeasible.",
        "- Family-ID lexical order was not used for selection; seeded SHA-256 is only the final tie-break.",
        "",
        "## Lexicographic objective values",
        "",
        f"1. Routing-signature family-count SSD: `{objective['routing_signature_ssd']}`",
        f"2. Page family-count scaled SSD: `{objective['page_scaled_ssd']}` (unscaled `{objective['page_ssd']:.3f}`)",
        f"3. Atomic-component-count SSD: `{objective['atomic_component_count_ssd']}`",
        f"4. Seeded selection digest: `{report['selection_sha256']}`",
        "",
        "## Fold sizes and dialogue action",
        "",
        "| Fold | Families | Utterances | Components | ANSWER families | CLARIFY families | ANSWER utterances | CLARIFY utterances |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for fold_id in FOLD_IDS:
        fold = folds[fold_id]
        lines.append(
            f"| {fold_id} | {fold['families']} | {fold['utterances']} | {fold['atomic_components']} "
            f"| {fold['family_actions']['ANSWER']} | {fold['family_actions']['CLARIFY']} "
            f"| {fold['utterance_actions']['ANSWER']} | {fold['utterance_actions']['CLARIFY']} |"
        )

    lines.extend(["", "## Routing signatures (family counts)", ""])
    lines.append("| Fold | " + " | ".join(ROUTING_SIGNATURES) + " |")
    lines.append("|---|" + "---:|" * len(ROUTING_SIGNATURES))
    for fold_id in FOLD_IDS:
        counts = folds[fold_id]["routing_signatures_families"]
        lines.append("| " + fold_id + " | " + " | ".join(str(counts[s]) for s in ROUTING_SIGNATURES) + " |")

    lines.extend(["", "## Capability coverage (ANSWER-family counts)", ""])
    lines.append("| Fold | RAG YES/NO | Memory YES/NO | Planning YES/NO |")
    lines.append("|---|---:|---:|---:|")
    for fold_id in FOLD_IDS:
        values = folds[fold_id]["capability_yes_no_answer_families"]
        lines.append(
            f"| {fold_id} | {values['RAG']['YES']}/{values['RAG']['NO']} "
            f"| {values['Memory']['YES']}/{values['Memory']['NO']} "
            f"| {values['Planning']['YES']}/{values['Planning']['NO']} |"
        )

    lines.extend(["", "## LAD pages (family counts)", ""])
    lines.append("| Fold | " + " | ".join(LAD_PAGES) + " |")
    lines.append("|---|" + "---:|" * len(LAD_PAGES))
    for fold_id in FOLD_IDS:
        counts = folds[fold_id]["lad_pages_families"]
        lines.append("| " + fold_id + " | " + " | ".join(str(counts[p]) for p in LAD_PAGES) + " |")

    all_axes = sorted({axis for fold in folds.values() for axis in fold["contrast_axes_families"]})
    lines.extend(["", "## Contrast axes (family counts)", ""])
    lines.append("| Fold | " + " | ".join(all_axes) + " |")
    lines.append("|---|" + "---:|" * len(all_axes))
    for fold_id in FOLD_IDS:
        counts = folds[fold_id]["contrast_axes_families"]
        lines.append("| " + fold_id + " | " + " | ".join(str(counts.get(axis, 0)) for axis in all_axes) + " |")

    lines.extend(
        [
            "",
            "## Training-complement coverage",
            "",
            "For each fold, the 27-family training complement contains at least one family from every ANSWER signature `000` through `111`.",
            "",
            "Grouping, route, page, action, and fold fields are validation/audit metadata only and are prohibited model features.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def build_source_manifest(
    dev_payloads: Mapping[str, bytes], duplicate_pair_count: int
) -> dict[str, Any]:
    return {
        "schema_version": "rq2-v2-stage4-dev-source-manifest-v1",
        "dev_source_package": {
            "basename": DEV_RELEASE_BASENAME,
            "sha256": DEV_RELEASE_SHA256,
            "member_allowlist_exact": True,
            "members": [
                {
                    "name": name,
                    "sha256": sha256_bytes(dev_payloads[name]),
                    "size_bytes": len(dev_payloads[name]),
                }
                for name in DEV_ALLOWED_MEMBERS
            ],
        },
        "grouping_metadata_source": {
            "basename": STAGE3C_RELEASE_BASENAME,
            "sha256": STAGE3C_RELEASE_SHA256,
            "inspected_member": STAGE3C_ASSIGNMENT_MEMBER,
            "selection": "PARTITION_EQUALS_DEV_ONLY",
            "retained_fields": list(GROUP_FIELDS),
            "non_dev_rows_retained": 0,
            "writer_identity_retained": False,
            "full_split_assignment_retained": False,
        },
        "verified_dev_structure": {
            "utterances": 72,
            "scenario_families": 36,
            "answer_utterances": 64,
            "clarify_utterances": 8,
            "utterances_per_family": 2,
            "duplicate_annotation_ids": 0,
            "duplicate_family_utterance_combinations": 72 - duplicate_pair_count,
            "all_partitions": ["DEV"],
            "visible_history_json_valid": True,
            "final_human_capability_labels_valid": True,
        },
        "governance": {
            "test_record_retained": False,
            "test_identifier_retained": False,
            "test_query_or_gold_accessed": False,
            "exact_dev_release_members_copied_unchanged": True,
        },
    }


def build_protocol(
    group_artifacts: Mapping[str, bytes],
    fold_artifacts: Mapping[str, bytes],
    family_folds: Mapping[str, str],
    optimization_report: Mapping[str, Any],
) -> dict[str, Any]:
    compact_assignment = [
        {"scenario_family_id": family_id, "validation_fold_id": family_folds[family_id]}
        for family_id in sorted(family_folds)
    ]
    return {
        "schema_version": "rq2-v2-stage4-dev-protocol-v1",
        "stage": "RQ2_V2_STAGE_4_0_DEV_ONLY_MODEL_DEVELOPMENT_PROTOCOL",
        "status": READY_STATUS,
        "source_commit": "ae30c78c00c88768f8c5b9622d3b48216a859a91",
        "dev_source": {
            "package_basename": DEV_RELEASE_BASENAME,
            "sha256": DEV_RELEASE_SHA256,
            "utterances": 72,
            "families": 36,
        },
        "dev_grouping_map": {
            "primary_artifact": "dev_atomic_group_map_v1.jsonl",
            "primary_sha256": sha256_bytes(group_artifacts["dev_atomic_group_map_v1.jsonl"]),
            "csv_sha256": sha256_bytes(group_artifacts["dev_atomic_group_map_v1.csv"]),
            "atomic_components": 24,
            "two_family_contrast_components": 12,
            "singleton_components": 12,
            "model_feature_eligible": False,
        },
        "cross_validation": {
            "seed": DEV_CV_SEED,
            "fold_count": 4,
            "expanded_iteration_rows": 288,
            "validation_families_per_fold": 9,
            "validation_utterances_per_fold": 18,
            "training_families_per_fold": 27,
            "training_utterances_per_fold": 54,
            "primary_artifact": "dev_cv_folds_v1.jsonl",
            "primary_sha256": sha256_bytes(fold_artifacts["dev_cv_folds_v1.jsonl"]),
            "csv_sha256": sha256_bytes(fold_artifacts["dev_cv_folds_v1.csv"]),
            "compact_validation_assignment_sha256": sha256_bytes(
                _jsonl_bytes(compact_assignment)
            ),
            "optimization": dict(optimization_report),
        },
        "feature_contract": MODEL_FEATURE_CONTRACT,
        "clarification_boundary": CLARIFICATION_BOUNDARY,
        "evaluation_metrics": METRIC_CONTRACT,
        "model_selection_tie_breaks": TIE_BREAK_CONTRACT,
        "test_prohibition": {
            "test_input_access": False,
            "test_gold_access": False,
            "test_performance_for_decisions": False,
            "test_execution": False,
        },
        "primary_experiment_augmentation": {
            "synthetic_augmentation_allowed": False,
            "existing_synthetic_stress_case_count": 35,
            "canonical_model_input_status": "NOT_CANONICAL_EXCLUDED_FROM_PRIMARY_STAGE4_CALIBRATION",
            "fabricate_canonical_fields": False,
        },
        "stage4_0_execution": {
            "model_training": False,
            "router_execution": False,
            "provider_calls": False,
            "model_performance_calculation": False,
            "rq3_execution": False,
        },
    }


def render_protocol_markdown(protocol: Mapping[str, Any]) -> bytes:
    lines = [
        "# RQ2-V2 Stage 4-0 DEV-only Model-Development Protocol",
        "",
        f"Status: `{READY_STATUS}`",
        "",
        "This freeze defines DEV-only cross-validation, scientific boundaries, metrics, and selection rules. It performs no model training, Router execution, provider call, performance calculation, TEST execution, or RQ3 work.",
        "",
        "## Source and grouping freeze",
        "",
        f"- DEV source SHA-256: `{DEV_RELEASE_SHA256}`",
        f"- Stage 3C grouping source SHA-256: `{STAGE3C_RELEASE_SHA256}`",
        "- Authorized DEV structure: 72 utterances, 36 families, 64 ANSWER, 8 CLARIFY.",
        "- Sanitized grouping structure: 24 atomic components; 12 paired contrast components and 12 singletons.",
        "- No non-DEV row, writer identity, or restricted full assignment is retained.",
        "",
        "## Shared architecture boundary",
        "",
        "All B0, B1, B2, B3, B4, and P1 end-to-end routes use the same separately evaluated upstream clarification gate. A predicted CLARIFY stops core routing and yields NOT_APPLICABLE for RAG, Memory, and Planning.",
        "",
        "Core Router model selection is a separate conditional comparison on final-human-Gold ANSWER cases. The clarification gate is not invoked in that conditional comparison; this prevents gate differences from entering the core comparison. End-to-end evaluation applies the shared gate first on all cases.",
        "",
        "## Model-visible feature profile",
        "",
        f"Primary profile: `{FEATURE_PROFILE}`",
        "",
        "Primary semantic fields are only `current_query`, `current_page`, `dashboard_context`, and parsed `visible_conversation_history`. Historical B1 retains only its query/page C0 interface. IDs, labels, partitions, folds, actions, route signatures, writer identity, and contrast/grouping metadata are prohibited features.",
        "",
        "## Four-fold DEV cross-validation",
        "",
        f"Seed: `{DEV_CV_SEED}`. Every validation fold has 9 families and 18 utterances, preserves complete atomic components, has one CLARIFY family, has YES and NO coverage for all three capabilities, and contains all five LAD pages. Each training complement contains all eight ANSWER signatures.",
        "",
        "The optimizer uses lexicographic objectives: routing-signature balance, page balance, component-count balance, then seeded SHA-256 as the final tie-break. It does not select folds in lexical family-ID order and does not require one family of every signature per fold.",
        "",
        "## Metrics and selection",
        "",
        "The primary core metric is Macro-F1 across RAG, Memory, and Planning on ANSWER cases only. Secondary, clarification, and end-to-end metrics are frozen in `stage4_dev_protocol_v1.json`.",
        "",
        "Core configuration tie-breaks are: higher Macro-F1; higher Exact Capability Set Match; higher Jaccard; lower under-routing; lower over-routing; simpler predeclared configuration; then deterministic config ID. TEST performance is prohibited from every decision.",
        "",
        "## Synthetic stress cases",
        "",
        "The existing 35 synthetic stress cases are excluded from the primary Stage 4 calibration because they are not canonical model-input cases. Canonical fields must not be fabricated for them.",
        "",
        "## Stop boundary",
        "",
        "This Stage 4-0 freeze does not authorize model tracks, training, tuning, prompt execution, provider calls, TEST access or execution, model-performance calculation, final example selection, B1 mapping freeze, B0 rule changes, or RQ3.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def render_status() -> bytes:
    return (
        "# RQ2-V2 Stage 4-0 Status\n\n"
        f"Status: `{READY_STATUS}`\n\n"
        "The DEV-only protocol, sanitized grouping map, deterministic four-fold CV freeze, metrics, tie-breaks, leakage checks, validators, and tests are complete.\n\n"
        "No Router was trained or executed. No provider was called. No model performance was calculated. No TEST input or Gold was accessed. No TEST row or identifier, writer identity, or full restricted split assignment is retained. No RQ3 work was performed.\n\n"
        "Stop here. Parallel Stage 4 DEV model tracks require separate authorization.\n"
    ).encode("utf-8")


def build_dynamic_artifacts(
    dev_payloads: Mapping[str, bytes],
    dev_rows: Sequence[Mapping[str, str]],
    group_rows: Sequence[Mapping[str, str]],
    duplicate_pair_count: int,
) -> tuple[dict[str, bytes], FoldSolution]:
    group_artifacts = render_group_artifacts(group_rows)
    families = build_families(dev_rows, group_rows)
    solution = optimise_folds(families)
    fold_artifacts, _ledger = render_fold_artifacts(dev_rows, group_rows, solution)
    optimization_report = build_optimization_report(solution)
    family_folds = validation_family_fold_map(solution)
    protocol = build_protocol(
        group_artifacts, fold_artifacts, family_folds, optimization_report
    )
    artifacts: dict[str, bytes] = dict(dev_payloads)
    artifacts.update(group_artifacts)
    artifacts.update(fold_artifacts)
    artifacts.update(
        {
            "DEV_SOURCE_MANIFEST.json": _json_bytes(
                build_source_manifest(dev_payloads, duplicate_pair_count)
            ),
            "DEV_CV_OPTIMIZATION_REPORT.json": _json_bytes(optimization_report),
            "DEV_CV_BALANCE_REPORT.md": render_balance_report(optimization_report),
            "stage4_dev_protocol_v1.json": _json_bytes(protocol),
            "STAGE4_DEV_PROTOCOL.md": render_protocol_markdown(protocol),
            "STATUS.md": render_status(),
        }
    )
    if set(artifacts) != set(GENERATED_PROTOCOL_FILES):
        raise ProtocolBuildError("generated artifact allowlist differs")
    return artifacts, solution


def build_sha256_manifest(root: Path) -> bytes:
    actual = {
        path.name
        for path in root.iterdir()
        if path.is_file() and path.name != SHA256_MANIFEST_NAME
    }
    if actual != set(REVIEW_PAYLOAD_FILES):
        extra = sorted(actual - set(REVIEW_PAYLOAD_FILES))
        missing = sorted(set(REVIEW_PAYLOAD_FILES) - actual)
        raise ProtocolBuildError(f"protocol file allowlist differs; extra={extra}, missing={missing}")
    value = {
        "schema_version": "rq2-v2-stage4-dev-protocol-sha256-manifest-v1",
        "hash_algorithm": "SHA-256",
        "files": [
            {
                "name": name,
                "sha256": sha256_file(root / name),
                "size_bytes": (root / name).stat().st_size,
            }
            for name in REVIEW_PAYLOAD_FILES
        ],
    }
    return _json_bytes(value)


def write_protocol(
    output_dir: Path,
    dev_payloads: Mapping[str, bytes],
    dev_rows: Sequence[Mapping[str, str]],
    group_rows: Sequence[Mapping[str, str]],
    duplicate_pair_count: int,
) -> FoldSolution:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts, solution = build_dynamic_artifacts(
        dev_payloads, dev_rows, group_rows, duplicate_pair_count
    )
    for name, payload in artifacts.items():
        (output_dir / name).write_bytes(payload)
    (output_dir / SHA256_MANIFEST_NAME).write_bytes(build_sha256_manifest(output_dir))
    return solution


def rebuild_cv_artifacts_from_frozen_files(root: Path) -> tuple[dict[str, bytes], FoldSolution]:
    root = Path(root)
    with (root / "dev_capability_gold_v1.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        dev_rows = [dict(row) for row in csv.DictReader(handle)]
    validate_dev_rows(dev_rows)
    with (root / "dev_atomic_group_map_v1.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        group_rows = [dict(row) for row in csv.DictReader(handle)]
    families = build_families(dev_rows, group_rows)
    solution = optimise_folds(families)
    group_artifacts = render_group_artifacts(group_rows)
    fold_artifacts, _ledger = render_fold_artifacts(dev_rows, group_rows, solution)
    optimization_report = build_optimization_report(solution)
    protocol = build_protocol(
        group_artifacts,
        fold_artifacts,
        validation_family_fold_map(solution),
        optimization_report,
    )
    return (
        {
            **fold_artifacts,
            "DEV_CV_OPTIMIZATION_REPORT.json": _json_bytes(optimization_report),
            "DEV_CV_BALANCE_REPORT.md": render_balance_report(optimization_report),
            "stage4_dev_protocol_v1.json": _json_bytes(protocol),
            "STAGE4_DEV_PROTOCOL.md": render_protocol_markdown(protocol),
        },
        solution,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev-zip", type=Path, default=DEFAULT_DEV_ZIP)
    parser.add_argument("--stage3c-zip", type=Path, default=DEFAULT_STAGE3C_ZIP)
    parser.add_argument("--output-dir", type=Path, default=PACKAGE_ROOT)
    args = parser.parse_args(argv)

    dev_payloads, dev_rows = load_dev_release(args.dev_zip)
    group_rows, pair_count = extract_dev_group_rows(args.stage3c_zip, dev_rows)
    solution = write_protocol(
        args.output_dir, dev_payloads, dev_rows, group_rows, pair_count
    )
    print(
        "BUILT_RQ2_V2_STAGE4_DEV_PROTOCOL "
        f"objective={solution.objective} candidates={solution.candidate_count} "
        f"selection_sha256={solution.selection_sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
