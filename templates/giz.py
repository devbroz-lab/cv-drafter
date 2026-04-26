"""
GIZ CV Renderer — Dev 3 territory.

Reads generated_fields.json from a completed pipeline run and fills the
GIZ-Template.docx using docxtpl (Jinja2-based Word templating).

This renderer is intentionally deterministic — no LLM calls, no decisions.
It only reads, transforms, and writes.

Usage (called by pipeline/orchestrator.py after checkpoint_3 approval):
    from templates.giz import run
    output_path = run(session_id)

Template placeholders handled:
    {{proposed_position}}
    {{category}}
    {{employer}}
    {{personal_info.title}} / {{personal_info.first_names}} / {{personal_info.family_name}}
    {{personal_info.date_of_birth}} / {{personal_info.place_of_residence}}
    {{nationality_display}}           -- derived (single or dual nationality)
    {%tr for edu in education %}      -- table row loop
    {%tr for lang in languages %}     -- table row loop (CEFR mapped here)
    {{membership_professional_bodies}}
    {{other_skills_display}}          -- derived (list joined to string)
    {{present_position}}
    {{years_with_firm}}
    {% for kq in key_qualifications %} -- bullet list loop
    {%tr for ce in countries_of_experience %}  -- table row loop
    {%tr for proj in relevant_projects %}      -- table row loop
    {{other_relevant_info}}
"""

from __future__ import annotations

import json
from pathlib import Path

try:
    from docxtpl import DocxTemplate
except ImportError as _err:
    raise ImportError(
        "docxtpl is required for the GIZ renderer. " "Run: pip install -e '.[dev]'"
    ) from _err

from pipeline.paths import (
    TEMPLATE_PATH,
    TEMPLATE_ROOT,
    ensure_under,
    get_giz_dynamic_template_path,
    get_giz_dynamic_unpack_dir,
    get_run_dir,
)
from templates.giz_dynamic_template import build_dynamic_template

# ---------------------------------------------------------------------------
# CEFR mapping — kept local so the renderer has zero dependency on the
# pipeline schema at render time (renderers should be self-contained).
# ---------------------------------------------------------------------------

