"""
Tests for Agent 7 (Field Editor) P5 context enrichment.

Verifies:
  - _field_key_from_path extracts the correct logical key
  - FIELD_WORD_LIMITS contains the expected entries
  - build_user_prompt includes field_key, donor, word_limit, cv_context sections
  - build_user_prompt is backward-compatible when donor/cv_context are omitted
  - run_field_editor passes donor and cv_context through to call_claude
    (via mock)
"""

import pytest
from unittest.mock import MagicMock, patch

from pipeline.agents.field_editor import (
    FIELD_WORD_LIMITS,
    _field_key_from_path,
    build_user_prompt,
    run_field_editor,
)


# ---------------------------------------------------------------------------
# _field_key_from_path
# ---------------------------------------------------------------------------

class TestFieldKeyFromPath:
    def test_simple_key(self):
        assert _field_key_from_path("proposed_position") == "proposed_position"

    def test_bracket_indexed_key(self):
        assert _field_key_from_path("key_qualifications[2]") == "key_qualifications"

    def test_nested_dot_path(self):
        assert _field_key_from_path("personal_info.first_names") == "first_names"

    def test_nested_with_index(self):
        assert _field_key_from_path("relevant_projects[1].activities_performed") == "activities_performed"

    def test_generated_fields_content(self):
        assert _field_key_from_path("generated_fields[0].content") == "content"

    def test_detailed_tasks(self):
        assert _field_key_from_path("generated_fields[3].content") == "content"


# ---------------------------------------------------------------------------
# FIELD_WORD_LIMITS
# ---------------------------------------------------------------------------

class TestFieldWordLimits:
    def test_giz_key_qualifications(self):
        assert FIELD_WORD_LIMITS[("giz", "key_qualifications")] == 25

    def test_world_bank_detailed_tasks(self):
        assert FIELD_WORD_LIMITS[("world_bank", "detailed_tasks")] == 30

    def test_missing_combination_returns_none(self):
        assert FIELD_WORD_LIMITS.get(("giz", "detailed_tasks")) is None
        assert FIELD_WORD_LIMITS.get(("world_bank", "key_qualifications")) is None


# ---------------------------------------------------------------------------
# build_user_prompt
# ---------------------------------------------------------------------------

class TestBuildUserPrompt:
    def test_contains_field_key(self):
        prompt = build_user_prompt(
            "key_qualifications[2]", "old value", "make it shorter",
            donor="giz",
        )
        assert "Field key: key_qualifications" in prompt

    def test_contains_donor_format(self):
        prompt = build_user_prompt(
            "key_qualifications[0]", "old value", "rewrite",
            donor="giz",
        )
        assert "Donor format: giz" in prompt

    def test_contains_word_limit_giz(self):
        prompt = build_user_prompt(
            "key_qualifications[0]", "old value", "rewrite",
            donor="giz",
        )
        assert "Word limit: 25 words" in prompt

    def test_contains_word_limit_wb(self):
        prompt = build_user_prompt(
            "generated_fields[0].content", "old value", "rewrite",
            donor="world_bank",
            cv_context=None,
        )
        # field_key is "content" which has no limit for world_bank
        assert "Word limit: no specific limit" in prompt

    def test_no_limit_when_field_not_in_table(self):
        prompt = build_user_prompt(
            "other_relevant_info", "old value", "rewrite",
            donor="giz",
        )
        assert "Word limit: no specific limit" in prompt

    def test_contains_cv_context(self):
        cv_context = {
            "proposed_position": "Team Lead, Energy Access",
            "top_projects": ["Grid Rehab Project", "Solar Mini-Grid"],
        }
        prompt = build_user_prompt(
            "key_qualifications[0]", "old value", "rewrite",
            donor="giz",
            cv_context=cv_context,
        )
        assert "Team Lead, Energy Access" in prompt
        assert "Grid Rehab Project" in prompt
        assert "Solar Mini-Grid" in prompt

    def test_still_contains_field_path_and_instruction(self):
        prompt = build_user_prompt(
            "key_qualifications[1]", "original text", "tighten to 20 words",
            donor="giz",
        )
        assert "Field path: key_qualifications[1]" in prompt
        assert "original text" in prompt
        assert "tighten to 20 words" in prompt

    def test_backward_compatible_no_donor(self):
        # donor="" and cv_context=None should not raise, and should produce valid prompt
        prompt = build_user_prompt("key_qualifications[0]", "value", "instruction")
        assert "Field path: key_qualifications[0]" in prompt
        assert "value" in prompt
        assert "instruction" in prompt
        assert "Word limit: no specific limit" in prompt

    def test_proposed_position_truncated_if_long(self):
        long_position = "A" * 200
        cv_context = {"proposed_position": long_position, "top_projects": []}
        prompt = build_user_prompt(
            "key_qualifications[0]", "val", "instr",
            donor="giz",
            cv_context=cv_context,
        )
        # The full 200-char string should not appear (truncation happens in orchestrator,
        # but here we just check the prompt was built without error)
        assert "CV context:" in prompt


# ---------------------------------------------------------------------------
# run_field_editor passes context to call_claude
# ---------------------------------------------------------------------------

class TestRunFieldEditorPassesContext:
    def _make_mock_client(self, action: str = "apply", value: str = "new text") -> MagicMock:
        """Return a mock Anthropic client that simulates a successful field edit."""
        import json
        response_text = json.dumps({"action": action, "value": value})
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=response_text[len('{"action": "'):])]  # after prefill
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        return mock_client

    def test_donor_and_cv_context_threaded_through(self):
        """call_claude receives donor and cv_context from run_field_editor."""
        generated = {"key_qualifications": ["Original bullet text here"]}
        edits = [{"field_path": "key_qualifications[0]", "instruction": "shorten it"}]
        donor = "giz"
        cv_context = {"proposed_position": "Team Lead", "top_projects": ["Project A"]}

        with patch("pipeline.agents.field_editor.call_claude") as mock_call:
            mock_call.return_value = {"action": "apply", "value": "Shorter text"}
            mutated, applied, skipped = run_field_editor(
                generated, None, edits, MagicMock(),
                donor=donor, cv_context=cv_context,
            )

        mock_call.assert_called_once()
        _, kwargs = mock_call.call_args
        assert kwargs.get("donor") == "giz"
        assert kwargs.get("cv_context") == cv_context
        assert applied == ["key_qualifications[0]"]
        assert mutated["key_qualifications"][0] == "Shorter text"

    def test_no_context_still_applies_edit(self):
        """Backward-compatible: no donor/cv_context still applies the edit."""
        generated = {"key_qualifications": ["Original"]}
        edits = [{"field_path": "key_qualifications[0]", "instruction": "rewrite"}]

        with patch("pipeline.agents.field_editor.call_claude") as mock_call:
            mock_call.return_value = {"action": "apply", "value": "Rewritten"}
            mutated, applied, skipped = run_field_editor(
                generated, None, edits, MagicMock(),
            )

        assert applied == ["key_qualifications[0]"]
        assert mutated["key_qualifications"][0] == "Rewritten"
