"""
Pipeline-wide constants used by agents and post-processing helpers.

Keep values in one place so thresholds can be tuned without hunting
across multiple agent files.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Anthropic model defaults
# ---------------------------------------------------------------------------

# Default model for all pipeline agents (A1, A2, A3, A5, A6).
# All non-field-editor agents import their model constant from this module —
# change the value here to update all of them simultaneously.
# Round 6: upgraded from deprecated claude-sonnet-4-20250514 to claude-sonnet-4-6.
# claude-sonnet-4-6 provides a 1M token context window (vs 200k), resolving A1
# context exhaustion on large CVs with long prompts. Same pricing tier; faster.
ANTHROPIC_MODEL: str = "claude-sonnet-4-6"
ANTHROPIC_MODEL_EXTRACTOR: str = "claude-opus-4-8"

# Model for Agent 4 (Fields Generator) — the sole generative synthesis agent.
# A4 must reason across four dense input blocks simultaneously to produce
# ToR-grounded qualification bullets; this is a Sonnet-class task.
# Round 6: also upgraded to claude-sonnet-4-6 for the 1M context window.
ANTHROPIC_SYNTHESIS_MODEL: str = "claude-sonnet-4-6"

# Hard token cap for content_reviewer LLM call.  The reviewer outputs the full
# CVData + review block, so this needs to be generous.
ANTHROPIC_MAX_TOKENS: int = 32000

# ---------------------------------------------------------------------------
# Content reviewer — post-processing thresholds
# ---------------------------------------------------------------------------

# Minimum energy-sector experience gap (years) that triggers the deterministic
# experience-gap high_severity injection for team_lead tier roles.
# If the candidate's documented energy years fall this far below what the ToR
# requires, the reviewer MUST flag it even if the LLM missed it.
EXPERIENCE_GAP_BLOCK_THRESHOLD_YEARS: float = 3.0

# Word-count over-limit tolerance.  A bullet that is within this fraction above
# the stated limit is not flagged as a low_severity issue.
# E.g. 0.10 means a 25-word limit allows up to 27 words before flagging.
WORD_COUNT_TOLERANCE_PCT: float = 0.10