_CEFR_MAP: dict[str, str] = {
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


def _map_cefr(level: str) -> str:
    return _CEFR_MAP.get(level.lower().strip(), level)


# ---------------------------------------------------------------------------
# Context builder — transforms CVData dict into template-ready context.
# All transformations happen here; the template stays dumb.
# ---------------------------------------------------------------------------


def _build_context(cv: dict) -> dict:
    pi = cv.get("personal_info", {})

    # Nationality display
    nat1 = pi.get("nationality", "").strip()
    nat2 = pi.get("nationality_second", "").strip()
    nationality_display = f"{nat1} / {nat2}" if (nat1 and nat2) else (nat1 or nat2)

    # Education rows
    education = []
    for edu in cv.get("education", []):
        date_from = edu.get("date_from", "").strip()
        date_to = edu.get("date_to", "").strip()
        if date_from and date_to:
            date_range = f"{date_from} \u2013 {date_to}"
        elif date_obtained := edu.get("date_obtained", "").strip():
            date_range = date_obtained
        else:
            date_range = date_from or date_to
        institution = edu.get("institution", "").strip()
        education.append(
            {
                "institution": (f"{institution} [{date_range}]" if date_range else institution),
                "date_from": date_from,
                "date_to": date_to,
                "degree": edu.get("degree", "").strip(),
            }
        )

    # Language rows — CEFR mapped at render time
    def _resolve_cefr(entry: dict, cefr_field: str, raw_field: str) -> str:
        cefr = entry.get(cefr_field, "").strip()
        if cefr:
            return cefr
        raw = entry.get(raw_field, "").strip()
        return _map_cefr(raw) if raw else ""

    languages = []
    for lang in cv.get("languages", []):
        languages.append(
            {
                "language": lang.get("language", "").strip(),
                "reading_cefr": _resolve_cefr(lang, "reading_cefr", "reading_raw"),
                "speaking_cefr": _resolve_cefr(lang, "speaking_cefr", "speaking_raw"),
                "writing_cefr": _resolve_cefr(lang, "writing_cefr", "writing_raw"),
            }
        )

    # Other skills — list to single display string
    other_skills_display = "; ".join(s.strip() for s in cv.get("other_skills", []) if s.strip())

    # Key qualifications — prefer generated_fields over extracted list
    generated_kq = [
        gf.get("content", "").strip()
        for gf in cv.get("generated_fields", [])
        if gf.get("field_key") == "key_qualifications" and gf.get("content", "").strip()
    ]
    extracted_kq = [kq.strip() for kq in cv.get("key_qualifications", []) if kq.strip()]
    key_qualifications = generated_kq if generated_kq else extracted_kq

    publications = [p.strip() for p in cv.get("publications", []) if p.strip()]

    # Countries of experience rows
    countries_of_experience = []
    for ce in cv.get("countries_of_experience", []):
        date_from = ce.get("date_from", "").strip()
        date_to = ce.get("date_to", "").strip()
        date_range = (
            f"{date_from} \u2013 {date_to}" if (date_from and date_to) else (date_from or date_to)
        )
        countries_of_experience.append(
            {
                "country": ce.get("country", "").strip(),
                "date_from": date_from,
                "date_to": date_to,
                "date_range": date_range,
            }
        )

    # Relevant projects rows
    relevant_projects = []
    for proj in cv.get("relevant_projects", []):
        relevant_projects.append(
            {
                "date_from": proj.get("date_from", "").strip(),
                "date_to": proj.get("date_to", "").strip(),
                "location": proj.get("location", "").strip(),
                "company": proj.get("company", "").strip(),
                "positions_held": proj.get("positions_held", "").strip(),
                "project_name": proj.get("project_name", "").strip(),
                "main_project_features": proj.get("main_project_features", "").strip(),
                "activities_performed": proj.get("activities_performed", "").strip(),
                "client": proj.get("client", "").strip(),
                "donor": proj.get("donor", "").strip(),
                "duration": proj.get("duration", "").strip(),
            }
        )

    return {
        # Identity
        "proposed_position": cv.get("proposed_position", "").strip(),
        "category": cv.get("category", "").strip(),
        "employer": cv.get("employer", "").strip(),
        "present_position": cv.get("present_position", "").strip(),
        "years_with_firm": cv.get("years_with_firm", "").strip(),
        # Personal info (flat for template convenience)
        "personal_info": {
            "title": pi.get("title", "").strip(),
            "first_names": pi.get("first_names", "").strip(),
            "family_name": pi.get("family_name", "").strip(),
            "full_name": pi.get("full_name", "").strip(),
            "date_of_birth": pi.get("date_of_birth", "").strip(),
            "place_of_residence": pi.get("place_of_residence", "").strip(),
            "email": pi.get("email", "").strip(),
            "phone": pi.get("phone", "").strip(),
        },
        # Derived display fields
        "nationality_display": nationality_display,
        "other_skills_display": other_skills_display,
        "membership_professional_bodies": cv.get("membership_professional_bodies", "").strip(),
        "other_relevant_info": cv.get("other_relevant_info", "").strip(),
        # Sections
        "education": education,
        "languages": languages,
        "key_qualifications": key_qualifications,
        "publications": publications,
        "countries_of_experience": countries_of_experience,
        "relevant_projects": relevant_projects,
    }


# ---------------------------------------------------------------------------
# Word-count utility — used by the orchestrator before calling Agent 6
# ---------------------------------------------------------------------------


def estimate_word_count(cv: dict) -> int:
    """
    Count words across all compressible fields in a CVData dict.
    Mirrors the compressor agent's definition of compressible fields exactly.
    """

    def w(s: str) -> int:
        return len(s.split()) if s else 0

    total = 0
    for proj in cv.get("relevant_projects", []):
        total += w(proj.get("activities_performed", ""))
        total += w(proj.get("main_project_features", ""))
    for gf in cv.get("generated_fields", []):
        total += w(gf.get("content", ""))
    for kq in cv.get("key_qualifications", []):
        total += w(kq)
    total += w(cv.get("other_relevant_info", ""))
    for skill in cv.get("other_skills", []):
        total += w(skill)
    for pub in cv.get("publications", []):
        total += w(pub)
    return total


def words_to_target(current_words: int, page_limit: int, words_per_page: int = 450) -> int:
    """
    Convert a page limit to a target word count for Agent 6 (Compressor).
    words_per_page default of 450 is a conservative estimate for a GIZ CV with tables.
    """
    return page_limit * words_per_page


def get_compression_params(session_id: str) -> dict:
    """
    Estimate current word count and resolve compression target for Agent 6.
    Called by the orchestrator before Phase 3 to pass target_words to the compressor.
    """
    run_dir = get_run_dir(session_id)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    gf = json.loads((run_dir / "generated_fields.json").read_text(encoding="utf-8"))
    cv_data = gf.get("generated", {})

    params = manifest.get("params", {})
    page_limit = int(params.get("page_limit") or 4)  # GIZ FormatProfile default

    current_words = estimate_word_count(cv_data)
    target_words = words_to_target(current_words, page_limit)

    return {
        "current_words": current_words,
        "target_words": target_words,
        "compression_ratio": 0.80,
        "page_limit": page_limit,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(
    session_id: str,
    template_path: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    """
    Render the GIZ CV for a completed pipeline run.

    Args:
        session_id:    The session UUID (maps to runs/{session_id}/ directory).
        template_path: Override default template location (for testing).
        output_path:   Override default output location (for testing).

    Returns:
        Path to the rendered output.docx.

    Raises:
        FileNotFoundError: If run directory or GIZ template is missing.
        ValueError:        If generated_fields.json is missing or malformed.
    """
    run_dir = get_run_dir(session_id)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    gf_path = run_dir / "generated_fields.json"
    if not gf_path.exists():
        raise ValueError(
            f"generated_fields.json not found in {run_dir}. "
            "Has the pipeline completed through Phase 3?"
        )

    gf = json.loads(gf_path.read_text(encoding="utf-8"))
    cv_data = gf.get("generated")
    if not cv_data:
        raise ValueError(
            "generated_fields.json has no 'generated' key. "
            "Has Agent 4 (Fields Generator) completed?"
        )

    tpl_path = ensure_under(template_path, TEMPLATE_ROOT) if template_path else TEMPLATE_PATH
    if not tpl_path.exists():
        raise FileNotFoundError(f"GIZ template not found at: {tpl_path}")

    out_path = ensure_under(output_path, run_dir) if output_path else run_dir / "output.docx"

    context = _build_context(cv_data)
    counts = {
        "education": len(context.get("education", [])),
        "languages": len(context.get("languages", [])),
        "countries_of_experience": len(context.get("countries_of_experience", [])),
        "relevant_projects": len(context.get("relevant_projects", [])),
        "key_qualifications": len(context.get("key_qualifications", [])),
        "publications": len(context.get("publications", [])),
    }
    dynamic_template_path = get_giz_dynamic_template_path(session_id)
    dynamic_unpacked_dir = get_giz_dynamic_unpack_dir(session_id)

    try:
        build_dynamic_template(
            src_docx=tpl_path,
            out_docx=dynamic_template_path,
            counts=counts,
            unpacked_dir=dynamic_unpacked_dir,
        )
    except Exception as exc:
        raise ValueError(
            f"Failed to build dynamic GIZ template for run {session_id}: {exc}"
        ) from exc

    doc = DocxTemplate(str(dynamic_template_path))
    doc.render(context)
    doc.save(str(out_path))

    return out_path
