"""
Path constants and security helpers for the CV pipeline.

All paths are resolved relative to the backend project root so the server
works correctly regardless of the working directory it is launched from.
"""

from __future__ import annotations

import re
from pathlib import Path

# Project root — two levels up from this file (pipeline/paths.py → pipeline/ → root)
_BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Local artifact storage — one folder per session_id
RUNS_ROOT: Path = _BACKEND_ROOT / "runs"

# GIZ Word template used by the renderer
TEMPLATE_ROOT: Path = _BACKEND_ROOT / "templates"
TEMPLATE_PATH: Path = TEMPLATE_ROOT / "GIZ-Template.docx"
GIZ_DYNAMIC_TEMPLATE_NAME = "GIZ-Template.dynamic.docx"
GIZ_DYNAMIC_UNPACK_DIR_NAME = "_giz_template_unpacked"

# run_id / session_id validation — letters, digits, hyphens, underscores only
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def ensure_under(path: Path, base: Path) -> Path:
    """
    Raise ValueError if *path* escapes *base* (path-traversal guard).
    Returns the resolved path on success.
    """
    resolved_base = base.resolve(strict=False)
    resolved_path = path.resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_base)
    except ValueError as exc:
        raise ValueError(f"Path escapes allowed scope: {resolved_path}") from exc
    return resolved_path


def resolve_under(base: Path, *parts: str | Path) -> Path:
    """Join *parts* onto *base* and ensure the result stays inside *base*."""
    candidate = base.joinpath(*parts)
    return ensure_under(candidate, base)


def validate_run_id(run_id: str) -> str:
    """Raise ValueError if *run_id* contains unsafe characters."""
    if not isinstance(run_id, str) or not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError("Invalid run_id format. Allowed: letters, numbers, '_' and '-' only.")
    return run_id


def get_run_dir(run_id: str) -> Path:
    """Return the run directory path for *run_id*, validated and scoped to RUNS_ROOT."""
    valid_id = validate_run_id(run_id)
    return resolve_under(RUNS_ROOT, valid_id)


def get_giz_dynamic_template_path(run_id: str) -> Path:
    """Return the run-scoped dynamic GIZ template path."""
    return resolve_under(get_run_dir(run_id), GIZ_DYNAMIC_TEMPLATE_NAME)


def get_giz_dynamic_unpack_dir(run_id: str) -> Path:
    """Return the run-scoped unpack directory used for dynamic template build."""
    return resolve_under(get_run_dir(run_id), GIZ_DYNAMIC_UNPACK_DIR_NAME)
