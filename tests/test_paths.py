"""
Tests for the shared bracket/dot path resolver in ``pipeline.utils.paths``
(extracted from field_editor; reused by A5 content_reviewer and A6 compressor).
"""

import pytest

from pipeline.utils.paths import get_by_path, normalise_path, set_by_path


class TestNormalisePath:
    def test_bracket(self):
        assert normalise_path("key_qualifications[2]") == ["key_qualifications", 2]

    def test_bracket_then_key(self):
        assert normalise_path("relevant_projects[1].location") == [
            "relevant_projects", 1, "location"
        ]

    def test_dot(self):
        assert normalise_path("personal_info.first_names") == [
            "personal_info", "first_names"
        ]


class TestGetSetByPath:
    def _data(self):
        return {
            "personal_info": {"first_names": "Ada"},
            "key_qualifications": ["a", "b", "c"],
            "relevant_projects": [
                {"main_project_features": "orig0"},
                {"main_project_features": "orig1"},
            ],
            "generated_fields": [{"content": "x"}],
        }

    def test_get_list_index(self):
        assert get_by_path(self._data(), "key_qualifications[1]") == "b"

    def test_get_nested(self):
        assert get_by_path(self._data(), "relevant_projects[0].main_project_features") == "orig0"

    def test_set_list_index(self):
        d = self._data()
        set_by_path(d, "key_qualifications[2]", "Z")
        assert d["key_qualifications"][2] == "Z"

    def test_set_nested_bracket(self):
        d = self._data()
        set_by_path(d, "relevant_projects[1].main_project_features", "new1")
        assert d["relevant_projects"][1]["main_project_features"] == "new1"

    def test_set_generated_fields_content(self):
        d = self._data()
        set_by_path(d, "generated_fields[0].content", "edited")
        assert d["generated_fields"][0]["content"] == "edited"

    def test_set_dot_notation(self):
        d = self._data()
        set_by_path(d, "personal_info.first_names", "Grace")
        assert d["personal_info"]["first_names"] == "Grace"

    def test_missing_key_raises(self):
        with pytest.raises((KeyError, IndexError, TypeError)):
            set_by_path(self._data(), "nope.deep.path", "v")

    def test_index_out_of_range_raises(self):
        with pytest.raises((KeyError, IndexError, TypeError)):
            set_by_path(self._data(), "relevant_projects[9].main_project_features", "v")
