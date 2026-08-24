"""End-to-end API tests against a throwaway SQLite file.

Auth: the `client` fixture (tests/conftest.py) overrides `get_current_user` to
a fixed test user, so every request below is implicitly logged in — the login
flow itself is covered separately in test_auth.py.
"""


def set_budget(client, total=10_000):
    r = client.put(
        "/api/budget",
        json={"name": "Test pot", "total_amount": total, "currency": "INR"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_budget_starts_empty_and_can_be_set(client):
    r = client.get("/api/budget")
    assert r.status_code == 200
    assert r.json()["total_amount"] == 0

    summary = set_budget(client, 25_000)
    assert summary["total_budget"] == 25_000
    assert summary["remaining"] == 25_000
    assert summary["percent_used"] == 0


def test_expense_reduces_remaining_and_splits_by_method(client):
    set_budget(client, 10_000)

    r = client.post(
        "/api/expenses",
        json={
            "name": "Ramen night",
            "category": "food",
            "cash_amount": 300,
            "gpay_amount": 200,
            "card_amount": 0,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["total"] == 500
    assert sorted(body["methods"]) == ["cash", "gpay"]

    s = client.get("/api/summary").json()
    assert s["total_spent"] == 500
    assert s["remaining"] == 9_500
    assert s["by_method"] == {"cash": 300.0, "gpay": 200.0, "card": 0.0}
    assert s["percent_used"] == 5.0


def test_expense_with_no_amount_is_rejected(client):
    set_budget(client)
    r = client.post("/api/expenses", json={"name": "Free hug"})
    assert r.status_code == 422


def test_expense_requires_a_name(client):
    set_budget(client)
    r = client.post("/api/expenses", json={"name": "   ", "cash_amount": 10})
    assert r.status_code == 422


def test_overspending_flips_status_to_overboard(client):
    set_budget(client, 1_000)
    client.post("/api/expenses", json={"name": "Bag", "card_amount": 1_500})
    s = client.get("/api/summary").json()
    assert s["remaining"] == -500
    assert s["status"] == "overboard"
    assert s["percent_used"] == 150.0


def test_status_ladder(client):
    set_budget(client, 1_000)
    client.post("/api/expenses", json={"name": "a", "cash_amount": 400})
    assert client.get("/api/summary").json()["status"] == "comfy"
    client.post("/api/expenses", json={"name": "b", "cash_amount": 200})
    assert client.get("/api/summary").json()["status"] == "watchful"
    client.post("/api/expenses", json={"name": "c", "cash_amount": 300})
    assert client.get("/api/summary").json()["status"] == "tight"


def test_split_created_with_expense(client):
    set_budget(client, 5_000)
    r = client.post(
        "/api/expenses",
        json={
            "name": "Dinner for two",
            "gpay_amount": 1_200,
            "split_with": "Meera",
            "split_amount": 600,
        },
    )
    assert r.status_code == 201

    splits = client.get("/api/splits").json()
    assert len(splits) == 1
    assert splits[0]["person"] == "Meera"
    assert splits[0]["amount"] == 600
    assert splits[0]["expense_name"] == "Dinner for two"

    s = client.get("/api/summary").json()
    assert s["owed_to_her"] == 600
    # money is out of the pot until they pay her back
    assert s["remaining"] == 3_800
    assert s["remaining_if_everyone_pays"] == 4_400


def test_split_bigger_than_expense_is_rejected(client):
    set_budget(client, 5_000)
    r = client.post(
        "/api/expenses",
        json={"name": "Snack", "cash_amount": 100, "split_with": "Ana", "split_amount": 500},
    )
    assert r.status_code == 422


def test_settling_a_split_returns_the_money(client):
    set_budget(client, 5_000)
    client.post("/api/expenses", json={"name": "Cab", "gpay_amount": 800})
    split = client.post(
        "/api/splits",
        json={"person": "Riya", "amount": 400, "direction": "they_owe", "note": "half the cab"},
    ).json()

    before = client.get("/api/summary").json()
    assert before["remaining"] == 4_200
    assert before["owed_to_her"] == 400

    r = client.patch(f"/api/splits/{split['id']}", json={"is_settled": True})
    assert r.status_code == 200
    assert r.json()["is_settled"] is True
    assert r.json()["settled_at"] is not None

    after = client.get("/api/summary").json()
    assert after["owed_to_her"] == 0
    assert after["recovered"] == 400
    assert after["remaining"] == 4_600


def test_she_owes_direction(client):
    set_budget(client, 5_000)
    client.post(
        "/api/splits",
        json={"person": "Mom", "amount": 1_000, "direction": "she_owes"},
    )
    s = client.get("/api/summary").json()
    assert s["she_owes"] == 1_000
    assert s["owed_to_her"] == 0
    assert s["remaining"] == 5_000
    assert s["remaining_if_everyone_pays"] == 4_000


def test_expense_filters(client):
    set_budget(client)
    client.post("/api/expenses", json={"name": "Latte", "category": "coffee", "cash_amount": 250})
    client.post("/api/expenses", json={"name": "Dress", "category": "shopping", "card_amount": 2_000})

    assert len(client.get("/api/expenses").json()) == 2
    assert len(client.get("/api/expenses?method=card").json()) == 1
    assert len(client.get("/api/expenses?category=coffee").json()) == 1
    assert len(client.get("/api/expenses?q=lat").json()) == 1
    assert client.get("/api/expenses?q=nothing").json() == []


def test_update_and_delete_expense(client):
    set_budget(client)
    e = client.post("/api/expenses", json={"name": "Typo", "cash_amount": 100}).json()

    r = client.patch(f"/api/expenses/{e['id']}", json={"name": "Fixed", "cash_amount": 150})
    assert r.status_code == 200
    assert r.json()["name"] == "Fixed"
    assert r.json()["total"] == 150

    assert client.delete(f"/api/expenses/{e['id']}").status_code == 204
    assert client.get("/api/expenses").json() == []
    assert client.delete(f"/api/expenses/{e['id']}").status_code == 404


def test_deleting_expense_removes_its_split(client):
    set_budget(client)
    e = client.post(
        "/api/expenses",
        json={"name": "Pizza", "cash_amount": 600, "split_with": "Sam", "split_amount": 300},
    ).json()
    assert len(client.get("/api/splits").json()) == 1

    client.delete(f"/api/expenses/{e['id']}")
    assert client.get("/api/splits").json() == []


def test_dashboard_shape(client):
    set_budget(client, 8_000)
    client.post("/api/expenses", json={"name": "Books", "category": "fun", "card_amount": 700})

    d = client.get("/api/dashboard?days=7").json()
    assert len(d["daily"]) == 7
    assert d["daily"][-1]["total"] == 700  # today is the last bucket
    assert d["categories"][0]["category"] == "fun"
    assert d["categories"][0]["emoji"] == "🎀"
    assert d["summary"]["top_category"] == "fun"
    assert len(d["recent"]) == 1


def test_reset_clears_everything_but_keeps_budget(client):
    set_budget(client, 3_000)
    client.post(
        "/api/expenses",
        json={"name": "Stuff", "cash_amount": 500, "split_with": "Zo", "split_amount": 200},
    )
    r = client.post("/api/budget/reset?keep_budget=true")
    assert r.status_code == 200
    s = r.json()
    assert s["total_budget"] == 3_000
    assert s["total_spent"] == 0
    assert s["expense_count"] == 0
    assert client.get("/api/splits").json() == []


def test_vibe_check_falls_back_offline(client):
    set_budget(client, 1_000)
    client.post("/api/expenses", json={"name": "Splurge", "card_amount": 2_000})
    r = client.post("/api/vibe-check")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "offline"
    assert body["mood"] == "overboard"
    assert len(body["message"]) > 0


def test_split_people_rollup(client):
    set_budget(client, 5_000)
    client.post("/api/splits", json={"person": "Meera", "amount": 300, "direction": "they_owe"})
    client.post("/api/splits", json={"person": "Meera", "amount": 200, "direction": "they_owe"})
    client.post("/api/splits", json={"person": "Sam", "amount": 100, "direction": "she_owes"})

    people = client.get("/api/splits/people").json()
    by_name = {p["person"]: p for p in people}
    assert by_name["Meera"]["pending"] == 500
    assert by_name["Sam"]["pending"] == -100
