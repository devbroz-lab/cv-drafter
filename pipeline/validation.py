"""
Deterministic validation helpers used by the content_reviewer agent.

These functions compute facts that can be derived directly from CV and ToR
data without calling the LLM.  Their results are injected into the
<pre_computed> tag so the LLM reviewer is aware of hard qualification gaps
it might otherwise miss.

None of these functions make pass/fail decisions on their own.  They feed
context to the LLM and to the post-processing injection logic in
content_reviewer.py.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Role tier extraction
# ---------------------------------------------------------------------------

_TEAM_LEAD_TOKENS: frozenset[str] = frozenset(
    [
        "team lead", "team leader", "team-lead", "team-leader",
        "lead ", " lead", "leader", "director", "chief", "manager",
        "deputy", "vp ", "vice president", "president", "head of",
        "head,", "head ",
    ]
)

_EXPERT_TOKENS: frozenset[str] = frozenset(
    [
        "senior expert", "senior specialist", "senior consultant",
        "expert", "specialist", "consultant",
    ]
)


def extract_role_tier(proposed_position: str, category: str) -> str:
    """
    Heuristically classify the role into one of two tiers:
      "team_lead"  — leadership title or category
      "expert"     — senior/junior individual contributor
      ""           — cannot be determined

    Used by _inject_experience_gap_finding to decide whether to apply the
    experience-gap threshold (only team_lead tier triggers the check).

    Parameters
    ----------
    proposed_position : str
        Free-text position title from the CV or manifest params.
    category : str
        Expert category string (e.g. "Senior Expert", "Team Leader").
    """
    haystack = (proposed_position + " " + category).lower()

    for token in _TEAM_LEAD_TOKENS:
        if token in haystack:
            return "team_lead"

    return "expert" if any(t in haystack for t in _EXPERT_TOKENS) else ""


# ---------------------------------------------------------------------------
# Required experience years extraction
# ---------------------------------------------------------------------------

def extract_required_years_for_tier(
    tor_data: dict[str, Any],
    proposed_position: str,
    category: str,
) -> int:
    """
    Extract the minimum years of (electricity/energy sector) experience
    required by the ToR for the given position/category.

    Strategy (in order):
    1. Look for explicit keys in tor_data: "required_years",
       "minimum_years", "experience_years", "years_experience".
    2. Scan any string value in tor_data for patterns like
       "10 years", "at least 10 years of experience".
    3. Fall back to tier-based defaults:
         team_lead → 10
         expert    → 5
         unknown   → 0

    Returns an integer (never negative).
    """
    # Direct key lookup
    for key in ("required_years", "minimum_years", "experience_years", "years_experience"):
        val = tor_data.get(key)
        if val is not None:
            try:
                return max(0, int(val))
            except (TypeError, ValueError):
                pass

    # Scan nested string values for year patterns
    years_candidates: list[int] = []
    _scan_for_year_mentions(tor_data, years_candidates)
    if years_candidates:
        return max(years_candidates)

    # Tier-based default
    tier = extract_role_tier(proposed_position, category)
    if tier == "team_lead":
        return 10
    if tier == "expert":
        return 5
    return 0


def _scan_for_year_mentions(obj: Any, results: list[int]) -> None:
    """Recursively walk a JSON-like structure looking for year-mention patterns."""
    pattern = re.compile(
        r"(?:at\s+least\s+)?(\d{1,2})\s*(?:\+\s*)?years?(?:\s+of)?"
        r"(?:\s+(?:relevant|professional|sector|electricity|energy|work))?"
        r"(?:\s+experience)?",
        re.IGNORECASE,
    )
    if isinstance(obj, str):
        for match in pattern.finditer(obj):
            try:
                results.append(int(match.group(1)))
            except ValueError:
                pass
    elif isinstance(obj, dict):
        for v in obj.values():
            _scan_for_year_mentions(v, results)
    elif isinstance(obj, list):
        for item in obj:
            _scan_for_year_mentions(item, results)


# ---------------------------------------------------------------------------
# Documented experience years from CV
# ---------------------------------------------------------------------------

_ENERGY_KEYWORDS: frozenset[str] = frozenset(
    [
        "energy", "electricity", "electric", "power", "grid", "utility",
        "renewable", "solar", "wind", "hydro", "transmission", "distribution",
        "generation", "off-grid", "microgrid", "mini-grid", "electrification",
        "REA", "NERC", "AEDC", "IBEDC", "EKEDC", "TCN", "KEDC",
    ]
)


def _parse_year(value: str | None) -> int | None:
    """Extract a 4-digit year from a free-text date string, or return None."""
    if not value:
        return None
    match = re.search(r"\b(19|20)\d{2}\b", str(value))
    return int(match.group()) if match else None


def _is_energy_project(project: dict[str, Any]) -> bool:
    """Return True if the project appears to be energy/electricity sector work."""
    fields_to_check = [
        project.get("project_name", ""),
        project.get("sector", ""),
        project.get("main_project_features", ""),
        project.get("client", ""),
        project.get("donor", ""),
        project.get("company", ""),
    ]
    combined = " ".join(str(f) for f in fields_to_check if f)
    combined_lower = combined.lower()
    return any(kw.lower() in combined_lower for kw in _ENERGY_KEYWORDS)


def total_documented_years(
    projects: list[dict[str, Any]],
    *,
    energy_only: bool = False,
) -> float:
    """
    Sum up the documented experience years across relevant_projects.

    Overlapping date ranges are not de-duplicated (simple sum).  This can
    overcount for candidates who worked multiple concurrent roles, but gives
    the LLM reviewer a useful lower-bound figure.

    Parameters
    ----------
    projects : list
        List of project dicts from CVData.relevant_projects.
    energy_only : bool
        When True, only count projects identified as energy/electricity sector.

    Returns
    -------
    float
        Total years (fractional, e.g. 2.5 for a 30-month role).
    """
    total: float = 0.0
    current_year = 2026  # conservative "present" fallback

    for project in projects:
        if energy_only and not _is_energy_project(project):
            continue

        date_from_raw = project.get("date_from") or ""
        date_to_raw = project.get("date_to") or ""

        # Accept "present", "ongoing", "current" as date_to
        if re.search(r"\b(?:present|ongoing|current|now)\b", str(date_to_raw), re.IGNORECASE):
            year_to = current_year
        else:
            year_to = _parse_year(date_to_raw)

        year_from = _parse_year(date_from_raw)

        if year_from is not None and year_to is not None and year_to >= year_from:
            total += year_to - year_from

    return total


# ---------------------------------------------------------------------------
# Geographic alternative pathway cross-reference
# ---------------------------------------------------------------------------

def cross_reference_geo_alternative(
    tor_data: dict[str, Any],
    candidate_countries: list[str],
) -> dict[str, Any]:
    """
    Compare the candidate's countries_of_experience against any geographic
    requirements in the ToR.

    Returns a dict that is injected verbatim into <pre_computed> for the LLM
    to reason about.  This function does NOT make a pass/fail decision.

    Returns
    -------
    dict with keys:
      required_regions  : list[str]  — regions/countries from tor_data
      candidate_countries: list[str] — from CV
      direct_match      : bool       — any overlap between required and candidate
      notes             : str        — human-readable summary for the LLM
    """
    # Extract geographic requirements from common tor_data keys
    required: list[str] = []
    for key in (
        "geographic_requirements", "required_countries", "required_regions",
        "region", "country", "geographic_focus", "country_experience",
    ):
        val = tor_data.get(key)
        if isinstance(val, list):
            required.extend(str(v) for v in val if v)
        elif isinstance(val, str) and val.strip():
            required.append(val.strip())

    # Also scan sub-sections (e.g. tor_data["requirements"]["geography"])
    for sub in ("requirements", "mandatory_requirements", "eligibility"):
        sub_obj = tor_data.get(sub)
        if isinstance(sub_obj, dict):
            for k in ("geography", "geographic", "region", "country"):
                v = sub_obj.get(k)
                if isinstance(v, list):
                    required.extend(str(i) for i in v if i)
                elif isinstance(v, str) and v.strip():
                    required.append(v.strip())

    # Normalise
    required_lower = [r.lower() for r in required]
    candidate_lower = [c.lower() for c in candidate_countries]

    direct_match = any(
        any(req in cand or cand in req for cand in candidate_lower)
        for req in required_lower
    )

    if not required:
        notes = "No explicit geographic requirement found in ToR."
    elif direct_match:
        notes = (
            f"Candidate has experience in {candidate_countries} which overlaps "
            f"with ToR geographic requirement(s): {required}."
        )
    else:
        notes = (
            f"Candidate countries {candidate_countries} do not directly match "
            f"ToR geographic requirement(s): {required}. "
            "Recruiter should verify alternative pathway qualification."
        )

    return {
        "required_regions": required,
        "candidate_countries": candidate_countries,
        "direct_match": direct_match,
        "notes": notes,
    }
