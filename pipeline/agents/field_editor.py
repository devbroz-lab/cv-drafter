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
applied : list[dict]
    Each item is {"path", "instruction", "previous_value", "new_value"}.
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

from pipeline.utils import strip_code_fences
from pipeline.utils.cefr import map_cefr as _map_cefr
from pipeline.config import ANTHROPIC_MODEL

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model — Dev 2's choice: Sonnet for editing quality
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# R7-I: RENDERER_FIELD_MAP — per-donor rendered project fields
# ---------------------------------------------------------------------------
# Keyed by normalised donor format string. Value: set of project-level field
# names that are actually placed in cells in the output .docx for that donor.
# A7 uses this map to detect and redirect edits to non-rendered fields before
# calling Claude, avoiding invisible changes that write to the data model but
# produce no visible change in the rendered document.

RENDERER_FIELD_MAP: dict[str, set[str]] = {
    "giz": {
        # Fields rendered in GIZ Table 2 (relevant_projects section):
        "project_name",
        "date_from",
        "date_to",
        "location",
        "company",
        "positions_held",
        "main_project_features",
        "client",
        "donor",
        "duration",
        # NOTE: "activities_performed" is NOT in this set — it is passed to the
        # template context by giz.py but is never placed in any table cell by
        # giz_dynamic_template.py. Editing it on a GIZ run has no visible effect.
    },
    "world_bank": {
        # Fields rendered in WB Table (relevant_projects section):
        "project_name",
        "year",
        "location",
        "client",
        "main_project_features",
        "positions_held",
        "activities_performed",
        # "tasks_assigned" is the rendered field (from generated_fields[].content),
        # not a raw project field — edits go through generated_fields[i].content paths.
    },
}

# Non-rendered project field → nearest rendered equivalent, per donor.
# Used to redirect edits so the change is visible in the output document.
_RENDERER_REDIRECT_MAP: dict[str, dict[str, str]] = {
    "giz": {
        "activities_performed": "main_project_features",
    },
    "world_bank": {},
}


def _check_renderer_field(
    field_path: str,
    donor: str,
) -> tuple[str | None, str | None]:
    """
    Check whether the target field is rendered for the given donor.

    Returns (redirect_path, skip_reason):
      - (None, None)              — field IS rendered; proceed normally.
      - (redirect_path, None)     — field is not rendered but can be redirected.
      - (None, skip_reason)       — field is not rendered and has no equivalent;
                                    caller should skip with the reason string.
    """
    if not donor or donor not in RENDERER_FIELD_MAP:
        return None, None  # unknown donor — no renderer awareness, proceed normally

    # Extract the leaf field key from paths like
    # "relevant_projects[1].activities_performed" -> "activities_performed"
    leaf = _field_key_from_path(field_path)

    # Only check project-level fields (path must contain "relevant_projects")
    if "relevant_projects" not in field_path:
        return None, None

    rendered_fields = RENDERER_FIELD_MAP[donor]
    if leaf in rendered_fields:
        return None, None  # rendered — no action needed

    # Field is NOT rendered. Try to redirect.
    redirect_leaf = _RENDERER_REDIRECT_MAP.get(donor, {}).get(leaf)
    if redirect_leaf:
        # Build the redirect path: replace the leaf in the original path
        import re as _re
        redirect_path = _re.sub(r"(\w+)$", redirect_leaf, field_path)
        return redirect_path, None

    # No redirect available — skip with explanation
    reason = (
        f"Field '{leaf}' is not rendered in the {donor.upper()} output document "
        f"and has no rendered equivalent. Edit has no visible effect."
    )
    return None, reason


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


def _preview_value(value: object) -> str:
    """Collapse whitespace and cap scalar values for API display."""
    text = " ".join(str(value).split())
    return _truncate_reason(text)


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
# Paragraph placeholder paths (Docx viewer fallback → key_qualifications[i])
# ---------------------------------------------------------------------------

_PARAGRAPH_PLACEHOLDER = re.compile(r"^paragraph_\d+$")


def _strip_bullet_prefix(s: str) -> str:
    # Leading bullets / dashes (hyphen last in class to avoid range ambiguity)
    return re.sub(r"^[\s•·▪▫\u2022\u2023–—*\-]+\s*", "", s.strip())


def _normalize_whitespace(s: str) -> str:
    return " ".join(s.split())


def _normalized_scalar_equals(a: object, b: object) -> bool:
    """Whitespace-insensitive equality for comparing edited scalar strings."""
    return _normalize_whitespace(str(a)).lower() == _normalize_whitespace(str(b)).lower()


