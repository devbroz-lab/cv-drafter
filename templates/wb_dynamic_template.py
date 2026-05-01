"""
World Bank dynamic template preprocessor.

Builds a run-scoped dynamic .docx by expanding loop placeholders in word/document.xml
into indexed Jinja expressions (tables 0–3 + publications bullet loop).
"""

from __future__ import annotations

import os
import re
import shutil
import zipfile
from pathlib import Path

_COUNT_KEYS = (
    "education",
    "languages",
    "employment_record",
    "relevant_projects",
    "publications",
)


def _find_tables(xml: str) -> list[tuple[int, int]]:
    starts = [m.start() for m in re.finditer(r"<w:tbl>", xml)]
    ends = [m.end() for m in re.finditer(r"</w:tbl>", xml)]
    return list(zip(starts, ends))


def _find_rows(text: str) -> list[re.Match[str]]:
    return list(re.finditer(r"<w:tr\b[^>]*>.*?</w:tr>", text, re.DOTALL))


def _find_cells(row_xml: str) -> list[re.Match[str]]:
    return list(re.finditer(r"<w:tc>.*?</w:tc>", row_xml, re.DOTALL))


def _find_paragraphs(cell_xml: str) -> list[re.Match[str]]:
    return list(re.finditer(r"<w:p\b[^>]*>.*?</w:p>", cell_xml, re.DOTALL))


def _para_has_jinja_for(para_xml: str) -> bool:
    texts = re.findall(r"<w:t(?:>| [^>]*>)(.*?)</w:t>", para_xml)
    return any(t.strip().startswith("{%") and "for " in t for t in texts)


def _para_has_jinja_endfor(para_xml: str) -> bool:
    texts = re.findall(r"<w:t(?:>| [^>]*>)(.*?)</w:t>", para_xml)
    return any(t.strip().startswith("{%") and "endfor" in t for t in texts)


def _replace_text_in_para(para_xml: str, old_text: str, new_text: str) -> str:
    for attr in ["", ' xml:space="preserve"']:
        old = f"<w:t{attr}>{old_text}</w:t>"
        if old in para_xml:
            return para_xml.replace(old, '<w:t xml:space="preserve">' + new_text + "</w:t>")

    def _repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        if old_text in inner:
            return f'<w:t xml:space="preserve">{inner.replace(old_text, new_text)}</w:t>'
        return match.group(0)

    return re.sub(
        r"<w:t(?:>| [^>]*>)(.*?)</w:t>",
        _repl,
        para_xml,
        flags=re.DOTALL,
    )


def _build_cell_with_body_paras(original_cell_xml: str, new_body_paras: list[str]) -> str:
    tc_pr_m = re.search(r"<w:tcPr>.*?</w:tcPr>", original_cell_xml, re.DOTALL)
    tc_pr = tc_pr_m.group(0) if tc_pr_m else ""
    body = "\n          ".join(new_body_paras)
    return f"<w:tc>\n          {tc_pr}\n          {body}\n        </w:tc>"


def _get_tr_open_and_tr_pr(row_xml: str) -> tuple[str, str]:
    tr_open_m = re.match(r"(<w:tr\b[^>]*>)", row_xml)
    tr_open = tr_open_m.group(1) if tr_open_m else "<w:tr>"
    tr_pr_m = re.search(r"(<w:trPr>.*?</w:trPr>)", row_xml, re.DOTALL)
    tr_pr = tr_pr_m.group(1) if tr_pr_m else ""
    return tr_open, tr_pr


