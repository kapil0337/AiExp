"""Google Sign-In: token verification + the session cookie.

The session cookie holds nothing but a signed, timestamped user id — no server
side session table, no JWT (nothing else needs to read this token, so the
extra `alg` surface JWT brings isn't worth it). `itsdangerous` is the same
primitive Flask uses for its own session cookie.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import User

SESSION_COOKIE_NAME = "bloom_session"

settings = get_settings()

DB = Annotated[Session, Depends(get_db)]


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt="bloom-session")


def create_session_cookie(user_id: int) -> str:
    return _serializer().dumps({"user_id": user_id})


def read_session_user_id(cookie_value: str) -> int | None:
    try:
        data = _serializer().loads(
            cookie_value, max_age=settings.session_max_age_days * 86400
        )
    except (BadSignature, SignatureExpired):
        return None
    return data.get("user_id")


def require_auth_configured() -> None:
    if not settings.auth_configured:
        raise HTTPException(
            status_code=500,
            detail="Google Sign-In isn't configured on this server yet 🔧",
        )


def verify_google_id_token(credential: str) -> dict:
    try:
        claims = id_token.verify_oauth2_token(
            credential, GoogleAuthRequest(), audience=settings.google_client_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=401, detail="That Google sign-in didn't check out 🚫"
        ) from exc

    if not claims.get("email_verified"):
        raise HTTPException(
            status_code=401, detail="Your Google email isn't verified 🚫"
        )
    return claims


def _user_from_cookie(request: Request, db: Session) -> User | None:
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not cookie:
        return None
    user_id = read_session_user_id(cookie)
    if user_id is None:
        return None
    return db.scalar(select(User).where(User.id == user_id))


def get_current_user(request: Request, db: DB) -> User:
    user = _user_from_cookie(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in 🔐")
    return user


def get_current_user_optional(request: Request, db: DB) -> User | None:
    return _user_from_cookie(request, db)
