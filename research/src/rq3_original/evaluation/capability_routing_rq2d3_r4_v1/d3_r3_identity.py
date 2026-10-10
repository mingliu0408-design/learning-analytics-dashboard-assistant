"""D3-R3 frozen identities and authorised legacy-entry mutation scope."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import ROOT, START_HEAD, sha256_file


AUTHORISED_LEGACY_FILES = {
    "evaluation/capability_routing_rq2d3_r3_v1/effective_d4_contract_v1_1.py": {
        "before_sha256": "cf12384c0f311953ee826439aa84be81eef52536d2276521a113e9e03705fc29",
        "function_names": ["execute_real_rq2d4_one_shot_v1_1"],
    },
    "evaluation/capability_routing_rq2d3_r3_v1/global_lock_receipt_v1_1.py": {
        "before_sha256": "739cbdccf3f6995c230e3f155f1818ac1721bd53bd123c2d5346dbafbedbc535",
        "function_names": ["locked_update_v1_1"],
    },
    "evaluation/capability_routing_rq2d3_r3_v1/track_b_feature_extractor_worker_v1_1.py": {
        "before_sha256": "ebb7f3ea204de47690237fe61576aae84cf2c2a3fea27c2dbde8dda6c34ee66c",
        "function_names": ["run_feature_extractor_worker_v1_1"],
    },
    "evaluation/capability_routing_rq2d3_r3_v1/track_b_predictor_worker_v1_1.py": {
        "before_sha256": "5fb5a7cc394d2d6268fd00ad7cda483bf14b9180a96816aa092c3f59c87115c0",
        "function_names": ["run_predictor_worker_v1_1"],
    },
    "evaluation/capability_routing_rq2d3_r3_v1/track_b_metric_worker_v1_1.py": {
        "before_sha256": "1733d3684e14152622f7c479e82ca456c2e5e0b973287f39e88ed448a405b046",
        "function_names": ["run_metric_worker_v1_1"],
    },
    "evaluation/capability_routing_rq2d3_r3_v1/worker_execution_authority_v1_1.py": {
        "before_sha256": "1b34c32a99070543eefeef6c7acc61a1e156b828db914fa3393b4186423a43c2",
        "function_names": ["issue_worker_credential_v1_1"],
    },
}


def d3_r3_identity_document_v1() -> dict[str, Any]:
    return {
        "schema_version": "d3-r3-frozen-identity-v1",
        "frozen_head": START_HEAD,
        "output_checksum_manifest_sha256": "5bd6958120a2cb8a3d70c2b750eb3c1755471d6820d864c9195eede77f30ee6c",
        "output_checksum_count": 53,
        "safe_outputs_changed": False,
        "development_parity_changed": False,
        "authorised_legacy_entry_file_count": len(AUTHORISED_LEGACY_FILES),
        "authorised_legacy_entry_files": [
            {
                "relative_path": relative,
                **metadata,
                "after_sha256": sha256_file(ROOT / relative),
            }
            for relative, metadata in sorted(AUTHORISED_LEGACY_FILES.items())
        ],
    }
