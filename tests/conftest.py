"""Shared fixtures: a throwaway SQLite DB and a logged-in test client.

Auth env vars must be set *before* backend.config's cached Settings is built
(same reason DATABASE_URL/NVIDIA_API_KEY are set at import time below).
"""

import os
import tempfile
from pathlib import Path

import pytest

TMP_DB = Path(tempfile.gettempdir()) / "bloom_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TMP_DB.as_posix()}"
os.environ["NVIDIA_API_KEY"] = ""
os.environ["SESSION_SECRET"] = "test-secret-not-for-prod"
os.environ["SESSION_COOKIE_SECURE"] = "false"
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
os.environ["ALLOWED_EMAILS"] = "test@example.com,test2@example.com"

from fastapi.testclient import TestClient  # noqa: E402

from backend.auth import get_current_user  # noqa: E402
from backend.database import Base, SessionLocal, engine  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import User  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def test_user():
    db = SessionLocal()
    user = User(google_sub="test-sub-1", email="test@example.com", name="Test User")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user


@pytest.fixture
def client(test_user):
    app.dependency_overrides[get_current_user] = lambda: test_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_current_user, None)
