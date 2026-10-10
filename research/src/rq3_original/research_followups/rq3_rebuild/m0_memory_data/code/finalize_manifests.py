"""Pre-commit provenance and output allowlist. Reads only declared inherited paths."""
import json
from pathlib import Path
import subprocess
import zipfile
from common import OWNED, SUBTREE, BASE_HEAD, sha, write_json, utc

SOURCES = [
    "utils/__init__.py", "utils/c4_memory/__init__.py",
    "utils/c4_memory/c4_memory_store.py", "utils/c4_memory/c4_memory_writer.py",
    "utils/c4_memory/c4_memory_retriever.py", "utils/c4_memory/c4_memory_provider.py",
    "utils/c4_memory/c4_memory_schema_v1.sql", "utils/c4_memory/c4_memory_contract_v1.json",
    "utils/c4_rag/corpus.py", "utils/c4_rag/retrievers.py",
    "semantic_runtime/config/semantic_routing_config.json",
    "semantic_runtime/config/semantic_router_selection_manifest_v1.json",
    "research_followups/rq3_reassessment/pipeline_rag_audit/SOURCE_MANIFEST.json",
    "evaluation/rq3_real_c4/track_m_memory/REAL_C4_MEMORY_RESULTS.md",
    "evaluation/rq3_real_c4/track_m_memory/memory_mechanism_results_v1.json",
    "evaluation/rq3_real_c4/track_m_memory/evaluate_memory_mechanism.py",
    "evaluation/rq3_real_c4/track_m_memory/tests/test_c4_memory.py",
]

def main():
    repo = OWNED.parents[2]
    def git(*args): return subprocess.check_output(["git", "-C", str(repo), *args])
    assert git("rev-parse", "HEAD").decode().strip() == BASE_HEAD
    assert git("branch", "--show-current").decode().strip() == "research/rq3-rebuild-m0-memory-data"
    assert not git("diff", "--name-only") and not git("diff", "--cached", "--name-only")
    unknown = git("ls-files", "--others", "--exclude-standard").decode().splitlines()
    assert all(p.startswith(SUBTREE + "/") for p in unknown)
    files = []
    for name in SOURCES:
        path = repo / name
        b = path.read_bytes()
        assert b == git("show", BASE_HEAD + ":" + name), "SOURCE_DRIFT:" + name
        files.append({"path": str(path), "repository_path": name, "bytes": len(b), "sha256": sha(path),
            "matches_base_commit_bytes": True,
            "use": "METADATA_SEARCH_ONLY_NOT_EXECUTED_OR_BENCHMARKED" if name.startswith("evaluation/") else
                   "PUBLIC_INTERFACE_FROZEN_CONTRACT_OR_PATH_PROVENANCE"})
    packet = Path("/Users/liuming/Downloads/RQ3_REBUILD_M0_CODEX_TASK_PACKET_2026-09-06.zip")
    with zipfile.ZipFile(packet) as z:
        assert z.testzip() is None
        prefix = z.namelist()[0].split("/")[0] + "/"
        source_manifest = json.loads(z.read(prefix + "MANIFEST.json"))
        for e in source_manifest["members"]:
            b = z.read(prefix + e["path"])
            import hashlib
            assert len(b) == e["bytes"] and hashlib.sha256(b).hexdigest() == e["sha256"]
            assert (OWNED / "task_spec" / e["path"]).read_bytes() == b
    identity = json.loads((OWNED / "diagnostics_v2/RUNTIME_IDENTITY.json").read_text())
    model_files = identity["snapshot_files"]
    for f in model_files:
        assert sha(f["path"]) == f["sha256"]
        if f["frozen_expected_sha256"] is not None: assert f["frozen_expected_sha256"] == f["sha256"]
    write_json(OWNED / "SOURCE_MANIFEST.json", {"generated_utc": utc(), "starting_head": BASE_HEAD,
        "scope": "Exact inherited interfaces/path metadata inspected; input packet; verified local snapshot file identities. No copied inherited implementation, old dataset rows or model weights.",
        "files": files, "input_packet": {"path": str(packet), "bytes": packet.stat().st_size,
            "sha256": sha(packet), "crc": "PASS", "verified_payload_members": source_manifest["members"]},
        "local_snapshot": model_files, "semantic_model_loaded": False, "loaded_model_hashes": "UNKNOWN",
        "execution_runtime": {"path": "/opt/anaconda3/bin/python3", "sha256": sha("/opt/anaconda3/bin/python3")},
        "not_accessed": ["E0/R0/P0 working directories or branch HEADs", "production or historical Memory databases",
            "credentials", "restricted identity mappings", "raw human/Judge ratings"],
        "boundary": "Old metadata search is not a new retrieval benchmark. Only new synthetic fixtures entered the owned runtime."})
    members = []
    for path in sorted(OWNED.rglob("*")):
        if not path.is_file(): continue
        relative = path.relative_to(OWNED)
        if relative.parts[0] in (".runtime", "packaging") or relative.as_posix() == "OUTPUT_MANIFEST.json": continue
        assert not path.is_symlink()
        assert path.suffix not in {".db", ".sqlite", ".pyc", ".zip"}
        members.append({"path": relative.as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)})
    write_json(OWNED / "OUTPUT_MANIFEST.json", {"generated_utc": utc(),
        "scope": "Every new owned file at pre-commit freeze except OUTPUT_MANIFEST.json itself. Excludes temporary runtime directories, post-commit packaging metadata and the ZIP. The review manifest separately covers exact committed payload bytes.",
        "members": members})
    print(json.dumps({"source_files_verified": len(files), "output_members_without_self": len(members),
                      "inherited_tracked_changes": 0, "other_untracked_paths": 0}))

if __name__ == "__main__": main()
