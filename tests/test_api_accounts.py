"""API testing: accounts, statements and branches (API-ACC-xx)."""
from decimal import Decimal

import pytest

from helpers import one, scalar

pytestmark = pytest.mark.api


def D(value):
    return Decimal(str(value))


def test_API_ACC_01_list_returns_only_my_accounts_with_branch_details(api, alice):
    r = api.get("/api/accounts", alice)
    assert r.status_code == 200
    data = r.json()
    assert [a["account_id"] for a in data] == [1]
    assert data[0]["branch_name"] == "Main Street Branch" and data[0]["ifsc_code"] == "BANK0001234"
    assert D(data[0]["balance"]) == 5000


def test_API_ACC_02_another_user_sees_only_their_own_accounts(api, bob):
    assert [a["account_id"] for a in api.get("/api/accounts", bob).json()] == [2]


def test_API_ACC_03_list_requires_login(api):
    assert api.get("/api/accounts").status_code == 401


def test_API_ACC_04_get_own_account_by_id(api, alice):
    r = api.get("/api/accounts/1", alice)
    assert r.status_code == 200 and r.json()["account_id"] == 1 and D(r.json()["balance"]) == 5000


def test_API_ACC_05_cannot_read_someone_elses_account(api, alice):
    assert api.get("/api/accounts/2", alice).status_code == 404


def test_API_ACC_06_nonexistent_account_returns_404(api, alice):
    assert api.get("/api/accounts/99999", alice).status_code == 404


@pytest.mark.parametrize("bad_id", ["abc", "0", "-1", "1.5", "1%20OR%201=1", "99999999999"])
def test_API_ACC_07_invalid_account_id_returns_400(api, alice, bad_id):
    assert api.get(f"/api/accounts/{bad_id}", alice).status_code == 400


def test_API_ACC_08_create_savings_account(api, alice, db):
    r = api.post("/api/accounts", alice, {"branch_id": 2, "account_type": "savings"})
    assert r.status_code == 201
    row = one(db, "SELECT user_id, branch_id, account_type, balance, status FROM accounts WHERE account_id = %s",
              (r.json()["account_id"],))
    assert row["user_id"] == 1 and row["branch_id"] == 2 and row["account_type"] == "savings"
    assert row["balance"] == 0 and row["status"] == "active"


def test_API_ACC_09_create_current_account(api, alice):
    assert api.post("/api/accounts", alice, {"branch_id": 1, "account_type": "current"}).status_code == 201


def test_API_ACC_10_new_account_appears_in_my_list(api, alice):
    new_id = api.post("/api/accounts", alice, {"branch_id": 3, "account_type": "savings"}).json()["account_id"]
    assert new_id in [a["account_id"] for a in api.get("/api/accounts", alice).json()]


@pytest.mark.parametrize("body", [{}, {"branch_id": 1}, {"account_type": "savings"}])
def test_API_ACC_11_missing_fields_return_400(api, alice, body):
    assert api.post("/api/accounts", alice, body).status_code == 400


@pytest.mark.parametrize("account_type", ["checking", "SAVINGS", "", 5, None])
def test_API_ACC_12_invalid_account_type_returns_400(api, alice, account_type):
    assert api.post("/api/accounts", alice, {"branch_id": 1, "account_type": account_type}).status_code == 400


def test_API_ACC_13_nonexistent_branch_returns_404(api, alice):
    assert api.post("/api/accounts", alice, {"branch_id": 999, "account_type": "savings"}).status_code == 404


@pytest.mark.parametrize("branch_id", ["abc", -1, 1.5, {"a": 1}, [1]])
def test_API_ACC_14_invalid_branch_id_returns_400(api, alice, branch_id):
    assert api.post("/api/accounts", alice, {"branch_id": branch_id, "account_type": "savings"}).status_code == 400


def test_API_ACC_15_create_requires_login(api):
    assert api.post("/api/accounts", None, {"branch_id": 1, "account_type": "savings"}).status_code == 401


def test_API_ACC_16_cannot_open_an_account_in_someone_elses_name(api, alice, db):
    r = api.post("/api/accounts", alice, {"branch_id": 1, "account_type": "savings", "user_id": 2})
    assert scalar(db, "SELECT user_id FROM accounts WHERE account_id = %s", (r.json()["account_id"],)) == 1


def test_API_ACC_17_new_account_cannot_be_created_with_a_starting_balance(api, alice, db):
    r = api.post("/api/accounts", alice, {"branch_id": 1, "account_type": "savings", "balance": 1000000})
    assert scalar(db, "SELECT balance FROM accounts WHERE account_id = %s", (r.json()["account_id"],)) == 0


# --------------------------------------------------------------- statements
def test_API_ACC_18_statement_totals_match_activity(api, alice):
    api.deposit(alice, 1, 100)
    api.withdraw(alice, 1, 30.25)
    r = api.get("/api/accounts/1/statement", alice)
    body = r.json()
    assert r.status_code == 200
    assert D(body["current_balance"]) == D("5069.75")
    assert body["summary"] == {"total_credits": "100.00", "total_debits": "30.25", "transaction_count": 2}
    assert {t["direction"] for t in body["transactions"]} == {"credit", "debit"}


def test_API_ACC_19_statement_of_unused_account_is_empty(api, alice):
    body = api.get("/api/accounts/1/statement", alice).json()
    assert body["summary"] == {"total_credits": "0.00", "total_debits": "0.00", "transaction_count": 0}
    assert body["transactions"] == []


def test_API_ACC_20_statement_shows_transfer_as_debit_and_credit(api, alice, bob):
    api.transfer(alice, 1, 2, 250)
    a = api.get("/api/accounts/1/statement", alice).json()["transactions"][0]
    b = api.get("/api/accounts/2/statement", bob).json()["transactions"][0]
    assert a["direction"] == "debit" and b["direction"] == "credit" and D(a["amount"]) == 250


def test_API_ACC_21_cannot_read_someone_elses_statement(api, alice):
    assert api.get("/api/accounts/2/statement", alice).status_code == 404


@pytest.mark.parametrize("bad_id", ["abc", "0", "-5"])
def test_API_ACC_22_statement_with_invalid_id_returns_400(api, alice, bad_id):
    assert api.get(f"/api/accounts/{bad_id}/statement", alice).status_code == 400


def test_API_ACC_23_statement_requires_login(api):
    assert api.get("/api/accounts/1/statement").status_code == 401


def test_API_ACC_24_statement_lists_newest_first(api, alice):
    for amount in (10, 20, 30):
        api.deposit(alice, 1, amount)
    amounts = [D(t["amount"]) for t in api.get("/api/accounts/1/statement", alice).json()["transactions"]]
    assert amounts == [30, 20, 10]


# ------------------------------------------------------------------ branches
def test_API_ACC_25_branches_are_listed_for_logged_in_users(api, alice):
    r = api.get("/api/branches", alice)
    assert r.status_code == 200 and len(r.json()) == 3
    assert {"branch_id", "branch_name", "ifsc_code", "address"} <= set(r.json()[0])


def test_API_ACC_26_branches_require_login(api):
    assert api.get("/api/branches").status_code == 401