def _key_qualification_bullets(generated: dict) -> list[str]:
    """
    Return the KQ bullet list that the GIZ renderer will display.

    Priority mirrors the renderer (_build_context in templates/giz.py):
      1. generated_fields entries with field_key == "key_qualifications" and
         non-empty content  (LLM-generated content).
      2. generated["key_qualifications"] raw list as fallback.
    """
    gf = generated.get("generated_fields")
    if isinstance(gf, list):
        out = [
            str(e.get("content", "")).strip()
            for e in gf
            if isinstance(e, dict)
            and e.get("field_key") == "key_qualifications"
            and str(e.get("content", "")).strip()
        ]
        if out:
            return out
    raw = generated.get("key_qualifications")
    if isinstance(raw, list) and raw:
        out = [str(x).strip() for x in raw if str(x).strip()]
        if out:
            return out
    return []


def _key_qualification_source(generated: dict) -> str:
    """
    Return which data source provides the active KQ bullets.

    Returns "generated_fields" when the renderer would use generated_fields
    content, "raw" when it falls back to key_qualifications, or "none" when
    both are empty.
    """
    gf = generated.get("generated_fields")
    if isinstance(gf, list):
        has_gf = any(
            isinstance(e, dict)
            and e.get("field_key") == "key_qualifications"
            and str(e.get("content", "")).strip()
            for e in gf
        )
        if has_gf:
            return "generated_fields"
    raw = generated.get("key_qualifications")
    if isinstance(raw, list) and any(str(x).strip() for x in raw):
        return "raw"
    return "none"


# ---------------------------------------------------------------------------
# Public API-facing translation for _key_qualification_source
# ---------------------------------------------------------------------------

_KQ_SOURCE_API_LABEL: dict[str, str] = {
    "generated_fields": "ai_generated",
    "raw":              "extracted",
    "none":             "absent",
}


def kq_source_label(generated: dict) -> str:
    """
    Return the API-facing label for the active KQ source.

    Maps the internal ``_key_qualification_source`` return values to
    user-friendly labels suitable for inclusion in the POST /field-edit
    response body:

    ``"ai_generated"``
        Agent 4 produced ToR-tailored key_qualification bullets.
        Field edits target ``generated_fields[j].content`` paths.

    ``"extracted"``
        Agent 4 produced no usable content.  The renderer fell back to
        Agent 1's raw ``key_qualifications`` list.  Edits target
        ``key_qualifications[i]`` paths.  The frontend should surface a
        contextual warning so the user knows they are editing the raw
        extraction, not AI-generated content.

    ``"absent"``
        Neither source has any bullets.  The key qualifications section
        is empty.  Field edits to KQ are unlikely to have any effect.
    """
    return _KQ_SOURCE_API_LABEL[_key_qualification_source(generated)]


def _key_qualification_path_for_index(generated: dict, bullet_index: int) -> str:
    """
    Return the canonical dot-path for the KQ bullet at *bullet_index*.

    When the active source is generated_fields, returns
    ``generated_fields[j].content`` for the j-th non-empty KQ entry.
    When the active source is the raw list, returns
    ``key_qualifications[bullet_index]``.
    """
    source = _key_qualification_source(generated)
    if source == "generated_fields":
        gf = generated.get("generated_fields", [])
        kq_entries = [
            (j, e)
            for j, e in enumerate(gf)
            if isinstance(e, dict)
            and e.get("field_key") == "key_qualifications"
            and str(e.get("content", "")).strip()
        ]
        if bullet_index < len(kq_entries):
            j = kq_entries[bullet_index][0]
            return f"generated_fields[{j}].content"
    return f"key_qualifications[{bullet_index}]"


_KQ_TEXT_MATCH_MIN_SCORE = 40
_ORI_TEXT_MATCH_MIN_SCORE = 35


def _match_key_qualification_index(paragraph_text: str, bullets: list[str]) -> int | None:
    """Best-effort match of clicked text to a key_qualifications bullet (mirrors UI logic)."""
    p0 = _strip_bullet_prefix(paragraph_text)
    p = _normalize_whitespace(p0).lower()
    if not p or not bullets:
        return None
    best_idx: int | None = None
    best_score = 0
    for i, bullet in enumerate(bullets):
        b0 = _strip_bullet_prefix(bullet)
        b = _normalize_whitespace(b0).lower()
        if not b:
            continue
        if p == b:
            score = 100
        elif p in b or b in p:
            score = 85
        else:
            pw = {w for w in p.split() if len(w) > 1}
            bw = {w for w in b.split() if len(w) > 1}
            inter = len(pw & bw)
            union = len(pw) + len(bw) - inter
            score = round(100 * inter / union) if union else 0
        if score > best_score:
            best_score = score
            best_idx = i
    if best_idx is None or best_score < _KQ_TEXT_MATCH_MIN_SCORE:
        return None
    return best_idx


