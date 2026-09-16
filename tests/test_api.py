"""End-to-end API tests against a throwaway SQLite file.

Auth: the `client` fixture (tests/conftest.py) overrides `get_current_user` to
a fixed test user, so every request below is implicitly logged in — the login
flow itself is covered separately in test_auth.py.
"""


def set_balance(client, balance=10_000):
    r = client.put("/api/account-balance", json={"balance": balance})
    assert r.status_code == 200, r.text
    return r.json()


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_balance_starts_zero_and_can_be_set(client):
    r = client.get("/api/budget")
    assert r.status_code == 200
    assert r.json()["account_balance"] == 0

    summary = set_balance(client, 25_000)
    assert summary["account_balance"] == 25_000


def test_expense_reduces_nothing_but_shows_in_spend(client):
    set_balance(client, 10_000)

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
    assert s["spent_this_month"] == 500
    assert s["account_balance"] == 10_000  # expenses don't touch the balance
    assert s["by_method"] == {"cash": 300.0, "gpay": 200.0, "card": 0.0}


def test_expense_with_no_amount_is_rejected(client):
    r = client.post("/api/expenses", json={"name": "Free hug"})
    assert r.status_code == 422


def test_expense_requires_a_name(client):
    r = client.post("/api/expenses", json={"name": "   ", "cash_amount": 10})
    assert r.status_code == 422


def test_split_created_with_expense(client):
    set_balance(client, 5_000)
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
    assert s["remaining_if_everyone_pays"] == 5_600


def test_split_bigger_than_expense_is_rejected(client):
    r = client.post(
        "/api/expenses",
        json={"name": "Snack", "cash_amount": 100, "split_with": "Ana", "split_amount": 500},
    )
    assert r.status_code == 422


def test_settling_a_split_updates_recovered_not_balance(client):
    set_balance(client, 5_000)
    client.post("/api/expenses", json={"name": "Cab", "gpay_amount": 800})
    split = client.post(
        "/api/splits",
        json={"person": "Riya", "amount": 400, "direction": "they_owe", "note": "half the cab"},
    ).json()

    before = client.get("/api/summary").json()
    assert before["owed_to_her"] == 400
    assert before["account_balance"] == 5_000

    r = client.patch(f"/api/splits/{split['id']}", json={"is_settled": True})
    assert r.status_code == 200
    assert r.json()["is_settled"] is True
    assert r.json()["settled_at"] is not None

    after = client.get("/api/summary").json()
    assert after["owed_to_her"] == 0
    assert after["recovered"] == 400
    # settling an IOU is bookkeeping only — the balance is edited by hand
    assert after["account_balance"] == 5_000


def test_she_owes_direction(client):
    set_balance(client, 5_000)
    client.post(
        "/api/splits",
        json={"person": "Mom", "amount": 1_000, "direction": "she_owes"},
    )
    s = client.get("/api/summary").json()
    assert s["she_owes"] == 1_000
    assert s["owed_to_her"] == 0
    assert s["remaining_if_everyone_pays"] == 4_000


def test_expense_filters(client):
    client.post("/api/expenses", json={"name": "Latte", "category": "coffee", "cash_amount": 250})
    client.post("/api/expenses", json={"name": "Dress", "category": "shopping", "card_amount": 2_000})

    assert len(client.get("/api/expenses").json()) == 2
    assert len(client.get("/api/expenses?method=card").json()) == 1
    assert len(client.get("/api/expenses?category=coffee").json()) == 1
    assert len(client.get("/api/expenses?q=lat").json()) == 1
    assert client.get("/api/expenses?q=nothing").json() == []


def test_expense_month_filter(client):
    client.post(
        "/api/expenses",
        json={"name": "New Year brunch", "cash_amount": 500, "spent_on": "2026-01-15"},
    )
    client.post(
        "/api/expenses",
        json={"name": "Valentine dinner", "cash_amount": 1_000, "spent_on": "2026-02-14"},
    )
    client.post(
        "/api/expenses",
        json={"name": "Month-end snack", "cash_amount": 100, "spent_on": "2026-02-28"},
    )

    jan = client.get("/api/expenses?month=2026-01").json()
    assert [e["name"] for e in jan] == ["New Year brunch"]

    feb = client.get("/api/expenses?month=2026-02").json()
    assert {e["name"] for e in feb} == {"Valentine dinner", "Month-end snack"}

    assert client.get("/api/expenses?month=2026-03").json() == []
    assert client.get("/api/expenses?month=bogus").status_code == 422


