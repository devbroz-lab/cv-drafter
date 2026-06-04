"""Unit tests for parametrized credit math."""

from decimal import Decimal

import pytest

from api.services.metering import engine


def test_usd_to_credits_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine.settings, "meter_credit_usd", 1.0)
    assert engine.usd_to_credits(2.0) == Decimal("2.0000")
    assert engine.usd_to_credits(0.20) == Decimal("0.2000")


def test_usd_to_credits_custom_credit_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine.settings, "meter_credit_usd", 2.0)
    assert engine.usd_to_credits(2.0) == Decimal("1.0000")


def test_rates_snapshot_includes_computed_credits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine.settings, "meter_pipeline_run_usd", 2.0)
    monkeypatch.setattr(engine.settings, "meter_revision_usd", 0.20)
    snap = engine.rates_snapshot()
    assert snap["pipeline_run_credits"] == "2.0000"
    assert snap["revision_credits"] == "0.2000"
