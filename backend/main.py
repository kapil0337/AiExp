"""Bloom Budget API. 🌸

All routes live under /api so the same app can serve the static frontend at /
locally and in Docker, while Vercel serves /public from its CDN and rewrites
/api/* into this ASGI app.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from contextlib import asynccontextmanager
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from . import __version__
from .ai import vibe_check
from .auth import (
    SESSION_COOKIE_NAME,
    create_session_cookie,
    get_current_user,
    get_current_user_optional,
    require_auth_configured,
    verify_google_id_token,
)
from .config import PUBLIC_DIR, get_settings
from .cycles import current_cycle, cycle_card_total, run_auto_settlements, settle_date_for
from .cycles import settle_now as cycles_settle_now
from .database import get_db, init_db
from .models import ZERO, Budget, CardCycleSettlement, CashHolding, Expense, Split, User
from .schemas import (
    AccountBalanceIn,
    AuthMe,
    BudgetIn,
    BudgetOut,
    CardCycleOut,
    CardSettlementOut,
    CashHoldingsIn,
    CashHoldingsOut,
    CategoryPoint,
    Dashboard,
    DayPoint,
    ExpenseIn,
    ExpenseOut,
    ExpenseUpdate,
    GoogleLoginIn,
    MethodBreakdown,
    MonthPoint,
    NicknameIn,
    SplitIn,
    SplitOut,
    SplitUpdate,
    Summary,
    UserOut,
    VibeCheck,
    money,
)

settings = get_settings()

CATEGORY_EMOJI = {
    "food": "🍜",
    "coffee": "☕",
    "groceries": "🛒",
    "shopping": "🛍️",
    "beauty": "💅",
    "travel": "🚕",
    "rent": "🏠",
    "bills": "🧾",
    "fun": "🎀",
    "health": "💊",
    "gifts": "🎁",
    "subscriptions": "📱",
    "other": "✨",
}

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Bloom Budget",
    description="A very pink expense tracker with a sassy NVIDIA-powered money coach.",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def dec(value: float | int | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ── budget helpers ──────────────────────────────────────────────────────────


def active_budget(db: Session, user: User) -> Budget:
    """The signed-in user's single active budget, created on first touch."""
    budget = db.scalar(
        select(Budget)
        .where(Budget.user_id == user.id, Budget.is_active.is_(True))
        .order_by(Budget.id.desc())
    )
    if budget is None:
        budget = Budget(
            user_id=user.id,
            name="My Budget",
            account_balance=ZERO,
            currency=settings.default_currency,
            is_active=True,
        )
        db.add(budget)
        db.commit()
        db.refresh(budget)
    return budget


