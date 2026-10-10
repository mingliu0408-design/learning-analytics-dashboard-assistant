"""E1 deterministic EN/ZH functional patterns, not a language-model evaluation."""
import re
from . import DOMAINS, PAGES

SELECTION_VERSION = "five-view-functional-en-zh-v1"
PATTERNS = {
    "Resources": r"\bresources?\b|\breadings?\b|资源|阅读材料",
    "Lecture": r"\blectures?\b|\bvideos?\b|\bcompletion rate\b|讲座|视频|听课|观看",
    "Debate": r"\bdebates?\b|\bposts?\b|\brepl(?:y|ies)\b|辩论|讨论|发帖|回复",
    "Reflection": r"\breflections?\b|\bcharacters?\b|反思|反省|字符",
}


def select_domains(query, page):
    if page not in PAGES:
        raise ValueError("Unknown dashboard page")
    q = query.casefold()
    named = tuple(d for d in DOMAINS if re.search(PATTERNS[d], q))
    # Explicit domain comparisons win before any week/course heuristic.
    if len(named) > 1:
        return named, "explicit_cross_domain"
    if re.search(r"\b(all (four|five)|overview|across (all )?(pages|areas))\b|所有页面|四个(?:活动)?域|五个页面|总览|跨页", q):
        return DOMAINS, "overview_or_all_domains"
    if named:
        return named, "explicit_domain"
    if (re.search(r"\b(summari[sz]e|summary|improve|improvement|advice|learning|study|progress)\b", q)
            or re.search(r"总结|总结一下|学习情况|学习表现|学习建议|改进|改善|提高|怎么学|如何学", q)):
        return DOMAINS, "broad_summary_or_advice"
    return (DOMAINS if page == "Overview" else (page,)), "current_view"
