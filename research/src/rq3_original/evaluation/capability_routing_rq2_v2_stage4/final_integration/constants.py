"""Immutable Stage 4N identities and narrow execution-package boundaries."""

from __future__ import annotations

from pathlib import Path


INTEGRATION_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = INTEGRATION_DIR.parents[2]
STAGE4_ROOT = INTEGRATION_DIR.parent
TEST_INPUT_DIR = INTEGRATION_DIR / "test_inputs"

SOURCE_STAGE_HEAD = "a26a204a1145bb9a7fc181da2f67c73be0cab627"
SOURCE_STAGE_BRANCH = "research/rq2-v2-stage4-m-specialist-composition"
STAGE4N_BRANCH = "research/rq2-v2-stage4-n-final-integration"
PRIMARY_FEATURE_PROFILE = "R2V2_PRIMARY_SEMANTIC_INPUT_V1"
PRIMARY_FIELDS = (
    "current_query",
    "current_page",
    "dashboard_context",
    "visible_conversation_history",
)
TEST_INPUT_FIELDS = ("annotation_case_id", *PRIMARY_FIELDS)
TEST_INPUT_STATUS = "FROZEN_UNSCORED_INPUTS"
TEST_STATUS = "NOT_EXECUTED"
READY_STATUS = "READY_FOR_PARALLEL_RQ2_V2_FINAL_TEST_PREDICTION_EXECUTION"

TEST_ESCROW_ZIP = Path("/Users/liuming/Downloads/RQ2_V2_TEST_ESCROW_2026-08-31.zip")
TEST_ESCROW_ZIP_SHA256 = (
    "6a07f32d4777cb9c31a1974a96f8c9e5bb5ff498c2c2fd5254334ef297e83fdf"
)
EXPECTED_TEST_INPUT_HASHES = {
    "test_inputs_frozen_v1.csv": (
        "96e5926a1c3165d3d28378fd5302c76c43867a7a8e7e47006fd0f54d745f5b78"
    ),
    "test_inputs_frozen_v1.jsonl": (
        "284e332dab6f91051960f84a717f8742283166db587d5b544eeb894a5b907cd8"
    ),
    "TEST_ESCROW_SHA256_MANIFEST.json": (
        "086f443fcf812478400b6660dc963b60cc895ae8e018000e133751131aa1de9d"
    ),
    "FROZEN_SPLIT_SUMMARY.md": (
        "05108de9a4850799de315a868904e579be4508959e2a18d8ef16c83cec633887"
    ),
}

