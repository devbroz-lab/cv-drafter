"""Unit tests for pipeline.utils.extract_json_object."""

from pipeline.utils import extract_json_object


class TestExtractJsonObject:

    def test_clean_object_returned_unchanged(self):
        raw = '{"a": 1, "b": "hello"}'
        assert extract_json_object(raw) == raw

    def test_strips_prose_before_object(self):
        raw = 'Here is the JSON: {"a": 1}'
        assert extract_json_object(raw) == '{"a": 1}'

    def test_strips_prose_after_object(self):
        raw = '{"a": 1}\nThat is all.'
        assert extract_json_object(raw) == '{"a": 1}'

    def test_strips_prose_on_both_sides(self):
        raw = 'Sure, here you go: {"a": 1} Hope that helps!'
        assert extract_json_object(raw) == '{"a": 1}'

    def test_returns_input_when_no_braces(self):
        raw = "no json here"
        assert extract_json_object(raw) == raw

    def test_handles_nested_objects(self):
        """rfind('}') must find the outermost closing brace, not the first."""
        raw = '{"outer": {"inner": 1}, "x": 2}'
        assert extract_json_object(raw) == raw
