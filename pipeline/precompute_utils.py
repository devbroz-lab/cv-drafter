"""
Shared deterministic pre-compute and post-process helpers.

These functions contain zero LLM calls.  They are used by multiple agents
to move arithmetic out of prompts and into Python where it is reliable.

Consumers
---------
  pipeline/agents/cv_tor_mapper.py    — keyword_overlap_score / geography_score /
                                        compute_composite_score / compute_project_duration
                                        (duration pre-compute moved upstream in Round 5)
  pipeline/agents/fields_generator.py  — compute_project_duration / compute_project_year
  pipeline/agents/compressor.py        — count_words_per_field / count_compressible_words_total
                                         restore_protected_fields
"""

from __future__ import annotations

import datetime
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

def _current_date() -> tuple[int, int]:
    """Return (year, month) for today. Evaluated at call time so tests can patch it."""
    today = datetime.date.today()
    return today.year, today.month


def _parse_date(raw: str | None) -> tuple[int, int] | None:
    """
    Parse a free-text date string into (year, month).

    Accepts:
      "March 2019" / "march 2019" / "Mar 2019"
      "2019"                       → (2019, 1)
      "Present" / "ongoing" / …   → (today.year, today.month) via _current_date()
      None / ""                    → None
    """
    if not raw:
        return None
    s = raw.strip()
    if _PRESENT_RE.search(s):
        return _current_date()

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
      ("March 2020", "Present")      → uses today's year/month via _current_date()
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
# Recovery-only input trimming (used by the parse-failure retry path)
# ---------------------------------------------------------------------------

def truncate_text_to_words(text: str, word_cap: int) -> str:
    """Return *text* truncated to at most *word_cap* whitespace-delimited words.

    Appends an ellipsis marker when truncation occurs so the model (and any
    human reading the artifact) can see the text was shortened.  Empty / None
    input returns ``""``.  This is used ONLY on the parse-failure recovery path
    to shrink an oversized request before retrying — never on the happy path.
    """
    if not text:
        return ""
    words = text.split()
    if len(words) <= word_cap:
        return text
    return " ".join(words[:word_cap]) + " […]"


def truncate_project_text(
    cv_data: dict[str, Any],
    word_cap: int,
    fields: tuple[str, ...] = ("main_project_features", "activities_performed"),
) -> dict[str, Any]:
    """Return a deep copy of *cv_data* with the given free-text project fields
    word-capped to *word_cap*.

    Recovery-only helper: A3/A4 (and A5/A6) call this from their ``reduce_input``
    closures to shrink the request after a JSON parse / truncation failure, so
    the retry sends provably *less* input than the attempt that failed.  The
    happy path never calls this.
    """
    import copy
    result = copy.deepcopy(cv_data)
    for project in result.get("relevant_projects", []):
        for field in fields:
            val = project.get(field, "")
            if val:
                project[field] = truncate_text_to_words(val, word_cap)
    return result


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


# ---------------------------------------------------------------------------
# R7.5-H — collapse_by_date_range (Round 7.5)
# ---------------------------------------------------------------------------


def collapse_by_date_range(
    entries: list[dict],
    label_field: str,
    date_from_field: str = "date_from",
    date_to_field: str = "date_to",
) -> list[dict]:
    """Group entries by exact (date_from, date_to). Concatenate label_field
    values alphabetically with ', '. Preserve first-occurrence order of groups.

    Parameters
    ----------
    entries : list[dict]
        List of dicts to collapse. Each must contain ``label_field``,
        ``date_from_field``, and ``date_to_field``.
    label_field : str
        The field whose values are concatenated for rows sharing the same
        date range. For ``countries_of_experience`` pass ``"country"``.
    date_from_field : str
        Name of the start-date field. Default ``"date_from"``.
    date_to_field : str
        Name of the end-date field. Default ``"date_to"``.

    Returns
    -------
    list[dict]
        Collapsed list. Rows with identical (date_from, date_to) pairs are
        merged into a single row whose ``label_field`` is the alphabetically
        sorted, comma-separated concatenation of all matching labels.
        All other fields are taken from the first occurrence of each group.
        Row ordering follows the first occurrence of each group in ``entries``.

    Notes
    -----
    - Matching is exact on the raw string values — no fuzzy or date-parsed
      comparison (Design decision 2 from PIPELINE_DIAGNOSTIC_ROUND_7.5.md).
    - Ordering of the output list is controlled separately by R7.5-G
      (``_sort_by_date_desc`` with ``primary_key="date_to"``).
    - General-purpose: importable by any future consumer (A7, other renderers,
      additional table types).
    """
    groups: dict[tuple[str, str], tuple[dict, list[str]]] = {}
    order: list[tuple[str, str]] = []

    for entry in entries:
        key = (entry.get(date_from_field, ""), entry.get(date_to_field, ""))
        label = entry.get(label_field, "")
        if key not in groups:
            groups[key] = (dict(entry), [label])
            order.append(key)
        else:
            groups[key][1].append(label)

    result: list[dict] = []
    for k in order:
        representative, labels = groups[k]
        collapsed = dict(representative)
        collapsed[label_field] = ", ".join(sorted(labels))
        result.append(collapsed)

    return result


