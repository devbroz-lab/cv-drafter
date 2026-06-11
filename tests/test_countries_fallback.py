"""
Unit tests for _derive_countries_from_projects in pipeline/agents/cv_extractor.py.

Verifies the Python safety-net that derives countries_of_experience from
project / employment location fields when the LLM left the list empty:
  - one CountryExperience per country found, using that entry's date range
  - rows emitted raw (single-country, not collapsed) — A3 collapses downstream
  - idempotent; warning appended once; LLM-warning deduplicated
"""

from models import CVData, CountryExperience, EmploymentRecord, RelevantProject
from pipeline.agents.cv_extractor import _derive_countries_from_projects


def _proj(**kwargs) -> RelevantProject:
    defaults = {
        "project_name": "P",
        "location": "Nairobi, Kenya",
        "date_from": "January 2018",
        "date_to": "December 2020",
    }
    defaults.update(kwargs)
    return RelevantProject(**defaults)


def _parsed(relevant_projects=None, employment_record=None, countries=None) -> CVData:
    return CVData(
        relevant_projects=relevant_projects or [],
        employment_record=employment_record or [],
        countries_of_experience=countries or [],
    )


class TestDeriveCountriesMapping:

    def test_single_country_with_project_dates(self):
        parsed = _parsed(relevant_projects=[
            _proj(location="Essen / Germany", date_from="August 2024", date_to="Present"),
        ])
        _derive_countries_from_projects(parsed)
        assert len(parsed.countries_of_experience) == 1
        ce = parsed.countries_of_experience[0]
        assert ce.country == "Germany"
        assert ce.date_from == "August 2024"
        assert ce.date_to == "Present"

    def test_multi_country_location_one_row_each(self):
        parsed = _parsed(relevant_projects=[
            _proj(location="Sri Lanka, India, Bhutan", date_from="2022", date_to="2023"),
        ])
        _derive_countries_from_projects(parsed)
        assert [c.country for c in parsed.countries_of_experience] == [
            "Sri Lanka", "India", "Bhutan",
        ]
        # All share the project's date range.
        assert all(c.date_from == "2022" and c.date_to == "2023"
                   for c in parsed.countries_of_experience)

    def test_rows_stay_single_country(self):
        # No collapsing at A1 — each row carries exactly one country name.
        parsed = _parsed(relevant_projects=[
            _proj(location="Afghanistan, Tajikistan", date_from="2020", date_to="2022"),
        ])
        _derive_countries_from_projects(parsed)
        assert all("," not in c.country for c in parsed.countries_of_experience)

    def test_employment_record_scanned(self):
        parsed = _parsed(
            relevant_projects=[],
            employment_record=[EmploymentRecord(
                employer="GFA", country="Morocco",
                from_date="2015", to_date="2017",
            )],
        )
        _derive_countries_from_projects(parsed)
        assert [c.country for c in parsed.countries_of_experience] == ["Morocco"]
        assert parsed.countries_of_experience[0].date_from == "2015"

    def test_exact_tuple_dedup(self):
        # Same country + same range across two projects → one row.
        parsed = _parsed(relevant_projects=[
            _proj(location="Germany", date_from="2020", date_to="2021"),
            _proj(location="Germany", date_from="2020", date_to="2021"),
        ])
        _derive_countries_from_projects(parsed)
        assert len(parsed.countries_of_experience) == 1

    def test_same_country_different_ranges_kept(self):
        parsed = _parsed(relevant_projects=[
            _proj(location="Germany", date_from="2020", date_to="2021"),
            _proj(location="Germany", date_from="2018", date_to="2019"),
        ])
        _derive_countries_from_projects(parsed)
        assert len(parsed.countries_of_experience) == 2


class TestDeriveCountriesIdempotence:

    def test_does_nothing_when_already_populated(self):
        existing = [CountryExperience(country="France", date_from="2010", date_to="2012")]
        parsed = _parsed(
            relevant_projects=[_proj(location="Germany")],
            countries=existing,
        )
        _derive_countries_from_projects(parsed)
        assert [c.country for c in parsed.countries_of_experience] == ["France"]
        assert not any("Python fallback" in w for w in parsed.extraction_warnings)

    def test_does_nothing_when_no_sources(self):
        parsed = _parsed()
        _derive_countries_from_projects(parsed)
        assert parsed.countries_of_experience == []
        assert parsed.extraction_warnings == []

    def test_no_warning_when_no_country_matched(self):
        parsed = _parsed(relevant_projects=[_proj(location="Gräfenberg")])
        _derive_countries_from_projects(parsed)
        assert parsed.countries_of_experience == []
        assert not any("Python fallback" in w for w in parsed.extraction_warnings)

    def test_running_twice_is_stable(self):
        parsed = _parsed(relevant_projects=[_proj(location="Germany")])
        _derive_countries_from_projects(parsed)
        n = len(parsed.countries_of_experience)
        _derive_countries_from_projects(parsed)
        assert len(parsed.countries_of_experience) == n


class TestDeriveCountriesWarnings:

    def test_warning_appended_once(self):
        parsed = _parsed(relevant_projects=[_proj(location="Germany")])
        _derive_countries_from_projects(parsed)
        fallback = [w for w in parsed.extraction_warnings if "Python fallback" in w]
        assert len(fallback) == 1
        assert "countries_of_experience derived from" in fallback[0]

    def test_llm_derived_warning_deduplicated(self):
        # The A1 prompt's own derived-countries warning shares the marker
        # substring and must be replaced, not duplicated.
        parsed = _parsed(relevant_projects=[_proj(location="Germany")])
        parsed.extraction_warnings = [
            "countries_of_experience derived from project/employment locations — "
            "no dedicated countries section found in CV. Verify list and date ranges."
        ]
        _derive_countries_from_projects(parsed)
        derived = [w for w in parsed.extraction_warnings
                   if "countries_of_experience derived from" in w]
        assert len(derived) == 1
