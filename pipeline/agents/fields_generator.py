"""
Agent 4 — Fields Generator.

Fills empty derived fields on CVData and generates format-specific content
(e.g. tailored key_qualifications for GIZ) using the filtered CV and DistilledToR.

Input:  runs/{session_id}/mapped_cv.json + tor_data.json + manifest.json
Output: runs/{session_id}/generated_fields.json  (initial write)
"""

from __future__ import annotations

import json
from pathlib import Path

from anthropic import Anthropic

import copy
import logging

from models import FORMAT_PROFILES, CVData
from pipeline.config import ANTHROPIC_SYNTHESIS_MODEL

log = logging.getLogger(__name__)
from pipeline.manifest import update_step
from pipeline.precompute_utils import compute_project_duration, compute_project_year
from pipeline.utils import extract_json_object, resolve_tor_for_agents, strip_code_fences

client = Anthropic()


# ---------------------------------------------------------------------------
# P15 / P2-A4: pre-compute project dates before sending to the LLM
# ---------------------------------------------------------------------------

def _precompute_project_dates(cv_data: dict) -> dict:
    """
    Walk cv_data["relevant_projects"] and fill in empty ``duration`` and
    ``year`` fields using the deterministic Python helpers.

    Only fills fields that are currently empty string "".  Never overwrites
    a non-empty value (i.e. if Agent 1 already extracted a duration, keep it).

    Returns a shallow-copied cv_data dict with the updated projects list.
    """
    result = copy.deepcopy(cv_data)
    for project in result.get("relevant_projects", []):
        date_from = project.get("date_from", "")
        date_to = project.get("date_to", "")

        if not project.get("duration", ""):
            computed = compute_project_duration(date_from, date_to)
            if computed:
                project["duration"] = computed

        if not project.get("year", ""):
            computed = compute_project_year(date_from, date_to)
            if computed:
                project["year"] = computed

    return result


# ---------------------------------------------------------------------------
# Fix 8 Part 3: per-project text cap for A4 input
# ---------------------------------------------------------------------------

# Maximum words per field per project in the A4 user message.
# Prevents token exhaustion from a small number of extremely dense projects
# (e.g. Run 6 WB: one project had 694-word activities_performed).
# The full text is preserved untouched in mapped_cv.json; only the A4
# input copy is trimmed.
A4_INPUT_PROJECT_WORD_CAP: int = 150

# Fields capped per project.  Other project fields are never trimmed.
_A4_CAPPED_FIELDS: tuple[str, ...] = ("activities_performed", "main_project_features")


def _truncate_project_text_for_a4(cv_data: dict) -> dict:
    """
    Return a deep copy of ``cv_data`` with ``activities_performed`` and
    ``main_project_features`` trimmed to at most ``A4_INPUT_PROJECT_WORD_CAP``
    words per project.

    Trimmed text is suffixed with ``"…"`` (U+2026) so Agent 4 can see that
    the content was cut and avoid claiming completeness in its output.

    Empty fields are left unchanged (no ``"…"`` is appended).
    The original ``cv_data`` dict is never mutated.
    The full text remains intact in ``mapped_cv.json`` on disk.
    """
    result = copy.deepcopy(cv_data)
    for project in result.get("relevant_projects", []):
        for field in _A4_CAPPED_FIELDS:
            text = project.get(field, "") or ""
            words = text.split()
            if len(words) > A4_INPUT_PROJECT_WORD_CAP:
                project[field] = " ".join(words[:A4_INPUT_PROJECT_WORD_CAP]) + "\u2026"
    return result


# ---------------------------------------------------------------------------
# Fix M Part 2: restore original project text after A4 returns
# ---------------------------------------------------------------------------

