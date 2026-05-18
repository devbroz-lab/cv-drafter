"""
Tests for pipeline/precompute_utils.py

Covers:
  - count_words
  - count_words_per_field / count_compressible_words_total
  - compute_project_duration
  - compute_project_year
  - restore_protected_fields
  - keyword_overlap_score (Fix 4, Round 5)
  - geography_score (Fix 4, Round 5)
  - compute_composite_score (Fix 4, Round 5)
  - collapse_by_date_range (Fix SS, Round 7.5)
"""

import datetime

import pytest
from pipeline.precompute_utils import (
    collapse_by_date_range,
    compute_composite_score,
    compute_project_duration,
    compute_project_year,
    count_compressible_words_total,
    count_words,
    count_words_per_field,
    geography_score,
    keyword_overlap_score,
    restore_protected_fields,
)


# ---------------------------------------------------------------------------
# count_words
# ---------------------------------------------------------------------------

class TestCountWords:
    def test_empty_string(self):
        assert count_words("") == 0

    def test_none(self):
        assert count_words(None) == 0  # type: ignore[arg-type]

    def test_single_word(self):
        assert count_words("hello") == 1

    def test_multiple_words(self):
        assert count_words("hello world foo") == 3

    def test_extra_whitespace(self):
        # str.split() collapses any whitespace
        assert count_words("  hello   world  ") == 2


# ---------------------------------------------------------------------------
# count_words_per_field / count_compressible_words_total
# ---------------------------------------------------------------------------

_SAMPLE_CV: dict = {
    "relevant_projects": [
        {
            "activities_performed": "Led grid rehabilitation across three provinces.",
            "main_project_features": "Transmission line upgrade.",
        },
        {
            "activities_performed": "",
            "main_project_features": "Solar mini-grid deployment.",
        },
    ],
    "generated_fields": [
        {"content": "Expert in renewable energy project design."},
    ],
    "key_qualifications": ["Grid engineer", "SCADA specialist"],
    "other_relevant_info": "Published three papers.",
    "other_skills": ["Python", "GIS"],
    "employment_record": [
        {"description": "Senior consultant at GFA."},
    ],
    "training": ["PMP certification course"],
    "publications": ["Energy access paper 2021"],
    # Protected fields (should NOT be counted)
    "personal_info": {"first_names": "John", "family_name": "Doe"},
    "education": [{"institution": "MIT"}],
}


class TestCountWordsPerField:
    def test_structure_keys_present(self):
        result = count_words_per_field(_SAMPLE_CV)
        assert "relevant_projects[0].activities_performed" in result
        assert "relevant_projects[0].main_project_features" in result
        assert "relevant_projects[1].main_project_features" in result
        assert "generated_fields[0].content" in result
        assert "key_qualifications[0]" in result
        assert "key_qualifications[1]" in result
        assert "other_relevant_info" in result
        assert "other_skills[0]" in result
        assert "other_skills[1]" in result
        assert "employment_record[0].description" in result
        assert "training[0]" in result
        assert "publications[0]" in result

    def test_empty_activity_excluded(self):
        result = count_words_per_field(_SAMPLE_CV)
        # relevant_projects[1].activities_performed is "" — should not appear
        assert "relevant_projects[1].activities_performed" not in result

    def test_protected_fields_excluded(self):
        result = count_words_per_field(_SAMPLE_CV)
        assert not any("personal_info" in k for k in result)
        assert not any("education" in k for k in result)

    def test_word_counts_correct(self):
        result = count_words_per_field(_SAMPLE_CV)
        # "Led grid rehabilitation across three provinces." → 6 words
        assert result["relevant_projects[0].activities_performed"] == 6
        # "Grid engineer" → 2 words
        assert result["key_qualifications[0]"] == 2

    def test_total_matches_sum(self):
        result = count_words_per_field(_SAMPLE_CV)
        total = count_compressible_words_total(_SAMPLE_CV)
        assert total == sum(result.values())

    def test_empty_cv(self):
        assert count_words_per_field({}) == {}
        assert count_compressible_words_total({}) == 0


# ---------------------------------------------------------------------------
# compute_project_duration
# ---------------------------------------------------------------------------

