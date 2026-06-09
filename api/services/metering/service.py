"""Metering persistence and orchestration (Supabase tables)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from api.services.database import get_service_client, get_session_row
from api.services.metering import engine

log = logging.getLogger(__name__)


class InsufficientCreditsError(Exception):
    def __init__(
        self,
        *,
        event: str,
        required: Decimal,
        available: Decimal,
    ) -> None:
        self.event = event
        self.required = required
        self.available = available
        super().__init__(
            f"Insufficient credits for {event}: need {required}, have {available}"
        )


@dataclass(slots=True)
class BalanceView:
    available_credits: Decimal
    reserved_credits: Decimal

    @property
    def total_credits(self) -> Decimal:
        return self.available_credits + self.reserved_credits


def get_rates() -> dict[str, Any]:
    return engine.rates_snapshot()


def _ledger_exists(idempotency_key: str) -> bool:
    result = (
        get_service_client()
        .table("meter_ledger")
        .select("id")
        .eq("idempotency_key", idempotency_key)
        .limit(1)
        .execute()
    )
    return bool(result.data)


def _append_ledger(
    *,
    user_id: str,
    session_id: str | None,
    event_type: str,
    amount_credits: Decimal,
    idempotency_key: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    payload = {
        "user_id": user_id,
        "session_id": session_id,
        "event_type": event_type,
        "amount_credits": str(amount_credits),
        "usd_rate_snapshot": engine.rates_snapshot(),
        "idempotency_key": idempotency_key,
        "metadata": metadata or {},
    }
    get_service_client().table("meter_ledger").insert(payload).execute()


def _get_balance_row(user_id: str) -> dict[str, Any] | None:
    result = (
        get_service_client()
        .table("user_meter_balances")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    return result.data[0]


def _upsert_balance(
    user_id: str,
    *,
    available: Decimal,
    reserved: Decimal,
) -> None:
    payload = {
        "user_id": user_id,
        "available_credits": str(available),
        "reserved_credits": str(reserved),
    }
    get_service_client().table("user_meter_balances").upsert(payload).execute()


def ensure_user_meter_account(user_id: str) -> BalanceView:
    row = _get_balance_row(user_id)
    if row is None:
        _upsert_balance(user_id, available=Decimal("0"), reserved=Decimal("0"))
        return BalanceView(Decimal("0"), Decimal("0"))
    return BalanceView(
        Decimal(str(row["available_credits"])),
        Decimal(str(row["reserved_credits"])),
    )


def provision_new_user(user_id: str) -> None:
    """Grant initial credits once per user (idempotent)."""
    ensure_user_meter_account(user_id)
    key = f"grant:{user_id}"
    if _ledger_exists(key):
        return
    amount = engine.initial_grant_credits()
    if amount <= 0:
        return
    balance = _get_balance_row(user_id) or {
        "available_credits": "0",
        "reserved_credits": "0",
    }
    available = Decimal(str(balance["available_credits"])) + amount
    reserved = Decimal(str(balance["reserved_credits"]))
    _upsert_balance(user_id, available=available, reserved=reserved)
    _append_ledger(
        user_id=user_id,
        session_id=None,
        event_type="grant",
        amount_credits=amount,
        idempotency_key=key,
        metadata={"reason": "initial_grant"},
    )
    log.info("Granted %s credits to user %s", amount, user_id)


def get_balance(user_id: str) -> BalanceView:
    ensure_user_meter_account(user_id)
    row = _get_balance_row(user_id)
    assert row is not None
    return BalanceView(
        Decimal(str(row["available_credits"])),
        Decimal(str(row["reserved_credits"])),
    )


def list_ledger(user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 100))
    result = (
        get_service_client()
        .table("meter_ledger")
        .select(
            "id, session_id, event_type, amount_credits, metadata, created_at"
        )
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(safe_limit)
        .execute()
    )
    return list(result.data or [])


def _get_session_metering(session_id: str) -> dict[str, Any] | None:
    result = (
        get_service_client()
        .table("session_metering")
        .select("*")
        .eq("session_id", session_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    return result.data[0]


def _upsert_session_metering(session_id: str, **fields: Any) -> None:
    existing = _get_session_metering(session_id) or {}
    payload: dict[str, Any] = {
        "session_id": session_id,
        "pipeline_reserved": bool(existing.get("pipeline_reserved")),
        "pipeline_committed": bool(existing.get("pipeline_committed")),
        "revision_count": int(existing.get("revision_count") or 0),
    }
    payload.update(fields)
    get_service_client().table("session_metering").upsert(payload).execute()


def reserve_pipeline_run(*, user_id: str, session_id: str) -> Decimal:
    """Hold pipeline credits until commit or release."""
    ensure_user_meter_account(user_id)
    key = f"pipeline_reserve:{session_id}"
    if _ledger_exists(key):
        return engine.pipeline_run_credits()

    sm = _get_session_metering(session_id)
    if sm and sm.get("pipeline_reserved"):
        return engine.pipeline_run_credits()

    amount = engine.pipeline_run_credits()
    balance = get_balance(user_id)
    if balance.available_credits < amount:
        raise InsufficientCreditsError(
            event="pipeline_run",
            required=amount,
            available=balance.available_credits,
        )

    new_available = balance.available_credits - amount
    new_reserved = balance.reserved_credits + amount
    _upsert_balance(user_id, available=new_available, reserved=new_reserved)
    _append_ledger(
        user_id=user_id,
        session_id=session_id,
        event_type="reserve",
        amount_credits=-amount,
        idempotency_key=key,
        metadata={"for": "pipeline_run"},
    )
    _upsert_session_metering(session_id, pipeline_reserved=True)
    return amount


def commit_pipeline_run(*, session_id: str) -> None:
    """Finalize a reserved pipeline charge after successful completion."""
    sm = _get_session_metering(session_id)
    if not sm or not sm.get("pipeline_reserved") or sm.get("pipeline_committed"):
        return

    row = get_session_row(session_id)
    if not row:
        return
    user_id = str(row["user_id"])
    key = f"pipeline_commit:{session_id}"
    if _ledger_exists(key):
        _upsert_session_metering(
            session_id, pipeline_committed=True, pipeline_reserved=False
        )
        return

    amount = engine.pipeline_run_credits()
    balance = get_balance(user_id)
    if balance.reserved_credits < amount:
        log.warning(
            "Pipeline commit for session %s: reserved %s < %s",
            session_id,
            balance.reserved_credits,
            amount,
        )
        amount = balance.reserved_credits

    new_reserved = balance.reserved_credits - amount
    _upsert_balance(user_id, available=balance.available_credits, reserved=new_reserved)
    _append_ledger(
        user_id=user_id,
        session_id=session_id,
        event_type="pipeline_run",
        amount_credits=Decimal("0"),
        idempotency_key=key,
        metadata={"committed_reserved": str(amount)},
    )
    _upsert_session_metering(
        session_id,
        pipeline_committed=True,
        pipeline_reserved=False,
    )


def release_pipeline_reserve(session_id: str) -> None:
    """Return reserved pipeline credits when the run fails or is cancelled."""
    sm = _get_session_metering(session_id)
    if not sm or not sm.get("pipeline_reserved") or sm.get("pipeline_committed"):
        return

    row = get_session_row(session_id)
    if not row:
        return
    user_id = str(row["user_id"])

    key = f"pipeline_release:{session_id}"
    if _ledger_exists(key):
        _upsert_session_metering(session_id, pipeline_reserved=False)
        return

    amount = engine.pipeline_run_credits()
    balance = get_balance(user_id)
    release = min(amount, balance.reserved_credits)
    new_available = balance.available_credits + release
    new_reserved = balance.reserved_credits - release
    _upsert_balance(user_id, available=new_available, reserved=new_reserved)
    _append_ledger(
        user_id=user_id,
        session_id=session_id,
        event_type="release",
        amount_credits=release,
        idempotency_key=key,
        metadata={"for": "pipeline_run"},
    )
    _upsert_session_metering(session_id, pipeline_reserved=False)


def debit_revision(*, user_id: str, session_id: str, round_num: int) -> Decimal:
    ensure_user_meter_account(user_id)
    key = f"revision:{session_id}:{round_num}"
    if _ledger_exists(key):
        return engine.revision_credits()

    amount = engine.revision_credits()
    balance = get_balance(user_id)
    if balance.available_credits < amount:
        raise InsufficientCreditsError(
            event="revision",
            required=amount,
            available=balance.available_credits,
        )

    new_available = balance.available_credits - amount
    _upsert_balance(user_id, available=new_available, reserved=balance.reserved_credits)
    _append_ledger(
        user_id=user_id,
        session_id=session_id,
        event_type="revision",
        amount_credits=-amount,
        idempotency_key=key,
        metadata={"round": round_num},
    )

    sm = _get_session_metering(session_id)
    rev_count = int((sm or {}).get("revision_count") or 0) + 1
    _upsert_session_metering(session_id, revision_count=rev_count)
    return amount


def refund_revision(*, user_id: str, session_id: str, round_num: int) -> None:
    key = f"revision_refund:{session_id}:{round_num}"
    if _ledger_exists(key):
        return

    debit_key = f"revision:{session_id}:{round_num}"
    if not _ledger_exists(debit_key):
        return

    amount = engine.revision_credits()
    balance = get_balance(user_id)
    _upsert_balance(
        user_id,
        available=balance.available_credits + amount,
        reserved=balance.reserved_credits,
    )
    _append_ledger(
        user_id=user_id,
        session_id=session_id,
        event_type="revision_refund",
        amount_credits=amount,
        idempotency_key=key,
        metadata={"round": round_num},
    )
