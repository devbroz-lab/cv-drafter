"""
Agent 7 — Field Editor.

Applies targeted, user-directed natural-language edits to specific fields in
generated_fields.json["generated"] before the compressor runs.

Pipeline entry point
--------------------
    from pipeline.agents import field_editor
    applied, skipped = field_editor.run(run_dir, edits)

Parameters
----------
run_dir : Path
    Session run directory (runs/{session_id}/).
edits : list[dict]
    Each item: {"field_path": str, "instruction": str}. Max 5 items.
    Paths are relative to generated_fields["generated"].
    Both bracket (key_qualifications[2]) and dot (key_qualifications.2)
    notations are supported and normalised internally.

Returns
-------
applied : list[str]
    Field paths where the edit was successfully written.
skipped : list[dict]
    Each item is {"path": str, "reason": str}. Reason is capped at
    200 characters with a trailing ellipsis if truncated. Pipeline
    continues regardless.

All agent logic, prompts, path utilities, model choice, and assistant prefill
are exactly as authored by Dev 2 in field_editor_agent.py.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from anthropic import Anthropic

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model — Dev 2's choice: Sonnet for editing quality
# ---------------------------------------------------------------------------

MODEL = "claude-sonnet-4-20250514"
# MODEL = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# P5: Word-limit table — per (donor, field_key)
# ---------------------------------------------------------------------------
# Keyed by (donor_format, field_key).  Donor format is the normalised string
# ("giz" or "world_bank").  field_key is the logical field name with list
# indices stripped.
#
# Values are word limits in words (matching the generation rules in Agent 4).
# If a (donor, field_key) pair is not in this dict, no specific limit applies.

FIELD_WORD_LIMITS: dict[tuple[str, str], int] = {
    ("giz", "key_qualifications"): 25,
    ("world_bank", "detailed_tasks"): 30,
}

# ---------------------------------------------------------------------------
# Fix 1: Skip-reason transparency
# ---------------------------------------------------------------------------

# Hard cap on skip reason strings returned to the API.
# Frontends rely on this for inline display without wrapping.
_SKIP_REASON_MAX_LEN: int = 200


def _truncate_reason(reason: str) -> str:
    """Cap a skip reason at _SKIP_REASON_MAX_LEN chars, appending \u2026 if truncated."""
    if len(reason) <= _SKIP_REASON_MAX_LEN:
        return reason
    return reason[: _SKIP_REASON_MAX_LEN - 1] + "\u2026"


# ---------------------------------------------------------------------------
# PATH UTILITIES
# Copied verbatim from field_editor_agent.py by Dev 2.
# Handles both bracket notation (key_qualifications[2]) and dot notation.
# ---------------------------------------------------------------------------


def _normalise_path(field_path: str) -> list[str | int]:
    """
    Convert a mixed bracket/dot path string into a list of keys/indices.

    Examples
    --------
    "key_qualifications[2]"         → ["key_qualifications", 2]
    "relevant_projects[1].location" → ["relevant_projects", 1, "location"]
    "personal_info.first_names"     → ["personal_info", "first_names"]
    """
    # Replace [N] bracket notation with .N so we can split uniformly
    normalised = re.sub(r"\[(\d+)\]", r".\1", field_path)
    parts = []
    for part in normalised.split("."):
        part = part.strip()
        if not part:
            continue
        parts.append(int(part) if part.isdigit() else part)
    return parts


def get_by_path(data: dict, field_path: str):
    """Return the value at field_path inside data, or raise KeyError/IndexError."""
    parts = _normalise_path(field_path)
    node = data
    for part in parts:
        if isinstance(node, list):
            if not isinstance(part, int):
                raise KeyError(f"Expected integer index, got '{part}'")
            node = node[part]
        elif isinstance(node, dict):
            node = node[str(part)]
        else:
            raise KeyError(f"Cannot descend into {type(node).__name__} at '{part}'")
    return node


def set_by_path(data: dict, field_path: str, new_value) -> None:
    """Write new_value at field_path inside data (in-place)."""
    parts = _normalise_path(field_path)
    node = data
    for part in parts[:-1]:
        if isinstance(node, list):
            node = node[part]
        elif isinstance(node, dict):
            node = node[str(part)]
        else:
            raise KeyError(f"Cannot descend into {type(node).__name__} at '{part}'")

    last = parts[-1]
    if isinstance(node, list):
        node[last] = new_value
    else:
        node[str(last)] = new_value


# ---------------------------------------------------------------------------
# PROMPT — copied verbatim from field_editor_agent.py by Dev 2
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_A7 = """\
You are a copy-editor applying recruiter instructions to professional CV fields \
formatted for international development donors (GIZ, World Bank).

