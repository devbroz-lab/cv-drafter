"""
Unit tests for _apply_employment_fallback in pipeline/agents/cv_extractor.py.

Verifies that the Python safety-net correctly maps employment_record entries
to relevant_projects with the right field routing:
  - description  → main_project_features
  - activities_performed is always left empty
  - employer     → project_name AND company
  - client/donor stay ""
  - short-description warning references main_project_features
"""

import pytest

from models import CVData, EmploymentRecord, RelevantProject
from pipeline.agents.cv_extractor import _apply_employment_fallback


def _make_emp(**kwargs) -> EmploymentRecord:
    defaults = {
        "employer": "Acme Corp",
        "positions_held": "Senior Consultant",
        "description": "Led institutional reform across water sector.",
        "from_date": "January 2018",
        "to_date": "December 2020",
        "country": "Kenya",
        "location": "",
    }
    defaults.update(kwargs)
    return EmploymentRecord(**defaults)


def _make_parsed(employment_record=None, relevant_projects=None) -> CVData:
    emp = employment_record or []
    proj = relevant_projects or []
    return CVData(employment_record=emp, relevant_projects=proj)


class TestApplyEmploymentFallbackFieldMapping:

    def test_main_project_features_receives_description(self):
        emp = _make_emp(description="Led water sector reform.")
        parsed = _make_parsed(employment_record=[emp])
        _apply_employment_fallback(parsed)
        assert parsed.relevant_projects[0].main_project_features == "Led water sector reform."

    def test_activities_performed_is_empty(self):
        emp = _make_emp(description="Led water sector reform.")
        parsed = _make_parsed(employment_record=[emp])
        _apply_employment_fallback(parsed)
        assert parsed.relevant_projects[0].activities_performed == ""

    def test_project_name_from_employer(self):
        emp = _make_emp(employer="WorldBank Ltd")
        parsed = _make_parsed(employment_record=[emp])
        _apply_employment_fallback(parsed)
        assert parsed.relevant_projects[0].project_name == "WorldBank Ltd"

    def test_company_from_employer(self):
        emp = _make_emp(employer="WorldBank Ltd")
        parsed = _make_parsed(employment_record=[emp])
        _apply_employment_fallback(parsed)
        assert parsed.relevant_projects[0].company == "WorldBank Ltd"

    def test_client_is_empty(self):
        emp = _make_emp()
        parsed = _make_parsed(employment_record=[emp])
        _apply_employment_fallback(parsed)
        assert parsed.relevant_projects[0].client == ""

    def test_donor_is_empty(self):
        emp = _make_emp()
        parsed = _make_parsed(employment_record=[emp])
        _apply_employment_fallback(parsed)
        assert parsed.relevant_projects[0].donor == ""

    def test_positions_held_mapped(self):
        emp = _make_emp(positions_held="Team Leader")
        parsed = _make_parsed(employment_record=[emp])
        _apply_employment_fallback(parsed)
        assert parsed.relevant_projects[0].positions_held == "Team Leader"

    def test_location_from_location_field(self):
        emp = _make_emp(location="Nairobi", country="Kenya")
        parsed = _make_parsed(employment_record=[emp])
        _apply_employment_fallback(parsed)
        assert parsed.relevant_projects[0].location == "Nairobi"

    def test_location_falls_back_to_country(self):
        emp = _make_emp(location="", country="Kenya")
        parsed = _make_parsed(employment_record=[emp])
        _apply_employment_fallback(parsed)
        assert parsed.relevant_projects[0].location == "Kenya"

    def test_multiple_entries_mapped(self):
        emps = [_make_emp(employer=f"Org{i}") for i in range(3)]
        parsed = _make_parsed(employment_record=emps)
        _apply_employment_fallback(parsed)
        assert len(parsed.relevant_projects) == 3


class TestApplyEmploymentFallbackIdempotence:

    def test_does_nothing_when_relevant_projects_non_empty(self):
        emp = _make_emp()
        existing = RelevantProject(project_name="ExistingProject")
        parsed = _make_parsed(employment_record=[emp], relevant_projects=[existing])
        _apply_employment_fallback(parsed)
        assert len(parsed.relevant_projects) == 1
        assert parsed.relevant_projects[0].project_name == "ExistingProject"

    def test_does_nothing_when_no_employment_record(self):
        parsed = _make_parsed(employment_record=[], relevant_projects=[])
        _apply_employment_fallback(parsed)
        assert parsed.relevant_projects == []


class TestApplyEmploymentFallbackWarnings:

    def test_fallback_warning_appended(self):
        emp = _make_emp(description="Led water sector reform in Kenya.")
        parsed = _make_parsed(employment_record=[emp])
        _apply_employment_fallback(parsed)
        assert any("Python fallback" in w for w in parsed.extraction_warnings)

    def test_short_description_warning_references_main_project_features(self):
        emp = _make_emp(description="Short text")  # < 5 words
        parsed = _make_parsed(employment_record=[emp])
        _apply_employment_fallback(parsed)
        short_warnings = [w for w in parsed.extraction_warnings if "from employment record" in w]
        assert len(short_warnings) == 1
        assert "main_project_features" in short_warnings[0]
        assert "activities_performed" not in short_warnings[0]

    def test_adequate_description_no_short_warning(self):
        emp = _make_emp(description="Led water sector institutional reform across three provinces.")
        parsed = _make_parsed(employment_record=[emp])
        _apply_employment_fallback(parsed)
        short_warnings = [w for w in parsed.extraction_warnings if "from employment record" in w]
        assert len(short_warnings) == 0

    def test_duplicate_fallback_warning_deduplicated(self):
        emp = _make_emp()
        parsed = _make_parsed(employment_record=[emp])
        parsed.extraction_warnings = [
            "No dedicated project section found — relevant_projects populated from employment_record entries for pipeline compatibility."
        ]
        _apply_employment_fallback(parsed)
        fallback_warnings = [w for w in parsed.extraction_warnings if "Python fallback" in w]
        assert len(fallback_warnings) == 1
