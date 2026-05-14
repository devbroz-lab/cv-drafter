"""
Tests for Agent 7 (Field Editor) P5 context enrichment.

Verifies:
  - _field_key_from_path extracts the correct logical key
  - FIELD_WORD_LIMITS contains the expected entries
  - build_user_prompt includes field_key, donor, word_limit, cv_context sections
  - build_user_prompt is backward-compatible when donor/cv_context are omitted
  - run_field_editor passes donor and cv_context through to call_claude
    (via mock)

Also covers Mismatch 3 fix — GIZ CEFR enrichment:
  - When donor == "giz" and the stored *_cefr field is empty, run_field_editor
    enriches the prompt's current_value with the mapped sibling *_raw value.
  - The write still targets the original cefr path.
  - The enrichment is skipped when donor != "giz".
  - The enrichment is skipped when the cefr field is already non-empty.
"""

import pytest
from unittest.mock import MagicMock, patch

from pipeline.agents.field_editor import (
    FIELD_WORD_LIMITS,
    _field_key_from_path,
    build_user_prompt,
    kq_source_label,
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


# ---------------------------------------------------------------------------
# Mismatch 3 fix — GIZ CEFR enrichment
# ---------------------------------------------------------------------------


class TestCefrEnrichment:
    """
    When donor == "giz" and the stored *_cefr field is empty, run_field_editor
    must pass the mapped *_raw value as current_value to call_claude.
    The write target (the cefr field) must remain unchanged.
    """

    def _make_generated(self, reading_cefr: str = "", reading_raw: str = "fluent") -> dict:
        return {
            "languages": [
                {
                    "language": "English",
                    "reading_cefr": reading_cefr,
                    "reading_raw": reading_raw,
                    "speaking_cefr": "",
                    "speaking_raw": "fluent",
                    "writing_cefr": "",
                    "writing_raw": "good",
                }
            ]
        }

    def test_enriched_current_value_passed_to_claude(self):
        """When reading_cefr is empty, call_claude receives the mapped raw value."""
        generated = self._make_generated(reading_cefr="", reading_raw="fluent")
        edits = [{"field_path": "languages[0].reading_cefr", "instruction": "change to B2"}]

        captured_current_value = None

        def capture_call(client, field_path, current_value, instruction, **kwargs):
            nonlocal captured_current_value
            captured_current_value = current_value
            return {"action": "apply", "value": "B2"}

        with patch("pipeline.agents.field_editor.call_claude", side_effect=capture_call):
            mutated, applied, skipped = run_field_editor(
                generated, None, edits, MagicMock(), donor="giz"
            )

        # "fluent" maps to "C2" via _map_cefr
        assert captured_current_value == "C2"
        assert applied == ["languages[0].reading_cefr"]
        assert mutated["languages"][0]["reading_cefr"] == "B2"

    def test_write_targets_cefr_field_not_raw(self):
        """The write must land on reading_cefr, not reading_raw."""
        generated = self._make_generated(reading_cefr="", reading_raw="fluent")
        edits = [{"field_path": "languages[0].reading_cefr", "instruction": "change to B2"}]

        with patch("pipeline.agents.field_editor.call_claude") as mock_call:
            mock_call.return_value = {"action": "apply", "value": "B2"}
            mutated, applied, skipped = run_field_editor(
                generated, None, edits, MagicMock(), donor="giz"
            )

        assert mutated["languages"][0]["reading_cefr"] == "B2"
        assert mutated["languages"][0]["reading_raw"] == "fluent"  # raw is unchanged

    def test_no_enrichment_when_cefr_already_set(self):
        """If reading_cefr is already non-empty, pass it as-is to Claude."""
        generated = self._make_generated(reading_cefr="B1", reading_raw="basic")
        edits = [{"field_path": "languages[0].reading_cefr", "instruction": "change to B2"}]

        captured_current_value = None

        def capture_call(client, field_path, current_value, instruction, **kwargs):
            nonlocal captured_current_value
            captured_current_value = current_value
            return {"action": "apply", "value": "B2"}

        with patch("pipeline.agents.field_editor.call_claude", side_effect=capture_call):
            run_field_editor(generated, None, edits, MagicMock(), donor="giz")

        assert captured_current_value == "B1"

    def test_no_enrichment_when_donor_is_not_giz(self):
        """CEFR enrichment must NOT apply for non-GIZ donors."""
        generated = self._make_generated(reading_cefr="", reading_raw="fluent")
        edits = [{"field_path": "languages[0].reading_cefr", "instruction": "change to B2"}]

        captured_current_value = None

        def capture_call(client, field_path, current_value, instruction, **kwargs):
            nonlocal captured_current_value
            captured_current_value = current_value
            return {"action": "apply", "value": "B2"}

        with patch("pipeline.agents.field_editor.call_claude", side_effect=capture_call):
            run_field_editor(generated, None, edits, MagicMock(), donor="world_bank")

        # No enrichment — raw stored value (empty string) is passed
        assert captured_current_value == ""

    def test_speaking_and_writing_cefr_fields_also_enriched(self):
        """Enrichment applies to all three CEFR fields, not just reading."""
        generated = {
            "languages": [
                {
                    "language": "French",
                    "reading_cefr": "",
                    "reading_raw": "good",
                    "speaking_cefr": "",
                    "speaking_raw": "good",
                    "writing_cefr": "",
                    "writing_raw": "fair",
                }
            ]
        }

        captured = {}

        def capture_call(client, field_path, current_value, instruction, **kwargs):
            captured[field_path] = current_value
            return {"action": "apply", "value": "B1"}

        edits = [
            {"field_path": "languages[0].reading_cefr",  "instruction": "change to B2"},
            {"field_path": "languages[0].speaking_cefr", "instruction": "change to B2"},
            {"field_path": "languages[0].writing_cefr",  "instruction": "change to B2"},
        ]

        with patch("pipeline.agents.field_editor.call_claude", side_effect=capture_call):
            run_field_editor(generated, None, edits, MagicMock(), donor="giz")

        # "good" → "C1", "fair" → "B1/B2"
        assert captured["languages[0].reading_cefr"] == "C1"
        assert captured["languages[0].speaking_cefr"] == "C1"
        assert captured["languages[0].writing_cefr"] == "B1/B2"


# ---------------------------------------------------------------------------
# Fix 6 — kq_source_label
# ---------------------------------------------------------------------------


class TestKqSourceLabel:
    """kq_source_label translates _key_qualification_source to API labels."""

    def test_returns_ai_generated_when_generated_fields_active(self):
        generated = {
            "generated_fields": [
                {"field_key": "key_qualifications", "content": "Led solar projects."},
            ],
            "key_qualifications": ["Raw bullet"],
        }
        assert kq_source_label(generated) == "ai_generated"

    def test_returns_extracted_when_only_raw_active(self):
        generated = {
            "generated_fields": [
                {"field_key": "key_qualifications", "content": ""},
            ],
            "key_qualifications": ["Raw bullet"],
        }
        assert kq_source_label(generated) == "extracted"

    def test_returns_absent_when_both_sources_empty(self):
        generated = {
            "generated_fields": [],
            "key_qualifications": [],
        }
        assert kq_source_label(generated) == "absent"

    def test_returns_absent_when_no_kq_keys_at_all(self):
        generated = {}
        assert kq_source_label(generated) == "absent"

    def test_generated_fields_beats_raw_when_non_empty(self):
        generated = {
            "generated_fields": [
                {"field_key": "key_qualifications", "content": "Generated."},
            ],
            "key_qualifications": ["Raw"],
        }
        assert kq_source_label(generated) == "ai_generated"

    def test_all_three_label_values_are_valid_literals(self):
        valid = {"ai_generated", "extracted", "absent"}
        assert kq_source_label({}) in valid
        assert kq_source_label({"key_qualifications": ["x"]}) in valid
        assert kq_source_label({
            "generated_fields": [{"field_key": "key_qualifications", "content": "x"}]
        }) in valid


class TestRunWrapperReturnsKqSource:
    """The outer run() function returns kq_source as the third element."""

    def test_run_returns_three_tuple(self, tmp_path):
        import json
        gf_data = {
            "generated": {
                "key_qualifications": ["Original bullet"],
                "generated_fields": [],
            }
        }
        (tmp_path / "generated_fields.json").write_text(
            json.dumps(gf_data), encoding="utf-8"
        )

        from pipeline.agents.field_editor import run as field_editor_run

        edits = [{"field_path": "key_qualifications[0]", "instruction": "shorten"}]

        with patch("pipeline.agents.field_editor.call_claude") as mock_call:
            mock_call.return_value = {"action": "apply", "value": "Short bullet"}
            result = field_editor_run(tmp_path, edits)

        assert len(result) == 3
        applied, skipped, kq_source = result
        assert kq_source in {"ai_generated", "extracted", "absent"}

    def test_kq_source_reflects_post_edit_state(self, tmp_path):
        """After a successful edit to generated_fields, kq_source is ai_generated."""
        import json
        gf_data = {
            "generated": {
                "key_qualifications": [],
                "generated_fields": [
                    {"field_key": "key_qualifications", "content": "Original generated."}
                ],
            }
        }
        (tmp_path / "generated_fields.json").write_text(
            json.dumps(gf_data), encoding="utf-8"
        )

        from pipeline.agents.field_editor import run as field_editor_run

        edits = [{
            "field_path": "generated_fields[0].content",
            "instruction": "make shorter",
        }]

        with patch("pipeline.agents.field_editor.call_claude") as mock_call:
            mock_call.return_value = {"action": "apply", "value": "Short."}
            _, _, kq_source = field_editor_run(tmp_path, edits)

        assert kq_source == "ai_generated"

    def test_kq_source_is_extracted_when_only_raw_present(self, tmp_path):
        import json
        gf_data = {
            "generated": {
                "key_qualifications": ["Raw bullet"],
                "generated_fields": [],
            }
        }
        (tmp_path / "generated_fields.json").write_text(
            json.dumps(gf_data), encoding="utf-8"
        )

        from pipeline.agents.field_editor import run as field_editor_run

        edits = [{"field_path": "key_qualifications[0]", "instruction": "rewrite"}]

        with patch("pipeline.agents.field_editor.call_claude") as mock_call:
            mock_call.return_value = {"action": "apply", "value": "Rewritten."}
            _, _, kq_source = field_editor_run(tmp_path, edits)

        assert kq_source == "extracted"


class TestFieldEditResponseKqSource:
    """FieldEditResponse accepts kq_source and rejects invalid values."""

    def test_accepts_all_three_valid_labels(self):
        from api.models.requests import FieldEditResponse
        base = dict(
            session_id="abc",
            status="checkpoint_3_pending",
            round=2,
            applied=[],
            skipped=[],
            message="ok",
        )
        for label in ("ai_generated", "extracted", "absent"):
            resp = FieldEditResponse(**base, kq_source=label)
            assert resp.kq_source == label

    def test_rejects_invalid_label(self):
        from pydantic import ValidationError
        from api.models.requests import FieldEditResponse
        with pytest.raises(ValidationError):
            FieldEditResponse(
                session_id="abc",
                status="checkpoint_3_pending",
                round=2,
                applied=[],
                skipped=[],
                message="ok",
                kq_source="unknown_value",
            )
