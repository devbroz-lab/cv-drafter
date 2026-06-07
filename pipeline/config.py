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

# Output-token CEILINGS (not targets).  max_tokens is a hard cap the model is
# NOT aware of, so raising it cannot, by itself, make outputs longer — it only
# removes the truncation wall.  Output size is controlled separately by the
# agent prompts (word limits, project caps, lean output contracts).
#
# claude-sonnet-4-6 max output = 64K; claude-opus-4-8 max output = 128K.  The
# previous shared value of 32000 was roughly half of Sonnet's ceiling and a
# quarter of Opus's, which truncated rich-CV runs (and produced malformed JSON
# on near-limit outputs).  Both values stream (required for max_tokens > ~16K),
# which every agent already does.
#
# Sonnet agents (A2, A3, A4, A5, A6): exactly Sonnet 4.6's output ceiling.
ANTHROPIC_MAX_TOKENS: int = 64000

# CV Extractor (A1) runs on Opus 4.8 (ANTHROPIC_MODEL_EXTRACTOR).  Opus supports
# up to 128K output; 64000 is ample headroom for a single CVData extraction and
# can be raised toward 128000 if an exceptionally large CV ever truncates.
ANTHROPIC_MAX_TOKENS_EXTRACTOR: int = 64000

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
