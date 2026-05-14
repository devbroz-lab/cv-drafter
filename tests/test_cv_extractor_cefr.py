"""
Tests for the _populate_cefr_fields helper introduced in cv_extractor.py (Fix 3).

Verifies:
  - Raw field populated, cefr empty → cefr populated via map_cefr.
  - Cefr already populated → not overwritten (idempotency).
  - Both raw and cefr empty → both stay empty.
  - Unknown raw value → cefr gets the unchanged passthrough (map_cefr fallback).
  - Idempotency: running twice produces identical output.
  - All three cefr fields (reading, speaking, writing) are handled.
  - Multiple language entries are all processed independently.
"""

import pytest

from models import CVData
from pipeline.agents.cv_extractor import _populate_cefr_fields
from pipeline.utils.cefr import map_cefr


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_cv(**language_fields) -> CVData:
    """Build a minimal CVData with one language entry from the given fields."""
    lang_defaults = {
        "language": "English",
        "reading_raw": "",
        "speaking_raw": "",
        "writing_raw": "",
        "reading_cefr": "",
        "speaking_cefr": "",
        "writing_cefr": "",
    }
    lang_defaults.update(language_fields)
    raw = {
        "personal_info": {},
        "languages": [lang_defaults],
    }
    return CVData.model_validate(raw)


# ---------------------------------------------------------------------------
# Core mapping behaviour
# ---------------------------------------------------------------------------

class TestPopulateCefrFieldsMapping:
    def test_raw_populated_cefr_empty_is_mapped(self):
        cv = _make_cv(reading_raw="fluent", reading_cefr="")
        _populate_cefr_fields(cv)
        assert cv.languages[0].reading_cefr == map_cefr("fluent")
        assert cv.languages[0].reading_cefr == "C2"

    def test_speaking_raw_mapped(self):
        cv = _make_cv(speaking_raw="good", speaking_cefr="")
        _populate_cefr_fields(cv)
        assert cv.languages[0].speaking_cefr == "C1"

    def test_writing_raw_mapped(self):
        cv = _make_cv(writing_raw="basic", writing_cefr="")
        _populate_cefr_fields(cv)
        assert cv.languages[0].writing_cefr == "A2"

    def test_all_three_fields_mapped_independently(self):
        cv = _make_cv(
            reading_raw="fluent",   reading_cefr="",
            speaking_raw="good",    speaking_cefr="",
            writing_raw="fair",     writing_cefr="",
        )
        _populate_cefr_fields(cv)
        assert cv.languages[0].reading_cefr == "C2"
        assert cv.languages[0].speaking_cefr == "C1"
        assert cv.languages[0].writing_cefr == "B1/B2"

    def test_unknown_raw_value_passes_through_unchanged(self):
        """map_cefr returns the original string when no mapping exists."""
        cv = _make_cv(reading_raw="conversational", reading_cefr="")
        _populate_cefr_fields(cv)
        assert cv.languages[0].reading_cefr == "conversational"

    def test_native_raw_maps_correctly(self):
        cv = _make_cv(reading_raw="mother tongue", reading_cefr="")
        _populate_cefr_fields(cv)
        assert cv.languages[0].reading_cefr == "Native"


# ---------------------------------------------------------------------------
# Idempotency — does not overwrite existing cefr values
# ---------------------------------------------------------------------------

class TestPopulateCefrFieldsIdempotency:
    def test_cefr_already_set_not_overwritten(self):
        cv = _make_cv(reading_raw="fluent", reading_cefr="B1")
        _populate_cefr_fields(cv)
        # "fluent" maps to C2, but B1 was already set — must not change
        assert cv.languages[0].reading_cefr == "B1"

    def test_running_twice_produces_same_result(self):
        cv = _make_cv(reading_raw="good", reading_cefr="")
        _populate_cefr_fields(cv)
        first = cv.languages[0].reading_cefr
        _populate_cefr_fields(cv)
        second = cv.languages[0].reading_cefr
        assert first == second == "C1"

    def test_partial_set_only_empty_fields_filled(self):
        cv = _make_cv(
            reading_raw="fluent",   reading_cefr="A1",   # pre-set — not overwritten
            speaking_raw="good",    speaking_cefr="",    # empty — filled
            writing_raw="basic",    writing_cefr="",     # empty — filled
        )
        _populate_cefr_fields(cv)
        assert cv.languages[0].reading_cefr == "A1"    # unchanged
        assert cv.languages[0].speaking_cefr == "C1"   # filled
        assert cv.languages[0].writing_cefr == "A2"    # filled


# ---------------------------------------------------------------------------
# No-op cases
# ---------------------------------------------------------------------------

class TestPopulateCefrFieldsNoOp:
    def test_both_raw_and_cefr_empty_stays_empty(self):
        cv = _make_cv(reading_raw="", reading_cefr="")
        _populate_cefr_fields(cv)
        assert cv.languages[0].reading_cefr == ""

    def test_no_languages_no_error(self):
        cv = CVData.model_validate({"personal_info": {}, "languages": []})
        _populate_cefr_fields(cv)  # should not raise

    def test_whitespace_only_raw_not_mapped(self):
        cv = _make_cv(reading_raw="   ", reading_cefr="")
        _populate_cefr_fields(cv)
        assert cv.languages[0].reading_cefr == ""


