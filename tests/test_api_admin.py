"""API testing: admin endpoints and access control (API-ADM-xx)."""
from decimal import Decimal

import pytest

from helpers import balance, run, scalar

pytestmark = pytest.mark.api


def D(value):
    return Decimal(str(value))


ADMIN_GET_ROUTES = ["/api/admin/stats", "/api/admin/users", "/api/admin/accounts",
                    "/api/admin/transactions", "/api/admin/audit-log"]


@pytest.mark.parametrize("path", ADMIN_GET_ROUTES)
def test_API_ADM_01_admin_routes_reject_anonymous_requests(api, path):
    assert api.get(path).status_code == 401


@pytest.mark.parametrize("path", ADMIN_GET_ROUTES)
def test_API_ADM_02_admin_routes_reject_customers_with_403(api, alice, path):
    assert api.get(path, alice).status_code == 403


def test_API_ADM_03_customer_cannot_change_account_status(api, alice, db):
    r = api.patch("/api/admin/accounts/1/status", alice, {"status": "frozen"})
    assert r.status_code == 403
    assert scalar(db, "SELECT status FROM accounts WHERE account_id = 1") == "active"


def test_API_ADM_04_stats_match_the_database(api, admin):
    body = api.get("/api/admin/stats", admin).json()
    assert body["totalUsers"] == 3 and body["totalAccounts"] == 2 and body["totalTransactions"] == 0
    assert D(body["totalBalance"]) == 8000


def test_API_ADM_05_stats_update_after_activity(api, admin, alice):
    api.deposit(alice, 1, 500)
    body = api.get("/api/admin/stats", admin).json()
    assert body["totalTransactions"] == 1 and D(body["totalBalance"]) == 8500


def test_API_ADM_06_user_list_has_all_users_and_no_password_data(api, admin):
    r = api.get("/api/admin/users", admin)
    assert r.status_code == 200 and len(r.json()) == 3
    assert "password" not in r.text.lower() and "$2b$" not in r.text


def test_API_ADM_07_account_list_includes_owner_and_branch(api, admin):
    data = api.get("/api/admin/accounts", admin).json()
    assert len(data) == 2
    assert {"owner_name", "owner_email", "branch_name", "balance", "status"} <= set(data[0])


def test_API_ADM_08_transaction_list_is_newest_first_and_capped_at_200(api, admin, alice):
    for amount in (1, 2, 3):
        api.deposit(alice, 1, amount)
    data = api.get("/api/admin/transactions", admin).json()
    assert [D(t["amount"]) for t in data] == [3, 2, 1] and len(data) <= 200


def test_API_ADM_09_audit_log_records_balance_changes_with_owner(api, admin, alice):
    api.deposit(alice, 1, 100)
    log = api.get("/api/admin/audit-log", admin).json()
    assert len(log) == 1
    assert log[0]["owner_name"] == "Alice Johnson"
    assert D(log[0]["old_balance"]) == 5000 and D(log[0]["new_balance"]) == 5100


def test_API_ADM_10_freeze_blocks_the_customer_end_to_end(api, admin, alice, db):
    assert api.patch("/api/admin/accounts/1/status", admin, {"status": "frozen"}).status_code == 200
    assert api.deposit(alice, 1, 10).status_code == 400
    assert api.withdraw(alice, 1, 10).status_code == 400
    assert api.transfer(alice, 1, 2, 10).status_code == 400
    assert balance(db, 1) == 5000


def test_API_ADM_11_unfreeze_restores_normal_operation(api, admin, alice):
    api.patch("/api/admin/accounts/1/status", admin, {"status": "frozen"})
    assert api.patch("/api/admin/accounts/1/status", admin, {"status": "active"}).status_code == 200
    assert api.deposit(alice, 1, 10).status_code == 201


@pytest.mark.parametrize("status", ["open", "FROZEN", "", None, 1, ["active"], {"a": 1}])
def test_API_ADM_12_invalid_status_value_returns_400(api, admin, status):
    assert api.patch("/api/admin/accounts/1/status", admin, {"status": status}).status_code == 400


def test_API_ADM_13_status_update_with_empty_body_returns_400(api, admin):
    assert api.patch("/api/admin/accounts/1/status", admin, {}).status_code == 400


def test_API_ADM_14_status_update_for_unknown_account_returns_404(api, admin):
    assert api.patch("/api/admin/accounts/99999/status", admin, {"status": "frozen"}).status_code == 404


@pytest.mark.parametrize("bad_id", ["abc", "0", "-1", "1.5", "99999999999"])
def test_API_ADM_15_status_update_with_invalid_id_returns_400(api, admin, bad_id):
    assert api.patch(f"/api/admin/accounts/{bad_id}/status", admin, {"status": "frozen"}).status_code == 400


def test_API_ADM_16_account_with_money_cannot_be_closed(api, admin, db):
    r = api.patch("/api/admin/accounts/1/status", admin, {"status": "closed"})
    assert r.status_code == 400
    assert scalar(db, "SELECT status FROM accounts WHERE account_id = 1") == "active"


def test_API_ADM_17_empty_account_can_be_closed(api, admin, db):
    run(db, "UPDATE accounts SET balance = 0 WHERE account_id = 1")
    assert api.patch("/api/admin/accounts/1/status", admin, {"status": "closed"}).status_code == 200
    assert scalar(db, "SELECT status FROM accounts WHERE account_id = 1") == "closed"


@pytest.mark.parametrize("new_status", ["active", "frozen"])
def test_API_ADM_18_closed_account_cannot_be_reopened(api, admin, db, new_status):
    run(db, "UPDATE accounts SET balance = 0, status = 'closed' WHERE account_id = 1")
    assert api.patch("/api/admin/accounts/1/status", admin, {"status": new_status}).status_code == 400
    assert scalar(db, "SELECT status FROM accounts WHERE account_id = 1") == "closed"


def test_API_ADM_19_demoted_admin_loses_access_immediately(api, admin, db):
    """verifyToken re-reads the role from the database, not from the token."""
    assert api.get("/api/admin/stats", admin).status_code == 200
    run(db, "UPDATE users SET role = 'customer' WHERE user_id = 3")
    assert api.get("/api/admin/stats", admin).status_code == 403


def test_API_ADM_20_promoted_customer_gains_access_immediately(api, alice, db):
    assert api.get("/api/admin/stats", alice).status_code == 403
    run(db, "UPDATE users SET role = 'admin' WHERE user_id = 1")
    assert api.get("/api/admin/stats", alice).status_code == 200


def test_API_ADM_21_a_customer_cannot_become_admin_through_any_api_call(api, alice, db):
    api.put("/api/auth/me", alice, {"name": "Alice", "role": "admin"})
    api.post("/api/accounts", alice, {"branch_id": 1, "account_type": "savings", "role": "admin"})
    assert scalar(db, "SELECT role FROM users WHERE user_id = 1") == "customer"
    assert api.get("/api/admin/stats", alice).status_code == 403
