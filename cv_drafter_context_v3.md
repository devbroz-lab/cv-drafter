# CV Drafter Project — Master Context Document v3
> Complete context from the full design, architecture, and development planning session.
> Feed this entire file into a new chat to resume with zero context loss.
> This is the definitive version — supersedes v1 and v2 entirely.

---

## 1. The Business Problem

A consulting company in the renewable energy and international development sector submits CVs of deployed experts to donors when winning project bids. These CVs must strictly follow donor-mandated formats — GIZ, World Bank, ADB, EBRD, UNDP, EU, etc.

**Current pain:**
- 100s of CVs reformatted manually every month
- ~200 Euro per CV paid to employees
- Monthly overhead upwards of 50,000 Euro
- Tedious, error-prone, slow

**What's being built:**
A standalone SaaS. User uploads a raw CV (PDF or DOCX), selects target format (GIZ or World Bank), optionally provides a Terms of Reference document and recruiter comments, and gets back a properly formatted Word document ready to submit.

**Why it's hard:**
Donor templates are strict Word documents with specific table structures, field names, date formats, page limits, and section ordering. One structural deviation can get a submission rejected.

**Business context:**
- Business lead: Alias
- Partner organization: DevBroz
- Immediate pitch target: GFA
- BD strategy covers development sector orgs, Germany/EU IT stakeholders, facilitator organizations
- Related product: Intugle (data analytics platform — separate)
- GTC trifold brochure in progress covering Data Engineering, Analytics, AI/ML, Automation, Custom Software

---

## 2. Prototype (Reference Only — Do Not Use as Starting Point)

Prototype repo: https://github.com/qamarali01/cv-drafter-prototype

**The production build starts from scratch.** Only `models.py` is carried forward (updated version in Section 6).

**Prototype tech stack:**
- Python backend (FastAPI)
- React + Vite frontend
- OpenAI GPT-4o
- `python-docx` for reading and writing
- Sessions stored locally under `runs/<session_id>/`

**Why prototype is not production-ready** (full list):
- No PDF input support — crashes silently
- No async — server blocks 15–40s per request
- Local file storage only — lost on cloud redeploy
- No auth or multi-tenancy
- GIZ projects section wrong format — text blob instead of structured table
- Language levels wrong format — writes "Good" instead of CEFR "C1/C2"
- Detailed Tasks always blank — Agent 3 never existed
- `cell.text =` assignment destroys Word template formatting
- Hardcoded paragraph indices (`paragraphs[8]`, `paragraphs[11]`) — breaks on template changes
- Country experience dates always blank
- Employment country column always blank in WB
- No retry/error handling on LLM calls
- No logging or observability
- Name splitting naive — breaks on multi-word last names

---

## 3. Tech Stack — All Decisions Locked

| Concern | Decision | Reason |
|---|---|---|
| Language | Python 3.12.10 | Last full bugfix release with binary installers. 3.12.13 exists but is source-only — no binary installer |
| Framework | FastAPI | Existing choice |
| Auth | Supabase Auth | Third-party, handles JWT and user management |
| Database | Supabase Postgres | Sessions table, user records |
| File storage | Supabase Storage | Replaces local `runs/` — simplest option, one account covers auth + db + storage |
| Async | FastAPI BackgroundTasks | Not Celery — add Celery only when scale demands it |
| AI model | OpenAI GPT-4o | Structured outputs via `response_format=CVData` |
| Template rendering | `docxtpl` | Not raw python-docx, not raw Jinja2 — handles Word XML fragmentation |
| Agent orchestration | Plain Python async — NO LangGraph | Pipeline is purely sequential |
| Dependency management | `pip-tools` — two-file approach | Never use `>=` in requirements.txt |

**On BackgroundTasks vs Celery:**
BackgroundTasks = waiter takes order and comes back when ready. Celery = dedicated ticket system with multiple cooks. BackgroundTasks is correct for zero users — switch to Celery when real scale demands it.

**On Supabase Storage vs Cloudflare R2:**
R2 has no egress fees and S3-compatible API. Supabase Storage is simpler — one account for everything. Decision: start with Supabase Storage, migrate to R2 if CDN or volume demands it.

**On LangGraph:**
Not used. Pipeline always runs same steps in same order. No step decides its own next step. Human is always in the loop. LangGraph only needed for autonomous self-correction loops — a future product decision, not a current requirement.

**Python version enforcement:**
```
.python-version file at repo root: 3.12.10
```
Runtime check in `api/config.py`:
```python
import sys
if sys.version_info < (3, 12) or sys.version_info >= (3, 13):
    raise RuntimeError(f"Python 3.12.x required. You are running {sys.version}.")
```
All devs: `pyenv install 3.12.10 && pyenv local 3.12.10`

**Dependency management:**
```bash
pip install pip-tools
pip-compile requirements.in   # generates pinned requirements.txt
pip-sync requirements.txt     # installs + removes stale packages
```
Both `requirements.in` and `requirements.txt` are committed to git.
Never use `pip install -r` — always use `pip-sync`.

---

## 4. Directory Structure

Root directory is `backend/`.