def _restore_truncated_project_text(
    cv_data_out: dict,
    original_cv_data: dict,
) -> dict:
    """
    Restore ``activities_performed`` and ``main_project_features`` in
    *cv_data_out* from *original_cv_data* for every project, matched by
    list index.

    Purpose
    -------
    ``_truncate_project_text_for_a4`` creates a truncated copy of ``cv_data``
    for the A4 user-message input to prevent token exhaustion.  Agent 4 is
    instructed not to modify already-populated fields, so it copies the
    truncated text verbatim into its output.  This function restores the
    original untruncated text from *original_cv_data* (pre-truncation source)
    before the artifact is written to ``generated_fields.json``.

    Restoration is unconditional per project — the original values are always
    the source of truth regardless of whether A4 introduced the marker or not.

    Parameters
    ----------
    cv_data_out : dict
        The ``model_dump()`` result of A4's validated ``CVData`` output.
    original_cv_data : dict
        The ``cv_data`` dict as it existed *before* truncation was applied
        (i.e. after ``_precompute_project_dates`` but before
        ``_truncate_project_text_for_a4``).

    Returns
    -------
    dict
        A deep copy of *cv_data_out* with the capped fields restored from
        *original_cv_data*.  Neither input is mutated.
    """
    result = copy.deepcopy(cv_data_out)
    out_projects = result.get("relevant_projects", [])
    orig_projects = original_cv_data.get("relevant_projects", [])

    if len(out_projects) != len(orig_projects):
        log.warning(
            "_restore_truncated_project_text: A4 returned %d projects "
            "but the original had %d. Skipping text restoration to avoid "
            "index mismatch — review the A4 output for unexpected project "
            "additions or removals.",
            len(out_projects),
            len(orig_projects),
        )
        return result

    for i, proj in enumerate(out_projects):
        for field in _A4_CAPPED_FIELDS:
            if field in orig_projects[i]:
                proj[field] = orig_projects[i][field]

    return result