# These are raw-file identities from the exact Stage 4M source commit.  The
# Stage 4N builder never discovers a new baseline from current bytes.
EXPECTED_SOURCE_HASHES = {
    "evaluation/capability_routing_rq2_v2_stage4/dev_protocol/stage4_dev_protocol_v1.json": "9e4e8afa354f544d58d6d30187af194e52968df5ec21ccbdcb7f6585adb75336",
    "evaluation/capability_routing_rq2_v2_stage4/track_h_b2_b3/sanity_baseline_definitions_v1.json": "4c5d4305eabe86309ca7d2ce512d7d2d3a47bf7986e509cc7c6202da0091ef66",
    "evaluation/capability_routing_rq2_v2_stage4/track_h_b2_b3/diagnostic_audit.py": "55b658df57c67c560e5dc2a00bc12090de48e18a4b1f3702fbe967378fa4c803",
    "evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/clarification_candidate_configs_v1.json": "2fafc85335237943bb600eb7b8acb43a0facf8b26b90aec7aafdefd9acbf7b4e",
    "evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/clarification_gate.py": "ef532e656da3de775a6f33f8cee5defab8e63e2571066b517a115de1234615eb",
    "evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/clarification_gate_frozen_v1.json": "ca411f9ef8711811b3aa5408b79e28463cef432fe3fc31bf106d3fa80a350438",
    "evaluation/capability_routing_rq2_v2_stage1/track_b_b0_b1/b0_rule_router.py": "834a457cf996039a4edae4422240f25047af203a07f35d3d8036aab5f9d28c27",
    "evaluation/capability_routing_rq2_v2_stage1/track_b_b0_b1/config/b0_rules_v1.json": "84fdd1413958199106c10c4105df248e9ace7075ca6988e50c6bcdc253146f53",
    "evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/b0_frozen_config_v1.json": "6b7e8fd5beee14c35375785ae5bcbef4490404c390eaeeb666d19a94987df634",
    "evaluation/capability_routing_rq2_v2_stage1/track_b_b0_b1/b1_legacy_intent_adapter.py": "884a37cef06516d6df1e41ab5cd8316bd5e2a3ddbc999d8364e48cdbb7d0458f",
    "evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/c0_identity_frozen_v1.json": "5a05e29258b47f3ea08a42f3518d226d4bc96889bfe15b134f03ad6958cc3db0",
    "evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/b1_mapping_frozen_v1.json": "b643aeaabaafdcb665add04eabb12f2435a5c9c82262b8721906335fc4261f09",
    "evaluation/capability_routing_rq2_v2_stage1/track_c_b2_b3/canonical_text.py": "d6eaf3216d40e24c22dd4e4a9e47b49f2542460a2c763a330ee348d1c0ed219d",
    "evaluation/capability_routing_rq2_v2_stage1/track_c_b2_b3/embeddings.py": "2091e032c49d8aebcf75a3a1381d8cf8ffc2c8b0d3d87dea28975a6131b15565",
    "evaluation/capability_routing_rq2_v2_stage1/track_c_b2_b3/prototype_router.py": "abbd46ef137a1e1bb581b36a12ad8df61fc9f08e4132a424e825c6b122de6d3a",
    "evaluation/capability_routing_rq2_v2_stage1/track_c_b2_b3/ovr_router.py": "ff7f4b870cb7ae0e464a2056b722f92f50ff0f6711e2ec946f53d1da4c964e0b",
    "evaluation/capability_routing_rq2_v2_stage1/track_c_b2_b3/router_common.py": "21fc177b26fb0614224568f575dfe56f4cade1944519163acb052055e66c2875",
    "evaluation/capability_routing_rq2_v2_stage4/track_h_b2_b3/dev_embedding_identity_v1.json": "e039fe44e7eb93dda67de15469e49e7dbbc9db407132aee04653250329c80c0f",
    "evaluation/capability_routing_rq2_v2_stage4/track_h_b2_b3/b2_frozen_model_v1.json": "fec02db702dd9ce0a86934c4fe626b27944657b92241ce8e35d4cf06c3fbda17",
    "evaluation/capability_routing_rq2_v2_stage4/track_h_b2_b3/b3_frozen_model_v1.json": "256315f594687763513d7586f18b76e94e073ec87e3babec842eab9e3430eb32",
    "evaluation/capability_routing_rq2_v2_stage4/track_h_b2_b3/track_h.py": "90025880bb523fae599060e8acd6c883d7f1aac1532b5c6d0faa97e6bf56ee59",
    "evaluation/capability_routing_rq2_v2_stage4/track_i_b4/b4_prompt_template_frozen_v1.txt": "62dd0072b40f812bea9d2400bf5053c1d727187c47cab3c8777a341e0a185541",
    "evaluation/capability_routing_rq2_v2_stage4/track_i_b4/b4_response_schema_v2.json": "8017f1677e3ddc0bdd5042cff1c87e1e8ef4053da10b5c86da2cf45c35319876",
    "evaluation/capability_routing_rq2_v2_stage4/track_i_b4/b4_final_full_dev_prompt_package_v1.json": "245a4f74d2428017ab36fc5eaba41c6f617b5ec01c099153b23524a0d33734d5",
    "evaluation/capability_routing_rq2_v2_stage4/track_i_b4/b4_final_frozen_configuration_v2.json": "12a75dd33298f6e1078b326e7c922eb92f2675ee87c7f7858fdf19494072d470",
    "evaluation/capability_routing_rq2_v2_stage4/track_i_b4/b4_execution_runtime_v1.json": "bce30fa44ecdd331718fd8e8c83760beac02dc14c3e3898cde1c46c0c429c817",
    "evaluation/capability_routing_rq2_v2_stage4/track_i_b4/execute_b4_dev_r1.py": "d9b016578fd9bf13d3c07c3f00c8a39d0cc358a0223a8754a17ef9777b8853b5",
    "evaluation/capability_routing_rq2_v2_stage4/track_j_p1_protocol/p1_candidate_policies_frozen_v1.json": "33de16b95f90847f0788c50914b32fbe403b952dc216b9c4f7a43ae14c7859cd",
    "evaluation/capability_routing_rq2_v2_stage4/track_j_p1_protocol/p1_nested_selection_protocol_v1.json": "d62d9b6bceb435334effb4111d92434488b74d67f6552ea25376a5af6a23c90a",
    "evaluation/capability_routing_rq2_v2_stage4/track_j_p1_protocol/p1_final_policy_frozen_v1.json": "011f11ce244b564f87b4a555d8d0b0d4e2113bc9b77ab58c6ba2d5118d58d855",
    "evaluation/capability_routing_rq2_v2_stage4/track_j_p1_protocol/p1_protocol.py": "b2c865a0e5379b635f94787df035a4d3cb61005cdd1c450d137e17dae819729d",
    "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/rag_specialist_prompt_frozen_v1.txt": "e0e34a097ec0449e2cedfa305d43c7aad7b096ca5fb0a64dc54ad39e9c035d5c",
    "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/rag_specialist_schema_v1.json": "3a304b91bc642e8d04f59077b4f1240bf5f242105f888cfdb634ffa858901866",
    "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/rag_specialist_final_full_dev_prompt_package_v1.json": "60c5d9de78bf60c2b186c46ab3c935511c2a994bc8974a2bc965e5aa2ffc6f55",
    "evaluation/capability_routing_rq2_v2_stage4/track_k_rag_specialist_execution/rag_specialist_frozen_configuration_v1.json": "19fc104b55ed92ec6c9a988fe6664d5f062f92e473a5ff4d77f8c88aa871c7cc",
    "evaluation/capability_routing_rq2_v2_stage4/track_k_rag_specialist_execution/rag_specialist_protocol.py": "811232eff93520c2885eb38742336efa3f3d80d83a9ac771d6ff5db780eeebf3",
    "evaluation/capability_routing_rq2_v2_stage4/track_k_rag_specialist_execution/execute_rag_specialist_dev.py": "66eec4f10f211ef42c92193d80435979a52fc117c531e0a63114da4091594b22",
    "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/memory_specialist_prompt_frozen_v1.txt": "c8a53b27f16b84ef0373ddfdd20eab997cc986eab10a93a138ede06571ebab04",
    "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/memory_specialist_schema_v1.json": "41a0f015b3fd7589bd1a08bd1d3e2a7c8bd5491b22c2531ef43ead634642a3d7",
    "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/memory_specialist_final_full_dev_prompt_package_v1.json": "ba27b9ee29960d0dfe67389f685e3338ff90b4ed71b57756a0e3abe890eb6875",
    "evaluation/capability_routing_rq2_v2_stage4/track_l_memory_specialist_execution/memory_specialist_frozen_configuration_v1.json": "8813854b4a73e4c07416e26db0b72f28ab1923f415053f8d48ad31b0eca0a3c3",
    "evaluation/capability_routing_rq2_v2_stage4/track_l_memory_specialist_execution/memory_specialist_common.py": "6dc17319b34944c21d43056b007d1c0ee61ef9e820577d0093226fcd5223688a",
    "evaluation/capability_routing_rq2_v2_stage4/track_l_memory_specialist_execution/execute_memory_specialist_dev.py": "fd2fb0ee798b5db9eac9ece17ba199ab5206d8a3e9980687872c97f368161c38",
    "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/p2_rag_specialist_composition_contract_v1.json": "532bd513cc9b5f11003036ecbbc492f0305e359ae48f6cb133a05fe43d26f6ad",
    "evaluation/capability_routing_rq2_v2_stage4/track_m_specialist_composition/p2_rag_specialist_composition_frozen_v1.json": "bf31ac10f8af9532bff3f071835d3db997987fc1e0ae529525f42c65179ee3ad",
    "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/p3_capability_specialists_composition_contract_v1.json": "36e4c0589979f762568d29680a6d76b8c6116680072c051d00b2c5739e030288",
    "evaluation/capability_routing_rq2_v2_stage4/track_m_specialist_composition/p3_rag_memory_specialists_frozen_v1.json": "3a05be7546c62e24b571451a80a801338bf2beb7badc126bfe9dcd5f17255c13",
    "evaluation/capability_routing_rq2_v2_stage4/track_m_specialist_composition/p4_memory_specialist_composition_frozen_v1.json": "ed2b91b63c13c9f45a3d75820f4bff294201b5e9982750d006eb32832c1b0ce4",
    "evaluation/capability_routing_rq2_v2_stage4/track_m_specialist_composition/P4_POST_DEV_EXTENSION_DISCLOSURE.md": "069dd748739086a5df2b9c604c0fa6da404604d1195e6d14f3bba54cd49b81a0",
    "evaluation/capability_routing_rq2_v2_stage4/track_m_specialist_composition/run_stage4m.py": "f34dd143ca22a9aee8b6daab9588e077bb7c421c20494450f906aadaf2c96c31",
    "evaluation/capability_routing_rq2_v2_stage4/track_m_specialist_composition/specialist_composition_source_verification_v1.json": "a00525ead8a20fe21e90da2346bad85728071e0a1ec97139abb117a043b1aa67",
    "evaluation/capability_routing_rq2_v2_stage4/track_m_specialist_composition/STAGE4M_OUTPUT_SHA256_MANIFEST.json": "a280684fd4de1d06f459bffe054a940c5579b3acf697eab32c703dd6ca2307df",
}