# ---------------------------------------------------------------------------
# R5-B — Python relevance scoring helpers (Round 5)
# ---------------------------------------------------------------------------


def keyword_overlap_score(
    project: dict,
    keywords: list[str],
) -> tuple[float, list[str]]:
    """
    Compute a keyword-overlap relevance score for a single project.

    Concatenates ``project_name``, ``main_project_features``,
    ``activities_performed``, and ``positions_held`` into a searchable text
    blob, then counts how many keywords from *keywords* appear in it
    (case-insensitive substring match).

    Parameters
    ----------
    project : dict
        A single ``RelevantProject`` dict from ``CVData.relevant_projects``.
    keywords : list[str]
        Merged keyword list from all three ``ScoringKeywords`` lists
        (``role_implied`` + ``scope_implied`` + ``explicit``).

    Returns
    -------
    (score, matched_keywords) : (float, list[str])
        ``score`` is ``hits / len(keywords)`` clamped to ``[0.0, 1.0]``.
        Returns ``(0.0, [])`` when *keywords* is empty.
    """
    if not keywords:
        return 0.0, []

    text = " ".join([
        project.get("main_project_features", "") or "",
        project.get("activities_performed", "") or "",
        project.get("positions_held", "") or "",
        project.get("project_name", "") or "",
    ]).lower()

    matched: list[str] = []
    for kw in keywords:
        if kw.lower() in text:
            matched.append(kw)

    score = min(1.0, len(matched) / len(keywords))
    return score, matched


def geography_score(
    project: dict,
    required_countries: list[str],
) -> tuple[float, list[str]]:
    """
    Compute a geography-match relevance score for a single project.

    Checks whether the project's ``location`` and/or ``country`` fields
    overlap with *required_countries*.

    Match tiers
    -----------
    - Exact / substring match (case-insensitive): 1.0
    - Partial region match (any word longer than 4 chars from the required
      string appears in the project location): 0.5
    - No match: 0.0

    Returns the highest tier found plus the list of matched country strings.
    Returns ``(0.0, [])`` when *required_countries* is empty.
    """
    if not required_countries:
        return 0.0, []

    project_location = (
        (project.get("location", "") or "") + " " +
        (project.get("country", "") or "")
    ).lower().strip()

    best_score = 0.0
    matched: list[str] = []

    for req in required_countries:
        req_lower = req.lower()
        if req_lower in project_location or project_location in req_lower:
            best_score = max(best_score, 1.0)
            matched.append(req)
        else:
            # Partial / regional match — any significant word overlap
            req_words = [w for w in req_lower.split() if len(w) > 4]
            loc_words = project_location.split()
            if req_words and any(w in loc_words for w in req_words):
                best_score = max(best_score, 0.5)
                matched.append(req)

    return best_score, matched


def compute_composite_score(
    kw_score: float,
    geo_score: float,
    keyword_weight: float = 0.35,
    geography_weight: float = 0.15,
) -> float:
    """
    Combine the two Python-computable scoring dimensions into a partial
    composite covering 50% of the total relevance weighting.

    The LLM (Agent 3) adds the remaining 50% (tasks 30% + competencies 20%)
    by adjusting the composite within ±0.10 based on its semantic assessment.

    Parameters
    ----------
    kw_score : float    Keyword overlap score (0.0–1.0).
    geo_score : float   Geography match score (0.0, 0.5, or 1.0).
    keyword_weight : float   Default 0.35 (per scoring design doc).
    geography_weight : float Default 0.15 (per scoring design doc).

    Returns
    -------
    float
        Partial composite score in [0.0, 1.0].
    """
    return round(kw_score * keyword_weight + geo_score * geography_weight, 4)