SYSTEM_PROMPT_A4 = """
You are the Fields Generator agent in a document processing pipeline. You
receive a filtered CVData object, a DistilledToR object, a FormatProfile,
and pipeline params. Your job is to:

  1. Fill any empty fields in CVData that can be derived from the available
     information.
  2. Generate format-specific content declared in FormatProfile.generative_field_keys
     and write it into CVData.generated_fields.

You are the first agent that writes new content. Everything you write must be
grounded in evidence from the CV — you are a skilled writer, not an inventor.

## OUTPUT PRIORITY ORDER

When you generate your response, always follow this sequence:

  1. **First — generate all `generated_fields` entries (Part 2 below).** This is
     your highest-priority output. The pipeline depends on non-empty
     `generated_fields[].content` to proceed. An empty `content` string
     will cause the pipeline to halt.

  2. **Second — fill empty derived fields (Part 1 below).** If you are
     constrained by output length, ensure Part 2 is complete before filling
     all of Part 1. An incomplete Part 1 is recoverable; an empty
     `generated_fields` is not.

  3. Return the full CVData — both parts must be present in the response.

## Output contract (READ FIRST)
- Your entire response must be a single JSON object — nothing else.
- The FIRST non-whitespace character MUST be `{`. The LAST MUST be `}`.
- No preamble. No reasoning text. No "Here is the JSON". No explanation.
- No markdown fences (no ```json, no ```).
- Do all reasoning silently. Only the JSON object is emitted.
- The output must be a valid, complete CVData object.
- Return the full CVData — not just the fields you changed.

## Tone and style
- Active and punchy. Action verbs. No pronouns.
- No filler phrases: do not use "responsible for", "involved in",
  "participated in", "assisted with", "worked on".
- Every sentence must contain a concrete noun or measurable outcome where
  the source material provides one.
- Good: "Designed grid-integration framework adopted across 3 pilot provinces."
- Bad: "Responsible for supporting the design of grid frameworks."

## Part 1 — Fill empty fields

### present_position
- If empty, derive from the most recent RelevantProject.positions_held.
- If already populated, leave unchanged.

### key_qualifications (extracted field on CVData)
- If empty and no generated version will be produced (which should not happen
  for GIZ), leave as [].
- If already populated from extraction, leave unchanged — do not overwrite.

### relevant_projects — empty subfields only
For each RelevantProject, fill only fields that are empty string "":
- `duration`: the pipeline has pre-computed this value from date_from and
  date_to before calling you. The pre-filled value is already present in the
  `<cv_data>` you received. Copy it exactly as received — do NOT recalculate,
  modify, or derive your own duration value.
- `year`: the pipeline has pre-computed this value as well. Copy it exactly
  as received — do NOT recalculate or derive your own year string.
- All other project fields: never fill — if empty, leave empty.

### All other CVData fields
- Do not touch any field that is already populated.
- Do not generate content for fields not listed above.

## Part 2 — Generate format-specific content

The FormatProfile.generative_field_keys list declares what to generate.
For each key in that list, generate the appropriate content and append
GeneratedField items to CVData.generated_fields.

### Minimum output guarantee

**Never return an empty `content` string for any GeneratedField.**
An empty entry causes a pipeline halt — a weak but honest bullet is always
preferable.

- Generate at least one GeneratedField entry per key in
  `generative_field_keys`, even when CV-ToR alignment is weak or evidence
  is sparse.
- Ground the entry in whatever CV evidence does exist. If the evidence is
  genuinely weak or marginal, produce the most honest bullet possible and
  flag it in `generation_warnings` with a message such as:
  `"Low-confidence <field_key> bullet: <one-sentence reason — e.g. 'No geographic alignment with ToR, used closest available project'>"`.
- Do not omit entries. Do not set `content` to `""`, `null`, or a
  placeholder like `"N/A"`.
- A `generation_warnings` flag is not a substitute for generating
  content — include both.

**This guarantee applies to ALL keys in `generative_field_keys`, regardless
of format or alignment:**
- GIZ runs: `key_qualifications` — at least one entry.
- WB runs: `detailed_tasks` — at least one entry.

Geographic mismatch, sector mismatch, or any alignment weakness does NOT
exempt you from generating at least one entry for each key. If the candidate
has no experience in The Gambia but the ToR requires it, you still produce at
least one `detailed_tasks` entry grounded in the candidate's closest available
experience, flagged via `generation_warnings`:
  `"Low-confidence detailed_tasks entry: No geographic alignment with ToR
  (required: The Gambia); used closest available project."`.

Returning an empty list for any `generative_field_keys` key — including
`detailed_tasks` — causes the pipeline to halt at the post-A4 validator.
A weak but honest entry is always preferable to a halt.

### GIZ: field_key = "key_qualifications"

Generate a set of tailored qualification bullets for this specific assignment.
Each bullet becomes one GeneratedField with field_key="key_qualifications".

#### Source preference: condense the candidate's own KQ when bullet-style

When ``cv_data.key_qualifications`` contains 2 or more entries that are already
in bullet format — sentence-length, achievement- or duration-based
(e.g. "Over 22 years extensive experience...", "Led X for Y years..."),
and are reasonably aligned with the ToR requirements — PREFER to SELECT,
CONDENSE, and LIGHTLY EDIT those existing entries rather than generating
new bullets from scratch.

For each candidate bullet you keep, set ``source = "experience"`` to reflect
that the content is grounded in the candidate's own stated qualifications.

Generate FROM SCRATCH (and use ``source = "tor"`` or ``"generated"``
accordingly) ONLY when one of the following conditions is true:
  1. ``cv_data.key_qualifications`` is empty or ``[]``.
  2. The existing entries are paragraph-style prose (not discrete bullets)
     — multi-sentence running text rather than one-fact-per-entry.
  3. The existing bullets are clearly misaligned with the ToR — wrong sector,
     wrong role type, or covering none of the ToR's required competencies.

Mixing is acceptable: you may keep 1–2 of the candidate's own bullets and
add 1 new ToR-grounded bullet to fill a competency gap. Mark each entry's
``source`` field accurately regardless of whether it came from the candidate
or was newly synthesised.

#### How many bullets to generate
- Read the proposed_position and the ToR's key_tasks and required_competencies.
- Generate one bullet per major competency cluster the ToR requires.
- Aim for 3–6 bullets.
- If the ToR clearly contains fewer than 3 distinct competency clusters, generate
  one bullet per cluster — do not pad with weak or invented content.
- Minimum is 1 strong, well-grounded bullet (see Minimum output guarantee
  above — never return empty content). Maximum is 6.
- Do not pad — a focused set of 2 strong bullets is better than 4 weak ones.

#### What each bullet must do
- Address a specific requirement from the ToR (key_tasks, required_competencies,
  or sector_keywords).
- Be grounded in the expert's actual experience — synthesise across multiple
  projects if needed, but never claim experience that has no basis in the CV.
- Lead with an action verb.
- Be one sentence, maximum 25 words.
- Contain at least one sector keyword from DistilledToR.sector_keywords where
  naturally applicable.

#### source field for each GeneratedField
- "tor"        — bullet addresses a ToR requirement with no direct CV evidence
                 (use sparingly — flag in warnings if more than 1 such bullet)
- "experience" — bullet is grounded in one or more CV projects or qualifications
- "generated"  — bullet synthesises both ToR requirement and CV evidence

#### Ordering
- Place the most ToR-critical bullet first.
- Place geography-specific bullets last.

#### Warnings
If any of the following apply, append a warning string to the output's
`generation_warnings` list:
- More than 1 bullet has source="tor" (weak CV grounding)
- A required_competency from the ToR could not be addressed by any CV evidence
- The expert's CV contains no projects matching the ToR's geography

### World Bank: field_key = "detailed_tasks"

Generate a set of forward-looking task statements describing what the expert
will do on this specific assignment. Each task becomes one GeneratedField
with field_key="detailed_tasks".

These are NOT qualification bullets. They describe future responsibilities,
not past experience. They are written as if addressed to the expert
("You will..." implied, but no pronouns used).

#### How many tasks to generate
- Derive directly from DistilledToR.key_tasks — one GeneratedField per
  distinct task cluster.
- Minimum 1, aim for 3–8 (see Minimum output guarantee above — never
  return empty content). Maximum is 8.
- Do not invent tasks that are not grounded in the ToR.

#### What each task statement must do
- Correspond to a specific item in key_tasks or a clearly implied
  sub-task of one.
- Be concrete and outcome-oriented — state what will be produced or
  delivered, not just what will be done.
- Lead with an action verb.
- Be one sentence, maximum 30 words.
- Include at least one sector keyword from DistilledToR.sector_keywords
  where naturally applicable.
- Good: "Develop a capacity-building curriculum for 40 ministry staff
  covering ESMAP methodologies and renewable energy planning tools."
- Bad: "Support training activities related to energy."

#### source field for each GeneratedField
- "tor"        — task is stated directly in the ToR key_tasks
- "generated"  — task is inferred from ToR context and expert background

#### Ordering
- Order tasks to match the logical sequence of the assignment
  (scoping → analysis → delivery → reporting).

#### Warnings
If any of the following apply, append a warning string to the output's
`generation_warnings` list:
- A key_task from the ToR could not be mapped to any expert competency
  or past project
- The expert has no prior project in the ToR's stated geography

## Output structure
Return the full CVData object with:
- `generated_fields` populated with all GeneratedField items produced
- `present_position` and project subfields filled where applicable
- A top-level `generation_warnings` list (may be empty)

The output JSON must have this shape:
{
  "data": { ...full CVData object... },
  "generation_warnings": []
}

## Inputs
The user message will contain:
  <cv_data>       — filtered CVData from mapped_cv.json          </cv_data>
  <tor_data>      — DistilledToR from tor_data.json              </tor_data>
  <format_profile>— FormatProfile for this run's donor format    </format_profile>
  <params>        — pipeline params (proposed_position, etc.)    </params>
"""

