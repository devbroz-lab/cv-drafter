"""Tests for LLM JSON repair and parsing helpers."""

import pytest

from pipeline.utils import loads_llm_json_object, repair_llm_json_text


def test_repair_trailing_comma() -> None:
    raw = '{"a": 1,}'
    repaired = repair_llm_json_text(raw)
    assert loads_llm_json_object(repaired, context="test") == {"a": 1}


def test_repair_smart_quotes() -> None:
    raw = "{\u201ca\u201d: 1}"
    repaired = repair_llm_json_text(raw)
    assert loads_llm_json_object(repaired, context="test") == {"a": 1}


def test_loads_strips_fences_and_extracts_object() -> None:
    raw = 'Note:\n```json\n{"ok": true}\n```'
    assert loads_llm_json_object(raw, context="test") == {"ok": True}
