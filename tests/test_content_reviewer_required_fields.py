"""
Tests for the empty-required-field "human review" injector in
pipeline/agents/content_reviewer.py (Feature: empty-field flags).

Covers the donor-aware injector directly and through _apply_post_processing,
plus one integration test through content_reviewer.run with a monkeypatched LLM.
"""

import json

from models import (
    CountryExperience,
    CVData,
    DistilledToR,
    Education,
    GeneratedField,
    LanguageProficiency,
    PersonalInfo,
    RelevantProject,
)
from pipeline.agents import content_reviewer
from pipeline.agents.content_reviewer import (
    _apply_post_processing,
    _inject_empty_required_field_findings,
    _is_empty_value,
)
from pipeline.manifest import create_manifest


def _empty_review():
    return {"high_severity": [], "low_severity": [], "passed": True}


def _full_giz_cv() -> dict:
    """A CV with every GIZ-required field populated."""
    return CVData(
        personal_info=PersonalInfo(
            first_names="Ada",
            nationality="German",
            date_of_birth="July 7 1980",
            place_of_residence="Berlin, Germany",
        ),
        education=[Education(institution="MIT", degree="MSc")],
        languages=[LanguageProficiency(language="English", reading_raw="Fluent")],
        countries_of_experience=[CountryExperience(country="Germany")],
        relevant_projects=[RelevantProject(project_name="P1")],
    ).model_dump()


class TestIsEmptyValue:
    def test_none_blank_and_empty_list(self):
        assert _is_empty_value(None)
        assert _is_empty_value("")
        assert _is_empty_value("   ")
        assert _is_empty_value([])

    def test_non_empty(self):
        assert not _is_empty_value("x")
        assert not _is_empty_value(["a"])


class TestInjectorBasics:
    def test_empty_cv_flags_all_giz_required(self):
        review = _empty_review()
        cv = CVData().model_dump()
        injected = _inject_empty_required_field_findings(review, cv, "giz")
        paths = {f["path"] for f in injected}
        assert paths == {
            "personal_info.date_of_birth",
            "personal_info.nationality",
            "personal_info.place_of_residence",
            "countries_of_experience",
            "education",
            "languages",
        }

    def test_finding_shape(self):
        review = _empty_review()
        injected = _inject_empty_required_field_findings(review, CVData().model_dump(), "giz")
        f = injected[0]
        assert f["solvability"] == "human"
        assert f["_injected_by_postprocessing"] is True
        assert f["field"] and f["issue"] and f["recommendation"]
        # appended to the review's high_severity list too
        assert f in review["high_severity"]

    def test_full_cv_injects_nothing(self):
        review = _empty_review()
        injected = _inject_empty_required_field_findings(review, _full_giz_cv(), "giz")
        assert injected == []


class TestDonorAwareness:
    def test_place_of_residence_giz_only(self):
        cv = CVData().model_dump()
        giz = {f["path"] for f in _inject_empty_required_field_findings(_empty_review(), cv, "giz")}
        wb = {f["path"] for f in _inject_empty_required_field_findings(_empty_review(), cv, "world_bank")}
        assert "personal_info.place_of_residence" in giz
        assert "personal_info.place_of_residence" not in wb

    def test_employment_record_wb_only(self):
        cv = CVData().model_dump()
        giz = {f["path"] for f in _inject_empty_required_field_findings(_empty_review(), cv, "giz")}
        wb = {f["path"] for f in _inject_empty_required_field_findings(_empty_review(), cv, "world_bank")}
        assert "employment_record" in wb
        assert "employment_record" not in giz

    def test_unknown_donor_falls_back_to_giz(self):
        cv = CVData().model_dump()
        unknown = {f["path"] for f in _inject_empty_required_field_findings(_empty_review(), cv, "acme")}
        giz = {f["path"] for f in _inject_empty_required_field_findings(_empty_review(), cv, "giz")}
        assert unknown == giz


class TestAlsoAcceptAndDedup:
    def test_nationality_second_suppresses_flag(self):
        cv = CVData(
            personal_info=PersonalInfo(nationality="", nationality_second="French"),
        ).model_dump()
        paths = {f["path"] for f in _inject_empty_required_field_findings(_empty_review(), cv, "giz")}
        assert "personal_info.nationality" not in paths

    def test_dedup_by_path(self):
        review = {
            "high_severity": [
                {"path": "personal_info.nationality", "field": "x", "issue": "y"}
            ],
            "low_severity": [],
            "passed": True,
        }
        injected = _inject_empty_required_field_findings(review, CVData().model_dump(), "giz")
        assert all(f["path"] != "personal_info.nationality" for f in injected)

    def test_dedup_by_field_text(self):
        review = {
            "high_severity": [
                {"path": "", "field": "Date of birth",
                 "issue": "The date of birth is missing from the CV."}
            ],
            "low_severity": [],
            "passed": True,
        }
        injected = _inject_empty_required_field_findings(review, CVData().model_dump(), "giz")
        assert all(f["path"] != "personal_info.date_of_birth" for f in injected)


class TestApplyPostProcessing:
    def test_forces_passed_false_and_records_audit(self):
        review = _empty_review()
        audit = _apply_post_processing(review, {"donor": "giz"}, CVData().model_dump())
        assert review["passed"] is False
        assert len(audit["empty_required_field_injections"]) == 6

    def test_full_cv_keeps_passed_true(self):
        review = _empty_review()
        audit = _apply_post_processing(review, {"donor": "giz"}, _full_giz_cv())
        assert audit["empty_required_field_injections"] == []
        assert review["passed"] is True


class TestIntegrationThroughRun:
    def _setup(self, run_dir, cv: CVData):
        (run_dir / "generated_fields.json").write_text(
            json.dumps({
                "approved": False, "approved_at": None,
                "generated": cv.model_dump(),
                "generation_warnings": [],
                "review": None, "compression": None,
            }),
            encoding="utf-8",
        )
        tor = DistilledToR(position_title="Regulatory Specialist")
        (run_dir / "tor_data.json").write_text(
            json.dumps({"approved": False, "approved_at": None,
                        "pools": [tor.model_dump()], "selected_pool_index": 0}),
            encoding="utf-8",
        )
        create_manifest(run_dir, run_id="t", cv_path="", tor_path="",
                        params={"donor": "giz", "proposed_position": "Expert 4: Specialist"})

    def test_empty_fields_block_and_surface_in_review(self, tmp_path, monkeypatch):
        cv = CVData(
            personal_info=PersonalInfo(first_names="Ada"),  # everything else empty
            relevant_projects=[RelevantProject(project_name="P1")],
            generated_fields=[GeneratedField(
                field_key="key_qualifications", content="x", source="experience")],
        )
        self._setup(tmp_path, cv)

        def fake_call(**kwargs):
            return {"review": {"high_severity": [], "low_severity": [], "passed": True}}

        monkeypatch.setattr(content_reviewer, "call_agent_json", fake_call)
        _, passed = content_reviewer.run(tmp_path)

        gf = json.loads((tmp_path / "generated_fields.json").read_text(encoding="utf-8"))
        injected = [h for h in gf["review"]["high_severity"]
                    if h.get("_injected_by_postprocessing")]
        assert injected, "expected empty-field findings in the review block"
        assert gf["review"]["passed"] is False
        assert passed is False