def clean_jinja_runs(xml: str) -> str:
    """
    Collapse split Jinja tags in table cells into a single run and strip proofErr.
    WB uses the same <w:t> attribute variants as the standalone script.
    """

    def fix_cell(cell_xml: str) -> str:
        cell_xml = re.sub(r"<w:proofErr[^/]*/>", "", cell_xml)

        def fix_para(para_xml: str) -> str:
            runs = list(re.finditer(r"<w:r\b[^>]*>.*?</w:r>", para_xml, re.DOTALL))
            if not runs:
                return para_xml
            combined = "".join(
                "".join(
                    re.findall(r"<w:t(?:>| [^>]*>)(.*?)</w:t>", r.group(0), re.DOTALL)
                )
                for r in runs
            )
            if "{{" not in combined and "{%" not in combined:
                return para_xml
            p_pr_m = re.search(r"<w:pPr>.*?</w:pPr>", para_xml, re.DOTALL)
            p_pr = p_pr_m.group(0) if p_pr_m else ""
            r_pr = ""
            for r in runs:
                r_pr_m = re.search(r"<w:rPr>.*?</w:rPr>", r.group(0), re.DOTALL)
                if r_pr_m:
                    r_pr = r_pr_m.group(0)
                    break
            space = ' xml:space="preserve"' if " " in combined else ""
            new_run = f"<w:r>{r_pr}<w:t{space}>{combined}</w:t></w:r>"
            open_tag_m = re.match(r"<w:p\b[^>]*>", para_xml)
            if not open_tag_m:
                return para_xml
            return f"{open_tag_m.group(0)}{p_pr}{new_run}</w:p>"

        return re.sub(
            r"<w:p\b[^>]*>.*?</w:p>",
            lambda m: fix_para(m.group(0)),
            cell_xml,
            flags=re.DOTALL,
        )

    return re.sub(r"<w:tc>.*?</w:tc>", lambda m: fix_cell(m.group(0)), xml, flags=re.DOTALL)


def expand_table(
    xml: str,
    tbl_idx: int,
    n_items: int,
    get_substitutions,
) -> str:
    tables = _find_tables(xml)
    if tbl_idx >= len(tables):
        raise ValueError(
            f"Expected table index {tbl_idx}, but document has only {len(tables)} table(s)."
        )
    s, e = tables[tbl_idx]
    tbl_xml = xml[s:e]
    rows = _find_rows(tbl_xml)
    if not rows:
        raise ValueError(f"Table {tbl_idx} has no rows and cannot be expanded.")
    tmpl_row = rows[-1]
    tmpl_row_xml = tmpl_row.group(0)
    cells = _find_cells(tmpl_row_xml)
    tr_open, tr_pr = _get_tr_open_and_tr_pr(tmpl_row_xml)

    cell_body_paras = []
    for cell in cells:
        paras = _find_paragraphs(cell.group(0))
        bodies = [
            p.group(0)
            for p in paras
            if not _para_has_jinja_for(p.group(0)) and not _para_has_jinja_endfor(p.group(0))
        ]
        cell_body_paras.append((cell, bodies))

    new_rows_xml = []
    for item_i in range(n_items):
        row_cells = []
        for cell_j, (cell, body_paras) in enumerate(cell_body_paras):
            new_bodies = get_substitutions(cell_j, item_i, body_paras)
            row_cells.append(_build_cell_with_body_paras(cell.group(0), new_bodies))
        cells_joined = "\n        ".join(row_cells)
        new_row = f"{tr_open}\n        {tr_pr}\n        {cells_joined}\n      </w:tr>"
        new_rows_xml.append(new_row)

    combined = "\n        ".join(new_rows_xml)
    new_tbl = tbl_xml[: tmpl_row.start()] + combined + tbl_xml[tmpl_row.end() :]
    return xml[:s] + new_tbl + xml[e:]


def expand_bullet_loop(
    xml: str,
    for_text: str,
    endfor_text: str,
    var_text: str,
    n: int,
    indexed_fn,
) -> str:
    tbl_ranges = _find_tables(xml)

    def in_table(pos: int) -> bool:
        return any(s <= pos <= e for s, e in tbl_ranges)

    all_paras = list(re.finditer(r"<w:p\b[^>]*>.*?</w:p>", xml, re.DOTALL))
    for_idx = endfor_idx = body_idx = None

    for idx, pm in enumerate(all_paras):
        if in_table(pm.start()):
            continue
        texts = re.findall(r"<w:t(?:>| [^>]*>)(.*?)</w:t>", pm.group(0))
        joined = "".join(texts)
        if for_text in joined and for_idx is None:
            for_idx = idx
            if var_text in joined:
                body_idx = idx
        if endfor_text in joined and for_idx is not None and endfor_idx is None:
            endfor_idx = idx
        if var_text in joined and for_idx is not None and body_idx is None:
            body_idx = idx

    if for_idx is None or endfor_idx is None or body_idx is None:
        return xml

    for_para = all_paras[for_idx]
    endfor_para = all_paras[endfor_idx]
    body_para = all_paras[body_idx].group(0)

    for merged in [f"{for_text} {var_text}", f"{for_text}{var_text}"]:
        for attr in ["", ' xml:space="preserve"']:
            tag = f"<w:t{attr}>{merged}</w:t>"
            if tag in body_para:
                space = ' xml:space="preserve"' if " " in var_text else ""
                body_para = body_para.replace(tag, f"<w:t{space}>{var_text}</w:t>")

    new_paras = ""
    for i in range(n):
        new_p = _replace_text_in_para(body_para, var_text, indexed_fn(i))
        new_paras += new_p + "\n"

    return xml[: for_para.start()] + new_paras + xml[endfor_para.end() :]


