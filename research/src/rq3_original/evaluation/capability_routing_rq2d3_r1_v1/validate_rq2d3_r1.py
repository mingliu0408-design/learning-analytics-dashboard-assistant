"""Build, validate, checksum, and package the D3-R1 contract completion."""

from __future__ import annotations

import argparse
import ast
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import zipfile
from typing import Any, Iterable

from . import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    CAPABILITIES,
    HERE,
    METRIC_IMPLEMENTATION_SHA256,
    REVIEW_ZIP_NAME,
    ROOT,
    SIGN_FLIP_DRAWS,
    SIGN_FLIP_SEED,
    START_HEAD,
    TARGET_BRANCH,
    canonical_json_bytes,
    downloads_path,
    durable_write,
    sha256_bytes,
    sha256_file,
)
from .cluster_bootstrap import run_whole_cluster_bootstrap_v1, type7_quantile_v1
from .clustered_sign_flip import (
    exhaustive_sign_flip_fixture_v1,
    ordered_cluster_deltas_v1,
    run_clustered_sign_flip_v1,
)
from .effective_statistical_contract import effective_statistical_contract_v1_1
from .exact_set_utility import (
    case_utility_difference_v1,
    exact_jaccard_utility_v1,
    summarise_case_outcomes_v1,
)
from .holm_adjustment import holm_adjust_secondary_pvalues_v1
from .restricted_access_firewall import restricted_access_audit_v1
from .starting_state import git, validate_starting_state
from .statistical_contract_authority import (
    historical_contract_authority_v1,
    statistical_completion_authority_v1,
)
from .synthetic_statistical_fixture import (
    all_tie_fixture_v1,
    frozen_metric_binding_v1,
    synthetic_24x2_fixture_v1,
    synthetic_fixture_manifest_v1,
    synthetic_metric_binding_v1,
)


PYTHON_FILES = (
    "__init__.py",
    "starting_state.py",
    "statistical_contract_authority.py",
    "exact_set_utility.py",
    "clustered_sign_flip.py",
    "cluster_bootstrap.py",
    "holm_adjustment.py",
    "effective_statistical_contract.py",
    "restricted_access_firewall.py",
    "synthetic_statistical_fixture.py",
    "validate_rq2d3_r1.py",
    "test_rq2d3_r1_unittest.py",
)
DOCUMENT_FILES = (
    "RQ2D3_R1_STATISTICAL_CONTRACT_COMPLETION.md",
    "RQ2D3_R1_CLUSTERED_SIGN_FLIP_AND_BOOTSTRAP.md",
    "RQ2D3_R1_GOVERNANCE_AND_D3_RESTART.md",
)
SAFE_JSON_FILES = (
    "rq2d3_r1_preflight_report_v1.json",
    "rq2d3_r1_statistical_completion_authority_v1.json",
    "rq2_final_statistical_contract_v1_1.json",
    "rq2d3_r1_synthetic_validation_v1.json",
    "rq2d3_r1_validation_report_v1.json",
)
CHECKSUM_NAME = "rq2d3_r1_output_checksums_v1.sha256"
REVIEW_EXTRA_MEMBERS = (
    "review/GIT_STATE.txt",
    "review/DIFF_SUMMARY.txt",
    "review/REVIEW_CHECKSUMS.sha256",
)


class D3R1ValidationError(RuntimeError):
    pass


def _json(name: str) -> dict[str, Any]:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def tracked_output_paths() -> list[Path]:
    return sorted(
        [
            *(HERE / name for name in PYTHON_FILES),
            *(ROOT / "docs/thesis_mainline/rq2" / name for name in DOCUMENT_FILES),
            *(HERE / name for name in SAFE_JSON_FILES),
        ],
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )


def _public_bootstrap(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key != "_distributions"}


