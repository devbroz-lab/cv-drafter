"""
Tests for Field Editor Fix 1 — skip-reason transparency.

Verifies:
  - _truncate_reason helper (length cap, ellipsis, no-op when short)
  - All 5 skip paths emit {"path": str, "reason": str} dicts
  - Reasons are truncated when the source string exceeds 200 chars
  - run_field_editor returns list[dict] for skipped (not list[str])
  - FieldEditResponse accepts list[FieldEditSkip] and rejects list[str]
"""

import pytest
from unittest.mock import MagicMock, patch
from pydantic import ValidationError

from pipeline.agents.field_editor import (
    _SKIP_REASON_MAX_LEN,
    _truncate_reason,
    run_field_editor,
)
from api.models.requests import FieldEditItem, FieldEditResponse, FieldEditSkip


# ---------------------------------------------------------------------------
# _truncate_reason helper
# ---------------------------------------------------------------------------

class TestTruncateReason:
    def test_short_reason_unchanged(self):
        r = "Cannot fabricate certification."
        assert _truncate_reason(r) == r

    def test_exactly_at_limit_unchanged(self):
        r = "x" * _SKIP_REASON_MAX_LEN
        assert _truncate_reason(r) == r
        assert not r.endswith("\u2026")

    def test_one_over_limit_truncated(self):
        r = "x" * (_SKIP_REASON_MAX_LEN + 1)
        result = _truncate_reason(r)
        assert len(result) == _SKIP_REASON_MAX_LEN
        assert result.endswith("\u2026")

    def test_very_long_reason_truncated(self):
        r = "a" * 500
        result = _truncate_reason(r)
        assert len(result) == _SKIP_REASON_MAX_LEN
        assert result.endswith("\u2026")
        assert result[: _SKIP_REASON_MAX_LEN - 1] == "a" * (_SKIP_REASON_MAX_LEN - 1)

    def test_empty_string_unchanged(self):
        assert _truncate_reason("") == ""

    def test_limit_constant_is_200(self):
        assert _SKIP_REASON_MAX_LEN == 200


# ---------------------------------------------------------------------------
# paragraph_<n> → key_qualifications[i] (anchor_text from Docx viewer)
# ---------------------------------------------------------------------------


class TestParagraphPlaceholderResolution:
    def test_resolves_with_anchor_to_key_qualifications(self):
        generated = {
            "key_qualifications": [
                "Lead solar deployment projects in Kenya.",
                "Second bullet",
            ]
        }
        edits = [
            {
                "field_path": "paragraph_20",
                "instruction": "Make shorter",
                "anchor_text": "Lead solar deployment projects in Kenya.",
            }
        ]
        with patch("pipeline.agents.field_editor.call_claude") as m:
            m.return_value = {"action": "apply", "value": "Lead solar in Kenya."}
            mutated, applied, skipped = run_field_editor(generated, None, edits, MagicMock())
        assert applied == ["key_qualifications[0]"]
        assert skipped == []
        assert mutated["key_qualifications"][0] == "Lead solar in Kenya."

    def test_paragraph_n_without_anchor_still_fails(self):
        generated = {"key_qualifications": ["x"]}
        edits = [{"field_path": "paragraph_5", "instruction": "y"}]
        _, applied, skipped = run_field_editor(generated, None, edits, MagicMock())
        assert applied == []
        assert len(skipped) == 1
        assert "path resolution failed" in skipped[0]["reason"]


class TestFieldEditItemAnchorText:
    def test_optional_anchor_text(self):
        a = FieldEditItem(field_path="key_qualifications[0]", instruction="x")
        assert a.anchor_text is None
        b = FieldEditItem(
            field_path="paragraph_2",
            instruction="x",
            anchor_text="Clicked line of text",
        )
        assert b.anchor_text == "Clicked line of text"


# ---------------------------------------------------------------------------
# Skip path 1: path resolution failure
# ---------------------------------------------------------------------------

class TestPathResolutionFailureReason:
    def test_skip_dict_emitted(self):
        generated = {"key_qualifications": ["bullet one"]}
        edits = [{"field_path": "nonexistent.path", "instruction": "rewrite"}]
        _, applied, skipped = run_field_editor(generated, None, edits, MagicMock())
        assert applied == []
        assert len(skipped) == 1
        assert skipped[0]["path"] == "nonexistent.path"
        assert "path resolution failed" in skipped[0]["reason"]

    def test_reason_is_string(self):
        generated = {}
        edits = [{"field_path": "missing.key", "instruction": "x"}]
        _, _, skipped = run_field_editor(generated, None, edits, MagicMock())
        assert isinstance(skipped[0]["reason"], str)

    def test_reason_within_length_limit(self):
        generated = {}
        edits = [{"field_path": "missing.key", "instruction": "x"}]
        _, _, skipped = run_field_editor(generated, None, edits, MagicMock())
        assert len(skipped[0]["reason"]) <= _SKIP_REASON_MAX_LEN