def test_update_and_delete_expense(client):
    e = client.post("/api/expenses", json={"name": "Typo", "cash_amount": 100}).json()

    r = client.patch(f"/api/expenses/{e['id']}", json={"name": "Fixed", "cash_amount": 150})
    assert r.status_code == 200
    assert r.json()["name"] == "Fixed"
    assert r.json()["total"] == 150

    assert client.delete(f"/api/expenses/{e['id']}").status_code == 204
    assert client.get("/api/expenses").json() == []
    assert client.delete(f"/api/expenses/{e['id']}").status_code == 404


def test_deleting_expense_removes_its_split(client):
    e = client.post(
        "/api/expenses",
        json={"name": "Pizza", "cash_amount": 600, "split_with": "Sam", "split_amount": 300},
    ).json()
    assert len(client.get("/api/splits").json()) == 1

    client.delete(f"/api/expenses/{e['id']}")
    assert client.get("/api/splits").json() == []


def test_dashboard_shape(client):
    client.post("/api/expenses", json={"name": "Books", "category": "fun", "card_amount": 700})

    d = client.get("/api/dashboard?days=7").json()
    assert len(d["daily"]) == 7
    assert d["daily"][-1]["total"] == 700  # today is the last bucket
    assert len(d["monthly"]) == 12
    assert d["monthly"][-1]["total"] == 700  # current month is the last bucket
    assert d["categories"][0]["category"] == "fun"
    assert d["categories"][0]["emoji"] == "🎀"
    assert d["summary"]["top_category"] == "fun"
    assert len(d["recent"]) == 1


def test_reset_clears_expenses_but_keeps_balance(client):
    set_balance(client, 3_000)
    client.post(
        "/api/expenses",
        json={"name": "Stuff", "cash_amount": 500, "split_with": "Zo", "split_amount": 200},
    )
    r = client.post("/api/budget/reset")
    assert r.status_code == 200
    s = r.json()
    assert s["account_balance"] == 3_000
    assert s["spent_this_month"] == 0
    assert s["expense_count"] == 0
    assert client.get("/api/splits").json() == []


def test_vibe_check_falls_back_offline(client):
    client.post("/api/expenses", json={"name": "Splurge", "card_amount": 2_000})
    r = client.post("/api/vibe-check")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "offline"
    assert len(body["message"]) > 0


def test_split_people_rollup(client):
    client.post("/api/splits", json={"person": "Meera", "amount": 300, "direction": "they_owe"})
    client.post("/api/splits", json={"person": "Meera", "amount": 200, "direction": "they_owe"})
    client.post("/api/splits", json={"person": "Sam", "amount": 100, "direction": "she_owes"})

    people = client.get("/api/splits/people").json()
    by_name = {p["person"]: p for p in people}
    assert by_name["Meera"]["pending"] == 500
    assert by_name["Sam"]["pending"] == -100


def test_cash_holdings_default_and_set(client):
    r = client.get("/api/cash-holdings")
    assert r.status_code == 200
    assert r.json()["total"] == 0

    r = client.put(
        "/api/cash-holdings",
        json={"note_500": 2, "note_200": 1, "note_100": 3, "note_50": 0, "note_20": 0, "note_10": 0},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1_500  # 2*500 + 1*200 + 3*100
    assert body["note_500"] == 2

    # persists across reads and is never folded into the account balance
    set_balance(client, 1_000)
    assert client.get("/api/cash-holdings").json()["total"] == 1_500
    assert client.get("/api/summary").json()["account_balance"] == 1_000


def test_card_cycle_appears_in_summary(client):
    s = client.get("/api/summary").json()
    cycle = s["card_cycle"]
    assert cycle["cycle_start"] < cycle["cycle_end"]
    assert cycle["settle_date"] >= cycle["cycle_end"]
    assert cycle["card_spent_so_far"] == 0

    client.post("/api/expenses", json={"name": "Groceries", "card_amount": 450})
    s2 = client.get("/api/summary").json()
    assert s2["card_cycle"]["card_spent_so_far"] == 450


def test_settle_now_noop_when_cycle_still_open(client):
    client.post("/api/expenses", json={"name": "Groceries", "card_amount": 450})
    r = client.post("/api/card-cycle/settle-now")
    assert r.status_code == 200
    assert r.json() == {"settled": False, "settlement": None}
    assert client.get("/api/card-cycle/history").json() == []
