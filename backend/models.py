"""ORM models.

Money is stored as Numeric(12, 2) everywhere — never float — and only converted
to float at the API boundary.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

MONEY = Numeric(12, 2)
ZERO = Decimal("0.00")


class User(Base):
    """A Google account allowed to sign in."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), default="")
    # Self-chosen, distinct from `name` (Google's real name) — this is what
    # Bloomie calls the user. Empty until set on first login.
    nickname: Mapped[str] = mapped_column(String(40), default="")
    picture: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_login_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    budgets: Mapped[list[Budget]] = relationship(back_populates="user")


class Budget(Base):
    """The pot of money. One row is active per user at a time."""

    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80), default="My Budget")
    account_balance: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="budgets")
    expenses: Mapped[list[Expense]] = relationship(
        back_populates="budget", cascade="all, delete-orphan"
    )
    splits: Mapped[list[Split]] = relationship(
        back_populates="budget", cascade="all, delete-orphan"
    )


class Expense(Base):
    """One thing she bought.

    A single purchase can be paid partly in cash, partly GPay, partly card —
    hence three amount columns rather than one amount + one method.
    """

    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(
        ForeignKey("budgets.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    name: Mapped[str] = mapped_column(String(120))
    emoji: Mapped[str] = mapped_column(String(8), default="🌸")
    category: Mapped[str] = mapped_column(String(40), default="other", index=True)
    note: Mapped[str] = mapped_column(String(300), default="")
    spent_on: Mapped[dt.date] = mapped_column(Date, index=True)

    cash_amount: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    gpay_amount: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    card_amount: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    budget: Mapped[Budget] = relationship(back_populates="expenses")
    splits: Mapped[list[Split]] = relationship(
        back_populates="expense", cascade="all, delete-orphan"
    )

    @property
    def total(self) -> Decimal:
        return (
            (self.cash_amount or ZERO)
            + (self.gpay_amount or ZERO)
            + (self.card_amount or ZERO)
        )

    @property
    def methods(self) -> list[str]:
        used = []
        if (self.cash_amount or ZERO) > 0:
            used.append("cash")
        if (self.gpay_amount or ZERO) > 0:
            used.append("gpay")
        if (self.card_amount or ZERO) > 0:
            used.append("card")
        return used


Index("ix_expenses_budget_date", Expense.budget_id, Expense.spent_on)


class Split(Base):
    """Money owed in either direction.

    direction = 'they_owe'  -> someone owes her (she fronted the cash)
    direction = 'she_owes'  -> she owes someone
    """

    __tablename__ = "splits"

    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(
        ForeignKey("budgets.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expense_id: Mapped[int | None] = mapped_column(
        ForeignKey("expenses.id", ondelete="CASCADE"), nullable=True, index=True
    )

    person: Mapped[str] = mapped_column(String(80))
    emoji: Mapped[str] = mapped_column(String(8), default="💌")
    amount: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    direction: Mapped[str] = mapped_column(String(16), default="they_owe", index=True)
    note: Mapped[str] = mapped_column(String(300), default="")

    is_settled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    settled_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    budget: Mapped[Budget] = relationship(back_populates="splits")
    expense: Mapped[Expense | None] = relationship(back_populates="splits")


class CashHolding(Base):
    """Physical cash counted by INR note denomination. Informational only —
    never summed into `Budget.account_balance`.
    """

    __tablename__ = "cash_holdings"

    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(
        ForeignKey("budgets.id", ondelete="CASCADE"), unique=True, index=True
    )
    note_500: Mapped[int] = mapped_column(default=0)
    note_200: Mapped[int] = mapped_column(default=0)
    note_100: Mapped[int] = mapped_column(default=0)
    note_50: Mapped[int] = mapped_column(default=0)
    note_20: Mapped[int] = mapped_column(default=0)
    note_10: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CardCycleSettlement(Base):
    """One row per settled 8th-to-8th credit card cycle.

    Doubles as the idempotency guard for lazy auto-settlement: the unique
    index on (budget_id, cycle_start, cycle_end) means two concurrent requests
    racing to settle the same cycle can't both deduct — the loser's insert
    fails and it backs off instead of double-charging the balance.
    """

    __tablename__ = "card_cycle_settlements"

    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(
        ForeignKey("budgets.id", ondelete="CASCADE"), index=True
    )
    cycle_start: Mapped[dt.date] = mapped_column(Date)
    cycle_end: Mapped[dt.date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(MONEY, default=ZERO)
    source: Mapped[str] = mapped_column(String(8), default="auto")  # auto | manual
    settled_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


Index(
    "ix_card_cycle_unique",
    CardCycleSettlement.budget_id,
    CardCycleSettlement.cycle_start,
    CardCycleSettlement.cycle_end,
    unique=True,
)
