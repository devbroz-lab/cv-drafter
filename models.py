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

# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class PersonalInfo(BaseModel):
    """
    GIZ fields:  title, first_names, family_name, date_of_birth,
                 nationality (supports dual), place_of_residence
    WB fields:   full_name, date_of_birth, nationality
    """

    title: str = Field(default="", description="Salutation: Mr. / Mrs. / Dr. / Prof.")
    first_names: str = Field(default="", description="All given/first names")
    family_name: str = Field(default="", description="Surname / family name")
    full_name: str = Field(
        default="", description="Full name as a single string — derived or extracted"
    )  # noqa: E501
    date_of_birth: str = Field(
        default="", description="Date of birth as found in CV (e.g. 03.08.1985 or 07 July 1961)"
    )  # noqa: E501
    nationality: str = Field(default="", description="Primary nationality")
    nationality_second: str = Field(
        default="", description="Second nationality if dual citizen (GIZ asks for this)"
    )  # noqa: E501
    place_of_residence: str = Field(
        default="", description="City and country of current residence (GIZ field)"
    )  # noqa: E501
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
    date_obtained: str = Field(
        default="", description="Year degree was obtained (used in WB format)"
    )  # noqa: E501
    degree: str = Field(default="", description="Full degree, diploma, or certificate description")
    major: str = Field(
        default="", description="Major subjects or specialization if listed separately"
    )  # noqa: E501


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
    speaking_cefr: str = Field(
        default="", description="Speaking — mapped to CEFR (A1–C2 or Native)"
    )  # noqa: E501
    writing_cefr: str = Field(default="", description="Writing — mapped to CEFR (A1–C2 or Native)")


class CountryExperience(BaseModel):
    """
    GIZ format:  COUNTRY | DATE FROM – DATE TO
    WB format:   Countries of Work Experience (comma-separated string, no dates)
    """

    country: str = Field(default="", description="Country name")
    date_from: str = Field(
        default="", description="Start of experience in this country (month/year)"
    )  # noqa: E501
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
    description: str = Field(
        default="", description="Brief description of role (GIZ professional experience column)"
    )  # noqa: E501


class RelevantProject(BaseModel):
    """
    GIZ format:  DATE FROM-DATE TO | LOCATION | COMPANY | POSITION | DESCRIPTION
    WB format:   Name | Year | Location | Client | Description | Position | Activities

    This is the most complex section — both formats require it but structure differently.
    The renderer handles formatting; schema stores everything.
    """

    project_name: str = Field(default="", description="Name of assignment or project")
    date_from: str = Field(default="", description="Start date of assignment")
    date_to: str = Field(default="", description="End date of assignment")
    year: str = Field(default="", description="Year(s) — e.g. '2019-2021' (WB uses this)")
    duration: str = Field(default="", description="Duration of assignment — e.g. '8 months'")
    location: str = Field(default="", description="Country or city where work was performed")
    client: str = Field(default="", description="Client organization")
    company: str = Field(default="", description="Consulting firm / employer on this project")
    contact: str = Field(default="", description="Contact person at the client organization")
    donor: str = Field(default="", description="Funding donor — e.g. USAID, World Bank, GIZ, EBRD")
    main_project_features: str = Field(default="", description="Brief description of the project")
    positions_held: str = Field(default="", description="Position held on this project")
    activities_performed: str = Field(
        default="", description="Detailed activities and responsibilities"
    )  # noqa: E501


class DetailedTask(BaseModel):
    """
    Appears in WB format as 'Detailed Tasks Assigned' column.
    Not extracted from the CV — generated by Agent 3 (Tasks Writer)
    using the ToR/JD and the expert's relevant past experience.
    """

    task: str = Field(default="", description="A single detailed task statement")
    source: str = Field(
        default="", description="Where this task came from: 'tor' | 'experience' | 'generated'"
    )


# ---------------------------------------------------------------------------
# Root model
# ---------------------------------------------------------------------------