C0_ROOT = Path(
    "/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3"
)
C0_SOURCE_HEAD = "ad43bd4addcb9a257690ca81e1185a6a0d1b5bb7"
MPNET_REVISION = "e8c3b32edf5434bc2275fc9bab85f82640a19130"
MPNET_ROOT = C0_ROOT / "semantic_runtime/models/all-mpnet-base-v2" / MPNET_REVISION
EXTERNAL_SOURCE_HASHES = {
    str(C0_ROOT / "semantic_runtime/artifacts/intent_index_embeddings_mpnet_base_v2_v1.npz"): "8b6fb268970c119ec58ce304e1c9ad0380e161fe086713dbf77d432b547bf9d8",
    str(C0_ROOT / "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl"): "b4cac34df91c074a4a2fa85e4ccc52623563f3358fe44938771f8303f00b6be9",
    str(C0_ROOT / "utils/production_intent_router.py"): "e3b7517a6520c35b6b4727249ed536d617b880a25cb23abe5eab020e5912c6b1",
    str(C0_ROOT / "utils/semantic_intent_router.py"): "10f64166401ac0ecbf1c4d7051420f5406754190f58ce95d3f890d6cc8d0dbe9",
    str(C0_ROOT / "semantic_runtime/config/semantic_routing_config.json"): "5d1f59587e16f03cd7640e2392fdad757731854ca9e1276de779a0050dac2220",
    str(MPNET_ROOT / "config.json"): "d46a3e04ded82bba22528424480697d394eeda6a27484e08c5bb2bdf5906cfa0",
    str(MPNET_ROOT / "model.safetensors"): "78c0197b6159d92658e319bc1d72e4c73a9a03dd03815e70e555c5ef05615658",
    str(MPNET_ROOT / "tokenizer.json"): "b8be2c30ba5dd723a6d5ee26d013da103d5408d92ddcb23747622f9e48f1d842",
}

