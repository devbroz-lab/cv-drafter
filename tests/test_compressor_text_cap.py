"""
Tests for Fix Z — per-project text cap in compressor.py.

Mirrors the structure of tests/test_fields_generator_text_cap.py.

Fix Z verifies:
  - activities_performed over cap is truncated to A6_INPUT_PROJECT_WORD_CAP
    words with a trailing "…" (U+2026).
  - main_project_features over cap is truncated.
  - Fields at exactly the cap are not truncated.
  - Fields under the cap are unchanged.
  - Empty fields are unchanged (no "…" appended).
  - Truncated text is suffixed with "…" (U+2026).
  - The original cv_data dict is not mutated (operates on a deep copy).
  - truncation_events list is populated for each truncated field.
  - No truncation_events when all fields are under cap.
  - Events have the correct shape (project_name, field, original_word_count,
    truncated_word_count).
  - Both fields truncated independently across the same project.
  - Multiple projects are all processed.
"""

import copy
import pytest

from pipeline.agents.compressor import (
    A6_INPUT_PROJECT_WORD_CAP,
    _A6_CAPPED_FIELDS,
    _truncate_project_text_for_a6,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _words(n: int, word: str = "word") -> str:
    return " ".join([word] * n)


def _cv(projects: list[dict]) -> dict:
    return {"relevant_projects": projects}


# ---------------------------------------------------------------------------
# Core truncation behaviour
# ---------------------------------------------------------------------------

class TestTruncateProjectTextForA6:
    def test_over_cap_activities_truncated(self):
        text_300 = _words(300)
        cv = _cv([{"project_name": "P", "activities_performed": text_300}])
        result, _ = _truncate_project_text_for_a6(cv)
        truncated = result["relevant_projects"][0]["activities_performed"]
        word_count = len(truncated.rstrip("\u2026").split())
        assert word_count == A6_INPUT_PROJECT_WORD_CAP
        assert truncated.endswith("\u2026")

    def test_main_project_features_truncated(self):
        text_300 = _words(300, "feat")
        cv = _cv([{"project_name": "P", "main_project_features": text_300}])
        result, _ = _truncate_project_text_for_a6(cv)
        truncated = result["relevant_projects"][0]["main_project_features"]
        word_count = len(truncated.rstrip("\u2026").split())
        assert word_count == A6_INPUT_PROJECT_WORD_CAP
        assert truncated.endswith("\u2026")

    def test_exactly_at_cap_not_truncated(self):
        text_at_cap = _words(A6_INPUT_PROJECT_WORD_CAP)
        cv = _cv([{"project_name": "P", "activities_performed": text_at_cap}])
        result, events = _truncate_project_text_for_a6(cv)
        assert result["relevant_projects"][0]["activities_performed"] == text_at_cap
        assert not result["relevant_projects"][0]["activities_performed"].endswith("\u2026")
        assert events == []

    def test_under_cap_unchanged(self):
        text_50 = _words(50)
        cv = _cv([{"project_name": "P", "activities_performed": text_50}])
        result, events = _truncate_project_text_for_a6(cv)
        assert result["relevant_projects"][0]["activities_performed"] == text_50
        assert events == []

    def test_empty_field_unchanged(self):
        cv = _cv([{"project_name": "P", "activities_performed": ""}])
        result, events = _truncate_project_text_for_a6(cv)
        assert result["relevant_projects"][0]["activities_performed"] == ""
        assert events == []

    def test_ellipsis_appended_u2026(self):
        cv = _cv([{"project_name": "P", "activities_performed": _words(200)}])
        result, _ = _truncate_project_text_for_a6(cv)
        truncated = result["relevant_projects"][0]["activities_performed"]
        assert truncated[-1] == "\u2026"

    def test_original_not_mutated(self):
        long_text = _words(694)
        cv = _cv([{"project_name": "P", "activities_performed": long_text}])
        original_copy = copy.deepcopy(cv)
        _truncate_project_text_for_a6(cv)
        assert cv == original_copy

    def test_truncation_events_populated(self):
        cv = _cv([{"project_name": "MyProject", "activities_performed": _words(300)}])
        _, events = _truncate_project_text_for_a6(cv)
        assert len(events) == 1
        assert events[0]["project_name"] == "MyProject"
        assert events[0]["field"] == "activities_performed"
        assert events[0]["original_word_count"] == 300
        assert events[0]["truncated_word_count"] == A6_INPUT_PROJECT_WORD_CAP

    def test_no_events_when_under_cap(self):
        cv = _cv([{"project_name": "P", "activities_performed": _words(50)}])
        _, events = _truncate_project_text_for_a6(cv)
        assert events == []

    def test_events_shape(self):
        """Events must have project_name, field, original_word_count, truncated_word_count."""
        cv = _cv([{"project_name": "TestProject", "activities_performed": _words(400)}])
        _, events = _truncate_project_text_for_a6(cv)
        assert len(events) == 1
        evt = events[0]
        assert "project_name" in evt
        assert "field" in evt
        assert "original_word_count" in evt
        assert "truncated_word_count" in evt
        assert evt["original_word_count"] == 400
        assert evt["truncated_word_count"] == A6_INPUT_PROJECT_WORD_CAP

    def test_both_fields_truncated_independently(self):
        cv = _cv([{
            "project_name": "P",
            "activities_performed": _words(400, "act"),
            "main_project_features": _words(300, "feat"),
        }])
        result, events = _truncate_project_text_for_a6(cv)
        proj = result["relevant_projects"][0]
        assert proj["activities_performed"].endswith("\u2026")
        assert proj["main_project_features"].endswith("\u2026")
        assert len(proj["activities_performed"].rstrip("\u2026").split()) == A6_INPUT_PROJECT_WORD_CAP
        assert len(proj["main_project_features"].rstrip("\u2026").split()) == A6_INPUT_PROJECT_WORD_CAP
        # Two truncation events — one per field
        assert len(events) == 2
        fields_in_events = {e["field"] for e in events}
        assert "activities_performed" in fields_in_events
        assert "main_project_features" in fields_in_events

    def test_multiple_projects_all_processed(self):
        cv = _cv([
            {"project_name": f"P{i}", "activities_performed": _words(300)}
            for i in range(4)
        ])
        result, events = _truncate_project_text_for_a6(cv)
        for proj in result["relevant_projects"]:
            assert proj["activities_performed"].endswith("\u2026")
        assert len(events) == 4