```
backend/
│
├── .env                          # real secrets — never commit
├── .env.example                  # empty template — commit this
├── .gitignore
├── .python-version               # contains: 3.12.10
├── requirements.in               # human-maintained loose constraints
├── requirements.txt              # machine-generated exact pins via pip-compile
├── models.py                     # shared CVData schema — owned by nobody, locked
│
├── api/
│   ├── __init__.py
│   ├── server.py                 # FastAPI app, mounts routers, nothing else
│   ├── config.py                 # env vars via pydantic-settings + Python version check
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── sessions.py           # all /sessions endpoints
│   │   └── health.py             # GET /health — no auth required
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth.py               # get_current_user FastAPI dependency
│   │   ├── database.py           # all Supabase DB calls
│   │   └── storage.py            # all Supabase Storage calls
│   │
│   └── models/
│       ├── __init__.py
│       └── requests.py           # Pydantic models for API request/response shapes
│
├── pipeline/
│   ├── __init__.py
│   ├── runner.py                 # NOT orchestrator.py — plain sequential runner
│   ├── extractor/
│   │   ├── __init__.py           # exposes extract_text(path) — routes to docx or pdf
│   │   ├── docx_extractor.py     # Dev 1 owns
│   │   └── pdf_extractor.py      # Dev 1 owns
│   └── agents/                   # Dev 2's territory — Dev 1 never touches
│       ├── __init__.py
│       ├── extractor_agent.py    # Agent 1
│       ├── mapper_agent.py       # Agent 2
│       ├── tasks_agent.py        # Agent 3 — WB only
│       ├── reviewer_agent.py     # Agent 4
│       └── condenser_agent.py    # Agent 5
│
├── templates/                    # Dev 3's territory — Dev 1 never touches
│   ├── __init__.py
│   ├── base.py                   # BaseTemplate ABC + registry
│   ├── giz.py                    # GIZ renderer using docxtpl
│   ├── world_bank.py             # WB renderer using docxtpl
│   ├── GIZ-Template.docx         # Word template with {{placeholders}}
│   └── WB-Template.docx          # Word template with {{placeholders}}
│
├── runs/                         # temp local dir — files land here briefly before Supabase upload
│   └── .gitkeep
│
└── tests/
    ├── __init__.py
    ├── test_sessions.py
    ├── test_extractor.py
    └── sample_files/
        ├── sample_giz.docx       # Merita Kostari GIZ CV
        └── sample_wb.docx        # Jamil Musleh WB CV
```

**Critical naming decision:** File is `runner.py` not `orchestrator.py`. "Orchestrator" implies LangGraph-style dynamic routing which is not what this is. It is a plain sequential runner.

**.gitignore must include:**
```
.env
__pycache__/
*.pyc
.venv/
venv/
runs/*
!runs/.gitkeep
```

---

## 5. The Full Agent Pipeline

5 AI agents + 1 deterministic renderer. Purely sequential — each step depends on previous step's output. No parallelism possible or needed.

```
Raw CV uploaded (.docx or .pdf)
          ↓
[Dev 1 — File Extractor]
  python-docx or pdfplumber reads file
  outputs tagged plain text: [HEADING] [BOLD] [TABLE] [NORMAL]
  NO AI — purely mechanical file reading
          ↓
Tagged plain text string
          ↓
[Agent 1 — Extractor Agent]              Dev 2
  Receives: raw_text + target_format
  GPT-4o maps text → CVData fields
  Format-aware: GIZ populates relevant_projects only
                WB populates both employment_record and relevant_projects
          ↓
CVData object
          ↓
[Agent 2 — Alignment Mapper]             Dev 2    ← receives ToR + JD
  Reorders and reweights CVData to match project role
  For GIZ: also tailors key_qualifications to ToR language
  Format-agnostic — does not need target_format
          ↓
[Agent 3 — Tasks Writer]                 Dev 2    ← WB ONLY
  Generates detailed_tasks from ToR + expert background
  HYBRID: takes past experience, reframes using ToR language
  DOES NOT RUN for GIZ — GIZ has no Detailed Tasks section
  Example:
    Raw: "Conducted energy audits for 15 factories in Kenya (2019)"
    Output: "Experienced in conducting industrial energy audits..."
          ↓
[Agent 4 — Reviewer / Reviser]           Dev 2    ← receives recruiter comments
  Applies recruiter comments
  Flags missing fields
  Refines tone and length
  Format-agnostic
          ↓
[Agent 5 — Condenser]                    Dev 2
  Trims content to fit page limit
  Does not need target_format — needs page_limit number only
  Only runs if page_limit is set
          ↓
[Renderer — deterministic, not an agent] Dev 3
  Takes final CVData
  Fills GIZ or WB Word template using docxtpl
  Outputs .docx
          ↓
Output: formatted CV ready to submit
```

**Which agents need `target_format` passed in:**

| Agent | Needs target_format? | Why |
|---|---|---|
| Extractor | YES | Determines which fields to populate |
| Alignment Mapper | No | Pure content reweighting |
| Tasks Writer | No — doesn't run for GIZ | Skipped entirely for GIZ |
| Reviewer | No | Pure content revision |
| Condenser | No — needs page_limit only | Already passed separately |
| Renderer | Yes — implicitly | It IS the format |

**runner.py correctly handles Tasks Writer:**
```python
# Tasks writer only runs for WB format
if target_format == "world_bank":
    cv_data = await write_tasks(cv_data, tor_text, job_description)
```