Your only job is to carry out the recruiter's edit instruction and return a JSON \
object — nothing else. The recruiter is a trusted professional working on their \
own candidate's CV. Their instructions are authoritative.

RESPONSE FORMAT
---------------
You must always respond with exactly one of these two JSON shapes:

  {"action": "apply", "value": "<edited field value as a plain string>"}
  {"action": "skip",  "reason": "<one short sentence, max 25 words, explaining why>"}

DEFAULT: ALWAYS USE "apply"
---------------------------
"apply" is your default action. Execute the instruction as literally as possible.

Use "skip" ONLY in this one situation:
  The instruction explicitly names a specific credential, certification, \
publication, award, or external fact (e.g. "add their PMP certification", \
"mention the 2019 UN report") that is completely absent from the current \
field value AND absent from the CV context provided, AND adding it would \
constitute inserting a verifiable claim the recruiter has not supplied.

DO NOT use "skip" for any of the following — use "apply" instead:
  - Changing or correcting a location, city, country, or region
  - Making text more concise, shorter, or trimmed to a word limit
  - Rewording, rephrasing, or paraphrasing for clarity or tone
  - Switching between active and passive voice
  - Removing filler language, hedging words, or weak phrasing
  - Changing a date, year, or duration that the recruiter specifies
  - Adjusting emphasis, adding adjectives, or strengthening language
  - Any instruction that can be satisfied by modifying existing text

When in doubt, apply your best interpretation of the instruction. A slightly \
imperfect edit is always better than a skip.

APPLY RULES
-----------
- "value" must be a plain string — the new field text only.
- No markdown, no bullet symbols (unless the original used them), no extra \
quotes, no explanation inside the value.
- Preserve all factual content of the original unless the instruction \
explicitly asks you to change a specific fact.
- Respect the word limit if one is provided. If the edited text would exceed \
it, trim to fit while preserving the instruction's intent.
- Apply donor format conventions:
    GIZ        — active verbs, past tense, evidence-grounded, concise.
    World Bank — forward-looking task statements, action verbs, outcome-oriented.
- Do not add commentary before or after the JSON object.

CONTEXT FIELDS (provided in the user message)
---------------------------------------------
  Field key      — The logical CV field being edited (e.g. key_qualifications,
                   detailed_tasks, activities_performed). Use this to understand
                   the field's role in the document.

  Donor format   — "giz" or "world_bank". Apply its conventions as above.

  Word limit     — Maximum word count for this field type. Trim if needed.
                   If "no specific limit", write naturally within context.

  CV context     — The proposed position and top project names. Use this as
                   grounding to understand the expert's background.\
"""

def _field_key_from_path(field_path: str) -> str:
    """
    Strip list indices from a field path to get the logical field key.

    Examples:
      "key_qualifications[2]"              → "key_qualifications"
      "relevant_projects[1].activities_performed" → "activities_performed"
      "generated_fields[0].content"        → "content"
      "personal_info.first_names"          → "first_names"
    """
    # Normalise bracket notation to dot notation, then take the last non-numeric segment
    normalised = re.sub(r"\[(\d+)\]", r".\1", field_path)
    parts = [p for p in normalised.split(".") if p and not p.isdigit()]
    return parts[-1] if parts else field_path


def build_user_prompt(
    field_path: str,
    current_value: str,
    instruction: str,
    *,
    donor: str = "",
    cv_context: dict | None = None,
) -> str:
    """
    Build the user prompt for a single field edit.

    Parameters
    ----------
    field_path     : dot/bracket path into generated_fields["generated"]
    current_value  : current scalar value of the field
    instruction    : natural-language edit instruction from the user
    donor          : normalised donor format string ("giz" or "world_bank")
    cv_context     : dict with keys "proposed_position" (str) and
                     "top_projects" (list[str]) — used as a CV grounding snippet
    """
    field_key = _field_key_from_path(field_path)
    word_limit = FIELD_WORD_LIMITS.get((donor, field_key)) if donor else None
    word_limit_str = f"{word_limit} words" if word_limit else "no specific limit"

    context_lines: list[str] = [
        f"Field key: {field_key}",
        f"Donor format: {donor or 'not specified'}",
        f"Word limit: {word_limit_str}",
    ]
    if cv_context:
        proposed = cv_context.get("proposed_position", "")
        top_projects = cv_context.get("top_projects", [])
        snippet_parts = []
        if proposed:
            snippet_parts.append(f"Proposed position: {proposed}")
        if top_projects:
            snippet_parts.append("Top projects: " + ", ".join(top_projects))
        if snippet_parts:
            context_lines.append("CV context: " + " | ".join(snippet_parts))

    context_block = "\n".join(context_lines)

    return (
        f"{context_block}\n\n"
        f"Field path: {field_path}\n\n"
        f"Current value:\n\"\"\"\n{current_value}\n\"\"\"\n\n"
        f"Edit instruction: {instruction}"
    )


