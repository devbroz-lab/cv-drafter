"""
Tests for the intelligent parse-failure recovery helper
``pipeline.utils.llm.call_agent_json``.

Key behaviours:
  - With a ``reduce_input`` callback, a JSONDecodeError (or max_tokens) triggers
    a retry that sends the *reduced* message returned by the callback.
  - With ``reduce_input=None``, there is NO retry — the helper fails fast (never
    re-sends the error-causing input).
"""

import types

import pytest

from pipeline.utils.llm import call_agent_json


class _Resp:
    def __init__(self, text: str, stop_reason: str = "end_turn"):
        self.stop_reason = stop_reason
        self.content = [types.SimpleNamespace(text=text)]
        self.usage = types.SimpleNamespace(input_tokens=1, output_tokens=1)


class _Stream:
    def __init__(self, resp: _Resp):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._resp


class _Messages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.sent: list[str] = []

    def stream(self, *, model, max_tokens, system, messages):
        self.sent.append(messages[0]["content"])
        return _Stream(self._responses[len(self.sent) - 1])


class _Client:
    def __init__(self, responses):
        self.messages = _Messages(responses)


def _call(client, reduce_input=None, max_retries=2):
    return call_agent_json(
        client=client,
        model="m",
        max_tokens=10,
        system="s",
        user_message="full",
        context="test",
        reduce_input=reduce_input,
        max_retries=max_retries,
    )


class TestReducedRetry:
    def test_json_error_then_reduced_retry_succeeds(self):
        client = _Client([_Resp("{bad json"), _Resp('{"ok": 1}')])
        attempts = []

        def reduce(attempt: int) -> str:
            attempts.append(attempt)
            return f"reduced-{attempt}"

        out = _call(client, reduce_input=reduce)
        assert out == {"ok": 1}
        # reduce_input called once (for attempt 1); second call used the reduced msg
        assert attempts == [1]
        assert client.messages.sent == ["full", "reduced-1"]

    def test_max_tokens_then_reduced_retry_succeeds(self):
        client = _Client([_Resp("", stop_reason="max_tokens"), _Resp('{"ok": 2}')])

        def reduce(attempt: int) -> str:
            return f"reduced-{attempt}"

        out = _call(client, reduce_input=reduce)
        assert out == {"ok": 2}
        assert client.messages.sent == ["full", "reduced-1"]


class TestFailFastWithoutReduceInput:
    def test_json_error_no_retry_raises(self):
        client = _Client([_Resp("{bad json")])
        with pytest.raises(ValueError, match="invalid JSON"):
            _call(client, reduce_input=None)
        # Exactly one call — the failing input is never re-sent.
        assert client.messages.sent == ["full"]

    def test_max_tokens_no_retry_raises_truncation(self):
        client = _Client([_Resp("", stop_reason="max_tokens")])
        with pytest.raises(ValueError, match="truncated"):
            _call(client, reduce_input=None)
        assert client.messages.sent == ["full"]


class TestRetryExhaustion:
    def test_all_reduced_retries_fail_then_raises(self):
        client = _Client([_Resp("{bad"), _Resp("{still bad"), _Resp("{nope")])
        sent_reduced = []

        def reduce(attempt: int) -> str:
            sent_reduced.append(attempt)
            return f"reduced-{attempt}"

        with pytest.raises(ValueError, match="invalid JSON"):
            _call(client, reduce_input=reduce, max_retries=2)
        # 1 initial + 2 reduced = 3 calls; reduce_input invoked for attempts 1 and 2
        assert client.messages.sent == ["full", "reduced-1", "reduced-2"]
        assert sent_reduced == [1, 2]