---

## 6. runner.py — What It Actually Is

NOT a LangGraph orchestrator. NOT an agent coordinator. A plain Python async function that sequences pipeline steps and gives Dev 1 a stable import interface.

**Why it exists:** Team boundary separation. Dev 1's `sessions.py` imports only from `runner.py`. Dev 2 restructures `pipeline/agents/` freely without breaking Dev 1.

**Locked function signatures — Dev 2 must match these exactly:**

```python
# pipeline/runner.py

from pathlib import Path
from pipeline.extractor import extract_text
from pipeline.agents.extractor_agent import run as extract_cv_data
from pipeline.agents.mapper_agent import run as map_to_assignment
from pipeline.agents.tasks_agent import run as write_tasks
from pipeline.agents.reviewer_agent import run as review
from pipeline.agents.condenser_agent import run as condense

async def run_pipeline(
    input_path: Path,
    target_format: str,
    page_limit: int | None,
    tor_text: str,
    job_description: str,
    recruiter_comments: str,
) -> Path:
    raw_text = extract_text(input_path)
    cv_data = await extract_cv_data(raw_text, target_format)
    cv_data = await map_to_assignment(cv_data, tor_text, job_description)
    if target_format == "world_bank":
        cv_data = await write_tasks(cv_data, tor_text, job_description)
    if recruiter_comments.strip():
        cv_data = await review(cv_data, recruiter_comments)
    if page_limit:
        cv_data = await condense(cv_data, page_limit)
    from templates.base import get_registry
    template = get_registry().get(target_format)
    output_path = input_path.parent / f"output_{target_format}.docx"
    template.generate(cv_data, output_path)
    return output_path


async def run_revision(
    session_id: str,
    new_comment: str,
    target_format: str,
    page_limit: int | None,
    tor_text: str,
    job_description: str,
) -> Path:
    # Dev 2 fills internals — signature is locked
    ...
```

**Dev 1's stub** (used while Dev 2 builds the real pipeline):
```python
async def run_pipeline(...) -> Path:
    await asyncio.sleep(3)
    output_path = input_path.parent / f"stub_output_{input_path.name}"
    output_path.write_bytes(input_path.read_bytes())
    return output_path
```

---

## 7. CVData Schema — Locked (models.py)

**The most important file in the project.** All three developers import from it. No one modifies without agreement from all three.

**Derived from two real CVs:**
- GIZ format: Merita Kostari (GFA template) — `GIZ_CV-Merita_Kostari-WB_Expert4-draft150723_.docx`
- World Bank format: Abdul Jamil Musleh — `CV-WB-Jamil_Musleh.docx`

**Design rules:**
- All strings default to `""` — never `None`
- All lists default to `[]` — never `None`
- Every agent returns a NEW CVData instance — never mutates in place
- Schema is a superset — each renderer picks what it needs
- Adding new donor format = extend schema, never replace it

**Critical distinction on employment_record vs relevant_projects:**

GIZ has ONE experience section called "Professional experience" with columns:
`DATE FROM–DATE TO | LOCATION | COMPANY | POSITION | DESCRIPTION`
Each row is a **project/assignment** — not a job. Maps to `relevant_projects`.
GIZ does NOT have a separate employment record table.

WB has TWO sections:
- Employment Record: `PERIOD | EMPLOYING ORGANIZATION AND TITLE | COUNTRY` → `employment_record`
- Relevant Experience: project blocks → `relevant_projects`

**How Field descriptions work:** The LLM sees `Field(description=...)` values — these are serialized to JSON Schema and sent to the model. Class-level docstrings (`"""..."""`) are invisible to the LLM — they are for human developers only.

**Why schema is format-agnostic (not format-conditional):**
- One CV extraction can produce both GIZ and WB outputs — extract once, render twice
- All agents between extraction and rendering are format-agnostic
- Adding new formats requires only a new renderer — not schema changes
- Format awareness belongs in the renderer and the extractor agent system prompt, not the data model

