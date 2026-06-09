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

from models import FORMAT_PROFILES, CVData
from pipeline.config import ANTHROPIC_SYNTHESIS_MODEL, ANTHROPIC_MAX_TOKENS
from pipeline.manifest import update_step
from pipeline.precompute_utils import (
    compute_project_duration,
    compute_project_year,
    truncate_project_text,
)
from pipeline.utils import call_agent_json, resolve_tor_for_agents

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

  3. Return the PATCH object (see "## Output structure") — never the CVData.
     `generated_fields` (Part 2) is required; Part 1 fields are optional.

## Output contract (READ FIRST)
- Your entire response must be a single JSON object — nothing else.
- The FIRST non-whitespace character MUST be `{`. The LAST MUST be `}`.
- No preamble. No reasoning text. No "Here is the JSON". No explanation.
- No markdown fences (no ```json, no ```).
- Do all reasoning silently. Only the JSON object is emitted.
- Output a small PATCH object (shape in "## Output structure"), NOT the CVData.
- Do NOT echo or reproduce the CV. The pipeline already has the full CVData and
  merges your patch into it. Reproducing it wastes output and risks truncation.

## Tone and style
- Active and punchy. Action verbs. No pronouns.
- No filler phrases: do not use "responsible for", "involved in",
  "participated in", "assisted with", "worked on".
- Every sentence must contain a concrete noun or measurable outcome where
  the source material provides one.
- Good: "Designed grid-integration framework adopted across 3 pilot provinces."
- Bad: "Responsible for supporting the design of grid frameworks."

## Part 1 — Targeted field fills (reported as patch entries, NOT echoed)

You do not return the CVData, so you only report the few fields you fill.
`duration` and `year` are pre-computed by the pipeline — do NOT touch them.

### present_position
- If `<cv_data>.present_position` is empty, derive it from the most recent
  RelevantProject's `positions_held` and report it in the patch's
  `present_position` field.
- If it is already populated, omit `present_position` from the patch (or set
  it to ""). Never overwrite a populated value.

### project main_project_features (project_overviews)

Each entry is `{"index": <0-based index into relevant_projects>, "main_project_features": "<text>"}`.
The `<params>.donor` value selects the behaviour:

**GIZ (donor = "giz") — write a full narrative for EVERY project.**
The GIZ output renders ONLY `main_project_features` as the project description —
it never shows `activities_performed`. So for GIZ you MUST emit one
`project_overviews` entry for EVERY project in `<cv_data>.relevant_projects`.
- 50–90 words. Weave together what the project IS (objective, sector,
  client/donor programme, geography) AND the candidate's concrete role and
  contributions — drawn from that project's existing `main_project_features`,
  `activities_performed`, `positions_held`, and metadata.
- It must read as a self-contained project description; the reader will not see
  `activities_performed` separately.
- Ground every statement in that project's own data — never invent figures,
  clients, or outcomes. Past tense, active voice, no pronouns, no filler.
- Emit an entry even when source detail is thin: write the best 1–2 sentence
  narrative the available metadata supports. These entries OVERWRITE the
  extracted text, so cover every project.

**World Bank (donor = "world_bank") — fill only when empty.**
WB renders `main_project_features` and `activities_performed` separately, so do
NOT merge them. Emit an entry ONLY for a project whose `main_project_features`
is empty AND whose `activities_performed` is populated:
- Describe what the project IS (objective, sector, scope, client/donor) — NOT
  what the candidate did. Never duplicate `activities_performed`.
- 1–3 sentences scaled to available metadata.
- If both are empty, or `main_project_features` is already populated, do NOT
  emit an entry for that project.

Use each project's index in `<cv_data>.relevant_projects` as `index`. Do not
report any field other than `present_position` and `project_overviews` in Part 1.

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

#### Bullet style — noun/stat-led preference
Strong preference (not a hard prohibition) for opening with a quantified noun
phrase rather than an action verb:
- Year-count: "X years of experience in…"
- Measurable metric: "Led X projects across Y countries…"
- Domain noun: "Extensive experience in energy policy…"

Verb-led openings ("Delivered…", "Conducted…", "Designed…", "Drafted…") are
not the preferred convention and should be avoided unless no credible noun
phrase can be constructed from the available CV evidence.

Exceptions where a verb is inherently the stronger framing are acceptable:
"Appointed as…", "Elected to…", "Awarded…".

#### Candidate-anchoring rule
Each bullet must be grounded in evidence unique to this candidate. At least
one candidate-specific detail must appear in every bullet:
- An organisation name (employer, client, or donor)
- A country or region of assignment
- A measurable outcome (project count, team size, budget figure)
- A role title held by this candidate
- A named instrument, regulation, framework, or project

A bullet that could apply to any expert with broadly similar experience
against this ToR is insufficient. If you cannot anchor the bullet to a
specific candidate detail, rewrite it using the closest available evidence
from the CV and flag it in ``generation_warnings``.

This rule applies to both GIZ (key_qualifications) and WB (detailed_tasks) formats.

#### What each bullet must do
- Address a specific requirement from the ToR (key_tasks, required_competencies,
  or sector_keywords).
- Be grounded in the expert's actual experience — synthesise across multiple
  projects if needed, but never claim experience that has no basis in the CV.
