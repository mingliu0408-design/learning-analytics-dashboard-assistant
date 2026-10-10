"""Build the P2-A development functional-QA corpus and contamination audit.

The queries in this file are newly authored development prompts. They are not
training examples and must never be copied into the approved semantic index.
"""

from __future__ import annotations

from difflib import SequenceMatcher
import json
from pathlib import Path
import re
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).with_name("functional_qa_cases_v1.jsonl")
AUDIT_OUTPUT = Path(__file__).with_name("functional_qa_contamination_audit_v1.json")
APPROVED_INDEX = PROJECT_ROOT / "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl"
OLD_BENCHMARK = PROJECT_ROOT / "evaluation/unified_benchmark_scenarios.jsonl"


ROUTES = {
    "dashboard": ["dashboard_interpretation", "overview_summary", "overview_metric_specific"],
    "metric": ["metric_definition", "technical_data"],
    "planning": ["rq2_recommendation", "overview_planning", "overview_recommendation"],
    "course": ["course_content", "memory_resolved_follow_up"],
    "cross": ["cross_page_relationship"],
    "memory": ["memory_state_direct_answer", "memory_resolved_follow_up", "memory_plan_revision"],
    "guard": ["access_or_capability", "source_boundary_capability", "discrepancy_or_correction"],
    "social": ["social_interaction"],
    "unsupported": ["unsupported_task"],
    "oos": ["out_of_scope"],
    "ambiguous": ["ambiguous_clarification", "follow_up_without_context"],
}


def expectation(
    query: str,
    *,
    page: str = "Overview",
    intents: Iterable[str],
    routes: Iterable[str],
    dashboard: bool | None,
    rag: bool | None,
    planner: bool | None,
    memory: bool | None = False,
    scope: Iterable[str] = (),
    domain: str = "",
    supplementary: Iterable[str] = (),
    forbidden_sources: Iterable[str] = (),
    special: str = "",
    memory_expectation: dict[str, Any] | None = None,
    invariants: dict[str, Any] | None = None,
) -> dict[str, Any]:
    acceptable_intents = list(intents)
    acceptable_routes = list(routes)
    return {
        "query": query,
        "page": page,
        "expected_intent_family": acceptable_intents[0] if acceptable_intents else "",
        "acceptable_intents": acceptable_intents,
        "forbidden_intents": ["dashboard_interpretation"] if special in {"social", "unsupported", "out_of_scope", "ambiguous"} else [],
        "expected_route": acceptable_routes[0] if acceptable_routes else "",
        "acceptable_routes": acceptable_routes,
        "should_use_dashboard": dashboard,
        "should_use_course_rag": rag,
        "should_use_planner": planner,
        "should_use_memory": memory,
        "acceptable_source_scopes": list(scope),
        "expected_primary_domain": domain,
        "allowed_supplementary_domains": list(supplementary),
        "forbidden_source_types": list(forbidden_sources),
        "expected_special_handling": special,
        "memory_expectation": memory_expectation or {},
        "response_invariants": invariants or {},
    }


def record(case_id: str, family: str, turns: list[dict[str, Any]], notes: str = "") -> dict[str, Any]:
    first = turns[0]
    return {
        "case_id": case_id,
        "family": family,
        "turns": turns,
        "expected_intent_family": first["expected_intent_family"],
        "acceptable_intents": first["acceptable_intents"],
        "forbidden_intents": first["forbidden_intents"],
        "expected_route": first["expected_route"],
        "acceptable_routes": first["acceptable_routes"],
        "should_use_dashboard": first["should_use_dashboard"],
        "should_use_course_rag": first["should_use_course_rag"],
        "should_use_planner": first["should_use_planner"],
        "should_use_memory": first["should_use_memory"],
        "expected_primary_domain": first["expected_primary_domain"],
        "allowed_supplementary_domains": first["allowed_supplementary_domains"],
        "forbidden_source_types": first["forbidden_source_types"],
        "expected_special_handling": first["expected_special_handling"],
        "memory_expectation": first["memory_expectation"],
        "response_invariants": first["response_invariants"],
        "notes": notes,
    }