def _anchor_matches_other_relevant_info(anchor: str, ori: str) -> bool:
    """True if clicked paragraph text is part of the stored other_relevant_info body."""
    ori_s = str(ori).strip()
    if not ori_s:
        return False
    p = _normalize_whitespace(_strip_bullet_prefix(anchor)).lower()
    o = _normalize_whitespace(ori_s).lower()
    if not p:
        return False
    if p == o:
        return True
    if o in p and len(o) >= 12:
        return True
    if p in o:
        return True
    pw = {w for w in p.split() if len(w) > 1}
    ow = {w for w in o.split() if len(w) > 1}
    if not pw:
        return False
    inter = len(pw & ow)
    union = len(pw) + len(ow) - inter
    score = round(100 * inter / union) if union else 0
    return score >= _ORI_TEXT_MATCH_MIN_SCORE


def resolve_paragraph_placeholder_path(
    generated: dict,
    field_path: str,
    anchor_text: str | None,
) -> str:
    """
    Map frontend fallback paths like ``paragraph_20`` to real dot-paths using
    anchor_text: try ``key_qualifications[i]`` first, then ``other_relevant_info``.
    """
    if not _PARAGRAPH_PLACEHOLDER.match(field_path):
        return field_path
    if not anchor_text or not str(anchor_text).strip():
        return field_path
    a = str(anchor_text).strip()

    bullets = _key_qualification_bullets(generated)
    if bullets:
        idx = _match_key_qualification_index(a, bullets)
        if idx is not None:
            return _key_qualification_path_for_index(generated, idx)

    ori = generated.get("other_relevant_info")
    if isinstance(ori, str) and ori.strip() and _anchor_matches_other_relevant_info(a, ori):
        return "other_relevant_info"

    return field_path


