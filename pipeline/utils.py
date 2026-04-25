"""Shared helper utilities used by agents across the pipeline."""

from __future__ import annotations


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
