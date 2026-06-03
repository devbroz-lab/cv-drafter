"""
Agent 1 — CV Extractor.

Reads tagged CV text and extracts its contents into a structured CVData object
using Claude.  Runs in parallel with Agent 2 (ToR Summarizer) during Phase 1.

Input:  plain-tagged CV text (from pipeline/extractor)
Output: runs/{session_id}/cv_data.json
"""

from __future__ import annotations

import json
from pathlib import Path

from anthropic import Anthropic

from models import CVData, RelevantProject
from pipeline.config import ANTHROPIC_MODEL_EXTRACTOR, ANTHROPIC_MAX_TOKENS
from pipeline.manifest import update_step
from pipeline.utils import extract_json_object, strip_code_fences
from pipeline.utils.cefr import map_cefr, map_numeric_scale_inverted

client = Anthropic()


SYSTEM_PROMPT_A1 = """
You are the CV Extractor agent in a document processing pipeline. Your sole job
is to read a CV document and extract its contents into a structured JSON object
that strictly conforms to the CVData schema.

## Output contract (READ FIRST)
- Your entire response must be a single JSON object — nothing else.
- The FIRST non-whitespace character MUST be `{`. The LAST MUST be `}`.
- No preamble. No reasoning text. No "Here is the JSON". No explanation.
- No markdown fences (no ```json, no ```).
- Do all reasoning silently. Only the JSON object is emitted.
- The JSON must be a valid, complete CVData object.
- Every field defined in the schema must be present.
- All string fields default to "" if not found.
- All list fields default to [] if not found.
- Never use null.

## Schema
{{ CVData.model_json_schema() }}

## Extraction rules

### Strictness
- Extract only what is explicitly present in the CV text.
- Do not infer, assume, or generate content.
- If a field is not stated, leave it as "" or [].

### Unfilled placeholder detection

Watch for text that appears to be an unfilled template placeholder. Common
patterns: a standalone uppercase letter where a number belongs ("More than X
years", "team of N people"); bracket-delimited tokens (`[YEARS]`, `[NUMBER]`,
`<YEARS>`, `{n}`).

When detected: extract the text faithfully, then append to `extraction_warnings`:
  `"<field_path> contains likely unfilled placeholder: '<verbatim text>'"`
  Example: `"key_qualifications[3] contains likely unfilled placeholder:
  'More than X years experience as Team Leader'"`

Do NOT flag genuine abbreviations or established terms (X-ray, HIV/AIDS).

- Exception 1: if `present_position` is not explicitly stated, derive it from
  `relevant_projects` using the following priority order:
    1. Projects with `date_to` equal to "Present" (case-insensitive) rank above
       all dated entries.
    2. Among multiple "Present" entries, use the one with the latest `date_from`.
    3. Among dated entries (no "Present"), use the one with the latest `date_to`.
    4. If still tied after all of the above, use the first entry in document order.
  Use the `positions_held` field of the chosen project as `present_position`.
  If `positions_held` is also empty, use `project_name` as a fallback.
- Exception 2: derive `full_name` by joining `first_names` + `family_name`
  if a single full-name string is not explicitly present.

### Experience section — format-specific rules

The donor format is passed in the user message as <donor>. Apply the rules
for the matching format below.

#### GIZ
- ALL work experience goes into `relevant_projects`. One entry per project
  or assignment.
- Leave `employment_record` as [] — it is a WB-only field.
- If the CV lists a general job history table (employer + period, no project
  detail), map each entry to a RelevantProject with `project_name` (from
  employer), `date_from`, `date_to`, and `positions_held` populated, and leave
  project-specific fields (client, donor, main_project_features,
  activities_performed) as "".
- See `### Employment-only fallback` below — that rule applies to GIZ runs too.
  NEVER return an empty `relevant_projects` for a GIZ run.

#### World Bank (donor = "world_bank")
- Populate BOTH `employment_record` AND `relevant_projects`.
- `employment_record`: one entry per employer or job role. Each entry captures
  the institutional employment history — who the expert worked for, in what
  role, and for how long. Fields to populate: `employer`, `positions_held`,
  `from_date`, `to_date`, `country`. Leave `location` and `description` as ""
  unless the CV provides them explicitly.
- `relevant_projects`: one entry per discrete project or assignment, regardless
  of employer. Fields to populate: `project_name`, `date_from`, `date_to`,
  `location`, `client`, `company`, `main_project_features`,
  `activities_performed`, `positions_held`. Leave `donor` as "" unless
  explicitly stated in the CV.
- `year` on each RelevantProject: derive as "YYYY" or "YYYY–YYYY" from
  `date_from` and `date_to`. WB renderers use `year` rather than the
  separate date fields.
- It is normal for a single employer period to contain multiple projects —
  extract all of them into `relevant_projects`.

### Project description field split (all formats)

For every RelevantProject entry extracted from a dedicated project table or
project section, split the source description content between the two
description fields as follows:

- `main_project_features` → the PROJECT context: what the assignment is,
  its objective, scope, sector, geographic coverage, and the client/donor
  programme it sits within. This is background that describes the project
  itself, not the candidate's role. Typically found at the start of a
  description block, or in a dedicated "Project Background" / "Objective"
  sub-field.

- `activities_performed` → the CANDIDATE's actions: what this specific
  expert did, their responsibilities, deliverables, and tasks. These are
  action-led statements ("Develop...", "Assess...", "Provide...",
  "Draft...") that describe the candidate's contribution, not the project
  in general.

**When the source description is a combined block with no structural
separation** (i.e. a single prose or bullet-list paragraph mixing project
context and candidate tasks):
- Assign context-setting sentences (project purpose, programme name,
  geographic scope, client objectives) to `main_project_features`.
- Assign action-led sentences and task lists to `activities_performed`.
- If the entire description is task-only (all sentences are action-led
  with no project context), leave `main_project_features` as "" and put
  everything in `activities_performed`.
- If the entire description is context-only (no candidate actions
  mentioned), put everything in `main_project_features` and leave
  `activities_performed` as "".
- Never duplicate content across both fields.

**This rule applies only to proper project entries** (from a
`relevant_projects` table or project section). For the employment-only
fallback, the mapping is fixed: `description → main_project_features`,
`activities_performed` left as "".

### Employment-only fallback (all formats)

If `relevant_projects` is empty after applying the format-specific rules above
AND `employment_record` has one or more entries, map each `employment_record`
entry to a `RelevantProject` using this mapping:

  employer          → project_name  (use employer name as the project name)
  employer          → company       (also populate company from employer)
  positions_held    → positions_held
  description       → main_project_features
  from_date/to_date → date_from/date_to
  location/country  → location
  Leave client, donor, activities_performed as "".

This rule applies to ALL formats — for GIZ runs it means `relevant_projects`
will NEVER be returned empty when the CV has any employment history.

Append ONE `extraction_warnings` entry:
  "No dedicated project section found — relevant_projects populated from
  employment_record entries for pipeline compatibility."

Edge cases:
- If `relevant_projects` is already non-empty (even 1 entry), do NOT apply
  this fallback — trust the existing routing.
- If an employment entry's description is fewer than 5 words, include it but
  append a per-entry `extraction_warnings` entry:
  "relevant_projects[N] (from employment record): main_project_features is
  very short — may be insufficiently detailed."

### Merged-cell and two-column project tables

Some CVs present project experience in a two-column table where:
- The **left column** contains the project title merged with date ranges in a
  single cell spanning multiple visual rows.
- The **right column** provides the project body (activities, client, etc.).

When you encounter this layout:
- Treat the first substantive non-date text in the left column as `project_name`.
- Treat date strings in the same left-column cell as `date_from` / `date_to`.
- Map right-column content to the appropriate project body fields.

If you genuinely cannot identify `project_name` from the left column
(e.g. the cell contains only dates, is blank, or the layout is ambiguous),
leave `project_name = ""` AND append an `extraction_warnings` entry:
  `"relevant_projects[N].project_name could not be determined from source
  table layout (merged-cell or missing title)."`

Do NOT fabricate a project name. An empty `project_name` with a warning is
the correct output for ambiguous layouts.

### Date normalisation
- For range dates (`date_from`, `date_to`, `date_obtained` on Education,
  CountryExperience, and RelevantProject): normalise to "Month YYYY" format —
  e.g. "March 2019", "January 2005".
- If only a year is given (e.g. "2019"), keep it as "2019" — do not invent a month.
- If a date range end uses "present", "current", "to date", or any equivalent,
  normalise it to "Present".
- For `date_of_birth` specifically: normalise to "Month D YYYY" format —
  e.g. "July 7 1961", "August 3 1985". The day must be kept; do not drop it.
  If the source gives DD.MM.YYYY (e.g. "7.07.1961"), convert to "July 7 1961".

### Date ordering validation

After extracting all date_from / date_to pairs, validate ordering across ALL
fields that use them:
- `relevant_projects[]` (date_from, date_to)
- `education[]` (date_from, date_to)
- `employment_record[]` (from_date, to_date)
- `countries_of_experience[]` (date_from, date_to)

**Ordering rule**: `date_from` must be chronologically earlier than or equal
to `date_to`. "Present" / "current" / "to date" always sorts LATER than any
literal date — a pair with `date_to = "Present"` is always correctly ordered.

**When an inversion is detected**:
1. Swap `date_from` and `date_to` in the output.
2. Append an `extraction_warnings` entry of the form:
   `"<field_path>[N] date_from/date_to inverted at source; swapped during
   extraction. Original: date_from='<X>', date_to='<Y>'."`
   For example:
   `"countries_of_experience[2] date_from/date_to inverted at source; swapped
   during extraction. Original: date_from='2020', date_to='2015'."`

This corrects transcription errors in the source document while making the
correction fully visible via extraction_warnings for human verification.

### Text normalisation
- Normalise all proper nouns (names, institutions, companies, countries) to
  Title Case.
- Strip all leading/trailing whitespace from every string value.
- Fix common-word typos only where the correction is completely unambiguous
  (e.g. "teh" → "the", "recieve" → "receive", "occured" → "occurred").
  NEVER apply typo correction to proper nouns, names, institutions, companies,
  countries, acronyms, or any word that might be domain-specific terminology.
  If you are uncertain whether a word is a typo or an intentional term, leave
  it exactly as found.
  Do not rephrase, reword, or improve content.

### Personal info
- `title`: accept only Mr. / Mrs. / Dr. / Prof.
  Normalise variants — e.g. "Professor" → "Prof.", "Doctor" → "Dr.".
  If absent or unclear, leave as "".
- `nationality_second`: populate only if the CV explicitly mentions dual
  nationality.
- `place_of_residence`: use "City, Country" format where both are available.

### Education
- List entries in reverse chronological order (most recent first).
- Use `date_obtained` only if the CV gives a single graduation or award year
  rather than a start–end range.
- Leave `major` as "" unless the CV lists it separately from the degree title.

#### Degree-only routing rule
``education[]`` is for degree-level qualifications ONLY. Route an entry to
``education[]`` only if it is one of the following:
- Bachelor's degree (BA, BSc, BEng, LLB, or equivalent)
- Master's degree (MA, MSc, MEng, MBA, LLM, or equivalent)
- Doctoral degree (PhD, DPhil, EdD, or equivalent)
- Juris Doctor (JD) or professional law degree / bar diploma
- Any equivalent formal multi-year degree (typically ≥ 3 years of full-time study)

The following must NOT go to ``education[]`` — route them elsewhere:
- Short courses (< 6 months): → ``training[]``
- Seminars and workshops: → ``training[]``
- International training programmes that do not award a formal degree: → ``training[]``
- Certificate programmes under 6 months duration: → ``training[]``
- Professional designations without a formal degree title (e.g. a CFA, PMP,
  or chartered designation not tied to a multi-year university programme):
  → ``certifications[]`` per the certifications dual-routing rule above

When in doubt (e.g. a "Professional Diploma" or executive programme with
ambiguous duration or awarding body), prefer ``certifications[]`` over
``education[]`` and append an ``extraction_warnings`` entry noting the
ambiguity.

### Language fields
- Populate only the raw fields: `reading_raw`, `speaking_raw`, `writing_raw`.
- Copy the proficiency level exactly as written in the CV, after whitespace
  normalisation.
- Leave `reading`, `speaking`, `writing`, `reading_cefr`, `speaking_cefr`,
  `writing_cefr` as "" — CEFR mapping is handled by the renderer, not here.

### Numeric language scale direction
Inspect the CV's language table header or introductory text for an explicit
scale direction indicator. Set ``language_scale_direction`` accordingly:

- ``"1_best"`` — when the header states 1 = highest proficiency.
  Examples: "1 – excellent; 5 – basic", "1 = fluent, 5 = basic",
  "1 (best) to 5 (worst)".
- ``"1_worst"`` — when the header states 1 = lowest proficiency.
  Examples: "1 = basic, 5 = excellent", "1 – beginner; 5 – native",
  "1 (poor) to 5 (excellent)".
- ``null`` — when no scale indicator is found, the scale is descriptive
  (Good/Fair/Poor), or the direction is ambiguous.

When you set ``language_scale_direction`` to any non-null value, also append
an entry to ``extraction_warnings`` noting that the numeric scale was detected
and that CEFR mapping requires human verification if the direction inference
may be uncertain.

### key_qualifications
- Extract the key qualifications or profile summary exactly as written in the CV
  if such a section exists. One string per bullet or sentence.
- This is source material only — it is NOT tailored to any specific assignment.
- Leave as [] if no such section exists in the CV.

### Other skills / Certifications / Training routing

Route content to fields based on the SOURCE DOCUMENT'S OWN LABEL, not the
content type:

- Section labelled "Other skills" (or "Other relevant skills", "Additional
  skills", or close variants) → ``other_skills``. This applies even when the
  content is certification- or training-style.
- Section labelled "Certifications" (or "Professional certifications",
  "Certificates") → ``certifications``.
- Section labelled "Training" (or "Long-term training", "Professional
  development", "Training and education") → ``training``.
- Section labelled "Membership in professional bodies" (or "Professional
  memberships", "Memberships") → ``membership_professional_bodies`` (free text;
  join multiple entries with "; " if needed).

#### Certifications dual-routing rule
Formal professional credentials and chartered/registered engineering designations
(e.g. Eur Ing, C Eng, PE, CEng, PEng, Pr Eng, or national equivalents) must be
written to BOTH fields:
  1. `certifications[]` — as a structured entry (the credential as the entry text).
  2. `membership_professional_bodies` — retained in the free-text string.
These fields serve different downstream purposes: `certifications[]` feeds
Agent 4 KQ generation; `membership_professional_bodies` feeds the renderer directly.
This rule applies regardless of which section label the source CV uses.

If a single section contains a mix with no explicit label, prefer
``other_skills`` for courses, workshops, and non-formal credentials;
prefer ``certifications`` for named certifications with awarding bodies.

If the source document has BOTH an "Other skills" section AND a
"Certifications" section, populate BOTH fields independently — do not merge
the contents into one field.

### References
- CITATION ROUTING: A section labelled "References", "Reference List", or
  similar that contains CITATIONS (entries with author, title, journal/
  conference, and year) must be routed to `publications[]`, NOT to
  `references[]`. The `references[]` field (schema: name, title, organisation,
  email, phone) is reserved exclusively for named CONTACT references.
- If the CV contains a "References" or "Contacts" section with named individuals
  and contact details, extract each contact into a Reference entry.
- Map fields as found in the source: `name`, `title`, `organisation`, `email`,
  `phone`. Leave any sub-field as "" if not present in the CV.
- If no References section exists, leave `references` as [].
- Do NOT fabricate contact details — extract only what is explicitly stated.

### Certification / Declaration
- If the CV contains a certification, undertaking, or declaration block
  (commonly worded "I, the undersigned, certify that to the best of my
  knowledge and belief, this bio-data correctly describes myself, my
  qualifications, and my experience..."), extract the full text verbatim into
  `certification_declaration`. Preserve the wording exactly, including any
  signature-date line structure, but strip leading/trailing whitespace.
- If no such block exists, leave `certification_declaration` as "".

### Fields to leave empty — always
- `proposed_position`, `category`, `employer`, `years_with_firm`: always "".
  These are injected by the pipeline from human-supplied params, never extracted.
- `generated_fields`: always [].
  Populated later by the Fields Generator agent.
- `world_bank_affiliation`: leave as "" unless explicitly present in the CV.
"""