def build_summary(db: Session, budget: Budget) -> Summary:
    run_auto_settlements(db, budget)

    today = dt.date.today()
    month_start = dt.date(today.year, today.month, 1)
    month_end = (
        dt.date(today.year + 1, 1, 1)
        if today.month == 12
        else dt.date(today.year, today.month + 1, 1)
    )

    totals = db.execute(
        select(
            func.coalesce(func.sum(Expense.cash_amount), 0),
            func.coalesce(func.sum(Expense.gpay_amount), 0),
            func.coalesce(func.sum(Expense.card_amount), 0),
            func.count(Expense.id),
        ).where(
            Expense.budget_id == budget.id,
            Expense.spent_on >= month_start,
            Expense.spent_on < month_end,
        )
    ).one()
    cash, gpay, card, count = totals

    spent = Decimal(str(cash)) + Decimal(str(gpay)) + Decimal(str(card))

    def split_sum(direction: str, settled: bool) -> Decimal:
        value = db.scalar(
            select(func.coalesce(func.sum(Split.amount), 0)).where(
                Split.budget_id == budget.id,
                Split.direction == direction,
                Split.is_settled.is_(settled),
            )
        )
        return Decimal(str(value or 0))

    owed_to_her = split_sum("they_owe", False)
    she_owes = split_sum("she_owes", False)
    recovered = split_sum("they_owe", True) - split_sum("she_owes", True)

    # Biggest single expense this month
    biggest = db.scalar(
        select(
            func.max(Expense.cash_amount + Expense.gpay_amount + Expense.card_amount)
        ).where(
            Expense.budget_id == budget.id,
            Expense.spent_on >= month_start,
            Expense.spent_on < month_end,
        )
    )

    # Top category by spend this month
    top_row = db.execute(
        select(
            Expense.category,
            func.sum(
                Expense.cash_amount + Expense.gpay_amount + Expense.card_amount
            ).label("t"),
        )
        .where(
            Expense.budget_id == budget.id,
            Expense.spent_on >= month_start,
            Expense.spent_on < month_end,
        )
        .group_by(Expense.category)
        .order_by(func.sum(
            Expense.cash_amount + Expense.gpay_amount + Expense.card_amount
        ).desc())
        .limit(1)
    ).first()

    avg = float(spent) / today.day if today.day else 0.0

    cycle_start, cycle_end = current_cycle(today)
    card_cycle = CardCycleOut(
        cycle_start=cycle_start,
        cycle_end=cycle_end,
        settle_date=settle_date_for(cycle_end),
        card_spent_so_far=money(cycle_card_total(db, budget.id, cycle_start, cycle_end)),
    )

    account_balance = Decimal(str(budget.account_balance or 0))

    return Summary(
        budget_id=budget.id,
        budget_name=budget.name,
        currency=budget.currency,
        account_balance=money(account_balance),
        spent_this_month=money(spent),
        month_label=month_start.strftime("%Y-%m"),
        by_method=MethodBreakdown(
            cash=money(cash), gpay=money(gpay), card=money(card)
        ),
        owed_to_her=money(owed_to_her),
        she_owes=money(she_owes),
        recovered=money(recovered),
        remaining_if_everyone_pays=money(account_balance + owed_to_her - she_owes),
        expense_count=int(count or 0),
        days_tracked=today.day,
        avg_per_day=round(avg, 2),
        biggest_expense=money(biggest),
        top_category=top_row[0] if top_row else None,
        card_cycle=card_cycle,
    )


# ── meta ────────────────────────────────────────────────────────────────────


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "version": __version__,
        "ai": "nvidia" if settings.ai_enabled else "offline",
    }


@app.get("/api/meta")
def meta() -> dict:
    return {
        "app_name": settings.app_name.strip() or "Bloom Budget",
        "ai_enabled": settings.ai_enabled,
        "google_client_id": settings.google_client_id,
        "categories": [
            {"key": k, "emoji": v, "label": k.capitalize()}
            for k, v in CATEGORY_EMOJI.items()
        ],
    }


# ── budget ──────────────────────────────────────────────────────────────────


@app.get("/api/budget", response_model=BudgetOut)
def read_budget(db: DB, user: CurrentUser) -> BudgetOut:
    b = active_budget(db, user)
    return BudgetOut(
        id=b.id,
        name=b.name,
        account_balance=money(b.account_balance),
        currency=b.currency,
        created_at=b.created_at,
    )


@app.put("/api/budget", response_model=Summary)
def set_budget(payload: BudgetIn, db: DB, user: CurrentUser) -> Summary:
    b = active_budget(db, user)
    b.name = payload.name.strip() or "My Budget"
    b.currency = payload.currency.strip().upper()[:8] or "INR"
    db.commit()
    db.refresh(b)
    return build_summary(db, b)


@app.put("/api/account-balance", response_model=Summary)
def set_account_balance(payload: AccountBalanceIn, db: DB, user: CurrentUser) -> Summary:
    b = active_budget(db, user)
    b.account_balance = dec(payload.balance)
    db.commit()
    db.refresh(b)
    return build_summary(db, b)


@app.post("/api/budget/reset", response_model=Summary)
def reset_budget(db: DB, user: CurrentUser) -> Summary:
    """Wipe expenses + splits. Balance, cash counts, and card-cycle history stay."""
    b = active_budget(db, user)
    db.query(Split).filter(Split.budget_id == b.id).delete(synchronize_session=False)
    db.query(Expense).filter(Expense.budget_id == b.id).delete(
        synchronize_session=False
    )
    db.commit()
    db.refresh(b)
    return build_summary(db, b)


# ── cash holdings ───────────────────────────────────────────────────────────


def _cash_total(h: CashHolding) -> Decimal:
    return Decimal(
        500 * h.note_500
        + 200 * h.note_200
        + 100 * h.note_100
        + 50 * h.note_50
        + 20 * h.note_20
        + 10 * h.note_10
    )