class TestComputeProjectDuration:
    def test_same_year(self):
        assert compute_project_duration("January 2019", "June 2019") == "5 months"

    def test_full_years(self):
        result = compute_project_duration("2015", "2019")
        assert result == "4 years"

    def test_rounds_to_one_year(self):
        # 13 months → rounds to 1 year
        result = compute_project_duration("January 2019", "February 2020")
        assert result == "1 year"

    def test_rounds_to_two_years(self):
        # 24 months exactly
        result = compute_project_duration("January 2018", "January 2020")
        assert result == "2 years"

    def test_present_in_date_to(self):
        today = datetime.date.today()
        total_months = (today.year - 2020) * 12 + (today.month - 1)
        years_rounded = max(1, int(total_months / 12 + 0.5))
        expected = f"{years_rounded} year{'s' if years_rounded != 1 else ''}"
        result = compute_project_duration("January 2020", "Present")
        assert result == expected

    def test_missing_date_from(self):
        assert compute_project_duration("", "June 2020") == ""

    def test_missing_date_to(self):
        assert compute_project_duration("January 2018", "") == ""

    def test_both_missing(self):
        assert compute_project_duration("", "") == ""
        assert compute_project_duration(None, None) == ""

    def test_date_to_before_date_from(self):
        assert compute_project_duration("June 2020", "January 2019") == ""

    def test_month_name_variants(self):
        assert compute_project_duration("Mar 2020", "Sep 2020") == "6 months"


# ---------------------------------------------------------------------------
# compute_project_year
# ---------------------------------------------------------------------------

class TestComputeProjectYear:
    def test_same_year(self):
        assert compute_project_year("January 2019", "December 2019") == "2019"

    def test_different_years(self):
        result = compute_project_year("2015", "2019")
        assert result == "2015\u20132019"  # en-dash

    def test_present_in_date_to(self):
        today = datetime.date.today()
        result = compute_project_year("January 2020", "Present")
        assert result == f"2020\u2013{today.year}"

    def test_only_date_from(self):
        assert compute_project_year("2018", "") == "2018"
        assert compute_project_year("2018", None) == "2018"

    def test_only_date_to(self):
        assert compute_project_year("", "2019") == "2019"
        assert compute_project_year(None, "2019") == "2019"

    def test_both_missing(self):
        assert compute_project_year("", "") == ""
        assert compute_project_year(None, None) == ""


# ---------------------------------------------------------------------------
# restore_protected_fields
# ---------------------------------------------------------------------------

PROTECTED = frozenset({"personal_info", "education", "proposed_position"})


class TestRestoreProtectedFields:
    def test_no_changes(self):
        original = {"personal_info": {"name": "Alice"}, "other": "x"}
        modified = {"personal_info": {"name": "Alice"}, "other": "y"}
        restored, paths = restore_protected_fields(original, modified, PROTECTED)
        assert paths == []
        assert restored["other"] == "y"

    def test_restores_altered_protected_field(self):
        original = {"personal_info": {"name": "Alice"}, "other": "x"}
        modified = {"personal_info": {"name": "BOB"}, "other": "y"}
        restored, paths = restore_protected_fields(original, modified, PROTECTED)
        assert "personal_info" in paths
        assert restored["personal_info"]["name"] == "Alice"
        assert restored["other"] == "y"  # non-protected field kept

    def test_does_not_mutate_inputs(self):
        original = {"personal_info": {"name": "Alice"}}
        modified = {"personal_info": {"name": "BOB"}}
        restore_protected_fields(original, modified, PROTECTED)
        assert original["personal_info"]["name"] == "Alice"
        assert modified["personal_info"]["name"] == "BOB"

    def test_multiple_restorations(self):
        original = {
            "personal_info": {"name": "Alice"},
            "education": [{"degree": "BSc"}],
            "proposed_position": "Team Lead",
        }
        modified = {
            "personal_info": {"name": "X"},
            "education": [],
            "proposed_position": "Changed",
        }
        _, paths = restore_protected_fields(original, modified, PROTECTED)
        assert set(paths) == {"personal_info", "education", "proposed_position"}

    def test_ignores_non_protected_fields(self):
        original = {"personal_info": {"name": "Alice"}, "other_skills": ["old"]}
        modified = {"personal_info": {"name": "Alice"}, "other_skills": ["new"]}
        restored, paths = restore_protected_fields(original, modified, PROTECTED)
        assert paths == []
        assert restored["other_skills"] == ["new"]  # non-protected, not restored


