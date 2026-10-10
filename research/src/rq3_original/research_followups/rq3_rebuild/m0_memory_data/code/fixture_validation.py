"""Standalone review checks: no inherited repository or ML packages required."""
import json
from common import FLAGS, OWNED, sha

FORBIDDEN_RUNTIME = {"expected_fact_ids", "expected_constraints", "required_memory_fact_ids",
    "expected_active_authorized_fact_ids", "expected_stored_fact_ids", "human_review", "source_class",
    "persistent_retrieval_needed", "expected_outcomes", "split", "clarification_required"}

def assert_runtime_separation(value):
    if isinstance(value, dict):
        assert not (set(value) & FORBIDDEN_RUNTIME), "EVALUATION_FIELD_IN_RUNTIME"
        for v in value.values(): assert_runtime_separation(v)
    elif isinstance(value, list):
        for v in value: assert_runtime_separation(v)

def validate_fixtures(root=OWNED):
    directory = root / "fixtures"
    freeze = json.loads((directory / "FIXTURE_FREEZE.json").read_text())
    for f in freeze["files"]:
        assert sha(directory / f["path"]) == f["sha256"], "FIXTURE_CHANGED_AFTER_FREEZE"
    runtime = json.loads((directory / "synthetic_runtime.json").read_text())
    evaluation = json.loads((directory / "synthetic_evaluation_only.json").read_text())
    assert 12 <= len(runtime) <= 16
    assert {r["case_id"] for r in runtime} == {e["case_id"] for e in evaluation}
    assert len({r["family_id"] for r in runtime}) == len(runtime)
    assert_runtime_separation(runtime)
    for r in runtime:
        assert r["flags"] == FLAGS
        assert r["target"]["query"].strip()
        turns = {t["turn_id"]: t for t in r["source_turns"]}
        assert len(turns) == len(r["source_turns"])
        for op in r["setup_operations"]:
            turn = turns[op["source_turn_id"]]
            a, b = op["source_span_chars"]
            assert turn["content"][a:b] == op["evidence_span"]
            assert op["learner_id"] == turn["learner_id"] and op["course_id"] == turn["course_id"]
    for e in evaluation:
        assert e["flags"] == FLAGS and e["split"] == "NOT_ASSIGNED"
        assert all(e["human_review"][x] == "" for x in ("writer", "reviewer", "signature"))
        for c in e["expected_constraints"]:
            assert c["fact_id"] in e["required_memory_fact_ids"] and c["why_needed"]
    return runtime, {e["case_id"]: e for e in evaluation}

def coverage(required, retrieved, *, ran=True, clarification=False):
    """A miss remains a miss even when assertions about reporting pass."""
    missing = sorted(set(required) - set(retrieved))
    if not ran:
        status = "NOT_RUN"
    elif clarification:
        status = "AMBIGUOUS_OR_UNSUPPORTED_REQUIRES_CLARIFICATION"
    elif not required:
        status = "NOT_REQUIRED"
    elif not missing:
        status = "COMPLETE"
    elif set(required) & set(retrieved):
        status = "PARTIAL"
    else:
        status = "MISS"
    return status, missing

if __name__ == "__main__":
    r, e = validate_fixtures()
    print(f"Standalone fixture integrity/separation checks passed: {len(r)} synthetic families")