B4_MODEL = "gpt-4o-mini-2024-07-18"
B4_PROMPT_SHA256 = "62dd0072b40f812bea9d2400bf5053c1d727187c47cab3c8777a341e0a185541"
B4_SCHEMA_SHA256 = "8017f1677e3ddc0bdd5042cff1c87e1e8ef4053da10b5c86da2cf45c35319876"
B4_EXAMPLE_SET_SHA256 = "020ec80b8b592a62c9975b47bf5bc63c9dd86c029da05a6a4afd43440291aff2"
RAG_PROMPT_SHA256 = "e0e34a097ec0449e2cedfa305d43c7aad7b096ca5fb0a64dc54ad39e9c035d5c"
RAG_SCHEMA_SHA256 = "3a304b91bc642e8d04f59077b4f1240bf5f242105f888cfdb634ffa858901866"
RAG_EXAMPLE_SET_SHA256 = "a932596e126ab66c054173bd1b9c454cbba9988e9d0b418da2d80c3e1df1e6eb"
MEMORY_PROMPT_SHA256 = "c8a53b27f16b84ef0373ddfdd20eab997cc986eab10a93a138ede06571ebab04"
MEMORY_SCHEMA_SHA256 = "41a0f015b3fd7589bd1a08bd1d3e2a7c8bd5491b22c2531ef43ead634642a3d7"
MEMORY_EXAMPLE_SET_SHA256 = "57a7aecd53710a1587388711177d7564f4560f1a8729939d445268d2514d3eb4"

