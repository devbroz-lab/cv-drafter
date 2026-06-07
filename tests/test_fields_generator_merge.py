"""
Tests for the A4 (Fields Generator) output-contract refactor.

A4 now returns a PATCH ({generated_fields, present_position, project_overviews,
generation_warnings}) instead of echoing the full CVData. The pipeline merges
the patch into the mapped CVData. These tests monkeypatch the LLM helper so no
network call is made.
"""

import json

import pytest

from models import CVData, DistilledToR, PersonalInfo, RelevantProject
from pipeline import validators
from pipeline.agents import fields_generator
from pipeline.manifest import create_manifest


def _setup_run_dir(run_dir):
    proj = RelevantProject(
        project_name="P1",
        activities_performed="Led grid inspections across three provinces.",
        main_project_features="",  # empty → eligible for an overview patch
    )
    cv = CVData(
        personal_info=PersonalInfo(first_names="Ada"),
        present_position="",  # empty → eligible to be filled
        relevant_projects=[proj],
    )
    (run_dir / "mapped_cv.json").write_text(
        json.dumps({"approved": False, "approved_at": None, "data": cv.model_dump()}),
        encoding="utf-8",
    )
    tor = DistilledToR(position_title="Engineer")
    (run_dir / "tor_data.json").write_text(
        json.dumps({
            "approved": False, "approved_at": None,
            "pools": [tor.model_dump()], "selected_pool_index": 0,
        }),
        encoding="utf-8",
    )
    create_manifest(run_dir, run_id="t", cv_path="", tor_path="", params={"donor": "giz"})


class TestPatchMerge:
    def test_patch_merges_into_full_cvdata(self, tmp_path, monkeypatch):
        _setup_run_dir(tmp_path)

        def fake_call(**kwargs):
            return {
                "generated_fields": [
                    {"field_key": "key_qualifications", "content": "KQ bullet", "source": "experience"}
                ],
                "present_position": "Senior Engineer",
                "project_overviews": [
                    {"index": 0, "main_project_features": "Project overview text."}
                ],
                "generation_warnings": [],
            }

        monkeypatch.setattr(fields_generator, "call_agent_json", fake_call)
        fields_generator.run(tmp_path)

        gf = json.loads((tmp_path / "generated_fields.json").read_text(encoding="utf-8"))
        g = gf["generated"]
        assert g["generated_fields"][0]["content"] == "KQ bullet"
        assert g["present_position"] == "Senior Engineer"
        assert g["relevant_projects"][0]["main_project_features"] == "Project overview text."
        # Unrelated input fields preserved verbatim.
        assert g["personal_info"]["first_names"] == "Ada"

    def test_present_position_not_overwritten_when_already_set(self, tmp_path, monkeypatch):
        _setup_run_dir(tmp_path)
        # Pre-set present_position in the mapped data.
        mapped = json.loads((tmp_path / "mapped_cv.json").read_text(encoding="utf-8"))
        mapped["data"]["present_position"] = "Existing Title"
        (tmp_path / "mapped_cv.json").write_text(json.dumps(mapped), encoding="utf-8")

        def fake_call(**kwargs):
            return {
                "generated_fields": [
                    {"field_key": "key_qualifications", "content": "x", "source": "tor"}
                ],
                "present_position": "Should Not Win",
                "project_overviews": [],
                "generation_warnings": [],
            }

        monkeypatch.setattr(fields_generator, "call_agent_json", fake_call)
        fields_generator.run(tmp_path)

        g = json.loads((tmp_path / "generated_fields.json").read_text(encoding="utf-8"))["generated"]
        assert g["present_position"] == "Existing Title"

    def test_empty_generated_fields_triggers_hard_block_validator(self, tmp_path, monkeypatch):
        _setup_run_dir(tmp_path)

        def fake_call(**kwargs):
            return {"generated_fields": [], "generation_warnings": []}

        monkeypatch.setattr(fields_generator, "call_agent_json", fake_call)
        # run() itself succeeds (merge of empty list is valid)…
        fields_generator.run(tmp_path)
        # …but the orchestrator's hard-block validator rejects all-empty content.
        with pytest.raises(validators.PipelineValidationError):
            validators.validate_fields_generator_output(tmp_path)


def _setup_donor(run_dir, *, donor, mpf, activities="Led grid work."):
    proj = RelevantProject(
        project_name="P1",
        main_project_features=mpf,
        activities_performed=activities,
    )
    cv = CVData(personal_info=PersonalInfo(first_names="Ada"), relevant_projects=[proj])
    (run_dir / "mapped_cv.json").write_text(
        json.dumps({"approved": False, "approved_at": None, "data": cv.model_dump()}),
        encoding="utf-8",
    )
    tor = DistilledToR(position_title="Engineer")
    (run_dir / "tor_data.json").write_text(
        json.dumps({"approved": False, "approved_at": None,
                    "pools": [tor.model_dump()], "selected_pool_index": 0}),
        encoding="utf-8",
    )
    create_manifest(run_dir, run_id="t", cv_path="", tor_path="", params={"donor": donor})


def _kq_patch(overview_text):
    return {
        "generated_fields": [
            {"field_key": "key_qualifications", "content": "KQ bullet", "source": "experience"}
        ],
        "present_position": "",
        "project_overviews": [{"index": 0, "main_project_features": overview_text}],
        "generation_warnings": [],
    }


class TestProjectOverviewDonorBehaviour:
    def test_giz_overwrites_nonempty_main_project_features(self, tmp_path, monkeypatch):
        # GIZ renders only main_project_features → A4 narrative OVERWRITES the
        # existing terse extraction.
        _setup_donor(tmp_path, donor="giz", mpf="Terse extracted summary.")
        monkeypatch.setattr(fields_generator, "call_agent_json",
                            lambda **kw: _kq_patch("Rich GIZ narrative weaving context and role."))
        fields_generator.run(tmp_path)
        g = json.loads((tmp_path / "generated_fields.json").read_text(encoding="utf-8"))["generated"]
        assert g["relevant_projects"][0]["main_project_features"] == \
            "Rich GIZ narrative weaving context and role."

    def test_wb_does_not_overwrite_nonempty_main_project_features(self, tmp_path, monkeypatch):
        # WB renders the fields separately → fill-empty-only; a non-empty mpf is kept.
        _setup_donor(tmp_path, donor="world_bank", mpf="Existing WB project context.")
        monkeypatch.setattr(fields_generator, "call_agent_json",
                            lambda **kw: _kq_patch("Should be ignored for WB"))
        fields_generator.run(tmp_path)
        g = json.loads((tmp_path / "generated_fields.json").read_text(encoding="utf-8"))["generated"]
        assert g["relevant_projects"][0]["main_project_features"] == "Existing WB project context."

    def test_wb_fills_empty_main_project_features(self, tmp_path, monkeypatch):
        _setup_donor(tmp_path, donor="world_bank", mpf="")
        monkeypatch.setattr(fields_generator, "call_agent_json",
                            lambda **kw: _kq_patch("Filled WB overview."))
        fields_generator.run(tmp_path)
        g = json.loads((tmp_path / "generated_fields.json").read_text(encoding="utf-8"))["generated"]
        assert g["relevant_projects"][0]["main_project_features"] == "Filled WB overview."
