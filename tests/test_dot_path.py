import pytest
from api.services.dot_path import DotPathError, get_by_dot_path, set_by_dot_path


def test_get_set_nested():
    root: dict = {"generated_fields": [{"content": "old"}]}
    assert get_by_dot_path(root, "generated_fields.0.content") == "old"
    set_by_dot_path(root, "generated_fields.0.content", "new")
    assert root["generated_fields"][0]["content"] == "new"


def test_get_invalid_path():
    with pytest.raises(DotPathError):
        get_by_dot_path({}, "missing.key")


def test_empty_path():
    with pytest.raises(DotPathError):
        set_by_dot_path({}, "  ", "x")
