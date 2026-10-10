"""One-time model-authored engineering fixtures. Never generates human/test data.

Run only before first diagnostics; refuses existing output files. Dialogue event
times below are fictional. Execution/freeze times are recorded separately in UTC.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from common import FLAGS, OWNED, write_json, sha, utc

L = "synthetic-learner-a"
C = "synthetic-course-maths"
ASOF = "2026-08-20T10:00:00+00:00"

def case(number, coverage, query, need, source_class, explanation, *, required=(),
         authorized=(), stored=(), kind="CROSS_SESSION_READ", visible=(), course=C):
    name = f"SYN-M0-{number:02d}"
    runtime = {"case_id": name, "family_id": name + "-family", "episode_id": name + "-episode",
        "flags": FLAGS, "episode_kind": kind,
        "source_turns": [], "setup_operations": [],
        "target": {"learner_id": L, "course_id": course, "session_id": name + "-target-session",
            "as_of": ASOF, "horizon": "current synthetic study week", "query": query,
            "page": "synthetic study workspace", "visible_history": list(visible),
            "visibility_rule": "Only listed target-session turns are visible; earlier sessions are hidden."}}
    evaluation = {"case_id": name, "family_id": runtime["family_id"], "flags": FLAGS,
        "coverage_category": coverage, "persistent_retrieval_needed": need,
        "source_class": source_class, "need_and_control_rationale": explanation,
        "required_memory_fact_ids": list(required), "expected_active_authorized_fact_ids": list(authorized),
        "expected_stored_fact_ids": list(stored), "expected_constraints": [],
        "task_facts_already_visible": [], "clarification_required": False,
        "expected_write_rejections": {}, "human_review": {"writer": "", "reviewer": "", "signature": "",
            "review_status": "NOT_HUMAN_REVIEWED"}, "split": "NOT_ASSIGNED"}
    return runtime, evaluation

def op(pair, fact_id, content, typ="GOAL", *, course=C, learner=L, role="USER",
       operation="ADD", prior=None, time="2026-08-10T09:00:00+00:00", session="earlier-session-1",
       valid_from=None, valid_to=None, source=None, confidence=1.0, basis=None):
    r, _ = pair
    tid = r["case_id"] + "-turn-" + str(len(r["source_turns"]) + 1)
    text = source if source is not None else content
    turn = {"turn_id": tid, "session_id": r["case_id"] + "-" + session,
        "learner_id": learner, "course_id": course, "timestamp": time, "role": role,
        "content": text, "provenance": "MODEL_AUTHORED_SYNTHETIC_SOURCE_TURN"}
    r["source_turns"].append(turn)
    r["setup_operations"].append({"fact_id": fact_id, "source_turn_id": tid,
        "learner_id": learner, "course_id": course, "operation": operation,
        "memory_type": typ, "content": content, "target_fact_id": prior,
        "claim_basis": basis or ("VERIFIED_SYSTEM_EVENT" if role == "SYSTEM" else
                                 "ASSISTANT_ADVICE" if role == "ASSISTANT" else "EXPLICIT_USER_STATEMENT"),
        "confidence": confidence, "consent_status": "GRANTED", "valid_from": valid_from or time,
        "valid_to": valid_to, "evidence_span": text, "source_span_chars": [0, len(text)]})

def create():
    out = []
    p = case(1, "cross_session_goal_and_time", "Can you remind me what I wanted to achieve in maths this week and how much study time I said I had?",
        True, "SOURCE_PRESENT", "Both goal and time budget were stated in an earlier session.",
        required=["f01-goal", "f01-time"], authorized=["f01-goal", "f01-time"], stored=["f01-goal", "f01-time"])
    op(p, "f01-goal", "My goal this week is to explain why the quadratic formula works.")
    op(p, "f01-time", "I have only twenty minutes for maths after work on weekdays.", "CONSTRAINT",
       time="2026-08-10T09:01:00+00:00")
    p[1]["expected_constraints"] = [{"fact_id": "f01-time", "description": "Twenty minutes after work on weekdays",
        "why_needed": "A recalled study plan must preserve the explicit time limit."}]
    out.append(p)

    p = case(2, "stable_preference_limited_applicability", "For reviewing a proof, which study format did I say works best for me?",
        True, "SOURCE_PRESENT", "Preference explicitly applies to proof revision, not all learning tasks.",
        required=["f02-pref"], authorized=["f02-pref"], stored=["f02-pref"])
    op(p, "f02-pref", "When reviewing proofs, I prefer a written worked example before a video.", "PREFERENCE")
    out.append(p)

    p = case(3, "system_active_plan_and_completed_actions", "Where did we leave my maths plan, and which action have I already finished?",
        True, "SOURCE_PRESENT", "System plan and explicit learner completion have different origins.",
        required=["f03-plan", "f03-done"], authorized=["f03-plan", "f03-done"], stored=["f03-plan", "f03-done"])
    op(p, "f03-plan", "Active maths plan: review the worked example, then attempt the two practice problems.", "ACTIVE_PLAN", role="SYSTEM")
    op(p, "f03-done", "I finished reviewing the worked example; the two practice problems are still unfinished.", "COMPLETED_ACTION",
       time="2026-08-15T09:00:00+00:00", session="completion-session")
    out.append(p)

    p = case(4, "event_time_supersession", "What is my updated weekday study limit after the correction I made last time?",
        True, "SOURCE_PRESENT", "Only the explicit correction is currently eligible; old limit must stay superseded.",
        required=["f04-new"], authorized=["f04-new"], stored=["f04-old", "f04-new"], kind="EXPLICIT_STATE_UPDATE_EPISODE")
    op(p, "f04-old", "My weekday study limit is forty minutes.", "CONSTRAINT")
    op(p, "f04-new", "Correction: my weekday study limit is now fifteen minutes, replacing forty minutes.",
       "CORRECTION", operation="SUPERSEDE", prior="f04-old", time="2026-08-18T09:00:00+00:00", session="correction-session")
    p[1]["expected_constraints"] = [{"fact_id": "f04-new", "description": "Fifteen minutes, not forty",
        "why_needed": "Target explicitly asks for the current version."}]
    out.append(p)

    visible = [{"role": "user", "content": "I will first read the graph, then check its units.",
                "timestamp": "2026-08-20T09:58:00+00:00", "turn_id": "visible-session-choice"}]
    p = case(5, "session_state_distinct_from_persistence", "Can you restate the second action I just chose?", False,
        "SESSION_ONLY", "Immediate antecedent is in the legitimate current-session window; no persistent store needed.",
        visible=visible, kind="CURRENT_SESSION_REFERENCE")
    p[1]["task_facts_already_visible"] = ["check its units"]
    out.append(p)

    p = case(6, "present_but_irrelevant", "What maths deadline did I mention in our earlier conversation?", True,
        "IRRELEVANT_ONLY", "Only an unrelated recipe preference exists; missing maths deadline remains missing.",
        required=["f06-missing-deadline"], authorized=["f06-unrelated"], stored=["f06-unrelated"])
    op(p, "f06-unrelated", "For baking recipes I prefer photographs of the finished bread.", "PREFERENCE")
    out.append(p)

    p = case(7, "source_absent_need_remains", "What did I say my revision goal was in our previous session?", True,
        "SOURCE_ABSENT", "A request for missing history still needs history; absence is not a self-contained task.",
        required=["f07-unavailable-goal"])
    p[1]["clarification_required"] = True
    out.append(p)

    visible = [{"role": "user", "content": "My goal is to compare two methods for solving simultaneous equations.",
        "timestamp": "2026-08-20T09:59:00+00:00", "turn_id": "visible-repeated-goal"}]
    p = case(8, "fact_already_visible", "What goal have I just repeated?", False, "VISIBLE_ONLY",
        "Same stored fact is already visible; frozen duplicate exclusion should suppress redundant retrieval.",
        authorized=["f08-goal"], stored=["f08-goal"], visible=visible)
    op(p, "f08-goal", visible[0]["content"])
    p[1]["task_facts_already_visible"] = ["f08-goal"]
    out.append(p)

    p = case(9, "learner_disabled_access", "Remind me of my earlier geometry goal.", True, "PRESENT_UNAUTHORISED",
        "Stored row survives disabling but provider must not enter retrieval.", required=["f09-goal"], stored=["f09-goal"],
        kind="EXPLICIT_ACCESS_CONTROL_EPISODE")
    op(p, "f09-goal", "My geometry goal is to explain the angle sum of a triangle.")
    op(p, None, None, None, operation="DISABLE", time="2026-08-19T09:00:00+00:00", session="control-session",
       source="Please disable memory access for me.")
    out.append(p)

    p = case(10, "two_learners_similar_vocabulary", "Which algebra topic did I decide to practise?", True,
        "SOURCE_PRESENT", "Nearly identical vocabulary from another learner must never cross identity scope.",
        required=["f10-own"], authorized=["f10-own"], stored=["f10-own", "f10-other"])
    op(p, "f10-own", "I decided to practise algebra by solving linear equations.")
    op(p, "f10-other", "I decided to practise algebra by expanding cubic expressions.", learner="synthetic-learner-b")
    out.append(p)

    p = case(11, "same_learner_two_courses", "Which project did I choose to focus on for this maths course?", True,
        "SOURCE_PRESENT", "Same learner identity in two course databases; only maths partition enters target retrieval.",
        required=["f11-maths"], authorized=["f11-maths"], stored=["f11-maths", "f11-physics"])
    op(p, "f11-maths", "For this maths course I chose to focus on the quadratic modelling project.")
    op(p, "f11-physics", "For this physics course I chose to focus on the pendulum modelling project.", course="synthetic-course-physics")
    out.append(p)

    p = case(12, "ambiguous_antecedent", "Can we continue that plan?", True, "AMBIGUOUS_SOURCE",
        "Two valid plans and no target antecedent. Retrieval availability cannot resolve which was intended.",
        authorized=["f12-a", "f12-b"], stored=["f12-a", "f12-b"])
    op(p, "f12-a", "My current algebra plan is to check the worked examples.", "ACTIVE_PLAN")
    op(p, "f12-b", "My current geometry plan is to draw and label the diagrams.", "ACTIVE_PLAN", time="2026-08-10T09:01:00+00:00")
    p[1]["clarification_required"] = True
    out.append(p)

    p = case(13, "goal_constraint_plan_bundle", "Could you bring back the plan we settled on, including what it is meant to achieve and the limits I gave you?",
        True, "SOURCE_PRESENT", "Three distinct source spans are needed; any one selected item is insufficient.",
        required=["f13-goal", "f13-bound", "f13-plan"], authorized=["f13-goal", "f13-bound", "f13-plan"],
        stored=["f13-goal", "f13-bound", "f13-plan"])
    op(p, "f13-goal", "I want to distinguish correlation from a causal relationship.")
    op(p, "f13-bound", "Tuesday is unavailable and I can spare a quarter of an hour on Thursday.", "CONSTRAINT", time="2026-08-10T09:01:00+00:00")
    op(p, "f13-plan", "Our active study plan is to contrast the two scatterplots and explain the difference.", "ACTIVE_PLAN", role="SYSTEM", time="2026-08-10T09:02:00+00:00")
    p[1]["expected_constraints"] = [{"fact_id": "f13-bound", "description": "No Tuesday; fifteen minutes Thursday",
        "why_needed": "The target asks for all previously supplied limits."}]
    out.append(p)

    p = case(14, "explicit_delete_and_withdrawal", "What study preference did I previously save?", True, "PRESENT_UNAUTHORISED",
        "Deletion redacts content and withdraws consent; target cannot restore the old fact.",
        required=["f14-pref"], stored=["f14-pref"], kind="EXPLICIT_STATE_UPDATE_EPISODE")
    op(p, "f14-pref", "I prefer an audio explanation when revising geometry.", "PREFERENCE")
    op(p, None, None, None, operation="DELETE", prior="f14-pref", source="Delete my saved study preference.",
       time="2026-08-18T09:00:00+00:00", session="deletion-session")
    out.append(p)

    p = case(15, "same_course_current_expired_future_windows", "What study time limit applies to me this week?", True,
        "SOURCE_PRESENT", "Earlier/future intervals must remain excluded, independently of relevance.",
        required=["f15-current"], authorized=["f15-current"], stored=["f15-expired", "f15-current", "f15-future"])
    op(p, "f15-expired", "For the first week of August my study limit is one hour a day.", "CONSTRAINT",
       time="2026-08-01T09:00:00+00:00", valid_to="2026-08-08T00:00:00+00:00")
    op(p, "f15-current", "This week my study time limit is twenty-five minutes a day.", "CONSTRAINT",
       time="2026-08-18T09:00:00+00:00", valid_to="2026-08-24T00:00:00+00:00")
    op(p, "f15-future", "Next month my study time limit will be ninety minutes a day.", "CONSTRAINT",
       time="2026-08-19T09:00:00+00:00", valid_from="2026-09-01T00:00:00+00:00")
    out.append(p)

    p = case(16, "rejected_assistant_advice_and_inference", "What study goal did I personally commit to?", True,
        "SOURCE_ABSENT", "Assistant suggestions and model-only inferences are not learner commitments.",
        required=["f16-missing-commitment"])
    op(p, "f16-advice", "You should make algebra revision your study goal.", role="ASSISTANT")
    op(p, "f16-inference", "The learner probably prefers visual explanations.", "PREFERENCE", role="SYSTEM", basis="MODEL_INFERENCE")
    p[1]["expected_write_rejections"] = {"f16-advice": "ASSISTANT_ADVICE_NOT_LEARNER_FACT", "f16-inference": "MODEL_INFERENCE"}
    p[1]["clarification_required"] = True
    out.append(p)
    return out

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OWNED / "fixtures")
    args = parser.parse_args()
    names = ["synthetic_runtime.json", "synthetic_evaluation_only.json", "FIXTURE_FREEZE.json"]
    args.output.mkdir(parents=True, exist_ok=True)
    if any((args.output / n).exists() for n in names):
        raise FileExistsError("REFUSE_TO_REAUTHOR_EXISTING_FIXTURES")
    pairs = create()
    write_json(args.output / names[0], [r for r, e in pairs])
    write_json(args.output / names[1], [e for r, e in pairs])
    write_json(args.output / names[2], {"freeze_utc": utc(), "flags": FLAGS,
        "stage": "BEFORE_ANY_RETRIEVAL", "family_count": len(pairs), "authoring": "MODEL_AUTHORED",
        "query_selection": "Written from constructed dialogue; no retrieval or response score inspected.",
        "files": [{"path": n, "sha256": sha(args.output / n)} for n in names[:2]]})

if __name__ == "__main__":
    main()