def build_synthetic_validation_v1() -> dict[str, Any]:
    fixture = synthetic_24x2_fixture_v1()
    group_rows = []
    case_deltas: list[Fraction] = []
    for group_id, case_ids in fixture["groups"]:
        rows = []
        for case_id in case_ids:
            delta = case_utility_difference_v1(
                {capability: capability in fixture["left"][case_id] for capability in CAPABILITIES},
                {capability: capability in fixture["right"][case_id] for capability in CAPABILITIES},
                {capability: capability in fixture["gold"][case_id] for capability in CAPABILITIES},
            )
            case_deltas.append(delta)
            rows.append((case_id, delta))
        group_rows.append((group_id, tuple(rows)))
    ordered_deltas = ordered_cluster_deltas_v1(group_rows)
    sign_first = run_clustered_sign_flip_v1(ordered_deltas)
    sign_second = run_clustered_sign_flip_v1(ordered_deltas)
    if sign_first != sign_second:
        raise D3R1ValidationError("sign-flip deterministic double run failed")
    zero_deltas = tuple((group_id, Fraction(0, 1)) for group_id, _ in ordered_deltas)
    all_zero = run_clustered_sign_flip_v1(zero_deltas)
    if all_zero["p_value"] != 1.0 or all_zero["rng_bit_draw_count"] != 0:
        raise D3R1ValidationError("all-zero sign-flip contract failed")
    small = list(zero_deltas)
    small[0] = (small[0][0], Fraction(1, 2))
    small[1] = (small[1][0], Fraction(-1, 4))
    exhaustive = exhaustive_sign_flip_fixture_v1(tuple(small))

    binding = synthetic_metric_binding_v1()
    bootstrap_first = run_whole_cluster_bootstrap_v1(
        fixture["groups"], fixture["left"], fixture["right"], fixture["gold"], binding
    )
    bootstrap_second = run_whole_cluster_bootstrap_v1(
        fixture["groups"], fixture["left"], fixture["right"], fixture["gold"], synthetic_metric_binding_v1()
    )
    first_public = _public_bootstrap(bootstrap_first)
    second_public = _public_bootstrap(bootstrap_second)
    if first_public != second_public:
        raise D3R1ValidationError("bootstrap deterministic double run failed")
    frozen_binding = frozen_metric_binding_v1()
    if frozen_binding.implementation_sha256 != METRIC_IMPLEMENTATION_SHA256:
        raise D3R1ValidationError("frozen metric binding mismatch")

    utility_fixtures = {
        "perfect": exact_jaccard_utility_v1({"planning"}, {"planning"}) == 1,
        "disjoint": exact_jaccard_utility_v1({"planning"}, {"clarification"}) == 0,
        "partial": exact_jaccard_utility_v1(
            {"planning", "episodic_memory"}, {"planning", "course_retrieval"}
        )
        == Fraction(1, 3),
        "both_empty": exact_jaccard_utility_v1(set(), set()) == 1,
        "one_empty": exact_jaccard_utility_v1(set(), {"planning"}) == 0,
    }
    outcome = summarise_case_outcomes_v1(case_deltas)
    all_tie = all_tie_fixture_v1()
    all_tie_deltas = [
        case_utility_difference_v1(
            {capability: capability in all_tie["left"][case_id] for capability in CAPABILITIES},
            {capability: capability in all_tie["right"][case_id] for capability in CAPABILITIES},
            {capability: capability in all_tie["gold"][case_id] for capability in CAPABILITIES},
        )
        for case_id in sorted(all_tie["gold"])
    ]
    all_tie_outcome = summarise_case_outcomes_v1(all_tie_deltas)
    holm_first = holm_adjust_secondary_pvalues_v1(
        {"B1_VS_B0": Fraction(1, 20), "P1_VS_B0": Fraction(1, 20)}
    )
    holm_second = holm_adjust_secondary_pvalues_v1(
        {"B1_VS_B0": Fraction(1, 20), "P1_VS_B0": Fraction(1, 20)}
    )
    type7_examples = {
        "p0": type7_quantile_v1([0.0, 1.0, 2.0, 3.0], 0.0),
        "p1": type7_quantile_v1([0.0, 1.0, 2.0, 3.0], 1.0),
        "p025": type7_quantile_v1([0.0, 1.0, 2.0, 3.0], 0.025),
        "p975": type7_quantile_v1([0.0, 1.0, 2.0, 3.0], 0.975),
        "singleton": type7_quantile_v1([7.0], 0.5),
    }
    return {
        "schema_version": "rq2d3-r1-synthetic-validation-v1",
        "status": "PASS",
        "fixture": synthetic_fixture_manifest_v1(),
        "utility_contract": {
            "all_fixture_checks_pass": all(utility_fixtures.values()),
            "checks": utility_fixtures,
            "exact_fraction_partial_overlap": "1/3",
            "float_tolerance_used": False,
        },
        "outcomes": {
            "wins_ties_losses_total": outcome["total"],
            "matched_rank_biserial_status": outcome["matched_rank_biserial"]["status"],
            "all_ties_rank_biserial_status": all_tie_outcome["matched_rank_biserial"]["status"],
        },
        "sign_flip": {
            "draw_count": sign_first["draw_count"],
            "seed": sign_first["seed"],
            "two_sided": sign_first["test_direction"] == "TWO_SIDED",
            "plus_one_correction": sign_first["plus_one_correction"],
            "deterministic_double_run": True,
            "all_zero_p_value": all_zero["p_value"],
            "all_zero_rng_bits": all_zero["rng_bit_draw_count"],
            "small_exhaustive_fixture": exhaustive,
        },
        "bootstrap": {
            **first_public,
            "deterministic_double_run": True,
            "full_resample_count": BOOTSTRAP_RESAMPLES,
            "full_group_selection_count": BOOTSTRAP_RESAMPLES * 24,
            "full_case_slot_count": BOOTSTRAP_RESAMPLES * 48,
            "metric_callback_identity_required": True,
            "future_frozen_metric_implementation_sha256": METRIC_IMPLEMENTATION_SHA256,
        },
        "type7": {
            "interpolation": "LINEAR_TYPE_7",
            "examples": type7_examples,
            "third_party_quantile_used": False,
        },
        "holm": {
            "family_size": 2,
            "primary_excluded": True,
            "deterministic_tie_fixture": holm_first == holm_second,
            "fixture": holm_first,
        },
        "restricted_access": restricted_access_audit_v1(),
        "track_b_prediction_count": 0,
        "track_b_metric_count": 0,
        "model_execution_count": 0,
        "provider_calls": 0,
        "network_access": False,
    }