```python
"""
CVData schema — unified superset for GIZ, World Bank, and future donor formats.

Derived from:
  - GIZ format: GIZ_CV-Merita_Kostari (GFA template)
  - World Bank format: CV-WB-Jamil_Musleh

Design rules:
  - All strings default to "" — never None
  - All lists default to [] — never None
  - Every agent returns a NEW CVData instance — never mutates in place
  - This schema is a superset: each renderer picks what it needs
  - Adding a new donor format = extend this schema, never replace it
"""

from __future__ import annotations
from pydantic import BaseModel, Field


class PersonalInfo(BaseModel):
    """
    GIZ fields:  title, first_names, family_name, date_of_birth,
                 nationality (supports dual), place_of_residence
    WB fields:   full_name, date_of_birth, nationality
    """
    title: str = Field(default="", description="Salutation: Mr. / Mrs. / Dr. / Prof.")
    first_names: str = Field(default="", description="All given/first names")
    family_name: str = Field(default="", description="Surname / family name")
    full_name: str = Field(default="", description="Full name as a single string — derived or extracted")
    date_of_birth: str = Field(default="", description="Date of birth as found in CV (e.g. 03.08.1985 or 07 July 1961)")
    nationality: str = Field(default="", description="Primary nationality")
    nationality_second: str = Field(default="", description="Second nationality if dual citizen (GIZ asks for this)")
    place_of_residence: str = Field(default="", description="City and country of current residence (GIZ field)")
    email: str = Field(default="", description="Email address")
    phone: str = Field(default="", description="Phone number")


class Education(BaseModel):
    """
    GIZ format:  Institution [date from – date to] | Degree obtained
    WB format:   School/University | Degree/certificate | Date obtained
    """
    institution: str = Field(default="", description="Name of school, college, or university")
    date_from: str = Field(default="", description="Start year/date of study")
    date_to: str = Field(default="", description="End year/date of study")
    date_obtained: str = Field(default="", description="Year degree was obtained (used in WB format)")
    degree: str = Field(default="", description="Full degree, diploma, or certificate description")
    major: str = Field(default="", description="Major subjects or specialization if listed separately")


class LanguageProficiency(BaseModel):
    """
    GIZ format:  CEFR scale A1–C2, or 'mother tongue'
    WB format:   Free text (Mother Tongue / Excellent / Very Good / Good)

    Both raw (as extracted) and mapped (normalized) values are stored.
    Renderer picks which to use.
    """
    language: str = Field(default="", description="Language name")
    reading_raw: str = Field(default="", description="Reading proficiency exactly as found in CV")
    speaking_raw: str = Field(default="", description="Speaking proficiency exactly as found in CV")
    writing_raw: str = Field(default="", description="Writing proficiency exactly as found in CV")
    reading: str = Field(default="", description="Reading — normalized to Good/Fair/Poor")
    speaking: str = Field(default="", description="Speaking — normalized to Good/Fair/Poor")
    writing: str = Field(default="", description="Writing — normalized to Good/Fair/Poor")
    reading_cefr: str = Field(default="", description="Reading — mapped to CEFR (A1–C2 or Native)")
    speaking_cefr: str = Field(default="", description="Speaking — mapped to CEFR (A1–C2 or Native)")
    writing_cefr: str = Field(default="", description="Writing — mapped to CEFR (A1–C2 or Native)")


class CountryExperience(BaseModel):
    """
    GIZ format:  COUNTRY | DATE FROM – DATE TO
    WB format:   Countries of Work Experience (comma-separated, no dates)
    """
    country: str = Field(default="", description="Country name")
    date_from: str = Field(default="", description="Start of experience in this country (month/year)")
    date_to: str = Field(default="", description="End of experience — 'to Date' if current")


class EmploymentRecord(BaseModel):
    """
    WB format only: PERIOD | Employing organization and title/position | COUNTRY

    GIZ does NOT have a separate employment record table.
    GIZ's "Professional experience" table is project-by-project and maps
    to RelevantProject, not EmploymentRecord.
    """
    from_date: str = Field(default="", description="Start date of employment (month/year or year)")
    to_date: str = Field(default="", description="End date — 'To Date' or 'Present' if current")
    employer: str = Field(default="", description="Name of employing organization")
    location: str = Field(default="", description="City and/or country of employment (GIZ field)")
    country: str = Field(default="", description="Country of employment (WB field)")
    positions_held: str = Field(default="", description="Job title / position held")
    description: str = Field(default="", description="Brief description of role (GIZ professional experience column)")


class RelevantProject(BaseModel):
    """
    GIZ format:  DATE FROM–DATE TO | LOCATION | COMPANY | POSITION | DESCRIPTION (one row per project)
    WB format:   Name | Year | Location | Client | Project Description | Position | Activities (one block per project)
    """
    project_name: str = Field(default="", description="Name of assignment or project")
    date_from: str = Field(default="", description="Start date of assignment")
    date_to: str = Field(default="", description="End date of assignment")
    year: str = Field(default="", description="Year(s) — e.g. '2019-2021' (WB uses this)")
    duration: str = Field(default="", description="Duration of assignment — e.g. '8 months'")
    location: str = Field(default="", description="Country or city where work was performed")
    client: str = Field(default="", description="Client organization")
    company: str = Field(default="", description="Consulting firm / employer on this project")
    donor: str = Field(default="", description="Funding donor — e.g. USAID, World Bank, GIZ, EBRD")
    main_project_features: str = Field(default="", description="Brief description of the project")
    positions_held: str = Field(default="", description="Position held on this project")
    activities_performed: str = Field(default="", description="Detailed activities and responsibilities")


class DetailedTask(BaseModel):
    """
    WB format only — appears in the left column of the Relevant Experience table.
    Not extracted from the CV — generated by Agent 3 (Tasks Writer) from ToR + expert background.
    Agent 3 does NOT run for GIZ format.
    """
    task: str = Field(default="", description="A single detailed task statement")
    source: str = Field(
        default="",
        description="Where this task came from: 'tor' | 'experience' | 'generated'"
    )


class CVData(BaseModel):
    """
    Unified CV data container — superset of all donor format fields.

    GIZ-specific fields:  title, first_names, family_name, place_of_residence,
                          category, years_with_firm, key_qualifications,
                          other_relevant_info, membership_professional_bodies
    WB-specific fields:   world_bank_affiliation, detailed_tasks, employment_record
    Shared fields:        everything else

    To add a new donor format:
      1. Check if required fields already exist here
      2. Add missing fields with a comment marking which format introduced them
      3. Write a new renderer in templates/ — never touch existing fields
    """

    # --- Identity ---
    personal_info: PersonalInfo = Field(default_factory=PersonalInfo)
    proposed_position: str = Field(default="", description="Role proposed for on this specific project")
    category: str = Field(default="", description="Expert category in the project (GIZ — e.g. 'STE pool 2')")
    employer: str = Field(default="", description="Name of the firm submitting this CV")
    years_with_firm: str = Field(default="", description="Years with the submitting firm (GIZ field)")
    present_position: str = Field(default="", description="Current job title (GIZ field)")

    # --- Qualifications ---
    education: list[Education] = Field(default_factory=list, description="Educational qualifications in reverse chronological order")
    key_qualifications: list[str] = Field(default_factory=list, description="Bullet-point summary of key qualifications relevant to assignment (GIZ field)")
    certifications: list[str] = Field(default_factory=list, description="Professional certifications or memberships in professional associations")
    membership_professional_bodies: str = Field(default="", description="Membership in professional bodies — free text (GIZ field)")
    other_skills: list[str] = Field(default_factory=list, description="Other relevant skills, short-term trainings, workshops (GIZ field)")
    training: list[str] = Field(default_factory=list, description="Longer training courses and programs (WB field)")
    publications: list[str] = Field(default_factory=list, description="Publications, presentations, studies — one string per item")
    other_relevant_info: str = Field(default="", description="Catch-all for other relevant information (GIZ field)")

    # --- Geography & Languages ---
    countries_of_experience: list[CountryExperience] = Field(default_factory=list, description="Countries where expert has worked, with date ranges where available")
    languages: list[LanguageProficiency] = Field(default_factory=list, description="Languages with proficiency levels — raw, normalized, and CEFR all stored")

    # --- Experience ---
    employment_record: list[EmploymentRecord] = Field(
        default_factory=list,
        description=(
            "WB format only — simple job history table (employer, title, period, country). "
            "GIZ does not have this section — leave empty for GIZ CVs."
        )
    )
    relevant_projects: list[RelevantProject] = Field(
        default_factory=list,
        description=(
            "GIZ: fills the entire Professional Experience table — one entry per project. "
            "WB: fills the Relevant Experience project blocks — one entry per project."
        )
    )

    # --- Assignment-specific (generated, not extracted) ---
    detailed_tasks: list[DetailedTask] = Field(
        default_factory=list,
        description=(
            "WB format only — tasks for this specific project. NOT extracted from CV. "
            "Generated by Agent 3 (Tasks Writer) from ToR + expert background. "
            "Agent 3 does not run for GIZ — leave empty for GIZ."
        )
    )

    # --- WB-specific ---
    world_bank_affiliation: str = Field(
        default="",
        description="Details of any current or past World Bank Group employment or appointments (WB field)"
    )


def map_to_cefr(level: str) -> str:
    """
    Convert free-text proficiency to CEFR scale.
    GIZ requires CEFR (A1–C2). WB accepts free text.
    Call this in the GIZ renderer context builder, not in the agents.
    """
    mapping = {
        "mother tongue": "Native", "native": "Native",
        "fluent": "C2", "excellent": "C2",
        "very good": "C1/C2",
        "good": "C1",
        "fair": "B1/B2", "intermediate": "B1/B2",
        "working": "B1",
        "basic": "A2", "beginner": "A1",
        "poor": "A1/A2",
        "a1": "A1", "a2": "A2", "b1": "B1", "b2": "B2",
        "c1": "C1", "c2": "C2",
        "c1/c2": "C1/C2", "b1/b2": "B1/B2", "a1/a2": "A1/A2",
    }
    return mapping.get(level.lower().strip(), level)
```

