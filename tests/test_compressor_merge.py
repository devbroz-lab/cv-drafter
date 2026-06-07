"""
Tests for the A6 (compressor) patch-contract refactor.

A6 now returns `compression` + a `compressed_fields` [{path, content}] patch
(no CVData echo). The pipeline applies the patch onto a copy of the
pre-compression data, recomputes the authoritative word count, and restores
protected fields. These tests monkeypatch the LLM helper.
"""

import json

from models import CVData, DistilledToR, PersonalInfo, RelevantProject
from pipeline.agents import compressor
from pipeline.manifest import create_manifest


def _setup_run_dir(run_dir, *, donor="giz"):
    proj = RelevantProject(
        project_name="P1",
        main_project_features=" ".join(["context"] * 25),  # long enough to force compression
        activities_performed="Original activities text that should be preserved on GIZ",
    )
    cv = CVData(personal_info=PersonalInfo(first_names="Ada"), relevant_projects=[proj])
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
    tor = DistilledToR(position_title="Engineer")
    (run_dir / "tor_data.json").write_text(
        json.dumps({"approved": False, "approved_at": None,
                    "pools": [tor.model_dump()], "selected_pool_index": 0}),
        encoding="utf-8",
    )
    create_manifest(run_dir, run_id="t", cv_path="", tor_path="", params={"donor": donor})


class TestA6PatchMerge:
    def test_giz_compressed_field_applied_activities_preserved(self, tmp_path, monkeypatch):
        _setup_run_dir(tmp_path, donor="giz")

        def fake_call(**kwargs):
            return {
                "compression": {
                    "applied": True, "words_before": 0, "words_after": 0,
                    "target_words": 10, "ratio_applied": False,
                    "target_not_reached": False, "fields_shortened": [],
                },
                "compressed_fields": [
                    {"path": "relevant_projects[0].main_project_features", "content": "Short context."}
                ],
                "generation_warnings": [],
            }

        monkeypatch.setattr(compressor, "call_agent_json", fake_call)
        # target_words=10 forces the LLM path (current_words > 10).
        cv_out = compressor.run(tmp_path, target_words=10)

        gf = json.loads((tmp_path / "generated_fields.json").read_text(encoding="utf-8"))
        g = gf["generated"]
        assert g["relevant_projects"][0]["main_project_features"] == "Short context."
        # GIZ: activities_performed preserved from the pre-compression input.
        assert g["relevant_projects"][0]["activities_performed"] == \
            "Original activities text that should be preserved on GIZ"
        # Authoritative words_after recomputed by Python (LLM sent 0).
        assert gf["compression"]["words_after"] > 0
        assert g["personal_info"]["first_names"] == "Ada"

    def test_wb_activities_is_compressible(self, tmp_path, monkeypatch):
        _setup_run_dir(tmp_path, donor="world_bank")

        def fake_call(**kwargs):
            return {
                "compression": {
                    "applied": True, "words_before": 0, "words_after": 0,
                    "target_words": 10, "ratio_applied": False,
                    "target_not_reached": False, "fields_shortened": [],
                },
                "compressed_fields": [
                    {"path": "relevant_projects[0].activities_performed", "content": "Tight activities."}
                ],
                "generation_warnings": [],
            }

        monkeypatch.setattr(compressor, "call_agent_json", fake_call)
        compressor.run(tmp_path, target_words=10)

        g = json.loads((tmp_path / "generated_fields.json").read_text(encoding="utf-8"))["generated"]
        assert g["relevant_projects"][0]["activities_performed"] == "Tight activities."

    def test_unresolved_compressed_path_skipped(self, tmp_path, monkeypatch):
        _setup_run_dir(tmp_path, donor="giz")

        def fake_call(**kwargs):
            return {
                "compression": {
                    "applied": True, "words_before": 0, "words_after": 0,
                    "target_words": 10, "ratio_applied": False,
                    "target_not_reached": False, "fields_shortened": [],
                },
                "compressed_fields": [
                    {"path": "relevant_projects[9].main_project_features", "content": "x"}
                ],
                "generation_warnings": [],
            }

        monkeypatch.setattr(compressor, "call_agent_json", fake_call)
        # Should not raise despite the out-of-range path.
        compressor.run(tmp_path, target_words=10)
        g = json.loads((tmp_path / "generated_fields.json").read_text(encoding="utf-8"))["generated"]
        # Original main_project_features unchanged (bad-path patch skipped).
        assert g["relevant_projects"][0]["main_project_features"].startswith("context")