def _build_prompt(system: str) -> str:
    schema_json = json.dumps(CVData.model_json_schema(), indent=2)
    return system.replace("{{ CVData.model_json_schema() }}", schema_json)


# ---------------------------------------------------------------------------
# Fix 3: CEFR centralisation — populate structured fields at write time
# ---------------------------------------------------------------------------

def _apply_cefr_with_direction(raw: str, direction: str | None) -> str:
    """
    Map a raw proficiency string to a CEFR label, respecting the numeric scale
    direction recorded on the CV.

    For non-numeric inputs (freetext, parenthetical, CEFR codes) the direction
    is irrelevant and ``map_cefr`` handles them normally.

    For numeric inputs:
    - ``direction == "1_worst"`` → use the inverted mapping
      (1=basic: 1→A1, 2→A2, 3→B1, 4→B2, 5→C1).
    - ``direction == "1_best"`` or ``None`` → use the default mapping
      (1=excellent: 1→C2, 2→C1, 3→B2, 4→B1, 5→A2).
    """
    if direction != "1_worst":
        return map_cefr(raw)

    # "1_worst" path: attempt digit-based inversion via map_numeric_scale_inverted
    # For non-numeric inputs, fall back to the standard map_cefr.
    token = raw.strip()

    # Bare integer
    if token.isdigit():
        result = map_numeric_scale_inverted(token)
        if result is not None:
            return result
        return "?"   # out-of-range integer

    # Slash-separated all-integer (e.g. "3/4/4")
    parts = [t.strip() for t in token.split("/")]
    if all(p.isdigit() for p in parts):
        mapped = [map_numeric_scale_inverted(p) for p in parts]
        if any(m is None for m in mapped):
            return "?"
        return "/".join(m for m in mapped)  # type: ignore[arg-type]

    # Not a numeric input → delegate to standard map_cefr
    return map_cefr(raw)


