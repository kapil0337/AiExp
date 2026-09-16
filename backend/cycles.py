"""Credit card billing cycle math + lazy settlement.

Cycle runs the 8th of one month to the 8th of the next. The prior cycle's
card spend is auto-deducted from the account balance once its settle date (the
26th of the month the cycle ended in) has passed. There is no scheduler/cron
in this app — and none would survive a serverless (Vercel) deploy anyway — so
settlement is lazy: `run_auto_settlements` runs at the top of every summary
read and catches up on anything due, however late the user opens the app.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import ZERO, Budget, CardCycleSettlement, Expense

CYCLE_DAY = 8
SETTLE_DAY = 26


def _add_months(d: dt.date, months: int) -> dt.date:
    m = d.month - 1 + months
    y = d.year + m // 12
    return dt.date(y, m % 12 + 1, CYCLE_DAY)


def cycle_start_for(reference: dt.date) -> dt.date:
    """The 8th that opens the cycle containing `reference`."""
    if reference.day >= CYCLE_DAY:
        return dt.date(reference.year, reference.month, CYCLE_DAY)
    return _add_months(dt.date(reference.year, reference.month, CYCLE_DAY), -1)


def current_cycle(today: dt.date) -> tuple[dt.date, dt.date]:
    start = cycle_start_for(today)
    return start, _add_months(start, 1)


def settle_date_for(cycle_end: dt.date) -> dt.date:
    return dt.date(cycle_end.year, cycle_end.month, SETTLE_DAY)


def cycle_card_total(db: Session, budget_id: int, start: dt.date, end: dt.date) -> Decimal:
    value = db.scalar(
        select(func.coalesce(func.sum(Expense.card_amount), 0)).where(
            Expense.budget_id == budget_id,
            Expense.spent_on >= start,
            Expense.spent_on < end,
        )
    )
    return Decimal(str(value or 0))


def _next_unsettled_cycle(db: Session, budget: Budget) -> tuple[dt.date, dt.date] | None:
    last = db.scalar(
        select(CardCycleSettlement)
        .where(CardCycleSettlement.budget_id == budget.id)
        .order_by(CardCycleSettlement.cycle_end.desc())
    )
    if last is not None:
        start = last.cycle_end
    else:
        first = db.scalar(
            select(func.min(Expense.spent_on)).where(Expense.budget_id == budget.id)
        )
        if first is None:
            return None
        start = cycle_start_for(first)
    return start, _add_months(start, 1)


def _settle(
    db: Session, budget: Budget, start: dt.date, end: dt.date, source: str
) -> CardCycleSettlement | None:
    amount = cycle_card_total(db, budget.id, start, end)
    row = CardCycleSettlement(
        budget_id=budget.id, cycle_start=start, cycle_end=end, amount=amount, source=source
    )
    budget.account_balance = (budget.account_balance or ZERO) - amount
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        db.refresh(budget)
        return None
    db.refresh(row)
    return row


def run_auto_settlements(
    db: Session, budget: Budget, today: dt.date | None = None
) -> list[CardCycleSettlement]:
    today = today or dt.date.today()
    settled = []
    while True:
        nxt = _next_unsettled_cycle(db, budget)
        if nxt is None:
            break
        start, end = nxt
        if settle_date_for(end) > today:
            break
        row = _settle(db, budget, start, end, source="auto")
        if row is None:
            break
        settled.append(row)
    return settled


def settle_now(
    db: Session, budget: Budget, today: dt.date | None = None
) -> CardCycleSettlement | None:
    """Manual override: settle the oldest completed-but-not-yet-due cycle
    immediately, skipping the wait for the 26th. Never touches the cycle
    still in progress, so the 8th-to-8th grid never shifts.
    """
    today = today or dt.date.today()
    nxt = _next_unsettled_cycle(db, budget)
    if nxt is None:
        return None
    start, end = nxt
    if end > today:
        return None
    return _settle(db, budget, start, end, source="manual")
