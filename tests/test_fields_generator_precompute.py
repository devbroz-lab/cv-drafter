"""
Tests for the project date pre-compute helper in fields_generator.py.

Note (Round 5 — Fix 4): The CALL SITE for this pre-compute moved upstream
to cv_tor_mapper.run() so that A3's LLM can see duration as a scoring signal.
The _precompute_project_dates helper remains in fields_generator.py for
backward compatibility and is no longer called from fields_generator.run().
The equivalent helper in cv_tor_mapper.py is _precompute_project_dates_for_mapper.

Verifies that _precompute_project_dates (the legacy helper):
  - fills empty duration and year fields using Python helpers
  - never overwrites non-empty existing values
  - handles missing/partial dates gracefully
  - does not mutate the original cv_data dict
"""

import pytest
from pipeline.agents.fields_generator import _precompute_project_dates


class TestPrecomputeProjectDates:
    def _make_cv(self, projects: list[dict]) -> dict:
        return {"relevant_projects": projects}

    def test_fills_empty_duration_and_year(self):
        cv = self._make_cv([{
            "date_from": "January 2018",
            "date_to": "January 2020",
            "duration": "",
            "year": "",
        }])
        result = _precompute_project_dates(cv)
        proj = result["relevant_projects"][0]
        assert proj["duration"] == "2 years"
        assert proj["year"] == "2018\u20132020"

    def test_does_not_overwrite_existing_duration(self):
        cv = self._make_cv([{
            "date_from": "January 2018",
            "date_to": "January 2020",
            "duration": "Existing value",
            "year": "",
        }])
        result = _precompute_project_dates(cv)
        proj = result["relevant_projects"][0]
        assert proj["duration"] == "Existing value"
        # year is empty → should be filled
        assert proj["year"] == "2018\u20132020"

    def test_does_not_overwrite_existing_year(self):
        cv = self._make_cv([{
            "date_from": "January 2018",
            "date_to": "January 2020",
            "duration": "",
            "year": "2018–2020",
        }])
        result = _precompute_project_dates(cv)
        proj = result["relevant_projects"][0]
        assert proj["year"] == "2018–2020"

    def test_missing_dates_leaves_fields_empty(self):
        cv = self._make_cv([{
            "date_from": "",
            "date_to": "",
            "duration": "",
            "year": "",
        }])
        result = _precompute_project_dates(cv)
        proj = result["relevant_projects"][0]
        assert proj["duration"] == ""
        assert proj["year"] == ""

    def test_present_date_to(self):
        cv = self._make_cv([{
            "date_from": "January 2020",
            "date_to": "Present",
            "duration": "",
            "year": "",
        }])
        result = _precompute_project_dates(cv)
        proj = result["relevant_projects"][0]
        assert proj["duration"] != ""  # some computed value
        assert "2020" in proj["year"]

    def test_does_not_mutate_original(self):
        cv = self._make_cv([{
            "date_from": "January 2018",
            "date_to": "January 2020",
            "duration": "",
            "year": "",
        }])
        original_duration = cv["relevant_projects"][0]["duration"]
        _precompute_project_dates(cv)
        assert cv["relevant_projects"][0]["duration"] == original_duration

    def test_multiple_projects(self):
        cv = self._make_cv([
            {"date_from": "2015", "date_to": "2017", "duration": "", "year": ""},
            {"date_from": "2018", "date_to": "2021", "duration": "", "year": ""},
        ])
        result = _precompute_project_dates(cv)
        assert result["relevant_projects"][0]["duration"] == "2 years"
        assert result["relevant_projects"][1]["duration"] == "3 years"
        assert result["relevant_projects"][0]["year"] == "2015\u20132017"
        assert result["relevant_projects"][1]["year"] == "2018\u20132021"

    def test_no_projects_is_safe(self):
        cv = {"relevant_projects": []}
        result = _precompute_project_dates(cv)
        assert result["relevant_projects"] == []

    def test_cv_without_projects_key(self):
        cv: dict = {}
        result = _precompute_project_dates(cv)
        assert result.get("relevant_projects", []) == []
