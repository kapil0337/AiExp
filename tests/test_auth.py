"""Covers the real login flow: Google verification is monkeypatched (never a
production backdoor route), everything downstream — allowlist check, cookie
issuance, per-user data isolation — runs for real.

`backend.main` imports `verify_google_id_token` by name, so the patch target
is `backend.main.verify_google_id_token`, not the definition in `backend.auth`.
"""

from fastapi.testclient import TestClient

import backend.main as main_module
from backend.main import app


def fake_claims(email: str, sub: str = "sub-1") -> dict:
    return {
        "sub": sub,
        "email": email,
        "email_verified": True,
        "name": "Some Person",
        "picture": "https://example.com/pic.jpg",
    }


def raw_client() -> TestClient:
    """A client with no auth override — exercises the real dependency."""
    return TestClient(app)


def test_me_when_logged_out():
    r = raw_client().get("/api/auth/me")
    assert r.status_code == 200
    assert r.json() == {"authenticated": False, "user": None}


def test_protected_route_requires_login():
    r = raw_client().get("/api/summary")
    assert r.status_code == 401


def test_login_rejects_email_not_on_allowlist(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "verify_google_id_token",
        lambda credential: fake_claims("nope@example.com"),
    )
    c = raw_client()
    r = c.post("/api/auth/google", json={"credential": "whatever"})
    assert r.status_code == 403
    assert c.get("/api/auth/me").json()["authenticated"] is False


def test_login_success_sets_cookie_and_persists(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "verify_google_id_token",
        lambda credential: fake_claims("test@example.com"),
    )
    c = raw_client()
    r = c.post("/api/auth/google", json={"credential": "whatever"})
    assert r.status_code == 200
    assert r.json()["email"] == "test@example.com"

    me = c.get("/api/auth/me")
    assert me.json()["authenticated"] is True
    assert me.json()["user"]["email"] == "test@example.com"

    assert c.get("/api/summary").status_code == 200


def test_remember_false_sets_a_browser_session_cookie(monkeypatch):
    """Unchecking "keep me signed in" should drop Max-Age so the cookie dies
    with the browser session instead of persisting for session_max_age_days."""
    monkeypatch.setattr(
        main_module,
        "verify_google_id_token",
        lambda credential: fake_claims("test@example.com"),
    )
    c = raw_client()
    r = c.post("/api/auth/google", json={"credential": "whatever", "remember": False})
    assert r.status_code == 200
    set_cookie = r.headers["set-cookie"]
    assert "max-age" not in set_cookie.lower()

    # remember=True (the default) does persist
    c2 = raw_client()
    r2 = c2.post("/api/auth/google", json={"credential": "whatever"})
    assert "max-age" in r2.headers["set-cookie"].lower()


def test_logout_clears_session(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "verify_google_id_token",
        lambda credential: fake_claims("test@example.com"),
    )
    c = raw_client()
    c.post("/api/auth/google", json={"credential": "whatever"})
    assert c.get("/api/auth/me").json()["authenticated"] is True

    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").json()["authenticated"] is False
    assert c.get("/api/summary").status_code == 401


def test_each_account_only_sees_its_own_data(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "verify_google_id_token",
        lambda credential: fake_claims("test@example.com", sub="sub-a"),
    )
    alice = raw_client()
    alice.post("/api/auth/google", json={"credential": "a"})
    alice_expense = alice.post(
        "/api/expenses", json={"name": "Alice's coffee", "cash_amount": 100}
    ).json()

    monkeypatch.setattr(
        main_module,
        "verify_google_id_token",
        lambda credential: fake_claims("test2@example.com", sub="sub-b"),
    )
    bob = raw_client()
    bob.post("/api/auth/google", json={"credential": "b"})
    bob.post("/api/expenses", json={"name": "Bob's lunch", "cash_amount": 200})

    alice_list = alice.get("/api/expenses").json()
    bob_list = bob.get("/api/expenses").json()
    assert [e["name"] for e in alice_list] == ["Alice's coffee"]
    assert [e["name"] for e in bob_list] == ["Bob's lunch"]

    assert bob.delete(f"/api/expenses/{alice_expense['id']}").status_code == 404
