"""Original, invented learning activity and teaching material for the demo.

These records are not anonymised research participants or UCL course extracts.
The examples teach generic study habits, not a real university curriculum.
"""
from copy import deepcopy

PAGES = ("Overview", "Resources", "Lecture", "Debate", "Reflection")
SAMPLE_QUESTIONS = {
    "Overview": ["本周学习活动如何？", "帮我制定一个30分钟的学习计划"],
    "Resources": ["课程材料建议怎样批判性阅读？", "我的资源浏览次数说明什么？"],
    "Lecture": ["视频观看数据能证明我已经理解了吗？", "如何检查视频学习后的理解？"],
    "Debate": ["怎样写一条有证据的讨论回复？", "帮我制定一个讨论参与计划"],
    "Reflection": ["怎样写一篇有证据的学习反思？", "结合我保存的目标，制定反思计划"],
}

WEEKLY = [
    {"week": 1, "resource_views": 8, "video_minutes": 42, "video_completion": 70,
     "debate_posts": 1, "debate_replies": 2, "reflection_words": 220},
    {"week": 2, "resource_views": 12, "video_minutes": 55, "video_completion": 82,
     "debate_posts": 2, "debate_replies": 3, "reflection_words": 340},
    {"week": 3, "resource_views": 6, "video_minutes": 28, "video_completion": 46,
     "debate_posts": 0, "debate_replies": 1, "reflection_words": 160},
    {"week": 4, "resource_views": 10, "video_minutes": 48, "video_completion": 76,
     "debate_posts": 1, "debate_replies": 2, "reflection_words": 290},
]

COURSE_MATERIALS = [
    {"id": "demo-reflection-01", "title": "Evidence-based reflection / 有证据的学习反思",
     "week": "W4", "page": "Reflection", "task_type": "reflection", "source": "synthetic/course/reflection.md",
     "text": "To write an evidence-based reflection, describe one specific learning event, cite an observable example, explain what changed in your understanding, and choose one next action. Activity counts can describe participation but cannot establish understanding. Separate observation from interpretation and acknowledge missing evidence. 有证据的学习反思应描述具体事件、列出观察证据、解释认识变化，并确定一个下一步行动。活动次数不能证明理解。", "data_kind": "SYNTHETIC"},
    {"id": "demo-reading-01", "title": "Critical reading checklist / 批判性阅读检查表",
     "week": "W2", "page": "Resources", "task_type": "reading", "source": "synthetic/course/reading.md",
     "text": "For critical reading, identify the author's main claim, list the evidence offered for that claim, ask what assumptions or limitations remain, and compare one alternative explanation. Keep short notes with separate columns for claims, supporting evidence, and unanswered questions. Reading a page repeatedly does not by itself demonstrate comprehension. 批判性阅读要区分主张、支持证据、假设与局限，并比较替代解释。", "data_kind": "SYNTHETIC"},
    {"id": "demo-debate-01", "title": "Evidence-based debate reply / 有证据的讨论回复",
     "week": "W3", "page": "Debate", "task_type": "debate", "source": "synthetic/course/debate.md",
     "text": "An evidence-based debate reply states which claim you respond to, gives one concrete observation or course example, explains why that evidence supports or challenges the claim, and asks a focused question. Respectful disagreement addresses the argument rather than the person. Reply counts show participation frequency, not argument quality. 讨论回复应指出回应的主张、举出具体证据、解释其关系，并提出聚焦问题。", "data_kind": "SYNTHETIC"},
    {"id": "demo-video-01", "title": "Video understanding check / 视频理解检查",
     "week": "W1", "page": "Lecture", "task_type": "lecture", "source": "synthetic/course/video.md",
     "text": "After watching a lecture video, close the notes and explain one concept in your own words. Produce a small example or counterexample, then compare it with the teaching material and record one remaining question. Video completion measures recorded playback and cannot prove attention, understanding, mastery, or learning gains. 视频观看完成度只反映播放活动，不能证明注意力、理解或学习效果。", "data_kind": "SYNTHETIC"},
    {"id": "demo-planning-01", "title": "Small study plan / 小规模学习计划",
     "week": "W4", "page": "Overview", "task_type": "planning", "source": "synthetic/course/planning.md",
     "text": "A small study plan names an explicit goal, selects one permitted resource, schedules a short learning action followed by a self-check, and stays within the time budget supplied by the learner. Estimates are provisional and should be adjusted by the learner. Completion of planned actions is different from achievement of a learning outcome. 学习计划需明确目标、选择材料、安排行动与自查，并遵守学习者提供的时间预算。", "data_kind": "SYNTHETIC"},
]


def dashboard_snapshot(page="Overview"):
    """Return a fresh JSON-compatible view of invented activity."""
    if page not in PAGES:
        raise ValueError("Unknown dashboard page")
    totals = {key: sum(row[key] for row in WEEKLY) for key in WEEKLY[0] if key not in ("week", "video_completion")}
    totals["video_completion"] = round(sum(row["video_completion"] for row in WEEKLY) / len(WEEKLY), 1)
    keys = {"Overview": ["resource_views", "video_minutes", "debate_posts", "reflection_words"],
            "Resources": ["resource_views"], "Lecture": ["video_minutes", "video_completion"],
            "Debate": ["debate_posts", "debate_replies"], "Reflection": ["reflection_words"]}[page]
    labels = {"resource_views": "资源浏览次数", "video_minutes": "视频观看分钟", "video_completion": "视频平均完成度百分比",
              "debate_posts": "讨论发帖数", "debate_replies": "讨论回复数", "reflection_words": "反思字数"}
    evidence = [{"id": f"dashboard-{page.lower()}-{key}", "kind": "DASHBOARD", "title": labels[key],
                 "text": f"合成学习者4周的{labels[key]}：{totals[key]}。这是活动记录，不能用于证明理解、能力或学习效果。",
                 "source": "demo/data.py:WEEKLY", "page": page} for key in keys]
    return {"page": page, "scope": {"learner_id": "demo-learner", "course_id": "demo-course", "data_kind": "SYNTHETIC"},
            "metrics": {key: totals[key] for key in keys}, "weekly": deepcopy(WEEKLY), "evidence": evidence,
            "limitations": ["所有学习活动与课程材料均为原创合成示例。", "图表依据结构化活动数据，不使用图像识别。"]}