DOWNLOADS_DIR = Path("/Users/liuming/Downloads")
PACKAGE_PATHS = {
    "DETERMINISTIC": DOWNLOADS_DIR
    / "RQ2_V2_FINAL_TEST_DETERMINISTIC_EXECUTION_PACKAGE_2026-08-31.zip",
    "B4": DOWNLOADS_DIR / "RQ2_V2_FINAL_TEST_B4_EXECUTION_PACKAGE_2026-08-31.zip",
    "RAG_SPECIALIST": DOWNLOADS_DIR
    / "RQ2_V2_FINAL_TEST_RAG_SPECIALIST_EXECUTION_PACKAGE_2026-08-31.zip",
    "MEMORY_SPECIALIST": DOWNLOADS_DIR
    / "RQ2_V2_FINAL_TEST_MEMORY_SPECIALIST_EXECUTION_PACKAGE_2026-08-31.zip",
    "INTERNAL_REVIEW": DOWNLOADS_DIR
    / "RQ2_V2_STAGE_4N_FINAL_INTEGRATION_REVIEW_2026-08-31.zip",
}

FORBIDDEN_TEST_FIELD_NAMES = frozenset(
    {
        "capability",
        "capabilities",
        "capability_labels",
        "dialogue_action",
        "scenario_family_id",
        "writer_id",
        "writer_identity",
        "contrast_id",
        "contrast_group_id",
        "gold",
        "gold_rag",
        "gold_memory",
        "gold_planning",
        "partition",
        "split",
        "rag_context_state",
        "memory_context_state",
    }
)

METHOD_IDS = (
    "R2V2-D0_ALWAYS_ON",
    "R2V2-D1_NEVER_ON",
    "R2V2-CG1_CLARIFICATION_RULE",
    "R2V2-B0_RULE",
    "R2V2-B1_LEGACY_INTENT",
    "R2V2-B2_PROTOTYPE",
    "R2V2-B3_OVR",
    "R2V2-B4_JOINT_LLM",
    "R2V2-P1_HYBRID",
    "R2V2-P2_RAG_SPECIALIST_COMPOSITION",
    "R2V2-P3_RAG_MEMORY_SPECIALISTS",
    "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION",
    "R2V2-RAG_SPECIALIST",
    "R2V2-MEMORY_SPECIALIST",
)

