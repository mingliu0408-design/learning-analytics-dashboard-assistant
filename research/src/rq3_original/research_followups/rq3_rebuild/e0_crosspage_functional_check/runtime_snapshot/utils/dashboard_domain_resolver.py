"""Authoritative deterministic dashboard-domain and scope resolution.

The aliases here describe query-language evidence domains. Navigation-only
page aliases (for example ``overview``) remain in the evidence synthesiser.
"""

from __future__ import annotations

import re


DASHBOARD_DOMAINS = ("lecture", "resources", "debate", "reflection")

DASHBOARD_DOMAIN_ALIASES = {
    "lecture": (
        "video views",
        "video view",
        "lectures",
        "lecture",
        "videos",
        "video",
        "viewing",
        "watching",
    ),
    "resources": (
        "reading access",
        "resource clicks",
        "resource views",
        "resources",
        "resource",
        "readings",
        "reading",
    ),
    "debate": (
        "discussions",
        "discussion",
        "debates",
        "debate",
        "forums",
        "forum",
        "posts",
        "post",
        "replies",
        "reply",
    ),
    "reflection": (
        "google docs",
        "written work",
        "reflections",
        "reflection",
        "reflective",
        "writing",
        "gdocs",
    ),
}

_WHOLE_DASHBOARD_RE = re.compile(
    r"\b(?:all dashboard areas|all four dashboard areas|compare all dashboard areas|"
    r"across all dashboard areas|across (?:my|the) whole dashboard|"
    r"dashboard-wide|all four areas|the four areas|all areas of my dashboard|"
    r"across the dashboard)\b",
    flags=re.IGNORECASE,
)


def detect_explicit_dashboard_domains(query: str) -> list[str]:
    """Return unique explicitly named evidence domains in textual order."""

    value = str(query or "")
    found: list[tuple[int, int, str]] = []
    for domain, aliases in DASHBOARD_DOMAIN_ALIASES.items():
        positions = [
            match.start()
            for alias in aliases
            if (match := re.search(rf"\b{re.escape(alias)}\b", value, re.IGNORECASE))
        ]
        if positions:
            found.append((min(positions), DASHBOARD_DOMAINS.index(domain), domain))
    found.sort()
    return [domain for _position, _stable_order, domain in found]


def is_explicit_whole_dashboard_query(query: str) -> bool:
    """Return whether the query explicitly requests a whole-dashboard scope."""

    return bool(_WHOLE_DASHBOARD_RE.search(str(query or "")))


def detect_dashboard_application_target(query: str) -> str:
    """Return a syntactically explicit ``in/for/into`` application target.

    This uses the authoritative aliases above; it is a distinct grammatical
    role from the general textual-order detector.
    """

    value = str(query or "")
    found: list[tuple[int, int, str]] = []
    for domain, aliases in DASHBOARD_DOMAIN_ALIASES.items():
        for alias in aliases:
            match = re.search(
                rf"\b(?:in|for|into)\s+(?:(?:my|the)\s+)?{re.escape(alias)}\b",
                value,
                flags=re.IGNORECASE,
            )
            if match:
                found.append((match.start(), DASHBOARD_DOMAINS.index(domain), domain))
    found.sort()
    return found[0][2] if found else ""


def resolve_dashboard_scope(query: str) -> list[str]:
    """Resolve deterministic dashboard scope with documented precedence.

    Two or more named domains are an explicit comparison set. Otherwise an
    explicit whole-dashboard request wins over one candidate domain; the named
    domain is then the candidate being assessed, not a scope restriction.
    """

    named = detect_explicit_dashboard_domains(query)
    if len(named) >= 2:
        return named
    if is_explicit_whole_dashboard_query(query):
        return list(DASHBOARD_DOMAINS)
    return named
