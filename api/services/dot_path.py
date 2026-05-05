"""
Dot-path navigation on nested dict/list structures (same rules as POST /resolve overrides).

Paths are relative to the root object (e.g. CVData under generated_fields.json "generated").
Numeric segments address list indices; other segments address dict keys.
"""

from __future__ import annotations

from typing import Any


class DotPathError(ValueError):
    """Invalid path or structure mismatch when reading or writing a dot path."""


def _split_path(path: str) -> list[str]:
    parts = [p for p in path.strip().split(".") if p]
    if not parts:
        raise DotPathError("Path is empty or invalid")
    return parts


def get_by_dot_path(root: Any, path: str) -> Any:
    """Return the value at *path* starting from *root* (dict or list at top level)."""
    parts = _split_path(path)
    obj: Any = root
    try:
        for part in parts:
            obj = obj[int(part)] if part.isdigit() else obj[part]
    except (KeyError, IndexError, TypeError) as exc:
        raise DotPathError(f"Cannot resolve path {path!r}: {exc}") from exc
    return obj


def set_by_dot_path(root: Any, path: str, value: Any) -> None:
    """Set the value at *path* on *root* (mutates *root* in place)."""
    parts = _split_path(path)
    obj: Any = root
    try:
        for part in parts[:-1]:
            obj = obj[int(part)] if part.isdigit() else obj[part]
        last = parts[-1]
        if last.isdigit():
            obj[int(last)] = value
        else:
            obj[last] = value
    except (KeyError, IndexError, TypeError) as exc:
        raise DotPathError(f"Cannot set path {path!r}: {exc}") from exc
