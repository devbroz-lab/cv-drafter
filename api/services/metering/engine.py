"""Pure credit math — rates come from settings, not hard-coded in call sites."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from api.config import settings

_QUANT = Decimal("0.0001")


def _d(value: float | int | str | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(_QUANT, rounding=ROUND_HALF_UP)


def credit_usd_value() -> Decimal:
    return _d(settings.meter_credit_usd)


def usd_to_credits(usd: float | Decimal) -> Decimal:
    """Convert a USD amount to credits using METER_CREDIT_USD."""
    base = credit_usd_value()
    if base <= 0:
        raise ValueError("meter_credit_usd must be positive")
    return (_d(usd) / base).quantize(_QUANT, rounding=ROUND_HALF_UP)


def pipeline_run_credits() -> Decimal:
    return usd_to_credits(settings.meter_pipeline_run_usd)


def revision_credits() -> Decimal:
    return usd_to_credits(settings.meter_revision_usd)


def initial_grant_credits() -> Decimal:
    return _d(settings.meter_initial_grant_credits)


def rates_snapshot() -> dict[str, Any]:
    """Serializable rates for API responses and ledger audit rows."""
    return {
        "credit_usd": float(settings.meter_credit_usd),
        "pipeline_run_usd": float(settings.meter_pipeline_run_usd),
        "revision_usd": float(settings.meter_revision_usd),
        "initial_grant_credits": float(settings.meter_initial_grant_credits),
        "pipeline_run_credits": str(pipeline_run_credits()),
        "revision_credits": str(revision_credits()),
    }