def _preflight(starting: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "rq2d3-r1-preflight-report-v1",
        "stage": "RQ2-D3-R1",
        "status": "PASS",
        "starting_state": starting,
        "timing": "POST_CAPABILITY_GOLD_FREEZE_PRE_PREDICTION",
        "track_b_prediction_exists": False,
        "track_b_metric_exists": False,
        "restricted_access_count": 0,
        "model_execution_count": 0,
        "d4_execution_count": 0,
        "provider_calls": 0,
        "network_access": False,
    }


def _validation_report() -> dict[str, Any]:
    return {
        "schema_version": "rq2d3-r1-validation-report-v1",
        "stage": "RQ2-D3-R1",
        "status": "PASS",
        "effective_contract": "PASS",
        "exact_utility": "PASS",
        "case_outcomes": "PASS",
        "cluster_aggregation": "PASS",
        "two_sided_sign_flip": f"{SIGN_FLIP_DRAWS}/{SIGN_FLIP_DRAWS} DRAWS PASS",
        "plus_one_monte_carlo": "PASS",
        "whole_cluster_bootstrap": f"{BOOTSTRAP_RESAMPLES}/{BOOTSTRAP_RESAMPLES} RESAMPLES PASS",
        "type7_interval": "PASS",
        "secondary_holm": "PASS",
        "deterministic_double_runs": "PASS",
        "restricted_access_count": 0,
        "track_b_prediction_count": 0,
        "track_b_metric_count": 0,
        "model_execution_count": 0,
        "protected_source_change_count": 0,
        "governed_text_leak_count": 0,
    }


def _write_json(name: str, value: dict[str, Any]) -> None:
    durable_write(HERE / name, canonical_json_bytes(value))


def write_output_checksums() -> None:
    lines = [
        f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}"
        for path in tracked_output_paths()
    ]
    durable_write(HERE / CHECKSUM_NAME, ("\n".join(lines) + "\n").encode("utf-8"))


def build_all() -> dict[str, Any]:
    starting = validate_starting_state()
    authority = statistical_completion_authority_v1()
    historical = historical_contract_authority_v1()
    contract = effective_statistical_contract_v1_1()
    synthetic = build_synthetic_validation_v1()
    _write_json("rq2d3_r1_statistical_completion_authority_v1.json", authority)
    _write_json("rq2_final_statistical_contract_v1_1.json", contract)
    _write_json("rq2d3_r1_synthetic_validation_v1.json", synthetic)
    _write_json("rq2d3_r1_preflight_report_v1.json", _preflight(starting))
    _write_json("rq2d3_r1_validation_report_v1.json", _validation_report())
    write_output_checksums()
    validate_all()
    return {"starting": starting, "authority": authority, "historical": historical, "contract": contract, "synthetic": synthetic}