# The prefill string locks the opening of Claude's response to a JSON object,
# making it structurally impossible for Claude to write preamble text before it.
ASSISTANT_PREFILL = '{"action": "'

# ---------------------------------------------------------------------------
# CLAUDE CALL — copied verbatim from field_editor_agent.py by Dev 2
# ---------------------------------------------------------------------------


def call_claude(
    client: Anthropic,
    field_path: str,
    current_value: str,
    instruction: str,
    *,
    donor: str = "",
    cv_context: dict | None = None,
) -> dict:
    """
    Call Claude for a single field edit using JSON schema + assistant prefill.

    Returns a parsed dict with one of these shapes:
      {"action": "apply", "value": str}
      {"action": "skip",  "reason": str}

    Raises ValueError if the response cannot be parsed into either shape.
    """
    raw = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        system=SYSTEM_PROMPT_A7,
        messages=[
            {
                "role": "user",
                "content": build_user_prompt(
                    field_path,
                    str(current_value),
                    instruction,
                    donor=donor,
                    cv_context=cv_context,
                ),
            },
            # Prefill: forces the response to begin with '{"action": "'
            # Claude continues from this exact string, so it cannot deviate
            # from the JSON object format.
            {
                "role": "assistant",
                "content": ASSISTANT_PREFILL,
            },
        ],
    )

    # Reassemble: Claude's continuation is appended to our prefill
    continuation = raw.content[0].text
    full_response = ASSISTANT_PREFILL + continuation

    # Parse and validate
    try:
        parsed = json.loads(full_response)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Response was not valid JSON: {exc}\nRaw: {full_response!r}"
        ) from exc

    action = parsed.get("action")
    if action == "apply":
        if not isinstance(parsed.get("value"), str):
            raise ValueError(f"'apply' response missing string 'value'. Got: {parsed}")
    elif action == "skip":
        if not isinstance(parsed.get("reason"), str):
            raise ValueError(f"'skip' response missing string 'reason'. Got: {parsed}")
    else:
        raise ValueError(f"Unknown action '{action}'. Full response: {parsed}")

    return parsed


# ---------------------------------------------------------------------------
# MAIN AGENT LOGIC — copied verbatim from field_editor_agent.py by Dev 2
# ---------------------------------------------------------------------------