# ---------------------------------------------------------------------------
# Multiple language entries
# ---------------------------------------------------------------------------

class TestPopulateCefrFieldsMultipleLanguages:
    def test_all_entries_processed_independently(self):
        raw = {
            "personal_info": {},
            "languages": [
                {
                    "language": "English",
                    "reading_raw": "fluent", "reading_cefr": "",
                    "speaking_raw": "",      "speaking_cefr": "",
                    "writing_raw": "",       "writing_cefr": "",
                },
                {
                    "language": "French",
                    "reading_raw": "basic",  "reading_cefr": "",
                    "speaking_raw": "good",  "speaking_cefr": "B2",  # pre-set
                    "writing_raw": "",       "writing_cefr": "",
                },
            ],
        }
        cv = CVData.model_validate(raw)
        _populate_cefr_fields(cv)
        # English
        assert cv.languages[0].reading_cefr == "C2"
        # French
        assert cv.languages[1].reading_cefr == "A2"
        assert cv.languages[1].speaking_cefr == "B2"   # pre-set, not overwritten
        assert cv.languages[1].writing_cefr == ""       # raw empty, stays empty


# ---------------------------------------------------------------------------
# Fix 3 + Fix 7 integration — parenthetical and numeric raw values
# ---------------------------------------------------------------------------

class TestPopulateCefrFieldsFix7Integration:
    """
    _populate_cefr_fields calls map_cefr, which now handles parenthetical
    and numeric formats (Fix 7).  Confirm the two fixes compose correctly.
    """

    def test_parenthetical_raw_is_resolved(self):
        """'Proficient (C2)' raw → reading_cefr 'C2'."""
        raw = {
            "personal_info": {},
            "languages": [{
                "language": "English",
                "reading_raw": "Proficient (C2)", "reading_cefr": "",
                "speaking_raw": "",               "speaking_cefr": "",
                "writing_raw": "",                "writing_cefr": "",
            }],
        }
        cv = CVData.model_validate(raw)
        _populate_cefr_fields(cv)
        assert cv.languages[0].reading_cefr == "C2"

    def test_numeric_raw_in_range_maps_to_cefr(self):
        """'3' raw → reading_cefr 'B2' (1_best default: 3=B2)."""
        raw = {
            "personal_info": {},
            "languages": [{
                "language": "French",
                "reading_raw": "3", "reading_cefr": "",
                "speaking_raw": "",  "speaking_cefr": "",
                "writing_raw": "",   "writing_cefr": "",
            }],
        }
        cv = CVData.model_validate(raw)
        _populate_cefr_fields(cv)
        assert cv.languages[0].reading_cefr == "B2"

    def test_numeric_raw_out_of_range_produces_sentinel(self):
        """Numeric scale '7' raw → reading_cefr '?' (out-of-range sentinel)."""
        from pipeline.utils.cefr import CEFR_UNRESOLVABLE_SENTINEL
        raw = {
            "personal_info": {},
            "languages": [{
                "language": "German",
                "reading_raw": "7", "reading_cefr": "",
                "speaking_raw": "",  "speaking_cefr": "",
                "writing_raw": "",   "writing_cefr": "",
            }],
        }
        cv = CVData.model_validate(raw)
        _populate_cefr_fields(cv)
        assert cv.languages[0].reading_cefr == CEFR_UNRESOLVABLE_SENTINEL

    def test_slash_separated_raw_maps_each_digit(self):
        """Round 4 reference (1_best default): '3/4/4' → 'B2/B1/B1'."""
        raw = {
            "personal_info": {},
            "languages": [{
                "language": "French",
                "reading_raw": "3/4/4", "reading_cefr": "",
                "speaking_raw": "",     "speaking_cefr": "",
                "writing_raw": "",      "writing_cefr": "",
            }],
        }
        cv = CVData.model_validate(raw)
        _populate_cefr_fields(cv)
        assert cv.languages[0].reading_cefr == "B2/B1/B1"

    def test_language_scale_direction_1_worst_inverts(self):
        """When language_scale_direction='1_worst', numeric mapping is inverted."""
        raw = {
            "personal_info": {},
            "language_scale_direction": "1_worst",
            "languages": [{
                "language": "English",
                "reading_raw": "1",  "reading_cefr": "",
                "speaking_raw": "3", "speaking_cefr": "",
                "writing_raw": "5",  "writing_cefr": "",
            }],
        }
        cv = CVData.model_validate(raw)
        _populate_cefr_fields(cv)
        # 1_worst: 1→A1, 3→B1, 5→C1
        assert cv.languages[0].reading_cefr == "A1"
        assert cv.languages[0].speaking_cefr == "B1"
        assert cv.languages[0].writing_cefr == "C1"