def run(run_dir: Path) -> CVData:
    """
    Generate format-specific fields and write the initial generated_fields.json.

    Returns:
        Validated CVData with generated_fields populated.
    """
    update_step(run_dir, "fields_generator", "running")

    mapped_raw = json.loads((run_dir / "mapped_cv.json").read_text(encoding="utf-8"))
    tor_raw = json.loads((run_dir / "tor_data.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    cv_data = mapped_raw["data"]
    tor_data = resolve_tor_for_agents(tor_raw, context="fields_generator.run")
    params = manifest["params"]

    raw_donor = params.get("donor", "giz")
    donor = raw_donor.strip().lower().replace(" ", "_")

    if donor not in FORMAT_PROFILES:
        update_step(run_dir, "fields_generator", "failed")
        raise ValueError(
            f"Unknown donor format: '{raw_donor}'. " f"Valid values: {list(FORMAT_PROFILES.keys())}"
        )

    format_profile = FORMAT_PROFILES[donor]

    # P15/P2-A4 — NOTE (Round 5): duration and year pre-compute was moved upstream
    # to cv_tor_mapper.run() (Fix 4) so A3's LLM sees populated duration values.
    # The pre-fill is therefore already applied before this point; calling
    # _precompute_project_dates here again would be a no-op (it only fills
    # empty values) but we skip it to avoid the redundant deepcopy on every run.
    # cv_data = _precompute_project_dates(cv_data)  ← now happens in cv_tor_mapper

    # Fix M Part 2: preserve the pre-truncation copy so full text can be
    # restored into the artifact after A4 returns.
    cv_data_full = cv_data

    # Fix 8 Part 3: trim activities_performed and main_project_features to
    # A4_INPUT_PROJECT_WORD_CAP words per project.  Prevents token exhaustion
    # from a small number of extremely dense projects (e.g. WB sessions with
    # 600+ word activity descriptions).  mapped_cv.json is not affected.
    # cv_data_full holds the untruncated source for the artifact write.
    cv_data = _truncate_project_text_for_a4(cv_data)

    user_message = (
        f"<cv_data>\n{json.dumps(cv_data, indent=2)}\n</cv_data>\n\n"
        f"<tor_data>\n{json.dumps(tor_data, indent=2)}\n</tor_data>\n\n"
        f"<format_profile>\n{json.dumps(format_profile.model_dump(), indent=2)}"
        "\n</format_profile>\n\n"
        f"<params>\n{json.dumps(params, indent=2)}\n</params>"
    )

    response = client.messages.create(
        model=ANTHROPIC_SYNTHESIS_MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT_A4,
        messages=[{"role": "user", "content": user_message}],
    )

    if response.stop_reason == "max_tokens":
        update_step(run_dir, "fields_generator", "failed")
        raise ValueError("Fields Generator response truncated (max_tokens reached).")

    raw = strip_code_fences(response.content[0].text.strip())
    raw = extract_json_object(raw)

    try:
        parsed = json.loads(raw)
        cv_data_out = CVData.model_validate(parsed["data"])
        generation_warnings = parsed.get("generation_warnings", [])
    except Exception as exc:
        update_step(run_dir, "fields_generator", "failed")
        raise ValueError(
            f"Fields Generator returned invalid output: {exc}\n\nRaw output:\n{raw}"
        ) from exc

    # Fix M Part 2: restore original activities_performed / main_project_features
    # from the pre-truncation cv_data_full into A4's output before writing the
    # artifact.  This prevents the "…" truncation marker from leaking into
    # generated_fields.json and being flagged by A5 as a coherence break.
    generated_dict = _restore_truncated_project_text(
        cv_data_out.model_dump(), cv_data_full
    )

    gf_path = run_dir / "generated_fields.json"
    existing = json.loads(gf_path.read_text(encoding="utf-8")) if gf_path.exists() else {}
    existing.update(
        {
            "approved": False,
            "approved_at": None,
            "generated": generated_dict,
            "generation_warnings": generation_warnings,
            "review": None,
            "compression": None,
        }
    )
    gf_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")

    update_step(run_dir, "fields_generator", "done")
    return cv_data_out
