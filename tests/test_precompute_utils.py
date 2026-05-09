"""
Tests for pipeline/precompute_utils.py

Covers:
  - count_words
  - count_words_per_field / count_compressible_words_total
  - compute_project_duration
  - compute_project_year
  - restore_protected_fields
"""

import pytest
from pipeline.precompute_utils import (
    compute_project_duration,
    compute_project_year,
    count_compressible_words_total,
    count_words,
    count_words_per_field,
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
        result = compute_project_duration("January 2020", "Present")
        # 2026-01 minus 2020-01 = 72 months = 6 years
        assert result == "6 years"

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
        result = compute_project_year("January 2020", "Present")
        assert result == f"2020\u2013{2026}"

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
