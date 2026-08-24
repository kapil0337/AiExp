"""Request/response shapes. Money crosses the wire as float, rounded to 2dp."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

METHODS = ("cash", "gpay", "card")
DIRECTIONS = ("they_owe", "she_owes")


def money(value: Decimal | float | None) -> float:
    return round(float(value or 0), 2)


# ── Budget ──────────────────────────────────────────────────────────────────


class BudgetIn(BaseModel):
    name: str = Field(default="My Budget", max_length=80)
    total_amount: float = Field(ge=0, le=1_000_000_000)
    currency: str = Field(default="INR", max_length=8)


class BudgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    total_amount: float
    currency: str
    created_at: dt.datetime


# ── Expense ─────────────────────────────────────────────────────────────────


class ExpenseIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    emoji: str = Field(default="🌸", max_length=8)
    category: str = Field(default="other", max_length=40)
    note: str = Field(default="", max_length=300)
    spent_on: dt.date | None = None

    cash_amount: float = Field(default=0, ge=0, le=1_000_000_000)
    gpay_amount: float = Field(default=0, ge=0, le=1_000_000_000)
    card_amount: float = Field(default=0, ge=0, le=1_000_000_000)

    # Optional one-shot split created alongside the expense.
    split_with: str | None = Field(default=None, max_length=80)
    split_amount: float | None = Field(default=None, ge=0, le=1_000_000_000)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Give it a name, bestie ✨")
        return v

    def total(self) -> float:
        return round(self.cash_amount + self.gpay_amount + self.card_amount, 2)


class ExpenseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    emoji: str | None = Field(default=None, max_length=8)
    category: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=300)
    spent_on: dt.date | None = None
    cash_amount: float | None = Field(default=None, ge=0, le=1_000_000_000)
    gpay_amount: float | None = Field(default=None, ge=0, le=1_000_000_000)
    card_amount: float | None = Field(default=None, ge=0, le=1_000_000_000)


class ExpenseOut(BaseModel):
    id: int
    name: str
    emoji: str
    category: str
    note: str
    spent_on: dt.date
    cash_amount: float
    gpay_amount: float
    card_amount: float
    total: float
    methods: list[str]
    created_at: dt.datetime

    @classmethod
    def from_model(cls, e) -> ExpenseOut:
        return cls(
            id=e.id,
            name=e.name,
            emoji=e.emoji,
            category=e.category,
            note=e.note or "",
            spent_on=e.spent_on,
            cash_amount=money(e.cash_amount),
            gpay_amount=money(e.gpay_amount),
            card_amount=money(e.card_amount),
            total=money(e.total),
            methods=e.methods,
            created_at=e.created_at,
        )


# ── Split ───────────────────────────────────────────────────────────────────


class SplitIn(BaseModel):
    person: str = Field(min_length=1, max_length=80)
    emoji: str = Field(default="💌", max_length=8)
    amount: float = Field(gt=0, le=1_000_000_000)
    direction: str = Field(default="they_owe")
    note: str = Field(default="", max_length=300)
    expense_id: int | None = None

    @field_validator("direction")
    @classmethod
    def _dir(cls, v: str) -> str:
        if v not in DIRECTIONS:
            raise ValueError(f"direction must be one of {DIRECTIONS}")
        return v

    @field_validator("person")
    @classmethod
    def _person(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Who is it though? 👀")
        return v


class SplitUpdate(BaseModel):
    person: str | None = Field(default=None, min_length=1, max_length=80)
    emoji: str | None = Field(default=None, max_length=8)
    amount: float | None = Field(default=None, gt=0, le=1_000_000_000)
    direction: str | None = None
    note: str | None = Field(default=None, max_length=300)
    is_settled: bool | None = None

    @field_validator("direction")
    @classmethod
    def _dir(cls, v: str | None) -> str | None:
        if v is not None and v not in DIRECTIONS:
            raise ValueError(f"direction must be one of {DIRECTIONS}")
        return v


class SplitOut(BaseModel):
    id: int
    person: str
    emoji: str
    amount: float
    direction: str
    note: str
    is_settled: bool
    settled_at: dt.datetime | None
    expense_id: int | None
    expense_name: str | None
    created_at: dt.datetime

    @classmethod
    def from_model(cls, s) -> SplitOut:
        return cls(
            id=s.id,
            person=s.person,
            emoji=s.emoji,
            amount=money(s.amount),
            direction=s.direction,
            note=s.note or "",
            is_settled=s.is_settled,
            settled_at=s.settled_at,
            expense_id=s.expense_id,
            expense_name=s.expense.name if s.expense else None,
            created_at=s.created_at,
        )


# ── Dashboard ───────────────────────────────────────────────────────────────


class MethodBreakdown(BaseModel):
    cash: float
    gpay: float
    card: float


class Summary(BaseModel):
    budget_id: int
    budget_name: str
    currency: str
    total_budget: float
    total_spent: float
    remaining: float
    percent_used: float
    by_method: MethodBreakdown
    owed_to_her: float
    she_owes: float
    recovered: float
    remaining_if_everyone_pays: float
    expense_count: int
    days_tracked: int
    avg_per_day: float
    biggest_expense: float
    top_category: str | None
    status: str  # comfy | watchful | tight | overboard


class DayPoint(BaseModel):
    date: dt.date
    cash: float
    gpay: float
    card: float
    total: float


class CategoryPoint(BaseModel):
    category: str
    emoji: str
    total: float
    count: int


class Dashboard(BaseModel):
    summary: Summary
    daily: list[DayPoint]
    categories: list[CategoryPoint]
    recent: list[ExpenseOut]


# ── AI ──────────────────────────────────────────────────────────────────────


class VibeCheck(BaseModel):
    message: str
    mood: str
    emoji: str
    source: str  # nvidia | offline


# ── Auth ────────────────────────────────────────────────────────────────────


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    nickname: str
    picture: str
    created_at: dt.datetime

    @classmethod
    def from_model(cls, u) -> UserOut:
        return cls(
            id=u.id,
            email=u.email,
            name=u.name or "",
            nickname=u.nickname or "",
            picture=u.picture or "",
            created_at=u.created_at,
        )


class GoogleLoginIn(BaseModel):
    credential: str = Field(min_length=1)
    remember: bool = True


class AuthMe(BaseModel):
    authenticated: bool
    user: UserOut | None = None


class NicknameIn(BaseModel):
    nickname: str = Field(min_length=1, max_length=40)

    @field_validator("nickname")
    @classmethod
    def _strip_nickname(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Give Bloomie something to call you 🥺")
        return v
