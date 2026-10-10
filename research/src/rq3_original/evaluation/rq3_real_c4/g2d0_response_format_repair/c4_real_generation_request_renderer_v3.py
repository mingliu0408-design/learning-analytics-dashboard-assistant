#!/usr/bin/env python3
"""Deterministic plain-text renderer for frozen C4 REAL provider-visible context V3."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from typing import Any, Iterable, Mapping


EXPECTED_CONTEXT_FIELDS = frozenset(
    {
        "current_page",
        "current_query",
        "visible_conversation_history",
        "evidence",
        "planning_support",
    }
)

EVIDENCE_SECTION = {
    "current_page_context": "DASHBOARD EVIDENCE",
    "dashboard_activity": "DASHBOARD EVIDENCE",
    "course_material": "COURSE EVIDENCE",
    "learner_memory": "LEARNER MEMORY",
}

PLANNING_LABELS = {
    "student_state": "Student situation",
    "main_issue": "Main issue",
    "recommended_action": "Recommended action",
    "why_this_matters": "Why this matters",
    "why_this_fits_the_student": "Why this fits the student",
    "action_steps": "Suggested steps",
    "learner_constraints": "Learner constraints",
    "supporting_evidence": "Supporting grounds",
    "uncertainty_or_limitations": "Planning limitation",
}


Fact = tuple[str, str]


@dataclass(frozen=True)
class RenderedRequestV3:
    text: str
    rendered_substantive_facts: tuple[Fact, ...]


def _scalar_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    raise TypeError(f"unsupported substantive scalar: {type(value).__name__}")


def _friendly_label(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


def _is_substantive_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) and not (
        isinstance(value, str) and not value
    )


def _source_nested_facts(value: Any, path: str) -> list[Fact]:
    facts: list[Fact] = []
    if _is_substantive_scalar(value):
        facts.append((path, _scalar_text(value)))
    elif isinstance(value, Mapping):
        for key in sorted(value):
            facts.extend(_source_nested_facts(value[key], f"{path}.{key}"))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            facts.extend(_source_nested_facts(nested, f"{path}[{index}]"))
    elif value not in (None, "", {}, []):
        raise TypeError(f"unsupported provider-visible value at {path}")
    return facts


def source_substantive_facts(context: Mapping[str, Any]) -> tuple[Fact, ...]:
    """Collect the V2 provider-visible facts the V3 rendering must preserve."""

    if set(context) != EXPECTED_CONTEXT_FIELDS:
        raise ValueError("provider-visible context field set mismatch")
    facts: list[Fact] = [
        ("current_page", _scalar_text(context["current_page"])),
        ("current_query", _scalar_text(context["current_query"])),
    ]
    history = context["visible_conversation_history"]
    if not isinstance(history, list):
        raise TypeError("visible conversation history must be a list")
    for index, message in enumerate(history):
        if not isinstance(message, Mapping) or set(message) != {"role", "content"}:
            raise ValueError("visible conversation message shape mismatch")
        facts.extend(_source_nested_facts(message, f"visible_history[{index}]"))

    evidence = context["evidence"]
    if not isinstance(evidence, Mapping) or set(evidence) != {"evidence", "availability_notes"}:
        raise ValueError("provider evidence envelope mismatch")
    items = evidence["evidence"]
    notes = evidence["availability_notes"]
    if not isinstance(items, list) or not isinstance(notes, list):
        raise TypeError("provider evidence envelope lists are malformed")
    source_occurrence: Counter[str] = Counter()
    for item in items:
        if not isinstance(item, Mapping) or item.get("source") not in EVIDENCE_SECTION:
            raise ValueError("provider evidence source is not renderable")
        source = str(item["source"])
        index = source_occurrence[source]
        source_occurrence[source] += 1
        for key in sorted(set(item) - {"source"}):
            facts.extend(
                _source_nested_facts(item[key], f"evidence.{source}[{index}].{key}")
            )
    for index, note in enumerate(notes):
        facts.extend(_source_nested_facts(note, f"availability_notes[{index}]"))

    planning = context["planning_support"]
    if planning is not None:
        if not isinstance(planning, Mapping) or set(planning) != {"status", "plan", "limitations"}:
            raise ValueError("Planning support envelope mismatch")
        limitations = planning["limitations"]
        if limitations is not None:
            facts.extend(_source_nested_facts(limitations, "planning.limitations"))
        plan = planning["plan"]
        if plan is not None:
            if not isinstance(plan, Mapping):
                raise TypeError("Planning plan must be an object or null")
            for key in sorted(plan):
                facts.extend(_source_nested_facts(plan[key], f"planning.plan.{key}"))
        # The frozen status is an internal execution state, not student-facing content.
    return tuple(facts)


def _render_nested(
    value: Any,
    path: str,
    facts: list[Fact],
    *,
    indent: int = 0,
    label: str | None = None,
) -> list[str]:
    prefix = "  " * indent
    lines: list[str] = []
    if _is_substantive_scalar(value):
        text = _scalar_text(value)
        facts.append((path, text))
        if label is None:
            lines.append(f"{prefix}- {text}")
        elif "\n" in text:
            lines.extend((f"{prefix}- {label}:", text))
        else:
            lines.append(f"{prefix}- {label}: {text}")
        return lines
    if isinstance(value, Mapping):
        if label is not None and value:
            lines.append(f"{prefix}- {label}:")
            indent += 1
        for key in sorted(value):
            lines.extend(
                _render_nested(
                    value[key],
                    f"{path}.{key}",
                    facts,
                    indent=indent,
                    label=_friendly_label(str(key)),
                )
            )
        return lines
    if isinstance(value, list):
        if label is not None and value:
            lines.append(f"{prefix}- {label}:")
            indent += 1
        for index, nested in enumerate(value):
            lines.extend(
                _render_nested(
                    nested,
                    f"{path}[{index}]",
                    facts,
                    indent=indent,
                )
            )
        return lines
    if value not in (None, "", {}, []):
        raise TypeError(f"unsupported provider-visible value at {path}")
    return lines


def _section(title: str, lines: Iterable[str]) -> str | None:
    material = [line for line in lines if line != ""]
    if not material:
        return None
    return title + "\n" + "\n".join(material)


def render_generation_request_v3_with_audit(
    context: Mapping[str, Any],
) -> RenderedRequestV3:
    """Render one provider-visible V2 context as ordinary deterministic text."""

    source_facts = source_substantive_facts(context)
    rendered_facts: list[Fact] = []
    sections: list[str] = []

    page = _scalar_text(context["current_page"])
    rendered_facts.append(("current_page", page))
    sections.append("CURRENT LAD PAGE\n" + page)

    query = _scalar_text(context["current_query"])
    rendered_facts.append(("current_query", query))
    sections.append("STUDENT REQUEST\n" + query)

    history_lines: list[str] = []
    for index, message in enumerate(context["visible_conversation_history"]):
        role = _scalar_text(message["role"])
        content = _scalar_text(message["content"])
        rendered_facts.extend(
            (
                (f"visible_history[{index}].content", content),
                (f"visible_history[{index}].role", role),
            )
        )
        history_lines.extend((f"Message {index + 1} role: {role}", content))
    history_section = _section("VISIBLE CONVERSATION HISTORY", history_lines)
    if history_section:
        sections.append(history_section)

    evidence = context["evidence"]
    section_lines: dict[str, list[str]] = {
        "DASHBOARD EVIDENCE": [],
        "COURSE EVIDENCE": [],
        "LEARNER MEMORY": [],
    }
    source_occurrence: Counter[str] = Counter()
    section_occurrence: Counter[str] = Counter()
    for item in evidence["evidence"]:
        source = str(item["source"])
        source_index = source_occurrence[source]
        source_occurrence[source] += 1
        section_title = EVIDENCE_SECTION[source]
        item_lines: list[str] = []
        for key in sorted(set(item) - {"source"}):
            item_lines.extend(
                _render_nested(
                    item[key],
                    f"evidence.{source}[{source_index}].{key}",
                    rendered_facts,
                    label=_friendly_label(str(key)),
                )
            )
        if item_lines:
            section_occurrence[section_title] += 1
            section_lines[section_title].append(
                f"Evidence item {section_occurrence[section_title]}"
            )
            section_lines[section_title].extend(item_lines)
    for title in ("DASHBOARD EVIDENCE", "COURSE EVIDENCE", "LEARNER MEMORY"):
        rendered = _section(title, section_lines[title])
        if rendered:
            sections.append(rendered)

    planning = context["planning_support"]
    planning_lines: list[str] = []
    if planning is not None:
        if planning["limitations"] is not None:
            planning_lines.extend(
                _render_nested(
                    planning["limitations"],
                    "planning.limitations",
                    rendered_facts,
                    label="Planning limitations",
                )
            )
        plan = planning["plan"]
        if isinstance(plan, Mapping):
            planning_order = (
                "student_state",
                "main_issue",
                "recommended_action",
                "why_this_matters",
                "why_this_fits_the_student",
                "action_steps",
                "supporting_evidence",
                "learner_constraints",
                "uncertainty_or_limitations",
            )
            if set(plan) != set(planning_order):
                raise ValueError("Planning plan field set mismatch")
            for key in planning_order:
                planning_lines.extend(
                    _render_nested(
                        plan[key],
                        f"planning.plan.{key}",
                        rendered_facts,
                        label=PLANNING_LABELS[key],
                    )
                )
    planning_section = _section("PLANNING SUPPORT", planning_lines)
    if planning_section:
        sections.append(planning_section)

    limitation_lines: list[str] = []
    for index, note in enumerate(evidence["availability_notes"]):
        limitation_lines.extend(
            _render_nested(
                note,
                f"availability_notes[{index}]",
                rendered_facts,
            )
        )
    limitations_section = _section("LIMITATIONS", limitation_lines)
    if limitations_section:
        sections.append(limitations_section)

    text = "\n\n".join(sections) + "\n"
    if Counter(rendered_facts) != Counter(source_facts):
        raise RuntimeError("renderer lost, added, or changed substantive provider-visible content")
    return RenderedRequestV3(text=text, rendered_substantive_facts=tuple(rendered_facts))


def render_generation_request_v3(context: Mapping[str, Any]) -> str:
    return render_generation_request_v3_with_audit(context).text


if __name__ == "__main__":
    raise SystemExit("Import render_generation_request_v3; no standalone mode is provided.")
