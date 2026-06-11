"""
Tests for render-time "[Not found in source CV]" placeholders in the GIZ and
World Bank renderers (_build_context). Placeholders apply only to donor-required
fields; non-required empty fields stay empty.
"""

from models import (
    CountryExperience,
    CVData,
    Education,
    EmploymentRecord,
    LanguageProficiency,
    PersonalInfo,
    RelevantProject,
)
from templates.base import NOT_FOUND_PLACEHOLDER
from templates import giz, wb

PH = NOT_FOUND_PLACEHOLDER


def _empty_cv() -> dict:
    # A project is present so the relevant_projects table renders, but all
    # required identity/section fields are empty.
    return CVData(relevant_projects=[RelevantProject(project_name="P1")]).model_dump()


def _full_cv() -> dict:
    return CVData(
        personal_info=PersonalInfo(
            nationality="German", date_of_birth="July 7 1980",
            place_of_residence="Berlin, Germany",
        ),
        education=[Education(institution="MIT", degree="MSc")],
        languages=[LanguageProficiency(language="English", reading_raw="Fluent")],
        countries_of_experience=[CountryExperience(country="Germany", date_from="2020", date_to="2021")],
        employment_record=[EmploymentRecord(employer="GFA", country="Germany")],
        relevant_projects=[RelevantProject(project_name="P1", client="")],
    ).model_dump()


class TestGizPlaceholders:
    def test_scalar_placeholders(self):
        ctx = giz._build_context(_empty_cv())
        assert ctx["personal_info"]["date_of_birth"] == PH
        assert ctx["personal_info"]["place_of_residence"] == PH
        assert ctx["nationality_display"] == PH

    def test_empty_required_tables_get_one_placeholder_row(self):
        ctx = giz._build_context(_empty_cv())
        assert len(ctx["education"]) == 1
        assert ctx["education"][0]["institution"] == PH
        assert len(ctx["languages"]) == 1
        assert ctx["languages"][0]["language"] == PH
        assert len(ctx["countries_of_experience"]) == 1
        assert ctx["countries_of_experience"][0]["country"] == PH

    def test_populated_values_untouched(self):
        ctx = giz._build_context(_full_cv())
        assert ctx["personal_info"]["date_of_birth"] == "July 7 1980"
        assert ctx["nationality_display"] == "German"
        assert len(ctx["education"]) == 1
        assert ctx["education"][0]["institution"] == "MIT"
        assert ctx["countries_of_experience"][0]["country"] == "Germany"

    def test_non_required_empty_field_stays_empty(self):
        ctx = giz._build_context(_empty_cv())
        # project client is empty and NOT required → never a placeholder
        assert ctx["relevant_projects"][0]["client"] == ""


class TestWbPlaceholders:
    def test_scalar_placeholders(self):
        ctx = wb._build_context(_empty_cv())
        assert ctx["personal_info"]["date_of_birth"] == PH
        assert ctx["personal_info"]["nationality"] == PH
        assert ctx["countries_display"] == PH

    def test_empty_required_tables_get_one_placeholder_row(self):
        ctx = wb._build_context(_empty_cv())
        assert len(ctx["education"]) == 1 and ctx["education"][0]["institution"] == PH
        assert len(ctx["languages"]) == 1 and ctx["languages"][0]["language"] == PH
        assert len(ctx["employment_record"]) == 1
        assert ctx["employment_record"][0]["employer"] == PH

    def test_populated_values_untouched(self):
        ctx = wb._build_context(_full_cv())
        assert ctx["personal_info"]["nationality"] == "German"
        assert ctx["countries_display"] == "Germany"
        assert ctx["employment_record"][0]["employer"] == "GFA"


class TestLegacyOtherSkillsList:
    """Renderers read raw artifact JSON, so a pre-change legacy list value for
    other_skills must not crash _build_context (it is coerced to a string)."""

    def test_giz_coerces_legacy_list(self):
        cv = _empty_cv()
        cv["other_skills"] = ["Python", "GIS"]
        ctx = giz._build_context(cv)
        assert ctx["other_skills_display"] == "Python; GIS"

    def test_wb_coerces_legacy_list(self):
        cv = _empty_cv()
        cv["other_skills"] = ["Python", "GIS"]
        ctx = wb._build_context(cv)
        assert ctx["other_skills_display"] == "Python; GIS"