# ---------------------------------------------------------------------------
# Skip path 2: non-scalar target (list/dict)
# ---------------------------------------------------------------------------

class TestNonScalarTargetReason:
    def test_list_target_skipped_with_reason(self):
        generated = {"key_qualifications": ["bullet one", "bullet two"]}
        # Pointing to the list itself, not an element
        edits = [{"field_path": "key_qualifications", "instruction": "rewrite all"}]
        _, applied, skipped = run_field_editor(generated, None, edits, MagicMock())
        assert applied == []
        assert len(skipped) == 1
        assert skipped[0]["path"] == "key_qualifications"
        assert "not a scalar" in skipped[0]["reason"]

    def test_dict_target_skipped_with_reason(self):
        generated = {"personal_info": {"first_names": "Alice"}}
        edits = [{"field_path": "personal_info", "instruction": "update"}]
        _, _, skipped = run_field_editor(generated, None, edits, MagicMock())
        assert "not a scalar" in skipped[0]["reason"]

    def test_reason_within_length_limit(self):
        generated = {"key_qualifications": ["x"]}
        edits = [{"field_path": "key_qualifications", "instruction": "x"}]
        _, _, skipped = run_field_editor(generated, None, edits, MagicMock())
        assert len(skipped[0]["reason"]) <= _SKIP_REASON_MAX_LEN


# ---------------------------------------------------------------------------
# Skip path 3: API / parse error
# ---------------------------------------------------------------------------

class TestApiErrorReason:
    def test_api_error_skipped_with_reason(self):
        generated = {"key_qualifications": ["original bullet"]}
        edits = [{"field_path": "key_qualifications[0]", "instruction": "rewrite"}]

        with patch("pipeline.agents.field_editor.call_claude") as mock_call:
            mock_call.side_effect = RuntimeError("connection timeout")
            _, applied, skipped = run_field_editor(generated, None, edits, MagicMock())

        assert applied == []
        assert len(skipped) == 1
        assert skipped[0]["path"] == "key_qualifications[0]"
        assert "API or parse error" in skipped[0]["reason"]
        assert "connection timeout" in skipped[0]["reason"]

    def test_long_exception_message_truncated(self):
        generated = {"key_qualifications": ["bullet"]}
        edits = [{"field_path": "key_qualifications[0]", "instruction": "x"}]
        long_exc_msg = "E" * 500

        with patch("pipeline.agents.field_editor.call_claude") as mock_call:
            mock_call.side_effect = RuntimeError(long_exc_msg)
            _, _, skipped = run_field_editor(generated, None, edits, MagicMock())

        assert len(skipped[0]["reason"]) == _SKIP_REASON_MAX_LEN
        assert skipped[0]["reason"].endswith("\u2026")


# ---------------------------------------------------------------------------
# Skip path 4: LLM chose skip
# ---------------------------------------------------------------------------

class TestLlmSkipReason:
    def test_llm_reason_forwarded_verbatim(self):
        generated = {"key_qualifications": ["original"]}
        edits = [{"field_path": "key_qualifications[0]", "instruction": "add PhD"}]
        llm_reason = "Cannot add a PhD qualification not present in the original value."

        with patch("pipeline.agents.field_editor.call_claude") as mock_call:
            mock_call.return_value = {"action": "skip", "reason": llm_reason}
            _, applied, skipped = run_field_editor(generated, None, edits, MagicMock())

        assert applied == []
        assert skipped[0]["path"] == "key_qualifications[0]"
        assert skipped[0]["reason"] == llm_reason  # short reason — not truncated

    def test_long_llm_reason_truncated(self):
        generated = {"key_qualifications": ["original"]}
        edits = [{"field_path": "key_qualifications[0]", "instruction": "x"}]
        long_reason = "R" * 500

        with patch("pipeline.agents.field_editor.call_claude") as mock_call:
            mock_call.return_value = {"action": "skip", "reason": long_reason}
            _, _, skipped = run_field_editor(generated, None, edits, MagicMock())

        assert len(skipped[0]["reason"]) == _SKIP_REASON_MAX_LEN
        assert skipped[0]["reason"].endswith("\u2026")


# ---------------------------------------------------------------------------
# Skip path 5: write-back failure
# ---------------------------------------------------------------------------

