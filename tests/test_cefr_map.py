"""
Tests for pipeline/utils/cefr.py — map_cefr function (Fix 7).

Covers:
  - Existing CEFR_MAP table entries preserved (no regression).
  - Parenthetical extraction: "Proficient (C2)" → "C2", etc.
  - Numeric scale sentinel: "1", "3", "1/5", "3/5" → "?".
  - Unknown free-text passes through unchanged.
  - Edge cases: empty string, whitespace, nested/malformed parentheses.
  - CEFR_UNRESOLVABLE_SENTINEL constant value.
  - Case-insensitivity preserved for all paths.
"""

import pytest
from pipeline.utils.cefr import (
    CEFR_MAP,
    CEFR_UNRESOLVABLE_SENTINEL,
    NUMERIC_SCALE_TO_CEFR,
    NUMERIC_SCALE_TO_CEFR_INVERTED,
    map_cefr,
    map_numeric_scale_inverted,
)


# ---------------------------------------------------------------------------
# Constant
# ---------------------------------------------------------------------------

class TestCefrSentinel:
    def test_sentinel_is_question_mark(self):
        assert CEFR_UNRESOLVABLE_SENTINEL == "?"


# ---------------------------------------------------------------------------
# Existing table entries — no regression
# ---------------------------------------------------------------------------

class TestExistingTableEntries:
    @pytest.mark.parametrize("raw, expected", [
        ("fluent",        "C2"),
        ("Fluent",        "C2"),
        ("FLUENT",        "C2"),
        ("excellent",     "C2"),
        ("very good",     "C1/C2"),
        ("good",          "C1"),
        ("fair",          "B1/B2"),
        ("intermediate",  "B1/B2"),
        ("working",       "B1"),
        ("basic",         "A2"),
        ("beginner",      "A1"),
        ("poor",          "A1/A2"),
        ("native",        "Native"),
        ("mother tongue", "Native"),
        ("b2",            "B2"),
        ("B2",            "B2"),
        ("c1",            "C1"),
        ("C1",            "C1"),
        ("c1/c2",         "C1/C2"),
        ("a1/a2",         "A1/A2"),
        ("b1/b2",         "B1/B2"),
    ])
    def test_existing_entries_unchanged(self, raw, expected):
        assert map_cefr(raw) == expected

    def test_leading_trailing_whitespace_stripped(self):
        assert map_cefr("  fluent  ") == "C2"

    def test_all_cefr_map_keys_resolve(self):
        """Every key in CEFR_MAP should map to a non-empty value."""
        for key, value in CEFR_MAP.items():
            assert map_cefr(key) == value
            assert map_cefr(key.upper()) == value


# ---------------------------------------------------------------------------
# Parenthetical extraction (Run 2 failure mode)
# ---------------------------------------------------------------------------

class TestParentheticalExtraction:
    def test_proficient_c2(self):
        assert map_cefr("Proficient (C2)") == "C2"

    def test_advanced_c1(self):
        assert map_cefr("Advanced (C1)") == "C1"

    def test_upper_intermediate_b2(self):
        assert map_cefr("Upper Intermediate (B2)") == "B2"

    def test_elementary_a2(self):
        assert map_cefr("Elementary (A2)") == "A2"

    def test_native_speaker_parenthetical(self):
        assert map_cefr("Native Speaker (Native)") == "Native"

    def test_inner_text_case_insensitive(self):
        assert map_cefr("Proficient (c2)") == "C2"
        assert map_cefr("Proficient (C2)") == "C2"

    def test_inner_text_is_freetext_not_cefr_code(self):
        """If inner text maps via freetext, use that mapping."""
        assert map_cefr("(fluent)") == "C2"

    def test_parenthetical_with_unknown_inner_falls_through(self):
        """Unknown inner text → passthrough the full original string."""
        result = map_cefr("Proficient (X9)")
        assert result == "Proficient (X9)"

    def test_parenthetical_with_numeric_inner_in_range_maps(self):
        """Inner "3" is a valid 1-5 scale digit → maps to B2 (1_best default)."""
        assert map_cefr("Level (3)") == "B2"

    def test_parenthetical_with_out_of_range_numeric_gives_sentinel(self):
        """Inner "7" is outside 1-5 scale → sentinel."""
        assert map_cefr("Level (7)") == CEFR_UNRESOLVABLE_SENTINEL

    def test_whitespace_in_inner(self):
        assert map_cefr("Good ( C1 )") == "C1"


# ---------------------------------------------------------------------------
# Numeric scale mapping (1–5 scale, Run 2 Round 2 fix)
# ---------------------------------------------------------------------------

