"""
Bracket/dot path navigation on nested dict/list structures.

Handles BOTH bracket notation (``key_qualifications[2]``) and dot notation
(``key_qualifications.2``), normalising them internally. This is the path
format emitted by the content reviewer (``generated_fields[0].content``), the
compressor patch, and the field editor.

Originally lived in ``pipeline/agents/field_editor.py``; extracted here so the
content reviewer (A5) and compressor (A6) can reuse the exact same resolver to
apply their patch outputs. ``field_editor`` re-imports these names unchanged.
"""

from __future__ import annotations

import re


def normalise_path(field_path: str) -> list[str | int]:
    """
    Convert a mixed bracket/dot path string into a list of keys/indices.

    Examples
    --------
    "key_qualifications[2]"         -> ["key_qualifications", 2]
    "relevant_projects[1].location" -> ["relevant_projects", 1, "location"]
    "personal_info.first_names"     -> ["personal_info", "first_names"]
    """
    # Replace [N] bracket notation with .N so we can split uniformly
    normalised = re.sub(r"\[(\d+)\]", r".\1", field_path)
    parts: list[str | int] = []
    for part in normalised.split("."):
        part = part.strip()
        if not part:
            continue
        parts.append(int(part) if part.isdigit() else part)
    return parts


def get_by_path(data: dict, field_path: str):
    """Return the value at field_path inside data, or raise KeyError/IndexError."""
    parts = normalise_path(field_path)
    node = data
    for part in parts:
        if isinstance(node, list):
            if not isinstance(part, int):
                raise KeyError(f"Expected integer index, got '{part}'")
            node = node[part]
        elif isinstance(node, dict):
            node = node[str(part)]
        else:
            raise KeyError(f"Cannot descend into {type(node).__name__} at '{part}'")
    return node


def set_by_path(data: dict, field_path: str, new_value) -> None:
    """Write new_value at field_path inside data (in-place). Raises on bad path."""
    parts = normalise_path(field_path)
    node = data
    for part in parts[:-1]:
        if isinstance(node, list):
            node = node[part]
        elif isinstance(node, dict):
            node = node[str(part)]
        else:
            raise KeyError(f"Cannot descend into {type(node).__name__} at '{part}'")

    last = parts[-1]
    if isinstance(node, list):
        node[last] = new_value
    else:
        node[str(last)] = new_value
