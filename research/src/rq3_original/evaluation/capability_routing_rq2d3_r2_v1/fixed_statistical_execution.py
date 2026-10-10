"""Non-overridable binding of real inputs to the frozen D3-R1 procedures."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping, Sequence

from evaluation.capability_routing_rq2d3_r1_v1.cluster_bootstrap import run_whole_cluster_bootstrap_v1
from evaluation.capability_routing_rq2d3_r1_v1.clustered_sign_flip import ordered_cluster_deltas_v1, run_clustered_sign_flip_v1
from evaluation.capability_routing_rq2d3_r1_v1.exact_set_utility import exact_jaccard_utility_v1, summarise_case_outcomes_v1
from evaluation.capability_routing_rq2d3_r1_v1.holm_adjustment import holm_adjust_secondary_pvalues_v1

from . import COMPARISONS, EFFECTIVE_STATISTICAL_CONTRACT_RELATIVE, EFFECTIVE_STATISTICAL_CONTRACT_SHA256, PRIMARY_COMPARISON, ROOT, SECONDARY_COMPARISONS, sha256_file
from .frozen_metric_binding import load_frozen_track_b_metric_binding_v1, load_synthetic_metric_binding_v1


FROZEN_D3_R1_MODULES = {
    Path("evaluation/capability_routing_rq2d3_r1_v1/exact_set_utility.py"): "3e67e9bfce15ee3cb671f028afa7ca0ceed2787aaf7bb1cb9060106bdadeda3b",
    Path("evaluation/capability_routing_rq2d3_r1_v1/clustered_sign_flip.py"): "87ac43d86a93d59ce23202a50dd1401c231e1663bcfd42487d11ff3344f37dcf",
    Path("evaluation/capability_routing_rq2d3_r1_v1/cluster_bootstrap.py"): "632b8045cad098dd74a00f4a4cb45205c394586003f4796d8de851df2fd405b6",
    Path("evaluation/capability_routing_rq2d3_r1_v1/holm_adjustment.py"): "59f06fb914aab619b9dc503d4177ca7e34a28f2358313ce252780a4277fbfec8",
}


def verify_frozen_statistical_sources_v1() -> dict[str, str]:
    identities = dict(FROZEN_D3_R1_MODULES)
    identities[EFFECTIVE_STATISTICAL_CONTRACT_RELATIVE] = EFFECTIVE_STATISTICAL_CONTRACT_SHA256
    for relative_path, expected in identities.items():
        path = ROOT / relative_path
        if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
            raise RuntimeError("BLOCKED_RQ2_D3_R2_STATISTICAL_BINDING")
    return {str(path): value for path, value in identities.items()}


def _run_statistics(
    ordered_groups: Sequence[tuple[str, tuple[str, str]]],
    predictions_by_method: Mapping[str, Mapping[str, frozenset[str]]],
    gold_by_id: Mapping[str, frozenset[str]],
    *,
    synthetic: bool,
) -> dict[str, Any]:
    verify_frozen_statistical_sources_v1()
    binding = load_synthetic_metric_binding_v1() if synthetic else load_frozen_track_b_metric_binding_v1()
    case_ids = {case_id for _, cases in ordered_groups for case_id in cases}
    if len(ordered_groups) != 24 or len(case_ids) != 48 or set(predictions_by_method) != {"B0", "B1", "P1"}:
        raise ValueError("fixed statistics require B0/B1/P1 over 24 x 2 cases")
    if set(gold_by_id) != case_ids or any(set(rows) != case_ids for rows in predictions_by_method.values()):
        raise ValueError("fixed statistics identity mismatch")
    comparison_results: dict[str, Any] = {}
    for comparison in COMPARISONS:
        left, right = comparison.split("_VS_")
        deltas = {
            case_id: exact_jaccard_utility_v1(predictions_by_method[left][case_id], gold_by_id[case_id])
            - exact_jaccard_utility_v1(predictions_by_method[right][case_id], gold_by_id[case_id])
            for case_id in case_ids
        }
        clustered = ordered_cluster_deltas_v1(
            (group_id, tuple((case_id, deltas[case_id]) for case_id in cases))
            for group_id, cases in ordered_groups
        )
        sign_flip = run_clustered_sign_flip_v1(clustered)
        bootstrap = run_whole_cluster_bootstrap_v1(
            ordered_groups,
            predictions_by_method[left],
            predictions_by_method[right],
            gold_by_id,
            binding,
        )
        bootstrap.pop("_distributions", None)
        comparison_results[comparison] = {
            "wins_ties_losses": summarise_case_outcomes_v1(deltas.values()),
            "clustered_sign_flip": sign_flip,
            "whole_cluster_bootstrap": bootstrap,
        }
    secondary_raw = {
        comparison: Fraction(
            comparison_results[comparison]["clustered_sign_flip"]["p_numerator"],
            comparison_results[comparison]["clustered_sign_flip"]["p_denominator"],
        )
        for comparison in SECONDARY_COMPARISONS
    }
    return {
        "contract_id": "RQ2_TRACK_B_FIXED_PRIMARY_AND_SECONDARY_STATISTICS_V1",
        "effective_statistical_contract_sha256": EFFECTIVE_STATISTICAL_CONTRACT_SHA256,
        "synthetic_test_only": synthetic,
        "comparisons": comparison_results,
        "primary": {"comparison": PRIMARY_COMPARISON, "p_value_adjustment": "UNADJUSTED"},
        "secondary_holm": holm_adjust_secondary_pvalues_v1(secondary_raw),
        "fixed_draws": 100000,
        "fixed_sign_flip_seed": 20260829,
        "fixed_resamples": 50000,
        "fixed_bootstrap_seed": 20260828,
        "type7": True,
    }


def run_fixed_primary_and_secondary_statistics_v1(
    *,
    ordered_groups: Sequence[tuple[str, tuple[str, str]]],
    predictions_by_method: Mapping[str, Mapping[str, frozenset[str]]],
    gold_by_id: Mapping[str, frozenset[str]],
) -> dict[str, Any]:
    """Real entry: no callback, metric, seed, draw, or resample override."""

    return _run_statistics(ordered_groups, predictions_by_method, gold_by_id, synthetic=False)


def run_fixed_synthetic_statistics_v1(
    *,
    ordered_groups: Sequence[tuple[str, tuple[str, str]]],
    predictions_by_method: Mapping[str, Mapping[str, frozenset[str]]],
    gold_by_id: Mapping[str, frozenset[str]],
) -> dict[str, Any]:
    return _run_statistics(ordered_groups, predictions_by_method, gold_by_id, synthetic=True)


def fixed_statistical_execution_contract_document_v1() -> dict[str, Any]:
    return {
        "schema_version": "track-b-fixed-statistical-execution-contract-v1",
        "status": "FROZEN",
        "real_interface": "run_fixed_primary_and_secondary_statistics_v1(*, ordered_groups, predictions_by_method, gold_by_id)",
        "effective_contract_sha256": EFFECTIVE_STATISTICAL_CONTRACT_SHA256,
        "frozen_source_sha256": verify_frozen_statistical_sources_v1(),
        "cluster_count": 24,
        "cases_per_group": 2,
        "sign_flip_draws": 100000,
        "sign_flip_seed": 20260829,
        "bootstrap_resamples": 50000,
        "bootstrap_seed": 20260828,
        "quantile": "LINEAR_TYPE_7",
        "primary": PRIMARY_COMPARISON,
        "secondary": list(SECONDARY_COMPARISONS),
        "caller_overridable_parameters": [],
        "real_and_synthetic_factories_separate": True,
    }