def _populate_cefr_fields(parsed: CVData) -> None:
    """
    Map *_raw → *_cefr in place for every LanguageEntry whose structured
    cefr field is empty.

    Respects ``parsed.language_scale_direction``:
    - ``None`` or ``"1_best"`` → default mapping (1=excellent → C2).
    - ``"1_worst"`` → inverted mapping (1=basic → A1).

    Agent 1's prompt deliberately leaves *_cefr empty; Python maps them here so
    every downstream consumer reads a consistent, pre-resolved value.

    Idempotent: never overwrites an already-populated cefr value.
    """
    direction = parsed.language_scale_direction  # None | "1_best" | "1_worst"

    for lang in parsed.languages:
        for raw_attr, cefr_attr in (
            ("reading_raw",  "reading_cefr"),
            ("speaking_raw", "speaking_cefr"),
            ("writing_raw",  "writing_cefr"),
        ):
            current = (getattr(lang, cefr_attr, "") or "").strip()
            if current:
                continue  # already set — respect the existing value
            raw_val = (getattr(lang, raw_attr, "") or "").strip()
            if raw_val:
                setattr(lang, cefr_attr, _apply_cefr_with_direction(raw_val, direction))


def _derive_year(date_from: str, date_to: str) -> str:
    """
    Derive the WB-style `year` string ("YYYY" or "YYYY–YYYY") from date strings.
    Handles "Month YYYY", "YYYY", "Present", or empty values gracefully.
    """
    def _extract_year(s: str) -> str:
        if not s:
            return ""
        s = s.strip()
        if s.lower() == "present":
            return "Present"
        # Last 4-digit token in the string
        import re
        m = re.search(r"\b(\d{4})\b", s)
        return m.group(1) if m else ""

    y_from = _extract_year(date_from)
    y_to = _extract_year(date_to)

    if y_from and y_to and y_from != y_to:
        return f"{y_from}–{y_to}"
    return y_from or y_to