def active_cash_holding(db: Session, budget: Budget) -> CashHolding:
    holding = db.scalar(select(CashHolding).where(CashHolding.budget_id == budget.id))
    if holding is None:
        holding = CashHolding(budget_id=budget.id)
        db.add(holding)
        db.commit()
        db.refresh(holding)
    return holding


def _cash_out(h: CashHolding) -> CashHoldingsOut:
    return CashHoldingsOut(
        note_500=h.note_500,
        note_200=h.note_200,
        note_100=h.note_100,
        note_50=h.note_50,
        note_20=h.note_20,
        note_10=h.note_10,
        total=money(_cash_total(h)),
        updated_at=h.updated_at,
    )


@app.get("/api/cash-holdings", response_model=CashHoldingsOut)
def read_cash_holdings(db: DB, user: CurrentUser) -> CashHoldingsOut:
    b = active_budget(db, user)
    return _cash_out(active_cash_holding(db, b))


@app.put("/api/cash-holdings", response_model=CashHoldingsOut)
def set_cash_holdings(payload: CashHoldingsIn, db: DB, user: CurrentUser) -> CashHoldingsOut:
    b = active_budget(db, user)
    h = active_cash_holding(db, b)
    for field, value in payload.model_dump().items():
        setattr(h, field, value)
    db.commit()
    db.refresh(h)
    return _cash_out(h)


# ── credit card cycle ───────────────────────────────────────────────────────


@app.post("/api/card-cycle/settle-now")
def settle_card_cycle_now(db: DB, user: CurrentUser) -> dict:
    b = active_budget(db, user)
    row = cycles_settle_now(db, b)
    return {
        "settled": row is not None,
        "settlement": CardSettlementOut.model_validate(row, from_attributes=True)
        if row
        else None,
    }


@app.get("/api/card-cycle/history", response_model=list[CardSettlementOut])
def card_cycle_history(db: DB, user: CurrentUser) -> list[CardSettlementOut]:
    b = active_budget(db, user)
    rows = db.scalars(
        select(CardCycleSettlement)
        .where(CardCycleSettlement.budget_id == b.id)
        .order_by(CardCycleSettlement.cycle_end.desc())
    ).all()
    return [CardSettlementOut.model_validate(r, from_attributes=True) for r in rows]


# ── expenses ────────────────────────────────────────────────────────────────


