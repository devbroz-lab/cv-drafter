"""
Tests for the *_for_manifest warning readers in pipeline/validators.py that
backfill agent warnings (extraction / alignment / generation / review) into
manifest.json so they stream on the polled /manifest channel.
"""

import json

from pipeline.validators import (
    alignment_warnings_for_manifest,
    extraction_warnings_for_manifest,
    generation_warnings_for_manifest,
    review_summary_for_manifest,
)


def _write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


class TestExtractionWarnings:
    def test_reads_and_tags_stage(self, tmp_path):
        _write(tmp_path / "cv_data.json", {"data": {"extraction_warnings": ["w1", "w2"]}})
        out = extraction_warnings_for_manifest(tmp_path)
        assert [w["message"] for w in out] == ["w1", "w2"]
        assert all(w["stage"] == "cv_extractor" for w in out)
        assert all(w["kind"] == "extraction_warning" for w in out)

    def test_missing_file_returns_empty(self, tmp_path):
        assert extraction_warnings_for_manifest(tmp_path) == []

    def test_empty_list_returns_empty(self, tmp_path):
        _write(tmp_path / "cv_data.json", {"data": {"extraction_warnings": []}})
        assert extraction_warnings_for_manifest(tmp_path) == []

    def test_blank_messages_skipped(self, tmp_path):
        _write(tmp_path / "cv_data.json", {"data": {"extraction_warnings": ["", "  ", "real"]}})
        out = extraction_warnings_for_manifest(tmp_path)
        assert [w["message"] for w in out] == ["real"]


class TestAlignmentWarnings:
    def test_reads_and_tags_stage(self, tmp_path):
        _write(tmp_path / "mapped_cv.json", {"alignment": {"warnings": ["dropped 3 projects"]}})
        out = alignment_warnings_for_manifest(tmp_path)
        assert out[0]["stage"] == "cv_tor_mapper"
        assert out[0]["kind"] == "alignment_warning"
        assert out[0]["message"] == "dropped 3 projects"

    def test_missing_file_returns_empty(self, tmp_path):
        assert alignment_warnings_for_manifest(tmp_path) == []


class TestGenerationWarnings:
    def test_reads_and_tags_stage(self, tmp_path):
        _write(tmp_path / "generated_fields.json", {"generation_warnings": ["low-confidence bullet"]})
        out = generation_warnings_for_manifest(tmp_path)
        assert out[0]["stage"] == "fields_generator"
        assert out[0]["kind"] == "generation_warning"

    def test_missing_file_returns_empty(self, tmp_path):
        assert generation_warnings_for_manifest(tmp_path) == []


class TestReviewSummary:
    def test_summarises_findings(self, tmp_path):
        _write(tmp_path / "generated_fields.json", {
            "review": {
                "high_severity": [{"issue": "x"}, {"issue": "y"}],
                "low_severity": [{"issue": "z"}],
                "passed": False,
            }
        })
        out = review_summary_for_manifest(tmp_path)
        assert len(out) == 1
        entry = out[0]
        assert entry["stage"] == "content_reviewer"
        assert entry["kind"] == "review_findings"
        assert entry["message"] == "2 high / 1 low severity finding(s)"
        assert entry["details"] == {"high": 2, "low": 1, "passed": False}

    def test_no_findings_returns_empty(self, tmp_path):
        _write(tmp_path / "generated_fields.json", {
            "review": {"high_severity": [], "low_severity": [], "passed": True}
        })
        assert review_summary_for_manifest(tmp_path) == []

    def test_no_review_block_returns_empty(self, tmp_path):
        _write(tmp_path / "generated_fields.json", {"review": None})
        assert review_summary_for_manifest(tmp_path) == []

    def test_missing_file_returns_empty(self, tmp_path):
        assert review_summary_for_manifest(tmp_path) == []