# ---------------------------------------------------------------------------
# keyword_overlap_score — Fix 4 (Round 5)
# ---------------------------------------------------------------------------

class TestKeywordOverlapScore:
    def _proj(self, features="", activities="", positions="", name="") -> dict:
        return {
            "main_project_features": features,
            "activities_performed": activities,
            "positions_held": positions,
            "project_name": name,
        }

    def test_empty_keywords_returns_zero(self):
        proj = self._proj(features="grid code tariff renewable energy")
        score, matches = keyword_overlap_score(proj, [])
        assert score == 0.0
        assert matches == []

    def test_all_keywords_match_returns_one(self):
        proj = self._proj(features="grid code tariff design renewable energy")
        keywords = ["grid code", "tariff design", "renewable energy"]
        score, matches = keyword_overlap_score(proj, keywords)
        assert score == 1.0
        assert set(matches) == set(keywords)

    def test_partial_match(self):
        proj = self._proj(features="grid code and distribution planning")
        keywords = ["grid code", "tariff design", "distribution planning"]
        score, matches = keyword_overlap_score(proj, keywords)
        assert score == pytest.approx(2 / 3, abs=0.01)
        assert "grid code" in matches
        assert "distribution planning" in matches
        assert "tariff design" not in matches

    def test_case_insensitive(self):
        proj = self._proj(features="Grid Code Tariff Design")
        keywords = ["grid code", "tariff design"]
        score, _ = keyword_overlap_score(proj, keywords)
        assert score == 1.0

    def test_score_capped_at_one(self):
        proj = self._proj(features="a b c d e f g h i j k l")
        keywords = ["a", "b", "c"]
        score, matches = keyword_overlap_score(proj, keywords)
        assert score == 1.0

    def test_all_fields_searched(self):
        proj = {
            "main_project_features": "grid code",
            "activities_performed": "tariff design",
            "positions_held": "team leader",
            "project_name": "Energy Project",
        }
        keywords = ["grid code", "tariff design", "team leader", "energy project"]
        score, matches = keyword_overlap_score(proj, keywords)
        assert score == 1.0


# ---------------------------------------------------------------------------
# geography_score — Fix 4 (Round 5)
# ---------------------------------------------------------------------------

class TestGeographyScore:
    def _proj(self, location="", country="") -> dict:
        return {"location": location, "country": country}

    def test_empty_required_returns_zero(self):
        proj = self._proj(location="Nairobi, Kenya")
        score, matches = geography_score(proj, [])
        assert score == 0.0
        assert matches == []

    def test_exact_country_match(self):
        proj = self._proj(country="Kenya")
        score, matches = geography_score(proj, ["Kenya"])
        assert score == 1.0
        assert "Kenya" in matches

    def test_case_insensitive_match(self):
        proj = self._proj(location="Nairobi, KENYA")
        score, matches = geography_score(proj, ["kenya"])
        assert score == 1.0

    def test_partial_regional_match(self):
        proj = self._proj(location="Addis Ababa, Ethiopia")
        # "Africa" appears as a word in neither but "Ethiopia" is >4 chars
        score, matches = geography_score(proj, ["Ethiopia"])
        assert score == 1.0

    def test_regional_partial_overlap(self):
        proj = self._proj(location="West Africa")
        score, matches = geography_score(proj, ["Sub-Saharan Africa"])
        # "Africa" is a >4 char word present in both
        assert score >= 0.5

    def test_no_match_returns_zero(self):
        proj = self._proj(location="Oslo, Norway", country="Norway")
        score, matches = geography_score(proj, ["South Africa", "Kenya"])
        assert score == 0.0
        assert matches == []


# ---------------------------------------------------------------------------
# compute_composite_score — Fix 4 (Round 5)
# ---------------------------------------------------------------------------