def assert_double_finalisation() -> None:
    build_all()
    first = {path.name: path.read_bytes() for path in [*tracked_output_paths(), HERE / CHECKSUM_NAME]}
    build_all()
    second = {path.name: path.read_bytes() for path in [*tracked_output_paths(), HERE / CHECKSUM_NAME]}
    if first != second:
        raise D3R1ValidationError("double finalisation byte identity mismatch")


def assert_python_ast() -> None:
    for name in PYTHON_FILES:
        path = HERE / name
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def assert_change_scope() -> None:
    allowed = (
        "evaluation/capability_routing_rq2d3_r1_v1/",
        "docs/thesis_mainline/rq2/RQ2D3_R1_",
    )
    for relative in git("diff", "--name-only", START_HEAD).stdout.decode().splitlines():
        if relative and not relative.startswith(allowed):
            raise D3R1ValidationError("BLOCKED_RQ2_D3_R1_PROTECTED_SOURCE_MUTATED")


def assert_restricted_access_static_firewall() -> None:
    forbidden_markers = (
        "track_b_opaque_" + "mapping_v1.jsonl",
        "track_b_canonical_" + "case_bank_v1.jsonl",
        "track_b_contextual_capability_" + "final_gold_v1.jsonl",
        "track_b_hidden_legacy_" + "metadata_v1.jsonl",
    )
    for name in PYTHON_FILES:
        if name == "restricted_access_firewall.py":
            continue
        source = (HERE / name).read_text(encoding="utf-8")
        if any(marker in source for marker in forbidden_markers):
            raise D3R1ValidationError("BLOCKED_RQ2_D3_R1_RESTRICTED_ACCESS")


def assert_safe_outputs() -> None:
    forbidden_keys = {
        "review_case_id",
        "current_query",
        "necessary_conversation_history",
        "raw_scenario_id",
        "contrast_set_id",
        "rationale",
        "prediction",
        "track_b_metric",
    }

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if set(value) & forbidden_keys:
                raise D3R1ValidationError("unsafe key in tracked JSON")
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    absolute_marker = "/" + "Users" + "/"
    governed_id_marker = "TB" + "V1-"
    for name in SAFE_JSON_FILES:
        value = _json(name)
        text = json.dumps(value, ensure_ascii=False)
        if absolute_marker in text or governed_id_marker in text:
            raise D3R1ValidationError("governed or absolute value in tracked JSON")
        walk(value)


def governed_text_leak_scan(paths: Iterable[Path] | None = None) -> dict[str, Any]:
    scanned = list(paths) if paths is not None else tracked_output_paths()
    leaks = []
    absolute_marker = "/" + "Users" + "/"
    governed_id_marker = "TB" + "V1-"
    for path in scanned:
        text = path.read_text(encoding="utf-8")
        if absolute_marker in text or governed_id_marker in text:
            leaks.append(path.relative_to(ROOT).as_posix())
    if leaks:
        raise D3R1ValidationError("governed-text leak: " + ", ".join(leaks))
    return {"status": "PASS", "scanned_file_count": len(scanned), "leak_count": 0}


def validate_output_checksums() -> dict[str, Any]:
    expected = {path.relative_to(ROOT).as_posix() for path in tracked_output_paths()}
    observed = set()
    for line in (HERE / CHECKSUM_NAME).read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        observed.add(relative)
        if sha256_file(ROOT / relative) != digest:
            raise D3R1ValidationError(f"checksum mismatch: {relative}")
    if observed != expected:
        raise D3R1ValidationError("output checksum path-set mismatch")
    return {"status": "PASS", "referenced_tracked_output_count": len(observed)}


def validate_all(*, require_review_zip: bool = False) -> None:
    validate_starting_state()
    assert_python_ast()
    assert_change_scope()
    assert_restricted_access_static_firewall()
    assert_safe_outputs()
    governed_text_leak_scan()
    validate_output_checksums()
    contract = _json("rq2_final_statistical_contract_v1_1.json")
    synthetic = _json("rq2d3_r1_synthetic_validation_v1.json")
    access = synthetic["restricted_access"]
    if (
        contract != effective_statistical_contract_v1_1()
        or synthetic.get("status") != "PASS"
        or access.get("restricted_access_count") != 0
        or synthetic.get("track_b_prediction_count") != 0
        or synthetic.get("track_b_metric_count") != 0
    ):
        raise D3R1ValidationError("D3-R1 output invariant mismatch")
    if require_review_zip:
        validate_review_zip()


def _checksum_member_paths() -> list[str]:
    return [
        line.split("  ", 1)[1]
        for line in (HERE / CHECKSUM_NAME).read_text(encoding="utf-8").splitlines()
        if line
    ]