def _remove_employment_loop_row(xml: str) -> str:
    """Remove employment table loop row; keep header only (n_emp == 0)."""
    tables = _find_tables(xml)
    if len(tables) < 3:
        return xml
    s, e = tables[2]
    tbl = xml[s:e]
    rows = _find_rows(tbl)
    if len(rows) < 2:
        return xml
    new_tbl = tbl[: rows[1].start()] + tbl[rows[-1].end() :]
    return xml[:s] + new_tbl + xml[e:]


def _remove_publications_loop_paragraphs(xml: str) -> str:
    """Remove publications for/endfor block when n_pubs == 0."""
    for_idx = xml.find("{% for pub in publications %}")
    if for_idx == -1:
        return xml
    para_start = xml.rfind("<w:p ", 0, for_idx)
    if para_start == -1:
        return xml
    endfor_idx = xml.find("{% endfor %}", for_idx)
    if endfor_idx == -1:
        return xml
    para_end = xml.find("</w:p>", endfor_idx)
    if para_end == -1:
        return xml
    para_end += 6
    return xml[:para_start] + xml[para_end:]


def preprocess_document_xml(xml: str, counts: dict[str, int]) -> str:
    missing = [k for k in _COUNT_KEYS if k not in counts]
    if missing:
        raise ValueError(f"Missing required count keys: {', '.join(missing)}")
    invalid = [k for k in _COUNT_KEYS if counts.get(k, 0) < 0]
    if invalid:
        raise ValueError(f"Count values must be >= 0 for: {', '.join(invalid)}")

    xml = clean_jinja_runs(xml)

    n_edu = counts.get("education", 0)
    n_lang = counts.get("languages", 0)
    n_emp = counts.get("employment_record", 0)
    n_proj = counts.get("relevant_projects", 0)
    n_pubs = counts.get("publications", 0)

    def edu_subs(cell_j: int, i: int, body_paras: list[str]) -> list[str]:
        new: list[str] = []
        for p in body_paras:
            p2 = p
            if cell_j == 0:
                p2 = _replace_text_in_para(
                    p2, "{{ edu.institution }}", f"{{{{ education[{i}].institution }}}}"
                )
            elif cell_j == 1:
                p2 = _replace_text_in_para(p2, "{{ edu.degree }}", f"{{{{ education[{i}].degree }}}}")
            elif cell_j == 2:
                p2 = _replace_text_in_para(
                    p2, "{{ edu.date_obtained }}", f"{{{{ education[{i}].date_obtained }}}}"
                )
            new.append(p2)
        return new

    xml = expand_table(xml, 0, n_edu, edu_subs)

    def lang_subs(cell_j: int, i: int, body_paras: list[str]) -> list[str]:
        var_map = {
            0: ("{{ lang.language }}", f"{{{{ languages[{i}].language }}}}"),
            1: ("{{ lang.reading_raw }}", f"{{{{ languages[{i}].reading_raw }}}}"),
            2: ("{{ lang.speaking_raw }}", f"{{{{ languages[{i}].speaking_raw }}}}"),
            3: ("{{ lang.writing_raw }}", f"{{{{ languages[{i}].writing_raw }}}}"),
        }
        new: list[str] = []
        for p in body_paras:
            p2 = p
            if cell_j in var_map:
                p2 = _replace_text_in_para(p2, var_map[cell_j][0], var_map[cell_j][1])
            new.append(p2)
        return new

    xml = expand_table(xml, 1, n_lang, lang_subs)

    if n_emp > 0:

        def emp_subs(cell_j: int, i: int, body_paras: list[str]) -> list[str]:
            new: list[str] = []
            for p in body_paras:
                p2 = p
                if cell_j == 0:
                    p2 = _replace_text_in_para(
                        p2, "{{ emp.period }}", f"{{{{ employment_record[{i}].period }}}}"
                    )
                elif cell_j == 1:
                    p2 = _replace_text_in_para(
                        p2, "{{ emp.employer }}", f"{{{{ employment_record[{i}].employer }}}}"
                    )
                    p2 = _replace_text_in_para(
                        p2, "{{ emp.position }}", f"{{{{ employment_record[{i}].position }}}}"
                    )
                elif cell_j == 2:
                    p2 = _replace_text_in_para(
                        p2, "{{ emp.country }}", f"{{{{ employment_record[{i}].country }}}}"
                    )
                new.append(p2)
            return new

        xml = expand_table(xml, 2, n_emp, emp_subs)
    else:
        xml = _remove_employment_loop_row(xml)

    def proj_subs(cell_j: int, i: int, body_paras: list[str]) -> list[str]:
        new: list[str] = []
        for p in body_paras:
            p2 = p
            if cell_j == 0:
                p2 = _replace_text_in_para(
                    p2,
                    "{{ proj.tasks_assigned }}",
                    f"{{{{ relevant_projects[{i}].tasks_assigned }}}}",
                )
            elif cell_j == 1:
                for old, new_var in [
                    ("{{ proj.project_name }}", f"{{{{ relevant_projects[{i}].project_name }}}}"),
                    ("{{ proj.year }}", f"{{{{ relevant_projects[{i}].year }}}}"),
                    ("{{ proj.location }}", f"{{{{ relevant_projects[{i}].location }}}}"),
                    ("{{ proj.client }}", f"{{{{ relevant_projects[{i}].client }}}}"),
                    (
                        "{{ proj.main_project_features }}",
                        f"{{{{ relevant_projects[{i}].main_project_features }}}}",
                    ),
                    ("{{ proj.positions_held }}", f"{{{{ relevant_projects[{i}].positions_held }}}}"),
                    (
                        "{{ proj.activities_performed }}",
                        f"{{{{ relevant_projects[{i}].activities_performed }}}}",
                    ),
                ]:
                    p2 = _replace_text_in_para(p2, old, new_var)
            new.append(p2)
        return new

    xml = expand_table(xml, 3, n_proj, proj_subs)

    if n_pubs == 0:
        xml = _remove_publications_loop_paragraphs(xml)
    else:
        xml = expand_bullet_loop(
            xml,
            "{% for pub in publications %}",
            "{% endfor %}",
            "{{ pub }}",
            n_pubs,
            lambda i: f"{{{{ publications[{i}] }}}}",
        )

    return xml


def build_dynamic_template(
    src_docx: Path,
    out_docx: Path,
    counts: dict[str, int],
    unpacked_dir: Path,
) -> Path:
    if not src_docx.exists():
        raise FileNotFoundError(f"Source template not found: {src_docx}")

    if unpacked_dir.exists():
        shutil.rmtree(unpacked_dir)
    unpacked_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(src_docx, "r") as zin:
        zin.extractall(unpacked_dir)

    doc_path = unpacked_dir / "word" / "document.xml"
    if not doc_path.exists():
        raise FileNotFoundError(f"Missing document.xml inside template: {doc_path}")

    xml = doc_path.read_text(encoding="utf-8")
    xml = preprocess_document_xml(xml, counts)
    doc_path.write_text(xml, encoding="utf-8")

    out_docx.parent.mkdir(parents=True, exist_ok=True)
    if out_docx.exists():
        out_docx.unlink()

    with zipfile.ZipFile(out_docx, "w", zipfile.ZIP_DEFLATED) as zout:
        for root, _, files in os.walk(unpacked_dir):
            for file in files:
                file_path = Path(root) / file
                arcname = file_path.relative_to(unpacked_dir)
                zout.write(file_path, arcname.as_posix())

    return out_docx
