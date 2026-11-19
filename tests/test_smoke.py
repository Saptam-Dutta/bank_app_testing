"""Smoke testing: a fast "is the build alive and do the core flows work?" check (SMK-xx).

Run these first after every deploy or code change. If a smoke test fails there is no point
running the 500+ detailed tests. The whole file takes a few seconds:

    python -m pytest -m smoke
"""
import time

import pytest
from playwright.sync_api import expect

from helpers import balance, scalar

pytestmark = pytest.mark.smoke

TABLES = {"branches", "users", "accounts", "transactions", "loans", "audit_log"}


@pytest.mark.api
def test_SMK_01_server_is_up_and_health_endpoint_answers(api):
    r = api.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.database
def test_SMK_02_database_is_reachable_with_all_six_tables(db):
    with db.cursor() as cur:
        cur.execute("SHOW TABLES")
        names = {list(row.values())[0] for row in cur.fetchall()}
    assert TABLES <= names, f"Missing tables: {TABLES - names}"


@pytest.mark.database
def test_SMK_03_seed_data_is_loaded(db):
    assert scalar(db, "SELECT COUNT(*) FROM users") == 3
    assert scalar(db, "SELECT COUNT(*) FROM accounts") == 2
    assert scalar(db, "SELECT COUNT(*) FROM branches") == 3


@pytest.mark.api
def test_SMK_04_customer_can_log_in(api):
    r = api.post("/api/auth/login", json={"email": "alice@example.com", "password": "password123"})
    assert r.status_code == 200 and r.json()["token"]


@pytest.mark.api
def test_SMK_05_admin_can_log_in_and_reach_the_admin_area(api, admin):
    r = api.get("/api/admin/stats", admin)
    assert r.status_code == 200


@pytest.mark.api
def test_SMK_06_logged_in_user_can_read_profile_and_accounts(api, alice):
    assert api.get("/api/auth/me", alice).json()["email"] == "alice@example.com"
    accounts = api.get("/api/accounts", alice).json()
    assert len(accounts) == 1 and accounts[0]["account_id"] == 1


@pytest.mark.api
def test_SMK_07_deposit_works_and_changes_the_balance(api, alice, db):
    assert api.deposit(alice, 1, "100.00").status_code == 201
    assert balance(db, 1) == 5100


@pytest.mark.api
def test_SMK_08_withdrawal_works_and_changes_the_balance(api, alice, db):
    r = api.withdraw(alice, 1, "100.00")
    assert r.status_code == 201
    assert balance(db, 1) == 4900


@pytest.mark.api
def test_SMK_09_transfer_moves_money_and_total_stays_the_same(api, alice, db):
    r = api.transfer(alice, 1, 2, "250.00")
    assert r.status_code == 201
    assert (balance(db, 1), balance(db, 2)) == (4750, 3250)


@pytest.mark.api
def test_SMK_10_transaction_history_lists_the_new_transaction(api, alice):
    api.deposit(alice, 1, "10.00")
    history = api.get("/api/transactions", alice).json()
    assert len(history) == 1 and history[0]["type"] == "deposit"


@pytest.mark.api
def test_SMK_11_protected_endpoint_rejects_a_request_without_a_token(api):
    assert api.get("/api/accounts").status_code == 401


@pytest.mark.api
def test_SMK_12_unknown_route_gives_a_clean_json_404(api):
    r = api.get("/api/does-not-exist")
    assert r.status_code == 404 and r.json()["error"]


@pytest.mark.api
def test_SMK_13_smoke_path_responds_fast_enough_to_be_usable(api, alice):
    """Not a performance test: only catches a build that is hanging (each call < 2 s)."""
    for path in ("/api/health", "/api/accounts", "/api/transactions", "/api/branches"):
        started = time.perf_counter()
        assert api.get(path, alice).status_code == 200
        assert time.perf_counter() - started < 2.0, f"{path} took more than 2 seconds"


@pytest.mark.ui
def test_SMK_14_landing_page_loads_without_console_errors(ui):
    ui.goto("/index.html")
    expect(ui.page.locator("h1")).to_have_text("Banking, made simple.")
    assert ui.console_errors == []


@pytest.mark.ui
def test_SMK_15_user_can_log_in_through_the_browser_and_see_their_balance(ui):
    ui.login_via_form("alice@example.com", "password123")
    ui.page.wait_for_url("**/dashboard.html")
    expect(ui.page.locator("#accountsList")).to_contain_text("5000.00")
    assert ui.console_errors == []