def _apply_employment_fallback(parsed: CVData) -> None:
    """
    Python-side safety net: if the LLM left relevant_projects empty but
    employment_record has entries, map each employment entry to a
    RelevantProject.  Mirrors the prompt's employment-only fallback so the
    rest of the pipeline always has project data to work with.

    Also derives the WB `year` field from date strings so WB renderers
    can use it without further calculation.

    Idempotent: does nothing when relevant_projects is already non-empty.
    """
    if parsed.relevant_projects or not parsed.employment_record:
        return  # LLM handled it, or nothing to map

    fallback_warning = (
        "Python fallback: relevant_projects populated from employment_record "
        "(LLM did not produce project entries). Review project detail quality."
    )

    for i, emp in enumerate(parsed.employment_record):
        description = emp.description or ""
        project = RelevantProject(
            project_name=emp.employer or "",
            company=emp.employer or "",
            positions_held=emp.positions_held or "",
            main_project_features=description,
            activities_performed="",
            date_from=emp.from_date or "",
            date_to=emp.to_date or "",
            location=(emp.location or emp.country or ""),
            client="",
            donor="",
            year=_derive_year(emp.from_date or "", emp.to_date or ""),
        )
        parsed.relevant_projects.append(project)

        if len(description.split()) < 5:
            parsed.extraction_warnings.append(
                f"relevant_projects[{i}] (from employment record): "
                f"main_project_features is very short — may be insufficiently detailed."
            )

    # Deduplicate: drop the LLM's warning if already present, then add the Python one
    parsed.extraction_warnings = [
        w for w in parsed.extraction_warnings
        if "relevant_projects populated from employment" not in w
    ]
    parsed.extraction_warnings.append(fallback_warning)