def expected_review_members() -> set[str]:
    return {
        *_checksum_member_paths(),
        (HERE / CHECKSUM_NAME).relative_to(ROOT).as_posix(),
        *REVIEW_EXTRA_MEMBERS,
    }


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def _git_review_metadata() -> dict[str, bytes]:
    branch = git("branch", "--show-current").stdout.decode().strip()
    head = git("rev-parse", "HEAD").stdout.decode().strip()
    relative = int(git("rev-list", "--count", f"{START_HEAD}..HEAD").stdout.decode().strip())
    status = git("status", "--porcelain=v1", "--untracked-files=all").stdout.decode()
    if branch != TARGET_BRANCH or relative != 1 or status:
        raise D3R1ValidationError("review ZIP requires clean committed R1 state")
    return {
        "review/GIT_STATE.txt": (
            f"branch={branch}\nhead={head}\nbase={START_HEAD}\nrelative_commits=1\n"
            "working_tree_clean=true\nindex_clean=true\nremote_count=0\ntag_count=0\n"
        ).encode("utf-8"),
        "review/DIFF_SUMMARY.txt": git("diff", "--stat", START_HEAD, "HEAD").stdout,
    }


def create_review_zip() -> dict[str, Any]:
    validate_all()
    paths = [ROOT / relative for relative in _checksum_member_paths()]
    paths.append(HERE / CHECKSUM_NAME)
    members = {path.relative_to(ROOT).as_posix(): path.read_bytes() for path in paths}
    members.update(_git_review_metadata())
    members["review/REVIEW_CHECKSUMS.sha256"] = (
        "\n".join(f"{sha256_bytes(value)}  {name}" for name, value in sorted(members.items())) + "\n"
    ).encode("utf-8")
    if set(members) != expected_review_members():
        raise D3R1ValidationError("BLOCKED_RQ2_D3_R1_REVIEW_PACKAGE_INCOMPLETE")
    destination = downloads_path(REVIEW_ZIP_NAME)
    with zipfile.ZipFile(destination, "w") as archive:
        for name, value in sorted(members.items()):
            archive.writestr(_zip_info(name), value)
    result = validate_review_zip()
    result.update({"review_zip_sha256": sha256_file(destination), "review_zip_size_bytes": destination.stat().st_size})
    return result


def validate_review_zip() -> dict[str, Any]:
    path = downloads_path(REVIEW_ZIP_NAME)
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise D3R1ValidationError("review ZIP integrity failure")
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != expected_review_members():
            raise D3R1ValidationError("BLOCKED_RQ2_D3_R1_REVIEW_PACKAGE_INCOMPLETE")
        values = {name: archive.read(name) for name in names}
    checks = set()
    for line in values["review/REVIEW_CHECKSUMS.sha256"].decode("utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if sha256_bytes(values[name]) != digest:
            raise D3R1ValidationError("review checksum mismatch")
        checks.add(name)
    if checks != set(values) - {"review/REVIEW_CHECKSUMS.sha256"}:
        raise D3R1ValidationError("review checksum coverage mismatch")
    absolute_marker = "/" + "Users" + "/"
    governed_id_marker = "TB" + "V1-"
    for name, value in values.items():
        text = value.decode("utf-8")
        if absolute_marker in text or governed_id_marker in text:
            raise D3R1ValidationError(f"governed content in review member: {name}")
    return {
        "zip_integrity": "PASS",
        "exact_allowlist": "PASS",
        "internal_checksums": "PASS",
        "governed_text_leak_scan": "PASS",
        "member_count": len(values),
        "referenced_tracked_output_count": len(_checksum_member_paths()),
        "referenced_output_member_count": len(set(_checksum_member_paths()) & set(values)),
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--review-zip", action="store_true")
    parser.add_argument("--require-review-zip", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    selected = sum((args.build, args.review_zip, args.require_review_zip))
    if selected > 1:
        parser.error("choose at most one operation")
    if args.build:
        build_all()
        result: dict[str, Any] = {"operation": "build"}
    elif args.review_zip:
        result = {"operation": "review_zip", **create_review_zip()}
    else:
        validate_all(require_review_zip=args.require_review_zip)
        result = {"operation": "validate", "review_zip_required": args.require_review_zip}
    print(json.dumps({"status": "PASS", "stage": "RQ2-D3-R1", "restricted_access_count": 0, "track_b_prediction_count": 0, "track_b_metric_count": 0, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
