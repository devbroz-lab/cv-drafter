"""
Pipeline-wide constants used by agents and post-processing helpers.

Keep values in one place so thresholds can be tuned without hunting
across multiple agent files.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Anthropic model defaults
# ---------------------------------------------------------------------------

# Model used by content_reviewer (and any agent that does not override it).
ANTHROPIC_MODEL: str = "claude-sonnet-6"

# Hard token cap for content_reviewer LLM call.  The reviewer outputs the full
# CVData + review block, so this needs to be generous.
ANTHROPIC_MAX_TOKENS: int = 16000

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