---

## 8. GIZ vs WB Format Comparison

### GIZ Format (Merita Kostari CV — GFA template)

Sections in order:
1. Proposed role in the project
2. Category (e.g. STE pool 2)
3. Staff of (company name)
4. Title / First names / Family name / DOB / Nationality / Place of residence
5. Education: INSTITUTION [DATE FROM–DATE TO] | DEGREE(S) OBTAINED
6. Language skills: LANGUAGE | READING | SPEAKING | WRITING (CEFR A1–C2)
7. Membership of professional bodies
8. Other skills
9. Present position
10. Years within the firm
11. Key qualifications (bullet list tailored to assignment)
12. Specific experience in the region: COUNTRY | DATE FROM–DATE TO
13. Professional experience: DATE FROM–DATE TO | LOCATION | COMPANY | POSITION | DESCRIPTION
14. Other relevant information (publications etc.)

**Critical:** GIZ has NO separate employment record. The "Professional experience" table is project-by-project. Each row = one project/assignment = one `RelevantProject` entry.

### WB Format (Jamil Musleh CV)

Sections in order:
1. Name of Staff
2. Proposed Position
3. Employer
4. Date of Birth
5. Nationality
6. Education: School/University | Degree/Certificate | Date Obtained
7. Professional Certification or Membership in Professional Associations
8. Countries of Work Experience (comma-separated list, no dates)
9. Languages: LANGUAGE | SPEAKING | READING | WRITING (free text)
10. Employment Record: PERIOD | EMPLOYING ORGANIZATION AND TITLE | COUNTRY
11. Relevant Experience:
    - Left column: Detailed Tasks Assigned (forward-looking, generated from ToR)
    - Right column: Project blocks (Name | Year | Client | Position | Activities)

