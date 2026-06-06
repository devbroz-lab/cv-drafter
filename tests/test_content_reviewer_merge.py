"""
Tests for the A5 (content_reviewer) patch-contract refactor.

A5 now returns ONLY a `review` block (no CVData echo). The pipeline applies each
low_severity {path, fixed} onto a copy of the generated data, then runs the
existing deterministic post-processing. These tests monkeypatch the LLM helper.
"""

import json

from models import CVData, DistilledToR, GeneratedField, PersonalInfo, RelevantProject
from pipeline.agents import content_reviewer
from pipeline.manifest import create_manifest


def _setup_run_dir(run_dir, *, proposed_position="Expert 4: Regulatory Specialist"):
    cv = CVData(
        personal_info=PersonalInfo(first_names="Ada"),
        proposed_position=proposed_position,
        relevant_projects=[RelevantProject(project_name="P1", main_project_features="ctx")],
        generated_fields=[
            GeneratedField(
                field_key="key_qualifications",
                content="Was responsible for managing grid inspections",
                source="experience",
            )
        ],
    )
    (run_dir / "generated_fields.json").write_text(
        json.dumps({
            "approved": False, "approved_at": None,
            "generated": cv.model_dump(),
            "generation_warnings": [],
            "review": None,
            "compression": None,
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
                    params={"donor": "giz", "proposed_position": proposed_position})


class TestA5PatchMerge:
    def test_low_severity_fix_applied_to_path(self, tmp_path, monkeypatch):
        _setup_run_dir(tmp_path)

        def fake_call(**kwargs):
            return {"review": {
                "high_severity": [],
                "low_severity": [{
                    "path": "generated_fields[0].content",
                    "field": "Filler language",
                    "issue": "Contains 'responsible for'",
                    "original": "Was responsible for managing grid inspections",
                    "fixed": "Managed grid inspections across 3 provinces",
                    "solvability": "pipeline",
                }],
                "passed": True,
            }}

        monkeypatch.setattr(content_reviewer, "call_agent_json", fake_call)
        cv_out, passed = content_reviewer.run(tmp_path)

        gf = json.loads((tmp_path / "generated_fields.json").read_text(encoding="utf-8"))
        assert gf["generated"]["generated_fields"][0]["content"] == \
            "Managed grid inspections across 3 provinces"
        # Unrelated data preserved
        assert gf["generated"]["personal_info"]["first_names"] == "Ada"
        assert gf["review"] is not None
        assert passed is True

    def test_high_severity_forces_passed_false(self, tmp_path, monkeypatch):
        # Non-team-lead tier so the experience-gap injection does not fire.
        _setup_run_dir(tmp_path, proposed_position="Expert 4: Regulatory Specialist")

        def fake_call(**kwargs):
            return {"review": {
                "high_severity": [{
                    "path": "relevant_projects[0].date_from",
                    "field": "Date consistency",
                    "issue": "date_from later than date_to",
                    "recommendation": "Correct the date",
                    "solvability": "pipeline",
                }],
                "low_severity": [],
                "passed": True,  # LLM wrong on purpose
            }}

        monkeypatch.setattr(content_reviewer, "call_agent_json", fake_call)
        cv_out, passed = content_reviewer.run(tmp_path)

        gf = json.loads((tmp_path / "generated_fields.json").read_text(encoding="utf-8"))
        assert gf["review"]["passed"] is False  # enforced by _enforce_passed_field
        assert passed is False

    def test_unresolved_fix_path_skipped_not_fatal(self, tmp_path, monkeypatch):
        _setup_run_dir(tmp_path)

        def fake_call(**kwargs):
            return {"review": {
                "high_severity": [],
                "low_severity": [{
                    "path": "relevant_projects[9].main_project_features",  # out of range
                    "field": "x", "issue": "y", "original": "a", "fixed": "b",
                    "solvability": "pipeline",
                }],
                "passed": True,
            }}

        monkeypatch.setattr(content_reviewer, "call_agent_json", fake_call)
        # Should complete without raising despite the unresolved path.
        cv_out, passed = content_reviewer.run(tmp_path)
        gf = json.loads((tmp_path / "generated_fields.json").read_text(encoding="utf-8"))
        # Original content untouched (the bad-path fix was skipped).
        assert gf["generated"]["generated_fields"][0]["content"].startswith("Was responsible")
