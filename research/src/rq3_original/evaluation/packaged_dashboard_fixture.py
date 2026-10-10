"""Small synthetic dashboard frames for privacy-safe clean-package smoke tests.

These rows are invented and contain no source student records. The normal
application does not use them when its dashboard input files are present.
"""

from __future__ import annotations

from datetime import date

import pandas as pd


SYNTHETIC_STUDENT_ID = 301127


def build_packaged_dashboard_frames() -> dict[str, pd.DataFrame]:
    """Return deterministic synthetic frames matching the dashboard contract."""

    moodle = pd.DataFrame(
        [
            {
                "Time": f"2025-10-{week + 1:02d} 10:00:00",
                "Week": week,
                "Day_of_week": "Monday",
                "Time_of_day": "Morning",
                "Activity": activity,
                "Content_week": week,
                "Activity_event": "views",
                "Event": event,
                "ID": SYNTHETIC_STUDENT_ID,
            }
            for week, activity, event in (
                (1, "Resources", "Resources_views"),
                (2, "Resources", "Resources_views"),
                (3, "Lecture", "Video_views"),
                (4, "Debate", "Debate_views"),
                (5, "Debate", "Debate_posts"),
                (6, "Debate", "Debate_replies"),
            )
        ]
    )
    echo = pd.DataFrame(
        [
            ("Week1 Introductory Lecture", 1, 1, 50),
            ("Week2 Data as the Key Affordance of Technology", 2, 2, 55),
            ("Week3 No Lecture Video", 3, 0, 0),
            ("Week4 Learning Analytics", 4, 1, 60),
            ("Week5 Multimodal Learning Analytics", 5, 3, 65),
            ("Week6 Value-driven Nature of Data", 6, 2, 55),
            ("Week7 Predictions to Discovery", 7, 2, 60),
            ("Week8 Hybrid Intelligence Systems", 8, 0, 0),
            ("Week9 Evidence-informed AI", 9, 0, 0),
        ],
        columns=["Class", "Content_week", "Video Views", "Video View %"],
    )
    echo["ID"] = SYNTHETIC_STUDENT_ID
    gdocs = pd.DataFrame(
        [
            {
                "Date": date(2025, 10, 6),
                "absStrCount": 240.0,
                "dayOfWeek": "Monday",
                "day": 1,
                "Week": 1,
                "ID": SYNTHETIC_STUDENT_ID,
            },
            {
                "Date": date(2025, 10, 13),
                "absStrCount": 360.0,
                "dayOfWeek": "Monday",
                "day": 8,
                "Week": 2,
                "ID": SYNTHETIC_STUDENT_ID,
            },
        ]
    )
    features = pd.DataFrame(
        [
            {
                "ID": SYNTHETIC_STUDENT_ID,
                "Debate_posts": 1,
                "Debate_replies": 1,
                "Debate_views": 3,
                "Resources_views": 2,
                "Video_clicks": 1,
                "Video_view%_avg": 0.44,
                "Video_views_sum": 11,
                "Total_chars": 600,
                "Num_unique_students_have_viewed": 1,
                "Num_unique_students_i_viewed": 1,
                "Num_unique_students_have_replied": 1,
                "Num_unique_students_i_replied": 1,
            }
        ]
    )
    network_columns = ["From", "From_person", "To", "To_person", "count", "week"]
    reply_network = pd.DataFrame(
        [(SYNTHETIC_STUDENT_ID, "Synthetic learner", 900001, "Synthetic peer", 1, 5)],
        columns=network_columns,
    )
    view_network = pd.DataFrame(
        [(SYNTHETIC_STUDENT_ID, "Synthetic learner", 900001, "Synthetic peer", 2, 4)],
        columns=network_columns,
    )
    gdocs_ts = pd.DataFrame(
        [
            {"day": 1, "previousCohorts": 200.0, "currentCohort": 220.0},
            {"day": 8, "previousCohorts": 300.0, "currentCohort": 340.0},
        ]
    )
    return {
        "moodle": moodle,
        "echo": echo,
        "gdocs": gdocs,
        "features": features,
        "reply_network": reply_network,
        "view_network": view_network,
        "gdocs_ts": gdocs_ts,
    }
