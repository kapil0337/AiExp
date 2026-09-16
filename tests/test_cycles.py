"""Unit tests for the 8th-to-8th credit card cycle math and lazy settlement,
exercised directly against `backend.cycles` (not through the API) so `today`
can be pinned deterministically.
"""

import datetime as dt
from decimal import Decimal

from backend import cycles
from backend.models import CardCycleSettlement, Expense


def add_expense(db_session, budget, spent_on, card_amount=0):
    e = Expense(
        budget_id=budget.id,
        user_id=budget.user_id,
        name="test",
        category="other",
        spent_on=spent_on,
        card_amount=Decimal(str(card_amount)),
    )
    db_session.add(e)
    db_session.commit()
    return e


def test_cycle_start_for_boundaries():
    assert cycles.cycle_start_for(dt.date(2026, 8, 8)) == dt.date(2026, 8, 8)
    assert cycles.cycle_start_for(dt.date(2026, 8, 7)) == dt.date(2026, 7, 8)
    assert cycles.cycle_start_for(dt.date(2026, 8, 9)) == dt.date(2026, 8, 8)


def test_current_cycle_and_settle_date():
    start, end = cycles.current_cycle(dt.date(2026, 8, 20))
    assert (start, end) == (dt.date(2026, 8, 8), dt.date(2026, 9, 8))
    assert cycles.settle_date_for(end) == dt.date(2026, 9, 26)


def test_no_expenses_ever_means_nothing_to_settle(db_session, budget):
    settled = cycles.run_auto_settlements(db_session, budget, today=dt.date(2026, 12, 1))
    assert settled == []
    assert budget.account_balance == Decimal("0.00")


def test_run_auto_settlements_is_idempotent(db_session, budget):
    budget.account_balance = Decimal("1000.00")
    db_session.commit()
    add_expense(db_session, budget, dt.date(2026, 1, 15), card_amount=200)

    today = dt.date(2026, 2, 26)  # settle date for the Jan8-Feb8 cycle
    first = cycles.run_auto_settlements(db_session, budget, today=today)
    assert len(first) == 1
    assert first[0].amount == Decimal("200.00")
    db_session.refresh(budget)
    assert budget.account_balance == Decimal("800.00")

    second = cycles.run_auto_settlements(db_session, budget, today=today)
    assert second == []
    db_session.refresh(budget)
    assert budget.account_balance == Decimal("800.00")  # not deducted twice

    rows = db_session.query(CardCycleSettlement).filter_by(budget_id=budget.id).all()
    assert len(rows) == 1


def test_run_auto_settlements_catches_up_multiple_cycles(db_session, budget):
    budget.account_balance = Decimal("1000.00")
    db_session.commit()
    add_expense(db_session, budget, dt.date(2026, 1, 15), card_amount=100)  # cycle Jan8-Feb8
    add_expense(db_session, budget, dt.date(2026, 3, 1), card_amount=50)  # cycle Feb8-Mar8

    # far enough that several cycles (incl. a zero-card one) are all overdue
    settled = cycles.run_auto_settlements(db_session, budget, today=dt.date(2026, 6, 1))
    assert len(settled) >= 3
    db_session.refresh(budget)
    assert budget.account_balance == Decimal("850.00")  # 1000 - 100 - 50 - 0...


def test_settle_now_skips_still_open_cycle(db_session, budget):
    add_expense(db_session, budget, dt.date(2026, 8, 20), card_amount=300)
    result = cycles.settle_now(db_session, budget, today=dt.date(2026, 8, 25))
    assert result is None
    db_session.refresh(budget)
    assert budget.account_balance == Decimal("0.00")


def test_settle_now_settles_a_completed_cycle_early(db_session, budget):
    budget.account_balance = Decimal("500.00")
    db_session.commit()
    add_expense(db_session, budget, dt.date(2026, 8, 15), card_amount=300)  # cycle ends Sep 8

    # cycle has ended (today > Sep 8) but its auto-settle date (Sep 26) hasn't arrived
    result = cycles.settle_now(db_session, budget, today=dt.date(2026, 9, 10))
    assert result is not None
    assert result.amount == Decimal("300.00")
    assert result.source == "manual"
    db_session.refresh(budget)
    assert budget.account_balance == Decimal("200.00")