@app.get("/api/expenses", response_model=list[ExpenseOut])
def list_expenses(
    db: DB,
    user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=120),
    method: str | None = Query(default=None, pattern="^(cash|gpay|card)$"),
    category: str | None = Query(default=None, max_length=40),
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
) -> list[ExpenseOut]:
    b = active_budget(db, user)
    stmt = select(Expense).where(Expense.budget_id == b.id)

    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Expense.name.ilike(like))
    if category:
        stmt = stmt.where(Expense.category == category)
    if method:
        column = {
            "cash": Expense.cash_amount,
            "gpay": Expense.gpay_amount,
            "card": Expense.card_amount,
        }[method]
        stmt = stmt.where(column > 0)
    if month:
        year, mon = (int(part) for part in month.split("-"))
        start = dt.date(year, mon, 1)
        end = dt.date(year + 1, 1, 1) if mon == 12 else dt.date(year, mon + 1, 1)
        stmt = stmt.where(Expense.spent_on >= start, Expense.spent_on < end)

    stmt = (
        stmt.order_by(Expense.spent_on.desc(), Expense.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [ExpenseOut.from_model(e) for e in db.scalars(stmt).all()]


@app.post("/api/expenses", response_model=ExpenseOut, status_code=201)
def create_expense(payload: ExpenseIn, db: DB, user: CurrentUser) -> ExpenseOut:
    if payload.total() <= 0:
        raise HTTPException(
            status_code=422,
            detail="Pick at least one payment method and an amount above zero 💸",
        )

    b = active_budget(db, user)
    expense = Expense(
        budget_id=b.id,
        user_id=user.id,
        name=payload.name,
        emoji=payload.emoji or CATEGORY_EMOJI.get(payload.category, "🌸"),
        category=payload.category,
        note=payload.note,
        spent_on=payload.spent_on or dt.date.today(),
        cash_amount=dec(payload.cash_amount),
        gpay_amount=dec(payload.gpay_amount),
        card_amount=dec(payload.card_amount),
    )
    db.add(expense)
    db.flush()

    if payload.split_with and payload.split_amount and payload.split_amount > 0:
        if payload.split_amount > payload.total():
            raise HTTPException(
                status_code=422,
                detail="The split can't be bigger than the expense itself 🙈",
            )
        db.add(
            Split(
                budget_id=b.id,
                user_id=user.id,
                expense_id=expense.id,
                person=payload.split_with.strip(),
                amount=dec(payload.split_amount),
                direction="they_owe",
                note=f"from {expense.name}",
            )
        )

    db.commit()
    db.refresh(expense)
    return ExpenseOut.from_model(expense)


@app.patch("/api/expenses/{expense_id}", response_model=ExpenseOut)
def update_expense(
    expense_id: int, payload: ExpenseUpdate, db: DB, user: CurrentUser
) -> ExpenseOut:
    b = active_budget(db, user)
    e = db.scalar(
        select(Expense).where(Expense.id == expense_id, Expense.budget_id == b.id)
    )
    if e is None:
        raise HTTPException(status_code=404, detail="Expense not found 🔍")

    data = payload.model_dump(exclude_unset=True)
    for field in ("cash_amount", "gpay_amount", "card_amount"):
        if field in data and data[field] is not None:
            setattr(e, field, dec(data.pop(field)))
        else:
            data.pop(field, None)
    for field, value in data.items():
        if value is not None:
            setattr(e, field, value)

    if e.total <= 0:
        db.rollback()
        raise HTTPException(status_code=422, detail="An expense needs an amount 💸")

    db.commit()
    db.refresh(e)
    return ExpenseOut.from_model(e)


@app.delete("/api/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: int, db: DB, user: CurrentUser) -> Response:
    b = active_budget(db, user)
    e = db.scalar(
        select(Expense).where(Expense.id == expense_id, Expense.budget_id == b.id)
    )
    if e is None:
        raise HTTPException(status_code=404, detail="Expense not found 🔍")
    db.delete(e)
    db.commit()
    return Response(status_code=204)


# ── splits ──────────────────────────────────────────────────────────────────


@app.get("/api/splits", response_model=list[SplitOut])
def list_splits(
    db: DB,
    user: CurrentUser,
    settled: bool | None = Query(default=None),
    direction: str | None = Query(default=None, pattern="^(they_owe|she_owes)$"),
) -> list[SplitOut]:
    b = active_budget(db, user)
    stmt = (
        select(Split)
        .where(Split.budget_id == b.id)
        .options(selectinload(Split.expense))
    )
    if settled is not None:
        stmt = stmt.where(Split.is_settled.is_(settled))
    if direction:
        stmt = stmt.where(Split.direction == direction)
    stmt = stmt.order_by(Split.is_settled.asc(), Split.id.desc())
    return [SplitOut.from_model(s) for s in db.scalars(stmt).all()]


@app.post("/api/splits", response_model=SplitOut, status_code=201)
def create_split(payload: SplitIn, db: DB, user: CurrentUser) -> SplitOut:
    b = active_budget(db, user)
    if payload.expense_id is not None:
        exists = db.scalar(
            select(Expense.id).where(
                Expense.id == payload.expense_id, Expense.budget_id == b.id
            )
        )
        if exists is None:
            raise HTTPException(status_code=404, detail="That expense doesn't exist 🔍")

    s = Split(
        budget_id=b.id,
        user_id=user.id,
        expense_id=payload.expense_id,
        person=payload.person,
        emoji=payload.emoji,
        amount=dec(payload.amount),
        direction=payload.direction,
        note=payload.note,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return SplitOut.from_model(s)


@app.patch("/api/splits/{split_id}", response_model=SplitOut)
def update_split(
    split_id: int, payload: SplitUpdate, db: DB, user: CurrentUser
) -> SplitOut:
    b = active_budget(db, user)
    s = db.scalar(select(Split).where(Split.id == split_id, Split.budget_id == b.id))
    if s is None:
        raise HTTPException(status_code=404, detail="Split not found 🔍")

    data = payload.model_dump(exclude_unset=True)
    if "amount" in data and data["amount"] is not None:
        s.amount = dec(data.pop("amount"))
    else:
        data.pop("amount", None)

    if "is_settled" in data and data["is_settled"] is not None:
        s.is_settled = data.pop("is_settled")
        s.settled_at = dt.datetime.now(dt.UTC) if s.is_settled else None

    for field, value in data.items():
        if value is not None:
            setattr(s, field, value)

    db.commit()
    db.refresh(s)
    return SplitOut.from_model(s)


@app.delete("/api/splits/{split_id}", status_code=204)
def delete_split(split_id: int, db: DB, user: CurrentUser) -> Response:
    b = active_budget(db, user)
    s = db.scalar(select(Split).where(Split.id == split_id, Split.budget_id == b.id))
    if s is None:
        raise HTTPException(status_code=404, detail="Split not found 🔍")
    db.delete(s)
    db.commit()
    return Response(status_code=204)


# ── dashboard ───────────────────────────────────────────────────────────────


@app.get("/api/dashboard", response_model=Dashboard)
def dashboard(
    db: DB, user: CurrentUser, days: int = Query(default=14, ge=3, le=90)
) -> Dashboard:
    b = active_budget(db, user)
    summary = build_summary(db, b)

    today = dt.date.today()
    start = today - dt.timedelta(days=days - 1)

    rows = db.execute(
        select(
            Expense.spent_on,
            func.coalesce(func.sum(Expense.cash_amount), 0),
            func.coalesce(func.sum(Expense.gpay_amount), 0),
            func.coalesce(func.sum(Expense.card_amount), 0),
        )
        .where(Expense.budget_id == b.id, Expense.spent_on >= start)
        .group_by(Expense.spent_on)
    ).all()

    buckets: dict[dt.date, tuple[float, float, float]] = {
        r[0]: (float(r[1]), float(r[2]), float(r[3])) for r in rows
    }
    daily = []
    for i in range(days):
        day = start + dt.timedelta(days=i)
        cash, gpay, card = buckets.get(day, (0.0, 0.0, 0.0))
        daily.append(
            DayPoint(
                date=day,
                cash=round(cash, 2),
                gpay=round(gpay, 2),
                card=round(card, 2),
                total=round(cash + gpay + card, 2),
            )
        )

    month_start = dt.date(today.year, today.month, 1)
    month_end = (
        dt.date(today.year + 1, 1, 1)
        if today.month == 12
        else dt.date(today.year, today.month + 1, 1)
    )

    cat_rows = db.execute(
        select(
            Expense.category,
            func.sum(
                Expense.cash_amount + Expense.gpay_amount + Expense.card_amount
            ).label("t"),
            func.count(Expense.id),
        )
        .where(
            Expense.budget_id == b.id,
            Expense.spent_on >= month_start,
            Expense.spent_on < month_end,
        )
        .group_by(Expense.category)
        .order_by(func.sum(
            Expense.cash_amount + Expense.gpay_amount + Expense.card_amount
        ).desc())
    ).all()

    categories = [
        CategoryPoint(
            category=row[0],
            emoji=CATEGORY_EMOJI.get(row[0], "✨"),
            total=money(row[1]),
            count=int(row[2]),
        )
        for row in cat_rows
    ]

    months = []
    cursor = month_start
    for _ in range(12):
        months.append(cursor)
        cursor = (
            dt.date(cursor.year - 1, 12, 1)
            if cursor.month == 1
            else dt.date(cursor.year, cursor.month - 1, 1)
        )
    months.reverse()
    earliest = months[0]

    month_rows = db.execute(
        select(
            Expense.spent_on,
            Expense.cash_amount,
            Expense.gpay_amount,
            Expense.card_amount,
        ).where(Expense.budget_id == b.id, Expense.spent_on >= earliest)
    ).all()

    month_buckets: dict[tuple[int, int], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for spent_on, c, g, cd in month_rows:
        bucket = month_buckets[(spent_on.year, spent_on.month)]
        bucket[0] += float(c)
        bucket[1] += float(g)
        bucket[2] += float(cd)

    monthly = []
    for m in months:
        c, g, cd = month_buckets.get((m.year, m.month), [0.0, 0.0, 0.0])
        monthly.append(
            MonthPoint(
                month=m.strftime("%Y-%m"),
                cash=round(c, 2),
                gpay=round(g, 2),
                card=round(cd, 2),
                total=round(c + g + cd, 2),
            )
        )

    recent_rows = db.scalars(
        select(Expense)
        .where(Expense.budget_id == b.id)
        .order_by(Expense.spent_on.desc(), Expense.id.desc())
        .limit(6)
    ).all()

    return Dashboard(
        summary=summary,
        daily=daily,
        monthly=monthly,
        categories=categories,
        recent=[ExpenseOut.from_model(e) for e in recent_rows],
    )


@app.get("/api/summary", response_model=Summary)
def summary_only(db: DB, user: CurrentUser) -> Summary:
    return build_summary(db, active_budget(db, user))


# ── the sassy coach ─────────────────────────────────────────────────────────


@app.post("/api/vibe-check", response_model=VibeCheck)
async def ai_vibe_check(db: DB, user: CurrentUser) -> VibeCheck:
    summary = build_summary(db, active_budget(db, user))
    return await vibe_check(summary, nickname=user.nickname or None)


# ── who groups spend per person (used by the splits screen) ─────────────────


@app.get("/api/splits/people")
def split_people(db: DB, user: CurrentUser) -> list[dict]:
    b = active_budget(db, user)
    rows = db.scalars(select(Split).where(Split.budget_id == b.id)).all()
    per: dict[str, dict] = defaultdict(
        lambda: {"person": "", "emoji": "💌", "pending": 0.0, "settled": 0.0, "net": 0.0}
    )
    for s in rows:
        entry = per[s.person.lower()]
        entry["person"] = s.person
        entry["emoji"] = s.emoji
        sign = 1 if s.direction == "they_owe" else -1
        amount = float(s.amount or 0) * sign
        if s.is_settled:
            entry["settled"] += amount
        else:
            entry["pending"] += amount
        entry["net"] += amount
    out = list(per.values())
    out.sort(key=lambda r: abs(r["pending"]), reverse=True)
    for r in out:
        r["pending"] = round(r["pending"], 2)
        r["settled"] = round(r["settled"], 2)
        r["net"] = round(r["net"], 2)
    return out


# ── auth ────────────────────────────────────────────────────────────────────


@app.post("/api/auth/google", response_model=UserOut)
def login_with_google(payload: GoogleLoginIn, db: DB, response: Response) -> UserOut:
    require_auth_configured()
    claims = verify_google_id_token(payload.credential)

    email = claims["email"].lower()
    if email not in settings.allowed_emails_set:
        raise HTTPException(
            status_code=403, detail="This Google account isn't on the guest list ✋"
        )

    user = db.scalar(select(User).where(User.google_sub == claims["sub"]))
    if user is None:
        user = User(google_sub=claims["sub"], email=email)
        db.add(user)
    user.email = email
    user.name = claims.get("name", "")
    user.picture = claims.get("picture", "")
    user.last_login_at = dt.datetime.now(dt.UTC)
    db.commit()
    db.refresh(user)

    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_cookie(user.id),
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        # Unchecked "keep me signed in" -> a browser session cookie (no
        # max_age) that's gone once the browser closes, instead of persisting
        # for the full session_max_age_days.
        max_age=settings.session_max_age_days * 86400 if payload.remember else None,
    )
    return UserOut.from_model(user)


@app.post("/api/auth/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"ok": True}


@app.get("/api/auth/me", response_model=AuthMe)
def auth_me(request: Request, db: DB) -> AuthMe:
    user = get_current_user_optional(request, db)
    return AuthMe(
        authenticated=user is not None,
        user=UserOut.from_model(user) if user else None,
    )


@app.put("/api/auth/nickname", response_model=UserOut)
def set_nickname(payload: NicknameIn, db: DB, user: CurrentUser) -> UserOut:
    user.nickname = payload.nickname
    db.commit()
    db.refresh(user)
    return UserOut.from_model(user)


# ── errors ──────────────────────────────────────────────────────────────────


@app.exception_handler(ValueError)
async def value_error_handler(_request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


# ── static frontend (local + docker; Vercel serves /public from its CDN) ────

if PUBLIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="static")
