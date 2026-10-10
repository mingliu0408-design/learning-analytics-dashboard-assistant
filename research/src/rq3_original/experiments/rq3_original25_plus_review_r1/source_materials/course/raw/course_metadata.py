"""Small verified course metadata used by offline evaluation.

The records here are intentionally compact. They are not full lecture
transcripts; they only capture titles and short source notes that can be
verified from the anonymised module files bundled with the repository.
"""

from __future__ import annotations

import re
from typing import Any


LECTURE_METADATA_BY_WEEK: dict[str, dict[str, Any]] = {
    "W1": {
        "title": "Introductory Lecture",
        "recorded_lecture_title": "Week1 Introductory Lecture",
        "confidence": "medium",
        "source_notes": [
            "input/echo/echo_logs.csv lists Class as Week1 Introductory Lecture.",
            "System Data/Module/Module readings.pdf lists Week 1 as Introduction to DUTE_AI and Learning Analytics.",
        ],
        "content_summary": "Introductory module material on DUTE_AI and learning analytics.",
    },
    "W2": {
        "title": "Data as the Key Affordance of Technology",
        "recorded_lecture_title": "Week2 Data as the Key Affordance of Technology",
        "confidence": "medium",
        "source_notes": [
            "input/echo/echo_logs.csv lists Class as Week2 Data as the Key Affordance of Technology.",
        ],
        "content_summary": "Data as a key affordance in educational technology.",
    },
    "W3": {
        "title": "Richard Noss Lecture",
        "recorded_lecture_title": "Week3 No Lecture Video",
        "confidence": "medium",
        "source_notes": [
            "System Data/Module/Module Handbook.doc lists Session 3 as Richard Noss Lecture.",
            "input/echo/echo_logs.csv lists Class as Week3 No Lecture Video.",
        ],
        "content_summary": "A special lecture week; the activity log marks no standard lecture video.",
    },
    "W4": {
        "title": "Learning Analytics",
        "recorded_lecture_title": "W4 Lecture on Learning Analytics",
        "confidence": "high",
        "source_notes": [
            "System Data/Module/Module Weekly Pages.html labels Week 4 as Learning Analytics and the activity as W4 Lecture on Learning Analytics.",
            "System Data/Module/Module Handbook.doc labels Session 4 as Learning Analytics.",
            "System Data/Module/Module readings.pdf lists Week 4 as Learning Analytics.",
            "input/echo/echo_logs.csv lists Class as Week4 Learning Analytics.",
            "input/moodle_links.pdf lists a W4 lecture link but does not give a fuller title.",
        ],
        "content_summary": (
            "The available weekly page describes W4 as introducing learning analytics, "
            "the relationship between learning theories, learning design, digital data "
            "traces and learning analytics, plus practical prediction/classification work."
        ),
        "disambiguation_note": (
            "The same sources place Multimodal Learning Analytics in W5, not W4."
        ),
    },
    "W5": {
        "title": "Multimodal Learning Analytics",
        "recorded_lecture_title": "W5 Lecture: Multimodal Learning Analytics",
        "confidence": "high",
        "source_notes": [
            "System Data/Module/Module Weekly Pages.html labels Week 5 as Multimodal Learning Analytics.",
            "System Data/Module/Module Handbook.doc labels Session 5 as Multimodal Learning Analytics.",
            "System Data/Module/Module readings.pdf lists Week 5 as Multimodal Learning Analytics.",
            "input/echo/echo_logs.csv lists Class as Week5 Multimodal Learning Analytics.",
        ],
        "content_summary": "The week focuses on multimodal data for modelling and supporting learning.",
    },
    "W6": {
        "title": "Value-driven Nature of Data",
        "recorded_lecture_title": "Week6 Value-driven Nature of Data",
        "confidence": "medium",
        "source_notes": [
            "input/echo/echo_logs.csv lists Class as Week6 Value-driven Nature of Data.",
            "System Data/Module/Module Handbook.doc lists Session 6 as Value-driven Nature of Data and Performance Measures.",
        ],
        "content_summary": "Values embedded in data, algorithms, and performance measures.",
    },
    "W7": {
        "title": "From Predictions to Discovery and Generation with AI in Education",
        "recorded_lecture_title": "Week7 From Predictions to Discovery and Generation with AI in Education",
        "confidence": "medium",
        "source_notes": [
            "input/echo/echo_logs.csv lists Class as Week7 From Predictions to Discovery and Generation with AI in Education.",
        ],
        "content_summary": "AI in education, prediction, discovery, and generation.",
    },
    "W8": {
        "title": "AI and a Vision for Hybrid Intelligence Systems",
        "recorded_lecture_title": "Week8 AI and a Vision for Hybrid Intelligence Systems",
        "confidence": "medium",
        "source_notes": [
            "input/echo/echo_logs.csv lists Class as Week8 AI and a Vision for Hybrid Intelligence Systems.",
            "System Data/Module/Module Handbook.doc lists Session 8 with the same title.",
        ],
        "content_summary": "AI in education and hybrid intelligence systems.",
    },
    "W9": {
        "title": "Evidence-informed Implementations of AI in Education",
        "recorded_lecture_title": "Week9 Evidence-informed Implementations of AI in Education",
        "confidence": "medium",
        "source_notes": [
            "input/echo/echo_logs.csv lists Class as Week9 Evidence-informed Implementations of AI in Education.",
        ],
        "content_summary": "Evidence-informed implementation of AI in educational settings.",
    },
}

for _week, _record in LECTURE_METADATA_BY_WEEK.items():
    _record.setdefault("week", _week)
    _sources: list[str] = []
    for _note in _record.get("source_notes", []):
        _match = re.match(r"([^ ]+(?: [^ ]+)*) (?:lists|labels)", str(_note))
        if _match and _match.group(1) not in _sources:
            _sources.append(_match.group(1))
    _record.setdefault("source_files", _sources)
    _record.setdefault("source_file", "; ".join(_sources))
    _record.setdefault("note", _record.get("disambiguation_note", ""))


def get_lecture_metadata(week: str | int) -> dict[str, Any] | None:
    """Return metadata for a week such as ``W4`` or integer ``4``."""

    key = normalise_week_key(week)
    if not key:
        return None
    record = LECTURE_METADATA_BY_WEEK.get(key)
    return dict(record) if record else None


def lecture_titles_by_week() -> dict[str, str]:
    """Return a compact week-to-title mapping."""

    return {week: str(record["title"]) for week, record in LECTURE_METADATA_BY_WEEK.items()}


def normalise_week_key(week: str | int) -> str:
    """Normalise week identifiers to ``W<number>``."""

    text = str(week).strip()
    if not text:
        return ""
    if text.upper().startswith("W"):
        text = text[1:]
    try:
        return f"W{int(text)}"
    except ValueError:
        return ""