**Critical:** WB has TWO experience sections — Employment Record (job history) AND Relevant Experience (project detail).

### Key Differences

| Feature | GIZ | WB |
|---|---|---|
| Name format | Split: Title + First names + Family name | Single: Full name |
| Language scale | CEFR (A1–C2) | Free text |
| Employment record | Does not exist | Separate table |
| Project section | Professional experience table | Relevant Experience blocks |
| Detailed Tasks | Does not exist | Left column of experience table |
| Key qualifications | Dedicated section | Not present |
| Country experience | With date ranges | Comma list, no dates |
| Place of residence | Yes | No |
| Category | Yes (STE pool etc.) | No |
| Years with firm | Yes | No |

---

## 9. What "Detailed Tasks" Is (WB Only)

The Detailed Tasks section is forward-looking but grounded in past experience.

**NOT:** extracted from the CV
**NOT:** invented future tasks
**IS:** past experience reframed to match ToR language

Agent 3 (Tasks Writer) reads:
- Expert's relevant past experience (from CVData after mapping)
- ToR/JD language and specific requirements

Example transformation:
- Raw CV: *"Conducted energy audits for 15 factories in Kenya (2019–2021)"*
- Detailed Task: *"Experienced in conducting industrial energy audits, developing training materials for local engineers, and producing donor-ready technical reports"*

**For GIZ instead:** Key qualifications serve a similar purpose. Agent 2 (Alignment Mapper) tailors `key_qualifications` to reflect ToR language — no separate agent needed.

---

## 10. Why docxtpl (Not Raw python-docx)

**Raw Jinja2 on .docx files breaks silently** — Word's XML often splits `{{name}}` across multiple XML nodes so Jinja2 never sees it as one token.

**`python-docx-template` (docxtpl)** wraps Jinja2 and handles XML splitting. Industry standard.

**What the current prototype does wrong:**
- `cell.text = value` — clears all runs, fonts, colors, bold from template cell
- `paragraphs[8].text` — hardcoded positional index, breaks if template changes
- Projects dumped as raw text blob — GIZ requires structured table per project
- Language levels written as "Good" not "C1/C2"

**What docxtpl approach looks like:**

In the Word template:
```
{{proposed_position}}
{{personal_info.family_name}}, {{personal_info.first_names}}

{% for project in relevant_projects %}
{{project.date_from}}–{{project.date_to}} | {{project.location}} | {{project.company}} | {{project.positions_held}}
{{project.activities_performed}}
{% endfor %}
```

In Python:
```python
from docxtpl import DocxTemplate

def generate(self, cv_data: CVData, output_path) -> Path:
    tpl = DocxTemplate(str(TEMPLATE_PATH))
    context = {
        "proposed_position": cv_data.proposed_position,
        "personal_info": cv_data.personal_info,
        "education": cv_data.education,
        "languages": [
            {**lang.dict(),
             "speaking": map_to_cefr(lang.speaking),
             "reading": map_to_cefr(lang.reading),
             "writing": map_to_cefr(lang.writing)}
            for lang in cv_data.languages
        ],
        "relevant_projects": cv_data.relevant_projects,
        "detailed_tasks": cv_data.detailed_tasks,
    }
    tpl.render(context)
    tpl.save(str(output_path))
    return output_path
```

**Key benefit:** Template changes = update the .docx file only. Python code unchanged.

---

## 11. Extraction Step vs Extractor Agent

These are two completely separate steps with different concerns.

**Dev 1's job — file reading (mechanical):**
- Problem: .docx is ZIP of XML, PDF is binary
- Tool: `python-docx` or `pdfplumber`
- Output: tagged plain text string
- No AI, no content understanding
- Tagged output format:
  ```
  [HEADING] Education
  [BOLD] Kabul Polytechnic University
  [NORMAL] Degree in Electrical Engineering 2009
  [TABLE 1]
  English | Good | Good | Good
  [END TABLE]
  ```

**Dev 2's job — content understanding (AI):**
- Problem: unstructured text with no consistent format
- Tool: GPT-4o with `response_format=CVData`
- Output: populated CVData object
- Also receives `target_format` to know which fields to populate

**Why separated:**
- Different failure modes — file format bug (Dev 1) vs extraction quality bug (Dev 2)
- Each person debugs their own piece independently

**In `pipeline/extractor/__init__.py`:**
```python
def extract_text(file_path: str | Path) -> str:
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return extract_text_from_docx(path)
    elif suffix == ".pdf":
        return extract_text_from_pdf(path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")
```

---

## 12. Extractor Agent System Prompt Structure

The extractor agent is format-aware. Dev 2 must implement:

