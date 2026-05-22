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

import html as _html
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

from pipeline.precompute_utils import _parse_date
from pipeline.utils.cefr import map_cefr as _map_cefr


def _xml_str(s: str) -> str:
    """
    Escape XML special characters so values are safe for insertion into docx
    XML via docxtpl's string-based Jinja2 rendering.

    R7-F: docxtpl renders {{ variable }} by substituting the Python string
    directly into the OOXML source. If a value contains a bare '&', the
    resulting XML is invalid and the parser strips the character (confirmed in
    production runs: "Legal & Policy" -> "Legal  Policy"). html.escape() maps
    '&' -> '&amp;', '<' -> '&lt;', '>' -> '&gt;', ensuring all values are
    valid XML text nodes.
    """
    return _html.escape(str(s), quote=False)


def _edu_date_sort_key(edu: dict) -> tuple:
    """Descending sort key for education entries: newest date_to first."""
    to_parsed = _parse_date(edu.get("date_to", "") or edu.get("date_obtained", ""))
    from_parsed = _parse_date(edu.get("date_from", ""))
    to_key = to_parsed if to_parsed else (0, 0)
    from_key = from_parsed if from_parsed else (0, 0)
    return (to_key[0], to_key[1], from_key[0], from_key[1])


# ---------------------------------------------------------------------------
# Context builder — transforms CVData dict into template-ready context.
# All transformations happen here; the template stays dumb.
# ---------------------------------------------------------------------------


def _build_context(cv: dict) -> dict:
    pi = cv.get("personal_info", {})

    # Education rows
    # R7-G: sort education entries newest-first before building rows.
    # GIZ CV convention is most-recent qualification at the top.
    sorted_education = sorted(
        cv.get("education", []),
        key=_edu_date_sort_key,
        reverse=True,
    )

    education = []
    for edu in sorted_education:
        date_from = edu.get("date_from", "").strip()
        date_to = edu.get("date_to", "").strip()
        date_obtained = edu.get("date_obtained", "").strip()

        # R7-E: do NOT append "[date_range]" to the institution cell — dates
        # are already rendered in the date_from / date_to columns by the dynamic
        # template. Appending them here produces double date display in the output.
        institution = edu.get("institution", "").strip()

        # R7-E edge case: single-year diploma where only date_obtained is
        # present. Write date_obtained into date_from so the template's
        # "{{ date_from }} – {{ date_to }}" substitution still renders something
        # in the date column rather than leaving it blank.
        if not date_from and date_obtained:
            date_from = date_obtained

        education.append(
            {
                # R7-F: _xml_str escapes & -> &amp; so ampersands in institution
                # names are not stripped by the docx XML parser.
                "institution": _xml_str(institution),
                "date_from": _xml_str(date_from),
                "date_to": _xml_str(date_to),
                "degree": _xml_str(edu.get("degree", "").strip()),
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
                "language": _xml_str(lang.get("language", "").strip()),
                "reading_cefr": _xml_str(_resolve_cefr(lang, "reading_cefr", "reading_raw")),
                "speaking_cefr": _xml_str(_resolve_cefr(lang, "speaking_cefr", "speaking_raw")),
                "writing_cefr": _xml_str(_resolve_cefr(lang, "writing_cefr", "writing_raw")),
            }
        )

    # R7-F: _xml_str applied to joined strings so ampersands in skill names
    # are not stripped by the XML parser.
    other_skills_display = _xml_str(
        "; ".join(s.strip() for s in cv.get("other_skills", []) if s.strip())
    )

    # Key qualifications — prefer generated_fields over extracted list
    # R7-F: _xml_str escapes any '&' in bullet text.
    generated_kq = [
        _xml_str(gf.get("content", "").strip())
        for gf in cv.get("generated_fields", [])
        if gf.get("field_key") == "key_qualifications" and gf.get("content", "").strip()
    ]
    extracted_kq = [_xml_str(kq.strip()) for kq in cv.get("key_qualifications", []) if kq.strip()]
    key_qualifications = generated_kq if generated_kq else extracted_kq

    publications = [_xml_str(p.strip()) for p in cv.get("publications", []) if p.strip()]

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
                "country": _xml_str(ce.get("country", "").strip()),
                "date_from": _xml_str(date_from),
                "date_to": _xml_str(date_to),
                "date_range": _xml_str(date_range),
            }
        )

    # Relevant projects rows
    # R7-F: _xml_str applied to all string fields so ampersands in project
    # names, client names, locations, etc. are not stripped by the XML parser.
    relevant_projects = []
    for proj in cv.get("relevant_projects", []):
        relevant_projects.append(
            {
                "date_from": _xml_str(proj.get("date_from", "").strip()),
                "date_to": _xml_str(proj.get("date_to", "").strip()),
                "location": _xml_str(proj.get("location", "").strip()),
                "company": _xml_str(proj.get("company", "").strip()),
                "positions_held": _xml_str(proj.get("positions_held", "").strip()),
                "project_name": _xml_str(proj.get("project_name", "").strip()),
                "main_project_features": _xml_str(proj.get("main_project_features", "").strip()),
                "activities_performed": _xml_str(proj.get("activities_performed", "").strip()),
                "client": _xml_str(proj.get("client", "").strip()),
                "donor": _xml_str(proj.get("donor", "").strip()),
                "duration": _xml_str(proj.get("duration", "").strip()),
            }
        )

    # R7-F: _xml_str applied to all string values in the context dict.
    # docxtpl renders {{ variable }} by string-substituting into OOXML; bare
    # '&' characters would produce invalid XML and get stripped by the parser.
    nat1 = pi.get("nationality", "").strip()
    nat2 = pi.get("nationality_second", "").strip()
    nationality_display = _xml_str(f"{nat1} and {nat2}" if (nat1 and nat2) else (nat1 or nat2))

    return {
        # Identity
        "proposed_position": _xml_str(cv.get("proposed_position", "").strip()),
        "category": _xml_str(cv.get("category", "").strip()),
        "employer": _xml_str(cv.get("employer", "").strip()),
        "present_position": _xml_str(cv.get("present_position", "").strip()),
        "years_with_firm": _xml_str(cv.get("years_with_firm", "").strip()),
        # Personal info (flat for template convenience)
        "personal_info": {
            "title": _xml_str(pi.get("title", "").strip()),
            "first_names": _xml_str(pi.get("first_names", "").strip()),
            "family_name": _xml_str(pi.get("family_name", "").strip()),
            "full_name": _xml_str(pi.get("full_name", "").strip()),
            "date_of_birth": _xml_str(pi.get("date_of_birth", "").strip()),
            "place_of_residence": _xml_str(pi.get("place_of_residence", "").strip()),
            "email": _xml_str(pi.get("email", "").strip()),
            "phone": _xml_str(pi.get("phone", "").strip()),
        },
        # Derived display fields
        "nationality_display": nationality_display,
        "other_skills_display": other_skills_display,
        "membership_professional_bodies": _xml_str(cv.get("membership_professional_bodies", "").strip()),
        "other_relevant_info": _xml_str(cv.get("other_relevant_info", "").strip()),
        # Sections
        "education": education,
        "languages": languages,
        "key_qualifications": key_qualifications,
        "publications": publications,
        # Optional sections — rendered when non-empty (requires template placeholders)
        "references": [
            {k: _xml_str(v) if isinstance(v, str) else v for k, v in r.items()}
            for r in cv.get("references", [])
            if r.get("name", "").strip()
        ],
        "certification_declaration": _xml_str(cv.get("certification_declaration", "").strip()),
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
