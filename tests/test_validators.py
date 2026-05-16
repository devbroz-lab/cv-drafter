"""
Tests for pipeline/validators.py — hard-block validators and soft-flag checks.

Covers validate_fields_generator_output (hard-block):
  - All entries empty → raises PipelineValidationError with correct stage/details.
  - At least one non-empty entry → returns silently (passes).
  - Empty generated_fields list (no entries at all) → raises.
  - Missing generated_fields.json → raises clearly.
  - Malformed JSON → raises clearly.
  - details dict has correct counts and donor info when manifest is present.
  - Whitespace-only content is treated as empty.
  - PipelineValidationError __str__ includes stage, message, details.

Covers check_fields_generator_warnings, check_content_reviewer_warnings,
check_compressor_warnings (Fix 5b soft flags):
  - Missing file → returns [] (no crash).
  - Healthy output → returns [].
  - Each warning condition triggers the expected entry.
"""

import json
import pytest
from pathlib import Path

from pipeline.validators import (
    PipelineValidationError,
    validate_fields_generator_output,
    check_fields_generator_warnings,
    check_content_reviewer_warnings,
    check_compressor_warnings,
    check_tor_summarizer_warnings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_gf(tmp_path: Path, entries: list[dict], donor: str = "giz") -> None:
    """Write a minimal generated_fields.json into tmp_path."""
    gf = {
        "generated": {
            "generated_fields": entries,
            "proposed_position": "Energy Specialist",
        }
    }
    (tmp_path / "generated_fields.json").write_text(
        json.dumps(gf, indent=2), encoding="utf-8"
    )


def _write_manifest(tmp_path: Path, donor: str = "giz") -> None:
    """Write a minimal manifest.json with the given donor."""
    manifest = {"params": {"donor": donor}, "steps": []}
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# PipelineValidationError
# ---------------------------------------------------------------------------

class TestPipelineValidationError:
    def test_attributes(self):
        exc = PipelineValidationError(
            stage="fields_generator",
            message="all empty",
            details={"total_entries": 3, "non_empty_entries": 0},
        )
        assert exc.stage == "fields_generator"
        assert exc.message == "all empty"
        assert exc.details["total_entries"] == 3

    def test_str_includes_stage_and_message(self):
        exc = PipelineValidationError("fields_generator", "bad output")
        assert "fields_generator" in str(exc)
        assert "bad output" in str(exc)

    def test_str_includes_details(self):
        exc = PipelineValidationError(
            "fields_generator", "bad", {"donor": "giz"}
        )
        assert "giz" in str(exc)

    def test_no_details_still_works(self):
        exc = PipelineValidationError("fields_generator", "msg")
        assert exc.details == {}
        assert "fields_generator" in str(exc)


# ---------------------------------------------------------------------------
# validate_fields_generator_output — file-level guards
# ---------------------------------------------------------------------------

class TestValidateFieldsGeneratorOutputFileGuards:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(PipelineValidationError) as exc_info:
            validate_fields_generator_output(tmp_path)
        assert exc_info.value.stage == "fields_generator"
        assert "not found" in str(exc_info.value).lower()

    def test_malformed_json_raises(self, tmp_path):
        (tmp_path / "generated_fields.json").write_text(
            "{ not valid json }", encoding="utf-8"
        )
        with pytest.raises(PipelineValidationError) as exc_info:
            validate_fields_generator_output(tmp_path)
        assert "parsed" in str(exc_info.value).lower() or "parse" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# validate_fields_generator_output — content checks
# ---------------------------------------------------------------------------

class TestValidateFieldsGeneratorOutputContent:
    def test_all_empty_content_raises(self, tmp_path):
        _write_gf(tmp_path, [
            {"field_key": "key_qualifications", "content": ""},
            {"field_key": "key_qualifications", "content": ""},
            {"field_key": "key_qualifications", "content": ""},
        ])
        with pytest.raises(PipelineValidationError) as exc_info:
            validate_fields_generator_output(tmp_path)
        assert exc_info.value.stage == "fields_generator"

    def test_whitespace_only_content_treated_as_empty(self, tmp_path):
        _write_gf(tmp_path, [
            {"field_key": "key_qualifications", "content": "   "},
            {"field_key": "key_qualifications", "content": "\t\n"},
        ])
        with pytest.raises(PipelineValidationError):
            validate_fields_generator_output(tmp_path)

    def test_empty_entries_list_raises(self, tmp_path):
        _write_gf(tmp_path, [])
        with pytest.raises(PipelineValidationError) as exc_info:
            validate_fields_generator_output(tmp_path)
        assert exc_info.value.stage == "fields_generator"

    def test_one_non_empty_passes(self, tmp_path):
        _write_gf(tmp_path, [
            {"field_key": "key_qualifications", "content": ""},
            {"field_key": "key_qualifications", "content": "Led renewable energy projects across SSA."},
        ])
        # Should not raise
        validate_fields_generator_output(tmp_path)

    def test_all_non_empty_passes(self, tmp_path):
        _write_gf(tmp_path, [
            {"field_key": "key_qualifications", "content": "Bullet one."},
            {"field_key": "key_qualifications", "content": "Bullet two."},
        ])
        validate_fields_generator_output(tmp_path)

    def test_single_non_empty_passes(self, tmp_path):
        _write_gf(tmp_path, [
            {"field_key": "key_qualifications", "content": "Single bullet."},
        ])
        validate_fields_generator_output(tmp_path)


# ---------------------------------------------------------------------------
# validate_fields_generator_output — details dict
# ---------------------------------------------------------------------------

class TestValidateFieldsGeneratorOutputDetails:
    def test_details_contain_correct_counts(self, tmp_path):
        _write_gf(tmp_path, [
            {"field_key": "key_qualifications", "content": ""},
            {"field_key": "key_qualifications", "content": ""},
            {"field_key": "key_qualifications", "content": ""},
        ])
        with pytest.raises(PipelineValidationError) as exc_info:
            validate_fields_generator_output(tmp_path)
        details = exc_info.value.details
        assert details["total_entries"] == 3
        assert details["empty_entries"] == 3
        assert details["non_empty_entries"] == 0

    def test_details_include_donor_when_manifest_present(self, tmp_path):
        _write_gf(tmp_path, [
            {"field_key": "key_qualifications", "content": ""},
        ])
        _write_manifest(tmp_path, donor="giz")
        with pytest.raises(PipelineValidationError) as exc_info:
            validate_fields_generator_output(tmp_path)
        assert exc_info.value.details["donor"] == "giz"

    def test_details_include_generative_field_keys_for_giz(self, tmp_path):
        _write_gf(tmp_path, [
            {"field_key": "key_qualifications", "content": ""},
        ])
        _write_manifest(tmp_path, donor="giz")
        with pytest.raises(PipelineValidationError) as exc_info:
            validate_fields_generator_output(tmp_path)
        keys = exc_info.value.details["generative_field_keys"]
        assert "key_qualifications" in keys

    def test_details_donor_unknown_when_manifest_missing(self, tmp_path):
        _write_gf(tmp_path, [
            {"field_key": "key_qualifications", "content": ""},
        ])
        # No manifest written
        with pytest.raises(PipelineValidationError) as exc_info:
            validate_fields_generator_output(tmp_path)
        assert exc_info.value.details.get("donor") == "unknown"

    def test_error_message_mentions_agent_4(self, tmp_path):
        _write_gf(tmp_path, [
            {"field_key": "key_qualifications", "content": ""},
        ])
        with pytest.raises(PipelineValidationError) as exc_info:
            validate_fields_generator_output(tmp_path)
        assert "Agent 4" in exc_info.value.message


# ---------------------------------------------------------------------------
# Fix 5b — soft-flag check helpers
# ---------------------------------------------------------------------------

def _write_gf_with_review_compression(
    tmp_path: Path,
    entries: list[dict] | None = None,
    generation_warnings: list[str] | None = None,
    review: dict | None = None,
    compression: dict | None = None,
) -> None:
    gf = {
        "generated": {
            "generated_fields": entries or [],
        },
        "generation_warnings": generation_warnings or [],
        "review": review,
        "compression": compression,
    }
    (tmp_path / "generated_fields.json").write_text(
        json.dumps(gf, indent=2), encoding="utf-8"
    )


class TestCheckFieldsGeneratorWarnings:
    def test_missing_file_returns_empty(self, tmp_path):
        assert check_fields_generator_warnings(tmp_path) == []

    def test_healthy_output_returns_empty(self, tmp_path):
        _write_gf_with_review_compression(
            tmp_path,
            entries=[{"field_key": "kq", "content": "Good bullet."}],
            generation_warnings=["one warning"],
        )
        assert check_fields_generator_warnings(tmp_path) == []

    def test_high_generation_warnings_flagged(self, tmp_path):
        _write_gf_with_review_compression(
            tmp_path,
            entries=[{"field_key": "kq", "content": "Bullet"}],
            generation_warnings=["w1", "w2", "w3", "w4"],  # > threshold of 3
        )
        warnings = check_fields_generator_warnings(tmp_path)
        kinds = [w["kind"] for w in warnings]
        assert "generation_warnings_high" in kinds

    def test_partial_empty_fields_flagged(self, tmp_path):
        _write_gf_with_review_compression(
            tmp_path,
            entries=[
                {"field_key": "kq", "content": "Good bullet."},
                {"field_key": "kq", "content": ""},  # one empty
            ],
        )
        warnings = check_fields_generator_warnings(tmp_path)
        kinds = [w["kind"] for w in warnings]
        assert "partial_empty_generated_fields" in kinds

    def test_all_empty_not_flagged_here(self, tmp_path):
        """All-empty case is the hard-block domain, not soft-flag."""
        _write_gf_with_review_compression(
            tmp_path,
            entries=[{"field_key": "kq", "content": ""}],
        )
        warnings = check_fields_generator_warnings(tmp_path)
        kinds = [w["kind"] for w in warnings]
        assert "partial_empty_generated_fields" not in kinds


class TestCheckContentReviewerWarnings:
    def test_missing_file_returns_empty(self, tmp_path):
        assert check_content_reviewer_warnings(tmp_path) == []

    def test_healthy_review_returns_empty(self, tmp_path):
        _write_gf_with_review_compression(
            tmp_path,
            review={"high_severity": [], "low_severity": [], "passed": True},
        )
        assert check_content_reviewer_warnings(tmp_path) == []

    def test_null_review_block_flagged(self, tmp_path):
        _write_gf_with_review_compression(tmp_path, review=None)
        warnings = check_content_reviewer_warnings(tmp_path)
        assert any(w["kind"] == "review_block_null" for w in warnings)

    def test_high_severity_count_flagged(self, tmp_path):
        _write_gf_with_review_compression(
            tmp_path,
            review={
                "high_severity": [{"msg": f"issue {i}"} for i in range(6)],
                "low_severity": [],
                "passed": False,
            },
        )
        warnings = check_content_reviewer_warnings(tmp_path)
        assert any(w["kind"] == "high_severity_count_unusual" for w in warnings)

    def test_low_high_severity_not_flagged(self, tmp_path):
        _write_gf_with_review_compression(
            tmp_path,
            review={"high_severity": [{"msg": "one"}], "low_severity": [], "passed": False},
        )
        warnings = check_content_reviewer_warnings(tmp_path)
        assert all(w["kind"] != "high_severity_count_unusual" for w in warnings)


class TestCheckCompressorWarnings:
    def test_missing_file_returns_empty(self, tmp_path):
        assert check_compressor_warnings(tmp_path) == []

    def test_healthy_compression_returns_empty(self, tmp_path):
        _write_gf_with_review_compression(
            tmp_path,
            compression={"applied": True, "words_before": 1000, "words_after": 700,
                         "target_words": 700, "target_not_reached": False},
        )
        assert check_compressor_warnings(tmp_path) == []

    def test_null_compression_block_flagged(self, tmp_path):
        _write_gf_with_review_compression(tmp_path, compression=None)
        warnings = check_compressor_warnings(tmp_path)
        assert any(w["kind"] == "compression_block_null" for w in warnings)

    def test_applied_false_flagged(self, tmp_path):
        _write_gf_with_review_compression(
            tmp_path,
            compression={"applied": False, "words_before": 600, "target_words": 700,
                         "words_after": 600, "target_not_reached": False},
        )
        warnings = check_compressor_warnings(tmp_path)
        assert any(w["kind"] == "applied_false" for w in warnings)

    def test_target_not_reached_flagged(self, tmp_path):
        _write_gf_with_review_compression(
            tmp_path,
            compression={"applied": True, "words_before": 1200, "words_after": 900,
                         "target_words": 700, "target_not_reached": True},
        )
        warnings = check_compressor_warnings(tmp_path)
        assert any(w["kind"] == "target_not_reached" for w in warnings)

    def test_suspiciously_low_words_after_flagged(self, tmp_path):
        _write_gf_with_review_compression(
            tmp_path,
            compression={"applied": True, "words_before": 800, "words_after": 100,
                         "target_words": 700, "target_not_reached": False},
        )
        warnings = check_compressor_warnings(tmp_path)
        assert any(w["kind"] == "words_after_suspiciously_low" for w in warnings)


# ---------------------------------------------------------------------------
# Fix Y — check_tor_summarizer_warnings
# ---------------------------------------------------------------------------

def _write_tor(tmp_path: Path, pools: list[dict]) -> None:
    """Write a minimal tor_data.json into tmp_path."""
    tor = {
        "approved": False,
        "approved_at": None,
        "pools": pools,
        "selected_pool_index": 0,
    }
    (tmp_path / "tor_data.json").write_text(
        json.dumps(tor, indent=2), encoding="utf-8"
    )


def _healthy_pool() -> dict:
    return {
        "position_title": "Grid Code Expert",
        "sector": "Energy",
        "key_tasks": ["Develop grid integration framework."],
        "required_qualifications": [],
        "required_competencies": [],
        "preferred_competencies": [],
        "sector_keywords": ["grid code"],
        "language_requirements": [],
        "geography": "South Africa",
        "country_experience_required": ["South Africa"],
        "page_limit_stated": None,
        "page_limit_source": "",
        "scoring_keywords": {
            "explicit": ["South Africa", "grid code"],
            "scope_implied": ["transmission planning"],
            "role_implied": ["stability criteria"],
        },
    }


def _empty_keywords_pool() -> dict:
    pool = _healthy_pool()
    pool["scoring_keywords"] = {"explicit": [], "scope_implied": [], "role_implied": []}
    return pool


class TestCheckTorSummarizerWarnings:
    def test_missing_file_returns_empty(self, tmp_path):
        assert check_tor_summarizer_warnings(tmp_path) == []

    def test_healthy_tor_returns_empty(self, tmp_path):
        _write_tor(tmp_path, [_healthy_pool()])
        assert check_tor_summarizer_warnings(tmp_path) == []

    def test_empty_scoring_keywords_flagged(self, tmp_path):
        _write_tor(tmp_path, [_empty_keywords_pool()])
        warnings = check_tor_summarizer_warnings(tmp_path)
        assert any(w["kind"] == "scoring_keywords_empty" for w in warnings)

    def test_empty_position_title_flagged(self, tmp_path):
        pool = _healthy_pool()
        pool["position_title"] = ""
        _write_tor(tmp_path, [pool])
        warnings = check_tor_summarizer_warnings(tmp_path)
        assert any(w["kind"] == "position_title_empty" for w in warnings)

    def test_no_pools_returns_empty(self, tmp_path):
        _write_tor(tmp_path, [])
        assert check_tor_summarizer_warnings(tmp_path) == []

    def test_partial_keyword_list_not_flagged(self, tmp_path):
        """One populated list is sufficient — no scoring_keywords_empty warning."""
        pool = _empty_keywords_pool()
        pool["scoring_keywords"]["role_implied"] = ["grid code", "stability criteria"]
        _write_tor(tmp_path, [pool])
        warnings = check_tor_summarizer_warnings(tmp_path)
        assert all(w["kind"] != "scoring_keywords_empty" for w in warnings)