```python
async def run(raw_text: str, target_format: str) -> CVData:
    completion = client.beta.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": build_system_prompt(target_format)},
            {"role": "user", "content": raw_text},
        ],
        response_format=CVData,
    )
    return completion.choices[0].message.parsed


def build_system_prompt(target_format: str) -> str:
    base = """
You are an expert CV parser for international development sector CVs.
Extract all information from the CV text into the provided JSON schema.
Rules:
- Only extract information explicitly present in the source text
- Never invent or infer data not present in the CV
- If a field is not found, leave it as empty string or empty list
- Preserve exact dates, names, and numbers as they appear
- For employment in reverse chronological order (most recent first)
"""
    if target_format == "giz":
        return base + """
FORMAT-SPECIFIC RULES FOR GIZ:
- The "Professional experience" table contains project-by-project entries.
  Map EACH ROW to one entry in relevant_projects. Do NOT populate employment_record — leave it empty.
- Each project row columns: date from-to → date_from/date_to, location → location,
  company → company, position → positions_held, description → activities_performed.
- The project name is typically the bold heading inside the description column.
- Languages use CEFR scale (A1–C2) — store as-is in the _cefr fields and _raw fields.
- "Specific experience in the region" table maps to countries_of_experience with date_from and date_to.
- detailed_tasks must be left empty — it is not used in GIZ format.
"""
    elif target_format == "world_bank":
        return base + """
FORMAT-SPECIFIC RULES FOR WORLD BANK:
- "Employment Record" table maps to employment_record.
  Each row: period → from_date/to_date, organization+title → employer/positions_held, country → country.
- "Relevant Experience" right column maps to relevant_projects.
  Each project block: extract name, year, client, position held, activities performed.
- "Countries of Work Experience" is comma-separated — split into countries_of_experience.
  WB does not provide date ranges per country — leave date_from and date_to empty.
- Languages use free text (Mother Tongue / Excellent / Very Good / Good) — store in _raw fields.
- "Detailed Tasks Assigned" column is NOT extracted — it will be generated by a separate agent.
  Leave detailed_tasks empty.
"""
    return base
```

---

## 13. Three-Developer Work Split

**Only hard dependency:** Lock `models.py` before anyone writes code.

### Dev 1 — Ingestion & Infrastructure
Owns: `api/`, `pipeline/extractor/`, `pipeline/runner.py` stub

Tasks in order:
1. Project structure setup
2. Supabase project creation + sessions table + storage bucket
3. Auth middleware (`get_current_user` dependency)
4. Database service (create/get/update sessions)
5. Storage service (upload/download/signed URLs)
6. API endpoints (sessions router)
7. Pipeline stub in `runner.py`
8. File extractor module (docx + pdf)

### Dev 2 — AI Pipeline
Owns: `pipeline/agents/`, fills in `pipeline/runner.py` real implementation

Tasks:
- Extractor agent (format-aware, system prompt per format)
- Alignment mapper
- Tasks writer (WB only)
- Reviewer/reviser
- Condenser

### Dev 3 — Renderer
Owns: `templates/`

Tasks:
- Tag GIZ and WB Word templates with `{{placeholders}}`
- Rewrite `giz.py` using docxtpl
- Rewrite `world_bank.py` using docxtpl
- CEFR language mapping
- Project table loop (structured, not text blob)
- Output validation

---

## 14. API Contract (Share With All Three Devs)

```
POST   /sessions
       Accepts: multipart/form-data
         cv_file            file     required — .docx or .pdf only
         target_format      string   required — "giz" | "world_bank"
         page_limit         integer  optional
         tor_text           string   optional
         job_description    string   optional
         recruiter_comments string   optional
       Returns: { "id": "uuid", "status": "processing" }
       Errors: 400 wrong file type, 401 not authenticated

GET    /sessions/{id}/status
       Returns: {
         "id": "uuid",
         "status": "pending|processing|done|failed",
         "target_format": "giz",
         "round": 1,
         "download_url": "https://... (only when done)",
         "error_message": "... (only when failed)",
         "created_at": "2024-01-01T00:00:00Z"
       }
       Errors: 404, 401

POST   /sessions/{id}/comments
       Accepts: { "comment": "please emphasise solar experience" }
       Returns: { "id": "uuid", "status": "processing" }
       Errors: 400 if status != "done", 404, 401

GET    /health
       Returns: { "status": "ok" }
       No auth required
```

---

## 15. Supabase Sessions Table

```sql
create table sessions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references auth.users(id) on delete cascade,
    status text not null default 'pending',
    target_format text not null,
    page_limit integer,
    tor_text text default '',
    job_description text default '',
    recruiter_comments text default '',
    source_cv_filename text default '',
    source_cv_storage_path text default '',
    output_storage_path text default '',
    error_message text,
    round integer default 1,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

alter table sessions enable row level security;

create policy "Users see own sessions"
    on sessions for all
    using (auth.uid() = user_id);
```

Status values: `pending` → `processing` → `done` → `failed`

File storage path structure:
```
cv-files/
  {session_id}/
    input/original_cv.docx
    output/round_01_giz.docx
         /round_02_giz.docx
```

---

## 16. Dev 1 Build Phases — Detailed

### Phase 1 — Project structure (Day 1)
Create directory structure. Write config.py, server.py, health.py, .env files.
Done when: `uvicorn api.server:app --reload` starts, `/health` returns 200.

### Phase 2 — Supabase setup (Day 1–2)
Create project, run SQL above, create `cv-files` bucket (private).
Done when: Python script inserts and reads a session row.

### Phase 3 — Auth middleware (Day 2)
Write `api/services/auth.py` with `get_current_user`.
Done when: No token → 401. Valid Supabase JWT → passes through.