def single_family(
    prefix: str,
    family: str,
    queries: list[tuple[str, str]],
    **kwargs: Any,
) -> list[dict[str, Any]]:
    return [
        record(f"FQA-{prefix}-{index:03d}", family, [expectation(query, page=page, **kwargs)])
        for index, (page, query) in enumerate(queries, 1)
    ]


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    cases += single_family(
        "SOC", "social_interaction",
        [
            ("Overview", "hi"),
            ("Resources", "Hey, good to see you"),
            ("Lecture", "Morning!"),
            ("Debate", "Hello, hope you're well"),
            ("Reflection", "Many thanks"),
            ("Overview", "Cheers, that cleared things up"),
            ("Resources", "How's it going?"),
            ("Lecture", "Good evening to you"),
            ("Debate", "I appreciate the help"),
            ("Reflection", "Catch you later"),
        ],
        intents=["social_interaction"], routes=ROUTES["social"], dashboard=False, rag=False,
        planner=False, scope=["no_supported_source"], special="social",
        invariants={"must_be_brief": True, "must_not_include_dashboard_statistics": True,
                    "must_not_claim_course_content": True},
    )
    cases += single_family(
        "DASH", "dashboard_interpretation",
        [
            ("Overview", "What picture of my recent engagement emerges from these panels?"),
            ("Resources", "How should I read the pattern in my resource activity?"),
            ("Lecture", "What do my recorded viewing habits suggest at a high level?"),
            ("Debate", "Help me make sense of the participation pattern shown here."),
            ("Reflection", "What can I reasonably conclude from my reflection activity display?"),
            ("Resources", "Is there a noticeable rhythm in when I open learning resources?"),
            ("Lecture", "Summarise the main signal in this lecture activity page."),
            ("Debate", "What stands out in my discussion-board activity?"),
            ("Overview", "Give me a cautious reading of the overall activity summary."),
        ],
        intents=["dashboard_interpretation"], routes=ROUTES["dashboard"], dashboard=True,
        rag=False, planner=False, scope=["dashboard_only"],
        invariants={"must_ground_dashboard_claims": True, "must_not_claim_causality": True},
    )
    cases += single_family(
        "MET", "quantitative_metric",
        [
            ("Resources", "In this display, what exactly is counted as a resource view?"),
            ("Debate", "How is the discussion reply count defined?"),
            ("Reflection", "What does the edited-character figure represent?"),
            ("Lecture", "How many distinct real lecture videos are in my record?"),
            ("Lecture", "Show the numerator and denominator behind the watched-video average."),
            ("Lecture", "Which rows contribute to the all-tracked-rows percentage?"),
            ("Debate", "What is the current value of my debate-post count?"),
            ("Resources", "Does one click or one file opening create the number shown here?"),
        ],
        intents=["metric_clarification", "quantitative_metric_query", "technical_data_question"],
        routes=ROUTES["metric"], dashboard=True, rag=False, planner=False,
        scope=["dashboard_only"], invariants={"must_define_or_calculate_requested_metric": True},
    )
    cases += single_family(
        "PLAN", "planning_or_strategy",
        [
            ("Overview", "I have ten days to catch up; how should I arrange the work?"),
            ("Lecture", "Help me build a workable study rhythm before next Friday."),
            ("Debate", "What sequence of small actions would fit the coming week?"),
            ("Resources", "I can spare twenty minutes each evening; how should I use them?"),
            ("Overview", "Which tasks should come first if I want to recover steadily?"),
            ("Reflection", "Turn my current position into a short, practical study schedule."),
            ("Lecture", "How could I spread the remaining lecture work across five days?"),
            ("Debate", "Give me an order for rebuilding my discussion participation this week."),
            ("Resources", "Help me organise preparation so I am ready by Monday."),
            ("Overview", "What would a realistic two-week routine look like from here?"),
        ],
        intents=["planning_or_strategy"], routes=ROUTES["planning"], dashboard=True,
        rag=False, planner=True, scope=["dashboard_only"],
        invariants={"must_contain_actionable_steps": True},
    )
    cases += single_family(
        "IMP", "improvement_recommendation",
        [
            ("Debate", "Which single change would most improve my discussion participation?"),
            ("Lecture", "What should I adjust first in my lecture-viewing habits?"),
            ("Resources", "Where is the clearest opportunity to improve my resource use?"),
            ("Reflection", "Suggest a concrete way to strengthen my reflection practice."),
            ("Overview", "Based on my activity, what is the most useful improvement to make now?"),
            ("Debate", "Recommend two specific changes to make my contributions more consistent."),
            ("Lecture", "What practical adjustment would address the weakest viewing pattern?"),
            ("Resources", "Give me one evidence-based improvement for preparation activity."),
        ],
        intents=["improvement_recommendation"], routes=ROUTES["planning"], dashboard=True,
        rag=False, planner=True, scope=["dashboard_only"],
        invariants={"must_contain_specific_improvement": True},
    )
    cases += single_family(
        "RAG", "course_content",
        [
            ("Lecture", "Which ideas are introduced in the Week 4 recorded session?"),
            ("Resources", "What is the Week 5 core reading about, based on the indexed material?"),
            ("Debate", "What question are students asked to consider in the Week 6 debate?"),
            ("Reflection", "What guidance do the course materials give for the reflective task?"),
            ("Lecture", "Locate the teaching material connected with multimodal learning analytics."),
            ("Resources", "Which source is listed for social learning analytics?"),
            ("Lecture", "Summarise only what the retrieved Week 3 material supports."),
            ("Resources", "Where in the course material is learning design discussed?"),
            ("Debate", "Find the indexed course evidence for the collaborative-learning discussion."),
            ("Reflection", "What does the supplied course guidance say I should reflect on?"),
        ],
        intents=["course_content_question"], routes=ROUTES["course"], dashboard=False,
        rag=True, planner=False, scope=["course_only"], forbidden_sources=["dashboard"],
        invariants={"must_ground_course_claims_in_retrieval": True},
    )
    cases += single_family(
        "XPG", "cross_page_relationship",
        [
            ("Overview", "How does my lecture viewing pattern relate to my debate participation?"),
            ("Resources", "Compare my resource access with my discussion activity."),
            ("Reflection", "Is there an association between reflection activity and lecture engagement?"),
            ("Debate", "Set my debate replies alongside my preparation in Resources."),
            ("Lecture", "What relationship appears between video engagement and reflective writing?"),
            ("Overview", "Compare the Resources, Lecture, and Debate patterns without claiming cause."),
            ("Reflection", "Do my discussion and reflection traces move in a similar way?"),
        ],
        intents=["cross_page_relationship"], routes=ROUTES["cross"], dashboard=True,
        rag=False, planner=False, scope=["dashboard_only"],
        supplementary=["resources", "lecture", "debate", "reflection"],
        invariants={"must_keep_domain_attribution": True, "must_not_claim_causality": True},
    )

    plan_first = expectation(
        "I need a three-step routine to rebuild my debate participation this week.", page="Debate",
        intents=["planning_or_strategy"], routes=ROUTES["planning"], dashboard=True, rag=False,
        planner=True, memory=False, scope=["dashboard_only"],
        memory_expectation={"active_plan_updated": True},
    )
    cases.append(record("FQA-MEM-001", "memory_follow_up", [
        plan_first,
        expectation("What routine did you just set for me?", page="Resources", intents=["memory_state_query"],
                    routes=["memory_state_direct_answer"], dashboard=False, rag=False, planner=False,
                    memory=True, scope=["memory_only"], memory_expectation={"active_plan_present": True}),
    ], "Create and recall a structured plan."))
    cases.append(record("FQA-MEM-002", "memory_follow_up", [
        expectation("Give me exactly three numbered ways to improve my resource preparation.", page="Resources",
                    intents=["improvement_recommendation"], routes=ROUTES["planning"], dashboard=True,
                    rag=False, planner=True, scope=["dashboard_only"],
                    memory_expectation={"numbered_referents_updated": True}),
        expectation("Could you unpack the second action?", page="Lecture", intents=["improvement_recommendation", "planning_or_strategy"],
                    routes=["memory_resolved_follow_up"], dashboard=True, rag=False, planner=False,
                    memory=True, scope=["dashboard_only"], memory_expectation={"referenced_item_number": "2"}),
    ], "Resolve a numbered recommendation."))
    cases.append(record("FQA-MEM-003", "memory_follow_up", [
        expectation("My goal is to contribute one thoughtful debate reply each week.", page="Debate",
                    intents=["planning_or_strategy", "improvement_recommendation"], routes=ROUTES["planning"],
                    dashboard=True, rag=False, planner=True, scope=["dashboard_only"]),
        expectation("What goal am I currently working toward?", page="Overview", intents=["memory_state_query"],
                    routes=["memory_state_direct_answer"], dashboard=False, rag=False, planner=False,
                    memory=True, scope=["memory_only"], memory_expectation={"active_goal_present": True}),
    ], "Store and query an explicit goal."))
    cases.append(record("FQA-MEM-004", "memory_follow_up", [
        expectation("Find the indexed material for the Week 5 lecture on multimodal analytics.", page="Lecture",
                    intents=["course_content_question"], routes=["course_content"], dashboard=False, rag=True,
                    planner=False, scope=["course_only"]),
        expectation("How could I apply that topic in my reflection?", page="Reflection",
                    intents=["hybrid_course_and_planning"], routes=["hybrid_course_and_planning"], dashboard=True,
                    rag=True, planner=True, memory=True, scope=["hybrid"],
                    memory_expectation={"active_course_item_present": True}),
    ], "Resolve a course-item pronoun and apply it."))
    cases.append(record("FQA-MEM-005", "memory_follow_up", [
        expectation("I want to catch up with the Week 4 lecture.", page="Lecture",
                    intents=["course_content_question"], routes=["course_content"],
                    dashboard=False, rag=True, planner=False, scope=["course_only"]),
        expectation("Correction: I meant Week 5, not Week 4.", page="Lecture", intents=["discrepancy_or_correction", "course_content_question"],
                    routes=["discrepancy_or_correction", "memory_resolved_follow_up"], dashboard=False, rag=True,
                    planner=False, memory=True, scope=["course_only"],
                    memory_expectation={"corrections_applied": True}),
        expectation("Which lecture week is my catch-up goal about now?", page="Reflection", intents=["memory_state_query"],
                    routes=["memory_state_direct_answer"], dashboard=False, rag=False, planner=False,
                    memory=True, scope=["memory_only"], memory_expectation={"active_course_week": "W5"}),
    ], "Correct course context and verify persistence."))
    cases.append(record("FQA-MEM-006", "memory_follow_up", [
        plan_first,
        expectation("I finished the first action; what comes next?", page="Debate",
                    intents=["planning_or_strategy", "improvement_recommendation"], routes=["memory_resolved_follow_up"],
                    dashboard=True, rag=False, planner=False, memory=True, scope=["dashboard_only"],
                    memory_expectation={"completed_step": 1, "next_pending_step": 2}),
        expectation("Remind me what the next action involves.", page="Debate",
                    intents=["planning_or_strategy", "improvement_recommendation"], routes=["memory_resolved_follow_up"],
                    dashboard=True, rag=False, planner=False, memory=True, scope=["dashboard_only"],
                    memory_expectation={"active_plan_present": True}),
    ], "Progress through a retained plan."))

    source_cases = [
        ("Overview", "Using dashboard data only, tell me what my overall activity suggests.", ["dashboard_interpretation"], ROUTES["dashboard"], True, False, False, ["dashboard_only"], ["course_material"]),
        ("Lecture", "Do not use course materials; interpret only my lecture activity record.", ["dashboard_interpretation"], ROUTES["dashboard"], True, False, False, ["dashboard_only"], ["course_material"]),
        ("Resources", "Use course materials only to identify the Week 5 reading.", ["course_content_question"], ["course_content"], False, True, False, ["course_only"], ["dashboard", "memory"]),
        ("Debate", "Answer from my dashboard only: what topic does the Week 6 debate cover?", ["course_content_question"], ["source_boundary_capability"], False, False, False, ["dashboard_only"], ["course_material"]),
        ("Reflection", "Exclude the lecture dashboard and compare my debate and reflection activity.", ["cross_page_relationship"], ["cross_page_relationship"], True, False, False, ["dashboard_only"], ["dashboard:lecture"]),
        ("Resources", "Without Resources data, compare my lecture viewing and debate participation.", ["cross_page_relationship"], ["cross_page_relationship"], True, False, False, ["dashboard_only"], ["dashboard:resources"]),
    ]
    for i, (page, query, intents, routes, dash, rag, planner, scope, forbidden) in enumerate(source_cases, 1):
        cases.append(record(f"FQA-SRC-{i:03d}", "source_restriction", [expectation(
            query, page=page, intents=intents, routes=routes, dashboard=dash, rag=rag, planner=planner,
            scope=scope, forbidden_sources=forbidden, special="source_restriction",
            invariants={"excluded_source_not_used": True},
        )]))

    cases += single_family(
        "GRD", "capability_privacy_guard",
        [
            ("Lecture", "Can you see whether I watched a recording outside this dashboard?"),
            ("Debate", "Are you able to post a discussion reply using my account?"),
            ("Resources", "Can you open files from my private cloud storage?"),
            ("Overview", "Is the personal activity shown here anonymised from other students?"),
            ("Reflection", "Can another student inspect my individual reflection record?"),
            ("Lecture", "Do you have access to the full private recording transcript?"),
            ("Overview", "Can you reveal another learner's dashboard figures to me?"),
            ("Resources", "Will you change the underlying activity log if I ask?"),
        ],
        intents=["access_or_capability_question"], routes=["access_or_capability"], dashboard=True,
        rag=False, planner=False, scope=["dashboard_only"], special="guard",
        invariants={"must_state_capability_or_privacy_boundary": True},
    )

    cases += single_family(
        "AMB", "ambiguous_request",
        [
            ("Overview", "Could you expand on the second one?"),
            ("Resources", "What do you make of that?"),
            ("Lecture", "Could you explain this a little more?"),
            ("Debate", "And the other point?"),
            ("Reflection", "What would you suggest for it?"),
            ("Overview", "Is that a positive result?"),
        ],
        intents=["ambiguous", "dashboard_interpretation"], routes=ROUTES["ambiguous"], dashboard=False,
        rag=False, planner=False, scope=["memory_only", "no_supported_source"], special="ambiguous",
        invariants={"must_request_clarification": True, "must_not_include_dashboard_statistics": True},
    )

    oos = [
        ("Overview", "Suggest a vegetarian supper for tonight."),
        ("Resources", "What was the result of yesterday's cricket match?"),
        ("Lecture", "Help me choose a weekend hotel in Lisbon."),
        ("Debate", "Write a sales slogan for a bicycle shop."),
        ("Reflection", "Can you forecast the weather for my holiday?"),
        ("Overview", "Which shares should I buy this month?"),
    ]
    cases += single_family(
        "OOS", "unsupported_out_of_scope", oos,
        intents=["out_of_scope"], routes=ROUTES["oos"], dashboard=False, rag=False, planner=False,
        scope=["no_supported_source"], special="out_of_scope",
        invariants={"must_not_invent_personal_dashboard_interpretation": True},
    )

    corrections = [
        ("Lecture", "The dashboard says zero views, but I watched the recording yesterday."),
        ("Debate", "That count cannot be right because I posted twice this morning."),
        ("Resources", "Your last answer used Week 4; I was referring to Week 5."),
        ("Reflection", "The reflection total shown here differs from what I submitted."),
        ("Overview", "You attributed those resource views to lectures; please correct the source."),
        ("Debate", "I meant debate replies rather than debate views in my previous question."),
    ]
    correction_records = single_family(
        "COR", "correction_discrepancy", corrections,
        intents=["discrepancy_or_correction"], routes=["discrepancy_or_correction"], dashboard=True,
        rag=False, planner=False, scope=["dashboard_only"], special="correction",
        invariants={"must_acknowledge_discrepancy": True, "must_not_fabricate_cause": True},
    )
    correction_records[2]["turns"][0].update({
        "expected_intent_family": "ambiguous",
        "acceptable_intents": ["ambiguous"],
        "forbidden_intents": ["dashboard_interpretation"],
        "expected_route": "ambiguous_clarification",
        "acceptable_routes": ["ambiguous_clarification"],
        "should_use_dashboard": False,
        "should_use_course_rag": False,
        "should_use_planner": False,
        "should_use_memory": False,
        "acceptable_source_scopes": ["no_supported_source"],
        "expected_special_handling": "ambiguous",
        "response_invariants": {"must_request_clarification": True},
    })
    for key in (
        "expected_intent_family", "acceptable_intents", "forbidden_intents",
        "expected_route", "acceptable_routes", "should_use_dashboard",
        "should_use_course_rag", "should_use_planner", "should_use_memory",
        "expected_special_handling", "response_invariants",
    ):
        correction_records[2][key] = correction_records[2]["turns"][0][key]
    cases += correction_records
    assert len(cases) == 100, len(cases)
    assert sum(len(case["turns"]) > 1 for case in cases) == 6
    return cases


def normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).casefold()).strip()


def corpus_queries(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        candidates = []
        for key in ("query_text", "student_query", "query", "text", "prompt"):
            if isinstance(value.get(key), str):
                candidates.append(value[key])
        for candidate in candidates:
            rows.append({"text": candidate, "source": f"{path.name}:{line_no}"})
    return rows


def contamination_audit(cases: list[dict[str, Any]]) -> dict[str, Any]:
    corpora = {
        "approved_semantic_index": corpus_queries(APPROVED_INDEX),
        "old_62_benchmark": corpus_queries(OLD_BENCHMARK),
    }
    exact: list[dict[str, str]] = []
    normalised_matches: list[dict[str, str]] = []
    near: list[dict[str, Any]] = []
    for case in cases:
        for turn_index, turn in enumerate(case["turns"], 1):
            query = turn["query"]
            norm = normalise(query)
            for corpus_name, rows in corpora.items():
                for row in rows:
                    if query == row["text"]:
                        exact.append({"case_id": case["case_id"], "query": query, "corpus": corpus_name, **row})
                    if norm and norm == normalise(row["text"]):
                        normalised_matches.append({"case_id": case["case_id"], "query": query, "corpus": corpus_name, **row})
                    ratio = SequenceMatcher(None, norm, normalise(row["text"])).ratio()
                    if ratio >= 0.90 and norm != normalise(row["text"]):
                        near.append({"case_id": case["case_id"], "turn": turn_index, "query": query,
                                     "corpus": corpus_name, "matched_text": row["text"],
                                     "source": row["source"], "similarity": round(ratio, 4)})
    return {
        "development_set": True,
        "primary_v3_used": False,
        "total_cases": len(cases),
        "total_turns": sum(len(case["turns"]) for case in cases),
        "single_turn_cases": sum(len(case["turns"]) == 1 for case in cases),
        "multi_turn_sequences": sum(len(case["turns"]) > 1 for case in cases),
        "exact_matches": exact,
        "normalised_matches": normalised_matches,
        "obvious_near_verbatim_matches": near,
    }


def main() -> None:
    cases = build_cases()
    audit = contamination_audit(cases)
    if audit["exact_matches"] or audit["normalised_matches"]:
        raise SystemExit(json.dumps(audit, ensure_ascii=False, indent=2))
    OUTPUT.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8")
    AUDIT_OUTPUT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: audit[key] for key in (
        "total_cases", "total_turns", "single_turn_cases", "multi_turn_sequences",
    )}, indent=2))
    print(f"near_verbatim={len(audit['obvious_near_verbatim_matches'])}")


if __name__ == "__main__":
    main()
