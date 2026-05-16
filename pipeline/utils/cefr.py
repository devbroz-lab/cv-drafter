"""
Shared CEFR level mapping used by the GIZ renderer and the field editor.

Single source of truth — ``templates.giz``, ``pipeline.agents.cv_extractor``,
and ``pipeline.agents.field_editor`` all import from here so the mapping can
never silently diverge between extraction, rendering, and editing.

Public API
----------
CEFR_MAP : dict[str, str]
    Lowercase free-text level → canonical CEFR label.

NUMERIC_SCALE_TO_CEFR : dict[str, str]
    1–5 numeric scale → canonical CEFR label, **"1_best" default convention**
    (1 = excellent / highest proficiency).
    1→C2, 2→C1, 3→B2, 4→B1, 5→A2.
    This is the dominant convention in development-sector CVs; confirmed as
    the correct default from Round 3 production validation (Merita Kostari,
    header "1 – excellent; 5 – basic").

NUMERIC_SCALE_TO_CEFR_INVERTED : dict[str, str]
    1–5 numeric scale → canonical CEFR label, "1_worst" convention
    (1 = basic / lowest proficiency).
    1→A1, 2→A2, 3→B1, 4→B2, 5→C1.
    Used when ``CVData.language_scale_direction == "1_worst"``.

CEFR_UNRESOLVABLE_SENTINEL : str
    Value returned by ``map_cefr`` when the input is a numeric value outside
    the 1–5 range, or a slash-separated string that contains an out-of-range
    digit.  Callers and the renderer display this as-is, signalling that the
    field requires manual review.

map_cefr(level: str) -> str
    Returns the canonical CEFR label for *level* using the "1_best" default.
    Handles:
      - Exact free-text matches ("fluent" → "C2", "good" → "C1", …)
      - Exact CEFR-code matches ("b2" → "B2", "c1/c2" → "C1/C2", …)
      - Parenthetical formats ("Proficient (C2)" → "C2",
        "Upper Intermediate (B2)" → "B2")
      - Parenthetical with numeric inner ("Level (3)" → "B2" with 1_best)
      - Numeric 1–5 scale inputs ("1" → "C2", "3" → "B2", "5" → "A2")
      - Slash-separated multi-skill numeric ("3/4/4" → "B2/B1/B1")
      - Out-of-range integers / unresolvable inputs → CEFR_UNRESOLVABLE_SENTINEL
      - Unknown free-text → returned unchanged (existing fallback behaviour)

map_numeric_scale_inverted(token: str) -> str | None
    Maps a single digit token using the "1_worst" inverted scale.
    Returns the CEFR label, or None if outside 1–5.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

CEFR_MAP: dict[str, str] = {
    "mother tongue": "Native",
    "native": "Native",
    "fluent": "C2",
    "excellent": "C2",
    "very good": "C1/C2",
    "good": "C1",
    "fair": "B1/B2",
    "intermediate": "B1/B2",
    "working": "B1",
    "basic": "A2",
    "beginner": "A1",
    "poor": "A1/A2",
    "a1": "A1",
    "a2": "A2",
    "b1": "B1",
    "b2": "B2",
    "c1": "C1",
    "c2": "C2",
    "c1/c2": "C1/C2",
    "b1/b2": "B1/B2",
    "a1/a2": "A1/A2",
}

# 1–5 numeric scale → CEFR, "1_best" convention (1 = excellent = highest CEFR).
# This is the default mapping used by map_cefr and _populate_cefr_fields.
# Confirmed as the correct default from Round 3 production validation
# (Merita Kostari, header "1 – excellent; 5 – basic").
NUMERIC_SCALE_TO_CEFR: dict[str, str] = {
    "1": "C2",
    "2": "C1",
    "3": "B2",
    "4": "B1",
    "5": "A2",
}

# 1–5 numeric scale → CEFR, "1_worst" convention (1 = basic = lowest CEFR).
# Used when CVData.language_scale_direction == "1_worst".
NUMERIC_SCALE_TO_CEFR_INVERTED: dict[str, str] = {
    "1": "A1",
    "2": "A2",
    "3": "B1",
    "4": "B2",
    "5": "C1",
}

# Returned for integers outside 1–5 or slash strings containing out-of-range digits.
CEFR_UNRESOLVABLE_SENTINEL: str = "?"

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

# Matches the first parenthetical in a string: "Proficient (C2)" → group 1 = "C2"
_PAREN_PATTERN: re.Pattern[str] = re.compile(r"\(([^)]+)\)")

# Matches a bare integer (possibly with surrounding whitespace — handled by .strip())
_BARE_INT_PATTERN: re.Pattern[str] = re.compile(r"^\d+$")

# Matches slash-separated all-integer tokens: "1/5", "3/4/4", "3 / 4 / 4"
_SLASH_NUMERIC_PATTERN: re.Pattern[str] = re.compile(
    r"^\d+(?:\s*/\s*\d+)+$"
)


def _try_numeric_scale(token: str) -> str | None:
    """
    Return the CEFR label for digit token *token* using the "1_best" default
    mapping, or ``None`` if outside the 1–5 range.
    """
    return NUMERIC_SCALE_TO_CEFR.get(token.strip())


def map_numeric_scale_inverted(token: str) -> str | None:
    """
    Return the CEFR label for digit token *token* using the "1_worst"
    inverted mapping, or ``None`` if outside the 1–5 range.

    Called by ``_populate_cefr_fields`` in ``cv_extractor.py`` when
    ``CVData.language_scale_direction == "1_worst"``.
    """
    return NUMERIC_SCALE_TO_CEFR_INVERTED.get(token.strip())


def _map_numeric_or_sentinel(raw: str) -> str | None:
    """
    Attempt to map *raw* as a numeric scale value.

    Returns
    -------
    str | None
        A canonical CEFR string if the input is a recognisable numeric
        expression, or ``None`` if the raw string is not numeric at all
        (caller should fall through to unknown-passthrough).

    Notes
    -----
    - Bare integer in 1–5 → mapped CEFR label.
    - Bare integer outside 1–5 → CEFR_UNRESOLVABLE_SENTINEL.
    - Slash-separated all-digits, all in 1–5 → "/".join of mapped labels.
    - Slash-separated with any digit outside 1–5 → CEFR_UNRESOLVABLE_SENTINEL.
    - Non-numeric raw → None (not our concern; caller passes through).
    """
    # Slash-separated (two or more digit tokens)
    if _SLASH_NUMERIC_PATTERN.fullmatch(raw):
        tokens = [t.strip() for t in raw.split("/")]
        mapped = [_try_numeric_scale(t) for t in tokens]
        if any(m is None for m in mapped):
            return CEFR_UNRESOLVABLE_SENTINEL
        return "/".join(m for m in mapped)  # type: ignore[arg-type]

    # Bare integer
    if _BARE_INT_PATTERN.fullmatch(raw):
        result = _try_numeric_scale(raw)
        return result if result is not None else CEFR_UNRESOLVABLE_SENTINEL

    return None  # not a numeric expression


# ---------------------------------------------------------------------------
# Public mapping function
# ---------------------------------------------------------------------------

def map_cefr(level: str) -> str:
    """
    Return the canonical CEFR label for *level*.

    Resolution order
    ----------------
    1. Exact lookup in ``CEFR_MAP`` (case-insensitive, whitespace-stripped).
    2. Parenthetical extraction: if the stripped input contains a parenthetical
       (e.g. "Proficient (C2)"), extract the inner text and re-run step 1 on
       it; then try step 3 (numeric scale) on the inner text.
    3. Numeric-scale mapping:
       - Bare integer 1–5 → CEFR label.
       - Slash-separated all-integers (e.g. "3/4/4") → each mapped independently,
         joined with "/".  Any digit outside 1–5 → CEFR_UNRESOLVABLE_SENTINEL.
       - Integer outside 1–5 → CEFR_UNRESOLVABLE_SENTINEL.
    4. Unknown input: return *level* unchanged (preserves the existing fallback
       behaviour — callers can decide how to treat unrecognised values).
    """
    raw = level.strip()
    if not raw:
        return level

    # Step 1: exact table lookup
    canonical = CEFR_MAP.get(raw.lower())
    if canonical:
        return canonical

    # Step 2: parenthetical extraction ("Proficient (C2)" → try "C2")
    m = _PAREN_PATTERN.search(raw)
    if m:
        inner = m.group(1).strip()
        # Step 2a: table lookup on inner text
        inner_canonical = CEFR_MAP.get(inner.lower())
        if inner_canonical:
            return inner_canonical
        # Step 2b: numeric scale on inner text ("Level (3)" → "B1")
        numeric_result = _map_numeric_or_sentinel(inner)
        if numeric_result is not None:
            return numeric_result

    # Step 3: numeric scale mapping
    numeric_result = _map_numeric_or_sentinel(raw)
    if numeric_result is not None:
        return numeric_result

    # Step 4: unknown free-text — passthrough
    return level