### Phase 4 — Database service (Day 2–3)
Write `api/services/database.py` with create/get/update/set_processing/set_done/set_failed/increment_round.

### Phase 5 — Storage service (Day 3)
Write `api/services/storage.py` with upload/download/signed URLs.
Done when: Upload .docx, get signed URL, paste in browser, download works.

### Phase 6 — API endpoints (Day 3–4)
Write `api/routers/sessions.py` with all endpoints plus background task functions.
Done when: Full stub flow works — upload → processing → done → download URL.

### Phase 7 — Pipeline stub (Day 4)
Write stub `pipeline/runner.py`. Copies input as output after 3s sleep.
Never change function signatures — they are the handshake with Dev 2.

### Phase 8 — File extractor module (Day 5)
Write `pipeline/extractor/docx_extractor.py` and `pipeline/extractor/pdf_extractor.py`.
Done when: `extract_text()` works on both sample CVs producing readable tagged text.

---

## 17. Revision Mechanisms

**Two types of revision, two different code paths:**

**Type 1 — AI revision (natural language):**
"Emphasise solar energy experience more" → Reviewer agent → new .docx
Existing `/sessions/{id}/comments` endpoint handles this.

**Type 2 — Direct field edit (surgical):**
"Change client name in project 2 to Ministry of Energy" → skip agents → update CVData → renderer only
New `PATCH /sessions/{id}/cv-data` endpoint (add later).

Neither requires LangGraph. Both are straight-line operations.

---

## 18. Future Format Expansion Policy

One schema, forever. Adding ADB, EU, UNDP:
1. Check if fields exist in CVData
2. Add missing fields — mark which format introduced them
3. Write new renderer — `templates/adb.py` etc.
4. Existing renderers unaffected — all fields default to empty

Separate schema only if a format is so structurally different it would break existing renderers — extremely unlikely for standard donor formats.

---

## 19. Sample CVs Available

Two real CVs are in `tests/sample_files/`:

**GIZ — Merita Kostari** (`GIZ_CV-Merita_Kostari-WB_Expert4-draft150723_.docx`)
- GFA template, legal/regulatory expert, energy sector
- Dual nationality: Montenegro + Kosovo
- Place of residence: Sintra, Portugal
- Languages in CEFR: Albanian (mother tongue), English C2, Balkan languages C2
- Professional experience: 15+ project entries from 2001 to present
- Donors seen: USAID, World Bank, EBRD, EU/European Commission, IFC

**WB — Abdul Jamil Musleh** (`CV-WB-Jamil_Musleh.docx`)
- Standard WB template, electrical engineer
- Nationality: Afghan
- Languages in free text: Pashto (Mother Tongue), Dari (Excellent), English (Very Good), German (Good)
- Employment Record: 7 entries from 2011–present
- Relevant Projects: 4 project blocks with full detail
- Employer: GreenTech Consulting GmbH (GTC)

---

## 20. Production Gap Priority Order

### 🔴 Must fix before any real customer
1. No PDF input — crashes silently
2. No async — server hangs 15–40s per request
3. Local storage only — lost on cloud redeploy
4. No auth / multi-tenancy
5. GIZ projects section wrong format — text blob
6. Language levels wrong — "Good" not "C1/C2"
7. Detailed Tasks always blank — Agent 3 missing
8. `cell.text =` destroys formatting

### 🟡 Fix before scaling
9. Hardcoded paragraph indices
10. Country experience dates blank
11. Employment country column blank (WB)
12. No retry/error handling on LLM calls
13. Page limit condenser unreliable

### 🟠 Production hygiene
14. OpenAI only — no model abstraction
15. No logging or observability
16. No error feedback to user on missing fields
17. Name splitting naive

---

## 21. What Still Needs to Be Done Before Full Team Velocity

1. **Tagged Word templates** — open GIZ-Template.docx and WB-Template.docx in Word, replace every fillable cell with `{{placeholder}}` tags matching CVData field names. 2–3 hours. Unblocks Dev 3 completely.

2. **Agent system prompts document** — full system prompts for all 5 agents. Dev 2's most important piece. Needs domain input since prompts must reflect how GIZ/WB CVs work in practice. Format for extractor agent is sketched in Section 12.

3. **API contract** — already defined in Section 14. Needs to be shared formally as a document with Dev 2 and Dev 3.

---

## 22. Suggested Build Order

1. ✅ Lock `models.py` — done
2. Dev 1 Phases 1–7 — foundation and stub pipeline
3. Dev 3 tags Word templates with placeholders
4. Dev 2 builds extractor agent
5. Dev 2 builds alignment mapper
6. Dev 2 builds tasks writer (WB only)
7. Dev 3 rewrites GIZ renderer with docxtpl
8. Integration — wire real pipeline into runner.py, end-to-end test GIZ
9. Dev 1 Phase 8 — file extractor module
10. Dev 2 builds reviewer and condenser
11. Dev 3 rewrites WB renderer
12. Integration — end-to-end test WB
13. Add PDF extraction (Dev 1)
14. Auth + cloud deployment hardening
15. Direct field edit endpoint PATCH /sessions/{id}/cv-data (add later)

---

*End of context document v3. Supersedes v1 and v2. All decisions, architectural choices, code, team boundaries, format analysis, and gap analysis from the full session are captured above.*