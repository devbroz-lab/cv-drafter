"""
World Bank CV Renderer.

Reads generated_fields.json from a completed pipeline run and fills
WB-Template.docx using docxtpl after building a run-scoped dynamic template.

Usage (called by pipeline/orchestrator.py after checkpoint_3 approval):
    from templates.wb import run
    output_path = run(session_id)
"""

from __future__ import annotations

import json
from pathlib import Path

try:
    from docxtpl import DocxTemplate
except ImportError as _err:
    raise ImportError(
        "docxtpl is required for the World Bank renderer. " "Run: pip install -e '.[dev]'"
    ) from _err

from pipeline.paths import (
    TEMPLATE_ROOT,
    WB_TEMPLATE_PATH,
    ensure_under,
    get_run_dir,
    get_wb_dynamic_template_path,
    get_wb_dynamic_unpack_dir,
)
from templates.wb_dynamic_template import build_dynamic_template


def _build_context(cv: dict) -> dict:
    """
    Convert CVData dict into the Jinja2 context expected by the WB template.

    - Languages use raw proficiency (freetext), not CEFR.
    - employment_record.period from from_date + to_date; position from positions_held.
    - tasks_assigned per project from generated_fields (field_key=detailed_tasks) by index.
    """
    pi = cv.get("personal_info", {})

    education = []
    for edu in cv.get("education", []):
        date_from = edu.get("date_from", "").strip()
        date_to = edu.get("date_to", "").strip()
        date_obtained = edu.get("date_obtained", "").strip()
        if not date_obtained:
            if date_from and date_to:
                date_obtained = f"{date_from} – {date_to}"
            else:
                date_obtained = date_from or date_to
        education.append(
            {
                "institution": edu.get("institution", "").strip(),
                "degree": edu.get("degree", "").strip(),
                "date_obtained": date_obtained,
            }
        )

    languages = []
    for lang in cv.get("languages", []):
        languages.append(
            {
                "language": lang.get("language", "").strip(),
                "reading_raw": lang.get("reading_raw", "").strip(),
                "speaking_raw": lang.get("speaking_raw", "").strip(),
                "writing_raw": lang.get("writing_raw", "").strip(),
            }
        )

    employment_record = []
    for emp in cv.get("employment_record", []):
        from_date = emp.get("from_date", "").strip()
        to_date = emp.get("to_date", "").strip()
        if from_date and to_date:
            period = f"{from_date} – {to_date}"
        else:
            period = from_date or to_date
        employment_record.append(
            {
                "period": period,
                "employer": emp.get("employer", "").strip(),
                "position": emp.get("positions_held", "").strip(),
                "country": emp.get("country", "").strip(),
            }
        )

    detailed_tasks = [
        gf.get("content", "").strip()
        for gf in cv.get("generated_fields", [])
        if gf.get("field_key") == "detailed_tasks" and gf.get("content", "").strip()
    ]

    relevant_projects = []
    for i, proj in enumerate(cv.get("relevant_projects", [])):
        date_from = proj.get("date_from", "").strip()
        date_to = proj.get("date_to", "").strip()
        year = proj.get("year", "").strip()
        if not year:
            if date_from and date_to:
                year = f"{date_from} – {date_to}"
            else:
                year = date_from or date_to

        relevant_projects.append(
            {
                "tasks_assigned": detailed_tasks[i] if i < len(detailed_tasks) else "",
                "project_name": proj.get("project_name", "").strip(),
                "year": year,
                "location": proj.get("location", "").strip(),
                "client": proj.get("client", "").strip(),
                "main_project_features": proj.get("main_project_features", "").strip(),
                "positions_held": proj.get("positions_held", "").strip(),
                "activities_performed": proj.get("activities_performed", "").strip(),
            }
        )

    publications = [p.strip() for p in cv.get("publications", []) if p.strip()]

    return {
        "proposed_position": cv.get("proposed_position", "").strip(),
        "world_bank_affiliation": cv.get("world_bank_affiliation", "").strip(),
        "personal_info": {
            "full_name": pi.get("full_name", "").strip(),
            "date_of_birth": pi.get("date_of_birth", "").strip(),
            "nationality": pi.get("nationality", "").strip(),
            "email": pi.get("email", "").strip(),
            "phone": pi.get("phone", "").strip(),
        },
        "education": education,
        "languages": languages,
        "employment_record": employment_record,
        "relevant_projects": relevant_projects,
        "publications": publications,
    }


def estimate_word_count(cv: dict) -> int:
    """Count words across compressible fields; keep in sync with compressor._count_compressible_words."""

    def w(s: str) -> int:
        return len(s.split()) if s else 0

    total = 0
    for proj in cv.get("relevant_projects", []):
        total += w(proj.get("activities_performed", ""))
        total += w(proj.get("main_project_features", ""))
    for emp in cv.get("employment_record", []):
        total += w(emp.get("description", ""))
    for gf in cv.get("generated_fields", []):
        total += w(gf.get("content", ""))
    for kq in cv.get("key_qualifications", []):
        total += w(kq)
    total += w(cv.get("other_relevant_info", ""))
    for skill in cv.get("other_skills", []):
        total += w(skill)
    for item in cv.get("training", []):
        total += w(item)
    for pub in cv.get("publications", []):
        total += w(pub)
    return total


def words_to_target(current_words: int, page_limit: int, words_per_page: int = 450) -> int:
    return page_limit * words_per_page


def get_compression_params(session_id: str) -> dict:
    """Resolve compression target for Agent 6 (World Bank)."""
    run_dir = get_run_dir(session_id)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    gf = json.loads((run_dir / "generated_fields.json").read_text(encoding="utf-8"))
    cv_data = gf.get("generated", {})

    params = manifest.get("params", {})
    page_limit = int(params.get("page_limit") or 4)

    current_words = estimate_word_count(cv_data)
    target_words = words_to_target(current_words, page_limit)

    return {
        "current_words": current_words,
        "target_words": target_words,
        "compression_ratio": 0.80,
        "page_limit": page_limit,
    }


def run(
    session_id: str,
    template_path: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    """Render the World Bank CV for a completed pipeline run."""
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

    tpl_path = ensure_under(template_path, TEMPLATE_ROOT) if template_path else WB_TEMPLATE_PATH
    if not tpl_path.exists():
        raise FileNotFoundError(f"WB template not found at: {tpl_path}")

    out_path = ensure_under(output_path, run_dir) if output_path else run_dir / "output.docx"

    context = _build_context(cv_data)
    counts = {
        "education": len(context["education"]),
        "languages": len(context["languages"]),
        "employment_record": len(context["employment_record"]),
        "relevant_projects": len(context["relevant_projects"]),
        "publications": len(context["publications"]),
    }
    dynamic_template_path = get_wb_dynamic_template_path(session_id)
    dynamic_unpacked_dir = get_wb_dynamic_unpack_dir(session_id)

    try:
        build_dynamic_template(
            src_docx=tpl_path,
            out_docx=dynamic_template_path,
            counts=counts,
            unpacked_dir=dynamic_unpacked_dir,
        )
    except Exception as exc:
        raise ValueError(
            f"Failed to build dynamic WB template for run {session_id}: {exc}"
        ) from exc

    doc = DocxTemplate(str(dynamic_template_path))
    doc.render(context)
    doc.save(str(out_path))

    return out_path