class CVData(BaseModel):
    """
    Unified CV data container — superset of all donor format fields.

    GIZ-specific fields:  title, first_names, family_name, place_of_residence,
                          category, years_with_firm, key_qualifications,
                          other_relevant_info, membership_professional_bodies
    WB-specific fields:   world_bank_affiliation, detailed_tasks
    Shared fields:        everything else

    To add a new donor format:
      1. Check if required fields already exist here
      2. Add missing fields with a comment marking which format introduced them
      3. Write a new renderer in templates/ — never touch this schema's existing fields
    """

    # --- Identity ---
    personal_info: PersonalInfo = Field(default_factory=PersonalInfo)
    proposed_position: str = Field(
        default="", description="Role the expert is proposed for on this specific project"
    )
    category: str = Field(
        default="", description="Expert category in the project (GIZ field — e.g. 'STE pool 2')"
    )
    employer: str = Field(default="", description="Name of the firm submitting this CV")
    years_with_firm: str = Field(
        default="", description="Years the expert has been with the submitting firm (GIZ field)"
    )
    present_position: str = Field(
        default="", description="Current job title (GIZ field — e.g. 'Independent Consultant')"
    )

    # --- Qualifications ---
    education: list[Education] = Field(
        default_factory=list,
        description="Educational qualifications in reverse chronological order",
    )
    key_qualifications: list[str] = Field(
        default_factory=list,
        description="Bullet-point summary of key qualifications relevant to assignment (GIZ field)",
    )
    certifications: list[str] = Field(
        default_factory=list,
        description="Professional certifications or memberships in professional associations",
    )
    membership_professional_bodies: str = Field(
        default="", description="Membership in professional bodies — free text (GIZ field)"
    )
    other_skills: list[str] = Field(
        default_factory=list,
        description="Other relevant skills, short-term trainings, workshops (GIZ field)",
    )
    training: list[str] = Field(
        default_factory=list, description="Longer training courses and programs (WB field)"
    )
    publications: list[str] = Field(
        default_factory=list,
        description="Publications, presentations, studies — one string per item",
    )
    other_relevant_info: str = Field(
        default="", description="Catch-all for other relevant information (GIZ field)"
    )

    # --- Geography & Languages ---
    countries_of_experience: list[CountryExperience] = Field(
        default_factory=list, description="Countries where expert has worked, with date ranges"
    )
    languages: list[LanguageProficiency] = Field(
        default_factory=list,
        description="Languages with proficiency levels (raw + normalized + CEFR)",
    )

    # --- Experience ---
    employment_record: list[EmploymentRecord] = Field(
        default_factory=list, description="Full employment history in reverse chronological order"
    )
    relevant_projects: list[RelevantProject] = Field(
        default_factory=list,
        description="Past projects that illustrate capability for the assigned role",
    )

    # --- Assignment-specific (generated, not extracted) ---
    detailed_tasks: list[DetailedTask] = Field(
        default_factory=list,
        description=(
            "Tasks assigned for this specific project — NOT extracted from CV. "
            "Generated by Agent 3 (Tasks Writer) from ToR + expert background. "
            "WB format places this in the left column of the Relevant Experience table."
        ),
    )

    # --- WB-specific ---
    world_bank_affiliation: str = Field(
        default="",
        description="Details of any current or past World Bank Group employment or appointments",
    )

    # --- Agent-generated fields (populated by Fields Generator agent) ---
    generated_fields: list[GeneratedField] = Field(
        default_factory=list,
        description=(
            "Format-specific content generated by the Fields Generator agent. "
            "Each entry has a field_key (e.g. 'key_qualifications'), content string, "
            "and source tag ('tor' | 'experience' | 'generated'). "
            "Renderers prefer generated_fields over extracted equivalents."
        ),
    )


# ---------------------------------------------------------------------------
# CEFR mapping utility — used by renderers, not agents
# ---------------------------------------------------------------------------


def map_to_cefr(level: str) -> str:
    """
    Convert free-text proficiency level to CEFR scale.
    GIZ requires CEFR (A1–C2). WB accepts free text.
    Call this in the GIZ renderer context builder, not in the agents.
    """
    mapping = {
        "mother tongue": "Native",
        "native": "Native",
        "fluent": "C2",
        "excellent": "C2",
        "very good": "C1/C2",
        "good": "C1",
        "fair": "B1/B2",
        "intermediate": "B1/B2",
        "working": "B1",
        "basic": "A2",
        "beginner": "A1",
        "poor": "A1/A2",
        # Pass-through for already-mapped CEFR values
        "a1": "A1",
        "a2": "A2",
        "b1": "B1",
        "b2": "B2",
        "c1": "C1",
        "c2": "C2",
        "c1/c2": "C1/C2",
        "b1/b2": "B1/B2",
        "a1/a2": "A1/A2",
    }
    return mapping.get(level.lower().strip(), level)


# ---------------------------------------------------------------------------
# Agent-pipeline types — added alongside the locked contract (additive only)
# ---------------------------------------------------------------------------


class GeneratedField(BaseModel):
    """
    A single piece of format-specific content produced by the Fields Generator agent.
    Multiple GeneratedField items are stored in CVData.generated_fields.

    field_key  — identifies the logical field (e.g. 'key_qualifications')
    content    — the generated text (one bullet, one sentence, etc.)
    source     — provenance tag:
                   'tor'        bullet addresses a ToR requirement with no direct CV evidence
                   'experience' bullet is grounded in one or more CV projects/qualifications
                   'generated'  bullet synthesises both ToR requirement and CV evidence
    """

    field_key: str = Field(default="")
    content: str = Field(default="")
    source: str = Field(default="")


class DistilledToR(BaseModel):
    """
    Structured summary of a Terms of Reference document produced by Agent 2
    (ToR Summarizer).  Consumed by Agents 3, 4, 5, and 6.
    """

    position_title: str = Field(default="")
    sector: str = Field(default="")
    geography: str = Field(default="")
    donor: str = Field(default="")
    required_qualifications: list[str] = Field(default_factory=list)
    required_experience_years: str = Field(default="")
    key_tasks: list[str] = Field(default_factory=list)
    required_competencies: list[str] = Field(default_factory=list)
    preferred_competencies: list[str] = Field(default_factory=list)
    sector_keywords: list[str] = Field(default_factory=list)
    language_requirements: list[str] = Field(default_factory=list)
    country_experience_required: list[str] = Field(default_factory=list)
    page_limit_stated: int | None = Field(default=None)
    page_limit_source: str = Field(default="")


class FormatProfile(BaseModel):
    """
    Declares format-specific pipeline behaviour for a donor format.
    Used by the Fields Generator agent to know which fields to generate.
    """

    format_id: str
    generative_field_keys: list[str] = Field(default_factory=list)
    page_limit_default: int | None = Field(default=None)
    language_scale: str = Field(default="cefr")


FORMAT_PROFILES: dict[str, FormatProfile] = {
    "giz": FormatProfile(
        format_id="giz",
        generative_field_keys=["key_qualifications"],
        page_limit_default=4,
        language_scale="cefr",
    ),
    "world_bank": FormatProfile(
        format_id="world_bank",
        generative_field_keys=["detailed_tasks"],
        page_limit_default=4,
        language_scale="freetext",
    ),
}


# Resolve the forward reference used in CVData.generated_fields
CVData.model_rebuild()