class TestComputeCompositeScore:
    def test_both_zero(self):
        assert compute_composite_score(0.0, 0.0) == 0.0

    def test_full_keyword_no_geo(self):
        # 1.0 * 0.35 + 0.0 * 0.15 = 0.35
        assert compute_composite_score(1.0, 0.0) == pytest.approx(0.35)

    def test_no_keyword_full_geo(self):
        # 0.0 * 0.35 + 1.0 * 0.15 = 0.15
        assert compute_composite_score(0.0, 1.0) == pytest.approx(0.15)

    def test_both_full(self):
        # 1.0 * 0.35 + 1.0 * 0.15 = 0.50
        assert compute_composite_score(1.0, 1.0) == pytest.approx(0.50)

    def test_custom_weights(self):
        assert compute_composite_score(0.5, 0.5, keyword_weight=0.4, geography_weight=0.2) == pytest.approx(0.30)


# ---------------------------------------------------------------------------
# collapse_by_date_range — Fix SS (Round 7.5)
# ---------------------------------------------------------------------------

def _country(name: str, date_from: str, date_to: str) -> dict:
    return {"country": name, "date_from": date_from, "date_to": date_to}


class TestCollapseByDateRange:
    def test_empty_input(self):
        assert collapse_by_date_range([], label_field="country") == []

    def test_single_entry_passes_through(self):
        entries = [_country("Kosovo", "January 1999", "Present")]
        result = collapse_by_date_range(entries, label_field="country")
        assert len(result) == 1
        assert result[0]["country"] == "Kosovo"

    def test_identical_range_merged_alphabetically(self):
        """Two countries with identical date range → one row, labels sorted."""
        entries = [
            _country("Croatia",  "January 2014", "December 2018"),
            _country("Albania",  "January 2014", "December 2018"),
        ]
        result = collapse_by_date_range(entries, label_field="country")
        assert len(result) == 1
        assert result[0]["country"] == "Albania, Croatia"

    def test_multiple_countries_same_range_sorted_alphabetically(self):
        entries = [
            _country("Montenegro",     "2014", "2018"),
            _country("Albania",        "2014", "2018"),
            _country("Bosnia",         "2014", "2018"),
            _country("North Macedonia","2014", "2018"),
        ]
        result = collapse_by_date_range(entries, label_field="country")
        assert len(result) == 1
        expected = "Albania, Bosnia, Montenegro, North Macedonia"
        assert result[0]["country"] == expected

    def test_different_ranges_kept_separate(self):
        """Entries with different date ranges are NOT merged."""
        entries = [
            _country("Kosovo",  "January 1999", "Present"),
            _country("Albania", "January 2014", "December 2018"),
        ]
        result = collapse_by_date_range(entries, label_field="country")
        assert len(result) == 2

    def test_first_occurrence_order_preserved(self):
        """Output row order follows first occurrence of each date-range group."""
        entries = [
            _country("Kosovo",  "1999", "Present"),
            _country("Albania", "2014", "2018"),
            _country("Serbia",  "1999", "Present"),   # same range as Kosovo
        ]
        result = collapse_by_date_range(entries, label_field="country")
        # First group: (1999, Present) — Kosovo then Serbia
        # Second group: (2014, 2018) — Albania
        assert len(result) == 2
        assert result[0]["date_from"] == "1999"
        assert result[0]["date_to"] == "Present"
        assert result[1]["date_from"] == "2014"

    def test_non_country_label_field(self):
        """Works with arbitrary label_field name."""
        entries = [
            {"city": "Pristina", "date_from": "2010", "date_to": "2015"},
            {"city": "Tirana",   "date_from": "2010", "date_to": "2015"},
        ]
        result = collapse_by_date_range(entries, label_field="city")
        assert len(result) == 1
        assert result[0]["city"] == "Pristina, Tirana"

    def test_non_label_fields_taken_from_first_occurrence(self):
        """Non-label fields on merged rows come from the first entry."""
        entries = [
            {"country": "B", "date_from": "2010", "date_to": "2015", "extra": "first"},
            {"country": "A", "date_from": "2010", "date_to": "2015", "extra": "second"},
        ]
        result = collapse_by_date_range(entries, label_field="country")
        assert result[0]["extra"] == "first"

    def test_exact_match_only_no_fuzzy(self):
        """'2014' and 'January 2014' are different keys — not merged."""
        entries = [
            _country("Albania", "2014",         "2018"),
            _country("Croatia", "January 2014", "2018"),
        ]
        result = collapse_by_date_range(entries, label_field="country")
        assert len(result) == 2
