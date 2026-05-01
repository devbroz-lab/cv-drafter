"""
Dispatch renderers and compression helpers by session target_format.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

_RenderFn = Callable[[str], Path]


def get_renderer(target_format: str) -> _RenderFn:
    fmt = (target_format or "giz").strip().lower().replace(" ", "_")
    if fmt == "giz":
        from templates import giz

        return giz.run
    if fmt == "world_bank":
        from templates import wb

        return wb.run
    raise ValueError(
        f"Unknown target_format: {target_format!r}. Supported: 'giz', 'world_bank'"
    )


def get_compression_params(target_format: str, session_id: str) -> dict:
    fmt = (target_format or "giz").strip().lower().replace(" ", "_")
    if fmt == "giz":
        from templates import giz

        return giz.get_compression_params(session_id)
    if fmt == "world_bank":
        from templates import wb

        return wb.get_compression_params(session_id)
    raise ValueError(
        f"Unknown target_format: {target_format!r}. Supported: 'giz', 'world_bank'"
    )