def run(run_dir: Path, cv_text: str, params: dict) -> CVData:
    """
    Extract CV text into a CVData object, inject pipeline params, and write
    runs/{session_id}/cv_data.json.

    Args:
        run_dir: Path to the session run directory.
        cv_text: Tagged plain text from pipeline/extractor.
        params:  Pipeline params dict (proposed_position, category, employer,
                 years_with_firm, donor, page_limit, ...).

    Returns:
        Validated CVData instance.
    """
    update_step(run_dir, "cv_extractor", "running")

    with client.messages.stream(
        model=ANTHROPIC_MODEL_EXTRACTOR,
        max_tokens=ANTHROPIC_MAX_TOKENS,
        system=_build_prompt(SYSTEM_PROMPT_A1),
        messages=[
            {
                "role": "user",
                "content": (
                    "Extract the CV below into a CVData JSON object.\n\n"
                    f"<donor>{params.get('donor', '')}</donor>\n\n"
                    f"<cv>\n{cv_text}\n</cv>"
                ),
            }
        ],
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "max_tokens":
        update_step(run_dir, "cv_extractor", "failed")
        raise ValueError(
            "CV Extractor response was truncated (max_tokens reached). "
            "Increase max_tokens or reduce CV length."
        )

    raw = strip_code_fences(response.content[0].text.strip())
    raw = extract_json_object(raw)

    try:
        parsed = CVData.model_validate_json(raw)
    except Exception as exc:
        update_step(run_dir, "cv_extractor", "failed")
        raise ValueError(
            f"CV Extractor returned invalid JSON: {exc}\n\nRaw output:\n{raw}"
        ) from exc

    # Inject upfront params — agent correctly leaves these empty during extraction
    parsed.proposed_position = params.get("proposed_position", "")
    parsed.category = params.get("category", "")
    parsed.employer = params.get("employer", "")
    parsed.years_with_firm = params.get("years_with_firm", "")

    # Populate structured CEFR fields from *_raw values (Fix 3).
    # Agent 1 deliberately leaves *_cefr empty; Python maps them here so
    # every downstream consumer reads a consistent, pre-resolved value.
    _populate_cefr_fields(parsed)

    # Python-side safety net: if the LLM left relevant_projects empty despite
    # employment_record being populated, map employment entries to projects so
    # downstream agents always have project data.  Runs after CEFR so the
    # final parsed object is fully normalised before the fallback fires.
    _apply_employment_fallback(parsed)

    output = {
        "approved": False,
        "approved_at": None,
        "data": parsed.model_dump(),
    }
    (run_dir / "cv_data.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    update_step(run_dir, "cv_extractor", "done")
    return parsed
