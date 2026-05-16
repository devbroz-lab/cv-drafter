"""
Issue DD — JSON-only output contract marker tests for A5 and A6.

Assert that the required Output contract phrases are present in
SYSTEM_PROMPT_A5 and SYSTEM_PROMPT_A6 so that accidental future edits
removing the contract are caught immediately by the test suite.
"""

from pipeline.agents.compressor import SYSTEM_PROMPT_A6
from pipeline.agents.content_reviewer import SYSTEM_PROMPT_A5


# ---------------------------------------------------------------------------
# A5 — Content Reviewer
# ---------------------------------------------------------------------------

class TestSystemPromptA5JsonOnly:
    """A5 prompt must enforce the JSON-only output contract."""

    def test_output_contract_section_present(self):
        assert "Output contract" in SYSTEM_PROMPT_A5

    def test_first_char_rule_present(self):
        assert "FIRST non-whitespace" in SYSTEM_PROMPT_A5


# ---------------------------------------------------------------------------
# A6 — Compressor
# ---------------------------------------------------------------------------

class TestSystemPromptA6JsonOnly:
    """A6 prompt must enforce the JSON-only output contract."""

    def test_output_contract_section_present(self):
        assert "Output contract" in SYSTEM_PROMPT_A6

    def test_first_char_rule_present(self):
        assert "FIRST non-whitespace" in SYSTEM_PROMPT_A6
