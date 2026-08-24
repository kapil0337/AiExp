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
from .database import get_db, init_db
from .models import ZERO, Budget, Expense, Split, User
from .schemas import (
    AuthMe,
    BudgetIn,
    BudgetOut,
    CategoryPoint,
    Dashboard,
    DayPoint,
    ExpenseIn,
    ExpenseOut,
    ExpenseUpdate,
    GoogleLoginIn,
    MethodBreakdown,
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
            total_amount=ZERO,
            currency=settings.default_currency,
            is_active=True,
        )
        db.add(budget)
        db.commit()
        db.refresh(budget)
    return budget


def build_summary(db: Session, budget: Budget) -> Summary:
    totals = db.execute(
        select(
            func.coalesce(func.sum(Expense.cash_amount), 0),
            func.coalesce(func.sum(Expense.gpay_amount), 0),
            func.coalesce(func.sum(Expense.card_amount), 0),
            func.count(Expense.id),
            func.min(Expense.spent_on),
            func.max(Expense.spent_on),
        ).where(Expense.budget_id == budget.id)
    ).one()
    cash, gpay, card, count, first_day, last_day = totals

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

    total_budget = Decimal(str(budget.total_amount or 0))
    remaining = total_budget - spent + recovered
    percent = float(spent / total_budget * 100) if total_budget > 0 else 0.0

    if total_budget <= 0:
        status = "comfy"
    elif percent > 100:
        status = "overboard"
    elif percent >= 85:
        status = "tight"
    elif percent >= 50:
        status = "watchful"
    else:
        status = "comfy"

    # Biggest single expense
    biggest = db.scalar(
        select(
            func.max(Expense.cash_amount + Expense.gpay_amount + Expense.card_amount)
        ).where(Expense.budget_id == budget.id)
    )

    # Top category by spend
    top_row = db.execute(
        select(
            Expense.category,
            func.sum(
                Expense.cash_amount + Expense.gpay_amount + Expense.card_amount
            ).label("t"),
        )
        .where(Expense.budget_id == budget.id)
        .group_by(Expense.category)
        .order_by(func.sum(
            Expense.cash_amount + Expense.gpay_amount + Expense.card_amount
        ).desc())
        .limit(1)
    ).first()

    days_tracked = (last_day - first_day).days + 1 if first_day and last_day else 0
    avg = float(spent) / days_tracked if days_tracked else 0.0

    return Summary(
        budget_id=budget.id,
        budget_name=budget.name,
        currency=budget.currency,
        total_budget=money(total_budget),
        total_spent=money(spent),
        remaining=money(remaining),
        percent_used=round(percent, 1),
        by_method=MethodBreakdown(
            cash=money(cash), gpay=money(gpay), card=money(card)
        ),
        owed_to_her=money(owed_to_her),
        she_owes=money(she_owes),
        recovered=money(recovered),
        remaining_if_everyone_pays=money(remaining + owed_to_her - she_owes),
        expense_count=int(count or 0),
        days_tracked=days_tracked,
        avg_per_day=round(avg, 2),
        biggest_expense=money(biggest),
        top_category=top_row[0] if top_row else None,
        status=status,
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
        total_amount=money(b.total_amount),
        currency=b.currency,
        created_at=b.created_at,
    )


@app.put("/api/budget", response_model=Summary)
def set_budget(payload: BudgetIn, db: DB, user: CurrentUser) -> Summary:
    b = active_budget(db, user)
    b.name = payload.name.strip() or "My Budget"
    b.total_amount = dec(payload.total_amount)
    b.currency = payload.currency.strip().upper()[:8] or "INR"
    db.commit()
    db.refresh(b)
    return build_summary(db, b)


@app.post("/api/budget/reset", response_model=Summary)
def reset_budget(
    db: DB, user: CurrentUser, keep_budget: bool = Query(default=True)
) -> Summary:
    """Wipe expenses + splits. Optionally zero the pot too."""
    b = active_budget(db, user)
    db.query(Split).filter(Split.budget_id == b.id).delete(synchronize_session=False)
    db.query(Expense).filter(Expense.budget_id == b.id).delete(
        synchronize_session=False
    )
    if not keep_budget:
        b.total_amount = ZERO
    db.commit()
    db.refresh(b)
    return build_summary(db, b)


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

    cat_rows = db.execute(
        select(
            Expense.category,
            func.sum(
                Expense.cash_amount + Expense.gpay_amount + Expense.card_amount
            ).label("t"),
            func.count(Expense.id),
        )
        .where(Expense.budget_id == b.id)
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

    recent_rows = db.scalars(
        select(Expense)
        .where(Expense.budget_id == b.id)
        .order_by(Expense.spent_on.desc(), Expense.id.desc())
        .limit(6)
    ).all()

    return Dashboard(
        summary=summary,
        daily=daily,
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