def run_field_editor(
    generated: dict,
    review: dict | None,
    edits: list[dict],
    client: Anthropic,
    *,
    donor: str = "",
    cv_context: dict | None = None,
) -> tuple[dict, list[str], list[dict]]:
    """
    Apply edits sequentially to a deep copy of `generated`.

    Parameters
    ----------
    generated : dict
        The ["generated"] subtree of generated_fields.json.
    review : dict | None
        The ["review"] subtree (passed to agent as context in full pipeline;
        logged here for awareness but not sent to Claude in the silo).
    edits : list[dict]
        Each item: {"field_path": str, "instruction": str}
    donor : str
        Normalised donor format string ("giz" or "world_bank").  Used by
        build_user_prompt to look up word limits and apply format conventions.
    cv_context : dict | None
        Minimal CV grounding snippet with keys "proposed_position" and
        "top_projects".  Forwarded to build_user_prompt.

    Returns
    -------
    mutated : dict
        The edited copy of `generated`.
    applied : list[str]
        Field paths where the edit was successfully written.
    skipped : list[dict]
        Each item is {"path": str, "reason": str}.  Reason is truncated to
        _SKIP_REASON_MAX_LEN characters with a trailing ellipsis if the
        source string was longer.  Categories: path resolution failure,
        non-scalar target, API or parse error, LLM skip decision,
        write-back failure.
    """
    import copy
    mutated = copy.deepcopy(generated)
    applied: list[str] = []
    skipped: list[dict] = []

    for i, edit in enumerate(edits, start=1):
        field_path  = edit["field_path"]
        instruction = edit["instruction"]

        log.debug("[Edit %d/%d] path='%s'", i, len(edits), field_path)
        log.debug("  instruction: %s", instruction)

        # --- Resolve current value ---
        try:
            current_value = get_by_path(mutated, field_path)
        except (KeyError, IndexError, TypeError) as exc:
            reason = f"path resolution failed: {exc}"
            log.warning("  SKIPPED — %s", reason)
            skipped.append({"path": field_path, "reason": _truncate_reason(reason)})
            continue

        # Guard: only edit scalar values
        if isinstance(current_value, list | dict):
            reason = (
                f"resolved value is {type(current_value).__name__}, not a scalar. "
                "Use a more specific path (e.g. list[N]) to target a scalar element."
            )
            log.warning("  SKIPPED — %s", reason)
            skipped.append({"path": field_path, "reason": _truncate_reason(reason)})
            continue

        log.debug("  current value: %s", str(current_value)[:120])

        # --- Call Claude ---
        try:
            result = call_claude(
                client,
                field_path,
                current_value,
                instruction,
                donor=donor,
                cv_context=cv_context,
            )
        except Exception as exc:
            reason = f"API or parse error: {exc}"
            log.warning("  API / parse error for '%s': %s", field_path, exc)
            skipped.append({"path": field_path, "reason": _truncate_reason(reason)})
            continue

        # --- Dispatch on action ---
        if result["action"] == "skip":
            log.info("  SKIPPED (agent) — %s", result["reason"])
            skipped.append({"path": field_path, "reason": _truncate_reason(result["reason"])})
            continue

        new_value = result["value"]

        # --- Write back ---
        try:
            set_by_path(mutated, field_path, new_value)
        except (KeyError, IndexError, TypeError) as exc:
            reason = f"write-back failed: {exc}"
            log.warning("  Write-back failed for '%s': %s", field_path, exc)
            skipped.append({"path": field_path, "reason": _truncate_reason(reason)})
            continue

        log.info("  applied '%s' → %s", field_path, new_value[:120])
        applied.append(field_path)

    return mutated, applied, skipped


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------


def run(
    run_dir: Path,
    edits: list[dict],
    donor: str = "",
    cv_context: dict | None = None,
) -> tuple[list[str], list[dict]]:
    """
    Pipeline entry point called by the HTTP handler (POST /field-edit).

    Reads generated_fields.json, applies edits via run_field_editor(),
    writes the mutated generated dict back (preserving all top-level keys),
    and returns (applied, skipped).

    field_editor has no manifest step — the caller is responsible for
    transitioning the DB session status (set_processing before calling,
    set_checkpoint_pending(3) after returning).

    Parameters
    ----------
    run_dir    : session run directory
    edits      : list of {"field_path": str, "instruction": str} dicts
    donor      : normalised donor format ("giz" or "world_bank").  Passed
                 in by the orchestrator; falls back to "" if not provided.
    cv_context : {"proposed_position": str, "top_projects": list[str]}.
                 Built by the orchestrator from the session manifest and
                 generated_fields.json.  If not provided, context sections
                 are omitted from the user prompt (backward-compatible).

    Returns
    -------
    applied : list[str]
        Field paths where the edit was successfully written.
    skipped : list[dict]
        Each item is {"path": str, "reason": str}.  Reason capped at
        _SKIP_REASON_MAX_LEN chars with trailing ellipsis if truncated.
    """
    gf_path = run_dir / "generated_fields.json"
    if not gf_path.exists():
        raise FileNotFoundError(
            f"generated_fields.json not found in {run_dir}. "
            "Has the pipeline completed through Phase 3 (fields_generator + content_reviewer)?"
        )

    gf = json.loads(gf_path.read_text(encoding="utf-8"))
    generated = gf.get("generated")
    if not generated:
        raise ValueError(
            "generated_fields.json has no 'generated' key. "
            "Has Agent 4 (Fields Generator) completed?"
        )
    review = gf.get("review")

    client = Anthropic()  # reads ANTHROPIC_API_KEY from environment

    mutated, applied, skipped = run_field_editor(
        generated,
        review,
        edits,
        client,
        donor=donor,
        cv_context=cv_context,
    )

    # Write back — preserve all top-level keys, only replace "generated"
    gf["generated"] = mutated
    gf_path.write_text(json.dumps(gf, indent=2, ensure_ascii=False), encoding="utf-8")

    log.info(
        "field_editor complete — applied=%s skipped=%s run_dir=%s",
        applied,
        skipped,
        run_dir,
    )
    return applied, skipped
