"""
Tests for A2 (ToR Summarizer) prompt instructions — R5-A (Round 5).

These tests do NOT call the LLM.  They assert that required marker phrases
are present in SYSTEM_PROMPT_A2 so that accidental future edits removing
the scoring_keywords extraction instructions are caught immediately.

R5-A — scoring_keywords: A2 emits role_implied, scope_implied, explicit
         keyword sets into DistilledToR.scoring_keywords for use by R5-B's
         Python relevance scorer.
"""

from pipeline.agents.tor_summarizer import SYSTEM_PROMPT_A2


class TestSystemPromptA2ScoringKeywords:
    """scoring_keywords section must be present and complete in SYSTEM_PROMPT_A2."""

    def test_scoring_keywords_section_present(self):
        assert "scoring_keywords" in SYSTEM_PROMPT_A2

    def test_three_keyword_categories_documented(self):
        """All three category names must appear in the prompt."""
        assert "role_implied" in SYSTEM_PROMPT_A2
        assert "scope_implied" in SYSTEM_PROMPT_A2
        assert "explicit" in SYSTEM_PROMPT_A2

    def test_role_implied_inference_documented(self):
        """role_implied must be described as an inferential / reasoning step."""
        lower = SYSTEM_PROMPT_A2.lower()
        assert "infer" in lower or "inferential" in lower or "reason" in lower

    def test_keyword_count_guidance_present(self):
        """The prompt must give quantity guidance for each list."""
        # Should mention a numeric range or count guidance
        assert "5" in SYSTEM_PROMPT_A2 and "15" in SYSTEM_PROMPT_A2

    def test_scoring_keywords_section_position(self):
        """scoring_keywords section must appear before country_experience_required (confirms reorder)."""
        scoring_idx = SYSTEM_PROMPT_A2.find("### scoring_keywords")
        country_idx = SYSTEM_PROMPT_A2.find("### country_experience_required")
        assert scoring_idx != -1, "### scoring_keywords section not found"
        assert country_idx != -1, "### country_experience_required section not found"
        assert scoring_idx < country_idx, (
            "scoring_keywords section must appear before country_experience_required "
            "(R6-D reorder not applied)"
        )

    def test_scoring_keywords_non_empty_guarantee_present(self):
        """Non-empty guarantee language must be present in the scoring_keywords section."""
        lower = SYSTEM_PROMPT_A2.lower()
        assert "non-empty guarantee" in lower or "non-empty" in lower
        # Must mention that returning all empty is treated as failure
        assert "extraction failure" in lower or "failure" in lower


# ---------------------------------------------------------------------------
# Issue DD — JSON-only output contract (A2)
# ---------------------------------------------------------------------------

class TestSystemPromptA2JsonOnly:
    """A2 prompt must enforce the JSON-only output contract."""

    def test_output_contract_section_present(self):
        assert "Output contract" in SYSTEM_PROMPT_A2

    def test_first_char_rule_present(self):
        assert "FIRST non-whitespace" in SYSTEM_PROMPT_A2
