"""
Shared deterministic pre-compute and post-process helpers.

These functions contain zero LLM calls.  They are used by multiple agents
to move arithmetic out of prompts and into Python where it is reliable.

Consumers
---------
  pipeline/agents/fields_generator.py  — compute_project_duration / compute_project_year
  pipeline/agents/compressor.py        — count_words_per_field / count_compressible_words_total
                                         restore_protected_fields
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Word counting
# ---------------------------------------------------------------------------

def count_words(text: str) -> int:
    """Count whitespace-delimited tokens in a string.  Empty / None → 0."""
    if not text:
        return 0
    return len(text.split())


def count_words_per_field(cv_data: dict[str, Any]) -> dict[str, int]:
    """
    Return a flat dict of {label: word_count} for every compressible sub-field.

    Labels use a human-readable dotted path so the compressor can report them
    in the compression block.  Only compressible fields are included — the same
    set that ``count_compressible_words_total`` sums.

    Examples of returned keys:
      "relevant_projects[0].activities_performed"
      "relevant_projects[1].main_project_features"
      "generated_fields[0].content"
      "key_qualifications[2]"
      "other_relevant_info"
      "other_skills[0]"
      "employment_record[0].description"
      "training[0]"
      "publications[0]"
    """
    result: dict[str, int] = {}

    for i, proj in enumerate(cv_data.get("relevant_projects", [])):
        for sub in ("activities_performed", "main_project_features"):
            val = proj.get(sub, "")
            if val:
                result[f"relevant_projects[{i}].{sub}"] = count_words(val)

    for i, gf in enumerate(cv_data.get("generated_fields", [])):
        val = gf.get("content", "")
        if val:
            result[f"generated_fields[{i}].content"] = count_words(val)

    for i, item in enumerate(cv_data.get("key_qualifications", [])):
        if item:
            result[f"key_qualifications[{i}]"] = count_words(item)

    val = cv_data.get("other_relevant_info", "")
    if val:
        result["other_relevant_info"] = count_words(val)

    for i, item in enumerate(cv_data.get("other_skills", [])):
        if item:
            result[f"other_skills[{i}]"] = count_words(item)

    for i, item in enumerate(cv_data.get("employment_record", [])):
        desc = item.get("description", "")
        if desc:
            result[f"employment_record[{i}].description"] = count_words(desc)

    for i, item in enumerate(cv_data.get("training", [])):
        if item:
            result[f"training[{i}]"] = count_words(item)

    for i, item in enumerate(cv_data.get("publications", [])):
        if item:
            result[f"publications[{i}]"] = count_words(item)

    return result


def count_compressible_words_total(cv_data: dict[str, Any]) -> int:
    """Sum of all compressible word counts for cv_data.  Mirrors the old
    ``_count_compressible_words`` in compressor.py but uses the shared helper."""
    return sum(count_words_per_field(cv_data).values())


# ---------------------------------------------------------------------------
# Date / duration calculation (used by Agent 4 pre-compute)
# ---------------------------------------------------------------------------

_PRESENT_RE = re.compile(r"\b(present|ongoing|current|now|to\s+date)\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_MONTH_MAP: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}

_CURRENT_YEAR = 2026
_CURRENT_MONTH = 1  # conservative — treat "present" as Jan of current year


def _parse_date(raw: str | None) -> tuple[int, int] | None:
    """
    Parse a free-text date string into (year, month).

    Accepts:
      "March 2019" / "march 2019" / "Mar 2019"
      "2019"                       → (2019, 1)
      "Present" / "ongoing" / …   → (_CURRENT_YEAR, _CURRENT_MONTH)
      None / ""                    → None
    """
    if not raw:
        return None
    s = raw.strip()
    if _PRESENT_RE.search(s):
        return (_CURRENT_YEAR, _CURRENT_MONTH)

    year_m = _YEAR_RE.search(s)
    if not year_m:
        return None
    year = int(year_m.group())

    # Look for a month name before or after the year
    lower = s.lower()
    month = 1
    for name, num in _MONTH_MAP.items():
        if name in lower:
            month = num
            break

    return (year, month)


def _months_between(from_tuple: tuple[int, int], to_tuple: tuple[int, int]) -> int:
    """Return the number of whole months between two (year, month) tuples."""
    y1, m1 = from_tuple
    y2, m2 = to_tuple
    return max(0, (y2 - y1) * 12 + (m2 - m1))


def compute_project_duration(date_from: str | None, date_to: str | None) -> str:
    """
    Compute a human-readable duration string from two free-text date fields.

    Returns:
      "N months"  — when < 12 months (e.g. "8 months")
      "N years"   — when >= 12 months, rounded to nearest whole year
      ""          — if either date is missing / unparseable or date_to < date_from

    The string is rounded to the nearest whole unit (months < 12, years >= 12).
    Rounding: 0.5 rounds up.

    Examples:
      ("January 2018", "June 2019")  → "17 months"  (< 18 months)
      ("2015", "2019")               → "4 years"
      ("March 2020", "Present")      → uses _CURRENT_YEAR / _CURRENT_MONTH
      ("", "2019")                   → ""
    """
    parsed_from = _parse_date(date_from)
    parsed_to = _parse_date(date_to)
    if parsed_from is None or parsed_to is None:
        return ""

    total_months = _months_between(parsed_from, parsed_to)
    if total_months <= 0:
        return ""

    if total_months < 12:
        return f"{total_months} months"

    years_exact = total_months / 12
    years_rounded = int(years_exact + 0.5)  # round half-up
    years_rounded = max(1, years_rounded)
    return f"{years_rounded} year{'s' if years_rounded != 1 else ''}"


def compute_project_year(date_from: str | None, date_to: str | None) -> str:
    """
    Derive the "year" display string used by some renderers.

    Returns:
      "YYYY"        — if date_from and date_to resolve to the same year
      "YYYY–YYYY"   — if they differ (en-dash separator, matching WB renderer style)
      "YYYY"        — if only date_from is parseable
      ""            — if neither is parseable

    "Present" in date_to is rendered as the current year integer.
    """
    from_parsed = _parse_date(date_from)
    to_parsed = _parse_date(date_to)

    if from_parsed is None and to_parsed is None:
        return ""

    if from_parsed is not None and to_parsed is None:
        return str(from_parsed[0])

    if from_parsed is None and to_parsed is not None:
        return str(to_parsed[0])

    y_from = from_parsed[0]
    y_to = to_parsed[0]

    if y_from == y_to:
        return str(y_from)
    return f"{y_from}\u2013{y_to}"  # en-dash


# ---------------------------------------------------------------------------
# Protected-field restoration (used by Agent 6 post-processing)
# ---------------------------------------------------------------------------

def restore_protected_fields(
    original: dict[str, Any],
    modified: dict[str, Any],
    protected: frozenset[str],
) -> tuple[dict[str, Any], list[str]]:
    """
    For each top-level key in ``protected``, overwrite the value in ``modified``
    with the value from ``original`` if they differ.

    This is a shallow top-level restore: it replaces the entire value of a
    protected key (which may itself be a dict or list) rather than diffing
    into sub-fields.

    Returns
    -------
    restored : dict
        A copy of ``modified`` with protected fields restored from ``original``.
    restored_paths : list[str]
        The field names that were actually restored (only those that differed).
    """
    import copy
    restored = copy.deepcopy(modified)
    restored_paths: list[str] = []

    for field in protected:
        original_val = original.get(field)
        modified_val = modified.get(field)
        if original_val != modified_val:
            restored[field] = copy.deepcopy(original_val)
            restored_paths.append(field)

    return restored, restored_paths