class TestNumericScaleMapping:
    """Integers 1–5 map to CEFR labels using the '1_best' default convention."""

    def test_numeric_scale_to_cefr_constant(self):
        """1_best default: 1=excellent=C2."""
        assert NUMERIC_SCALE_TO_CEFR == {
            "1": "C2", "2": "C1", "3": "B2", "4": "B1", "5": "A2",
        }

    @pytest.mark.parametrize("raw, expected", [
        ("1", "C2"), ("2", "C1"), ("3", "B2"), ("4", "B1"), ("5", "A2"),
    ])
    def test_bare_integer_in_range_maps(self, raw, expected):
        assert map_cefr(raw) == expected

    @pytest.mark.parametrize("raw", ["0", "6", "7", "10", "100"])
    def test_bare_integer_out_of_range_gives_sentinel(self, raw):
        assert map_cefr(raw) == CEFR_UNRESOLVABLE_SENTINEL

    def test_slash_two_element_both_in_range(self):
        """'1/5' → 'C2/A2' (each digit mapped with 1_best default)."""
        assert map_cefr("1/5") == "C2/A2"

    def test_slash_two_element_varied(self):
        assert map_cefr("3/5") == "B2/A2"
        assert map_cefr("2/4") == "C1/B1"

    def test_slash_three_element_run4_reference(self):
        """Round 4 reference (1_best default): '3/4/4' → 'B2/B1/B1'."""
        assert map_cefr("3/4/4") == "B2/B1/B1"

    def test_slash_with_spaces_all_in_range(self):
        """Whitespace around slashes is allowed."""
        assert map_cefr("3 / 4 / 4") == "B2/B1/B1"
        assert map_cefr("1 / 5") == "C2/A2"

    def test_slash_with_out_of_range_digit_gives_sentinel(self):
        """Any out-of-range digit in a slash string → whole string is sentinel."""
        assert map_cefr("3/7") == CEFR_UNRESOLVABLE_SENTINEL
        assert map_cefr("1/6") == CEFR_UNRESOLVABLE_SENTINEL
        assert map_cefr("3/4/9") == CEFR_UNRESOLVABLE_SENTINEL

    def test_cefr_codes_with_digits_not_treated_as_numeric(self):
        """B1, C2 etc. match the CEFR_MAP first — never reach numeric path."""
        assert map_cefr("B1") == "B1"
        assert map_cefr("C2") == "C2"
        assert map_cefr("A2") == "A2"
        assert map_cefr("C1/C2") == "C1/C2"


# ---------------------------------------------------------------------------
# Inverted numeric scale (1_worst convention)
# ---------------------------------------------------------------------------

class TestInvertedNumericScale:
    """NUMERIC_SCALE_TO_CEFR_INVERTED and map_numeric_scale_inverted."""

    def test_inverted_constant(self):
        assert NUMERIC_SCALE_TO_CEFR_INVERTED == {
            "1": "A1", "2": "A2", "3": "B1", "4": "B2", "5": "C1",
        }

    @pytest.mark.parametrize("token, expected", [
        ("1", "A1"), ("2", "A2"), ("3", "B1"), ("4", "B2"), ("5", "C1"),
    ])
    def test_inverted_in_range_maps(self, token, expected):
        assert map_numeric_scale_inverted(token) == expected

    @pytest.mark.parametrize("token", ["0", "6", "7", "100"])
    def test_inverted_out_of_range_returns_none(self, token):
        assert map_numeric_scale_inverted(token) is None

    def test_inverted_does_not_affect_map_cefr(self):
        """map_cefr always uses 1_best default; inversion is separate."""
        assert map_cefr("1") == "C2"   # 1_best default unchanged
        assert map_numeric_scale_inverted("1") == "A1"  # inverted separately


# ---------------------------------------------------------------------------
# Unknown free-text passthrough
# ---------------------------------------------------------------------------

class TestUnknownPassthrough:
    def test_conversational_passes_through(self):
        assert map_cefr("conversational") == "conversational"

    def test_limited_passes_through(self):
        assert map_cefr("limited") == "limited"

    def test_full_professional_proficiency_passes_through(self):
        assert map_cefr("Full professional proficiency") == "Full professional proficiency"

    def test_arbitrary_string_passes_through(self):
        assert map_cefr("xyz_unknown") == "xyz_unknown"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_string_returns_empty_string(self):
        assert map_cefr("") == ""

    def test_whitespace_only_returns_whitespace(self):
        # strip() → empty, no table hit, no parens, not numeric → passthrough
        assert map_cefr("   ") == "   "

    def test_none_type_not_accepted_directly(self):
        """map_cefr expects a str — this is a type contract, not tested here."""
        # Just confirm the function works on valid strings
        assert isinstance(map_cefr("fluent"), str)
