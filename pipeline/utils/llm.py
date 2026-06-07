"""
Shared LLM call + JSON-parse helper with *intelligent* parse-failure recovery.

Every agent runs the same sequence:

    client.messages.stream(...) -> get_final_message()
      -> stop_reason check
      -> strip_code_fences -> extract_json_object -> json.loads

``call_agent_json`` centralises that sequence and adds a recovery path for the
two failure modes that appeared after the CV Extractor moved to Opus 4.8:

  1. ``stop_reason == "max_tokens"`` — output genuinely exceeded the budget.
  2. ``json.JSONDecodeError`` (e.g. "Expecting ',' delimiter") on a *completed*
     (``end_turn``) but oversized output — a malformed token somewhere in a
     much larger JSON blob.

Recovery is **not** a blind retry.  Re-sending the identical request just
reproduces the same oversized / error-causing payload.  The retry fires ONLY
when the caller supplies a ``reduce_input`` callback that returns a *smaller*
user message for the next attempt (the "intelligent garnish").  When no
``reduce_input`` is given, the helper fails fast with the same error the agents
raised before — guaranteeing a retry never re-sends the failing input.

This module makes NO decisions about WHAT to trim; that lives in each agent's
``reduce_input`` closure (only the agent knows its message structure).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from pipeline.utils._helpers import extract_json_object, strip_code_fences

log = logging.getLogger(__name__)


def _log_usage(response, *, context: str, attempt: int) -> None:
    """Log per-call output/input token usage so the anti-inflation guardrail is
    observable (compare output_tokens before/after a change)."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    log.info(
        "agent_call usage [%s attempt=%d]: input_tokens=%s output_tokens=%s stop_reason=%s",
        context,
        attempt,
        getattr(usage, "input_tokens", None),
        getattr(usage, "output_tokens", None),
        getattr(response, "stop_reason", None),
    )


def call_agent_json(
    *,
    client,
    model: str,
    max_tokens: int,
    system: str,
    user_message: str,
    context: str,
    reduce_input: Callable[[int], str] | None = None,
    max_retries: int = 2,
) -> dict:
    """Run a streaming LLM call and return the parsed JSON object.

    Parameters
    ----------
    client : Anthropic
        The Anthropic SDK client.
    model, max_tokens, system : str / int / str
        Forwarded to ``client.messages.stream``.  ``max_tokens`` is a hard
        ceiling, not a target.
    user_message : str
        The user message for the first (full-input) attempt.
    context : str
        Short label for log / error messages (e.g. ``"cv_tor_mapper.run"``).
    reduce_input : Callable[[int], str] | None
        Given the next attempt number (1-based), returns a NEW, smaller user
        message — the "intelligent garnish" that drops the error-causing input.
        When ``None``, the helper does NOT retry and re-raises (fail fast).
    max_retries : int
        Maximum number of *reduced* retries after the initial attempt.

    Returns
    -------
    dict
        The parsed JSON object.  Callers still run their own Pydantic
        ``model_validate`` afterwards, so schema-validation errors stay in the
        agent.

    Raises
    ------
    ValueError
        On truncation (``max_tokens``) with no further reduction available, or
        on a ``JSONDecodeError`` that survives all reduced retries.  Message
        wording mirrors the agents' previous inline errors.
    """
    message = user_message

    for attempt in range(max_retries + 1):
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": message}],
        ) as stream:
            response = stream.get_final_message()

        _log_usage(response, context=context, attempt=attempt)

        can_retry = reduce_input is not None and attempt < max_retries

        # --- Truncation -----------------------------------------------------
        if response.stop_reason == "max_tokens":
            if can_retry:
                log.warning(
                    "%s hit max_tokens (attempt %d) — retrying with reduced input",
                    context,
                    attempt,
                )
                message = reduce_input(attempt + 1)
                continue
            raise ValueError(
                f"{context} response was truncated (max_tokens reached). "
                "Increase max_tokens or reduce input length."
            )

        # --- Parse ----------------------------------------------------------
        raw = strip_code_fences(response.content[0].text.strip())
        raw = extract_json_object(raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            if can_retry:
                log.warning(
                    "%s returned invalid JSON (attempt %d): %s — retrying with reduced input",
                    context,
                    attempt,
                    exc,
                )
                message = reduce_input(attempt + 1)
                continue
            raise ValueError(
                f"{context} returned invalid JSON: {exc}\n\nRaw output:\n{raw}"
            ) from exc

    # Unreachable: the loop either returns or raises on the final attempt.
    raise ValueError(f"{context} exhausted all parse attempts.")