- Open with a noun/stat-led phrase (see Bullet style above). If using a verb,
  prefer inherently strong ones (Appointed, Elected, Awarded).
- Be one sentence, maximum 25 words.
- Contain at least one sector keyword from DistilledToR.sector_keywords where
  naturally applicable.
- Include at least one candidate-specific detail (see Candidate-anchoring rule).

#### source field for each GeneratedField
- "tor"        — bullet addresses a ToR requirement with no direct CV evidence
                 (use sparingly — flag in warnings if more than 1 such bullet)
- "experience" — bullet is grounded in CV projects, qualifications, certifications,
                 or training entries (a certifications[] entry OR a training[] entry
                 matching a required_competency may ground a KQ bullet with
                 source="experience"; apply editorial judgment — not every training
                 entry warrants a bullet, surface only when directly relevant to a
                 ToR required competency)
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
Return a PATCH object — never the CVData. Shape:
{
  "generated_fields": [
    { "field_key": "key_qualifications" | "detailed_tasks", "content": "...", "source": "tor" | "experience" | "generated" }
  ],
  "present_position": "<string, or omit / \"\" if already populated>",
  "project_overviews": [
    { "index": 0, "main_project_features": "..." }
  ],
  "generation_warnings": []
}

- `generated_fields` is REQUIRED and must be non-empty (see Minimum output
  guarantee) — it holds every GeneratedField item you produce in Part 2.
- `present_position` and `project_overviews` are the only Part 1 outputs.
- `generation_warnings` is a (possibly empty) list of warning strings.
- Emit nothing else — no CV fields, no `data` block.

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
    # to cv_tor_mapper.run() (R5-B) so A3's LLM sees populated duration values.
    # The pre-fill is therefore already applied before this point; calling
    # _precompute_project_dates here again would be a no-op (it only fills
    # empty values) but we skip it to avoid the redundant deepcopy on every run.
    # cv_data = _precompute_project_dates(cv_data)  ← now happens in cv_tor_mapper

    # R7-J: A4 receives full untruncated cv_data on the happy path. A4 now returns
    # a PATCH (generated_fields + present_position + project_overviews) instead of
    # echoing the whole CVData — the pipeline merges it below. This keeps A4 output
    # small regardless of how rich the Opus-extracted input is.

    def _build_user_message(cd: dict) -> str:
        return (
            f"<cv_data>\n{json.dumps(cd, indent=2)}\n</cv_data>\n\n"
            f"<tor_data>\n{json.dumps(tor_data, indent=2)}\n</tor_data>\n\n"
            f"<format_profile>\n{json.dumps(format_profile.model_dump(), indent=2)}"
            "\n</format_profile>\n\n"
            f"<params>\n{json.dumps(params, indent=2)}\n</params>"
        )

    def _reduce_input(attempt: int) -> str:
        # Recovery only: shrink per-project free-text so a retry sends less input.
        word_cap = 200 if attempt == 1 else 120
        return _build_user_message(truncate_project_text(cv_data, word_cap))

    try:
        parsed = call_agent_json(
            client=client,
            model=ANTHROPIC_SYNTHESIS_MODEL,
            max_tokens=ANTHROPIC_MAX_TOKENS,  # ceiling, not a target
            system=SYSTEM_PROMPT_A4,
            user_message=_build_user_message(cv_data),
            context="Fields Generator",
            reduce_input=_reduce_input,
        )
    except Exception as exc:
        update_step(run_dir, "fields_generator", "failed")
        raise ValueError(f"Fields Generator failed: {exc}") from exc

    try:
        # A4 returns a PATCH, not the CVData. Merge it into the mapped CVData.
        merged = copy.deepcopy(cv_data)
        merged["generated_fields"] = parsed.get("generated_fields", []) or []

        present_position = (parsed.get("present_position") or "").strip()
        if present_position and not (merged.get("present_position") or "").strip():
            merged["present_position"] = present_position

        # Donor-aware merge of project_overviews:
        #  - GIZ: main_project_features is the ONLY rendered project text, so a
        #    narrative is written for every project — OVERWRITE the terse extract.
        #  - WB: main_project_features and activities_performed render separately,
        #    so only FILL when empty (never overwrite / merge).
        projects = merged.get("relevant_projects", [])
        is_giz = donor == "giz"
        for overview in parsed.get("project_overviews", []) or []:
            try:
                idx = int(overview.get("index"))
            except (TypeError, ValueError):
                continue
            text = (overview.get("main_project_features") or "").strip()
            if not text or not (0 <= idx < len(projects)):
                continue
            current = (projects[idx].get("main_project_features") or "").strip()
            if is_giz or not current:
                projects[idx]["main_project_features"] = text

        cv_data_out = CVData.model_validate(merged)
        generation_warnings = parsed.get("generation_warnings", []) or []
    except Exception as exc:
        update_step(run_dir, "fields_generator", "failed")
        raise ValueError(
            f"Fields Generator produced an invalid patch: {exc}\n\n"
            f"Parsed keys: {list(parsed.keys())}"
        ) from exc

    generated_dict = cv_data_out.model_dump()

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
    try:
        from api.services.run_artifacts import push_run_artifact

        push_run_artifact(run_dir.name, gf_path)
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "generated_fields Storage sync failed for %s", run_dir.name, exc_info=True
        )

    update_step(run_dir, "fields_generator", "done")
    return cv_data_out