# ---------------------------------------------------------------------------
# PROMPT — copied verbatim from field_editor_agent.py by Dev 2
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_A7 = """\
You are a copy-editor applying recruiter instructions to professional CV fields \
formatted for international development donors (GIZ, World Bank).

Your only job is to carry out the recruiter's edit instruction and return a JSON \
object — nothing else. The recruiter is a trusted professional with direct \
knowledge of the candidate. Their instructions are authoritative and may include \
facts the recruiter has been told by the candidate or the candidate's firm.

RESPONSE FORMAT
---------------
You must always respond with exactly one of these two JSON shapes:

  {"action": "apply", "value": "<edited field value as a plain string>"}
  {"action": "skip",  "reason": "<one short sentence, max 25 words, explaining why>"}

DEFAULT: ALWAYS USE "apply"
---------------------------
"apply" is your default action. Execute the instruction as literally as possible.

Use "skip" ONLY in this one situation:
  The instruction asks you to add a specific named credential, certification, \
publication, or award (e.g. "add their PMP certification", "mention the 2019 \
UN award") AND the instruction itself does not supply the necessary detail \
(name, year, issuing body) AND it is absent from the CV context provided. \
In this case adding it would require you to independently invent a verifiable \
claim — skip and explain what detail is missing.

DO NOT use "skip" for any of the following — use "apply" instead:
  - The recruiter supplies new information in the instruction itself — even if \
it is absent from the CV context. If the instruction contains the fact, include it.
  - Changing or correcting a location, city, country, or region
  - Adding a project name, employer name, or role title the recruiter provides
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
it, compress existing content first to make room — do not drop the new \
information the recruiter has asked you to add.
- Apply donor format conventions:
    GIZ        — active verbs, past tense, evidence-grounded, concise.
    World Bank — forward-looking task statements, action verbs, outcome-oriented.
- Do not add commentary before or after the JSON object.

DONOR-AWARE FIELD PATHS
-----------------------
Field paths are donor-aware. Some fields exist in the data model but are not
rendered in the output document for a given donor format:
  - GIZ:        "activities_performed" on relevant_projects is NOT rendered.
  - World Bank: "activities_performed" on relevant_projects IS rendered.

The pipeline redirects edits to non-rendered fields to the nearest rendered
equivalent before calling you (e.g. GIZ activities_performed → main_project_features).
If you receive a field path, it has already been validated as a rendered field.

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
    Call Claude for a single field edit using JSON schema.

    Returns a parsed dict with one of these shapes:
      {"action": "apply", "value": str}
      {"action": "skip",  "reason": str}

    Raises ValueError if the response cannot be parsed into either shape.
    """
    raw = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2000,
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
        ],
    )

    raw_text = strip_code_fences(raw.content[0].text)
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Response was not valid JSON: {exc}\nRaw: {raw_text!r}"
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
) -> tuple[dict, list[dict], list[dict]]:
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
    applied: list[dict] = []
    skipped: list[dict] = []

    for i, edit in enumerate(edits, start=1):
        raw_path = edit["field_path"]
        instruction = edit["instruction"]
        anchor_text = edit.get("anchor_text")

        field_path = resolve_paragraph_placeholder_path(mutated, raw_path, anchor_text)
        if field_path != raw_path:
            log.info("[Edit %d/%d] resolved path '%s' → '%s'", i, len(edits), raw_path, field_path)

        # R7-I: redirect or skip edits targeting non-rendered project fields.
        redirect_path, renderer_skip_reason = _check_renderer_field(field_path, donor)
        if renderer_skip_reason:
            log.info("  SKIPPED (non-rendered field) — %s", renderer_skip_reason)
            skipped.append({"path": field_path, "reason": _truncate_reason(renderer_skip_reason)})
            continue
        if redirect_path:
            log.info(
                "  REDIRECTED (non-rendered field) '%s' → '%s'", field_path, redirect_path
            )
            field_path = redirect_path

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

        # Fix 3: GIZ CEFR enrichment — when the stored *_cefr field is empty
        # the renderer derives the displayed value from the sibling *_raw field
        # via _resolve_cefr.  Pass that rendered display value to Claude so the
        # agent edits from what the user actually saw in the document, not from
        # an empty string.
        prompt_current_value = current_value
        if donor == "giz" and not str(current_value).strip():
            _cefr_m = re.match(
                r"^languages\[(\d+)\]\.(reading|speaking|writing)_cefr$", field_path
            )
            if _cefr_m:
                _lang_idx = int(_cefr_m.group(1))
                _raw_key = f"{_cefr_m.group(2)}_raw"
                try:
                    _raw_val = mutated.get("languages", [])[_lang_idx].get(_raw_key, "")
                    _mapped = _map_cefr(str(_raw_val))
                    if _mapped:
                        prompt_current_value = _mapped
                        log.debug(
                            "  CEFR enrichment: %s is empty; using mapped raw value '%s'",
                            field_path,
                            _mapped,
                        )
                except (IndexError, AttributeError, TypeError):
                    pass  # enrichment is advisory — any failure is silent

        # --- Call Claude ---
        try:
            result = call_claude(
                client,
                field_path,
                prompt_current_value,
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

        if _normalized_scalar_equals(new_value, current_value):
            reason = (
                "Editor produced text identical to the original after normalizing whitespace. "
                "Try a more explicit instruction or specify exact wording to change."
            )
            log.warning("  SKIPPED — unchanged value for '%s'", field_path)
            skipped.append({"path": field_path, "reason": _truncate_reason(reason)})
            continue

        # --- Write back ---
        try:
            set_by_path(mutated, field_path, new_value)
        except (KeyError, IndexError, TypeError) as exc:
            reason = f"write-back failed: {exc}"
            log.warning("  Write-back failed for '%s': %s", field_path, exc)
            skipped.append({"path": field_path, "reason": _truncate_reason(reason)})
            continue

        log.info("  applied '%s' → %s", field_path, new_value[:120])
        applied.append(
            {
                "path": field_path,
                "instruction": instruction,
                "previous_value": _preview_value(current_value),
                "new_value": _preview_value(new_value),
            }
        )

    return mutated, applied, skipped


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------


def run(
    run_dir: Path,
    edits: list[dict],
    donor: str = "",
    cv_context: dict | None = None,
) -> tuple[list[dict], list[dict], str]:
    """
    Pipeline entry point called by the HTTP handler (POST /field-edit).

    Reads generated_fields.json, applies edits via run_field_editor(),
    writes the mutated generated dict back (preserving all top-level keys),
    and returns (applied, skipped, kq_source).

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
    kq_source : str
        API-facing label for the active KQ source after edits are applied.
        One of ``"ai_generated"``, ``"extracted"``, or ``"absent"``.
        Computed from the post-edit state of mutated so that a successful
        edit promoting the source is reflected accurately.
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

    # Compute kq_source from the post-edit state so that a successful edit
    # that promotes the source (e.g. absent → ai_generated) is reflected.
    kq_source = kq_source_label(mutated)

    # Write back — preserve all top-level keys, only replace "generated"
    gf["generated"] = mutated
    gf_path.write_text(json.dumps(gf, indent=2, ensure_ascii=False), encoding="utf-8")

    log.info(
        "field_editor complete — applied=%s skipped=%s kq_source=%s run_dir=%s",
        applied,
        skipped,
        kq_source,
        run_dir,
    )
    return applied, skipped, kq_source