class TestWriteBackFailureReason:
    def test_write_back_failure_skipped_with_reason(self):
        generated = {"key_qualifications": ["original"]}
        edits = [{"field_path": "key_qualifications[0]", "instruction": "rewrite"}]

        with patch("pipeline.agents.field_editor.call_claude") as mock_call:
            mock_call.return_value = {"action": "apply", "value": "new text"}
            with patch("pipeline.agents.field_editor.set_by_path") as mock_set:
                mock_set.side_effect = KeyError("write exploded")
                _, applied, skipped = run_field_editor(generated, None, edits, MagicMock())

        assert applied == []
        assert skipped[0]["path"] == "key_qualifications[0]"
        assert "write-back failed" in skipped[0]["reason"]


# ---------------------------------------------------------------------------
# Shape invariants across all skip paths
# ---------------------------------------------------------------------------

class TestSkipDictShape:
    def _get_skipped(self, generated: dict, field_path: str, mock_action=None) -> list[dict]:
        edits = [{"field_path": field_path, "instruction": "x"}]
        if mock_action:
            with patch("pipeline.agents.field_editor.call_claude") as m:
                m.return_value = mock_action
                _, _, skipped = run_field_editor(generated, None, edits, MagicMock())
        else:
            _, _, skipped = run_field_editor(generated, None, edits, MagicMock())
        return skipped

    def test_each_skip_has_path_and_reason_keys(self):
        # path resolution failure
        skipped = self._get_skipped({}, "nonexistent")
        assert set(skipped[0].keys()) == {"path", "reason"}

    def test_path_matches_input_field_path(self):
        skipped = self._get_skipped({}, "nonexistent.key")
        assert skipped[0]["path"] == "nonexistent.key"

    def test_both_values_are_strings(self):
        skipped = self._get_skipped({}, "nonexistent")
        assert isinstance(skipped[0]["path"], str)
        assert isinstance(skipped[0]["reason"], str)

    def test_reason_never_empty(self):
        skipped = self._get_skipped({}, "nonexistent")
        assert skipped[0]["reason"] != ""

    def test_reason_length_capped(self):
        generated = {"key_qualifications": ["bullet"]}
        skipped = self._get_skipped(
            generated,
            "key_qualifications[0]",
            mock_action={"action": "skip", "reason": "Z" * 500},
        )
        assert len(skipped[0]["reason"]) <= _SKIP_REASON_MAX_LEN

    def test_nothing_skipped_when_apply_succeeds(self):
        generated = {"key_qualifications": ["original"]}
        edits = [{"field_path": "key_qualifications[0]", "instruction": "rewrite"}]
        with patch("pipeline.agents.field_editor.call_claude") as m:
            m.return_value = {"action": "apply", "value": "new text"}
            _, applied, skipped = run_field_editor(generated, None, edits, MagicMock())
        assert skipped == []
        assert applied == ["key_qualifications[0]"]


# ---------------------------------------------------------------------------
# FieldEditResponse / FieldEditSkip Pydantic model
# ---------------------------------------------------------------------------

class TestFieldEditResponseModel:
    def _base_kwargs(self, skipped):
        return dict(
            session_id="abc123",
            status="checkpoint_3_pending",
            round=2,
            applied=["relevant_projects[1].location"],
            skipped=skipped,
            message="done",
        )

    def test_accepts_skip_dicts(self):
        resp = FieldEditResponse(
            **self._base_kwargs([{"path": "key_qualifications[2]", "reason": "No cert found."}])
        )
        assert len(resp.skipped) == 1
        assert resp.skipped[0].path == "key_qualifications[2]"
        assert resp.skipped[0].reason == "No cert found."

    def test_accepts_empty_skipped(self):
        resp = FieldEditResponse(**self._base_kwargs([]))
        assert resp.skipped == []

    def test_rejects_plain_strings(self):
        with pytest.raises(ValidationError):
            FieldEditResponse(**self._base_kwargs(["key_qualifications[2]"]))

    def test_field_edit_skip_model_directly(self):
        skip = FieldEditSkip(path="p", reason="r")
        assert skip.path == "p"
        assert skip.reason == "r"

    def test_reason_too_long_rejected_by_model(self):
        # Model enforces max_length=201 (200 content chars + 1 for ellipsis)
        with pytest.raises(ValidationError):
            FieldEditSkip(path="p", reason="x" * 202)

    def test_reason_at_201_chars_accepted(self):
        # 200 content chars + ellipsis = exactly 201 chars — should pass
        skip = FieldEditSkip(path="p", reason="x" * 200 + "\u2026")
        assert len(skip.reason) == 201
