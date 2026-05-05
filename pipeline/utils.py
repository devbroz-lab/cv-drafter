"""Shared helper utilities used by agents across the pipeline."""

from __future__ import annotations

import json
from collections.abc import Collection
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from pipeline.text_encoding import UTF_8


def strip_code_fences(text: str) -> str:
    """
    Strip markdown code fences from LLM output.

    Handles both:
      ```json
      { ... }
      ```
    and bare:
      ```
      { ... }
      ```
    """
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _snippet(s: str, max_len: int = 240) -> str:
    """Single-line repr preview for logs and error messages."""
    folded = " ".join(s.split())
    if len(folded) <= max_len:
        return repr(folded)
    return repr(folded[:max_len] + "…")


def load_json_file(
    path: Path,
    *,
    context: str,
    required_keys: Collection[str] | None = None,
) -> Any:
    """
    Read *path* as decoded UTF-8 JSON with fail-fast, verbose diagnostics.

    Parameters
    ----------
    path:
        Relative or absolute path to the JSON file.
    context:
        Short caller label included in errors (e.g. ``cv_tor_mapper.cv_data``).
    required_keys:
        When set, parsed value must be a dict containing each key.

    Raises
    ------
    ValueError
        Missing path, unreadable file, non-UTF-8 bytes, empty content,
        JSON decode error, wrong type, or missing keys.
    """
    resolved = path.resolve()
    if not path.exists():
        raise ValueError(f"[{context}] JSON file missing: {resolved}")
    try:
        text = path.read_text(encoding=UTF_8, errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"[{context}] File is not valid UTF-8 ({UTF_8} strict): {resolved}: {exc}"
        ) from exc
    except OSError as exc:
        raise ValueError(f"[{context}] Could not read file: {resolved} ({exc})") from exc

    stripped = text.strip()
    if not stripped:
        raise ValueError(f"[{context}] JSON file empty or whitespace-only: {resolved}")

    try:
        data = json.loads(text)
    except JSONDecodeError as exc:
        raise ValueError(
            f"[{context}] Invalid JSON in {resolved}: {exc}; snippet={_snippet(stripped)}"
        ) from exc

    if required_keys:
        if not isinstance(data, dict):
            raise ValueError(
                f"[{context}] Expected JSON object in {resolved}, got {type(data).__name__}"
            )
        missing = sorted(k for k in required_keys if k not in data)
        if missing:
            raise ValueError(
                f"[{context}] JSON in {resolved} missing required keys {missing}; "
                f"present={sorted(data.keys())!r}"
            )
    return data


def parse_json_string(raw: str, *, context: str) -> Any:
    """Parse JSON from raw LLM text (strips fences first). Raises ValueError when invalid."""
    text = strip_code_fences(raw) if raw else ""
    stripped = text.strip()
    if not stripped:
        raise ValueError(f"[{context}] LLM output empty after stripping code fences")
    try:
        return json.loads(stripped)
    except JSONDecodeError as exc:
        raise ValueError(
            f"[{context}] Invalid JSON in LLM output: {exc}; snippet={_snippet(stripped)}"
        ) from exc


def clean_unicode(obj: object) -> object:
    """
    Recursively replace Windows replacement characters (\\ufffd) introduced
    by encoding mismatches with an em-dash.  Safe to call on any JSON-like
    structure (str, dict, list, or scalar).
    """
    if isinstance(obj, str):
        return obj.replace("\ufffd", "\u2014")
    if isinstance(obj, dict):
        return {k: clean_unicode(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_unicode(i) for i in obj]
    return obj


def load_tor_envelope(path: Path, *, context: str) -> dict[str, Any]:
    """Load tor_data.json envelope as a JSON object."""
    raw = load_json_file(path, context=context, required_keys=None)
    if not isinstance(raw, dict):
        raise ValueError(
            f"[{context}] Expected tor_data envelope object in {path.resolve()}, "
            f"got {type(raw).__name__}"
        )
    return raw


def resolve_selected_tor_pool(
    tor_raw: dict[str, Any],
    *,
    context: str,
    allow_legacy_data: bool = True,
) -> dict[str, Any]:
    """
    Resolve the selected DistilledToR pool from tor_data envelope.

    Preferred envelope:
      {
        "pools": [ ... ],
        "selected_pool_index": <int>
      }

    Temporary compatibility:
      {
        "data": { ... }
      }
    """
    pools = tor_raw.get("pools")
    if pools is not None:
        if not isinstance(pools, list) or len(pools) == 0:
            raise ValueError(
                f"[{context}] tor_data.pools must be a non-empty list, got: {type(pools).__name__}"
            )

        selected_pool_index = tor_raw.get("selected_pool_index")
        if selected_pool_index is None:
            raise ValueError(
                f"[{context}] selected_pool_index is not set. Pick a ToR pool before continuing."
            )
        if isinstance(selected_pool_index, bool) or not isinstance(selected_pool_index, int):
            raise ValueError(
                f"[{context}] selected_pool_index must be an integer, got: "
                f"{type(selected_pool_index).__name__}"
            )
        if selected_pool_index < 0 or selected_pool_index >= len(pools):
            raise ValueError(
                f"[{context}] selected_pool_index {selected_pool_index} out of range for "
                f"{len(pools)} pool(s)."
            )

        selected = pools[selected_pool_index]
        if not isinstance(selected, dict):
            raise ValueError(
                f"[{context}] selected pool must be a JSON object, got: {type(selected).__name__}"
            )
        return selected

    if allow_legacy_data and "data" in tor_raw:
        data = tor_raw["data"]
        if not isinstance(data, dict):
            raise ValueError(
                f"[{context}] legacy tor_data['data'] must be an object, got: "
                f"{type(data).__name__}"
            )
        return data

    raise ValueError(
        f"[{context}] tor_data envelope missing 'pools'. "
        "Expected tor_data['pools'][tor_data['selected_pool_index']]."
    )


def resolve_tor_for_agents(tor_raw: dict[str, Any], *, context: str) -> dict[str, Any]:
    """
    Resolve a DistilledToR payload for agent execution from tor_data envelope.

    For new envelope shape (`pools`), agent stages prior to explicit UI selection
    may still need a deterministic ToR object; in that case this helper defaults
    to the first pool when `selected_pool_index` is unset.
    """
    pools = tor_raw.get("pools")
    if pools is not None:
        if not isinstance(pools, list) or len(pools) == 0:
            raise ValueError(
                f"[{context}] tor_data.pools must be a non-empty list, got: {type(pools).__name__}"
            )

        selected_pool_index = tor_raw.get("selected_pool_index")
        if selected_pool_index is None:
            selected_pool_index = 0
        if isinstance(selected_pool_index, bool) or not isinstance(selected_pool_index, int):
            raise ValueError(
                f"[{context}] selected_pool_index must be an integer, got: "
                f"{type(selected_pool_index).__name__}"
            )
        if selected_pool_index < 0 or selected_pool_index >= len(pools):
            raise ValueError(
                f"[{context}] selected_pool_index {selected_pool_index} out of range for "
                f"{len(pools)} pool(s)."
            )

        selected = pools[selected_pool_index]
        if not isinstance(selected, dict):
            raise ValueError(
                f"[{context}] selected pool must be a JSON object, got: {type(selected).__name__}"
            )
        return selected

    data = tor_raw.get("data")
    if data is not None:
        if not isinstance(data, dict):
            raise ValueError(
                f"[{context}] legacy tor_data['data'] must be an object, got: "
                f"{type(data).__name__}"
            )
        return data

    raise ValueError(
        f"[{context}] tor_data envelope missing both 'pools' and legacy 'data'."
    )