REPORTING_TIERS = {
    "TIER_0_DIAGNOSTIC": ["R2V2-D0_ALWAYS_ON", "R2V2-D1_NEVER_ON"],
    "TIER_1_ORIGINAL_PRE_SPECIFIED": [
        "R2V2-B0_RULE",
        "R2V2-B1_LEGACY_INTENT",
        "R2V2-B2_PROTOTYPE",
        "R2V2-B3_OVR",
        "R2V2-B4_JOINT_LLM",
        "R2V2-P1_HYBRID",
    ],
    "TIER_2_DEV_INFORMED_PREDECLARED_SPECIALISTS": [
        "R2V2-P2_RAG_SPECIALIST_COMPOSITION",
        "R2V2-P3_RAG_MEMORY_SPECIALISTS",
    ],
    "TIER_3_POST_DEV_EXPLORATORY": [
        "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION"
    ],
}

DETERMINISTIC_METHOD_IDS = (
    "R2V2-CG1_CLARIFICATION_RULE",
    "R2V2-D0_ALWAYS_ON",
    "R2V2-D1_NEVER_ON",
    "R2V2-B0_RULE",
    "R2V2-B1_LEGACY_INTENT",
    "R2V2-B2_PROTOTYPE",
    "R2V2-B3_OVR",
)

PROVIDER_STREAMS = {
    "B4": {
        "method_id": "R2V2-B4_JOINT_LLM",
        "manifest": "b4_test_execution_manifest_v1.jsonl",
        "logical_prefix": "R2V2-B4-TEST",
        "prompt_package": "evaluation/capability_routing_rq2_v2_stage4/track_i_b4/b4_final_full_dev_prompt_package_v1.json",
        "configuration": "evaluation/capability_routing_rq2_v2_stage4/track_i_b4/b4_final_frozen_configuration_v2.json",
        "schema": "evaluation/capability_routing_rq2_v2_stage4/track_i_b4/b4_response_schema_v2.json",
        "prompt_sha256": B4_PROMPT_SHA256,
        "schema_sha256": B4_SCHEMA_SHA256,
        "example_set_sha256": B4_EXAMPLE_SET_SHA256,
        "max_output_tokens": 64,
        "schema_name": "rq2_v2_b4_capability_route_v1",
    },
    "RAG_SPECIALIST": {
        "method_id": "R2V2-RAG_SPECIALIST",
        "manifest": "rag_specialist_test_execution_manifest_v1.jsonl",
        "logical_prefix": "R2V2-RAG-SPECIALIST-TEST",
        "prompt_package": "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/rag_specialist_final_full_dev_prompt_package_v1.json",
        "configuration": "evaluation/capability_routing_rq2_v2_stage4/track_k_rag_specialist_execution/rag_specialist_frozen_configuration_v1.json",
        "schema": "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/rag_specialist_schema_v1.json",
        "prompt_sha256": RAG_PROMPT_SHA256,
        "schema_sha256": RAG_SCHEMA_SHA256,
        "example_set_sha256": RAG_EXAMPLE_SET_SHA256,
        "max_output_tokens": 32,
        "schema_name": "rq2_v2_rag_specialist_v1",
    },
    "MEMORY_SPECIALIST": {
        "method_id": "R2V2-MEMORY_SPECIALIST",
        "manifest": "memory_specialist_test_execution_manifest_v1.jsonl",
        "logical_prefix": "R2V2-MEMORY-SPECIALIST-TEST",
        "prompt_package": "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/memory_specialist_final_full_dev_prompt_package_v1.json",
        "configuration": "evaluation/capability_routing_rq2_v2_stage4/track_l_memory_specialist_execution/memory_specialist_frozen_configuration_v1.json",
        "schema": "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/memory_specialist_schema_v1.json",
        "prompt_sha256": MEMORY_PROMPT_SHA256,
        "schema_sha256": MEMORY_SCHEMA_SHA256,
        "example_set_sha256": MEMORY_EXAMPLE_SET_SHA256,
        "max_output_tokens": 32,
        "schema_name": "rq2_v2_memory_specialist_v1",
    },
}
